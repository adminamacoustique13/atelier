"""Le débit du moteur : places d'écriture, vérificateur hors place, réveil, limites.

Les places viennent de `atelier/places.py`, déjà testé seul ; ici, le moteur qui s'en sert, avec
l'agent simulé, une fausse heure Unix que le test fait avancer, et une veille courte : aucun test
n'attend vraiment une limite de l'abonnement.
"""

import threading
import time
from collections import defaultdict

import pytest

from atelier import moteur as module
from atelier import places as module_places
from atelier.agents import AgentSimule
from atelier.controles import ControlesSimules
from atelier.modele import Chantier
from atelier.moteur import MOTIF_ARRET, PHASES, RELANCER_TEL, Moteur
from atelier.places import PAUSE_SURCHARGE_S, heure_dite
from tests.test_moteur import Horloge, chantier, tache, traces
from tests.test_serveur import atelier_simule

T0 = 1_800_000_000.0  # une fausse heure Unix
QUART = 15 * 60  # la suspension d'un refus pour limite dont l'heure est inconnue


class Heure:
    """Une fausse heure Unix : elle n'avance que quand le test le dit, ou de `pas` par lecture."""

    def __init__(self, pas=0.0):
        self.t, self.pas = T0, pas

    def __call__(self):
        self.t += self.pas
        return self.t


class AgentGuette(AgentSimule):
    """L'agent simulé, qui signale le début de chaque appel (tâche, rôle), retient ceux de
    `retenus` jusqu'à `liberation`, et note le plus grand nombre d'agents en marche, et
    d'ouvriers en marche."""

    def executer(self, consigne, modele, effort, dossier, lecture_seule=False, contexte=None,
                 copie_jetable=False, reprendre=None):  # fmt: skip
        cle, ouvrier = (contexte.get("tache"), contexte["role"]), contexte["role"] == "ouvrier"
        with self.verrou_guette:
            self.en_marche += 1
            self.ouvriers += ouvrier
            self.pic = max(self.pic, self.en_marche)
            self.pic_ouvriers = max(self.pic_ouvriers, self.ouvriers)
        self.debuts[cle].set()
        try:
            if cle in self.retenus:
                assert self.liberation.wait(5)
            return super().executer(consigne, modele, effort, dossier, lecture_seule, contexte,
                                    copie_jetable, reprendre)  # fmt: skip
        finally:
            with self.verrou_guette:
                self.en_marche -= 1
                self.ouvriers -= ouvrier

    def compte(self, tache_, role):
        return sum(1 for a in list(self.appels) if a.get("tache") == tache_ and a["role"] == role)


def guette(c, retenus=(), **reglages):
    agent = AgentGuette(perimetres={t.id: t.perimetre for t in c.taches}, **reglages)
    agent.verrou_guette, agent.liberation = threading.Lock(), threading.Event()
    agent.debuts, agent.retenus = defaultdict(threading.Event), set(retenus)
    agent.en_marche = agent.pic = agent.ouvriers = agent.pic_ouvriers = 0
    return agent


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


def etats(atelier):
    with atelier.moteur.verrou:
        return [t.etat for t in atelier.moteur.chantier.taches]


def finir(m, agent, fil):
    agent.liberation.set()
    fil.join(5)
    assert not fil.is_alive() and not m.en_route


@pytest.fixture(autouse=True)
def veille_courte(monkeypatch):
    monkeypatch.setattr(module, "PAS_VEILLE_S", 0.01)


# --- les places : le vérificateur n'en tient pas ----------------------------------------------


def test_un_verificateur_ne_retient_pas_de_place_et_une_troisieme_tache_part():
    c = chantier([tache("A"), tache("B"), tache("C")])
    agent = guette(c, retenus={("A", "verificateur"), ("B", "ouvrier"), ("C", "ouvrier")})
    m = Moteur(c, agent, ControlesSimules(), {"paralleles": 2})
    fil = en_fond(m)
    assert agent.debuts[("A", "verificateur")].wait(5) and agent.debuts[("B", "ouvrier")].wait(5)
    assert agent.debuts[("C", "ouvrier")].wait(5)  # A vérifiée, B et C écrivent : deux places
    with m.verrou:
        assert c.tache("A").etat == "en_verification"
        assert (c.debit["en_ecriture"], c.debit["agents_en_marche"]) == (2, 3)
    finir(m, agent, fil)
    assert [t.etat for t in c.taches] == ["verifie"] * 3 and agent.pic == 3


