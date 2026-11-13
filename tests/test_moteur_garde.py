"""Le travail refusé est gardé (fiche M8) : la copie de la tâche reste, le tour suivant la reprend.

Chaque test mène le moteur sur un vrai dépôt git rangé dans `tmp_path`, avec les vrais contrôles
(`ControlesGit`) et l'agent simulé. L'ouvrier de ces tests ajoute une ligne à `a_passes.txt` à
chaque passage, avant de jouer son scénario : on lit ainsi, dans le dossier de chaque ouvrier et
dans la branche principale à la fin, quel travail a été gardé. Aucun test n'attend une durée : les
attentes portent sur un état (le fil, une phase, la fin du moteur).
"""

import json
import shutil
import subprocess
import threading
import time
from pathlib import Path

import pytest

from atelier import moteur as module
from atelier.agents import AgentSimule, Resultat
from atelier.consignes import SUR_PLACE
from atelier.controles import ControlesGit
from atelier.guichet import ARRETE
from atelier.modele import Chantier, Contrat, Tache
from atelier.moteur import ABANDONNER, MOTIF_ARRET, PHASES, RELANCER_TEL, Moteur
from atelier.serveur import Atelier

T0 = 1_800_000_000.0  # une fausse heure Unix, pour les suspensions
PASSES = "a_passes.txt"
REPART_PROPRE = "Tu repars d'un état propre."


def git(dossier, *arguments):
    return subprocess.run(
        ["git", *arguments], cwd=dossier, check=True, capture_output=True, text=True
    ).stdout


@pytest.fixture
def depot(tmp_path):
    racine = tmp_path / "projet"
    racine.mkdir()
    git(racine, "init", "-q", "-b", "main")
    git(racine, "config", "user.name", "Essai")
    git(racine, "config", "user.email", "essai@example.invalid")
    (racine / "LISEZMOI.md").write_text("socle\n", "utf-8")
    git(racine, "add", "-A")
    git(racine, "commit", "-q", "-m", "socle")
    return racine


def tache(**champs):
    reglages = {"titre": "Tâche A", "type": "mecanique", "criteres": ["Ça marche."]}
    return Tache(id="A", **{"perimetre": ["a.py", "a_*"], **reglages, **champs})


def chantier(taches, **contrat):
    reglages = {"objectif": "Essai", "valide": True, **contrat}
    return Chantier(projet="essai", contrat=Contrat(**reglages), taches=taches)


class Ouvrier(AgentSimule):
    """L'agent simulé, dont chaque ouvrier (reprise à chaud comprise) ajoute d'abord une ligne à
    `a_passes.txt`, puis joue son scénario. Il note, pour chaque passage : la tentative, le
    dossier, ce qu'il y trouve, sa consigne, s'il reprend une session, et la copie que l'état de
    la tâche nomme à ce moment. `en_trop` : un fichier hors périmètre écrit au passage de ce rang.
    """

    def __init__(self, scenario=None, chantier=None, en_trop=None, **champs):
        super().__init__(scenario or {}, perimetres={"A": ["a.py", "a_*"]}, **champs)
        self.chantier, self.en_trop, self.passages = chantier, en_trop or {}, []
        self.pendant_l_ouvrier = None  # appelé au début de chaque passage d'ouvrier

    def executer(self, consigne, modele, effort, dossier, lecture_seule=False, contexte=None,
                 copie_jetable=False, reprendre=None):  # fmt: skip
        if contexte.get("role") == "ouvrier":
            self._passer(consigne, Path(dossier), contexte, reprendre)
        return super().executer(consigne, modele, effort, dossier, lecture_seule, contexte,
                                copie_jetable, reprendre)  # fmt: skip

    def _passer(self, consigne, dossier, contexte, reprendre):
        fichier = dossier / PASSES
        trouve = fichier.read_text("utf-8") if fichier.exists() else ""
        copie = self.chantier.tache("A").copie if self.chantier else None
        self.passages.append({"tentative": contexte["tentative"], "dossier": dossier,
                              "trouve": trouve, "consigne": consigne, "copie": copie,
                              "reprise": reprendre is not None})  # fmt: skip
        fichier.write_text(f"{trouve}passe {len(self.passages)}\n", "utf-8")
        if len(self.passages) in self.en_trop:
            (dossier / self.en_trop[len(self.passages)]).write_text("interdit\n", "utf-8")
        if self.pendant_l_ouvrier is not None:
            self.pendant_l_ouvrier(len(self.passages))

    def departs(self):
        """Les passages des départs neufs, sans les reprises à chaud."""
        return [p for p in self.passages if not p["reprise"]]


