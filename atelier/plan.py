"""La forme d'un plan : combien de tâches travaillent en même temps, et ce qui les retient.

Le moteur lance ensemble toutes les tâches prêtes : dépendances vérifiées, périmètre libre.
Ce module rejoue ces deux règles sur un plan, sans rien lancer, pour dire en combien de vagues
il tient. Il ne lit ni n'écrit rien : il prend des tâches et rend des listes et du texte.
"""

from __future__ import annotations

from atelier.controles import se_chevauchent


def _champs(tache) -> tuple[str, list[str], list[str]]:
    """L'identifiant, les dépendances et le périmètre d'une tâche, objet `Tache` ou dict du plan."""
    if isinstance(tache, dict):
        lire = tache.get
    else:
        def lire(cle, defaut=None):
            return getattr(tache, cle, defaut)
    return str(lire("id", "")), list(lire("depend_de", None) or []), list(
        lire("perimetre", None) or []
    )


def _et(mots: list[str]) -> str:
    """« A », « A et B », « A, B et C »."""
    if len(mots) < 2:
        return "".join(mots)
    return ", ".join(mots[:-1]) + " et " + mots[-1]


def _ce_qui_chevauche(tache: str, autre: str, perimetres: dict[str, list[str]]) -> str:
    """Dit en clair pourquoi deux tâches ne peuvent pas travailler en même temps."""
    for x in perimetres[tache]:
        for y in perimetres[autre]:
            if x == y:
                return f"{tache} et {autre} touchent tous deux {x}"
            if se_chevauchent([x], [y]):
                return f"{tache} ({x}) et {autre} ({y}) peuvent toucher les mêmes fichiers"
    return f"{tache} et {autre} peuvent toucher les mêmes fichiers"


def _vague_suivante(restantes, passees, perimetres, retenues) -> list[str]:
    """Une vague : dans l'ordre du plan, chaque tâche prête qui ne chevauche aucune déjà prise.

    C'est la règle de `Moteur._prochaine` : la première prête dans le plan part, et une tâche
    prête qui chevauche une tâche partie attend la vague suivante.
    """
    vague: list[str] = []
    for ident, deps in restantes:
        if not set(deps) <= passees:
            continue
        gene = next((a for a in vague if se_chevauchent(perimetres[ident], perimetres[a])), None)
        if gene is None:
            vague.append(ident)
            continue
        phrase = _ce_qui_chevauche(ident, gene, perimetres)
        if phrase not in retenues:
            retenues.append(phrase)
    return vague


def _problemes(taches: list[tuple[str, list[str], list[str]]]) -> list[str]:
    """Ce qui empêche un plan d'aller au bout : identifiant vide ou doublé, dépendance inconnue."""
    connus: set[str] = set()
    problemes = []
    for ident, _, _ in taches:
        if not ident:
            problemes.append("une tâche n'a pas d'identifiant")
        elif ident in connus:
            problemes.append(f"deux tâches portent l'identifiant {ident}")
        connus.add(ident)
    for ident, deps, _ in taches:
        inconnues = [d for d in deps if d not in connus]
        if inconnues:
            qui = "qui n'est pas" if len(inconnues) == 1 else "qui ne sont pas"
            problemes.append(f"{ident} dépend de {_et(inconnues)}, {qui} dans le plan")
    return problemes


def _cycle(depart: str, dependances: dict[str, list[str]], bloquees: set[str]) -> list[str]:
    """Suit les dépendances bloquées depuis une tâche jusqu'à retomber sur un pas déjà fait."""
    chemin: list[str] = []
    courant = depart
    while courant not in chemin:
        chemin.append(courant)
        suivant = next((d for d in dependances.get(courant, []) if d in bloquees), None)
        if suivant is None:
            return []
        courant = suivant
    return chemin[chemin.index(courant):]


def _bloquees_en_clair(bloquees: list[str], dependances: dict[str, list[str]]) -> list[str]:
    """Dit pourquoi les tâches qui ne partent jamais restent à quai : boucle ou attente."""
    reste = set(bloquees)
    vus: set[str] = set()
    phrases = []
    for ident in bloquees:
        boucle = _cycle(ident, dependances, reste)
        if not boucle or vus & set(boucle):
            continue
        vus |= set(boucle)
        if len(boucle) == 1:
            phrases.append(f"{boucle[0]} dépend d'elle-même")
        else:
            phrases.append(f"{_et(boucle)} s'attendent en boucle")
    return phrases


def _plus_longue_chaine(taches, dependances: dict[str, list[str]]) -> int:
    """Le nombre de tâches de la plus longue suite où chacune attend la précédente."""
    longueurs: dict[str, int] = {}
    for ident, _, _ in taches:
        longueurs[ident] = _longueur(ident, dependances, longueurs, set())
    return max(longueurs.values(), default=0)


def _longueur(ident, dependances, connues: dict[str, int], en_cours: set[str]) -> int:
    if ident in connues:
        return connues[ident]
    if ident in en_cours or ident not in dependances:
        return 0  # une boucle ou une dépendance inconnue : signalées à part
    en_cours.add(ident)
    plus = max((_longueur(d, dependances, connues, en_cours) for d in dependances[ident]),
               default=0)
    en_cours.discard(ident)
    connues[ident] = plus + 1
    return plus + 1


