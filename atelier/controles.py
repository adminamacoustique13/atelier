"""Les contrôles mécaniques : périmètre, commandes du projet, enregistrement dans git.

Chaque tâche travaille dans sa propre copie du dépôt (un « arbre de travail » git).
Deux agents en parallèle ne se voient donc pas, et rien n'entre dans la branche
principale sans avoir été vérifié.
"""

from __future__ import annotations

import subprocess
import threading
from fnmatch import fnmatch
from pathlib import Path

TOUJOURS_PERMIS = ("chantier/relais/*",)


def hors_perimetre(fichiers: list[str], perimetre: list[str]) -> list[str]:
    """Rend les fichiers modifiés qui sortent du périmètre de la tâche."""
    motifs = list(perimetre) + list(TOUJOURS_PERMIS)
    return sorted(f for f in fichiers if not any(fnmatch(f, m) for m in motifs))


def se_chevauchent(a: list[str], b: list[str]) -> bool:
    """Dit si deux périmètres peuvent toucher un même fichier."""
    return any(fnmatch(x, y) or fnmatch(y, x) for x in a for y in b)


class ControlesSimules:
    """Contrôles sans git ni commandes : pour la démonstration et les tests du moteur."""

    def preparer(self, tache) -> Path | None:
        return None

    def fichiers_modifies(self, tache, dossier, resultat) -> list[str]:
        return list(resultat.fichiers or [])

    def mecaniques(self, tache, dossier) -> tuple[bool, str]:
        return True, ""

    def enregistrer(self, tache, dossier) -> None:
        return None

    def annuler(self, tache, dossier) -> None:
        return None


class ControlesGit:
    """Contrôles réels : un arbre de travail par tâche, commandes du profil, fusion après accord."""

    def __init__(self, depot: Path, commandes: list[str] | None = None):
        self.depot = Path(depot)
        self.commandes = commandes or []
        self.verrou_fusion = threading.Lock()
        exclusions = self.depot / ".git" / "info" / "exclude"
        if exclusions.parent.exists() and ".atelier/" not in exclusions.read_text("utf-8"):
            with exclusions.open("a", encoding="utf-8") as fichier:
                fichier.write("\n.atelier/\n")

    def _git(self, *arguments: str, dossier: Path | None = None) -> str:
        resultat = subprocess.run(
            ["git", *arguments], cwd=dossier or self.depot, capture_output=True, text=True
        )
        if resultat.returncode != 0:
            raise RuntimeError(f"git {' '.join(arguments)} : {resultat.stderr.strip()}")
        return resultat.stdout

    def _arbre(self, tache) -> Path:
        return self.depot / ".atelier" / "arbres" / tache.id.replace("/", "_")

    def preparer(self, tache) -> Path:
        """Crée pour la tâche une copie de travail propre, partie de l'état vérifié."""
        arbre = self._arbre(tache)
        if arbre.exists():
            self._git("worktree", "remove", "--force", str(arbre))
        arbre.parent.mkdir(parents=True, exist_ok=True)
        with self.verrou_fusion:
            self._git("worktree", "add", "-q", "-B", f"tache/{tache.id}", str(arbre), "HEAD")
        return arbre

    def fichiers_modifies(self, tache, dossier, resultat) -> list[str]:
        """Rend les fichiers réellement modifiés, lus dans git et non dans le compte rendu."""
        sortie = self._git("status", "--porcelain", "--untracked-files=all", dossier=dossier)
        return [ligne[3:].split(" -> ")[-1].strip('"') for ligne in sortie.splitlines() if ligne]

    def mecaniques(self, tache, dossier) -> tuple[bool, str]:
        """Lance les commandes du profil. S'arrête à la première qui échoue."""
        journal = []
        for commande in self.commandes:
            resultat = subprocess.run(
                commande, shell=True, cwd=dossier, capture_output=True, text=True
            )
            journal.append(f"$ {commande}\n{resultat.stdout}{resultat.stderr}")
            if resultat.returncode != 0:
                return False, "\n".join(journal)
        return True, "\n".join(journal)

    def enregistrer(self, tache, dossier) -> None:
        """Enregistre le travail vérifié et le fait entrer dans la branche principale."""
        self._git("add", "-A", dossier=dossier)
        if self._git("status", "--porcelain", dossier=dossier).strip():
            self._git("commit", "-q", "-m", f"{tache.id} : {tache.titre}", dossier=dossier)
        with self.verrou_fusion:
            self._git("merge", "-q", "--no-edit", f"tache/{tache.id}")
            self._git("worktree", "remove", "--force", str(dossier))
            self._git("branch", "-q", "-D", f"tache/{tache.id}")

    def annuler(self, tache, dossier) -> None:
        """Jette le travail refusé : la tentative suivante repartira d'un état propre."""
        if dossier and Path(dossier).exists():
            self._git("worktree", "remove", "--force", str(dossier))
