"""Les agents : Claude Code en ligne de commande, ou un simulateur pour les essais."""

from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from atelier.consignes import BALISE_PLAN, ROLE_ORCHESTRATEUR

OUTILS_LECTURE = ["Read", "Glob", "Grep"]
OUTILS_ECRITURE = ["Edit", "Write"]
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


@dataclass
class Resultat:
    """Ce qu'un agent rend : son texte, son coût, et s'il a pu aller au bout."""

    ok: bool
    texte: str = ""
    cout_usd: float = 0.0
    tokens: int = 0
    erreur: str = ""
    fichiers: list[str] | None = None


class AgentClaude:
    """Lance Claude Code en ligne de commande, avec le modèle et l'effort demandés."""

    def __init__(self, profil: dict | None = None, delai_max_s: int = 3600):
        self.profil = profil or {}
        self.delai_max_s = delai_max_s

    def _outils(self, lecture_seule: bool) -> list[str]:
        """Rend la liste des outils permis : lecture, commandes du projet, écriture si permise."""
        commandes = [f"Bash({c}:*)" for c in self.profil.get("commandes_permises", [])]
        outils = OUTILS_LECTURE + commandes + GIT_LECTURE
        return outils if lecture_seule else outils + OUTILS_ECRITURE

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
        alias = self.profil.get("alias_modeles", {}).get(modele, modele)
        commande = [
            "claude", "-p", consigne,
            "--model", alias,
            "--effort", effort,
            "--output-format", "json",
            "--no-session-persistence",
            "--allowedTools", *self._outils(lecture_seule),
        ]  # fmt: skip
        if lecture_seule:
            commande += ["--disallowedTools", *OUTILS_ECRITURE]
        else:
            commande += ["--permission-mode", "acceptEdits"]
        try:
            sortie = subprocess.run(
                commande, cwd=dossier, capture_output=True, text=True, timeout=self.delai_max_s
            )
        except (OSError, subprocess.TimeoutExpired) as erreur:
            return Resultat(ok=False, erreur=f"Claude Code n'a pas pu aller au bout : {erreur}")
        return lire_sortie_claude(sortie.stdout, sortie.stderr)

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
        identifiant, ensuite on la reprend. Elle lit le dépôt mais n'écrit rien.
        """
        alias = self.profil.get("alias_modeles", {}).get("fable", "fable")
        commande = [
            "claude", "-p", message,
            "--model", alias,
            "--effort", "high",
            "--output-format", "stream-json", "--verbose", "--include-partial-messages",
            "--append-system-prompt", ROLE_ORCHESTRATEUR,
            # En conversation : lecture seule, sans les commandes du projet (qui exécutent du code).
            "--allowedTools", *OUTILS_LECTURE, *GIT_LECTURE,
            "--disallowedTools", *OUTILS_ECRITURE,
            *(["--resume", session] if reprise else ["--session-id", session]),
        ]  # fmt: skip
        try:
            with subprocess.Popen(
                commande, cwd=dossier, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True
            ) as processus:
                return lire_flux_claude(processus.stdout, sur_texte, sur_outil)
        except OSError as erreur:
            return Resultat(ok=False, erreur=f"Claude Code n'a pas pu démarrer : {erreur}")


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


def _suivre(evenement: dict, morceaux: list[str], sur_texte, sur_outil) -> None:
    """Relaie un événement du flux : un bout de texte, ou un outil qui démarre."""
    if evenement.get("type") == "stream_event":
        delta = (evenement.get("event") or {}).get("delta") or {}
        if delta.get("type") == "text_delta" and delta.get("text"):
            morceaux.append(delta["text"])
            if sur_texte:
                sur_texte(delta["text"])
    elif evenement.get("type") == "assistant" and sur_outil:
        for bloc in (evenement.get("message") or {}).get("content") or []:
            if isinstance(bloc, dict) and bloc.get("type") == "tool_use":
                sur_outil(decrire_outil(bloc))


def lire_flux_claude(lignes, sur_texte=None, sur_outil=None) -> Resultat:
    """Lit la réponse de Claude Code au fil de l'eau, une ligne JSON après l'autre."""
    morceaux: list[str] = []
    final = None
    for ligne in lignes:
        try:
            evenement = json.loads(ligne)
        except ValueError:
            continue
        if not isinstance(evenement, dict):
            continue
        if evenement.get("type") == "result":
            final = evenement
        else:
            _suivre(evenement, morceaux, sur_texte, sur_outil)
    if final is None:
        return Resultat(ok=False, erreur="Claude Code s'est arrêté sans répondre.")
    resultat = lire_sortie_claude(json.dumps(final))
    if resultat.ok and not resultat.texte:
        resultat.texte = "".join(morceaux)
    return resultat


def lire_sortie_claude(sortie: str, erreurs: str = "") -> Resultat:
    """Traduit la sortie JSON de Claude Code en résultat."""
    try:
        donnees = json.loads(sortie)
    except ValueError:
        return Resultat(ok=False, erreur=(erreurs or sortie or "Sortie vide.")[-500:])
    usage = donnees.get("usage") or {}
    tokens = int(usage.get("input_tokens", 0)) + int(usage.get("output_tokens", 0))
    texte = str(donnees.get("result", ""))
    if donnees.get("is_error"):
        return Resultat(ok=False, erreur=texte or "Erreur signalée par Claude Code.", tokens=tokens)
    return Resultat(
        ok=True, texte=texte, cout_usd=float(donnees.get("total_cost_usd") or 0), tokens=tokens
    )


@dataclass
class AgentSimule:
    """Joue un scénario écrit d'avance : pour la démonstration et les tests.

    Le scénario donne, pour chaque tâche, l'issue de chaque tentative :
    "ok", "bacle", "ne_sait_pas", "consigne", "deborde" ou "erreur".
    """

    scenario: dict[str, list[str]] = field(default_factory=dict)
    delai_s: float = 0.0
    perimetres: dict[str, list[str]] = field(default_factory=dict)
    plan: dict | None = None
    appels: list[dict] = field(default_factory=list)

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
        time.sleep(self.delai_s)
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
        for mot in texte.split(" "):
            time.sleep(min(self.delai_s, 1.0) / 25)
            if sur_texte:
                sur_texte(mot + " ")
        return Resultat(ok=True, texte=texte, cout_usd=0.8, tokens=6000)
