"""Le serveur local : il fait tourner le moteur et alimente le tableau de bord.

Il n'écoute que sur la machine elle-même (127.0.0.1) : rien n'est exposé au réseau.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
import uuid
from collections import deque
from contextlib import suppress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from atelier import archives, dosage
from atelier.agents import MODE_PAR_DEFAUT, MODES_OUVRIERS, AgentSimule, lire_mode, mode_valide
from atelier.carte import ExplicateurAuto, ExplicateurClaude, SuiviCarte, provisoire
from atelier.consignes import (
    BALISE_OUTILS,
    BALISE_PLAN,
    extraire_outils,
    extraire_plan,
    message_avec_etat,
)
from atelier.guichet import ARRETE, CHOIX, Guichet
from atelier.mise_a_jour import Etat, Resultat
from atelier.modele import ETATS_FR, Chantier, Contrat, ProjetImpossible, ecrire_cahier
from atelier.moteur import ARRETEE, Moteur, taches_du_plan
from atelier.rythme import TRANCHE_S, Rythmes

PAGE = Path(__file__).parent / "tableau" / "index.html"
ICONE = Path(__file__).parent / "tableau" / "icone.png"
# Les polices du tableau de bord, livrées avec l'Atelier : seules celles-ci sont servies.
POLICES = {
    f"/polices/{nom}": (Path(__file__).parent / "tableau" / "polices" / nom, nature)
    for nom, nature in (
        ("geist.woff2", "font/woff2"),
        ("geist-mono.woff2", "font/woff2"),
        ("doto.woff", "font/woff"),
    )
}
MANIFESTE = json.dumps(
    {
        "name": "Atelier",
        "short_name": "Atelier",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#000000",
        "theme_color": "#000000",
        "icons": [{"src": "/icone.png", "sizes": "1024x1024", "type": "image/png"}],
    },
    ensure_ascii=False,
).encode("utf-8")


VARIABLE_CLE = "ANTHROPIC_API_KEY"
CONNEXION_DEMO = (
    "Démonstration : les agents sont simulés, rien de réel n'est appelé et rien n'est facturé."
)
CONNEXION_CLE_PRESENTE = (
    "Une variable ANTHROPIC_API_KEY est présente dans l'environnement de l'Atelier : si Claude "
    "l'utilise, c'est cette clé API qui sera facturée, et non ton abonnement. Pour la retirer, "
    "regarde d'abord comment l'Atelier a été lancé : le LISEZMOI explique où elle est posée et "
    "la commande exacte pour l'enlever, puis comment relancer l'Atelier."
)
CONNEXION_ATTENDUE = (
    "Aucune variable ANTHROPIC_API_KEY dans l'environnement de l'Atelier. "
    "La source réelle de connexion sera dite dès que le premier agent aura commencé."
)
CONNEXION_ABONNEMENT = (
    "Le SDK de Claude annonce qu'aucune clé API n'est utilisée : le travail est compté sur ton "
    "abonnement Claude. Si tu n'es pas connecté à ton compte, ou si tu passes par une passerelle "
    "d'entreprise, ouvre le Terminal, lance « claude » puis tape « /status » pour le vérifier."
)
CONNEXION_ABONNEMENT_MALGRE_VARIABLE = (
    "Le SDK de Claude annonce qu'aucune clé API n'est utilisée, bien qu'une variable "
    "ANTHROPIC_API_KEY soit présente dans l'environnement de l'Atelier. Je n'en sais pas plus : "
    "pour vérifier ce qui est facturé, ouvre le Terminal, lance « claude » puis tape « /status »."
)
CONNEXION_CLE = (
    "Confirmé par le SDK de Claude : une clé API est utilisée, comme la variable "
    "ANTHROPIC_API_KEY le laissait prévoir. C'est cette clé qui est facturée, et non ton "
    "abonnement Claude."
)
CONNEXION_CLE_SANS_VARIABLE = (
    "Le SDK de Claude annonce qu'une clé API est utilisée, alors qu'aucune variable "
    "ANTHROPIC_API_KEY n'était visible : elle vient d'un réglage de Claude Code, ou d'une "
    "connexion faite avec une clé plutôt qu'avec ton abonnement. C'est cette clé qui est "
    "facturée, et non ton abonnement. Pour le vérifier, ouvre le Terminal, lance « claude » "
    "puis tape « /status ». Si tu t'es connecté avec une clé, tape « /login » et choisis ton "
    "compte ; si elle vient d'un réglage (un bloc « env » ou un « apiKeyHelper » de "
    "~/.claude/settings.json), retire ce réglage."
)
DEPARTS = (CONNEXION_DEMO, CONNEXION_CLE_PRESENTE, CONNEXION_ATTENDUE)
CONFIRMATIONS = (
    CONNEXION_ABONNEMENT,
    CONNEXION_ABONNEMENT_MALGRE_VARIABLE,
    CONNEXION_CLE,
    CONNEXION_CLE_SANS_VARIABLE,
)
# Quand le texte d'une phrase change, l'ancien texte s'ajoute ici. Il reste reconnu comme
# annonce de connexion mais ne vaut aucune phrase actuelle : l'annonce suivante est réécrite
# (une de trop au pire), et le fil ne reste jamais sur une ancienne phrase devenue fausse.
ANCIENNES_ANNONCES: tuple[str, ...] = ()
ANNONCES = DEPARTS + CONFIRMATIONS + ANCIENNES_ANNONCES  # reconnues à leur texte exact


# Le mode des ouvriers : le libellé du menu et ce que la personne responsable verra.
MODES_FR = {
    "default": (
        "Me demander",
        "Les ouvriers modifient les fichiers de leur copie, mais toute autre action qui n'est "
        "pas permise d'avance te demande une carte.",
    ),
    "acceptEdits": (
        "Accepter les modifications",
        "Les ouvriers modifient les fichiers et rangent les dossiers de leur copie sans "
        "demander, et le reste de ce qui n'est pas permis d'avance te demande une carte.",
    ),
    "plan": (
        "Répétition",
        "L'ouvrier prépare son plan et chaque modification de fichier te demande une carte, "
        "mais les commandes permises d'avance par le projet (comme python3 ou npm) tournent "
        "sans carte et peuvent écrire ; une dernière carte te demande s'il peut passer à "
        "l'exécution.",
    ),
    "dontAsk": (
        "Refuser sans demander",
        "Tout ce qui n'est pas permis d'avance est refusé sans carte, et l'ouvrier fait avec "
        "ce qui lui reste.",
    ),
    "auto": (
        "Laisser un arbitre décider",
        "Un modèle approuve ou refuse à ta place ce qui t'aurait demandé une carte, ainsi que "
        "les commandes qui exécutent du code même permises d'avance (le reste passe sans lui) ; "
        "ses refus s'affichent dans l'activité de l'agent, et après trop de refus les demandes "
        "te reviennent en cartes.",
    ),
}
CHOIX_MODES = [
    {"mode": mode, "libelle": MODES_FR[mode][0], "explication": MODES_FR[mode][1]}
    for mode in MODES_OUVRIERS
]


def libelle_mode(mode) -> str:
    """Le libellé français d'un mode ; un mode inconnu est rendu tel quel, coupé à 40 caractères."""
    connu = isinstance(mode, str) and mode in MODES_FR
    return MODES_FR[mode][0] if connu else " ".join(str(mode).split())[:40]


