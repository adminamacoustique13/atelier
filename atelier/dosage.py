"""Dosage : quel modèle et quel effort pour quelle tâche, et comment monter d'un cran.

Règle de fond : on dose selon ce que coûterait une erreur passée inaperçue.
On part bas pour le mécanique, au plus haut pour la physique et les formules de norme.
"""

from __future__ import annotations

MODELES = ("haiku", "sonnet", "opus", "fable")
EFFORTS = ("low", "medium", "high", "xhigh", "max")

EFFORTS_FR = {
    "low": "faible",
    "medium": "moyen",
    "high": "élevé",
    "xhigh": "très élevé",
    "max": "max",
}

DEPART = {
    "mecanique": ("haiku", "low"),
    "courante": ("sonnet", "medium"),
    "delicate": ("opus", "high"),
    "physique": ("fable", "max"),
    "conception": ("fable", "high"),
}

TYPES_FR = {
    "mecanique": "Mécanique",
    "courante": "Courante",
    "delicate": "Délicate",
    "physique": "Physique",
    "conception": "Conception",
}


def depart(type_tache: str, table: dict | None = None) -> tuple[str, str]:
    """Rend le modèle et l'effort de départ pour un type de tâche."""
    choix = (table or {}).get(type_tache) or DEPART.get(type_tache) or DEPART["courante"]
    return choix[0], choix[1]


def dans_plafond(modele: str, effort: str, plafond: tuple[str, str]) -> bool:
    """Dit si un dosage reste sous le plafond d'escalade du contrat."""
    rang, rang_plafond = MODELES.index(modele), MODELES.index(plafond[0])
    if rang != rang_plafond:
        return rang < rang_plafond
    return EFFORTS.index(effort) <= EFFORTS.index(plafond[1])


def monter(modele: str, effort: str, motif: str) -> tuple[str, str] | None:
    """Rend le cran au-dessus, ou None si on est déjà tout en haut.

    Un travail bâclé appelle plus d'effort. Un agent qui ne sait pas faire appelle
    un modèle plus capable. Tout en haut de l'échelle des modèles, on pousse l'effort.
    """
    rang_modele, rang_effort = MODELES.index(modele), EFFORTS.index(effort)
    effort_possible = rang_effort < len(EFFORTS) - 1
    if motif == "bacle" and effort_possible:
        return modele, EFFORTS[rang_effort + 1]
    if rang_modele < len(MODELES) - 1:
        return MODELES[rang_modele + 1], effort
    if effort_possible:
        return modele, EFFORTS[rang_effort + 1]
    return None


def verificateur(modele: str, effort: str) -> tuple[str, str]:
    """Rend le dosage du vérificateur : un modèle au-dessus de l'ouvrier.

    Quand l'ouvrier est déjà le modèle le plus capable, le vérificateur l'est aussi,
    en effort max : il devra s'appuyer sur des références extérieures.
    """
    rang = MODELES.index(modele)
    if rang < len(MODELES) - 1:
        plancher = max(EFFORTS.index(effort), EFFORTS.index("medium"))
        return MODELES[rang + 1], EFFORTS[plancher]
    return modele, "max"


def libelle(modele: str, effort: str) -> str:
    """Écrit un dosage en clair, par exemple « Sonnet, effort moyen »."""
    return f"{modele.capitalize()}, effort {EFFORTS_FR.get(effort, effort)}"
