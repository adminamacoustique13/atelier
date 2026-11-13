"""Les niveaux de vérification branchés dans le moteur, la retouche, les contrôles non rejoués.

Chaque test passe par le moteur entier (ouvrier, périmètre, contrôles, vérificateur) et constate
ce que reçoit le vérificateur lancé : son modèle, son effort et sa consigne, comparée au
caractère près à celle que rédige `atelier.consignes`. Les doubles donnent eux-mêmes ce qu'une
autre tâche ajoute aux contrôles : `empreinte(dossier)` et `differences(dossier, avant, apres)`.
Les tests de concurrence attendent un état, jamais une durée.
"""

import itertools
import json
import subprocess
import sys

import pytest

from atelier import dosage
from atelier import moteur as module
from atelier.agents import Resultat
from atelier.consignes import (
    consigne_reverification,
    consigne_verificateur,
    consigne_verificateur_bornee,
)
from atelier.controles import ControlesGit, ControlesSimules
from atelier.moteur import MOTIF_ARRET, RELANCER_TEL, Jugement, Moteur, taches_du_plan
from tests.test_fusion import JOURNAL, MARQUEURS
from tests.test_moteur import AgentParRang, chantier, tache, traces
from tests.test_moteur_places import T0, Heure, attendre_que, en_fond

PROFIL = {"commandes": ["pytest -q"]}
SORTIE = "12 passed in 0.41s (sortie-jouee-7f3a)"  # ce que rendent les contrôles du double
CHANGES = ["a.py", "tests/test_a.py"]  # les fichiers que le double dit changés par la retouche
SANS_COMMANDE = "aucune commande de contrôle"  # dans la phrase dite au fil une fois


def verdict(valide=False, motif="bacle", resume="Le cas vide n'est pas traité.", **en_plus):
    """Le texte d'un vérificateur : un court verdict, puis l'objet JSON sur la dernière ligne."""
    objet = {"valide": valide, "motif": motif, "resume": resume, **en_plus}
    return "Verdict.\n" + json.dumps(objet, ensure_ascii=False)


ACCORD = verdict(True, "bacle", "Tous les critères sont remplis.")
LOCAL = verdict(motif="local", resume="La liste vide plante.", reste=["Traiter la liste vide."],
                fichiers=["a.py"])  # fmt: skip
BACLE = verdict(reste=["Ajouter le test du cas vide."], fichiers=["tests/test_a.py"])


class Agent(AgentParRang):
    """L'agent par rang de `test_moteur`, qui note chaque vérificateur lancé : son dosage, sa
    consigne, et le relevé que porte la tâche à son départ. `pannes` donne, par (tâche, rôle), la
    nature de l'échec de chacun des premiers appels, qui s'arrêtent sur une erreur (None : cet
    appel-là travaille normalement)."""

    def __init__(self, c, issues=None, textes=None, pannes=None, **champs):
        perimetres = {t.id: t.perimetre for t in c.taches}
        super().__init__(issues, textes, perimetres=perimetres, **champs)
        self.chantier, self.verifs, self.releves_a_la_reprise = c, [], []
        self.pannes = {cle: list(natures) for cle, natures in (pannes or {}).items()}

    def executer(self, consigne, modele, effort, dossier, lecture_seule=False, contexte=None,
                 copie_jetable=False, reprendre=None):  # fmt: skip
        contexte = contexte or {}
        if contexte.get("role") == "ouvrier" and reprendre is not None:
            self.releves_a_la_reprise.append(self.chantier.tache(contexte["tache"]).releve)
        if contexte.get("role") == "verificateur":
            t = self.chantier.tache(contexte["tache"])
            self.verifs.append({"tache": t.id, "modele": modele, "effort": effort,
                                "consigne": consigne, "releve": t.releve,
                                "releve_sur": t.releve_sur})  # fmt: skip
        resultat = super().executer(consigne, modele, effort, dossier, lecture_seule, contexte,
                                    copie_jetable, reprendre)  # fmt: skip
        natures = self.pannes.get((contexte.get("tache"), contexte.get("role")))
        nature = natures.pop(0) if natures else None
        if nature is not None:
            erreur = "Arrêt simulé de l'agent."
            return Resultat(ok=False, erreur=erreur, session=resultat.session, nature=nature)
        return resultat


class Controles(ControlesSimules):
    """Des contrôles simulés qui jouent `sorties` puis passent avec `SORTIE`, donnent une
    empreinte qui change à chaque passe de l'ouvrier, et les fichiers changés entre deux.

    `releves_au_depart` : le relevé de la tâche à chaque copie préparée (départ neuf), avant
    que la passe ne soit jugée. `principale` : ce que rendent les contrôles de la branche
    principale, appel après appel, puis ils passent.
    """

    commandes = ["pytest -q"]

    def __init__(self, sorties=(), principale=(), empreinte_en_panne=False):
        self.sorties, self.principale = list(sorties), list(principale)
        self.passes, self.panne = 0, empreinte_en_panne
        self.releves_au_depart, self.demandes = [], []

    def preparer(self, t):
        self.releves_au_depart.append((t.releve, t.releve_sur))

    def fichiers_modifies(self, t, dossier, resultat):
        self.passes += 1  # le contenu de la copie vient de changer
        return super().fichiers_modifies(t, dossier, resultat)

    def mecaniques(self, t, dossier):
        return self.sorties.pop(0) if self.sorties else (True, SORTIE)

    def controler_principale(self):
        return self.principale.pop(0) if self.principale else (True, "")

    def empreinte(self, dossier):
        if self.panne:
            raise RuntimeError("git ne répond pas")
        return f"etat-{self.passes}"

    def differences(self, dossier, avant, apres):
        self.demandes.append((avant, apres))
        return list(CHANGES) if avant != apres else []


def monter(taches, profil=None, controles=None, **agent):
    c = chantier(taches)
    a = Agent(c, **agent)
    controles = controles or Controles()
    return c, Moteur(c, a, controles, profil), a, controles