def test_avec_une_seule_place_l_ouvrier_de_b_part_pendant_que_a_est_verifiee():
    c = chantier([tache("A"), tache("B")])
    agent = guette(c, retenus={("A", "verificateur")})
    m = Moteur(c, agent, ControlesSimules(), {"paralleles": 1})
    fil = en_fond(m)
    assert agent.debuts[("B", "ouvrier")].wait(5)
    finir(m, agent, fil)
    assert [t.etat for t in c.taches] == ["verifie"] * 2


def test_sans_reglage_six_taches_partent_ensemble_et_pas_une_septieme():
    c = chantier([tache(x) for x in "ABCDEFG"])
    agent = guette(c, retenus={(x, "ouvrier") for x in "ABCDEFG"})
    m = Moteur(c, agent, ControlesSimules())
    fil = en_fond(m)
    assert attendre_que(lambda: sum(agent.debuts[(x, "ouvrier")].is_set() for x in "ABCDEFG") == 6)
    time.sleep(0.05)  # le temps qu'une septième parte, si elle le pouvait
    assert not agent.debuts[("G", "ouvrier")].is_set()
    finir(m, agent, fil)
    assert all(t.etat == "verifie" for t in c.taches)


def test_les_agents_en_marche_ne_depassent_jamais_agents_max():
    c = chantier([tache(x) for x in "ABCDEF"])
    agent = guette(c, delai_s=0.02)
    Moteur(c, agent, ControlesSimules(), {"agents_max": 2}).executer()
    assert all(t.etat == "verifie" for t in c.taches) and agent.pic <= 2
    assert c.agents_lances == 12


# --- les limites : rien n'est compté, la tâche repart seule -------------------------------------


def test_une_limite_suspend_les_departs_puis_la_tache_repart_seule_sans_tentative():
    c = chantier([tache("A"), tache("B")])
    heure = Heure()
    agent = guette(c, limites={"A": ["refus"]}, delai_limite_s=None)
    m = Moteur(c, agent, ControlesSimules(), {"paralleles": 1}, heure=heure)
    fil = en_fond(m)
    reprise = T0 + QUART
    phrase = f"plus aucun lancement, ils reprennent {heure_dite(reprise, T0)}."
    assert attendre_que(lambda: any(phrase in t for t in fil_de(m)))
    pause = PHASES["pause"].format(heure_dite(reprise, T0))
    assert attendre_que(lambda: (m.phase("A") or {}).get("texte") == pause)
    time.sleep(0.05)  # une vingtaine de réveils : rien ne doit partir
    with m.verrou:
        assert [(a["tache"], a["role"]) for a in agent.appels] == [("A", "ouvrier")]
        assert (c.tache("A").tentatives, c.agents_lances) == (0, 0)
        assert c.debit["reprise"] == reprise and c.tache("A").historique == []
    heure.t = reprise
    fil.join(5)
    assert not fil.is_alive()
    a = c.tache("A")
    assert [t.etat for t in c.taches] == ["verifie"] * 2 and c.demandes == []
    assert traces(a) == [(1, "valide", False)] and a.tentatives == 1 and c.montees == 0
    assert c.agents_lances == 4  # deux ouvriers et deux vérificateurs : le refusé ne compte pas
    assert a.historique[0]["durees"]["pause"] > 0  # l'attente est dite et mesurée
    assert sum(phrase in t for t in fil_de(m)) == 1


