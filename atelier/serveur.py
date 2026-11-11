"""Le serveur local : il fait tourner le moteur et alimente le tableau de bord.

Il n'écoute que sur la machine elle-même (127.0.0.1) : rien n'est exposé au réseau.
"""

from __future__ import annotations

import json
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from atelier import dosage
from atelier.consignes import (
    BALISE_OUTILS,
    BALISE_PLAN,
    extraire_outils,
    extraire_plan,
    message_avec_etat,
)
from atelier.modele import ETATS_FR, Chantier, Contrat, ProjetImpossible, ecrire_cahier
from atelier.moteur import Moteur, taches_du_plan

PAGE = Path(__file__).parent / "tableau" / "index.html"
ICONE = Path(__file__).parent / "tableau" / "icone.png"
MANIFESTE = json.dumps(
    {
        "name": "Atelier",
        "short_name": "Atelier",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#2b2c2f",
        "theme_color": "#2b2c2f",
        "icons": [{"src": "/icone.png", "sizes": "1024x1024", "type": "image/png"}],
    },
    ensure_ascii=False,
).encode("utf-8")


def point_d_etape(chantier: Chantier, en_marche: bool) -> str:
    """Dit en deux phrases où en est le chantier et si la personne responsable est attendue."""
    taches = chantier.taches
    verifiees = sum(t.etat == "verifie" for t in taches)
    en_cours = sum(t.etat in ("en_cours", "en_verification") for t in taches)
    attente = sum(d["reponse"] is None for d in chantier.demandes)
    bilan = f"{verifiees} tâches vérifiées sur {len(taches)}"
    if not taches:
        return "Aucun chantier en cours. Dis-moi ce que tu veux construire."
    if not chantier.contrat.valide:
        return "Le contrat de chantier attend ta validation. Rien ne démarre avant."
    if attente:
        pluriel = "décisions" if attente > 1 else "décision"
        return f"{bilan}. J'ai besoin de toi pour {attente} {pluriel}."
    if chantier.termine:
        return f"Chantier terminé : {bilan}. Tout est enregistré."
    if en_marche:
        return f"{bilan}, {en_cours} en cours. Je n'ai pas besoin de toi pour l'instant."
    return f"{bilan}. Le chantier est à l'arrêt."


def statistiques(chantier: Chantier) -> list[dict]:
    """Compte, par type de tâche, les réussites du premier coup et les refus."""
    lignes = []
    for cle, nom in dosage.TYPES_FR.items():
        taches = [t for t in chantier.taches if t.type == cle]
        if not taches:
            continue
        refus = sum(sum(h["issue"] != "valide" for h in t.historique) for t in taches)
        premier_coup = sum(t.etat == "verifie" and t.tentatives == 1 for t in taches)
        lignes.append({"type": nom, "premier_coup": premier_coup, "refus": refus})
    return lignes


def vue(chantier: Chantier, en_marche: bool, mode: str, occupe=False, brouillon=None) -> dict:
    """Prépare tout ce que le tableau de bord affiche."""
    donnees = chantier.en_dict()
    for tache in donnees["taches"]:
        tache["etat_fr"] = ETATS_FR.get(tache["etat"], tache["etat"])
        tache["dosage_fr"] = dosage.libelle(tache["modele"], tache["effort"])
        verificateur = dosage.verificateur(tache["modele"], tache["effort"])
        tache["verificateur_fr"] = dosage.libelle(*verificateur)
    contrat = donnees["contrat"]
    contrat["plafond_fr"] = dosage.libelle(contrat["plafond_modele"], contrat["plafond_effort"])
    donnees["point_d_etape"] = point_d_etape(chantier, en_marche)
    donnees["statistiques"] = statistiques(chantier)
    donnees["en_marche"] = en_marche
    donnees["occupe"] = occupe
    donnees["brouillon"] = brouillon or {"texte": "", "outils": []}
    donnees["mode"] = mode
    return donnees


ACCEPTER_OUTILS, REFUSER_OUTILS = "Accepter ce réglage", "Refuser"