def phrase_mode_reel(agent: str, demande: str, reel: str, raison: str = "") -> str:
    """La phrase du fil quand le mode réellement appliqué à un agent n'est pas le mode demandé."""
    if demande and reel == demande:
        return f"{agent} travaille de nouveau dans le mode demandé, « {libelle_mode(reel)} »."
    if not demande:
        return f"Mode réellement appliqué à {agent} : « {libelle_mode(reel)} »."
    phrase = (
        f"{agent} devait travailler en mode « {libelle_mode(demande)} », mais c'est le mode "
        f"« {libelle_mode(reel)} » qui est appliqué"
    )
    return f"{phrase} : {raison}." if raison else f"{phrase}."


def phrase_mode_refuse(mode) -> str:
    """Pourquoi la route refuse un mode : il est inconnu, ou c'est le contournement total."""
    if mode == "bypassPermissions":
        return (
            "Le mode bypassPermissions, qui laisserait les agents tout faire sans rien demander, "
            "n'est pas proposé par l'Atelier : rien n'a changé."
        )
    noms = ", ".join(f"« {libelle} »" for libelle, _ in MODES_FR.values())
    return f"Ce mode n'existe pas : choisis parmi {noms}. Rien n'a changé."


def phrase_mode_illisible(valeur) -> str:
    """La phrase du fil quand le profil demande un mode inconnu, mal écrit ou refusé."""
    montre = f"« {' '.join(valeur.split())[:40]} »" if isinstance(valeur, str) else "illisible"
    return (
        f"Le profil du projet (chantier/profil.json) demande pour les ouvriers un mode que "
        f"l'Atelier ne connaît pas ou refuse ({montre}) : ils travaillent en mode "
        f"« {libelle_mode(MODE_PAR_DEFAUT)} »."
    )


def phrase_mode_change(mode: str, touches: int) -> str:
    """La phrase du fil après un changement du mode des ouvriers."""
    debut = f"Mode des ouvriers : « {libelle_mode(mode)} »."
    if touches == 0:
        return f"{debut} Il vaudra pour les prochains ouvriers lancés."
    if touches == 1:
        return f"{debut} Il vaut aussi, dès maintenant, pour l'ouvrier en marche."
    return f"{debut} Il vaut aussi, dès maintenant, pour les {touches} ouvriers en marche."


def cle_api_presente(environnement=None) -> bool:
    """Dit si la variable ANTHROPIC_API_KEY existe et n'est pas vide. Sa valeur n'est jamais lue."""
    environnement = os.environ if environnement is None else environnement
    return bool(str(environnement.get(VARIABLE_CLE, "")).strip())


def annonce_de_depart(mode: str, cle_presente: bool) -> str:
    """La phrase du fil au démarrage : ce qui est su de l'environnement, sans appel réel."""
    if mode == "démonstration":
        return CONNEXION_DEMO
    return CONNEXION_CLE_PRESENTE if cle_presente else CONNEXION_ATTENDUE


def annonce_de_source(source: str, cle_presente: bool) -> str:
    """La phrase du fil quand un agent a appris la vraie source ; vide si elle est inconnue."""
    if source == "abonnement":
        return CONNEXION_ABONNEMENT_MALGRE_VARIABLE if cle_presente else CONNEXION_ABONNEMENT
    if source == "clé API":
        return CONNEXION_CLE if cle_presente else CONNEXION_CLE_SANS_VARIABLE
    return ""


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


