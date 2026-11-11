"""La mise à jour d'Atelier : savoir si le dépôt en ligne a avancé, puis tirer le nouveau code.

Atelier vit dans un clone git de son dépôt en ligne. Ce module ne connaît ni le serveur ni la
page : il rend des phrases en français, l'appelant les affiche. Il ne s'arrête jamais lui-même ;
quand `Resultat.fait` est vrai, c'est à l'appelant de s'arrêter pour être relancé sur le
nouveau code.
"""

from __future__ import annotations

import os
import re
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

BRANCHE = "main"
DELAI_GIT_S = 60

_CAUSES = (  # (morceaux de la sortie de git, cause en mots simples), du plus précis au plus large
    (("terminal prompts disabled", "authentication failed", "could not read username",
      "permission denied"), "le dépôt en ligne demande un identifiant qu'Atelier n'a pas"),
    (("could not resolve host", "unable to access", "connection", "timed out",
      "network is unreachable", "early eof"), "le dépôt en ligne ne répond pas"),
    (("does not appear to be a git repository", "not found", "could not read from remote",
      "no such remote"), "le dépôt en ligne est introuvable"),
)
_DIVERGENCE = ("not possible to fast-forward", "divergent branches", "diverging branches")
_GENERIQUE = "git n'a pas pu aller au bout"
_SANS_REPONSE = "le dépôt en ligne ne répond pas"


@dataclass(frozen=True)
class Etat:
    disponible: bool
    phrase: str
    verifie: bool  # faux tant qu'aucune interrogation du dépôt en ligne n'a réussi


@dataclass(frozen=True)
class Resultat:
    fait: bool  # vrai : le code a changé, il faut redémarrer
    phrase: str
    detail: str = ""  # sortie brute de git, pour le journal seulement


def _nettoyer(texte: str) -> str:
    """Retire d'un texte les identifiants glissés dans une adresse (https://nom:mdp@hote)."""
    return re.sub(r"://[^/@\s]+@", "://***@", texte).strip()[:500]


def _git(dossier: Path, *arguments: str) -> tuple[int | None, str, str]:
    """Lance git sans shell ni saisie possible. Rend (code, sortie, erreur) ; code None = délai."""
    env = dict(
        os.environ,
        GIT_TERMINAL_PROMPT="0",
        GIT_ASKPASS="",
        GIT_EDITOR="true",
        GIT_MERGE_AUTOEDIT="no",
        GIT_SSH_COMMAND="ssh -o BatchMode=yes",
        LC_ALL="C",
    )
    try:
        r = subprocess.run(
            ["git", *arguments], cwd=dossier, capture_output=True, text=True, env=env,
            stdin=subprocess.DEVNULL, timeout=DELAI_GIT_S,
        )
    except subprocess.TimeoutExpired:
        return None, "", "délai dépassé"
    except OSError as erreur:
        return -1, "", str(erreur)
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def _cause(code: int | None, erreur: str) -> str:
    if code is None:
        return _SANS_REPONSE
    bas = erreur.lower()
    for morceaux, cause in _CAUSES:
        if any(m in bas for m in morceaux):
            return cause
    return _GENERIQUE