def jugements_de(m):
    """Fait noter au moteur chaque jugement d'une passe (`_juger`), dans l'ordre."""
    vus, juger = [], m._juger

    def noter(*arguments, **reglages):
        jugement = juger(*arguments, **reglages)
        vus.append(jugement)
        return jugement

    m._juger = noter
    return vus


# --- un niveau par test, à travers le moteur --------------------------------------------------


def test_niveau_complet_un_modele_au_dessus_et_la_consigne_complete_avec_les_controles():
    a = tache("A", type="delicate")
    c, m, agent, _ = monter([a], PROFIL)
    m.executer()
    (v,) = agent.verifs
    assert (v["modele"], v["effort"]) == dosage.verificateur("opus", "high") == ("fable", "high")
    assert v["consigne"] == consigne_verificateur(a, c.contrat, PROFIL, sortie_controles=SORTIE)
    assert a.etat == "verifie" and traces(a) == [(1, "valide", False)]


def test_niveau_borne_le_meme_modele_et_la_consigne_bornee_au_verdict_complet():
    a = tache("A", type="courante")
    c, m, agent, _ = monter([a], PROFIL)
    m.executer()
    (v,) = agent.verifs
    assert (v["modele"], v["effort"]) == (a.modele, a.effort) == ("sonnet", "medium")
    attendue = consigne_verificateur_bornee(a, c.contrat, PROFIL, SORTIE, verdict_complet=True)
    assert v["consigne"] == attendue
    assert '"local"' in v["consigne"] and a.etat == "verifie"
    assert "Vérificateur lancé (Sonnet, effort moyen)." in [e["texte"] for e in c.evenements]


def test_niveau_mecanique_aucun_verificateur_les_controles_decident_seuls():
    a = tache("A")  # mécanique, et le profil a une commande de contrôle
    controles = Controles(sorties=[(False, "$ pytest -q\n1 failed")])
    c, m, agent, _ = monter([a], PROFIL, controles)
    m.executer()
    assert agent.verifs == [] and [x["role"] for x in agent.appels] == ["ouvrier", "ouvrier"]
    assert a.etat == "verifie" and c.agents_lances == 2  # l'ouvrier et sa reprise, rien d'autre
    assert traces(a) == [(1, "ne_sait_pas", False), (1, "valide", True)]
    assert a.historique[0]["origine"] == "controles"  # le contrôle rouge a refusé seul
    assert "Entrée sans vérificateur" in a.historique[-1]["detail"]
    assert any("aucun vérificateur ne part" in e["texte"] for e in c.evenements)
    assert not any(SANS_COMMANDE in e["texte"] for e in c.evenements)


# --- le plancher : un calcul ne passe jamais sans vérificateur ----------------------------------


@pytest.mark.parametrize("reglage", ["mecanique", "bornee"])
@pytest.mark.parametrize("type_", ["delicate", "physique"])
def test_le_plancher_tient_contre_le_profil(type_, reglage):
    a = tache("A", type=type_)
    profil = {**PROFIL, "verification": {type_: reglage}}
    c, m, agent, _ = monter([a], profil)
    m.executer()
    (v,) = agent.verifs
    assert (v["modele"], v["effort"]) == dosage.verificateur(*dosage.depart(type_))
    assert v["consigne"] == consigne_verificateur(a, c.contrat, profil, sortie_controles=SORTIE)
    assert a.etat == "verifie"


@pytest.mark.parametrize("reglage", ["mecanique", "bornee"])
def test_la_reparation_de_la_branche_principale_garde_le_plancher(reglage):
    """La tâche que le moteur ajoute seul (type « courante ») reçoit la vérification complète,
    même quand le profil fait descendre les tâches courantes et les réparations."""
    profil = {**PROFIL, "verification": {"courante": reglage, "reparation": reglage}}
    controles = Controles(principale=[(False, "1 failed sur la branche principale")])
    c, m, agent, _ = monter([tache("A", type="courante")], profil, controles)
    m.executer()
    reparation = c.tache("REPARATION-1")
    assert reparation.type == "courante" and reparation.etat == "verifie" and c.termine
    (v,) = [v for v in agent.verifs if v["tache"] == "REPARATION-1"]
    assert (v["modele"], v["effort"]) == ("opus", "medium")  # un modèle au-dessus
    attendue = consigne_verificateur(reparation, c.contrat, profil, sortie_controles=SORTIE)
    assert v["consigne"] == attendue
    assert len([v for v in agent.verifs if v["tache"] == "A"]) == (reglage == "bornee")


def test_un_type_inconnu_et_un_niveau_pose_dans_le_plan_ne_font_pas_descendre():
    """Le niveau ne vient que du type et du profil : un « niveau » ou une « verification » posé
    par tâche dans le plan n'est pas lu, et un type inconnu est vérifié complètement, même si le
    profil le nomme."""
    profil = {**PROFIL, "verification": {"inconnu": "mecanique", "physique": "mecanique"}}
    brut = {"id": "P", "titre": "Formule de la norme", "type": "physique", "perimetre": ["p.py"],
            "verification": "mecanique", "niveau": "mecanique"}  # fmt: skip
    (p,) = taches_du_plan({"taches": [brut]}, profil)
    x = tache("X", type="inconnu")
    c, m, agent, _ = monter([p, x], profil)
    m.executer()
    verifs = {v["tache"]: v for v in agent.verifs}
    for t in (p, x):
        assert verifs[t.id]["consigne"] == consigne_verificateur(
            t, c.contrat, profil, sortie_controles=SORTIE
        )
    assert (verifs["P"]["modele"], verifs["X"]["modele"]) == ("fable", "opus")


def test_mecanique_sans_commande_de_controle_devient_bornee_et_le_fil_le_dit_une_fois():
    a, b = tache("A"), tache("B")
    c, m, agent, _ = monter([a, b], {})
    m.executer()
    assert sorted(v["tache"] for v in agent.verifs) == ["A", "B"]
    for v in agent.verifs:
        t = c.tache(v["tache"])
        assert (v["modele"], v["effort"]) == ("sonnet", "medium")  # le même modèle que l'ouvrier
        assert v["consigne"] == consigne_verificateur_bornee(
            t, c.contrat, {}, "", verdict_complet=True
        )
    assert [t.etat for t in c.taches] == ["verifie", "verifie"]
    assert len([e for e in c.evenements if SANS_COMMANDE in e["texte"]]) == 1