def forme_du_plan(taches: list) -> dict:
    """Calcule la forme d'un plan : ses vagues, sa largeur, ce qui le retient, en clair.

    `taches` : des objets `Tache` ou des dicts du plan (clés `id`, `depend_de`, `perimetre`),
    dans l'ordre du plan. Rend un dict :
    - `taches` (int) : le nombre de tâches ;
    - `vagues` (list[list[str]]) : les identifiants de chaque vague, dans l'ordre du plan ;
    - `nb_vagues` (int), `plus_grande_vague` (int), `plus_longue_chaine` (int) ;
    - `retenues` (list[str]) : ce qui retient des tâches hors de la première vague, en clair ;
    - `problemes` (list[str]) : ce qui empêche le plan d'aller au bout, vide s'il est possible ;
    - `jamais` (list[str]) : les tâches qui ne partiraient jamais ;
    - `possible` (bool) ; `phrase` (str) : le résumé pour la personne et l'orchestrateur.
    """
    champs = [_champs(t) for t in taches]
    perimetres = {ident: perimetre for ident, _, perimetre in champs}
    dependances = {ident: deps for ident, deps, _ in champs}
    restantes = [(ident, deps) for ident, deps, _ in champs]
    vagues: list[list[str]] = []
    retenues: list[str] = []
    passees: set[str] = set()
    while restantes:
        vague = _vague_suivante(restantes, passees, perimetres, retenues)
        if not vague:
            break  # plus rien de prêt : dépendance inconnue ou boucle, dites plus bas
        vagues.append(vague)
        passees |= set(vague)
        restantes = [(i, d) for i, d in restantes if i not in passees]
    jamais = [i for i, _ in restantes]
    problemes = _problemes(champs) + _bloquees_en_clair(jamais, dependances)
    forme = {
        "taches": len(champs),
        "vagues": vagues,
        "nb_vagues": len(vagues),
        "plus_grande_vague": max((len(v) for v in vagues), default=0),
        "plus_longue_chaine": _plus_longue_chaine(champs, dependances),
        "retenues": _retenues(champs, vagues, retenues),
        "problemes": problemes,
        "jamais": jamais,
        "possible": not problemes and not jamais,
    }
    forme["phrase"] = resumer(forme)
    return forme


def _retenues(champs, vagues: list[list[str]], chevauchements: list[str]) -> list[str]:
    """Pour chaque tâche hors de la première vague, ses dépendances ; puis les chevauchements."""
    premiere = set(vagues[0]) if vagues else set()
    partie = {i for v in vagues for i in v}
    attentes = [f"{ident} attend {_et(deps)}" for ident, deps, _ in champs
                if ident in partie and ident not in premiere and deps]
    return attentes + [c for c in chevauchements if c not in attentes]


def _nombre(n: int, mot: str) -> str:
    """« une tâche », « 3 tâches » (les deux mots dits ici sont féminins)."""
    return f"une {mot}" if n == 1 else f"{n} {mot}s"


def _largeur_en_clair(forme: dict) -> str:
    """« tient en 3 vagues ; jusqu'à 5 tâches travaillent en même temps. »"""
    vagues, plus_grande = forme["nb_vagues"], forme["plus_grande_vague"]
    if vagues == 1 and plus_grande == 1:
        return "tient en une vague."
    if vagues == 1:
        return "tient en une seule vague : toutes ses tâches travaillent en même temps."
    if plus_grande == 1:
        return f"tient en {_nombre(vagues, 'vague')} ; une seule tâche travaille à la fois."
    return (f"tient en {_nombre(vagues, 'vague')} ; jusqu'à {plus_grande} tâches travaillent "
            "en même temps.")


def _impossible_en_clair(forme: dict) -> str:
    """« Ce plan ne peut pas aller au bout : D ne partirait jamais. En cause : … »"""
    jamais = forme["jamais"]
    bilan = ""
    if jamais:
        verbe = "ne partiraient jamais" if len(jamais) > 1 else "ne partirait jamais"
        bilan = f" : {_et(jamais)} {verbe}"
    return f"Ce plan ne peut pas aller au bout{bilan}. En cause : {' ; '.join(forme['problemes'])}."


def resumer(forme: dict) -> str:
    """Le résumé en français d'une forme rendue par `forme_du_plan`, en phrases complètes."""
    if not forme["taches"]:
        return "Ce plan ne contient aucune tâche."
    phrases = [] if forme["possible"] else [_impossible_en_clair(forme)]
    parties = sum(len(v) for v in forme["vagues"])
    if parties:
        taille = "d'une seule tâche" if forme["taches"] == 1 else f"de {forme['taches']} tâches"
        sujet = (f"Ce plan {taille}" if forme["possible"]
                 else f"La partie qui peut partir, {_nombre(parties, 'tâche')},")
        phrases.append(f"{sujet} {_largeur_en_clair(forme)}")
        if forme["possible"] and forme["plus_longue_chaine"] > 1:
            phrases.append(f"Sa plus longue chaîne de dépendances compte "
                           f"{forme['plus_longue_chaine']} tâches.")
    if forme["retenues"]:
        phrases.append(f"Ce qui le retient : {' ; '.join(forme['retenues'])}.")
    return " ".join(phrases)
