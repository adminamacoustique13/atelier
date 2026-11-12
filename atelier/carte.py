"""La carte du code d'un projet : ses fichiers, une explication en français pour chacun, qui se
sert de qui, et ce qui a changé depuis la version précédente.

L'analyse ne repart jamais de zéro : chaque fichier porte une empreinte de son contenu, et seuls
les fichiers dont l'empreinte a changé sont relus et réexpliqués. La carte vit dans
`.atelier/carte.json` du projet, qui reste sur la machine.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import posixpath
import re
import subprocess
import threading
from datetime import datetime
from pathlib import Path

from atelier.archives import date_fr
from atelier.consignes import dernier_json

FICHIER = Path(".atelier") / "carte.json"
DOSSIERS_IGNORES = set(
    ".git .atelier node_modules .venv venv env __pycache__ dist build .next .nuxt .pytest_cache "
    ".ruff_cache .mypy_cache target .idea .vscode .cache coverage .turbo .parcel-cache".split()
)
EXTENSIONS = {
    "code": set(
        ".py .js .mjs .cjs .ts .tsx .jsx .go .rs .java .kt .swift .rb .php .c .h .cpp .hpp .cs "
        ".sh .lua .dart .vue .svelte .sql .r .scala .ex .exs".split()
    ),
    "page": set(".html .htm .css .scss .sass .less .svg".split()),
    "réglages": set(".json .toml .yaml .yml .ini .cfg .conf .lock .env .plist .xml".split()),
    "documentation": set(".md .txt .rst .adoc".split()),
}
NOMS_REGLAGES = set("dockerfile makefile .gitignore .gitattributes .editorconfig procfile".split())
BINAIRES = set(
    ".png .jpg .jpeg .gif .webp .ico .icns .pdf .zip .gz .tar .7z .woff .woff2 .ttf .otf .eot "
    ".mp3 .mp4 .mov .wav .ogg .webm .bin .exe .dll .so .dylib .class .jar .pyc .db .sqlite "
    ".bundle".split()
)
LANGAGES = dict(
    paire.split("=")
    for paire in (
        ".py=Python .js=JavaScript .mjs=JavaScript .cjs=JavaScript .ts=TypeScript .tsx=TypeScript "
        ".jsx=JavaScript .html=HTML .css=CSS .sh=shell .go=Go .rs=Rust .java=Java .rb=Ruby "
        ".php=PHP .swift=Swift .kt=Kotlin .sql=SQL .vue=Vue"
    ).split()
)
EXPLICABLES = {"code", "page", "tests", "réglages"}
TAILLE_MAX = 1_000_000  # un fichier plus gros n'est pas lu : il reste une étoile, sans détail
EXTRAIT_MAX = 12_000  # ce que Claude lit d'un fichier
LOT_MAX = 40_000  # ce que Claude lit en un appel
FICHIERS_PAR_LOT = 8
PIECES_MAX = 40
JS_EXT = (".js", ".ts", ".tsx", ".jsx", ".mjs", ".cjs", ".vue", ".svelte", ".css")


# --- les fichiers -----------------------------------------------------------------------------


def genre(chemin: str) -> str:
    """Le genre d'un fichier : code, tests, page, réglages, documentation ou autre."""
    nom = posixpath.basename(chemin).lower()
    ext = posixpath.splitext(nom)[1]
    parties = chemin.lower().split("/")[:-1]
    est_test = nom.startswith("test_") or re.search(r"(_test|\.test|\.spec)\.\w+$", nom)
    if ext in EXTENSIONS["code"] and (est_test or {"tests", "test", "__tests__"} & set(parties)):
        return "tests"
    if nom in NOMS_REGLAGES:
        return "réglages"
    for nom_genre, extensions in EXTENSIONS.items():
        if ext in extensions:
            return nom_genre
    return "autre"


def _git(depot: Path, *arguments: str) -> str:
    environnement = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    resultat = subprocess.run(
        ["git", "-C", str(depot), *arguments],
        capture_output=True,
        text=True,
        timeout=60,
        stdin=subprocess.DEVNULL,
        env=environnement,
    )
    if resultat.returncode != 0:
        raise OSError(resultat.stderr.strip() or "git a échoué")
    return resultat.stdout


