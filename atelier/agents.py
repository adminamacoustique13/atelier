"""Les agents : Claude Code piloté par l'Agent SDK, ou un simulateur pour les essais.

Les deux offrent la même interface au moteur et au serveur : `executer`, `converser`,
`arreter(tache)`, `changer_mode(mode)`, `modes_appliques()`, et les attributs `guichet`,
`sur_evenement` et `source_connexion`. La propriété `mode_ouvriers` existe aussi sur les deux, mais
seuls les tests la lisent : le serveur garde son propre `mode_ouvriers`.

Le mode des ouvriers (un mode de permission de Claude Code) ne touche que les ouvriers.
L'orchestrateur reste en lecture seule, en mode « default », quoi qu'il arrive. Le vérificateur
ne peut jamais écrire dans la copie de l'ouvrier : il travaille dans une copie jetable du
livrable, où ses essais passent sans carte (« acceptEdits »), ou à défaut en lecture seule.
"""

from __future__ import annotations

import functools
import json
import os
import re
import string
import threading
import time
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
from pathlib import Path

from atelier.consignes import BALISE_PLAN, ROLE_ORCHESTRATEUR
from atelier.guichet import ARRETE, CHAINE, SUBSTITUTION

OUTILS_LECTURE = ["Read", "Glob", "Grep"]
OUTILS_ECRITURE = ["Edit", "Write"]
# Interdits au vérificateur et à la conversation ; une règle qui les vise ne leur est pas donnée.
ECRITURE = ("Edit", "Write", "MultiEdit", "NotebookEdit")
# Une règle simple : un nom d'outil, suivi ou non d'une seule paire de parenthèses non vide.
# Le SDK joint les outils permis par des virgules : une virgule ferait lire deux règles.
REGLE_SIMPLE = re.compile(r"[A-Za-z0-9_.:-]+(\([^(),\x00-\x1f\x7f]+\))?")
# Git en lecture seule : regarder l'historique et les branches, jamais les changer. `git branch`
# n'est permis que seul : suivi d'un mot, il est refusé (`interdits`), la branche courante se lit
# par `git status` ou `git rev-parse --abbrev-ref HEAD`.
GIT_LECTURE = [
    f"Bash(git {c}:*)"
    for c in (
        "status", "diff", "log", "show", "ls-files", "remote -v", "remote get-url", "rev-parse",
    )
] + ["Bash(git branch)"]  # fmt: skip

# Des commandes qui lisent sans rien changer ni rien lancer d'autre, permises à tous les agents.
# Écartées exprès : sed, awk, find, xargs, sort et rg, qui savent exécuter une autre commande
# (sed e, system(), -exec, --compress-program, --pre), et less ou more (commande « ! »).
LECTURE_SHELL = [
    f"Bash({c}:*)"
    for c in (
        "ls", "cat", "head", "tail", "wc", "grep", "diff", "cmp", "uniq", "cut", "tr", "nl",
        "column", "file", "stat", "du", "pwd", "which", "tree", "basename", "dirname",
        "realpath", "jq", "md5sum", "shasum", "sha256sum",
    )
]  # fmt: skip
# Les outils courants du développement, permis d'avance aux ouvriers et aux vérificateurs, quel
# que soit le profil : sans eux, chaque tâche ouvrait des cartes et s'arrêtait en ton absence.
# rm, mv et cp n'y sont pas : le mode « Accepter les modifications » les laisse passer dans la
# copie de travail, et seulement là.
COMMANDES_DEV = [
    f"Bash({c}:*)"
    for c in (
        "python", "pip", "pip3", "pytest", "ruff", "mypy", "black", "node", "tsc", "pnpm",
        "yarn", "make", "go", "rustc", "mkdir", "touch",
    )
]  # fmt: skip
# Chercher sur le web ne touche à rien ; lire une page (WebFetch) passe toujours par une carte.
WEB_LECTURE = ["WebSearch"]

# --- Ce qui est refusé d'office à tout agent (`interdits`) ---------------------------------------
# Claude Code compare une règle Bash au texte de la commande, morceau par morceau d'une chaîne,
# espaces répétées ramenées à une seule et casse comprise : `Bash(x:*)` vaut pour `x` et `x ...`,
# une étoile ailleurs pour n'importe quelle suite de caractères, et une étoile seule en fin après
# une espace (`Bash(x *)`) pour `x` aussi. Avant de comparer, il retire les variables posées
# devant, les lanceurs (`env`, `xargs`, `timeout`...) et les redirections, dont il juge la cible
# par les règles Read et Edit. Un refus passe avant toute permission, toute règle retenue et le
# guichet. Ce n'est qu'une barrière sur le texte : voir LISEZMOI, « Les autorisations ».

# Git : tout est refusé, sauf une courte liste de lectures. Un refus ne connaît pas d'exception :
# la liste des commandes de git doit donc être entière. C'est celle de git 2.43
# (`git --list-cmds=builtins,main,others`), plus les commandes plus récentes et les extensions
# connues ; un test la compare au git installé. Une commande ajoutée par un programme `git-xxx`
# du PATH est refusée elle aussi (`_externes_git`).
LECTURES_GIT = (
    "status", "diff", "log", "show", "blame", "ls-files", "rev-parse", "cat-file", "grep",
    "shortlog", "describe", "merge-base", "ls-tree", "rev-list", "name-rev", "for-each-ref",
    "show-ref", "diff-tree", "diff-files", "diff-index", "check-ignore", "count-objects",
    "whatchanged", "help", "version", "var",
)  # fmt: skip
# Ces deux commandes lisent ou écrivent selon leurs mots : voir `_gestes_git`.
LECTURES_RESTREINTES = ("branch", "remote")
COMMANDES_GIT = (
    "add", "am", "annotate", "apply", "archimport", "archive", "backfill", "bisect", "blame",
    "branch", "bugreport", "bundle", "cat-file", "check-attr", "check-ignore", "check-mailmap",
    "check-ref-format", "checkout", "checkout--worker", "checkout-index", "cherry", "cherry-pick",
    "citool", "clean", "clone", "column", "commit", "commit-graph", "commit-tree", "config",
    "count-objects", "credential", "credential-cache", "credential-cache--daemon",
    "credential-store", "cvsexportcommit", "cvsimport", "cvsserver", "daemon", "describe",
    "diagnose", "diff", "diff-files", "diff-index", "diff-tree", "difftool", "difftool--helper",
    "fast-export", "fast-import", "fetch", "fetch-pack", "filter-branch", "fmt-merge-msg",
    "for-each-ref", "for-each-repo", "format-patch", "fsck", "fsck-objects", "fsmonitor--daemon",
    "gc", "get-tar-commit-id", "gitk", "gitweb", "grep", "gui", "hash-object", "help", "hook",
    "http-backend",
    "http-fetch", "http-push", "imap-send", "index-pack", "init", "init-db", "instaweb",
    "interpret-trailers", "last-modified", "log", "ls-files", "ls-remote", "ls-tree", "mailinfo",
    "mailsplit", "maintenance", "merge", "merge-base", "merge-file", "merge-index",
    "merge-octopus", "merge-one-file", "merge-ours", "merge-recursive", "merge-recursive-ours",
    "merge-recursive-theirs", "merge-resolve", "merge-subtree", "merge-tree", "mergetool",
    "mktag", "mktree", "multi-pack-index", "mv", "name-rev", "notes", "p4", "pack-objects",
    "pack-redundant", "pack-refs", "patch-id", "pickaxe", "prune", "prune-packed", "pull", "push",
    "quiltimport", "range-diff", "read-tree", "rebase", "receive-pack", "reflog", "refs",
    "remote", "remote-ext", "remote-fd", "remote-ftp", "remote-ftps", "remote-http",
    "remote-https", "repack", "replace", "replay", "repo", "request-pull", "rerere", "reset",
    "restore", "rev-list", "rev-parse", "revert", "rm", "scalar", "send-email", "send-pack",
    "sh-i18n", "sh-i18n--envsubst", "sh-setup", "shell", "shortlog", "show", "show-branch",
    "show-index", "show-ref",
    "sparse-checkout", "stage", "stash", "status", "stripspace", "submodule", "submodule--helper",
    "subtree", "svn", "switch", "symbolic-ref", "tag", "unpack-file", "unpack-objects",
    "update-index", "update-ref", "update-server-info", "upload-archive",
    "upload-archive--writer", "upload-pack", "var", "verify-commit", "verify-pack", "verify-tag",
    "version", "web--browse", "whatchanged", "worktree", "write-tree",
)  # fmt: skip
# Des extensions répandues, installées à part (`git lfs`, `git flow`...).
EXTENSIONS_GIT = (
    "lfs", "flow", "filter-repo", "clang-format", "absorb", "crypt", "secret", "annex",
    "credential-manager", "credential-osxkeychain", "credential-libsecret", "credential-wincred",
    "extras", "delete-branch", "undo", "sync", "town", "machete", "spice", "branchless",
)  # fmt: skip
# `git remote` : seuls les sous-gestes qui écrivent sont refusés, même après une option
# (`git remote -v set-url ...`) ; git n'en connaît pas d'autres. `git remote -v` reste.
SOUS_GESTES_REMOTE = (
    "add", "set-url", "remove", "rm", "rename", "set-head", "set-branches", "prune", "update",
)  # fmt: skip
# Ce qu'une lecture sait faire d'autre qu'afficher : écrire un fichier (`--output`, abrégé comme
# git l'accepte), lancer un programme (`git grep -O`, `--open-files-in-pager`, `git help --web`).
OPTIONS_QUI_ECRIVENT = {lecture: ("--out",) for lecture in LECTURES_GIT}
OPTIONS_QUI_ECRIVENT |= {"grep": ("--out", "-O", "--op"), "help": ("--out", "-w")}
# Le programme git sous un autre nom : toute autre casse (Mac et Windows ne la distinguent pas),
# un chemin, `git.exe`. Aucune lecture n'est permise sous ces noms : tout y est refusé.
CASSES_DE_GIT = tuple(
    "".join(c.upper() if (rang >> i) & 1 else c for i, c in enumerate("git")) for rang in range(8)
)
FORMES_DE_GIT = ("*/{}", "*\\{}", "{}.exe", "*/{}.exe", "*\\{}.exe")
NOM_DE_COMMANDE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.+-]*")
SUFFIXE_DE_PROGRAMME = re.compile(r"\.(exe|cmd|bat|sh|py)$", re.IGNORECASE)


def _gestes_git() -> list[str]:
    """Les règles qui refusent git sauf ses lectures, sous toutes les formes décrites plus haut."""
    regles = ["Bash(git -*)"]  # une option avant le geste : -C, -c, --git-dir, --no-pager...
    permises = (*LECTURES_GIT, *LECTURES_RESTREINTES)
    refusees = [c for c in dict.fromkeys(COMMANDES_GIT + EXTENSIONS_GIT) if c not in permises]
    regles += [f"Bash(git {commande} *)" for commande in refusees]
    # `git branch` suivi de quoi que ce soit : `**` exige au moins une espace après le mot.
    regles.append("Bash(git branch **)")
    for geste in SOUS_GESTES_REMOTE:
        regles += [f"Bash(git remote {geste} *)", f"Bash(git remote * {geste})"]
        regles.append(f"Bash(git remote * {geste} *)")
    for lecture, options in OPTIONS_QUI_ECRIVENT.items():
        regles += [f"Bash(git {lecture} *{option}*)" for option in options]
    regles += [f"Bash({nom} *)" for nom in CASSES_DE_GIT if nom != "git"]
    regles += [f"Bash({forme.format(nom)} *)" for nom in CASSES_DE_GIT for forme in FORMES_DE_GIT]
    return regles


