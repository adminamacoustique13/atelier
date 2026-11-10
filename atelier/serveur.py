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
from atelier.consignes import BALISE_PLAN, extraire_plan, message_avec_etat
from atelier.modele import ETATS_FR, Chantier, Contrat, ecrire_cahier
from atelier.moteur import Moteur, taches_du_plan

PAGE = Path(__file__).parent / "tableau" / "index.html"


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
        return f"Chantier terminé : {bilan}. Tout est enregistré"
    if en_marche:
        return f"{bilan}, {en_cours} en cours. Je n'ai pas besoin de toi pour l'instant"
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
    contrat = donnees["contrat"]
    contrat["plafond_fr"] = dosage.libelle(contrat["plafond_modele"], contrat["plafond_effort"])
    donnees["point_d_etape"] = point_d_etape(chantier, en_marche)
    donnees["statistiques"] = statistiques(chantier)
    donnees["en_marche"] = en_marche
    donnees["occupe"] = occupe
    donnees["brouillon"] = brouillon or {"texte": "", "outils": []}
    donnees["mode"] = mode
    return donnees


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
            accueil = "Bonjour Dis-moi ce que tu veux construire, je te proposerai un découpage."
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
                "texte": self.brouillon["texte"].split(BALISE_PLAN)[0],
                "outils": list(self.brouillon["outils"]),
            }
            return vue(self.moteur.chantier, self.en_marche(), self.mode, self.occupe, brouillon)

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
        self.moteur.repondre(demande_id, choix)
        self.lancer()

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
        texte, plan = extraire_plan(reponse.texte)
        with self.moteur.verrou:
            self.moteur.chantier.cout_usd += reponse.cout_usd
            self.moteur.chantier.tokens += reponse.tokens
        self._dire(texte or "Voici le plan.")
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
    """Répond aux demandes du tableau de bord."""

    atelier: Atelier

    def log_message(self, *arguments) -> None:
        return None

    def _repondre(self, code: int, corps: bytes, nature: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", f"{nature}; charset=utf-8")
        self.send_header("Content-Length", str(len(corps)))
        self.end_headers()
        self.wfile.write(corps)

    def _json(self, donnees: dict, code: int = 200) -> None:
        corps = json.dumps(donnees, ensure_ascii=False).encode("utf-8")
        self._repondre(code, corps, "application/json")

    def do_GET(self) -> None:
        if self.path == "/api/etat":
            return self._json(self.atelier.vue())
        if self.path in ("/", "/index.html"):
            return self._repondre(200, PAGE.read_bytes(), "text/html")
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
            else:
                return self._json({"erreur": "Adresse inconnue."}, 404)
        except (KeyError, StopIteration, ValueError):
            return self._json({"erreur": "Demande introuvable ou incomplète."}, 400)
        return self._json(self.atelier.vue())


def creer_serveur(atelier: Atelier, port: int = 8765) -> ThreadingHTTPServer:
    """Crée le serveur du tableau de bord, limité à la machine locale."""
    gestionnaire = type("RequetesLiees", (Requetes,), {"atelier": atelier})
    return ThreadingHTTPServer(("127.0.0.1", port), gestionnaire)
