"""Tests de `atelier.refus` : refus qui se répète et empêchements signalés."""

from atelier import refus
from atelier.refus import empechements, meme_refus, refus_identiques_de_suite


def _refus(detail, issue="refuse", origine=None):
    entree = {"issue": issue, "detail": detail}
    if origine is not None:
        entree["origine"] = origine
    return entree


UV = "La commande `uv run pytest` est interdite aux agents : permission refusée"


def test_meme_texte_est_le_meme_refus():
    assert meme_refus(_refus(UV), _refus(UV))


def test_numero_de_ligne_ou_duree_ne_change_pas_le_refus():
    a = _refus("valeur 1234567 contre 7654321 sur 9999 cas en 1000 ms")
    b = _refus("valeur 2345 contre 5432 sur 8 cas en 7 ms")
    assert meme_refus(a, b)
    c = _refus("tests/test_a.py:12 : assert 3 == 4 après 1.2 s")
    d = _refus("tests/test_a.py:187 : assert 30 == 41 après 15.9 s")
    assert meme_refus(c, d)


A = (
    "uv.lock est absent du dépôt et les versions de ruff, pytest et pre-commit ne sont figées "
    "nulle part, donc le critère 1 n'est pas tenu"
)
B = (
    "uv.lock est absent et les dépendances de développement ne sont pas figées, et rien ne "
    "montre que uv sync, ruff check et pytest passent"
)
C = (
    "uv.lock est absent, donc les versions de ruff, pytest et pre-commit ne sont figées "
    "nulle part et le critère 1 n'est pas tenu"
)


def test_les_trois_vrais_refus_du_chantier_sont_les_memes_deux_a_deux():
    for x, y in [(A, B), (B, C), (A, C)]:
        assert meme_refus(_refus(x), _refus(y))
    assert refus_identiques_de_suite([_refus(A), _refus(B), _refus(C)]) == 3


PAIRES_DIFFERENTES = [
    (
        "Le critère 2 n'est pas tenu : des lignes dépassent 100 caractères dans le calcul",
        "FAILED tests/test_carte.py::test_vue - assert 3 == 4 (1 failed, 20 passed)",
    ),
    (
        "La page ne s'affiche pas sur téléphone : le bouton Lancer est coupé par le bandeau",
        "La consigne ne dit pas comment reprendre après un redémarrage du serveur",
    ),
    (
        "Le critère 1 n'est pas tenu : uv.lock est absent du dépôt",
        "Le critère 3 n'est pas tenu : la page n'affiche pas les tokens des tâches",
    ),
    (
        "Le livrable déborde du périmètre : atelier/carte.py modifié",
        "Le livrable déborde du périmètre : atelier/moteur.py modifié",
    ),
    (
        "FAILED tests/test_carte.py::test_vue - assert 3 == 4 (1 failed, 20 passed)",
        "FAILED tests/test_moteur.py::test_boucle - assert 5 == 6 (1 failed, 20 passed)",
    ),
]


def test_refus_de_meme_issue_sur_des_sujets_differents():
    for x, y in PAIRES_DIFFERENTES:
        assert not meme_refus(_refus(x), _refus(y)), (x, y)
        assert not meme_refus(_refus(x, origine="perimetre"), _refus(y, origine="perimetre"))


def test_entrees_mal_formees_pour_les_refus():
    assert not meme_refus(None, None)
    assert not meme_refus({"issue": "refuse", "detail": 5}, {"issue": "refuse", "detail": None})
    assert not meme_refus("texte", _refus(UV))
    assert refus_identiques_de_suite([None]) == 0
    assert refus_identiques_de_suite([_refus(UV), None]) == 0
    assert refus_identiques_de_suite([None, _refus(UV)]) == 1
    assert refus_identiques_de_suite(None) == 0


def test_deux_refus_differents_de_meme_issue_ne_sont_pas_les_memes():
    a = _refus("Le livrable déborde du périmètre : atelier/carte.py modifié")
    b = _refus("Le vérificateur a trouvé que la page ne s'ouvre plus sur téléphone")
    assert not meme_refus(a, b)


def test_origine_ou_issue_differente_ecarte():
    assert not meme_refus(_refus(UV, origine="agent"), _refus(UV, origine="verdict"))
    assert not meme_refus(_refus(UV, origine="agent"), _refus(UV))
    assert not meme_refus(_refus(UV, issue="refuse"), _refus(UV, issue="erreur"))


def test_origine_absente_des_deux_compte_comme_egale():
    assert meme_refus(_refus(UV), _refus(UV))


def test_detail_vide_n_est_pas_une_preuve():
    assert not meme_refus(_refus(""), _refus(""))
    assert not meme_refus({"issue": "refuse"}, {"issue": "refuse"})
    assert not meme_refus(_refus(""), _refus(UV))


def test_seuil_garde_les_refus_voisins_mais_differents():
    a = _refus("x" * 100)
    b = _refus("x" * 70 + "y" * 30)
    assert not meme_refus(a, b)
    assert refus.SEUIL_RESSEMBLANCE == 0.9


def test_seuls_les_600_derniers_caracteres_comptent():
    fin = "la fin qui compte, identique " * 25
    assert meme_refus(_refus("début différent " * 40 + fin), _refus("autre début " * 40 + fin))


def test_suite_de_refus_identiques():
    assert refus_identiques_de_suite([]) == 0
    assert refus_identiques_de_suite([_refus(UV)]) == 1
    assert refus_identiques_de_suite([_refus(UV)] * 3) == 3


def test_suite_coupee_par_un_refus_different():
    autre = _refus("tout autre chose : le périmètre est dépassé par deux fichiers")
    assert refus_identiques_de_suite([_refus(UV), autre, _refus(UV), _refus(UV)]) == 2


def test_une_entree_valide_coupe_la_suite():
    valide = {"issue": "valide", "detail": UV}
    assert refus_identiques_de_suite([_refus(UV), _refus(UV), valide]) == 0
    assert refus_identiques_de_suite([_refus(UV), valide, _refus(UV), _refus(UV)]) == 2


def test_empechement_en_debut_de_ligne():
    texte = "J'ai fini le reste.\n  EMPÊCHÉ : uv — commande interdite\nFin."
    assert empechements(texte, None, None) == ["uv — commande interdite"]


def test_empechement_au_milieu_d_une_ligne_ne_compte_pas():
    texte = "FAILED test_x - assert 'EMPÊCHÉ : uv' in sortie\nrésultat : EMPÊCHÉ : rien"
    assert empechements(texte, None, None) == []


def test_ordre_et_doublons():
    texte = "EMPÊCHÉ : uv\nEMPÊCHÉ : uv\nEMPÊCHÉ : git push"
    verdict = {"empeche": ["git push", "curl"]}
    assert empechements(texte, ["Bash(uv)", "curl"], verdict) == [
        "uv",
        "git push",
        "Bash(uv)",
        "curl",
    ]


def test_empeche_du_verdict_en_chaine():
    assert empechements("", None, {"empeche": "  npm interdit "}) == ["npm interdit"]


def test_rien_de_signale():
    assert empechements("tout va bien", [], {"resume": "ok"}) == []
    assert empechements("", None, None) == []


def test_entrees_mal_formees_ne_levent_pas():
    assert empechements(None, "pas une liste", "pas un dict") == []
    assert empechements(42, [None, 3, "x"], {"empeche": [1, None, "y"]}) == ["x", "y"]
    assert empechements("EMPÊCHÉ :", [""], {"empeche": ""}) == []
