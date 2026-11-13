"""La sous-tâche (fiche M10) : après un refus qui nomme ce qui reste, l'ouvrier suivant ne règle
que cela, sur le travail gardé.

Chaque test mène le moteur sur un vrai dépôt git (`depot`, de `test_moteur_garde`), avec les vrais
contrôles et l'agent simulé, dont chaque ouvrier ajoute une ligne à `a_passes.txt`. On lit la
consigne reçue par chaque ouvrier, son modèle et son effort, ce qui entre dans la branche
principale et ce que garde l'historique. Aucun test n'attend une durée.
"""

import pytest

from atelier import dosage
from atelier import moteur as module
from atelier.consignes import SUR_PLACE
from atelier.moteur import RELANCER_TEL, Moteur
from tests.test_moteur_garde import (
    PASSES,
    REPART_PROPRE,
    TROIS_PASSES,
    Controles,
    Heure,
    Ouvrier,
    assert_aucune_copie,
    chantier,
    depot,  # noqa: F401  (le dépôt git de chaque test)
    fil,
    tache,
)
from tests.test_moteur_niveaux import verdict

pytestmark = pytest.mark.montee_sur_le_fond  # la règle sans réglage : monter seulement sur le fond

POINT = "Traiter la liste vide dans `b.py`, ligne 12."
LOCAL = verdict(motif="local", resume="La liste vide plante.", reste=[POINT], fichiers=["b.py"])
BACLE = verdict(reste=["Ajouter le test du cas vide."], fichiers=[])
AUTRE = verdict(motif="local", resume="Le cache garde une valeur périmée.",
                reste=["Vider le cache après une modification."], fichiers=["a.py"])  # fmt: skip
TROIS_REFUS = {1: LOCAL, 2: BACLE, 3: AUTRE}  # trois refus qui ne se ressemblent pas
REDACTION = verdict(reste=["Corriger le résumé."], fichiers=["a_notes.md"])
CONFORME = "Le reste de ce travail est conforme"
JAMAIS = "test -f a_jamais.txt"  # un contrôle rouge tant que personne n'écrit ce fichier


class OuvrierDose(Ouvrier):
    """L'ouvrier de `test_moteur_garde`, qui note en plus le modèle et l'effort de chaque
    passage, et dont le vérificateur rend le texte de `verdicts` pour la tentative qu'il juge
    (sinon celui du scénario)."""

    def __init__(self, scenario=None, verdicts=None, **champs):
        super().__init__(scenario, **champs)
        self.verdicts, self.doses = verdicts or {}, []

    def executer(self, consigne, modele, effort, dossier, lecture_seule=False, contexte=None,
                 copie_jetable=False, reprendre=None):  # fmt: skip
        if contexte.get("role") == "ouvrier":
            self.doses.append((modele, effort))
        resultat = super().executer(consigne, modele, effort, dossier, lecture_seule, contexte,
                                    copie_jetable, reprendre)  # fmt: skip
        texte = self.verdicts.get(contexte.get("tentative"))
        if contexte.get("role") == "verificateur" and texte and resultat.ok:
            resultat.texte = texte
        return resultat

    def departs_doses(self):
        """Le modèle et l'effort de chaque départ neuf, sans les reprises à chaud."""
        return [d for d, p in zip(self.doses, self.passages, strict=True) if not p["reprise"]]


def mener(depot, scenario=None, commandes=None, verdicts=None, en_trop=None, profil=None,  # noqa: F811
          limites=None, heure=None, **contrat):  # fmt: skip
    c = chantier([tache()], **contrat)
    en_plus = {"limites": limites, "delai_limite_s": None} if limites else {}
    agent = OuvrierDose(scenario, verdicts, chantier=c, en_trop=en_trop, **en_plus)
    controles = Controles(depot, commandes)
    reglages = {"heure": heure} if heure else {}
    return c, Moteur(c, agent, controles, profil, **reglages), agent, controles


def sous_taches(a):
    """Le nom de sous-tâche de chaque entrée de l'historique ("" pour une passe ordinaire)."""
    return [e.get("sous_tache", "") for e in a.historique]


# --- un refus qui nomme le reste ouvre une sous-tâche ----------------------------------------