# --- la sortie des contrôles joués, jamais rejoués ---------------------------------------------


def test_la_sortie_reellement_jouee_par_les_controles_arrive_au_verificateur(tmp_path):
    def git(*arguments):
        subprocess.run(["git", *arguments], cwd=tmp_path, check=True, capture_output=True)

    git("init", "-q", "-b", "main")
    git("config", "user.name", "Essai")
    git("config", "user.email", "essai@example.invalid")
    (tmp_path / "LISEZMOI.md").write_text("socle\n", "utf-8")
    git("add", "-A")
    git("commit", "-q", "-m", "socle")
    # La commande calcule ce qu'elle affiche : seul son vrai passage peut l'écrire.
    commande = f"\"{sys.executable}\" -c \"print('sortie-jouee-' + str(6 * 7))\""
    profil = {"commandes": [commande]}
    a = tache("A", type="courante")
    c = chantier([a])
    agent = Agent(c)
    Moteur(c, agent, ControlesGit(tmp_path, commandes=[commande]), profil).executer()
    (v,) = agent.verifs
    assert "sortie-jouee-42" in v["consigne"] and "sortie-jouee-42" not in commande
    assert "Ne rejoue aucune de ces commandes" in v["consigne"]
    assert a.etat == "verifie"


@pytest.mark.parametrize("type_", ["delicate", "courante"])
def test_la_sortie_des_controles_arrive_aux_trois_consignes(type_):
    """Le premier vérificateur (complet ou borné) puis celui de la retouche reçoivent chacun la
    sortie que les contrôles viennent de rendre sur la passe qu'ils jugent."""
    a = tache("A", type=type_)
    sorties = [(True, "premiere-passe-1111"), (True, "retouche-2222")]
    c, m, agent, _ = monter([a], PROFIL, Controles(sorties), textes={"A": [BACLE, ACCORD]})
    m.executer()
    premiere, retouche = agent.verifs
    assert "premiere-passe-1111" in premiere["consigne"]
    assert "retouche-2222" in retouche["consigne"] and "premiere-passe" not in retouche["consigne"]
    assert "Ce que la retouche a touché" in retouche["consigne"]
    assert a.etat == "verifie"


def test_rien_n_est_joue_sans_commande_au_profil_le_moteur_passe_none():
    """Sans commande au profil, les consignes complète et de retouche sont celles d'avant,
    même si le double des contrôles affiche quelque chose."""
    a = tache("A", type="delicate")
    controles = Controles(sorties=[(True, "affiche-sans-commande"), (True, "encore")])
    c, m, agent, _ = monter([a], {}, controles, textes={"A": [BACLE, ACCORD]})
    m.executer()
    premiere, retouche = agent.verifs
    assert premiere["consigne"] == consigne_verificateur(a, c.contrat, {}, sortie_controles=None)
    attendue = consigne_reverification(a, c.contrat, {}, BACLE, sortie_controles=None,
                                       fichiers=CHANGES)  # fmt: skip
    assert retouche["consigne"] == attendue
    assert "affiche-sans-commande" not in premiere["consigne"]


# --- la retouche --------------------------------------------------------------------------------


def test_un_refus_local_ecrit_le_releve_puis_la_retouche_est_jugee_au_niveau_de_l_ouvrier():
    a = tache("A", type="courante")
    profil = {**PROFIL, "verification": {"courante": "complete"}}  # le premier : un cran au-dessus
    controles = Controles()
    c, m, agent, _ = monter([a], profil, controles, textes={"A": [LOCAL, ACCORD]})
    vus = jugements_de(m)
    m.executer()
    premiere, retouche = agent.verifs
    assert (premiere["modele"], premiere["effort"]) == ("opus", "medium")
    assert (retouche["modele"], retouche["effort"]) == (a.modele, a.effort) == ("sonnet", "medium")
    # Au départ de la retouche, la tâche porte le relevé et l'état de la copie déjà vue.
    assert "La liste vide plante." in retouche["releve"]
    assert "Traiter la liste vide." in retouche["releve"]
    assert retouche["releve_sur"] == "etat-1"
    assert controles.demandes == [("etat-1", "etat-2")]
    attendue = consigne_reverification(a, c.contrat, profil, LOCAL, sortie_controles=SORTIE,
                                       fichiers=CHANGES)  # fmt: skip
    assert retouche["consigne"] == attendue
    assert "`tests/test_a.py`" in retouche["consigne"]
    assert traces(a) == [(1, "local", False), (1, "valide", True)] and a.etat == "verifie"
    assert vus[0].motif == "local" and vus[0].reprenable  # la retouche part à chaud
    assert (a.releve, a.releve_sur) == ("", "")  # effacés par l'accord


def test_la_retouche_d_une_tache_du_plancher_reste_complete():
    a = tache("A", type="delicate")
    c, m, agent, _ = monter([a], PROFIL, textes={"A": [BACLE, ACCORD]})
    m.executer()
    premiere, retouche = agent.verifs
    assert (premiere["modele"], premiere["effort"]) == ("fable", "high")
    assert (retouche["modele"], retouche["effort"]) == ("fable", "high")  # pas celui de l'ouvrier
    attendue = consigne_reverification(a, c.contrat, PROFIL, BACLE, sortie_controles=SORTIE,
                                       fichiers=CHANGES)  # fmt: skip
    assert retouche["consigne"] == attendue
    assert a.etat == "verifie"


def test_sans_empreinte_la_retouche_part_quand_meme_sans_nommer_de_fichier():
    a = tache("A", type="courante")
    controles = Controles(empreinte_en_panne=True)
    c, m, agent, _ = monter([a], PROFIL, controles, textes={"A": [BACLE, ACCORD]})
    m.executer()
    _, retouche = agent.verifs
    assert retouche["releve_sur"] == "" and "Ajouter le test du cas vide." in retouche["releve"]
    attendue = consigne_reverification(a, c.contrat, PROFIL, BACLE, sortie_controles=SORTIE)
    assert retouche["consigne"] == attendue and a.etat == "verifie"