class Controles(ControlesGit):
    """Les vrais contrôles, qui notent chaque copie préparée, jetée ou contrôlée."""

    def __init__(self, depot, commandes=None, partages=None):
        super().__init__(depot, commandes=commandes, partages=partages)
        self.preparees, self.annulees, self.mecaniques_vues = [], [], 0
        self.perimetres_vus = []

    def preparer(self, t):
        self.preparees.append(t.id)
        return super().preparer(t)

    def annuler(self, t, dossier):
        self.annulees.append(Path(dossier) if dossier else None)
        return super().annuler(t, dossier)

    def fichiers_modifies(self, t, dossier, resultat):
        vus = super().fichiers_modifies(t, dossier, resultat)
        self.perimetres_vus.append(sorted(vus))
        return vus

    def mecaniques(self, t, dossier):
        self.mecaniques_vues += 1
        return super().mecaniques(t, dossier)


# Le profil qui coupe les sous-tâches : après un refus des contrôles, l'ouvrier suivant reprend
# toute la mission sur la copie gardée. Les sous-tâches ont leurs tests à part
# (`test_moteur_sous_tache`).
SANS_SOUS_TACHE = {"sous_taches": 0}


def mener(depot, scenario=None, commandes=None, taches=None, en_trop=None, profil=None,
          **contrat):  # fmt: skip
    c = chantier(taches or [tache()], **contrat)
    agent = Ouvrier(scenario, chantier=c, en_trop=en_trop)
    controles = Controles(depot, commandes)
    return c, Moteur(c, agent, controles, profil), agent, controles


def fil(c):
    return [e["texte"] for e in c.evenements]


def copies_sur_le_disque(depot):
    """Les copies de tâche restées sur le disque, et celles que git connaît encore."""
    arbres = depot / ".atelier" / "arbres"
    dossiers = sorted(p.name for p in arbres.iterdir()) if arbres.exists() else []
    connues = git(depot, "worktree", "list", "--porcelain").count("worktree ") - 1
    return dossiers, connues


def assert_aucune_copie(depot, a):
    assert a.copie == ""
    assert copies_sur_le_disque(depot) == ([], 0)


def lignes_dans_la_principale(depot):
    return (depot / PASSES).read_text("utf-8").splitlines()


# Une commande de contrôle qui ne passe qu'au troisième passage d'ouvrier gardé dans la copie.
TROIS_PASSES = f'n=$(grep -c passe {PASSES}); echo "lignes : $n"; test "$n" -ge 3'


# --- après un refus, le second départ reprend la même copie ----------------------------------


def test_apres_des_controles_rouges_le_second_depart_reprend_la_meme_copie(depot):
    c, m, agent, controles = mener(depot, commandes=[TROIS_PASSES], profil=SANS_SOUS_TACHE)
    m.executer()
    a = c.tache("A")
    assert a.etat == "verifie" and a.tentatives == 2
    premier, second = agent.departs()
    assert second["tentative"] == 2 and second["dossier"] == premier["dossier"]
    assert second["trouve"] == "passe 1\npasse 2\n"  # le départ et sa reprise sont encore là
    assert controles.preparees == ["A"]  # la copie n'a pas été préparée deux fois
    assert SUR_PLACE in second["consigne"] and REPART_PROPRE not in second["consigne"]
    assert "Les contrôles automatiques échouent" in second["consigne"]  # les remarques du refus
    assert SUR_PLACE not in premier["consigne"]
    # Les contrôles ont jugé la copie entière : ils ne passent qu'avec le travail gardé.
    assert [e["origine"] for e in a.historique] == ["controles", "controles", ""]
    assert lignes_dans_la_principale(depot) == ["passe 1", "passe 2", "passe 3"]
    assert any("resté dans sa copie" in t for t in fil(c))
    assert controles.annulees == []  # entrée dans la branche : retirée par l'enregistrement
    assert_aucune_copie(depot, a)


def test_apres_un_refus_du_verificateur_le_second_depart_reprend_la_meme_copie(depot):
    c, m, agent, controles = mener(depot, {"A": ["bacle", "ok"]})
    m.executer()
    a = c.tache("A")
    assert a.etat == "verifie" and a.tentatives == 2
    premier, second = agent.departs()
    assert second["dossier"] == premier["dossier"] and second["trouve"] == "passe 1\npasse 2\n"
    assert controles.preparees == ["A"]
    assert SUR_PLACE in second["consigne"]
    assert '"motif": "bacle"' in second["consigne"]  # le verdict entier
    assert lignes_dans_la_principale(depot) == ["passe 1", "passe 2", "passe 3"]
    assert_aucune_copie(depot, a)


def test_apres_un_echec_de_l_agent_le_second_depart_reprend_la_meme_copie(depot):
    c, m, agent, controles = mener(depot, {"A": ["erreur", "ok"]})
    m.executer()
    a = c.tache("A")
    assert a.etat == "verifie" and a.tentatives == 2
    assert [e["origine"] for e in a.historique] == ["agent", ""]
    premier, second = agent.departs()
    assert second["dossier"] == premier["dossier"] and second["trouve"] == "passe 1\n"
    assert controles.preparees == ["A"] and SUR_PLACE in second["consigne"]
    assert "L'agent s'est arrêté sur une erreur" in second["consigne"]
    assert lignes_dans_la_principale(depot) == ["passe 1", "passe 2"]
    assert_aucune_copie(depot, a)