# Comment une ligne d'activité dit l'événement ({0} : son contenu ; {1} : le libellé d'un mode).
LIGNES_PAR_GENRE = {
    "attente": "En attente de ton autorisation : {0}",
    "refus": "Refusé par l'arbitre : {0}.",
    "mode": "Mode réellement appliqué : {1}.",
}
LIGNES_MAX = 30  # lignes d'activité gardées par agent
LARGEUR_MAX = 300  # caractères par ligne d'activité
MORCEAU_MAX = LIGNES_MAX * LARGEUR_MAX  # de quoi remplir toutes les lignes : le reste est perdu
AGENTS_MAX = 40  # agents gardés : au-delà, les plus anciens sont retirés
TRANCHE_DEMO_S = 0.5  # les courbes d'activité de la démonstration : 10 secondes sur 20 colonnes
SESSIONS_MAX = AGENTS_MAX  # sessions suivies pour la confirmation de connexion, de même


class Activite:
    """Les dernières lignes d'activité de chaque agent en marche, en mémoire et bornées.

    `ajouter` est appelé par le rappel `sur_evenement` des agents, qui tourne dans la boucle de
    leur session : il ne fait que ranger l'événement, sous un verrou, sans rien écrire ni
    attendre. Hors démonstration, ce rappel est `Atelier._sur_evenement`, qui écrit en plus dans
    le fil, rarement, une confirmation de la source de connexion.

    Seule exception, rare : un événement « mode » qui dit un mode réel nouveau pour cet agent
    est passé à `sur_mode` (l'atelier l'écrit au fil), hors du verrou, une fois par changement.
    """

    def __init__(self, tranche_s: float = TRANCHE_S):
        self._verrou = threading.Lock()
        self._lignes: dict[str, deque[str]] = {}
        self._reste: dict[str, str] = {}  # le texte reçu qui n'est pas encore une ligne entière
        self._modes: dict[str, tuple] = {}  # le dernier mode réel dit, par agent en marche
        self.rythmes = Rythmes(tranche_s=tranche_s)  # combien chaque agent agit, pour les courbes
        self.sur_mode = None

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
            demande = evenement.get("demande") if isinstance(evenement, dict) else None
            nouveau = self._ranger_evenement(nom, genre, contenu, demande)
        if nouveau and self.sur_mode is not None:
            with suppress(Exception):
                self.sur_mode(evenement)

    def _ranger_evenement(self, nom: str, genre, contenu: str, demande) -> bool:
        """Sous le verrou : range l'événement ; rend True pour un mode réel nouveau."""
        self.rythmes.compter(nom, str(genre), contenu)
        if genre == "fin":
            self._lignes.pop(nom, None)
            self._reste.pop(nom, None)
            self._modes.pop(nom, None)
            return False
        self._lignes.setdefault(nom, deque(maxlen=LIGNES_MAX))
        while len(self._lignes) > AGENTS_MAX:  # sans « fin », on oublie les plus anciens
            ancien = next(iter(self._lignes))
            del self._lignes[ancien]
            self._reste.pop(ancien, None)
            self._modes.pop(ancien, None)
        if genre == "texte":
            recu = self._reste.get(nom, "") + contenu.replace("\r", "")
            *entieres, reste = recu.split("\n")
            self._ranger(nom, "\n".join(entieres))
            coupe = len(reste) - len(reste) % LARGEUR_MAX  # le reste reste borné lui aussi
            self._ranger(nom, reste[:coupe])
            self._reste[nom] = reste[coupe:]
            return False
        self._ranger(nom, self._reste.pop(nom, ""))
        self._ranger(nom, LIGNES_PAR_GENRE.get(genre, "{}").format(contenu, libelle_mode(contenu)))
        if genre != "mode":
            return False
        dit, self._modes[nom] = self._modes.get(nom), (contenu, str(demande or ""))
        return dit != self._modes[nom]

    def rythme(self) -> dict:
        """Les courbes d'activité des agents en marche et des tâches finies (voir `rythme`)."""
        with self._verrou:
            return self.rythmes.vue()

    def oublier_bilans(self) -> None:
        """Un nouveau chantier repart sans les courbes de l'ancien."""
        with self._verrou:
            self.rythmes.oublier_bilans()

    def oublier_modes(self) -> None:
        """Après un changement de mode demandé, tout écart de mode réel sera dit de nouveau."""
        with self._verrou:
            self._modes.clear()

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


RACINE_ATELIER = Path(__file__).resolve().parent.parent  # la démonstration cartographie l'Atelier
EN_COURS_TTL_S = 3.0  # le travail en cours des agents est relu au plus toutes les 3 secondes

ACCUEIL = "Bonjour. Dis-moi ce que tu veux construire, je te proposerai un découpage."
CHANTIER_OCCUPE = (
    "Un agent travaille ou l'orchestrateur répond : attends qu'il ait fini, ou arrête-le, "
    "avant d'ouvrir un nouveau chantier."
)
CHANTIER_VIDE = "Ce chantier est encore vide : il n'y a rien à archiver."


