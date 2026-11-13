"""Réglages communs à toute la suite de tests.

Les tests qui créent un vrai dépôt git ne doivent pas hériter de la configuration git de la
machine : une signature des commits par un service extérieur, par exemple, les ferait échouer
sans défaut du code. Pour toute la session de tests, git lit donc une configuration globale
vide et ignore la configuration système. Le produit, lui, n'est pas touché : ce fichier ne
sert qu'aux tests.
"""

import pytest


@pytest.fixture(scope="session", autouse=True)
def git_sans_configuration_de_la_machine(tmp_path_factory):
    vide = tmp_path_factory.mktemp("git") / "config-globale-vide"
    vide.write_text("", "utf-8")
    with pytest.MonkeyPatch.context() as reglages:
        reglages.setenv("GIT_CONFIG_GLOBAL", str(vide))
        reglages.setenv("GIT_CONFIG_NOSYSTEM", "1")
        yield


@pytest.fixture(autouse=True)
def pont_sans_attente_ni_memoire_des_couts(monkeypatch):
    """Deux réglages du pont (`atelier.sdk`), pour chaque test.

    Après une interruption, le pont attend le message de fin de Claude Code (jusqu'à 2 s dans le
    produit). Les faux clients de la plupart des tests n'en envoient jamais : chaque arrêt y
    dormirait pour rien. L'attente du message de fin (`delai_fin_s`) est donc courte ici ;
    l'interruption elle-même garde sa borne. Les tests qui portent sur cette attente la règlent.

    Le registre des cumuls de coût est commun au processus, et les tests réutilisent les mêmes
    identifiants de session : il est vidé avant chaque test, pour qu'aucun n'hérite d'un autre.
    """
    from atelier.sdk import SessionSDK, vider_les_cumuls

    monkeypatch.setattr(SessionSDK, "delai_fin_s", 0.01)
    vider_les_cumuls()
    yield
    vider_les_cumuls()


@pytest.fixture(autouse=True)
def montee_d_avant(request, monkeypatch):
    """Les tests écrits avant le 2026-11-13 prouvent la règle « refus » : après tout refus, une
    seconde chance puis un cran de plus. Elle reste dans le produit (`"montee": "refus"` au
    profil) et ils continuent de la prouver. Le produit, lui, suit sans réglage la règle
    « fond » (le modèle ne monte que si le fond est jugé faux) : les tests qui la prouvent
    portent la marque `montee_sur_le_fond`, et ne reçoivent pas ce réglage."""
    if request.node.get_closest_marker("montee_sur_le_fond") is None:
        from atelier import moteur

        monkeypatch.setattr(moteur, "MONTEE_SANS_REGLAGE", "refus")
