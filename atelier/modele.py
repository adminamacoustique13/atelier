"""Les objets du chantier : tâche, contrat, chantier. Tout se lit et s'écrit en fichiers."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime
from pathlib import Path

ETATS_FR = {
    "a_lancer": "À lancer",
    "en_cours": "En cours",
    "en_verification": "En vérification",
    "verifie": "Vérifiée",
    "revenu": "Revenue vers toi",
    "abandonnee": "Abandonnée",
}

ZONES_ROUGES = [
    "Changer un choix d'architecture inscrit au journal",
    "Supprimer des fichiers ou réécrire l'historique git",
    "Déployer ou pousser en production",
    "Toucher aux secrets",
    "Ajouter au produit une bibliothèque dont la licence n'est pas permissive "
    "ou qui envoie des données à l'extérieur",
    "Modifier les tests de référence ou les garde-fous eux-mêmes",
]


class ProjetImpossible(Exception):
    """Un projet n'a pas pu être créé ou ouvert ; le message dit pourquoi, en clair."""


def ecrire_d_un_seul_geste(chemin: Path, texte: str) -> None:
    """Écrit un texte (UTF-8) dans un fichier d'un seul geste ; crée son dossier au besoin.

    Le texte part dans un fichier voisin, qui prend la place de l'ancien une fois écrit en
    entier : une écriture interrompue laisse l'ancien fichier intact, jamais un fichier tronqué,
    et le fichier voisin est retiré. L'erreur de l'écriture est relevée telle quelle.

    Pas faite pour deux écritures simultanées du même fichier : le fichier voisin porte
    toujours le même nom, l'appelant doit donc tenir un verrou.
    """
    chemin.parent.mkdir(parents=True, exist_ok=True)
    voisin = chemin.with_name(chemin.name + ".tmp")
    try:
        with open(voisin, "w", encoding="utf-8") as flux:
            flux.write(texte)
            flux.flush()
            os.fsync(flux.fileno())  # le texte est sur le disque avant de prendre la place
        os.replace(voisin, chemin)
    except BaseException:
        try:
            voisin.unlink(missing_ok=True)
        except OSError:
            pass  # dans la mesure du possible : l'erreur d'origine compte davantage
        raise


@dataclass
class Tache:
    """Une tâche du cahier des charges, avec son dosage et son histoire."""

    id: str
    titre: str
    type: str = "courante"
    pourquoi: str = ""
    criteres: list[str] = field(default_factory=list)
    perimetre: list[str] = field(default_factory=list)
    depend_de: list[str] = field(default_factory=list)
    fournit: str = ""
    attend: str = ""
    etat: str = "a_lancer"
    modele: str = ""
    effort: str = ""
    tentatives: int = 0
    rallonge: int = 0
    relances_auto: int = 0  # relances faites seules, sans la personne responsable
    montees: int = 0
    ajoutee: bool = False
    verdict: str = ""
    cout_usd: float = 0.0
    tokens: int = 0
    historique: list[dict] = field(default_factory=list)
    # La copie de travail qui porte le travail en cours ou refusé ("" : aucune).
    copie: str = ""
    # Ce qui reste à régler d'un travail gardé dans sa copie, quand un refus le nomme : un
    # dictionnaire (`genre`, `points`, `fichiers` ; pendant une sous-tâche, `en_cours`, son nom,
    # et `dosage` ; `permis`, les fichiers qu'une sous-tâche de cette copie a pu toucher), vide
    # quand rien ne reste.
    reste: dict = field(default_factory=dict)
    # Le nombre de sous-tâches déjà parties pour cette tâche.
    sous_taches: int = 0
    # Ce que le vérificateur a relevé quand tout le reste était conforme, et l'état de la copie
    # qu'il a vue ("" : rien) : le tour suivant est une retouche sur ces seuls points.
    releve: str = ""
    releve_sur: str = ""
    # Les pannes d'agent de suite (réseau, quota) : elles font patienter, sans coûter d'essai.
    pannes: int = 0

    def sous_tache_possible(self, maxi: int) -> bool:
        """Dit si le tour suivant peut être une sous-tâche.

        Vrai seulement s'il reste des points à régler, si la tâche a une copie gardée et si son
        nombre de sous-tâches est strictement sous `maxi` (donc jamais avec `maxi` à 0).
        """
        return bool(self.reste) and bool(self.copie) and self.sous_taches < maxi


@dataclass
class Contrat:
    """Le contrat de chantier : la seule chose validée à la main avant de lancer."""

    objectif: str
    hors_perimetre: str = ""
    max_tentatives: int = 3
    max_montees: int = 2
    plafond_modele: str = "opus"
    plafond_effort: str = "high"
    zones_rouges: list[str] = field(default_factory=lambda: list(ZONES_ROUGES))
    valide: bool = False
    max_cout_usd: float = 0.0  # 0 : pas de budget ; sinon plus aucun agent ne part au-delà