GIT_ECRITURE = _gestes_git()


@functools.lru_cache(maxsize=8)
def _externes_git(chemins: str) -> tuple[str, ...]:
    """Les commandes que des programmes `git-xxx` des dossiers `chemins` (le PATH) ajoutent à
    git, hors de ses lectures : elles sont refusées comme les autres (`git xxx`)."""
    noms = set()
    for dossier in filter(None, chemins.split(os.pathsep)):
        with suppress(OSError):
            for entree in os.listdir(dossier):
                nom = SUFFIXE_DE_PROGRAMME.sub("", entree[4:])
                if entree[:4].lower() == "git-" and NOM_DE_COMMANDE.fullmatch(nom):
                    noms.add(nom)
    return tuple(sorted(noms - set(LECTURES_GIT) - set(LECTURES_RESTREINTES)))


# Les fichiers de secrets : ni lus ni écrits par les outils de fichiers, ni nommés dans une
# commande. Un nom vaut partout sur le disque (la copie de travail et le dossier du projet, à
# côté), comme fichier et comme dossier. La clé `secrets` du profil en ajoute (`_secrets`).
# `credentials` et `secrets` ne sont fermés que comme données (sans extension, ou avec une
# extension de données) : `CredentialsForm.tsx` ou `src/secrets.py` restent du code ouvert.
EXTENSIONS_DE_DONNEES = (
    "json", "yml", "yaml", "toml", "ini", "env", "txt", "csv", "xml", "cfg", "conf", "properties",
)  # fmt: skip
SECRETS = (
    ".env", ".env.*", "*.pem", "*.key", "*.p12", "*.pfx", "id_rsa*", "id_ed25519*", "id_ecdsa*",
    "id_dsa*",
    *(f"{nom}{suite}" for nom in ("credentials", "secrets")
      for suite in ("", *(f".{e}" for e in EXTENSIONS_DE_DONNEES))),
    ".credentials*", ".secrets*", ".git-credentials", ".netrc", ".npmrc", ".pypirc", ".ssh",
    ".aws", ".gnupg",
)  # fmt: skip
SECRETS_DE_LA_MACHINE = (
    "~/.ssh/**", "~/.aws/**", "~/.gnupg/**", "~/.config/gh/**", "~/.claude/.credentials.json",
    "~/.git-credentials", "~/.netrc", "~/.npmrc", "~/.pypirc",
)  # fmt: skip
# `.env.*` reste fermé sauf ces quatre modèles, ouverts aux outils de fichiers. Un refus ne
# connaissant pas d'exception, le reste est fermé par son complément (`_env_sauf_modeles`).
MODELES_ENV = ("example", "sample", "template", "dist")
# Les bornes possibles d'un intervalle `[a-b]` : la bibliothèque de motifs de Claude Code
# (`ignore`) protège `\ $ . | * + ( ) { ^` d'une barre inverse, et `/ [ ] , -` y ont un sens.
BORNES_SURES = set(string.ascii_letters + string.digits + "!\"#%&':;<=>@_`~")
DERNIER_CARACTERE = 0xFFFD
# Un motif de secret lisible : des lettres, des chiffres, `_ . - + ~ /` et l'étoile, sans espace
# ni virgule ni parenthèse, qui casseraient une règle.
MOTIF_DE_SECRET = re.compile(r"[A-Za-z0-9_.*~/+-]+")
# Ce qui peut précéder un nom de secret dans une commande : `cat .env`, `a/.env`, `".env"`,
# `--fichier=.env`, `HEAD:.env`, `@.env`. Le nom doit commencer là : `os.environ` ne nomme pas
# `.env`. Une redirection (`> .env`) est jugée par Claude Code sur les règles Edit.
BORDS_DE_NOM = (" ", "/", "\\", '"', "'", "=", ":", "@")
# Un nom fait de lettres seules (`credentials`, `id_rsa`) est aussi un mot courant du code : il
# n'est refusé que suivi d'une barre, d'un guillemet ou de rien (`credentials`, `secrets/`,
# `"credentials"`), pour que `grep -rn credentials app/` reste permis.
MOT_SEUL = re.compile(r"[A-Za-z0-9_-]+")
FINS_DE_MOT = ("", "/*", '"*', "'*")


def _secrets(profil) -> list[str]:
    """Les motifs de secrets : la liste d'origine, puis ceux de la clé `secrets` du profil.

    Une valeur mal formée est ignorée sans erreur : pas une liste, un élément qui n'est pas une
    chaîne, une chaîne vide, un motif hors de `MOTIF_DE_SECRET`, sans lettre ni chiffre (`**`) ou
    qui remonte (`../x`). La liste d'origine reste toujours.
    """
    en_plus = profil.get("secrets") if isinstance(profil, dict) else None
    lus = [m.strip() for m in en_plus if isinstance(m, str)] if isinstance(en_plus, list) else []
    valides = [m for m in lus if MOTIF_DE_SECRET.fullmatch(m) and re.search(r"[A-Za-z0-9]", m)]
    valides = [m for m in valides if ".." not in m.split("/")]
    return list(dict.fromkeys([*SECRETS, *SECRETS_DE_LA_MACHINE, *valides]))


def _classe_sauf(exclus: set[str]) -> str:
    """Une classe `[...]` de tout caractère d'un nom de fichier, sauf `exclus` dans leurs deux
    casses (Claude Code compare les chemins sans la casse). Faite d'intervalles dont les bornes
    sont sûres : un caractère douteux en bord d'intervalle reste hors de la classe."""
    exclus = {c for x in exclus for c in (x.lower(), x.upper())} | set("/\\[]")
    coupures = sorted({0x20, DERNIER_CARACTERE + 1} | {ord(c) for c in exclus})
    morceaux = []
    for avant, apres in zip(coupures, coupures[1:], strict=False):
        debut, fin = avant + 1, apres - 1
        while debut <= fin and not _borne_sure(debut):
            debut += 1
        while fin >= debut and not _borne_sure(fin):
            fin -= 1
        if debut <= fin:
            morceaux.append(chr(debut) if debut == fin else f"{chr(debut)}-{chr(fin)}")
    if morceaux and morceaux[0].startswith("!"):  # `[!` se lirait comme une négation
        morceaux.append(morceaux.pop(0))
    point = "" if "." in exclus else "."  # seul, le point reste sûr : il ferme `.env.e.x`
    return "[" + point + "".join(morceaux) + "]"


def _borne_sure(point: int) -> bool:
    return chr(point) in BORNES_SURES or (point >= 0xA0 and not 0xD800 <= point <= 0xDFFF)


def _env_sauf_modeles(base: str) -> list[str]:
    """Les motifs qui ferment `.env.*` sauf les quatre modèles (`MODELES_ENV`) : pour chaque
    début d'un modèle, ce début suivi d'un caractère qui ne prolonge aucun modèle, ce début seul,
    et un modèle suivi de quoi que ce soit (`.env.example.local`)."""
    debuts = sorted({m[:i] for m in MODELES_ENV for i in range(len(m))})
    motifs = []
    for debut in debuts:
        suites = {m[len(debut)] for m in MODELES_ENV if m.startswith(debut)}
        motifs.append(f"{base}.env.{debut}{_classe_sauf(suites)}*")
        if debut:
            motifs.append(f"{base}.env.{debut}")
    return motifs + [f"{base}.env.{modele}?*" for modele in MODELES_ENV]


def _fichiers_secrets(motif: str) -> list[str]:
    """Les règles Read et Edit qui ferment un secret aux outils de fichiers.

    `Read(...)` vaut pour Read, Grep et Glob ; `Edit(...)` pour Edit, Write et NotebookEdit. Un
    motif ancré (`~/`, `//`) est gardé ; `/x` devient `//x`, Claude Code lisant sinon `/x` à
    partir du fichier de réglages ; un nom vaut partout (`//**/`), lui et ce qu'il contient.
    """
    if motif == ".env.*":
        chemins = _env_sauf_modeles("//**/")
    else:
        if motif.startswith(("~/", "//")):
            chemin = motif
        elif motif.startswith("/"):
            chemin = "/" + motif
        else:
            chemin = "//**/" + re.sub(r"^(\./|\*\*/)+", "", motif)
        chemins = [chemin] if chemin.endswith("/**") else [chemin, chemin + "/**"]
    return [f"{outil}({c})" for outil in ("Read", "Edit") for c in chemins]


def _coeur(motif: str) -> str:
    """Le nom qu'une commande écrirait pour ce motif : sans `~/`, `//`, `./`, `**/` devant, ni
    `/**` derrière. `~/.ssh/**` donne `.ssh`."""
    coeur = re.sub(r"^(~/|/+|\./|\*\*/)+", "", motif)
    return re.sub(r"(/\*+|/)+$", "", coeur)


def _commandes_secretes(motif: str) -> list[str]:
    """Les règles Bash qui refusent une commande nommant ce secret, en minuscules et en
    majuscules (`.ENV` : Mac et Windows ne distinguent pas la casse). `.env` y est refusé sous
    toutes ses formes, modèles compris : un modèle se lit par l'outil de lecture."""
    coeur, regles = _coeur(motif), []
    for forme in dict.fromkeys((coeur, coeur.upper())):
        if forme.startswith("*") and "*" not in forme[1:] and "/" not in forme:  # `*.pem`
            fin = forme[1:]
            regles += [f"Bash(*{fin})"] + [f"Bash(*{fin}{s}*)" for s in (" ", '"', "'")]
        elif forme.startswith("*"):  # une étoile au milieu : le motif tel quel, n'importe où
            regles.append(f"Bash({forme}*)")
        else:
            nom = forme.rstrip("*")
            mot = MOT_SEUL.fullmatch(nom) and not forme.endswith("*")
            fins = FINS_DE_MOT if mot else ("*",)
            regles += [f"Bash(*{bord}{nom}{fin})" for bord in BORDS_DE_NOM for fin in fins]
    return regles


def interdits(profil: dict | None = None) -> list[str]:
    """Tout ce qui est refusé d'office à un agent, quel qu'il soit, sous forme de règles Claude
    Code : lire ou écrire un fichier de secrets avec les outils de fichiers, nommer un secret
    dans une commande, et toute commande git hors de ses lectures (`GIT_ECRITURE`, plus les
    commandes `git-xxx` du PATH).

    Les secrets sont la liste d'origine (`SECRETS`, `SECRETS_DE_LA_MACHINE`) et la clé `secrets`
    du profil, une liste de motifs (`"secrets": ["*.sqlite", "config/prod.yaml"]`) ; une valeur
    mal formée est ignorée. Le pont les donne à Claude Code comme refus (`permissions.deny`), qui
    l'emportent sur toute permission, sur une règle « Toujours » et sur le guichet.
    """
    motifs = _secrets(profil)
    regles = [r for m in motifs for r in _fichiers_secrets(m)]
    regles += [r for m in motifs for r in _commandes_secretes(m)]
    regles += GIT_ECRITURE
    regles += [f"Bash(git {nom} *)" for nom in _externes_git(os.environ.get("PATH", ""))]
    return list(dict.fromkeys(regles))


