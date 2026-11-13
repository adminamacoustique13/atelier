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
