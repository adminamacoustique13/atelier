"""Les pannes d'agent : la tâche patiente, de plus en plus longtemps, puis repart seule.

Une panne (`Resultat.nature` « panne ») ou une connexion perdue (« connexion ») ne dit rien du
travail. Les doubles posent eux-mêmes cette nature : le moteur ne lit qu'elle, jamais le texte de
l'erreur. Aucune attente réelle : une fausse heure Unix que le test fait avancer, une veille
courte, et chaque test attend un état, jamais une durée.
"""

import json
import threading
import time
from collections import Counter, defaultdict
from pathlib import Path

import pytest

from atelier import agents as module_agents
from atelier import archives, serveur
from atelier import moteur as module
from atelier.agents import AgentSimule, Resultat
from atelier.consignes import dernier_json
from atelier.controles import ControlesSimules
from atelier.modele import Chantier
from atelier.moteur import (
    ATTENTE_PANNE,
    CONNEXION_PERDUE,
    MOTIF_ARRET,
    PAUSES_PANNE_S,
    PHASES,
    RELANCER_TEL,
    Moteur,
    cle_de_phase,
    pauses_du_profil,
)
from atelier.places import heure_dite
from tests.test_moteur import Horloge, chantier, tache, traces

T0 = 1_800_000_000.0  # une fausse heure Unix
QUART = 15 * 60  # la suspension d'un refus pour limite dont l'heure est inconnue
ERREURS = {"panne": "Coupure simulée du réseau.", "connexion": "Session simulée expirée."}


class Heure:
    """Une fausse heure Unix : elle n'avance que quand le test le dit, ou de `pas` par lecture."""

    def __init__(self, pas=0.0):
        self.t, self.pas = T0, pas
        self.verrou = threading.Lock()

    def __call__(self):
        with self.verrou:
            self.t += self.pas
            return self.t


class AgentEnPanne(AgentSimule):
    """L'agent simulé, dont les appels peuvent tomber en panne ou perdre la connexion.

    `natures` donne, par (tâche, rôle), ce que rendent ses appels successifs : « panne » ou
    « connexion » (un échec aussitôt, de cette nature, sans rien écrire), ou "" (le jeu prévu de
    l'agent simulé). Un appel de `retenus` qui joue son jeu prévu attend `liberation`. `liberer`
    est noté dans `liberes`.
    """

    def executer(self, consigne, modele, effort, dossier, lecture_seule=False, contexte=None,
                 copie_jetable=False, reprendre=None):  # fmt: skip
        contexte = contexte or {}
        cle = (contexte.get("tache"), contexte.get("role"))
        with self.verrou_pannes:
            rang = self.vus[cle]
            self.vus[cle] += 1
        suite = self.natures.get(cle, [])
        nature = suite[rang] if rang < len(suite) else ""
        self.debuts[cle].set()
        if nature:
            self.appels.append({**contexte, "modele": modele, "effort": effort, "nature": nature})
            return Resultat(ok=False, erreur=ERREURS[nature], tokens=100, nature=nature)
        if cle in self.retenus:
            assert self.liberation.wait(5)
        return super().executer(consigne, modele, effort, dossier, lecture_seule, contexte,
                                copie_jetable, reprendre)  # fmt: skip

    def liberer(self, tache_):
        self.liberes.append(tache_)


def agent_en_panne(c, natures=None, retenus=(), **reglages):
    agent = AgentEnPanne(perimetres={t.id: t.perimetre for t in c.taches}, **reglages)
    agent.natures, agent.retenus, agent.liberes = natures or {}, set(retenus), []
    agent.verrou_pannes, agent.vus = threading.Lock(), Counter()
    agent.debuts, agent.liberation = defaultdict(threading.Event), threading.Event()
    return agent


class SansLiberer:
    """Un agent qui n'a pas encore `liberer` (`leve=False`), ou dont `liberer` lève."""

    def __init__(self, agent, leve=False):
        self.executer, self.arreter = agent.executer, agent.arreter
        if leve:
            self.liberer = self._lever

    @staticmethod
    def _lever(tache_):
        raise RuntimeError("liberer en panne")


class ControlesNotes(ControlesSimules):
    """Les contrôles simulés, qui notent les copies jetées."""

    def __init__(self):
        self.annulees = []

    def annuler(self, tache_, dossier):
        self.annulees.append(tache_.id)


@pytest.fixture(autouse=True)
def veille_courte(monkeypatch):
    monkeypatch.setattr(module, "PAS_VEILLE_S", 0.01)


def en_fond(m):
    fil = threading.Thread(target=m.executer, daemon=True)
    fil.start()
    return fil


def attendre_que(condition, delai=5.0):
    limite = time.monotonic() + delai
    while time.monotonic() < limite:
        if condition():
            return True
        time.sleep(0.005)
    return condition()


def fil_de(m):
    with m.verrou:
        return [e["texte"] for e in m.chantier.evenements]


def compte(agent, tache_, role):
    return sum(1 for a in list(agent.appels) if a.get("tache") == tache_ and a["role"] == role)


def ouvriers(agent, tache_):
    """Le niveau et le numéro de chaque ouvrier lancé pour la tâche."""
    return [(a["modele"], a["effort"], a["tentative"]) for a in list(agent.appels)
            if a.get("tache") == tache_ and a["role"] == "ouvrier"]  # fmt: skip


def phase_de(m, tache_):
    return (m.phase(tache_) or {}).get("texte")


def en_pause_jusqu_a(fin, maintenant=T0):
    return PHASES["panne"].format(heure_dite(fin, maintenant))


def finir(m, fil):
    fil.join(5)
    assert not fil.is_alive() and not m.en_route


# --- le contrat : les pauses, leur réglage, la phase -------------------------------------------


def test_les_pauses_par_defaut_vont_d_une_minute_a_une_heure():
    assert PAUSES_PANNE_S == (60, 300, 900, 1800, 3600)
    assert pauses_du_profil({}) == PAUSES_PANNE_S