def test_apres_des_controles_rouges_le_depart_suivant_est_une_sous_tache(depot):  # noqa: F811
    c, m, agent, controles = mener(depot, commandes=[TROIS_PASSES])
    m.executer()
    a = c.tache("A")
    assert a.etat == "verifie"
    premier, second = agent.departs()
    assert second["dossier"] == premier["dossier"] and controles.preparees == ["A"]
    assert "## Sous-tâche A-a, de la tâche A" in second["consigne"]
    assert "Les contrôles automatiques du projet ont échoué" in second["consigne"]
    assert CONFORME not in second["consigne"]  # personne n'a encore jugé ce travail
    assert "lignes : 2" in second["consigne"]  # ce qui a échoué, tel que les contrôles l'ont dit
    assert SUR_PLACE not in second["consigne"] and "Sous-tâche" not in premier["consigne"]
    assert sous_taches(a) == ["", "", "A-a"]
    assert [e["tentative"] for e in a.historique] == [1, 1, 1]  # elle garde le numéro du départ
    assert a.tentatives == 1 and a.sous_taches == 1 and a.rallonge == 0
    annonce = "Sous-tâche A-a lancée (Sonnet, effort élevé), 1 sur 2"
    assert any(t.startswith(annonce) for t in fil(c))
    assert sum(t.startswith("Ouvrier lancé") for t in fil(c)) == 1  # la sous-tâche a sa phrase
    assert (depot / PASSES).read_text("utf-8").splitlines() == ["passe 1", "passe 2", "passe 3"]
    assert_aucune_copie(depot, a)


def test_un_verdict_local_donne_ses_points_mot_pour_mot_et_dit_le_reste_conforme(depot):  # noqa: F811
    c, m, agent, _ = mener(depot, {"A": ["bacle", "ok"]}, verdicts={1: LOCAL})
    m.executer()
    a = c.tache("A")
    assert a.etat == "verifie"
    consigne = agent.departs()[1]["consigne"]
    assert "## Sous-tâche A-a, de la tâche A" in consigne
    assert CONFORME in consigne and POINT in consigne and "b.py" in consigne
    assert sous_taches(a)[-1] == "A-a"


def test_un_fond_juge_faux_efface_le_reste_et_le_modele_monte_repart_d_une_copie_propre(depot):  # noqa: F811
    scenario = {"A": ["bacle", "ne_sait_pas", "ok"]}
    c, m, agent, controles = mener(depot, scenario, verdicts={1: LOCAL})
    m.executer()
    a = c.tache("A")
    assert a.etat == "verifie" and a.sous_taches == 1 and c.montees == 1
    premier, sous, dernier = agent.departs()
    assert "## Sous-tâche A-a" in sous["consigne"]
    # Le fond est jugé faux : le travail n'est pas rapiécé, le modèle monté repart de zéro.
    assert "Sous-tâche" not in dernier["consigne"] and SUR_PLACE not in dernier["consigne"]
    assert REPART_PROPRE in dernier["consigne"] and dernier["trouve"] == ""
    assert controles.preparees == ["A", "A"] and len(controles.annulees) == 1
    assert sous_taches(a)[-1] == ""
    assert (depot / PASSES).read_text("utf-8").splitlines() == ["passe 4"]


def test_un_refus_qui_ne_nomme_rien_n_ouvre_pas_de_sous_tache(depot):  # noqa: F811
    c, m, agent, _ = mener(depot, {"A": ["bacle", "ok"]})  # le verdict simulé n'a pas de reste
    m.executer()
    a = c.tache("A")
    assert a.sous_taches == 0 and a.rallonge == 0 and a.reste == {}
    assert all("Sous-tâche" not in p["consigne"] for p in agent.passages)
    assert not any(t.startswith("Sous-tâche") for t in fil(c))
    assert sous_taches(a) == ["", "", ""]
    # Le départ suivant est une tentative ordinaire, qui reprend la copie gardée.
    assert a.etat == "verifie" and a.tentatives == 2
    assert SUR_PLACE in agent.departs()[1]["consigne"]