class Heure:
    """Une fausse heure Unix qui avance d'un pas à chaque lecture : la suspension finit seule."""

    def __init__(self, pas):
        self.t, self.pas = T0, pas

    def __call__(self):
        self.t += self.pas
        return self.t


def test_apres_une_suspension_le_meme_depart_reprend_la_copie(depot, monkeypatch):
    monkeypatch.setattr(module, "PAS_VEILLE_S", 0.01)  # la fausse heure se relit souvent
    c = chantier([tache()])
    agent = Ouvrier(chantier=c, limites={"A": ["refus"]}, delai_limite_s=None)
    controles = Controles(depot)
    m = Moteur(c, agent, controles, heure=Heure(pas=60.0))
    m.executer()
    a = c.tache("A")
    assert a.etat == "verifie" and a.tentatives == 1  # la suspension ne compte pas
    refuse, repart = agent.passages
    assert refuse["tentative"] == repart["tentative"] == 1
    assert repart["dossier"] == refuse["dossier"] and repart["trouve"] == "passe 1\n"
    assert controles.preparees == ["A"] and SUR_PLACE in repart["consigne"]
    assert lignes_dans_la_principale(depot) == ["passe 1", "passe 2"]
    assert_aucune_copie(depot, a)


# --- la copie est jetée : débord, arrêt par la personne, abandon ------------------------------


def copie_a_chaque_decision(m):
    """Note la copie que nomme l'état de A quand le fil dit la suite décidée après un refus."""
    vues = []

    def entendre():
        dernier = m.chantier.evenements[-1]["texte"] if m.chantier.evenements else ""
        if "Seconde chance" in dernier or "monte d'un cran" in dernier:
            vues.append(m.chantier.tache("A").copie)

    m.sur_changement = entendre
    return vues


def test_apres_un_debord_la_copie_est_jetee_et_le_depart_suivant_repart_propre(depot):
    c, m, agent, controles = mener(depot, {"A": ["deborde", "ok"]})
    decisions = copie_a_chaque_decision(m)
    m.executer()
    assert decisions == [""]  # jetée dès le refus, avant la décision de la suite
    a = c.tache("A")
    assert a.etat == "verifie" and a.tentatives == 2
    assert [e["origine"] for e in a.historique] == ["perimetre", "perimetre", ""]
    premier, second = agent.departs()
    assert premier["copie"] == str(premier["dossier"])  # elle était bien retenue
    assert controles.annulees == [premier["dossier"]]
    assert controles.preparees == ["A", "A"]
    assert second["trouve"] == "" and SUR_PLACE not in second["consigne"]
    assert REPART_PROPRE in second["consigne"]
    assert not (depot / "hors_perimetre.txt").exists()
    assert lignes_dans_la_principale(depot) == ["passe 3"]
    assert_aucune_copie(depot, a)


def test_une_erreur_d_agent_qui_laisse_un_fichier_hors_perimetre_ne_garde_pas_la_copie(depot):
    c, m, agent, controles = mener(depot, {"A": ["erreur", "ok"]}, en_trop={1: "secret.txt"})
    decisions = copie_a_chaque_decision(m)
    m.executer()
    assert decisions == [""]  # jetée dès l'erreur, avant la seconde chance
    a = c.tache("A")
    assert a.etat == "verifie"
    premier, second = agent.departs()
    assert controles.annulees == [premier["dossier"]] and controles.preparees == ["A", "A"]
    assert second["trouve"] == "" and SUR_PLACE not in second["consigne"]
    assert any("hors périmètre (secret.txt) : je la jette" in t for t in fil(c))
    assert not (depot / "secret.txt").exists()
    assert_aucune_copie(depot, a)


@pytest.mark.parametrize("moment", ["avant_le_depart", "preparation", "pendant_l_ouvrier"])
def test_un_arret_par_la_personne_jette_la_copie_gardee(depot, moment):
    c = chantier([tache()])
    agent = Ouvrier({"A": ["bacle", "ok"]}, chantier=c)
    controles = Controles(depot)
    arrets = []
    signal = {"avant_le_depart": "Je monte d'un cran", "preparation": "resté dans sa copie"}

    def entendre():  # l'arrêt tombe au moment voulu, lu dans le fil
        dernier = c.evenements[-1]["texte"] if c.evenements else ""
        if not arrets and moment in signal and signal[moment] in dernier:
            arrets.append((c.tache("A").copie, m.arreter("A")))

    def pendant(rang):  # le second départ de l'ouvrier vient de commencer
        if moment == "pendant_l_ouvrier" and rang == 3:
            arrets.append((c.tache("A").copie, m.arreter("A")))

    agent.pendant_l_ouvrier = pendant
    m = Moteur(c, agent, controles, sur_changement=entendre)
    m.executer()
    a = c.tache("A")
    assert arrets == [(str(agent.passages[0]["dossier"]), True)]  # gardée jusqu'à l'arrêt
    assert a.etat == "revenu" and c.demandes[-1]["question"].endswith(MOTIF_ARRET)
    assert "Travail gardé" not in c.demandes[-1]["question"]
    assert controles.annulees == [agent.passages[0]["dossier"]]
    assert_aucune_copie(depot, a)