@pytest.mark.parametrize(
    "reglage, attendu",
    [
        ([], ()),
        ([10, 20.5], (10, 20.5)),
        ((0, 30), (0, 30)),
        ("60", PAUSES_PANNE_S),
        (60, PAUSES_PANNE_S),
        (None, PAUSES_PANNE_S),
        ({"a": 60}, PAUSES_PANNE_S),
        ([60, "300"], PAUSES_PANNE_S),
        ([60, -1], PAUSES_PANNE_S),
        ([True], PAUSES_PANNE_S),
        ([float("inf")], PAUSES_PANNE_S),
        ([float("nan")], PAUSES_PANNE_S),
    ],
)
def test_pauses_panne_s_est_lu_sans_erreur(reglage, attendu):
    assert pauses_du_profil({"pauses_panne_s": reglage}) == attendu


def test_un_profil_mal_forme_garde_les_pauses_par_defaut():
    assert pauses_du_profil(None) == PAUSES_PANNE_S


def test_la_phase_de_pause_apres_une_panne_a_sa_propre_cle():
    phrase = en_pause_jusqu_a(T0 + 60)
    assert phrase.startswith("Patiente après une panne") and heure_dite(T0 + 60, T0) in phrase
    assert cle_de_phase(phrase) == "panne"


# --- critère 1 : une panne de l'ouvrier ----------------------------------------------------------


def test_une_panne_de_l_ouvrier_le_fait_patienter_puis_il_repart_sans_rien_compter():
    c = chantier([tache("A")])
    heure, horloge = Heure(), Horloge()
    agent = agent_en_panne(c, {("A", "ouvrier"): ["panne"]})
    m = Moteur(c, agent, ControlesSimules(), heure=heure, horloge=horloge)
    fil = en_fond(m)
    assert attendre_que(lambda: phase_de(m, "A") == en_pause_jusqu_a(T0 + 60))
    time.sleep(0.05)  # une vingtaine de réveils : rien ne doit repartir avant la fin de la pause
    with m.verrou:
        a = c.tache("A")
        assert compte(agent, "A", "ouvrier") == 1 and c.agents_lances == 0
        assert c.debit["pauses"] == {"A": T0 + 60}
        assert (c.debit["en_ecriture"], c.debit["agents_en_marche"]) == (0, 0)
        assert a.pannes == 1 and traces(a) == [(1, ATTENTE_PANNE, False)] and a.etat == "en_cours"
    horloge.t += 60
    heure.t = T0 + 60
    finir(m, fil)
    a = c.tache("A")
    assert a.etat == "verifie" and c.demandes == [] and c.montees == 0
    assert traces(a) == [(1, ATTENTE_PANNE, False), (1, "valide", False)]
    assert a.tentatives == 1 and c.agents_lances == 2 and a.pannes == 0
    premier, second = ouvriers(agent, "A")
    assert premier == second  # même niveau, même numéro de tentative
    assert a.historique[0]["origine"] == "" and "Coupure simulée" in a.historique[0]["detail"]
    assert a.historique[1]["durees"]["panne"] == 60  # la pause est dite et mesurée
    assert agent.liberes == ["A"]
    annonce = "C'est une panne, pas un refus du travail : nouvel essai "
    assert sum(annonce in t for t in fil_de(m)) == 1
    assert not any("Seconde chance" in t or "J'ai besoin de toi" in t for t in fil_de(m))


def test_cinq_pannes_de_suite_suivent_les_cinq_pauses_puis_la_tache_repart():
    c = chantier([tache("A")])
    heure = Heure()
    agent = agent_en_panne(c, {("A", "ouvrier"): ["panne"] * 5})
    m = Moteur(c, agent, ControlesSimules(), heure=heure)
    fil = en_fond(m)
    fin = T0
    for pause in PAUSES_PANNE_S:
        debut, fin = fin, fin + pause
        assert attendre_que(lambda f=fin: c.debit.get("pauses") == {"A": f})
        assert attendre_que(lambda d=debut, f=fin: phase_de(m, "A") == en_pause_jusqu_a(f, d))
        heure.t = fin
    finir(m, fil)
    a = c.tache("A")
    assert a.etat == "verifie" and c.demandes == []
    assert traces(a) == [(1, ATTENTE_PANNE, False)] * 5 + [(1, "valide", False)]
    assert a.tentatives == 1 and c.agents_lances == 2 and a.pannes == 0
    assert len(set(ouvriers(agent, "A"))) == 1 and agent.liberes == ["A"] * 5


def test_une_panne_de_plus_apres_la_derniere_pause_suit_la_regle_des_erreurs_d_agent():
    c = chantier([tache("A")])
    heure = Heure()
    agent = agent_en_panne(c, {("A", "ouvrier"): ["panne"] * 3})
    m = Moteur(c, agent, ControlesSimules(), {"pauses_panne_s": [60]}, heure=heure)
    fil = en_fond(m)
    assert attendre_que(lambda: c.debit.get("pauses") == {"A": T0 + 60})
    heure.t = T0 + 60
    finir(m, fil)
    a = c.tache("A")
    # La règle d'aujourd'hui : seconde chance au même niveau, puis deux erreurs identiques.
    assert a.etat == "revenu" and a.tentatives == 2 and a.pannes == 3 and c.montees == 0
    assert traces(a) == [(1, ATTENTE_PANNE, False), (1, "ne_sait_pas", False),
                         (2, "ne_sait_pas", False)]  # fmt: skip
    assert [e["origine"] for e in a.historique] == ["", "agent", "agent"]
    assert any("Seconde chance au même niveau" in t for t in fil_de(m))
    (demande,) = [d for d in c.demandes if d.get("nature") == "blocage"]
    assert "les agents se sont arrêtés deux fois de suite sur la même erreur" in demande["question"]
    assert c.agents_lances == 2 and agent.liberes == ["A"]
    assert not any(ATTENTE_PANNE in p for p in demande["preuves"])  # une pause n'est pas un refus


