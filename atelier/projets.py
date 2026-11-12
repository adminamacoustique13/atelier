"""Plusieurs projets dans le même atelier : un dossier par projet, sous une même racine."""

from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import unicodedata
from datetime import datetime
from pathlib import Path

from atelier import archives
from atelier import carte as carte_du_code
from atelier.agents import AgentClaude
from atelier.controles import ControlesGit, expliquer_refus_git
from atelier.git import IDENTITE_DE_REPLI, lancer_git
from atelier.modele import Chantier, Contrat, ProjetImpossible
from atelier.serveur import Atelier


def cle_de(nom: str) -> str:
    """Tire du nom d'un projet un nom de dossier simple : minuscules, chiffres et tirets."""
    sans_accents = unicodedata.normalize("NFKD", nom).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", sans_accents.lower()).strip("-")


# Ce que les agents peuvent lancer d'emblée : de quoi installer leurs outils et lancer les
# tests en Python, Rust ou JavaScript. Un profil qui fixe sa propre liste la garde telle quelle.
COMMANDES_PAR_DEFAUT = ["uv", "python3", "cargo", "npm", "npx"]


def lire_profil(depot: Path) -> dict:
    """Lit le profil du projet ; sans liste de commandes permises, celle par défaut vaut."""
    chemin = depot / "chantier" / "profil.json"
    profil = json.loads(chemin.read_text("utf-8")) if chemin.exists() else {}
    profil.setdefault("commandes_permises", list(COMMANDES_PAR_DEFAUT))
    return profil


# Tenus hors de git sur cet ordinateur seulement : l'état de l'Atelier, et ce que les outils
# fabriquent en lançant les tests (un ouvrier ou un vérificateur qui lance pytest crée un
# __pycache__). Sans cela, ces fichiers sortaient du périmètre de la tâche et entraient dans
# ses enregistrements : constaté au premier essai réel.
EXCLUSIONS = (
    ".atelier/",
    "__pycache__/",
    "*.py[cod]",
    ".pytest_cache/",
    ".ruff_cache/",
    ".mypy_cache/",
    ".venv/",
    "node_modules/",
    ".DS_Store",
)


def exclure_etat(depot: Path) -> None:
    """Tient l'état de l'Atelier et les fichiers fabriqués par les outils hors de l'historique
    git, par .git/info/exclude : le dépôt lui-même n'est pas touché, et ses copies de travail
    (git worktree) lisent le même fichier. Un fichier déjà suivi par git le reste."""
    exclusions = depot / ".git" / "info" / "exclude"
    if not (depot / ".git").is_dir():
        return
    exclusions.parent.mkdir(exist_ok=True)
    actuel = exclusions.read_text("utf-8") if exclusions.exists() else ""
    manquent = [motif for motif in EXCLUSIONS if motif not in actuel.split()]
    if manquent:
        debut = actuel.rstrip("\n") + ("\n" if actuel.strip() else "")
        exclusions.write_text(debut + "\n".join(manquent) + "\n", "utf-8")


def lire_etat(depot: Path, nom: str) -> Chantier:
    """Relit l'état du chantier d'un dépôt ; sans état, ou s'il est illisible, un chantier vide.

    Un état illisible (fichier tronqué ou abîmé) n'est pas effacé : il est mis de côté sous un
    autre nom dans `.atelier/`, et le fil du chantier neuf le dit. Sans cela le projet ne
    s'ouvrirait plus, et l'Atelier ne démarrerait plus si c'est son premier projet.
    """
    etat = depot / ".atelier" / "etat.json"
    neuf = Chantier(projet=nom, contrat=Contrat(objectif=""))
    if not etat.exists():
        return neuf
    try:
        return Chantier.charger(etat)
    except (ValueError, TypeError, KeyError, AttributeError) as erreur:
        ecarte = etat.with_name(f"etat-illisible-{datetime.now():%Y%m%d-%H%M%S}.json")
        os.replace(etat, ecarte)
        raison = " ".join(f"{type(erreur).__name__} : {erreur}".split())[:200]
        neuf.noter(
            f"L'état de ce chantier était illisible ({raison}). Je l'ai mis de côté dans "
            f".atelier/{ecarte.name} et je repars d'un chantier vide. Le code du projet, son "
            "historique git et les chantiers archivés ne sont pas touchés.",
            auteur="orchestrateur",
        )
        return neuf