class Atelier:
    """Relie un dépôt, un chantier, le moteur et le tableau de bord."""

    def __init__(
        self,
        depot: Path,
        chantier: Chantier,
        agent,
        controles,
        profil,
        mode="réel",
        guichet=None,
    ):
        self.depot = Path(depot)
        self.mode = mode
        # En démonstration un agent simulé ne travaille que quelques secondes : tranches courtes.
        self.activite = Activite(TRANCHE_DEMO_S if mode == "démonstration" else TRANCHE_S)
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
        self.activite.sur_mode = self._noter_mode_reel
        # Le mode des ouvriers vient du profil ; tout ce qui n'est pas l'un des cinq modes vaut
        # « acceptEdits », et l'agent le reçoit avant tout lancement.
        lu = profil.get("mode_ouvriers") if isinstance(profil, dict) else None
        self.mode_ouvriers = lire_mode(lu)
        if hasattr(agent, "changer_mode"):
            agent.changer_mode(self.mode_ouvriers)
        self._cle_presente = False
        # La dernière annonce de connexion du fil, telle que le rappel des agents la connaît ;
        # vide si elle est inconnue (le fil sera relu). Elle n'est posée que sous `moteur.verrou`.
        self._annonce_dite = ""
        # Les sessions d'agent qui ont fait leur seule confirmation possible ; retirées au « fin ».
        self._sessions_dites: dict[str, None] = {}
        self._verrou_sessions = threading.Lock()  # ne protège que `_sessions_dites`
        self.fil: threading.Thread | None = None
        self.fil_message: threading.Thread | None = None
        self.occupe = False
        self.brouillon = {"texte": "", "outils": []}
        self.sur_vue = None
        self.moteur = Moteur(chantier, agent, controles, profil, sur_changement=self._sauver)
        self.archives = archives.lister(self.depot)  # relue à chaque archivage, pas à chaque vue
        # La carte du code : en démonstration, celle de l'Atelier lui-même, expliquée par ses
        # propres commentaires ; un vrai projet fait écrire ses explications par Claude.
        simule = isinstance(agent, AgentSimule)
        explicateur = ExplicateurAuto() if simule else ExplicateurClaude(self.depot)
        self.carte = SuiviCarte(
            RACINE_ATELIER if mode == "démonstration" else self.depot, explicateur
        )
        if self.carte.carte is not None and mode != "démonstration":
            self.carte.demarrer_veille()
        self._en_cours_cache: tuple[float, dict, dict] = (0.0, {}, {})
        if not chantier.taches and not chantier.evenements:
            chantier.noter(ACCUEIL, auteur="orchestrateur")
        if isinstance(profil, dict) and "mode_ouvriers" in profil and not mode_valide(lu):
            phrase = phrase_mode_illisible(lu)
            if not chantier.evenements or chantier.evenements[-1]["texte"] != phrase:
                chantier.noter(phrase, auteur="orchestrateur")  # une fois par ouverture
        self._sauver()

    def _noter_annonce(self, phrase: str, comparee_a: tuple) -> None:
        """Écrit la phrase, sauf si la dernière annonce du fil prise dans `comparee_a` est elle.

        Un départ se compare au dernier départ (`DEPARTS`, règle R1). Une confirmation se compare
        à la dernière annonce de connexion, toutes familles confondues (`ANNONCES`, règle R2).
        Un texte retiré (`ANCIENNES_ANNONCES`) compte dans les deux cas, et ne vaut jamais
        `phrase` : s'il est le plus récent, l'annonce est réécrite.
        """
        with self.moteur.verrou:
            fil = self.moteur.chantier.evenements
            derniere = next((e["texte"] for e in reversed(fil) if e["texte"] in comparee_a), "")
            if derniere != phrase:
                self.moteur.chantier.noter(phrase, auteur="orchestrateur")

    def annoncer_connexion(self, environnement=None) -> None:
        """Dit dans le fil, à l'ouverture du projet, ce qui est su de la facturation.

        En démonstration, rien n'est réel : une phrase suffit. Sinon la phrase dit seulement si la
        variable ANTHROPIC_API_KEY est dans l'environnement de l'Atelier, puis la vraie source est
        annoncée dès qu'un agent l'a apprise, et de nouveau chaque fois qu'elle change. Le départ
        n'est écrit que s'il diffère du dernier départ du fil ; la confirmation, que si la
        dernière annonce de connexion n'est pas déjà elle : un simple redémarrage n'ajoute rien.
        """
        self._cle_presente = cle_api_presente(environnement)
        depart = annonce_de_depart(self.mode, self._cle_presente)
        self._noter_annonce(depart, DEPARTS + ANCIENNES_ANNONCES)
        with self.moteur.verrou:
            self._annonce_dite = ""  # le fil sera relu à la première source apprise
        with self._verrou_sessions:
            self._sessions_dites.clear()
        if self.mode != "démonstration":  # en démonstration, aucune confirmation
            self.moteur.agent.sur_evenement = self._sur_evenement
        self._sauver()

    def _sur_evenement(self, evenement: dict) -> None:
        """Rappel des agents : range l'activité, et confirme la source de connexion si besoin.

        Chaque session d'agent, de son premier événement à son « fin », confirme au plus une
        fois : au premier de ses événements où la source est connue. Si la phrase est déjà la
        dernière annonce connue, rien n'est fait de plus, sans verrou ni remontée du fil ;
        sinon elle est écrite (`_confirmer`). Une écriture qui échoue est retentée à
        l'événement suivant de la même session, « fin » compris.
        """
        self.activite.ajouter(evenement)
        if not isinstance(evenement, dict):
            return
        nom = str(evenement.get("agent", ""))
        if nom not in self._sessions_dites:
            source = getattr(self.moteur.agent, "source_connexion", "")
            phrase = annonce_de_source(source, self._cle_presente)
            if phrase and (phrase == self._annonce_dite or self._confirmer(phrase)):
                self._retenir_session(nom)
        if evenement.get("type") == "fin" and nom in self._sessions_dites:
            with self._verrou_sessions:
                self._sessions_dites.pop(nom, None)

    def _confirmer(self, phrase: str) -> bool:
        """Écrit la confirmation selon R2 puis sauve ; rend False, sans lever, si cela échoue."""
        try:
            with self.moteur.verrou:
                if self._annonce_dite != phrase:
                    self._annonce_dite = ""  # inconnue tant que l'écriture n'a pas réussi
                    self._noter_annonce(phrase, ANNONCES)
                    self._annonce_dite = phrase
            self._sauver()
            return True
        except Exception:
            with self.moteur.verrou:
                self._annonce_dite = ""  # relue au prochain essai : R2 évite tout doublon
            return False

    def _retenir_session(self, nom: str) -> None:
        """Note que la session `nom` a confirmé ; au-delà de `SESSIONS_MAX`, oublie la plus
        ancienne, qui pourrait alors confirmer une seconde fois."""
        with self._verrou_sessions:
            self._sessions_dites[nom] = None
            while len(self._sessions_dites) > SESSIONS_MAX:
                del self._sessions_dites[next(iter(self._sessions_dites))]

    def _sauver(self) -> None:
        with self.moteur.verrou:
            chantier = self.moteur.chantier
            chantier.sauver(self.depot / ".atelier" / "etat.json")
            ecrire_cahier(chantier, self.depot / "chantier" / "CAHIER.md")
            if self.sur_vue:
                self.sur_vue(self.vue())
        if hasattr(self, "carte"):
            self.carte.signaler()  # une tâche vient peut-être d'entrer dans le code

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
        donnees["rythmes"] = self.activite.rythme()
        donnees["mode_ouvriers"] = self._vue_mode()
        donnees["archives"] = list(self.archives)
        donnees["carte"] = self.carte.resume(self.en_cours(), self.provisoire())
        donnees["nom_propose"] = archives.nom_propose(self.moteur.chantier)
        controles = self.moteur.controles
        if hasattr(controles, "distant"):
            donnees["distant"] = {"adresse": controles.distant(), "probleme": controles.envoi}
        return donnees

    def _vue_mode(self) -> dict:
        """Le mode choisi, les cinq choix, et les ouvriers en marche dont le mode réel diffère."""
        choisi = self.mode_ouvriers
        lire = getattr(self.moteur.agent, "modes_appliques", None)
        reels = lire() if lire is not None else {}
        appliques = [
            {"agent": nom, "mode": mode, "libelle": libelle_mode(mode)}
            for nom, mode in reels.items()
            if mode != choisi
        ]
        return {
            "choisi": choisi,
            "libelle": libelle_mode(choisi),
            "choix": [dict(choix) for choix in CHOIX_MODES],
            "appliques": appliques,
        }

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

    # --- le mode des ouvriers -----------------------------------------------------

    def changer_mode(self, mode) -> dict:
        """Choisit le mode des ouvriers : l'écrit au profil et l'applique à chaud aux ouvriers.

        Un mode inconnu, mal typé ou « bypassPermissions » est refusé sans rien écrire. Le
        vérificateur et l'orchestrateur ne sont jamais touchés : ils restent en lecture seule.
        """
        if not mode_valide(mode):
            return {"fait": False, "phrase": phrase_mode_refuse(mode)}
        with self._verrou_profil:  # l'écriture et le changement à chaud, dans le même ordre
            probleme = self._ecrire_au_profil("mode_ouvriers", mode)
            self._propager({"mode_ouvriers": mode})
            self.mode_ouvriers = mode
            self.activite.oublier_modes()  # « déjà dit » ne vaut que depuis ce changement
            changer = getattr(self.moteur.agent, "changer_mode", None)
            with self.moteur.verrou:  # la phrase du changement passe avant ce qu'en dira l'ouvrier
                touches = changer(mode) if changer is not None else 0
                phrase = phrase_mode_change(mode, touches)
                self.moteur.chantier.noter(phrase, auteur="orchestrateur")
        self._sauver()
        if probleme:
            phrase += f" Il n'a pas pu être enregistré et sera oublié au redémarrage : {probleme}"
        return {"fait": True, "phrase": phrase}

    def _ecrire_au_profil(self, cle: str, valeur) -> str:
        """Sous `_verrou_profil` : écrit une clé de `chantier/profil.json` sans toucher au reste.

        Comme pour une règle « toujours » : un fichier absent est créé ; un fichier illisible,
        ou qui n'est pas un objet, n'est pas écrasé. Rend "" ou la raison de l'échec.
        """
        chemin = self.depot / "chantier" / "profil.json"
        try:
            fichier = json.loads(chemin.read_text("utf-8")) if chemin.exists() else {}
            if not isinstance(fichier, dict):
                raise ValueError("le profil du projet n'est pas lisible")
            fichier[cle] = valeur
            chemin.parent.mkdir(parents=True, exist_ok=True)
            chemin.write_text(json.dumps(fichier, ensure_ascii=False, indent=2) + "\n", "utf-8")
        except ValueError:
            return "le profil du projet (chantier/profil.json) n'est pas lisible, corrige-le."
        except OSError:
            return "le profil du projet (chantier/profil.json) n'a pas pu être écrit."
        return ""

    def _noter_mode_reel(self, evenement: dict) -> None:
        """Écrit au fil, une fois par agent et par changement, le mode réellement appliqué."""
        demande, raison = evenement.get("demande") or "", evenement.get("raison") or ""
        phrase = phrase_mode_reel(str(evenement["agent"]), str(demande), str(evenement["contenu"]),
                                  str(raison))  # fmt: skip
        self._dire(phrase)
        self._sauver()

    def noter_au_fil(self, phrase: str) -> None:
        """Écrit une phrase du moteur au fil du projet, et sauve l'état."""
        with self.moteur.verrou:
            self.moteur.chantier.noter(phrase)
        self._sauver()

    # --- un nouveau chantier dans le même projet --------------------------------

    def nouveau_chantier(self, nom="") -> dict:
        """Archive le chantier en cours sous un nom, et repart d'un chantier vide dans le projet.

        La conversation, le contrat, les tâches et un journal partent dans `.atelier/archives/` ;
        le code du projet n'est pas touché. L'orchestrateur repart d'une session neuve, sans
        souvenir de l'ancienne. Refusé tant qu'un agent travaille ou que l'orchestrateur répond.
        Sans nom, le chantier reçoit celui que propose l'Atelier (son objectif).
        """
        with self.moteur.verrou:
            if self.en_marche() or self.occupe:
                return {"fait": False, "phrase": CHANTIER_OCCUPE}
            ancien = self.moteur.chantier
            if not ancien.taches and not any(e["auteur"] == "toi" for e in ancien.evenements):
                return {"fait": False, "phrase": CHANTIER_VIDE}
            avait_annonce = any(e["texte"] in DEPARTS for e in ancien.evenements)
            j = archives.archiver(self.depot, ancien, nom, self._contexte_archive())
            nouveau = Chantier(projet=ancien.projet, contrat=Contrat(objectif=""))
            nouveau.noter(ACCUEIL, auteur="orchestrateur")
            phrase = (
                f"Nouveau chantier ouvert. Le précédent, « {j['nom']} », est archivé : "
                f"{j['bilan'][0].lower()}{j['bilan'][1:]} Son journal se relit dans l'onglet "
                "Chantier, sous « Chantiers archivés ». Le code du projet n'a pas changé."
            )
            nouveau.noter(phrase)
            self.moteur.chantier = nouveau
            self.brouillon = {"texte": "", "outils": []}
            self.activite.oublier_bilans()
            self.archives = archives.lister(self.depot)
        if avait_annonce:
            self.annoncer_connexion()  # le nouveau fil redit ce qui est su de la facturation
        else:
            self._sauver()
        return {"fait": True, "phrase": phrase}

    # --- la carte du code ---------------------------------------------------------------

    def en_cours(self) -> dict[str, list[str]]:
        """Les fichiers que les agents sont en train de modifier, et par qui : {chemin: [agents]}.

        Lu dans la copie de travail de chaque tâche en cours, au plus toutes les 3 secondes. En
        démonstration, rien n'est modifié pour de vrai : chaque tâche en cours fait clignoter
        deux fichiers de la carte, toujours les mêmes.
        """
        return self._travail_en_cours()[0]

    def provisoire(self) -> dict:
        """Les fichiers et les liens nouveaux que les agents écrivent, pas encore vérifiés."""
        return self._travail_en_cours()[1]

    def _travail_en_cours(self) -> tuple[dict[str, list[str]], dict]:
        maintenant = time.monotonic()
        if maintenant - self._en_cours_cache[0] < EN_COURS_TTL_S:
            return self._en_cours_cache[1], self._en_cours_cache[2]
        with self.moteur.verrou:
            actives = [
                t for t in self.moteur.chantier.taches if t.etat in ("en_cours", "en_verification")
            ]
        noms = {}
        for agent in self.activite.agents():
            noms.setdefault(agent.get("tache", ""), []).append(agent["nom"])
        resultat: dict[str, list[str]] = {}
        brouillons = []
        for tache in actives:
            agents = noms.get(tache.id) or [f"tâche {tache.id}"]
            fichiers = self._fichiers_en_cours(tache)
            for chemin in fichiers:
                resultat.setdefault(chemin, []).extend(agents)
            brouillons.append(self._brouillon(tache, agents, fichiers))
        with self.carte.verrou:
            carte = self.carte.carte
        prov = provisoire(carte, [b for b in brouillons if b])
        self._en_cours_cache = (maintenant, resultat, prov)
        return resultat, prov

    def _brouillon(self, tache, agents: list[str], fichiers: list[str]) -> dict | None:
        controles = self.moteur.controles
        if hasattr(controles, "_arbre"):
            return {"agents": agents, "fichiers": fichiers, "dossier": controles._arbre(tache)}
        if self.mode != "démonstration" or not fichiers:
            return None
        # Démonstration : chaque tâche écrit un nouveau fichier, relié aux deux qu'elle modifie.
        nom = f"atelier/brouillon_{tache.id.lower()}.py"
        resume = f"Nouveau fichier de la tâche {tache.id} : {tache.titre}."
        fantome = {"chemin": nom, "genre": "code", "lignes": 60, "resume": resume}
        liens = [[nom, fichiers[0]], [fichiers[-1], nom]]
        return {"agents": agents, "dossier": None, "fantomes": [fantome], "liens": liens}

    def _fichiers_en_cours(self, tache) -> list[str]:
        controles = self.moteur.controles
        if hasattr(controles, "_arbre"):
            dossier = controles._arbre(tache)
            if not dossier.exists():
                return []
            with suppress(Exception):
                return controles.fichiers_modifies(tache, dossier, None)
            return []
        if self.mode != "démonstration" or self.carte.carte is None:
            return []
        codes = sorted(c for c, f in self.carte.carte["fichiers"].items() if f["genre"] == "code")
        if not codes:
            return []
        rang = sum(map(ord, tache.id)) % len(codes)
        return sorted({codes[rang], codes[(rang + 3) % len(codes)]})

    def estimer_carte(self) -> dict:
        """Ce que coûterait l'analyse : combien de fichiers, combien d'appels à Claude."""
        e = self.carte.estimer()
        if self.mode == "démonstration":
            phrase = (
                f"Démonstration : la carte montre le code de l'Atelier, {e['fichiers']} fichiers. "
                "Les explications sont tirées de ses commentaires, sans appel à Claude."
            )
        elif not self.carte.explicateur.reel:
            phrase = (
                f"{e['fichiers']} fichiers. Les explications sont tirées des commentaires du code."
            )
        elif not e["a_expliquer"]:
            phrase = f"{e['fichiers']} fichiers, tous déjà expliqués : aucun appel à Claude."
        else:
            phrase = (
                f"{e['fichiers']} fichiers, dont {e['a_expliquer']} à expliquer : environ "
                f"{e['appels']} appel{'s' if e['appels'] > 1 else ''} à Claude (Sonnet), sur ton "
                "abonnement. Ensuite, seuls les fichiers modifiés seront réexpliqués."
            )
        return {**e, "phrase": phrase}

    def analyser_carte(self) -> dict:
        if not self.carte.analyser():
            return {"fait": False, "phrase": "L'analyse est déjà en cours."}
        return {
            "fait": True,
            "phrase": "Analyse lancée : la carte se remplit au fil des explications.",
        }

    def _contexte_archive(self) -> dict:
        """Ce que le journal dit de la livraison : le mode, le dépôt en ligne, le dernier envoi."""
        controles = self.moteur.controles
        distant = controles.distant() if hasattr(controles, "distant") else ""
        probleme = getattr(controles, "envoi", "") or ""
        return {"mode": self.mode, "distant": distant or "", "probleme": probleme}

    def lire_archive(self, ident) -> dict:
        """Le journal d'un chantier archivé de ce projet, pour le tableau de bord."""
        j = archives.lire(self.depot, ident)
        if j is None:
            return {"trouvee": False, "phrase": "Cette archive est introuvable ou illisible."}
        return {"trouvee": True, "journal": j}

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