# Les cinq modes que la personne responsable peut choisir pour les ouvriers. Le mode
# « bypassPermissions » n'en fait pas partie : il n'est accepté nulle part.
MODES_OUVRIERS = ("default", "acceptEdits", "plan", "dontAsk", "auto")
MODE_PAR_DEFAUT = "acceptEdits"
# Ce que l'agent simulé joue en mode auto : un refus de l'arbitre, et la demande d'après la pause.
REFUS_SIMULE = "Lance curl https://example.com (règle Data Exfiltration)"
DEMANDE_PAUSE = {"command": "curl https://example.com"}
PAUSE_REFUS = 3  # refus de suite après lesquels l'arbitre du vrai Claude Code se met en pause

RAISONS_SIMULEES = {
    "bacle": "Un critère de la consigne a été négligé.",
    "ne_sait_pas": "Le calcul est faux sur un cas de référence.",
    "consigne": "Les critères ne suffisent pas à prouver le but.",
}
DEMANDE_SIMULEE = {"command": "npm install left-pad"}
# Deux erreurs à part, que l'appelant reconnaît à leur texte exact (`resultat.erreur == ...`).
LIMITE_ATTEINTE = "L'agent a été refusé : une limite de l'abonnement Claude est atteinte."
REPRISE_IMPOSSIBLE = "La session de la tentative précédente ne peut pas être reprise."
# Une troisième : le serveur de Claude limite les requêtes un moment, sans que la limite de
# l'abonnement soit atteinte (Claude Code le marque pourtant « rate_limit »). Une courte pause.
SURCHARGE = "L'agent a été refusé : Claude est surchargé pour un moment (pas une limite atteinte)."
LIMITE_INCONNUE = "inconnue"  # le type d'une limite que le SDK ne nomme pas
REFUSES_MAX = 20  # outils refusés retenus dans un résultat (`Resultat.refuses`)
OBJET_MAX = 120  # longueur de l'objet d'un outil dans sa forme courte (« Bash(uv sync) »)
# Ce que l'agent simulé joue, dans `limites`, en refusant aussitôt l'appel.
REFUS_DE_LIMITE = ("refus", "surcharge")
# Une forme courte : le nom de l'outil et son objet entre parenthèses.
FORME_COURTE = re.compile(r"[^()]+\((.+)\)", re.DOTALL)
ESPACES = re.compile(r"[ \t]+")  # Claude Code ramène ces suites à une espace pour comparer
# Les commandes dont Claude Code (2.1.308, sa table `BP`) vérifie les chemins : un argument hors
# du dossier de travail y fait demander, malgré une règle qui permet la commande.
CHEMINS_VERIFIES = frozenset(
    "cd ls find mkdir touch rm rmdir mv cp cat head tail sort uniq wc cut paste column tr file "
    "stat diff awk gawk mawk nawk strings hexdump od base64 nl tac man rev fold expand unexpand "
    "fmt comm cmp pr numfmt tsort grep egrep fgrep rg sed git jq sha256sum sha1sum md5sum tee"
    .split()
)
# Une redirection : `2>`, `&>`, `>>`, `<`…, un `&` s'il vise un descripteur, puis sa cible.
REDIRECTION_LUE = re.compile(r"(\d*|&)(>>|>|<)(&?)[ \t]*([^\s;&|<>]*)")
DESCRIPTEUR = re.compile(r"\d+|-")
SUR_DANS_LA_COPIE = re.compile(r"[\w.@+-][\w./@+-]*", re.ASCII)  # relatif, sans guillemet ni joker
REMONTE = re.compile(r"(^|/)\.\.(/|$)")
TILDE = re.compile(r"(^|[\s=:'\"])~")  # un `~` que le shell remplacerait par le dossier personnel
# Les fenêtres de l'abonnement que nomme le SDK (`RateLimitType`), dites en clair.
LIMITES_LUES = {
    "five_hour": "fenêtre de 5 heures",
    "seven_day": "fenêtre de 7 jours",
    "seven_day_opus": "fenêtre de 7 jours d'Opus",
    "seven_day_sonnet": "fenêtre de 7 jours de Sonnet",
    "overage": "dépassement payant",
}
CHOIX_LUS = {
    "une_fois": "autorisé une fois",
    "toujours": "autorisé pour ce projet",
    "chantier": "autorisé pour ce chantier",
    "non": "refusé",
}


@dataclass
class Resultat:
    """Ce qu'un agent rend : son texte, son coût, et s'il a pu aller au bout."""

    ok: bool
    texte: str = ""
    cout_usd: float = 0.0
    tokens: int = 0
    erreur: str = ""
    fichiers: list[str] | None = None
    # Pour un refus pour limite (`erreur == LIMITE_ATTEINTE`) : la limite, comme le SDK la nomme
    # (« five_hour »…, ou « inconnue »), et l'heure où elle se lève (secondes Unix), si connue.
    type_limite: str = ""
    fin_limite: float | None = None
    # L'identifiant de la session Claude Code de l'agent, "" s'il est inconnu : de quoi la
    # reprendre. Hors comparaison : deux résultats égaux le restent, quelle que soit la session.
    session: str = field(default="", compare=False)
    # Les outils refusés pendant le tour, sous leur forme courte (« Bash(uv sync) ») : sans
    # doublon, dans l'ordre, REFUSES_MAX au plus. Hors comparaison, comme `session`.
    refuses: list[str] = field(default_factory=list, compare=False)
    # Vrai quand l'agent est resté ouvert après avoir rendu la main : la suite (un contrôle
    # rouge, un manque relevé) peut lui être donnée tout de suite. Hors comparaison.
    ouverte: bool = field(default=False, compare=False)
    # Pourquoi l'agent a échoué, en un mot : « arret », « delai », « limite », « surcharge »,
    # « reprise », « connexion », « budget » ou « panne » ; vide sans échec ou si inconnu.
    nature: str = field(default="", compare=False)
    # Vrai quand le coût rendu est incomplet (agent coupé avant son message de fin).
    cout_incomplet: bool = field(default=False, compare=False)


def decrire_limite(statut: str, type_limite: str, fin=None, utilisation=None) -> str:
    """Dit en une phrase une limite de l'abonnement : proche (« alerte ») ou atteinte.

    `fin` est l'heure de remise à zéro (secondes Unix), `utilisation` la part consommée (0 à 1).
    """
    nom = LIMITES_LUES.get(type_limite, f"limite {type_limite or LIMITE_INCONNUE}")
    etat = "proche" if statut == "alerte" else "atteinte"
    phrase = f"Limite de l'abonnement {etat} ({nom}"
    if isinstance(utilisation, (int, float)) and not isinstance(utilisation, bool):
        phrase += f", {round(utilisation * 100)} % consommés"
    phrase += ")"
    if isinstance(fin, (int, float)) and not isinstance(fin, bool):
        phrase += " ; remise à zéro à " + time.strftime("%H:%M", time.localtime(fin))
    return phrase + "."


def mode_valide(mode) -> bool:
    """Dit si `mode` est l'un des cinq modes permis aux ouvriers (jamais bypassPermissions)."""
    return isinstance(mode, str) and mode in MODES_OUVRIERS


def lire_mode(valeur) -> str:
    """Le mode des ouvriers lu dans un profil : l'un des cinq, sinon « acceptEdits »."""
    return valeur if mode_valide(valeur) else MODE_PAR_DEFAUT


def _poste(contexte: dict | None) -> tuple[str | None, str]:
    """Rend la tâche d'un appel (None sans tâche) et le nom de l'agent, comme « B-ouvrier-1 »."""
    contexte = contexte or {}
    tache = contexte.get("tache")
    if not tache:
        return None, "orchestrateur"
    role, tentative = contexte.get("role", "ouvrier"), contexte.get("tentative", 1)
    return str(tache), f"{tache}-{role}-{tentative}"


def _emettre(rappel, agent: str, type_: str, contenu: str, **en_plus) -> None:
    """Relaie un événement en direct ; une erreur du rappel ne touche pas l'agent."""
    if rappel is not None:
        with suppress(Exception):
            rappel({"agent": agent, "type": type_, "contenu": contenu, **en_plus})


def _fin(resultat: Resultat) -> str:
    return "L'agent a terminé." if resultat.ok else resultat.erreur


def _ecrit(regle: str) -> bool:
    """Dit si une règle simple porte sur un outil d'écriture, avec ou sans parenthèses."""
    return regle.split("(", 1)[0].lower() in {o.lower() for o in ECRITURE}


def _regles_simples(regles) -> list[str]:
    """Les règles simples d'une liste, sans les espaces autour ; tout le reste est écarté."""
    if not isinstance(regles, (list, tuple)):
        return []
    lues = [r.strip() for r in regles if isinstance(r, str)]
    return [r for r in lues if REGLE_SIMPLE.fullmatch(r)]


def _regles_d_avance(profil: dict, lecture_seule: bool) -> list[str]:
    """Les outils permis d'avance à un agent : lecture, commandes du profil, socle, et l'écriture
    si elle est permise. Les règles retenues (`autorisations`, chantier) n'y sont pas."""
    commandes = [f"Bash({c}:*)" for c in profil.get("commandes_permises", [])]
    outils = OUTILS_LECTURE + commandes + COMMANDES_DEV + GIT_LECTURE + LECTURE_SHELL
    outils += WEB_LECTURE
    return outils if lecture_seule else outils + OUTILS_ECRITURE


def commande_permise(profil: dict, commande: str) -> bool:
    """Dit si un ouvrier pourrait lancer cette commande sans rien demander.

    Les règles sont celles qu'un ouvrier reçoit d'avance (`_regles_d_avance` : le socle et les
    commandes permises du profil) et celles retenues dans le profil (`autorisations`) ; celles
    du chantier en cours n'y sont pas, elles s'effacent avec lui. Elles sont lues comme Claude
    Code les lit : `Bash(uv:*)` permet `uv` et `uv ...`, `Bash(uv sync)` cette seule commande,
    `Bash` toute commande. Chaque commande d'une chaîne (&&, ||, ;, |, &) doit être permise.

    Faux aussi pour ce que Claude Code fait demander malgré une règle : une variable (`$`), un
    `~` en début de mot, une redirection hors de la copie (seules passent `/dev/null`, un
    descripteur comme `2>&1`, une lecture `< fichier` dans la copie, et une écriture `> fichier`
    dans la copie quand le mode des ouvriers du profil est « acceptEdits »), et, pour les
    commandes dont il vérifie les chemins (`CHEMINS_VERIFIES` : cat, ls, grep, git…), un
    argument absolu ou qui remonte par `..`. Faux enfin pour une commande vide ou mal formée,
    une substitution, un caractère de contrôle, et tout ce que les règles ne couvrent pas (un
    `cd`, une variable posée devant).
    """
    if not isinstance(commande, str) or not commande.strip() or SUBSTITUTION.search(commande):
        return False
    profil = profil if isinstance(profil, dict) else {}
    ecrit = lire_mode(profil.get("mode_ouvriers")) == "acceptEdits"
    sans_redirection = _sans_redirections(commande, ecrit)
    if sans_redirection is None or "$" in commande or TILDE.search(commande):
        return False
    permises = profil.get("commandes_permises", [])
    lisibles = isinstance(permises, (list, tuple))
    permises = [c for c in permises if isinstance(c, str)] if lisibles else []
    regles = _regles_d_avance({"commandes_permises": permises}, lecture_seule=False)
    regles += _regles_simples(profil.get("autorisations"))
    morceaux = [ESPACES.sub(" ", m).strip() for m in CHAINE.split(sans_redirection)]
    return all(m and _dans_la_copie(m) and any(_couvre(r, m) for r in regles) for m in morceaux)


