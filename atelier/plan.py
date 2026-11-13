"""La forme d'un plan : combien de tâches travaillent en même temps, et ce qui les retient.

Le moteur lance ensemble toutes les tâches prêtes : dépendances vérifiées, périmètre libre
(hors fichiers partagés). Ce module rejoue ces deux règles sur un plan, sans rien lancer, pour
dire en combien de vagues il tient. Il ne lit ni n'écrit rien : il prend des tâches et rend des
listes et du texte.
"""

from __future__ import annotations

from collections.abc import Iterable

from atelier.controles import se_chevauchent


def _champs(tache) -> tuple[str, list[str], list[str]]:
    """L'identifiant, les dépendances et le périmètre d'une tâche, objet `Tache` ou dict du plan."""
    if isinstance(tache, dict):
        lire = tache.get
    else:
        def lire(cle, defaut=None):
            return getattr(tache, cle, defaut)
    deps = list(dict.fromkeys(lire("depend_de", None) or []))  # une dépendance citée deux fois
    return str(lire("id", "")), deps, list(lire("perimetre", None) or [])


def _et(mots: list[str]) -> str:
    """« A », « A et B », « A, B et C »."""
    if len(mots) < 2:
        return "".join(mots)
    return ", ".join(mots[:-1]) + " et " + mots[-1]


def _premier_recoupement(a: list[str], b: list[str], partages: list[str]) -> tuple[str, str]:
    """Le premier couple de motifs (de `a`, de `b`) qui peuvent toucher un même fichier non
    partagé."""
    for x in a:
        for y in b:
            if se_chevauchent([x], [y], partages):
                return x, y
    return "", ""


def _vague_suivante(
    restantes, passees, idents, perimetres, chevauchements, partages: list[str]
) -> list[int]:
    """Une vague : dans l'ordre du plan, chaque tâche prête qui ne chevauche aucune déjà prise.

    C'est la règle de `Moteur._prochaine` : la première prête dans le plan part, et une tâche
    prête qui chevauche une tâche partie, hors fichiers partagés, attend la vague suivante. Les
    tâches sont suivies par leur rang dans le plan, non par leur identifiant : le moteur lance
    aussi deux tâches de même identifiant. Rend les rangs de la vague.
    """
    vague: list[int] = []
    for rang, deps in restantes:
        if not set(deps) <= passees:
            continue
        gene = next(
            (a for a in vague if se_chevauchent(perimetres[rang], perimetres[a], partages)), None
        )
        if gene is None:
            vague.append(rang)
            continue
        x, y = _premier_recoupement(perimetres[rang], perimetres[gene], partages)
        ligne = [idents[rang], idents[gene], x, y]
        if ligne not in chevauchements:
            chevauchements.append(ligne)
    return vague


def _problemes(taches: list[tuple[str, list[str], list[str]]]) -> list[str]:
    """Ce qui cloche dans un plan : identifiant vide ou doublé, dépendance inconnue.

    Un identifiant doublé n'empêche pas le moteur d'aller au bout (il lance chaque tâche) ; il
    est dit parce qu'une dépendance vers lui devient ambiguë.
    """
    nombres: dict[str, int] = {}
    problemes = []
    for ident, _, _ in taches:
        nombres[ident] = nombres.get(ident, 0) + 1
        if not ident:
            problemes.append("une tâche n'a pas d'identifiant")
        elif nombres[ident] == 2:
            problemes.append(f"deux tâches portent l'identifiant {ident}")
        elif nombres[ident] == 3:
            ancien = f"deux tâches portent l'identifiant {ident}"
            problemes[problemes.index(ancien)] = f"plusieurs tâches portent l'identifiant {ident}"
    for ident, deps, _ in taches:
        inconnues = [d for d in deps if d not in nombres]
        if inconnues:
            qui = "qui n'est pas" if len(inconnues) == 1 else "qui ne sont pas"
            problemes.append(f"{ident} dépend de {_et(inconnues)}, {qui} dans le plan")
    return list(dict.fromkeys(problemes))


def _cycle(depart: str, dependances: dict[str, list[str]], bloquees: set[str]) -> list[str]:
    """Suit les dépendances bloquées depuis une tâche jusqu'à retomber sur un pas déjà fait."""
    chemin: list[str] = []
    vus: set[str] = set()
    courant = depart
    while courant not in vus:
        chemin.append(courant)
        vus.add(courant)
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
        if ident in vus:
            continue
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
    """Le nombre de tâches de la plus longue suite où chacune attend la précédente.

    Parcours en profondeur avec une pile, non récursif : une chaîne de milliers de tâches passe.
    Une boucle ou une dépendance inconnue compte pour 0 (elles sont signalées à part).
    """
    longueurs: dict[str, int] = {}
    for depart, _, _ in taches:
        if depart in longueurs:
            continue
        pile = [depart]
        en_cours = {depart}
        suite: dict[str, int] = {}
        while pile:
            ident = pile[-1]
            deps = dependances[ident]
            i = suite.get(ident, 0)
            descend = False
            while i < len(deps):
                d = deps[i]
                i += 1
                if d in longueurs or d not in dependances or d in en_cours:
                    continue
                suite[ident] = i
                pile.append(d)
                en_cours.add(d)
                descend = True
                break
            if descend:
                continue
            pile.pop()
            en_cours.discard(ident)
            longueurs[ident] = 1 + max((longueurs.get(d, 0) for d in deps), default=0)
    return max(longueurs.values(), default=0)