class Atelier:
    """Relie un dépôt, un chantier, le moteur et le tableau de bord."""

    def __init__(self, depot: Path, chantier: Chantier, agent, controles, profil, mode="réel"):
        self.depot = Path(depot)
        self.mode = mode
        self.fil: threading.Thread | None = None
        self.fil_message: threading.Thread | None = None
        self.occupe = False
        self.brouillon = {"texte": "", "outils": []}
        self.sur_vue = None
        self.moteur = Moteur(chantier, agent, controles, profil, sur_changement=self._sauver)
        if not chantier.taches and not chantier.evenements:
            accueil = "Bonjour. Dis-moi ce que tu veux construire, je te proposerai un découpage."
            chantier.noter(accueil, auteur="orchestrateur")
        self._sauver()

    def _sauver(self) -> None:
        with self.moteur.verrou:
            chantier = self.moteur.chantier
            chantier.sauver(self.depot / ".atelier" / "etat.json")
            ecrire_cahier(chantier, self.depot / "chantier" / "CAHIER.md")
            if self.sur_vue:
                self.sur_vue(self.vue())

    def en_marche(self) -> bool:
        return bool(self.fil and self.fil.is_alive())

    def vue(self) -> dict:
        with self.moteur.verrou:
            brouillon = {
                "texte": self.brouillon["texte"].split(BALISE_PLAN)[0].split(BALISE_OUTILS)[0],
                "outils": list(self.brouillon["outils"]),
            }
            donnees = vue(self.moteur.chantier, self.en_marche(), self.mode, self.occupe, brouillon)
        controles = self.moteur.controles
        if hasattr(controles, "distant"):
            donnees["distant"] = {"adresse": controles.distant(), "probleme": controles.envoi}
        return donnees

    def relier(self, adresse: str) -> None:
        """Relie le projet à un dépôt en ligne (GitHub ou autre)."""
        if not hasattr(self.moteur.controles, "relier"):
            raise ProjetImpossible("La démonstration n'a pas de vrai dépôt à relier.")
        try:
            self.moteur.controles.relier(adresse)
        except ValueError as erreur:
            raise ProjetImpossible(str(erreur)) from erreur

    def lancer(self) -> None:
        """Démarre le moteur en arrière-plan, s'il ne tourne pas déjà."""
        if not self.en_marche():
            self.fil = threading.Thread(target=self.moteur.executer, daemon=True)
            self.fil.start()

    def valider_contrat(self) -> None:
        with self.moteur.verrou:
            self.moteur.chantier.contrat.valide = True
            self.moteur.chantier.noter("Contrat validé. Je lance le chantier.")
        self._sauver()
        self.lancer()

    def decider(self, demande_id: str, choix: str) -> None:
        demande = next(d for d in self.moteur.chantier.demandes if d["id"] == demande_id)
        if demande.get("nature") == "outils":
            return self._regler_outils(demande, choix)
        self.moteur.repondre(demande_id, choix)
        self.lancer()

    # --- les outils du projet ----------------------------------------------------

    def _proposer_outils(self, outils: dict) -> None:
        """Transforme un réglage d'outils proposé par l'orchestrateur en décision à prendre."""

        def liste(cle: str) -> list[str] | None:
            valeur = outils.get(cle)
            if not isinstance(valeur, list):
                return None
            return [v.strip() for v in valeur if isinstance(v, str) and v.strip()]

        permises, controles = liste("commandes_permises"), liste("commandes")
        if not permises and controles is None:
            return self._dire("(Le réglage d'outils proposé était illisible : rien n'a changé.)")
        parties = ["L'orchestrateur propose de régler les outils du projet."]
        if permises:
            parties.append("Commandes permises aux agents : " + ", ".join(permises) + ".")
        if controles is not None:
            rejoues = " ; ".join(controles) if controles else "aucun"
            parties.append(f"Contrôles rejoués par l'atelier après chaque livrable : {rejoues}.")
        if str(outils.get("pourquoi") or "").strip():
            parties.append(f"Pourquoi : {str(outils['pourquoi']).strip()}")
        with self.moteur.verrou:
            demandes = self.moteur.chantier.demandes
            demandes.append(
                {
                    "id": f"outils-{len(demandes) + 1}",
                    "tache": None,
                    "nature": "outils",
                    "question": " ".join(parties),
                    "options": [ACCEPTER_OUTILS, REFUSER_OUTILS],
                    "reponse": None,
                    "outils": {"commandes_permises": permises, "commandes": controles},
                }
            )

    def _regler_outils(self, demande: dict, choix: str) -> None:
        """Applique (ou écarte) un réglage d'outils, l'écrit dans le profil et le fait valoir."""
        with self.moteur.verrou:
            if demande["reponse"] is not None:
                return
            demande["reponse"] = choix
        if choix != ACCEPTER_OUTILS:
            return self._dire("Réglage des outils écarté : rien n'a changé.")
        chemin = self.depot / "chantier" / "profil.json"
        fichier = json.loads(chemin.read_text("utf-8")) if chemin.exists() else {}
        actuelles = fichier.get(
            "commandes_permises", self.moteur.profil.get("commandes_permises", [])
        )
        permises = list(
            dict.fromkeys([*actuelles, *(demande["outils"]["commandes_permises"] or [])])
        )
        fichier["commandes_permises"] = permises
        if demande["outils"]["commandes"] is not None:
            fichier["commandes"] = demande["outils"]["commandes"]
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_text(json.dumps(fichier, ensure_ascii=False, indent=2) + "\n", "utf-8")
        # Le même profil est lu par l'atelier, le moteur et les agents : tous suivent tout de suite.
        lus = (self.moteur.profil, getattr(self.moteur.agent, "profil", None))
        for profil in {id(p): p for p in lus if isinstance(p, dict)}.values():
            profil["commandes_permises"] = permises
            if "commandes" in fichier:
                profil["commandes"] = fichier["commandes"]
        if hasattr(self.moteur.controles, "regler_outils"):
            self.moteur.controles.regler_outils(fichier)
        self._dire(
            "Outils réglés. Commandes permises aux agents : " + ", ".join(permises) + ". "
            "Une tâche revenue vers toi peut maintenant être relancée."
        )
        self._sauver()

    # --- la conversation ---------------------------------------------------------

    def message(self, texte: str) -> None:
        """Reçoit un message de la personne responsable et y répond en arrière-plan."""
        texte = texte.strip()
        if not texte or self.occupe:
            return
        with self.moteur.verrou:
            self.moteur.chantier.noter(texte, auteur="toi")
            self.occupe = True
        self._sauver()
        self.fil_message = threading.Thread(target=self._traiter, args=(texte,), daemon=True)
        self.fil_message.start()

    def _traiter(self, texte: str) -> None:
        try:
            self._recevoir(texte, self._interroger(texte))
        finally:
            with self.moteur.verrou:
                self.occupe = False
                self.brouillon = {"texte": "", "outils": []}
            self._sauver()

    def _dire(self, texte: str) -> None:
        with self.moteur.verrou:
            self.moteur.chantier.noter(texte, auteur="orchestrateur")

    def _etat_en_clair(self) -> str:
        chantier = self.moteur.chantier
        lignes = [point_d_etape(chantier, self.en_marche())]
        lignes += [f"- {t.id} {t.titre} : {ETATS_FR.get(t.etat, t.etat)}" for t in chantier.taches]
        permises = ", ".join(self.moteur.profil.get("commandes_permises", [])) or "aucune"
        lignes.append(f"Commandes permises aux agents : {permises}")
        rejoues = " ; ".join(self.moteur.profil.get("commandes", [])) or "aucun"
        lignes.append(f"Contrôles rejoués par l'atelier après chaque livrable : {rejoues}")
        controles = self.moteur.controles
        if hasattr(controles, "distant"):
            adresse = controles.distant()
            lignes.append(f"Dépôt en ligne : {adresse}" if adresse else "Dépôt en ligne : aucun")
            if controles.envoi:
                lignes.append(f"Dernier envoi en échec : {controles.envoi}")
        return "\n".join(lignes)

    def _interroger(self, texte: str):
        """Envoie le message à la session Claude Code de l'orchestrateur, gardée d'un message
        à l'autre, et suit sa réponse pendant qu'elle s'écrit."""
        chantier = self.moteur.chantier
        with self.moteur.verrou:
            reprise = bool(chantier.session)
            session = chantier.session or str(uuid.uuid4())
            chantier.session = session
            message = message_avec_etat(self._etat_en_clair(), texte)
            contexte = {"chantier": bool(chantier.taches)}

        def sur_texte(morceau: str) -> None:
            self.brouillon["texte"] += morceau

        reponse = self.moteur.agent.converser(
            message,
            session,
            reprise,
            self.depot,
            sur_texte,
            self.brouillon["outils"].append,
            contexte,
        )
        if not reponse.ok and not reprise:
            chantier.session = ""
        return reponse

    def _recevoir(self, demande: str, reponse) -> None:
        """Affiche la réponse de l'orchestrateur et, s'il rend un plan, prépare le contrat."""
        if not reponse.ok:
            return self._dire(f"Je n'ai pas pu joindre Claude Code. {reponse.erreur}")
        texte, outils = extraire_outils(reponse.texte)
        texte, plan = extraire_plan(texte)
        with self.moteur.verrou:
            self.moteur.chantier.cout_usd += reponse.cout_usd
            self.moteur.chantier.tokens += reponse.tokens
        self._dire(texte or "Voici le plan.")
        if outils:
            self._proposer_outils(outils)
        if plan:
            self._adopter(plan, demande)

    def _adopter(self, plan: dict, demande: str) -> None:
        """Transforme le plan rendu en tâches et en contrat à valider."""
        chantier, agent = self.moteur.chantier, self.moteur.agent
        taches = taches_du_plan(plan, self.moteur.profil)
        with self.moteur.verrou:
            if chantier.contrat.valide and not chantier.termine:
                return chantier.noter("Plan non repris : le contrat est déjà validé.")
            if not taches:
                return chantier.noter("Le plan rendu ne contenait aucune tâche lisible.")
            chantier.taches, chantier.demandes, chantier.termine = taches, [], False
            chantier.agents_lances = chantier.montees = 0
            chantier.contrat = Contrat(
                objectif=str(plan.get("objectif") or demande),
                hors_perimetre=str(plan.get("hors_perimetre") or ""),
                max_agents=3 * len(taches) + 2,
            )
            chantier.noter(f"Plan reçu : {len(taches)} tâches. Le contrat attend ta validation.")
        if hasattr(agent, "perimetres"):
            agent.perimetres = {t.id: t.perimetre for t in taches}


