"""Le serveur local : il fait tourner le moteur et alimente le tableau de bord.

Il n'écoute que sur la machine elle-même (127.0.0.1) : rien n'est exposé au réseau.
"""

from __future__ import annotations

import json
import threading
import uuid
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from atelier import dosage
from atelier.agents import AgentSimule
from atelier.consignes import (
    BALISE_OUTILS,
    BALISE_PLAN,
    extraire_outils,
    extraire_plan,
    message_avec_etat,
)
from atelier.guichet import ARRETE, CHOIX, Guichet
from atelier.modele import ETATS_FR, Chantier, Contrat, ProjetImpossible, ecrire_cahier
from atelier.moteur import ARRETEE, Moteur, taches_du_plan

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


def point_d_etape(chantier: Chantier, en_marche: bool, autorisations: int = 0) -> str:
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
    if attente or autorisations:
        besoins = [(attente, "décision"), (autorisations, "autorisation")]
        mots = [f"{n} {nom}{'s' if n > 1 else ''}" for n, nom in besoins if n]
        return f"{bilan}. J'ai besoin de toi pour {' et '.join(mots)}."
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
        issues = [h["issue"] for t in taches for h in t.historique]
        refus = sum(issue not in ("valide", ARRETEE) for issue in issues)
        premier_coup = sum(t.etat == "verifie" and t.tentatives == 1 for t in taches)
        lignes.append({"type": nom, "premier_coup": premier_coup, "refus": refus})
    return lignes


def vue(
    chantier: Chantier, en_marche: bool, mode: str, occupe=False, brouillon=None, autorisations=0
) -> dict:
    """Prépare tout ce que le tableau de bord affiche."""
    donnees = chantier.en_dict()
    for tache in donnees["taches"]:
        tache["etat_fr"] = ETATS_FR.get(tache["etat"], tache["etat"])
        tache["dosage_fr"] = dosage.libelle(tache["modele"], tache["effort"])
        verificateur = dosage.verificateur(tache["modele"], tache["effort"])
        tache["verificateur_fr"] = dosage.libelle(*verificateur)
    contrat = donnees["contrat"]
    contrat["plafond_fr"] = dosage.libelle(contrat["plafond_modele"], contrat["plafond_effort"])
    donnees["point_d_etape"] = point_d_etape(chantier, en_marche, autorisations)
    donnees["statistiques"] = statistiques(chantier)
    donnees["en_marche"] = en_marche
    donnees["occupe"] = occupe
    donnees["brouillon"] = brouillon or {"texte": "", "outils": []}
    donnees["mode"] = mode
    return donnees


LIGNES_MAX = 30  # lignes d'activité gardées par agent
LARGEUR_MAX = 300  # caractères par ligne d'activité
MORCEAU_MAX = LIGNES_MAX * LARGEUR_MAX  # de quoi remplir toutes les lignes : le reste est perdu
AGENTS_MAX = 40  # agents gardés : au-delà, les plus anciens sont retirés


