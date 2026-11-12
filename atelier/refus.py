"""Reconnaître un refus qui se répète et un agent empêché, sans appel à un modèle.

Module pur : aucun effet de bord, aucun import d'un autre module d'Atelier. Le moteur s'en sert
pour ne pas relancer une tâche refusée plusieurs fois pour la même raison, et pour lire ce que
les agents disent de ce qui les empêche de travailler (une commande interdite, par exemple).
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

SEUIL_RESSEMBLANCE = 0.9
"""Ressemblance de forme (entre 0 et 1) à partir de laquelle deux détails sont les mêmes."""

SEUIL_MOTS_COMMUNS = 0.3
"""Indice de Jaccard des mots significatifs à partir duquel deux détails disent la même chose."""

MOTS_SIGNIFICATIFS_MIN = 3
"""Mots significatifs que chaque détail doit porter pour que l'indice de Jaccard compte."""

LETTRES_MIN_D_UN_MOT = 4
"""Un mot significatif a au moins ce nombre de lettres : les mots-outils sont courts."""

CARACTERES_COMPARES = 600
"""Nombre de caractères de la fin du détail que l'on compare."""

MARQUE_EMPECHEMENT = "EMPÊCHÉ :"
"""Début de ligne par lequel un ouvrier signale ce qui l'empêche de travailler."""

MOTS_VIDES = frozenset(
    "avec dans pour sont cette elle être mais donc rien nulle part tout tous aussi comme plus "
    "sans leur leurs même ainsi entre sous chez fait faire été ont les des une que qui pas par "
    "sur est ces ses aux critère tenu livrable".split()
)
"""Mots trop courants dans les refus pour prouver qu'ils parlent du même sujet."""

_CHIFFRES = re.compile(r"\d+")
_ESPACES = re.compile(r"\s+")
_MOT = re.compile(r"[\w./:-]+")
_FICHIER = re.compile(r"[\w/-]+(?:\.[a-z]\w*)+")


def _normaliser(detail: object) -> str:
    """Rend le détail comparable : minuscules, nombres remplacés par « # », espaces réduits.

    Seuls les `CARACTERES_COMPARES` derniers caractères du texte ainsi réduit sont gardés.
    """
    texte = detail if isinstance(detail, str) else ""
    texte = _CHIFFRES.sub("#", texte.lower())
    return _ESPACES.sub(" ", texte).strip()[-CARACTERES_COMPARES:]


def _fichiers(texte: str) -> set[str]:
    """Rend les noms de fichiers cités dans le texte normalisé (un mot, un point, une extension)."""
    return set(_FICHIER.findall(texte))


def _mots(texte: str) -> set[str]:
    """Rend les mots significatifs du texte normalisé : assez longs, hors mots vides."""
    mots = (m.strip(".:") for m in _MOT.findall(texte))
    return {m for m in mots if len(m) >= LETTRES_MIN_D_UN_MOT and m not in MOTS_VIDES}


def _details_proches(detail_a: str, detail_b: str) -> bool:
    """Dit si deux détails normalisés parlent du même sujet.

    Si les deux citent des fichiers, ce doivent être les mêmes (deux débords sur des fichiers
    différents ne sont pas le même refus). Ensuite, soit la forme est quasi identique, soit les
    mots significatifs se recouvrent assez : un même refus reformulé garde ses identifiants.
    """
    fichiers_a, fichiers_b = _fichiers(detail_a), _fichiers(detail_b)
    if fichiers_a and fichiers_b and fichiers_a != fichiers_b:
        return False
    if SequenceMatcher(None, detail_a, detail_b).ratio() >= SEUIL_RESSEMBLANCE:
        return True
    mots_a, mots_b = _mots(detail_a), _mots(detail_b)
    if min(len(mots_a), len(mots_b)) < MOTS_SIGNIFICATIFS_MIN:
        return False
    return len(mots_a & mots_b) / len(mots_a | mots_b) >= SEUIL_MOTS_COMMUNS


def meme_refus(a: dict, b: dict) -> bool:
    """Dit si deux entrées d'historique décrivent le même refus.

    Il faut la même origine (absente des deux compte comme égale), la même issue et un détail
    proche (voir `_details_proches`). Un détail vide des deux côtés ne prouve rien : le résultat
    est alors faux, comme pour toute entrée qui n'est pas un dictionnaire.
    """
    if not isinstance(a, dict) or not isinstance(b, dict):
        return False
    if a.get("origine") != b.get("origine") or a.get("issue") != b.get("issue"):
        return False
    detail_a, detail_b = _normaliser(a.get("detail")), _normaliser(b.get("detail"))
    if not detail_a and not detail_b:
        return False
    return _details_proches(detail_a, detail_b)


def refus_identiques_de_suite(historique: list[dict]) -> int:
    """Compte les refus identiques consécutifs à la fin de l'historique.

    Une entrée d'issue `valide` coupe la suite : si la dernière entrée est valide, le résultat
    est zéro ; sinon on remonte tant que l'entrée précédente est le même refus que la dernière.
    """
    if not isinstance(historique, list) or not historique:
        return 0
    dernier = historique[-1]
    if not isinstance(dernier, dict) or dernier.get("issue") == "valide":
        return 0
    nombre = 1
    for entree in reversed(historique[:-1]):
        if not meme_refus(entree, dernier) or entree.get("issue") == "valide":
            break
        nombre += 1
    return nombre


def _lignes_d_empechement(compte_rendu: object) -> list[str]:
    """Rend le texte des lignes du compte rendu qui commencent par la marque d'empêchement."""
    if not isinstance(compte_rendu, str):
        return []
    trouves = []
    for ligne in compte_rendu.splitlines():
        ligne = ligne.strip()
        if ligne.startswith(MARQUE_EMPECHEMENT):
            trouves.append(ligne[len(MARQUE_EMPECHEMENT) :].strip())
    return trouves


def _champ_empeche(verdict: object) -> list[str]:
    """Rend le champ `empeche` d'un verdict, qu'il soit une chaîne ou une liste de chaînes."""
    if not isinstance(verdict, dict):
        return []
    valeur = verdict.get("empeche")
    elements = valeur if isinstance(valeur, list) else [valeur]
    return [e.strip() for e in elements if isinstance(e, str)]


def empechements(compte_rendu: str, refuses: list[str] | None, verdict: dict | None) -> list[str]:
    """Liste, sans doublon et dans l'ordre, ce qui empêche l'agent de travailler.

    D'abord les lignes du compte rendu qui commencent par « EMPÊCHÉ : », puis les outils refusés
    par le pont, puis le champ `empeche` du verdict. Une liste vide veut dire que rien n'est
    signalé ; une entrée mal formée est ignorée, jamais une erreur.
    """
    refuses_valides = (
        [r.strip() for r in refuses if isinstance(r, str)] if isinstance(refuses, list) else []
    )
    resultat: list[str] = []
    for texte in [*_lignes_d_empechement(compte_rendu), *refuses_valides, *_champ_empeche(verdict)]:
        if texte and texte not in resultat:
            resultat.append(texte)
    return resultat
