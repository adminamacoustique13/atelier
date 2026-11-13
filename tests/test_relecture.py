"""Les défauts trouvés à la relecture du 2026-11-13, un test par défaut corrigé.

Chaque test rejoue le scénario par lequel le vérificateur de la relecture a montré le défaut ;
il échouait sur le code d'avant la correction. Vrai dépôt git pour ce qui touche à la copie de
travail, contrôles simulés pour le budget.
"""

from pathlib import Path

import pytest

from atelier.agents import Resultat
from atelier.moteur import COPIE_CHANGEE, PLAFOND_AU_DELA, Moteur, _chemin_simple
from tests.test_moteur import tache as tache_simple
from tests.test_moteur_budget import PROFIL, monter_cher, rouge
from tests.test_moteur_budget import Controles as ControlesChers
from tests.test_moteur_garde import (
    SANS_SOUS_TACHE,
    TROIS_PASSES,
    Controles,
    Ouvrier,
    assert_aucune_copie,
    chantier,
    depot,  # noqa: F401  (le dépôt git de chaque test)
    fil,
    interrompue_en_verification,
    tache,
)
from tests.test_moteur_niveaux import verdict
from tests.test_moteur_sous_tache import LOCAL, POINT, mener, sous_taches
from tests.test_reprise_seule import atelier_sur, finir, serveur  # noqa: F401
from tests.test_reprise_seule import chantier as chantier_relu
from tests.test_reprise_seule import tache as tache_relue

pytestmark = pytest.mark.montee_sur_le_fond  # la règle du produit sans réglage


def nomme(*fichiers):
    return verdict(motif="local", resume="La liste vide plante.", reste=["Corriger b."],
                   fichiers=list(fichiers))  # fmt: skip


# --- 1. les fichiers nommés par le vérificateur n'ouvrent pas le périmètre à tout ----------


@pytest.mark.parametrize("ouverture", ["*", "**/*", "*.txt", "../secret.txt", "/tmp/secret.txt",
                                       ".git/config", "sec?et.txt", "[s]ecret.txt"])  # fmt: skip
def test_un_motif_nomme_par_le_verificateur_n_ouvre_rien(depot, ouverture):  # noqa: F811
    c, m, agent, _ = mener(depot, {"A": ["bacle", "ok", "ok"]}, verdicts={1: nomme(ouverture)},
                           en_trop={3: "secret.txt"})  # fmt: skip
    m.executer()
    a = c.tache("A")
    assert "perimetre" in [e["origine"] for e in a.historique]  # la sous-tâche a débordé
    assert not (depot / "secret.txt").exists()


def test_un_fichier_nomme_ne_reste_pas_ouvert_a_tout_pour_l_ouvrier_suivant(depot):  # noqa: F811
    scenario = {"A": ["bacle", "ne_sait_pas", "ok", "ok"]}
    c, m, agent, _ = mener(depot, scenario, verdicts={1: nomme("*")}, en_trop={5: "secret.txt"})
    m.executer()
    assert not (depot / "secret.txt").exists()


@pytest.mark.parametrize(
    "ecrit, attendu",
    [
        ("b.py", "b.py"),
        ("./src/b.py", "src/b.py"),
        (" docs/été.md ", "docs/été.md"),
        ("*", ""), ("src/*.py", ""), ("a[bc].py", ""), ("a?.py", ""),
        ("../b.py", ""), ("src/../../b.py", ""), ("/etc/passwd", ""), ("src/", ""), ("", ""),
        (".git/config", ""), (".atelier/etat.json", ""), ("a\nb.py", ""), (None, ""), (3, ""),
        ("x" * 201, ""),
    ],
)  # fmt: skip
def test_seul_un_chemin_simple_est_garde(ecrit, attendu):
    assert _chemin_simple(ecrit) == attendu


def test_un_fichier_du_perimetre_d_une_autre_tache_n_est_pas_ouvert_a_la_sous_tache():
    a = tache_simple("A", copie="/quelque/part")
    autres = [tache_simple("B"), tache_simple("C", etat="verifie")]
    m = Moteur(chantier([a, *autres]), Ouvrier(), None)
    with m.verrou:
        gardes = m._fichiers_nommes(a, ["b.py", "c.py", "d.py", "d.py", "*"])
    assert gardes == ["c.py", "d.py"]  # B peut encore y écrire ; C est déjà entrée


