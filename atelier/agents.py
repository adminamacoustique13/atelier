"""Les agents : Claude Code piloté par l'Agent SDK, ou un simulateur pour les essais.

Les deux offrent la même interface au moteur et au serveur : `executer`, `converser`,
`arreter(tache)`, et les attributs `guichet`, `sur_evenement` et `source_connexion`.
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

RAISONS_SIMULEES = {
    "bacle": "Un critère de la consigne a été négligé.",
    "ne_sait_pas": "Le calcul est faux sur un cas de référence.",
    "consigne": "Les critères ne suffisent pas à prouver le but.",
}
DEMANDE_SIMULEE = {"command": "npm install left-pad"}
CHOIX_LUS = {
    "une_fois": "autorisé une fois",
    "toujours": "autorisé pour ce projet",
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


def _poste(contexte: dict | None) -> tuple[str | None, str]:
    """Rend la tâche d'un appel (None sans tâche) et le nom de l'agent, comme « B-ouvrier-1 »."""
    contexte = contexte or {}
    tache = contexte.get("tache")
    if not tache:
        return None, "orchestrateur"
    role, tentative = contexte.get("role", "ouvrier"), contexte.get("tentative", 1)
    return str(tache), f"{tache}-{role}-{tentative}"


def _emettre(rappel, agent: str, type_: str, contenu: str) -> None:
    """Relaie un événement en direct ; une erreur du rappel ne touche pas l'agent."""
    if rappel is not None:
        with suppress(Exception):
            rappel({"agent": agent, "type": type_, "contenu": contenu})


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
    """Un agent en marche : son nom, et le drapeau que pose une demande d'arrêt."""

    def __init__(self, nom: str, couper=None):
        self.nom, self.couper = nom, couper
        self.arret = threading.Event()  # posé par `arreter`
        self.reveil = threading.Event()  # posé par `arreter` ou par la réponse du guichet
        self.fin_emise = False


class _Postes:
    """Les agents en marche, rangés par tâche (None : l'orchestrateur)."""

    def __init__(self):
        self._verrou = threading.Lock()
        self._marches: dict[str | None, _Marche] = {}

    @contextmanager
    def occuper(self, tache: str | None, nom: str, couper=None):
        """Inscrit l'agent pour la durée de son travail : un arrêt peut alors le viser."""
        marche = _Marche(nom, couper)
        with self._verrou:
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


def _arrete(marche: _Marche, resultat: Resultat) -> Resultat:
    """Un arrêt demandé pendant le travail l'emporte sur ce que l'agent a rendu."""
    if not marche.arret.is_set():
        return resultat
    return Resultat(ok=False, erreur=ARRETE, cout_usd=resultat.cout_usd, tokens=resultat.tokens)


class AgentClaude:
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
        self._postes = _Postes()

    def _outils(self, lecture_seule: bool) -> list[str]:
        """Rend la liste des outils permis : lecture, commandes du projet, écriture si permise."""
        commandes = [f"Bash({c}:*)" for c in self.profil.get("commandes_permises", [])]
        outils = OUTILS_LECTURE + commandes + GIT_LECTURE
        return outils if lecture_seule else outils + OUTILS_ECRITURE

    def _autorisations(self, lecture_seule: bool) -> list[str]:
        """Les règles simples retenues du profil ; en lecture seule, sans celles qui écrivent."""
        regles = _regles_simples(self.profil.get("autorisations"))
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
    ) -> Resultat:
        """Exécute une consigne et rend le résultat de l'agent."""
        tache, nom = _poste(contexte)
        return self._travailler(
            tache, nom, consigne,
            modele=self._alias(modele), effort=effort, dossier=dossier,
            outils_permis=self._outils(lecture_seule) + self._autorisations(lecture_seule),
            outils_interdits=list(ECRITURE) if lecture_seule else [],
            mode_permission="default" if lecture_seule else "acceptEdits",
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
            # En conversation : lecture seule, sans les commandes du projet (qui exécutent du code).
            outils_permis=OUTILS_LECTURE + GIT_LECTURE, outils_interdits=list(ECRITURE),
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

    def _travailler(self, tache, nom, consigne, sur_texte=None, sur_outil=None, **reglages):
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

        with self._postes.occuper(tache, nom, couper) as marche:
            session.sur_evenement = self._relais(marche, session, sur_texte, sur_outil)
            try:
                resultat = session.envoyer(consigne)
            finally:
                fermer()
                fermee.wait()  # la fermeture lancée par un arrêt est attendue elle aussi
        resultat = _arrete(marche, resultat)  # après le retrait du poste : aucune fenêtre
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
}
GESTES |= {"Bash": ("Lance", "command"), "Skill": ("Utilise le skill", "skill")}


