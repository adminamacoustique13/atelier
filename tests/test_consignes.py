"""Les consignes gardent ce qu'elles doivent dire : le moteur et les agents en dépendent."""

import hashlib
import inspect
import re
import subprocess

import pytest

from atelier.consignes import (
    COMMANDES_SIMPLES,
    COPIE_JETABLE,
    EMPECHE_OUVRIER,
    MARQUE_BLOCAGE,
    MARQUE_EMPECHE,
    PREUVE_MANQUANTE,
    PREUVES_MAX,
    REGLES_DECOUPAGE,
    RELAIS_PERMIS,
    RELECTURE,
    ROLE_ORCHESTRATEUR,
    SORTIE_BORNEE,
    SUIVI,
    SUR_PLACE,
    consigne_ouvrier,
    consigne_planification,
    consigne_reprise,
    consigne_reverification,
    consigne_sous_tache,
    consigne_verificateur,
    consigne_verificateur_bornee,
    lire_verdict,
    message_de_diagnostic,
)
from atelier.controles import TOUJOURS_PERMIS, ControlesGit, hors_perimetre
from atelier.modele import Contrat, Tache

PROFIL = {"commandes": ["pytest -q", "ruff check ."]}
CONTRAT = Contrat(objectif="But du chantier")
JSON_DU_VERDICT = (
    '{"valide": true ou false, "motif": "bacle" ou "ne_sait_pas" ou "consigne", '
    '"resume": "une ou deux phrases"}'
)


def tache(**champs):
    reglages = {
        "id": "B2",
        "titre": "Lire le profil",
        "criteres": ["Rend 42.", "Refuse -1."],
        "perimetre": ["b.py", "tests/test_b.py"],
    }
    return Tache(**{**reglages, **champs})


def verifications(copie_jetable):
    """Les trois consignes de vérification, pour une même tâche et un même cadre."""
    t = tache()
    return {
        "complete": consigne_verificateur(t, CONTRAT, PROFIL, copie_jetable),
        "reverification": consigne_reverification(t, CONTRAT, PROFIL, "Refusé.", copie_jetable),
        "bornee": consigne_verificateur_bornee(t, CONTRAT, PROFIL, "3 passed", copie_jetable),
    }


def rendu(texte):
    return texte.split("## Ce que tu rends", 1)[1]


# --- la reprise à chaud ----------------------------------------------------------------------


def test_la_reprise_apres_un_verdict_porte_le_verdict_entier_et_ce_qu_il_faut_faire():
    verdict = "DEBUT-DU-VERDICT\n" + "Le critère 2 manque. " * 400 + '\n{"valide": false}'
    texte = consigne_reprise(tache(), "verdict", verdict, PROFIL)
    assert verdict in texte
    assert "Corrige chaque point qu'il recale" in texte
    assert "Ne change rien d'autre" in texte and "ne défais pas ce qui était juste" in texte
    assert "`pytest -q`" in texte and "`ruff check .`" in texte
    assert "`chantier/relais/B2.md`" in texte and "mets-la à jour" in texte
    assert f"« {MARQUE_EMPECHE} »" in texte


def test_la_reprise_apres_un_debord_nomme_les_fichiers_hors_perimetre():
    texte = consigne_reprise(tache(), "perimetre", ["DECISIONS.md", "c.py"], PROFIL)
    assert "- `DECISIONS.md`\n- `c.py`" in texte
    assert "hors de ton périmètre" in texte and "fiche de relais" in texte
    en_texte = consigne_reprise(tache(), "perimetre", "Fichiers modifiés : c.py.", PROFIL)
    assert "Fichiers modifiés : c.py." in en_texte


def test_la_reprise_apres_un_debord_dit_de_defaire_avec_l_outil_d_edition_pas_avec_git():
    texte = consigne_reprise(tache(), "perimetre", ["c.py"], PROFIL)
    assert "avec l'outil Edit" in texte
    assert "N'emploie aucune commande git" in texte and "`git checkout`" in texte
    assert "`git diff -- <chemin>`" not in texte and "`rm <chemin>`" not in texte


def test_la_reprise_apres_des_controles_rouges_porte_leur_sortie():
    sortie = "FAILED tests/test_b.py::test_refuse - AssertionError\n1 failed, 3 passed"
    texte = consigne_reprise(tache(), "controles", sortie, PROFIL)
    assert sortie in texte and "échouent" in texte


@pytest.mark.parametrize("origine", ["verdict", "perimetre", "controles"])
def test_la_reprise_est_courte_l_ouvrier_a_deja_sa_consigne(origine):
    texte = consigne_reprise(tache(), origine, "", PROFIL)
    assert len(texte) < len(consigne_ouvrier(tache(), CONTRAT, PROFIL)) / 2
    assert "Rend 42." not in texte and "## Interdits" not in texte


def test_une_reprise_d_origine_inconnue_est_refusee():
    with pytest.raises(ValueError, match="agent"):
        consigne_reprise(tache(), "agent", "", PROFIL)


def test_la_reprise_sans_commande_de_controle_ne_liste_pas_un_vide():
    texte = consigne_reprise(tache(), "verdict", "Refusé.", {})
    assert "(aucune)" not in texte and "Relance ensuite les tests" in texte


def test_la_reprise_cite_les_outils_refuses_a_l_ouvrier():
    refuses = ("Bash(git push)", "WebFetch(https://exemple.org)")
    texte = consigne_reprise(tache(), "verdict", "Refusé.", PROFIL, refuses)
    assert "- `Bash(git push)`\n- `WebFetch(https://exemple.org)`\n" in texte
    assert "Ces outils t'ont été refusés pendant ton travail : tu ne peux pas t'en servir" in texte
    # Avant la fiche de relais, qui reste à sa place ; sans outil refusé, rien n'en est dit.
    assert texte.index("- `WebFetch") < texte.index("Si tu tiens une fiche de relais")
    sans = consigne_reprise(tache(), "verdict", "Refusé.", PROFIL)
    assert "t'ont été refusés" not in sans and sans == texte.replace(
        texte[texte.index("Ces outils") : texte.index("Si tu tiens")], ""
    )


# --- la seconde vérification, après une reprise ----------------------------------------------


@pytest.mark.parametrize("copie_jetable", [True, False])
def test_la_reverification_recoit_le_verdict_precedent_en_entier_et_ne_refait_pas_le_reste(
    copie_jetable,
):
    precedent = "DEBUT\n" + "Le test de -1 ne peut pas échouer. " * 300 + '\n{"valide": false}'
    texte = consigne_reverification(tache(), CONTRAT, PROFIL, precedent, copie_jetable)
    assert precedent in texte
    assert "Pour chaque point recalé, vérifie par toi-même qu'il est corrigé" in texte
    assert "ces corrections n'ont rien défait" in texte
    assert "Ne refais pas le reste de la vérification" in texte
    assert ("copie jetable" in texte) is copie_jetable


def test_la_reverification_dit_que_les_remarques_d_un_verdict_borne_ne_sont_pas_des_recalages():
    texte = consigne_reverification(tache(), CONTRAT, PROFIL, "Remarque : un nom à revoir.")
    assert "ce ne sont pas des points recalés" in texte
    assert "tu n'as pas à les contrôler comme tels" in texte


def test_la_reverification_rend_le_meme_verdict_que_la_verification_complete():
    for copie_jetable in (True, False):
        textes = verifications(copie_jetable)
        assert rendu(textes["reverification"]) == rendu(textes["complete"])
        assert JSON_DU_VERDICT in rendu(textes["complete"])


# --- la vérification bornée ------------------------------------------------------------------


def test_la_verification_bornee_recoit_la_fin_de_la_sortie_bornee_a_1500_caracteres():
    sortie = "DEBUT-DE-LA-SORTIE" + "." * 3000 + "12 passed in 0.31s"
    texte = consigne_verificateur_bornee(tache(), CONTRAT, PROFIL, sortie, True)
    assert SORTIE_BORNEE == 1500
    assert sortie[-SORTIE_BORNEE:] in texte
    assert sortie[-SORTIE_BORNEE - 1 :] not in texte
    assert "DEBUT-DE-LA-SORTIE" not in texte


@pytest.mark.parametrize("copie_jetable", [True, False])
def test_la_verification_bornee_ne_cherche_que_ce_qui_bloque_sans_relancer_ni_muter(
    copie_jetable,
):
    texte = consigne_verificateur_bornee(tache(), CONTRAT, PROFIL, "3 passed", copie_jetable)
    assert "1. Rend 42.\n2. Refuse -1." in texte and "Vérifie chaque critère" in texte
    assert "comportement faux, une perte de travail ou de données, une faille" in texte
    assert "Ne relance pas toute la suite" in texte
    assert "Ne fais pas de mutation" in texte
    assert "pour une mutation (changer le code" not in texte  # le cadre n'en propose pas
    assert '"remarques"' in texte and "Une remarque ne recale pas" in texte
    assert JSON_DU_VERDICT in texte and '"empeche"' in texte