class Activite:
    """Les dernières lignes d'activité de chaque agent en marche, en mémoire et bornées.

    `ajouter` est le rappel `sur_evenement` des agents : il tourne dans la boucle de leur
    session et ne fait que ranger l'événement, sous un verrou, sans rien écrire ni attendre.
    """

    def __init__(self):
        self._verrou = threading.Lock()
        self._lignes: dict[str, deque[str]] = {}
        self._reste: dict[str, str] = {}  # le texte reçu qui n'est pas encore une ligne entière

    def _ranger(self, nom: str, texte: str) -> None:
        lignes = self._lignes[nom]
        for ligne in texte.split("\n"):
            ligne = ligne.strip()
            lignes.extend(ligne[i : i + LARGEUR_MAX] for i in range(0, len(ligne), LARGEUR_MAX))

    def ajouter(self, evenement: dict) -> None:
        """Range un événement `{"agent", "type", "contenu"}` ; un « fin » retire l'agent."""
        try:
            nom, genre = str(evenement["agent"]), evenement["type"]
            contenu = str(evenement["contenu"])[-MORCEAU_MAX:]  # un morceau démesuré est coupé
        except (KeyError, TypeError):
            return
        with self._verrou:
            if genre == "fin":
                self._lignes.pop(nom, None)
                self._reste.pop(nom, None)
                return
            self._lignes.setdefault(nom, deque(maxlen=LIGNES_MAX))
            while len(self._lignes) > AGENTS_MAX:  # sans « fin », on oublie les plus anciens
                ancien = next(iter(self._lignes))
                del self._lignes[ancien]
                self._reste.pop(ancien, None)
            if genre == "texte":
                recu = self._reste.get(nom, "") + contenu.replace("\r", "")
                *entieres, reste = recu.split("\n")
                self._ranger(nom, "\n".join(entieres))
                coupe = len(reste) - len(reste) % LARGEUR_MAX  # le reste reste borné lui aussi
                self._ranger(nom, reste[:coupe])
                self._reste[nom] = reste[coupe:]
                return
            self._ranger(nom, self._reste.pop(nom, ""))
            if genre == "attente":
                contenu = f"En attente de ton autorisation : {contenu}"
            self._ranger(nom, contenu)

    def agents(self) -> list[dict]:
        """Rend, pour chaque agent en marche, son nom, sa tâche, son rôle et ses lignes."""
        with self._verrou:
            vus = [(n, [*lignes, self._reste.get(n, "")]) for n, lignes in self._lignes.items()]
        agents = []
        for nom, lignes in vus:
            morceaux = nom.rsplit("-", 2)
            tache, role = (morceaux[0], morceaux[1]) if len(morceaux) == 3 else ("", nom)
            lignes = [ligne.strip() for ligne in lignes if ligne.strip()]
            lignes = lignes[-LIGNES_MAX:]
            agents.append({"nom": nom, "tache": tache, "role": role, "lignes": lignes})
        return agents


ACCEPTER_OUTILS, REFUSER_OUTILS = "Accepter ce réglage", "Refuser"


