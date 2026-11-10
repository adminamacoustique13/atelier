"""Plusieurs projets dans le même atelier : un dossier par projet, sous une même racine."""

from __future__ import annotations

import json
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


def ouvrir_depot(depot: Path) -> Atelier:
    """Monte l'atelier d'un dépôt existant, avec de vrais agents Claude Code."""
    profil = lire_profil(depot)
    etat = depot / ".atelier" / "etat.json"
    if etat.exists():
        chantier = Chantier.charger(etat)
    else:
        chantier = Chantier(projet=profil.get("nom", depot.name), contrat=Contrat(objectif=""))
    controles = ControlesGit(depot, profil.get("commandes", []))
    return Atelier(depot, chantier, AgentClaude(profil), controles, profil)


def _git(dossier: Path, *arguments: str) -> str:
    try:
        sortie = subprocess.run(
            ["git", *arguments], cwd=dossier, capture_output=True, text=True, check=True
        )
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
        self.ateliers: dict[str, Atelier] = {}
        self.dossiers: dict[str, Path] = {}
        self.courant = ""

    def ajouter(self, atelier: Atelier) -> str:
        cle = atelier.depot.name
        self.ateliers[cle] = atelier
        self.courant = self.courant or cle
        return cle

    def decouvrir(self) -> None:
        """Repère sous la racine les dossiers qui ont déjà un chantier d'atelier."""
        for dossier in sorted(self.racine.iterdir()):
            if (dossier / ".atelier" / "etat.json").exists() and dossier.name not in self.ateliers:
                self.dossiers[dossier.name] = dossier

    def atelier(self) -> Atelier:
        return self.ateliers[self.courant]

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

    def vue(self) -> dict:
        donnees = self.atelier().vue()
        donnees["projets"] = self.liste()
        donnees["racine"] = str(self.racine)
        return donnees