def decrire_outil(bloc: dict) -> str:
    """Dit en quelques mots ce que Claude Code est en train de faire."""
    verbe, cle = GESTES.get(bloc.get("name", ""), (bloc.get("name", "Outil"), ""))
    objet = str((bloc.get("input") or {}).get(cle, ""))
    return f"{verbe} {objet}".strip()[:120]


@dataclass
class AgentSimule:
    """Joue un scénario écrit d'avance : pour la démonstration et les tests.

    Le scénario donne, pour chaque tâche, l'issue de chaque tentative :
    "ok", "bacle", "ne_sait_pas", "consigne", "deborde" ou "erreur".
    Si un guichet lui est attaché, le premier ouvrier lancé y dépose une demande
    d'autorisation d'exemple et attend la réponse avant de poursuivre.
    """

    scenario: dict[str, list[str]] = field(default_factory=dict)
    delai_s: float = 0.0
    perimetres: dict[str, list[str]] = field(default_factory=dict)
    plan: dict | None = None
    appels: list[dict] = field(default_factory=list)
    guichet: object = None
    sur_evenement: object = None
    source_connexion: str = ""
    _postes: _Postes = field(default_factory=_Postes, init=False, repr=False, compare=False)
    _demandes: list[str] = field(default_factory=list, init=False, repr=False, compare=False)
    _verrou: object = field(default_factory=threading.Lock, init=False, repr=False, compare=False)

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
    ) -> Resultat:
        """Rend le résultat prévu par le scénario pour cette tâche et cette tentative."""
        contexte = contexte or {}
        self.appels.append({**contexte, "modele": modele, "effort": effort})
        tache, nom = _poste(contexte)
        with self._postes.occuper(tache, nom, lambda: self._annuler(nom)) as marche:
            _emettre(self.sur_evenement, nom, "outil", "Lit la consigne")
            if contexte.get("role") == "ouvrier" and self._premiere_demande(nom):
                self._demander(marche)
            arrete = marche.arret.wait(self.delai_s)
            prevu = Resultat(ok=False) if arrete else self._prevu(contexte, dossier, modele)
        resultat = _arrete(marche, prevu)  # après le retrait du poste : aucune fenêtre
        _emettre(self.sur_evenement, nom, "fin", _fin(resultat))
        return resultat

    def _premiere_demande(self, nom: str) -> bool:
        """Vrai pour le premier ouvrier lancé alors qu'un guichet est attaché, et lui seul."""
        with self._verrou:
            if self.guichet is None or self._demandes:
                return False
            self._demandes.append(nom)
            return True

    def _demander(self, marche: _Marche) -> None:
        """Dépose la demande d'exemple au guichet et attend sa réponse, ou un arrêt."""
        guichet, nom, reponses = self.guichet, marche.nom, []
        _emettre(self.sur_evenement, nom, "attente", decrire_outil(_bash(DEMANDE_SIMULEE)))

        def demander():
            with suppress(Exception):
                reponses.append(guichet.demander(nom, "Bash", dict(DEMANDE_SIMULEE)))
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
            _emettre(self.sur_evenement, nom, "outil", decrire_outil(_bash(DEMANDE_SIMULEE)))

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
