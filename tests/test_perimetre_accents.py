"""Un fichier au nom accentué (ou à espace, guillemet, apostrophe) est reconnu dans son périmètre.

Vrais dépôts git dans `tmp_path`, vraie chaîne du produit : `fichiers_modifies` puis
`hors_perimetre`. Git, sans `-z`, écrit ces noms entre guillemets avec des codes octaux.
"""

import subprocess
from types import SimpleNamespace

import pytest

from atelier.controles import ControlesGit, hors_perimetre

NOMS = [
    "docs/été.md",
    "notes de chantier.md",
    'docs/dit "oui".md',
    "docs/l'été.md",
]


def git(dossier, *arguments):
    return subprocess.run(["git", *arguments], cwd=dossier, check=True,
                          capture_output=True, text=True).stdout  # fmt: skip


def depot(dossier, fichiers=()):
    git(dossier, "init", "-q", "-b", "main")
    git(dossier, "config", "user.name", "Essai")
    git(dossier, "config", "user.email", "essai@example.invalid")
    git(dossier, "config", "core.quotePath", "true")
    (dossier / "LISEZMOI.md").write_text("socle\n", "utf-8")
    for nom in fichiers:
        (dossier / nom).parent.mkdir(parents=True, exist_ok=True)
        (dossier / nom).write_text("socle\n", "utf-8")
    git(dossier, "add", "-A")
    git(dossier, "commit", "-q", "-m", "socle")
    return ControlesGit(dossier), SimpleNamespace(id="A", titre="Essai")


def debords(controles, tache, perimetre):
    modifies = controles.fichiers_modifies(tache, controles.depot, None)
    return modifies, hors_perimetre(modifies, perimetre)


@pytest.mark.parametrize("quote_path", ["true", "false"])
@pytest.mark.parametrize("nom", NOMS)
def test_un_fichier_modifie_a_nom_special_est_dans_son_perimetre(tmp_path, nom, quote_path):
    controles, tache = depot(tmp_path, [nom])
    git(tmp_path, "config", "core.quotePath", quote_path)
    (tmp_path / nom).write_text("changé\n", "utf-8")
    modifies, hors = debords(controles, tache, [nom])
    assert modifies == [nom] and hors == []


@pytest.mark.parametrize("quote_path", ["true", "false"])
def test_un_fichier_nouveau_non_suivi_a_nom_special_est_dans_son_perimetre(tmp_path, quote_path):
    controles, tache = depot(tmp_path)
    git(tmp_path, "config", "core.quotePath", quote_path)
    for nom in NOMS:
        (tmp_path / nom).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / nom).write_text("neuf\n", "utf-8")
    modifies, hors = debords(controles, tache, NOMS)
    assert sorted(modifies) == sorted(NOMS) and hors == []


def test_un_fichier_supprime_a_nom_special_est_dans_son_perimetre(tmp_path):
    controles, tache = depot(tmp_path, NOMS)
    for nom in NOMS:
        (tmp_path / nom).unlink()
    modifies, hors = debords(controles, tache, NOMS)
    assert sorted(modifies) == sorted(NOMS) and hors == []


def test_un_renommage_accentue_voit_l_ancien_et_le_nouveau_nom(tmp_path):
    controles, tache = depot(tmp_path, ["docs/été.md"])
    git(tmp_path, "mv", "docs/été.md", "docs/hiver d'été.md")
    modifies, hors = debords(controles, tache, ["docs/été.md", "docs/hiver d'été.md"])
    assert sorted(modifies) == ["docs/hiver d'été.md", "docs/été.md"] and hors == []
    # Si l'ancien nom sort du périmètre, c'est un débord : sa suppression est une modification.
    assert debords(controles, tache, ["docs/hiver d'été.md"])[1] == ["docs/été.md"]


@pytest.mark.parametrize("quote_path", ["true", "false"])
def test_un_fichier_accentue_hors_perimetre_est_signale_sous_son_vrai_nom(tmp_path, quote_path):
    controles, tache = depot(tmp_path)
    git(tmp_path, "config", "core.quotePath", quote_path)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "été.md").write_text("neuf\n", "utf-8")
    (tmp_path / "calcul.py").write_text("x = 1\n", "utf-8")
    _, hors = debords(controles, tache, ["calcul.py"])
    assert hors == ["docs/été.md"]
    assert (tmp_path / hors[0]).exists()


def test_les_noms_ordinaires_gardent_la_meme_liste_dans_le_meme_ordre(tmp_path):
    controles, tache = depot(tmp_path, ["a.py", "src/b.py"])
    (tmp_path / "src" / "b.py").write_text("y\n", "utf-8")
    (tmp_path / "a.py").unlink()
    (tmp_path / "z.txt").write_text("z\n", "utf-8")
    (tmp_path / "m").mkdir()
    (tmp_path / "m" / "n.txt").write_text("n\n", "utf-8")
    attendu = [
        ligne[3:] for ligne in
        git(tmp_path, "status", "--porcelain", "--untracked-files=all").splitlines()
    ]  # fmt: skip
    assert controles.fichiers_modifies(tache, tmp_path, None) == attendu
