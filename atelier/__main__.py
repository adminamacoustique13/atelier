"""Les commandes de l'atelier : demo, planifier, servir, instantanes."""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from pathlib import Path

from atelier.agents import AgentClaude, AgentSimule
from atelier.controles import ControlesGit, ControlesSimules
from atelier.modele import Chantier, Contrat
from atelier.moteur import RELANCER, planifier
from atelier.serveur import PAGE, Atelier, creer_serveur


def lire_profil(depot: Path) -> dict:
    """Lit le profil du projet, ou rend un profil vide."""
    chemin = depot / "chantier" / "profil.json"
    return json.loads(chemin.read_text("utf-8")) if chemin.exists() else {}


OBJECTIF_DEMO = "Moteur de calcul : formules de la norme, validées sur les cas de référence."


def plan_de_demonstration() -> tuple[dict, dict]:
    """Prépare le découpage d'exemple et le scénario que joueront les agents simulés."""

    def tache(identifiant, titre, nature, pourquoi, depend_de=(), ajoutee=False):
        return {
            "id": identifiant,
            "titre": titre,
            "type": nature,
            "pourquoi": pourquoi,
            "criteres": ["Les cas de référence passent.", "Les tests couvrent chaque critère."],
            "perimetre": [f"coeur/{identifiant.lower().replace('.', '_')}.py"],
            "depend_de": list(depend_de),
            "ajoutee": ajoutee,
        }

    plan = {
        "objectif": OBJECTIF_DEMO,
        "hors_perimetre": "Les écrans, les exports et les performances.",
        "taches": [
            tache("A", "Lecture des données d'entrée", "courante", "Tout le calcul en dépend."),
            tache("B", "Formule de la norme", "physique", "Une erreur ici se verrait très tard."),
            tache(
                "B.1",
                "Cas limite : valeur négative",
                "courante",
                "Cas découvert en cours de route.",
                ["B"],
                ajoutee=True,
            ),
            tache("C", "Jeu de tests de référence", "mecanique", "Fixer les valeurs attendues."),
            tache(
                "D",
                "Liaison avec l'interface",
                "mecanique",
                "Exposer le calcul au reste du code.",
                ["A", "B"],
            ),
            tache("E", "Contrat entre modules", "delicate", "Deux modules en dépendent."),
        ],
    }
    scenario = {
        "C": ["ne_sait_pas", "ne_sait_pas", "ok"],
        "D": ["deborde", "ok"],
        "E": ["bacle", "bacle", "ok"],
    }
    return plan, scenario


def atelier_de_demonstration(delai_s: float) -> Atelier:
    """Monte un atelier complet sur un dossier temporaire, avec des agents simulés."""
    depot = Path(tempfile.mkdtemp(prefix="atelier-demo-"))
    plan, scenario = plan_de_demonstration()
    chantier = Chantier(projet="Projet de démonstration", contrat=Contrat(objectif=""))
    agent = AgentSimule(scenario, delai_s, plan=plan)
    return Atelier(depot, chantier, agent, ControlesSimules(), {}, mode="démonstration")


def commande_demo(arguments) -> None:
    atelier = atelier_de_demonstration(arguments.delai)
    serveur = creer_serveur(atelier, arguments.port)
    print(f"Tableau de bord de démonstration : http://127.0.0.1:{arguments.port}")
    serveur.serve_forever()


def commande_planifier(arguments) -> None:
    depot = Path(arguments.depot).resolve()
    profil = lire_profil(depot)
    taches = planifier(AgentClaude(profil), arguments.objectif, profil, depot)
    if not taches:
        raise SystemExit("Le découpage n'a rendu aucune tâche. Rien n'a été écrit.")
    chantier = Chantier(
        projet=profil.get("nom", depot.name),
        contrat=Contrat(objectif=arguments.objectif, max_agents=3 * len(taches)),
        taches=taches,
    )
    chantier.sauver(depot / ".atelier" / "etat.json")
    print(f"{len(taches)} tâches proposées. Lance « servir » pour relire et valider le contrat.")


def commande_servir(arguments) -> None:
    depot = Path(arguments.depot).resolve()
    profil = lire_profil(depot)
    etat = depot / ".atelier" / "etat.json"
    if etat.exists():
        chantier = Chantier.charger(etat)
    else:
        chantier = Chantier(projet=profil.get("nom", depot.name), contrat=Contrat(objectif=""))
    controles = ControlesGit(depot, profil.get("commandes", []))
    atelier = Atelier(depot, chantier, AgentClaude(profil), controles, profil)
    serveur = creer_serveur(atelier, arguments.port)
    print(f"Tableau de bord : http://127.0.0.1:{arguments.port}")
    serveur.serve_forever()


def commande_instantanes(arguments) -> None:
    """Joue la démonstration d'une traite et l'inscrit dans une page autonome."""
    atelier = atelier_de_demonstration(0.0)
    vues = [atelier.vue()]
    atelier.sur_vue = vues.append
    atelier.message(OBJECTIF_DEMO)
    atelier.fil_message.join()
    atelier.valider_contrat()
    atelier.fil.join()
    demande = atelier.moteur.chantier.demandes[0]["id"]
    vues.append(atelier.vue())
    atelier.decider(demande, RELANCER)
    atelier.fil.join()
    vues.append(atelier.vue())
    page = PAGE.read_text("utf-8").replace(
        "/*INSTANTANES*/[]", json.dumps(vues, ensure_ascii=False).replace("</", "<\\/")
    )
    Path(arguments.sortie).write_text(page, "utf-8")
    print(f"{len(vues)} instantanés écrits dans {arguments.sortie}")


def main() -> None:
    analyseur = argparse.ArgumentParser(prog="atelier", description=__doc__)
    commandes = analyseur.add_subparsers(dest="commande", required=True)

    demo = commandes.add_parser("demo", help="Tableau de bord avec des agents simulés.")
    demo.add_argument("--port", type=int, default=8765)
    demo.add_argument("--delai", type=float, default=2.5, help="Secondes par agent simulé.")
    demo.set_defaults(action=commande_demo)

    plan = commandes.add_parser("planifier", help="Découpe un objectif en tâches (appel réel).")
    plan.add_argument("objectif")
    plan.add_argument("--depot", default=".")
    plan.set_defaults(action=commande_planifier)

    servir = commandes.add_parser("servir", help="Tableau de bord et moteur sur un vrai dépôt.")
    servir.add_argument("--depot", default=".")
    servir.add_argument("--port", type=int, default=8765)
    servir.set_defaults(action=commande_servir)

    instantanes = commandes.add_parser("instantanes", help="Page autonome de démonstration.")
    instantanes.add_argument("sortie")
    instantanes.set_defaults(action=commande_instantanes)

    arguments = analyseur.parse_args()
    arguments.action(arguments)


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, subprocess.SubprocessError):
        raise SystemExit(0) from None