def _sans_redirections(commande: str, ecrit: bool) -> str | None:
    """La commande sans ses redirections, ou None si l'une d'elles ferait demander.

    Passent : un descripteur vers un autre (`2>&1`, `>&2`), `/dev/null`, une lecture `< fichier`
    dans la copie, et une écriture `> fichier` (ou `>>`, `&>`) dans la copie si `ecrit` (le mode
    « acceptEdits ») ; tout le reste, dont `<<` et `<<<`, fait demander.
    """
    for trouve in REDIRECTION_LUE.finditer(commande):
        _, sens, descripteur, cible = trouve.groups()
        if descripteur:
            permise = DESCRIPTEUR.fullmatch(cible) is not None
        else:
            dans_la_copie = (sens == "<" or ecrit) and _chemin_dans_la_copie(cible)
            permise = cible == "/dev/null" or dans_la_copie
        if not permise:
            return None
    return REDIRECTION_LUE.sub(" ", commande)


def _chemin_dans_la_copie(chemin: str) -> bool:
    """Un chemin relatif fait de caractères sûrs, qui ne remonte pas par `..`."""
    return SUR_DANS_LA_COPIE.fullmatch(chemin) is not None and not REMONTE.search(chemin)


def _dans_la_copie(morceau: str) -> bool:
    """Pour une commande dont Claude Code vérifie les chemins, aucun argument n'en sort : ni
    absolu ni remontant par `..`, même comme valeur d'option (`--x=/y`). Les autres passent."""
    mots = morceau.split()
    if not mots or mots[0].rsplit("/", 1)[-1] not in CHEMINS_VERIFIES:
        return True
    for mot in (m.strip("'\"") for m in mots[1:]):
        valeur = mot.split("=", 1)[1] if mot.startswith("-") and "=" in mot else mot
        if valeur.lstrip("'\"").startswith("/") or REMONTE.search(valeur):
            return False
    return True


def _couvre(regle: str, commande: str) -> bool:
    """Dit si une règle couvre une commande simple, comme Claude Code compare les règles Bash."""
    nom, parenthese, reste = regle.partition("(")
    if nom != "Bash":
        return False
    if not parenthese:
        return True  # « Bash » seul permet toute commande
    contenu = ESPACES.sub(" ", reste.removesuffix(")"))
    if contenu.endswith(":*"):
        prefixe = contenu.removesuffix(":*")
        return bool(prefixe) and (commande == prefixe or commande.startswith(prefixe + " "))
    return "*" not in contenu and commande == contenu


class _Marche:
    """Un agent en marche : son nom, et le drapeau que pose une demande d'arrêt.

    Pour un ouvrier, `mode` est le mode choisi : posé à l'inscription, puis à chaque changement de
    mode ; seul l'agent simulé le relit (la session du pont reçoit le mode par `changer_mode`).
    `change` est le drapeau que pose chaque changement de mode ; seul l'agent simulé l'attend.
    `session` est la session du pont de l'agent réel (None pour l'agent simulé) : `appliques` lui
    demande le mode appliqué. Pour l'agent simulé seulement, `joue` est le dernier mode joué, afin
    de ne jouer qu'une fois chaque changement, et `applique` le mode que `appliques` rend, qui
    peut retomber à « default ».
    """

    def __init__(self, nom: str, couper=None, session=None, ouvrier: bool = False):
        self.nom, self.couper = nom, couper
        self.session, self.ouvrier = session, ouvrier
        self.arret = threading.Event()  # posé par `arreter`
        self.reveil = threading.Event()  # posé par `arreter` ou par la réponse du guichet
        self.change = threading.Event()  # posé par un changement de mode
        self.fin_emise = False
        self.mode = self.applique = self.joue = ""


class _Postes:
    """Les agents en marche, rangés par tâche (None : l'orchestrateur), et le mode des ouvriers.

    Le même verrou protège les deux : un ouvrier qui démarre pendant un changement de mode est
    soit inscrit avant (le changement le touche), soit après (il lit le nouveau mode).
    """

    def __init__(self, mode: str = MODE_PAR_DEFAUT):
        self._verrou = threading.Lock()
        self._marches: dict[str | None, _Marche] = {}
        self.mode = lire_mode(mode)

    @contextmanager
    def occuper(self, tache: str | None, nom: str, couper=None, session=None, ouvrier=False):
        """Inscrit l'agent pour la durée de son travail : un arrêt peut alors le viser.

        Un ouvrier reçoit sous le verrou le mode choisi ; sa session le prendra à la connexion.
        """
        marche = _Marche(nom, couper, session, ouvrier)
        with self._verrou:
            if ouvrier:
                marche.mode = marche.applique = self.mode
                if session is not None:
                    session.changer_mode(self.mode)  # ne bloque pas : rien n'est encore connecté
            self._marches[tache] = marche
        try:
            yield marche
        finally:
            with self._verrou:
                if self._marches.get(tache) is marche:
                    del self._marches[tache]

    def arreter(self, tache: str | None) -> bool:
        with self._verrou:
            marche = self._marches.get(tache)
            if marche is None:
                return False
            marche.arret.set()
            marche.reveil.set()
        if marche.couper is not None:
            marche.couper()
        return True

    def changer_mode(self, mode: str) -> int:
        """Retient le mode des ouvriers et le passe à ceux en marche ; rend le nombre touché.

        Rien de lent sous le verrou : `SessionSDK.changer_mode` confie l'appel à la boucle de
        la session et rend aussitôt. Les autres agents ne sont jamais touchés.
        """
        with self._verrou:
            self.mode, touches = mode, 0
            for marche in self._marches.values():
                if marche.ouvrier:
                    marche.mode = mode
                    marche.change.set()
                    session = marche.session
                    touches += session is None or bool(session.changer_mode(mode))
        return touches

    def appliques(self) -> dict[str, str]:
        """Le mode réellement appliqué à chaque ouvrier en marche, quand il est connu."""
        with self._verrou:
            ouvriers = [m for m in self._marches.values() if m.ouvrier]
        lus = {m.nom: m.session.mode_applique if m.session else m.applique for m in ouvriers}
        return {nom: mode for nom, mode in lus.items() if mode}


class _ModeDesOuvriers:
    """Ce que les deux agents offrent pour le mode des ouvriers ; il leur faut `_postes`."""

    @property
    def mode_ouvriers(self) -> str:
        return self._postes.mode

    def changer_mode(self, mode) -> int:
        """Choisit le mode des ouvriers ; l'applique tout de suite à ceux en marche.

        Rend le nombre d'ouvriers en marche touchés. Le vérificateur et la conversation ne le
        sont jamais. Lève ValueError pour un mode inconnu ou « bypassPermissions ».
        """
        if not mode_valide(mode):
            raise ValueError(f"Mode des ouvriers refusé : {mode!r}.")
        return self._postes.changer_mode(mode)

    def modes_appliques(self) -> dict[str, str]:
        """Pour chaque ouvrier en marche, le mode réellement appliqué, quand il est connu."""
        return self._postes.appliques()


# Les ouvriers gardés ouverts en même temps, par défaut (`ouverts_max` du profil). La référence
# n'a pas de plafond : six, comme les places du régulateur.
OUVERTS_MAX = 6
# `liberer` rend la main au plus tard après ce délai ; la déconnexion finit alors derrière.
DELAI_LIBERER_S = 5.0
# Borne de `liberer_tous`, qui attend la fin de toutes les fermetures : celle du pont attend au
# plus ~95 s (tour en cours 30 s, déconnexions 35 s, fil de la boucle 30 s).
DELAI_FERMETURES_S = 100.0


def lire_garde(profil) -> tuple[bool, int]:
    """Lit au profil `ouvrier_ouvert` (vrai par défaut) et `ouverts_max` (OUVERTS_MAX).

    Aide pour le moteur, qui décide de passer `garder_ouvert=True` à `executer` : l'agent ne lit
    jamais `ouvrier_ouvert`, seulement `ouverts_max`. Seul un booléen compte pour le premier,
    seul un entier positif ou nul pour le second ; toute autre valeur vaut la valeur par défaut.
    `ouverts_max: 0` ne garde aucun ouvrier ouvert.
    """
    profil = profil if isinstance(profil, dict) else {}
    garder = profil.get("ouvrier_ouvert", True)
    maxi = profil.get("ouverts_max", OUVERTS_MAX)
    lisible = isinstance(maxi, int) and not isinstance(maxi, bool) and maxi >= 0
    return garder if isinstance(garder, bool) else True, maxi if lisible else OUVERTS_MAX


class _Ouvert:
    """Un ouvrier qui peut rester ouvert après son tour : sa session, fermée une seule fois.

    `fermeture` ferme la session (celle du pont, ou la note de l'agent simulé). `gardable` : le
    tour peut finir ouvert. `liberee`, posé par `liberer` pendant un tour, le fait fermer à la
    fin de ce tour au lieu de le garder. `mode` : pour l'agent simulé, le mode des ouvriers.
    """

    def __init__(self, session, fermeture, gardable: bool = False, mode: str = ""):
        self.session, self._fermeture = session, fermeture
        self.gardable, self.mode, self.liberee = gardable, mode, False
        self._une_fois, self.fermee = threading.Lock(), threading.Event()

    @property
    def fermant(self) -> bool:
        """Vrai dès que la fermeture a commencé, par un appel ou par le fil d'arrêt."""
        return self._une_fois.locked()

    def fermer(self) -> None:  # une seule fois, par l'appel, `liberer` ou le fil d'arrêt
        if self._une_fois.acquire(blocking=False):
            try:
                self._fermeture()
            finally:
                self.fermee.set()

    def fermer_et_attendre(self) -> None:
        """Ferme, ou attend la fermeture lancée ailleurs (un arrêt) : rien n'en sort vivant."""
        self.fermer()
        self.fermee.wait()


def _fermer_sans_lever(ouvert: _Ouvert) -> None:
    with suppress(Exception):
        ouvert.fermer_et_attendre()