def test_au_plus_huit_fichiers_sont_ouverts():
    a = tache_simple("A")
    m = Moteur(chantier([a]), Ouvrier(), None)
    with m.verrou:
        assert len(m._fichiers_nommes(a, [f"f{i}.py" for i in range(20)])) == 8


# --- 2. ce qui change dans la copie pendant la vérification n'entre pas ----------------------


class OuvrierQuiContinue(Ouvrier):
    """Un ouvrier dont un travail de fond écrit encore dans sa copie pendant que le
    vérificateur relit ; `fois` : le nombre de vérifications pendant lesquelles il le fait."""

    def __init__(self, fois=1, **champs):
        super().__init__(**champs)
        self.fois, self.copie_ouvrier = fois, None

    def executer(self, consigne, modele, effort, dossier, lecture_seule=False, contexte=None,
                 copie_jetable=False, reprendre=None):  # fmt: skip
        if contexte.get("role") == "ouvrier":
            self.copie_ouvrier = Path(dossier)
        if contexte.get("role") == "verificateur" and self.fois > 0:
            self.fois -= 1
            (self.copie_ouvrier / "a_ajout.txt").write_text("écrit après le contrôle\n", "utf-8")
        return super().executer(consigne, modele, effort, dossier, lecture_seule, contexte,
                                copie_jetable, reprendre)  # fmt: skip


def test_une_copie_changee_pendant_la_verification_n_est_pas_enregistree(depot):  # noqa: F811
    c = chantier([tache()])
    agent = OuvrierQuiContinue(chantier=c)
    Moteur(c, agent, Controles(depot)).executer()
    a = c.tache("A")
    refusee = a.historique[0]
    assert (refusee["issue"], refusee["origine"], refusee["detail"]) == (
        "ne_sait_pas", "controles", COPIE_CHANGEE,
    )  # fmt: skip
    assert any(COPIE_CHANGEE in t for t in fil(c))
    # Le départ suivant reprend la copie : le fichier ajouté est alors contrôlé et vérifié.
    assert a.etat == "verifie" and a.tentatives == 2
    assert (depot / "a_ajout.txt").exists()
    assert_aucune_copie(depot, a)


def test_une_copie_restee_telle_quelle_entre_du_premier_coup(depot):  # noqa: F811
    c = chantier([tache()])
    Moteur(c, OuvrierQuiContinue(fois=0, chantier=c), Controles(depot)).executer()
    a = c.tache("A")
    assert a.etat == "verifie" and a.tentatives == 1 and len(a.historique) == 1


# --- 3 et 4. le budget : un vérificateur plafonné, un retour coupé qui ne compte pas ----------


def test_au_dela_du_budget_le_verificateur_garde_un_plafond():
    c, m, agent = monter_cher([tache_simple("A", type="courante")], {**PROFIL, "budget_usd": 1.0})
    m.executer()
    ouvrier, verificateur = agent.plafonds[:2]
    assert ouvrier == 1.0
    assert verificateur == pytest.approx(1.0 * PLAFOND_AU_DELA)  # jamais « sans limite »
    assert c.tache("A").etat == "verifie"  # un travail rendu est jugé jusqu'au bout


def test_un_retour_coupe_par_son_plafond_ne_compte_ni_tentative_ni_erreur_d_agent():
    a = tache_simple("A", type="mecanique")
    controles = ControlesChers(sorties=[rouge("test_un")])
    c, m, agent = monter_cher([a], {**PROFIL, "budget_usd": 5}, controles, coupes={2})
    m.executer()
    assert [(e["tentative"], e["issue"], e["origine"]) for e in a.historique] == [
        (1, "ne_sait_pas", "controles"), (2, "valide", ""),
    ]  # fmt: skip
    assert "agent" not in [e["origine"] for e in a.historique]
    assert any("coupé par le plafond du budget" in e["texte"] for e in c.evenements)
    assert not any("Seconde chance" in e["texte"] for e in c.evenements)
    assert c.demandes == []


# --- 6. une erreur d'agent pendant une sous-tâche garde ce qui restait à régler --------------