def test_une_panne_entre_deux_erreurs_d_agent_ne_les_separe_pas():
    c = chantier([tache("A")])
    heure = Heure()
    natures = {("A", "ouvrier"): ["", "panne"]}
    agent = agent_en_panne(c, natures, scenario={"A": ["erreur", "erreur", "ok"]})
    m = Moteur(c, agent, ControlesSimules(), heure=heure)
    fil = en_fond(m)
    assert attendre_que(lambda: c.debit.get("pauses") == {"A": T0 + 60})
    heure.t = T0 + 60
    finir(m, fil)
    a = c.tache("A")
    assert a.etat == "revenu" and a.tentatives == 2
    assert [e["issue"] for e in a.historique] == ["ne_sait_pas", ATTENTE_PANNE, "ne_sait_pas"]
    # Comme sans panne (`test_deux_erreurs_d_agent_identiques_bloquent_sans_monter`) : bloquée.
    (demande,) = [d for d in c.demandes if d.get("nature") == "blocage"]
    assert "les agents se sont arrêtés deux fois de suite sur la même erreur" in demande["question"]


# --- critère 2 : le compte des pannes repart ----------------------------------------------------


def test_une_reussite_de_l_agent_remet_le_compte_des_pannes_a_zero():
    c = chantier([tache("A")])
    heure = Heure()
    natures = {("A", "ouvrier"): ["panne"], ("A", "verificateur"): ["panne"]}
    agent = agent_en_panne(c, natures)
    m = Moteur(c, agent, ControlesSimules(), heure=heure)
    fil = en_fond(m)
    assert attendre_que(lambda: c.debit.get("pauses") == {"A": T0 + 60})
    heure.t = T0 + 60  # l'ouvrier repart et va au bout ; son vérificateur tombe en panne
    assert attendre_que(lambda: c.debit.get("pauses") == {"A": T0 + 120})  # une minute, pas cinq
    with m.verrou:
        assert c.tache("A").pannes == 1
    heure.t = T0 + 120
    finir(m, fil)
    a = c.tache("A")
    assert a.etat == "verifie" and a.pannes == 0
    assert traces(a) == [(1, ATTENTE_PANNE, False)] * 2 + [(1, "valide", False)]


def test_un_echec_d_une_autre_nature_remet_le_compte_des_pannes_a_zero():
    c = chantier([tache("A")])
    heure = Heure()
    natures = {("A", "ouvrier"): ["panne", "", "panne"]}
    agent = agent_en_panne(c, natures, scenario={"A": ["erreur", "ok"]})
    m = Moteur(c, agent, ControlesSimules(), heure=heure)
    fil = en_fond(m)
    assert attendre_que(lambda: c.debit.get("pauses") == {"A": T0 + 60})
    heure.t = T0 + 60  # l'ouvrier repart et s'arrête sur une erreur sans nature ; puis une panne
    assert attendre_que(lambda: c.debit.get("pauses") == {"A": T0 + 120})
    heure.t = T0 + 120
    finir(m, fil)
    a = c.tache("A")
    assert a.etat == "verifie" and a.pannes == 0 and a.tentatives == 2
    assert [e["issue"] for e in a.historique] == [ATTENTE_PANNE, "ne_sait_pas", ATTENTE_PANNE,
                                                  "valide"]  # fmt: skip


# --- critère 5 : le vérificateur en panne -------------------------------------------------------


def test_un_verificateur_en_panne_repart_seul_et_le_travail_de_l_ouvrier_reste():
    c = chantier([tache("A")])
    heure, controles = Heure(), ControlesNotes()
    agent = agent_en_panne(c, {("A", "verificateur"): ["panne"]})
    m = Moteur(c, agent, controles, heure=heure)
    fil = en_fond(m)
    assert attendre_que(lambda: phase_de(m, "A") == en_pause_jusqu_a(T0 + 60))
    with m.verrou:
        assert c.tache("A").etat == "en_verification" and c.agents_lances == 1
        assert (c.debit["agents_en_marche"], c.debit["verificateurs_en_attente"]) == (0, 0)
    heure.t = T0 + 60
    finir(m, fil)
    a = c.tache("A")
    assert a.etat == "verifie" and a.tentatives == 1 and c.demandes == []
    assert (compte(agent, "A", "ouvrier"), compte(agent, "A", "verificateur")) == (1, 2)
    assert traces(a) == [(1, ATTENTE_PANNE, False), (1, "valide", False)]
    assert controles.annulees == [] and c.agents_lances == 2 and agent.liberes == ["A"]
    assert any("seul le vérificateur repart" in t for t in fil_de(m))
    assert not any("j'en relance un, une seule fois" in t for t in fil_de(m))


# --- critère 7 : arrêt et limite pendant la pause, état sauvé ----------------------------------


@pytest.mark.parametrize("role", ["ouvrier", "verificateur"])
def test_un_arret_pendant_la_pause_rend_la_main_tout_de_suite(monkeypatch, role):
    monkeypatch.setattr(module, "PAS_VEILLE_S", 30.0)  # seul le signal de l'arrêt peut réveiller
    c = chantier([tache("A")])
    agent = agent_en_panne(c, {("A", role): ["panne"]})
    m = Moteur(c, agent, ControlesSimules(), heure=Heure())
    fil = en_fond(m)
    assert attendre_que(lambda: phase_de(m, "A") == en_pause_jusqu_a(T0 + 60))
    assert m.arreter("A")
    finir(m, fil)  # l'heure n'a pas bougé : la pause n'est pas finie
    a = c.tache("A")
    assert a.etat == "revenu" and c.demandes[-1]["question"].endswith(MOTIF_ARRET)
    assert traces(a) == [(1, ATTENTE_PANNE, False), (1, "arretee", False)]
    assert compte(agent, "A", role) == 1  # aucun agent relancé
    assert m.places.en_pause("A", T0) is None