class _OuvriersOuverts:
    """Ce que les deux agents offrent pour l'ouvrier gardé ouvert après avoir rendu la main.

    Un ouvrier n'est gardé que si l'appel le demande (`executer(..., garder_ouvert=True)`) :
    celui qui le demande le libère. Il faut aux agents `_gardes` (tâche -> ouvrier ouvert qui
    attend la suite), `_en_tour` (tâche -> ouvrier gardable en plein tour), `_fermetures` (les
    ouvriers en train de fermer), `_verrou_ouverts` et `_plafond()`. Seul un ouvrier attaché à
    une tâche est gardé ; un ouvrier qui attend ne tient aucun poste : `arreter` le ferme aussi.
    """

    delai_liberer_s = DELAI_LIBERER_S

    def liberer(self, tache) -> None:
        """Ferme l'ouvrier gardé ouvert pour cette tâche, s'il y en a un. Ne lève jamais.

        Rend la main dès la déconnexion faite, et au plus tard après `delai_liberer_s` (5 s) :
        une déconnexion plus lente finit dans un fil à part, que `liberer_tous` attend. Un
        ouvrier de la tâche en plein tour n'est pas interrompu (c'est le rôle d'`arreter`) : il
        sera fermé à la fin de son tour, qui rend `ouverte` faux. Sans effet pour une tâche
        inconnue, ou appelé une seconde fois.
        """
        with suppress(Exception):
            ouvert = self._retirer_ouvert(tache)
            if ouvert is not None:
                self._fermer_a_part(ouvert).wait(self.delai_liberer_s)

    def liberer_tous(self) -> None:
        """Ferme tous les ouvriers gardés ouverts, ensemble, et attend la fin de toutes les
        fermetures, celles lancées avant par `liberer` ou `arreter` comprises (DELAI_FERMETURES_S
        au plus). Ne lève jamais. Ceux en plein tour sont fermés à la fin de leur tour.
        """
        with suppress(Exception):
            with self._verrou_ouverts:
                ouverts = list(self._gardes.values())
                self._gardes.clear()
                for en_tour in self._en_tour.values():
                    en_tour.liberee = True
            for ouvert in ouverts:
                self._fermer_a_part(ouvert)
            with self._verrou_ouverts:
                en_cours = list(self._fermetures)
            limite = time.monotonic() + DELAI_FERMETURES_S
            for ouvert in en_cours:
                ouvert.fermee.wait(max(0.0, limite - time.monotonic()))

    def _fermer_a_part(self, ouvert: _Ouvert) -> threading.Event:
        """Lance la fermeture dans un fil à part, notée dans `_fermetures` jusqu'à sa fin ; rend
        l'événement posé quand elle est finie."""
        with self._verrou_ouverts:
            self._fermetures.add(ouvert)

        def fermer():
            try:
                _fermer_sans_lever(ouvert)
            finally:
                with self._verrou_ouverts:
                    self._fermetures.discard(ouvert)

        threading.Thread(target=fermer, daemon=True, name="atelier-liberer").start()
        return ouvert.fermee

    def _retirer_ouvert(self, tache) -> _Ouvert | None:
        """Retire l'ouvrier ouvert de la tâche (à fermer par l'appelant), et marque celui qui
        est en plein tour pour qu'il soit fermé à la fin de ce tour."""
        cle = str(tache) if tache else None
        with self._verrou_ouverts:
            en_tour = self._en_tour.get(cle)
            if en_tour is not None:
                en_tour.liberee = True
            return self._gardes.pop(cle, None)

    def _fermer_l_ancien(self, tache) -> None:
        """Avant un nouvel ouvrier de la tâche : ferme l'ancien resté ouvert et attend sa
        déconnexion (bornée par celle du pont), pour que deux ne travaillent jamais ensemble."""
        ouvert = self._retirer_ouvert(tache)
        if ouvert is not None:
            _fermer_sans_lever(ouvert)

    def _fermer_en_attente(self, tache) -> None:
        """Pour `arreter` : ferme dans un fil à part l'ouvrier ouvert qui attend, sans bloquer."""
        with suppress(Exception):
            ouvert = self._retirer_ouvert(tache)
            if ouvert is not None:
                self._fermer_a_part(ouvert)

    def _inscrire_en_tour(self, tache: str, ouvert: _Ouvert) -> None:
        with self._verrou_ouverts:
            self._en_tour[tache] = ouvert

    def _prendre_ouvert(self, tache: str, convient) -> _Ouvert | None:
        """L'ouvrier ouvert de la tâche, s'il convient à la suite (`convient(ouvert)`, appelé
        sous le verrou) : il passe alors en plein tour. Sinon None, et il reste où il est."""
        with self._verrou_ouverts:
            ouvert = self._gardes.get(tache)
            if ouvert is None or not convient(ouvert):
                return None
            del self._gardes[tache]
            self._en_tour[tache] = ouvert
            return ouvert

    def _ranger(self, tache, ouvert: _Ouvert, reussi: bool) -> bool:
        """À la fin d'un tour : garde l'ouvrier ouvert, ou le ferme et attend la déconnexion.

        Gardé seulement s'il est gardable (l'appel l'a demandé), après un tour réussi, sans
        arrêt ni `liberer`, et sous le plafond. Rend vrai s'il est gardé.
        """
        maxi = self._plafond()
        with self._verrou_ouverts:
            if self._en_tour.get(tache) is ouvert:
                del self._en_tour[tache]
            garde = ouvert.gardable and reussi and not ouvert.liberee and not ouvert.fermant
            garde = garde and tache not in self._gardes and len(self._gardes) < maxi
            if garde:
                self._gardes[tache] = ouvert
        if not garde:
            ouvert.fermer_et_attendre()
        return garde


def _sans_reprise(rappel, nom: str) -> Resultat:
    """Une reprise demandée d'une session vide : l'erreur à part, sans lancer d'agent."""
    resultat = Resultat(ok=False, erreur=REPRISE_IMPOSSIBLE)
    _emettre(rappel, nom, "fin", _fin(resultat))
    return resultat


def _empecher(resultat: Resultat, outils: tuple[str, ...]) -> Resultat:
    """Le résultat d'un ouvrier simulé empêché : outils refusés, une ligne « EMPÊCHÉ » chacun.

    Un arrêt reste un arrêt : il ne porte rien de plus.
    """
    if not outils or resultat.erreur == ARRETE:
        return resultat
    resultat.refuses = list(outils)
    lignes = [
        f"EMPÊCHÉ : {_objet_de_forme(o)} — l'outil a été refusé : je ne peux pas aller plus loin."
        for o in outils
    ]
    resultat.texte = "\n".join([resultat.texte, *lignes] if resultat.texte else lignes)
    return resultat


def _objet_de_forme(forme: str) -> str:
    """L'objet d'une forme courte (« uv sync » pour « Bash(uv sync) »), ou la forme entière."""
    trouve = FORME_COURTE.fullmatch(forme)
    return trouve[1] if trouve else forme


def _arrete(marche: _Marche, resultat: Resultat) -> Resultat:
    """Un arrêt demandé pendant le travail l'emporte sur ce que l'agent a rendu.

    Le résultat d'arrêt garde ce que le travail a coûté (coût, tokens, coût incomplet) ; sa
    nature est « arret », celle que le pont donne déjà à un tour arrêté.
    """
    if not marche.arret.is_set():
        return resultat
    return Resultat(ok=False, erreur=ARRETE, cout_usd=resultat.cout_usd, tokens=resultat.tokens,
                    nature="arret", cout_incomplet=resultat.cout_incomplet)  # fmt: skip