def test_la_verification_bornee_sans_commande_de_controle_le_dit():
    texte = consigne_verificateur_bornee(tache(), CONTRAT, {}, "", False)
    assert "n'a pas de commande de contrôle" in texte and "[début de la sortie]" not in texte


# --- les empêchements ------------------------------------------------------------------------


def test_la_marque_d_empechement_est_celle_que_le_moteur_cherche():
    assert MARQUE_EMPECHE == "EMPÊCHÉ :"


def lignes_qui_commencent_par_la_marque(texte):
    return [ligne for ligne in texte.splitlines() if ligne.startswith(MARQUE_EMPECHE)]


def test_l_ouvrier_sait_signaler_un_empechement_et_pourquoi():
    texte = consigne_ouvrier(tache(), CONTRAT, PROFIL)
    assert f"« {MARQUE_EMPECHE} », au tout début de la ligne" in texte
    assert "compte rendu final" in texte and "à l'aveugle" in texte
    assert lignes_qui_commencent_par_la_marque(texte)  # l'exemple, écrit tel qu'attendu


# Le début de la règle du signe d'empêchement : chez l'ouvrier, sa reprise et le vérificateur.
SI_EMPECHE = (
    "Si une commande refusée ou un outil qui manque (commande non permise, programme absent, "
    "réseau coupé) t'empêche "
)


def test_l_ouvrier_ne_signale_un_refus_que_si_la_tache_ne_peut_pas_se_faire_sans():
    ouvrier = consigne_ouvrier(tache(), CONTRAT, PROFIL)
    assert (
        f"{SI_EMPECHE}d'aller au bout de la tâche, écris-le dans ton compte rendu final (rubrique "
        f"Doutes et demandes) par une ligne « {MARQUE_EMPECHE} » ; sinon fais sans, et dis-le au "
        "même endroit, sans cette ligne."
    ) in ouvrier
    # Une seule règle, conditionnelle dès son premier mot, qui n'oblige pas à créer une fiche.
    section = ouvrier.split("## Si tu es empêché\n", 1)[1].split("\n## ", 1)[0]
    assert section.startswith(SI_EMPECHE) and section.count(SI_EMPECHE) == 1
    assert "fiche de relais" not in section and "dans les deux cas" not in section
    for refuses in ((), ("Bash(git push)",)):  # la même règle, une fois, dans chaque reprise
        reprise = consigne_reprise(tache(), "verdict", "Refusé.", PROFIL, refuses)
        assert reprise.count(SI_EMPECHE) == 1, refuses
        assert (
            f"{SI_EMPECHE}d'aller au bout de la tâche, écris-le dans ton compte rendu par une "
            f"ligne « {MARQUE_EMPECHE} » ; sinon fais sans"
        ) in reprise


@pytest.mark.parametrize("copie_jetable", [True, False])
def test_le_verificateur_ne_signale_un_refus_que_s_il_n_a_pas_pu_conclure_sans(copie_jetable):
    for nom, texte in verifications(copie_jetable).items():
        assert (
            f"{SI_EMPECHE}de vérifier un critère, écris-le dans ton verdict par une ligne "
            f"« {MARQUE_EMPECHE} » ; sinon fais sans, et dis-le au même endroit, sans cette ligne."
        ) in texte, nom
        assert texte.count(SI_EMPECHE) == 1, nom
        assert "même si tu as pu conclure par un autre moyen" not in texte, nom


@pytest.mark.parametrize("copie_jetable", [True, False])
def test_les_trois_verifications_savent_signaler_un_empechement(copie_jetable):
    for nom, texte in verifications(copie_jetable).items():
        assert f"« {MARQUE_EMPECHE} », au tout début de la ligne" in texte, nom
        assert lignes_qui_commencent_par_la_marque(texte), nom
        assert 'champ "empeche" du JSON' in texte and '"empeche": [' in texte, nom
        assert "relancerait" in texte, nom


# --- les textes partagés ---------------------------------------------------------------------


def test_les_regles_de_decoupage_sont_dans_les_deux_textes_de_l_orchestrateur():
    assert REGLES_DECOUPAGE in consigne_planification("Objectif", PROFIL)
    assert REGLES_DECOUPAGE in ROLE_ORCHESTRATEUR


def test_les_commandes_simples_sont_chez_l_ouvrier_et_chez_les_verificateurs():
    assert COMMANDES_SIMPLES in consigne_ouvrier(tache(), CONTRAT, PROFIL)
    assert COMMANDES_SIMPLES in COPIE_JETABLE
    for nom, texte in verifications(True).items():
        assert COMMANDES_SIMPLES in texte, nom
    textes = verifications(False)
    assert COMMANDES_SIMPLES in textes["reverification"]
    assert COMMANDES_SIMPLES in textes["bornee"]


# --- le fichier que chaque tâche voudrait toucher --------------------------------------------


def test_le_decoupage_sort_le_fichier_commun_des_taches_et_le_confie_au_raccord():
    assert (
        "ce fichier n'entre dans le périmètre d'aucune autre tâche que celle de raccord"
        in REGLES_DECOUPAGE
    )
    assert "`chantier/relais/<id de la tâche>.md`" in REGLES_DECOUPAGE
    assert "La tâche de raccord dépend de ces tâches et recopie ces lignes" in REGLES_DECOUPAGE
    assert "écris-le dans ses critères" in REGLES_DECOUPAGE


def test_le_decoupage_dit_pourquoi_une_dependance_est_vraie():
    assert "Chaque tâche est contrôlée seule" in REGLES_DECOUPAGE
    assert "avec toute la suite de tests du projet" in REGLES_DECOUPAGE


def test_l_ouvrier_ne_touche_pas_le_fichier_commun_et_l_ecrit_dans_sa_fiche():
    texte = consigne_ouvrier(tache(), CONTRAT, {"regles": ["Une ligne à DECISIONS.md."]})
    assert "Une ligne à DECISIONS.md." in texte
    assert "hors de ton périmètre" in texte and "ne le touche pas" in texte
    assert "`chantier/relais/B2.md` est toujours permis" in texte


@pytest.mark.parametrize("copie_jetable", [True, False])
def test_les_trois_verifications_savent_que_la_fiche_de_relais_n_est_pas_un_debord(copie_jetable):
    assert "`chantier/relais/`" in RELAIS_PERMIS
    assert "ne comptent jamais comme un débord de périmètre" in RELAIS_PERMIS
    for nom, texte in verifications(copie_jetable).items():
        perimetre = texte.split("## Périmètre autorisé\n", 1)[1].split("\n\n", 1)[0]
        assert perimetre == "b.py, tests/test_b.py\n" + RELAIS_PERMIS, nom


def test_la_fiche_de_relais_est_hors_de_tout_perimetre():
    assert "chantier/relais/*" in TOUJOURS_PERMIS
    assert hors_perimetre(["chantier/relais/B2.md", "b.py"], ["b.py"]) == []


def test_la_fiche_de_relais_d_une_tache_entre_dans_la_branche_principale(tmp_path):
    """La règle du fichier commun repose là-dessus : la tâche de raccord relit ces fiches."""

    def git(*arguments):
        resultat = subprocess.run(
            ["git", *arguments], cwd=tmp_path, check=True, capture_output=True, text=True
        )
        return resultat.stdout

    git("init", "-q", "-b", "main")
    git("config", "user.name", "Essai")
    git("config", "user.email", "essai@example.invalid")
    (tmp_path / "LISEZMOI.md").write_text("socle\n", "utf-8")
    git("add", "-A")
    git("commit", "-q", "-m", "socle")
    t, controles = tache(), ControlesGit(tmp_path)
    copie = controles.preparer(t)
    (copie / "b.py").write_text("X = 1\n", "utf-8")
    (copie / "chantier" / "relais").mkdir(parents=True)
    (copie / "chantier" / "relais" / "B2.md").write_text("Ligne pour le journal.\n", "utf-8")

    assert hors_perimetre(controles.fichiers_modifies(t, copie, None), t.perimetre) == []
    assert controles.enregistrer(t, copie) == ""
    assert git("show", "main:chantier/relais/B2.md") == "Ligne pour le journal.\n"


# --- la lecture du verdict -------------------------------------------------------------------


def test_un_verdict_d_aujourd_hui_se_lit_exactement_comme_avant():
    verdict = lire_verdict('Vu.\n{"valide": false, "motif": "ne_sait_pas", "resume": " Faux. "}')
    assert verdict == {"valide": False, "motif": "ne_sait_pas", "resume": "Faux."}
    assert lire_verdict("Pas de JSON.") == {
        "valide": False,
        "motif": "ne_sait_pas",
        "resume": "Le vérificateur n'a pas rendu de verdict lisible.",
    }