def forme_du_plan(taches: list, partages: Iterable[str] = ()) -> dict:
    """Calcule la forme d'un plan : ses vagues, sa largeur, ce qui le retient, en clair.

    `taches` : des objets `Tache` ou des dicts du plan (clés `id`, `depend_de`, `perimetre`),
    dans l'ordre du plan. `partages` : les motifs des fichiers partagés du profil
    (`fichiers_partages`), qui ne retiennent aucune tâche. Rend un dict :
    - `taches` (int) : le nombre de tâches ;
    - `vagues` (list[list[str]]) : les identifiants de chaque vague, dans l'ordre du plan ;
    - `nb_vagues` (int), `plus_grande_vague` (int), `plus_longue_chaine` (int) ;
    - `retenues` (list[str]) : ce qui retient des tâches hors de la première vague, en clair,
      le détail paire par paire ;
    - `attentes` (list[str]) et `chevauchements` (list[[tâche, gênante, motif, motif]]) : les
      mêmes retenues en données, d'où la phrase regroupe les fichiers partagés ;
    - `problemes` (list[str]) : ce qui cloche dans le plan, vide s'il est sain. Un identifiant
      doublé y figure sans empêcher le plan d'aller au bout : le moteur lance chaque tâche ;
    - `jamais` (list[str]) : les tâches qui ne partiraient jamais ;
    - `possible` (bool) : plan sain, sans problème ni tâche qui ne parte jamais ;
    - `phrase` (str) : le résumé pour la personne et l'orchestrateur.
    """
    champs = [_champs(t) for t in taches]
    idents = [ident for ident, _, _ in champs]
    perimetres = [perimetre for _, _, perimetre in champs]
    partages = list(partages)  # relu à chaque paire de tâches
    dependances: dict[str, list[str]] = {}
    for ident, deps, _ in champs:
        dependances[ident] = list(dict.fromkeys(dependances.get(ident, []) + deps))
    restantes = [(rang, deps) for rang, (_, deps, _) in enumerate(champs)]
    vagues: list[list[str]] = []
    chevauchements: list[list[str]] = []
    passees: set[str] = set()
    while restantes:
        vague = _vague_suivante(restantes, passees, idents, perimetres, chevauchements, partages)
        if not vague:
            break  # plus rien de prêt : dépendance inconnue ou boucle, dites plus bas
        vagues.append([idents[r] for r in vague])
        passees |= {idents[r] for r in vague}
        pris = set(vague)
        restantes = [(r, d) for r, d in restantes if r not in pris]
    jamais = [idents[r] for r, _ in restantes]
    problemes = _problemes(champs) + _bloquees_en_clair(jamais, dependances)
    attentes = _attentes(champs, vagues)
    forme = {
        "taches": len(champs),
        "vagues": vagues,
        "nb_vagues": len(vagues),
        "plus_grande_vague": max((len(v) for v in vagues), default=0),
        "plus_longue_chaine": _plus_longue_chaine(champs, dependances),
        "retenues": attentes + [_chevauchement_en_clair(c) for c in chevauchements],
        "attentes": attentes,
        "chevauchements": chevauchements,
        "problemes": problemes,
        "jamais": jamais,
        "possible": not problemes and not jamais,
    }
    forme["phrase"] = resumer(forme)
    return forme


def _attentes(champs, vagues: list[list[str]]) -> list[str]:
    """Pour chaque tâche hors de la première vague, ce qu'elle attend (une fois chacune)."""
    premiere = set(vagues[0]) if vagues else set()
    partie = {i for v in vagues for i in v}
    attentes = [f"{ident} attend {_et(deps)}" for ident, deps, _ in champs
                if ident in partie and ident not in premiere and deps]
    return list(dict.fromkeys(attentes))


def _chevauchement_en_clair(ligne: list[str]) -> str:
    """Une paire de tâches qui ne peuvent pas travailler ensemble, dite en clair."""
    tache, gene, x, y = ligne
    if not x:
        return f"{tache} et {gene} peuvent toucher les mêmes fichiers"
    if x == y:
        return f"{tache} et {gene} touchent toutes deux {x}"
    return f"{tache} ({x}) et {gene} ({y}) peuvent toucher les mêmes fichiers"


# Au-delà de ce nombre de tâches, la phrase dit « 10 tâches » au lieu de les nommer.
NOMMEES_AU_PLUS = 5


