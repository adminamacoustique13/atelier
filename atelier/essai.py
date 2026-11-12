"""L'essai réel : un petit chantier joué de bout en bout avec de vrais agents.

Les tests (`pytest`) ne font tourner l'Atelier que sur des faux clients. Cet essai vérifie, sur
la machine où l'Atelier est installé, ce que seuls de vrais agents peuvent montrer : la
bibliothèque se charge, la connexion répond et dit ce qui est facturé, l'orchestrateur
converse, un ouvrier écrit dans sa copie, les contrôles et le vérificateur passent, le travail
entre dans la branche principale sans fichier en trop, et le bouton « Arrêter » coupe un agent
sans laisser de programme Claude derrière lui.

Il travaille dans un dépôt jetable, hors de tes projets, sur de petits modèles (Sonnet en effort
faible pour les ouvriers). Compte quelques minutes et de l'ordre d'un dollar en coût
équivalent, compté sur ton abonnement ou ta clé comme tout travail de l'Atelier.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from atelier.moteur import ARRETEE

NOM_PROJET = "Essai de l'Atelier"
VERSION_ATTENDUE = "0.2.172"  # celle de uv.lock, sur laquelle tous les tests ont tourné
DELAI_CONVERSATION_S = 300
DELAI_CHANTIER_S = 900
DELAI_ARRET_S = 60  # une tâche arrêtée doit revenir dans ce délai
PAUSE_S = 0.5


def plan_d_essai(python: str) -> dict:
    """Deux tâches indépendantes : A va au bout, B sera arrêtée dès que son ouvrier travaille."""
    return {
        "objectif": "Vérifier l'Atelier de bout en bout sur un module minuscule.",
        "hors_perimetre": "Tout autre fichier que ceux des périmètres.",
        "taches": [
            {
                "id": "A",
                "titre": "Fonction moyenne",
                "type": "courante",
                "pourquoi": "Un livrable minuscule qui doit traverser tout le chantier.",
                "criteres": [
                    "calcul.py définit moyenne(liste), qui rend la moyenne arithmétique en "
                    "nombre réel : moyenne([1, 2]) vaut 1.5.",
                    "moyenne([]) lève ValueError.",
                    f"La commande {python} -c \"import calcul; "
                    "assert calcul.moyenne([2, 4]) == 3\" réussit.",
                ],
                "perimetre": ["calcul.py"],
            },
            {
                "id": "B",
                "titre": "Module de textes (sera arrêtée)",
                "type": "courante",
                "pourquoi": "Sert à essayer le bouton « Arrêter » pendant que l'ouvrier travaille.",
                "criteres": [
                    "texte.py définit inverser(s), compter_voyelles(s), est_palindrome(s) et "
                    "titre(s), chacune avec une docstring et des exemples.",
                ],
                "perimetre": ["texte.py"],
            },
        ],
    }


@dataclass
class Rapport:
    """Les étapes de l'essai, chacune réussie ou non, avec ce qui a été constaté."""

    lignes: list[tuple[bool | None, str, str]] = field(default_factory=list)
    sortie: object = sys.stdout

    def noter(self, reussi: bool | None, etape: str, detail: str = "") -> bool:
        self.lignes.append((reussi, etape, detail))
        marque = {True: "ok   ", False: "ÉCHEC", None: "info "}[reussi]
        print(f"{marque} {etape}" + (f" : {detail}" if detail else ""), file=self.sortie)
        self.sortie.flush()
        return bool(reussi)

    @property
    def reussi(self) -> bool:
        return all(reussi is not False for reussi, _, _ in self.lignes)

    def markdown(self) -> str:
        lignes = ["# Essai réel de l'Atelier", ""]
        bilan = "tout est passé." if self.reussi else "des étapes ont échoué."
        lignes.append(f"Résultat : {bilan}")
        lignes.append("")
        for reussi, etape, detail in self.lignes:
            marque = {True: "[ok]", False: "[ÉCHEC]", None: "[info]"}[reussi]
            lignes.append(f"- {marque} {etape}" + (f" : {detail}" if detail else ""))
        return "\n".join(lignes) + "\n"


def _git(dossier: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments], cwd=dossier, capture_output=True, text=True, check=True
    ).stdout