# --- ce qui efface le relevé ---------------------------------------------------------------------


def test_le_releve_est_efface_par_un_accord():
    a = tache("A", type="courante")
    c, m, agent, _ = monter([a], PROFIL, textes={"A": [BACLE, ACCORD]})
    m.executer()
    assert agent.verifs[1]["releve"] != ""  # la retouche l'a reçu
    assert (a.releve, a.releve_sur) == ("", "") and a.etat == "verifie"


def test_le_releve_est_efface_par_un_refus_d_un_autre_motif():
    """La retouche refusée pour le fond efface le relevé : le départ neuf qui suit le trouve
    vide. Contre-épreuve : refusée pour « bâclé », elle le laisse (test suivant)."""
    a = tache("A", type="courante")
    fond = verdict(motif="ne_sait_pas", resume="La démarche est fausse.")
    controles = Controles()
    c, m, agent, _ = monter([a], PROFIL, controles, textes={"A": [BACLE, fond, ACCORD]})
    m.executer()
    assert controles.releves_au_depart == [("", ""), ("", "")]
    assert agent.verifs[1]["releve"] != "" and agent.verifs[2]["releve"] == ""
    assert a.etat == "verifie"


def test_le_releve_est_efface_par_un_depart_dans_une_copie_neuve():
    a = tache("A", type="courante")
    controles = Controles()
    c, m, agent, _ = monter([a], PROFIL, controles, textes={"A": [BACLE, BACLE, ACCORD]})
    m.executer()
    assert controles.releves_au_depart[1][0] != ""  # encore là quand la copie neuve est prête
    troisieme = agent.verifs[2]  # le premier vérificateur du départ neuf
    assert (troisieme["releve"], troisieme["releve_sur"]) == ("", "")
    attendue = consigne_verificateur_bornee(a, c.contrat, PROFIL, SORTIE, verdict_complet=True)
    assert troisieme["consigne"] == attendue  # une vérification entière, pas une retouche
    assert a.etat == "verifie" and a.tentatives == 2


def test_le_releve_est_efface_par_un_debord():
    a = tache("A", type="courante")
    controles = Controles()
    issues = {("A", "ouvrier"): ["ok", "deborde", "ok"]}  # la retouche écrit hors périmètre
    c, m, agent, _ = monter([a], PROFIL, controles, issues=issues, textes={"A": [BACLE, ACCORD]})
    m.executer()
    assert traces(a)[:2] == [(1, "bacle", False), (1, "deborde", True)]
    assert agent.releves_a_la_reprise[0] != ""  # écrit par le refus « bâclé »
    assert controles.releves_au_depart == [("", ""), ("", "")]  # effacé par le débord
    assert len(agent.verifs) == 2 and agent.verifs[1]["releve"] == ""
    assert a.etat == "verifie"


def test_le_releve_reste_apres_un_arret():
    a = tache("A", type="courante")
    c = chantier([a])
    agent = Agent(c, textes={"A": [BACLE]})
    m = Moteur(c, agent, Controles(), PROFIL)
    m.sur_changement = lambda: (
        c.evenements and "Je redonne la main" in c.evenements[-1]["texte"] and m.arreter("A")
    )
    m.executer()
    assert a.etat == "revenu" and traces(a)[-1][1] == "arretee"
    assert "Ajouter le test du cas vide." in a.releve and a.releve_sur == "etat-1"


def test_le_releve_reste_apres_une_erreur_du_verificateur_de_la_retouche():
    """Un vérificateur en erreur ne dit rien du travail : le relevé reste, et le départ neuf
    qui suit le trouve encore."""
    a = tache("A", type="courante")
    controles = Controles()
    pannes = {("A", "verificateur"): [None, "delai", "delai"]}
    c, m, agent, _ = monter([a], PROFIL, controles, textes={"A": [BACLE, ACCORD]}, pannes=pannes)
    m.executer()
    assert [e["origine"] for e in a.historique][:2] == ["verdict", "agent"]
    assert "Ajouter le test du cas vide." in controles.releves_au_depart[1][0]
    assert a.etat == "verifie"


def test_le_releve_reste_apres_un_refus_des_controles():
    """Un contrôle rouge sur la retouche ne dit rien de ce qui était relevé : il reste, et le
    départ neuf qui suit le trouve encore (avant de l'effacer, la copie étant neuve)."""
    a = tache("A", type="courante")
    controles = Controles(sorties=[(True, SORTIE), (False, "$ pytest -q\n1 failed")])
    c, m, agent, _ = monter([a], PROFIL, controles, textes={"A": [BACLE, ACCORD]})
    m.executer()
    assert traces(a)[:2] == [(1, "bacle", False), (1, "ne_sait_pas", True)]
    assert controles.releves_au_depart[1][0] != ""
    assert a.etat == "verifie"


# --- arrêt, limite ------------------------------------------------------------------------------


def test_un_arret_juste_avant_le_lancement_d_un_verificateur_borne_ne_lance_rien():
    a = tache("A", type="courante")
    c = chantier([a])
    agent = Agent(c)
    m = Moteur(c, agent, Controles(), PROFIL)
    arrets = []

    def au_changement():
        dernier = c.evenements[-1]["texte"] if c.evenements else ""
        if dernier.startswith("Vérificateur lancé (Sonnet, effort moyen)") and not arrets:
            arrets.append(m.arreter("A"))

    m.sur_changement = au_changement
    m.executer()
    assert arrets == [True] and agent.verifs == []
    assert [x["role"] for x in agent.appels] == ["ouvrier"] and c.agents_lances == 1
    assert a.etat == "revenu" and traces(a) == [(1, "arretee", False)]
    assert c.demandes[-1]["question"].endswith(MOTIF_ARRET)