def test_le_verdict_rend_remarques_et_empeche_quand_ils_sont_la():
    texte = (
        'Vu.\n{"valide": true, "motif": "bacle", "resume": "Bon.", '
        '"remarques": ["Un nom peu clair.", " Une docstring vide. "], '
        '"empeche": "mutmut — commande refusée"}'
    )
    assert lire_verdict(texte) == {
        "valide": True,
        "motif": "bacle",
        "resume": "Bon.",
        "remarques": ["Un nom peu clair.", "Une docstring vide."],
        "empeche": ["mutmut — commande refusée"],
    }


@pytest.mark.parametrize("valeur", ['""', "[]", '[1, null, "  "]', '{"a": 1}', "3", "null"])
def test_des_champs_facultatifs_vides_ou_mal_formes_ne_figurent_pas(valeur):
    texte = f'{{"valide": false, "motif": "bacle", "resume": "Non.", "remarques": {valeur}, '
    texte += f'"empeche": {valeur}}}'
    assert lire_verdict(texte) == {"valide": False, "motif": "bacle", "resume": "Non."}


def test_un_verdict_illisible_garde_son_empechement():
    verdict = lire_verdict('{"empeche": ["uv run pytest -q — commande refusée"]}')
    assert verdict["valide"] is False and verdict["motif"] == "ne_sait_pas"
    assert verdict["empeche"] == ["uv run pytest -q — commande refusée"]


# --- le diagnostic d'un blocage --------------------------------------------------------------


def test_le_message_de_diagnostic_cite_la_tache_les_preuves_et_les_empechements():
    preuves = [
        {"tentative": 1, "origine": "controles", "issue": "ne_sait_pas", "detail": "uv refusé"},
        "Les contrôles automatiques échouent : uv introuvable",
    ]
    texte = message_de_diagnostic(tache(), preuves, ["uv run pytest -q — commande refusée"])
    assert texte.startswith(f"{MARQUE_BLOCAGE} : tâche B2]")
    assert "B2 — Lire le profil" in texte and "1. Rend 42." in texte
    assert "1. tentative 1, controles, ne_sait_pas : uv refusé" in texte
    assert "2. Les contrôles automatiques échouent : uv introuvable" in texte
    assert "- uv run pytest -q — commande refusée" in texte
    assert "bloc atelier-outils" in texte and "« commandes_permises »" in texte
    assert "Permettre une commande reste la décision de la personne" in texte


def test_le_diagnostic_ne_cite_que_les_derniers_refus_chacun_par_sa_fin():
    preuves = [f"refus n°{i}" for i in range(1, 8)]
    preuves[-1] = "DEBUT-DU-REFUS" + "x" * 5000 + "refus n°7"
    texte = message_de_diagnostic(tache(), preuves, [])
    assert PREUVES_MAX == 5
    assert "refus n°1" not in texte and "refus n°2" not in texte
    assert all(f"refus n°{i}" in texte for i in range(3, 8))
    assert "DEBUT-DU-REFUS" not in texte


def test_le_diagnostic_sans_empechement_dit_que_les_refus_se_repetent():
    texte = message_de_diagnostic(tache(), ["Refusé."], [])
    assert "aucun n'a été signalé : ce sont les refus qui se répètent" in texte


def test_le_role_de_l_orchestrateur_dit_ce_qu_attend_le_message_de_blocage():
    blocage = ROLE_ORCHESTRATEUR.split("Blocage. ", 1)[1].split("\n\n", 1)[0]
    assert f"« {MARQUE_BLOCAGE} »" in blocage
    assert "Cherche la cause" in blocage and "bloc atelier-outils" in blocage
    assert "Permettre une" in blocage and "reste sa décision" in blocage


# --- seul un vrai `true` vaut accord ---------------------------------------------------------


def test_un_vrai_true_vaut_accord():
    verdict = lire_verdict('Vu.\n{"valide": true, "motif": "bacle", "resume": " Tout est fait. "}')
    assert verdict["valide"] is True
    assert verdict["resume"] == "Tout est fait."


@pytest.mark.parametrize(
    "valeur",
    ['"false"', '"true"', '"oui"', '""', "1", "0", "1.0", "null", "[]", "[true]", "{}", '{"a": 1}'],
)
def test_toute_autre_valeur_que_true_vaut_refus(valeur):
    assert lire_verdict('{"valide": %s, "motif": "consigne"}' % valeur)["valide"] is False


def test_un_refus_en_chaine_garde_le_motif_et_le_resume_comme_un_refus_ordinaire():
    texte = '{"valide": "false", "motif": "consigne", "resume": "  Il manque un test.  "}'
    assert lire_verdict(texte) == {
        "valide": False,
        "motif": "consigne",
        "resume": "Il manque un test.",
    }
    inconnu = '{"valide": "oui", "motif": "n_importe_quoi", "resume": " Non. "}'
    assert lire_verdict(inconnu) == {"valide": False, "motif": "bacle", "resume": "Non."}


def test_un_verdict_sans_cle_valide_reste_illisible():
    verdict = lire_verdict('{"motif": "bacle", "resume": "x"}')
    assert verdict["valide"] is False and verdict["motif"] == "ne_sait_pas"


# =============================================================================================
# M2 : une preuve par critère, des contrôles non rejoués, le verdict « local », la sous-tâche.
# =============================================================================================

SORTIE = "DEBUT-DE-LA-SORTIE" + "." * 3000 + "1793 passed in 301.20s"
FIN_DE_SORTIE = SORTIE[-SORTIE_BORNEE:]


def empreinte(texte):
    return hashlib.sha256(texte.encode("utf-8")).hexdigest()


def section(texte, titre):
    """Le corps d'une section « ## titre », jusqu'à la suivante."""
    return texte.split(f"## {titre}\n", 1)[1].split("\n## ", 1)[0]


def avec_sortie(copie_jetable, profil=PROFIL, sortie=SORTIE):
    """Les deux vérifications qui reçoivent la sortie des contrôles de l'Atelier."""
    t = tache()
    return {
        "complete": consigne_verificateur(
            t, CONTRAT, profil, copie_jetable, sortie_controles=sortie
        ),
        "reverification": consigne_reverification(
            t, CONTRAT, profil, "Refusé.", copie_jetable, sortie_controles=sortie
        ),
    }


# --- le texte d'aujourd'hui, figé -------------------------------------------------------------
#
# Ces empreintes (SHA-256) sont celles des textes que rendait le code du commit 56710b3, avant
# M2, pour la tâche `tache()` et `PROFIL` ci-dessus : `git show 56710b3:atelier/consignes.py`
# les redonne. Un caractère changé dans un texte appelé sans les nouveaux paramètres change son
# empreinte. Les tests plus haut en gardent déjà une partie (le cadre, le périmètre, la règle
# d'empêchement, le verdict en `rendu`, SORTIE_BORNEE), mais aucun ne fige un texte entier.
TEXTES_D_AUJOURD_HUI = {
    ("complete", True): "6eaab7e9de6bd69eec75b1f58171b6a380e6823c9d1f6f5d615ea84527062cb2",
    ("complete", False): "0c76a9cdce6982cdd6ad173c4a0283ffbaa339386ce35d780b4600254ac3f684",
    ("reverification", True): "6b87d41a07f2d066e6a79d8b1b92d830a300e0e43590ab06954672474a926b9d",
    ("reverification", False): "c2a3e6a69c0ee0a1d9a013f99bb4277f0015f4ddef36e5b28039ef23ef03308d",
    ("bornee", True): "05fb06144d5803b3cf7c576ba609612a2a56a65858ef66d67879d2dc1548744f",
    ("bornee", False): "a04320693dbd402ec87f4f80bd71beded725cbec8fe1310bda6765c0cdd9ee24",
}


@pytest.mark.parametrize(("nom", "copie_jetable"), list(TEXTES_D_AUJOURD_HUI))
def test_sans_les_nouveaux_parametres_les_verifications_rendent_le_texte_d_avant(
    nom, copie_jetable
):
    texte = verifications(copie_jetable)[nom]
    assert empreinte(texte) == TEXTES_D_AUJOURD_HUI[(nom, copie_jetable)]


def test_les_autres_formes_d_appel_rendent_aussi_le_texte_d_avant():
    t = tache()
    assert empreinte(consigne_verificateur(t, CONTRAT, PROFIL, True, "- `a.py`")) == (
        "4d33929d17cdf38cb574655860a6ee6ca77728dea272ff8c585cc132d72140c2"
    )
    assert empreinte(consigne_verificateur(t, CONTRAT, PROFIL, False, "- `a.py`")) == (
        "eaff2e1627df669bbc97cc7cfac27318ca40c98d951a94b9e92f485e114b98d3"
    )
    assert empreinte(consigne_verificateur(t, CONTRAT, {})) == (
        "ddd309d9ecfb7f0ae8edbaf320af0ee88ae207dc111ddc69b8cc325bc8ea504d"
    )
    assert empreinte(consigne_reverification(t, CONTRAT, {}, "Refusé.")) == (
        "491d5804748db2eb21edcec8c43b399ea8ef69715f50e4aae9200e3cd6bbe656"
    )
    assert empreinte(consigne_reverification(t, CONTRAT, {}, "Refusé.", True)) == (
        "3ab6d35976b3e144210322579aeab70c99c39c8e4ff76e46ee02c2f8f116cb7a"
    )


