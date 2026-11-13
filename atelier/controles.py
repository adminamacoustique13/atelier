"""Les contrôles mécaniques : périmètre, commandes du projet, enregistrement dans git.

Chaque tâche travaille dans sa propre copie du dépôt (un « arbre de travail » git).
Deux agents en parallèle ne se voient donc pas, et rien n'entre dans la branche
principale sans avoir été vérifié.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import threading
from collections.abc import Iterable
from contextlib import suppress
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
        # n'entrent pas tant qu'il en reste (`enregistrer`). Vidé à chaque copie neuve.
        self._a_marqueurs: dict[str, list[str]] = {}

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
        """Crée pour la tâche une copie de travail propre, partie de l'état vérifié."""
        self._a_marqueurs.pop(tache.id, None)
        arbre = self._arbre(tache)
        if arbre.exists():
            with self.verrou_fusion:
                self._git("worktree", "remove", "--force", str(arbre))
        arbre.parent.mkdir(parents=True, exist_ok=True)
        with self.verrou_fusion:
            self._git("worktree", "add", "-q", "-B", f"tache/{tache.id}", str(arbre), "HEAD")
        return arbre

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
                    self._a_marqueurs[tache.id] = marques
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

    def _marqueurs_restants(self, tache, dossier) -> list[str]:
        """Les fichiers rendus à l'ouvrier avec des marqueurs qui en ont encore une ligne.

        Le contenu est lu, et non `git diff --check`, qui ignore les fichiers non suivis et
        prend un soulignement Markdown pour un marqueur.
        """
        restants = []
        for chemin in self._a_marqueurs.get(tache.id, []):
            fichier = Path(dossier) / chemin
            lignes = fichier.read_text("utf-8", "replace").splitlines() if fichier.is_file() else []
            if any(ligne.startswith(DEBUTS_DE_MARQUEUR) for ligne in lignes):
                restants.append(chemin)
        return restants

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
        """Jette le travail refusé : la tentative suivante repartira d'un état propre."""
        if dossier and Path(dossier).exists():
            with self.verrou_fusion:
                self._git("worktree", "remove", "--force", str(dossier))