def test_une_limite_pendant_une_verification_bornee_fait_attendre_sans_rien_compter(monkeypatch):
    monkeypatch.setattr(module, "PAS_VEILLE_S", 0.01)
    a = tache("A", type="courante")
    c = chantier([a])
    heure = Heure()
    agent = Agent(c, limites={"A": ["", "refus"]}, delai_limite_s=None)
    m = Moteur(c, agent, Controles(), PROFIL, heure=heure)
    fil = en_fond(m)
    assert attendre_que(lambda: c.debit.get("reprise") is not None)
    assert attendre_que(lambda: (m.phase("A") or {}).get("texte", "").startswith("En pause"))
    with m.verrou:
        assert a.etat == "en_verification" and c.agents_lances == 1 and a.tentatives == 1
        assert len(agent.verifs) == 1 and a.historique == []
    heure.t = T0 + 3600
    fil.join(5)
    assert not fil.is_alive()
    assert a.etat == "verifie" and traces(a) == [(1, "valide", False)]
    assert c.agents_lances == 2 and a.tentatives == 1  # le vérificateur refusé ne compte pas
    attendue = consigne_verificateur_bornee(a, c.contrat, PROFIL, SORTIE, verdict_complet=True)
    assert [(v["modele"], v["consigne"]) for v in agent.verifs] == [("sonnet", attendue)] * 2


def test_un_verificateur_borne_n_attend_pas_une_limite_propre_a_opus(monkeypatch):
    """Le jeton attendu est celui du vérificateur qui part : une limite propre à Opus ne retient
    pas un vérificateur borné de Sonnet."""
    monkeypatch.setattr(module, "PAS_VEILLE_S", 0.01)
    a = tache("A", type="courante")
    c = chantier([a])
    agent = Agent(c, limites={"A": ["", "refus"]}, delai_limite_s=None,
                  type_limite="seven_day_opus")  # fmt: skip
    m = Moteur(c, agent, Controles(), PROFIL, heure=Heure())  # l'heure n'avance jamais
    fil = en_fond(m)
    assert attendre_que(lambda: not fil.is_alive())  # aucune attente de la fin de la limite
    assert a.etat == "verifie" and [v["modele"] for v in agent.verifs] == ["sonnet", "sonnet"]
    assert c.debit["suspensions"] == {"opus": T0 + 15 * 60}


# --- les champs nouveaux de `Jugement` ----------------------------------------------------------


def test_un_jugement_construit_ailleurs_garde_des_valeurs_neutres():
    j = Jugement("bacle", "détail", "verdict")
    assert (j.lisible, j.nature, j.reste, j.fichiers) == (False, "", (), ())
    assert (j.meme_defaut, j.fond_faux) == (False, False)


def test_un_refus_lisible_porte_lisible_reste_et_fichiers_mais_pas_fond_faux():
    a = tache("A", type="courante")
    c, m, agent, _ = monter([a], PROFIL, textes={"A": [LOCAL, ACCORD]})
    vus = jugements_de(m)
    m.executer()
    refus, accord = vus
    assert (refus.lisible, refus.origine, refus.motif) == (True, "verdict", "local")
    assert refus.reste == ("Traiter la liste vide.",) and refus.fichiers == ("a.py",)
    assert not refus.fond_faux and not refus.meme_defaut and refus.nature == ""
    assert accord.motif is None and accord.lisible


def test_un_fond_juge_faux_et_le_meme_defaut_dit_par_le_verificateur_de_la_retouche():
    a = tache("A", type="courante")
    meme = verdict(resume="Le cas vide plante encore.", meme_defaut=True, reste=["Idem."])
    fond = verdict(motif="ne_sait_pas", resume="La formule est fausse.", meme_defaut=True)
    textes = {"A": [verdict(meme_defaut=True), meme, fond, ACCORD]}
    c, m, agent, _ = monter([a], PROFIL, textes=textes)
    vus = jugements_de(m)
    m.executer()
    premier, retouche, depart_neuf = vus[0], vus[1], vus[2]
    assert not premier.meme_defaut  # un premier jugement n'est pas une retouche
    assert retouche.meme_defaut and not retouche.fond_faux
    assert depart_neuf.fond_faux and not depart_neuf.meme_defaut  # pas une retouche non plus
    assert depart_neuf.lisible and depart_neuf.motif == "ne_sait_pas"


def test_un_verdict_illisible_n_est_ni_lisible_ni_un_fond_faux():
    a = tache("A", type="courante")
    textes = {"A": ["Je n'ai pas conclu.", "Toujours rien.", ACCORD]}
    c, m, agent, _ = monter([a], PROFIL, textes=textes)
    vus = jugements_de(m)
    m.executer()
    illisible = vus[0]
    assert (illisible.motif, illisible.origine) == ("ne_sait_pas", "verdict")
    assert not illisible.lisible
    assert not illisible.fond_faux and illisible.reste == () and not illisible.reprenable
    assert (a.releve, a.releve_sur) == ("", "")


def test_l_echec_d_un_agent_porte_sa_nature():
    a = tache("A", type="courante")
    pannes = {("A", "ouvrier"): ["delai"], ("A", "verificateur"): ["delai", "delai"]}
    c, m, agent, _ = monter([a], PROFIL, pannes=pannes)
    vus = jugements_de(m)
    m.executer()
    ouvrier, verificateur = vus[0], vus[1]
    assert (ouvrier.origine, ouvrier.nature) == ("agent", "delai")
    assert (verificateur.origine, verificateur.nature) == ("agent", "delai")
    assert not verificateur.lisible and not verificateur.fond_faux


def test_un_refus_des_controles_porte_dans_reste_ce_qui_a_echoue():
    a = tache("A", type="courante")
    sortie = "$ ruff check .\nAll checks passed!\n$ pytest -q\nFAILED test_a.py::test_vide\n1 fail"
    controles = Controles(sorties=[(False, sortie)])
    c, m, agent, _ = monter([a], PROFIL, controles)
    vus = jugements_de(m)
    m.executer()
    refus = vus[0]
    assert refus.origine == "controles"
    assert refus.reste == ("$ pytest -q\nFAILED test_a.py::test_vide\n1 fail",)
    assert not refus.lisible and not refus.fond_faux


# --- reprise après la vérification : types du plan, conflits résolus --------------------------
# Les sondes du vérificateur de M5 sont fondues ici, sans leurs affichages.

