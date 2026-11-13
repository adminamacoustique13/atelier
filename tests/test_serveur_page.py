"""Ce que le serveur donne à la page pour la fiche M13 : le budget « X $ sur Y $ », le travail
gardé d'une tâche revenue, le vérificateur selon le niveau, et la demande de budget.

Les lectures du moteur faites pour la page (`niveau_prevu`, `budget_prevu`) ne disent rien au fil
et n'écrivent rien dans l'état : la page les relit à chaque rafraîchissement.
"""

import pytest

from atelier import dosage
from atelier.agents import AgentSimule
from atelier.controles import ControlesSimules
from atelier.moteur import MECANIQUE_SANS_CONTROLE, NATURE_BUDGET, Moteur
from atelier.serveur import SANS_VERIFICATEUR, VERIFICATIONS_FR, vue, vue_du_budget
from tests.test_moteur import chantier, tache
from tests.test_serveur import atelier_simule

AVEC_COMMANDE = {"commandes": ["pytest -q"]}


def moteur(taches, profil=None, **contrat):
    c = chantier(taches, **contrat)
    return c, Moteur(c, AgentSimule(), ControlesSimules(), profil)


# --- le budget ------------------------------------------------------------------------------


@pytest.mark.parametrize("budget", [0, 0.0, -3, None])
def test_sans_budget_la_page_ne_recoit_rien(budget):
    assert vue_du_budget(12.4, budget) is None


def test_le_budget_dit_la_depense_le_plafond_et_la_phrase():
    assert vue_du_budget(12.4, 40) == {
        "depense_usd": 12.4, "budget_usd": 40, "atteint": False, "fr": "12,40 $ sur 40,00 $",
    }  # fmt: skip


@pytest.mark.parametrize("depense, atteint", [(39.99, False), (40.0, True), (41.5, True)])
def test_le_budget_est_atteint_des_qu_il_est_egale(depense, atteint):
    assert vue_du_budget(depense, 40.0)["atteint"] is atteint


def test_les_milliers_sont_separes_comme_sur_la_page():
    assert vue_du_budget(1234.5, 2000)["fr"] == "1 234,50 $ sur 2 000,00 $"


def test_le_budget_prevu_est_celui_du_contrat_sinon_celui_du_profil():
    assert moteur([tache("A")])[1].budget_prevu() == 0.0
    assert moteur([tache("A")], {"budget_usd": 40})[1].budget_prevu() == 40.0
    assert moteur([tache("A")], {"budget_usd": 40}, max_cout_usd=48.0)[1].budget_prevu() == 48.0


@pytest.mark.parametrize("regle", [True, "40", -1, 0, None, [40]])
def test_un_budget_illisible_au_profil_vaut_aucun_budget(regle):
    assert moteur([tache("A")], {"budget_usd": regle})[1].budget_prevu() == 0.0


def test_lire_le_budget_pour_la_page_n_ecrit_rien_dans_le_contrat():
    c, m = moteur([tache("A")], {"budget_usd": 40})
    assert m.budget_prevu() == 40.0 and c.contrat.max_cout_usd == 0.0


def test_la_vue_de_l_atelier_porte_le_budget_et_sa_phrase(tmp_path):
    atelier = atelier_simule(tmp_path, [tache("A")], profil={"budget_usd": 40})
    atelier.moteur.chantier.cout_usd = 12.4
    assert atelier.vue()["budget"]["fr"] == "12,40 $ sur 40,00 $"
    assert atelier_simule(tmp_path / "b", [tache("A")]).vue()["budget"] is None


# --- le vérificateur selon le niveau --------------------------------------------------------


def test_sans_niveau_dit_la_vue_garde_le_verificateur_de_la_verification_complete():
    c = chantier([tache("A", modele="sonnet", effort="medium")])
    (a,) = vue(c, False, "demo")["taches"]
    assert a["verification"] == dosage.COMPLETE
    assert a["verification_fr"] == "Vérification complète"
    assert a["verificateur_fr"] == dosage.libelle(*dosage.verificateur("sonnet", "medium"))


def test_une_verification_bornee_nomme_un_verificateur_du_meme_modele():
    c = chantier([tache("A", modele="sonnet", effort="low")])
    (a,) = vue(c, False, "demo", niveaux={"A": dosage.BORNEE})["taches"]
    assert a["verification_fr"] == "Vérification bornée"
    assert a["verificateur_fr"] == "Sonnet, effort moyen"  # jamais sous l'effort moyen