def creer_projet_d_essai(dossier: Path, python: str) -> None:
    """Un dépôt neuf, comme « Nouveau projet », avec un contrôle qui n'a besoin de rien."""
    from atelier.projets import COMMANDES_PAR_DEFAUT

    (dossier / "chantier").mkdir(parents=True)
    profil = {
        "nom": NOM_PROJET,
        "commandes": [f'{python} -c "import calcul; assert calcul.moyenne([2, 4]) == 3"'],
        # Le Python de l'Atelier, que citent les critères : sans lui, chaque agent qui lance le
        # contrôle demanderait une carte, et l'essai ne distinguerait plus les vraies demandes.
        "commandes_permises": [*COMMANDES_PAR_DEFAUT, python],
        "dosage": {"courante": ["sonnet", "low"]},
    }
    texte = json.dumps(profil, ensure_ascii=False, indent=2) + "\n"
    (dossier / "chantier" / "profil.json").write_text(texte, "utf-8")
    (dossier / ".gitignore").write_text(".atelier/\n", "utf-8")
    _git(dossier, "init", "-q", "-b", "main")
    identite = ["-c", "user.name=Atelier", "-c", "user.email=atelier@localhost"]
    _git(dossier, "add", "-A")
    _git(dossier, *identite, "commit", "-q", "-m", "Création du projet d'essai")


def programmes_claude(racine_pid: int) -> list[str]:
    """Les programmes Claude Code encore lancés par ce processus (directement ou non)."""
    sortie = subprocess.run(
        ["ps", "-A", "-o", "pid=,ppid=,command="], capture_output=True, text=True
    ).stdout
    enfants: dict[int, list[tuple[int, str]]] = {}
    for ligne in sortie.splitlines():
        morceaux = ligne.split(None, 2)
        if len(morceaux) == 3 and morceaux[0].isdigit() and morceaux[1].isdigit():
            enfants.setdefault(int(morceaux[1]), []).append((int(morceaux[0]), morceaux[2]))
    trouves, a_voir = [], [racine_pid]
    while a_voir:
        for pid, commande in enfants.get(a_voir.pop(), []):
            a_voir.append(pid)
            if "claude" in commande.lower():
                trouves.append(f"{pid} {commande[:100]}")
    return trouves


def _attendre(condition, delai_s: float) -> bool:
    limite = time.monotonic() + delai_s
    while time.monotonic() < limite:
        if condition():
            return True
        time.sleep(PAUSE_S)
    return bool(condition())


