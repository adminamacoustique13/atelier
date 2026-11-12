"""Les contrôles mécaniques : périmètre, commandes du projet, enregistrement dans git.

Chaque tâche travaille dans sa propre copie du dépôt (un « arbre de travail » git).
Deux agents en parallèle ne se voient donc pas, et rien n'entre dans la branche
principale sans avoir été vérifié.
"""

from __future__ import annotations

import os
import signal
import subprocess
import threading
from fnmatch import fnmatch
from pathlib import Path

TOUJOURS_PERMIS = ("chantier/relais/*",)
CAHIER = "chantier/CAHIER.md"
# Le temps laissé à chaque commande de contrôle du profil avant de l'arrêter : une suite de tests
# qui ne rend pas la main ne retient pas sa tâche pour toujours. Clé `delai_controles_s` du profil.
DELAI_CONTROLES_S = 1800


def expliquer_refus_git(message: str) -> str:
    """Traduit en clair les refus de git les plus courants face à un dépôt en ligne."""
    if any(m in message for m in ("Username", "Authentication", "Permission denied", "403")):
        return (
            "GitHub demande une connexion. Soit l'adresse est fausse, soit le dépôt est privé "
            "et git n'est pas encore connecté à ton compte sur cet ordinateur."
        )
    if "not found" in message or "does not exist" in message or "does not appear" in message:
        return "Aucun dépôt à cette adresse. Vérifie-la en l'ouvrant dans le navigateur."
    if "Could not resolve host" in message:
        return "Pas d'accès au réseau, ou nom de site mal écrit."
    if "fetch first" in message or "non-fast-forward" in message or "rejected" in message:
        return (
            "Le dépôt en ligne contient déjà des enregistrements que ce projet n'a pas "
            "(souvent un LISEZMOI créé par GitHub). Crée-le vide, sans aucun fichier, ou "
            "reprends-le plutôt avec « Reprendre un dépôt existant »."
        )
    return message


def hors_perimetre(fichiers: list[str], perimetre: list[str]) -> list[str]:
    """Rend les fichiers modifiés qui sortent du périmètre de la tâche."""
    motifs = list(perimetre) + list(TOUJOURS_PERMIS)
    return sorted(f for f in fichiers if not any(fnmatch(f, m) for m in motifs))


def se_chevauchent(a: list[str], b: list[str]) -> bool:
    """Dit si deux périmètres peuvent toucher un même fichier."""
    return any(fnmatch(x, y) or fnmatch(y, x) for x in a for y in b)


def lire_delai(valeur) -> float:
    """Le délai des contrôles lu dans un profil : un nombre de secondes positif, sinon 30 min."""
    correct = isinstance(valeur, (int, float)) and not isinstance(valeur, bool) and valeur > 0
    return float(valeur) if correct else float(DELAI_CONTROLES_S)