def test_une_limite_pendant_la_pause_s_y_ajoute_et_la_plus_tardive_l_emporte():
    c = chantier([tache("A"), tache("B")])
    heure = Heure()
    agent = agent_en_panne(c, {("A", "ouvrier"): ["panne"]}, retenus={("B", "ouvrier")},
                           limites={"B": ["refus"]}, delai_limite_s=None)  # fmt: skip
    m = Moteur(c, agent, ControlesSimules(), {"paralleles": 2}, heure=heure)
    fil = en_fond(m)
    assert attendre_que(lambda: phase_de(m, "A") == en_pause_jusqu_a(T0 + 60))
    agent.liberation.set()  # B est refusée pour limite pendant la pause de A
    assert attendre_que(lambda: c.debit.get("reprise") == T0 + QUART)
    heure.t = T0 + 60  # la pause est finie, pas la suspension
    suspendue = PHASES["pause"].format(heure_dite(T0 + QUART, T0 + 60))
    assert attendre_que(lambda: phase_de(m, "A") == suspendue)
    assert compte(agent, "A", "ouvrier") == 1
    heure.t = T0 + QUART
    finir(m, fil)
    a = c.tache("A")
    assert [t.etat for t in c.taches] == ["verifie"] * 2 and c.demandes == []
    assert traces(a) == [(1, ATTENTE_PANNE, False), (1, "valide", False)]
    assert a.tentatives == 1 and c.agents_lances == 4
    assert sorted(agent.liberes) == ["A", "B"]


def test_l_etat_sauve_pendant_une_pause_la_dit_et_se_relit(tmp_path):
    c = chantier([tache("A")])
    agent = agent_en_panne(c, {("A", "ouvrier"): ["panne"]})
    m = Moteur(c, agent, ControlesSimules(), heure=Heure())
    fil = en_fond(m)
    assert attendre_que(lambda: c.debit.get("pauses") == {"A": T0 + 60})
    with m.verrou:
        c.sauver(tmp_path / "etat.json")
    assert m.arreter("A")
    finir(m, fil)
    relu = Chantier.charger(tmp_path / "etat.json")
    assert relu.debit["pauses"] == {"A": T0 + 60}
    phrase = "Une tâche patiente après une panne de son agent : elle repart "
    assert f"{phrase}{heure_dite(T0 + 60, T0)}." in relu.debit["phrase"]
    a = relu.tache("A")
    assert a.pannes == 1 and a.etat == "en_cours" and traces(a) == [(1, ATTENTE_PANNE, False)]


# --- critère 4 : la connexion perdue ------------------------------------------------------------


def test_une_connexion_perdue_suspend_tout_et_le_fil_le_dit_une_seule_fois():
    c = chantier([tache("A"), tache("B"), tache("C", modele="opus", effort="medium")])
    heure = Heure()
    natures = {("A", "ouvrier"): ["connexion", "connexion"], ("B", "ouvrier"): ["connexion"]}
    agent = agent_en_panne(c, natures, retenus={("B", "ouvrier")})
    m = Moteur(c, agent, ControlesSimules(), {"paralleles": 2}, heure=heure)
    fil = en_fond(m)
    assert attendre_que(lambda: compte(agent, "A", "ouvrier") == compte(agent, "B", "ouvrier") == 1)
    assert attendre_que(lambda: c.debit.get("suspensions") == {"connexion": T0 + 300})
    suspendue = PHASES["pause"].format(heure_dite(T0 + 300, T0))
    assert attendre_que(lambda: phase_de(m, "A") == phase_de(m, "B") == suspendue)
    time.sleep(0.05)  # deux places libres, mais tous les modèles sont suspendus
    assert compte(agent, "C", "ouvrier") == 0
    heure.t = T0 + 300  # nouvel essai : A perd encore la connexion, B attend d'être libérée
    assert attendre_que(lambda: c.debit.get("suspensions") == {"connexion": T0 + 600})
    agent.liberation.set()
    heure.t = T0 + 600
    finir(m, fil)
    assert [t.etat for t in c.taches] == ["verifie"] * 3 and c.demandes == []
    assert all(traces(t) == [(1, "valide", False)] for t in c.taches)
    assert all(t.tentatives == 1 and t.pannes == 0 for t in c.taches)
    assert c.agents_lances == 6  # trois ouvriers et trois vérificateurs : rien d'autre ne compte
    assert sum(t == CONNEXION_PERDUE for t in fil_de(m)) == 1
    assert sum("connexion" in t.lower() for t in fil_de(m)) == 1
    assert "/login" in CONNEXION_PERDUE and sorted(agent.liberes) == ["A", "A", "B"]


def test_une_connexion_retrouvee_puis_perdue_est_dite_de_nouveau():
    c = chantier([tache("A")])
    natures = {("A", "ouvrier"): ["connexion"], ("A", "verificateur"): ["connexion"]}
    agent = agent_en_panne(c, natures)
    Moteur(c, agent, ControlesSimules(), heure=Heure(pas=60.0)).executer()
    assert c.tache("A").etat == "verifie"  # l'ouvrier a travaillé entre les deux pertes
    assert sum(e["texte"] == CONNEXION_PERDUE for e in c.evenements) == 2


# --- les places rendues pendant la pause --------------------------------------------------------