class AgentClaude(_ModeDesOuvriers, _OuvriersOuverts):
    """Fait travailler Claude Code par l'Agent SDK, avec le modèle et l'effort demandés.

    Chaque appel ouvre sa propre session du pont (`atelier.sdk`) et la ferme en partant, sauf
    l'ouvrier d'une tâche lancé avec `garder_ouvert=True` qui rend la main sans erreur ni arrêt :
    il reste connecté (`resultat.ouverte`) jusqu'à `liberer`, et `executer(reprendre=session)`
    lui donne la suite dans la même conversation.
    Un outil qui n'est ni permis ni interdit passe par le guichet, s'il y en a un.
    """

    # Le moteur ne demande `garder_ouvert` qu'à un agent qui le dit (voir `Moteur._garde`), et
    # ne lui donne un plafond de dépense (`budget_usd`) que s'il dit savoir le tenir.
    garde_les_ouvriers = True
    plafonne_la_depense = True


    def __init__(self, profil: dict | None = None, delai_max_s: int = 3600, fabrique_client=None):
        self.profil = profil or {}
        self.delai_max_s = delai_max_s
        self.fabrique_client = fabrique_client  # un faux client SDK, pour les tests
        self.guichet = None
        self.sur_evenement = None
        self.source_connexion = ""
        # Rend les règles retenues pour le chantier en cours ; le serveur la branche sur son état.
        self.regles_chantier = list
        self._postes = _Postes(lire_mode(self.profil.get("mode_ouvriers")))
        # Les ouvriers gardés ouverts (`_OuvriersOuverts`) : qui attend la suite, qui travaille.
        self._gardes: dict[str, _Ouvert] = {}
        self._en_tour: dict[str, _Ouvert] = {}
        self._fermetures: set[_Ouvert] = set()
        self._verrou_ouverts = threading.Lock()

    def _plafond(self) -> int:
        return lire_garde(self.profil)[1]

    def _outils(self, lecture_seule: bool) -> list[str]:
        """Rend la liste des outils permis : lecture, commandes du projet, écriture si permise."""
        return _regles_d_avance(self.profil, lecture_seule)

    def _autorisations(self, lecture_seule: bool) -> list[str]:
        """Les règles simples retenues, du profil puis du chantier en cours, sans doublon.

        En lecture seule, sans celles qui écrivent. Une erreur en lisant celles du chantier
        n'en donne aucune : l'outil repassera par le guichet.
        """
        try:
            du_chantier = self.regles_chantier()
        except Exception:
            du_chantier = []
        regles = _regles_simples(self.profil.get("autorisations"))
        regles += [r for r in _regles_simples(du_chantier) if r not in regles]
        return [r for r in regles if not (lecture_seule and _ecrit(r))]

    def _alias(self, modele: str) -> str:
        return self.profil.get("alias_modeles", {}).get(modele, modele)

    def executer(
        self,
        consigne: str,
        modele: str,
        effort: str,
        dossier: Path | None,
        lecture_seule: bool = False,
        contexte: dict | None = None,
        copie_jetable: bool = False,
        reprendre: str | None = None,
        garder_ouvert: bool = False,
        budget_usd: float | None = None,
    ) -> Resultat:
        """Exécute une consigne et rend le résultat de l'agent.

        `copie_jetable` : le vérificateur travaille dans une copie du livrable que l'atelier
        jette après son avis. Il peut y écrire sans carte (ses essais : un fichier modifié pour
        voir un test échouer, un script), puisque rien de ce qu'il y fait n'est enregistré ; il
        n'a toujours aucun accès en écriture à la copie de l'ouvrier, ni aux modes des ouvriers.

        `reprendre` : l'identifiant d'une session rendue par un appel précédent (`session` du
        résultat). L'agent repart dans cette session, et la consigne lui arrive comme un message
        de plus ; `dossier` doit être celui de cette session. Si elle ne peut pas être reprise,
        le résultat a pour erreur `REPRISE_IMPOSSIBLE`, et rien d'autre n'est tenté ; une
        session vide ("") la rend aussi, sans lancer d'agent. Sans `reprendre` (None), la
        session est neuve, comme toujours.

        `garder_ouvert` : un ouvrier de tâche rendu sans erreur ni arrêt reste connecté après
        l'appel (`resultat.ouverte`), sous le plafond `ouverts_max` du profil, jusqu'à `liberer`.
        L'appelant qui le demande le libère. Sans lui (par défaut), la connexion est fermée quand
        l'agent rend la main, comme toujours. Le vérificateur et l'orchestrateur ne restent
        jamais ouverts.

        L'ouvrier gardé ouvert : si celui de la tâche est encore connecté sur la session
        `reprendre`, avec les mêmes réglages (modèle, effort, dossier, outils, mode des ouvriers,
        refus d'office), la consigne lui part dans la même conversation, sans rien rouvrir ; il
        reste ouvert ensuite ou se ferme selon `garder_ouvert` de cet appel. Sinon, tout nouvel
        ouvrier de la tâche le ferme d'abord (en attendant sa déconnexion), et la reprise se
        fait par la session, comme ci-dessus.
        """
        tache, nom = _poste(contexte)
        bac_a_sable = lecture_seule and copie_jetable
        ecrit = not lecture_seule or bac_a_sable
        if bac_a_sable:
            mode = "acceptEdits"
        else:  # le mode d'un ouvrier est relu sous le verrou des postes, à son inscription
            mode = "default" if lecture_seule else self._postes.mode
        reprise = {}
        if reprendre is not None:  # une session qu'on ne peut pas reprendre rend une erreur à part
            if not isinstance(reprendre, str) or not reprendre.strip():  # session vide : rien
                return _sans_reprise(self.sur_evenement, nom)  # n'est lancé à la place
            reprise = {"session": reprendre, "reprise": True, "reprise_exigee": True}
        reglages = {
            "modele": self._alias(modele), "effort": effort, "dossier": dossier,
            "outils_permis": self._outils(not ecrit) + self._autorisations(not ecrit),
            "outils_interdits": [] if ecrit else list(ECRITURE), "mode_permission": mode,
        }  # fmt: skip
        de_tache = not lecture_seule and tache is not None
        if de_tache:
            ouvert = self._ouvert_pour(tache, reprendre, reglages)
            if ouvert is not None:  # la suite, dans la même conversation
                ouvert.gardable = bool(garder_ouvert)
                resultat = self._tour(tache, nom, ouvert, consigne, ouvrier=True)
                if not getattr(ouvert.session, "suite_perdue", False):
                    return resultat
                # Le programme resté ouvert n'était plus là : `_tour` l'a fermé, et la suite
                # part par la reprise de session, comme s'il n'y avait pas eu d'ouvrier ouvert.
            self._fermer_l_ancien(tache)  # jamais deux ouvriers pour une même tâche
        garder = de_tache and bool(garder_ouvert)
        # Le plafond de dépense n'entre pas dans les réglages comparés pour servir une suite : il
        # change à chaque appel, et celui d'un ouvrier resté ouvert date de sa connexion.
        return self._travailler(
            tache, nom, consigne, ouvrier=not lecture_seule, garder=garder,
            budget_usd=budget_usd, **reglages, **reprise,
        )  # fmt: skip

    def _ouvert_pour(self, tache: str, reprendre, reglages: dict) -> _Ouvert | None:
        """L'ouvrier ouvert de la tâche, s'il est sur la session `reprendre` et que rien de ses
        réglages n'a changé depuis sa connexion (ni ses droits, ni le mode) ; sinon None."""
        if reprendre is None:
            return None
        refus = interdits(self.profil)

        def convient(ouvert: _Ouvert) -> bool:
            session = ouvert.session
            memes = all(getattr(session, cle, None) == valeur for cle, valeur in reglages.items())
            return session.session == reprendre and memes and session.refus_d_office == refus

        return self._prendre_ouvert(tache, convient)

    def converser(
        self,
        message: str,
        session: str,
        reprise: bool,
        dossier: Path | None,
        sur_texte=None,
        sur_outil=None,
        contexte: dict | None = None,
    ) -> Resultat:
        """Envoie un message à la session Claude Code de l'orchestrateur et suit sa réponse.

        La session est gardée d'un message à l'autre : la première fois on lui donne son
        identifiant (un UUID), ensuite on la reprend. Elle lit le dépôt mais n'écrit rien.
        """
        return self._travailler(
            None, "orchestrateur", message, sur_texte, sur_outil,
            modele=self._alias("fable"), effort="high", dossier=dossier,
            # En conversation : lecture seule, sans les commandes permises d'office aux ouvriers ;
            # mais les règles que la personne a retenues (« Toujours pour ce projet ») valent aussi
            # ici, sauf celles qui écrivent : sinon la même carte reviendrait à chaque message.
            outils_permis=OUTILS_LECTURE + GIT_LECTURE + LECTURE_SHELL + WEB_LECTURE
            + self._autorisations(lecture_seule=True),
            outils_interdits=list(ECRITURE),
            mode_permission="default", role_ajoute=ROLE_ORCHESTRATEUR,
            session=session, reprise=reprise,
        )  # fmt: skip

    def arreter(self, tache: str | None = None) -> bool:
        """Arrête l'agent en marche pour cette tâche, ou sans tâche l'orchestrateur qui répond.

        Rend True si un agent était en marche ; son appel rend alors l'arrêt. Ne bloque pas :
        la session est fermée dans un fil à part (`fermer` n'oublie pas un arrêt arrivé avant le
        tour), et c'est l'appel arrêté qui attend la fin de cette fermeture avant de rendre.
        Un ouvrier de la tâche gardé ouvert, qui attend la suite, est fermé lui aussi, dans un
        fil à part ; il ne compte pas comme agent en marche.
        """
        en_marche = self._postes.arreter(tache or None)
        if tache:
            self._fermer_en_attente(tache)
        return en_marche

    def _travailler(
        self, tache, nom, consigne, sur_texte=None, sur_outil=None, ouvrier=False, garder=False,
        **reglages,
    ):  # fmt: skip
        """Ouvre une session du pont, lui confie la consigne et rend le résultat.

        Tout lancement passe par ici, et chacun reçoit les interdits du profil (`interdits`),
        quel que soit le rôle de l'agent. Quand l'appel rend la main, la session est fermée et
        son client déconnecté, même après un arrêt : l'appel suivant ne croise jamais un Claude
        Code encore en train de sortir. Seule exception, `garder` (un ouvrier de tâche) : rendu
        sans erreur ni arrêt, sous le plafond, il reste ouvert jusqu'à `liberer`.
        """
        from atelier.sdk import SessionSDK

        session = SessionSDK(
            nom, guichet=self.guichet, delai_max_s=self.delai_max_s,
            fabrique_client=self.fabrique_client, refus_d_office=interdits(self.profil),
            **reglages,
        )  # fmt: skip
        ouvert = _Ouvert(session, session.fermer, gardable=garder)
        if garder:
            self._inscrire_en_tour(tache, ouvert)
        return self._tour(tache, nom, ouvert, consigne, ouvrier, sur_texte, sur_outil)

    def _tour(self, tache, nom, ouvert: _Ouvert, consigne, ouvrier, sur_texte=None,
              sur_outil=None) -> Resultat:  # fmt: skip
        """Un tour de la session d'`ouvert` : neuve, ou gardée ouverte depuis le tour d'avant.

        Un tour qui ne peut pas rester ouvert ferme la session avant le retrait du poste ; un
        tour gardable la garde ou la ferme ensuite (`_ranger`), et le résultat le dit.
        """
        session, resultat = ouvert.session, None

        def couper():
            threading.Thread(target=ouvert.fermer, daemon=True, name=f"atelier-arret-{nom}").start()

        with self._postes.occuper(tache, nom, couper, session, ouvrier) as marche:
            session.sur_evenement = self._relais(marche, session, sur_texte, sur_outil)
            try:
                resultat = session.envoyer(consigne)
            finally:
                if not (ouvert.gardable and resultat is not None and resultat.ok):
                    ouvert.fermer_et_attendre()  # celle lancée par un arrêt est attendue aussi
        resultat = _arrete(marche, resultat)  # après le retrait du poste : aucune fenêtre
        resultat.ouverte = self._ranger(tache, ouvert, resultat.ok)
        perdue = resultat.erreur == REPRISE_IMPOSSIBLE  # la session demandée n'est pas la sienne
        resultat.session = "" if perdue else session.session or ""
        self.source_connexion = session.source_connexion or self.source_connexion
        if not marche.fin_emise:  # le pont n'a pas commencé de tour : arrêté avant
            _emettre(self.sur_evenement, nom, "fin", _fin(resultat))
        return resultat

    def _relais(self, marche: _Marche, session, sur_texte, sur_outil):
        """Le rappel donné au pont : il sert le serveur et les rappels de la conversation."""
        general, cibles = self.sur_evenement, {"texte": sur_texte, "outil": sur_outil}

        def relayer(evenement: dict) -> None:
            marche.fin_emise = marche.fin_emise or evenement["type"] == "fin"
            self.source_connexion = session.source_connexion or self.source_connexion
            rappel = cibles.get(evenement["type"])
            if rappel is not None:
                with suppress(Exception):
                    rappel(evenement["contenu"])
            if general is not None:
                general(evenement)

        return relayer


GESTES = {
    "Read": ("Lit", "file_path"),
    "Grep": ("Cherche", "pattern"),
    "Glob": ("Parcourt", "pattern"),
    "Edit": ("Modifie", "file_path"),
    "MultiEdit": ("Modifie", "file_path"),
    "Write": ("Écrit", "file_path"),
    "NotebookEdit": ("Modifie", "notebook_path"),
    "WebFetch": ("Lit la page", "url"),
    "WebSearch": ("Cherche sur le web", "query"),
    "Task": ("Confie à un sous-agent :", "description"),
    "Agent": ("Confie à un sous-agent :", "description"),
    "ToolSearch": ("Cherche un outil", "query"),
}
GESTES |= {"Bash": ("Lance", "command"), "Skill": ("Utilise le skill", "skill")}
CHEMINS = ("file_path", "notebook_path", "path")


def decrire_outil(bloc: dict, racine=None) -> str:
    """Dit en quelques mots ce que Claude Code est en train de faire.

    Un chemin dans la copie de travail (`racine`) est écrit à partir d'elle : « Modifie
    calcul.py » plutôt que tout le chemin. Une commande accompagnée de sa description (Claude
    Code en donne une, en clair) commence par elle.
    """
    verbe, cle = GESTES.get(bloc.get("name", ""), (bloc.get("name", "Outil"), ""))
    objet = _objet(bloc, racine)
    if cle == "command":
        description = " ".join(str(_entree(bloc).get("description") or "").split())
        if description:
            return f"{description} — {objet}".strip(" —")[:120]
    return f"{verbe} {objet}".strip()[:120]


def forme_courte(bloc: dict, racine=None) -> str:
    """Un outil appelé, sous la forme « Bash(uv sync) », « Edit(calcul.py) », ou son seul nom.

    L'objet est celui que montre `decrire_outil` (la commande sur une ligne, sans sa
    description ; un chemin à partir de `racine`), coupé au-delà de OBJET_MAX caractères.
    """
    nom = bloc.get("name")
    nom = " ".join(nom.split()) if isinstance(nom, str) else ""
    objet = _objet(bloc, racine)
    if len(objet) > OBJET_MAX:
        objet = objet[: OBJET_MAX - 1] + "…"
    return f"{nom or 'Outil'}({objet})" if objet else nom or "Outil"


def _entree(bloc: dict) -> dict:
    entree = bloc.get("input") or {}
    return entree if isinstance(entree, dict) else {}


def _objet(bloc: dict, racine=None) -> str:
    """Sur quoi porte un outil : sa commande sur une ligne, son chemin (à partir de `racine`)…"""
    nom = bloc.get("name", "")
    entree, cle = _entree(bloc), GESTES.get(nom, ("", ""))[1] if isinstance(nom, str) else ""
    if cle == "command":
        return str(entree.get("command", "")).replace("\n", " ; ").strip()
    objet = " ".join(str(entree.get(cle, "")).split())
    if cle in CHEMINS and racine and objet:
        prefixe = str(racine).rstrip("/") + "/"
        objet = objet[len(prefixe):] if objet.startswith(prefixe) else objet
    return objet


# Ce que les agents simulés font en patientant (démonstration), et l'écart entre deux gestes.
GESTES_SIMULES = (
    "Lit le périmètre", "Cherche les appels", "Lit les tests", "Écrit le code", "Écrit le code",
    "Lance les contrôles", "Relit le changement", "Écrit les tests", "Lance les tests",
)
ETAPES_SIMULEES = ("lire le périmètre", "écrire le code", "écrire les tests", "relire")
RYTHME_GESTES = (0.4, 0.3, 1.6, 0.5, 0.2, 0.3, 2.2, 0.6, 0.4, 1.1, 0.3, 0.8)


