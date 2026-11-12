"""Les consignes gardent ce qu'elles doivent dire : le moteur et les agents en dépendent."""

import subprocess

import pytest

from atelier.consignes import (
    COMMANDES_SIMPLES,
    COPIE_JETABLE,
    MARQUE_BLOCAGE,
    MARQUE_EMPECHE,
    PREUVES_MAX,
    REGLES_DECOUPAGE,
    RELAIS_PERMIS,
    ROLE_ORCHESTRATEUR,
    SORTIE_BORNEE,
    consigne_ouvrier,
    consigne_planification,
    consigne_reprise,
    consigne_reverification,
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


def test_l_ouvrier_ne_signale_un_refus_que_si_la_tache_ne_peut_pas_se_faire_sans():
    ouvrier = consigne_ouvrier(tache(), CONTRAT, PROFIL)
    assert (
        f"N'écris la ligne « {MARQUE_EMPECHE} » pour ce qui t'est refusé que si la tâche ne peut "
        "pas se faire sans ; sinon fais sans, et dis-le dans ta fiche de relais."
    ) in ouvrier
    assert "Signale le refus dans les deux cas" not in ouvrier
    # La même phrase, une seule fois, dans la consigne et dans chaque reprise.
    from atelier.consignes import EMPECHE_SI_INDISPENSABLE

    assert ouvrier.count(EMPECHE_SI_INDISPENSABLE) == 1
    for refuses in ((), ("Bash(git push)",)):
        reprise = consigne_reprise(tache(), "verdict", "Refusé.", PROFIL, refuses)
        assert reprise.count(EMPECHE_SI_INDISPENSABLE) == 1, refuses
        assert "comme le dit ta consigne" not in reprise


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
