"""Les contrôles mécaniques : périmètre, commandes du projet, enregistrement dans git.

Chaque tâche travaille dans sa propre copie du dépôt (un « arbre de travail » git).
Deux agents en parallèle ne se voient donc pas, et rien n'entre dans la branche
principale sans avoir été vérifié.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from collections.abc import Iterable
from contextlib import suppress
from datetime import datetime
from fnmatch import fnmatch
from pathlib import Path

from atelier.git import IDENTITE_DE_REPLI, lancer_git
from atelier.modele import ecrire_d_un_seul_geste

TOUJOURS_PERMIS = ("chantier/relais/*",)
CAHIER = "chantier/CAHIER.md"
# Combien de fois une tâche rejoue la branche principale qui a bougé pendant ses contrôles.
ESSAIS_INTEGRATION = 3
# Les fichiers partagés à fusionner en « union », lus par git pour les fusions de l'Atelier.
FICHIER_UNIONS = Path(".atelier") / "unions.gitattributes"


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


# Les caches que git ignore et qu'une copie de vérification n'a pas à partager.
CACHES = {"__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache", ".DS_Store"}


def _chemins_du_statut(sortie: str) -> list[str]:
    """Les chemins d'un `git status --porcelain -z` : pour un renommage, le nouveau et l'ancien."""
    chemins, morceaux = [], sortie.split("\0")
    while morceaux:
        ligne = morceaux.pop(0)
        if len(ligne) < 4:
            continue
        chemins.append(ligne[3:])
        if ligne[0] in "RC" and morceaux:
            chemins.append(morceaux.pop(0))
    return chemins


def _relier(source: Path, cible: Path) -> None:
    """Relie un fichier ignoré par un lien. Un dossier, lui, est recréé et c'est son contenu
    qui est relié : git ne reconnaît pas un lien comme le dossier ignoré (« node_modules/ »)."""
    if cible.exists() or cible.is_symlink():
        return
    cible.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir() and not source.is_symlink():
        cible.mkdir()
        for element in source.iterdir():
            (cible / element.name).symlink_to(element)
    else:
        cible.symlink_to(source)


def _correspond(chemin: str, motif: str) -> bool:
    """Dit si le chemin est égal au motif, ou y correspond au sens de `fnmatch`.

    L'égalité d'abord : `fnmatch` lit `[slug]` comme une classe de caractères, et un chemin
    à crochets ne se reconnaîtrait pas lui-même.
    """
    return chemin == motif or fnmatch(chemin, motif)


def hors_perimetre(fichiers: list[str], perimetre: list[str]) -> list[str]:
    """Rend les fichiers modifiés qui sortent du périmètre de la tâche."""
    motifs = list(perimetre) + list(TOUJOURS_PERMIS)
    return sorted(f for f in fichiers if not any(_correspond(f, m) for m in motifs))


def se_chevauchent(a: list[str], b: list[str], partages: Iterable[str] = ()) -> bool:
    """Dit si deux périmètres peuvent toucher un même fichier qui n'est pas partagé.

    `partages` : les motifs des fichiers partagés (`fichiers_partages`). Une entrée de périmètre
    que l'un d'eux couvre ne retient personne : plusieurs tâches peuvent y travailler en même
    temps, et leurs changements y sont fusionnés à l'entrée dans la branche principale.
    """
    motifs = list(partages)
    a = [p for p in a if not motif_partage(p, motifs)]
    b = [p for p in b if not motif_partage(p, motifs)]
    return any(_correspond(x, y) or _correspond(y, x) for x in a for y in b)


def motif_partage(chemin: str, motifs: Iterable[str]) -> str:
    """Le premier motif de fichier partagé qui couvre ce chemin ou cette entrée de périmètre,
    ou "" s'il n'est pas partagé."""
    return next((motif for motif in motifs if _correspond(chemin, motif)), "")


# Les deux façons de fusionner un fichier partagé : « union » garde les lignes des deux côtés,
# sans jamais de conflit ; « git » fusionne comme d'habitude, et un conflit revient à l'ouvrier.
FUSIONS = ("union", "git")


def fichiers_partages(profil: dict) -> dict[str, str]:
    """Les fichiers partagés que déclare le profil (clé `fichiers_partages`) : motif -> fusion.

    Chaque entrée est un objet `{"motif": "<motif glob>", "fusion": "union" | "git"}`, `fusion`
    absente valant « git ». Une entrée mal formée est ignorée : pas un objet, fusion inconnue,
    motif vide, avec un espace, ou qui commence par « # » ou « ! » (ces trois-là casseraient la
    ligne du fichier d'attributs, voir `ControlesGit._reglages`). Une clé absente ou qui n'est
    pas une liste n'en déclare aucun.
    """
    entrees = profil.get("fichiers_partages") if isinstance(profil, dict) else None
    partages: dict[str, str] = {}
    for entree in entrees if isinstance(entrees, list) else []:
        if not isinstance(entree, dict):
            continue
        motif, fusion = entree.get("motif"), entree.get("fusion", "git")
        mots = motif.split() if isinstance(motif, str) else []
        if len(mots) == 1 and not mots[0].startswith(("#", "!")) and fusion in FUSIONS:
            partages[mots[0]] = fusion
    return partages


# Ce que `poser_conflits` dit de chaque fichier en conflit : deux versions réunies dans le fichier
# par des marqueurs, ou un fichier supprimé d'un côté et modifié de l'autre (sans marqueurs).
MARQUEURS = "marqueurs"
SUPPRIME_SUR_LA_PRINCIPALE = "supprime_sur_la_principale"
SUPPRIME_PAR_LA_TACHE = "supprime_par_la_tache"
# Le début d'une ligne de marqueur de conflit laissée par git ; « ======= » seul n'en est pas
# un sûr : c'est aussi un soulignement de titre en Markdown.
DEBUTS_DE_MARQUEUR = ("<<<<<<< ", ">>>>>>> ")
# Où une copie de tâche garde la liste de ses fichiers rendus avec des marqueurs : dans le dossier
# git propre à cette copie (`.git/worktrees/<tâche>/`), hors des fichiers du projet. La liste
# survit à un redémarrage de l'Atelier et disparaît avec la copie (retrait, entrée, oubli).
FICHIER_MARQUEURS = "atelier-marqueurs.json"
# Combien de fois `empreinte` recommence quand la copie change pendant son calcul.
ESSAIS_EMPREINTE = 3


# Le temps laissé à chaque commande de contrôle du profil avant de l'arrêter : une suite de tests
# qui ne rend pas la main ne retient pas sa tâche pour toujours. Clé `delai_controles_s` du profil.
DELAI_CONTROLES_S = 1800


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

    def enregistrer(self, tache, dossier) -> str:
        return ""

    def controler_principale(self) -> tuple[bool, str]:
        return True, ""

    def annuler(self, tache, dossier) -> None:
        return None

    def etat_du_depot(self, taches, profil: dict | None = None) -> dict:
        """Un état du dépôt d'exemple, sans git, de la même forme que `ControlesGit`."""
        return etat_du_depot_d_exemple(taches)

    # Sans copie de travail, rien n'est jamais gardé : versions neutres des trois méthodes de la
    # copie gardée (voir `ControlesGit`), dont héritent aussi les doubles des tests.

    def copie_existante(self, dossier) -> bool:
        return False

    def place_de_la_copie(self, tache) -> Path | None:
        return None

    def empreinte(self, dossier) -> str:
        return ""

    def differences(self, dossier, avant: str, apres: str = "") -> list[str]:
        return []

    def conflit_pose(self, dossier) -> bool:
        return False


