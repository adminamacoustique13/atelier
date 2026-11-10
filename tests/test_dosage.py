from atelier import dosage


def test_depart_selon_le_type():
    assert dosage.depart("mecanique") == ("haiku", "low")
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