def test_une_verification_mecanique_ne_nomme_aucun_verificateur():
    c = chantier([tache("A", modele="haiku", effort="low")])
    (a,) = vue(c, False, "demo", niveaux={"A": dosage.MECANIQUE})["taches"]
    assert a["verification"] == dosage.MECANIQUE
    assert a["verification_fr"] == "Vérification mécanique seule"
    assert a["verificateur_fr"] == SANS_VERIFICATEUR


def test_un_niveau_inconnu_est_dit_complet():
    c = chantier([tache("A", modele="sonnet", effort="medium")])
    (a,) = vue(c, False, "demo", niveaux={"A": "rapide"})["taches"]
    assert a["verification"] == dosage.COMPLETE
    assert a["verification_fr"] == VERIFICATIONS_FR[dosage.COMPLETE]


@pytest.mark.parametrize(
    "type_, profil, attendu",
    [
        ("mecanique", AVEC_COMMANDE, dosage.MECANIQUE),
        ("mecanique", {}, dosage.BORNEE),  # sans commande de contrôle, il faut un vérificateur
        ("delicate", AVEC_COMMANDE, dosage.COMPLETE),
        ("inconnu", AVEC_COMMANDE, dosage.COMPLETE),
    ],
)
def test_le_niveau_prevu_est_celui_du_moteur_et_ne_dit_rien_au_fil(type_, profil, attendu):
    c, m = moteur([tache("A", type=type_)], profil)
    a = c.tache("A")
    assert m.niveau_prevu(a) == attendu and c.evenements == []
    assert m._niveau(a) == attendu  # le moteur, lui, peut le dire au fil une fois


def test_le_moteur_dit_encore_au_fil_ce_que_la_page_lit_en_silence():
    c, m = moteur([tache("A")], {})
    m.niveau_prevu(c.tache("A"))
    assert c.evenements == []
    m._niveau(c.tache("A"))
    assert [e["texte"] for e in c.evenements] == [MECANIQUE_SANS_CONTROLE]


def test_la_vue_de_l_atelier_porte_le_niveau_de_chaque_tache(tmp_path):
    taches = [tache("A"), tache("B", type="delicate")]
    atelier = atelier_simule(tmp_path, taches, profil=AVEC_COMMANDE)
    a, b = atelier.vue()["taches"]
    assert (a["verification"], a["verificateur_fr"]) == (dosage.MECANIQUE, SANS_VERIFICATEUR)
    assert b["verification"] == dosage.COMPLETE and b["verificateur_fr"] != SANS_VERIFICATEUR
    assert atelier.moteur.chantier.evenements == []  # lire la vue ne dit rien au fil


# --- le travail gardé d'une tâche revenue ---------------------------------------------------


@pytest.mark.parametrize(
    "etat, copie, garde",
    [
        ("revenu", "/projet/.atelier/arbres/A", True),
        ("revenu", "", False),
        ("en_cours", "/projet/.atelier/arbres/A", False),  # elle travaille : rien à annoncer
        ("verifie", "", False),
    ],
)
def test_seule_une_tache_revenue_avec_sa_copie_dit_travail_garde(etat, copie, garde):
    c = chantier([tache("A", etat=etat, copie=copie, modele="sonnet", effort="low")])
    assert vue(c, False, "demo")["taches"][0]["travail_garde"] is garde


# --- la demande de budget -------------------------------------------------------------------


def test_une_tache_arretee_par_le_budget_revient_avec_une_demande_que_la_page_reconnait(tmp_path):
    atelier = atelier_simule(tmp_path, [tache("A")], profil={"budget_usd": 0.01})
    atelier.moteur.chantier.cout_usd = 0.02  # le budget est déjà dépassé avant le départ
    atelier.moteur.executer()
    donnees = atelier.vue()
    (demande,) = donnees["demandes"]
    assert demande["nature"] == NATURE_BUDGET and demande["reponse"] is None
    assert donnees["budget"]["atteint"] is True and donnees["budget"]["fr"] == "0,02 $ sur 0,01 $"
    assert donnees["taches"][0]["etat"] == "revenu"