@pytest.mark.parametrize("limites", [["surcharge", "refus"], ["refus", "refus"]])
def test_une_limite_ou_une_surcharge_ne_comptent_ni_tentative_ni_montee_ni_blocage(limites):
    c = chantier([tache("A")])
    agent = AgentSimule(perimetres={"A": ["a.py"]}, limites={"A": limites}, delai_limite_s=None)
    m = Moteur(c, agent, ControlesSimules(), heure=Heure(pas=60.0))
    m.executer()
    a = c.tache("A")
    assert a.etat == "verifie" and traces(a) == [(1, "valide", False)]
    assert (a.tentatives, c.montees, c.agents_lances, c.demandes) == (1, 0, 2, [])
    assert [x["role"] for x in agent.appels] == ["ouvrier"] * 3 + ["verificateur"]
    surcharge = [t for t in fil_de(m) if t.startswith("Claude est surchargé")]
    assert len(surcharge) == limites.count("surcharge")


def test_l_echeance_reveille_les_departs_pendant_qu_aucun_agent_ne_finit():
    c = chantier([tache("A"), tache("C")])
    heure = Heure()
    agent = guette(c, retenus={("C", "ouvrier")}, limites={"A": ["refus"]}, delai_limite_s=None)
    m = Moteur(c, agent, ControlesSimules(), heure=heure)
    fil = en_fond(m)
    assert agent.debuts[("C", "ouvrier")].wait(5)
    assert attendre_que(lambda: c.debit.get("reprise") == T0 + QUART)
    heure.t += QUART  # personne ne finit : seule l'échéance peut relancer A
    assert attendre_que(lambda: agent.compte("A", "verificateur") == 1, delai=1.0)
    assert agent.compte("C", "verificateur") == 0  # C écrit encore
    finir(m, agent, fil)
    assert c.tache("A").tentatives == 1 and c.tache("C").etat == "verifie"


def test_le_reveil_suit_l_heure_de_remise_a_zero_sans_attendre_la_veille(monkeypatch):
    monkeypatch.setattr(module, "PAS_VEILLE_S", 30.0)
    monkeypatch.setattr(module_places, "MARGE_REPRISE_S", 0)
    c = chantier([tache("A")])
    agent = AgentSimule(perimetres={"A": ["a.py"]}, limites={"A": ["refus"]}, delai_limite_s=0.2)
    debut = time.monotonic()
    Moteur(c, agent, ControlesSimules()).executer()  # l'heure du mur, cette fois
    assert time.monotonic() - debut < 1.0
    assert c.tache("A").etat == "verifie" and c.tache("A").tentatives == 1


def test_une_limite_propre_a_opus_laisse_partir_une_tache_sonnet():
    c = chantier([tache("Z"), tache("X", modele="opus", effort="medium"), tache("Y")])
    heure = Heure()
    reglages = {"limites": {"Z": ["refus"]}, "type_limite": "seven_day_opus"}
    agent = guette(c, delai_limite_s=None, **reglages)
    m = Moteur(c, agent, ControlesSimules(), {"paralleles": 1}, heure=heure)
    fil = en_fond(m)
    assert agent.debuts[("Y", "ouvrier")].wait(5)  # Z refusée : X (Opus) attend, Y (Sonnet) part
    assert attendre_que(lambda: c.tache("Y").etat == "en_verification")
    time.sleep(0.05)
    with m.verrou:
        assert agent.compte("X", "ouvrier") == 0 and agent.compte("Y", "verificateur") == 0
        assert c.debit["suspensions"] == {"opus": T0 + QUART} and c.debit["reprise"] is None
    assert any(t.startswith("La limite propre à Opus est atteinte") for t in fil_de(m))
    heure.t += QUART
    finir(m, agent, fil)
    assert [t.etat for t in c.taches] == ["verifie"] * 3
    assert c.tache("Z").tentatives == 1 and c.agents_lances == 6


def test_un_verificateur_refuse_pour_limite_est_relance_sur_la_meme_copie_sans_compter():
    c = chantier([tache("A")])
    heure = Heure()
    agent = guette(c, limites={"A": ["", "refus"]}, delai_limite_s=None)
    m = Moteur(c, agent, ControlesSimules(), heure=heure)
    fil = en_fond(m)
    assert attendre_que(lambda: c.debit.get("reprise") == T0 + QUART)
    with m.verrou:
        assert c.tache("A").etat == "en_verification" and c.agents_lances == 1
    heure.t += QUART
    finir(m, agent, fil)
    a = c.tache("A")
    assert a.etat == "verifie" and traces(a) == [(1, "valide", False)]
    assert [x["role"] for x in agent.appels] == ["ouvrier", "verificateur", "verificateur"]
    assert c.agents_lances == 2