def rendre_avec_le_travail_garde(depot):
    """Mène A jusqu'à ce qu'elle revienne à la personne, son travail gardé : au plafond, avec une
    seule tentative, un refus du vérificateur ne peut ni monter ni relancer seul."""
    c, m, agent, controles = mener(
        depot, {"A": ["bacle", "ok"]}, max_tentatives=1, plafond_modele="sonnet",
        plafond_effort="low",
    )  # fmt: skip
    m.executer()
    return c, m, agent, controles


def test_une_tache_rendue_dit_travail_garde_et_ou_puis_sa_relance_reprend_la_copie(depot):
    c, m, agent, controles = rendre_avec_le_travail_garde(depot)
    a = c.tache("A")
    copie = agent.passages[0]["dossier"]
    assert a.etat == "revenu" and a.copie == str(copie)
    assert (copie / PASSES).read_text("utf-8") == "passe 1\npasse 2\n"  # resté sur le disque
    (demande,) = c.demandes
    assert f"Travail gardé dans sa copie de travail ({copie})" in demande["question"]
    m.repondre(demande["id"], RELANCER_TEL)
    m.executer()
    assert a.etat == "verifie"
    relance = agent.departs()[-1]
    assert relance["dossier"] == copie and relance["trouve"] == "passe 1\npasse 2\n"
    assert SUR_PLACE in relance["consigne"]
    assert '"motif": "bacle"' in relance["consigne"]  # le verdict du dernier refus
    assert controles.preparees == ["A"] and controles.annulees == []
    assert lignes_dans_la_principale(depot) == ["passe 1", "passe 2", "passe 3"]
    assert_aucune_copie(depot, a)


def test_une_tache_rendue_puis_abandonnee_jette_sa_copie(depot):
    c, m, agent, controles = rendre_avec_le_travail_garde(depot)
    a = c.tache("A")
    copie = agent.passages[0]["dossier"]
    assert "Travail gardé" in c.demandes[-1]["question"] and copie.exists()
    m.repondre(c.demandes[-1]["id"], ABANDONNER)
    assert a.etat == "abandonnee" and controles.annulees == [copie]
    assert_aucune_copie(depot, a)


def test_une_copie_disparue_fait_partir_proprement_dans_une_copie_neuve(depot):
    c, m, agent, controles = rendre_avec_le_travail_garde(depot)
    a = c.tache("A")
    copie = agent.passages[0]["dossier"]
    shutil.rmtree(copie)  # effacée à la main : git la croit encore là
    m.repondre(c.demandes[-1]["id"], RELANCER_TEL)
    m.executer()
    assert a.etat == "verifie" and controles.preparees == ["A", "A"]
    relance = agent.departs()[-1]
    assert relance["trouve"] == "" and SUR_PLACE not in relance["consigne"]
    phrases = [t for t in fil(c) if "n'existe plus" in t]
    assert phrases == [f"La copie gardée pour cette tâche n'existe plus ({copie}) : l'ouvrier "
                       "repart d'une copie neuve."]  # fmt: skip
    assert lignes_dans_la_principale(depot) == ["passe 3"]
    assert_aucune_copie(depot, a)


# --- arrêtée pendant sa vérification : rejugée sans ouvrier ----------------------------------


def interrompue_en_verification(depot, controles, pendant="verification", fichiers=None):
    """Une tâche qu'un arrêt de l'Atelier a coupée, telle que la reprise après un arrêt la rend :
    « à lancer », son numéro gardé, une entrée `interrompue`, et sa copie avec le travail."""
    t = tache(etat="a_lancer", tentatives=1)
    copie = controles.preparer(t)
    for nom, texte in (fichiers or {PASSES: "passe 0\n", "a.py": "# fait\n"}).items():
        (copie / nom).write_text(texte, "utf-8")
    entree = {"tentative": 1, "modele": t.modele, "effort": t.effort, "issue": "interrompue",
              "detail": "Interrompue par un arrêt de l'Atelier."}  # fmt: skip
    if pendant:
        entree["pendant"] = pendant
    t.historique.append(entree)
    t.copie = str(copie)
    controles.preparees.clear()
    return t, copie


def test_interrompue_en_verification_avec_sa_copie_seul_le_jugement_est_refait(depot):
    controles = Controles(depot, commandes=[f"grep -q 'passe 0' {PASSES}"])
    t, copie = interrompue_en_verification(depot, controles)
    c = chantier([t])
    agent = Ouvrier(chantier=c)
    Moteur(c, agent, controles).executer()
    assert t.etat == "verifie" and t.tentatives == 1  # son numéro, gardé
    assert [x["role"] for x in agent.appels] == ["verificateur"]  # aucun ouvrier
    assert c.agents_lances == 1 and controles.preparees == []
    assert controles.perimetres_vus == [["a.py", PASSES]] and controles.mecaniques_vues >= 1
    assert [(e["tentative"], e["issue"]) for e in t.historique] == [(1, "interrompue"),
                                                                    (1, "valide")]  # fmt: skip
    assert any("s'était arrêté pendant la vérification" in x for x in fil(c))
    assert lignes_dans_la_principale(depot) == ["passe 0"]
    assert_aucune_copie(depot, t)