class ControlesGit:
    """Contrôles réels : un arbre de travail par tâche, commandes du profil, fusion après accord."""

    def __init__(
        self,
        depot: Path,
        commandes: list[str] | None = None,
        delai_s=None,
        partages: dict[str, str] | None = None,
    ):
        self.depot = Path(depot)
        self.commandes = commandes or []
        self.delai_s = lire_delai(delai_s)
        self.verrou_fusion = threading.Lock()
        self.envoi = ""  # dernier problème d'envoi vers le dépôt en ligne, vide si tout va bien
        self._distant: str | None = None
        self.identite: tuple[str, ...] = ()
        if not self._config("user.email"):
            # Sans nom git sur l'ordinateur, les enregistrements échoueraient : on signe Atelier.
            self.identite = IDENTITE_DE_REPLI
        partages = partages or {}
        self.unions = [motif for motif, fusion in partages.items() if fusion == "union"]
        self._verrou_unions = threading.Lock()  # `FICHIER_UNIONS` s'écrit d'un seul geste
        # Par tâche, les fichiers rendus à l'ouvrier avec des marqueurs (`poser_conflits`) : ils
        # n'entrent pas tant qu'il en reste (`enregistrer`). La liste vit dans la copie
        # (`FICHIER_MARQUEURS`) ; ici, seulement un raccourci : tâche -> (copie, liste).
        self._a_marqueurs: dict[str, tuple[str, list[str]]] = {}

    def _config(self, cle: str) -> str:
        # Une clé absente (git rend un code d'erreur) donne une valeur vide.
        return lancer_git(self.depot, "config", cle).stdout.strip()

    def _reglages(self, commande: str) -> tuple[str, ...]:
        """Les réglages mis devant une commande git : l'identité pour ce qui enregistre ou
        fusionne ; pour une fusion, en plus, les fichiers partagés en « union ».

        Ceux-ci sont écrits juste avant, dans `FICHIER_UNIONS`, que git lit comme ses attributs
        (`core.attributesFile`) : dans ces fichiers, il garde les lignes des deux côtés au lieu
        de s'arrêter sur un conflit. Rien n'est écrit dans `.git/` ni enregistré dans le projet.
        Chaque motif est ancré à la racine (`/<motif>`), et git n'y fait pas traverser les
        dossiers à `*` : il ne couvre jamais plus que le même motif lu par fnmatch.
        """
        if commande not in ("commit", "merge"):
            return ()
        if commande == "commit" or not self.unions:
            return self.identite
        chemin = self.depot / FICHIER_UNIONS
        with self._verrou_unions:
            ecrire_d_un_seul_geste(chemin, "".join(f"/{m} merge=union\n" for m in self.unions))
        return (*self.identite, "-c", f"core.attributesFile={chemin}")

    def _git(self, *arguments: str, dossier: Path | None = None, delai: int = 120) -> str:
        # Un échec ou un délai dépassé devient une RuntimeError ; une OSError remonte.
        try:
            reglages = self._reglages(arguments[0])
            resultat = lancer_git(dossier or self.depot, *reglages, *arguments, delai=delai)
        except subprocess.TimeoutExpired as erreur:
            raise RuntimeError(f"git {arguments[0]} : pas de réponse à temps") from erreur
        if resultat.returncode != 0:
            raise RuntimeError(f"git {' '.join(arguments)} : {resultat.stderr.strip()}")
        return resultat.stdout

    def _arbre(self, tache) -> Path:
        return self.depot / ".atelier" / "arbres" / tache.id.replace("/", "_")

    def preparer(self, tache) -> Path:
        """Crée pour la tâche une copie de travail propre, partie de l'état vérifié.

        Une copie gardée qui n'est plus utilisable (effacée à la main, ou un dossier que git ne
        connaît plus) ne retient rien : son dossier est retiré, et git oublie d'abord les copies
        disparues, qui garderaient sinon la branche de la tâche.
        """
        self._a_marqueurs.pop(tache.id, None)
        arbre = self._arbre(tache)
        if arbre.exists():
            self._retirer_arbre(arbre)
        arbre.parent.mkdir(parents=True, exist_ok=True)
        with self.verrou_fusion:
            self._git("worktree", "prune")
            self._git("worktree", "add", "-q", "-B", f"tache/{tache.id}", str(arbre), "HEAD")
        return arbre

    def _retirer_arbre(self, arbre: Path) -> None:
        """Retire une copie de travail de tâche, même quand git ne la reconnaît plus.

        Le dossier n'est effacé à la main que s'il est rangé parmi les copies des tâches.
        """
        with self.verrou_fusion, suppress(RuntimeError):
            self._git("worktree", "remove", "--force", str(arbre))
        if arbre.exists() and self._parmi_les_arbres(arbre):
            shutil.rmtree(arbre, ignore_errors=True)
        with self.verrou_fusion, suppress(RuntimeError):
            self._git("worktree", "prune")

    def _parmi_les_arbres(self, dossier: Path) -> bool:
        """Dit si le dossier est une copie de tâche de ce dépôt : un dossier direct de
        `.atelier/arbres/`, hors la copie de contrôle de la branche principale."""
        racine = (self.depot / ".atelier" / "arbres").resolve()
        try:
            chemin = Path(dossier).resolve()
        except (OSError, ValueError):  # un chemin impossible (caractère nul…) n'en est pas une
            return False
        return chemin.parent == racine and chemin.name != "_principale"

    def place_de_la_copie(self, tache) -> Path:
        """Le chemin que l'Atelier donne à la copie de travail de cette tâche : une copie gardée
        qui nomme un autre chemin n'est pas la sienne, et ne se reprend ni ne se jette."""
        return self._arbre(tache)

    # --- la copie gardée : la reconnaître, et savoir si son contenu a changé ----------

    def copie_existante(self, dossier) -> bool:
        """Dit si `dossier` est une copie de travail utilisable de ce dépôt.

        Vrai seulement pour une copie de tâche rangée à sa place (`.atelier/arbres/<tâche>`),
        que git reconnaît comme une copie de ce dépôt-ci, avec un commit de départ lisible.
        Un dossier effacé, vidé, venu d'ailleurs ou que git a oublié rend False, comme un chemin
        impossible. Ne lève pas.
        """
        try:
            return bool(dossier) and self._copie_reconnue(Path(dossier))
        except (RuntimeError, OSError, ValueError):
            return False

    def _copie_reconnue(self, dossier: Path) -> bool:
        """`copie_existante`, qui peut lever : le chemin est lu une fois résolu."""
        if not self._parmi_les_arbres(dossier):
            return False
        chemin = dossier.resolve()
        if not chemin.is_dir() or not (chemin / ".git").exists():
            return False
        commun = self._git("rev-parse", "--git-common-dir", dossier=chemin).strip()
        racine = self._git("rev-parse", "--show-toplevel", dossier=chemin).strip()
        self._git("rev-parse", "-q", "--verify", "HEAD", dossier=chemin)
        attendu = self._git("rev-parse", "--git-common-dir").strip()
        meme_depot = (chemin / commun).resolve() == (self.depot / attendu).resolve()
        return meme_depot and Path(racine).resolve() == chemin

    def empreinte(self, dossier) -> str:
        """Un texte qui change si et seulement si le contenu de la copie change.

        C'est l'identifiant git de l'arbre de tous ses fichiers, suivis ou non (ceux que git
        ignore exceptés ; le contenu d'un dépôt git imbriqué non plus n'est pas vu). Il est
        calculé dans un index provisoire, hors de la copie : ni l'index de la copie ni ses
        fichiers ne sont touchés. Ne lève jamais : quand le calcul échoue, même après
        `ESSAIS_EMPREINTE` essais (la copie change pendant le calcul, git échoue, ce n'est pas une
        copie), elle rend "", qui veut dire « inconnue », jamais « inchangée ».
        """
        for _ in range(ESSAIS_EMPREINTE):
            with suppress(RuntimeError, OSError, ValueError, subprocess.TimeoutExpired):
                return self._empreinte(Path(dossier))
        return ""

    def _empreinte(self, dossier: Path) -> str:
        """Un essai d'`empreinte`, qui lève si git échoue."""
        provisoire = Path(tempfile.mkdtemp(prefix="atelier-empreinte-"))
        try:
            index = provisoire / "index"
            reel = Path(self._git("rev-parse", "--git-path", "index", dossier=dossier).strip())
            reel = reel if reel.is_absolute() else dossier / reel
            if reel.exists():
                shutil.copyfile(reel, index)  # garde ce que git sait déjà : plus rapide
            environnement = {"GIT_INDEX_FILE": str(index)}
            for arguments in (("add", "-A"), ("write-tree",)):
                resultat = lancer_git(dossier, *arguments, delai=120, environnement=environnement)
                if resultat.returncode != 0:
                    raise RuntimeError(f"git {arguments[0]} : {resultat.stderr.strip()}")
            empreinte = resultat.stdout.strip()
            if not empreinte:
                raise RuntimeError("git write-tree : rien rendu")
            return empreinte
        finally:
            shutil.rmtree(provisoire, ignore_errors=True)

    def differences(self, dossier, avant: str, apres: str = "") -> list[str]:
        """Les fichiers qui diffèrent entre deux empreintes de la copie, triés.

        `apres` vide : l'empreinte de la copie maintenant. Un fichier renommé compte sous ses
        deux noms. Une empreinte vide (« inconnue ») ou illisible ne compare rien et rend une
        liste vide : savoir si rien n'a changé demande deux empreintes non vides. Ne lève pas.
        """
        apres = apres or (self.empreinte(dossier) if avant else "")
        if not avant or not apres or avant == apres:
            return []
        try:
            sortie = self._git(
                "diff", "--name-only", "-z", "--no-renames", avant, apres, dossier=Path(dossier)
            )
        except (RuntimeError, OSError, ValueError):
            return []
        return sorted(nom for nom in sortie.split("\0") if nom)

    def _copie(self, tache) -> Path:
        return self.depot / ".atelier" / "verifications" / tache.id.replace("/", "_")

    def copie_de_verification(self, tache, dossier) -> Path:
        """Une copie jetable du livrable, pour que le vérificateur y fasse ses essais.

        Elle part du même commit que la copie de l'ouvrier, puis reçoit ses fichiers modifiés,
        créés ou supprimés : `git status` et `git diff` y montrent le même livrable. Les fichiers
        que git ignore (node_modules, .venv, .env...) n'y sont pas recopiés mais reliés, pour que
        les tests y tournent sans réinstaller ; les caches ne le sont pas. Ce que le vérificateur
        y change n'atteint jamais ce qui sera enregistré, et la copie est jetée après son avis.
        """
        dossier, copie = Path(dossier), self._copie(tache)
        self.jeter_copie(copie)
        copie.parent.mkdir(parents=True, exist_ok=True)
        with self.verrou_fusion:
            self._git("worktree", "add", "-q", "--detach", str(copie), "HEAD", dossier=dossier)
        changes = self._git("status", "--porcelain", "-z", "--untracked-files=all", dossier=dossier)
        for chemin in _chemins_du_statut(changes):
            source, cible = dossier / chemin, copie / chemin
            if source.is_symlink() or source.is_file():
                cible.parent.mkdir(parents=True, exist_ok=True)
                if cible.is_symlink() or cible.exists():
                    cible.unlink()
                shutil.copy2(source, cible, follow_symlinks=False)
            elif cible.is_symlink() or cible.is_file():
                cible.unlink()
        ignores = self._git("status", "--porcelain", "-z", "--ignored", dossier=dossier)
        for ligne in ignores.split("\0"):
            chemin = ligne[3:].rstrip("/") if ligne.startswith("!! ") else ""
            if not chemin or Path(chemin).name in CACHES or chemin.endswith(".pyc"):
                continue
            _relier(dossier / chemin, copie / chemin)
        return copie

    def jeter_copie(self, copie) -> None:
        """Jette la copie du vérificateur, quoi qu'il y ait fait."""
        copie = Path(copie)
        if copie.exists():
            with self.verrou_fusion, suppress(RuntimeError):
                self._git("worktree", "remove", "--force", str(copie))
        if copie.exists():
            shutil.rmtree(copie, ignore_errors=True)
        with self.verrou_fusion, suppress(RuntimeError):
            self._git("worktree", "prune")

    def fichiers_modifies(self, tache, dossier, resultat) -> list[str]:
        """Rend les fichiers réellement modifiés, lus dans git et non dans le compte rendu."""
        # `-z` : git rend alors les noms tels quels, sans guillemets ni codes (accent, espace...).
        sortie = self._git("status", "--porcelain", "-z", "--untracked-files=all", dossier=dossier)
        return _chemins_du_statut(sortie)

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

    def enregistrer(self, tache, dossier) -> str:
        """Fait entrer le travail vérifié dans la branche principale ; rend "" ou le problème.

        Si la branche principale a avancé depuis la préparation (une autre tâche est entrée),
        elle est d'abord fusionnée dans la copie de la tâche, et les commandes du projet y sont
        relancées : on n'enregistre que ce qui a été contrôlé tel quel. Un conflit ou un contrôle
        qui échoue rend le problème, et rien n'entre dans la branche principale. Un fichier
        rendu à l'ouvrier avec des marqueurs de conflit n'entre pas non plus s'il en reste.
        """
        restants = self._marqueurs_restants(tache, dossier)
        if restants is None:
            return (
                "La liste des fichiers rendus avec des marqueurs de conflit est illisible pour "
                "cette copie : je ne sais plus lesquels surveiller. Rien n'entre dans la branche "
                "principale : la tentative suivante repart d'une copie propre."
            )
        if restants:
            return (
                f"Des marqueurs de conflit restent dans : {', '.join(restants)}. Rien n'entre "
                "dans la branche principale : la tentative suivante en repart."
            )
        try:
            self._git("add", "-A", dossier=dossier)
            if self._git("status", "--porcelain", dossier=dossier).strip():
                self._git("commit", "-q", "-m", f"{tache.id} : {tache.titre}", dossier=dossier)
            for _ in range(ESSAIS_INTEGRATION):
                base = self._git("rev-parse", "HEAD").strip()
                probleme = self._integrer(base, dossier)
                if probleme:
                    return probleme
                with self.verrou_fusion:
                    if self._git("rev-parse", "HEAD").strip() != base:
                        continue  # une autre tâche est entrée pendant les contrôles : on rejoue
                    self._git("merge", "-q", "--ff-only", f"tache/{tache.id}")
                    self._git("worktree", "remove", "--force", str(dossier))
                    self._a_marqueurs.pop(tache.id, None)  # la liste est partie avec la copie
                    self._git("branch", "-q", "-D", f"tache/{tache.id}")
                    self.enregistrer_cahier(f"Cahier : {tache.id} enregistrée")
                break
            else:
                return "La branche principale a bougé à chaque contrôle : je recommence plus tard."
        except RuntimeError as erreur:
            return f"L'enregistrement dans git a échoué : {erreur}"
        self.envoyer()
        return ""

    def _integrer(self, base: str, dossier) -> str:
        """Fusionne `base` dans la copie de la tâche et relance les contrôles ; rend le problème."""
        if self._ancetre(base, dossier):
            return ""  # rien de neuf : les contrôles ont déjà porté sur ce code
        try:
            self._git("merge", "-q", "--no-edit", base, dossier=dossier)
        except RuntimeError:
            with suppress(RuntimeError):
                self._git("merge", "--abort", dossier=dossier)
            return (
                "Conflit avec la branche principale, où d'autres tâches sont entrées entre-temps : "
                "la tentative suivante repart de la branche principale actuelle."
            )
        passe, sortie = self.mecaniques(None, dossier)
        if passe:
            return ""
        return (
            "Les contrôles échouent une fois ce travail mêlé à la branche principale actuelle :\n"
            + sortie[-1500:]
        )

    def _ancetre(self, base: str, dossier) -> bool:
        """Dit si `base` est déjà contenu dans la branche de la copie de travail."""
        resultat = lancer_git(dossier, "merge-base", "--is-ancestor", base, "HEAD")
        return resultat.returncode == 0

    def poser_conflits(self, tache, dossier) -> dict[str, str]:
        """Refait dans la copie de la tâche la fusion de la branche principale actuelle, et y
        laisse les conflits pour l'ouvrier ; rend chaque fichier en conflit avec sa nature
        (`MARQUEURS`, `SUPPRIME_SUR_LA_PRINCIPALE`, `SUPPRIME_PAR_LA_TACHE`).

        La copie est alors posée sur la branche principale : le travail de la tâche, marqueurs
        de conflit compris, y devient un changement non enregistré, comme pour une tâche partie
        de là. Périmètre, contrôles, vérificateur et enregistrement le voient donc comme
        d'habitude, et l'historique ne garde aucun état à marqueurs. Sans conflit (l'échec venait
        d'ailleurs, ou la branche principale a changé depuis), ou si git échoue, la fusion est
        défaite et rien n'est rendu : la tâche suit alors le chemin d'un refus ordinaire.
        """
        with suppress(RuntimeError):
            base = self._git("rev-parse", "HEAD").strip()
            try:
                self._git("merge", "-q", "--no-commit", "--no-ff", base, dossier=dossier)
            except RuntimeError:
                conflits = self._conflits(dossier)
                if conflits:
                    self._git("reset", "-q", base, dossier=dossier)
                    marques = [c for c, nature in conflits.items() if nature == MARQUEURS]
                    self._retenir_marqueurs(tache, dossier, marques)
                    return conflits
        with suppress(RuntimeError):
            self._git("merge", "--abort", dossier=dossier)
        return {}

    def _conflits(self, dossier) -> dict[str, str]:
        """Les fichiers en conflit de la fusion en cours, avec leur nature.

        Git garde, pour chacun, la version de la tâche (étape 2) et celle de la branche
        principale (étape 3) ; celle qui manque est celle d'un côté qui a supprimé le fichier.
        """
        etapes: dict[str, set[str]] = {}
        for entree in self._git("ls-files", "-u", "-z", dossier=dossier).split("\0"):
            if "\t" in entree:
                tete, chemin = entree.split("\t", 1)
                etapes.setdefault(chemin, set()).add(tete.split()[-1])
        natures = {}
        for chemin, vues in etapes.items():
            if "2" not in vues:
                natures[chemin] = SUPPRIME_PAR_LA_TACHE
            else:
                natures[chemin] = MARQUEURS if "3" in vues else SUPPRIME_SUR_LA_PRINCIPALE
        return natures

    def _marqueurs_restants(self, tache, dossier) -> list[str] | None:
        """Les fichiers rendus à l'ouvrier avec des marqueurs qui en ont encore une ligne.

        Le contenu est lu, et non `git diff --check`, qui ignore les fichiers non suivis et
        prend un soulignement Markdown pour un marqueur. Rend None quand la liste de ces
        fichiers est illisible : on ne sait plus lesquels regarder, et rien ne doit entrer.
        """
        poses = self._marqueurs_poses(tache, dossier)
        if poses is None:
            return None
        restants = []
        for chemin in poses:
            fichier = Path(dossier) / chemin
            lignes = fichier.read_text("utf-8", "replace").splitlines() if fichier.is_file() else []
            if any(ligne.startswith(DEBUTS_DE_MARQUEUR) for ligne in lignes):
                restants.append(chemin)
        return restants

    def _fichier_des_marqueurs(self, dossier) -> Path:
        """Le fichier de la liste des marqueurs, dans le dossier git propre à la copie."""
        propre = Path(self._git("rev-parse", "--git-dir", dossier=Path(dossier)).strip())
        propre = propre if propre.is_absolute() else Path(dossier) / propre
        return propre / FICHIER_MARQUEURS

    def conflit_pose(self, dossier) -> bool:
        """Dit si cette copie a reçu un conflit de fusion à résoudre (`poser_conflits`).

        La liste des marqueurs, écrite à ce moment dans le dossier git de la copie, en est la
        trace : elle suit la copie d'un départ à l'autre, survit à un redémarrage, et part avec
        elle. Quand git ne sait pas répondre, la réponse est oui : dans le doute, le travail est
        vérifié complètement. Sans copie (aucun dossier), il n'y a rien à marquer."""
        if dossier is None:
            return False
        try:
            return self._fichier_des_marqueurs(dossier).exists()
        except (RuntimeError, OSError):
            return True

    def _retenir_marqueurs(self, tache, dossier, marques: list[str]) -> None:
        """Écrit la liste des fichiers rendus avec des marqueurs, pour cette copie, et la garde
        en raccourci. L'écrire est nécessaire : sans elle, un redémarrage laisserait entrer les
        marqueurs (une RuntimeError ou une OSError remonte)."""
        ecrire_d_un_seul_geste(self._fichier_des_marqueurs(dossier), json.dumps(marques))
        self._a_marqueurs[tache.id] = (str(dossier), list(marques))

    def _marqueurs_poses(self, tache, dossier) -> list[str] | None:
        """Les fichiers rendus avec des marqueurs dans cette copie : le raccourci s'il porte sur
        elle, sinon la liste écrite dans son dossier git (aucune si elle n'existe pas).

        Une liste écrite mais illisible (tronquée, vide, d'une autre forme, git qui ne répond
        pas) rend None : après un redémarrage le raccourci est vide, et le prendre pour « aucun
        fichier à surveiller » laisserait entrer des marqueurs dans la branche principale."""
        raccourci = self._a_marqueurs.get(tache.id)
        if raccourci is not None and raccourci[0] == str(dossier):
            return raccourci[1]
        try:
            fichier = self._fichier_des_marqueurs(dossier)
            if not fichier.exists():
                return []
            lus = json.loads(fichier.read_text("utf-8"))
        except (RuntimeError, OSError, ValueError):
            return None
        if not isinstance(lus, list) or not all(isinstance(c, str) for c in lus):
            return None
        return lus

    def controler_principale(self) -> tuple[bool, str]:
        """Lance les commandes du projet sur la branche principale, dans une copie propre.

        Une copie à part, et non le dossier du projet : ni fichier en cours d'édition, ni
        copies de travail des tâches (rangées sous .atelier/) ne se mêlent aux contrôles.
        """
        if not self.commandes:
            return True, ""
        copie = self.depot / ".atelier" / "arbres" / "_principale"
        try:
            with self.verrou_fusion:
                if copie.exists():
                    self._git("worktree", "remove", "--force", str(copie))
                copie.parent.mkdir(parents=True, exist_ok=True)
                self._git("worktree", "add", "-q", "--detach", str(copie), "HEAD")
            return self.mecaniques(None, copie)
        except RuntimeError as erreur:
            return False, f"Impossible de préparer la copie de contrôle : {erreur}"
        finally:
            if copie.exists():
                with self.verrou_fusion, suppress(RuntimeError):
                    self._git("worktree", "remove", "--force", str(copie))

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
        """Jette le travail refusé : la tentative suivante repartira d'un état propre.

        Une copie de tâche rangée à sa place est retirée même si git ne la reconnaît plus
        (`_retirer_arbre`), sans lever : une copie gardée peut avoir été abîmée entre-temps.
        """
        self._a_marqueurs.pop(getattr(tache, "id", ""), None)  # la liste part avec la copie
        if dossier and self._parmi_les_arbres(Path(dossier)):
            self._retirer_arbre(Path(dossier))
        elif dossier and Path(dossier).exists():
            with self.verrou_fusion:
                self._git("worktree", "remove", "--force", str(dossier))

    def etat_du_depot(self, taches, profil: dict | None = None) -> dict:
        """Lit l'état du dépôt pour le tableau de bord, sans rien changer ni rien demander au
        réseau.

        `taches` : les tâches du chantier (de chacune, `id`, `titre` et `etat` sont lus).
        `profil` : le profil du projet, pour les fichiers partagés ; sans lui, c'est le fichier
        `chantier/profil.json` qui est lu. Rend un dictionnaire fait de textes, de nombres, de
        listes et de dictionnaires (voir `chantier/relais/D1.md` pour chaque clé). Ne lève jamais :
        ce qui n'a pas pu être lu reste vide, avec une phrase sous la clé `probleme` de la partie
        touchée.
        """
        taches = _taches_lisibles(taches)
        try:
            return _LectureDepot(self.depot, taches, profil).lire()
        except Exception as erreur:  # le tableau de bord ne doit jamais tomber sur cette lecture
            return _etat_vide(taches, f"La lecture du dépôt a échoué ({type(erreur).__name__}).")


