"""Le serveur local : il fait tourner le moteur et alimente le tableau de bord.

Il n'écoute que sur la machine elle-même (127.0.0.1) : rien n'est exposé au réseau.
"""

from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
import uuid
from collections import deque
from contextlib import suppress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from atelier import archives, dosage
from atelier.agents import (
    MODE_PAR_DEFAUT,
    MODES_OUVRIERS,
    AgentSimule,
    commande_permise,
    lire_mode,
    mode_valide,
)
from atelier.carte import ExplicateurAuto, ExplicateurClaude, SuiviCarte, provisoire
from atelier.consignes import (
    BALISE_OUTILS,
    BALISE_PLAN,
    extraire_outils,
    extraire_plan,
    message_avec_etat,
    message_de_diagnostic,
)
from atelier.guichet import ARRETE, CHOIX, Guichet
from atelier.mise_a_jour import Etat, Resultat
from atelier.modele import (
    ETATS_FR,
    Chantier,
    Contrat,
    ProjetImpossible,
    ecrire_cahier,
    ecrire_d_un_seul_geste,
)
from atelier.moteur import ARRETEE, Moteur, taches_du_plan
from atelier.rythme import TRANCHE_S, Rythmes, poste

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


def _avant_balises(texte: str) -> str:
    """Rend le texte de l'orchestrateur coupé à la première balise de plan ou d'outils."""
    return texte.split(BALISE_PLAN)[0].split(BALISE_OUTILS)[0]


def _liste_de_textes(valeur) -> bool:
    """Dit si une valeur lue dans le profil est une liste dont chaque élément est un texte."""
    return isinstance(valeur, list) and all(isinstance(v, str) for v in valeur)


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
        refus = sum(issue not in ("valide", ARRETEE, "attente_panne") for issue in issues)
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
# Une ligne où l'agent dit l'étape qu'il entame (sa consigne le lui demande) : « Étape : ... ».
ETAPE = re.compile(r"^[*_#\s]*[ÉéEe]tape\s*(\d+\s*(?:/\s*\d+)?)?\s*[:：]\s*[*_]*\s*(.+?)[*_]*$")
PROFIL_ILLISIBLE = "le profil du projet (chantier/profil.json) n'est pas lisible, corrige-le."
PROFIL_NON_ECRIT = "le profil du projet (chantier/profil.json) n'a pas pu être écrit."
REESSAYER_OUTILS = "La demande reste ouverte : accepte-la à nouveau une fois le profil corrigé."
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
        self._temps: dict[str, list[float]] = {}  # [départ, dernière action], par agent en marche
        self._etapes: dict[str, str] = {}  # la dernière ligne « Étape : ... » de chaque agent
        self.horloge = time.monotonic
        self.rythmes = Rythmes(tranche_s=tranche_s)  # combien chaque agent agit, pour les courbes
        self.sur_mode = None

    def _ranger(self, nom: str, texte: str) -> None:
        lignes = self._lignes[nom]
        for ligne in texte.split("\n"):
            ligne = ligne.strip()
            etape = ETAPE.match(ligne)
            if etape and etape.group(2).strip():
                rang = "".join((etape.group(1) or "").split())
                dite = f"{rang} · {etape.group(2).strip()}" if rang else etape.group(2).strip()
                self._etapes[nom] = dite[:LARGEUR_MAX]
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
            self._oublier(nom)
            return False
        maintenant = self.horloge()
        self._temps.setdefault(nom, [maintenant, maintenant])[1] = maintenant
        self._lignes.setdefault(nom, deque(maxlen=LIGNES_MAX))
        while len(self._lignes) > AGENTS_MAX:  # sans « fin », on oublie les plus anciens
            self._oublier(next(iter(self._lignes)))
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

    def _oublier(self, nom: str) -> None:
        for registre in (self._lignes, self._reste, self._modes, self._temps, self._etapes):
            registre.pop(nom, None)

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
            maintenant = self.horloge()
            vus = [
                (n, [*lignes, self._reste.get(n, "")], self._etapes.get(n, ""), self._temps.get(n))
                for n, lignes in self._lignes.items()
            ]
        agents = []
        for nom, lignes, etape, temps in vus:
            tache, role = poste(nom)
            lignes = [ligne.strip() for ligne in lignes if ligne.strip()]
            lignes = lignes[-LIGNES_MAX:]
            depart, derniere = temps or (maintenant, maintenant)
            agents.append(
                {
                    "nom": nom,
                    "tache": tache,
                    "role": role,
                    "lignes": lignes,
                    "etape": etape,  # ce que l'agent dit faire, s'il l'a dit
                    "depuis_s": round(maintenant - depart),  # depuis son premier signe de vie
                    "calme_s": round(maintenant - derniere),  # depuis sa dernière action
                }
            )
        return agents


ACCEPTER_OUTILS, REFUSER_OUTILS = "Accepter ce réglage", "Refuser"
# Où en est le diagnostic d'un blocage, gardé dans sa demande (donc dans l'état sauvé) : rangé en
# attente de la conversation, envoyé à l'orchestrateur, puis l'une des issues (« propose »,
# « sans_proposition », « lanceur », « echec », « arrete », « sans_objet », « interrompu »). Les
# deux premiers, relus à l'ouverture, disent un diagnostic resté sans réponse quand l'Atelier
# s'est arrêté. Avec « propose », la demande de blocage porte aussi `reglage` : l'identifiant de la
# demande d'outils qu'il a fait naître, seule à pouvoir relancer la tâche.
DIAGNOSTIC_EN_ATTENTE, DIAGNOSTIC_EN_COURS = "en_attente", "en_cours"
DIAGNOSTIC_INACHEVE = (DIAGNOSTIC_EN_ATTENTE, DIAGNOSTIC_EN_COURS)
DIAGNOSTIC_PROPOSE = "propose"
BLOCAGE_OUVERT = "sa demande reste ouverte, avec ses options."
DEBLOQUE = "Ce réglage débloque la tâche "  # la phrase d'une demande d'outils liée à un blocage
# Les lanceurs généraux, que l'atelier ne propose jamais de permettre d'un clic : ils laisseraient
# les agents lancer tout le reste. Comparés au nom de base de chaque mot de la commande proposée
# (« /bin/bash » vaut « bash », « bash.exe » aussi). Un interprète n'en est un que suivi d'une
# option qui exécute du code (`python -c`, `node -e`) : seul, il est déjà permis par le socle
# (`python`, `node`) ou par les commandes par défaut (`python3`).
LANCEURS_GENERAUX = frozenset(
    {
        "sh", "bash", "zsh", "dash", "ksh", "mksh", "ash", "fish", "csh", "tcsh", "pwsh",
        "powershell", "cmd", "env", "eval", "exec", "command", "builtin", "xargs", "time",
        "nohup", "nice", "timeout", "setsid", "stdbuf", "busybox", "parallel", "watch",
        "script", "sudo", "doas", "su", "npx", "pnpx", "bunx", "uvx", "pkexec", "runuser", "chroot",
        "rbash", "nu", "xonsh", "expect", "strace", "toybox", "ssh", "wsl", "awk", "gawk", "mawk",
        "nawk",
    }
)  # fmt: skip
INTERPRETE = re.compile(
    r"(python|pythonw|py|pypy|node|nodejs|perl|ruby|php|deno|bun|lua|luajit|rscript|r|julia"
    r"|osascript|tclsh)[\d.]*"
)
# Un shell dont le nom porte un suffixe de version : « ksh93 », « zsh-5.9 », « bash5 ».
SHELL_VERSIONNE = re.compile(
    r"(sh|bash|zsh|dash|ksh|mksh|ash|fish|csh|tcsh|rbash)([\d.]+|-[\d.]+)"
)
# Un lanceur de paquets n'en est un que suivi de son sous-mot : « yarn dlx », « bun x »...
LANCEURS_DE_PAQUETS = (("yarn", "dlx"), ("bun", "x"), ("uv", "tool", "run"), ("pipx", "run"))
OPTIONS_FIND_QUI_LANCENT = frozenset({"-exec", "-execdir", "-ok", "-okdir"})
OPTION_DE_CODE = re.compile(r"-[a-z]*[cepr]|--(eval|print|command|exec)(=.*)?")
# Un premier mot proposé à la validation doit être un nom de commande simple : pas une variable
# posée devant, pas une option, pas une parenthèse.
MOT_DE_COMMANDE = re.compile(r"[\w./][\w.+/-]*")


