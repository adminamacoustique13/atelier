"""Les périmètres : un chemin à crochets (`app/[slug]/page.tsx`) se reconnaît lui-même."""

from atelier.controles import hors_perimetre, motif_partage, se_chevauchent

CHEMIN = "app/[slug]/page.tsx"


def test_un_chemin_a_crochets_ecrit_tel_quel_dans_le_perimetre_n_en_sort_pas():
    assert hors_perimetre([CHEMIN], [CHEMIN]) == []


def test_deux_perimetres_qui_ont_le_meme_chemin_a_crochets_se_chevauchent():
    assert se_chevauchent([CHEMIN], [CHEMIN]) is True


def test_un_chemin_a_crochets_declare_partage_n_est_pas_retenu():
    assert motif_partage(CHEMIN, [CHEMIN]) == CHEMIN
    assert se_chevauchent([CHEMIN], [CHEMIN], partages=[CHEMIN]) is False


def test_les_motifs_ordinaires_se_comportent_comme_avant():
    assert hors_perimetre(
        ["atelier/x.py", "tests/test_a.py", "z.py"], ["atelier/*", "tests/test_*.py"]
    ) == ["z.py"]
    assert se_chevauchent(["atelier/*"], ["atelier/x.py"]) is True
    assert se_chevauchent(["atelier/*"], ["tests/x.py"]) is False