def test_un_reste_sans_point_n_ouvre_pas_de_sous_tache():
    a = tache(copie="/quelque/part", reste={"permis": ["b.py"]})
    m = Moteur(chantier([a]), Ouvrier(), None)
    with m.verrou:
        assert m._ouvrir_sous_tache(a, copie_gardee=True) == ""
    assert a.sous_taches == 0 and a.rallonge == 0 and a.reste == {"permis": ["b.py"]}


def test_sans_copie_gardee_le_reste_est_oublie():
    a = tache(reste={"genre": "verdict", "points": [POINT], "fichiers": ["b.py"]})
    m = Moteur(chantier([a]), Ouvrier(), None)
    with m.verrou:
        assert m._ouvrir_sous_tache(a, copie_gardee=False) == ""
    assert a.reste == {} and a.sous_taches == 0


# --- une sous-tâche ne compte pas de tentative -------------------------------------------------


def rendue_apres_ses_sous_taches(depot, **reglages):  # noqa: F811
    """Mène A, que son vérificateur refuse à chaque passage pour une raison nouvelle, jusqu'à
    ce qu'elle revienne à la personne. Le contrat ne lui donne qu'une tentative."""
    scenario = {"A": ["bacle"]}
    c, m, agent, controles = mener(depot, scenario, verdicts=TROIS_REFUS, max_tentatives=1,
                                   **reglages)  # fmt: skip
    m.executer()
    return c, m, agent, controles


def nom_de_sous_tache(passage):
    consigne = passage["consigne"]
    return next((nom for nom in ("A-a", "A-b") if f"## Sous-tâche {nom}," in consigne), "")


def test_deux_sous_taches_partent_au_dela_de_la_seule_tentative_du_contrat(depot):  # noqa: F811
    c, m, agent, _ = rendue_apres_ses_sous_taches(depot)
    a = c.tache("A")
    assert [nom_de_sous_tache(p) for p in agent.departs()] == ["", "A-a", "A-b"]
    assert a.tentatives == 1 and a.sous_taches == 2 and a.rallonge == 0  # une seule comptée
    assert {e["tentative"] for e in a.historique} == {1}
    assert sous_taches(a) == ["", "", "A-a", "A-a", "A-b", "A-b"]
    assert a.etat == "revenu"  # ses deux sous-tâches passées, elle revient à la personne
    assert "en_cours" not in a.reste and "dosage" not in a.reste
    assert a.reste["genre"] == "verdict" and a.reste["points"]


def test_chaque_passage_d_ouvrier_a_son_propre_numero_pour_l_agent(depot):  # noqa: F811
    c, m, agent, _ = rendue_apres_ses_sous_taches(depot)
    assert [p["tentative"] for p in agent.departs()] == [1, 2, 3]  # le rang du passage
    verificateurs = [x["tentative"] for x in agent.appels if x.get("role") == "verificateur"]
    assert verificateurs == [1, 1, 2, 2, 3, 3]


def test_une_sous_tache_part_meme_quand_le_meme_refus_revient_puis_la_tache_est_bloquee(depot):  # noqa: F811
    c, m, agent, _ = mener(depot, commandes=[JAMAIS], max_tentatives=1)
    m.executer()
    a = c.tache("A")
    textes = fil(c)
    annonces = [t for t in textes if "une sous-tâche règle ce qui reste" in t]
    assert len(annonces) == 1 and annonces[0].startswith("Refusée.")
    assert [nom_de_sous_tache(p) for p in agent.departs()] == ["", "A-a"]
    # Le même refus une troisième fois de suite : la tâche revient, sans seconde sous-tâche.
    assert a.etat == "revenu" and c.demandes[-1]["nature"] == "blocage"
    assert sous_taches(a) == ["", "", "A-a"] and a.sous_taches == 1


def test_le_profil_peut_couper_les_sous_taches(depot):  # noqa: F811
    c, m, agent, _ = mener(depot, commandes=[JAMAIS], max_tentatives=1,
                           profil={"sous_taches": 0})  # fmt: skip
    m.executer()
    a = c.tache("A")
    assert a.etat == "revenu" and a.tentatives == 1 and a.rallonge == 0 and a.sous_taches == 0
    assert all("Sous-tâche" not in p["consigne"] for p in agent.passages)
    assert not any(t.startswith("Sous-tâche") for t in fil(c))