def test_rejugee_et_refusee_la_copie_reste_pour_l_ouvrier_suivant(depot):
    controles = Controles(depot, commandes=[TROIS_PASSES])
    t, copie = interrompue_en_verification(depot, controles)
    c = chantier([t])
    agent = Ouvrier(chantier=c)
    Moteur(c, agent, controles, SANS_SOUS_TACHE).executer()
    assert t.etat == "verifie"
    assert [x["role"] for x in agent.appels][0] == "ouvrier"  # le refus des contrôles, d'abord
    premier = agent.passages[0]
    assert premier["dossier"] == copie and premier["trouve"] == "passe 0\n"
    assert SUR_PLACE in premier["consigne"] and "lignes : 1" in premier["consigne"]
    assert t.historique[1]["origine"] == "controles" and t.historique[1]["tentative"] == 1
    assert controles.preparees == []
    assert_aucune_copie(depot, t)


def test_rejugee_une_copie_qui_deborde_est_refusee_et_jetee(depot):
    controles = Controles(depot)
    t, copie = interrompue_en_verification(depot, controles, fichiers={"secret.txt": "x\n"})
    c = chantier([t])
    agent = Ouvrier(chantier=c)
    Moteur(c, agent, controles).executer()
    assert t.historique[1]["origine"] == "perimetre"  # le périmètre jugé sur la copie gardée
    assert copie in controles.annulees
    assert not (depot / "secret.txt").exists() and t.etat == "verifie"
    assert_aucune_copie(depot, t)


def test_interrompue_en_verification_sans_sa_copie_un_ouvrier_part_dans_une_neuve(depot):
    controles = Controles(depot)
    t, copie = interrompue_en_verification(depot, controles)
    shutil.rmtree(copie)
    c = chantier([t])
    agent = Ouvrier(chantier=c)
    Moteur(c, agent, controles).executer()
    assert [x["role"] for x in agent.appels] == ["ouvrier", "verificateur"]
    assert controles.preparees == ["A"] and agent.passages[0]["trouve"] == ""
    assert sum("n'existe plus" in x for x in fil(c)) == 1
    assert not any("s'était arrêté pendant la vérification" in x for x in fil(c))
    assert t.etat == "verifie" and lignes_dans_la_principale(depot) == ["passe 1"]  # neuve
    assert_aucune_copie(depot, t)


def test_interrompue_en_cours_avec_sa_copie_l_ouvrier_la_reprend_sur_place(depot):
    controles = Controles(depot)
    t, copie = interrompue_en_verification(depot, controles, pendant="")
    c = chantier([t])
    agent = Ouvrier(chantier=c)
    Moteur(c, agent, controles).executer()
    assert [x["role"] for x in agent.appels] == ["ouvrier", "verificateur"]
    assert agent.passages[0]["dossier"] == copie and agent.passages[0]["trouve"] == "passe 0\n"
    assert SUR_PLACE in agent.passages[0]["consigne"] and controles.preparees == []
    assert lignes_dans_la_principale(depot) == ["passe 0", "passe 1"]
    assert_aucune_copie(depot, t)


def test_interrompue_en_cours_une_copie_qui_deborde_n_est_pas_reprise(depot):
    controles = Controles(depot)
    fichiers = {PASSES: "passe 0\n", "secret.txt": "interdit\n"}
    t, copie = interrompue_en_verification(depot, controles, pendant="", fichiers=fichiers)
    c = chantier([t])
    agent = Ouvrier(chantier=c)
    Moteur(c, agent, controles).executer()
    assert controles.annulees[0] == copie and controles.preparees == ["A"]
    assert agent.passages[0]["trouve"] == "" and SUR_PLACE not in agent.passages[0]["consigne"]
    assert any("hors périmètre (secret.txt) : je la jette" in x for x in fil(c))
    assert t.etat == "verifie" and not (depot / "secret.txt").exists()
    assert_aucune_copie(depot, t)


# --- l'état sauvé avant le départ -------------------------------------------------------------


def test_la_copie_est_dans_l_etat_sauve_avant_le_depart_de_l_ouvrier(depot, tmp_path):
    etat = tmp_path / "etat.json"
    c = chantier([tache()])
    agent = Ouvrier({"A": ["bacle", "ok"]}, chantier=c)
    lus = []

    def couper(rang):  # une coupure juste après le départ : seul compte ce qui est sur le disque
        dossier = agent.passages[-1]["dossier"]
        lus.append((Chantier.charger(etat).tache("A").copie, str(dossier), dossier.exists()))

    agent.pendant_l_ouvrier = couper
    m = Moteur(c, agent, Controles(depot), sur_changement=lambda: c.sauver(etat))
    m.executer()
    assert len(lus) == 3  # le départ, sa reprise à chaud, le second départ
    assert all(copie == dossier and existe for copie, dossier, existe in lus)
    assert Chantier.charger(etat).tache("A").copie == ""  # entrée : plus rien n'est gardé