# ---------------------------------------------------------------------------------------------
# La lecture de l'état du dépôt (`ControlesGit.etat_du_depot`) : tout ce qui suit lui sert.
# Elle ne change rien : git ne prend aucun verrou facultatif (`GIT_OPTIONAL_LOCKS=0`, sans quoi
# `git status` réécrirait l'index), aucune commande n'écrit, aucune n'interroge le réseau.
# ---------------------------------------------------------------------------------------------
DELAI_LECTURE_S = 5.0  # le temps laissé à chaque commande git de la lecture
BUDGET_LECTURE_S = 20.0  # et à la lecture entière : passé ce temps, le reste n'est pas lu
ENREGISTREMENTS_LUS = 2000  # la profondeur d'historique où l'on cherche l'entrée d'une tâche
ENREGISTREMENTS_MONTRES = 8
FICHIERS_NOMMES = 20  # les noms rendus par tâche (le nombre, lui, est complet)
FICHIERS_LUS_POUR_MARQUEURS = 500
OCTETS_LUS_POUR_MARQUEURS = 2_000_000
COMMANDES_PAR_TACHE = 4  # au plus : point commun, départ, retard, fichiers modifiés
ETATS_EN_ROUTE = ("en_cours", "en_verification")  # des tâches qui ont branche et copie
ETAT_ENTREE = "verifie"  # l'état que le moteur donne à une tâche une fois son travail entré
SANS_VERROU = {"GIT_OPTIONAL_LOCKS": "0"}
FORMAT_ENREGISTREMENT = "%H%x1f%h%x1f%P%x1f%ct%x1f%s"
REFUS = "git a refusé la commande"