class Requetes(BaseHTTPRequestHandler):
    """Répond aux demandes du tableau de bord, pour le projet affiché."""

    projets = None  # les projets de l'atelier (atelier.projets.Projets)

    @property
    def atelier(self) -> Atelier:
        return self.projets.atelier()

    def log_message(self, *arguments) -> None:
        return None

    def _repondre(self, code: int, corps: bytes, nature: str) -> None:
        self.send_response(code)
        binaire = nature.startswith("image/")
        self.send_header("Content-Type", nature if binaire else f"{nature}; charset=utf-8")
        self.send_header("Content-Length", str(len(corps)))
        self.end_headers()
        self.wfile.write(corps)

    def _json(self, donnees: dict, code: int = 200) -> None:
        corps = json.dumps(donnees, ensure_ascii=False).encode("utf-8")
        self._repondre(code, corps, "application/json")

    def do_GET(self) -> None:
        if self.path == "/api/etat":
            return self._json(self.projets.vue())
        if self.path in ("/", "/index.html"):
            return self._repondre(200, PAGE.read_bytes(), "text/html")
        if self.path in ("/icone.png", "/apple-touch-icon.png", "/favicon.ico"):
            return self._repondre(200, ICONE.read_bytes(), "image/png")
        if self.path == "/manifest.webmanifest":
            return self._repondre(200, MANIFESTE, "application/manifest+json")
        return self._json({"erreur": "Adresse inconnue."}, 404)

    def do_POST(self) -> None:
        longueur = int(self.headers.get("Content-Length") or 0)
        try:
            corps = json.loads(self.rfile.read(longueur) or b"{}")
            if self.path == "/api/contrat/valider":
                self.atelier.valider_contrat()
            elif self.path == "/api/decision":
                self.atelier.decider(corps["id"], corps["choix"])
            elif self.path == "/api/message":
                self.atelier.message(corps["texte"])
            elif self.path == "/api/projets/creer":
                self.projets.creer(corps["nom"])
            elif self.path == "/api/projets/cloner":
                self.projets.cloner(corps["adresse"])
            elif self.path == "/api/projet/relier":
                self.atelier.relier(corps["adresse"])
            elif self.path == "/api/projets/ouvrir":
                self.projets.ouvrir(corps["id"])
            else:
                return self._json({"erreur": "Adresse inconnue."}, 404)
        except ProjetImpossible as erreur:
            return self._json({"erreur": str(erreur)}, 400)
        except (KeyError, StopIteration, ValueError):
            return self._json({"erreur": "Demande introuvable ou incomplète."}, 400)
        return self._json(self.projets.vue())


def creer_serveur(projets, port: int = 8765) -> ThreadingHTTPServer:
    """Crée le serveur du tableau de bord, limité à la machine locale."""
    gestionnaire = type("RequetesLiees", (Requetes,), {"projets": projets})
    return ThreadingHTTPServer(("127.0.0.1", port), gestionnaire)