TYPES_SONDES = ["mecanique", "courante", "delicate", "physique", "conception", "reparation", "",
                "inconnu", "délicate", "Delicate", "DELICATE", "physique ", "Mecanique", "norme",
                "calcul", "mécanique"]  # fmt: skip
PROFIL_PARTAGE = {**PROFIL, "fichiers_partages": [{"motif": JOURNAL, "fusion": "git"}]}
INCONNU = "n'est pas un type connu"  # dans la phrase dite au fil pour un type inconnu


def reglages_pour(type_):
    return [
        None, "rien", ["mecanique"], {type_: "mecanique"}, {type_: "bornee"},
        {type_: "complete"}, {type_: "MECANIQUE"}, {type_: ["mecanique"]},
        dict.fromkeys([*dosage.NIVEAU_DEPART, "", "inconnu", type_, type_.lower(),
                       type_.strip()], "mecanique"),
    ]  # fmt: skip


def genre_de(v, t, c, profil):
    """Le genre de la vérification reçue (complète, bornée, autre, aucune) et son modèle."""
    if v is None:
        return "AUCUN"
    if v["consigne"] == consigne_verificateur(t, c.contrat, profil, sortie_controles=SORTIE):
        return f"complete/{v['modele']}"
    bornee = consigne_verificateur_bornee(t, c.contrat, profil, SORTIE, verdict_complet=True)
    return f"{'bornee' if v['consigne'] == bornee else 'autre'}/{v['modele']}"


def test_matrice_des_types_et_des_reglages_du_profil():
    """Chaque type posé sur la tâche, sous neuf réglages du profil (mal formés compris) : hors
    mécanique, courante et conception, la vérification est toujours complète."""
    fautes = []
    for type_ in TYPES_SONDES:
        for reglage in reglages_pour(type_):
            profil = dict(PROFIL) if reglage is None else {**PROFIL, "verification": reglage}
            t = tache("A", type=type_)
            c, m, agent, _ = monter([t], profil)
            m.executer()
            genre = genre_de(agent.verifs[0] if agent.verifs else None, t, c, profil)
            sensible = type_ not in ("mecanique", "courante", "conception")
            if sensible and not genre.startswith("complete"):
                fautes.append((type_, reglage, genre))
            assert t.etat == "verifie"
    assert not fautes, fautes


@pytest.mark.parametrize("ecrit", ["délicate", "Delicate", "physique ", "calcul", "norme",
                                   "securite", "", "reparation"])  # fmt: skip
@pytest.mark.parametrize("reglage", [None, {"courante": "mecanique"}])
def test_par_le_plan_un_type_inconnu_ou_mal_ecrit_est_verifie_completement(ecrit, reglage):
    """Le vrai chemin : le plan de l'orchestrateur passe par `taches_du_plan`, puis le moteur.
    Une graphie d'un type connu est ramenée à ce type ; un type inconnu reste tel qu'écrit,
    son ouvrier est dosé comme une courante, et il est vérifié complètement, profil ou non."""
    profil = dict(PROFIL) if reglage is None else {**PROFIL, "verification": reglage}
    brut = {"id": "P", "titre": "Formule de la norme", "perimetre": ["p.py"], "type": ecrit}
    (p,) = taches_du_plan({"taches": [brut]}, profil)
    connu = {"délicate": "delicate", "Delicate": "delicate", "physique ": "physique",
             "reparation": "reparation"}.get(ecrit)  # fmt: skip
    assert p.type == (connu or ecrit)
    c, m, agent, _ = monter([p], profil)
    m.executer()
    (v,) = agent.verifs
    assert genre_de(v, p, c, profil).startswith("complete")
    assert (v["modele"], v["effort"]) == dosage.verificateur(p.modele, p.effort)
    notes = [e for e in c.evenements if INCONNU in e["texte"]]
    if connu is None:
        assert (p.modele, p.effort) == dosage.depart("courante")
        assert len(notes) == 1 and notes[0]["tache"] == "P"
    else:
        assert notes == []
    assert p.etat == "verifie"


def test_le_fil_dit_le_type_inconnu_une_fois_pour_chaque_tache():
    plan = {"taches": [{"id": x, "titre": x, "type": "calcul", "perimetre": [f"{x}.py"]}
                       for x in ("P", "Q")]}  # fmt: skip
    p, q = taches_du_plan(plan, PROFIL)
    c, m, agent, _ = monter([p, q], PROFIL, textes={"P": [BACLE, ACCORD]})
    m.executer()  # P passe deux fois par le vérificateur, la phrase n'est dite qu'une fois
    notes = [e for e in c.evenements if INCONNU in e["texte"]]
    assert sorted(e["tache"] for e in notes) == ["P", "Q"]
    assert notes[0]["texte"].startswith("Le type de cette tâche (« calcul »)")


@pytest.mark.parametrize("connu", sorted(set(dosage.TYPES_FR) | set(dosage.NIVEAU_DEPART)))
def test_chaque_type_que_le_produit_definit_est_connu_sous_toutes_ses_graphies(connu):
    """Les types lus là où le produit les définit (`dosage`) : un type ajouté plus tard n'est
    pas « inconnu » par oubli, et aucune de ses graphies ne le fait changer de niveau."""
    graphies = (connu, connu.upper(), f"  {connu.capitalize()} ", connu.replace("e", "é", 1))
    for ecrit in graphies:
        (p,) = taches_du_plan({"taches": [{"id": "P", "titre": "T", "type": ecrit}]}, {})
        assert p.type == connu, ecrit
    c, m, agent, _ = monter([p], PROFIL)
    m.executer()
    assert not any(INCONNU in e["texte"] for e in c.evenements)
    assert module.TYPES_CONNUS == tuple(dict.fromkeys([*dosage.TYPES_FR, *dosage.NIVEAU_DEPART]))


class ControlesConflit(Controles):
    """Le double, dont l'enregistrement bute `conflits` fois sur un conflit de fusion, rendu à
    l'ouvrier sur un fichier partagé en « git »."""

    def __init__(self, conflits=1, **champs):
        super().__init__(**champs)
        self.conflits = conflits

    def enregistrer(self, t, dossier):
        if self.conflits:
            self.conflits -= 1
            return "Conflit avec la branche principale."
        return ""

    def poser_conflits(self, t, dossier):
        return {JOURNAL: MARQUEURS}