def test_les_nouveaux_parametres_ont_une_valeur_par_defaut_qui_ne_change_rien():
    # Absent ou égal à sa valeur par défaut : la même consigne ; celle d'avant est figée plus haut.
    t = tache()
    for fonction, args in (
        (consigne_verificateur, ()),
        (consigne_reverification, ("Refusé.",)),
    ):
        defaut = inspect.signature(fonction).parameters["sortie_controles"].default
        assert defaut is None
        assert fonction(t, CONTRAT, PROFIL, *args) == fonction(
            t, CONTRAT, PROFIL, *args, sortie_controles=defaut
        )
    assert inspect.signature(consigne_reverification).parameters["fichiers"].default is None
    assert inspect.signature(consigne_ouvrier).parameters["sur_place"].default is False


# --- critère 1 : une ligne par critère, avec la preuve ----------------------------------------


def test_l_ouvrier_relit_la_mission_et_prouve_chaque_critere_avant_de_rendre():
    rendre = section(consigne_ouvrier(tache(), CONTRAT, PROFIL), "À rendre")
    assert RELECTURE in rendre
    assert "relis la mission du début à la fin" in rendre
    assert "Pour chaque critère, écris dans ton compte rendu une ligne" in rendre
    assert "la preuve que tu as constatée toi-même" in rendre
    assert "la commande lancée et son résultat" in rendre
    # Ce qu'il n'a pas pu faire : écrit aussi, avec la raison exacte, et jamais passé sous silence.
    assert "Un critère que tu n'as pas pu remplir ou prouver, écris-le aussi" in rendre
    assert "sa raison exacte" in rendre and "passé sous silence fait refuser" in rendre
    assert "Fait (une ligne par critère, avec la preuve)" in rendre


def test_la_preuve_par_critere_est_demandee_une_fois_et_en_fin_de_consigne():
    texte = consigne_ouvrier(tache(), CONTRAT, PROFIL)
    assert texte.count(RELECTURE) == 1
    assert texte.index(RELECTURE) > texte.index("## À rendre")
    assert texte.rstrip().endswith("Doutes et demandes.")
    # La reprise dans la session de l'ouvrier ne la répète pas : il a déjà sa consigne.
    assert RELECTURE not in consigne_reprise(tache(), "verdict", "Refusé.", PROFIL)


# --- critère 2 : le travail précédent est resté dans le dossier --------------------------------


def test_sur_place_dit_que_le_travail_est_reste_et_qu_il_faut_le_reprendre():
    texte = consigne_ouvrier(tache(), CONTRAT, PROFIL, "Il manque la preuve du critère 2.", True)
    precedent = section(texte, "Tentative précédente")
    assert SUR_PLACE in precedent
    assert "d'un passage précédent est resté dans le dossier courant" in precedent
    assert "`git status` et `git diff`" in precedent
    assert "Ne recommence pas de zéro : reprends ce travail" in precedent
    assert "corrige seulement ce qui est relevé" in precedent
    assert precedent.endswith("Voici ce qui a été relevé :\nIl manque la preuve du critère 2.\n")
    assert "état propre" not in texte  # la phrase d'un départ à neuf dirait le contraire


def test_sur_place_sans_remarque_le_dit_quand_meme_sans_annoncer_une_liste_vide():
    texte = consigne_ouvrier(tache(), CONTRAT, PROFIL, sur_place=True)
    precedent = section(texte, "Tentative précédente")
    assert precedent.strip() == SUR_PLACE
    assert "Voici ce qui a été relevé" not in texte


def test_sans_sur_place_la_phrase_du_travail_reste_est_absente():
    for remarques in ("", "Trop lent."):
        texte = consigne_ouvrier(tache(), CONTRAT, PROFIL, remarques)
        assert SUR_PLACE not in texte and "est resté dans le dossier" not in texte
        assert "Ne recommence pas de zéro" not in texte
    avec = consigne_ouvrier(tache(), CONTRAT, PROFIL, "Trop lent.")
    assert section(avec, "Tentative précédente") == (
        "Une tentative précédente a été refusée. Tu repars d'un état propre. "
        "Voici ce qui a été relevé :\nTrop lent.\n"
    )
    assert "Tentative précédente" not in consigne_ouvrier(tache(), CONTRAT, PROFIL)


def test_sur_place_ne_change_que_la_section_du_passage_precedent():
    sans = consigne_ouvrier(tache(), CONTRAT, PROFIL, "Trop lent.")
    avec = consigne_ouvrier(tache(), CONTRAT, PROFIL, "Trop lent.", True)
    retire = section(sans, "Tentative précédente")
    remplace = section(avec, "Tentative précédente")
    assert sans.replace(retire, remplace) == avec


# --- critères 3 et 4 : les contrôles que l'Atelier vient de jouer ----------------------------


@pytest.mark.parametrize("copie_jetable", [True, False])
def test_le_verificateur_recoit_le_resultat_des_controles_et_ne_les_rejoue_pas(copie_jetable):
    for nom, texte in avec_sortie(copie_jetable).items():
        assert FIN_DE_SORTIE in texte, nom
        assert SORTIE[-SORTIE_BORNEE - 1 :] not in texte, nom  # la fin seulement
        assert "DEBUT-DE-LA-SORTIE" not in texte, nom
        assert "- `pytest -q`\n- `ruff check .`" in texte, nom
        assert "L'Atelier vient de jouer lui-même les commandes de contrôle" in texte, nom
        assert "Ne rejoue aucune de ces commandes, ni la suite de tests entière" in texte, nom
        assert "Tiens ce résultat pour constaté" in texte, nom
        # L'ancienne demande, qui dirait le contraire, n'y est plus.
        assert "Lance les commandes de contrôle" not in texte, nom
        assert "L'Atelier a rejoué après la correction" not in texte, nom


@pytest.mark.parametrize("copie_jetable", [True, False])
def test_le_verificateur_produit_lui_meme_une_preuve_absente_au_lieu_de_refuser(copie_jetable):
    for nom, texte in avec_sortie(copie_jetable).items():
        assert PREUVE_MANQUANTE in texte, nom
        assert "ne montre pas la preuve d'un critère, ne refuse pas pour cela seul" in texte, nom
        assert "produis la preuve toi-même" in texte, nom
        # La règle entière : quand refuser, et quand le critère est tenu.
        assert "Si elle passe, le critère est tenu" in texte, nom
        assert "Refuse quand la preuve échoue ou quand le travail manque" in texte, nom
        # Une preuve impossible n'est jamais un critère tenu, quelle que soit la raison donnée.
        assert "Si tu ne peux pas produire la preuve toi-même, le critère n'est pas tenu" in texte
        assert "et tu refuses, quelle que soit la raison que l'agent donne" in texte
        assert 'sert seulement à choisir le motif, ou à remplir "empeche"' in texte
        assert "que l'agent n'en donne pas la raison" not in texte  # l'ancienne porte de sortie


def test_sans_sortie_des_controles_aucune_de_ces_regles_n_est_demandee():
    for copie_jetable in (True, False):
        for nom, texte in verifications(copie_jetable).items():
            assert "produis la preuve toi-même" not in texte, nom
            assert "ne refuse pas pour cela seul" not in texte, nom
            assert "Ne rejoue aucune de ces commandes" not in texte, nom
            assert "L'Atelier vient de jouer lui-même" not in texte, nom


def test_une_sortie_vide_est_dite_et_ne_laisse_pas_un_blanc():
    for nom, texte in avec_sortie(False, sortie="").items():
        vide = "[début de la sortie]\n(les commandes n'ont rien affiché)\n[fin de la sortie]"
        assert vide in texte, nom
        assert "Ne rejoue aucune de ces commandes" in texte, nom


def test_sans_commande_de_controle_l_atelier_n_a_rien_joue_mais_la_preuve_reste_a_produire():
    for nom, texte in avec_sortie(False, profil={}).items():
        assert "n'a pas de commande de contrôle : l'Atelier n'a rien fait passer" in texte, nom
        assert "[début de la sortie]" not in texte and "Ne rejoue aucune" not in texte, nom
        assert PREUVE_MANQUANTE in texte, nom


@pytest.mark.parametrize("copie_jetable", [True, False])
def test_avec_la_sortie_des_controles_le_cadre_et_les_regles_communes_restent(copie_jetable):
    for nom, texte in avec_sortie(copie_jetable).items():
        assert texte.count(SI_EMPECHE) == 1, nom
        assert f"« {MARQUE_EMPECHE} », au tout début de la ligne" in texte, nom
        assert 'champ "empeche" du JSON' in texte and '"empeche": [' in texte, nom
        # Comme aujourd'hui : la vérification complète en lecture seule n'a pas cette règle.
        if copie_jetable or nom != "complete":
            assert COMMANDES_SIMPLES in texte, nom
        assert SUIVI in texte, nom
        assert RELAIS_PERMIS in texte, nom
        assert "1. Rend 42.\n2. Refuse -1." in texte, nom
        assert ("copie jetable" in texte) is copie_jetable, nom