class Essai:
    """Joue l'essai sur un projet jetable et remplit le rapport."""

    def __init__(self, racine: Path, rapport: Rapport, avec_arret: bool = True):
        self.racine = racine
        self.rapport = rapport
        self.avec_arret = avec_arret
        self.python = shlex.quote(sys.executable)
        self.atelier = None
        self.phases: list[str] = []
        self.etapes: list[str] = []
        self.cartes: list[str] = []

    def jouer(self) -> bool:
        etapes = (
            self.bibliotheque,
            self.projet,
            self.conversation,
            self.chantier,
            self.livraison,
        )
        for etape in etapes:
            if not etape():
                break
        if self.atelier is not None:
            chantier = self.atelier.moteur.chantier
            self.rapport.noter(
                None,
                "Coût de l'essai",
                f"{chantier.agents_lances} agents lancés, coût équivalent "
                f"{chantier.cout_usd:.2f} $, {chantier.tokens} tokens",
            )
        return self.rapport.reussi

    # --- les étapes --------------------------------------------------------------

    def bibliotheque(self) -> bool:
        try:
            from importlib.metadata import version

            import claude_agent_sdk  # noqa: F401
        except ImportError as erreur:
            return self.rapport.noter(
                False, "La bibliothèque claude-agent-sdk se charge", f"{erreur}. Lance « uv sync »."
            )
        trouvee = version("claude-agent-sdk")
        detail = f"version {trouvee}"
        if trouvee != VERSION_ATTENDUE:
            detail += f", l'Atelier a été testé sur la {VERSION_ATTENDUE} (lance « uv sync »)"
        return self.rapport.noter(trouvee == VERSION_ATTENDUE, "La bibliothèque se charge", detail)

    def projet(self) -> bool:
        from atelier.projets import ouvrir_depot

        dossier = self.racine / "essai-atelier"
        creer_projet_d_essai(dossier, self.python)
        self.atelier = ouvrir_depot(dossier)
        self.atelier.annoncer_connexion()
        exclusions = (dossier / ".git" / "info" / "exclude").read_text("utf-8")
        return self.rapport.noter(
            "__pycache__/" in exclusions,
            "Projet jetable créé",
            f"{dossier} (les fichiers fabriqués par les outils sont exclus de git)",
        )

    def conversation(self) -> bool:
        atelier = self.atelier
        avant = len(atelier.moteur.chantier.evenements)
        atelier.message(
            "Ceci est l'essai automatique de l'Atelier. Réponds en une seule phrase : combien "
            "de fichiers vois-tu dans ce dépôt ? Ne propose aucun plan."
        )
        fini = _attendre(lambda: not atelier.occupe, DELAI_CONVERSATION_S)
        nouveaux = atelier.moteur.chantier.evenements[avant:]
        reponses = [e["texte"] for e in nouveaux if e.get("auteur") == "orchestrateur"]
        echec = next((r for r in reponses if r.startswith("Je n'ai pas pu joindre")), "")
        ok = fini and bool(reponses) and not echec
        detail = echec or (reponses[-1][:160] if reponses else "aucune réponse")
        self.rapport.noter(ok, "L'orchestrateur répond", detail if fini else "délai dépassé")
        source = getattr(atelier.moteur.agent, "source_connexion", "") or "inconnue"
        connexion = [e["texte"] for e in nouveaux if "SDK de Claude" in e["texte"]]
        self.rapport.noter(
            None if source == "abonnement" else False if source == "clé API" else None,
            "Ce qui est facturé, selon le SDK",
            f"{source}" + (f" ({connexion[-1][:140]}…)" if connexion else ""),
        )
        return ok

    def chantier(self) -> bool:
        atelier = self.atelier
        # Chaque phase notée par le moteur, même brève (une copie de travail se prépare vite).
        noter = atelier.moteur._phase

        def retenir(tache, phrase):
            self.phases.append(f"{tache.id} {phrase}")
            noter(tache, phrase)

        atelier.moteur._phase = retenir
        atelier._adopter(plan_d_essai(self.python), "Essai")
        if not self.avec_arret:
            moteur = atelier.moteur
            moteur.chantier.taches = [t for t in moteur.chantier.taches if t.id != "B"]
        atelier.valider_contrat()
        arret = self._suivre_arret() if self.avec_arret else None
        termine = _attendre(self._suivre, DELAI_CHANTIER_S)
        a = atelier.moteur.chantier.tache("A")
        tentatives = "; ".join(f"{h['issue']} : {h['detail'][:120]}" for h in a.historique)
        self.rapport.noter(
            termine and a.etat == "verifie",
            "La tâche A traverse tout le chantier",
            f"état « {a.etat} » après {a.tentatives} tentative(s). {tentatives}"
            if termine
            else "délai dépassé",
        )
        phases_a = [p[2:] for p in self.phases if p.startswith("A ")]
        self.rapport.noter(
            len(set(phases_a)) >= 5,
            "Le moteur dit les phases de la tâche A",
            " → ".join(dict.fromkeys(phases_a)) or "aucune",
        )
        self.rapport.noter(
            None,
            "Étapes annoncées par les agents",
            " | ".join(dict.fromkeys(self.etapes)) or "aucune (la consigne les demande)",
        )
        if self.cartes:
            self.rapport.noter(
                None, "Cartes d'autorisation acceptées une fois", " | ".join(self.cartes)
            )
        du_verificateur = [c for c in self.cartes if "-verificateur-" in c.split(" : ")[0]]
        self.rapport.noter(
            not du_verificateur,
            "Le vérificateur fait ses essais sans carte, dans sa copie jetable",
            " | ".join(du_verificateur) or "aucune carte",
        )
        if arret is not None:
            self._dire_arret(arret)
        return termine and a.etat == "verifie"

    def _suivre(self) -> bool:
        """Un tour de surveillance : phases, étapes, cartes. Rend True quand tout est fini."""
        atelier = self.atelier
        for agent in atelier.activite.agents():
            if agent["etape"]:
                self.etapes.append(f"{agent['tache']} {agent['role']} : {agent['etape']}")
        for carte in atelier.guichet.ouvertes() if atelier.guichet else []:
            self.cartes.append(f"{carte['agent']} : {carte['detail'][:80]}")
            atelier.autoriser(carte["id"], "une_fois")
        return not atelier.en_marche()

    def _suivre_arret(self) -> dict:
        """Arrête B dès que son ouvrier agit ; rend ce qui a été constaté."""
        atelier, constat = self.atelier, {}

        def ouvrier_b_agit() -> bool:
            self._suivre()
            return any(a["tache"] == "B" and a["lignes"] for a in atelier.activite.agents())

        if not _attendre(ouvrier_b_agit, DELAI_CHANTIER_S):
            return {"demande": False, "detail": "l'ouvrier de B n'a jamais commencé"}
        debut = time.monotonic()
        constat["demande"] = atelier.arreter("B").get("fait", False)

        def b_revenue() -> bool:
            self._suivre()
            return atelier.moteur.chantier.tache("B").etat not in ("en_cours", "en_verification")

        constat["revenue"] = _attendre(b_revenue, DELAI_ARRET_S)
        constat["duree_s"] = time.monotonic() - debut
        b = atelier.moteur.chantier.tache("B")
        constat["etat"] = b.etat
        constat["issue"] = b.historique[-1]["issue"] if b.historique else ""
        return constat

    def _dire_arret(self, constat: dict) -> None:
        if not constat.get("demande"):
            self.rapport.noter(False, "« Arrêter » coupe l'ouvrier de B", constat.get("detail", ""))
            return
        self.rapport.noter(
            constat["revenue"] and constat["issue"] == ARRETEE,
            "« Arrêter » coupe l'ouvrier de B",
            f"revenue en {constat['duree_s']:.0f} s, état « {constat['etat']} », "
            f"issue « {constat['issue']} »",
        )
        restes: list[str] = []

        def plus_aucun() -> bool:  # le temps que Claude Code finisse de se fermer
            restes[:] = programmes_claude(os.getpid())
            return not restes

        _attendre(plus_aucun, 15)
        self.rapport.noter(
            not restes,
            "Aucun programme Claude ne reste après la fin",
            "; ".join(restes) or "aucun",
        )

    def livraison(self) -> bool:
        depot = self.atelier.depot
        suivis = _git(depot, "ls-files").split()
        journal = _git(depot, "log", "--format=%s").splitlines()
        en_trop = [f for f in suivis if f not in ("calcul.py", ".gitignore")
                   and not f.startswith("chantier/")]  # fmt: skip
        ok = "calcul.py" in suivis and not en_trop and any(s.startswith("A :") for s in journal)
        self.rapport.noter(
            ok,
            "Le travail de A est dans main, sans fichier en trop",
            f"fichiers suivis : {', '.join(suivis)}",
        )
        controle = subprocess.run(
            [sys.executable, "-c", "import calcul; assert calcul.moyenne([1, 2]) == 1.5"],
            cwd=depot,
            capture_output=True,
            text=True,
        )
        return self.rapport.noter(
            controle.returncode == 0,
            "Le code livré marche",
            (controle.stderr.strip().splitlines() or ["moyenne([1, 2]) == 1.5"])[-1],
        )


def commande_essai(arguments) -> None:
    """`python -m atelier essai` : joue l'essai, écrit le rapport, sort en erreur si besoin."""
    racine = Path(arguments.dossier).expanduser().resolve() if arguments.dossier else None
    racine = racine or Path(tempfile.mkdtemp(prefix="atelier-essai-"))
    racine.mkdir(parents=True, exist_ok=True)
    print(f"Essai réel de l'Atelier, dans {racine}")
    print("Il lance de vrais agents : compte quelques minutes et de l'ordre d'un dollar.\n")
    rapport = Rapport()
    try:
        reussi = Essai(racine, rapport, avec_arret=not arguments.sans_arret).jouer()
    except Exception as erreur:  # l'essai rapporte tout, même ce qu'il n'avait pas prévu
        rapport.noter(False, "L'essai s'est interrompu", f"{type(erreur).__name__} : {erreur}")
        reussi = False
    fichier = racine / "ESSAI.md"
    fichier.write_text(rapport.markdown(), "utf-8")
    print(f"\n{'Tout est passé.' if reussi else 'Des étapes ont échoué.'} Rapport : {fichier}")
    sys.stdout.flush()
    os._exit(0 if reussi else 1)  # sans attendre les fils de fond des agents