def lancer_commande(commande: str, dossier, delai_s: float) -> tuple[int | None, str]:
    """Lance une commande du profil ; rend (code de sortie, ce qu'elle a affiché).

    Le code est None si elle n'a pas fini dans le délai : elle est alors arrêtée avec tout ce
    qu'elle avait lancé (son propre groupe de processus, là où le système en a).
    """
    processus = subprocess.Popen(
        commande, shell=True, cwd=dossier, text=True, start_new_session=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )  # fmt: skip
    try:
        sortie, erreurs = processus.communicate(timeout=delai_s)
        return processus.returncode, f"{sortie}{erreurs}"
    except subprocess.TimeoutExpired:
        try:
            os.killpg(processus.pid, signal.SIGKILL)
        except (AttributeError, OSError):  # pas de groupe sur ce système, ou déjà fini
            processus.kill()
        try:
            sortie, erreurs = processus.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            sortie, erreurs = "", ""
        return None, f"{sortie}{erreurs}"


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

    def __init__(self, depot: Path, commandes: list[str] | None = None, delai_s=None):
        self.depot = Path(depot)
        self.commandes = commandes or []
        self.delai_s = lire_delai(delai_s)
        self.verrou_fusion = threading.Lock()
        self.envoi = ""  # dernier problème d'envoi vers le dépôt en ligne, vide si tout va bien
        self._distant: str | None = None
        self.identite: list[str] = []
        if not self._config("user.email"):
            # Sans nom git sur l'ordinateur, les enregistrements échoueraient : on signe Atelier.
            self.identite = ["-c", "user.name=Atelier", "-c", "user.email=atelier@localhost"]

    def _config(self, cle: str) -> str:
        resultat = subprocess.run(
            ["git", "config", cle], cwd=self.depot, capture_output=True, text=True
        )
        return resultat.stdout.strip()
        exclusions = self.depot / ".git" / "info" / "exclude"
        if exclusions.parent.exists() and ".atelier/" not in exclusions.read_text("utf-8"):
            with exclusions.open("a", encoding="utf-8") as fichier:
                fichier.write("\n.atelier/\n")

    def _git(self, *arguments: str, dossier: Path | None = None, delai: int = 120) -> str:
        # Pas de question posée par git : l'Atelier tourne sans terminal.
        env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
        try:
            signe = self.identite if arguments[0] in ("commit", "merge") else []
            resultat = subprocess.run(
                ["git", *signe, *arguments],
                cwd=dossier or self.depot,
                capture_output=True,
                text=True,
                env=env,
                timeout=delai,
            )
        except subprocess.TimeoutExpired as erreur:
            raise RuntimeError(f"git {arguments[0]} : pas de réponse à temps") from erreur
        if resultat.returncode != 0:
            raise RuntimeError(f"git {' '.join(arguments)} : {resultat.stderr.strip()}")
        return resultat.stdout

    def _arbre(self, tache) -> Path:
        return self.depot / ".atelier" / "arbres" / tache.id.replace("/", "_")

    def preparer(self, tache) -> Path:
        """Crée pour la tâche une copie de travail propre, partie de l'état vérifié."""
        arbre = self._arbre(tache)
        if arbre.exists():
            with self.verrou_fusion:
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
        """Lance les commandes du profil. S'arrête à la première qui échoue ou qui ne finit pas."""
        journal = []
        for commande in self.commandes:
            code, sortie = lancer_commande(commande, dossier, self.delai_s)
            journal.append(f"$ {commande}\n{sortie}")
            if code is None:
                journal.append(
                    f"Pas de réponse après {self.delai_s:g} secondes : la commande a été arrêtée "
                    "(réglage « delai_controles_s » du profil)."
                )
            if code != 0:
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
            self.enregistrer_cahier(f"Cahier : {tache.id} enregistrée")
        self.envoyer()

    def enregistrer_cahier(self, message: str) -> None:
        """Fait entrer le cahier du chantier dans l'historique, et lui seul."""
        self.enregistrer_fichier(CAHIER, message)

    def enregistrer_fichier(self, chemin: str, message: str) -> None:
        """Enregistre un fichier de l'atelier (cahier, profil) dans l'historique, et lui seul."""
        if not (self.depot / chemin).exists():
            return
        self._git("add", "--", chemin)
        if self._git("diff", "--cached", "--name-only", "--", chemin).strip():
            self._git("commit", "-q", "-m", message, "--", chemin)

    def regler_outils(self, profil: dict) -> None:
        """Prend en compte un nouveau profil et l'enregistre, puis l'envoie s'il y a lieu."""
        self.commandes = list(profil.get("commandes", []))
        self.delai_s = lire_delai(profil.get("delai_controles_s"))
        with self.verrou_fusion:
            self.enregistrer_fichier("chantier/profil.json", "Outils du projet")
        self.envoyer()

    def distant(self) -> str:
        """Adresse du dépôt en ligne (origin), ou chaîne vide s'il n'y en a pas."""
        if self._distant is None:
            try:
                self._distant = self._git("remote", "get-url", "origin").strip()
            except RuntimeError:
                self._distant = ""
        return self._distant

    def relier(self, adresse: str) -> None:
        """Relie le projet à un dépôt en ligne et y envoie tout ce qui est déjà enregistré."""
        adresse = adresse.strip()
        if not adresse or adresse.startswith("-"):
            raise ValueError("Colle l'adresse du dépôt, par exemple https://github.com/moi/projet.")
        with self.verrou_fusion:
            self.enregistrer_cahier("Cahier du chantier")
            action = "set-url" if self.distant() else "add"
            self._git("remote", action, "origin", adresse)
            self._distant = adresse
        self.envoyer(lever=True)

    def envoyer(self, lever: bool = False) -> None:
        """Envoie la branche courante vers le dépôt en ligne, s'il y en a un.

        Un échec n'annule rien : le travail reste enregistré sur l'ordinateur, et le
        problème s'affiche au tableau de bord jusqu'au prochain envoi réussi.
        """
        if not self.distant():
            return
        try:
            with self.verrou_fusion:
                self._git("push", "-q", "-u", "origin", "HEAD", delai=300)
            self.envoi = ""
        except RuntimeError as erreur:
            self.envoi = expliquer_refus_git(str(erreur))
            if lever:
                raise ValueError(self.envoi) from erreur

    def annuler(self, tache, dossier) -> None:
        """Jette le travail refusé : la tentative suivante repartira d'un état propre."""
        if dossier and Path(dossier).exists():
            with self.verrou_fusion:
                self._git("worktree", "remove", "--force", str(dossier))