PAUSE_VERIFICATION_S = 60  # `verifier` se limite seule à une interrogation par heure
PHRASE_DEJA_EN_COURS = "Une mise à jour est déjà en cours. Patiente un instant."
PHRASE_REDEMARRAGE = (
    "Atelier a été mis à jour. Il redémarre ; s'il ne revient pas dans quelques secondes, "
    "relance-le à la main."
)


class SuiviMiseAJour:
    """La mise à jour d'Atelier côté serveur : un seul objet pour tout le serveur.

    Un fil démon appelle `verifier()` et garde le dernier état ; la vue ne lit que cet état.
    `arreter` est la fonction qui arrête le processus après une mise à jour réussie ; `None`
    (démonstration, essais) : le serveur ne s'arrête jamais.
    """

    def __init__(self, maj, arreter=None, pause_s: float = PAUSE_VERIFICATION_S):
        self.maj = maj
        self.arreter = arreter
        self.pause_s = pause_s
        self.etat: Etat | None = None
        self._verrou = threading.Lock()
        self._fin = threading.Event()

    def demarrer(self) -> threading.Thread:
        fil = threading.Thread(target=self._boucle, daemon=True)
        fil.start()
        return fil

    def _boucle(self) -> None:
        while not self._fin.is_set():
            self.etat = self.maj.verifier()
            self._fin.wait(self.pause_s)

    def finir(self) -> None:
        """Arrête le fil de vérification (les essais)."""
        self._fin.set()

    def vue(self) -> dict:
        etat = self.etat
        return {"disponible": bool(etat and etat.disponible), "phrase": etat.phrase if etat else ""}

    def lancer(self, projets) -> Resultat:
        """Met à jour si aucun agent ne travaille et si aucune autre mise à jour n'est en cours."""
        if not self._verrou.acquire(blocking=False):
            return Resultat(False, PHRASE_DEJA_EN_COURS)
        try:
            travaille = any(a.en_marche() or a.occupe for a in list(projets.ateliers.values()))
            resultat = self.maj.mettre_a_jour(travaille)
        finally:
            self._verrou.release()
        if resultat.detail:
            print(f"Mise à jour : {resultat.detail}", file=sys.stderr, flush=True)
        if resultat.fait and self.arreter:
            resultat = Resultat(True, PHRASE_REDEMARRAGE)
        if projets.courant:
            projets.atelier().noter_au_fil(resultat.phrase)
        return resultat