def test_relue_apres_une_coupure_la_copie_sauvee_est_reprise(depot, tmp_path):
    """L'Atelier coupé pendant l'ouvrier : l'état relu nomme la copie, qui est reprise."""
    etat = tmp_path / "etat.json"
    c = chantier([tache()])
    agent = Ouvrier(chantier=c)
    gele = threading.Event()

    def couper(rang):
        if rang == 1:
            shutil.copyfile(etat, tmp_path / "coupure.json")  # l'état au moment de la coupure
            gele.set()

    agent.pendant_l_ouvrier = couper
    Moteur(c, agent, Controles(depot), sur_changement=lambda: c.sauver(etat)).executer()
    assert gele.is_set()
    # Le travail gardé de ce premier passage est remis en place, comme si rien n'était entré.
    git(depot, "reset", "-q", "--hard", "HEAD~1")
    relu = Chantier.charger(tmp_path / "coupure.json")
    copie = Path(relu.tache("A").copie)
    controles = Controles(depot)
    controles._git("worktree", "add", "-q", "-B", "tache/A", str(copie), "HEAD")
    (copie / PASSES).write_text("passe 1\n", "utf-8")
    m = Moteur(relu, Ouvrier(chantier=relu), controles)
    a = relu.tache("A")
    if a.etat == "revenu":  # rendue à la personne au chargement, selon la règle de reprise
        m.repondre(relu.demandes[-1]["id"], RELANCER_TEL)
    m.executer()
    assert a.etat == "verifie" and controles.preparees == []
    assert m.agent.passages[0]["trouve"] == "passe 1\n"
    assert_aucune_copie(depot, a)


# --- aucune copie ne reste pour une tâche finie ----------------------------------------------


@pytest.mark.parametrize(
    "scenario, commandes, sur_place",
    [
        ({"A": ["bacle", "ok"]}, None, True),
        ({"A": ["erreur", "ok"]}, None, True),
        ({}, [TROIS_PASSES], True),
        ({"A": ["deborde", "ok"]}, None, False),
        ({"A": ["ne_sait_pas", "bacle", "ok"]}, None, True),
    ],
)
def test_aucune_copie_ne_reste_apres_une_tache_verifiee(depot, scenario, commandes, sur_place):
    c, m, agent, controles = mener(depot, scenario, commandes, profil=SANS_SOUS_TACHE)
    m.executer()
    a = c.tache("A")
    assert a.etat == "verifie"
    assert all(p["copie"] == str(p["dossier"]) for p in agent.passages)  # retenue à chaque départ
    assert (SUR_PLACE in agent.departs()[-1]["consigne"]) is sur_place
    assert_aucune_copie(depot, a)


def test_jeter_les_copies_gardees_vide_le_disque_des_taches_rendues(depot):
    c, m, agent, controles = rendre_avec_le_travail_garde(depot)
    a = c.tache("A")
    copie = agent.passages[0]["dossier"]
    assert copie.exists()
    assert m.jeter_les_copies_gardees() == ["A"]
    assert controles.annulees == [copie] and a.etat == "revenu"
    assert_aucune_copie(depot, a)
    assert m.jeter_les_copies_gardees() == []


# --- reprise après vérification (M8, seconde passe) -------------------------------------------


def attendre_que(condition, delai=30.0):
    """Attend un état, au plus `delai` secondes (garde-fou : le test échoue, il ne pend pas)."""
    limite = time.monotonic() + delai
    while time.monotonic() < limite:
        if condition():
            return True
        time.sleep(0.005)
    return condition()


class AgentScript:
    """Un agent à script, repris de l'essai du vérificateur : `ouvrier(p)` reçoit un dict
    (dossier, rang, reprendre) et peut rendre un Resultat ; `verif(p)` rend True, False ou un
    Resultat."""

    def __init__(self, ouvrier=None, verif=None):
        self.ouvrier, self.verif = ouvrier, verif
        self.passages, self.verifs, self.appels = [], [], []

    def arreter(self, tache=None):
        return False

    def executer(self, consigne, modele, effort, dossier, lecture_seule=False, contexte=None,
                 copie_jetable=False, reprendre=None):  # fmt: skip
        role = (contexte or {}).get("role")
        self.appels.append(role)
        if role == "ouvrier":
            p = {"dossier": Path(dossier), "rang": len(self.passages) + 1, "reprendre": reprendre}
            self.passages.append(p)
            rendu = self.ouvrier(p) if self.ouvrier else None
            return rendu or Resultat(ok=True, texte="Compte rendu.", session="s-1")
        self.verifs.append({"rang": len(self.verifs) + 1})
        ok = self.verif(self.verifs[-1]) if self.verif else True
        if isinstance(ok, Resultat):
            return ok
        verdict = {"valide": bool(ok), "motif": "bacle", "resume": "bon" if ok else "à revoir"}
        return Resultat(ok=True, texte=json.dumps(verdict))


