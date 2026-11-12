"""Le guichet des autorisations : un agent y dépose une demande et attend la réponse.

Chaque demande bloque seulement le fil de l'agent qui l'a faite. La personne responsable
voit les demandes ouvertes sur le tableau de bord et répond : une fois, toujours pour ce
projet, toujours pendant ce chantier (quand aucune règle n'est assez étroite pour le projet), ou
non avec une indication. Sans réponse dans le délai, la demande se ferme sur « non ».
"""

import itertools
import json
import re
import secrets
import threading
from dataclasses import dataclass
from urllib.parse import urlsplit

CHOIX = ("une_fois", "toujours", "chantier", "non")
SANS_REPONSE = "Pas de réponse de la personne responsable."
ARRETE = "Arrêté par la personne responsable."
SCENARIO_EPUISE = "Le scénario de démonstration ne prévoit pas cette demande."
LONGUEUR_MAX = 160
DELAI_MAX_S = 24 * 3600
A_LA_LIGNE = " [retour à la ligne] "
DETAIL_MAX = 4000

# Ce qui enchaîne, redirige ou substitue des commandes, et tout caractère de contrôle.
ENCHAINEMENT = re.compile(r"[;&|<>`$()\\\x00-\x1f\x7f]")
# Un mot de commande sans guillemet, sans joker, sans affectation de variable.
MOT_SUR = re.compile(r"[\w./@+-]+", re.ASCII)
# Des commandes qui en lancent d'autres : une règle sur elles autoriserait n'importe quoi.
LANCEURS = {
    "sh", "bash", "rbash", "zsh", "dash", "fish", "ksh", "mksh", "csh", "tcsh", "ash",
    "busybox", "toybox", "pwsh", "powershell", "sudo", "su", "doas", "pkexec", "runuser", "sg",
    "env", "eval", "exec", "command", "builtin", "source", ".", "time", "nice", "ionice",
    "setsid", "stdbuf", "strace", "ltrace", "nohup", "timeout", "watch", "xargs", "parallel",
    "chroot", "unshare", "nsenter", "flock", "script", "ssh", "find", "taskset", "chrt",
    "systemd-run", "setarch", "fakeroot", "proot", "entr", "caffeinate", "xvfb-run", "gtimeout",
    "rlwrap", "unbuffer", "valgrind", "firejail", "gosu", "emacs", "docker", "podman", "nerdctl",
    "npx", "bunx", "uvx", "ts-node", "tsx", "nix-shell", "direnv", "dotenv", "chpst",
}
# Des paires dont le deuxième mot lance une commande quelconque (comparées en minuscules).
PAIRES = {
    ("uv", "run"), ("poetry", "run"), ("pipenv", "run"), ("conda", "run"), ("mamba", "run"),
    ("nix", "run"), ("nix", "shell"), ("nix", "develop"), ("pipx", "run"), ("hatch", "run"),
    ("pdm", "run"), ("rye", "run"), ("npm", "x"), ("pnpm", "dlx"), ("pnpm", "exec"),
    ("yarn", "dlx"), ("yarn", "exec"), ("bun", "x"), ("git", "-c"),
}
# Des interpréteurs : après eux, seul un nom de script (ou -m pour Python) reste étroit.
INTERPRETES = {
    "python", "pypy", "node", "nodejs", "deno", "bun", "perl", "ruby", "irb", "php", "lua",
    "luajit", "rscript", "r", "julia", "tclsh", "wish", "expect", "osascript", "awk", "gawk",
    "mawk", "nawk", "guile", "racket", "jshell", "ghci", "runghc",
}
# Des lanceurs purs : une règle sur leur premier mot permettrait n'importe quelle commande, même
# pour la durée d'un chantier. find et les lanceurs de paquets (npx...) en sont retirés : leur
# règle large reste à la portée d'un clic, la carte la montre avant.
LANCEURS_PURS = LANCEURS - {"find", "npx", "bunx", "uvx", "ts-node", "tsx"}
# Après ces commandes, une règle sur le seul premier mot ouvrirait trop (git -c lance une commande).
JAMAIS_LARGES = {"git"}
# Ce qui substitue une commande ou un fichier dans une autre : aucune règle de chantier n'est sûre.
SUBSTITUTION = re.compile(r"\$\(|`|<\(|>\(|[\x00-\x1f\x7f]")
# Ce qui sépare les commandes d'une chaîne, et les redirections, ignorées pour lire leurs débuts.
CHAINE = re.compile(r"&&|\|\||;|\|&?|&")
REDIRECTION = re.compile(r"\d*(>>?|<)&?\s*[^\s;&|]*")
OPTIONS_LONGUES = {"--eval", "--command", "--exec", "--execute", "--print", "--run"}
LIGNE = re.compile(r"\r\n|\r|\n")
CONTROLE = re.compile(r"[\x00-\x1f\x7f]")
INTERDIT_DANS_URL = re.compile(r"[\\@\s\x00-\x1f\x7f]")
DOMAINE = re.compile(r"([a-z0-9]([a-z0-9-]*[a-z0-9])?\.)+([a-z]{2,63}|xn--[a-z0-9-]+)")
# La machine elle-même ou un réseau interne : la règle ignore le port, elle ouvrirait tout.
SUFFIXES_INTERNES = (".localhost", ".local", ".internal", ".lan", ".home.arpa")
NOM_OUTIL = re.compile(r"[\w-]+", re.ASCII)

