import pytest

from atelier import dosage


def test_depart_selon_le_type():
    assert dosage.depart("mecanique") == ("sonnet", "low")
    assert dosage.depart("physique") == ("fable", "max")
    assert dosage.depart("conception") == ("fable", "high")
    assert dosage.depart("inconnu") == ("sonnet", "medium")


def test_la_table_du_projet_passe_avant_la_table_par_defaut():
    assert dosage.depart("mecanique", {"mecanique": ["sonnet", "low"]}) == ("sonnet", "low")


def test_un_travail_bacle_monte_l_effort():
    assert dosage.monter("sonnet", "medium", "bacle") == ("sonnet", "high")


def test_un_agent_qui_ne_sait_pas_monte_le_modele():
    assert dosage.monter("haiku", "low", "ne_sait_pas") == ("sonnet", "low")
    assert dosage.monter("opus", "high", "ne_sait_pas") == ("fable", "high")


def test_tout_en_haut_des_modeles_on_pousse_l_effort_puis_plus_rien():
    assert dosage.monter("fable", "high", "ne_sait_pas") == ("fable", "xhigh")
    assert dosage.monter("fable", "max", "ne_sait_pas") is None
    assert dosage.monter("fable", "max", "bacle") is None


def test_plafond():
    plafond = ("opus", "high")
    assert dosage.dans_plafond("sonnet", "max", plafond)
    assert dosage.dans_plafond("opus", "high", plafond)
    assert not dosage.dans_plafond("opus", "max", plafond)
    assert not dosage.dans_plafond("fable", "low", plafond)


def test_le_verificateur_est_un_modele_au_dessus():
    assert dosage.verificateur("haiku", "low") == ("sonnet", "medium")
    assert dosage.verificateur("sonnet", "high") == ("opus", "high")
    assert dosage.verificateur("opus", "max") == ("fable", "max")


def test_le_modele_le_plus_capable_est_verifie_par_lui_meme_en_effort_max():
    assert dosage.verificateur("fable", "high") == ("fable", "max")


# --- départ : Haiku n'est plus un point de départ, mais reste dans l'échelle ---------------


def test_aucun_type_ne_part_sur_haiku_qui_reste_dans_l_echelle():
    assert all(modele != "haiku" for modele, _ in dosage.DEPART.values())
    assert dosage.MODELES[0] == "haiku"


# --- le niveau de vérification ----------------------------------------------------------


def test_la_table_des_niveaux_de_verification():
    assert dosage.NIVEAUX == ("complete", "bornee", "mecanique")
    assert dosage.niveau_verification("delicate") == "complete"
    assert dosage.niveau_verification("physique") == "complete"
    assert dosage.niveau_verification("conception") == "complete"
    assert dosage.niveau_verification("courante") == "bornee"
    assert dosage.niveau_verification("mecanique") == "mecanique"


def test_chaque_type_connu_a_un_niveau_de_depart():
    assert set(dosage.TYPES_FR) <= set(dosage.NIVEAU_DEPART)
    assert set(dosage.NIVEAU_DEPART.values()) <= set(dosage.NIVEAUX)


def test_une_reparation_est_toujours_verifiee_completement():
    assert dosage.niveau_verification("courante", reparation=True) == "complete"
    assert dosage.niveau_verification("mecanique", reparation=True) == "complete"
    assert dosage.niveau_verification("reparation") == "complete"
    reglages = {"reparation": "mecanique", "courante": "mecanique"}
    assert dosage.niveau_verification("courante", reglages, reparation=True) == "complete"


def test_un_type_inconnu_recoit_la_verification_complete():
    assert dosage.niveau_verification("inconnu") == "complete"
    assert dosage.niveau_verification("") == "complete"


