"""La règle de montée du produit sans réglage : le modèle ne monte que si le fond est jugé faux.

Un manque, un contrôle rouge ou un débord se corrigent au même niveau ; seul un verdict lisible
qui dit que l'agent ne sait pas faire (`ne_sait_pas`) fait monter d'un cran. L'ancienne règle
(`"montee": "refus"`) reste au profil.
"""

import pytest

from atelier import dosage
from atelier import moteur as module
from tests.test_moteur import tache, traces
from tests.test_moteur_niveaux import ACCORD, BACLE, PROFIL, Controles, monter, verdict

pytestmark = pytest.mark.montee_sur_le_fond

FOND = verdict(motif="ne_sait_pas", resume="L'algorithme choisi ne peut pas marcher.")
AUTRE = verdict(reste=["Documenter la fonction."], fichiers=["a.py"], resume="La doc manque.")


def rouge(nom):
    return (False, f"$ pytest -q\nFAILED tests/test_a.py::{nom} - assert 1 == 2\n1 failed")


def test_la_regle_sans_reglage_est_le_fond():
    assert module.MONTEE_SANS_REGLAGE == "fond"  # ce fichier ne reçoit pas le réglage d'avant


def test_un_travail_bacle_se_corrige_au_meme_niveau_sans_monter():
    a = tache("A", type="courante")
    c, m, agent, _ = monter([a], PROFIL, textes={"A": [BACLE, AUTRE, ACCORD]})
    m.executer()
    assert a.etat == "verifie" and c.montees == 0 and a.montees == 0
    assert (a.modele, a.effort) == dosage.depart("courante")
    assert any("sans monter de modèle" in e["texte"] for e in c.evenements)


def test_un_fond_juge_faux_fait_monter_d_un_cran():
    a = tache("A", type="courante")
    c, m, agent, _ = monter([a], PROFIL, textes={"A": [FOND, ACCORD]})
    m.executer()
    assert a.etat == "verifie" and c.montees == 1 and a.tentatives == 2
    assert (a.modele, a.effort) == dosage.monter(*dosage.depart("courante"), "ne_sait_pas")
    assert [repris for _, _, repris in traces(a)] == [False, False]  # jamais rendu au même ouvrier


def test_des_controles_rouges_ne_font_jamais_monter():
    a = tache("A", type="mecanique")
    rouges = [rouge(f"test_{i}") for i in range(40)]  # toujours un échec différent
    c, m, agent, _ = monter([a], PROFIL, Controles(sorties=rouges))
    m.executer()
    assert a.etat == "revenu" and c.montees == 0
    assert (a.modele, a.effort) == dosage.depart("mecanique")
    assert a.relances_auto == 0  # pas de relance seule : le fond n'est pas en cause
    assert a.tentatives == c.contrat.max_tentatives


def test_le_meme_refus_deux_fois_de_suite_bloque_la_tache_au_lieu_de_la_faire_monter():
    a = tache("A", type="mecanique")
    rouges = [rouge("test_un")] * 10
    c, m, agent, _ = monter([a], PROFIL, Controles(sorties=rouges))
    m.executer()
    assert a.etat == "revenu" and c.montees == 0
    (demande,) = [d for d in c.demandes if d.get("nature") == "blocage"]
    assert demande["tache"] == "A"
    assert len(traces(a)) == 2  # deux passes ont suffi : la seconde redonnait le même échec


def test_un_fond_juge_faux_au_plafond_du_contrat_ne_monte_pas():
    a = tache("A", type="courante")
    c, m, agent, _ = monter([a], PROFIL, textes={"A": [FOND, FOND, FOND, FOND]})
    c.contrat.max_montees = 0
    m.executer()
    assert c.montees == 0 and a.etat == "revenu"


@pytest.mark.parametrize("reglage", [None, "n'importe quoi", 3, True])
def test_un_reglage_absent_ou_mal_forme_vaut_la_regle_du_fond(reglage):
    a = tache("A", type="courante")
    profil = {**PROFIL, "montee": reglage} if reglage is not None else PROFIL
    c, m, agent, _ = monter([a], profil, textes={"A": [BACLE, AUTRE, ACCORD]})
    m.executer()
    assert a.etat == "verifie" and c.montees == 0


def test_le_profil_peut_revenir_a_la_montee_apres_tout_refus():
    a = tache("A", type="courante")
    profil = {**PROFIL, "montee": "refus"}
    c, m, agent, _ = monter([a], profil, textes={"A": [BACLE, AUTRE, ACCORD]})
    m.executer()
    assert a.etat == "verifie" and c.montees == 1  # refusée après sa reprise : un cran de plus