def commit_courant(depot: Path) -> str:
    """L'identifiant du dernier commit du projet, ou vide si ce n'est pas un dépôt git."""
    try:
        return _git(depot, "rev-parse", "HEAD").strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _ignore(chemin: str) -> bool:
    parties = chemin.split("/")
    return bool(DOSSIERS_IGNORES & set(parties[:-1])) or (
        posixpath.splitext(parties[-1].lower())[1] in BINAIRES
    )


def lister_fichiers(depot: Path) -> dict[str, str]:
    """Les fichiers du projet et leur empreinte : ceux que suit git, sinon ceux du dossier."""
    depot = Path(depot)
    try:
        sortie = _git(depot, "ls-files", "-s", "-z")
        fichiers = {}
        for entree in filter(None, sortie.split("\0")):
            tete, chemin = entree.split("\t", 1)
            if not _ignore(chemin) and (depot / chemin).is_file():
                fichiers[chemin] = tete.split()[1]
        return fichiers
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        pass
    fichiers = {}
    for racine, dossiers, noms in os.walk(depot):
        dossiers[:] = sorted(d for d in dossiers if d not in DOSSIERS_IGNORES)
        for nom in noms:
            chemin = Path(racine, nom).relative_to(depot).as_posix()
            if not _ignore(chemin):
                with open(Path(racine, nom), "rb") as entree:
                    fichiers[chemin] = hashlib.sha1(entree.read(TAILLE_MAX)).hexdigest()
    return fichiers


def lire_texte(depot: Path, chemin: str) -> str | None:
    """Le texte d'un fichier, ou None s'il est trop gros ou n'est pas du texte."""
    try:
        donnees = (Path(depot) / chemin).read_bytes()[: TAILLE_MAX + 1]
    except OSError:
        return None
    if len(donnees) > TAILLE_MAX or b"\0" in donnees[:4096]:
        return None
    return donnees.decode("utf-8", errors="replace")


# --- les parties d'un fichier et ce qu'en disent ses commentaires -----------------------------


def _premiere_phrase(texte: str | None) -> str:
    texte = " ".join((texte or "").split())
    fin = re.search(r"(?<=[.!?])\s", texte)
    return (texte[: fin.start()] if fin else texte)[:240]