@pytest.mark.parametrize("type_", ["mecanique", "courante", "delicate"])
def test_apres_un_conflit_resolu_la_verification_est_complete_a_tout_niveau(type_):
    a = tache("A", type=type_)
    c, m, agent, _ = monter([a], PROFIL_PARTAGE, ControlesConflit())
    m.executer()
    resolu = agent.verifs[-1]
    assert "Conflit de fusion résolu" in resolu["consigne"]
    assert (resolu["modele"], resolu["effort"]) == dosage.verificateur(*dosage.depart(type_))
    assert len(agent.verifs) == (1 if type_ == "mecanique" else 2) and a.etat == "verifie"


@pytest.mark.parametrize("type_", ["mecanique", "courante"])
@pytest.mark.parametrize("motif", ["local", "bacle", "ne_sait_pas"])
def test_conflit_resolu_puis_refus_du_verificateur_la_correction_est_relue_completement(
    type_, motif
):
    a = tache("A", type=type_)
    resume, point = "La résolution efface ce que la branche avait mis.", "Rétablir la ligne."
    texte = verdict(motif=motif, resume=resume, reste=[point], fichiers=[JOURNAL])
    textes = {"A": [texte, ACCORD]} if type_ == "mecanique" else {"A": [ACCORD, texte, ACCORD]}
    c, m, agent, _ = monter([a], PROFIL_PARTAGE, ControlesConflit(), textes=textes)
    m.executer()
    (resolu,) = [v for v in agent.verifs if "Conflit de fusion résolu" in v["consigne"]]
    apres = agent.verifs[agent.verifs.index(resolu) + 1 :]
    assert apres, "la correction d'un refus de la résolution entre sans être relue"
    au_dessus = dosage.verificateur(*dosage.depart(type_))
    assert all((v["modele"], v["effort"]) == au_dessus for v in apres)
    assert "[début du verdict précédent]" in apres[0]["consigne"]
    assert a.etat == "verifie"


@pytest.mark.parametrize("type_", ["mecanique", "courante", "delicate"])
def test_conflit_resolu_puis_controles_rouges_la_resolution_est_relue_completement(type_):
    a = tache("A", type=type_)
    rouges = [(True, SORTIE), (False, "$ pytest -q\n1 failed")]
    c, m, agent, _ = monter([a], PROFIL_PARTAGE, ControlesConflit(sorties=rouges))
    m.executer()
    depart = [e["origine"] for e in a.historique if e["tentative"] == 1]
    assert depart[:2] == ["integration", "controles"]
    dernier = agent.verifs[-1]
    assert (dernier["modele"], dernier["effort"]) == dosage.verificateur(*dosage.depart(type_))
    assert dernier["consigne"] == consigne_verificateur(a, c.contrat, PROFIL_PARTAGE,
                                                       sortie_controles=SORTIE)  # fmt: skip
    assert a.etat == "verifie"


def test_la_relecture_d_un_fond_juge_faux_suit_le_niveau_de_la_tache():
    a = tache("A", type="courante")
    fond = verdict(motif="ne_sait_pas", resume="La démarche est fausse.")
    c, m, agent, _ = monter([a], PROFIL, textes={"A": [fond, ACCORD]})
    m.executer()
    _, relecture = agent.verifs
    assert (relecture["modele"], relecture["effort"]) == ("sonnet", "medium")
    attendue = consigne_reverification(a, c.contrat, PROFIL, fond, sortie_controles=SORTIE)
    assert relecture["consigne"] == attendue and a.etat == "verifie"


def test_la_retouche_d_une_reparation_et_d_un_type_inconnu_reste_complete():
    profil = {**PROFIL, "verification": {"courante": "bornee", "reparation": "bornee"}}
    controles = Controles(principale=[(False, "1 failed sur la branche principale")])
    textes = {"REPARATION-1": [BACLE, ACCORD], "X": [LOCAL, ACCORD]}
    taches = [tache("A", type="courante"), tache("X", type="inconnu")]
    c, m, agent, _ = monter(taches, profil, controles, textes=textes)
    m.executer()
    for identifiant in ("REPARATION-1", "X"):
        vus = [(v["modele"], "verdict précédent" in v["consigne"]) for v in agent.verifs
               if v["tache"] == identifiant]  # fmt: skip
        assert vus == [("opus", False), ("opus", True)], identifiant


def test_mecanique_avec_une_commande_qui_reussit_toujours_entre_sans_rien(tmp_path):
    """Permis par `dosage` : la seule commande du profil (`true`) décide, et elle passe."""

    def git(*arguments):
        subprocess.run(["git", *arguments], cwd=tmp_path, check=True, capture_output=True)

    git("init", "-q", "-b", "main")
    git("config", "user.name", "Essai")
    git("config", "user.email", "essai@example.invalid")
    (tmp_path / "LISEZMOI.md").write_text("socle\n", "utf-8")
    git("add", "-A")
    git("commit", "-q", "-m", "socle")
    a = tache("A")
    c = chantier([a])
    agent = Agent(c)
    controles = ControlesGit(tmp_path, commandes=["true"])
    Moteur(c, agent, controles, {"commandes": ["true"]}).executer()
    assert agent.verifs == [] and a.etat == "verifie"
    assert "Entrée sans vérificateur" in a.historique[-1]["detail"]


def test_un_local_sans_fin_ne_boucle_pas():
    a = tache("A", type="courante")
    c, m, agent, _ = monter([a], PROFIL, textes={"A": [LOCAL] * 40})
    m.executer()
    assert a.etat == "revenu"


def test_des_local_tous_differents_ne_bouclent_pas():
    locaux = [verdict(motif="local", resume=f"Défaut numéro {i} dans la fonction f{i}.",
                      reste=[f"Corriger f{i}."], fichiers=["a.py"]) for i in range(40)]  # fmt: skip
    a = tache("A", type="courante")
    c, m, agent, _ = monter([a], PROFIL, textes={"A": locaux})
    m.executer()
    assert a.etat == "revenu"