def test_la_reverification_garde_ses_etapes_et_ajoute_les_controles_a_la_quatrieme():
    textes = avec_sortie(False)
    texte = textes["reverification"]
    assert "Pour chaque point recalé, vérifie par toi-même qu'il est corrigé" in texte
    assert "Ne refais pas le reste de la vérification" in texte
    etape4 = texte.split("\n4. ", 1)[1].split("\n\n## Suivi", 1)[0]
    assert etape4.startswith("L'Atelier vient de jouer lui-même")
    assert etape4.endswith(PREUVE_MANQUANTE) and "\n5. " in etape4
    complete = textes["complete"]
    assert complete.split("\n5. ", 1)[1].startswith("L'Atelier vient de jouer lui-même")
    assert "\n6. " + PREUVE_MANQUANTE in complete


# --- critère 5 : les fichiers de la retouche -------------------------------------------------


@pytest.mark.parametrize("copie_jetable", [True, False])
def test_la_reverification_nomme_les_fichiers_changes_et_ne_juge_que_ce_qu_ils_touchent(
    copie_jetable,
):
    t = tache()
    texte = consigne_reverification(
        t, CONTRAT, PROFIL, "Refusé.", copie_jetable, fichiers=["b.py", "tests/test_b.py"]
    )
    touche = section(texte, "Ce que la retouche a touché")
    assert "- `b.py`\n- `tests/test_b.py`" in touche
    assert "Ne juge que ce que la retouche touche : ces fichiers, et ce qui en dépend" in touche
    assert "a déjà été jugé au tour précédent" in touche
    # Ne pas chercher ailleurs n'oblige pas à ignorer un défaut bloquant vu en chemin.
    assert "Si tu vois pourtant en chemin un défaut qui bloquerait" in texte
    assert "recale pour lui aussi" in texte
    assert "ne refuse pas pour un défaut" not in texte
    assert "Recale seulement pour un point" not in texte
    assert texte.index("## Ce que la retouche a touché") < texte.index("## Ce que tu dois faire")


def test_sans_fichiers_la_reverification_ne_juge_pas_moins():
    t = tache()
    sans = consigne_reverification(t, CONTRAT, PROFIL, "Refusé.")
    assert "Ce que la retouche a touché" not in sans and "ne juge que ce que" not in sans
    assert "Si tu vois pourtant en chemin un défaut qui bloquerait" in sans
    # Une liste vide ne nomme rien : le texte reste celui d'avant.
    assert consigne_reverification(t, CONTRAT, PROFIL, "Refusé.", fichiers=[]) == sans
    assert empreinte(sans) == TEXTES_D_AUJOURD_HUI[("reverification", False)]


def test_les_fichiers_et_les_controles_se_combinent_sans_se_gener():
    t = tache()
    deux = consigne_reverification(
        t, CONTRAT, PROFIL, "Refusé.", sortie_controles=SORTIE, fichiers=["b.py"]
    )
    assert "- `b.py`" in deux and FIN_DE_SORTIE in deux and PREUVE_MANQUANTE in deux
    assert '"meme_defaut"' in deux
    seul = consigne_reverification(t, CONTRAT, PROFIL, "Refusé.", fichiers=["b.py"])
    assert FIN_DE_SORTIE not in seul and PREUVE_MANQUANTE not in seul
    assert rendu(seul) == rendu(consigne_reverification(t, CONTRAT, PROFIL, "Refusé."))


# --- critère 6 : le verdict « local », les points à corriger, « meme_defaut » ----------------


def json_demande(texte):
    """La ligne d'objet JSON que le vérificateur doit rendre, telle que la consigne la décrit."""
    return next(ligne for ligne in rendu(texte).splitlines() if ligne.startswith('{"valide"'))


def cles_demandees(texte):
    return set(re.findall(r'"(\w+)":', json_demande(texte)))


@pytest.mark.parametrize("copie_jetable", [True, False])
def test_avec_la_sortie_des_controles_le_verdict_dit_local_reste_et_fichiers(copie_jetable):
    for nom, texte in avec_sortie(copie_jetable).items():
        verdict = rendu(texte)
        assert '"motif": "bacle" ou "local" ou "ne_sait_pas" ou "consigne"' in verdict, nom
        assert '"reste": ["un point à corriger"]' in verdict, nom
        assert '"fichiers": ["chemin/du/fichier"]' in verdict, nom
        assert '- "local" : un défaut précis, à un endroit que tu nommes' in verdict, nom
        assert "le reste du travail est conforme et tu l'as constaté" in verdict, nom
        assert "une retouche ne suffirait pas" in verdict, nom  # ne_sait_pas : le fond est faux
        # « bacle » et « local » nomment ce qui reste ; les autres motifs laissent les listes vides.
        assert 'Pour "bacle" et "local", remplis "reste" et "fichiers"' in verdict, nom
        assert "Cet agent ne recevra que cela" in verdict, nom
        assert 'laisse "reste" et "fichiers" vides' in verdict, nom
        assert '"empeche"' in verdict, nom


def test_meme_defaut_n_est_demande_qu_a_la_verification_d_une_retouche():
    textes = avec_sortie(False)
    assert "meme_defaut" not in textes["complete"]
    retouche = rendu(textes["reverification"])
    assert '"fichiers": ["chemin/du/fichier"], "meme_defaut": true ou false}' in retouche
    # La règle entière : vrai quand rien n'est corrigé, faux dès qu'un point l'est, ou autre refus.
    assert "true seulement si aucun des points relevés au verdict précédent n'est" in retouche
    assert "corrigé ; false dès qu'un de ces points au moins est corrigé." in retouche
    # Un refus pour autre chose se dit dans « reste » ; il ne contredit pas « meme_defaut ».
    assert 'Si tu refuses aussi pour autre chose, écris-le dans "reste"' in retouche
    assert "ou que ton refus porte sur autre chose" not in retouche


def test_sans_la_sortie_des_controles_le_verdict_ne_demande_rien_de_plus():
    for copie_jetable in (True, False):
        for nom, texte in verifications(copie_jetable).items():
            for mot in ('"local"', '"reste"', '"fichiers"', "meme_defaut"):
                assert mot not in texte, (nom, mot)
            assert JSON_DU_VERDICT in rendu(texte), nom
    # Les fichiers d'une retouche n'ouvrent pas la demande : le moteur ne la lit pas sans les
    # contrôles.
    t = tache()
    seul = consigne_reverification(t, CONTRAT, PROFIL, "Refusé.", fichiers=["b.py"])
    assert "meme_defaut" not in seul and '"reste"' not in seul and '"local"' not in seul


@pytest.mark.parametrize("copie_jetable", [True, False])
def test_ce_que_la_consigne_demande_est_ce_que_lire_verdict_lit(copie_jetable):
    textes = avec_sortie(copie_jetable)
    attendues = {"valide", "motif", "resume", "reste", "fichiers"}
    assert cles_demandees(textes["complete"]) == attendues
    assert cles_demandees(textes["reverification"]) == attendues | {"meme_defaut"}
    for texte in textes.values():
        motifs = re.findall(r'"(\w+)"', json_demande(texte).split('"motif": ', 1)[1].split(",")[0])
        assert motifs == ["bacle", "local", "ne_sait_pas", "consigne"]
        for motif in motifs:  # chaque motif décrit est un motif que l'Atelier reconnaît
            lu = lire_verdict('{"valide": false, "motif": "%s", "resume": "x"}' % motif)
            assert lu["motif"] == motif
    plein = (
        '{"valide": false, "motif": "local", "resume": "x", "reste": ["a"], '
        '"fichiers": ["f.py"], "meme_defaut": true}'
    )
    assert {"reste", "fichiers", "meme_defaut"} <= set(lire_verdict(plein))


def test_la_verification_bornee_n_est_pas_changee_par_le_verdict_complet():
    # M2 ne demande rien à la vérification bornée : elle garde son verdict, sans « local ».
    for copie_jetable in (True, False):
        texte = verifications(copie_jetable)["bornee"]
        assert JSON_DU_VERDICT in texte and '"local"' not in texte and '"reste"' not in texte


# --- critère 7 : le motif « local » -----------------------------------------------------------


@pytest.mark.parametrize("motif", ["bacle", "local", "ne_sait_pas", "consigne"])
def test_lire_verdict_garde_chaque_motif_connu(motif):
    texte = '{"valide": false, "motif": "%s", "resume": "Non."}' % motif
    assert lire_verdict(texte) == {"valide": False, "motif": motif, "resume": "Non."}


@pytest.mark.parametrize(
    "motif", ['"Local"', '"locale"', '""', "null", "1", '["local"]', '"n_importe"']
)
def test_un_motif_inconnu_ou_mal_ecrit_vaut_bacle(motif):
    texte = '{"valide": false, "motif": %s, "resume": "Non."}' % motif
    assert lire_verdict(texte)["motif"] == "bacle"
    assert lire_verdict('{"valide": false, "resume": "Non."}')["motif"] == "bacle"