GESTES = {
    "Bash": ("lancer la commande", "command"),
    "Write": ("écrire le fichier", "file_path"),
    "Edit": ("modifier le fichier", "file_path"),
    "Read": ("lire le fichier", "file_path"),
    "Grep": ("chercher", "pattern"),
    "Glob": ("parcourir les fichiers", "pattern"),
    "WebSearch": ("chercher sur le web", "query"),
    "Skill": ("utiliser le skill", "skill"),
}
CLES_DETAIL = {"Bash": "command", "WebFetch": "url", "Write": "file_path",
               "Edit": "file_path", "Read": "file_path", "ExitPlanMode": "plan"}
# L'outil par lequel un ouvrier en répétition (mode plan) demande à passer à l'exécution.
FIN_DE_REPETITION = "ExitPlanMode"


@dataclass
class Reponse:
    choix: str
    message: str = ""
    regle: str = ""
    regles: tuple[str, ...] = ()  # les règles d'un « chantier »


def _texte(entree, cle: str) -> str:
    """La valeur de la clé si l'entrée est un dictionnaire et la valeur une chaîne, sinon ""."""
    valeur = entree.get(cle) if isinstance(entree, dict) else None
    return valeur if isinstance(valeur, str) else ""


def _nom(mot: str) -> str:
    """Le nom d'une commande, en minuscules, sans chemin ni version (Python3.12 -> python)."""
    return (mot.rsplit("/", 1)[-1].rstrip("0123456789.") or mot).lower()


def _option_risquee(option: str, commande: str) -> bool:
    """Une option en deuxième mot qui ferait de la règle un passe-partout."""
    if not option.startswith("-"):
        return False
    if _nom(commande) in INTERPRETES:
        return option != "-m"
    if option.startswith("--"):
        return option in OPTIONS_LONGUES
    return bool(set(option[1:]) & {"c", "e"})


def _regle_bash(commande) -> str:
    """Les deux premiers mots d'une commande simple, ou rien dès qu'un doute existe."""
    if not isinstance(commande, str) or ENCHAINEMENT.search(commande):
        return ""
    debut = commande.split()[:2]
    if not debut or not all(MOT_SUR.fullmatch(mot) for mot in debut):
        return ""
    return "" if _debut_risque(debut) else f"Bash({' '.join(debut)}:*)"


def _debut_risque(debut: list[str]) -> bool:
    """Vrai si les deux premiers mots lancent, ou peuvent lancer, une commande quelconque."""
    noms = [_nom(mot) for mot in debut]
    if any(nom in LANCEURS for nom in noms):
        return True
    if len(debut) == 1:
        return noms[0] in INTERPRETES
    if (noms[0], debut[1].lower()) in PAIRES or noms[1] in INTERPRETES:
        return True
    return _option_risquee(debut[1], debut[0])


def _regle_large(mots: list[str]) -> str:
    """La règle sur le seul premier mot d'une commande, ou "" pour un lanceur pur ou un doute."""
    premier = mots[0]
    if not MOT_SUR.fullmatch(premier) or _nom(premier) in LANCEURS_PURS | JAMAIS_LARGES:
        return ""
    return f"Bash({premier}:*)"


def regles_chantier_pour(outil, entree) -> list[str]:
    """Les règles qui couvriraient la demande pendant le chantier, ou [] si aucune n'est sûre.

    Seulement pour une commande que la règle « toujours » ne couvre pas. Chaque commande d'une
    chaîne reçoit sa règle : la plus étroite si elle existe, sinon celle de son premier mot ;
    un « cd » de tête n'en reçoit pas. Une seule commande sans règle possible (un lanceur pur,
    une substitution, un mot douteux) et il n'y en a aucune : la demande reste au cas par cas.
    """
    if outil != "Bash" or regle_pour(outil, entree):
        return []
    commande = _texte(entree, "command")
    if not commande.strip() or SUBSTITUTION.search(commande):
        return []
    regles: list[str] = []
    for morceau in CHAINE.split(REDIRECTION.sub(" ", commande)):
        mots = morceau.split()
        if not mots or (_nom(mots[0]) == "cd" and len(mots) <= 2):
            continue
        regle = _regle_bash(morceau) or _regle_large(mots)
        if not regle:
            return []
        if regle not in regles:
            regles.append(regle)
    return regles