def test_deux_taches_en_panne_rendent_leur_place_a_une_troisieme_qui_travaille():
    c = chantier([tache("A"), tache("B"), tache("C")])
    heure = Heure()
    natures = {("A", "ouvrier"): ["panne"], ("B", "ouvrier"): ["panne"]}
    agent = agent_en_panne(c, natures, retenus={("C", "ouvrier")})
    m = Moteur(c, agent, ControlesSimules(), {"paralleles": 2}, heure=heure)
    fil = en_fond(m)
    assert agent.debuts[("C", "ouvrier")].wait(5)
    assert attendre_que(lambda: c.debit.get("pauses") == {"A": T0 + 60, "B": T0 + 60})
    pause = en_pause_jusqu_a(T0 + 60)
    assert attendre_que(lambda: phase_de(m, "A") == phase_de(m, "B") == pause)
    with m.verrou:
        assert c.debit["en_ecriture"] == 1 and c.debit["agents_en_marche"] == 1
    agent.liberation.set()
    assert attendre_que(lambda: c.tache("C").etat == "verifie")  # pendant la pause de A et B
    assert (compte(agent, "A", "ouvrier"), compte(agent, "B", "ouvrier")) == (1, 1)
    heure.t = T0 + 60
    finir(m, fil)
    assert [t.etat for t in c.taches] == ["verifie"] * 3 and c.demandes == []
    assert all(t.tentatives == 1 and t.pannes == 0 for t in c.taches)


# --- le réglage pauses_panne_s dans le moteur ---------------------------------------------------


def test_une_liste_de_pauses_vide_coupe_la_patience():
    c = chantier([tache("A")])
    agent = agent_en_panne(c, {("A", "ouvrier"): ["panne", "panne"]})
    Moteur(c, agent, ControlesSimules(), {"pauses_panne_s": []}, heure=Heure()).executer()
    a = c.tache("A")
    assert a.etat == "revenu" and a.tentatives == 2 and a.pannes == 2
    assert traces(a) == [(1, "ne_sait_pas", False), (2, "ne_sait_pas", False)]
    assert agent.liberes == [] and not any("C'est une panne" in e["texte"] for e in c.evenements)


def test_une_liste_de_pauses_mal_formee_vaut_les_pauses_par_defaut():
    c = chantier([tache("A")])
    heure = Heure()
    agent = agent_en_panne(c, {("A", "ouvrier"): ["panne"]})
    m = Moteur(c, agent, ControlesSimules(), {"pauses_panne_s": [60, "beaucoup"]}, heure=heure)
    fil = en_fond(m)
    assert attendre_que(lambda: phase_de(m, "A") == en_pause_jusqu_a(T0 + 60))
    heure.t = T0 + 60
    finir(m, fil)
    assert c.tache("A").etat == "verifie" and c.tache("A").tentatives == 1


# --- critère 8 : l'ouvrier resté ouvert est fermé à chaque suspension --------------------------


@pytest.mark.parametrize(
    "reglages",
    [
        {"natures": {("A", "ouvrier"): ["panne"]}},
        {"natures": {("A", "ouvrier"): ["connexion"]}},
        {"limites": {"A": ["refus"]}, "delai_limite_s": None},
        {"limites": {"A": ["surcharge"]}},
    ],
    ids=["panne", "connexion", "limite", "surcharge"],
)
def test_chaque_suspension_ferme_l_ouvrier_reste_ouvert(reglages):
    c = chantier([tache("A")])
    agent = agent_en_panne(c, **reglages)
    Moteur(c, agent, ControlesSimules(), heure=Heure(pas=60.0)).executer()
    a = c.tache("A")
    assert a.etat == "verifie" and a.tentatives == 1 and c.agents_lances == 2
    assert agent.liberes == ["A"]


@pytest.mark.parametrize("leve", [False, True], ids=["sans_liberer", "liberer_qui_leve"])
def test_un_agent_sans_liberer_ou_qui_leve_ne_casse_rien(leve):
    c = chantier([tache("A")])
    double = agent_en_panne(c, {("A", "ouvrier"): ["panne"], ("A", "verificateur"): ["connexion"]})
    agent = SansLiberer(double, leve)
    assert hasattr(agent, "liberer") is leve
    Moteur(c, agent, ControlesSimules(), heure=Heure(pas=60.0)).executer()
    a = c.tache("A")
    assert a.etat == "verifie" and a.tentatives == 1 and c.agents_lances == 2
    assert traces(a) == [(1, ATTENTE_PANNE, False), (1, "valide", False)]
    assert double.liberes == []


# --- reprise de M6 : une panne est neutre pour tout ce qui décide de la suite -------------------
# Essais du vérificateur de M6, fondus ici avec leurs doubles. L'heure simulée avance à chaque
# lecture : aucune attente réelle.

TEXTES = {
    "panne": "Coupure simulée du réseau.",
    "connexion": "Session simulée expirée.",
    "delai": "Délai simulé dépassé.",
    "budget": "Budget simulé dépassé.",
    "": "Arrêt simulé de l'agent.",
}
SUJETS = [
    "La fonction ne gère pas la liste vide.",
    "Le test ajouté compare la sortie à elle-même.",
    "Le fichier de configuration n'est pas relu au démarrage.",
    "La documentation contredit le comportement mesuré.",
    "Les messages d'erreur restent en anglais.",
    "Une division par zéro survient sur un tableau sans ligne.",
    "Le cache garde une valeur périmée après une modification.",
    "Les arrondis diffèrent du calcul de référence.",
]
JOURNAL = "DECISIONS.md"
PARTAGE = {"fichiers_partages": [{"motif": JOURNAL}]}