@pytest.mark.parametrize("reglage", [-1, True, "2", None, 1.5])
def test_un_reglage_illisible_garde_deux_sous_taches(depot, reglage):  # noqa: F811
    c, m, agent, _ = rendue_apres_ses_sous_taches(depot, profil={"sous_taches": reglage})
    assert c.tache("A").sous_taches == module.SOUS_TACHES == 2


def test_une_relance_par_la_personne_rend_ses_sous_taches_a_la_tache(depot):  # noqa: F811
    c, m, agent, _ = rendue_apres_ses_sous_taches(depot)
    a = c.tache("A")
    assert a.sous_taches == 2
    m.repondre(c.demandes[-1]["id"], RELANCER_TEL)
    assert a.sous_taches == 0
    agent.verdicts = {}  # le vérificateur suit désormais le scénario : il accepte
    agent.scenario = {"A": ["ok"]}
    m.executer()
    assert a.etat == "verifie"
    assert nom_de_sous_tache(agent.departs()[-1]) == "A-a"  # elle repart de la première
    assert sous_taches(a)[-1] == "A-a" and a.sous_taches == 1


# --- une suspension rend le numéro de la sous-tâche --------------------------------------------


def test_une_sous_tache_suspendue_rend_son_numero_et_repart_sous_le_meme_nom(depot, monkeypatch):  # noqa: F811
    monkeypatch.setattr(module, "PAS_VEILLE_S", 0.01)
    c, m, agent, _ = mener(depot, commandes=[TROIS_PASSES], limites={"A": ["", "", "refus"]},
                           heure=Heure(pas=60.0))  # fmt: skip
    m.executer()
    a = c.tache("A")
    assert a.etat == "verifie"
    refusee, repartie = agent.departs()[1:]
    assert nom_de_sous_tache(refusee) == nom_de_sous_tache(repartie) == "A-a"
    assert a.sous_taches == 1 and a.rallonge == 0 and a.tentatives == 1
    assert sum(t.startswith("Sous-tâche A-a lancée") for t in fil(c)) == 2
    assert sous_taches(a)[-1] == "A-a"


# --- les fichiers nommés par le vérificateur sont permis pour ce tour --------------------------


def test_la_sous_tache_peut_toucher_le_fichier_que_le_verificateur_a_nomme(depot):  # noqa: F811
    c, m, agent, controles = mener(
        depot, {"A": ["bacle", "ok"]}, verdicts={1: LOCAL}, en_trop={3: "b.py"}
    )
    m.executer()
    a = c.tache("A")
    assert a.etat == "verifie"
    assert [e["origine"] for e in a.historique] == ["verdict", "verdict", ""]
    assert (depot / "b.py").read_text("utf-8") == "interdit\n"  # entré avec le reste du travail
    assert controles.annulees == []
    assert_aucune_copie(depot, a)


def test_hors_sous_tache_le_fichier_nomme_n_est_pas_permis():
    reste = {"genre": "verdict", "points": [POINT], "fichiers": ["b.py"]}
    a = tache(copie="/quelque/part", reste=dict(reste))
    m = Moteur(chantier([a]), Ouvrier(), None)
    assert m._perimetre_du_tour(a) == ["a.py", "a_*"]  # un ouvrier ordinaire : rien de plus
    with m.verrou:
        assert m._ouvrir_sous_tache(a, copie_gardee=True) == "A-a"
    assert m._perimetre_du_tour(a) == ["a.py", "a_*", "b.py"]
    assert m._perimetre_de_la_copie(a) == ["a.py", "a_*"]  # pas encore touché
    with m.verrou:
        m._defaire_sous_tache(a)  # suspendue en plein travail : elle a pu y toucher
    assert m._perimetre_de_la_copie(a) == ["a.py", "a_*", "b.py"]
    assert m._perimetre_du_tour(a) == ["a.py", "a_*", "b.py"]
    assert a.sous_taches == 0 and a.rallonge == 0