def test_un_arret_pendant_la_suspension_rend_la_tache_tout_de_suite(monkeypatch):
    monkeypatch.setattr(module, "PAS_VEILLE_S", 30.0)  # seul le signal de l'arrêt peut réveiller
    c = chantier([tache("A")])
    agent = AgentSimule(perimetres={"A": ["a.py"]}, limites={"A": ["refus"]}, delai_limite_s=None)
    m = Moteur(c, agent, ControlesSimules(), heure=Heure())
    fil = en_fond(m)
    assert attendre_que(lambda: c.debit.get("reprise") is not None)
    assert m.arreter("A")
    fil.join(1.0)
    assert not fil.is_alive()
    a = c.tache("A")
    assert a.etat == "revenu" and a.tentatives == 0 and traces(a) == [(1, "arretee", False)]
    assert c.demandes[-1]["question"].endswith(MOTIF_ARRET)


def test_un_arret_interrompt_le_verificateur_qui_attend_son_jeton(monkeypatch):
    monkeypatch.setattr(module, "PAS_VEILLE_S", 30.0)
    c = chantier([tache("A")])
    agent = AgentSimule(perimetres={"A": ["a.py"]}, limites={"A": ["", "refus"]})
    m = Moteur(c, agent, ControlesSimules(), heure=Heure())
    fil = en_fond(m)
    assert attendre_que(lambda: m.phase("A") and m.phase("A")["texte"].startswith("En pause"))
    assert c.tache("A").etat == "en_verification" and m.arreter("A")
    fil.join(1.0)
    assert not fil.is_alive()
    a = c.tache("A")
    assert a.etat == "revenu" and traces(a) == [(1, "arretee", False)]
    assert [x["role"] for x in agent.appels] == ["ouvrier", "verificateur"]


def test_l_etat_des_places_est_sauve_mais_la_suspension_n_est_pas_relue(tmp_path):
    c = chantier([tache("A")])
    agent = AgentSimule(perimetres={"A": ["a.py"]}, limites={"A": ["refus"]}, delai_limite_s=None)
    m = Moteur(c, agent, ControlesSimules(), heure=Heure())
    fil = en_fond(m)
    assert attendre_que(lambda: c.debit.get("reprise") is not None)
    with m.verrou:
        c.sauver(tmp_path / "etat.json")
    assert m.arreter("A")
    fil.join(5)
    relu = Chantier.charger(tmp_path / "etat.json")
    assert relu.debit["reprise"] == T0 + QUART and relu.debit["places"] == 6
    assert "Une limite de l'abonnement est atteinte" in relu.debit["phrase"]
    suivant = Moteur(relu, AgentSimule(), ControlesSimules(), heure=Heure())
    assert suivant.places.suspension("sonnet", T0) is None


# --- le réveil : une décision part aussitôt, et ne se perd pas ----------------------------------


def test_une_decision_fait_partir_la_tache_aussitot_pendant_qu_une_autre_travaille(monkeypatch):
    monkeypatch.setattr(module, "PAS_VEILLE_S", 30.0)  # seule la décision peut réveiller
    c = chantier([tache("A"), tache("C")])
    agent = guette(c, {("C", "ouvrier")}, scenario={"A": ["consigne", "ok"]})
    m = Moteur(c, agent, ControlesSimules())
    fil = en_fond(m)
    assert attendre_que(lambda: c.tache("A").etat == "revenu" and c.demandes)
    m.repondre(c.demandes[-1]["id"], RELANCER_TEL)
    assert attendre_que(lambda: agent.compte("A", "ouvrier") == 2, delai=1.0)
    assert agent.compte("C", "verificateur") == 0  # C écrit toujours
    finir(m, agent, fil)
    assert [t.etat for t in c.taches] == ["verifie"] * 2