def test_le_profil_regle_le_niveau_par_type():
    reglages = {"courante": "mecanique", "mecanique": "bornee", "conception": "bornee"}
    assert dosage.niveau_verification("courante", reglages) == "mecanique"
    assert dosage.niveau_verification("mecanique", reglages) == "bornee"
    assert dosage.niveau_verification("conception", reglages) == "bornee"
    assert dosage.niveau_verification("courante", {"courante": "complete"}) == "complete"
    assert dosage.niveau_verification("inconnu", {"inconnu": "bornee"}) == "bornee"


def test_le_plancher_garde_la_verification_complete_des_types_delicats():
    reglages = {"delicate": "mecanique", "physique": "bornee", "reparation": "mecanique"}
    assert dosage.niveau_verification("delicate", reglages) == "complete"
    assert dosage.niveau_verification("physique", reglages) == "complete"
    assert dosage.niveau_verification("reparation", reglages) == "complete"


@pytest.mark.parametrize(
    "reglages",
    [
        None,
        "mecanique",
        ["courante", "mecanique"],
        42,
        {"courante": "rapide"},
        {"courante": "Mecanique"},
        {"courante": ["mecanique"]},
        {"courante": None},
        {"courante": 1},
    ],
)
def test_un_reglage_mal_forme_est_ignore_sans_erreur(reglages):
    assert dosage.niveau_verification("courante", reglages) == "bornee"


def test_chaque_niveau_a_sa_phrase_en_francais():
    for niveau in dosage.NIVEAUX:
        phrase = dosage.libelle_niveau(niveau)
        assert phrase.endswith(".") and phrase[0].isupper()
    assert len({dosage.libelle_niveau(n) for n in dosage.NIVEAUX}) == 3
    assert dosage.libelle_niveau("inconnu") == dosage.libelle_niveau("complete")


# --- le vérificateur selon le niveau ------------------------------------------------------


def test_en_verification_complete_le_verificateur_est_un_modele_au_dessus():
    assert dosage.verificateur_selon_niveau("sonnet", "low", "complete") == ("opus", "medium")
    assert dosage.verificateur_selon_niveau("opus", "high", "complete") == ("fable", "high")
    assert dosage.verificateur_selon_niveau("fable", "high", "complete") == ("fable", "max")
    for modele in dosage.MODELES:
        for effort in dosage.EFFORTS:
            attendu = dosage.verificateur(modele, effort)
            assert dosage.verificateur_selon_niveau(modele, effort, "complete") == attendu


def test_en_verification_bornee_le_verificateur_est_le_meme_modele():
    assert dosage.verificateur_selon_niveau("sonnet", "medium", "bornee") == ("sonnet", "medium")
    assert dosage.verificateur_selon_niveau("sonnet", "low", "bornee") == ("sonnet", "medium")
    assert dosage.verificateur_selon_niveau("opus", "high", "bornee") == ("opus", "high")
    assert dosage.verificateur_selon_niveau("fable", "max", "bornee") == ("fable", "max")


def test_en_verification_mecanique_il_n_y_a_pas_de_verificateur():
    assert dosage.verificateur_selon_niveau("sonnet", "low", "mecanique") is None
    assert dosage.verificateur_selon_niveau("fable", "max", "mecanique") is None


def test_un_niveau_inconnu_donne_le_verificateur_complet():
    assert dosage.verificateur_selon_niveau("sonnet", "low", "rapide") == ("opus", "medium")


def test_un_modele_hors_echelle_leve_comme_aujourd_hui():
    with pytest.raises(ValueError):
        dosage.verificateur_selon_niveau("inconnu", "low", "bornee")
    with pytest.raises(ValueError):
        dosage.verificateur_selon_niveau("inconnu", "low", "complete")


def test_l_appel_d_aujourd_hui_au_verificateur_est_inchange():
    assert dosage.verificateur("haiku", "low") == ("sonnet", "medium")
    assert dosage.verificateur("sonnet", "low") == ("opus", "medium")
    assert dosage.verificateur("sonnet", "high") == ("opus", "high")
    assert dosage.verificateur("opus", "max") == ("fable", "max")
    assert dosage.verificateur("fable", "low") == ("fable", "max")


