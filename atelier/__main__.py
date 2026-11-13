"""Les commandes de l'atelier : demo, planifier, servir, essai, instantanes."""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path

from atelier.agents import AgentClaude, AgentSimule
from atelier.controles import ControlesSimules
from atelier.guichet import Guichet
from atelier.mise_a_jour import MiseAJour, MiseAJourSimulee
from atelier.modele import Chantier, Contrat, ProjetImpossible
from atelier.moteur import RELANCER, planifier
from atelier.projets import Projets, creer_depot, lire_profil, ouvrir_depot
from atelier.serveur import PAGE, POLICES, Atelier, SuiviMiseAJour, creer_serveur, prendre_le_depot

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
        "C": ["ne_sait_pas", "ok"],
        "D": ["deborde", "ok"],
        "E": ["bacle", "ok"],
    }
    return plan, scenario


def projet_simule(dossier: Path, nom: str, delai_s: float) -> Atelier:
    """Monte un projet de démonstration : un dossier vide et des agents simulés."""
    dossier.mkdir(parents=True, exist_ok=True)
    plan, scenario = plan_de_demonstration()
    chantier = Chantier(projet=nom, contrat=Contrat(objectif=""))
    # Des gestes réguliers pendant que les agents patientent : leurs courbes d'activité vivent.
    agent = AgentSimule(scenario, delai_s, plan=plan, gestes_s=0.35)
    # Un vrai guichet : la demande d'exemple du premier ouvrier attend un clic sur la carte.
    guichet = Guichet()
    atelier = Atelier(
        dossier, chantier, agent, ControlesSimules(), {}, mode="démonstration", guichet=guichet
    )
    atelier.annoncer_connexion()
    return atelier


def atelier_de_demonstration(delai_s: float) -> Atelier:
    """Monte le projet de démonstration sur un dossier temporaire."""
    racine = Path(tempfile.mkdtemp(prefix="atelier-demo-"))
    return projet_simule(racine / "demonstration", "Projet de démonstration", delai_s)


def commande_demo(arguments) -> None:
    premier = atelier_de_demonstration(arguments.delai)
    projets = Projets(premier.depot.parent, lambda d, n: projet_simule(d, n, arguments.delai))
    projets.ajouter(premier)
    # Le double simulé : le bouton est visible, rien n'est appelé et le serveur ne s'arrête pas.
    suivi = SuiviMiseAJour(MiseAJourSimulee())
    suivi.demarrer()
    serveur = creer_serveur(projets, arguments.port, suivi)
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
        contrat=Contrat(objectif=arguments.objectif),
        taches=taches,
    )
    chantier.sauver(depot / ".atelier" / "etat.json")
    print(f"{len(taches)} tâches proposées. Lance « servir » pour relire et valider le contrat.")


class Lancement:
    """Ce que sait « servir » de son serveur : None tant que son port n'est pas pris."""

    serveur = None


LANCEMENT = Lancement()


def avec_annonce(fabrique):
    """Enveloppe une fabrique de projets : chaque projet ouvert annonce sa source de connexion.

    Le dépôt est d'abord verrouillé (`prendre_le_depot`), avant que son état ne soit relu ou
    écrit : si un autre Atelier le tient, le projet n'est pas ouvert, rien n'est écrit et
    l'erreur (`DepotOccupe`) le dit en clair. Le verrou reste à l'Atelier ouvert
    (`verrou_depot`). Si le serveur de « servir » a déjà pris son port, le projet ouvert reprend
    seul le chantier qu'un arrêt a interrompu (`Atelier.reprendre_apres_arret`).
    """

    def fabriquer(dossier, *arguments) -> Atelier:
        verrou = prendre_le_depot(dossier)
        try:
            atelier = fabrique(dossier, *arguments)
        except BaseException:
            verrou.relacher()
            raise
        atelier.verrou_depot = verrou
        atelier.annoncer_connexion()
        if LANCEMENT.serveur is not None:
            atelier.reprendre_apres_arret(LANCEMENT.serveur)
        return atelier

    return fabriquer


def monter_projets(arguments) -> tuple[Projets, Path]:
    """Ouvre les projets de `servir` : chacun annonce sa source de connexion à son ouverture."""
    if arguments.depot is None and arguments.racine is None:
        arguments.depot = "."
    depot = Path(arguments.depot).resolve() if arguments.depot else None
    racine = Path(arguments.racine).expanduser().resolve() if arguments.racine else depot.parent
    racine.mkdir(parents=True, exist_ok=True)
    projets = Projets(racine, avec_annonce(creer_depot), avec_annonce(ouvrir_depot))
    if depot:
        projets.ajouter(avec_annonce(ouvrir_depot)(depot))
    projets.decouvrir()
    projets.ouvrir_le_premier()
    return projets, racine


def arreter_le_processus() -> None:
    """Sort avec le code 0 : l'agent de lancement (KeepAlive à vrai) relance Atelier."""
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)