class AgentScript(AgentSimule):
    """`script[(tache, role)]` : ce que rendent les appels successifs, role parmi « ouvrier »,
    « reprise », « verificateur ». "" : le jeu prévu ; « panne », « connexion », « delai »,
    « budget », « erreur » (échec sans nature) : un échec de cette nature ; « limite »,
    « surcharge » : le refus correspondant. `verdicts[tache]` : les verdicts successifs des
    vrais vérificateurs (« ok » au-delà) ; `varie` : chaque refus a un résumé différent. Un
    appel de `retenus` attend `liberation` avant de rendre quoi que ce soit."""

    def executer(self, consigne, modele, effort, dossier, lecture_seule=False, contexte=None,
                 copie_jetable=False, reprendre=None):  # fmt: skip
        contexte = contexte or {}
        role = contexte.get("role")
        if role == "ouvrier" and reprendre is not None:
            role = "reprise"
        cle = (contexte.get("tache"), role)
        with self.verrou_script:
            rang = self.vus[cle]
            self.vus[cle] += 1
        suite = self.script.get(cle, [])
        jeu = suite[rang] if rang < len(suite) else ""
        self.debuts[cle].set()
        self.journal.append((contexte.get("tache"), role, jeu, modele, effort,
                             contexte.get("tentative")))  # fmt: skip
        if cle in self.retenus:
            assert self.liberation.wait(10)
        if jeu == "limite":
            return Resultat(ok=False, erreur=module_agents.LIMITE_ATTEINTE, type_limite="five_hour",
                            fin_limite=None, nature="limite", tokens=10)  # fmt: skip
        if jeu == "surcharge":
            return Resultat(ok=False, erreur=module_agents.SURCHARGE, nature="surcharge", tokens=10)
        if jeu:
            nature = "" if jeu == "erreur" else jeu
            return Resultat(ok=False, erreur=TEXTES[nature], tokens=100, cout_usd=0.01,
                            nature=nature)  # fmt: skip
        resultat = super().executer(consigne, modele, effort, dossier, lecture_seule, contexte,
                                    copie_jetable, reprendre)  # fmt: skip
        verdict = dernier_json(resultat.texte) if contexte.get("role") == "verificateur" else None
        if self.varie and verdict and verdict.get("valide") is False:
            with self.verrou_script:
                self.refus_rendus += 1
                rang = self.refus_rendus
            resultat.texte = json.dumps({**verdict, "resume": SUJETS[rang % len(SUJETS)]})
        return resultat

    def _issue(self, contexte):
        tache_ = contexte.get("tache", "")
        if contexte.get("role") == "verificateur":
            with self.verrou_script:
                suite = self.verdicts.get(tache_, [])
                return suite.pop(0) if suite else "ok"
        return "ok"

    def liberer(self, tache_):
        self.liberes.append(tache_)


def agent_script(c, script=None, verdicts=None, retenus=(), varie=False, **reglages):
    agent = AgentScript(perimetres={t.id: t.perimetre for t in c.taches}, **reglages)
    agent.script = {k: list(v) for k, v in (script or {}).items()}
    agent.verdicts = {k: list(v) for k, v in (verdicts or {}).items()}
    agent.retenus, agent.liberes, agent.varie = set(retenus), [], varie
    agent.verrou_script, agent.vus, agent.refus_rendus = threading.Lock(), Counter(), 0
    agent.debuts, agent.liberation = defaultdict(threading.Event), threading.Event()
    agent.journal = []
    return agent


def places_vides(m):
    """Vrai si plus rien n'est tenu ni retenu dans les places."""
    with m.verrou:
        p = m.places
        return (not p._taches and not p._attente and not p._pauses
                and p.en_ecriture() == 0 and p.agents_en_marche() == 0
                and not m._en_vol and not m._veulent_ecrire and not m._arretees)  # fmt: skip


class ControlesScript(ControlesSimules):
    """Enregistrement en conflit `conflits` fois, contrôles rouges `rouges` fois."""

    def __init__(self, conflits=0, rouges=0):
        self.conflits, self.rouges = conflits, rouges

    def enregistrer(self, tache_, dossier):
        if self.conflits:
            self.conflits -= 1
            return "Conflit avec la branche principale."
        return ""

    def poser_conflits(self, tache_, dossier):
        return {JOURNAL: "<<<<<<<"}

    def mecaniques(self, tache_, dossier):
        if self.rouges:
            self.rouges -= 1
            return False, "FAILED tests/test_a.py::test_un - assert 1 == 2"
        return True, ""


SCENARIOS = {
    "bacle_identique": dict(verdicts=["bacle"] * 4),
    "bacle_varie": dict(verdicts=["bacle"] * 4, varie=True),
    "conflit_x2": dict(conflits=2, profil=PARTAGE),
    "conflit_x3": dict(conflits=3, profil=PARTAGE),
    "controles_rouges_x3": dict(rouges=3),
    "erreur_ouvrier_x2": dict(script={("A", "ouvrier"): ["erreur", "erreur"]}),
    "erreur_verificateur_x4": dict(script={("A", "verificateur"): ["erreur"] * 4}),
}


def jouer(nom, insertion=None):
    """Joue le scénario, avec une panne glissée avant l'appel `insertion` = (rôle, rang) ; rend ce
    qui ne doit pas dépendre de la panne."""
    r = SCENARIOS[nom]
    t = tache("A", perimetre=[JOURNAL, "a.py"]) if "conflit" in nom else tache("A")
    c = chantier([t])
    script = {k: list(v) for k, v in r.get("script", {}).items()}
    if insertion is not None:
        role, rang = insertion
        suite = script.setdefault(("A", role), [])
        suite.extend([""] * (rang - len(suite)))
        suite.insert(rang, "panne")
    agent = agent_script(c, script, {"A": r.get("verdicts", [])}, varie=r.get("varie", False))
    controles = ControlesScript(r.get("conflits", 0), r.get("rouges", 0))
    m = Moteur(c, agent, controles, r.get("profil", {}), heure=Heure(pas=61.0))
    m.executer()
    a = c.tache("A")
    assert places_vides(m)
    return {
        "etat": a.etat,
        "tentatives": a.tentatives,
        "montees": c.montees,
        "niveau": (a.modele, a.effort),
        "agents_lances": c.agents_lances,
        "vrais_agents": [j[1:] for j in agent.journal if j[2] != "panne"],
        "historique": [(e["tentative"], e["issue"], e["origine"], e["reprise"])
                       for e in a.historique if e["issue"] != ATTENTE_PANNE],  # fmt: skip
        "blocages": [d.get("nature", "") for d in c.demandes],
    }


