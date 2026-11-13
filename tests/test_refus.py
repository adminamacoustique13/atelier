"""Tests de `atelier.refus` : refus qui se répète et empêchements signalés."""

from atelier import refus
from atelier.refus import (
    empechements,
    meme_forme,
    meme_refus,
    refus_de_meme_forme_de_suite,
    refus_identiques_de_suite,
    signature_des_controles,
)


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


# --- V3b : la forme, les contrôles, les identifiants, les erreurs d'agent --------------------

T = "Les contrôles automatiques échouent :\n"
SORTIE_UN = "....F\nFAILED tests/test_a.py::test_un - assert 1 == 2\n1 failed, 4 passed in 0.12s"
SORTIE_DEUX = "....F\nFAILED tests/test_a.py::test_deux - assert 3 == 4\n1 failed, 4 passed in 0.3s"
SORTIE_UN_AUTREMENT = (  # le même test échoue, avec une tout autre sortie
    "tests/test_a.py:41: in test_un\n    resultat = calculer(donnees_de_reference())\n"
    "coeur/calcul.py:12: in calculer\n    return table[cle]\nE   KeyError: 'pression'\n"
    "FAILED tests/test_a.py::test_un - KeyError: 'pression'\n1 failed, 4 passed in 0.40s"
)


def _controles(sortie, origine="controles"):
    return _refus(T + sortie, issue="ne_sait_pas", origine=origine)


def test_la_signature_lit_les_tests_en_echec_et_les_codes_de_forme():
    sortie = (
        "....F\nFAILED tests/test_a.py::test_un[1-2] - assert 1 == 2\n"
        "ERROR tests/test_b.py - ImportError: rien\n"
        "a.py:3:1: E501 Line too long (120 > 100)\n"  # format court de ruff
        "F401 [*] `os` imported but unused\n --> b.py:1:8\n"  # format actuel de ruff
    )
    assert signature_des_controles(sortie) == {
        "test:tests/test_a.py::test_un[1-2]", "test:tests/test_b.py", "forme:E501", "forme:F401",
    }  # fmt: skip
    # Une ligne d'assertion de pytest, un « FAILED » qui n'ouvre pas la ligne : rien.
    assert signature_des_controles("E       assert 3 == 4\n  FAILED ici\nTout va.") == set()
    assert signature_des_controles(None) == set()


def test_un_refus_des_controles_se_compare_par_ses_tests_en_echec():
    assert meme_refus(_controles(SORTIE_UN), _controles(SORTIE_UN_AUTREMENT))
    assert meme_forme(_controles(SORTIE_UN), _controles(SORTIE_UN_AUTREMENT))
    # Par le seul texte, ce même refus aurait été manqué.
    assert not meme_refus(_refus(T + SORTIE_UN), _refus(T + SORTIE_UN_AUTREMENT))
    assert not meme_refus(_controles(SORTIE_UN), _controles(SORTIE_DEUX))
    # Une sortie lisible et une illisible diffèrent ; deux illisibles se comparent par le texte.
    assert not meme_refus(_controles(SORTIE_UN), _controles("uv : commande introuvable"))
    assert meme_refus(_controles("uv : commande introuvable (127)"),
                      _controles("uv : commande introuvable (128)"))  # fmt: skip
    # Un refus à l'enregistrement rejoue les contrôles : même règle.
    assert meme_refus(_controles(SORTIE_UN, "integration"),
                      _controles(SORTIE_UN_AUTREMENT, "integration"))  # fmt: skip


def test_deux_codes_de_forme_differents_ne_sont_pas_le_meme_refus():
    e501 = "a.py:3:1: E501 Line too long (120 > 100)\nFound 1 error."
    f401 = "a.py:3:1: F401 `os` imported but unused\nFound 1 error."
    assert not meme_refus(_controles(e501), _controles(f401))
    assert not meme_refus(_refus(T + e501), _refus(T + f401))  # par le texte aussi