def test_une_decision_arrivee_pendant_la_conclusion_n_est_pas_perdue():
    c = chantier([tache("A")])
    agent = AgentSimule(perimetres={"A": ["a.py"]}, scenario={"A": ["consigne", "ok"]})
    reponses = []

    def sur_changement():
        dernier = c.evenements[-1]["texte"]
        if dernier.startswith("Je m'arrête ici") and not reponses:
            reponses.append(dernier)
            m.repondre(c.demandes[-1]["id"], RELANCER_TEL)

    m = Moteur(c, agent, ControlesSimules(), sur_changement=sur_changement)
    m.executer()
    assert reponses and c.tache("A").etat == "verifie" and not m.en_route
    assert fil_de(m)[-1].startswith("Chantier terminé")


# --- la reprise à chaud attend sa place, et passe avant les tâches neuves ------------------------


def test_une_limite_pendant_la_reprise_a_chaud_la_relance_dans_sa_session_sans_compter():
    c = chantier([tache("A")])
    agent = AgentSimule(perimetres={"A": ["a.py"]}, scenario={"A": ["bacle", "ok"]},
                        limites={"A": ["", "", "refus"]}, delai_limite_s=None)  # fmt: skip
    m = Moteur(c, agent, ControlesSimules(), heure=Heure(pas=60.0))
    m.executer()
    a = c.tache("A")
    assert traces(a) == [(1, "bacle", False), (1, "bacle", True), (2, "valide", False)]
    assert c.agents_lances == 6 and c.demandes == [] and a.tentatives == 2
    premiere = agent.reprises[0]["session"]
    assert [r["session"] for r in agent.reprises] == [premiere, premiere]  # relancée, refusée
    assert not any(e["origine"] == "agent" for e in a.historique)


def test_la_reprise_a_chaud_attend_sa_place_et_passe_avant_les_taches_neuves():
    c = chantier([tache("A"), tache("B"), tache("C")])
    agent = guette(c, {("B", "ouvrier")}, scenario={"A": ["bacle", "ok"]})
    m = Moteur(c, agent, ControlesSimules(), {"paralleles": 1})
    fil = en_fond(m)
    # A est refusée par son vérificateur pendant que B écrit : sa reprise attend la place.
    assert attendre_que(lambda: (m.phase("A") or {}).get("texte") == PHASES["place"])
    time.sleep(0.05)
    with m.verrou:
        assert agent.reprises == [] and c.debit["en_ecriture"] == 1
    finir(m, agent, fil)
    ouvriers = [(a["tache"], "reprise" in a) for a in agent.appels if a["role"] == "ouvrier"]
    assert ouvriers.index(("A", True)) < ouvriers.index(("C", False))
    assert ouvriers.index(("B", False)) < ouvriers.index(("A", True))
    assert agent.pic_ouvriers == 1  # une seule place : jamais deux ouvriers à la fois
    assert [t.etat for t in c.taches] == ["verifie"] * 3


# --- la surcharge, et le vérificateur qui attend un agent libre -----------------------------------


def test_une_surcharge_arrete_les_autres_departs_deux_minutes():
    c = chantier([tache("A"), tache("B")])
    heure = Heure()
    agent = guette(c, limites={"A": ["surcharge"]})
    m = Moteur(c, agent, ControlesSimules(), {"paralleles": 1}, heure=heure)
    fil = en_fond(m)
    assert attendre_que(lambda: c.debit.get("suspensions") == {"surcharge": T0 + 120})
    assert PAUSE_SURCHARGE_S == 120 and c.debit["reprise"] is None
    assert c.debit["phrase"].endswith(
        "Claude est surchargé pour un moment (ce n'est pas une limite de l'abonnement) : plus "
        f"aucun lancement, ils reprennent {heure_dite(T0 + 120, T0)}."
    )
    heure.t = T0 + 119
    time.sleep(0.05)
    assert [(a["tache"], a["role"]) for a in agent.appels] == [("A", "ouvrier")]
    heure.t = T0 + 120
    finir(m, agent, fil)
    assert [t.etat for t in c.taches] == ["verifie"] * 2 and c.tache("A").tentatives == 1
    assert sum(t.startswith("Claude est surchargé") for t in fil_de(m)) == 1