def insertions():
    for nom in SCENARIOS:
        compte = {}
        for role, *_ in jouer(nom)["vrais_agents"]:
            compte[role] = compte.get(role, 0) + 1
        for role, nombre in compte.items():
            for rang in range(nombre):
                yield nom, role, rang


def test_une_panne_pendant_la_reprise_d_un_conflit_ne_fait_pas_monter_d_un_cran():
    """B1 : `_repris_hors_fusion` lisait l'entrée `attente_panne` glissée entre le refus
    d'enregistrement et sa reprise comme un refus hors fusion, et le départ suivant montait."""
    sans = jouer("conflit_x2")
    assert (sans["etat"], sans["montees"], sans["niveau"]) == ("verifie", 0, ("sonnet", "low"))
    for insertion in (("reprise", 0), ("verificateur", 1)):
        avec = jouer("conflit_x2", insertion)
        assert (avec["montees"], avec["niveau"]) == (0, ("sonnet", "low")), insertion
        assert avec == sans, insertion


def test_une_panne_ne_retarde_pas_le_blocage_d_une_tache_refusee_pour_la_meme_raison():
    """B2 : l'entrée `attente_panne` coupait la suite de refus identiques dans `_fenetre`."""
    sans = jouer("bacle_identique")
    assert (sans["etat"], sans["blocages"], sans["agents_lances"]) == ("revenu", ["blocage"], 6)
    avec = jouer("bacle_identique", ("ouvrier", 1))
    assert avec["agents_lances"] == sans["agents_lances"]
    assert avec == sans


@pytest.mark.parametrize("nom, role, rang", list(insertions()))
def test_une_panne_glissee_n_importe_ou_ne_change_que_l_entree_attente_panne(nom, role, rang):
    """Même issue, mêmes tentatives, mêmes montées, mêmes vrais agents (rôle, modèle, effort,
    numéro), même demande, avec ou sans la panne."""
    assert jouer(nom, (role, rang)) == jouer(nom)


# --- reprise de M6 : la patience reste bornée -----------------------------------------------------


@pytest.mark.parametrize("autre", ["surcharge", "limite", "connexion"])
def test_une_alternance_panne_et_autre_suspension_finit_par_rendre_la_tache(autre):
    """B3 : une suspension ne remet plus `Tache.pannes` à zéro ; les pauses s'allongent et
    s'épuisent, puis la règle des erreurs d'agent rend la tâche."""
    c = chantier([tache("A")])
    agent = agent_script(c, {("A", "ouvrier"): ["panne", autre] * 40})
    m = Moteur(c, agent, ControlesSimules(), heure=Heure(pas=400.0))
    fil = en_fond(m)
    fil.join(30)
    assert not fil.is_alive()
    a = c.tache("A")
    pannes = sum(e["issue"] == ATTENTE_PANNE for e in a.historique)
    assert pannes <= len(module.PAUSES_PANNE_S) + 2 and a.etat == "revenu", (pannes, a.etat)


def test_une_alternance_sans_fin_de_pannes_et_de_surcharges_borne_les_agents_lances():
    c = chantier([tache("A")])
    agent = agent_script(c, {("A", "ouvrier"): ["panne", "surcharge"] * 500})
    m = Moteur(c, agent, ControlesSimules(), heure=Heure(pas=4000.0))
    m.executer()
    a = c.tache("A")
    assert a.etat == "revenu" and places_vides(m)
    # Cinq pauses, puis deux erreurs d'agent : sept pannes, et une surcharge entre deux pannes.
    pannes = sum(1 for j in agent.journal if j[2] == "panne")
    assert pannes == len(PAUSES_PANNE_S) + 2 and len(agent.journal) == 2 * pannes - 1
    assert c.agents_lances == 2 and a.tentatives == 2
    assert [e["issue"] for e in a.historique].count(ATTENTE_PANNE) == len(PAUSES_PANNE_S)


# « budget » n'y est plus : un ouvrier coupé par son plafond rend la tâche pour budget, sans
# rien compter contre elle (tests/test_moteur_budget.py).
@pytest.mark.parametrize("nature", ["delai", "erreur"])
def test_une_nature_qui_n_est_pas_une_panne_suit_la_regle_d_avant_sans_pause(nature):
    c = chantier([tache("A")])
    agent = agent_script(c, {("A", "ouvrier"): [nature, nature]})
    m = Moteur(c, agent, ControlesSimules(), heure=Heure())
    fil = en_fond(m)  # l'heure n'avance pas : une pause prise à tort ne finirait jamais
    fil.join(5)
    assert not fil.is_alive(), c.debit.get("pauses")
    a = c.tache("A")
    assert (a.etat, a.tentatives, a.pannes, c.agents_lances) == ("revenu", 2, 0, 2)
    assert [e["issue"] for e in a.historique] == ["ne_sait_pas"] * 2
    assert agent.liberes == [] and "pauses" not in c.debit and places_vides(m)


def test_une_panne_pure_est_bornee_cinq_pauses_puis_deux_erreurs_d_agent():
    c = chantier([tache("A")])
    agent = agent_script(c, {("A", "ouvrier"): ["panne"] * 100})
    m = Moteur(c, agent, ControlesSimules(), heure=Heure(pas=4000.0))
    m.executer()
    a = c.tache("A")
    assert (a.etat, a.tentatives, agent.vus[("A", "ouvrier")], c.agents_lances) == (
        "revenu", 2, 7, 2)  # fmt: skip
    assert places_vides(m)