def test_le_releve_d_avant_un_arret_ne_vaut_plus_apres_la_relance():
    a = tache("A", type="courante")
    c = chantier([a])
    agent = Agent(c, textes={"A": [BACLE, ACCORD]})
    m = Moteur(c, agent, Controles(), PROFIL)
    fait = []
    m.sur_changement = lambda: (
        not fait and c.evenements and "Je redonne la main" in c.evenements[-1]["texte"]
        and fait.append(m.arreter("A"))
    )  # fmt: skip
    m.executer()
    assert a.etat == "revenu" and a.releve
    m.repondre(c.demandes[-1]["id"], RELANCER_TEL)
    m.executer()
    v = agent.verifs[-1]
    assert v["releve"] == "" and a.etat == "verifie"
    assert v["consigne"] == consigne_verificateur_bornee(
        a, c.contrat, PROFIL, SORTIE, verdict_complet=True
    )


def test_apres_une_montee_le_depart_neuf_est_juge_en_entier():
    a = tache("A", type="courante")
    autre = verdict(resume="Le test du cas vide compare la sortie à elle-même.",
                    reste=["Comparer à une valeur écrite."], fichiers=["t.py"])  # fmt: skip
    c, m, agent, _ = monter([a], PROFIL, textes={"A": [BACLE, autre, ACCORD]})
    m.executer()
    v = agent.verifs[2]
    assert v["releve"] == "" and "verdict précédent" not in v["consigne"]


def test_une_reprise_apres_des_controles_rouges_seuls_n_est_pas_une_retouche():
    a = tache("A", type="courante")
    controles = Controles(sorties=[(False, "$ pytest -q\n1 failed")])
    c, m, agent, _ = monter([a], PROFIL, controles)
    m.executer()
    (v,) = agent.verifs
    assert v["consigne"] == consigne_verificateur_bornee(
        a, c.contrat, PROFIL, SORTIE, verdict_complet=True
    )


def test_un_releve_laisse_dans_l_etat_ne_fait_pas_d_un_depart_une_retouche():
    a = tache("A", type="courante")
    a.releve, a.releve_sur = "Vieux relevé.", "etat-0"
    c, m, agent, _ = monter([a], PROFIL)
    m.executer()
    (v,) = agent.verifs
    assert v["releve"] == "" and "verdict précédent" not in v["consigne"]


def test_une_retouche_sans_changement_de_la_copie_ne_nomme_aucun_fichier():
    class Fige(Controles):
        def empreinte(self, dossier):
            return "etat-fixe"

    a = tache("A", type="courante")
    c, m, agent, _ = monter([a], PROFIL, Fige(), textes={"A": [LOCAL, ACCORD]})
    m.executer()
    _, retouche = agent.verifs
    assert retouche["consigne"] == consigne_reverification(
        a, c.contrat, PROFIL, LOCAL, sortie_controles=SORTIE
    )


def test_une_tache_mecanique_entre_sans_passer_en_verification():
    a = tache("A")
    c = chantier([a])
    agent = Agent(c)
    etats = []

    class Vus(Controles):
        def enregistrer(self, t, dossier):
            etats.append((t.etat, m.phase(t.id)["texte"]))
            return ""

    m = Moteur(c, agent, Vus(), PROFIL)
    m.executer()
    assert etats == [("en_cours", "Enregistrement et fusion")] and a.etat == "verifie"


def test_un_profil_mal_forme_ne_fait_pas_tomber_le_moteur():
    profils = ({"commandes": "pytest -q"}, {"commandes": [""]}, {"commandes": [" ", None]},
               {"commandes": ["pytest"], "verification": [1, 2]},
               {"commandes": ["pytest"], "verification": {"mecanique": None}})  # fmt: skip
    for profil in profils:
        for type_ in ("mecanique", "delicate"):
            a = tache("A", type=type_)
            c, m, agent, _ = monter([a], profil)
            m.executer()
            assert a.etat == "verifie"
            if type_ == "delicate":
                assert [v["modele"] for v in agent.verifs] == ["fable"]


def test_aucune_retouche_sans_releve_ecrit_dans_le_meme_depart():
    """Toutes les suites de quatre verdicts parmi local, bâclé, fond faux et accord."""
    fond = verdict(motif="ne_sait_pas", resume="La démarche est fausse.")
    choix = {"L": LOCAL, "B": BACLE, "F": fond, "A": ACCORD}
    for suite in itertools.product("LBFA", repeat=4):
        a = tache("A", type="courante")
        c, m, agent, _ = monter([a], PROFIL, textes={"A": [choix[x] for x in suite] + [ACCORD]})
        m.executer()
        for rang, v in enumerate(agent.verifs):
            retouche = "Ce que la retouche a touché" in v["consigne"]
            assert retouche == bool(v["releve"]), (suite, rang)
            if retouche:
                assert suite[rang - 1] in "LB", (suite, rang)
        assert a.releve == "" or a.etat != "verifie"


def test_le_verificateur_borne_travaille_dans_la_copie_jetable(tmp_path):
    class AvecCopie(Controles):
        def preparer(self, t):
            super().preparer(t)
            return tmp_path

        def copie_de_verification(self, t, dossier):
            return tmp_path / "copie"

        def jeter_copie(self, *arguments):
            return None

    a = tache("A", type="courante")
    c = chantier([a])
    vus = []

    class Note(Agent):
        def executer(self, consigne, modele, effort, dossier, lecture_seule=False, contexte=None,
                     copie_jetable=False, reprendre=None):  # fmt: skip
            if (contexte or {}).get("role") == "verificateur":
                vus.append((dossier, copie_jetable))
            return super().executer(consigne, modele, effort, None, lecture_seule, contexte,
                                    copie_jetable, reprendre)  # fmt: skip

    agent = Note(c, textes={"A": [LOCAL, ACCORD]})
    Moteur(c, agent, AvecCopie(), PROFIL).executer()
    assert vus == [(tmp_path / "copie", True)] * 2
    assert agent.verifs[0]["consigne"] == consigne_verificateur_bornee(
        a, c.contrat, PROFIL, SORTIE, copie_jetable=True, verdict_complet=True
    )