def _pieces_python(texte: str) -> tuple[str, list[dict]]:
    try:
        arbre = ast.parse(texte)
    except (SyntaxError, ValueError):
        return "", []
    pieces = []
    for noeud in arbre.body:
        if isinstance(noeud, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            sorte = "classe" if isinstance(noeud, ast.ClassDef) else "fonction"
            doc = _premiere_phrase(ast.get_docstring(noeud))
            pieces.append({"nom": noeud.name, "ligne": noeud.lineno, "sorte": sorte, "doc": doc})
    return _premiere_phrase(ast.get_docstring(arbre)), pieces


JS_PIECE = re.compile(
    r"^[ \t]*(?:export\s+)?(?:default\s+)?(?:async\s+)?"
    r"(?:function\s*\*?\s*(?P<f>[\w$]+)|class\s+(?P<c>[\w$]+)|"
    r"(?:const|let|var)\s+(?P<v>[\w$]+)\s*=\s*(?:async\s*)?(?:function\b|\([^)]*\)\s*=>|[\w$]+\s*=>))",
    re.M,
)


def _commentaire_avant(lignes: list[str], index: int) -> str:
    morceaux = []
    for ligne in reversed(lignes[max(0, index - 6) : index]):
        propre = ligne.strip()
        if propre.startswith(("//", "*", "/*")):
            morceaux.insert(0, propre.lstrip("/*").rstrip("*/").strip())
        else:
            break
    return _premiere_phrase(" ".join(morceaux))


def _pieces_js(texte: str) -> tuple[str, list[dict]]:
    lignes = texte.split("\n")
    pieces = []
    for trouve in JS_PIECE.finditer(texte):
        nom = trouve.group("f") or trouve.group("c") or trouve.group("v")
        numero = texte.count("\n", 0, trouve.start()) + 1
        sorte = "classe" if trouve.group("c") else "fonction"
        doc = _commentaire_avant(lignes, numero - 1)
        pieces.append({"nom": nom, "ligne": numero, "sorte": sorte, "doc": doc})
    tete = re.match(r"\s*(?:/\*+(?P<b>.*?)\*/|(?P<l>(?://[^\n]*\n\s*)+))", texte, re.S)
    entete = ""
    if tete:
        entete = re.sub(r"^\s*(//|\*)\s?", "", tete.group("b") or tete.group("l") or "", flags=re.M)
    titre = re.search(r"<title>([^<]+)</title>", texte, re.I)
    return _premiere_phrase(entete) or (titre.group(1).strip() if titre else ""), pieces


def _doc_markdown(texte: str) -> str:
    titre = re.search(r"^#\s+(.+)$", texte, re.M)
    paragraphe = next(
        (
            b.strip()
            for b in re.split(r"\n\s*\n", texte)
            if b.strip() and not b.lstrip().startswith(("#", "```", "|", "<"))
        ),
        "",
    )
    debut = f"{titre.group(1).strip()}. " if titre else ""
    return (debut + _premiere_phrase(paragraphe)).strip()


def decrire(chemin: str, texte: str | None) -> tuple[str, list[dict]]:
    """Ce que le fichier dit de lui-même (son commentaire de tête) et ses principales parties."""
    if texte is None:
        return "", []
    ext = posixpath.splitext(chemin.lower())[1]
    if ext == ".py":
        doc, pieces = _pieces_python(texte)
    elif ext in (".js", ".ts", ".tsx", ".jsx", ".mjs", ".cjs", ".html", ".htm", ".vue", ".svelte"):
        doc, pieces = _pieces_js(texte)
    elif ext in (".md", ".rst", ".txt"):
        doc, pieces = _doc_markdown(texte), []
    else:
        doc, pieces = "", []
    return doc, sorted(pieces, key=lambda p: p["ligne"])[:PIECES_MAX]


def phrase_generique(chemin: str, fiche: dict) -> str:
    """Une phrase de repli, quand ni le fichier ni Claude n'ont rien dit."""
    langage = LANGAGES.get(posixpath.splitext(chemin.lower())[1], "")
    noms = {
        "code": f"Un fichier de code{' ' + langage if langage else ''}",
        "tests": "Des tests automatiques, qui vérifient qu'une partie du code fait ce qu'elle doit",
        "page": "Une partie de l'interface (page, mise en forme ou image vectorielle)",
        "réglages": "Un fichier de réglages, lu par un outil ou par le programme",
        "documentation": "Un texte de documentation",
    }
    return f"{noms.get(fiche['genre'], 'Un fichier')}, de {fiche['lignes']} lignes."


# --- qui se sert de qui -----------------------------------------------------------------------


def _modules_python(fichiers) -> dict[str, str]:
    index = {}
    for chemin in fichiers:
        if not chemin.endswith(".py"):
            continue
        parties = chemin[:-3].split("/")
        if parties[-1] == "__init__":
            parties = parties[:-1]
        for debut in (0, 1) if parties and parties[0] == "src" else (0,):
            if parties[debut:]:
                index.setdefault(".".join(parties[debut:]), chemin)
    return index


def _imports_python(chemin: str, texte: str, index: dict[str, str]) -> set[str]:
    try:
        arbre = ast.parse(texte)
    except (SyntaxError, ValueError):
        return set()
    paquet = (
        chemin[:-3].split("/")[:-1]
        if not chemin.endswith("__init__.py")
        else chemin.split("/")[:-1]
    )
    cibles = set()
    for noeud in ast.walk(arbre):
        candidats = []
        if isinstance(noeud, ast.Import):
            candidats = [a.name for a in noeud.names]
        elif isinstance(noeud, ast.ImportFrom):
            base = noeud.module or ""
            if noeud.level:
                parent = paquet[: len(paquet) - (noeud.level - 1)] if noeud.level > 1 else paquet
                base = ".".join([*parent, *([base] if base else [])])
            candidats = [f"{base}.{a.name}" if base else a.name for a in noeud.names] + [base]
        for nom in candidats:
            while nom:
                if nom in index:
                    cibles.add(index[nom])
                    break
                nom = nom.rpartition(".")[0]
    return cibles


JS_IMPORTS = [
    re.compile(r"""(?:import|export)\s[^'"`;]*?from\s*['"]([^'"]+)['"]"""),
    re.compile(r"""\bimport\s*\(?\s*['"]([^'"]+)['"]"""),
    re.compile(r"""\brequire\(\s*['"]([^'"]+)['"]\s*\)"""),
    re.compile(r"""<script[^>]*\ssrc=["']([^"']+)["']""", re.I),
    re.compile(r"""<link[^>]*\shref=["']([^"']+\.css)["']""", re.I),
    re.compile(r"""@import\s+(?:url\()?\s*["']([^"']+)["']"""),
]


def _imports_js(chemin: str, texte: str, fichiers) -> set[str]:
    cibles = set()
    dossier = posixpath.dirname(chemin)
    for motif in JS_IMPORTS:
        for cible in motif.findall(texte):
            if not cible.startswith((".", "/")) or "://" in cible:
                continue
            base = posixpath.normpath(
                cible.lstrip("/") if cible.startswith("/") else posixpath.join(dossier, cible)
            )
            for essai in (base, *(base + e for e in JS_EXT), *(f"{base}/index{e}" for e in JS_EXT)):
                if essai in fichiers:
                    cibles.add(essai)
                    break
    return cibles


def liens(depot: Path, fiches: dict) -> list[list[str]]:
    """Les liens « se sert de » entre fichiers du projet : [fichier, fichier dont il se sert]."""
    index = _modules_python(fiches)
    paires = set()
    for chemin in fiches:
        texte = lire_texte(depot, chemin)
        if texte is None:
            continue
        if chemin.endswith(".py"):
            cibles = _imports_python(chemin, texte, index)
        elif chemin.lower().endswith(
            (
                ".js",
                ".ts",
                ".tsx",
                ".jsx",
                ".mjs",
                ".cjs",
                ".html",
                ".htm",
                ".css",
                ".vue",
                ".svelte",
                ".scss",
            )
        ):
            cibles = _imports_js(chemin, texte, fiches)
        else:
            continue
        paires.update((chemin, c) for c in cibles if c != chemin)
    return sorted([a, b] for a, b in paires)


# --- la carte : relever, comparer, garder ce qui n'a pas changé -------------------------------


def _maintenant() -> str:
    return datetime.now().isoformat(timespec="minutes")


def relever(depot: Path, ancienne: dict | None = None) -> dict:
    """Une nouvelle carte du projet ; ce qui n'a pas changé depuis `ancienne` est repris tel quel.

    `changements` dit ce qui a bougé depuis la version précédente : fichiers nouveaux, modifiés et
    supprimés. Une première analyse n'a pas de version précédente : rien n'y est marqué.
    """
    depot = Path(depot)
    avant = (ancienne or {}).get("fichiers", {})
    fiches = {}
    for chemin, empreinte in lister_fichiers(depot).items():
        ancienne_fiche = avant.get(chemin)
        if ancienne_fiche and ancienne_fiche.get("sha") == empreinte:
            fiches[chemin] = ancienne_fiche
            continue
        texte = lire_texte(depot, chemin)
        doc, pieces = decrire(chemin, texte)
        fiches[chemin] = {
            "sha": empreinte,
            "genre": genre(chemin),
            "lignes": texte.count("\n") + (0 if texte.endswith("\n") or not texte else 1)
            if texte is not None
            else 0,
            "doc": doc,
            "pieces": pieces,
            "explication": (ancienne_fiche or {}).get("explication"),  # gardée, mais périmée
        }
    carte = {
        "version": (ancienne or {}).get("version", 0) + 1,
        "commit": commit_courant(depot),
        "analyse_le": (ancienne or {}).get("analyse_le") or _maintenant(),
        "maj_le": _maintenant(),
        "fichiers": fiches,
        "liens": liens(depot, fiches),
        "cout_usd": (ancienne or {}).get("cout_usd", 0.0),
        "changements": {"nouveaux": [], "modifies": [], "supprimes": [], "le": "", "depuis": ""},
    }
    if ancienne:
        carte["changements"] = comparer(ancienne, carte)
    return carte


def comparer(ancienne: dict, nouvelle: dict) -> dict:
    """Ce qui a changé entre deux versions de la carte."""
    avant, apres = ancienne.get("fichiers", {}), nouvelle["fichiers"]
    return {
        "nouveaux": sorted(set(apres) - set(avant)),
        "modifies": sorted(
            c for c in set(apres) & set(avant) if apres[c]["sha"] != avant[c].get("sha")
        ),
        "supprimes": sorted(set(avant) - set(apres)),
        "le": nouvelle["maj_le"],
        "depuis": ancienne.get("maj_le", ""),
    }


def a_jour(fiche: dict) -> bool:
    """L'explication de Claude correspond-elle encore au contenu du fichier ?"""
    explication = fiche.get("explication") or {}
    return explication.get("sha") == fiche["sha"]


def a_expliquer(carte: dict) -> list[str]:
    """Les fichiers qui attendent une explication de Claude : nouveaux, modifiés, jamais faits."""
    return sorted(
        c
        for c, f in carte["fichiers"].items()
        if f["genre"] in EXPLICABLES and f["lignes"] and not a_jour(f)
    )


def lots(depot: Path, chemins: list[str]) -> list[list[tuple[str, str]]]:
    """Range les fichiers à expliquer en lots, pour peu d'appels à Claude : (chemin, extrait)."""
    tous, courant, taille = [], [], 0
    for chemin in chemins:
        texte = lire_texte(depot, chemin) or ""
        if len(texte) > EXTRAIT_MAX:
            reste = len(texte) - EXTRAIT_MAX
            texte = texte[:EXTRAIT_MAX] + f"\n[… {reste} caractères de plus, non montrés]"
        if courant and (taille + len(texte) > LOT_MAX or len(courant) >= FICHIERS_PAR_LOT):
            tous.append(courant)
            courant, taille = [], 0
        courant.append((chemin, texte))
        taille += len(texte)
    return tous + ([courant] if courant else [])


CONSIGNE = """Tu expliques le code d'un projet à une personne qui ne sait pas programmer.
Elle dirige le projet et doit comprendre à quoi sert chaque fichier, sans jargon.

Pour chaque fichier ci-dessous, écris en français, au tutoiement :
- "resume" : une phrase qui dit à quoi sert le fichier dans le projet (160 caractères au plus) ;
- "detail" : deux à quatre phrases simples sur ce qu'il fait et avec quoi il travaille ;
- "pieces" : pour chacune des parties nommées dans la liste « Parties » du fichier, une phrase
  courte qui dit à quoi elle sert, sous la forme {{"nom": "...", "role": "..."}}.

Pas de jargon : si un mot technique est inévitable, explique-le dans la même phrase.
Ne lis aucun autre fichier : tout ce qu'il te faut est ci-dessous.
Réponds uniquement par un objet JSON de la forme
{{"fichiers": [{{"chemin": "...", "resume": "...", "detail": "...", "pieces": [...]}}]}}

{fichiers}"""


def consigne(lot: list[tuple[str, str]], carte: dict) -> str:
    """La consigne envoyée à Claude pour un lot de fichiers."""
    blocs = []
    for chemin, texte in lot:
        noms = (
            ", ".join(p["nom"] for p in carte["fichiers"][chemin]["pieces"][:PIECES_MAX])
            or "aucune"
        )
        blocs.append(f"=== Fichier : {chemin}\nParties : {noms}\n```\n{texte}\n```")
    return CONSIGNE.format(fichiers="\n\n".join(blocs))


def appliquer(carte: dict, lot: list[tuple[str, str]], reponse: dict | None) -> int:
    """Range dans la carte les explications reçues pour un lot ; rend combien ont été retenues."""
    recus = {f.get("chemin"): f for f in (reponse or {}).get("fichiers", []) if isinstance(f, dict)}
    retenues = 0
    for chemin, _ in lot:
        fiche, recu = carte["fichiers"].get(chemin), recus.get(chemin)
        if not fiche or not isinstance(recu, dict) or not str(recu.get("resume") or "").strip():
            continue
        roles = {
            str(p.get("nom")): str(p.get("role") or "")[:300]
            for p in recu.get("pieces") or []
            if isinstance(p, dict)
        }
        fiche["explication"] = {
            "sha": fiche["sha"],
            "resume": str(recu["resume"])[:300],
            "detail": str(recu.get("detail") or "")[:1500],
            "pieces": roles,
        }
        retenues += 1
    return retenues


def charger(depot: Path) -> dict | None:
    try:
        return json.loads((Path(depot) / FICHIER).read_text("utf-8"))
    except (OSError, ValueError):
        return None


def sauver(depot: Path, carte: dict) -> None:
    chemin = Path(depot) / FICHIER
    chemin.parent.mkdir(parents=True, exist_ok=True)
    provisoire = chemin.with_suffix(".tmp")
    provisoire.write_text(json.dumps(carte, ensure_ascii=False), "utf-8")
    provisoire.replace(chemin)


# --- ce que voit le tableau de bord -----------------------------------------------------------


def vue(carte: dict, en_cours: dict[str, list[str]] | None = None) -> dict:
    """La carte complète pour la page : fichiers expliqués, liens, changements, travail en cours."""
    en_cours = en_cours or {}
    nouveaux, modifies = (
        set(carte["changements"]["nouveaux"]),
        set(carte["changements"]["modifies"]),
    )
    fichiers = []
    for chemin, f in sorted(carte["fichiers"].items()):
        explication = f.get("explication") if a_jour(f) else None
        roles = (explication or {}).get("pieces", {})
        fichiers.append(
            {
                "chemin": chemin,
                "genre": f["genre"],
                "lignes": f["lignes"],
                "statut": "nouveau"
                if chemin in nouveaux
                else "modifie"
                if chemin in modifies
                else "",
                "resume": (explication or {}).get("resume")
                or f.get("doc")
                or phrase_generique(chemin, f),
                "detail": (explication or {}).get("detail", ""),
                "explique": bool(explication),
                "attente": f["genre"] in EXPLICABLES and bool(f["lignes"]) and not explication,
                "pieces": [
                    {
                        "nom": p["nom"],
                        "ligne": p["ligne"],
                        "sorte": p.get("sorte", "fonction"),
                        "role": roles.get(p["nom"]) or p.get("doc", ""),
                    }
                    for p in f["pieces"]
                ],
                "en_cours": en_cours.get(chemin, []),
            }
        )
    return {
        "version": carte["version"],
        "fichiers": fichiers,
        "liens": carte["liens"],
        "supprimes": carte["changements"]["supprimes"],
        "nouveaux_absents": sorted(c for c in en_cours if c not in carte["fichiers"]),
    }


def bilan_changements(changements: dict) -> str:
    """« 2 fichiers nouveaux, 3 modifiés, 1 supprimé » ; vide si rien n'a changé."""
    morceaux = []
    for cle, mot in (("nouveaux", "nouveau"), ("modifies", "modifié"), ("supprimes", "supprimé")):
        n = len(changements.get(cle, []))
        if n:
            morceaux.append(f"{n} {mot}{'s' if n > 1 else ''}")
    if not morceaux:
        return ""
    total = sum(len(changements.get(c, [])) for c in ("nouveaux", "modifies", "supprimes"))
    return f"{total} fichier{'s' if total > 1 else ''} : " + ", ".join(morceaux)


# --- celui qui écrit les explications ---------------------------------------------------------


class ExplicateurAuto:
    """Sans Claude : la carte se contente de ce que le code dit de lui-même. Rien n'est dépensé."""

    reel = False

    def expliquer(self, texte: str) -> tuple[dict | None, float]:
        return None, 0.0


class ExplicateurClaude:
    """Fait écrire les explications par Claude (Sonnet, effort faible), sans aucun outil."""

    reel = True
    INTERDITS = [
        "Bash",
        "Edit",
        "Write",
        "MultiEdit",
        "NotebookEdit",
        "WebFetch",
        "WebSearch",
        "Agent",
        "Task",
    ]

    def __init__(self, depot: Path, modele: str = "sonnet", fabrique_client=None):
        self.depot, self.modele, self.fabrique_client = Path(depot), modele, fabrique_client

    def expliquer(self, texte: str) -> tuple[dict | None, float]:
        from atelier.sdk import SessionSDK  # comme dans agents.py : jamais au chargement

        session = SessionSDK(
            "carte",
            self.modele,
            "low",
            dossier=self.depot,
            outils_permis=[],
            outils_interdits=self.INTERDITS,
            mode_permission="dontAsk",
            delai_max_s=300,
            fabrique_client=self.fabrique_client,
        )
        try:
            resultat = session.envoyer(texte)
        finally:
            session.fermer()
        if not resultat.ok:
            return None, resultat.cout_usd
        return dernier_json(resultat.texte), resultat.cout_usd


# --- le suivi : analyse, mise à jour après chaque version, explications en arrière-plan -------


class SuiviCarte:
    """La carte d'un projet, tenue à jour.

    `analyser()` lance l'analyse complète en arrière-plan. Ensuite, `verifier()` compare le dernier
    commit du projet à celui de la carte : s'il a changé (une tâche vérifiée, un commit fait
    ailleurs), la carte est relevée de nouveau, et seuls les fichiers changés sont réexpliqués.
    """

    PAUSE_S = 15.0

    def __init__(self, depot: Path, explicateur=None):
        self.depot = Path(depot)
        self.explicateur = explicateur or ExplicateurAuto()
        self.verrou = threading.Lock()  # protège `carte` et l'état du travail
        self.carte = charger(self.depot)
        self.travail = ""  # « analyse », « explications » ou vide
        self.restants = 0
        self.probleme = ""
        self._fil: threading.Thread | None = None
        self._veille: threading.Thread | None = None
        self._reveil = threading.Event()
        self._fin = threading.Event()

    # le travail en arrière-plan

    def occupe(self) -> bool:
        return bool(self._fil and self._fil.is_alive())

    def estimer(self) -> dict:
        """Combien de fichiers seraient relus, et combien d'appels à Claude il faudrait."""
        carte = relever(self.depot, self.carte)
        restants = a_expliquer(carte)
        appels = len(lots(self.depot, restants)) if self.explicateur.reel else 0
        return {"fichiers": len(carte["fichiers"]), "a_expliquer": len(restants), "appels": appels}

    def analyser(self) -> bool:
        """Lance l'analyse (ou la reprend) ; rend False si elle tourne déjà."""
        with self.verrou:
            if self.occupe():
                return False
            self._fil = threading.Thread(target=self._analyser, daemon=True)
            self._fil.start()
        return True

    def _analyser(self) -> None:
        with self.verrou:
            self.travail, self.probleme = "analyse", ""
        try:
            carte = relever(self.depot, self.carte)
            with self.verrou:
                self.carte = carte
                sauver(self.depot, carte)
            self._expliquer()
        except Exception as erreur:  # noqa: BLE001 - l'analyse ne doit jamais tuer le serveur
            with self.verrou:
                self.probleme = f"L'analyse s'est arrêtée : {erreur}"
        finally:
            with self.verrou:
                self.travail, self.restants = "", 0
        self.demarrer_veille()

    def _expliquer(self) -> None:
        with self.verrou:
            restants = a_expliquer(self.carte)
            self.travail, self.restants = "explications", len(restants)
            paquets = lots(self.depot, restants) if self.explicateur.reel else []
        for lot in paquets:
            if self._fin.is_set():
                return
            with self.verrou:
                texte = consigne(lot, self.carte)
            reponse, cout = self.explicateur.expliquer(texte)
            with self.verrou:
                if reponse is None and cout == 0:
                    self.probleme = (
                        "Claude n'a pas pu écrire une partie des explications : réessaie plus tard."
                    )
                appliquer(self.carte, lot, reponse)
                self.carte["cout_usd"] = round(self.carte.get("cout_usd", 0.0) + cout, 4)
                self.carte["version"] += 1
                self.restants = max(0, self.restants - len(lot))
                sauver(self.depot, self.carte)

    # la veille : une nouvelle version du code, et la carte suit

    def verifier(self) -> bool:
        """Relève la carte si le code a changé depuis la dernière version ; True si c'est fait."""
        with self.verrou:
            if self.carte is None or self.occupe():
                return False
            ancien = self.carte.get("commit", "")
        courant = commit_courant(self.depot)
        if not courant or courant == ancien:
            return False
        with self.verrou:
            self._fil = threading.Thread(target=self._mettre_a_jour, daemon=True)
            self._fil.start()
        return True

    def _mettre_a_jour(self) -> None:
        try:
            carte = relever(self.depot, self.carte)
            with self.verrou:
                self.carte = carte
                sauver(self.depot, carte)
            self._expliquer()
        except Exception as erreur:  # noqa: BLE001
            with self.verrou:
                self.probleme = f"La mise à jour de la carte s'est arrêtée : {erreur}"
        finally:
            with self.verrou:
                self.travail, self.restants = "", 0

    def signaler(self) -> None:
        """Une nouvelle version vient peut-être d'arriver : la veille regarde tout de suite."""
        self._reveil.set()

    def demarrer_veille(self) -> None:
        if self.carte is None or (self._veille and self._veille.is_alive()):
            return
        self._veille = threading.Thread(target=self._veiller, daemon=True)
        self._veille.start()

    def _veiller(self) -> None:
        while not self._fin.is_set():
            self._reveil.wait(self.PAUSE_S)
            self._reveil.clear()
            if not self._fin.is_set():
                self.verifier()

    def finir(self) -> None:
        self._fin.set()
        self._reveil.set()

    # ce que voit le tableau de bord

    def resume(self, en_cours: dict[str, list[str]] | None = None) -> dict:
        """L'état de la carte, en quelques champs : il part avec chaque vue du tableau de bord."""
        with self.verrou:
            carte, travail, restants, probleme = (
                self.carte,
                self.travail,
                self.restants,
                self.probleme,
            )
            if carte is None:
                etat = "en_cours" if self.occupe() else "absente"
                return {
                    "etat": etat,
                    "version": 0,
                    "travail": travail,
                    "probleme": probleme,
                    "en_cours": _liste_en_cours(en_cours),
                    "auto": not self.explicateur.reel,
                }
            fiches = carte["fichiers"].values()
            expliquables = [f for f in fiches if f["genre"] in EXPLICABLES and f["lignes"]]
            return {
                "etat": "prete",
                "version": carte["version"],
                "fichiers": len(carte["fichiers"]),
                "expliques": sum(1 for f in expliquables if a_jour(f)),
                "a_expliquer": sum(1 for f in expliquables if not a_jour(f)),
                "travail": travail,
                "restants": restants,
                "probleme": probleme,
                "analyse_le": date_fr(carte.get("analyse_le", "")),
                "maj_le": date_fr(carte.get("maj_le", "")),
                "changements": bilan_changements(carte["changements"]),
                "cout": f"{carte.get('cout_usd', 0.0):.2f}".replace(".", ",") + " $",
                "en_cours": _liste_en_cours(en_cours),
                "auto": not self.explicateur.reel,
            }

    def vue(self, en_cours=None) -> dict | None:
        with self.verrou:
            return vue(self.carte, en_cours) if self.carte else None


def _liste_en_cours(en_cours) -> list[dict]:
    return [{"chemin": c, "agents": a} for c, a in sorted((en_cours or {}).items())]