# --- critère 8 : reste, fichiers, meme_defaut -------------------------------------------------


def test_un_verdict_qui_remplit_reste_fichiers_et_meme_defaut_les_rend():
    texte = (
        'Vu.\n{"valide": false, "motif": "local", "resume": " Un cas oublié. ", '
        '"reste": [" Traiter le cas nul dans f() de a.py. ", "Ajouter son test."], '
        '"fichiers": ["a.py", "tests/test_a.py"], "meme_defaut": true}'
    )
    assert lire_verdict(texte) == {
        "valide": False,
        "motif": "local",
        "resume": "Un cas oublié.",
        "reste": ["Traiter le cas nul dans f() de a.py.", "Ajouter son test."],
        "fichiers": ["a.py", "tests/test_a.py"],
        "meme_defaut": True,
    }


def test_chaque_champ_se_lit_seul_et_les_autres_restent_absents():
    base = '{"valide": false, "motif": "bacle", "resume": "Non.", '
    seul_reste = lire_verdict(base + '"reste": ["x"]}')
    assert seul_reste["reste"] == ["x"] and "fichiers" not in seul_reste
    assert "meme_defaut" not in seul_reste
    seul_fichiers = lire_verdict(base + '"fichiers": ["a.py"]}')
    assert seul_fichiers["fichiers"] == ["a.py"] and "reste" not in seul_fichiers
    seul_meme = lire_verdict(base + '"meme_defaut": true}')
    assert seul_meme["meme_defaut"] is True
    assert "reste" not in seul_meme and "fichiers" not in seul_meme


# Ce qu'un verdict d'aujourd'hui rend : aucune clé de plus, qu'il ait ou non les champs vides.
VERDICTS_D_AUJOURD_HUI = [
    ('{"valide": true, "motif": "bacle", "resume": "Bon."}', "bacle", True, "Bon."),
    ('{"valide": false, "motif": "consigne", "resume": " Flou. "}', "consigne", False, "Flou."),
    ('{"valide": false, "motif": "ne_sait_pas"}', "ne_sait_pas", False, ""),
    ('{"valide": false, "motif": "bacle", "reste": [], "fichiers": []}', "bacle", False, ""),
    ('{"valide": false, "motif": "bacle", "reste": ["  "], "fichiers": [""]}', "bacle", False, ""),
    ('{"valide": false, "motif": "bacle", "meme_defaut": false}', "bacle", False, ""),
    ('{"valide": true, "meme_defaut": false, "reste": [], "fichiers": []}', "bacle", True, ""),
]


@pytest.mark.parametrize(("texte", "motif", "valide", "resume"), VERDICTS_D_AUJOURD_HUI)
def test_un_verdict_d_aujourd_hui_rend_le_meme_dictionnaire_sans_cle_de_plus(
    texte, motif, valide, resume
):
    assert lire_verdict("Vu.\n" + texte) == {"valide": valide, "motif": motif, "resume": resume}


def test_un_verdict_illisible_ne_porte_ni_reste_ni_fichiers_ni_meme_defaut():
    texte = '{"reste": ["a"], "fichiers": ["a.py"], "meme_defaut": true}'
    assert lire_verdict(texte) == {
        "valide": False,
        "motif": "ne_sait_pas",
        "resume": "Le vérificateur n'a pas rendu de verdict lisible.",
    }
    assert lire_verdict("Pas de JSON.") == lire_verdict("")


# Une valeur mal formée est ignorée sans erreur : la clé est absente, ou l'élément retiré.
VALEURS_MAL_FORMEES = [
    ('"un seul point"', None),  # un texte à la place d'une liste
    ('""', None),
    ("3", None),
    ("1.5", None),
    ("true", None),
    ("null", None),
    ('{"a": "b"}', None),  # un objet à la place d'une liste
    ("[]", None),
    ('[""]', None),
    ('["  ", "\\n"]', None),
    ("[1, 2]", None),  # des éléments qui ne sont pas des textes
    ("[null, true]", None),
    ('[["a"], {"b": 1}]', None),
    ('["a", 3]', ["a"]),  # un élément bon, un mauvais : le mauvais est retiré
    ('[3, "a", null, " b ", ""]', ["a", "b"]),
    ('[["a"], "b"]', ["b"]),
]


@pytest.mark.parametrize(("valeur", "attendu"), VALEURS_MAL_FORMEES)
@pytest.mark.parametrize("cle", ["reste", "fichiers"])
def test_un_reste_ou_des_fichiers_mal_formes_sont_ignores_sans_erreur(cle, valeur, attendu):
    texte = '{"valide": false, "motif": "bacle", "resume": "Non.", "%s": %s}' % (cle, valeur)
    verdict = lire_verdict(texte)
    if attendu is None:
        assert cle not in verdict
        assert verdict == {"valide": False, "motif": "bacle", "resume": "Non."}
    else:
        assert verdict[cle] == attendu


@pytest.mark.parametrize(
    "valeur",
    ['"true"', '"oui"', '"vrai"', "1", "1.0", "0", "false", '""', "null", "[]", "[true]", "{}"],
)
def test_meme_defaut_n_est_vrai_que_pour_le_booleen_json_true(valeur):
    texte = '{"valide": false, "motif": "bacle", "resume": "Non.", "meme_defaut": %s}' % valeur
    assert lire_verdict(texte) == {"valide": False, "motif": "bacle", "resume": "Non."}
    vrai = lire_verdict(texte.replace(valeur, "true"))
    assert vrai["meme_defaut"] is True


def test_les_nouveaux_champs_se_lisent_avec_remarques_et_empeche():
    texte = (
        '{"valide": false, "motif": "local", "resume": "Non.", "reste": ["a"], '
        '"fichiers": ["a.py"], "remarques": ["r"], "empeche": ["e"], "meme_defaut": true}'
    )
    assert lire_verdict(texte) == {
        "valide": False,
        "motif": "local",
        "resume": "Non.",
        "reste": ["a"],
        "fichiers": ["a.py"],
        "remarques": ["r"],
        "empeche": ["e"],
        "meme_defaut": True,
    }


# --- critère 9 : la sous-tâche ----------------------------------------------------------------

RESTE = [
    "Dans b.py, f() ne refuse pas -1 : lever ValueError, comme le critère 2 le demande.",
    "Ajouter dans tests/test_b.py le test qui le prouve.",
]


def sous_tache(**champs):
    reglages = {"pourquoi": "Lire sans surprise.", "fournit": "b.lire()", "attend": "a.py"}
    profil = {"regles": ["Pas de secret dans le code."], "commandes": ["pytest -q"]}
    contrat = Contrat(objectif="But du chantier", zones_rouges=["Ne pas toucher aux migrations."])
    t = tache(**{**reglages, **champs})
    return consigne_sous_tache(t, contrat, profil, RESTE, "B2-a")


def test_la_sous_tache_porte_son_nom_et_la_tache_dont_elle_vient():
    assert "## Sous-tâche B2-a, de la tâche B2 — Lire le profil" in sous_tache()
    autre = consigne_sous_tache(tache(), CONTRAT, PROFIL, RESTE, "B2-b")
    assert "## Sous-tâche B2-b, de la tâche B2" in autre and "B2-a" not in autre


def test_la_sous_tache_ne_demande_que_de_regler_les_points_du_reste():
    texte = sous_tache()
    reste = section(texte, "Ce qui reste à régler")
    assert reste.strip() == "1. " + RESTE[0] + "\n2. " + RESTE[1]
    assert "Ta mission ne porte que sur ces points" in texte
    assert "Ne refais pas le travail, ne le réécris pas et ne l'améliore pas" in texte
    assert "par la plus petite correction qui les traite vraiment" in texte
    assert "`git status` et `git diff` le montrent" in texte
    assert "resté dans le dossier courant" in texte
    assert "- Défaire ou réécrire ce qui est déjà fait et conforme." in texte
    # Ce que l'ouvrier d'une tâche entière reçoit, et que la sous-tâche ne reçoit pas.
    assert RELECTURE not in texte and "Pour chaque critère" not in texte


def test_la_mission_d_origine_est_donnee_comme_reference_et_jamais_comme_travail():
    texte = sous_tache()
    reference = section(texte, "Mission d'origine, pour référence seulement")
    assert "Elle est déjà faite : tu n'en refais rien" in reference
    assert "1. Rend 42.\n2. Refuse -1." in reference  # les critères y sont
    assert "Lire sans surprise." in reference  # le pourquoi aussi
    assert "b.lire()" in reference and "a.py" in reference
    # Les critères n'apparaissent nulle part ailleurs : ils ne sont pas demandés.
    assert texte.count("Rend 42.") == 1 and texte.count("Refuse -1.") == 1
    # Et ce qui est à régler n'est pas dans la référence.
    for point in RESTE:
        assert point not in reference
        assert point in section(texte, "Ce qui reste à régler")


