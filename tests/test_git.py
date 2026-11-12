import subprocess
import sys

import pytest

from atelier import git
from atelier.git import IDENTITE_DE_REPLI, lancer_git


@pytest.fixture
def depot(tmp_path):
    """Un vrai dépôt git avec un premier commit."""
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
    (tmp_path / "a.txt").write_text("un\n", "utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", *IDENTITE_DE_REPLI, "commit", "-q", "-m", "Premier"], cwd=tmp_path, check=True
    )
    return tmp_path


def test_une_commande_qui_reussit_rend_sa_sortie_sans_la_retoucher(depot):
    resultat = lancer_git(depot, "ls-files")
    assert resultat.returncode == 0
    assert resultat.stdout == "a.txt\n"
    assert resultat.args == ["git", "ls-files"]


def test_une_commande_qui_echoue_rend_son_code_et_son_message_sans_rien_lever(depot):
    resultat = lancer_git(depot, "rev-parse", "branche-inconnue")
    assert resultat.returncode != 0
    assert "branche-inconnue" in resultat.stderr


def test_un_delai_depasse_remonte(depot, monkeypatch):
    # Un faux git qui dort : la base doit transmettre le délai et laisser passer son dépassement.
    vrai_run = subprocess.run

    def run_qui_dort(commande, **options):
        return vrai_run([sys.executable, "-c", "import time; time.sleep(5)"], **options)

    monkeypatch.setattr(git.subprocess, "run", run_qui_dort)
    with pytest.raises(subprocess.TimeoutExpired):
        lancer_git(depot, "status", delai=0.2)


def test_sans_delai_git_a_tout_son_temps(depot, monkeypatch):
    options_vues = {}
    vrai_run = subprocess.run

    def run_espion(commande, **options):
        options_vues.update(options)
        return vrai_run(commande, **options)

    monkeypatch.setattr(git.subprocess, "run", run_espion)
    lancer_git(depot, "status")
    assert options_vues["timeout"] is None
    assert options_vues["stdin"] is subprocess.DEVNULL


def test_git_ne_peut_jamais_poser_de_question(depot, monkeypatch):
    # Ni l'environnement du processus ni les variables supplémentaires ne rouvrent les
    # questions. Git transmet son environnement à l'alias « !… », qui l'affiche.
    monkeypatch.setenv("GIT_TERMINAL_PROMPT", "1")
    resultat = lancer_git(
        depot, "-c", "alias.montre=!printenv GIT_TERMINAL_PROMPT", "montre",
        environnement={"GIT_TERMINAL_PROMPT": "1"},
    )  # fmt: skip
    assert resultat.stdout.strip() == "0"


def test_les_variables_supplementaires_sont_transmises(depot):
    resultat = lancer_git(
        depot, "-c", "alias.montre=!printenv ESSAI_ATELIER", "montre",
        environnement={"ESSAI_ATELIER": "bonjour"},
    )  # fmt: skip
    assert resultat.returncode == 0
    assert resultat.stdout.strip() == "bonjour"


def test_un_git_introuvable_remonte_en_oserror(depot, monkeypatch):
    monkeypatch.setenv("PATH", str(depot / "nulle-part"))
    with pytest.raises(OSError):
        lancer_git(depot, "status")