def test_une_sous_tache_arretee_avant_son_depart_ne_permet_aucun_fichier():
    a = tache(copie="/quelque/part",
              reste={"genre": "verdict", "points": [POINT], "fichiers": ["b.py"]})  # fmt: skip
    m = Moteur(chantier([a]), Ouvrier(), None)
    with m.verrou:
        m._ouvrir_sous_tache(a, copie_gardee=True)
        m._defaire_sous_tache(a, partie=False)
    assert m._perimetre_de_la_copie(a) == ["a.py", "a_*"] and a.sous_taches == 0


def test_un_fichier_que_le_verificateur_n_a_pas_nomme_reste_hors_perimetre(depot):  # noqa: F811
    c, m, agent, controles = mener(
        depot, {"A": ["bacle", "ok", "ok"]}, verdicts={1: LOCAL}, en_trop={3: "c.py"}
    )
    m.executer()
    a = c.tache("A")
    refusee = next(e for e in a.historique if e["origine"] == "perimetre")
    assert refusee["sous_tache"] == "A-a" and "c.py" in refusee["detail"]
    assert not (depot / "c.py").exists()


def test_le_fichier_permis_reste_dans_la_copie_gardee_d_une_sous_tache_a_l_autre(depot):  # noqa: F811
    scenario = {"A": ["bacle", "bacle", "ok"]}
    c, m, agent, controles = mener(
        depot, scenario, verdicts={1: LOCAL, 2: BACLE}, en_trop={3: "b.py"}
    )
    m.executer()
    a = c.tache("A")
    assert a.etat == "verifie"
    assert controles.preparees == ["A"] and controles.annulees == []  # jamais jetée
    assert "perimetre" not in [e["origine"] for e in a.historique]
    seconde = agent.departs()[2]
    assert "## Sous-tâche A-b" in seconde["consigne"]
    assert (seconde["dossier"] / "b.py").exists() or (depot / "b.py").exists()
    assert (depot / "b.py").exists()
    assert sous_taches(a) == ["", "", "A-a", "A-a", "A-b"]


# --- le dosage de la sous-tâche ---------------------------------------------------------------


def test_une_correction_de_code_part_sur_le_dosage_de_sous_tache_et_l_historique_le_garde(depot):  # noqa: F811
    c, m, agent, _ = mener(depot, {"A": ["bacle", "ok"]}, verdicts={1: LOCAL})
    m.executer()
    a = c.tache("A")
    depart, sous = agent.departs_doses()
    assert depart == (a.modele, a.effort) == ("sonnet", "low")
    assert sous == dosage.sous_tache("sonnet", "sonnet", False, 1) == ("sonnet", "high")
    entree = a.historique[-1]
    assert (entree["modele"], entree["effort"], entree["sous_tache"]) == ("sonnet", "high", "A-a")
    assert (a.modele, a.effort) == ("sonnet", "low")  # la tâche garde son dosage
    assert any("Sous-tâche A-a lancée (Sonnet, effort élevé)" in t for t in fil(c))


def test_un_reste_de_redaction_part_en_sonnet_effort_moyen(depot):  # noqa: F811
    c, m, agent, _ = mener(depot, {"A": ["bacle", "ok"]}, verdicts={1: REDACTION})
    m.executer()
    assert agent.departs_doses()[1] == ("sonnet", "medium")


def test_au_dela_du_plafond_du_contrat_la_sous_tache_garde_le_dosage_de_la_tache(depot):  # noqa: F811
    c, m, agent, _ = mener(depot, {"A": ["bacle", "ok"]}, verdicts={1: LOCAL},
                           plafond_modele="sonnet", plafond_effort="low")  # fmt: skip
    m.executer()
    a = c.tache("A")
    assert a.etat == "verifie"
    assert agent.departs_doses() == [("sonnet", "low"), ("sonnet", "low")]
    assert "## Sous-tâche A-a" in agent.departs()[1]["consigne"]


def test_la_seconde_sous_tache_monte_d_un_cran_d_effort(depot):  # noqa: F811
    scenario = {"A": ["bacle", "bacle", "ok"]}
    c, m, agent, _ = mener(depot, scenario, verdicts={1: LOCAL, 2: AUTRE},
                           plafond_modele="fable", plafond_effort="max")  # fmt: skip
    m.executer()
    assert agent.departs_doses()[1:] == [("sonnet", "high"), ("sonnet", "xhigh")]