def test_un_verificateur_sans_agent_libre_dit_qu_il_attend_et_le_temps_est_mesure():
    c = chantier([tache("A"), tache("B"), tache("C")])
    heure, horloge = Heure(), Horloge()  # le temps des mesures n'avance que sur ordre du test
    reglages = {"limites": {"A": ["", "refus"]}, "type_limite": "seven_day_opus"}
    agent = guette(c, {("B", "ouvrier"), ("C", "ouvrier")}, delai_limite_s=None, **reglages)
    profil = {"paralleles": 2, "agents_max": 2}
    m = Moteur(c, agent, ControlesSimules(), profil, horloge=horloge, heure=heure)
    fil = en_fond(m)
    # Le vérificateur de A, refusé (Opus), attend la reprise ; B et C écrivent, deux jetons.
    pause = PHASES["pause"].format(heure_dite(T0 + QUART, T0))
    assert attendre_que(lambda: (m.phase("A") or {}).get("texte") == pause)
    assert agent.debuts[("C", "ouvrier")].wait(5)
    horloge.t += 7
    heure.t += QUART  # la suspension prend fin : il ne manque plus qu'un agent libre
    assert attendre_que(lambda: (m.phase("A") or {}).get("texte") == PHASES["jeton"])
    assert c.tache("A").etat == "en_verification"
    horloge.t += 11
    finir(m, agent, fil)
    (entree,) = c.tache("A").historique
    assert entree["issue"] == "valide"
    assert (entree["durees"]["pause"], entree["durees"]["jeton"]) == (7, 11)


def test_un_ouvrier_qui_a_une_place_mais_pas_d_agent_libre_le_dit():
    c = chantier([tache("A", modele="opus", effort="medium"), tache("B"), tache("C")])
    heure = Heure()
    reglages = {"limites": {"A": ["refus"]}, "type_limite": "seven_day_opus"}
    agent = guette(c, {("B", "ouvrier"), ("C", "ouvrier")}, delai_limite_s=None, **reglages)
    m = Moteur(c, agent, ControlesSimules(), {"paralleles": 3, "agents_max": 2}, heure=heure)
    fil = en_fond(m)
    assert agent.debuts[("C", "ouvrier")].wait(5)  # A refusée (Opus) : C prend son jeton
    heure.t += QUART  # Opus repart, une place est libre, mais B et C tiennent les deux jetons
    assert attendre_que(lambda: (m.phase("A") or {}).get("texte") == PHASES["jeton"])
    finir(m, agent, fil)
    assert [t.etat for t in c.taches] == ["verifie"] * 3


# --- le fil qui ne démarre pas --------------------------------------------------------------------


def test_une_tache_dont_le_fil_ne_demarre_pas_revient_et_rend_sa_place(monkeypatch):
    demarrer = threading.Thread.start

    def start(fil):
        if fil.name == "atelier-B":
            raise RuntimeError("can't start new thread")
        return demarrer(fil)

    monkeypatch.setattr(threading.Thread, "start", start)
    c = chantier([tache("A"), tache("B")])
    m = Moteur(c, AgentSimule(perimetres={"A": ["a.py"], "B": ["b.py"]}), ControlesSimules())
    m.executer()  # rend la main : la place de B et sa marque « en vol » sont rendues
    b = c.tache("B")
    assert b.etat == "revenu" and traces(b) == [(0, "panne", False)]
    assert "RuntimeError : can't start new thread" in c.demandes[-1]["question"]
    assert c.tache("A").etat == "verifie" and not m.en_route
    assert (m.places.en_ecriture(), m.places.agents_en_marche(), m._en_vol) == (0, 0, set())


# --- en marche : la boucle du moteur, pas son fil -------------------------------------------------


