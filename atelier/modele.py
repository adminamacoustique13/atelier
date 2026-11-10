"""Les objets du chantier : tâche, contrat, chantier. Tout se lit et s'écrit en fichiers."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
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
    "Installer une dépendance ou un plugin nouveau",
    "Modifier les tests de référence ou les garde-fous eux-mêmes",
]


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
    montees: int = 0
    ajoutee: bool = False
    verdict: str = ""
    cout_usd: float = 0.0
    tokens: int = 0
    historique: list[dict] = field(default_factory=list)


@dataclass
class Contrat:
    """Le contrat de chantier : la seule chose validée à la main avant de lancer."""

    objectif: str
    hors_perimetre: str = ""
    max_agents: int = 12
    max_tentatives: int = 3
    max_montees: int = 2
    plafond_modele: str = "opus"
    plafond_effort: str = "high"
    zones_rouges: list[str] = field(default_factory=lambda: list(ZONES_ROUGES))
    valide: bool = False


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
        """Écrit l'état du chantier dans un fichier JSON."""
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_text(json.dumps(self.en_dict(), ensure_ascii=False, indent=2), "utf-8")

    @classmethod
    def depuis_dict(cls, donnees: dict) -> Chantier:
        """Reconstruit un chantier à partir d'un dictionnaire."""
        donnees = dict(donnees)
        contrat = Contrat(**donnees.pop("contrat"))
        taches = [Tache(**t) for t in donnees.pop("taches", [])]
        return cls(contrat=contrat, taches=taches, **donnees)

    @classmethod
    def charger(cls, chemin: Path) -> Chantier:
        """Lit l'état du chantier depuis un fichier JSON."""
        return cls.depuis_dict(json.loads(chemin.read_text("utf-8")))


def ecrire_cahier(chantier: Chantier, chemin: Path) -> None:
    """Écrit le cahier des charges lisible par une personne, en Markdown."""
    c = chantier.contrat
    lignes = [
        f"# Cahier des charges — {chantier.projet}",
        "",
        f"Objectif : {c.objectif}",
        "",
        f"Agents lancés : {chantier.agents_lances} / {c.max_agents} · "
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