def _domaine(url: str) -> str:
    """Le nom de domaine ordinaire d'une adresse web, ou "" au moindre doute."""
    if INTERDIT_DANS_URL.search(url):
        return ""
    try:
        morceaux = urlsplit(url)
        nom = morceaux.hostname or ""
    except ValueError:
        return ""
    if morceaux.scheme not in ("http", "https"):
        return ""
    if not DOMAINE.fullmatch(nom) or nom.endswith(SUFFIXES_INTERNES):
        return ""
    return nom


def regle_pour(outil, entree) -> str:
    """La règle Claude Code la plus étroite qui couvre la demande, ou "" si aucune n'est sûre."""
    if not isinstance(outil, str) or outil == FIN_DE_REPETITION:
        return ""  # passer à l'exécution se décide à chaque fois, jamais pour de bon
    if outil == "Bash":
        return _regle_bash(_texte(entree, "command"))
    if outil == "WebFetch":
        domaine = _domaine(_texte(entree, "url"))
        return f"WebFetch(domain:{domaine})" if domaine else ""
    return outil if NOM_OUTIL.fullmatch(outil) else ""


def _forme_lisible(outil, entree) -> str:
    cle = CLES_DETAIL.get(outil) if isinstance(outil, str) else None
    if cle and _texte(entree, cle):
        return _texte(entree, cle)
    try:
        return json.dumps(entree, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return repr(entree)


def detail_pour(outil, entree) -> str:
    """Le texte complet de ce qui est demandé, coupé seulement au-delà de DETAIL_MAX caractères."""
    texte = _forme_lisible(outil, entree)
    if len(texte) <= DETAIL_MAX:
        return texte
    return texte[:DETAIL_MAX] + f" [suite coupée : {len(texte) - DETAIL_MAX} caractères de plus]"


def _couper(texte: str) -> str:
    """Met le texte sur une ligne, garde les retours à la ligne visibles, coupe s'il le faut."""
    lignes = [" ".join(ligne.split()) for ligne in LIGNE.split(texte)]
    texte = CONTROLE.sub("?", A_LA_LIGNE.join(ligne for ligne in lignes if ligne))
    if len(texte) <= LONGUEUR_MAX:
        return texte
    coupe = texte[:LONGUEUR_MAX].rsplit(" ", 1)[0] or texte[:LONGUEUR_MAX]
    return coupe + " [...]"


def phrase_pour(agent, outil, entree, regle: str = "", pour_chantier: bool = False) -> str:
    """Dit en une phrase française ce que l'agent veut faire."""
    outil = outil if isinstance(outil, str) else str(outil)
    if outil == FIN_DE_REPETITION:
        return f"{agent} a fini sa répétition et demande à passer à l'exécution de son plan."
    if outil == "WebFetch" and _texte(entree, "url"):
        domaine = _domaine(_texte(entree, "url"))
        if domaine:
            return f"{agent} veut consulter le site {domaine}."
        return f"{agent} veut consulter l'adresse « {_couper(_texte(entree, 'url'))} »."
    verbe, cle = GESTES.get(outil, ("", ""))
    objet = _couper(_texte(entree, cle)) if cle else ""
    if not objet:
        return f"{agent} veut utiliser l'outil {_couper(outil)}."
    phrase = f"{agent} veut {verbe} « {objet} »."
    if outil == "Bash" and not regle and pour_chantier:
        phrase += " Cette commande peut être autorisée pour ce chantier, pas pour de bon."
    elif outil == "Bash" and not regle:
        phrase += " Cette commande ne peut être autorisée qu'au cas par cas."
    return phrase


class _Demande:
    def __init__(self, identifiant: str, agent, outil, entree):
        self.id, self.agent = identifiant, str(agent)
        self.outil = outil if isinstance(outil, str) else str(outil)
        self.regle = regle_pour(outil, entree)
        self.regles_chantier = regles_chantier_pour(outil, entree)
        self.phrase = phrase_pour(self.agent, outil, entree, self.regle, bool(self.regles_chantier))
        self.detail = detail_pour(outil, entree)
        self.reponse: Reponse | None = None
        self.reglee = threading.Event()

    def fiche(self) -> dict:
        return {"id": self.id, "agent": self.agent, "outil": self.outil,
                "phrase": self.phrase, "regle": self.regle, "detail": self.detail,
                "regles_chantier": list(self.regles_chantier)}


class Guichet:
    """Tient les demandes ouvertes ; un verrou unique protège la liste et les réponses."""

    def __init__(self, delai_s: float = 3600):
        if not delai_s > 0:
            raise ValueError("Le délai du guichet doit être un nombre positif.")
        self.delai_s = float(min(delai_s, DELAI_MAX_S))
        self._verrou = threading.Lock()
        self._ouvertes: dict[str, _Demande] = {}
        self._compteur = itertools.count(1)

    def _nouvel_identifiant(self) -> str:
        # Le compteur garantit l'unicité, la partie tirée au sort empêche de deviner.
        return f"d{next(self._compteur)}-{secrets.token_hex(4)}"

    def demander(self, agent: str, outil: str, entree: dict) -> Reponse:
        """Dépose la demande et bloque le fil appelant jusqu'à la réponse ou au délai."""
        with self._verrou:
            demande = _Demande(self._nouvel_identifiant(), agent, outil, entree)
            self._ouvertes[demande.id] = demande
        try:
            demande.reglee.wait(self.delai_s)
        finally:
            with self._verrou:
                # Une réponse arrivée juste après le délai, mais avant ce verrou, l'emporte.
                if demande.reponse is None:
                    self._fermer(demande, Reponse("non", SANS_REPONSE))
        return demande.reponse

    def _fermer(self, demande: _Demande, reponse: Reponse) -> None:
        """À appeler sous le verrou : retire la demande, range la réponse, réveille l'agent."""
        self._ouvertes.pop(demande.id, None)
        demande.reponse = reponse
        demande.reglee.set()

    def ouvertes(self) -> list[dict]:
        """Les demandes en attente, dans l'ordre d'arrivée, prêtes pour du JSON."""
        with self._verrou:
            return [d.fiche() for d in self._ouvertes.values()]

    def repondre(self, identifiant: str, choix: str, message: str = "") -> bool:
        """Règle une demande ouverte. Rend False si rien n'a été débloqué."""
        if not isinstance(identifiant, str) or not isinstance(choix, str) or choix not in CHOIX:
            return False
        message = message if isinstance(message, str) else ""
        with self._verrou:
            demande = self._ouvertes.get(identifiant)
            if demande is None or (choix == "toujours" and not demande.regle):
                return False
            if choix == "chantier" and not demande.regles_chantier:
                return False
            regle = demande.regle if choix == "toujours" else ""
            regles = tuple(demande.regles_chantier) if choix == "chantier" else ()
            self._fermer(demande, Reponse(choix, message, regle, regles))
        return True

    def annuler(self, agent: str) -> int:
        """Ferme sur « non » toutes les demandes ouvertes de cet agent ; rend leur nombre."""
        with self._verrou:
            visees = [d for d in self._ouvertes.values() if d.agent == str(agent)]
            for demande in visees:
                self._fermer(demande, Reponse("non", ARRETE))
        return len(visees)


class GuichetSimule(Guichet):
    """Pour la démonstration : répond tout de suite, selon un scénario écrit d'avance.

    Le scénario est une liste de choix (« une_fois », « toujours », « chantier », « non ») ou de
    Reponse,
    consommée dans l'ordre. Une fois épuisé, le guichet répond « non ». La règle d'un
    « toujours » est toujours celle que le vrai guichet proposerait, jamais celle du scénario.
    Quand cette règle manque, le vrai guichet refuserait « toujours » et laisserait la demande
    ouverte ; le guichet simulé, qui doit répondre tout de suite, répond alors « une_fois ». De
    même pour « chantier », dont les règles sont toujours celles du vrai guichet.
    """

    def __init__(self, scenario=()):
        super().__init__()
        self._scenario = [r if isinstance(r, Reponse) else Reponse(r) for r in scenario]
        if any(r.choix not in CHOIX for r in self._scenario):
            raise ValueError("Le scénario contient un choix inconnu.")
        self.demandes: list[dict] = []

    def demander(self, agent: str, outil: str, entree: dict) -> Reponse:
        with self._verrou:
            demande = _Demande(self._nouvel_identifiant(), agent, outil, entree)
            self.demandes.append(demande.fiche())
            prevue = self._scenario.pop(0) if self._scenario else Reponse("non", SCENARIO_EPUISE)
        if prevue.choix == "chantier":
            if not demande.regles_chantier:
                return Reponse("une_fois", prevue.message, "")
            return Reponse("chantier", prevue.message, "", tuple(demande.regles_chantier))
        if prevue.choix != "toujours":
            return Reponse(prevue.choix, prevue.message, "")
        if not demande.regle:
            return Reponse("une_fois", prevue.message, "")
        return Reponse("toujours", prevue.message, demande.regle)