class Atelier:
    """Relie un dépôt, un chantier, le moteur et le tableau de bord."""

    def __init__(
        self, depot: Path, chantier: Chantier, agent, controles, profil, mode="réel", guichet=None
    ):
        self.depot = Path(depot)
        self.mode = mode
        self.activite = Activite()
        self._verrou_profil = threading.Lock()
        # Un vrai agent reçoit un vrai guichet. Un agent simulé n'en reçoit un que si on le lui
        # donne : sans personne pour répondre, sa demande d'exemple attendrait le délai du guichet.
        guichet = guichet or getattr(agent, "guichet", None)
        if guichet is None and not isinstance(agent, AgentSimule):
            guichet = Guichet()
        self.guichet = guichet
        if guichet is not None:
            agent.guichet = guichet
        agent.sur_evenement = self.activite.ajouter
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
        autorisations = self.guichet.ouvertes() if self.guichet else []
        with self.moteur.verrou:
            brouillon = {
                "texte": self.brouillon["texte"].split(BALISE_PLAN)[0].split(BALISE_OUTILS)[0],
                "outils": list(self.brouillon["outils"]),
            }
            donnees = vue(
                self.moteur.chantier,
                self.en_marche(),
                self.mode,
                self.occupe,
                brouillon,
                len(autorisations),
            )
        donnees["autorisations"] = autorisations
        donnees["agents"] = self.activite.agents()
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
        with self._verrou_profil:  # le même verrou que pour une règle « toujours »
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
            valeurs = {"commandes_permises": permises}
            if "commandes" in fichier:
                valeurs["commandes"] = fichier["commandes"]
            self._propager(valeurs)
        if hasattr(self.moteur.controles, "regler_outils"):
            self.moteur.controles.regler_outils(fichier)
        self._dire(
            "Outils réglés. Commandes permises aux agents : " + ", ".join(permises) + ". "
            "Une tâche revenue vers toi peut maintenant être relancée."
        )
        self._sauver()

    def _propager(self, valeurs: dict) -> None:
        """Met à jour à chaud les profils lus par l'atelier, le moteur et les agents."""
        lus = (self.moteur.profil, getattr(self.moteur.agent, "profil", None))
        for profil in {id(p): p for p in lus if isinstance(p, dict)}.values():
            profil.update(valeurs)

    # --- les autorisations demandées par les agents ------------------------------

    def autoriser(self, identifiant, choix, message="") -> dict:
        """Répond à une demande d'autorisation ouverte et dit si elle a été réglée.

        « Toujours » ajoute la règle de la demande aux autorisations du profil du projet.
        """
        message = message if isinstance(message, str) else ""
        demande = next((d for d in self._ouvertes() if d["id"] == identifiant), None)
        regle = demande["regle"] if demande else ""
        if self.guichet is not None and self.guichet.repondre(identifiant, choix, message):
            return {"reglee": True, "phrase": self._retenir(choix, regle)}
        if choix not in CHOIX:
            phrase = "Ce choix n'existe pas : réponds « une fois », « toujours » ou « non »."
        elif demande is None:
            phrase = (
                "Cette demande n'existe plus : elle a déjà reçu une réponse, "
                "ou son agent s'est arrêté."
            )
        elif not regle:
            phrase = (
                "Aucune règle sûre n'existe pour cette demande : "
                "autorise-la une fois, ou refuse-la."
            )
        else:
            phrase = "La demande n'a pas pu être réglée."
        return {"reglee": False, "phrase": phrase}

    def _ouvertes(self) -> list[dict]:
        return self.guichet.ouvertes() if self.guichet is not None else []

    def _retenir(self, choix: str, regle: str) -> str:
        """Dit ce qui a été réglé ; pour « toujours », inscrit d'abord la règle au profil."""
        if choix == "non":
            return "Refusé."
        if choix == "une_fois":
            return "Autorisé cette fois."
        try:
            self._inscrire_regle(regle)
        except ValueError:
            raison = "le profil du projet (chantier/profil.json) n'est pas lisible, corrige-le."
        except OSError:
            raison = "le profil du projet (chantier/profil.json) n'a pas pu être écrit."
        else:
            with self.moteur.verrou:
                self.moteur.chantier.noter(f"Autorisation retenue pour ce projet : {regle}.")
            self._sauver()
            return f"Autorisé pour ce projet : la règle {regle} est enregistrée dans le profil."
        return f"Autorisé cette fois, mais la règle n'a pas pu être enregistrée : {raison}"

    def _inscrire_regle(self, regle: str) -> None:
        """Ajoute une règle, sans doublon, aux autorisations de `chantier/profil.json`."""
        with self._verrou_profil:
            chemin = self.depot / "chantier" / "profil.json"
            fichier = json.loads(chemin.read_text("utf-8")) if chemin.exists() else {}
            if not isinstance(fichier, dict):
                raise ValueError("le profil du projet n'est pas lisible")
            actuelles = fichier.get("autorisations", self.moteur.profil.get("autorisations"))
            regles = list(actuelles) if isinstance(actuelles, list) else []
            if regle not in regles:
                regles.append(regle)
                fichier["autorisations"] = regles
                chemin.parent.mkdir(parents=True, exist_ok=True)
                texte = json.dumps(fichier, ensure_ascii=False, indent=2) + "\n"
                chemin.write_text(texte, "utf-8")
            self._propager({"autorisations": regles})

    # --- l'arrêt -----------------------------------------------------------------

    def arreter(self, tache=None) -> dict:
        """Arrête l'agent d'une tâche, ou sans tâche la réponse en cours de l'orchestrateur."""
        if tache in (None, ""):
            if self.moteur.agent.arreter():
                return {"fait": True, "phrase": "Arrêt demandé : la réponse en cours s'arrête."}
            phrase = "L'orchestrateur ne répond à rien en ce moment : rien à arrêter."
            return {"fait": False, "phrase": phrase}
        if isinstance(tache, str) and self.moteur.arreter(tache):
            return {"fait": True, "phrase": f"Arrêt demandé pour la tâche {tache}."}
        if isinstance(tache, str) and self.moteur.enregistree(tache):
            phrase = (
                f"La tâche {tache} est déjà vérifiée : elle est enregistrée, "
                "trop tard pour l'arrêter."
            )
            return {"fait": False, "phrase": phrase}
        phrase = f"La tâche {tache} n'est ni en cours ni en vérification : rien à arrêter."
        return {"fait": False, "phrase": phrase}

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
        if not reponse.ok and not reprise and reponse.erreur != ARRETE:
            chantier.session = ""  # un arrêt, lui, garde la session : le message suivant la reprend
        return reponse

    def _recevoir(self, demande: str, reponse) -> None:
        """Affiche la réponse de l'orchestrateur et, s'il rend un plan, prépare le contrat."""
        if not reponse.ok and reponse.erreur == ARRETE:
            return self._arreter_reponse(reponse)
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

    def _arreter_reponse(self, reponse) -> None:
        """Garde ce que l'orchestrateur avait écrit, puis dit que sa réponse a été arrêtée."""
        with self.moteur.verrou:
            self.moteur.chantier.cout_usd += reponse.cout_usd
            self.moteur.chantier.tokens += reponse.tokens
            ecrit = self.brouillon["texte"].split(BALISE_PLAN)[0].split(BALISE_OUTILS)[0].strip()
        if ecrit:
            self._dire(ecrit)
        self._dire("(Réponse arrêtée par toi. Tu peux écrire la suite.)")

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
            action = ROUTES.get(self.path)
            if action is None:
                return self._json({"erreur": "Adresse inconnue."}, 404)
            if not isinstance(corps, dict):
                raise ValueError("corps illisible")
            en_plus = action(self, corps)
        except ProjetImpossible as erreur:
            return self._json({"erreur": str(erreur)}, 400)
        except (KeyError, StopIteration, ValueError):
            return self._json({"erreur": "Demande introuvable ou incomplète."}, 400)
        return self._json({**self.projets.vue(), **(en_plus or {})})