def test_une_erreur_d_agent_pendant_une_sous_tache_garde_le_point_a_regler(depot):  # noqa: F811
    c, m, agent, _ = mener(depot, {"A": ["bacle", "ok"]}, verdicts={1: LOCAL})
    executer, rangs = agent.executer, []

    def tomber_une_fois(consigne, modele, effort, dossier, *suite, **reglages):
        resultat = executer(consigne, modele, effort, dossier, *suite, **reglages)
        if reglages.get("contexte", {}).get("role") == "ouvrier":
            rangs.append(1)
            if len(rangs) == 3:  # le premier ouvrier de sous-tâche s'arrête sur une erreur
                return Resultat(ok=False, erreur="Délai dépassé.", session=resultat.session)
        return resultat

    agent.executer = tomber_une_fois
    m.executer()
    a = c.tache("A")
    assert a.etat == "verifie"
    tombee, reprise = agent.departs()[1:]
    assert "## Sous-tâche A-a" in tombee["consigne"] and POINT in tombee["consigne"]
    # La sous-tâche tombée rend son numéro : la suivante porte le même nom et le même point.
    assert "## Sous-tâche A-a" in reprise["consigne"] and POINT in reprise["consigne"]
    assert a.sous_taches == 1 and a.tentatives == 1
    assert sous_taches(a)[-1] == "A-a"


# --- 7. au départ suivant, l'ouvrier a son retour avant tout blocage -------------------------


def test_apres_un_rejugement_refuse_l_ouvrier_suivant_a_son_retour(depot):  # noqa: F811
    controles = Controles(depot, commandes=[TROIS_PASSES])
    t, copie = interrompue_en_verification(depot, controles)
    c = chantier([t])
    agent = Ouvrier(chantier=c)
    Moteur(c, agent, controles, SANS_SOUS_TACHE).executer()
    # Rejugée (rouge), puis un ouvrier (rouge encore), puis son retour : les contrôles passent.
    assert t.etat == "verifie" and c.demandes == []
    assert [p["reprise"] for p in agent.passages] == [False, True]


# --- 10. le vérificateur d'une sous-tâche est dosé sur l'ouvrier de la sous-tâche ------------


def test_le_verificateur_d_une_sous_tache_suit_le_dosage_de_son_ouvrier(depot):  # noqa: F811
    c, m, agent, _ = mener(depot, {"A": ["bacle", "ok"]}, verdicts={1: LOCAL})
    m.executer()
    juges = [(x["modele"], x["effort"]) for x in agent.appels if x.get("role") == "verificateur"]
    assert agent.departs_doses() == [("sonnet", "low"), ("sonnet", "high")]
    assert juges[-1] == ("sonnet", "high")  # et plus « effort moyen », celui de la tâche


# --- 15. une tâche rendue après une panne de l'Atelier n'a plus de sous-tâche en cours -------


def test_une_tache_rendue_apres_une_panne_ne_garde_pas_de_sous_tache_en_cours():
    reste = {"genre": "verdict", "points": [POINT], "fichiers": [], "en_cours": "A-a",
             "dosage": ["sonnet", "high"]}  # fmt: skip
    a = tache_simple("A", copie="/quelque/part", reste=reste, sous_taches=1, tentatives=1)
    m = Moteur(chantier([a]), Ouvrier(), None)
    with m.verrou:
        m._demander(a, "l'Atelier s'est arrêté.", "Arrêt.")
    assert a.historique[-1]["sous_tache"] == "A-a"  # la trace porte encore son nom
    assert "en_cours" not in a.reste and "dosage" not in a.reste and a.sous_taches == 0
    assert a.reste["points"] == [POINT] and m.salle()["A"]["sous_tache"] == ""


# --- 18. « Arrêter » pendant une reprise annoncée, quand l'orchestrateur répond --------------


def test_arreter_vise_d_abord_l_orchestrateur_qui_repond(tmp_path, serveur):  # noqa: F811
    a = atelier_sur(tmp_path, chantier_relu([tache_relue("A", etat="en_cours", tentatives=1)]))
    retours = []

    def attendre(delai_s, annulee):
        a.occupe = True  # l'orchestrateur répond pendant le délai
        retours.append(a.arreter())
        a.occupe = False
        return annulee.is_set()

    a.reprendre_apres_arret(serveur, attendre)
    finir(a)
    assert retours[0]["phrase"] != "Reprise annulée : aucune tâche n'est repartie seule."
    assert a.moteur.chantier.tache("A").etat == "verifie"  # la reprise a bien eu lieu