def test_en_marche_suit_la_boucle_du_moteur_et_pas_son_fil(tmp_path):
    atelier = atelier_simule(tmp_path, [tache("A")])
    m, sortie, suite = atelier.moteur, threading.Event(), threading.Event()
    mener = m._mener

    def mener_puis_tarder():
        mener()
        sortie.set()
        assert suite.wait(5)

    m._mener = mener_puis_tarder
    atelier.lancer()
    assert sortie.wait(5)
    assert atelier.fil.is_alive() and not atelier.en_marche()  # une décision relancerait
    suite.set()
    atelier.fil.join(5)
    assert etats(atelier) == ["verifie"]


def test_un_fil_parti_mais_pas_encore_entre_compte_comme_en_marche(tmp_path):
    atelier = atelier_simule(tmp_path, [tache("A")])
    m, entrer = atelier.moteur, threading.Event()
    executer = m.executer

    def executer_en_retard():
        assert entrer.wait(5)
        executer()

    m.executer = executer_en_retard
    atelier.lancer()
    assert atelier.en_marche() and not m.en_route
    entrer.set()
    atelier.fil.join(5)
    assert not atelier.en_marche() and etats(atelier) == ["verifie"]


def test_la_fin_d_un_ancien_lancement_ne_coupe_pas_la_route_du_suivant(tmp_path):
    agent = guette(chantier([tache("A"), tache("B")]), {("B", "ouvrier")})
    atelier = atelier_simule(tmp_path, [tache("A")], agent=agent)
    m, mener, second = atelier.moteur, atelier.moteur._mener, []

    def mener_puis_relancer():
        mener()
        if second:
            return
        with m.verrou:  # une tâche arrive après la sortie de la boucle : un second lancement
            m.chantier.taches.append(tache("B", modele="sonnet", effort="low"))
        second.append(threading.Thread(target=m.executer))
        second[0].start()
        assert agent.debuts[("B", "ouvrier")].wait(5)

    m._mener = mener_puis_relancer
    atelier.lancer()
    atelier.fil.join(5)  # le premier lancement a fini ; son `finally` est passé
    assert m.en_route and atelier.en_marche()
    agent.liberation.set()
    second[0].join(5)
    assert not m.en_route and etats(atelier) == ["verifie", "verifie"]


def test_un_executer_de_trop_suit_la_boucle_qui_tourne_sans_en_mener_une_autre():
    c = chantier([tache("A")])
    agent = guette(c, {("A", "ouvrier")})
    m = Moteur(c, agent, ControlesSimules())
    premier = en_fond(m)
    assert agent.debuts[("A", "ouvrier")].wait(5)
    de_trop = en_fond(m)
    time.sleep(0.05)
    assert de_trop.is_alive()  # il attend la fin de la boucle qui tourne
    finir(m, agent, premier)
    de_trop.join(5)
    assert not de_trop.is_alive() and agent.compte("A", "ouvrier") == 1
    assert sum(t.startswith("Chantier terminé") for t in fil_de(m)) == 1  # une seule boucle


def test_une_tache_en_vol_dont_le_modele_est_suspendu_ne_retient_pas_les_neuves():
    # Écrit par le vérificateur de F2 : sans la condition sur la suspension, une tâche qui attend
    # la fin d'une limite d'Opus retiendrait toutes les tâches neuves sur d'autres modèles.
    c = chantier(
        [
            tache("X", modele="opus", effort="medium"),
            tache("W", modele="haiku", effort="low"),
            tache("Y", modele="haiku", effort="low", depend_de=["W"]),
        ]
    )
    heure = Heure()
    agent = guette(
        c,
        retenus={("W", "ouvrier")},
        limites={"X": ["refus"]},
        type_limite="seven_day_opus",
        delai_limite_s=None,
    )
    m = Moteur(c, agent, ControlesSimules(), {"paralleles": 2}, heure=heure)
    fil = en_fond(m)
    assert attendre_que(
        lambda: "X" in m._veulent_ecrire and agent.debuts[("W", "ouvrier")].is_set()
    )
    agent.liberation.set()  # W finit : Y devient prête pendant que X (Opus) attend sa suspension
    assert agent.debuts[("Y", "ouvrier")].wait(3)
    heure.t += QUART
    fil.join(5)
    assert [t.etat for t in c.taches] == ["verifie"] * 3
