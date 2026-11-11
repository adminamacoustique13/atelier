"""Plusieurs projets dans le même atelier : un dossier par projet, sous une même racine."""

from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import unicodedata
from pathlib import Path

from atelier.agents import AgentClaude
from atelier.controles import ControlesGit
from atelier.modele import Chantier, Contrat, ProjetImpossible
from atelier.serveur import Atelier


def cle_de(nom: str) -> str:
    """Tire du nom d'un projet un nom de dossier simple : minuscules, chiffres et tirets."""
    sans_accents = unicodedata.normalize("NFKD", nom).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", sans_accents.lower()).strip("-")


def lire_profil(depot: Path) -> dict:
    """Lit le profil du projet, ou rend un profil vide."""
    chemin = depot / "chantier" / "profil.json"
    return json.loads(chemin.read_text("utf-8")) if chemin.exists() else {}


def exclure_etat(depot: Path) -> None:
    """Tient l'état de l'Atelier (.atelier/) hors de l'historique git, sans toucher au dépôt."""
    exclusions = depot / ".git" / "info" / "exclude"
    if not exclusions.parent.is_dir():
        return
    actuel = exclusions.read_text("utf-8") if exclusions.exists() else ""
    if ".atelier/" not in actuel.split():
        exclusions.write_text(
            actuel.rstrip("\n") + ("\n" if actuel.strip() else "") + ".atelier/\n"
        )


def expliquer_refus_de_clonage(message: str) -> str:
    """Traduit en clair les refus de git les plus courants au moment de récupérer un dépôt."""
    if any(m in message for m in ("Username", "Authentication", "Permission denied", "403")):
        return (
            "GitHub demande une connexion. Soit l'adresse est fausse, soit le dépôt est privé "
            "et git n'est pas encore connecté à ton compte sur cet ordinateur."
        )
    if "not found" in message or "does not exist" in message or "does not appear" in message:
        return "Aucun dépôt à cette adresse. Vérifie-la en l'ouvrant dans le navigateur."
    if "Could not resolve host" in message:
        return "Pas d'accès au réseau, ou nom de site mal écrit."
    return message


def ouvrir_depot(depot: Path) -> Atelier:
    """Monte l'atelier d'un dépôt existant, avec de vrais agents Claude Code."""
    exclure_etat(depot)
    profil = lire_profil(depot)
    etat = depot / ".atelier" / "etat.json"
    if etat.exists():
        chantier = Chantier.charger(etat)
    else:
        chantier = Chantier(projet=profil.get("nom", depot.name), contrat=Contrat(objectif=""))
    controles = ControlesGit(depot, profil.get("commandes", []))
    return Atelier(depot, chantier, AgentClaude(profil), controles, profil)


def _git(dossier: Path, *arguments: str, delai: int = 120) -> str:
    # Pas de question posée par git : l'Atelier tourne sans terminal, il échouerait en silence.
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    try:
        sortie = subprocess.run(
            ["git", *arguments],
            cwd=dossier,
            capture_output=True,
            text=True,
            check=True,
            env=env,
            timeout=delai,
        )
    except subprocess.TimeoutExpired as erreur:
        raise ProjetImpossible("Git n'a pas répondu à temps.") from erreur
    except (OSError, subprocess.CalledProcessError) as erreur:
        detail = getattr(erreur, "stderr", "") or str(erreur)
        raise ProjetImpossible(f"Git a refusé : {detail.strip()[:200]}") from erreur
    return sortie.stdout.strip()


def creer_depot(dossier: Path, nom: str) -> Atelier:
    """Crée le dossier d'un nouveau projet, son dépôt git et son profil, puis l'ouvre."""
    (dossier / "chantier").mkdir(parents=True)
    profil = json.dumps({"nom": nom, "commandes": []}, ensure_ascii=False, indent=2)
    (dossier / "chantier" / "profil.json").write_text(profil + "\n", "utf-8")
    (dossier / ".gitignore").write_text(".atelier/\n", "utf-8")
    _git(dossier, "init", "-q")
    identite = []
    if not subprocess.run(
        ["git", "config", "user.email"], cwd=dossier, capture_output=True, text=True
    ).stdout.strip():
        identite = ["-c", "user.name=Atelier", "-c", "user.email=atelier@localhost"]
    _git(dossier, "add", "-A")
    _git(dossier, *identite, "commit", "-q", "-m", "Création du projet")
    return ouvrir_depot(dossier)


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
                raise ProjetImpossible(expliquer_refus_de_clonage(str(erreur))) from erreur
            atelier = self._ouvrir(dossier)
        finally:
            with self.verrou:
                self.en_cours.discard(cle)
        with self.verrou:
            self.ateliers[cle] = atelier
            self.courant = cle
        return cle

    def vue(self) -> dict:
        if not self.courant:
            return {"aucun_projet": True, "projets": [], "racine": str(self.racine), "mode": "réel"}
        donnees = self.atelier().vue()
        donnees["projets"] = self.liste()
        donnees["racine"] = str(self.racine)
        return donnees