# Chaque route reçoit la requête et le corps lu ; elle peut rendre des champs de plus pour la
# réponse, qui est sinon la vue du tableau de bord.
ROUTES = {
    "/api/contrat/valider": lambda r, c: r.atelier.valider_contrat(),
    "/api/decision": lambda r, c: r.atelier.decider(c["id"], c["choix"]),
    "/api/message": lambda r, c: r.atelier.message(c["texte"]),
    "/api/projets/creer": lambda r, c: r.projets.creer(c["nom"]),
    "/api/projets/cloner": lambda r, c: r.projets.cloner(c["adresse"]),
    "/api/projet/relier": lambda r, c: r.atelier.relier(c["adresse"]),
    "/api/projets/ouvrir": lambda r, c: r.projets.ouvrir(c["id"]),
    "/api/autorisation": lambda r, c: {
        "autorisation": r.atelier.autoriser(c["id"], c["choix"], c.get("message", ""))
    },
    "/api/arreter": lambda r, c: {"arret": r.atelier.arreter(c.get("tache"))},
}


def creer_serveur(projets, port: int = 8765) -> ThreadingHTTPServer:
    """Crée le serveur du tableau de bord, limité à la machine locale."""
    gestionnaire = type("RequetesLiees", (Requetes,), {"projets": projets})
    return ThreadingHTTPServer(("127.0.0.1", port), gestionnaire)