JOURNAL = "JOURNAL.md"
PROFIL_JOURNAL = {"fichiers_partages": [{"motif": JOURNAL, "fusion": "git"}]}
A_OK = ["test -f a_ok.txt"]


def depot_au_journal(depot):
    (depot / JOURNAL).write_text("début\n", "utf-8")
    git(depot, "add", "-A")
    git(depot, "commit", "-q", "-m", "journal")
    return depot


def moteur_au_journal(depot, agent, etat, chantier_=None):
    c = chantier_ or chantier([tache(perimetre=["a_*", JOURNAL])], max_tentatives=4)
    controles = Controles(depot, A_OK, partages={JOURNAL: "git"})
    m = Moteur(c, agent, controles, profil=PROFIL_JOURNAL, sur_changement=lambda: c.sauver(etat))
    return c, m, controles


def conflit_puis_coupure(depot, etat, coupe, fige, couper_en_verification):
    """A écrit le journal ; une autre tâche entre et touche la même ligne pendant sa
    vérification ; l'enregistrement pose les marqueurs et rend la main à l'ouvrier, dont la
    reprise ne les résout pas et casse les contrôles : la copie est gardée, marqueurs compris.
    L'Atelier est ensuite coupé au départ suivant de l'ouvrier, ou pendant la vérification qui
    suit. Rend le chantier, l'agent et le fil du moteur coupé."""

    def ouvrier(p):
        d = p["dossier"]
        if p["rang"] == 1:
            (d / JOURNAL).write_text("début\nligne de A\n", "utf-8")
            (d / "a_ok.txt").write_text("ok\n", "utf-8")
        elif p["reprendre"] is not None:  # conflit laissé, contrôles cassés
            (d / "a_ok.txt").unlink(missing_ok=True)
        elif couper_en_verification:
            (d / "a_ok.txt").write_text("ok\n", "utf-8")  # contrôles réparés, conflit laissé
        else:  # coupé ici, au départ suivant sur la copie gardée
            coupe.set()
            fige.wait()
            return Resultat(ok=False, erreur=ARRETE)  # relâché après la fin : il ne fait rien

    def verif(p):
        if p["rang"] == 1:
            (depot / JOURNAL).write_text("début\nligne de B\n", "utf-8")
            git(depot, "commit", "-q", "-am", "B : une autre tâche est entrée")
            return True
        coupe.set()  # coupé pendant cette vérification
        fige.wait()
        return Resultat(ok=False, erreur=ARRETE)  # relâché après la fin : il ne fait rien

    agent = AgentScript(ouvrier, verif)
    c, m, _ = moteur_au_journal(depot, agent, etat)
    fil_coupe = threading.Thread(target=m.executer, daemon=True)
    fil_coupe.start()
    assert coupe.wait(30)
    return c, agent, fil_coupe


@pytest.mark.parametrize("en_verification", [False, True])
def test_apres_un_redemarrage_les_marqueurs_de_conflit_n_entrent_pas(depot, en_verification):
    depot_au_journal(depot)
    etat, coupe, fige = depot.parent / "etat.json", threading.Event(), threading.Event()
    c, agent, fil_coupe = conflit_puis_coupure(depot, etat, coupe, fige, en_verification)
    try:
        copie = agent.passages[-1]["dossier"]
        assert "<<<<<<< " in (copie / JOURNAL).read_text("utf-8")
        relu = Chantier.charger(etat)  # tout est relu du disque : rien de l'ancienne mémoire
        a = relu.tache("A")
        assert a.copie == str(copie)
        if en_verification:  # la règle de M7, émulée : à lancer, numéro gardé, `interrompue`
            assert a.etat == "en_verification"
            a.etat = "a_lancer"
            a.historique.append({"tentative": a.tentatives, "modele": a.modele,
                                 "effort": a.effort, "issue": "interrompue", "detail": "arrêt",
                                 "pendant": "verification"})  # fmt: skip

        def repare(p):  # répare les contrôles, jamais le conflit
            (p["dossier"] / "a_ok.txt").write_text("ok\n", "utf-8")

        agent2 = AgentScript(repare, lambda p: True)  # un vérificateur distrait
        _, m2, _ = moteur_au_journal(depot, agent2, depot.parent / "etat2.json", relu)
        if a.etat == "revenu":  # rendue au chargement, selon la règle de reprise de la base
            m2.repondre(relu.demandes[-1]["id"], RELANCER_TEL)
        m2.executer()
    finally:
        fige.set()  # le fil coupé se termine sans rien faire de plus
        fil_coupe.join(10)
    assert "<<<<<<< " not in git(depot, "show", f"HEAD:{JOURNAL}")
    assert any("Des marqueurs de conflit restent" in t for t in fil(relu))
    if en_verification:
        assert agent2.appels[0] == "verificateur"  # rejugée d'abord, sans ouvrier