def _quand(secondes: int) -> dict[str, str]:
    """L'heure d'un enregistrement : « 14:16 » pour l'écran, et l'instant en ISO 8601."""
    try:
        instant = datetime.fromtimestamp(secondes).astimezone()
    except (OverflowError, OSError, ValueError):
        return {"heure": "", "instant": ""}
    return {"heure": instant.strftime("%H:%M"), "instant": instant.isoformat(timespec="seconds")}


def _montrer(enregistrement: dict) -> dict:
    """Un enregistrement tel que le rend la lecture : id court, message, heure, instant."""
    return {
        "id": enregistrement["court"],
        "message": enregistrement["message"],
        **_quand(enregistrement["secondes"]),
    }


def _lire_enregistrement(ligne: str) -> dict | None:
    morceaux = ligne.split("\x1f", 4)
    if len(morceaux) != 5 or not morceaux[3].isdigit():
        return None
    complet, court, parents, secondes, message = morceaux
    return {
        "complet": complet, "court": court, "parents": parents.split(),
        "secondes": int(secondes), "message": message,
    }  # fmt: skip


def _taches_lisibles(taches) -> list:
    """Les tâches qui ont un identifiant : les autres sont sautées, la lecture n'en dit rien."""
    try:
        return [t for t in taches if getattr(t, "id", None) not in (None, "")]
    except TypeError:  # pas une suite de tâches
        return []