class MiseAJour:
    """Vérifie et applique la mise à jour du clone d'Atelier. Aucune méthode ne lève."""

    def __init__(self, dossier: Path, intervalle_s: float = 3600, horloge=time.monotonic):
        self.dossier = Path(dossier)
        self.intervalle_s = intervalle_s
        self.horloge = horloge
        self._verrou = threading.Lock()
        self._derniere: float | None = None
        self._etat = Etat(False, "La vérification n'a pas encore eu lieu.", False)

    def verifier(self) -> Etat:
        """Rend la dernière réponse connue ; interroge le dépôt en ligne au plus une fois
        par intervalle, et jamais deux fois en même temps."""
        if not self._verrou.acquire(blocking=False):
            return self._etat  # une interrogation est déjà en cours dans un autre fil
        try:
            maintenant = self.horloge()
            if self._derniere is None or maintenant - self._derniere >= self.intervalle_s:
                self._derniere = maintenant  # même un échec n'est pas retenté avant l'intervalle
                self._etat = self._interroger(self._etat)
            return self._etat
        except Exception:  # noqa: BLE001 - verifier ne doit jamais lever
            return self._etat
        finally:
            self._verrou.release()

    def _interroger(self, avant: Etat) -> Etat:
        code, sortie, erreur = _git(self.dossier, "ls-remote", "origin", f"refs/heads/{BRANCHE}")
        if code != 0 or not sortie:
            cause = _cause(code, erreur) if code != 0 else "la branche main n'existe pas en ligne"
            return Etat(avant.disponible, f"Impossible de vérifier pour l'instant : {cause}.",
                        avant.verifie)
        en_ligne = sortie.split()[0]
        # Rien n'est écrit : le dépôt en ligne a avancé si son commit n'est pas déjà dans le nôtre.
        present = _git(self.dossier, "cat-file", "-e", f"{en_ligne}^{{commit}}")[0] == 0
        ancetre = _git(self.dossier, "merge-base", "--is-ancestor", en_ligne, "HEAD")
        if present and ancetre[0] == 0:
            return Etat(False, "Atelier est à jour.", True)
        return Etat(True, "Une mise à jour d'Atelier est disponible.", True)

    def mettre_a_jour(self, agent_au_travail: bool) -> Resultat:
        """`git pull --ff-only origin main` dans le dossier d'Atelier, après les refus."""
        try:
            refus = self._refus(agent_au_travail)
            return refus if refus else self._tirer()
        except Exception as erreur:  # noqa: BLE001 - mettre_a_jour ne doit jamais lever
            return Resultat(False, "Mise à jour impossible : " + _GENERIQUE + ".",
                            _nettoyer(str(erreur)))

    def _refus(self, agent_au_travail: bool) -> Resultat | None:
        if agent_au_travail:
            return Resultat(False, "Mise à jour impossible : un agent travaille. "
                                   "Réessaie quand il aura fini.")
        code, branche, erreur = _git(self.dossier, "symbolic-ref", "--short", "-q", "HEAD")
        if code == 1 and not erreur:
            branche = ""  # tête détachée : pas sur main
        elif code != 0:
            return Resultat(False, f"Mise à jour impossible : {_GENERIQUE}.", _nettoyer(erreur))
        if branche != BRANCHE:
            return Resultat(False, "Mise à jour impossible : le dossier d'Atelier "
                                   "n'est pas sur la branche main.")
        code, sortie, erreur = _git(self.dossier, "status", "--porcelain", "--untracked-files=no")
        if code != 0:
            return Resultat(False, f"Mise à jour impossible : {_GENERIQUE}.", _nettoyer(erreur))
        if sortie:
            return Resultat(False, "Mise à jour impossible : le dossier d'Atelier contient des "
                                   "modifications qui ne viennent pas du dépôt en ligne.")
        return None

    def _tirer(self) -> Resultat:
        avant = _git(self.dossier, "rev-parse", "HEAD")[1]
        code, sortie, erreur = _git(self.dossier, "pull", "--ff-only", "origin", BRANCHE)
        detail = _nettoyer(sortie + "\n" + erreur)
        if code != 0:
            if any(m in erreur.lower() for m in _DIVERGENCE):
                cause = "l'histoire du dossier d'Atelier a divergé de celle du dépôt en ligne"
            else:
                cause = _cause(code, erreur)
            return Resultat(False, f"Mise à jour impossible : {cause}.", detail)
        if _git(self.dossier, "rev-parse", "HEAD")[1] == avant:
            return Resultat(False, "Atelier est déjà à jour.", detail)
        with self._verrou:
            self._etat = Etat(False, "Atelier est à jour.", True)
        return Resultat(True, "Atelier a été mis à jour. Il va redémarrer.", detail)


class MiseAJourSimulee:
    """Double pour la démonstration : même interface, ni git ni réseau."""

    def verifier(self) -> Etat:
        return Etat(True, "Une mise à jour d'Atelier est disponible.", True)

    def mettre_a_jour(self, agent_au_travail: bool) -> Resultat:
        if agent_au_travail:
            return Resultat(False, "Mise à jour impossible : un agent travaille. "
                                   "Réessaie quand il aura fini.")
        return Resultat(True, "Mise à jour simulée : rien n'a changé.")