def commande_servir(arguments) -> None:
    """Ouvre les projets (chacun verrouillé), prend le port, puis seulement reprend les chantiers
    qu'un arrêt a interrompus : un second Atelier sur le même dépôt s'arrête avant, en clair."""
    try:
        projets, racine = monter_projets(arguments)
    except ProjetImpossible as erreur:  # un dépôt déjà tenu par un autre Atelier, par exemple
        raise SystemExit(f"Atelier ne peut pas démarrer : {erreur}") from erreur
    # La mise à jour vise le dossier d'Atelier lui-même (celui qui contient le paquet), jamais
    # le dépôt d'un projet servi.
    suivi = SuiviMiseAJour(MiseAJour(Path(__file__).resolve().parent.parent), arreter_le_processus)
    suivi.demarrer()
    try:
        serveur = creer_serveur(projets, arguments.port, suivi)
    except OSError as erreur:  # le port est déjà pris : rien ne repart, rien n'est relancé
        raise SystemExit(
            f"Atelier ne peut pas démarrer : le port {arguments.port} n'a pas pu être pris "
            f"({erreur.strerror or erreur}). Un autre Atelier tourne peut-être déjà."
        ) from erreur
    print(f"Tableau de bord : http://127.0.0.1:{arguments.port}")
    print(f"Les nouveaux projets seront créés dans : {racine}")
    LANCEMENT.serveur = serveur
    try:
        for atelier in list(projets.ateliers.values()):
            atelier.reprendre_apres_arret(serveur)
        serveur.serve_forever()
    finally:
        LANCEMENT.serveur = None


def _attendre_une_autorisation(atelier: Atelier, delai_s: float = 10.0) -> str:
    """Attend la demande d'autorisation simulée et rend son identifiant."""
    limite = time.monotonic() + delai_s
    while time.monotonic() < limite:
        ouvertes = atelier.guichet.ouvertes()
        if ouvertes:
            return ouvertes[0]["id"]
        time.sleep(0.01)
    raise SystemExit("La démonstration n'a pas déposé sa demande d'autorisation.")


def polices_embarquees(page: str) -> str:
    """La page autonome s'ouvre sans serveur : ses polices y sont écrites en entier (data:)."""
    page = re.sub(r'<link rel="preload" href="/polices/[^"]+"[^>]*>\n?', "", page)
    for adresse, (fichier, nature) in POLICES.items():
        donnees = base64.b64encode(fichier.read_bytes()).decode("ascii")
        page = page.replace(f'url("{adresse}")', f'url("data:{nature};base64,{donnees}")')
    return page


def commande_instantanes(arguments) -> None:
    """Joue la démonstration d'une traite et l'inscrit dans une page autonome."""
    atelier = atelier_de_demonstration(0.0)
    vues = [atelier.vue()]
    atelier.sur_vue = vues.append
    atelier.message(OBJECTIF_DEMO)
    atelier.fil_message.join()
    atelier.valider_contrat()
    autorisation = _attendre_une_autorisation(atelier)
    vues.append(atelier.vue())  # la carte d'autorisation est ouverte
    atelier.autoriser(autorisation, "une_fois")  # la même voie qu'un clic sur la carte
    atelier.fil.join()
    demande = atelier.moteur.chantier.demandes[0]["id"]
    vues.append(atelier.vue())
    atelier.decider(demande, RELANCER)
    atelier.fil.join()
    vues.append(atelier.vue())
    page = PAGE.read_text("utf-8").replace(
        "/*INSTANTANES*/[]", json.dumps(vues, ensure_ascii=False).replace("</", "<\\/")
    )
    Path(arguments.sortie).write_text(polices_embarquees(page), "utf-8")
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
    servir.add_argument("--depot", help="Projet à ouvrir (par défaut : le dossier courant).")
    servir.add_argument("--port", type=int, default=8765)
    aide = "Dossier où créer les nouveaux projets (par défaut : le parent du dépôt)."
    servir.add_argument("--racine", help=aide)
    servir.set_defaults(action=commande_servir)

    essai = commandes.add_parser(
        "essai", help="Essai réel de bout en bout, sur un dépôt jetable (vrais agents)."
    )
    aide = "Où créer le dépôt jetable (par défaut : un dossier temporaire)."
    essai.add_argument("--dossier", help=aide)
    aide = "Sans l'essai du bouton « Arrêter »."
    essai.add_argument("--sans-arret", action="store_true", help=aide)
    essai.set_defaults(action=lambda a: __import__("atelier.essai").essai.commande_essai(a))

    instantanes = commandes.add_parser("instantanes", help="Page autonome de démonstration.")
    instantanes.add_argument("sortie")
    instantanes.set_defaults(action=commande_instantanes)

    arguments = analyseur.parse_args()
    arguments.action(arguments)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        raise SystemExit(0) from None