def _sujet(texte: str) -> str:
    """Le sujet d'un enregistrement fait de ce texte, comme git le rend (`%s`) : le premier
    paragraphe, ses lignes réunies par des espaces."""
    return " ".join(texte.split("\n\n")[0].split())


def _message_du_travail(tache) -> str:
    """Le message que l'Atelier donne à l'enregistrement du travail : « <id> : <titre> »."""
    return _sujet(f"{tache.id} : {getattr(tache, 'titre', '')}")


def _message_du_cahier(identifiant) -> str:
    """Le message de l'enregistrement du cahier, qui fait entrer la tâche dans le chantier."""
    return f"Cahier : {identifiant} enregistrée"


def _tache_du_message(message: str, taches: list) -> str:
    """La tâche que dit un message de l'Atelier, ou "" : exactement « <id> : <titre> » (le
    travail), « Cahier : <id> enregistrée » (l'entrée) ou « Merge ... into tache/<id> » (la
    branche du chantier fusionnée dans la sienne), pour une tâche donnée. Un début de message
    qui ressemble ne suffit pas : un enregistrement d'une personne n'est à aucune tâche."""
    fusion = re.fullmatch(r"Merge (?:commit|branch) .* into tache/(.+)", message)
    for tache in taches:
        identifiant = str(tache.id)
        if message in (_message_du_travail(tache), _message_du_cahier(identifiant)):
            return identifiant
        if fusion and fusion.group(1) == identifiant:
            return identifiant
    return ""