@dataclass
class AgentSimule(_ModeDesOuvriers, _OuvriersOuverts):
    """Joue un scénario écrit d'avance : pour la démonstration et les tests.

    Le scénario donne, pour chaque tâche, l'issue de chaque tentative :
    "ok", "bacle", "ne_sait_pas", "consigne", "deborde" ou "erreur".
    Si un guichet lui est attaché, le premier ouvrier lancé y dépose une demande
    d'autorisation d'exemple et attend la réponse avant de poursuivre.

    Les ouvriers suivent le mode choisi, même en marche. En mode auto, le premier ouvrier
    joue un refus de l'arbitre ; avec `pause_arbitre`, trois refus puis une demande au guichet
    (l'arbitre en pause) ; avec `retombee`, l'ouvrier retombe ensuite en mode « default ».

    Avec `gestes_s` (la démonstration), un agent qui patiente joue un geste de travail toutes les
    `gestes_s` secondes environ, pour que la courbe d'activité du tableau de bord vive.

    Les limites de l'abonnement, sur demande : `limites` donne, par tâche (« orchestrateur » pour
    un appel sans tâche), ce que jouent ses appels successifs à `executer`, tous rôles confondus :
    "refus" (refusé pour limite, aussitôt, sans rien écrire), "alerte" (un événement « limite »
    d'alerte, puis le travail prévu), "surcharge" (refusé aussitôt, Claude étant surchargé :
    l'erreur `SURCHARGE`, sans événement « limite », comme le pont), ou "" (rien de spécial).
    Au-delà de la liste, rien. La limite jouée est `type_limite`, levée `delai_limite_s` secondes
    plus tard (None : heure inconnue).

    Les ouvriers empêchés, sur demande : `empeches` donne, par tâche, ce que jouent ses ouvriers
    successifs (le vérificateur n'y touche pas) : un outil refusé sous sa forme courte (comme
    « Bash(uv sync) »), une liste de tels outils, ou "" (rien). L'ouvrier empêché suit son
    scénario, mais son résultat porte ces outils dans `refuses`, et son compte rendu une ligne
    « EMPÊCHÉ : uv sync — ... » par outil. Au-delà de la liste, rien.

    La reprise : chaque appel rend une session (`resultat.session`). `executer(...,
    reprendre=session)` repart dans une session déjà rendue, la note dans `reprises` et rend la
    même session ; une session inconnue, ou oubliée par `oublier_sessions`, rend
    `REPRISE_IMPOSSIBLE`. Par défaut, rien de tout cela ne change ce qu'il joue.

    L'ouvrier gardé ouvert, sur demande de l'appel (`executer(..., garder_ouvert=True)`) : le
    même contrat que l'agent réel. L'ouvrier d'une tâche rendu sans erreur ni arrêt reste
    ouvert (`ouverte`), sous `ouverts_max` ; `executer(..., reprendre=session)` sur lui, le
    mode des ouvriers inchangé, lui donne la suite dans la même session (notée dans `suivis`,
    pas dans `reprises`), en `delai_s` secondes, arrêtable, avec son événement « fin », puis le
    garde ou le ferme selon `garder_ouvert` de cet appel. Ce que joue chaque suite d'une tâche
    est donné par `suites` : "rien" (réussie, sans rien écrire), "erreur" (en échec, et
    l'ouvrier est fermé), ou "" (réussie : les fichiers du périmètre sont réécrits). Sinon, tout
    nouvel ouvrier de la tâche le ferme d'abord, et la reprise suit la règle ci-dessus.
    `liberer` et `liberer_tous` le ferment ; chaque session qui a pu rester ouverte est notée
    une fois dans `fermes` à sa fermeture. Sans `garder_ouvert`, rien ne change.
    """

    scenario: dict[str, list[str]] = field(default_factory=dict)
    delai_s: float = 0.0
    perimetres: dict[str, list[str]] = field(default_factory=dict)
    plan: dict | None = None
    appels: list[dict] = field(default_factory=list)
    guichet: object = None
    sur_evenement: object = None
    source_connexion: str = ""
    retombee: bool = False
    pause_arbitre: bool = False
    gestes_s: float = 0.0
    limites: dict[str, list[str]] = field(default_factory=dict)
    type_limite: str = "five_hour"
    delai_limite_s: float | None = 3600.0
    reprises: list[dict] = field(default_factory=list)
    empeches: dict[str, list] = field(default_factory=dict)
    suites: dict[str, list[str]] = field(default_factory=dict)
    ouverts_max: int = OUVERTS_MAX
    # Faux sans réglage : le moteur ne lui demande alors jamais de garder un ouvrier ouvert, et
    # la démonstration se déroule comme avant (voir `Moteur._garde`).
    garde_les_ouvriers: bool = False
    suivis: list[dict] = field(default_factory=list)
    fermes: list[str] = field(default_factory=list)
    _gardes: dict = field(default_factory=dict, init=False, repr=False, compare=False)
    _en_tour: dict = field(default_factory=dict, init=False, repr=False, compare=False)
    _fermetures: set = field(default_factory=set, init=False, repr=False, compare=False)
    _verrou_ouverts: object = field(
        default_factory=threading.Lock, init=False, repr=False, compare=False
    )
    _postes: _Postes = field(default_factory=_Postes, init=False, repr=False, compare=False)
    _demandes: list[str] = field(default_factory=list, init=False, repr=False, compare=False)
    _refus: list[str] = field(default_factory=list, init=False, repr=False, compare=False)
    _verrou: object = field(default_factory=threading.Lock, init=False, repr=False, compare=False)
    _joues: dict = field(default_factory=dict, init=False, repr=False, compare=False)
    _sessions: set = field(default_factory=set, init=False, repr=False, compare=False)
    _ouvertes: int = field(default=0, init=False, repr=False, compare=False)

    def _issue(self, contexte: dict) -> str:
        issues = self.scenario.get(contexte.get("tache", ""), ["ok"])
        return issues[min(contexte.get("tentative", 1), len(issues)) - 1]

    def _ecrire(self, dossier: Path | None, fichiers: list[str], marque: str) -> None:
        if dossier is None:
            return
        for nom in fichiers:
            chemin = Path(dossier) / nom
            chemin.parent.mkdir(parents=True, exist_ok=True)
            chemin.write_text(f"# {marque}\n", "utf-8")

    def arreter(self, tache: str | None = None) -> bool:
        """Arrête l'agent simulé en marche pour cette tâche, ou l'orchestrateur sans tâche.

        Ferme aussi, à part, l'ouvrier de la tâche gardé ouvert qui attend la suite.
        """
        en_marche = self._postes.arreter(tache or None)
        if tache:
            self._fermer_en_attente(tache)
        return en_marche

    def _plafond(self) -> int:
        return lire_garde({"ouverts_max": self.ouverts_max})[1]

    def _annuler(self, nom: str) -> None:
        if self.guichet is not None:
            with suppress(Exception):
                self.guichet.annuler(nom)

    def executer(
        self,
        consigne: str,
        modele: str,
        effort: str,
        dossier: Path | None,
        lecture_seule: bool = False,
        contexte: dict | None = None,
        copie_jetable: bool = False,
        reprendre: str | None = None,
        garder_ouvert: bool = False,
    ) -> Resultat:
        """Rend le résultat prévu par le scénario pour cette tâche et cette tentative.

        `garder_ouvert` : comme pour l'agent réel. La suite donnée à l'ouvrier ouvert de la
        tâche (`reprendre` sur sa session) est jouée par `_donner_suite`.
        """
        contexte = contexte or {}
        appel = {**contexte, "modele": modele, "effort": effort}
        self.appels.append(appel if reprendre is None else {**appel, "reprise": reprendre})
        tache, nom = _poste(contexte)
        jeu = self._jeu_de_limite(tache)
        ouvrier = contexte.get("role") == "ouvrier"
        de_tache = ouvrier and tache is not None
        if de_tache:
            ouvert = self._ouvert_simule(tache, reprendre)
            if ouvert is not None:
                ouvert.gardable = bool(garder_ouvert)
                return self._donner_suite(ouvert, consigne, contexte, dossier, modele, jeu)
            self._fermer_l_ancien(tache)  # jamais deux ouvriers pour une même tâche
        session = self._ouvrir_session(reprendre, consigne, contexte)
        if session is None or jeu in REFUS_DE_LIMITE:
            return self._refuser(nom, session, jeu)
        empeche = self._empechement(tache) if ouvrier else ()
        ouvert = self._ouvrir_gardable(tache, session) if de_tache and garder_ouvert else None
        with self._postes.occuper(tache, nom, lambda: self._annuler(nom), None, ouvrier) as marche:
            _emettre(self.sur_evenement, nom, "outil", "Lit la consigne")
            if jeu == "alerte":
                self._annoncer_limite(nom, "alerte")
            if ouvrier:
                self._jouer_mode(marche)
            if ouvrier and self._premiere_demande(nom):
                self._demander(marche)
            arrete = self._patienter(marche)
            prevu = Resultat(ok=False) if arrete else self._prevu(contexte, dossier, modele)
        resultat = _empecher(_arrete(marche, prevu), empeche)  # après le retrait du poste
        resultat.session = session
        if ouvert is not None:
            ouvert.mode = marche.mode  # le mode choisi, changements en marche compris
            resultat.ouverte = self._ranger(tache, ouvert, resultat.ok)
        _emettre(self.sur_evenement, nom, "fin", _fin(resultat))
        return resultat

    def _ouvrir_gardable(self, tache: str, session: str) -> _Ouvert:
        """Inscrit en plein tour un ouvrier simulé qui pourra rester ouvert sur `session`."""
        ouvert = _Ouvert(session, lambda: self.fermes.append(session), gardable=True)
        self._inscrire_en_tour(tache, ouvert)
        return ouvert

    def _ouvert_simule(self, tache: str, reprendre) -> _Ouvert | None:
        """L'ouvrier ouvert de la tâche, s'il est sur la session `reprendre` et que le mode des
        ouvriers n'a pas changé depuis son dernier tour ; sinon None."""
        if reprendre is None:
            return None
        mode = self._postes.mode
        return self._prendre_ouvert(tache, lambda o: o.session == reprendre and o.mode == mode)

    def _donner_suite(self, ouvert: _Ouvert, consigne: str, contexte: dict, dossier,
                      modele: str, jeu: str) -> Resultat:  # fmt: skip
        """Joue la suite donnée à l'ouvrier ouvert, dans sa session : ce que dit `suites`."""
        tache, nom = _poste(contexte)
        rang = len(self.suivis) + 1
        champs = {c: contexte.get(c) for c in ("tache", "role", "tentative")}
        self.suivis.append({**champs, "session": ouvert.session, "message": consigne})
        if jeu in REFUS_DE_LIMITE:  # refusé aussitôt : l'ouvrier est fermé
            self._ranger(tache, ouvert, False)
            return self._refuser(nom, ouvert.session, jeu)
        suite = self._suivant(self.suites, "suites", tache)
        with self._postes.occuper(tache, nom, lambda: self._annuler(nom), None, True) as marche:
            _emettre(self.sur_evenement, nom, "outil", "Lit la suite")
            if jeu == "alerte":
                self._annoncer_limite(nom, "alerte")
            self._jouer_mode(marche)
            arrete = self._patienter(marche)
            prevu = Resultat(ok=False) if arrete else self._suite_prevue(suite, tache, dossier,
                                                                           modele, rang)
        resultat = _arrete(marche, prevu)  # après le retrait du poste
        resultat.session = ouvert.session
        ouvert.mode = marche.mode
        resultat.ouverte = self._ranger(tache, ouvert, resultat.ok)
        _emettre(self.sur_evenement, nom, "fin", _fin(resultat))
        return resultat

    def _suite_prevue(self, suite: str, tache: str, dossier, modele: str, rang: int) -> Resultat:
        """Le résultat d'une suite : "erreur" échoue, "rien" n'écrit rien, sinon réécrit."""
        cout = {"haiku": 0.02, "sonnet": 0.09, "opus": 0.35, "fable": 0.80}.get(modele, 0.1)
        if suite == "erreur":
            return Resultat(ok=False, erreur="Arrêt simulé de l'agent.", tokens=500)
        if suite == "rien":
            return Resultat(ok=True, texte="Suite simulée : rien à changer.", cout_usd=cout,
                            tokens=3000, fichiers=[])  # fmt: skip
        fichiers = [f for f in self.perimetres.get(tache, []) if "*" not in f]
        self._ecrire(dossier, fichiers, f"tâche {tache}, suite {rang}")
        return Resultat(ok=True, texte="Suite simulée.", cout_usd=cout, tokens=3000,
                        fichiers=fichiers)  # fmt: skip

    def oublier_sessions(self) -> None:
        """Oublie les sessions rendues : les reprendre rendra désormais `REPRISE_IMPOSSIBLE`."""
        with self._verrou:
            self._sessions.clear()

    def _jeu_de_limite(self, tache: str | None) -> str:
        """Ce que `limites` fait jouer à cet appel : "refus", "surcharge", "alerte" ou ""."""
        return self._suivant(self.limites, "limites", tache or "orchestrateur")

    def _empechement(self, tache: str | None) -> tuple[str, ...]:
        """Les outils que `empeches` fait refuser à cet ouvrier de la tâche ; () pour aucun."""
        jeu = self._suivant(self.empeches, "empeches", tache or "")
        outils = [jeu] if isinstance(jeu, str) else jeu if isinstance(jeu, (list, tuple)) else []
        lus = (o.strip() for o in outils if isinstance(o, str) and o.strip())
        return tuple(dict.fromkeys(lus))[:REFUSES_MAX]

    def _suivant(self, jeux: dict, nom: str, cle: str):
        """L'entrée suivante de `jeux[cle]`, consommée appel après appel ; "" au-delà."""
        with self._verrou:
            rang = self._joues.get((nom, cle), 0)
            self._joues[(nom, cle)] = rang + 1
        suite = jeux.get(cle, [])
        return suite[rang] if rang < len(suite) else ""

    def _ouvrir_session(self, reprendre: str | None, message: str, contexte: dict) -> str | None:
        """La session de l'appel : neuve, ou celle à reprendre ; None si elle est inconnue."""
        with self._verrou:
            if reprendre is None:
                self._ouvertes += 1  # jamais deux fois le même numéro, même après un oubli
                session = f"session-simulee-{self._ouvertes}"
                self._sessions.add(session)
                return session
            if reprendre not in self._sessions:
                return None
        reprise = {c: contexte.get(c) for c in ("tache", "role", "tentative")}
        self.reprises.append({**reprise, "session": reprendre, "message": message})
        return reprendre

    def _refuser(self, nom: str, session: str | None, jeu: str) -> Resultat:
        """Rend aussitôt une reprise impossible, une surcharge ou un refus pour limite."""
        if session is None:
            resultat = Resultat(ok=False, erreur=REPRISE_IMPOSSIBLE)
        elif jeu == "surcharge":  # le pont n'annonce pas de limite : aucune n'est atteinte
            resultat = Resultat(ok=False, erreur=SURCHARGE, session=session)
        else:
            fin = self._annoncer_limite(nom, "atteinte")
            resultat = Resultat(ok=False, erreur=LIMITE_ATTEINTE, type_limite=self.type_limite,
                                fin_limite=fin, session=session)  # fmt: skip
        _emettre(self.sur_evenement, nom, "fin", _fin(resultat))
        return resultat

    def _annoncer_limite(self, nom: str, statut: str) -> float | None:
        """Émet l'événement « limite » qu'émettrait le pont ; rend l'heure de remise à zéro."""
        fin = None if self.delai_limite_s is None else time.time() + self.delai_limite_s
        utilisation = 0.9 if statut == "alerte" else 1.0
        texte = decrire_limite(statut, self.type_limite, fin, utilisation)
        _emettre(self.sur_evenement, nom, "limite", texte, statut=statut,
                 limite=self.type_limite, fin=fin, utilisation=utilisation)  # fmt: skip
        return fin

    def _patienter(self, marche: _Marche) -> bool:
        """Attend le délai de l'agent ; rend True dès un arrêt. Rejoue un changement de mode."""
        debut = time.monotonic()
        limite, geste = debut + self.delai_s, 0
        while not marche.arret.is_set():
            maintenant = time.monotonic()
            reste = limite - maintenant
            if reste <= 0:
                return False
            if self.gestes_s and maintenant - debut >= self._prochain_geste(geste):
                texte = GESTES_SIMULES[geste % len(GESTES_SIMULES)]
                if geste % 3 == 0:  # l'étape annoncée, comme le demande la consigne
                    rang = geste // 3 % len(ETAPES_SIMULEES)
                    etape = f"Étape {rang + 1}/{len(ETAPES_SIMULEES)} : {ETAPES_SIMULEES[rang]}\n"
                    _emettre(self.sur_evenement, marche.nom, "texte", etape)
                _emettre(self.sur_evenement, marche.nom, "outil", texte)
                geste += 1
            if marche.change.wait(min(reste, 0.02)):
                marche.change.clear()
                self._jouer_mode(marche)
        return True

    def _prochain_geste(self, rang: int) -> float:
        """L'instant du geste `rang`, irrégulier mais reproductible : des rafales et des pauses."""
        return sum(self.gestes_s * RYTHME_GESTES[i % len(RYTHME_GESTES)] for i in range(rang + 1))

    def _jouer_mode(self, marche: _Marche) -> None:
        """Joue le mode choisi pour cet ouvrier, une fois par changement de mode."""
        mode = marche.mode
        if mode == marche.joue:
            return
        marche.joue = marche.applique = mode
        if mode != "auto":
            return
        if self._premier_refus(marche.nom):
            for _ in range(PAUSE_REFUS if self.pause_arbitre else 1):
                _emettre(self.sur_evenement, marche.nom, "refus", REFUS_SIMULE)
            if self.pause_arbitre and self.guichet is not None:
                self._demander(marche, DEMANDE_PAUSE)  # l'arbitre en pause : retour au guichet
        if self.retombee:
            marche.applique = "default"
            _emettre(self.sur_evenement, marche.nom, "mode", "default", demande="auto", raison="")

    def _premier_refus(self, nom: str) -> bool:
        """Vrai pour le premier ouvrier qui travaille en mode auto, et lui seul."""
        with self._verrou:
            if self._refus:
                return False
            self._refus.append(nom)
            return True

    def _premiere_demande(self, nom: str) -> bool:
        """Vrai pour le premier ouvrier lancé alors qu'un guichet est attaché, et lui seul."""
        with self._verrou:
            if self.guichet is None or self._demandes:
                return False
            self._demandes.append(nom)
            return True

    def _demander(self, marche: _Marche, entree: dict = DEMANDE_SIMULEE) -> None:
        """Dépose une demande d'exemple au guichet et attend sa réponse, ou un arrêt."""
        guichet, nom, reponses = self.guichet, marche.nom, []
        marche.reveil.clear()  # une demande précédente a pu le laisser posé
        if marche.arret.is_set():
            return
        _emettre(self.sur_evenement, nom, "attente", decrire_outil(_bash(entree)))

        def demander():
            with suppress(Exception):
                reponses.append(guichet.demander(nom, "Bash", dict(entree)))
            marche.reveil.set()

        fil = threading.Thread(target=demander, daemon=True, name=f"atelier-demande-{nom}")
        fil.start()
        marche.reveil.wait()
        if marche.arret.is_set():
            return self._retirer(nom, fil)
        choix = getattr(reponses[0], "choix", "non") if reponses else "non"
        message = getattr(reponses[0], "message", "") if reponses else ""
        texte = f"Réponse de la personne responsable : {CHOIX_LUS.get(choix, 'refusé')}."
        _emettre(self.sur_evenement, nom, "texte", f"{texte} {message}".strip())
        if choix in ("une_fois", "toujours"):
            _emettre(self.sur_evenement, nom, "outil", decrire_outil(_bash(entree)))

    def _retirer(self, nom: str, fil: threading.Thread) -> None:
        """Après un arrêt, ferme aussi une demande déposée après l'annulation (2 s au plus)."""
        limite = time.monotonic() + 2
        while fil.is_alive() and time.monotonic() < limite:
            self._annuler(nom)
            fil.join(0.02)

    def _prevu(self, contexte: dict, dossier: Path | None, modele: str) -> Resultat:
        """Le résultat que le scénario prévoit pour ce rôle, cette tâche et cette tentative."""
        cout = {"haiku": 0.02, "sonnet": 0.09, "opus": 0.35, "fable": 0.80}.get(modele, 0.1)
        if contexte.get("role") == "orchestrateur":
            plan = json.dumps(self.plan or {"taches": []}, ensure_ascii=False)
            return Resultat(ok=True, texte=plan, cout_usd=cout, tokens=6000)
        issue = self._issue(contexte)
        if contexte.get("role") == "verificateur":
            valide = issue not in RAISONS_SIMULEES
            verdict = {
                "valide": valide,
                "motif": issue if issue in ("bacle", "ne_sait_pas", "consigne") else "bacle",
                "resume": "Tous les critères sont remplis." if valide else RAISONS_SIMULEES[issue],
            }
            return Resultat(ok=True, texte=json.dumps(verdict), cout_usd=cout, tokens=4000)
        if issue == "erreur":
            return Resultat(ok=False, erreur="Arrêt simulé de l'agent.", tokens=500)
        fichiers = [f for f in self.perimetres.get(contexte.get("tache", ""), []) if "*" not in f]
        if issue == "deborde":
            fichiers = fichiers + ["hors_perimetre.txt"]
        self._ecrire(dossier, fichiers, f"tâche {contexte.get('tache')}")
        return Resultat(
            ok=True, texte="Compte rendu simulé.", cout_usd=cout, tokens=9000, fichiers=fichiers
        )

    def converser(
        self,
        message: str,
        session: str,
        reprise: bool,
        dossier: Path | None,
        sur_texte=None,
        sur_outil=None,
        contexte: dict | None = None,
    ) -> Resultat:
        """Joue la réponse de l'orchestrateur : un plan si rien n'est lancé, sinon un mot."""
        contexte = contexte or {}
        self.appels.append({"role": "conversation", "session": session, "reprise": reprise})
        if self.plan and not contexte.get("chantier"):
            nombre = len(self.plan.get("taches", []))
            texte = (
                f"J'ai découpé ton objectif en {nombre} tâches. Relis le contrat et "
                "l'onglet Plan, puis valide quand ça te convient : rien ne démarre avant.\n\n"
                f"{BALISE_PLAN}\n{json.dumps(self.plan, ensure_ascii=False)}\n```"
            )
        else:
            texte = "C'est noté. (Réponse simulée : en vrai, Claude Code te répond ici.)"
        with self._postes.occuper(None, "orchestrateur") as marche:
            for mot in texte.split(" "):
                if marche.arret.wait(min(self.delai_s, 1.0) / 25):
                    break
                if sur_texte:
                    sur_texte(mot + " ")
                _emettre(self.sur_evenement, "orchestrateur", "texte", mot + " ")
        resultat = _arrete(marche, Resultat(ok=True, texte=texte, cout_usd=0.8, tokens=6000))
        _emettre(self.sur_evenement, "orchestrateur", "fin", _fin(resultat))
        return resultat


def _bash(entree: dict) -> dict:
    return {"name": "Bash", "input": entree}
