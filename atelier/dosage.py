"""Dosage : quel modèle et quel effort pour quelle tâche, et comment monter d'un cran.

Règle de fond : on dose selon ce que coûterait une erreur passée inaperçue.
On part bas pour le mécanique, au plus haut pour la physique et les formules de norme.
Haiku n'est plus un point de départ : il reste dans l'échelle, sous Sonnet, pour un plafond
ou un réglage de profil qui le demanderait.

La vérification suit la même règle : complète pour ce qui est délicat, de norme ou de
réparation ; bornée pour la fonctionnalité courante ; mécanique seule (sans vérificateur)
pour le travail mécanique.
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
    "mecanique": ("sonnet", "low"),
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


# Les trois niveaux de vérification, du plus exigeant au plus léger.
COMPLETE = "complete"
BORNEE = "bornee"
MECANIQUE = "mecanique"
NIVEAUX = (COMPLETE, BORNEE, MECANIQUE)

NIVEAUX_FR = {
    COMPLETE: (
        "Vérification complète : un vérificateur d'un modèle au-dessus éprouve les tests en "
        "cassant le code, refait ses propres essais et cherche à mettre le livrable en défaut."
    ),
    BORNEE: (
        "Vérification bornée : un vérificateur du même modèle contrôle les critères et ne "
        "cherche que ce qui bloquerait ; les remarques mineures ne recalent pas."
    ),
    MECANIQUE: (
        "Vérification mécanique seule : les contrôles du profil, le contrôle du périmètre et "
        "la lecture du diff, sans vérificateur."
    ),
}

# Le niveau de vérification de départ par type de tâche. « reparation » n'est pas un type
# que l'orchestrateur choisit : c'est la tâche que le moteur ajoute seul quand la branche
# principale est rouge (paramètre `reparation` de `niveau_verification`).
REPARATION = "reparation"
NIVEAU_DEPART = {
    "mecanique": MECANIQUE,
    "courante": BORNEE,
    "delicate": COMPLETE,
    "physique": COMPLETE,
    "conception": COMPLETE,
    REPARATION: COMPLETE,
}

# Les types que le profil ne peut pas faire descendre sous la vérification complète.
PLANCHER_COMPLET = frozenset({"delicate", "physique", REPARATION})


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


def niveau_verification(
    type_tache: str, reglages: dict | None = None, reparation: bool = False
) -> str:
    """Rend le niveau de vérification d'une tâche : « complete », « bornee » ou « mecanique ».

    `reglages` est la clé `verification` du profil, par exemple {"courante": "complete"}.
    Une valeur inconnue, mal formée ou une clé qui n'est pas un dictionnaire est ignorée.
    Les types délicat, physique et la réparation restent en vérification complète quoi que
    dise le profil. Un type inconnu reçoit la vérification complète : dans le doute, on vérifie.
    `reparation` dit que la tâche est une réparation de la branche principale, quel que soit
    son type.
    """
    cle = REPARATION if reparation else type_tache
    if cle in PLANCHER_COMPLET:
        return COMPLETE
    niveau = NIVEAU_DEPART.get(cle, COMPLETE)
    if isinstance(reglages, dict):
        demande = reglages.get(cle)
        if isinstance(demande, str) and demande in NIVEAUX:
            niveau = demande
    return niveau


def libelle_niveau(niveau: str) -> str:
    """Écrit un niveau de vérification en une phrase, pour l'affichage.

    Un niveau inconnu est lu comme la vérification complète, comme partout ailleurs.
    """
    return NIVEAUX_FR.get(niveau, NIVEAUX_FR[COMPLETE])


def verificateur_selon_niveau(modele: str, effort: str, niveau: str) -> tuple[str, str] | None:
    """Rend le dosage du vérificateur selon le niveau de vérification, ou None sans vérificateur.

    - complète : un modèle au-dessus de l'ouvrier, exactement comme `verificateur` ;
    - bornée : le même modèle que l'ouvrier, au même effort, sans descendre sous l'effort moyen ;
    - mécanique seule : aucun vérificateur (None).
    Un niveau inconnu est traité comme la vérification complète.
    """
    if niveau == MECANIQUE:
        return None
    if niveau == BORNEE:
        MODELES.index(modele)  # un modèle hors de l'échelle lève, comme dans `verificateur`
        plancher = max(EFFORTS.index(effort), EFFORTS.index("medium"))
        return modele, EFFORTS[plancher]
    return verificateur(modele, effort)


def libelle(modele: str, effort: str) -> str:
    """Écrit un dosage en clair, par exemple « Sonnet, effort moyen »."""
    return f"{modele.capitalize()}, effort {EFFORTS_FR.get(effort, effort)}"