def test_six_taches_toutes_en_panne_sur_une_seule_place_finissent_toutes():
    c = chantier([tache(x) for x in "ABCDEF"])
    script = {(x, "ouvrier"): ["panne", "panne"] for x in "ABCDEF"}
    script |= {(x, "verificateur"): ["panne"] for x in "ABCDEF"}
    agent = agent_script(c, script)
    m = Moteur(c, agent, ControlesSimules(), {"paralleles": 1}, heure=Heure(pas=7.0))
    fil = en_fond(m)
    fil.join(20)
    assert not fil.is_alive() and [t.etat for t in c.taches] == ["verifie"] * 6
    assert [t.tentatives for t in c.taches] == [1] * 6 and c.agents_lances == 12
    assert places_vides(m)


def test_la_derniere_tache_en_pause_se_reveille_seule_sans_signal(monkeypatch):
    """Heure réelle, veille de 30 s, pause de 0,3 s : seule `prochaine_echeance` la réveille."""
    monkeypatch.setattr(module, "PAS_VEILLE_S", 30.0)
    c = chantier([tache("A"), tache("B")])
    agent = agent_script(c, {("B", "ouvrier"): ["panne"], ("B", "verificateur"): ["panne"]})
    m = Moteur(c, agent, ControlesSimules(), {"pauses_panne_s": [0.3]})
    fil = en_fond(m)
    fil.join(10)
    assert not fil.is_alive() and [t.etat for t in c.taches] == ["verifie"] * 2
    assert places_vides(m)


def test_un_arret_deja_demande_quand_la_panne_arrive_n_ecrit_aucune_pause():
    c = chantier([tache("A")])
    agent = agent_script(c, {("A", "ouvrier"): ["panne"]}, retenus={("A", "ouvrier")})
    m = Moteur(c, agent, ControlesSimules(), heure=Heure())
    fil = en_fond(m)
    assert agent.debuts[("A", "ouvrier")].wait(5)
    assert m.arreter("A")  # l'ouvrier tourne encore : sa panne arrivera après l'arrêt
    agent.liberation.set()
    finir(m, fil)
    a = c.tache("A")
    assert a.etat == "revenu" and traces(a) == [(1, "arretee", False)] and a.pannes == 0
    assert agent.liberes == [] and not any("C'est une panne" in t for t in fil_de(m))
    assert places_vides(m)


# --- reprise de M6 : le compte des pannes ne survit ni à une relance ni à un redémarrage ---------


def test_apres_un_arret_et_une_relance_la_premiere_pause_repart_d_une_minute():
    c = chantier([tache("A")])
    heure = Heure()
    agent = agent_script(c, {("A", "ouvrier"): ["panne"] * 4})
    m = Moteur(c, agent, ControlesSimules(), heure=heure)
    fil = en_fond(m)
    fin = T0
    for pause in (60, 300):
        fin += pause
        assert attendre_que(lambda f=fin: c.debit.get("pauses") == {"A": f})
        heure.t = fin
    assert attendre_que(lambda: c.debit.get("pauses") == {"A": fin + 900})
    assert m.arreter("A")
    fil.join(5)
    assert c.tache("A").etat == "revenu" and places_vides(m)
    m.repondre(c.demandes[-1]["id"], RELANCER_TEL)
    assert c.tache("A").pannes == 0
    fil = en_fond(m)
    assert attendre_que(lambda: bool(c.debit.get("pauses")))
    try:
        assert c.debit["pauses"]["A"] - heure.t == 60
    finally:
        heure.t += 4000
        fil.join(5)


def test_au_chargement_le_compte_des_pannes_repart_de_zero(tmp_path):
    c = chantier([tache("A")])
    c.tache("A").pannes = 3
    c.sauver(tmp_path / "etat.json")
    relu = Chantier.charger(tmp_path / "etat.json")
    assert relu.tache("A").pannes == 3  # l'état garde le compte, pour l'affichage
    Moteur(relu, AgentSimule(), ControlesSimules())
    assert relu.tache("A").pannes == 0


def test_un_echec_d_une_autre_tache_ne_fait_pas_redire_la_connexion_perdue():
    c = chantier([tache("A"), tache("B")])
    script = {("A", "ouvrier"): ["connexion"] * 6, ("B", "ouvrier"): ["delai", "delai"]}
    agent = agent_script(c, script)
    m = Moteur(c, agent, ControlesSimules(), {"paralleles": 2}, heure=Heure(pas=100.0))
    fil = en_fond(m)
    fil.join(10)
    assert not fil.is_alive()
    assert sum(e["texte"] == CONNEXION_PERDUE for e in c.evenements) == 1


# --- reprise de M6 : les raccords hors du moteur ------------------------------------------------


def test_les_statistiques_ne_comptent_pas_une_pause_comme_un_refus():
    c = chantier([tache("A")])
    agent = agent_script(c, {("A", "ouvrier"): ["panne"]})
    Moteur(c, agent, ControlesSimules(), heure=Heure(pas=61.0)).executer()
    assert c.tache("A").etat == "verifie"
    assert [ligne["refus"] for ligne in serveur.statistiques(c)] == [0]


def test_le_temps_des_pauses_apres_panne_est_range_avec_l_attente():
    t = tache("A")
    t.historique = [{"tentative": 1, "issue": "valide", "durees": {"panne": 60.0, "ouvrier": 5}}]
    temps = archives.temps_par_groupe(t)
    assert (temps["attendre"], temps["autre"], temps["ecrire"]) == (60.0, 0.0, 5.0)


def test_le_tableau_ne_montre_pas_une_pause_apres_panne_d_une_croix():
    page = (Path(serveur.__file__).parent / "tableau" / "index.html").read_text("utf-8")
    ligne = next(x for x in page.splitlines() if "const ok = h.issue ===" in x)
    assert 'neutre = stoppee || h.issue === "attente_panne"' in ligne
    suite = page[page.index(ligne):][:400]
    assert '${ok ? "ok" : neutre ? "neutre" : "non"}' in suite
    assert '${ok ? "✓" : neutre ? "–" : "✕"}' in suite