IDENTIFIANTS_DIFFERENTS = [
    (
        "Le critère 2 n'est pas tenu : la fonction rend une valeur fausse sur le cas limite",
        "Le critère 3 n'est pas tenu : la fonction rend une valeur fausse sur le cas limite",
    ),
    (
        "Le test test_vue ne peut pas échouer : il compare la sortie à elle-même",
        "Le test test_boucle ne peut pas échouer : il compare la sortie à elle-même",
    ),
    (
        "Une ligne du module de calcul viole E501 et reste à corriger",
        "Une ligne du module de calcul viole W291 et reste à corriger",
    ),
]


def test_des_identifiants_differents_ecartent_des_refus_qui_se_ressemblent():
    for x, y in IDENTIFIANTS_DIFFERENTS:
        assert not meme_refus(_refus(x), _refus(y)), (x, y)
    # Un identifiant cité d'un seul côté ne départage rien.
    un_seul = "Le critère 2 n'est pas tenu : uv.lock est absent du dépôt"
    assert meme_refus(_refus(un_seul), _refus(un_seul.replace(" 2", "")))


def test_meme_forme_ne_reconnait_pas_une_reformulation():
    # Les vrais refus du chantier : A et B ne se ressemblent que par leurs mots.
    assert meme_refus(_refus(A), _refus(B)) and not meme_forme(_refus(A), _refus(B))
    assert meme_forme(_refus(A), _refus(C))
    assert meme_forme(_refus("valeur 1234 sur 9 cas"), _refus("valeur 77 sur 120 cas"))
    assert refus_identiques_de_suite([_refus(A), _refus(B), _refus(C)]) == 3
    assert refus_de_meme_forme_de_suite([_refus(A), _refus(B), _refus(C)]) == 1
    assert refus_de_meme_forme_de_suite([_refus(B), _refus(A), _refus(C)]) == 2
    assert refus_de_meme_forme_de_suite([_refus(UV)] * 3) == 3
    assert refus_de_meme_forme_de_suite([_refus(UV), {"issue": "valide", "detail": UV}]) == 0
    assert refus_de_meme_forme_de_suite(None) == 0


def test_une_erreur_d_agent_se_compare_par_sa_seule_forme():
    from atelier.agents import LIMITE_ATTEINTE, SURCHARGE

    def erreur(texte, origine="agent"):
        return _refus(f"L'agent s'est arrêté sur une erreur : {texte}", "ne_sait_pas", origine)

    assert not meme_refus(erreur(SURCHARGE), erreur(LIMITE_ATTEINTE))
    assert meme_refus(erreur(SURCHARGE, "verdict"), erreur(LIMITE_ATTEINTE, "verdict"))  # mots
    delai = "Claude Code n'a pas répondu dans le délai de {} s."
    assert meme_refus(erreur(delai.format(3600)), erreur(delai.format(1800)))


# --- les outils refusés qui lancent une commande de contrôle (V3b.1) -------------------------

CONTROLES_UV = ["Bash(uv run pytest -q)", "Bash(ruff check .)"]


def test_un_outil_refuse_est_un_controle_s_il_en_a_le_nom_et_le_premier_mot():
    refuses = ["Bash(uv sync)", "Bash(git push)", "Bash(uv)", "Bash(uvx ruff)", "Bash(ruff format)"]
    assert refus.outils_de_controle(refuses, CONTROLES_UV) == [
        "Bash(uv sync)", "Bash(uv)", "Bash(ruff format)",
    ]  # fmt: skip
    # Un autre outil, même nommé comme la commande, n'en lance aucune.
    assert refus.outils_de_controle(["Edit(uv sync)", "Read(uv)", "WebFetch"], CONTROLES_UV) == []


def test_sans_controle_ni_objet_aucun_outil_refuse_n_est_un_controle():
    assert refus.outils_de_controle(["Bash(uv sync)"], []) == []
    assert refus.outils_de_controle(["Bash", "Bash(uv sync)"], ["Bash", ""]) == []
    assert refus.outils_de_controle([None, 3, "Bash(uv sync)"], [None, *CONTROLES_UV]) == [
        "Bash(uv sync)"
    ]