def nom_de_base(mot: str) -> str:
    """Le nom d'une commande sans son chemin, ses guillemets ni « .exe », en minuscules."""
    nom = mot.strip("'\"").replace("\\", "/").rsplit("/", 1)[-1]
    return nom.lower().removesuffix(".exe")


def lanceur_general(commande: str) -> bool:
    """Dit si permettre cette commande (un mot ou un préfixe de plusieurs mots) laisserait les
    agents tout lancer : l'un de ses mots est un lanceur général, ou un interprète suivi d'une
    option qui exécute du code. Le seul filtre des lanceurs, pour la validation et le diagnostic."""
    noms = [nom_de_base(m) for m in str(commande).split()]
    for rang, nom in enumerate(noms):
        if nom in LANCEURS_GENERAUX or SHELL_VERSIONNE.fullmatch(nom):
            return True
        if any(tuple(noms[rang : rang + len(p)]) == p for p in LANCEURS_DE_PAQUETS):
            return True
        if nom == "find" and any(o in OPTIONS_FIND_QUI_LANCENT for o in noms[rang:]):
            return True
        if INTERPRETE.fullmatch(nom) and any(OPTION_DE_CODE.fullmatch(o) for o in noms[rang + 1 :]):
            return True
    return False


def lanceurs_proposes(outils) -> list[str]:
    """Les commandes d'un réglage d'outils proposé que `lanceur_general` écarte, dans l'ordre."""
    valeur = outils.get("commandes_permises") if isinstance(outils, dict) else None
    if not isinstance(valeur, list):
        return []
    return [v.strip() for v in valeur if isinstance(v, str) and lanceur_general(v)]


def premier_mot_a_permettre(commande: str) -> str:
    """Le premier mot d'une commande de contrôle, s'il peut être permis sans risque ; sinon ""."""
    mots = commande.split()
    mot = mots[0] if mots else ""
    simple = MOT_DE_COMMANDE.fullmatch(mot) is not None
    return mot if simple and not lanceur_general(mot) else ""


def delier_du_blocage(demande: dict) -> dict:
    """Un réglage d'outils gardé par un nouveau plan perd son lien au blocage de l'ancien chantier,
    et sa question la phrase qui promettait la relance : c'est un réglage ordinaire."""
    if demande.pop("pour_blocage", None) is not None:
        avant, trouvee, _ = demande["question"].rpartition(" " + DEBLOQUE)
        if trouvee:
            demande["question"] = avant
    return demande


def phrase_controles_non_permis(
    refusees: list[str], mots: list[str], sans_reglage: list[str]
) -> str:
    """Ce que l'atelier dit, à la validation, des commandes de contrôle non permises aux agents."""

    def citees(commandes: list[str]) -> str:
        return " ; ".join(f"« {c} »" for c in commandes)

    parties = [
        "Les contrôles que l'atelier rejoue après chaque livrable lancent des commandes que les "
        f"agents n'ont pas le droit de lancer : {citees(refusees)}. Sans elles, un ouvrier ne "
        "peut pas vérifier lui-même son travail, et sa tâche risque d'être refusée pour rien."
    ]
    if mots:
        parties.append("Je te propose de permettre aux agents : " + ", ".join(mots) + ".")
    if sans_reglage:
        parties.append(
            f"Pour {citees(sans_reglage)}, je ne sais pas proposer de réglage sûr : demande à "
            "l'orchestrateur de s'en occuper."
        )
    parties.append("Le chantier démarre quand même.")
    return " ".join(parties)


RACINE_ATELIER = Path(__file__).resolve().parent.parent  # la démonstration cartographie l'Atelier
EN_COURS_TTL_S = 3.0  # le travail en cours des agents est relu au plus toutes les 3 secondes

ACCUEIL = "Bonjour. Dis-moi ce que tu veux construire, je te proposerai un découpage."
CHANTIER_OCCUPE = (
    "Un agent travaille ou l'orchestrateur répond : attends qu'il ait fini, ou arrête-le, "
    "avant d'ouvrir un nouveau chantier."
)
CHANTIER_VIDE = "Ce chantier est encore vide : il n'y a rien à archiver."

# --- le verrou par dépôt : un seul Atelier sur un même dépôt ------------------------------------

VERROU_DEPOT = Path(".atelier") / "verrou"  # le fichier verrouillé, dans le dossier du projet
DEPOT_OCCUPE = (
    "un autre Atelier travaille déjà sur le projet « {nom} » ({dossier}). Je ne l'ouvre pas une "
    "seconde fois : je ne relance rien et je ne touche pas à son chantier. Ferme l'autre Atelier, "
    "ou sers-toi de son tableau de bord."
)


class DepotOccupe(ProjetImpossible):
    """Un autre Atelier tient le verrou de ce dépôt ; le message le dit en clair."""