def test_rendue_jamais_repondue_puis_nouveau_chantier_la_copie_ne_reste_pas(depot):
    c, m, agent, controles = rendre_avec_le_travail_garde(depot)
    atelier = Atelier(depot, c, agent, controles, {})
    assert c.tache("A").etat == "revenu" and copies_sur_le_disque(depot)[0] == ["A"]
    rendu = atelier.nouveau_chantier("ancien")
    assert rendu["fait"], rendu
    assert copies_sur_le_disque(depot) == ([], 0)


def test_l_abandon_d_une_copie_abimee_jette_quand_meme_son_dossier(depot):
    c, m, agent, controles = rendre_avec_le_travail_garde(depot)
    copie = Path(c.tache("A").copie)
    (copie / ".git").unlink()  # git ne la reconnaît plus, mais son dossier est là
    m.repondre(c.demandes[-1]["id"], ABANDONNER)
    assert c.tache("A").copie == "" and not copie.exists()
    assert copies_sur_le_disque(depot) == ([], 0)


def test_une_tache_ne_reprend_ni_ne_jette_la_copie_d_une_autre(depot):
    c, m, agent, controles = rendre_avec_le_travail_garde(depot)  # A rendue, travail gardé
    copie_a = Path(c.tache("A").copie)
    relu = Chantier.depuis_dict(c.en_dict())  # un état écrit ailleurs : B nomme la copie de A
    relu.taches.append(Tache("B", "Tâche B", type="mecanique", perimetre=["b.py", PASSES],
                             copie=str(copie_a)))  # fmt: skip
    agent2 = Ouvrier(chantier=relu)
    agent2.perimetres = {"B": ["b.py"]}
    controles2 = Controles(depot)
    Moteur(relu, agent2, controles2).executer()
    b = relu.tache("B")
    assert b.etat == "verifie" and controles2.preparees == ["B"]
    assert all(p["dossier"] != copie_a for p in agent2.passages)
    assert (copie_a / PASSES).read_text("utf-8") == "passe 1\npasse 2\n"  # intact
    assert relu.tache("A").copie == str(copie_a)
    phrases = [t for t in fil(relu) if "n'est pas la sienne" in t]
    assert phrases == [f"La copie nommée pour cette tâche ({copie_a}) n'est pas la sienne : je "
                       "n'y touche pas, et l'ouvrier repart d'une copie neuve."]  # fmt: skip


def test_apres_une_suspension_une_copie_qui_deborde_est_jetee_pendant_la_pause(depot, monkeypatch):
    monkeypatch.setattr(module, "PAS_VEILLE_S", 0.01)
    c = chantier([tache()])
    heure = Heure(pas=0.0)
    agent = Ouvrier(chantier=c, en_trop={1: "secret.txt"}, limites={"A": ["refus"]},
                    delai_limite_s=None)  # fmt: skip
    controles = Controles(depot)
    m = Moteur(c, agent, controles, heure=heure)
    fil_moteur = threading.Thread(target=m.executer, daemon=True)
    fil_moteur.start()
    pause = PHASES["pause"].split("{")[0]
    assert attendre_que(lambda: (m.phase("A") or {}).get("texte", "").startswith(pause))
    with m.verrou:  # pendant la pause : la copie qui déborde est déjà jetée
        assert c.tache("A").copie == "" and controles.annulees == [agent.passages[0]["dossier"]]
    heure.t += 10_000  # la suspension est finie
    fil_moteur.join(30)
    assert not fil_moteur.is_alive() and c.tache("A").etat == "verifie"
    assert agent.passages[1]["trouve"] == "" and not (depot / "secret.txt").exists()
    assert_aucune_copie(depot, c.tache("A"))


def test_le_perimetre_du_second_tour_est_juge_sur_toute_la_copie(depot):
    c, m, agent, controles = mener(depot, commandes=[TROIS_PASSES], en_trop={1: "a_premier.txt"})
    m.executer()
    assert c.tache("A").etat == "verifie" and controles.preparees == ["A"]
    assert len(controles.perimetres_vus) >= 4  # deux passes, la reprise de la copie, une passe
    assert all("a_premier.txt" in vus for vus in controles.perimetres_vus)  # le premier tour
    assert (depot / "a_premier.txt").exists()


def test_une_panne_de_l_atelier_pendant_la_tache_jette_la_copie(depot):
    class EnPanne(Controles):
        def mecaniques(self, t, dossier):
            raise OSError("disque plein")

    c = chantier([tache()])
    agent = Ouvrier(chantier=c)
    controles = EnPanne(depot, ["true"])
    Moteur(c, agent, controles).executer()
    a = c.tache("A")
    assert a.etat == "revenu" and "disque plein" in c.demandes[-1]["question"]
    assert "Travail gardé" not in c.demandes[-1]["question"]
    assert controles.annulees == [agent.passages[0]["dossier"]]
    assert_aucune_copie(depot, a)
