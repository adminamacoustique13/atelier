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

import json
import re
import threading
import time
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
from pathlib import Path

from atelier.consignes import BALISE_PLAN, ROLE_ORCHESTRATEUR
from atelier.guichet import ARRETE

OUTILS_LECTURE = ["Read", "Glob", "Grep"]
OUTILS_ECRITURE = ["Edit", "Write"]
# Interdits au vérificateur et à la conversation ; une règle qui les vise ne leur est pas donnée.
ECRITURE = ("Edit", "Write", "MultiEdit", "NotebookEdit")
# Une règle simple : un nom d'outil, suivi ou non d'une seule paire de parenthèses non vide.
# Le SDK joint les outils permis par des virgules : une virgule ferait lire deux règles.
REGLE_SIMPLE = re.compile(r"[A-Za-z0-9_.:-]+(\([^(),\x00-\x1f\x7f]+\))?")
# Git en lecture seule : regarder l'historique et les branches, jamais les changer.
GIT_LECTURE = [
    f"Bash(git {c}:*)"
    for c in (
        "status",
        "diff",
        "log",
        "show",
        "ls-files",
        "remote -v",
        "remote get-url",
        "branch --show-current",
        "branch -a",
        "branch -v",
        "rev-parse",
    )
]

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
LIMITE_INCONNUE = "inconnue"  # le type d'une limite que le SDK ne nomme pas
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


def _sans_reprise(rappel, nom: str) -> Resultat:
    """Une reprise demandée d'une session vide : l'erreur à part, sans lancer d'agent."""
    resultat = Resultat(ok=False, erreur=REPRISE_IMPOSSIBLE)
    _emettre(rappel, nom, "fin", _fin(resultat))
    return resultat


def _arrete(marche: _Marche, resultat: Resultat) -> Resultat:
    """Un arrêt demandé pendant le travail l'emporte sur ce que l'agent a rendu."""
    if not marche.arret.is_set():
        return resultat
    return Resultat(ok=False, erreur=ARRETE, cout_usd=resultat.cout_usd, tokens=resultat.tokens)