def _avec_marqueurs(dossier: Path, noms: list[str]) -> list[str]:
    """Ceux de ces fichiers (de la copie) qui portent encore une ligne de marqueur de conflit."""
    trouves = []
    for nom in noms[:FICHIERS_LUS_POUR_MARQUEURS]:
        chemin = dossier / nom
        try:
            if chemin.is_symlink() or not chemin.is_file():
                continue
            if chemin.stat().st_size > OCTETS_LUS_POUR_MARQUEURS:
                continue
            lignes = chemin.read_text("utf-8", "replace").splitlines()
        except OSError:
            continue
        if any(ligne.startswith(DEBUTS_DE_MARQUEUR) for ligne in lignes):
            trouves.append(nom)
    return trouves


def _fiche_vide(identifiant: str, probleme: str = "") -> dict:
    return {
        "branche": {"nom": f"tache/{identifiant}", "existe": False},
        "copie": {"existe": False, "dossier": f".atelier/arbres/{identifiant.replace('/', '_')}"},
        "depart": None,
        "retard": None,
        "modifies": {"nombre": 0, "noms": []},
        "conflits": [],
        "entree": None,
        "probleme": probleme,
    }


def _etat_vide(taches: list, probleme: str) -> dict:
    """L'état quand rien n'a pu être lu : toutes les parties vides, la phrase au chantier."""
    return {
        "chantier": {
            "branche": "", "detachee": False, "dernier": None, "derniers": [],
            "probleme": probleme,
        },
        "taches": {str(t.id): _fiche_vide(str(t.id), probleme) for t in taches},
        "en_ligne": {"suivie": "", "avance": None, "connu": None, "probleme": ""},
        "partages": {"fichiers": [], "probleme": ""},
    }  # fmt: skip


class _Reponse:
    """Ce que rend une commande de la lecture : sa sortie, ou la phrase de son échec."""

    def __init__(self, sortie: str = "", probleme: str = ""):
        self.sortie, self.probleme = sortie, probleme

    @property
    def ok(self) -> bool:
        return not self.probleme


class _Lecteur:
    """Lance les commandes git de la lecture : un délai par commande, un budget pour l'ensemble,
    et jamais d'exception (un git absent, trop lent ou en échec devient une phrase)."""

    def __init__(self):
        self.fin = time.monotonic() + BUDGET_LECTURE_S

    def git(self, dossier: Path, *arguments: str) -> _Reponse:
        reste = self.fin - time.monotonic()
        if reste <= 0:
            return _Reponse(probleme="la lecture a pris trop de temps")
        try:
            resultat = lancer_git(
                dossier, *arguments, delai=min(DELAI_LECTURE_S, reste), environnement=SANS_VERROU
            )
        except subprocess.TimeoutExpired:
            return _Reponse(probleme="git n'a pas répondu à temps")
        except OSError:
            return _Reponse(probleme="git ou le dossier est inaccessible")
        except ValueError:
            return _Reponse(probleme="git a rendu un texte illisible")
        if resultat.returncode != 0:
            return _Reponse(probleme=REFUS)
        return _Reponse(resultat.stdout)


def _phrase(partie: str, cause: str) -> str:
    return f"{partie} n'a pas pu être lu : {cause}."


def _noter(fiche: dict, phrase: str) -> None:
    """Garde la première phrase de problème d'une tâche."""
    if phrase and not fiche["probleme"]:
        fiche["probleme"] = phrase