def _verrouiller(flux) -> bool:
    """Pose sans attendre un verrou exclusif du système sur le fichier ouvert ; rend False s'il
    est déjà tenu, par un autre processus ou par une autre ouverture du même processus.

    Sous Windows, `msvcrt.locking` verrouille le premier octet ; ailleurs, `fcntl.flock`. Le
    système relâche l'un et l'autre quand le fichier est fermé ou que le processus meurt, même
    tué : aucun numéro de processus n'est écrit ni relu.
    """
    try:
        if os.name == "nt":
            import msvcrt

            flux.seek(0)
            msvcrt.locking(flux.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(flux.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


def _deverrouiller(flux) -> None:
    """Relâche le verrou de `_verrouiller` ; la fermeture du fichier le relâcherait aussi."""
    if os.name == "nt":
        import msvcrt

        flux.seek(0)
        msvcrt.locking(flux.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(flux.fileno(), fcntl.LOCK_UN)


class VerrouDepot:
    """Le verrou d'un dépôt : un verrou de fichier du système sur `.atelier/verrou`.

    Tenu par l'Atelier qui a ouvert le projet (`atelier.verrou_depot`) tant qu'il vit ; le
    système le relâche à la mort du processus. Le fichier n'est pas hérité par les agents
    lancés (Python ouvre ses fichiers non héritables), et il reste en place : seul le verrou
    compte, jamais l'existence du fichier.
    """

    def __init__(self, depot):
        self.depot = Path(depot)
        self.chemin = self.depot / VERROU_DEPOT
        self._flux = None

    @property
    def tenu(self) -> bool:
        """Dit si ce verrou-ci est tenu, par cet objet."""
        return self._flux is not None and not self._flux.closed

    def prendre(self) -> bool:
        """Prend le verrou sans attendre ; rend False, sans rien changer, s'il est déjà tenu."""
        if self.tenu:
            return True
        self.chemin.parent.mkdir(parents=True, exist_ok=True)
        flux = open(self.chemin, "a+b")  # noqa: SIM115 : gardé ouvert tant que le verrou est tenu
        if not _verrouiller(flux):
            flux.close()
            return False
        self._flux = flux
        return True

    def relacher(self) -> None:
        """Relâche le verrou s'il est tenu ; sans effet sinon."""
        flux, self._flux = self._flux, None
        if flux is None:
            return
        with suppress(OSError):
            _deverrouiller(flux)
        flux.close()

    def exiger(self) -> VerrouDepot:
        """Prend le verrou et se rend ; lève `DepotOccupe`, en clair, s'il est déjà tenu."""
        if not self.prendre():
            raise DepotOccupe(DEPOT_OCCUPE.format(nom=self.depot.name, dossier=self.depot))
        return self

    def __enter__(self) -> VerrouDepot:
        return self.exiger()

    def __exit__(self, *erreur) -> None:
        self.relacher()


def prendre_le_depot(depot) -> VerrouDepot:
    """Prend le verrou du dépôt et le rend ; lève `DepotOccupe` si un autre Atelier le tient."""
    return VerrouDepot(depot).exiger()


def depot_verrouille(depot) -> bool:
    """Dit si un Atelier, celui-ci compris, tient le verrou du dépôt : sert à tout code qui doit
    le savoir sans le prendre. Ne crée rien dans un dossier qui n'a pas de fichier de verrou."""
    essai = VerrouDepot(depot)
    if not essai.chemin.exists():
        return False
    if essai.prendre():
        essai.relacher()
        return False
    return True


def port_pris(serveur) -> bool:
    """Dit si `serveur` tient son port : sa prise est ouverte et n'écoute que 127.0.0.1."""
    prise = getattr(serveur, "socket", None)
    try:
        return prise is not None and prise.fileno() >= 0 and prise.getsockname()[0] == "127.0.0.1"
    except OSError:
        return False


def phrase_de_reprise(identifiants: list[str], delai_s: float) -> str:
    """L'annonce de la reprise seule : combien de tâches repartent, lesquelles, et quand."""
    nombre = len(identifiants)
    sujet = f"{nombre} tâche" if nombre == 1 else f"{nombre} tâches"
    verbe = "repart seule" if nombre == 1 else "repartent seules"
    secondes = round(delai_s)
    quand = "tout de suite" if secondes <= 0 else f"dans {secondes} seconde"
    quand += "s" if secondes > 1 else ""
    return (
        f"L'Atelier s'était arrêté pendant le chantier : {sujet} ({', '.join(identifiants)}) "
        f"{verbe} {quand}."
    )


def _attendre_le_delai(delai_s: float, annulee: threading.Event) -> bool:
    """L'attente de la reprise : rend vrai si elle a été annulée avant la fin du délai."""
    return annulee.wait(delai_s)


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
        self.fil_diagnostic: threading.Thread | None = None
        # Les demandes de blocage dont le diagnostic attend que la conversation se libère, dans
        # l'ordre où le moteur les a signalées. Protégée par `moteur.verrou`, comme `occupe`.
        self._diagnostics: deque[dict] = deque()
        self.occupe = False
        self.brouillon = {"texte": "", "outils": []}
        self.sur_vue = None
        self.moteur = Moteur(chantier, agent, controles, profil, sur_changement=self._sauver)
        # Les agents lisent à chaque lancement les règles du chantier en cours, quel qu'il soit.
        agent.regles_chantier = self._regles_du_chantier
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
        self._signaler_diagnostics_interrompus()
        self._sauver()

    @property
    def moteur(self) -> Moteur:
        return self._moteur

    @moteur.setter
    def moteur(self, moteur: Moteur) -> None:
        """Chaque moteur que l'atelier crée ou adopte lui signale ses blocages (`_sur_blocage`).

        Un nouveau chantier garde le même moteur, et donc ce rappel.
        """
        moteur.sur_blocage = self._sur_blocage
        self._moteur = moteur

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
        """Le moteur mène le chantier : sa boucle tourne, ou le fil lancé pour elle n'y est pas
        encore entré. Un fil qui finit après la sortie de la boucle ne compte plus : une décision
        reçue à ce moment relance le moteur (`lancer`)."""
        return self.moteur.en_route or self.moteur.fil_attendu(self.fil)

    def vue(self) -> dict:
        autorisations = self.guichet.ouvertes() if self.guichet else []
        with self.moteur.verrou:
            brouillon = {
                "texte": _avant_balises(self.brouillon["texte"]),
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
            for tache in donnees["taches"]:
                if tache["etat"] in ("en_cours", "en_verification"):
                    tache["phase"] = self.moteur.phase(tache["id"])
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

    # --- la reprise seule après un arrêt de l'Atelier ----------------------------

    verrou_depot: VerrouDepot | None = None  # posé par la fabrique de « servir » (avec_annonce)
    fil_reprise: threading.Thread | None = None  # le fil qui attend le délai, puis relance
    _reprise = ""  # "", "attente", "partie" ou "annulee" ; changé sous `moteur.verrou`
    _reprise_annulee: threading.Event | None = None

    def reprendre_apres_arret(self, serveur, attendre=None) -> list[str]:
        """Relance seul, après une annonce et un délai, les tâches qu'un arrêt a interrompues.

        Rien ne part sauf si tout ceci est vrai : un vrai chantier (pas la démonstration),
        `reprise_auto` au profil, le contrat validé, le port pris par `serveur` (`port_pris`),
        le verrou du dépôt tenu par cet Atelier (`verrou_depot`), et au moins une tâche qui
        attend sa reprise (`Moteur.taches_interrompues`). Sinon rien n'est écrit : ni annonce
        ni délai. Une seule reprise par Atelier : un second appel ne fait rien.

        L'annonce va au fil, puis un fil d'arrière-plan (`fil_reprise`) attend
        `reprise_apres_arret_s` : `attendre(delai_s, annulee)` rend vrai si la reprise a été
        annulée entre-temps (par défaut `annulee.wait(delai_s)` ; un test en injecte un qui
        n'attend pas). Rend les identifiants annoncés, [] si rien ne repart.
        """
        with self.moteur.verrou:
            if self._reprise or not self._reprise_permise(serveur):
                return []
            identifiants = self.moteur.taches_interrompues()
            if not identifiants:
                return []
            delai_s = self.moteur.delai_de_reprise()
            self._reprise, self._reprise_annulee = "attente", threading.Event()
            self.moteur.chantier.noter(phrase_de_reprise(identifiants, delai_s))
        self._sauver()
        self.fil_reprise = threading.Thread(
            target=self._relancer_apres_delai,
            args=(serveur, delai_s, attendre or _attendre_le_delai),
            name="atelier-reprise",
            daemon=True,
        )
        self.fil_reprise.start()
        return identifiants

    def _reprise_permise(self, serveur) -> bool:
        """Sous le verrou : les conditions de la reprise seule, hors des tâches à reprendre."""
        verrou = self.verrou_depot
        return (
            self.mode != "démonstration"
            and self.moteur.reprise_auto()
            and self.moteur.chantier.contrat.valide
            and port_pris(serveur)
            and verrou is not None
            and verrou.tenu
        )

    def _relancer_apres_delai(self, serveur, delai_s: float, attendre) -> None:
        """Le fil de la reprise : attend le délai, puis relance, sauf annulation ou erreur.

        Les conditions sont relues à la fin du délai, sous le verrou du moteur, avec la
        relance : une annulation arrivée avant passe, une annulation arrivée après ne trouve
        plus rien qui attende. Sur une erreur, rien ne part seul.
        """
        try:
            if attendre(delai_s, self._reprise_annulee):
                self.annuler_reprise()  # sans effet si elle l'est déjà : le fil l'a dit
                return
            with self.moteur.verrou:
                if self._reprise != "attente":
                    return
                self._reprise = "partie"
                phrase = self._relancer(serveur)
                if phrase:
                    self.moteur.chantier.noter(phrase)
            if phrase:
                self._sauver()
        except Exception as erreur:  # le fil de la reprise ne tombe pas sans le dire
            self._reprise_en_echec(erreur)

    def _relancer(self, serveur) -> str:
        """Sous le verrou, à la fin du délai : relance le moteur s'il le faut ; rend la phrase du
        fil, "" s'il n'y a rien à dire (plus rien n'attend, ou l'Atelier se ferme)."""
        identifiants = self.moteur.taches_interrompues()
        if not identifiants or not self._reprise_permise(serveur):
            return ""
        liste = ", ".join(identifiants)
        if self.en_marche():  # un clic pendant le délai l'a déjà lancé : pas de second départ
            return f"Le chantier tourne déjà : les tâches attendues ({liste}) repartent avec lui."
        self.lancer()
        return f"Reprise après l'arrêt : je relance le chantier ({liste})."

    def _reprise_en_echec(self, erreur: Exception) -> None:
        """Une erreur dans le fil de la reprise : le fil le dit ; si rien n'est encore parti, les
        tâches qui attendaient reviennent à la personne."""
        detail = " ".join(f"{type(erreur).__name__} : {erreur}".split())[:300]
        with suppress(Exception), self.moteur.verrou:
            partie = self._reprise == "partie"
            self._reprise = "partie" if partie else "annulee"
            suite = "" if partie else " Rien n'est reparti seul."
            phrase = f"La reprise après l'arrêt a rencontré une erreur ({detail}).{suite}"
            self.moteur.chantier.noter(phrase)
            if not partie:
                self.moteur.annuler_reprise()
        with suppress(Exception):
            self._sauver()

    def annuler_reprise(self) -> dict:
        """« Arrêter » pendant le délai de la reprise : rien ne part, le fil le dit, et les tâches
        qui l'attendaient reviennent à la personne, travail gardé (`Moteur.annuler_reprise`).

        Rend {"fait", "phrase"}, comme `arreter`. Sans reprise en attente, ne change rien.
        """
        with self.moteur.verrou:
            if self._reprise != "attente":
                phrase = "Aucune reprise n'attend son départ : il n'y a rien à annuler."
                return {"fait": False, "phrase": phrase}
            self._reprise = "annulee"
            self._reprise_annulee.set()
            phrase = "Reprise annulée : aucune tâche n'est repartie seule."
            self.moteur.chantier.noter(phrase)
            self.moteur.annuler_reprise()
        self._sauver()
        return {"fait": True, "phrase": phrase}

    def valider_contrat(self) -> None:
        with self.moteur.verrou:
            neuf = not self.moteur.chantier.contrat.valide
            self.moteur.chantier.contrat.valide = True
            self.moteur.chantier.noter("Contrat validé. Je lance le chantier.")
            if neuf:  # la question se pose une fois, quand la personne valide : elle est là
                self._verifier_les_controles()
        self._sauver()
        self.lancer()

    def _verifier_les_controles(self) -> None:
        """Sous le verrou, à la validation, sans modèle : les contrôles du profil sont-ils permis
        aux agents ? Sinon, une seule demande d'outils propose de permettre leurs premiers mots.

        Le moteur démarre quand même : l'atelier rejoue lui-même ces contrôles après chaque
        livrable, avec ses propres droits ; un agent qui ne peut pas les lancer travaille sans
        eux, ou demande une carte, et un refus qui se répète devient un blocage.
        """
        profil = self.moteur.profil
        commandes = profil.get("commandes", [])
        if not _liste_de_textes(commandes):
            return
        refusees = [c.strip() for c in commandes if c.strip() and not commande_permise(profil, c)]
        if not refusees:
            return
        mots = [premier_mot_a_permettre(c) for c in refusees]
        mots = list(dict.fromkeys(m for m in mots if m and not commande_permise(profil, m)))
        sans_reglage = [c for c in refusees if premier_mot_a_permettre(c) not in mots]
        question = phrase_controles_non_permis(refusees, mots, sans_reglage)
        if mots:  # visible au tableau de bord comme tout réglage d'outils, avant tout lancement
            self._ajouter_reglage(question, {"commandes_permises": mots, "commandes": None})
        else:  # rien à proposer d'un clic : le fil le dit
            self.moteur.chantier.noter(question)

    def decider(self, demande_id: str, choix: str) -> None:
        demande = next(d for d in self.moteur.chantier.demandes if d["id"] == demande_id)
        if demande.get("nature") == "outils":
            return self._regler_outils(demande, choix)
        self.moteur.repondre(demande_id, choix)
        self.lancer()

    # --- les outils du projet ----------------------------------------------------

    def _proposer_outils(self, outils: dict, blocage: dict | None = None) -> dict | None:
        """Transforme un réglage d'outils proposé par l'orchestrateur en décision à prendre.

        Rend la demande créée, ou None si le réglage était illisible. Avec `blocage` (la demande
        de blocage que ce réglage doit lever), la demande porte `pour_blocage` : l'accepter
        relancera seule la tâche bloquée, au même niveau.
        """

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
        en_plus = {}
        if blocage is not None and blocage.get("reponse") is None:
            parties.append(
                f"{DEBLOQUE}{blocage['tache']} : si tu l'acceptes, je la relance seul, au même "
                "niveau."
            )
            en_plus["pour_blocage"] = blocage["id"]
        reglage = {"commandes_permises": permises, "commandes": controles}
        return self._ajouter_reglage(" ".join(parties), reglage, **en_plus)

    def _ajouter_reglage(self, question: str, reglage: dict, **en_plus) -> dict:
        """Ajoute aux décisions une demande d'outils, qu'on accepte ou refuse ; la rend.

        Son identifiant est « outils-N », N le rang qu'elle prend ; s'il est déjà pris (un
        réglage gardé par un nouveau plan), le suivant libre : deux demandes ne se confondent pas.
        """
        with self.moteur.verrou:
            demandes = self.moteur.chantier.demandes
            pris, rang = {d.get("id") for d in demandes}, len(demandes) + 1
            while f"outils-{rang}" in pris:
                rang += 1
            demande = {
                "id": f"outils-{rang}",
                "tache": None,
                "nature": "outils",
                "question": question,
                "options": [ACCEPTER_OUTILS, REFUSER_OUTILS],
                "reponse": None,
                "outils": reglage,
                **en_plus,
            }
            demandes.append(demande)
        return demande

    def _regler_outils(self, demande: dict, choix: str) -> None:
        """Applique (ou écarte) un réglage d'outils, l'écrit dans le profil et le fait valoir.

        Un réglage accepté mais non appliqué (profil illisible ou non écrit) redevient en
        attente : l'accepter à nouveau, une fois le profil corrigé, l'applique. Un réglage qui
        lève un blocage, une fois appliqué, relance seul la tâche bloquée (`_annoncer_reglage`).
        """
        with self.moteur.verrou:
            if demande["reponse"] is not None:
                return
            demande["reponse"] = choix
        if choix != ACCEPTER_OUTILS:
            suite = self._blocage_encore_ouvert(demande)
            return self._dire(f"Réglage des outils écarté : rien n'a changé.{suite}")
        with self._verrou_profil:  # le même verrou que pour une règle « toujours »
            try:
                fichier = self._profil_avec_outils(demande["outils"])
                self._ecrire_profil(fichier)
            except ValueError:
                raison = PROFIL_ILLISIBLE
            except OSError:
                raison = PROFIL_NON_ECRIT
            else:
                raison = ""
                cles = ("commandes_permises", "commandes")
                self._propager({cle: fichier[cle] for cle in cles if cle in fichier})
        if raison:
            return self._rouvrir_reglage(demande, raison)
        if hasattr(self.moteur.controles, "regler_outils"):
            self.moteur.controles.regler_outils(fichier)
        relancee = self._annoncer_reglage(demande, fichier)
        self._sauver()
        if relancee:
            self.lancer()

    def _annoncer_reglage(self, demande: dict, fichier: dict) -> bool:
        """Dit au fil que le réglage est appliqué. S'il lève un blocage qui l'a fait naître et
        attend encore, relance la tâche au même niveau, comme le bouton « Relancer au même
        niveau » (`Moteur.relancer_au_meme_niveau`) ; rend alors True (le moteur est à lancer)."""
        debut = (
            "Outils réglés. Commandes permises aux agents : "
            + ", ".join(fichier["commandes_permises"])
            + "."
        )
        if not demande.get("pour_blocage"):
            self._dire(debut + " Une tâche revenue vers toi peut maintenant être relancée.")
            return False
        with self.moteur.verrou:  # la demande de blocage ne peut pas recevoir d'autre réponse ici
            blocage = self._blocage_lie(demande)
            if blocage is None:
                self._dire(f"{debut} Je ne relance rien : le blocage n'attend plus ta réponse.")
                return False
            # `_blocage_lie` seul sait que ce réglage est né de ce blocage, et il doit conclure
            # avant cette phrase, que le fil montre avant la décision. Sous le même verrou, le
            # blocage qu'il rend attend sa réponse : la relance part, son booléen n'apprend rien.
            self._dire(f"{debut} Je relance seul la tâche {blocage['tache']}, au même niveau.")
            self.moteur.relancer_au_meme_niveau(blocage["id"])
        return True

    def _blocage_lie(self, demande: dict) -> dict | None:
        """Sous le verrou : la demande de blocage que ce réglage d'outils doit lever, si c'est
        bien celle qui l'a fait naître (son diagnostic l'a proposé, et la désigne en retour) et
        si elle attend encore sa réponse ; sinon None. Un identifiant repris par un autre blocage,
        après un nouveau plan, ne suffit donc jamais à relancer une tâche."""
        ident = demande.get("pour_blocage")
        if not ident:
            return None
        for blocage in self.moteur.chantier.demandes:
            if blocage.get("nature") != "blocage" or blocage.get("id") != ident:
                continue
            ne_d_elle = blocage.get("diagnostic") == DIAGNOSTIC_PROPOSE
            if ne_d_elle and blocage.get("reglage") == demande.get("id"):
                return blocage if blocage.get("reponse") is None else None
        return None

    def _blocage_encore_ouvert(self, demande: dict) -> str:
        """Après un réglage écarté : ce qu'il advient du blocage qu'il devait lever, ou ""."""
        with self.moteur.verrou:
            blocage = self._blocage_lie(demande)
            if blocage is None:
                return ""
            return f" La tâche {blocage['tache']} reste bloquée : {BLOCAGE_OUVERT}"

    def _profil_avec_outils(self, outils: dict) -> dict:
        """Sous `_verrou_profil` : le profil lu, avec le réglage d'outils ajouté.

        Lève `ValueError` si le profil est illisible, ou si `commandes_permises` ou `commandes`
        y sont présentes sans être des listes de textes ; `OSError` s'il ne peut pas être lu.
        Sans `commandes_permises` dans le fichier, celles du profil en mémoire valent, si elles
        forment une liste de textes ; sinon on part d'une liste vide.
        """
        fichier = self._lire_profil()
        for cle in ("commandes_permises", "commandes"):
            if cle in fichier and not _liste_de_textes(fichier[cle]):
                raise ValueError(f"« {cle} » n'est pas une liste de textes")
        repli = self.moteur.profil.get("commandes_permises", [])
        if not _liste_de_textes(repli):  # une valeur en mémoire mal formée compte comme absente
            repli = []
        actuelles = fichier.get("commandes_permises", repli)
        fichier["commandes_permises"] = list(
            dict.fromkeys([*actuelles, *(outils["commandes_permises"] or [])])
        )
        if outils["commandes"] is not None:
            fichier["commandes"] = outils["commandes"]
        return fichier

    def _rouvrir_reglage(self, demande: dict, raison: str) -> None:
        """Remet en attente un réglage accepté mais non appliqué, et le dit au fil."""
        with self.moteur.verrou:  # les deux lignes se suivent, la demande redevient cliquable
            demande["reponse"] = None
            chantier = self.moteur.chantier
            chantier.noter(f"Réglage des outils non appliqué : {raison}", auteur="orchestrateur")
            chantier.noter(REESSAYER_OUTILS, auteur="orchestrateur")

    def _propager(self, valeurs: dict) -> None:
        """Met à jour à chaud les profils lus par l'atelier, le moteur et les agents."""
        lus = (self.moteur.profil, getattr(self.moteur.agent, "profil", None))
        for profil in {id(p): p for p in lus if isinstance(p, dict)}.values():
            profil.update(valeurs)

    # --- les autorisations demandées par les agents ------------------------------

    def autoriser(self, identifiant, choix, message="") -> dict:
        """Répond à une demande d'autorisation ouverte et dit si elle a été réglée.

        « Toujours » ajoute la règle de la demande aux autorisations du profil du projet ;
        « chantier » retient ses règles dans l'état du chantier en cours, qui partent avec lui.
        """
        message = message if isinstance(message, str) else ""
        demande = next((d for d in self._ouvertes() if d["id"] == identifiant), None)
        regle = demande["regle"] if demande else ""
        regles = demande.get("regles_chantier", []) if demande else []
        if self.guichet is not None and self.guichet.repondre(identifiant, choix, message):
            if choix == "chantier":
                return {"reglee": True, "phrase": self._retenir_pour_le_chantier(regles)}
            return {"reglee": True, "phrase": self._retenir(choix, regle)}
        if choix not in CHOIX:
            phrase = (
                "Ce choix n'existe pas : réponds « une fois », « toujours », "
                "« pendant ce chantier » ou « non »."
            )
        elif demande is None:
            phrase = (
                "Cette demande n'existe plus : elle a déjà reçu une réponse, "
                "ou son agent s'est arrêté."
            )
        elif choix == "chantier" and not regles:
            phrase = (
                "Aucune règle n'est possible pour cette demande, même pour ce chantier : "
                "autorise-la une fois, ou refuse-la."
            )
        elif choix == "toujours" and not regle:
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
            raison = PROFIL_ILLISIBLE
        except OSError:
            raison = PROFIL_NON_ECRIT
        else:
            with self.moteur.verrou:
                self.moteur.chantier.noter(f"Autorisation retenue pour ce projet : {regle}.")
            self._sauver()
            return f"Autorisé pour ce projet : la règle {regle} est enregistrée dans le profil."
        return f"Autorisé cette fois, mais la règle n'a pas pu être enregistrée : {raison}"

    def _regles_du_chantier(self) -> list[str]:
        """Les règles retenues pour le chantier en cours ; une copie, lue par les agents.

        Sans verrou : un agent la lit à son lancement, parfois sous le verrou du moteur, et
        copier une liste ne laisse rien voir à moitié.
        """
        return list(self.moteur.chantier.autorisations_chantier)

    def _retenir_pour_le_chantier(self, regles: list[str]) -> str:
        """Ajoute les règles, sans doublon, au chantier en cours ; le note au fil et sauve."""
        liste = ", ".join(regles)
        with self.moteur.verrou:  # le chantier ne peut pas être archivé entre-temps
            retenues = self.moteur.chantier.autorisations_chantier
            retenues.extend(r for r in dict.fromkeys(regles) if r not in retenues)
            self.moteur.chantier.noter(f"Autorisation retenue pendant ce chantier : {liste}.")
        self._sauver()
        return (
            f"Autorisé pendant ce chantier : {liste}. Ces règles s'effaceront quand le chantier "
            "sera archivé ; le profil du projet n'est pas touché."
        )

    def _inscrire_regle(self, regle: str) -> None:
        """Ajoute une règle, sans doublon, aux autorisations de `chantier/profil.json`."""
        with self._verrou_profil:
            fichier = self._lire_profil()
            actuelles = fichier.get("autorisations", self.moteur.profil.get("autorisations"))
            regles = list(actuelles) if isinstance(actuelles, list) else []
            if regle not in regles:
                regles.append(regle)
                fichier["autorisations"] = regles
                self._ecrire_profil(fichier)
            self._propager({"autorisations": regles})

    def _lire_profil(self) -> dict:
        """Lit `chantier/profil.json` pour le modifier ; à appeler sous `_verrou_profil`.

        Rend un dictionnaire, vide si le fichier n'existe pas. Lève `ValueError` si le contenu
        n'est pas du JSON ou n'est pas un objet, `OSError` si le fichier ne peut pas être lu.
        """
        chemin = self.depot / "chantier" / "profil.json"
        fichier = json.loads(chemin.read_text("utf-8")) if chemin.exists() else {}
        if not isinstance(fichier, dict):
            raise ValueError("le profil du projet n'est pas lisible")
        return fichier

    def _ecrire_profil(self, fichier: dict) -> None:
        """Écrit `chantier/profil.json` en entier ; à appeler sous `_verrou_profil`.

        D'un seul geste : une écriture interrompue laisse l'ancien profil intact. Crée le
        dossier `chantier` au besoin. Lève `OSError` si l'écriture échoue.
        """
        texte = json.dumps(fichier, ensure_ascii=False, indent=2) + "\n"
        ecrire_d_un_seul_geste(self.depot / "chantier" / "profil.json", texte)

    # --- le mode des ouvriers -----------------------------------------------------

    def changer_mode(self, mode) -> dict:
        """Choisit le mode des ouvriers : l'écrit au profil et l'applique à chaud aux ouvriers.

        Un mode inconnu, mal typé ou « bypassPermissions » est refusé sans rien écrire. Le
        vérificateur et l'orchestrateur ne sont jamais touchés.
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
        try:
            fichier = self._lire_profil()
            fichier[cle] = valeur
            self._ecrire_profil(fichier)
        except ValueError:
            return PROFIL_ILLISIBLE
        except OSError:
            return PROFIL_NON_ECRIT
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
        # Le code de l'Atelier lui-même d'abord : le tirage ne dérive pas vers les scripts d'essai
        # quand le dépôt grandit.
        codes = [c for c in codes if c.startswith("atelier/")] or codes
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
        if not texte:
            return
        with self.moteur.verrou:  # relu sous le verrou : un diagnostic peut prendre la main
            if self.occupe:
                return
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
            self._lancer_diagnostic()  # un blocage signalé pendant la réponse passe maintenant

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
            ecrit = _avant_balises(self.brouillon["texte"]).strip()
        if ecrit:
            self._dire(ecrit)
        self._dire("(Réponse arrêtée par toi. Tu peux écrire la suite.)")

    # --- le diagnostic d'un blocage -------------------------------------------------

    def _sur_blocage(self, demande: dict) -> None:
        """Rappel du moteur quand il bloque une tâche : range sa demande pour un diagnostic.

        Appelé depuis un fil du moteur, hors de son verrou : rend la main tout de suite. Le
        message part dans un fil à part (`_diagnostiquer`) dès que la conversation est libre,
        un seul par demande, dans l'ordre des blocages. Ne lève jamais : une erreur ici ne doit
        pas passer pour une panne de la tâche.
        """
        try:
            with self.moteur.verrou:
                rangee = self._demande_du_chantier(demande)
                if rangee is None or rangee.get("nature") != "blocage" or "diagnostic" in rangee:
                    return
                rangee["diagnostic"] = DIAGNOSTIC_EN_ATTENTE
                self._diagnostics.append(rangee)
            self._lancer_diagnostic()
        except Exception as erreur:
            with suppress(Exception):
                self._dire(f"Je n'ai pas pu faire chercher la cause du blocage ({erreur}).")

    def _demande_du_chantier(self, demande) -> dict | None:
        """Sous le verrou : la demande du chantier en cours, elle-même ou de même identifiant."""
        demandes = self.moteur.chantier.demandes
        trouvee = next((d for d in demandes if d is demande), None)
        if trouvee is None and isinstance(demande, dict):
            trouvee = next((d for d in demandes if d.get("id") == demande.get("id")), None)
        return trouvee

    def _lancer_diagnostic(self) -> None:
        """Envoie le diagnostic suivant si la conversation est libre ; sinon il attend sa fin."""
        with self.moteur.verrou:
            if self.occupe:
                return
            demande = self._prochain_diagnostic()
            if demande is None:
                return
            self.occupe = True
            demande["diagnostic"] = DIAGNOSTIC_EN_COURS
            self.fil_diagnostic = threading.Thread(
                target=self._diagnostiquer, args=(demande,), daemon=True
            )
            self.fil_diagnostic.start()

    def _prochain_diagnostic(self) -> dict | None:
        """Sous le verrou : la prochaine demande rangée qui attend encore, ou None.

        Une demande qui a reçu entre-temps la réponse de la personne, ou qui n'est plus celle
        du chantier en cours, n'est pas envoyée : la question ne se pose plus.
        """
        demandes = self.moteur.chantier.demandes
        while self._diagnostics:
            demande = self._diagnostics.popleft()
            if any(d is demande for d in demandes) and demande["reponse"] is None:
                return demande
            demande["diagnostic"] = "sans_objet"
        return None

    def _diagnostiquer(self, demande: dict) -> None:
        """Dans son fil : demande à l'orchestrateur la cause d'un blocage, et suit sa réponse."""
        try:
            self._recevoir_diagnostic(demande, self._envoyer_diagnostic(demande))
        except Exception as erreur:
            detail = " ".join(f"{type(erreur).__name__} : {erreur}".split())[:300]
            phrase = (
                f"Le diagnostic du blocage de la tâche {demande.get('tache')} a échoué sur une "
                f"erreur de l'Atelier ({detail}) : {BLOCAGE_OUVERT}"
            )
            self._finir_diagnostic(demande, "echec", phrase)
        finally:
            with self.moteur.verrou:
                self.occupe = False
                self.brouillon = {"texte": "", "outils": []}
            self._sauver()
            self._lancer_diagnostic()

    def _envoyer_diagnostic(self, demande: dict):
        """Envoie le message de diagnostic dans la conversation ; rend la réponse."""

        def liste(cle: str) -> list:
            valeur = demande.get(cle)
            return valeur if isinstance(valeur, list) else []

        with self.moteur.verrou:
            tache = self.moteur.chantier.tache(demande["tache"])
            message = message_de_diagnostic(tache, liste("preuves"), liste("empechements"))
            phrase = (
                f"La tâche {tache.id} est bloquée : je demande à l'orchestrateur d'en chercher la "
                "cause, sans t'attendre."
            )
            self.moteur.chantier.noter(phrase, tache.id, auteur="orchestrateur")
        self._sauver()
        return self._interroger(message)

    def _recevoir_diagnostic(self, demande: dict, reponse) -> None:
        """Affiche la réponse au diagnostic ; un bloc d'outils devient une demande liée au blocage.

        Le plan, lui, ne change plus : un bloc de plan rendu ici n'est pas repris.
        """
        tache = demande.get("tache")
        if not reponse.ok and reponse.erreur == ARRETE:
            self._arreter_reponse(reponse)
            phrase = f"Diagnostic du blocage de la tâche {tache} arrêté : {BLOCAGE_OUVERT}"
            return self._finir_diagnostic(demande, "arrete", phrase)
        if not reponse.ok:
            phrase = (
                f"Le diagnostic du blocage de la tâche {tache} a échoué, faute de joindre Claude "
                f"Code ({reponse.erreur}) : {BLOCAGE_OUVERT}"
            )
            return self._finir_diagnostic(demande, "echec", phrase)
        texte, outils = extraire_outils(reponse.texte)
        texte, plan = extraire_plan(texte)
        with self.moteur.verrou:
            self.moteur.chantier.cout_usd += reponse.cout_usd
            self.moteur.chantier.tokens += reponse.tokens
        if texte:
            self._dire(texte)
        if plan:
            self._dire("Plan non repris : le contrat est déjà validé.")
        return self._proposer_pour_blocage(demande, outils)

    def _proposer_pour_blocage(self, demande: dict, outils: dict | None) -> None:
        """Offre d'un clic le réglage rendu par un diagnostic, lié à son blocage ; sauf s'il
        permettrait un lanceur général (`lanceur_general`) : rien n'est alors offert, le fil dit
        pourquoi, et la demande de blocage reste ouverte avec ses options."""
        tache = demande.get("tache")
        lanceurs = lanceurs_proposes(outils)
        if lanceurs:
            citees = ", ".join(f"« {m} »" for m in lanceurs)
            phrase = (
                f"Le diagnostic du blocage de la tâche {tache} propose de permettre aux agents "
                f"{citees}, ce qui leur permettrait de tout lancer : je ne te le propose pas "
                f"d'un clic, et {BLOCAGE_OUVERT}"
            )
            return self._finir_diagnostic(demande, "lanceur", phrase)
        with self.moteur.verrou:  # le lien et son retour posés ensemble : aucun clic entre eux
            reglage = self._proposer_outils(outils, blocage=demande) if outils else None
            if reglage is not None:
                demande["diagnostic"], demande["reglage"] = DIAGNOSTIC_PROPOSE, reglage["id"]
                return None
        phrase = (
            f"Le diagnostic du blocage de la tâche {tache} ne propose aucun réglage d'outils "
            f"utilisable : {BLOCAGE_OUVERT}"
        )
        return self._finir_diagnostic(demande, "sans_proposition", phrase)

    def _finir_diagnostic(self, demande: dict, issue: str, phrase: str) -> None:
        """Note l'issue d'un diagnostic qui ne propose rien, et dit au fil pourquoi."""
        with self.moteur.verrou:
            demande["diagnostic"] = issue
            tache = str(demande.get("tache") or "")
            self.moteur.chantier.noter(phrase, tache, auteur="orchestrateur")

    def _signaler_diagnostics_interrompus(self) -> None:
        """À l'ouverture : un diagnostic resté sans réponse quand l'Atelier s'est arrêté n'est
        pas relancé seul (comme une tâche active, rien ne repart sans la personne) ; le fil le
        dit, une fois."""
        with self.moteur.verrou:
            for demande in self.moteur.chantier.demandes:
                if demande.get("nature") != "blocage" or demande.get("reponse") is not None:
                    continue
                if demande.get("diagnostic", DIAGNOSTIC_EN_ATTENTE) not in DIAGNOSTIC_INACHEVE:
                    continue
                demande["diagnostic"] = "interrompu"
                tache = demande.get("tache")
                self.moteur.chantier.noter(
                    f"Le diagnostic du blocage de la tâche {tache} n'avait pas abouti quand "
                    "l'Atelier s'est arrêté, et je ne le relance pas seul : sa demande reste "
                    "ouverte, avec ses options. Écris-moi si tu veux que l'orchestrateur en "
                    "cherche la cause.",
                    str(tache or ""),
                    auteur="orchestrateur",
                )

    def _adopter(self, plan: dict, demande: str) -> None:
        """Transforme le plan rendu en tâches et en contrat à valider."""
        chantier, agent = self.moteur.chantier, self.moteur.agent
        taches = taches_du_plan(plan, self.moteur.profil)
        with self.moteur.verrou:
            if chantier.contrat.valide and not chantier.termine:
                return chantier.noter("Plan non repris : le contrat est déjà validé.")
            if not taches:
                return chantier.noter("Le plan rendu ne contenait aucune tâche lisible.")
            # Un réglage d'outils rendu avec le plan, ou avant lui, attend toujours sa réponse ;
            # celui qui devait lever un blocage de l'ancien chantier n'est plus qu'un réglage.
            reglages = [
                delier_du_blocage(d)
                for d in chantier.demandes
                if d.get("nature") == "outils" and d["reponse"] is None
            ]
            chantier.taches, chantier.demandes, chantier.termine = taches, reglages, False
            chantier.agents_lances = chantier.montees = 0
            chantier.contrat = Contrat(
                objectif=str(plan.get("objectif") or demande),
                hors_perimetre=str(plan.get("hors_perimetre") or ""),
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
    """Répond aux demandes du tableau de bord, pour le projet affiché.

    Le serveur n'écoute que la machine, mais une page d'un autre site ouverte dans le même
    navigateur peut s'adresser à lui : chaque demande passe d'abord par `_refus`.
    """

    projets = None  # les projets de l'atelier (atelier.projets.Projets)
    suivi = None  # la mise à jour d'Atelier (SuiviMiseAJour), ou None
    apres = None  # à faire une fois la réponse envoyée (l'arrêt après une mise à jour)

    # Au-delà, un corps n'est pas lu : aucune demande du tableau de bord n'approche cette taille.
    LONGUEUR_MAX = 8 * 1024 * 1024
    # Ce que le navigateur dit de la provenance d'une demande : la page elle-même, ou la barre
    # d'adresse. Tout le reste (un autre site, un site voisin) est refusé.
    PROVENANCES = ("same-origin", "none")
    HOTE_REFUSE = "Cette adresse n'est pas celle du tableau de bord."
    AUTRE_SITE = "Cette demande vient d'un autre site : elle est refusée."
    PAS_DU_JSON = "Une demande qui change quelque chose doit être écrite en JSON."
    LONGUEUR_ILLISIBLE = "La longueur annoncée de la demande est illisible."
    CORPS_ILLISIBLE = "Demande introuvable ou incomplète."
    SORTE_REFUSEE = "Le tableau de bord n'accepte pas cette sorte de demande."
    DEMANDE_ILLISIBLE = "Cette demande est illisible pour le tableau de bord."

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

    def _hotes(self) -> set[str]:
        """Les deux noms du tableau de bord, avec le port réel du serveur."""
        port = self.server.server_address[1]
        return {f"127.0.0.1:{port}", f"localhost:{port}"}

    def _refus(self, ecriture: bool = False) -> tuple[int, str] | None:
        """Le code et la phrase du refus, ou None si la demande vient bien du tableau de bord.

        - l'en-tête Host doit être l'un des deux noms du tableau, au bon port : un nom de site
          qui se ferait passer pour la machine (une page qui a repris l'adresse 127.0.0.1) est
          refusé, comme un Host absent ;
        - une demande qui dit venir d'un autre site (Origin, Sec-Fetch-Site) est refusée ;
        - une écriture doit être du JSON, ce qu'une page d'un autre site ne peut pas envoyer
          sans l'accord du serveur, qui ne le donne jamais (aucun Access-Control-Allow-*).
        """
        hotes = self.headers.get_all("Host") or []
        if len(hotes) != 1 or hotes[0].strip().lower() not in self._hotes():
            return 403, self.HOTE_REFUSE
        origines = self.headers.get_all("Origin") or []
        permises = {f"http://{hote}" for hote in self._hotes()}
        if len(origines) > 1 or any(o.strip().lower() not in permises for o in origines):
            return 403, self.AUTRE_SITE
        provenance = self.headers.get("Sec-Fetch-Site")
        if provenance is not None and provenance.strip().lower() not in self.PROVENANCES:
            return 403, self.AUTRE_SITE
        nature = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if ecriture and nature != "application/json":
            return 415, self.PAS_DU_JSON
        return None

    def _longueur(self) -> int | None:
        """La longueur annoncée du corps (0 sans en-tête), None si illisible ou démesurée."""
        if "Transfer-Encoding" in self.headers:
            return None  # un corps en morceaux : le tableau de bord n'en envoie jamais
        brut = self.headers.get("Content-Length")
        if brut is None:
            return 0
        if not re.fullmatch(r"[0-9]{1,10}", brut.strip()) or int(brut) > self.LONGUEUR_MAX:
            return None
        return int(brut)

    def _lire_corps(self) -> tuple[int | None, bytes]:
        """Lit le corps annoncé, même s'il doit être refusé : la réponse arrive alors entière."""
        longueur = self._longueur()
        return longueur, self.rfile.read(longueur) if longueur else b""

    def _sorte_refusee(self) -> None:
        """OPTIONS, PUT, DELETE, PATCH : jamais d'accord, en particulier pour un autre site."""
        self._lire_corps()
        self.send_response(405)
        self.send_header("Allow", "GET, POST")
        corps = json.dumps({"erreur": self.SORTE_REFUSEE}, ensure_ascii=False).encode("utf-8")
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(corps)))
        self.end_headers()
        self.wfile.write(corps)

    do_OPTIONS = do_PUT = do_DELETE = do_PATCH = _sorte_refusee

    def send_error(self, code: int, message=None, explain=None) -> None:
        """Les erreurs que relève http.server lui-même (sorte de demande inconnue, ligne
        illisible) : en JSON et en français, comme les autres refus."""
        phrase = self.SORTE_REFUSEE if code == 501 else self.DEMANDE_ILLISIBLE
        corps = json.dumps({"erreur": phrase}, ensure_ascii=False).encode("utf-8")
        self.close_connection = True
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(corps)))
        self.send_header("Connection", "close")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(corps)

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
        refus = self._refus()
        if refus:
            return self._json({"erreur": refus[1]}, refus[0])
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
        longueur, brut = self._lire_corps()
        refus = self._refus(ecriture=True)
        if refus:
            return self._json({"erreur": refus[1]}, refus[0])
        if longueur is None:
            return self._json({"erreur": self.LONGUEUR_ILLISIBLE}, 400)
        try:
            corps = json.loads(brut or b"{}")
            action = ROUTES.get(self.path)
            if action is None:
                return self._json({"erreur": "Adresse inconnue."}, 404)
            if not isinstance(corps, dict):
                raise ValueError("corps illisible")
            en_plus = action(self, corps)
        except ProjetImpossible as erreur:
            return self._json({"erreur": str(erreur)}, 400)
        except (KeyError, StopIteration, ValueError):
            return self._json({"erreur": self.CORPS_ILLISIBLE}, 400)
        self._json({**self.vue(), **(en_plus or {})})
        if self.apres:
            self.wfile.flush()  # la page a sa réponse : le processus peut s'arrêter
            self.apres()


def _creer_projet(requete, corps) -> None:
    """Crée le projet ; la réponse est la vue, déjà celle du nouveau projet."""
    requete.projets.creer(corps["nom"])


def _cloner_projet(requete, corps) -> None:
    """Récupère le dépôt ; la réponse est la vue, déjà celle du nouveau projet."""
    requete.projets.cloner(corps["adresse"])


# Chaque route reçoit la requête et le corps lu ; elle peut rendre des champs de plus pour la
# réponse, qui est sinon la vue du tableau de bord.
ROUTES = {
    "/api/contrat/valider": lambda r, c: r.atelier.valider_contrat(),
    "/api/decision": lambda r, c: r.atelier.decider(c["id"], c["choix"]),
    "/api/message": lambda r, c: r.atelier.message(c["texte"]),
    "/api/projets/creer": _creer_projet,
    "/api/projets/cloner": _cloner_projet,
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