def ouvrir_depot(depot: Path) -> Atelier:
    """Monte l'atelier d'un dépôt existant, avec de vrais agents Claude Code."""
    exclure_etat(depot)
    profil = lire_profil(depot)
    chantier = lire_etat(depot, profil.get("nom", depot.name))
    controles = ControlesGit(
        depot, profil.get("commandes", []), delai_s=profil.get("delai_controles_s")
    )
    return Atelier(depot, chantier, AgentClaude(profil), controles, profil)


def _git(dossier: Path, *arguments: str, delai: int = 120) -> str:
    # Tout échec de git devient un ProjetImpossible, que l'écran montre tel quel.
    try:
        sortie = lancer_git(dossier, *arguments, delai=delai)
        sortie.check_returncode()
    except subprocess.TimeoutExpired as erreur:
        raise ProjetImpossible("Git n'a pas répondu à temps.") from erreur
    except (OSError, subprocess.CalledProcessError) as erreur:
        detail = getattr(erreur, "stderr", "") or str(erreur)
        raise ProjetImpossible(f"Git a refusé : {detail.strip()[:200]}") from erreur
    return sortie.stdout.strip()


def creer_depot(dossier: Path, nom: str) -> Atelier:
    """Crée le dossier d'un nouveau projet, son dépôt git et son profil, puis l'ouvre."""
    (dossier / "chantier").mkdir(parents=True)
    profil = {"nom": nom, "commandes": [], "commandes_permises": COMMANDES_PAR_DEFAUT}
    profil = json.dumps(profil, ensure_ascii=False, indent=2)
    (dossier / "chantier" / "profil.json").write_text(profil + "\n", "utf-8")
    (dossier / ".gitignore").write_text(".atelier/\n", "utf-8")
    _git(dossier, "init", "-q", "-b", "main")
    identite = []
    if not subprocess.run(
        ["git", "config", "user.email"], cwd=dossier, capture_output=True, text=True
    ).stdout.strip():
        identite = IDENTITE_DE_REPLI
    _git(dossier, "add", "-A")
    _git(dossier, *identite, "commit", "-q", "-m", "Création du projet")
    return ouvrir_depot(dossier)


def depot_en_ligne(dossier: Path) -> str:
    """L'adresse du dépôt en ligne (« origin »), lue dans .git/config, sans identifiants."""
    try:
        config = (Path(dossier) / ".git" / "config").read_text("utf-8", errors="replace")
    except OSError:
        return ""
    dedans = False
    for ligne in config.splitlines():
        ligne = ligne.strip()
        if ligne.startswith("["):
            dedans = ligne.replace(" ", "") == '[remote"origin"]'
        elif dedans and ligne.startswith("url"):
            adresse = ligne.split("=", 1)[-1].strip()
            adresse = re.sub(r"^[a-z]+://([^@/]*@)?", "", adresse)  # schéma et identifiants
            adresse = re.sub(r"^[^@/]+@([^:]+):", r"\1/", adresse)  # git@hote:chemin
            return re.sub(r"\.git$", "", adresse)
    return ""