def test_chaque_point_du_reste_figure_dans_la_sous_tache_mot_pour_mot():
    points = [f"Point {i} : « un cas précis », avec `code` et accents é à ù." for i in range(1, 8)]
    texte = consigne_sous_tache(tache(), CONTRAT, PROFIL, points, "B2-a")
    reste = section(texte, "Ce qui reste à régler")
    for i, point in enumerate(points, 1):
        assert f"{i}. {point}" in reste
    assert consigne_sous_tache(tache(), CONTRAT, PROFIL, [], "B2-a").count("(aucun)") == 1


def test_la_sous_tache_garde_les_regles_communes_a_tout_ouvrier():
    texte = sous_tache()
    # Périmètre.
    assert "- `b.py`\n- `tests/test_b.py`" in section(texte, "Ton périmètre")
    assert "Tu peux créer et modifier uniquement :" in texte
    assert "Rien hors de ton périmètre. Si tu penses en avoir besoin" in texte
    # Interdits : git, zones rouges.
    interdits = section(texte, "Interdits")
    assert "Aucun commit et aucune commande git qui modifie le dépôt" in interdits
    assert "- Ne pas toucher aux migrations." in interdits
    # Règles du projet et contrôles.
    assert "- Pas de secret dans le code." in texte and "- `pytest -q`" in texte
    assert "ne le touche pas : écris dans ta fiche de relais" in texte
    # Fiche de relais.
    assert "`chantier/relais/B2.md` est toujours permis" in section(texte, "Ta fiche de relais")
    # Empêchement : la règle de l'ouvrier, en entier.
    assert EMPECHE_OUVRIER in texte
    assert f"« {MARQUE_EMPECHE} », au tout début de la ligne" in texte
    assert texte.count(SI_EMPECHE) == 1
    assert "compte rendu final (rubrique Doutes et demandes)" in texte
    assert "Doutes et demandes" in section(texte, "À rendre")
    # Outils et suivi.
    assert COMMANDES_SIMPLES in texte and SUIVI in texte


def test_la_sous_tache_n_est_pas_la_consigne_de_la_tache_entiere():
    entiere = consigne_ouvrier(tache(), CONTRAT, PROFIL)
    sous = consigne_sous_tache(tache(), CONTRAT, PROFIL, RESTE, "B2-a")
    assert "## Tâche B2" in entiere and "## Tâche B2" not in sous
    assert "## Ce qui reste à régler" in sous and "## Ce qui reste à régler" not in entiere


# --- la retouche de M2 : genre et fichiers de la sous-tâche, vérification bornée complète ----


def sous_tache_avec(**options):
    reglages = {"pourquoi": "Lire sans surprise.", "fournit": "b.lire()", "attend": "a.py"}
    profil = {"regles": ["Pas de secret dans le code."], "commandes": ["pytest -q"]}
    contrat = Contrat(objectif="But du chantier", zones_rouges=["Ne pas toucher aux migrations."])
    return consigne_sous_tache(tache(**reglages), contrat, profil, RESTE, "B2-a", **options)


TITRE_SOUS_TACHE = "Sous-tâche B2-a, de la tâche B2 — Lire le profil"
CONFORME = "Le reste de ce travail est conforme : seuls les points ci-dessous restent à régler."
PRUDENTE = "Personne n'a encore jugé le reste de ce travail : il sera vérifié ensuite."
SANS_FICHIER = "Aucun autre fichier n'est permis."


def test_la_signature_de_la_sous_tache_gagne_genre_et_fichiers_en_dernier_et_facultatifs():
    parametres = inspect.signature(consigne_sous_tache).parameters
    assert list(parametres) == ["tache", "contrat", "profil", "reste", "nom", "genre", "fichiers"]
    assert parametres["genre"].default == "" and parametres["fichiers"].default is None


def test_seul_le_genre_verdict_affirme_que_le_reste_du_travail_est_conforme():
    texte = sous_tache_avec(genre="verdict")
    assert CONFORME in texte and PRUDENTE not in texte
    assert "Les contrôles automatiques du projet ont échoué" not in texte


@pytest.mark.parametrize(
    "genre",
    ["", "bacle", "local", "inconnu", "Verdict", "verdit", "verdict ", "controle", "CONTROLES"],
)
def test_tout_autre_genre_reste_prudent_une_faute_de_frappe_n_affirme_rien(genre):
    texte = sous_tache_avec(genre=genre)
    assert CONFORME not in texte and "est conforme :" not in texte
    assert PRUDENTE in section(texte, TITRE_SOUS_TACHE)
    assert "Les points ci-dessous restent à régler." in texte
    assert "Les contrôles automatiques du projet ont échoué" not in texte  # rien de plus affirmé


def test_sans_genre_la_sous_tache_est_la_meme_que_pour_un_genre_inconnu():
    assert sous_tache() == sous_tache_avec() == sous_tache_avec(genre="") == sous_tache_avec(
        genre="inconnu"
    )
    assert sous_tache_avec(fichiers=[]) == sous_tache() == sous_tache_avec(fichiers=None)


def test_un_reste_de_controles_ne_dit_pas_que_le_reste_du_travail_est_conforme():
    texte = sous_tache_avec(genre="controles")
    debut = section(texte, TITRE_SOUS_TACHE)
    assert CONFORME not in texte and "est conforme" not in debut
    assert "Les contrôles automatiques du projet ont échoué sur ce travail" in debut
    assert "sur les points ci-dessous : ce sont eux qui restent à régler" in debut
    assert "Personne ne l'a encore jugé ; il sera vérifié ensuite." in debut
    # Le reste de la consigne est celui des autres genres.
    nu = sous_tache()
    assert texte.replace(debut, "") == nu.replace(section(nu, TITRE_SOUS_TACHE), "")


def test_le_genre_ne_change_que_la_phrase_de_ce_qu_on_sait_du_travail():
    verdict = sous_tache_avec(genre="verdict")
    autres = {genre: sous_tache_avec(genre=genre) for genre in ("", "controles")}
    for genre, texte in autres.items():
        debut = section(texte, TITRE_SOUS_TACHE)
        avant = section(verdict, TITRE_SOUS_TACHE)
        assert texte.replace(debut, avant) == verdict, genre


def test_sans_fichiers_aucun_fichier_hors_de_la_liste_n_est_permis():
    perimetre = section(sous_tache(), "Ton périmètre")
    assert "- `b.py`\n- `tests/test_b.py`" in perimetre
    assert SANS_FICHIER in perimetre
    # Un point qui nomme un autre fichier ne le permet pas : l'ouvrier le signale.
    assert "Si un point à régler demande d'en toucher un autre, ne le touche pas" in perimetre
    assert "signale-le comme un empêchement, dans ton compte rendu, par une ligne" in perimetre
    assert f"« {MARQUE_EMPECHE} »" in perimetre
    assert "qui nomme le fichier et le point" in perimetre
    assert "Ces fichiers sont permis en plus" not in perimetre
    assert "que si un point à régler le nomme" not in sous_tache()  # l'ancienne phrase


def test_seuls_les_fichiers_passes_en_parametre_sont_permis_en_plus_pour_ce_tour():
    texte = sous_tache_avec(fichiers=["docs/resumes/RESUME_B2.md", "scripts/x.py"])
    perimetre = section(texte, "Ton périmètre")
    assert "- `b.py`\n- `tests/test_b.py`" in perimetre
    assert (
        "Ces fichiers sont permis en plus, pour ce tour, même hors du périmètre de la mission :"
        "\n- `docs/resumes/RESUME_B2.md`\n- `scripts/x.py`\n"
        f"{SANS_FICHIER} Si un point à régler demande d'en toucher un autre"
    ) in perimetre
    assert "que si un point à régler le nomme" not in texte
    # Ils ne sont ailleurs que dans le périmètre, et le reste de la consigne ne change pas.
    assert texte.count("RESUME_B2.md") == 1
    nu = sous_tache()
    assert texte.replace(perimetre, "") == nu.replace(section(nu, "Ton périmètre"), "")


def test_le_genre_et_les_fichiers_se_combinent():
    texte = sous_tache_avec(genre="controles", fichiers=["scripts/x.py"])
    assert "Les contrôles automatiques du projet ont échoué" in texte
    assert "- `scripts/x.py`" in section(texte, "Ton périmètre")
    for point in RESTE:
        assert f". {point}" in section(texte, "Ce qui reste à régler")


# La vérification bornée a la même règle que les deux autres : `verdict_complet`. Son paramètre
# `sortie_controles` était déjà obligatoire et donne déjà la sortie (voir la fiche M2) : le
# texte d'aujourd'hui, avec une sortie, est celui des empreintes `("bornee", ...)` plus haut.


def bornee_complete(copie_jetable, profil=PROFIL, sortie=SORTIE):
    return consigne_verificateur_bornee(
        tache(), CONTRAT, profil, sortie, copie_jetable, verdict_complet=True
    )