def _groupes_en_clair(chevauchements: list[list[str]]) -> list[str]:
    """Regroupe les chevauchements par fichier partagé : une proposition par fichier.

    Deux motifs identiques : « D et A touchent toutes deux X », « A, B et C touchent toutes X »,
    « 10 tâches touchent X ». Deux motifs différents (un dossier et un fichier dedans) :
    regroupés par tâche gênante.
    """
    exacts: dict[str, list[str]] = {}
    larges: dict[tuple[str, str], list[tuple[str, str]]] = {}
    sans_motif: list[str] = []
    for tache, gene, x, y in chevauchements:
        if not x:
            sans_motif.append(_chevauchement_en_clair([tache, gene, x, y]))
        elif x == y:
            membres = exacts.setdefault(x, [])
            membres += [m for m in (tache, gene) if m not in membres]
        else:
            larges.setdefault((gene, y), []).append((tache, x))
    phrases = [_fichier_partage_en_clair(f, m, chevauchements) for f, m in exacts.items()]
    phrases += [_dossier_partage_en_clair(g, y, liste) for (g, y), liste in larges.items()]
    return phrases + sans_motif


def _fichier_partage_en_clair(fichier: str, membres: list[str], chevauchements) -> str:
    """Les tâches qui touchent un même fichier, nommées ou comptées selon leur nombre."""
    if len(membres) == 1:
        return f"plusieurs tâches d'identifiant {membres[0]} touchent {fichier}"
    if len(membres) == 2:
        return f"{_et(membres)} touchent toutes deux {fichier}"
    if len(membres) <= NOMMEES_AU_PLUS:
        rangees = sorted(membres, key=_rang_dans(chevauchements))
        return f"{_et(rangees)} touchent toutes {fichier}"
    return f"{len(membres)} tâches touchent {fichier}"


def _dossier_partage_en_clair(gene: str, y: str, liste: list[tuple[str, str]]) -> str:
    """Les tâches dont le périmètre recoupe celui de `gene` sans être le même motif."""
    if len(liste) == 1:
        return _chevauchement_en_clair([liste[0][0], gene, liste[0][1], y])
    if len(liste) <= NOMMEES_AU_PLUS:
        return f"{_et([t for t, _ in liste])} peuvent toucher les mêmes fichiers que {gene} ({y})"
    return f"{len(liste)} tâches peuvent toucher les mêmes fichiers que {gene} ({y})"


def _rang_dans(chevauchements: list[list[str]]):
    """Une clé de tri : l'ordre où les tâches apparaissent dans les chevauchements."""
    ordre: dict[str, int] = {}
    for tache, gene, _, _ in chevauchements:
        for m in (gene, tache):
            ordre.setdefault(m, len(ordre))
    return ordre.__getitem__


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
    verbe = "ne partiraient jamais" if len(jamais) > 1 else "ne partirait jamais"
    return (f"Ce plan ne peut pas aller au bout : {_et(jamais)} {verbe}. "
            f"En cause : {' ; '.join(forme['problemes'])}.")


def _defaut_en_clair(forme: dict) -> str:
    """Pour un plan que le moteur mènera au bout malgré un défaut (identifiant doublé ou vide)."""
    phrase = ("Ce plan peut aller au bout, mais il a un défaut à corriger : "
              f"{' ; '.join(forme['problemes'])}.")
    if any("portent l'identifiant" in p for p in forme["problemes"]):
        phrase += (" Le moteur lance chacune de ces tâches ; ce qui dépend de cet identifiant "
                   "part dès que l'une d'elles est vérifiée.")
    return phrase


def _retenues_en_clair(forme: dict) -> list[str]:
    """Les attentes, puis les chevauchements regroupés par fichier."""
    if "attentes" not in forme:  # une forme sans le détail en données : la liste, telle quelle
        return forme["retenues"]
    return forme["attentes"] + _groupes_en_clair(forme["chevauchements"])


def resumer(forme: dict) -> str:
    """Le résumé en français d'une forme rendue par `forme_du_plan`, en phrases complètes."""
    if not forme["taches"]:
        return "Ce plan ne contient aucune tâche."
    phrases = []
    if forme["jamais"]:
        phrases.append(_impossible_en_clair(forme))
    elif forme["problemes"]:
        phrases.append(_defaut_en_clair(forme))
    parties = sum(len(v) for v in forme["vagues"])
    if parties:
        entier = not forme["jamais"]
        taille = "d'une seule tâche" if forme["taches"] == 1 else f"de {forme['taches']} tâches"
        sujet = (f"Ce plan {taille}" if entier
                 else f"La partie qui peut partir, {_nombre(parties, 'tâche')},")
        phrases.append(f"{sujet} {_largeur_en_clair(forme)}")
        if entier and forme["plus_longue_chaine"] > 1:
            phrases.append(f"Sa plus longue chaîne de dépendances compte "
                           f"{forme['plus_longue_chaine']} tâches.")
    retenues = _retenues_en_clair(forme)
    if retenues:
        phrases.append(f"Ce qui le retient : {' ; '.join(retenues)}.")
    return " ".join(phrases)