def resume_chantier(chantier: Chantier | None, travaille: bool = False, attente: int = 0) -> dict:
    """Où en est le chantier d'un projet, en une phrase et une barre de tâches."""
    if chantier is None:
        return {"nom": "", "etat": "vide", "phrase": "Aucun chantier commencé.", "taches": []}
    taches = [t.etat for t in chantier.taches]
    livrees, total = taches.count("verifie"), len(taches)
    parle = any(e.get("auteur") == "toi" for e in chantier.evenements)
    s = "s" if livrees > 1 else ""
    if not total and not parle:
        etat, phrase = "vide", "Aucun chantier commencé."
    elif not total:
        etat, phrase = "conversation", "Conversation en cours, pas encore de plan."
    elif not chantier.contrat.valide:
        etat, phrase = "plan", "Un plan attend ta validation."
    elif livrees == total:
        etat, phrase = "fini", f"Terminé : {total} tâche{s} livrée{s}."
    else:
        etat, phrase = "en_cours", f"{livrees} tâche{s} livrée{s} sur {total}."
    if attente:
        question = "Une question t'attend" if attente == 1 else f"{attente} questions t'attendent"
        etat, phrase = "attente", f"{phrase} {question}."
    elif travaille:
        etat, phrase = "travail", f"{phrase} Des agents travaillent en ce moment."
    nom = archives.nom_propose(chantier) if total or parle else ""
    return {"nom": nom, "etat": etat, "phrase": phrase, "taches": taches}


def _activite(dossier: Path) -> datetime:
    for chemin in (dossier / ".atelier" / "etat.json", dossier / ".git" / "HEAD", dossier):
        try:
            return datetime.fromtimestamp(chemin.stat().st_mtime)
        except OSError:
            continue
    return datetime.fromtimestamp(0)


