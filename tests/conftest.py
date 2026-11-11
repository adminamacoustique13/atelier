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