class Requetes(BaseHTTPRequestHandler):
    """Répond aux demandes du tableau de bord, pour le projet affiché."""

    projets = None  # les projets de l'atelier (atelier.projets.Projets)
    suivi = None  # la mise à jour d'Atelier (SuiviMiseAJour), ou None
    apres = None  # à faire une fois la réponse envoyée (l'arrêt après une mise à jour)

    def vue(self) -> dict:
        miseajour = self.suivi.vue() if self.suivi else {"disponible": False, "phrase": ""}
        return {**self.projets.vue(), "mise_a_jour": miseajour}

    def mettre_a_jour(self) -> dict:
        if not self.suivi:
            raise ProjetImpossible("La mise à jour n'est pas branchée sur ce serveur.")
        resultat = self.suivi.lancer(self.projets)
        if resultat.fait and self.suivi.arreter:
            self.apres = self.suivi.arreter
        return {"mise_a_jour_faite": {"fait": resultat.fait, "phrase": resultat.phrase}}

    @property
    def atelier(self) -> Atelier:
        return self.projets.atelier()

    def log_message(self, *arguments) -> None:
        return None

    def _repondre(self, code: int, corps: bytes, nature: str) -> None:
        self.send_response(code)
        binaire = nature.startswith(("image/", "font/"))
        self.send_header("Content-Type", nature if binaire else f"{nature}; charset=utf-8")
        self.send_header("Content-Length", str(len(corps)))
        self.end_headers()
        self.wfile.write(corps)

    def _json(self, donnees: dict, code: int = 200) -> None:
        corps = json.dumps(donnees, ensure_ascii=False).encode("utf-8")
        self._repondre(code, corps, "application/json")

    def do_GET(self) -> None:
        if self.path == "/api/etat":
            return self._json(self.vue())
        if self.path in ("/", "/index.html"):
            return self._repondre(200, PAGE.read_bytes(), "text/html")
        if self.path in ("/icone.png", "/apple-touch-icon.png", "/favicon.ico"):
            return self._repondre(200, ICONE.read_bytes(), "image/png")
        if self.path in POLICES:
            fichier, nature = POLICES[self.path]
            return self._repondre(200, fichier.read_bytes(), nature)
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
        self._json({**self.vue(), **(en_plus or {})})
        if self.apres:
            self.wfile.flush()  # la page a sa réponse : le processus peut s'arrêter
            self.apres()