class _LectureDepot:
    """Une lecture de l'état du dépôt. Chaque partie se lit seule : celle qui échoue reste vide
    avec sa phrase, les autres sont rendues."""

    def __init__(self, depot, taches: list, profil: dict | None):
        self.depot = Path(depot)
        self.taches = taches
        self.profil = profil
        self.historique_lu = False
        self.cause_historique = ""
        self.git = _Lecteur()
        self.enregistrements: list[dict] = []
        self.branches: set[str] | None = None
        self.probleme_branches = ""

    def lire(self) -> dict:
        racine = self.git.git(self.depot, "rev-parse", "--git-dir")
        if racine.ok:
            etat = _etat_vide(self.taches, "")
            etat["chantier"] = self._chantier()
            self._lire_branches()
            etat["taches"] = {str(t.id): self._tache(t) for t in self.taches}
            etat["en_ligne"] = self._en_ligne(etat["chantier"]["branche"])
        elif racine.probleme == REFUS:
            etat = _etat_vide(self.taches, "Ce dossier n'est pas un dépôt git.")
        else:
            etat = _etat_vide(self.taches, f"Le dépôt n'a pas pu être lu : {racine.probleme}.")
        etat["partages"] = self._partages()
        return etat

    # ---- la branche du chantier et ses enregistrements -------------------------------------

    def _chantier(self) -> dict:
        chantier = _etat_vide([], "")["chantier"]
        branche = self.git.git(self.depot, "symbolic-ref", "-q", "HEAD")
        if branche.ok:
            chantier["branche"] = branche.sortie.strip().removeprefix("refs/heads/")
        elif branche.probleme == REFUS:  # avec `-q`, un simple échec dit une tête détachée
            chantier["detachee"] = True
            chantier["probleme"] = "Le dossier du projet n'est sur aucune branche (tête détachée)."
        else:
            chantier["probleme"] = _phrase("La branche du chantier", branche.probleme)
        phrase = self._lire_enregistrements()
        if phrase and not chantier["probleme"]:
            chantier["probleme"] = phrase
        chantier["derniers"] = [
            {**_montrer(e), "tache": _tache_du_message(e["message"], self.taches)}
            for e in self.enregistrements[:ENREGISTREMENTS_MONTRES]
        ]
        chantier["dernier"] = chantier["derniers"][0] if chantier["derniers"] else None
        return chantier

    def _lire_enregistrements(self) -> str:
        """Lit l'historique du chantier d'un coup ; rend la phrase du problème, ou ""."""
        reponse = self.git.git(
            self.depot, "log", "--date-order", f"--max-count={ENREGISTREMENTS_LUS}",
            f"--format={FORMAT_ENREGISTREMENT}", "HEAD", "--",
        )  # fmt: skip
        if reponse.ok:
            self.historique_lu = True
            lus = (_lire_enregistrement(ligne) for ligne in reponse.sortie.splitlines())
            self.enregistrements = [e for e in lus if e]
            return ""
        if reponse.probleme == REFUS:
            sans_tete = not self.git.git(self.depot, "rev-parse", "--verify", "-q", "HEAD").ok
            if sans_tete:
                self.cause_historique = "ce dépôt n'a encore aucun enregistrement"
                return "Ce dépôt n'a encore aucun enregistrement."
        self.cause_historique = reponse.probleme
        return f"Les enregistrements n'ont pas pu être lus : {reponse.probleme}."

    # ---- les tâches --------------------------------------------------------------------------

    def _lire_branches(self) -> None:
        reponse = self.git.git(
            self.depot, "for-each-ref", "--format=%(refname)", "refs/heads/tache/"
        )
        if reponse.ok:
            self.branches = set(reponse.sortie.split("\n"))
        else:
            self.probleme_branches = f"Les branches n'ont pas pu être lues : {reponse.probleme}."

    def _tache(self, tache) -> dict:
        ident = str(tache.id)
        fiche = _fiche_vide(ident, self.probleme_branches)
        nom = fiche["branche"]["nom"]
        dossier = self.depot / fiche["copie"]["dossier"]
        # Les branches sont lues et cherchées par leur nom complet : un tag `tache/X` n'en est pas.
        fiche["branche"]["existe"] = bool(self.branches) and f"refs/heads/{nom}" in self.branches
        fiche["copie"]["existe"] = dossier.is_dir()
        if fiche["branche"]["existe"]:
            self._depart_et_retard(fiche, f"refs/heads/{nom}")
            if fiche["copie"]["existe"]:
                self._modifications(fiche, dossier)
        # Seule une tâche que le chantier dit entrée (`verifie`) a une entrée.
        if getattr(tache, "etat", "") == ETAT_ENTREE:
            self._entree(fiche, tache)
        _noter(fiche, self._absence(fiche, getattr(tache, "etat", "")))
        return fiche

    def _depart_et_retard(self, fiche: dict, nom: str) -> None:
        """Remplit `depart` et `retard` de la tâche, `nom` étant sa branche (nom complet)."""
        commun = self.git.git(self.depot, "merge-base", "HEAD", nom)
        if not commun.ok:
            _noter(fiche, _phrase("Le point de départ", commun.probleme))
            return
        format_ = f"--format={FORMAT_ENREGISTREMENT}"
        depart = self.git.git(self.depot, "log", "-1", format_, commun.sortie.strip(), "--")
        lu = _lire_enregistrement(depart.sortie.strip()) if depart.ok else None
        if lu:
            fiche["depart"] = _montrer(lu)
        else:
            _noter(fiche, _phrase("Le point de départ", depart.probleme or REFUS))
        ecarts = self.git.git(
            self.depot, "rev-list", "--left-right", "--count", f"HEAD...{nom}", "--"
        )
        gauche, _, droite = ecarts.sortie.strip().partition("\t")
        if ecarts.ok and gauche.isdigit() and droite.isdigit():
            fiche["retard"] = int(gauche)
        else:
            _noter(fiche, _phrase("Le retard", ecarts.probleme or REFUS))

    def _modifications(self, fiche: dict, dossier: Path) -> None:
        """Les fichiers modifiés et pas enregistrés de la copie, et ceux à marqueurs."""
        if not (dossier / ".git").exists():
            _noter(fiche, "Ce dossier n'est plus une copie de travail git.")
            return
        statut = self.git.git(dossier, "status", "--porcelain", "-z", "--untracked-files=all")
        if not statut.ok:
            _noter(fiche, _phrase("L'état de la copie", statut.probleme))
            return
        noms = _chemins_du_statut(statut.sortie)
        fiche["modifies"] = {"nombre": len(noms), "noms": noms[:FICHIERS_NOMMES]}
        fiche["conflits"] = _avec_marqueurs(dossier, noms)

    def _entree(self, fiche: dict, tache) -> None:
        """Pose `entree` : l'enregistrement par lequel le travail de la tâche est entré, et la
        façon dont. Il porte exactement le message que l'Atelier écrit pour elle ; s'il y en a
        plusieurs, c'est le plus ancien. Sans lui, une phrase dit pourquoi, et rien n'est deviné."""
        travail = _message_du_travail(tache)
        trouves = [e for e in self.enregistrements if e["message"] == travail]
        if trouves:
            bout, fusions = self._suite_des_fusions(trouves[-1], str(tache.id))
            facon = "apres_fusion" if fusions else "directe"
            fiche["entree"] = {**_montrer(bout), "facon": facon}
            return
        if not self.historique_lu:
            cause = self.cause_historique
            _noter(fiche, f"L'entrée de la tâche n'a pas pu être cherchée : {cause}.")
        else:
            _noter(
                fiche,
                "L'enregistrement d'entrée de cette tâche est introuvable dans l'historique lu "
                f"(jusqu'à {ENREGISTREMENTS_LUS} enregistrements) ; une tâche qui n'a rien "
                "changé n'en laisse pas.",
            )

    def _suite_des_fusions(self, travail: dict, identifiant: str) -> tuple[dict, int]:
        """Suit, après l'enregistrement du travail, les fusions de la branche du chantier dans
        celle de la tâche : des enregistrements à deux parents, dont le premier est le précédent
        et dont le message est celui de git pour cette fusion (« Merge ... into tache/<id> »)."""
        suivants: dict[str, dict] = {}
        for e in self.enregistrements:
            if (
                len(e["parents"]) == 2
                and e["message"].startswith("Merge ")
                and e["message"].endswith(f" into tache/{identifiant}")
            ):
                suivants.setdefault(e["parents"][0], e)
        courant, fusions = travail, 0
        while courant["complet"] in suivants and fusions < len(self.enregistrements):
            courant, fusions = suivants[courant["complet"]], fusions + 1
        return courant, fusions

    @staticmethod
    def _absence(fiche: dict, etat: str) -> str:
        branche, copie = fiche["branche"], fiche["copie"]
        if copie["existe"] and not branche["existe"]:
            return f"La branche {branche['nom']} n'existe plus, mais sa copie de travail est là."
        if etat in ETATS_EN_ROUTE and not fiche["entree"]:
            if not branche["existe"]:
                return f"La branche {branche['nom']} et la copie de travail de la tâche manquent."
            if not copie["existe"]:
                return "La copie de travail de la tâche a disparu."
        return ""

    # ---- le dépôt en ligne, tel que git le connaît sur le disque ---------------------------

    def _en_ligne(self, branche: str) -> dict:
        en_ligne = _etat_vide([], "")["en_ligne"]
        if not branche:
            return en_ligne
        suivie, en_ligne["probleme"] = self._branche_suivie(branche)
        if not suivie:
            return en_ligne
        en_ligne["suivie"] = suivie.removeprefix("refs/remotes/").removeprefix("refs/heads/")
        avance = self.git.git(self.depot, "rev-list", "--count", f"{suivie}..HEAD", "--")
        if avance.ok and avance.sortie.strip().isdigit():
            en_ligne["avance"] = int(avance.sortie.strip())
        else:
            en_ligne["probleme"] = _phrase("L'avance", avance.probleme or REFUS)
        format_ = f"--format={FORMAT_ENREGISTREMENT}"
        connu = self.git.git(self.depot, "log", "-1", format_, suivie, "--")
        lu = _lire_enregistrement(connu.sortie.strip()) if connu.ok else None
        en_ligne["connu"] = _montrer(lu) if lu else None
        return en_ligne

    def _branche_suivie(self, branche: str) -> tuple[str, str]:
        """La branche en ligne que git connaît sur le disque, par son nom complet (celle que le
        réglage de suivi désigne, sinon `refs/remotes/origin/<branche>`), et le problème.
        ("", "") sans dépôt en ligne ni branche suivie."""
        reglage = self.git.git(
            self.depot, "for-each-ref", "--format=%(upstream)", f"refs/heads/{branche}"
        )
        if not reglage.ok:
            return "", _phrase("La branche suivie", reglage.probleme)
        complet = reglage.sortie.strip() or f"refs/remotes/origin/{branche}"
        connue = self.git.git(self.depot, "rev-parse", "--verify", "-q", complet)
        if connue.ok:
            return complet, ""
        if connue.probleme != REFUS:
            return "", _phrase("La branche suivie", connue.probleme)
        if reglage.sortie.strip():
            return "", "La branche suivie n'est pas connue sur ce disque : rien n'en a été reçu."
        return "", ""

    # ---- les fichiers partagés ---------------------------------------------------------------

    def _partages(self) -> dict:
        profil, probleme = self.profil, ""
        if profil is None:
            chemin = self.depot / "chantier" / "profil.json"
            try:
                profil = json.loads(chemin.read_text("utf-8")) if chemin.exists() else {}
            except (OSError, ValueError):
                profil, probleme = {}, "Le profil du projet (chantier/profil.json) est illisible."
        fichiers = [{"motif": m, "fusion": f} for m, f in fichiers_partages(profil).items()]
        return {"fichiers": fichiers, "probleme": probleme}


