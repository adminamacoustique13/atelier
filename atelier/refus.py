"""Reconnaître un refus qui se répète et un agent empêché, sans appel à un modèle.

Module pur : aucun effet de bord, aucun import d'un autre module d'Atelier. Le moteur s'en sert
pour ne pas relancer une tâche refusée plusieurs fois pour la même raison, pour lire ce que
les agents disent de ce qui les empêche de travailler (une commande interdite, par exemple), et
pour reconnaître parmi les outils refusés ceux qui lancent une commande de contrôle.

Deux degrés de ressemblance, mesurés sur de vrais refus (voir le cahier, « V3-refus ») :
`meme_refus` accepte aussi deux détails qui partagent assez de mots, ce qui reconnaît un refus
reformulé mais se trompe parfois sur deux refus voisins ; `meme_forme` exige des détails de
forme quasi identique. Un refus des contrôles automatiques se compare d'abord par les tests en
échec et les codes du contrôle de forme lus dans sa sortie, pas par son texte.
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

ORIGINES_CONTROLEES = ("controles", "integration")
"""Les origines dont le détail porte la sortie des contrôles automatiques du projet."""

ORIGINES_SANS_MOTS = ("agent",)
"""Les origines dont le détail est écrit par le code, jamais reformulé par un modèle : la
ressemblance de mots n'y reconnaîtrait rien de plus que la forme, et confondrait deux erreurs
voisines (une surcharge et une limite de l'abonnement partagent presque tous leurs mots)."""

_CHIFFRES = re.compile(r"\d+")
_ESPACES = re.compile(r"\s+")
_MOT = re.compile(r"[\w./:-]+")
_FICHIER = re.compile(r"[\w/-]+(?:\.[a-z]\w*)+")
# Dans la sortie des contrôles : un test en échec de pytest (« FAILED chemin::test - ... »,
# « ERROR chemin »), et un code de ruff en tête de ligne, seul (« E501 Line too long », format
# actuel) ou après sa position (« a.py:12:5: E501 ... », format court).
_TEST_EN_ECHEC = re.compile(r"^(?:FAILED|ERROR) +(\S+)", re.MULTILINE)
_CODE_DE_FORME = re.compile(r"^(?:\S+:\d+:\d+: +)?([A-Z]{1,4}\d{2,4})\b", re.MULTILINE)
# Les identifiants qu'un détail cite : deux refus qui en citent de différents ne sont pas le même
# refus, même s'ils se ressemblent (deux tests d'un même fichier, deux critères écrits sur le même
# modèle, deux codes ruff). Lus avant que les chiffres soient remplacés ; seuls les codes ruff
# se lisent dans la casse d'origine, le reste en minuscules.
_IDENTIFIANTS = (
    (re.compile(r"\btest_\w+"), False),
    (re.compile(r"\bcrit[eè]res? *(?:n° *)?(\d+)"), False),
    (re.compile(r"\b[A-Z]{1,4}\d{2,4}\b"), True),
)


def _texte(detail: object) -> str:
    return detail if isinstance(detail, str) else ""


def _normaliser(detail: object) -> str:
    """Rend le détail comparable : minuscules, nombres remplacés par « # », espaces réduits.

    Seuls les `CARACTERES_COMPARES` derniers caractères du texte ainsi réduit sont gardés.
    """
    texte = _CHIFFRES.sub("#", _texte(detail).lower())
    return _ESPACES.sub(" ", texte).strip()[-CARACTERES_COMPARES:]


def signature_des_controles(sortie: object) -> frozenset[str]:
    """Les tests en échec et les codes du contrôle de forme lus dans une sortie de contrôles.

    Un test est rendu « test:chemin::nom », un code « forme:E501 ». Un ensemble vide veut dire
    qu'on n'a rien pu y lire : il faut alors comparer le texte.
    """
    texte = _texte(sortie)
    tests = {f"test:{t}" for t in _TEST_EN_ECHEC.findall(texte)}
    return frozenset(tests | {f"forme:{c}" for c in _CODE_DE_FORME.findall(texte)})


def _identifiants_differents(brut_a: str, brut_b: str) -> bool:
    """Dit si les deux détails citent, pour une même sorte d'identifiant, deux ensembles différents.

    Une sorte que l'un des deux ne cite pas ne départage rien.
    """
    for motif, sensible in _IDENTIFIANTS:
        trouves_a = set(motif.findall(brut_a if sensible else brut_a.lower()))
        trouves_b = set(motif.findall(brut_b if sensible else brut_b.lower()))
        if trouves_a and trouves_b and trouves_a != trouves_b:
            return True
    return False


def _fichiers(texte: str) -> set[str]:
    """Rend les noms de fichiers cités dans le texte normalisé (un mot, un point, une extension)."""
    return set(_FICHIER.findall(texte))


def _mots(texte: str) -> set[str]:
    """Rend les mots significatifs du texte normalisé : assez longs, hors mots vides."""
    mots = (m.strip(".:") for m in _MOT.findall(texte))
    return {m for m in mots if len(m) >= LETTRES_MIN_D_UN_MOT and m not in MOTS_VIDES}


def _details_proches(detail_a: str, detail_b: str, mots: bool = True) -> bool:
    """Dit si deux détails normalisés parlent du même sujet.

    Si les deux citent des fichiers, ce doivent être les mêmes (deux débords sur des fichiers
    différents ne sont pas le même refus). Ensuite, soit la forme est quasi identique, soit
    (avec `mots`) les mots significatifs se recouvrent assez : un même refus reformulé garde ses
    identifiants.
    """
    fichiers_a, fichiers_b = _fichiers(detail_a), _fichiers(detail_b)
    if fichiers_a and fichiers_b and fichiers_a != fichiers_b:
        return False
    if SequenceMatcher(None, detail_a, detail_b).ratio() >= SEUIL_RESSEMBLANCE:
        return True
    mots_a, mots_b = _mots(detail_a), _mots(detail_b)
    if not mots or min(len(mots_a), len(mots_b)) < MOTS_SIGNIFICATIFS_MIN:
        return False
    return len(mots_a & mots_b) / len(mots_a | mots_b) >= SEUIL_MOTS_COMMUNS


def _meme(a: object, b: object, mots: bool) -> bool:
    """Le cœur de `meme_refus` et de `meme_forme` ; `mots` permet la ressemblance de mots."""
    if not isinstance(a, dict) or not isinstance(b, dict):
        return False
    if a.get("origine") != b.get("origine") or a.get("issue") != b.get("issue"):
        return False
    brut_a, brut_b = _texte(a.get("detail")), _texte(b.get("detail"))
    if a.get("origine") in ORIGINES_CONTROLEES:
        signature_a, signature_b = signature_des_controles(brut_a), signature_des_controles(brut_b)
        if signature_a or signature_b:
            return signature_a == signature_b
    detail_a, detail_b = _normaliser(brut_a), _normaliser(brut_b)
    if not detail_a and not detail_b:
        return False
    if _identifiants_differents(brut_a, brut_b):
        return False
    return _details_proches(detail_a, detail_b, mots and a.get("origine") not in ORIGINES_SANS_MOTS)


def meme_refus(a: dict, b: dict) -> bool:
    """Dit si deux entrées d'historique décrivent le même refus.

    Il faut la même origine (absente des deux compte comme égale), la même issue et un détail
    proche (voir `_details_proches`), sans identifiant cité de part et d'autre qui diffère (nom
    de test, numéro de critère, code ruff). Un refus des contrôles automatiques dont la sortie
    laisse lire des tests en échec ou des codes de forme se compare par ces seuls ensembles ;
    une erreur d'agent, par sa seule forme (`ORIGINES_SANS_MOTS`). Un détail vide des deux côtés
    ne prouve rien : le résultat est alors faux, comme pour toute entrée qui n'est pas un
    dictionnaire.
    """
    return _meme(a, b, mots=True)


def meme_forme(a: dict, b: dict) -> bool:
    """Comme `meme_refus`, sans la ressemblance de mots : les détails doivent avoir quasiment la
    même forme (ou, pour les contrôles, les mêmes tests en échec et les mêmes codes de forme).

    C'est la seule ressemblance qui suffit à bloquer une tâche à qui un cran reste : celle des
    mots se trompe trop souvent sur deux refus voisins (cahier, « V3-refus »).
    """
    return _meme(a, b, mots=False)


def _suite(historique: object, comparer) -> int:
    """Compte, à la fin de l'historique, la dernière entrée et celles qui la précèdent sans
    interruption en étant le même refus qu'elle selon `comparer`."""
    if not isinstance(historique, list) or not historique:
        return 0
    dernier = historique[-1]
    if not isinstance(dernier, dict) or dernier.get("issue") == "valide":
        return 0
    nombre = 1
    for entree in reversed(historique[:-1]):
        if not comparer(entree, dernier) or entree.get("issue") == "valide":
            break
        nombre += 1
    return nombre


def refus_identiques_de_suite(historique: list[dict]) -> int:
    """Compte les refus identiques consécutifs à la fin de l'historique.

    Une entrée d'issue `valide` coupe la suite : si la dernière entrée est valide, le résultat
    est zéro ; sinon on remonte tant que l'entrée précédente est le même refus que la dernière.
    """
    return _suite(historique, meme_refus)


def refus_de_meme_forme_de_suite(historique: list[dict]) -> int:
    """Comme `refus_identiques_de_suite`, avec `meme_forme` : sans la ressemblance de mots."""
    return _suite(historique, meme_forme)


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


def _tete(forme: str) -> str:
    """Le nom d'un outil et le premier mot de son objet, pris dans sa forme courte : « Bash(uv »
    pour « Bash(uv sync) » comme pour « Bash(uv) » ; "" pour un outil sans objet."""
    mots = forme.split()
    tete = mots[0].removesuffix(")") if mots else ""
    return tete if "(" in tete else ""


def outils_de_controle(refuses: list[str], controles: list[str]) -> list[str]:
    """Les outils refusés qui lancent le premier mot d'une commande de contrôle, dans l'ordre.

    Les deux listes sont des formes courtes d'outils (`agents.forme_courte`, comme
    « Bash(uv sync) ») : un outil refusé en est s'il a le même nom et le même premier mot que
    l'un des contrôles (« Bash(uv sync) » pour « Bash(uv run pytest) », pas « Bash(uvx ruff) »).
    Une entrée qui n'est pas un texte est ignorée.
    """
    tetes = {_tete(c) for c in controles if isinstance(c, str)} - {""}
    return [r for r in refuses if isinstance(r, str) and _tete(r) in tetes]


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