# Chaque route reçoit la requête et le corps lu ; elle peut rendre des champs de plus pour la
# réponse, qui est sinon la vue du tableau de bord.
ROUTES = {
    "/api/contrat/valider": lambda r, c: r.atelier.valider_contrat(),
    "/api/decision": lambda r, c: r.atelier.decider(c["id"], c["choix"]),
    "/api/message": lambda r, c: r.atelier.message(c["texte"]),
    "/api/projets/creer": lambda r, c: {"projet_cree": r.projets.creer(c["nom"])},
    "/api/projets/cloner": lambda r, c: {"projet_cree": r.projets.cloner(c["adresse"])},
    "/api/projet/relier": lambda r, c: r.atelier.relier(c["adresse"]),
    "/api/projets/ouvrir": lambda r, c: r.projets.ouvrir(c["id"]),
    "/api/accueil": lambda r, c: {"accueil": r.projets.accueil()},
    "/api/projets/nouvelle-session": lambda r, c: {
        "nouveau_chantier": r.projets.nouvelle_session(c["id"], c.get("nom", ""))
    },
    "/api/autorisation": lambda r, c: {
        "autorisation": r.atelier.autoriser(c["id"], c["choix"], c.get("message", ""))
    },
    "/api/arreter": lambda r, c: {"arret": r.atelier.arreter(c.get("tache"))},
    "/api/mode": lambda r, c: {"changement_mode": r.atelier.changer_mode(c["mode"])},
    "/api/mise-a-jour": lambda r, c: r.mettre_a_jour(),
    "/api/chantier/nouveau": lambda r, c: {
        "nouveau_chantier": r.atelier.nouveau_chantier(c.get("nom", ""))
    },
    "/api/archives/lire": lambda r, c: {"archive": r.atelier.lire_archive(c["id"])},
    "/api/carte/estimer": lambda r, c: {"estimation": r.atelier.estimer_carte()},
    "/api/carte/analyser": lambda r, c: {"analyse": r.atelier.analyser_carte()},
    "/api/carte/lire": lambda r, c: {"carte_complete": r.atelier.carte.vue(r.atelier.en_cours())},
}


def creer_serveur(projets, port: int = 8765, suivi=None) -> ThreadingHTTPServer:
    """Crée le serveur du tableau de bord, limité à la machine locale."""
    gestionnaire = type("RequetesLiees", (Requetes,), {"projets": projets, "suivi": suivi})
    return ThreadingHTTPServer(("127.0.0.1", port), gestionnaire)