class Projets:
    """Les projets de l'atelier. Un seul est affiché ; les autres continuent de tourner."""

    def __init__(self, racine: Path, creer, ouvrir=None):
        self.racine = Path(racine)
        self._creer, self._ouvrir = creer, ouvrir
        self.verrou = threading.Lock()
        self.en_cours: set[str] = set()
        self.ateliers: dict[str, Atelier] = {}
        self.dossiers: dict[str, Path] = {}
        self.courant = ""

    def ajouter(self, atelier: Atelier) -> str:
        cle = atelier.depot.name
        self.ateliers[cle] = atelier
        self.courant = self.courant or cle
        return cle

    def decouvrir(self) -> None:
        """Repère sous la racine les dépôts git et les dossiers qui ont déjà un chantier."""
        for dossier in sorted(self.racine.iterdir()):
            connu = (dossier / ".git").exists() or (dossier / ".atelier" / "etat.json").exists()
            if dossier.is_dir() and connu and dossier.name not in self.ateliers:
                self.dossiers[dossier.name] = dossier

    def atelier(self) -> Atelier:
        if not self.courant:
            raise ProjetImpossible("Crée d'abord un projet.")
        return self.ateliers[self.courant]

    def ouvrir_le_premier(self) -> None:
        """Au démarrage sans projet désigné, affiche le premier projet trouvé, s'il y en a un."""
        if not self.courant and self.dossiers:
            self.ouvrir(sorted(self.dossiers)[0])

    def liste(self) -> list[dict]:
        noms = {cle: cle for cle in self.dossiers}
        noms.update({cle: a.moteur.chantier.projet for cle, a in self.ateliers.items()})
        return [
            {"id": cle, "nom": nom, "courant": cle == self.courant} for cle, nom in noms.items()
        ]

    def ouvrir(self, cle: str) -> None:
        with self.verrou:
            if cle not in self.ateliers:
                if cle not in self.dossiers or not self._ouvrir:
                    raise ProjetImpossible("Projet introuvable.")
                self.ateliers[cle] = self._ouvrir(self.dossiers[cle])
            self.courant = cle

    def creer(self, nom: str) -> str:
        nom = " ".join(str(nom).split())
        cle = cle_de(nom)
        if not cle:
            raise ProjetImpossible(
                "Donne un nom au projet, avec au moins une lettre ou un chiffre."
            )
        with self.verrou:
            dossier = self.racine / cle
            if dossier.exists() or cle in self.ateliers:
                raise ProjetImpossible(f"Un dossier « {cle} » existe déjà à cet endroit.")
            self.ateliers[cle] = self._creer(dossier, nom)
            self.courant = cle
        return cle

    def cloner(self, adresse: str) -> str:
        """Récupère un dépôt existant (GitHub ou autre) dans la racine, puis l'ouvre."""
        adresse = adresse.strip()
        nom = re.sub(r"\.git$", "", adresse.rstrip("/").rsplit("/", 1)[-1].rsplit(":", 1)[-1])
        cle = cle_de(nom)
        if not adresse or not cle:
            raise ProjetImpossible(
                "Colle l'adresse du dépôt, par exemple https://github.com/moi/projet."
            )
        if not self._ouvrir:
            raise ProjetImpossible("La démonstration ne récupère pas de vrai dépôt.")
        dossier = self.racine / cle
        with self.verrou:
            if dossier.exists() or cle in self.ateliers or cle in self.en_cours:
                raise ProjetImpossible(f"Un dossier « {cle} » existe déjà à cet endroit.")
            self.en_cours.add(cle)
        try:
            # Hors du verrou : un gros dépôt ne bloque ni les autres projets ni l'affichage.
            try:
                _git(self.racine, "clone", "--quiet", "--", adresse, str(dossier), delai=600)
            except ProjetImpossible as erreur:
                raise ProjetImpossible(expliquer_refus_git(str(erreur))) from erreur
            atelier = self._ouvrir(dossier)
        finally:
            with self.verrou:
                self.en_cours.discard(cle)
        with self.verrou:
            self.ateliers[cle] = atelier
            self.courant = cle
        return cle

    def accueil(self) -> list[dict]:
        """Chaque projet, du plus récemment touché au plus ancien, sans en démarrer aucun."""
        fiches = []
        for cle in sorted(set(self.ateliers) | set(self.dossiers)):
            atelier = self.ateliers.get(cle)
            dossier = atelier.depot if atelier else self.dossiers[cle]
            if atelier:
                # Le guichet d'abord, hors du verrou du moteur : c'est l'ordre que suit Atelier.vue,
                # l'inverse bloquerait le serveur quand un agent attend une autorisation.
                autorisations = len(atelier.guichet.ouvertes()) if atelier.guichet else 0
                travaille = atelier.en_marche() or atelier.occupe
                with atelier.moteur.verrou:
                    chantier = atelier.moteur.chantier
                    nom = chantier.projet
                    attente = autorisations + sum(d["reponse"] is None for d in chantier.demandes)
                    resume = resume_chantier(chantier, travaille, attente)
                passes = len(atelier.archives)
                carte = atelier.carte.carte
            else:
                try:
                    chantier = Chantier.charger(dossier / ".atelier" / "etat.json")
                except (OSError, ValueError, TypeError, KeyError):
                    chantier = None
                nom = chantier.projet if chantier else cle
                resume = resume_chantier(chantier)
                passes = len(archives.lister(dossier))
                carte = carte_du_code.charger(dossier)
            moment = _activite(dossier)
            fiches.append({
                "id": cle, "nom": nom, "courant": cle == self.courant, "ouvert": bool(atelier),
                "chantier": resume, "archives": passes,
                "fichiers": len(carte["fichiers"]) if carte else 0,
                "en_ligne": depot_en_ligne(dossier),
                "activite": moment.isoformat(timespec="seconds"),
                "activite_fr": archives.date_fr(moment.isoformat(timespec="minutes")),
            })  # fmt: skip
        return sorted(fiches, key=lambda f: f["activite"], reverse=True)

    def nouvelle_session(self, cle: str, nom: str = "") -> dict:
        """Ouvre un projet et y commence un nouveau chantier ; l'ancien est archivé."""
        self.ouvrir(cle)
        return self.atelier().nouveau_chantier(nom)

    def vue(self) -> dict:
        if not self.courant:
            return {"aucun_projet": True, "projets": [], "racine": str(self.racine), "mode": "réel"}
        donnees = self.atelier().vue()
        donnees["projets"] = self.liste()
        donnees["racine"] = str(self.racine)
        return donnees