@dataclass
class Chantier:
    """L'état complet d'un chantier."""

    projet: str
    contrat: Contrat
    taches: list[Tache] = field(default_factory=list)
    agents_lances: int = 0
    montees: int = 0
    cout_usd: float = 0.0
    tokens: int = 0
    evenements: list[dict] = field(default_factory=list)
    demandes: list[dict] = field(default_factory=list)
    termine: bool = False
    session: str = ""
    # Les règles retenues par « Toujours pendant ce chantier » : elles partent avec lui.
    autorisations_chantier: list[str] = field(default_factory=list)
    # Le débit : places d'écriture, agents en marche, suspensions pour limite (`Places.etat`),
    # rangé par le moteur pour l'affichage. Jamais relu par lui : après un redémarrage, le
    # premier refus pour limite rétablit la suspension.
    debit: dict = field(default_factory=dict)
    ouvert_le: str = field(default_factory=lambda: datetime.now().isoformat(timespec="minutes"))

    def tache(self, identifiant: str) -> Tache:
        """Rend la tâche portant cet identifiant."""
        return next(t for t in self.taches if t.id == identifiant)

    def noter(self, texte: str, tache: str = "", auteur: str = "moteur") -> None:
        """Ajoute une ligne au fil : du moteur, de la personne responsable ou de l'orchestrateur."""
        heure = datetime.now().strftime("%H:%M:%S")
        self.evenements.append({"heure": heure, "tache": tache, "texte": texte, "auteur": auteur})

    def en_dict(self) -> dict:
        """Rend le chantier sous forme de dictionnaire, prêt pour JSON."""
        return asdict(self)

    def sauver(self, chemin: Path) -> None:
        """Écrit l'état du chantier dans un fichier JSON, d'un seul geste.

        Le texte part dans un fichier voisin, qui prend la place de l'ancien une fois écrit en
        entier : un arrêt en pleine écriture laisse l'ancien état lisible, jamais un fichier
        tronqué.
        """
        ecrire_d_un_seul_geste(chemin, json.dumps(self.en_dict(), ensure_ascii=False, indent=2))

    @classmethod
    def depuis_dict(cls, donnees: dict) -> Chantier:
        """Reconstruit un chantier à partir d'un dictionnaire.

        Une clé absente prend sa valeur par défaut ; une clé inconnue du chantier, d'une tâche ou
        du contrat (écrite par une version plus récente) est ignorée, sans empêcher l'ouverture.
        """
        donnees = dict(donnees)
        donnees.setdefault("ouvert_le", "")  # un état d'avant cette date : inconnue
        reglages = dict(donnees.pop("contrat"))
        reglages.pop("max_agents", None)  # l'ancien plafond d'agents, retiré le 12 novembre 2026
        contrat = Contrat(**_connus(Contrat, reglages))
        taches = [Tache(**_connus(Tache, t)) for t in donnees.pop("taches", [])]
        return cls(contrat=contrat, taches=taches, **_connus(cls, donnees))

    @classmethod
    def charger(cls, chemin: Path) -> Chantier:
        """Lit l'état du chantier depuis un fichier JSON."""
        return cls.depuis_dict(json.loads(chemin.read_text("utf-8")))


def _connus(classe, donnees: dict) -> dict:
    """Ne garde d'un dictionnaire que les champs que la classe connaît."""
    noms = {champ.name for champ in fields(classe)}
    return {cle: valeur for cle, valeur in donnees.items() if cle in noms}


def ecrire_cahier(chantier: Chantier, chemin: Path) -> None:
    """Écrit le cahier des charges lisible par une personne, en Markdown."""
    c = chantier.contrat
    lignes = [
        f"# Cahier des charges — {chantier.projet}",
        "",
        f"Objectif : {c.objectif}",
        "",
        f"Agents lancés : {chantier.agents_lances} · "
        f"Montées en gamme : {chantier.montees} / {c.max_montees}",
        "",
    ]
    for t in chantier.taches:
        ajout = " (ajoutée en route)" if t.ajoutee else ""
        lignes += [
            f"## {t.id} — {t.titre}{ajout}",
            f"- État : {ETATS_FR.get(t.etat, t.etat)}",
            f"- Dosage : {t.modele}, effort {t.effort} · tentatives : {t.tentatives}",
            f"- Périmètre : {', '.join(t.perimetre) or 'non précisé'}",
        ]
        lignes += [f"- Critère {i} : {critere}" for i, critere in enumerate(t.criteres, 1)]
        if t.verdict:
            lignes.append(f"- Verdict : {t.verdict}")
        lignes.append("")
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text("\n".join(lignes), "utf-8")