def etat_du_depot_d_exemple(taches) -> dict:
    """Un état du dépôt cohérent avec la démonstration, sans git : les tâches vérifiées sont
    entrées (la première en entrée directe, la suivante après fusion), les tâches en route ont
    leur branche et quelques fichiers modifiés, les autres n'ont encore rien. Sans dépôt en ligne.
    """
    taches = list(taches)
    maintenant = int(time.time())
    entrees = [str(t.id) for t in taches if getattr(t, "etat", "") == "verifie"]
    fiches, derniers = {}, []
    for tache in taches:
        ident, etat = str(tache.id), getattr(tache, "etat", "")
        fiche = _fiche_vide(ident)
        if ident in entrees:
            rang = entrees.index(ident)
            quand = _quand(maintenant - 60 * (len(entrees) - rang))
            entree = {"id": f"{rang + 1:02d}a1c9e", "message": f"{ident} : {tache.titre}"}
            facon = "apres_fusion" if rang % 2 else "directe"
            fiche["entree"] = {**entree, **quand, "facon": facon}
            derniers.insert(0, {**entree, **quand, "tache": ident})
        elif etat in ETATS_EN_ROUTE:
            _poser_travail_d_exemple(fiche, tache, maintenant, len(entrees))
        fiches[ident] = fiche
    tete = derniers[:ENREGISTREMENTS_MONTRES]
    return {
        "chantier": {
            "branche": "main", "detachee": False, "dernier": tete[0] if tete else None,
            "derniers": tete, "probleme": "",
        },
        "taches": fiches,
        "en_ligne": {"suivie": "", "avance": None, "connu": None, "probleme": ""},
        "partages": {"fichiers": [], "probleme": ""},
    }  # fmt: skip


def _poser_travail_d_exemple(fiche: dict, tache, maintenant: int, entrees: int) -> None:
    """Pour une tâche en route : sa branche, sa copie, son point de départ et ses fichiers."""
    fiche["branche"]["existe"] = fiche["copie"]["existe"] = True
    fiche["depart"] = {"id": "3f9a1c7", "message": "Cahier du chantier", **_quand(maintenant - 600)}
    fiche["retard"] = entrees
    noms = list(getattr(tache, "perimetre", None) or []) or [f"coeur/{str(tache.id).lower()}.py"]
    fiche["modifies"] = {"nombre": len(noms), "noms": noms[:FICHIERS_NOMMES]}