def test_la_verification_bornee_complete_est_un_parametre_facultatif_qui_laisse_le_texte_d_avant():
    parametres = inspect.signature(consigne_verificateur_bornee).parameters
    assert list(parametres)[-2:] == ["copie_jetable", "verdict_complet"]
    assert parametres["verdict_complet"].default is False
    for copie_jetable in (True, False):
        texte = consigne_verificateur_bornee(tache(), CONTRAT, PROFIL, "3 passed", copie_jetable)
        assert empreinte(texte) == TEXTES_D_AUJOURD_HUI[("bornee", copie_jetable)]
        faux = consigne_verificateur_bornee(
            tache(), CONTRAT, PROFIL, "3 passed", copie_jetable, verdict_complet=False
        )
        assert faux == texte
        for mot in ('"local"', '"reste"', "produis la preuve", "Ne rejoue aucune"):
            assert mot not in texte


@pytest.mark.parametrize("copie_jetable", [True, False])
def test_la_verification_bornee_complete_donne_la_sortie_et_interdit_de_la_rejouer(copie_jetable):
    texte = bornee_complete(copie_jetable)
    assert FIN_DE_SORTIE in texte and "DEBUT-DE-LA-SORTIE" not in texte
    assert "- `pytest -q`\n- `ruff check .`" in texte
    assert "L'Atelier vient de jouer lui-même les commandes de contrôle" in texte
    assert "Ne rejoue aucune de ces commandes, ni la suite de tests entière" in texte
    assert "Tiens ce résultat pour constaté" in texte
    assert "Ne relance pas toute la suite" not in texte  # l'ancienne forme, remplacée


@pytest.mark.parametrize("copie_jetable", [True, False])
def test_la_verification_bornee_complete_produit_la_preuve_manquante_au_lieu_de_refuser(
    copie_jetable,
):
    texte = bornee_complete(copie_jetable)
    assert PREUVE_MANQUANTE in texte
    etapes = section(texte, "Ce que tu dois faire")
    assert etapes.index("\n4. " + PREUVE_MANQUANTE) > etapes.index("\n3. Ne fais pas de mutation")
    # L'ancienne phrase « un critère sans preuve n'est pas rempli » dirait le contraire.
    assert "Un critère sans preuve n'est pas rempli" not in texte
    assert "Un critère sans preuve, ni de l'agent ni de toi, n'est pas rempli." in texte
    assert "dont la preuve échoue n'est pas rempli" not in texte


@pytest.mark.parametrize("copie_jetable", [True, False])
def test_la_verification_bornee_complete_demande_local_reste_et_fichiers(copie_jetable):
    texte = bornee_complete(copie_jetable)
    verdict = rendu(texte)
    assert '"motif": "bacle" ou "local" ou "ne_sait_pas" ou "consigne"' in verdict
    assert '"reste": ["un point à corriger"], "fichiers": ["chemin/du/fichier"]}' in verdict
    assert '- "local" : un défaut précis, à un endroit que tu nommes' in verdict
    assert 'Pour "bacle" et "local", remplis "reste" et "fichiers"' in verdict
    assert 'laisse "reste" et "fichiers" vides' in verdict
    assert "meme_defaut" not in texte  # ce n'est pas une retouche
    assert cles_demandees(texte) == {"valide", "motif", "resume", "reste", "fichiers"}
    # Ses propres champs restent : empêchement, remarques qui ne recalent pas.
    assert '"empeche"' in verdict and '"remarques"' in verdict
    assert "Une remarque ne recale pas" in verdict
    plein = (
        '{"valide": false, "motif": "local", "resume": "x", "reste": ["a"], "fichiers": ["f.py"]}'
    )
    assert {"reste", "fichiers"} <= set(lire_verdict(plein))


@pytest.mark.parametrize("copie_jetable", [True, False])
def test_la_verification_bornee_complete_garde_son_cadre_et_les_regles_communes(copie_jetable):
    texte = bornee_complete(copie_jetable)
    assert "Ta vérification est bornée" in texte and "Ne fais pas de mutation" in texte
    assert "pour une mutation (changer le code" not in texte
    assert "1. Rend 42.\n2. Refuse -1." in texte
    assert texte.count(SI_EMPECHE) == 1 and COMMANDES_SIMPLES in texte
    assert SUIVI in texte and RELAIS_PERMIS in texte
    assert ("copie jetable" in texte) is copie_jetable


def test_la_verification_bornee_complete_sans_commande_ni_sortie():
    sans_commande = bornee_complete(False, profil={})
    assert "n'a pas de commande de contrôle" in sans_commande
    assert "[début de la sortie]" not in sans_commande and PREUVE_MANQUANTE in sans_commande
    vide = bornee_complete(False, sortie="")
    assert "(les commandes n'ont rien affiché)" in vide and "Ne rejoue aucune" in vide


# --- la reprise de M2 : une preuve impossible n'est jamais un critère tenu ----------------------


def test_la_raison_donnee_par_l_ouvrier_est_jugee_elle_ne_vaut_pas_acceptation():
    rendre = section(consigne_ouvrier(tache(), CONTRAT, PROFIL), "À rendre")
    assert "cette raison sera lue et jugée, elle ne vaut pas acceptation d'avance" in rendre
    assert "c'est accepté" not in rendre and "accepté quand la raison" not in rendre
    # Ce qui reste dit : la raison exacte est demandée, le silence fait refuser.
    assert "avec sa raison exacte" in rendre and "passé sous silence fait refuser" in rendre


def test_sans_preuve_du_verificateur_ni_de_l_agent_le_critere_n_est_pas_tenu():
    # Un vérificateur qui ne peut pas produire la preuve refuse toujours.
    assert "le critère n'est pas tenu et tu refuses" in PREUVE_MANQUANTE
    assert "quelle que soit la raison que l'agent donne" in PREUVE_MANQUANTE
    # La raison de l'agent ne sert qu'à choisir le motif ou à remplir « empeche ».
    assert 'sert seulement à choisir le motif, ou à remplir "empeche"' in PREUVE_MANQUANTE
    assert "que l'agent n'en donne pas la raison" not in PREUVE_MANQUANTE
    for nom, texte in avec_sortie(False).items():
        assert PREUVE_MANQUANTE in texte, nom


# --- la reprise de M2 : bacle n'exige pas un reste conforme ---------------------------------


@pytest.mark.parametrize("copie_jetable", [True, False])
def test_bacle_garde_ses_points_dans_reste_sans_exiger_que_le_reste_soit_conforme(copie_jetable):
    textes = dict(avec_sortie(copie_jetable))
    textes["bornee"] = bornee_complete(copie_jetable)
    for nom, texte in textes.items():
        verdict = rendu(texte)
        bacle = verdict.split('- "bacle" : ', 1)[1].split("\n- ", 1)[0]
        assert "en un endroit ou en plusieurs" in bacle, nom
        assert 'chaque point négligé va dans "reste"' in bacle, nom
        assert "conforme" not in bacle, nom  # un travail négligé à plusieurs endroits reste bacle
        # « local » reste un défaut précis, le reste conforme.
        local = verdict.split('- "local" : ', 1)[1].split("\n- ", 1)[0]
        assert "un défaut précis, à un endroit que tu nommes" in local, nom
        assert "le reste du travail est conforme et tu l'as constaté" in local, nom


def test_en_retouche_avec_fichiers_le_verificateur_ne_constate_pas_le_reste():
    t = tache()
    avec = consigne_reverification(
        t, CONTRAT, PROFIL, "Refusé.", sortie_controles=SORTIE, fichiers=["b.py"]
    )
    local = rendu(avec).split('- "local" : ', 1)[1].split("\n- ", 1)[0]
    assert "un défaut précis, à un endroit que tu nommes, qu'une retouche corrige" in local
    assert "le reste du travail n'est pas en cause" in local
    assert "constaté" not in local and "conforme" not in local
    # Sans fichiers, il lit tout le diff : la phrase reste celle des autres vérifications.
    sans = consigne_reverification(t, CONTRAT, PROFIL, "Refusé.", sortie_controles=SORTIE)
    assert "le reste du travail est conforme et tu l'as constaté" in rendu(sans)
    # Le reste du verdict est le même, avec ou sans fichiers.
    assert rendu(avec).replace("le reste du travail n'est pas en cause", "X") == rendu(
        sans
    ).replace("le reste du travail est conforme et tu l'as constaté", "X")


def test_meme_defaut_et_un_refus_pour_autre_chose_ne_se_contredisent_pas():
    retouche = rendu(avec_sortie(False)["reverification"])
    meme = retouche.split('- "meme_defaut"', 1)[1].split("\n\nPour ", 1)[0]
    assert "true seulement si aucun des points relevés au verdict précédent" in meme
    assert "false dès qu'un de ces points au moins est corrigé" in meme
    assert 'écris-le dans "reste"' in meme and "cela ne change pas" in meme
    assert "refus porte sur autre chose" not in meme  # l'ancienne règle, qui disait false