# --- M1 : le dosage d'une correction (mêmes réponses que la référence) --------------------------


@pytest.mark.parametrize(
    ("modele", "prevu", "attendu"),
    [
        ("fable", "opus", "opus"),  # montée après une erreur : retour au correcteur
        ("fable", "fable", "fable"),  # prévue complexe : elle garde son modèle
        ("fable", "", "opus"),
        ("sonnet", "fable", "sonnet"),  # jamais au-dessus du modèle de la tâche
        ("opus", "fable", "opus"),
        ("opus", "opus", "opus"),
        ("haiku", "", "sonnet"),  # jamais sous Sonnet
        ("haiku", "haiku", "sonnet"),
        ("sonnet", "inconnu", "sonnet"),  # un modèle prévu hors échelle est ignoré
    ],
)
def test_le_correcteur_ne_depasse_opus_que_pour_une_tache_prevue_au_dessus(
    modele, prevu, attendu
):
    assert dosage.correcteur(modele, prevu) == attendu


def test_le_correcteur_d_un_modele_hors_echelle_leve():
    with pytest.raises(ValueError):
        dosage.correcteur("inconnu")


@pytest.mark.parametrize(
    ("modele", "prevu", "documents", "rang", "attendu"),
    [
        ("opus", "opus", True, 1, ("sonnet", "medium")),  # un résumé : de la rédaction
        ("fable", "opus", True, 1, ("sonnet", "medium")),
        ("opus", "opus", True, 0, ("sonnet", "medium")),  # rang sous 1 : comme le rang 1
        ("opus", "opus", True, 2, ("opus", "high")),  # le résumé n'est toujours pas bon
        ("fable", "fable", True, 2, ("fable", "medium")),  # Fable corrige à effort mesuré
        ("opus", "opus", False, 1, ("opus", "high")),  # une correction de code
        ("opus", "opus", False, 2, ("opus", "xhigh")),  # le défaut revient : l'effort monte
        ("opus", "opus", False, 3, ("opus", "xhigh")),  # au-delà du rang 2 : le même cran
        ("fable", "opus", False, 1, ("opus", "high")),  # montée après une erreur : retour à Opus
        ("fable", "opus", False, 2, ("opus", "xhigh")),
        ("fable", "fable", False, 1, ("fable", "medium")),  # prévue complexe : garde Fable,
        ("fable", "fable", False, 2, ("fable", "high")),  # à effort mesuré
        ("sonnet", "sonnet", False, 1, ("sonnet", "high")),
        ("haiku", "haiku", False, 1, ("sonnet", "high")),  # jamais sous Sonnet
        ("opus", "", False, 1, ("opus", "high")),
    ],
)
def test_le_dosage_d_une_sous_tache_vient_du_reste_pas_de_la_tache(
    modele, prevu, documents, rang, attendu
):
    assert dosage.sous_tache(modele, prevu, documents, rang) == attendu


def test_une_sous_tache_se_dose_par_defaut_comme_une_correction_de_code_de_rang_1():
    assert dosage.sous_tache("opus") == ("opus", "high")
    assert dosage.sous_tache("opus", "opus", False, 1) == dosage.sous_tache("opus")


@pytest.mark.parametrize(
    ("fichiers", "attendu"),
    [
        (["RESUME.md", "AVIS.txt"], True),
        (["notes.rst"], True),
        (["LISEZMOI.MD", "Avis.TXT"], True),  # la casse ne compte pas
        (("RESUME.md",), True),  # un tuple convient
        (["RESUME.md", "db/social.py"], False),  # un seul fichier de code suffit
        (["db/social.py"], False),
        (["resume.md.bak"], False),  # c'est l'extension qui compte
        (["resume"], False),
        ([], False),  # aucun fichier nommé : faux
        (None, False),
        ("", False),
    ],
)
def test_un_reste_n_est_de_la_redaction_que_si_tous_ses_fichiers_le_sont(fichiers, attendu):
    assert dosage.que_des_documents(fichiers) is attendu