class AgentClaude(_ModeDesOuvriers):
    """Fait travailler Claude Code par l'Agent SDK, avec le modèle et l'effort demandés.

    Chaque appel ouvre sa propre session du pont (`atelier.sdk`) et la ferme en partant.
    Un outil qui n'est ni permis ni interdit passe par le guichet, s'il y en a un.
    """

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

    def _outils(self, lecture_seule: bool) -> list[str]:
        """Rend la liste des outils permis : lecture, commandes du projet, écriture si permise."""
        commandes = [f"Bash({c}:*)" for c in self.profil.get("commandes_permises", [])]
        outils = OUTILS_LECTURE + commandes + COMMANDES_DEV + GIT_LECTURE + LECTURE_SHELL
        outils += WEB_LECTURE
        return outils if lecture_seule else outils + OUTILS_ECRITURE

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
        return self._travailler(
            tache, nom, consigne, ouvrier=not lecture_seule,
            modele=self._alias(modele), effort=effort, dossier=dossier,
            outils_permis=self._outils(not ecrit) + self._autorisations(not ecrit),
            outils_interdits=[] if ecrit else list(ECRITURE),
            mode_permission=mode, **reprise,
        )  # fmt: skip

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
        """
        return self._postes.arreter(tache or None)

    def _travailler(
        self, tache, nom, consigne, sur_texte=None, sur_outil=None, ouvrier=False, **reglages
    ):
        """Ouvre une session du pont, lui confie la consigne et rend le résultat.

        Quand l'appel rend la main, la session est fermée et son client déconnecté, même après
        un arrêt : l'appel suivant ne croise jamais un Claude Code encore en train de sortir.
        """
        from atelier.sdk import SessionSDK

        session = SessionSDK(
            nom, guichet=self.guichet, delai_max_s=self.delai_max_s,
            fabrique_client=self.fabrique_client, **reglages,
        )  # fmt: skip
        une_fois, fermee = threading.Lock(), threading.Event()

        def fermer():  # une seule fois, par l'appel ou par le fil d'arrêt
            if une_fois.acquire(blocking=False):
                try:
                    session.fermer()
                finally:
                    fermee.set()

        def couper():
            threading.Thread(target=fermer, daemon=True, name=f"atelier-arret-{nom}").start()

        with self._postes.occuper(tache, nom, couper, session, ouvrier) as marche:
            session.sur_evenement = self._relais(marche, session, sur_texte, sur_outil)
            try:
                resultat = session.envoyer(consigne)
            finally:
                fermer()
                fermee.wait()  # la fermeture lancée par un arrêt est attendue elle aussi
        resultat = _arrete(marche, resultat)  # après le retrait du poste : aucune fenêtre
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
    entree = bloc.get("input") or {}
    entree = entree if isinstance(entree, dict) else {}
    verbe, cle = GESTES.get(bloc.get("name", ""), (bloc.get("name", "Outil"), ""))
    objet = " ".join(str(entree.get(cle, "")).split()) if cle != "command" else ""
    if cle in CHEMINS and racine and objet:
        prefixe = str(racine).rstrip("/") + "/"
        objet = objet[len(prefixe):] if objet.startswith(prefixe) else objet
    if cle == "command":
        objet = str(entree.get("command", "")).replace("\n", " ; ").strip()
        description = " ".join(str(entree.get("description") or "").split())
        if description:
            return f"{description} — {objet}".strip(" —")[:120]
    return f"{verbe} {objet}".strip()[:120]


# Ce que les agents simulés font en patientant (démonstration), et l'écart entre deux gestes.
GESTES_SIMULES = (
    "Lit le périmètre", "Cherche les appels", "Lit les tests", "Écrit le code", "Écrit le code",
    "Lance les contrôles", "Relit le changement", "Écrit les tests", "Lance les tests",
)
ETAPES_SIMULEES = ("lire le périmètre", "écrire le code", "écrire les tests", "relire")
RYTHME_GESTES = (0.4, 0.3, 1.6, 0.5, 0.2, 0.3, 2.2, 0.6, 0.4, 1.1, 0.3, 0.8)


@dataclass
class AgentSimule(_ModeDesOuvriers):
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
    d'alerte, puis le travail prévu), ou "" (rien de spécial). Au-delà de la liste, rien. La limite
    jouée est `type_limite`, levée `delai_limite_s` secondes plus tard (None : heure inconnue).

    La reprise : chaque appel rend une session (`resultat.session`). `executer(...,
    reprendre=session)` repart dans une session déjà rendue, la note dans `reprises` et rend la
    même session ; une session inconnue, ou oubliée par `oublier_sessions`, rend
    `REPRISE_IMPOSSIBLE`. Par défaut, rien de tout cela ne change ce qu'il joue.
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
        """Arrête l'agent simulé en marche pour cette tâche, ou l'orchestrateur sans tâche."""
        return self._postes.arreter(tache or None)

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
    ) -> Resultat:
        """Rend le résultat prévu par le scénario pour cette tâche et cette tentative."""
        contexte = contexte or {}
        appel = {**contexte, "modele": modele, "effort": effort}
        self.appels.append(appel if reprendre is None else {**appel, "reprise": reprendre})
        tache, nom = _poste(contexte)
        jeu = self._jeu_de_limite(tache)
        session = self._ouvrir_session(reprendre, consigne, contexte)
        if session is None or jeu == "refus":
            return self._refuser(nom, session, jeu)
        ouvrier = contexte.get("role") == "ouvrier"
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
        resultat = _arrete(marche, prevu)  # après le retrait du poste : aucune fenêtre
        resultat.session = session
        _emettre(self.sur_evenement, nom, "fin", _fin(resultat))
        return resultat

    def oublier_sessions(self) -> None:
        """Oublie les sessions rendues : les reprendre rendra désormais `REPRISE_IMPOSSIBLE`."""
        with self._verrou:
            self._sessions.clear()

    def _jeu_de_limite(self, tache: str | None) -> str:
        """Ce que `limites` fait jouer à cet appel pour cette tâche : "refus", "alerte" ou ""."""
        cle = tache or "orchestrateur"
        with self._verrou:
            rang = self._joues.get(cle, 0)
            self._joues[cle] = rang + 1
        jeux = self.limites.get(cle, [])
        return jeux[rang] if rang < len(jeux) else ""

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
        """Rend aussitôt une reprise impossible, ou un refus pour limite, et le dit."""
        if session is None:
            resultat = Resultat(ok=False, erreur=REPRISE_IMPOSSIBLE)
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
