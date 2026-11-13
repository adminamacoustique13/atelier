"""Le moteur : un chef de chantier en code.

Il lance les ouvriers, contrôle leur travail, fait passer le vérificateur, redonne la main à
l'ouvrier refusé dans sa session, monte d'un cran après un échec et s'arrête quand il sort du
contrat. Il bloque une tâche que relancer ne ferait pas avancer (un agent empêché, un même refus
qui se répète) et la rend à la personne avec une demande claire. Aucun modèle ne décide de ces
étapes : elles se déroulent de la même façon à chaque fois.

Il garde au travail jusqu'à `paralleles` ouvriers à la fois (le profil, 6 sans réglage), plus
les vérificateurs, qui ne tiennent pas de place d'écriture (`atelier/places.py`). Un agent refusé
pour une limite de l'abonnement, ou parce que Claude est surchargé, n'est pas un échec : les
lancements visés sont suspendus, et la tâche repart seule à la fin de la suspension, au même
niveau, sans rien compter.
"""

from __future__ import annotations

import re
import threading
import time
import unicodedata
import weakref
from collections.abc import Callable, Collection
from contextlib import suppress
from dataclasses import dataclass, replace
from itertools import dropwhile
from pathlib import Path

from atelier import dosage, refus
from atelier.agents import (
    FORME_COURTE,
    LIMITE_ATTEINTE,
    REPRISE_IMPOSSIBLE,
    SURCHARGE,
    Resultat,
    commande_permise,
    forme_courte,
    lire_garde,
)
from atelier.consignes import (
    PREUVE_MAX_CARACTERES,
    PREUVES_MAX,
    conflits_en_clair,
    consigne_ouvrier,
    consigne_planification,
    consigne_reprise,
    consigne_reverification,
    consigne_verificateur,
    consigne_verificateur_bornee,
    dernier_json,
    lire_verdict,
)
from atelier.controles import fichiers_partages, hors_perimetre, motif_partage, se_chevauchent
from atelier.guichet import ARRETE, CHAINE
from atelier.modele import Chantier, Tache
from atelier.places import Places, heure_dite, phrase_de_suspension

ACTIFS = ("en_cours", "en_verification")
# L'issue d'une tentative coupée par une panne de l'Atelier lui-même (git, disque, redémarrage) :
# la tâche revient à la personne responsable, sans seconde chance ni montée.
PANNE = "panne"
MOTIF_REDEMARRAGE = (
    "l'Atelier s'est arrêté pendant qu'elle était en cours (redémarrage ou panne). Ce que "
    "l'agent avait fait sans l'enregistrer est perdu."
)
DETAIL_REDEMARRAGE = "Interrompue par un arrêt de l'Atelier."
# La reprise seule après un arrêt (décision du 2026-11-13, qui remplace la règle ci-dessus sauf
# avec `reprise_auto: false` au profil) : au chargement, une tâche laissée active redevient « à
# lancer » avec une entrée d'issue `interrompue`, et le serveur la relance après une annonce et
# un délai (`reprise_apres_arret_s`). Au-delà de `INTERRUPTIONS_MAX` interruptions d'une même
# tâche, la suivante la rend à la personne : un Atelier qui tomberait en boucle ne la relance pas
# sans fin.
INTERROMPUE = "interrompue"
INTERRUPTIONS_MAX = 3
REPRISE_APRES_ARRET_S = 30
DETAIL_INTERROMPUE = "Interrompue par un arrêt de l'Atelier ; elle repart seule."
MOTIF_TROP_D_ARRETS = (
    f"l'Atelier s'est arrêté {INTERRUPTIONS_MAX + 1} fois pendant qu'elle travaillait. Je ne la "
    "relance plus seule, pour ne pas tourner en boucle : dis-moi si je la relance."
)
MOTIF_REPRISE_ANNULEE = (
    "tu as arrêté sa reprise après l'arrêt de l'Atelier : elle n'est pas repartie et attend ta "
    "décision."
)
RELANCER, ABANDONNER = "Relancer un cran plus haut", "Abandonner cette tâche"
RELANCER_TEL = "Relancer au même niveau"
# Le motif d'une tâche que la personne responsable a arrêtée : ni seconde chance, ni montée.
ARRETEE = "arretee"
MOTIF_ARRET = "arrêtée par toi."
DETAIL_ARRET = "Arrêtée par la personne responsable."
# Sans intervention : une tâche épuisée est relancée seule, un cran plus haut, une seule fois ;
# des contrôles rouges sur la branche principale lancent seuls une tâche de réparation.
RELANCES_AUTO = 1
MAX_REPARATIONS = 2
PREFIXE_REPARATION = "REPARATION-"
# La reprise à chaud : après un refus du vérificateur, du contrôle du périmètre ou des contrôles,
# l'ouvrier reprend la main dans sa session et sa copie, avec le refus en entier. Elle ne compte
# pas parmi les tentatives (qui bornent les départs neufs) : elle a sa borne, par départ neuf.
REPRISES_PAR_DEPART = 1
# Avec un ouvrier gardé ouvert (`_garde`) : combien de fois un contrôle rouge, ou un manque
# relevé, lui revient dans un même départ (réglages `retours_controles` et `complements`).
RETOURS_CONTROLES = 3
COMPLEMENTS = 1
REPONSE_AU_FIL = 300  # signes gardés de la réponse d'un ouvrier qui n'a rien changé
# Quand le modèle monte après un refus (réglage `montee` du profil) : "fond", seulement si le
# vérificateur juge le fond faux ; "refus", après tout refus, comme avant le 2026-11-13.
MONTEES = ("fond", "refus")
# Le budget du chantier en dollars (`budget_usd` au profil, gardé dans `contrat.max_cout_usd`).
NATURE_BUDGET = "budget"
RALLONGE_BUDGET = 1.2  # relancer une tâche arrêtée par le budget l'allonge d'un cinquième
MOTIF_BUDGET = (
    "le budget du chantier est atteint ({depense:.2f} $ dépensés pour {budget:.2f} $). La "
    "relancer accorde une rallonge d'un cinquième."
)
COUT_INCOMPLET = (
    "Le coût de cet agent est incomplet : il a été coupé avant son message de fin. Le total du "
    "chantier est donc sous-estimé."
)
MONTEE_SANS_REGLAGE = "fond"
MOTIFS_REPRIS = ("bacle", "ne_sait_pas")  # un verdict « consigne » revient à la personne
VERDICT_GARDE = 8000  # les derniers caractères du texte du vérificateur, gardés et transmis
SORTIE_REPRISE = 4000  # les derniers caractères de la sortie des contrôles, pour la reprise
# D'où vient un refus, écrit dans l'entrée d'historique (`origine`) ; "" pour une tentative
# acceptée, arrêtée ou coupée par une panne. « agent » : l'ouvrier, ou le vérificateur, s'est
# arrêté sur une erreur (délai, panne de Claude Code). Une limite de l'abonnement ou une
# surcharge n'est pas un refus : rien n'est tracé (voir `_suspendre`).
ORIGINES = ("agent", "perimetre", "controles", "verdict", "integration")
ORIGINES_FR = {
    "agent": "erreur d'agent",
    "perimetre": "contrôle du périmètre",
    "controles": "contrôles automatiques",
    "verdict": "vérificateur",
    "integration": "enregistrement",
}
# Le blocage : une tâche que relancer ne ferait pas avancer revient à la personne avec une
# demande de nature « blocage » (voir `_bloquer`), et les autres tâches continuent. Trois
# causes, selon la règle d'usage du cahier (« V3-refus ») ; la demande cite les refus comparés
# (`_refus_compares`) pour que la personne voie s'ils disent vraiment la même chose.
NATURE_BLOCAGE = "blocage"
EMPECHE = "empeche"  # un agent empêché de travailler (voir `Moteur._empeche`)
SANS_CRAN = "sans_cran"  # un refus identique au précédent, et plus aucun cran pour monter
REPETE = "repete"  # trois refus de même forme de suite, même si un cran reste
NOMBRES = ("une", "deux", "trois", "quatre", "cinq", "six", "sept", "huit", "neuf", "dix")
DETAIL_CITE = 300  # les derniers caractères d'un détail cité dans la question
AFFECTATION = re.compile(r"[A-Za-z_]\w*=\S*")  # une variable posée devant une commande
# La fin de la note d'un livrable accepté malgré des outils refusés à l'ouvrier, selon qu'il y en a
# un seul ou plusieurs, et que ce sont tous des commandes (à permettre dans les outils du projet).
FINS_D_OUTILS_REFUSES = {
    (True, True): "Si cette commande doit servir aux agents, tu peux la leur permettre dans les "
    "outils du projet.",
    (False, True): "Si ces commandes doivent servir aux agents, tu peux les leur permettre dans "
    "les outils du projet.",
    (True, False): "Si cet outil doit servir aux agents, tu peux le leur permettre.",
    (False, False): "Si ces outils doivent servir aux agents, tu peux les leur permettre.",
}
NON_REFUS = ("valide", ARRETEE, PANNE)  # les issues d'historique qui ne sont pas des refus
# Le travail refusé est gardé dans sa copie (`Tache.copie`) : le départ suivant le reprend sur
# place. Elle est jetée après un refus de ces origines, qui la laisse porter ce qu'il ne faut pas
# garder (un débord, un état de fusion) ; aussi pour un arrêt par la personne, un abandon, une
# panne de l'Atelier, et quand le travail est entré.
COPIE_JETEE = ("perimetre", "integration")
# L'entrée d'une tâche interrompue par un arrêt de l'Atelier ; avec `pendant: "verification"`,
# l'ouvrier avait rendu son travail et seul le jugement est à refaire (`Moteur._rejuger`).
INTERROMPUE = "interrompue"
HORS_REFUS = (*NON_REFUS, INTERROMPUE, "attente_panne")  # ni refus ni remarque pour la suite
TRAVAIL_GARDE = (
    "Travail gardé dans sa copie de travail ({}) : une relance le reprend là où il en est, un "
    "abandon le jette."
)
# La boucle d'`executer` et les tâches qui attendent une place, un jeton ou la fin d'une
# suspension dorment au plus ce temps ; un changement les réveille aussitôt (`_signaler`).
PAS_VEILLE_S = 5.0
# Une panne d'agent (`Resultat.nature` « panne » : réseau, service) ne dit rien du travail : la
# tâche patiente, de plus en plus longtemps, puis repart seule au même niveau, sans compter ni
# tentative, ni agent, ni refus (`Moteur._apres_une_panne`). Une panne de plus après la dernière
# pause compte comme une erreur d'agent ordinaire. Réglable par le profil (`pauses_panne_s`).
PAUSES_PANNE_S = (60, 300, 900, 1800, 3600)
NATURE_PANNE, NATURE_CONNEXION = "panne", "connexion"
# L'issue d'historique d'une passe qu'une panne d'agent a coupée : ni un essai, ni un refus ; la
# passe suivante reprend son numéro de tentative.
ATTENTE_PANNE = "attente_panne"
NON_REFUS += (ATTENTE_PANNE,)
# Une connexion à Claude perdue ne revient pas seule : seule la personne peut se reconnecter. Le
# fil le lui dit une fois, avec le geste, et les lancements sont réessayés toutes les cinq minutes
# (`places.PAUSE_CONNEXION_S`).
CONNEXION_PERDUE = (
    "Ta connexion à Claude a expiré ou manque : aucun agent ne peut travailler tant que tu ne "
    "t'es pas reconnecté. Ouvre un terminal (PowerShell sous Windows), tape « claude », puis "
    "« /login », et choisis ton compte avec abonnement. Je réessaie seul toutes les cinq "
    "minutes, sans rien compter contre les tâches."
)


def pauses_du_profil(profil: dict) -> tuple[float, ...]:
    """Les pauses après une panne d'agent, en secondes : celles du profil (`pauses_panne_s`),
    une liste de nombres positifs ou nuls ; absente ou mal formée, `PAUSES_PANNE_S`. Une liste
    vide coupe la patience : la première panne compte alors comme une erreur d'agent."""
    lues = profil.get("pauses_panne_s") if isinstance(profil, dict) else None
    if not isinstance(lues, (list, tuple)):
        return PAUSES_PANNE_S
    bonnes = all(  # ni texte, ni booléen, ni négatif, ni infini, ni « nan » (aucune comparaison)
        isinstance(p, (int, float)) and not isinstance(p, bool) and 0 <= p < float("inf")
        for p in lues
    )
    return tuple(lues) if bonnes else PAUSES_PANNE_S


def _quand_repart(pause: float, reprise: float, heure: float) -> str:
    """« à 14:05 (dans 5 minutes) » ; « dans un instant » sous une minute."""
    if pause < 60:
        return "dans un instant"
    minutes = round(pause / 60)
    return f"{heure_dite(reprise, heure)} (dans {minutes} minute{'s' if minutes > 1 else ''})"


@dataclass(frozen=True)
class Jugement:
    """Ce que le moteur conclut d'une passe de l'ouvrier : accepté (`motif` None) ou refusé.

    `complet` est ce que reçoit l'ouvrier repris : le verdict entier, la liste des fichiers hors
    périmètre, la fin de la sortie des contrôles, ou la liste des fichiers en conflit de fusion
    (`conflits_en_clair`). `verdict` est le texte du vérificateur de cette passe (ses
    `VERDICT_GARDE` derniers caractères), s'il a fini son tour. `reprenable` dit
    si l'ouvrier peut reprendre la main ; `reprise`, si la passe jugée était une reprise.
    `empechements` : ce que l'ouvrier ou le vérificateur ont signalé comme les empêchant de
    travailler, et les outils refusés à l'ouvrier (`refus.empechements`) ; `refuses_seuls` :
    parmi eux, les outils refusés qu'aucun agent ne signale aussi, que la reprise cite à
    l'ouvrier ; `blocage` : la cause qui bloque la tâche, "" sinon.

    Ce qui servira à décider après un refus, sans rien décider ici (valeurs neutres par défaut) :
    `lisible`, le vérificateur a rendu un verdict lisible ; `nature`, celle du résultat de l'agent
    quand l'échec vient de lui ; `reste` et `fichiers`, ceux du verdict (pour un refus des
    contrôles automatiques, `reste` porte ce qui a échoué) ; `meme_defaut`, dit par le
    vérificateur d'une retouche ; `fond_faux`, le vérificateur juge le fond faux (`_fond_faux`).
    """

    motif: str | None
    detail: str
    origine: str = ""
    complet: str | list[str] = ""
    verdict: str = ""
    reprenable: bool = False
    reprise: bool = False
    empechements: tuple[str, ...] = ()
    blocage: str = ""
    refuses_seuls: tuple[str, ...] = ()
    lisible: bool = False
    nature: str = ""
    reste: tuple[str, ...] = ()
    fichiers: tuple[str, ...] = ()
    meme_defaut: bool = False
    fond_faux: bool = False

    @property
    def signales(self) -> tuple[str, ...]:
        """Ce que les agents ont signalé eux-mêmes : les empêchements, hors outils refusés seuls."""
        return tuple(e for e in self.empechements if e not in self.refuses_seuls)

    def pour_la_suite(self) -> str:
        """Ce que reçoit le départ neuf qui suit : le verdict entier s'il y en a un, sinon le
        détail du refus."""
        return self.verdict if self.origine == "verdict" and self.verdict.strip() else self.detail


ARRET = Jugement(ARRETEE, DETAIL_ARRET)

# Les genres de vérification d'une passe (`Verification.genre`) : selon le niveau de la tâche,
# la retouche de ce qu'un vérificateur a relevé, la relecture qui suit la reprise d'un refus
# du fond, ou celle qui suit la reprise d'un conflit de fusion.
COMPLETE, BORNEE = dosage.COMPLETE, dosage.BORNEE
RETOUCHE, REVERIFICATION, CONFLIT = "retouche", "reverification", "conflit"
# Les motifs d'un refus lisible qui laissent le reste du travail acquis : le vérificateur écrit
# ce qu'il a relevé (`Tache.releve`), et la vérification suivante est une retouche.
MOTIFS_RELEVES = ("bacle", "local")
ENTREE_SANS_VERIFICATEUR = (
    "Entrée sans vérificateur : vérification mécanique seule, le contrôle du périmètre et les "
    "contrôles automatiques ont passé."
)
MECANIQUE_SANS_CONTROLE = (
    "Le profil n'a aucune commande de contrôle : une tâche mécanique ne peut pas être jugée par "
    "les seuls contrôles automatiques, elle reçoit donc une vérification bornée."
)
TYPE_INCONNU = (
    "Le type de cette tâche ({type}) n'est pas un type connu : elle sera vérifiée complètement, "
    "quel que soit le profil."
)


@dataclass(frozen=True)
class Verification:
    """Comment une passe est vérifiée : le genre (`COMPLETE`, `BORNEE`, `RETOUCHE`,
    `REVERIFICATION` ou `CONFLIT`), le dosage du vérificateur, la sortie des contrôles que le
    moteur vient de jouer (None quand il n'a rien joué), pour une retouche les fichiers changés
    depuis ce que le vérificateur précédent a vu (vide quand on ne sait pas les dire), et l'état
    de la copie que ce vérificateur va voir (`empreinte`, "" quand on ne sait pas le dire)."""

    genre: str
    modele: str
    effort: str
    sortie: str | None = None
    fichiers: tuple[str, ...] = ()
    empreinte: str = ""


def _court(texte: object, longueur: int) -> str:
    """Un texte sur une ligne, réduit à ses `longueur` derniers caractères, sans point final."""
    ligne = " ".join(str(texte or "").split())
    if len(ligne) > longueur:
        ligne = "[…] " + ligne[-longueur:]
    return ligne.rstrip(" .")


def _preuve(entree: dict) -> str:
    """Une preuve de blocage : le détail d'un refus, précédé de sa tentative et de son origine.

    Le détail garde ses lignes (une sortie de tests se lit ainsi) et ses
    `PREUVE_MAX_CARACTERES` derniers caractères : la cause est presque toujours à la fin.
    """
    tete = f"Tentative {entree.get('tentative', '?')}"
    tete += " (reprise)" if entree.get("reprise") else ""
    origine = ORIGINES_FR.get(entree.get("origine") or "", entree.get("issue") or "")
    detail = str(entree.get("detail") or "").strip()
    if len(detail) > PREUVE_MAX_CARACTERES:
        detail = "[…] " + detail[-PREUVE_MAX_CARACTERES:]
    return f"{tete}, {origine} : {detail}"


def _formes_lancees(commande: str) -> list[str]:
    """Les commandes que lance une chaîne Bash, chacune sous sa forme courte (`forme_courte`).

    La chaîne est coupée comme au guichet (`guichet.CHAINE` : &&, ||, ;, |, &) ; chaque commande
    perd les variables posées devant elle (`FOO=1 uv run pytest`), et un `cd …` ne lance rien.
    """
    formes = []
    for morceau in CHAINE.split(commande):
        mots = list(dropwhile(AFFECTATION.fullmatch, morceau.split()))
        if mots and mots[0] != "cd":
            formes.append(forme_courte({"name": "Bash", "input": {"command": " ".join(mots)}}))
    return formes


def _commande_bash(forme: str) -> str:
    """La commande d'un outil Bash, lue dans sa forme courte (« uv sync » pour « Bash(uv sync) »,
    `agents.FORME_COURTE`) ; "" pour un autre outil."""
    trouve = FORME_COURTE.fullmatch(forme)
    return trouve[1] if trouve and forme.startswith("Bash(") else ""


def _note_d_outils_refuses(refuses: tuple[str, ...]) -> str:
    """La note au fil d'un livrable accepté malgré des outils refusés à l'ouvrier, accordée à
    leur nombre ; elle ne parle de commande que si tous en sont (`FINS_D_OUTILS_REFUSES`)."""
    liste = " ; ".join(f"« {_court(r, DETAIL_CITE)} »" for r in refuses)
    seul = len(refuses) == 1
    constat = "Un outil a été refusé" if seul else "Des outils ont été refusés"
    commandes = all(_commande_bash(r) for r in refuses)
    return (
        f"{constat} à l'ouvrier pendant cette tâche : {liste}. Le livrable a quand même été "
        f"accepté et enregistré. {FINS_D_OUTILS_REFUSES[seul, commandes]}"
    )


def _refus_compares(fenetre: list[dict], cause: str) -> list[dict]:
    """Les refus que cite la question d'un blocage, pris à la fin de la fenêtre : le dernier
    pour un empêchement ; sinon toute la suite sur laquelle la règle a conclu, de refus de même
    forme (`REPETE`) ou identiques (`SANS_CRAN`), pour que la question en dise le vrai nombre."""
    if cause == EMPECHE:
        nombre = 1
    elif cause == REPETE:
        nombre = refus.refus_de_meme_forme_de_suite(fenetre)
    else:
        nombre = refus.refus_identiques_de_suite(fenetre)
    return fenetre[len(fenetre) - nombre :]


def _fois(nombre: int) -> str:
    """« deux fois », « trois fois »… : le nombre en lettres jusqu'à dix, en chiffres au-delà."""
    lettres = NOMBRES[nombre - 1] if 1 <= nombre <= len(NOMBRES) else str(nombre)
    return f"{lettres} fois"


def _raison_de_blocage(jugement: Jugement, cites: list[dict]) -> str:
    """La raison écrite dans la question d'une demande de blocage : la cause en une phrase, puis
    les détails des refus comparés (`_refus_compares`), pour que la personne voie une éventuelle
    confusion."""
    details = [f"« {_court(e.get('detail'), DETAIL_CITE)} »" for e in cites] or ["« »"]
    if jugement.blocage == EMPECHE:
        empeches = jugement.empechements[:PREUVES_MAX]
        liste = " ; ".join(f"« {_court(e, DETAIL_CITE)} »" for e in empeches)
        return (
            f"elle est bloquée parce qu'un agent a été empêché de travailler : {liste}. La "
            "relancer telle quelle buterait au même endroit tant que la cause reste là. Le "
            f"refus : {details[-1]}."
        )
    fois = _fois(len(cites))
    if jugement.blocage == REPETE:
        cause = (
            f"parce qu'elle a été refusée {fois} de suite pour la même raison : la relancer, "
            "même un cran plus haut, a peu de chances d'y changer quelque chose."
        )
    elif jugement.origine == "agent":
        cause = (
            f"parce que les agents se sont arrêtés {fois} de suite sur la même erreur, et "
            "qu'une erreur d'agent ne fait pas monter d'un cran : la relancer telle quelle ne "
            "changerait rien."
        )
    else:
        cause = (
            f"parce qu'elle a été refusée {fois} de suite pour la même raison, et que le "
            "contrat ne permet plus de monter d'un cran : la relancer telle quelle ne changerait "
            "rien."
        )
    return (
        f"elle est bloquée {cause} Les refus comparés : {' ; '.join(details)}. Si tu vois qu'ils "
        "ne disent pas la même chose, relance-la au même niveau."
    )


def _en_clair(erreur: Exception) -> str:
    """Une erreur de l'Atelier sur une ligne : son type et son message, 500 caractères au plus."""
    return " ".join(f"{type(erreur).__name__} : {erreur}".split())[:500]


class ContratNonValide(Exception):
    """Levée quand on tente de lancer un chantier dont le contrat n'est pas validé."""


def planifier(agent, objectif: str, profil: dict, dossier=None) -> list[Tache]:
    """Demande au modèle le plus capable de découper l'objectif, puis dose chaque tâche."""
    resultat = agent.executer(
        consigne_planification(objectif, profil),
        "fable",
        "high",
        dossier,
        lecture_seule=True,
        contexte={"role": "orchestrateur"},
    )
    return taches_du_plan(dernier_json(resultat.texte) or {}, profil)


CHAMPS_DU_PLAN = ("id", "titre", "type", "pourquoi", "criteres", "perimetre", "depend_de")
CHAMPS_DU_PLAN += ("fournit", "attend", "ajoutee")


# Les types de tâche que le produit connaît : ceux que l'orchestrateur choisit (`dosage.TYPES_FR`)
# et ceux qui ont un niveau de vérification de départ (`dosage.NIVEAU_DEPART`, réparation comprise).
TYPES_CONNUS = tuple(dict.fromkeys([*dosage.TYPES_FR, *dosage.NIVEAU_DEPART]))


def _type_du_plan(ecrit) -> str:
    """Le type d'une tâche tel que le plan l'écrit, ramené à sa forme connue quand il n'en
    diffère que par la casse, les accents ou les espaces autour (« Délicate », « physique  »).

    Un type qui reste inconnu est gardé tel qu'écrit (un texte vide pour une valeur nulle) : il
    n'est jamais confondu avec « courante », et le moteur le vérifie complètement."""
    texte = ecrit if isinstance(ecrit, str) else ("" if ecrit is None else str(ecrit))
    decompose = unicodedata.normalize("NFKD", texte.strip().lower())
    simple = "".join(c for c in decompose if not unicodedata.combining(c))
    return simple if simple in TYPES_CONNUS else texte


def taches_du_plan(plan: dict, profil: dict) -> list[Tache]:
    """Construit les tâches d'un plan rendu par l'orchestrateur, et dose chacune.

    Le type est ramené à sa forme connue (`_type_du_plan`) ; un type inconnu reste tel quel, et
    son ouvrier est dosé comme une tâche courante (`dosage.depart`), comme avant."""
    taches = []
    for brut in plan.get("taches") or []:
        if not isinstance(brut, dict) or not brut.get("id") or not brut.get("titre"):
            continue
        tache = Tache(**{cle: brut[cle] for cle in CHAMPS_DU_PLAN if cle in brut})
        tache.type = _type_du_plan(tache.type)
        tache.modele, tache.effort = dosage.depart(tache.type, profil.get("dosage"))
        taches.append(tache)
    return taches


# Les phases d'une tâche active, telles que le tableau de bord les écrit.
PHASES = {
    "preparation": "Préparation de sa copie de travail",
    "ouvrier": "L'ouvrier travaille (tentative {})",
    "reprise": "L'ouvrier reprend son travail après un refus (tentative {})",
    "perimetre": "Contrôle du périmètre",
    "controles": "Contrôles automatiques : ",
    "verificateur": "Le vérificateur relit ({})",
    "enregistrement": "Enregistrement et fusion",
    "place": "Attend une place d'écriture",
    "jeton": "Attend qu'un agent se libère",
    "pause": "En pause : les lancements reprennent {}",
    "panne": "Patiente après une panne de l'agent : nouvel essai {}",
}
# La clé de l'attente avant le départ, rangée avec les durées des phases (voir `_tracer`).
ATTENTE = "attente"


def cle_de_phase(phrase: str) -> str:
    """La clé de `PHASES` d'une phrase de phase, reconnue au texte qui précède son premier `{`.

    Une phrase qui ne vient d'aucune entrée de `PHASES` rend « autre » : elle est mesurée quand
    même, sous ce nom.
    """
    for cle, modele in PHASES.items():
        if phrase.startswith(modele.split("{")[0]):
            return cle
    return "autre"


class Moteur:
    """Conduit un chantier du contrat validé jusqu'à la dernière tâche vérifiée."""

    def __init__(
        self,
        chantier: Chantier,
        agent,
        controles,
        profil: dict | None = None,
        sur_changement: Callable[[], None] | None = None,
        horloge: Callable[[], float] | None = None,
        heure: Callable[[], float] | None = None,
    ):
        self.chantier = chantier
        # Une horloge monotone, en secondes : remplaçable dans les tests, jamais l'heure du mur.
        self.horloge = horloge or time.monotonic
        # L'heure du mur, en secondes Unix : celle des limites de l'abonnement, que les places
        # comparent aux heures de remise à zéro du SDK. Remplaçable dans les tests.
        self.heure = heure or time.time
        self.agent = agent
        self.controles = controles
        self.profil = profil or {}
        self.sur_changement = sur_changement or (lambda: None)
        # Appelé avec la demande, juste après qu'une tâche a été bloquée, hors du verrou ; jamais
        # pour une demande relue après un redémarrage. Une erreur qu'il lève est notée au fil.
        self.sur_blocage: Callable[[dict], None] | None = None
        self.verrou = threading.RLock()
        self._arretees: set[str] = set()  # les tâches dont l'arrêt est demandé, pas encore pris
        self._enregistrement: set[str] = set()  # acceptées : l'arrêt vient trop tard
        # Où en est chaque tâche active, en mémoire seulement : (phrase, depuis). Le tableau de
        # bord le montre même quand aucun agent ne tourne (copie, contrôles, fusion).
        self.phases: dict[str, tuple[str, float]] = {}
        # La mesure, sans rien décider : la phase mesurée de chaque tâche (clé, début), les
        # durées de sa tentative en cours, son attente avant le départ, et les moments où une
        # tâche est devenue prête (dépendance vérifiée, relance décidée, lancement du moteur).
        self._mesure: dict[str, tuple[str, float]] = {}
        self._durees: dict[str, dict[str, float]] = {}
        self._attentes: dict[str, float] = {}
        self._verifiee_a: dict[str, float] = {}
        self._relancee_a: dict[str, float] = {}
        self._lance_a = self.horloge()
        self._principale_rouge = False  # les réparations n'ont pas suffi : chantier pas fini
        # Le débit, sous le verrou comme le reste : les places d'écriture, les jetons d'agent et
        # les suspensions pour limite (relues du profil à chaque tour), les tâches qui ont leur
        # fil, et `en_route` tant qu'`executer` mène le chantier (une décision part aussitôt).
        self.places = Places()
        self._en_vol: set[str] = set()
        self._veulent_ecrire: dict[str, str] = {}  # tâches en vol sans place -> modèle
        self.en_route = False
        self._lancements = 0  # le numéro du dernier `executer` qui a pris la route
        self._fils_entres: weakref.WeakSet = weakref.WeakSet()  # entrés dans `executer`
        # Le réveil de ceux qui attendent (la boucle d'`executer`, les tâches en file) : un numéro
        # qui monte à chaque signal, pour qu'aucun ne se perde (`_signaler`, `_dormir`).
        self._reveil = threading.Condition()
        self._generation = 0
        for tache in chantier.taches:
            tache.pannes = 0  # une série de pannes ne survit pas à un redémarrage
            if not tache.modele:
                tache.modele, tache.effort = dosage.depart(tache.type, self.profil.get("dosage"))
        self._reprendre()

    # --- petits outils -------------------------------------------------------------

    def _noter(self, texte: str, tache: Tache | None = None) -> None:
        with self.verrou:
            self.chantier.noter(texte, tache.id if tache else "")
        self.sur_changement()

    def _phase(self, tache: Tache, phrase: str) -> None:
        """Note la phase : en mémoire, le tableau de bord la relit à chaque passage.

        Elle clôt aussi la mesure de la phase précédente et ouvre celle-ci : sa durée entre
        dans la tentative en cours, et `_tracer` l'écrit dans l'historique.
        """
        cle, maintenant = cle_de_phase(phrase), self.horloge()
        with self.verrou:
            self.phases[tache.id] = (phrase, maintenant)
            self._clore_mesure(tache.id, maintenant)
            self._mesure[tache.id] = (cle, maintenant)

    def _clore_mesure(self, identifiant: str, maintenant: float) -> None:
        """Sous le verrou : ajoute aux durées de la tentative celle de la phase mesurée."""
        mesuree = self._mesure.pop(identifiant, None)
        if mesuree is not None:
            durees = self._durees.setdefault(identifiant, {})
            durees[mesuree[0]] = durees.get(mesuree[0], 0.0) + maintenant - mesuree[1]

    def _partir(self, tache: Tache, heure: float) -> bool:
        """Sous le verrou : fait partir une tâche prête qui a sa place et son jeton
        (`Places.partir`), dans son propre fil ; sinon ne change rien et rend False.

        Note aussi son attente depuis qu'elle est prête : au lancement du moteur, à la
        vérification de sa dernière dépendance, ou à la relance décidée par la personne
        responsable, selon ce qui vient en dernier. Si son fil ne démarre pas, elle rend sa
        place et revient à la personne avec l'erreur, comme après une panne de l'Atelier.
        """
        if not self.places.partir(tache.id, tache.modele, heure):
            return False
        tache.etat = "en_cours"
        moments = [self._lance_a, self._relancee_a.pop(tache.id, self._lance_a)]
        moments += [self._verifiee_a.get(d, self._lance_a) for d in tache.depend_de]
        self._attentes[tache.id] = max(0.0, self.horloge() - max(moments))
        self._en_vol.add(tache.id)
        fil = threading.Thread(target=self._traiter, args=(tache,), name=f"atelier-{tache.id}")
        try:
            fil.start()
        except Exception as erreur:  # plus de fil possible, par exemple
            self._en_vol.discard(tache.id)
            self.places.finir(tache.id, heure)
            detail = _en_clair(erreur)
            raison = f"une erreur de l'Atelier l'a empêchée de partir. {detail}"
            self._demander(tache, raison, detail)
        return True

    def phase(self, identifiant: str) -> dict | None:
        """La phase en cours d'une tâche active et depuis combien de secondes, ou None."""
        with self.verrou:
            trouvee = self.phases.get(identifiant)
        if trouvee is None:
            return None
        return {"texte": trouvee[0], "depuis_s": round(self.horloge() - trouvee[1])}

    def _prendre_agent(self) -> None:
        """Compte un lancement d'agent, pour le bilan."""
        with self.verrou:
            self.chantier.agents_lances += 1

    def _compter(self, tache: Tache, resultat) -> None:
        with self.verrou:
            tache.cout_usd += resultat.cout_usd
            tache.tokens += resultat.tokens
            self.chantier.cout_usd += resultat.cout_usd
            self.chantier.tokens += resultat.tokens
        if getattr(resultat, "cout_incomplet", False):
            self._noter(COUT_INCOMPLET, tache)

    # --- le budget en dollars ---------------------------------------------------------------

    def _budget(self) -> float:
        """Le budget du chantier en dollars ; 0 : aucun. Celui du contrat, sinon celui du profil
        (`budget_usd`), recopié alors dans le contrat pour qu'une rallonge ait où s'écrire."""
        contrat = self.chantier.contrat
        with self.verrou:
            if contrat.max_cout_usd <= 0:
                regle = self.profil.get("budget_usd")
                lisible = isinstance(regle, (int, float)) and not isinstance(regle, bool)
                if lisible and regle > 0:
                    contrat.max_cout_usd = float(regle)
            return max(0.0, contrat.max_cout_usd)

    def _budget_atteint(self) -> bool:
        budget = self._budget()
        with self.verrou:
            return budget > 0 and self.chantier.cout_usd >= budget

    def _plafond(self) -> dict:
        """Ce qu'un appel d'agent ajoute pour qu'il ne dépasse pas ce qui reste du budget ; rien
        sans budget, ni pour un agent qui ne sait pas tenir un plafond (`plafonne_la_depense`)."""
        budget = self._budget()
        if budget <= 0 or not getattr(self.agent, "plafonne_la_depense", False):
            return {}
        with self.verrou:
            reste = budget - self.chantier.cout_usd
        return {"budget_usd": round(reste, 4)} if reste > 0 else {}

    def _rendre_pour_budget(self, tache: Tache) -> None:
        """Rend la tâche à la personne parce que le budget est atteint ; son travail, s'il y
        en a, reste dans sa copie. La relancer accorde une rallonge (`repondre`)."""
        with self.verrou:
            raison = MOTIF_BUDGET.format(
                depense=self.chantier.cout_usd, budget=self.chantier.contrat.max_cout_usd
            )
        self._rendre(tache, raison, nature=NATURE_BUDGET)

    def _rallonger(self, demande: dict) -> str:
        """Sous le verrou : la rallonge qu'accorde la relance d'une tâche arrêtée par le budget.
        Rend la phrase à dire au fil, ou "" quand il n'y a rien à allonger (le budget a déjà été
        relevé par une autre relance)."""
        contrat, depense = self.chantier.contrat, self.chantier.cout_usd
        if demande.get("nature") != NATURE_BUDGET or contrat.max_cout_usd <= 0:
            return ""
        if depense < contrat.max_cout_usd:
            return ""
        avant = contrat.max_cout_usd
        contrat.max_cout_usd = round(max(avant, depense) * RALLONGE_BUDGET, 2)
        return (
            f"Budget relevé d'un cinquième à ta demande : {avant:.2f} $ deviennent "
            f"{contrat.max_cout_usd:.2f} $."
        )

    def _tracer(
        self,
        tache: Tache,
        issue: str,
        detail: str,
        decalage: int = 0,
        origine: str = "",
        reprise: bool = False,
        verdict: str = "",
    ) -> None:
        """Sous le verrou : ajoute à l'historique de la tâche l'entrée d'une tentative.

        Le décalage vaut 1 pour une tentative arrêtée avant son départ, qui n'a pas encore été
        comptée dans `tache.tentatives`.

        L'entrée porte aussi `durees` : les secondes de chaque phase de la tentative, par clé de
        `PHASES`, et `attente` pour la première tentative d'un départ. La phase en cours est
        close ici ; une tentative jugée valide marque le moment où la tâche est vérifiée.

        Elle porte enfin `origine` (d'où vient le refus, parmi `ORIGINES`, "" sinon), `reprise`
        (vrai pour la passe d'une reprise à chaud, qui garde le numéro de son départ) et
        `verdict` (le texte du vérificateur de cette passe, "" s'il n'a rien rendu).
        """
        maintenant = self.horloge()
        self._clore_mesure(tache.id, maintenant)
        durees = self._durees.pop(tache.id, {})
        if tache.id in self._attentes:
            durees = {ATTENTE: self._attentes.pop(tache.id), **durees}
        if issue == "valide":
            self._verifiee_a[tache.id] = maintenant
        tache.historique.append(
            {
                "tentative": tache.tentatives + decalage,
                "modele": tache.modele,
                "effort": tache.effort,
                "issue": issue,
                "detail": detail,
                "origine": origine,
                "reprise": reprise,
                "verdict": verdict,
                "durees": {cle: round(secondes, 3) for cle, secondes in durees.items()},
            }
        )

    def _sous_plafond(self, suivant: tuple[str, str] | None) -> bool:
        """Dit si le cran proposé par `dosage.monter` existe et reste sous le plafond du contrat."""
        contrat = self.chantier.contrat
        plafond = (contrat.plafond_modele, contrat.plafond_effort)
        return suivant is not None and dosage.dans_plafond(*suivant, plafond)

    def _rendre(self, tache: Tache, raison: str, **en_plus) -> dict:
        """Rend une tâche à la personne responsable, avec une seule décision à prendre.

        `en_plus` : des clés ajoutées à la demande (celles d'un blocage). Rend la demande. Quand
        le travail de la tâche est gardé dans sa copie, la question le dit, avec le chemin de la
        copie (`TRAVAIL_GARDE`).
        """
        with self.verrou:
            tache.etat = "revenu"
            garde = f" {TRAVAIL_GARDE.format(tache.copie)}" if tache.copie else ""
            demande = {
                "id": f"{tache.id}-{len(self.chantier.demandes) + 1}",
                "tache": tache.id,
                "question": f"Tâche {tache.id}, « {tache.titre} » : {raison}{garde}",
                "options": [RELANCER_TEL, RELANCER, ABANDONNER],
                "reponse": None,
                **en_plus,
            }
            self.chantier.demandes.append(demande)
        self._noter(f"J'ai besoin de toi : {raison}", tache)
        return demande

    # --- les pannes de l'Atelier lui-même ------------------------------------------

    def _demander(self, tache: Tache, raison: str, detail: str) -> None:
        """Sous le verrou : rend la tâche après une panne, avec sa trace et sa décision."""
        tache.etat = "revenu"
        self._tracer(tache, PANNE, detail)
        self.chantier.demandes.append(
            {
                "id": f"{tache.id}-{len(self.chantier.demandes) + 1}",
                "tache": tache.id,
                "question": f"Tâche {tache.id}, « {tache.titre} » : {raison}",
                "options": [RELANCER_TEL, RELANCER, ABANDONNER],
                "reponse": None,
            }
        )
        self.chantier.noter(f"J'ai besoin de toi : {raison}", tache.id)

    def _reprendre(self) -> None:
        """Au chargement : remet en ordre les tâches qu'un arrêt de l'Atelier a laissées actives.

        Un moteur neuf n'a encore lancé aucun agent : une tâche « en cours » ou « en
        vérification » vient donc d'un état relu, et plus rien ne travaille pour elle. Sans cela
        elle ne repartirait jamais, et retiendrait celles qui dépendent d'elle ou partagent son
        périmètre. Par défaut elle redevient « à lancer » (`_interrompre`) ; avec
        `reprise_auto: false` au profil, elle est rendue à la personne, comme avant le
        2026-11-13. Rien n'est lancé ni sauvé ici : celui qui monte le moteur sauve ensuite, et
        seul le serveur relance (`Atelier.reprendre_apres_arret`).
        """
        auto = self.reprise_auto()
        with self.verrou:
            for tache in self.chantier.taches:
                if tache.etat not in ACTIFS:
                    continue
                if auto:
                    self._interrompre(tache)
                else:
                    self._demander(tache, MOTIF_REDEMARRAGE, DETAIL_REDEMARRAGE)

    def _interrompre(self, tache: Tache) -> None:
        """Sous le verrou, au chargement : une tâche active redevient « à lancer ».

        Son historique reçoit une entrée d'issue `interrompue`, au numéro de la tentative
        coupée. Ce numéro est rendu (la tentative ne compte pas), sauf si la tâche était en
        vérification avec une copie gardée : l'ouvrier avait rendu son travail, l'entrée porte
        `pendant: "verification"` et seul le jugement reste à refaire. Après `INTERRUPTIONS_MAX`
        interruptions, la suivante rend la tâche à la personne, avec la raison en clair.
        """
        if self.interruptions(tache) >= INTERRUPTIONS_MAX:
            self._demander(tache, MOTIF_TROP_D_ARRETS, DETAIL_REDEMARRAGE)
            return
        rejugee = tache.etat == "en_verification" and bool(tache.copie)
        self._tracer(tache, INTERROMPUE, DETAIL_INTERROMPUE)
        if rejugee:
            tache.historique[-1]["pendant"] = "verification"
        elif tache.tentatives > 0:
            tache.tentatives -= 1
        tache.etat = "a_lancer"

    @staticmethod
    def interruptions(tache: Tache) -> int:
        """Le nombre d'entrées `interrompue` de l'historique de la tâche : ses arrêts subis."""
        return sum(1 for entree in tache.historique if entree.get("issue") == INTERROMPUE)

    def reprise_auto(self) -> bool:
        """Dit si une tâche interrompue repart seule : vrai sauf `reprise_auto: false` au profil
        (seul le booléen faux compte ; toute autre valeur vaut vrai)."""
        return self.profil.get("reprise_auto") is not False

    def delai_de_reprise(self) -> float:
        """Les secondes entre l'annonce de la reprise et la relance : `reprise_apres_arret_s` du
        profil, un nombre positif ou nul ; absent ou mal formé, `REPRISE_APRES_ARRET_S`."""
        valeur = self.profil.get("reprise_apres_arret_s", REPRISE_APRES_ARRET_S)
        nombre = isinstance(valeur, (int, float)) and not isinstance(valeur, bool)
        if not nombre or not 0 <= valeur < float("inf"):  # NaN échoue aussi la comparaison
            return float(REPRISE_APRES_ARRET_S)
        return float(valeur)

    def taches_interrompues(self) -> list[str]:
        """Les tâches qui attendent leur reprise seule : « à lancer », et dont la dernière entrée
        d'historique est `interrompue`. Relu de l'état, cela survit à un nouvel arrêt pendant
        le délai ; une tâche revenue, bloquée ou arrêtée par la personne n'en est jamais."""
        with self.verrou:
            return [
                t.id
                for t in self.chantier.taches
                if t.etat == "a_lancer"
                and t.historique
                and t.historique[-1].get("issue") == INTERROMPUE
            ]

    def annuler_reprise(self) -> list[str]:
        """Rend à la personne les tâches qui attendent leur reprise seule, sans rien lancer.

        Aucune entrée n'est ajoutée : la dernière reste `interrompue`, et le travail gardé l'est
        encore quand la personne relance. Rend leurs identifiants.
        """
        with self.verrou:
            identifiants = self.taches_interrompues()
            for identifiant in identifiants:
                self._rendre(self.chantier.tache(identifiant), MOTIF_REPRISE_ANNULEE)
        return identifiants

    def _panne(self, tache: Tache, erreur: Exception) -> None:
        """Rend à la personne responsable une tâche coupée par une erreur de l'Atelier.

        Une étape git qui échoue, un disque plein, un agent qui lève : la tâche revient avec
        l'erreur écrite en clair, et les autres tâches continuent. Une tâche déjà vérifiée ou
        déjà rendue garde son état : l'erreur (souvent la sauvegarde) est seulement écrite au fil.
        """
        detail = _en_clair(erreur)
        raison = f"une erreur de l'Atelier l'a interrompue, pas l'agent. {detail}"
        with self.verrou:
            if tache.etat in ACTIFS:
                self._demander(tache, raison, detail)
            else:
                texte = f"Une erreur de l'Atelier a suivi cette tâche. {detail}"
                self.chantier.noter(texte, tache.id)
        with suppress(Exception):  # la sauvegarde peut être la panne elle-même
            self.sur_changement()

    # --- l'arrêt d'une tâche -------------------------------------------------------

    def arreter(self, identifiant: str) -> bool:
        """Arrête une tâche en cours ou en vérification et la rend à la personne responsable.

        Rend False si elle n'est ni l'une ni l'autre, ou si elle est déjà acceptée et en cours
        d'enregistrement : l'arrêt ne pèse alors sur rien. Quand aucun agent n'est en marche
        (entre l'ouvrier et le vérificateur, ou juste avant leur départ), c'est ce drapeau, relu
        juste avant chaque lancement d'agent, qui retient la tâche : une fois l'arrêt demandé,
        plus aucun agent ne démarre pour elle.
        """
        with self.verrou:
            tache = next((t for t in self.chantier.taches if t.id == identifiant), None)
            if tache is None or tache.etat not in ACTIFS:
                return False
            if identifiant in self._enregistrement:
                return False
            self._arretees.add(identifiant)
            self._signaler()  # une tâche en file (place, jeton, suspension) cesse d'attendre
        self.agent.arreter(identifiant)
        return True

    def enregistree(self, identifiant: str) -> bool:
        """Dit si la tâche est vérifiée, ou acceptée et en cours d'enregistrement."""
        with self.verrou:
            tache = next((t for t in self.chantier.taches if t.id == identifiant), None)
            return identifiant in self._enregistrement or bool(tache and tache.etat == "verifie")

    def _arretee(self, tache: Tache, resultat=None) -> bool:
        """Dit si la tâche a été arrêtée, par le drapeau ou par le résultat de l'agent."""
        with self.verrou:
            demande = tache.id in self._arretees
            self._arretees.discard(tache.id)
        return demande or (resultat is not None and resultat.erreur == ARRETE)

    # --- ordonnancement ------------------------------------------------------------

    def _prochaine(self, sauf: Collection[str] = ()) -> Tache | None:
        """Rend une tâche prête : dépendances vérifiées, périmètre libre hors fichiers partagés ;
        aucune de `sauf`."""
        taches = self.chantier.taches
        verifiees = {t.id for t in taches if t.etat == "verifie"}
        actives = [t for t in taches if t.etat in ACTIFS]
        partages = fichiers_partages(self.profil)
        for tache in taches:
            if tache.id in sauf:
                continue
            if tache.etat != "a_lancer" or not set(tache.depend_de) <= verifiees:
                continue
            if any(se_chevauchent(tache.perimetre, a.perimetre, partages) for a in actives):
                continue
            return tache
        return None

    def executer(self) -> None:
        """Lance tout ce qui peut l'être, en parallèle, jusqu'à ce que plus rien ne bouge.

        Chaque tâche part dans son propre fil dès qu'elle a sa place (`_lancer_pretes`) : au
        tour de la boucle, et aussitôt qu'une place ou un jeton se libère ou qu'une décision
        arrive. `en_route` dit que la boucle mène le chantier. Un `executer` appelé pendant
        qu'elle tourne n'en mène pas une seconde : il attend qu'elle ait fini.
        """
        with self.verrou:
            self._fils_entres.add(threading.current_thread())
            if not self.chantier.contrat.valide:
                raise ContratNonValide("Le contrat de chantier n'est pas validé.")
            suivre = self.en_route
            if not suivre:
                self._lancements += 1
                lancement, self._lance_a, self.en_route = self._lancements, self.horloge(), True
        if suivre:
            return self._attendre_la_fin()
        try:
            self._mener()
        finally:  # une panne du moteur ne laisse pas croire qu'il tourne encore, mais un
            with self.verrou:  # lancement plus récent garde la route
                if self._lancements == lancement:
                    self.en_route = False

    def fil_attendu(self, fil: threading.Thread | None) -> bool:
        """Dit si `fil`, parti pour exécuter `executer`, n'y est pas encore entré : il prendra la
        route (ou suivra celle qui tourne). Un fil pas encore parti ne compte pas."""
        return fil is not None and fil.ident is not None and fil not in self._fils_entres

    def _attendre_la_fin(self) -> None:
        """Pour un `executer` de trop : attend que la boucle qui tourne ait fini."""
        while True:
            with self.verrou:
                if not self.en_route:
                    return
                vue = self._generation
            self._dormir(vue, PAS_VEILLE_S)

    def _mener(self) -> None:
        """La boucle de réveil d'`executer`.

        Elle dort jusqu'à un signal (une tâche finie, une place ou un jeton rendu, une
        décision, un arrêt), jusqu'à la fin d'une alerte ou d'une suspension, et au plus
        `PAS_VEILLE_S`. Quand rien n'est en vol ni n'attend, elle contrôle la branche
        principale, puis conclut ; elle ne sort que sous le verrou, si rien n'est reparti
        depuis : une décision arrivée pendant la conclusion relance la boucle.
        """
        conclu = False
        while True:
            with self.verrou:
                occupe = self._lancer_pretes() or bool(self._en_vol)
                if conclu and not occupe:
                    self.en_route = False  # sous le verrou : la décision qui suit relancera
                    self._signaler()
                    return
                vue, delai = self._generation, self._veille()
            if occupe:
                conclu = False
                self._dormir(vue, delai)
            elif not self._reparer_si_besoin():  # une réparation ajoutée part au tour suivant
                self._conclure()
                conclu = True

    def _lancer_pretes(self) -> bool:
        """Sous le verrou : relit les places du profil, sert les vérificateurs en file, fait
        partir chaque tâche prête qui a sa place, et range l'état des places dans le chantier.

        Une tâche déjà en vol qui attend une place pour repartir écrire (`_prendre_place`) passe
        avant toute tâche neuve : tant que l'une d'elles pourrait partir dès qu'une place se
        libère (son modèle n'est pas suspendu), aucune tâche neuve ne part. Rend vrai si une
        tâche attend encore : une place, un jeton ou la fin d'une suspension.
        """
        self.places.regler(self.profil.get("paralleles"), self.profil.get("agents_max"))
        heure = self.heure()
        if self.places.servir(heure):
            self._signaler()
        en_vol_d_abord = any(
            self.places.suspension(modele, heure) is None
            for modele in self._veulent_ecrire.values()
        )
        attend = en_vol_d_abord or self._faire_partir_les_neuves(heure)
        self.chantier.debit = self.places.etat(heure)
        return attend

    def _faire_partir_les_neuves(self, heure: float) -> bool:
        """Sous le verrou : fait partir les tâches prêtes, dans l'ordre, tant qu'elles ont leur
        place ; rend vrai si l'une d'elles attend encore.

        Une tâche dont seul le modèle est suspendu laisse partir celles d'un autre modèle. Une
        tâche dont le fil finit encore part au signal de sa fin.
        """
        attend, sautees = False, set(self._en_vol)
        while (tache := self._prochaine(sautees)) is not None:
            if self._partir(tache, heure):
                continue
            attend = True
            if self.places.suspension(tache.modele, heure) is None:
                break  # ni place ni jeton : aucune autre tâche ne partirait
            sautees.add(tache.id)
        return attend

    def _reveiller(self) -> None:
        """Sous le verrou, après un changement des places ou une décision : fait partir ce qui
        le peut si la boucle d'`executer` tourne, puis réveille ceux qui attendent."""
        if self.en_route:
            self._lancer_pretes()
        self._signaler()

    def _signaler(self) -> None:
        """Sous le verrou : réveille la boucle d'`executer` et les tâches qui attendent."""
        with self._reveil:
            self._generation += 1
            self._reveil.notify_all()

    def _dormir(self, vue: int, delai: float) -> None:
        """Hors du verrou : dort au plus `delai` secondes, sauf si un signal a suivi `vue`.

        `vue` est le numéro lu sous le verrou avec ce qui a décidé d'attendre : un signal donné
        entre-temps n'est jamais perdu.
        """
        with self._reveil:
            if self._generation == vue:
                self._reveil.wait(delai)

    def _veille(self) -> float:
        """Sous le verrou : le temps de sommeil, jusqu'à la prochaine fin d'alerte ou de
        suspension, au plus `PAS_VEILLE_S`."""
        heure = self.heure()
        echeance = self.places.prochaine_echeance(heure)
        return PAS_VEILLE_S if echeance is None else min(PAS_VEILLE_S, echeance - heure)

    def _attendre(
        self,
        tache: Tache,
        obtenir: Callable[[float], bool],
        phrase_d_attente: Callable[[float], str],
    ) -> None:
        """Essaie `obtenir(heure)` sous le verrou jusqu'à ce qu'il réussisse, ou que l'arrêt de
        la tâche soit demandé.

        `obtenir` peut agir : prendre une place et un jeton s'ils sont libres. Entre deux essais,
        la phase de la tâche dit ce qu'elle attend (`phrase_d_attente(heure)`) et se mesure ;
        elle se réveille à chaque signal, à la fin d'une suspension, et au plus toutes les
        `PAS_VEILLE_S` secondes.
        """
        while True:
            with self.verrou:
                heure = self.heure()
                if tache.id in self._arretees or obtenir(heure):
                    return
                phrase = phrase_d_attente(heure)
                if self.phases.get(tache.id, ("",))[0] != phrase:
                    self._phase(tache, phrase)
                vue, delai = self._generation, self._veille()
            self._dormir(vue, delai)

    def _phrase_d_attente(self, modele: str, heure: float, manque: str) -> str:
        """Sous le verrou : ce qu'attend une tâche, pour sa phase. La fin d'une suspension de
        `modele` s'il est suspendu, sinon ce qui lui `manque` (« place » ou « jeton »)."""
        reprise = self.places.suspension(modele, heure)
        if reprise is None:
            return PHASES[manque]
        return PHASES["pause"].format(heure_dite(reprise, heure))

    def _prendre_place(self, tache: Tache) -> None:
        """La tâche repart écrire : attend la place et le jeton de son ouvrier, ou l'arrêt.

        Pour chaque ouvrier qui n'a pas reçu sa place au départ de la tâche : départ neuf après
        un refus, reprise à chaud, relance après une limite. Elle passe avant les tâches neuves
        (`_lancer_pretes`). Une tâche qui tient un jeton sans place et ne peut pas partir le rend
        (`Places.partir`) : il va aussitôt à qui l'attend.
        """

        def obtenir(heure: float) -> bool:
            tenait = self.places.a_son_jeton(tache.id)
            partie = self.places.partir(tache.id, tache.modele, heure)
            if partie:
                del self._veulent_ecrire[tache.id]
            if partie or tenait != self.places.a_son_jeton(tache.id):
                self._reveiller()  # l'état des places est rangé, un jeton rendu va à qui l'attend
            return partie

        def phrase_d_attente(heure: float) -> str:
            plein = self.places.en_ecriture() >= self.places.places_effectives(heure)
            return self._phrase_d_attente(tache.modele, heure, "place" if plein else "jeton")

        with self.verrou:
            tache.etat = "en_cours"
            self._veulent_ecrire[tache.id] = tache.modele
        try:
            self._attendre(tache, obtenir, phrase_d_attente)
        finally:  # arrêtée avant d'avoir sa place : les tâches neuves ne l'attendent plus
            with self.verrou:
                if self._veulent_ecrire.pop(tache.id, None) is not None:
                    self._reveiller()

    def _attendre_jeton(self, tache: Tache, modele: str | None = None) -> None:
        """La tâche passe en vérification et rend sa place, qui va aussitôt à une tâche prête ;
        attend le jeton de son vérificateur (`Places.en_verification`), ou l'arrêt.

        `modele` : celui du vérificateur qui va partir, selon le niveau de vérification ; sans
        lui, un modèle au-dessus de l'ouvrier."""
        if modele is None:
            modele, _ = dosage.verificateur(tache.modele, tache.effort)
        with self.verrou:
            tache.etat = "en_verification"
            self.places.en_verification(tache.id, modele, self.heure())
            self._reveiller()
        self._attendre(
            tache,
            lambda _: self.places.a_son_jeton(tache.id),
            lambda heure: self._phrase_d_attente(modele, heure, "jeton"),
        )

    def _malgre_les_limites(self, tache: Tache, attendre, lancer):
        """Lance un agent dès que `attendre(tache)` rend la main ; refusé pour limite ou
        surcharge, sans connexion ou en panne (`_suspendre`, qui patiente le temps de la pause),
        l'attend à nouveau (la fin de la suspension) et le relance, sans rien compter. Rend le
        résultat du dernier lancé, ou None si l'arrêt l'a retenu (`lancer` rend alors None)."""
        while True:
            attendre(tache)
            resultat = lancer()
            if resultat is None or not self._suspendre(tache, resultat):
                return resultat

    def _suspendre(self, tache: Tache, resultat) -> bool:
        """Dit si l'agent a été arrêté par ce qui ne dit rien du travail ; si oui, le retire du
        compte des agents lancés, et l'agent repartira au même niveau.

        Refusé pour limite ou surcharge : les lancements visés sont suspendus (`Places.refus`,
        `Places.surcharge`, deux minutes pour tous). Sans connexion à Claude (`nature`
        « connexion ») : tous les lancements sont suspendus cinq minutes (`_sans_connexion`). En
        panne (`nature` « panne ») : la tâche seule patiente avant de rendre la main
        (`_apres_une_panne`), tant qu'il reste des pauses. Rien d'autre n'est compté : ni
        tentative, ni refus, ni montée, ni blocage. Le fil le dit une fois par suspension, et
        l'ouvrier resté ouvert est fermé (`_liberer`). Seul un résultat qui sera jugé (rendu
        False, hors panne) met fin à la série de pannes de la tâche (`Tache.pannes`) : une
        suspension ne la coupe pas, pour que la patience reste bornée. Seule `nature` est lue,
        jamais le texte de l'erreur.
        """
        nature = getattr(resultat, "nature", "") or ""
        if not resultat.ok and nature == NATURE_PANNE:
            return self._apres_une_panne(tache, resultat)
        if not resultat.ok and nature == NATURE_CONNEXION:
            return self._sans_connexion(tache)
        if resultat.erreur not in (LIMITE_ATTEINTE, SURCHARGE):
            self._fin_des_pannes(tache, resultat)
            return False
        heure = self.heure()
        with self.verrou:
            self.chantier.agents_lances -= 1
            if resultat.erreur == SURCHARGE:
                suspension = self.places.surcharge(tache.id, heure)
            else:
                limite, fin = resultat.type_limite, resultat.fin_limite
                suspension = self.places.refus(tache.id, limite, fin, heure)
            self._reveiller()
        self._liberer(tache)
        if suspension["nouvelle"]:
            phrase = phrase_de_suspension(suspension["portee"], suspension["reprise"], heure)
            self._noter(
                f"{phrase} Rien n'est compté contre cette tâche : elle repartira seule, au même "
                "niveau.",
                tache,
            )
        return True

    def _fin_des_pannes(self, tache: Tache, resultat) -> None:
        """L'agent a rendu un travail qui sera jugé (réussite, ou échec qui n'est ni une panne
        ni une suspension) : la série de pannes de la tâche est finie. Seule une vraie réussite
        dit que la connexion à Claude marche : sa perte suivante sera de nouveau dite au fil
        (`Places.connexion_retablie`)."""
        with self.verrou:
            tache.pannes = 0
            if resultat.ok:
                self.places.connexion_retablie()

    def _apres_une_panne(self, tache: Tache, resultat) -> bool:
        """L'agent (ouvrier, reprise ou vérificateur) est tombé en panne : la tâche patiente,
        puis rend vrai pour que le même agent reparte, au même niveau et au même numéro.

        Ni tentative, ni agent, ni refus n'est compté ; l'historique reçoit une entrée
        `ATTENTE_PANNE`, `Tache.pannes` augmente, et la place et le jeton sont rendus pendant la
        pause (`Places.pause`) : les autres tâches avancent. La pause suit `pauses_du_profil`.
        Rend False, sans rien changer d'autre que le compte, quand les pauses sont épuisées : la
        règle des erreurs d'agent s'applique. Rend False aussi, sans rien compter, si l'arrêt de
        la tâche est déjà demandé : il l'emporte.
        """
        heure = self.heure()
        with self.verrou:
            if tache.id in self._arretees:
                return False
            pauses = pauses_du_profil(self.profil)
            rang, tache.pannes = tache.pannes, tache.pannes + 1
            if rang >= len(pauses):
                return False
            pause = pauses[rang]
            self.chantier.agents_lances -= 1
            verificateur = tache.etat == "en_verification"
            qui = "Le vérificateur" if verificateur else "L'ouvrier"
            detail = f"{qui} s'est arrêté sur une panne : {str(resultat.erreur).rstrip(' .')}."
            self._tracer(tache, ATTENTE_PANNE, detail)
            self.places.pause(tache.id, heure + pause, heure)
            self._reveiller()
        self._liberer(tache)
        quand = _quand_repart(pause, heure + pause, heure)
        suite = (
            f"seul le vérificateur repart {quand}, et le travail de l'ouvrier reste tel quel"
            if verificateur
            else f"nouvel essai {quand}, au même niveau, sans compter cette tentative"
        )
        self._noter(f"{detail} C'est une panne, pas un refus du travail : {suite}.", tache)
        self._patienter(tache)
        return True

    def _patienter(self, tache: Tache) -> None:
        """Attend la fin de la pause de la tâche après une panne (`Places.en_pause`), ou son arrêt.

        Pendant la pause, elle ne tient ni place ni jeton, et ne retient pas les tâches neuves ;
        sa phase dit qu'elle patiente et jusqu'à quelle heure. Une suspension qui tombe pendant
        ce temps s'ajoute : l'agent attend encore sa fin avant de repartir (`_prendre_place`,
        `_attendre_jeton`).
        """

        def phrase_d_attente(heure: float) -> str:
            fin = self.places.en_pause(tache.id, heure)
            return PHASES["panne"].format(heure_dite(heure if fin is None else fin, heure))

        self._attendre(
            tache, lambda heure: self.places.en_pause(tache.id, heure) is None, phrase_d_attente
        )

    def _sans_connexion(self, tache: Tache) -> bool:
        """La connexion à Claude est perdue : tous les lancements sont suspendus cinq minutes
        (`Places.connexion`), puis réessayés ; rien n'est compté contre la tâche. Le fil dit une
        seule fois, pour toutes les tâches et tous les essais, la perte et le geste qui la
        répare (`CONNEXION_PERDUE`). Rend True."""
        heure = self.heure()
        with self.verrou:
            self.chantier.agents_lances -= 1
            suspension = self.places.connexion(tache.id, heure)
            self._reveiller()
        self._liberer(tache)
        if suspension["premiere"]:
            self._noter(CONNEXION_PERDUE)
        return True

    def _liberer(self, tache: Tache) -> None:
        """Hors du verrou, à chaque suspension (panne, connexion, limite, surcharge) : demande à
        l'agent de fermer l'ouvrier resté ouvert pour la tâche (`agent.liberer`). Un agent qui
        n'a pas cette méthode, ou qui lève, ne change rien."""
        liberer = getattr(self.agent, "liberer", None)
        if callable(liberer):
            with suppress(Exception):
                liberer(tache.id)

    def _conclure(self) -> None:
        taches = self.chantier.taches
        with self.verrou:
            fini = all(t.etat in ("verifie", "abandonnee") for t in taches)
            self.chantier.termine = fini and not self._principale_rouge
        verifiees = sum(t.etat == "verifie" for t in taches)
        if self.chantier.termine:
            self._noter(f"Chantier terminé : {verifiees} tâches vérifiées sur {len(taches)}.")
        else:
            self._noter(f"Je m'arrête ici : {verifiees} tâches vérifiées sur {len(taches)}.")

    # --- une tâche, de l'ouvrier au vérificateur -----------------------------------

    def _traiter(self, tache: Tache) -> None:
        try:
            self._boucle(tache)
        except Exception as erreur:  # une panne ne fait tomber ni le moteur ni les autres tâches
            self._panne(tache, erreur)
        finally:  # rien de ce qui précède ne pèse sur un lancement suivant
            with self.verrou:
                self._arretees.discard(tache.id)
                self._enregistrement.discard(tache.id)
                self.phases.pop(tache.id, None)
                for mesures in (self._mesure, self._durees, self._attentes):
                    mesures.pop(tache.id, None)
                self._en_vol.discard(tache.id)
                self.places.finir(tache.id, self.heure())
                self._reveiller()  # sa place et son jeton vont aussitôt à qui les attend
            if self._garde():  # hors du verrou : l'ouvrier gardé ouvert pour la tâche est fermé
                self._liberer(tache)

    def _boucle(self, tache: Tache) -> None:
        """Mène la tâche de départ neuf en départ neuf, jusqu'à ce qu'elle soit vérifiée ou rendue.

        Le travail refusé est gardé dans sa copie (`tache.copie`) : le départ suivant, tout de
        suite ou après la réponse de la personne, le reprend sur place (`_departs`). Une panne de
        l'Atelier pendant la tâche laisse la copie dans un état inconnu : elle est jetée, puis
        la panne suit son chemin (`_traiter`, `_panne`).
        """
        try:
            self._departs(tache)
        except Exception:  # la panne remonte telle quelle ; la copie ne lui survit pas
            with suppress(Exception):
                self._jeter_copie_gardee(tache)
            raise

    def _departs(self, tache: Tache) -> None:
        """La boucle des départs d'une tâche.

        Chaque départ a sa reprise à chaud. Le premier départ a reçu sa place en partant
        (`_lancer_pretes`), les suivants l'attendent (`_prendre_place`). Un ouvrier refusé pour
        limite ou surcharge ne compte pas : le même départ recommence à la fin de la suspension,
        dans la copie gardée. Après un refus, la copie est gardée ou jetée (`_copie_apres`) avant
        la décision de la suite, pour que la question posée à la personne dise si le travail
        est gardé. Arrêtée pendant sa vérification par un arrêt de l'Atelier, la tâche est
        seulement rejugée sur sa copie, sans ouvrier (`_rejuger`).
        """
        remarques = self._remarques_de_depart(tache)
        while True:
            if self._arretee(tache):  # arrêt demandé avant le départ de l'ouvrier
                return self._arret_avant_depart(tache)
            rejuge = self._rejuger(tache)
            if rejuge is None:
                if self._budget_atteint():  # plus aucun ouvrier ne part au-delà du budget
                    return self._rendre_pour_budget(tache)
                self._prendre_agent()
            dossier, resultat = rejuge or self._lancer_ouvrier(tache, remarques)
            if resultat is None:  # arrêt demandé pendant la préparation : l'ouvrier n'est pas parti
                self._jeter_copie(tache, dossier)
                return self._arret_avant_depart(tache)
            if self._nature(resultat) == NATURE_BUDGET:  # coupé par son plafond : rien de compté
                with self.verrou:
                    tache.tentatives -= 1
                self._copie_apres(tache, dossier, resultat, None)
                return self._rendre_pour_budget(tache)
            if self._suspendre(tache, resultat):  # la tentative ne compte pas non plus
                with self.verrou:
                    tache.tentatives -= 1
                self._copie_apres(tache, dossier, resultat, None)
            else:
                jugement = self._jugement_du_depart(tache, dossier, resultat, rejuge is not None)
                if jugement.motif is None:
                    return self._verifiee(tache, jugement)
                self._copie_apres(tache, dossier, resultat, jugement)
                remarques = jugement.pour_la_suite()
                if not self._suite(tache, jugement):
                    return None
            self._prendre_place(tache)

    def _jugement_du_depart(self, tache: Tache, dossier, resultat, rejuge: bool) -> Jugement:
        """Juge la passe de l'ouvrier, puis ses reprises à chaud. Une copie rejugée après un
        arrêt de l'Atelier n'a plus d'ouvrier dans une session : son refus ne se reprend pas
        à chaud, le départ suivant reprend la copie."""
        jugement = self._passe(tache, dossier, resultat)
        if rejuge:
            return replace(jugement, reprenable=False)
        return self._reprises(tache, dossier, resultat.session, jugement)

    # --- la copie gardée : le travail refusé reste, le tour suivant le reprend -----------------

    def _place_de_la_copie(self, tache: Tache):
        """Le chemin que les contrôles donnent à la copie de la tâche, ou None s'ils n'en disent
        rien (doubles sans `place_de_la_copie`, contrôles sans copie)."""
        place = getattr(self.controles, "place_de_la_copie", None)
        return place(tache) if place is not None else None

    def _copie_a_soi(self, tache: Tache, chemin) -> bool:
        """Dit si la copie nommée est celle de cette tâche : le chemin que l'Atelier lui donne.
        Une tâche ne reprend ni ne jette la copie d'une autre, ni un dossier venu d'ailleurs.
        Sans place connue des contrôles, toute copie nommée passe ce contrôle."""
        try:
            place = self._place_de_la_copie(tache)
            return place is None or Path(chemin).resolve() == Path(place).resolve()
        except Exception:  # un chemin impossible n'est la copie de personne
            return False

    def _copie_utilisable(self, tache: Tache, chemin) -> bool:
        """Dit si la copie nommée est celle de la tâche et sert encore (`copie_existante` des
        contrôles, un dossier présent à défaut) ; une erreur vaut une copie absente."""
        if not chemin or not self._copie_a_soi(tache, chemin):
            return False
        existante = getattr(self.controles, "copie_existante", None)
        try:
            return bool(existante(Path(chemin))) if existante else Path(chemin).is_dir()
        except Exception:  # une copie illisible ne se reprend pas : une neuve la remplace
            return False

    def _copie_a_reprendre(self, tache: Tache) -> Path | None:
        """La copie gardée que reprend le départ qui commence, ou None : il en prépare une neuve.

        Une copie nommée qui n'existe plus (effacée à la main, disque nettoyé) est oubliée, et le
        fil le dit en une phrase. Un chemin qui n'est pas celui de la copie de cette tâche (un état
        écrit ailleurs) est oublié sans rien y toucher, et le fil le dit aussi. Une copie qui porte
        des fichiers hors périmètre (laissée par un arrêt de l'Atelier en plein travail) est
        jetée : un débord ne passe jamais au tour suivant.
        """
        with self.verrou:
            chemin = tache.copie
        if not chemin:
            return None
        if not self._copie_a_soi(tache, chemin):
            with self.verrou:
                tache.copie = ""
            self._noter(
                f"La copie nommée pour cette tâche ({chemin}) n'est pas la sienne : je n'y touche "
                "pas, et l'ouvrier repart d'une copie neuve.",
                tache,
            )
            return None
        if self._copie_utilisable(tache, chemin):
            jetee = self._jetee_si_elle_deborde(tache, Path(chemin), Resultat(ok=True))
            return None if jetee else Path(chemin)
        with self.verrou:
            tache.copie = ""
        self._noter(
            f"La copie gardée pour cette tâche n'existe plus ({chemin}) : l'ouvrier repart d'une "
            "copie neuve.",
            tache,
        )
        return None

    def _retenir_copie(self, tache: Tache, dossier) -> None:
        """Écrit le chemin de la copie dans l'état, et le fait sauver avant le départ de l'ouvrier :
        une coupure juste après ce départ retrouve ce travail."""
        valeur = str(dossier) if dossier is not None else ""
        with self.verrou:
            change, tache.copie = tache.copie != valeur, valeur
        if change or dossier is not None:
            self.sur_changement()

    def _jeter_copie(self, tache: Tache, dossier) -> None:
        """Jette la copie de la passe (`annuler`), et l'oublie : le départ suivant repart propre.

        Sans copie de travail (contrôles simulés), `annuler` est appelé comme avant, sur None.
        """
        with self.verrou:
            tache.copie = ""
        self.controles.annuler(tache, dossier)

    def _jeter_copie_gardee(self, tache: Tache) -> None:
        """Jette la copie que nomme `tache.copie`, s'il y en a une, et vide le champ.

        Seule la copie de cette tâche est jetée (`_copie_a_soi`) : un autre chemin est seulement
        oublié. Une copie abîmée (que git ne reconnaît plus) dont le dossier est encore là, à la
        place que les contrôles donnent à la tâche, est jetée quand même ; une copie qui n'existe
        plus est seulement oubliée.
        """
        with self.verrou:
            chemin, tache.copie = tache.copie, ""
        if not chemin or not self._copie_a_soi(tache, chemin):
            return
        abimee = self._place_de_la_copie(tache) is not None and self._dossier_present(chemin)
        if abimee or self._copie_utilisable(tache, chemin):
            self.controles.annuler(tache, Path(chemin))

    @staticmethod
    def _dossier_present(chemin) -> bool:
        """Dit si le dossier nommé est sur le disque ; un chemin impossible ne l'est pas."""
        try:
            return Path(chemin).is_dir()
        except (OSError, ValueError):
            return False

    def _copie_apres(self, tache: Tache, dossier, resultat, jugement: Jugement | None) -> None:
        """Après un refus (`jugement`) ou une suspension (None) : garde la copie ou la jette.

        Jetée pour un arrêt par la personne, un débord de périmètre ou un refus d'enregistrement
        (`COPIE_JETEE`) : elle porte ce qu'il ne faut pas garder. Gardée sinon (contrôles,
        verdict, erreur d'agent, suspension), sauf si elle porte des fichiers hors périmètre :
        après une erreur d'agent ou une suspension, le périmètre n'a pas été contrôlé.
        """
        jetee = jugement is not None and (
            jugement.motif == ARRETEE or jugement.origine in COPIE_JETEE
        )
        if dossier is None or jetee:
            return self._jeter_copie(tache, dossier)
        if jugement is None or jugement.origine == "agent":
            self._jetee_si_elle_deborde(tache, dossier, resultat)
        return None  # contrôles ou verdict : le périmètre vient de passer sur cette copie

    def _jetee_si_elle_deborde(self, tache: Tache, dossier, resultat) -> bool:
        """Jette la copie si elle porte des fichiers hors périmètre, et le dit au fil ; rend
        True si elle a été jetée. Le périmètre est lu sur toute la copie (`fichiers_modifies`)."""
        dehors = hors_perimetre(
            self.controles.fichiers_modifies(tache, dossier, resultat), tache.perimetre
        )
        if not dehors:
            return False
        self._noter(
            f"La copie porte des fichiers hors périmètre ({', '.join(dehors)}) : je la jette, le "
            "départ suivant repart d'une copie propre.",
            tache,
        )
        self._jeter_copie(tache, dossier)
        return True

    def _remarques_de_depart(self, tache: Tache) -> str:
        """Ce que reçoit le premier ouvrier d'un lancement quand une copie gardée l'attend : le
        dernier refus, comme `Jugement.pour_la_suite` (le verdict entier, sinon le détail)."""
        with self.verrou:
            if not tache.copie:
                return ""
            refus_ = [e for e in tache.historique if e.get("issue") not in HORS_REFUS]
        if not refus_:
            return ""
        dernier, verdict = refus_[-1], str(refus_[-1].get("verdict") or "")
        if dernier.get("origine") == "verdict" and verdict.strip():
            return verdict
        return str(dernier.get("detail") or "")

    def _rejuger(self, tache: Tache):
        """Après un arrêt de l'Atelier pendant la vérification, rend (copie, résultat) pour
        refaire seulement le jugement, sans ouvrier ; sinon None.

        Il faut que la dernière entrée d'historique soit `interrompue` avec `pendant:
        "verification"`, et que la copie gardée existe encore : sinon un ouvrier part, dans une
        copie neuve si elle a disparu (`_copie_a_reprendre`).
        """
        with self.verrou:
            dernier = tache.historique[-1] if tache.historique else {}
            chemin = tache.copie
        if dernier.get("issue") != INTERROMPUE or dernier.get("pendant") != "verification":
            return None
        if not self._copie_utilisable(tache, chemin):
            return None
        with self.verrou:
            tache.etat = "en_cours"
        self._noter(
            "L'Atelier s'était arrêté pendant la vérification : le travail de l'ouvrier est resté "
            "dans sa copie. Aucun ouvrier ne repart, je refais seulement le contrôle du périmètre, "
            "les contrôles automatiques et la vérification.",
            tache,
        )
        return Path(chemin), Resultat(ok=True)

    def _verifiee(self, tache: Tache, jugement: Jugement) -> None:
        """La tâche est vérifiée ; un empêchement signalé en chemin, ou un outil refusé à
        l'ouvrier, est seulement noté au fil. Son travail est entré : sa copie est oubliée, et
        retirée si l'enregistrement l'a laissée."""
        with self.verrou:
            tache.etat = "verifie"
        self._jeter_copie_gardee(tache)
        self._noter("Vérifiée et enregistrée.", tache)
        if jugement.signales:
            liste = " ; ".join(f"« {_court(e, DETAIL_CITE)} »" for e in jugement.empechements)
            self._noter(
                f"Un agent a signalé un empêchement pendant cette tâche : {liste}. Le livrable a "
                "quand même été accepté et enregistré. Si cette commande doit servir aux agents, "
                "tu peux la leur permettre dans les outils du projet.",
                tache,
            )
        elif jugement.refuses_seuls:
            self._noter(_note_d_outils_refuses(jugement.refuses_seuls), tache)

    def _suite(self, tache: Tache, jugement: Jugement) -> bool:
        """Décide de la suite d'un départ refusé ; rend False si la tâche s'arrête là.

        Une tâche bloquée revient à la personne ; une erreur d'agent ne fait jamais monter d'un
        cran ; les autres refus suivent l'escalade (`_apres_echec`).
        """
        if jugement.blocage:
            self._bloquer(tache, jugement)
            return False
        if jugement.origine == "agent":
            return self._apres_erreur_d_agent(tache, jugement)
        if self._montee() == "fond" and jugement.motif not in (ARRETEE, "consigne"):
            return self._suite_sur_le_fond(
                tache, jugement.motif, jugement.detail, jugement.fond_faux
            )
        repris = self._repris_hors_fusion(tache)
        return self._apres_echec(tache, jugement.motif, jugement.detail, repris)

    def _passe(
        self, tache: Tache, dossier, resultat, precedent: Jugement | None = None
    ) -> Jugement:
        """Juge une passe de l'ouvrier, fait entrer son travail s'il est accepté, et la trace.

        `precedent` est le refus qui a conduit à une reprise à chaud : la passe jugée est alors
        cette reprise, tracée au numéro de son départ avec `reprise: true`. Une passe refusée
        qui bloque la tâche (voir `_cause_de_blocage`) ne se reprend pas.
        """
        jugement = self._juger(tache, resultat, dossier, precedent)
        jugement = self._avec_empechements(jugement, resultat)
        if jugement.motif is None:
            jugement = self._enregistrer(tache, dossier, jugement)
        jugement = replace(jugement, reprise=precedent is not None)
        with self.verrou:
            self._tracer(
                tache,
                jugement.motif or "valide",
                jugement.detail,
                origine=jugement.origine,
                reprise=jugement.reprise,
                verdict=jugement.verdict,
            )
            cause = self._cause_de_blocage(tache, jugement)
        return replace(jugement, blocage=cause, reprenable=False) if cause else jugement

    @staticmethod
    def _avec_empechements(jugement: Jugement, resultat) -> Jugement:
        """Ajoute au jugement ce que l'ouvrier signale : ses lignes « EMPÊCHÉ : » et les outils
        que le pont lui a refusés, devant ce que le vérificateur a signalé.

        Les outils refusés qu'aucun agent ne signale aussi, mot pour mot, vont de plus dans
        `refuses_seuls` : seuls, ils ne bloquent pas toujours la tâche (`_empeche`).
        """
        lignes = refus.empechements(getattr(resultat, "texte", ""), None, None)
        outils = refus.empechements("", getattr(resultat, "refuses", None), None)
        tous = tuple(dict.fromkeys([*lignes, *outils, *jugement.empechements]))
        seuls = [o for o in outils if o not in lignes and o not in jugement.empechements]
        return replace(jugement, empechements=tous, refuses_seuls=tuple(seuls))

    def _enregistrer(self, tache: Tache, dossier, jugement: Jugement) -> Jugement:
        """Fait entrer le livrable accepté dans la branche principale ; rend le jugement final.

        Un refus d'enregistrement venu d'un conflit de fusion se reprend à chaud, une fois par
        départ (`_conflit_a_reprendre`) ; les autres ne se reprennent pas.
        """
        with self.verrou:  # dernier mot : un arrêt demandé jusqu'ici l'emporte
            if self._arretee(tache):
                return ARRET
            self._enregistrement.add(tache.id)
        self._phase(tache, PHASES["enregistrement"])
        probleme = self.controles.enregistrer(tache, dossier)
        if not probleme:
            return jugement
        with self.verrou:  # conflit, ou contrôles rouges une fois mêlé à la branche principale
            self._enregistrement.discard(tache.id)
        refus = replace(jugement, motif="ne_sait_pas", detail=probleme, origine="integration")
        return self._conflit_a_reprendre(tache, dossier, refus)

    def _conflit_a_reprendre(self, tache: Tache, dossier, refus: Jugement) -> Jugement:
        """Le refus d'enregistrement, rendu reprenable s'il vient d'un conflit de fusion sur des
        fichiers déclarés partagés en « git ».

        Les contrôles laissent alors ces fichiers, à marqueurs, dans la copie de l'ouvrier
        (`poser_conflits`), qui les reçoit à sa reprise. Une seule reprise de fusion par départ,
        et l'historique suffit à le savoir : un départ ne continue après un refus d'enregistrement
        que si ce refus a été repris ainsi. Un refus d'enregistrement déjà tracé dans ce départ
        veut donc dire que sa reprise de fusion a eu lieu.

        Dans tous les autres cas, le refus reste tel quel (le chemin d'avant) :
        sans `poser_conflits` (contrôles simulés), sans conflit, un fichier en conflit qui n'est
        pas déclaré en « git », ou une seconde fois. La copie est alors jetée et le départ
        suivant repart de la branche principale.
        """
        poser = getattr(self.controles, "poser_conflits", None)
        motifs = [m for m, fusion in fichiers_partages(self.profil).items() if fusion == "git"]
        with self.verrou:
            deja = any(e.get("origine") == "integration" for e in self._passes_du_depart(tache))
        if poser is None or not motifs or deja:
            return refus
        conflits = poser(tache, dossier)
        if not conflits or not all(motif_partage(chemin, motifs) for chemin in conflits):
            return refus
        detail = (
            "Conflit avec la branche principale, où d'autres tâches sont entrées entre-temps, "
            f"dans : {', '.join(conflits)}."
        )
        return replace(refus, detail=detail, complet=conflits_en_clair(conflits), reprenable=True)

    def _passes_du_depart(self, tache: Tache) -> list[dict]:
        """Sous le verrou : les entrées d'historique du départ en cours, reprises comprises. Une
        passe coupée par une panne d'agent (`ATTENTE_PANNE`) est neutre : elle n'y entre pas."""
        return [
            e
            for e in tache.historique
            if e.get("tentative") == tache.tentatives and e.get("issue") != ATTENTE_PANNE
        ]

    def _repris_hors_fusion(self, tache: Tache) -> bool:
        """Dit si ce départ a eu une reprise après un refus autre qu'un conflit de fusion : elle
        seule tient lieu de seconde chance pour l'escalade (`_apres_echec`).

        Seules comptent les passes tracées comme reprises (`reprise: true`), chacune jugée par
        l'entrée qui la précède : une reprise qui suit un refus d'enregistrement est une reprise
        de fusion. Une autre entrée du même numéro, comme un arrêt avant le départ (tracé sous
        le numéro du départ suivant), n'est pas une reprise.
        """
        with self.verrou:
            passes = self._passes_du_depart(tache)
        return any(
            apres.get("reprise") and avant.get("origine") != "integration"
            for avant, apres in zip(passes, passes[1:], strict=False)
        )

    # --- la reprise à chaud ---------------------------------------------------------

    def _reprises(self, tache: Tache, dossier, session: str, jugement: Jugement) -> Jugement:
        """Redonne la main à l'ouvrier refusé, dans ce départ, sans compter la reprise d'un
        conflit de fusion, bornée à part (`_conflit_a_reprendre`).

        Sans ouvrier gardé ouvert : `REPRISES_PAR_DEPART` fois au plus. Avec (`_garde`) : un
        contrôle rouge lui revient jusqu'à `retours_controles` fois, tout autre refus qui se
        reprend `complements` fois, et le retour s'arrête dès que le même échec revient.

        Rend le jugement de la dernière passe : celui de la reprise, ou le refus d'origine si
        aucune reprise n'a pu partir (refus qui ne se reprend pas, session perdue, copie restée
        telle quelle).
        """
        faits = {"controles": 0, "autres": 0, "tous": 0}
        while jugement.reprenable:
            if jugement.origine != "integration":
                if self._montee() == "fond" and jugement.fond_faux:
                    break  # un fond jugé faux ne revient jamais au même ouvrier : il fait monter
                if not self._retour_permis(jugement, faits):
                    break
            suivant = self._reprise(tache, dossier, session, jugement)
            if self._meme_echec(jugement, suivant):
                return replace(suivant, reprenable=False)
            jugement = suivant
        return jugement

    def _garde(self) -> bool:
        """Dit si le moteur garde les ouvriers ouverts : le profil le permet (`ouvrier_ouvert`,
        vrai sans réglage) et l'agent sait le faire (`garde_les_ouvriers`)."""
        sait = bool(getattr(self.agent, "garde_les_ouvriers", False))
        return sait and lire_garde(self.profil)[0]

    def _retour_permis(self, jugement: Jugement, faits: dict) -> bool:
        """Compte ce retour et dit s'il peut partir (voir `_reprises`). Aucun au-delà du budget."""
        if self._budget_atteint():
            return False
        if not self._garde():
            faits["tous"] += 1
            return faits["tous"] <= REPRISES_PAR_DEPART
        cle = "controles" if jugement.origine == "controles" else "autres"
        defaut = RETOURS_CONTROLES if cle == "controles" else COMPLEMENTS
        reglage = self.profil.get("retours_controles" if cle == "controles" else "complements")
        permis = reglage if isinstance(reglage, int) and not isinstance(reglage, bool) else defaut
        faits[cle] += 1
        return faits[cle] <= max(0, permis)

    def _meme_echec(self, avant: Jugement, apres: Jugement) -> bool:
        """Dit si le retour a redonné le même échec : inutile de le redonner une fois de plus.
        Ne vaut qu'avec un ouvrier gardé ouvert, où plusieurs retours se suivent."""
        if not self._garde() or apres.motif is None or not apres.reprenable:
            return False
        if avant.origine != apres.origine or apres.origine == "integration":
            return False
        return refus.meme_forme(
            {"issue": avant.motif, "detail": avant.detail, "origine": avant.origine},
            {"issue": apres.motif, "detail": apres.detail, "origine": apres.origine},
        )

    def _reprise(self, tache: Tache, dossier, session: str, refus: Jugement) -> Jugement:
        """Une reprise à chaud : l'ouvrier refusé corrige dans sa session et sa copie, puis sa
        passe est jugée comme les autres (périmètre, contrôles, vérificateur)."""
        self._noter(
            f"Refusée. {refus.detail} Je redonne la main au même ouvrier, dans sa copie et sa "
            "session, pour qu'il corrige.",
            tache,
        )
        # Avec un ouvrier gardé ouvert seulement : sans lui, toute reprise est jugée, comme avant.
        avant = self._empreinte(dossier) if self._garde() else ""
        resultat = self._malgre_les_limites(
            tache, self._prendre_place, lambda: self._lancer_reprise(tache, dossier, session, refus)
        )
        if resultat is not None and resultat.ok and self._inchangee(dossier, avant):
            self._noter(
                "L'ouvrier a rendu la main sans rien changer dans sa copie : le refus vaut tel "
                "quel, et je ne rejoue ni les contrôles ni le vérificateur. Sa réponse : « "
                f"{str(resultat.texte or '').strip()[:REPONSE_AU_FIL]} »",
                tache,
            )
            return replace(refus, reprenable=False)
        if resultat is None:  # arrêt demandé entre le refus et la reprise : elle ne part pas
            with self.verrou:
                self._tracer(tache, ARRETEE, DETAIL_ARRET, reprise=True)
            return replace(ARRET, reprise=True)
        if resultat.erreur == REPRISE_IMPOSSIBLE:  # ni entrée d'historique ni tentative de plus
            self._noter(
                "La session de l'ouvrier ne peut pas être reprise : je jette sa copie, et la "
                "suite est celle d'un refus sans reprise.",
                tache,
            )
            return replace(refus, reprenable=False)
        return self._passe(tache, dossier, resultat, precedent=refus)

    def _inchangee(self, dossier, avant: str) -> bool:
        """Dit si la copie est restée telle quelle depuis l'empreinte `avant`. Une empreinte
        inconnue (texte vide), avant ou après, ne prouve rien : la passe est alors jugée."""
        if not avant:
            return False
        apres = self._empreinte(dossier)
        return bool(apres) and apres == avant

    def _lancer_reprise(self, tache: Tache, dossier, session: str, jugement: Jugement):
        """Relance l'ouvrier dans sa session, sur sa copie, avec le refus ; rend son résultat.

        None si l'arrêt a été demandé avant : l'agent n'est pas lancé. La reprise compte parmi
        les agents lancés, jamais parmi les tentatives ; une session qu'on ne peut pas reprendre
        ne compte pas non plus parmi les agents, et sa durée n'est pas gardée.
        """
        with self.verrou:
            tache.etat = "en_cours"
        if self._arretee(tache):  # relu juste avant l'appel : rien de lent ne s'intercale
            return None
        self._prendre_agent()
        self._phase(tache, PHASES["reprise"].format(tache.tentatives))
        resultat = self.agent.executer(
            consigne_reprise(
                tache, jugement.origine, jugement.complet, self.profil, jugement.refuses_seuls
            ),
            tache.modele,
            tache.effort,
            dossier,
            contexte={"role": "ouvrier", "tache": tache.id, "tentative": tache.tentatives},
            reprendre=session,
            **self._garder_ouvert(),
            **self._plafond(),
        )
        self._compter(tache, resultat)
        if resultat.erreur == REPRISE_IMPOSSIBLE:
            with self.verrou:
                self.chantier.agents_lances -= 1
                self._mesure.pop(tache.id, None)
        return resultat

    def _lancer_ouvrier(self, tache: Tache, remarques: str):
        """Prépare le travail et lance l'ouvrier ; rend (dossier, résultat).

        Une copie gardée d'un passage précédent est reprise telle quelle, sans `preparer`, et la
        consigne le dit à l'ouvrier (`sur_place`) ; sinon une copie neuve est préparée. Son chemin
        est écrit dans l'état et sauvé avant le départ (`_retenir_copie`).

        Le résultat est None si l'arrêt a été demandé pendant la préparation : l'agent n'est
        alors pas lancé, et ni le compte des agents ni celui des tentatives ne le gardent.
        """
        gardee = self._copie_a_reprendre(tache)
        with self.verrou:
            tache.tentatives += 1
            tache.etat = "en_cours"
        self._noter(
            f"Ouvrier lancé ({dosage.libelle(tache.modele, tache.effort)}), "
            f"tentative {tache.tentatives}.",
            tache,
        )
        if gardee is None:
            self._phase(tache, PHASES["preparation"])
            dossier = self.controles.preparer(tache)
        else:
            dossier = gardee
            self._noter(
                "Le travail d'un passage précédent est resté dans sa copie : l'ouvrier le reprend "
                "et ne corrige que ce qui a été relevé, sans tout refaire.",
                tache,
            )
        self._retenir_copie(tache, dossier)
        if self._arretee(tache):  # relu juste avant l'appel : rien de lent ne s'intercale
            with self.verrou:
                tache.tentatives -= 1
                self.chantier.agents_lances -= 1
            return dossier, None
        self._phase(tache, PHASES["ouvrier"].format(tache.tentatives))
        resultat = self.agent.executer(
            consigne_ouvrier(
                tache, self.chantier.contrat, self.profil, remarques, sur_place=gardee is not None
            ),
            tache.modele,
            tache.effort,
            dossier,
            contexte={"role": "ouvrier", "tache": tache.id, "tentative": tache.tentatives},
            **self._garder_ouvert(),
            **self._plafond(),
        )
        self._compter(tache, resultat)
        return dossier, resultat

    def _garder_ouvert(self) -> dict:
        """Ce qu'un appel d'ouvrier ajoute pour que l'agent le garde ouvert ; rien quand le
        moteur ne garde pas (`_garde`) : un agent qui ne connaît pas ce paramètre ne le reçoit
        jamais."""
        return {"garder_ouvert": True} if self._garde() else {}

    def _arret_avant_depart(self, tache: Tache) -> None:
        """Rend la tâche arrêtée avant qu'un ouvrier n'ait travaillé, en gardant la trace.

        Un arrêt voulu par la personne repart d'un état propre : la copie gardée d'un passage
        précédent, s'il y en a une, est jetée.
        """
        self._jeter_copie_gardee(tache)
        with self.verrou:
            self._tracer(tache, ARRETEE, DETAIL_ARRET, decalage=1)
        self._rendre(tache, MOTIF_ARRET)

    def _juger(
        self, tache: Tache, resultat, dossier, precedent: Jugement | None = None
    ) -> Jugement:
        """Juge une passe de l'ouvrier : périmètre, contrôles, puis vérificateur.

        Rend un `Jugement` sans motif si le livrable est accepté. `precedent` est le refus qui a
        conduit à une reprise : venu du vérificateur, il appelle une vérification restreinte.

        Une passe sans `precedent` ouvre un départ, dans une copie neuve : ce qu'un vérificateur
        avait relevé sur une autre copie ne vaut plus (`_retenir_releve`). Un débord l'efface
        aussi ; un refus des contrôles ou une erreur de l'ouvrier le laissent.
        """
        if self._arretee(tache, resultat):
            return ARRET
        if precedent is None:
            self._retenir_releve(tache)
        if not resultat.ok:
            detail = f"L'agent s'est arrêté sur une erreur : {resultat.erreur}"
            return Jugement("ne_sait_pas", detail, "agent", nature=self._nature(resultat))
        refus, sortie = self._controler(tache, dossier, resultat)
        if refus is not None:
            if refus.origine == "perimetre":
                self._retenir_releve(tache)
            return refus
        if self._arretee(tache):  # aucun agent n'est en marche : le vérificateur ne part pas
            return ARRET
        return self._verifier(tache, dossier, precedent, sortie)

    @staticmethod
    def _nature(resultat) -> str:
        """La nature de l'échec d'un agent (`Resultat.nature`), "" quand il n'en dit rien."""
        nature = getattr(resultat, "nature", "")
        return nature if isinstance(nature, str) else ""

    def _controler(self, tache: Tache, dossier, resultat) -> tuple[Jugement | None, str | None]:
        """Contrôle le périmètre puis lance les contrôles ; rend (le refus ou None, la sortie).

        Ces deux refus se reprennent à chaud : l'ouvrier a fini son tour et le message existe.
        La sortie est celle des contrôles que le moteur vient de jouer et qui passent, telle
        quelle, pour le vérificateur ; None quand le profil n'a aucune commande de contrôle (rien
        n'a été joué) ou que la passe est refusée.
        """
        self._phase(tache, PHASES["perimetre"])
        modifies = self.controles.fichiers_modifies(tache, dossier, resultat)
        dehors = hors_perimetre(modifies, tache.perimetre)
        if dehors:
            detail = "Fichiers modifiés hors périmètre : " + ", ".join(dehors) + "."
            return Jugement("deborde", detail, "perimetre", list(dehors), reprenable=True), None
        commandes = getattr(self.controles, "commandes", None) or []
        if commandes:
            self._phase(tache, PHASES["controles"] + " ; ".join(commandes))
        passe, sortie = self.controles.mecaniques(tache, dossier)
        if passe:
            return None, (str(sortie or "") if self._commandes_au_profil() else None)
        detail = "Les contrôles automatiques échouent :\n" + sortie[-1500:]
        fin = sortie[-SORTIE_REPRISE:]
        reste = (self._ce_qui_echoue(sortie),)
        return Jugement("ne_sait_pas", detail, "controles", fin, reprenable=True, reste=reste), None

    def _commandes_au_profil(self) -> bool:
        """Dit si le profil a au moins une commande de contrôle : sans elle, rien n'est joué."""
        commandes = self.profil.get("commandes")
        return isinstance(commandes, list) and any(
            isinstance(c, str) and c.strip() for c in commandes
        )

    @staticmethod
    def _ce_qui_echoue(sortie: str) -> str:
        """Ce qui a échoué, lu dans la sortie des contrôles : depuis la dernière commande lancée
        (« $ … » ; les contrôles s'arrêtent à la première qui échoue), ses `SORTIE_REPRISE`
        derniers caractères."""
        texte = str(sortie or "")
        echec = texte[texte.rfind("\n$ ") + 1 :].strip()[-SORTIE_REPRISE:]
        return echec or "Les contrôles automatiques échouent sans rien afficher."

    def _niveau(self, tache: Tache) -> str:
        """Le niveau de vérification de la tâche : `dosage.niveau_verification`, d'après son type
        et le profil seulement, jamais d'après une valeur posée par tâche dans le plan.

        Une tâche de réparation de la branche principale garde le plancher, quel que soit son
        type ; un type inconnu est vérifié complètement, quoi que dise le profil. « mecanique »
        devient « bornee » quand le profil n'a aucune commande de contrôle : il ne resterait
        plus aucun contrôle. Le fil le dit une fois ; il dit aussi, une fois pour chaque tâche
        concernée, qu'un type inconnu sera vérifié complètement.
        """
        if not self._type_connu(tache):
            ecrit = f"« {tache.type} »" if str(tache.type or "").strip() else "vide"
            self._dire_une_fois(TYPE_INCONNU.format(type=ecrit), tache, par_tache=True)
            return COMPLETE
        reparation = tache.id.startswith(PREFIXE_REPARATION)
        niveau = dosage.niveau_verification(tache.type, self.profil.get("verification"), reparation)
        if niveau == dosage.MECANIQUE and not self._commandes_au_profil():
            self._dire_une_fois(MECANIQUE_SANS_CONTROLE, tache)
            return BORNEE
        return niveau

    @staticmethod
    def _type_connu(tache: Tache) -> bool:
        """Dit si le type de la tâche est un type que le produit connaît (`TYPES_CONNUS`)."""
        return isinstance(tache.type, str) and tache.type in TYPES_CONNUS

    def _plancher(self, tache: Tache) -> bool:
        """Dit si la tâche ne descend jamais sous la vérification complète : un type du plancher
        (`dosage.PLANCHER_COMPLET`), une réparation, ou un type inconnu."""
        if not self._type_connu(tache) or tache.id.startswith(PREFIXE_REPARATION):
            return True
        return tache.type in dosage.PLANCHER_COMPLET

    def _dire_une_fois(self, texte: str, tache: Tache, par_tache: bool = False) -> None:
        """Note `texte` au fil, sauf s'il y est déjà : une seule fois par chantier, ou une fois
        pour chaque tâche avec `par_tache`.

        Sans sauvegarde à part : la note qui suit aussitôt (« Vérificateur lancé ») l'emporte."""
        with self.verrou:
            deja = any(
                e.get("texte") == texte and (not par_tache or e.get("tache") == tache.id)
                for e in self.chantier.evenements
            )
            if not deja:
                self.chantier.noter(texte, tache.id)

    def _conflit_resolu(self, tache: Tache, dossier=None) -> bool:
        """Dit si la copie porte la résolution d'un conflit de fusion : un refus
        d'enregistrement a été tracé dans le départ en cours (il ne continue après lui que si ce
        conflit a été rendu à l'ouvrier, `_conflit_a_reprendre`), ou les contrôles disent que
        cette copie a reçu un conflit à résoudre (`conflit_pose`). La seconde marque suit la
        copie : un travail refusé puis gardé d'un départ à l'autre la porte encore."""
        with self.verrou:
            if any(e.get("origine") == "integration" for e in self._passes_du_depart(tache)):
                return True
        lire = getattr(self.controles, "conflit_pose", None)
        if lire is None:
            return False
        try:
            return bool(lire(dossier))
        except Exception:  # dans le doute, vérification complète
            return True

    def _choisir_verification(
        self, tache: Tache, dossier, precedent: Jugement | None, sortie: str | None
    ) -> Verification | None:
        """Comment vérifier cette passe ; None pour la vérification mécanique seule, décidée en
        dernier, une fois écarté tout ce qui impose un vérificateur.

        Une copie qui porte la résolution d'un conflit de fusion est vérifiée complètement
        jusqu'à son entrée, retouches comprises, quel que soit le niveau. Une tâche qui porte un
        relevé (`Tache.releve`) reçoit une retouche, faite au niveau de l'ouvrier, et complète
        pour une tâche du plancher (`_plancher`). La reprise d'un refus du vérificateur sans
        relevé (le fond) est relue sur la correction, au niveau de la tâche (borné au moins).
        Sinon le niveau de la tâche décide (`_niveau`).
        """
        origine = precedent.origine if precedent is not None else ""
        conflit = origine == "integration" or self._conflit_resolu(tache, dossier)
        niveau = COMPLETE if conflit else self._niveau(tache)
        with self.verrou:
            releve = tache.releve
        if releve:
            juge = COMPLETE if conflit or self._plancher(tache) else BORNEE
            return self._dosee(tache, RETOUCHE, juge, sortie, dossier)
        if origine == "integration":
            return self._dosee(tache, CONFLIT, COMPLETE, sortie, dossier)
        if origine == "verdict":
            juge = BORNEE if niveau == dosage.MECANIQUE else niveau
            return self._dosee(tache, REVERIFICATION, juge, sortie, dossier)
        if niveau == dosage.MECANIQUE:
            return None
        return self._dosee(tache, niveau, niveau, sortie, dossier)

    def _dosee(
        self, tache: Tache, genre: str, niveau: str, sortie: str | None, dossier
    ) -> Verification:
        """La vérification de ce genre, dosée par `dosage.verificateur_selon_niveau` : un modèle
        au-dessus de l'ouvrier au niveau complet, le même au niveau borné. Elle porte l'état de
        la copie que le vérificateur va voir et, pour une retouche, les fichiers changés depuis
        celui qu'avait vu le vérificateur précédent."""
        modele, effort = dosage.verificateur_selon_niveau(tache.modele, tache.effort, niveau)
        vu = self._empreinte(dossier)
        fichiers = ()
        if genre == RETOUCHE:
            with self.verrou:
                depuis = tache.releve_sur
            fichiers = self._fichiers_changes(dossier, depuis, vu)
        return Verification(genre, modele, effort, sortie, fichiers, vu)

    def _verification_d_avant(self, tache: Tache, precedent: Jugement | None) -> Verification:
        """La vérification d'avant les niveaux, pour un appel qui n'en dit pas : complète, ou
        restreinte après une reprise, sans sortie des contrôles."""
        origine = precedent.origine if precedent is not None else ""
        genre = {"verdict": REVERIFICATION, "integration": CONFLIT}.get(origine, COMPLETE)
        modele, effort = dosage.verificateur(tache.modele, tache.effort)
        return Verification(genre, modele, effort)

    def _empreinte(self, dossier) -> str:
        """L'état de la copie (`controles.empreinte`, un texte qui change avec son contenu), ou ""
        quand les contrôles ne savent pas le donner ou échouent."""
        lire = getattr(self.controles, "empreinte", None)
        if lire is None:
            return ""
        try:
            vu = lire(dossier)
        except Exception:  # sans empreinte, la retouche ne nomme pas les fichiers changés
            return ""
        return vu if isinstance(vu, str) else ""

    def _fichiers_changes(self, dossier, depuis: str, vu: str) -> tuple[str, ...]:
        """Les fichiers changés entre deux états de la copie (`controles.differences`) ; vide
        quand on ne sait pas les dire (une empreinte manque, pas de `differences`, une erreur)."""
        differences = getattr(self.controles, "differences", None)
        if differences is None or not depuis or not vu:
            return ()
        try:
            changes = differences(dossier, depuis, vu)
        except Exception:  # sans la liste, le vérificateur juge la retouche par le verdict
            return ()
        return tuple(dict.fromkeys(str(f) for f in changes or () if str(f).strip()))

    def _retenir_releve(self, tache: Tache, jugement: Jugement | None = None, vu: str = "") -> None:
        """Écrit dans la tâche ce que le vérificateur a relevé (`Tache.releve`) et l'état de la
        copie qu'il a vue (`Tache.releve_sur`), ou les efface.

        Écrits pour un refus lisible du vérificateur, de motif « bacle » ou « local ». Effacés
        sans jugement (départ dans une copie neuve, débord), pour un accord, ou pour un refus du
        vérificateur d'un autre motif. Une erreur d'agent ne change rien ; un arrêt non plus, qui
        n'arrive jamais jusqu'ici (`_juger` et `_verifier` le rendent avant).
        """
        if jugement is not None and jugement.origine == "agent":
            return
        garder = (
            jugement is not None
            and jugement.origine == "verdict"
            and jugement.lisible
            and jugement.motif in MOTIFS_RELEVES
        )
        releve = self._releve_de(jugement) if garder else ""
        with self.verrou:
            tache.releve, tache.releve_sur = releve, vu if garder else ""

    @staticmethod
    def _releve_de(jugement: Jugement) -> str:
        """Ce qu'un refus a relevé, de quoi rédiger la retouche : son résumé et ses points."""
        resume = jugement.detail.strip() or (
            f"Le vérificateur a refusé ce travail (motif « {jugement.motif} ») sans en dire plus."
        )
        lignes = [resume]
        if jugement.reste:
            lignes += ["Points relevés :", *(f"- {point}" for point in jugement.reste)]
        if jugement.fichiers:
            lignes.append("Fichiers concernés : " + ", ".join(jugement.fichiers) + ".")
        return "\n".join(lignes)

    def _sans_verificateur(self, tache: Tache) -> Jugement:
        """La vérification mécanique seule : le contrôle du périmètre et les contrôles
        automatiques ont passé, ils décident seuls. Aucun vérificateur ne part ; l'historique
        dit que la tâche est entrée sans vérificateur. La tâche ne porte alors aucun relevé : un
        relevé impose une retouche (`_choisir_verification`), il n'y a donc rien à effacer."""
        with self.verrou:
            tache.verdict = ENTREE_SANS_VERIFICATEUR
        self._noter(
            "Vérification mécanique seule : le contrôle du périmètre et les contrôles "
            "automatiques ont passé, aucun vérificateur ne part pour cette tâche.",
            tache,
        )
        return Jugement(None, ENTREE_SANS_VERIFICATEUR)

    def _verifier(
        self, tache: Tache, dossier, precedent: Jugement | None, sortie: str | None = None
    ) -> Jugement:
        """Fait relire le livrable par un vérificateur neuf et lit son verdict.

        Le niveau de vérification décide du vérificateur (`_choisir_verification`) ; au niveau
        mécanique, aucun ne part. `sortie` : celle des contrôles que le moteur vient de jouer,
        None quand il n'a rien joué. Un vérificateur en erreur ou au verdict illisible est
        relancé une fois, neuf, sur la même copie de l'ouvrier, avant de valoir refus ; sauf
        s'il signale un empêchement, sur lequel un second buterait aussi.
        """
        choix = self._choisir_verification(tache, dossier, precedent, sortie)
        if choix is None:
            return self._sans_verificateur(tache)
        avis = self._avis(tache, dossier, precedent, choix)
        if avis is None or self._arretee(tache, avis):
            return ARRET
        if self._a_relancer(avis):
            raison = (
                f"s'est arrêté sur une erreur ({str(avis.erreur).rstrip(' .')})"
                if not avis.ok
                else "n'a pas rendu de verdict lisible"
            )
            self._noter(
                f"Le vérificateur {raison} : j'en relance un, une seule fois, sur la même copie.",
                tache,
            )
            avis = self._avis(tache, dossier, precedent, choix)
            if avis is None or self._arretee(tache, avis):
                return ARRET
        jugement = self._lire_avis(tache, avis, choix)
        self._retenir_releve(tache, jugement, choix.empreinte)
        return jugement

    def _avis(
        self, tache: Tache, dossier, precedent: Jugement | None, choix: Verification | None = None
    ):
        """Compte et lance un vérificateur dès qu'il a son jeton ; rend son avis, ou None (arrêt
        avant son départ). Refusé pour limite ou surcharge, il repart après la suspension.

        `choix` : la vérification décidée (`_choisir_verification`) ; le jeton attendu est celui
        de son modèle. Sans lui, la vérification d'avant les niveaux."""
        choix = choix or self._verification_d_avant(tache, precedent)

        def lancer():
            self._prendre_agent()
            return self._lancer_verificateur(tache, dossier, precedent, choix)

        def attendre(t: Tache) -> None:
            self._attendre_jeton(t, choix.modele)

        return self._malgre_les_limites(tache, attendre, lancer)

    @staticmethod
    def _empeches_du_verificateur(avis) -> tuple[str, ...]:
        """Ce que le vérificateur signale : ses lignes « EMPÊCHÉ : » et le champ `empeche` de son
        objet JSON, même s'il s'est arrêté sur une erreur ou que son verdict est illisible."""
        texte = avis.texte or ""
        return tuple(refus.empechements(texte, None, dernier_json(texte)))

    def _a_relancer(self, avis) -> bool:
        """Dit si l'avis vient d'un vérificateur en erreur ou illisible, sans empêchement."""
        lisible = avis.ok and "valide" in (dernier_json(avis.texte or "") or {})
        return not lisible and not self._empeches_du_verificateur(avis)

    def _lire_avis(self, tache: Tache, avis, choix: Verification | None = None) -> Jugement:
        """Le jugement que porte l'avis du vérificateur.

        Seul un verdict lisible qui recale pour « bâclé », « local » ou « ne sait pas » se reprend
        à chaud : un verdict illisible, ou une consigne mal posée, ne se reprend pas. Un
        vérificateur en erreur est une erreur d'agent (origine « agent ») : elle ne fera pas
        monter d'un cran. Le jugement porte aussi `lisible`, `reste`, `fichiers`, `fond_faux` et,
        pour la relecture d'une correction (`choix`), `meme_defaut`.
        """
        empeches = self._empeches_du_verificateur(avis)
        verdict = lire_verdict(avis.texte) if avis.ok else lire_verdict("")
        texte = (avis.texte or "")[-VERDICT_GARDE:] if avis.ok else ""
        with self.verrou:
            tache.verdict = verdict["resume"]
        if verdict["valide"]:
            resume = verdict["resume"]
            return Jugement(None, resume, verdict=texte, empechements=empeches, lisible=True)
        if not avis.ok:
            detail = f"Le vérificateur s'est arrêté sur une erreur : {avis.erreur}"
            nature = self._nature(avis)
            return Jugement("ne_sait_pas", detail, "agent", empechements=empeches, nature=nature)
        lisible = "valide" in (dernier_json(avis.texte or "") or {})
        motif, resume = verdict["motif"], verdict["resume"]
        reprenable = lisible and motif in (*MOTIFS_REPRIS, "local")
        correction = choix is not None and choix.genre in (RETOUCHE, REVERIFICATION)
        return Jugement(
            motif, resume, "verdict", texte, texte, reprenable, False, empeches,
            lisible=lisible,
            reste=tuple(verdict.get("reste", ())),
            fichiers=tuple(verdict.get("fichiers", ())),
            meme_defaut=correction and bool(verdict.get("meme_defaut", False)),
            fond_faux=self._fond_faux(lisible, motif),
        )  # fmt: skip

    @staticmethod
    def _fond_faux(lisible: bool, motif: str | None) -> bool:
        """Dit si le vérificateur juge le fond faux : un verdict lisible qui refuse pour « ne sait
        pas ». Jamais un verdict illisible, une erreur du vérificateur, ni un autre refus."""
        return lisible and motif == "ne_sait_pas"

    def _lancer_verificateur(
        self,
        tache: Tache,
        dossier,
        precedent: Jugement | None = None,
        choix: Verification | None = None,
    ):
        """Lance le vérificateur ; rend son avis, ou None si l'arrêt a été demandé avant son départ.

        Dans ce cas l'agent n'est pas lancé et ne compte pas parmi les agents lancés. Le dosage et
        la consigne viennent de la vérification décidée (`choix`, `_choisir_verification`) :
        complète, bornée, retouche, relecture d'une correction ou d'un conflit résolu. Sans elle,
        la vérification d'avant les niveaux.
        """
        choix = choix or self._verification_d_avant(tache, precedent)
        modele, effort = choix.modele, choix.effort
        objet = " sur la correction" if choix.genre in (RETOUCHE, REVERIFICATION) else ""
        self._noter(f"Vérificateur lancé{objet} ({dosage.libelle(modele, effort)}).", tache)
        if self._arretee(tache):  # relu juste avant l'appel : rien de lent ne s'intercale
            with self.verrou:
                self.chantier.agents_lances -= 1
            return None
        self._phase(tache, PHASES["verificateur"].format(dosage.libelle(modele, effort)))
        copie = self._copie_de_verification(tache, dossier)
        en_plus = {"copie_jetable": True} if copie else {}
        try:
            avis = self.agent.executer(
                self._consigne_de_verification(tache, precedent, copie, choix),
                modele,
                effort,
                copie or dossier,
                lecture_seule=True,
                contexte={"role": "verificateur", "tache": tache.id, "tentative": tache.tentatives},
                **en_plus,
                **self._plafond(),
            )
        finally:
            if copie:
                self.controles.jeter_copie(copie)
        self._compter(tache, avis)
        return avis

    def _consigne_de_verification(
        self, tache: Tache, precedent: Jugement | None, copie, choix: Verification | None = None
    ) -> str:
        """La consigne de la vérification décidée, avec la sortie des contrôles joués.

        Retouche : la consigne restreinte, le relevé (ou le verdict entier qui vient de refuser)
        et les fichiers changés. Relecture d'une correction : la consigne restreinte et le
        verdict précédent. Bornée : la consigne bornée au verdict complet. Sinon la consigne
        complète, qui nomme les fichiers résolus après la reprise d'un conflit de fusion.
        """
        contrat, jetable, profil = self.chantier.contrat, bool(copie), self.profil
        choix = choix or self._verification_d_avant(tache, precedent)
        sortie = choix.sortie
        if choix.genre == RETOUCHE:
            precedent_ = self._verdict_releve(tache, precedent)
            fichiers = list(choix.fichiers) or None
            return consigne_reverification(
                tache, contrat, profil, precedent_, jetable, sortie, fichiers
            )
        if choix.genre == REVERIFICATION and precedent is not None:
            verdict = precedent.verdict
            return consigne_reverification(tache, contrat, profil, verdict, jetable, sortie)
        if choix.genre == BORNEE:
            return consigne_verificateur_bornee(
                tache, contrat, profil, sortie or "", jetable, verdict_complet=True
            )
        conflits = precedent.complet if choix.genre == CONFLIT and precedent is not None else ""
        return consigne_verificateur(tache, contrat, profil, jetable, conflits, sortie)

    def _verdict_releve(self, tache: Tache, precedent: Jugement | None) -> str:
        """Ce que reçoit le vérificateur d'une retouche comme verdict précédent : le verdict entier
        qui vient de refuser cette copie, s'il est là, sinon le relevé gardé dans la tâche."""
        if precedent is not None and precedent.origine == "verdict" and precedent.verdict.strip():
            return precedent.verdict
        with self.verrou:
            return tache.releve

    def _copie_de_verification(self, tache: Tache, dossier):
        """La copie jetable où le vérificateur fait ses essais, ou None : il relit alors la
        copie de l'ouvrier, sans rien y écrire, comme avant (contrôles simulés, échec de git)."""
        copier = getattr(self.controles, "copie_de_verification", None)
        if copier is None or dossier is None:
            return None
        try:
            return copier(tache, dossier)
        except Exception as erreur:  # le vérificateur part quand même, en relecture seule
            self._noter(f"Copie du vérificateur impossible, il relit seulement : {erreur}", tache)
            return None

    def _montee(self) -> str:
        """La règle de montée du profil (`montee`) : "fond" sans réglage ou mal réglée."""
        regle = self.profil.get("montee")
        return regle if regle in MONTEES else MONTEE_SANS_REGLAGE

    def _apres_echec(self, tache: Tache, motif: str, detail: str, repris: bool = False) -> bool:
        """Décide de la suite après un refus. Rend False si la tâche s'arrête là.

        C'est la règle « refus » (`"montee": "refus"` au profil), et, sous la règle « fond », la
        suite d'un arrêt ou d'une consigne mal posée ; pour les autres refus, la règle « fond »
        passe par `_suite_sur_le_fond`.

        `repris` dit que le refus vient de la reprise à chaud de ce départ. Elle tient lieu de
        seconde chance au même niveau : le départ neuf qui suit monte d'un cran si le contrat le
        permet, sinon repart au même niveau si c'était le premier départ, sinon la tâche revient.
        """
        contrat = self.chantier.contrat
        if motif == ARRETEE:  # ni seconde chance ni montée : la personne reprend la main
            self._rendre(tache, MOTIF_ARRET)
            return False
        if motif == "consigne":
            self._rendre(tache, f"le vérificateur juge la consigne mal posée. {detail}")
            return False
        if tache.tentatives >= contrat.max_tentatives + tache.rallonge:
            if self._relancer_seul(tache, motif, detail):
                return True
            self._rendre(tache, f"{tache.tentatives} tentatives sans succès. {detail}")
            return False
        premier = tache.tentatives - tache.rallonge == 1
        if premier and not repris:
            self._noter(f"Refusée. {detail} Seconde chance au même niveau.", tache)
            return True
        return self._monter(tache, motif, detail, repris, premier)

    def _suite_sur_le_fond(self, tache: Tache, motif: str, detail: str, fond_faux: bool) -> bool:
        """La suite d'un refus sous la règle « fond » (sans réglage) : le modèle ne monte que si
        le vérificateur juge le fond faux ; un manque, un contrôle rouge ou un débord se
        corrigent au même niveau, sur le travail gardé. Seul un fond jugé faux fait monter, et
        seul lui permet la relance seule d'une tâche épuisée ; tout autre refus repart au même
        niveau tant qu'il reste une tentative, puis la tâche revient à la personne."""
        contrat = self.chantier.contrat
        if tache.tentatives >= contrat.max_tentatives + tache.rallonge:
            if fond_faux and self._relancer_seul(tache, motif, detail):
                return True
            self._rendre(tache, f"{tache.tentatives} tentatives sans succès. {detail}")
            return False
        if fond_faux:
            premier = tache.tentatives - tache.rallonge == 1
            return self._monter(tache, motif, detail, False, premier)
        self._noter(
            f"Refusée. {detail} Le fond n'est pas en cause : je repars au même niveau, sans "
            "monter de modèle.",
            tache,
        )
        return True

    def _monter(self, tache: Tache, motif: str, detail: str, repris: bool, premier: bool) -> bool:
        """Monte d'un cran pour le départ suivant, si le contrat le permet.

        Sinon, après la reprise refusée d'un premier départ, la tâche repart au même niveau ;
        dans les autres cas, elle revient à la personne responsable.
        """
        refusee = "Refusée après sa reprise." if repris else "Refusée."
        suivant = dosage.monter(tache.modele, tache.effort, motif)
        with self.verrou:
            trop_de_montees = self.chantier.montees >= self.chantier.contrat.max_montees
        if trop_de_montees or not self._sous_plafond(suivant):
            if premier:
                self._noter(
                    f"{refusee} {detail} Le contrat ne permet pas de monter d'un cran : je "
                    "repars de zéro au même niveau.",
                    tache,
                )
                return True
            self._rendre(tache, f"le plafond d'escalade du contrat est atteint. {detail}")
            return False
        with self.verrou:
            tache.modele, tache.effort = suivant
            tache.montees += 1
            self.chantier.montees += 1
        self._noter(f"{refusee} {detail} Je monte d'un cran : {dosage.libelle(*suivant)}.", tache)
        return True

    def _relancer_seul(self, tache: Tache, motif: str, detail: str) -> bool:
        """Relance une tâche épuisée un cran plus haut, sans attendre la personne responsable.

        Seulement RELANCES_AUTO fois par tâche, et sous le plafond d'escalade du contrat : au-delà,
        la tâche revient vers la personne responsable, comme avant.
        """
        suivant = dosage.monter(tache.modele, tache.effort, motif)
        with self.verrou:
            if tache.relances_auto >= RELANCES_AUTO:
                return False
            if not self._sous_plafond(suivant):
                return False
            tache.relances_auto += 1
            tache.modele, tache.effort = suivant
            tache.rallonge = tache.tentatives
        self._noter(
            f"{tache.tentatives} tentatives sans succès. {detail} Je relance seul un cran plus "
            f"haut : {dosage.libelle(*suivant)}.",
            tache,
        )
        return True

    def _apres_erreur_d_agent(self, tache: Tache, jugement: Jugement) -> bool:
        """Après une erreur d'agent (délai, panne de Claude Code) : jamais de montée, qui
        paierait un modèle plus cher pour une panne. Seconde chance au même niveau ;
        la tâche revient si l'erreur se répète ou si ses tentatives sont épuisées."""
        with self.verrou:
            fenetre = self._fenetre(tache)
            epuisee = tache.tentatives >= self.chantier.contrat.max_tentatives + tache.rallonge
        if len(fenetre) >= 2 and fenetre[-2].get("origine") == "agent":
            self._rendre(
                tache,
                "deux erreurs d'agent de suite. Une erreur d'agent ne fait pas monter d'un cran : "
                f"je te laisse décider de la suite. {jugement.detail}",
            )
            return False
        if epuisee:
            self._rendre(tache, f"{tache.tentatives} tentatives sans succès. {jugement.detail}")
            return False
        refusee = "Refusée après sa reprise." if jugement.reprise else "Refusée."
        self._noter(
            f"{refusee} {jugement.detail} Seconde chance au même niveau : une erreur d'agent ne "
            "fait pas monter d'un cran.",
            tache,
        )
        return True

    # --- le blocage : une tâche que relancer ne ferait pas avancer ------------------------------

    def _fenetre(self, tache: Tache) -> list[dict]:
        """Sous le verrou : les entrées d'historique depuis la dernière relance décidée (par la
        personne, ou seule un cran plus haut). Un refus d'avant ne compte pas contre la suite.
        Une passe coupée par une panne d'agent (`ATTENTE_PANNE`) est neutre : elle n'y entre pas."""
        return [
            e
            for e in tache.historique
            if (e.get("tentative") or 0) > tache.rallonge and e.get("issue") != ATTENTE_PANNE
        ]

    def _cause_de_blocage(self, tache: Tache, jugement: Jugement) -> str:
        """Sous le verrou, la passe tracée : la cause qui bloque la tâche, ou "".

        La règle d'usage du cahier (« V3-refus », « V3b ») : un agent empêché bloque tout de
        suite (`_empeche`) ; un refus identique au précédent bloque quand plus aucun cran ne
        reste ; trois refus de même forme de suite bloquent même si un cran reste (la seule
        ressemblance de mots n'y suffit pas).
        """
        if jugement.motif in (None, ARRETEE):
            return ""
        if self._empeche(jugement):
            return EMPECHE
        fenetre = self._fenetre(tache)
        identique = len(fenetre) >= 2 and refus.meme_refus(fenetre[-2], fenetre[-1])
        if identique and not self._cran_disponible(tache, jugement):
            return SANS_CRAN
        if refus.refus_de_meme_forme_de_suite(fenetre) >= 3:
            return REPETE
        return ""

    def _empeche(self, jugement: Jugement) -> bool:
        """Dit si un agent est empêché de travailler : relancer la tâche buterait au même endroit.

        Ce qu'un agent signale (une ligne « EMPÊCHÉ : », le champ `empeche` du verdict) l'est
        toujours. Un outil refusé à l'ouvrier, seulement s'il lance le premier mot d'une des
        commandes d'un contrôle du profil que les agents n'ont pas le droit de lancer
        (`agents.commande_permise`) : sans lui, l'ouvrier ne peut pas rejouer ce contrôle. Un
        contrôle permis, l'ouvrier le lance lui-même : le refus est sans rapport. Contrôle et outil
        refusé se comparent commande par commande (`_formes_lancees`). Un autre outil refusé, seul,
        ne bloque pas : la reprise le cite à l'ouvrier.
        """
        if jugement.signales:
            return True
        commandes = self.profil.get("commandes")
        commandes = commandes if isinstance(commandes, list) else []
        controles = [
            forme
            for c in commandes
            if isinstance(c, str) and not commande_permise(self.profil, c)
            for forme in _formes_lancees(c)
        ]
        lancees = [
            forme for r in jugement.refuses_seuls for forme in _formes_lancees(_commande_bash(r))
        ]
        return bool(refus.outils_de_controle(lancees, controles))

    def _cran_disponible(self, tache: Tache, jugement: Jugement) -> bool:
        """Sous le verrou : dit si l'escalade pourrait encore monter d'un cran après ce refus.

        Jamais après une erreur d'agent. Sous la règle « fond », jamais non plus quand le fond
        n'est pas jugé faux : le même refus deux fois de suite bloque alors la tâche. Tentatives
        épuisées, seule la relance seule monterait.
        """
        if jugement.origine == "agent":
            return False
        if self._montee() == "fond" and not jugement.fond_faux:
            return False
        if not self._sous_plafond(dosage.monter(tache.modele, tache.effort, jugement.motif)):
            return False
        contrat = self.chantier.contrat
        if tache.tentatives >= contrat.max_tentatives + tache.rallonge:
            return tache.relances_auto < RELANCES_AUTO
        return self.chantier.montees < contrat.max_montees

    def _bloquer(self, tache: Tache, jugement: Jugement) -> None:
        """Rend la tâche bloquée avec une demande de nature « blocage », puis le dit à
        `sur_blocage`, hors du verrou. Les autres tâches continuent.

        La demande a les clés de toute demande de tâche, plus `nature`, `preuves` (les détails
        des derniers refus, `PREUVES_MAX` au plus, bornés) et `empechements`.
        """
        with self.verrou:
            cites = _refus_compares(self._fenetre(tache), jugement.blocage)
            passes = [e for e in tache.historique if e.get("issue") not in NON_REFUS]
            preuves = [_preuve(e) for e in passes[-PREUVES_MAX:]]
        demande = self._rendre(
            tache,
            _raison_de_blocage(jugement, cites),
            nature=NATURE_BLOCAGE,
            preuves=preuves,
            empechements=list(jugement.empechements),
        )
        if self.sur_blocage is None:
            return
        try:
            self.sur_blocage(demande)
        except Exception as erreur:  # le moteur continue : la demande reste ouverte
            detail = " ".join(f"{type(erreur).__name__} : {erreur}".split())[:300]
            self._noter(
                f"La suite donnée au blocage a échoué ({detail}). La demande reste ouverte : tu "
                "peux y répondre comme d'habitude.",
                tache,
            )

    # --- la branche principale, contrôlée en fin de chantier ---------------------------------

    def _reparer_si_besoin(self) -> bool:
        """Contrôle la branche principale quand tout est vérifié ; rouge, lance une réparation.

        Rend True si une tâche de réparation a été ajoutée. Au plus MAX_REPARATIONS par chantier :
        au-delà, le chantier s'arrête et le fil dit que les contrôles restent rouges.
        """
        self._principale_rouge = False
        controler = getattr(self.controles, "controler_principale", None)
        with self.verrou:
            taches = self.chantier.taches
            if controler is None or not taches or any(t.etat != "verifie" for t in taches):
                return False
            faites = sum(t.id.startswith(PREFIXE_REPARATION) for t in taches)
        passe, sortie = controler()
        if passe:
            return False
        if faites >= MAX_REPARATIONS:
            self._principale_rouge = True
            self._noter(
                f"Les contrôles échouent encore sur la branche principale après {faites} "
                "réparations : je m'arrête là.\n" + sortie[-1500:]
            )
            return False
        tache = self._tache_de_reparation(faites + 1, sortie)
        with self.verrou:
            self.chantier.taches.append(tache)
        self._noter(
            f"Les contrôles échouent sur la branche principale : je lance seul la tâche "
            f"{tache.id} pour les réparer.",
            tache,
        )
        return True

    def _tache_de_reparation(self, rang: int, sortie: str) -> Tache:
        """Une tâche qui fait repasser les contrôles du projet, avec ce qu'ils ont affiché."""
        tache = Tache(
            id=f"{PREFIXE_REPARATION}{rang}",
            titre="Réparer les contrôles de la branche principale",
            type="courante",
            pourquoi=(
                "Toutes les tâches sont vérifiées, mais les commandes de contrôle du projet "
                "échouent sur la branche principale. Voici leur sortie :\n" + sortie[-1500:]
            ),
            criteres=[
                "Les commandes de contrôle du projet passent toutes.",
                "La correction porte sur la cause, pas sur les tests : aucun test n'est retiré, "
                "affaibli ni sauté.",
            ],
            perimetre=["*"],
            ajoutee=True,
        )
        tache.modele, tache.effort = dosage.depart(tache.type, self.profil.get("dosage"))
        return tache

    # --- la réponse de la personne responsable ----------------------------------------------

    def repondre(self, demande_id: str, choix: str) -> None:
        """Applique la décision de la personne responsable sur une tâche qui lui est revenue.

        Une relance reprend la copie gardée, s'il y en a une ; un abandon la jette.
        """
        rallonge = ""
        with self.verrou:
            demande = next(d for d in self.chantier.demandes if d["id"] == demande_id)
            demande["reponse"] = choix
            tache = self.chantier.tache(demande["tache"])
            if choix in (RELANCER, RELANCER_TEL):
                # Au même niveau : utile quand la cause était ailleurs (un outil manquant, un
                # réglage corrigé depuis), pas dans la difficulté de la tâche.
                dernier = tache.historique[-1]["issue"] if tache.historique else ""
                suivant = dosage.monter(tache.modele, tache.effort, dernier)
                if suivant and choix == RELANCER:
                    tache.modele, tache.effort = suivant
                tache.rallonge = tache.tentatives
                tache.pannes = 0  # la patience après une panne repart d'une minute
                tache.etat = "a_lancer"
                rallonge = self._rallonger(demande)
                self._relancee_a[tache.id] = self.horloge()  # la mesure de l'attente seulement
            else:
                tache.etat = "abandonnee"
            jeter = tache.etat == "abandonnee" and tache.id not in self._en_vol
        if jeter:  # plus personne ne reprendra ce travail ; une relance, elle, le reprend
            self._jeter_copie_gardee(tache)
        self._noter(f"Décision reçue : {choix.lower()}.", tache)
        if rallonge:
            self._noter(rallonge, tache)
        with self.verrou:  # si le moteur tourne, la tâche relancée part sans attendre son tour
            self._reveiller()

    def jeter_les_copies_gardees(self) -> list[str]:
        """Jette les copies gardées des tâches qu'aucun fil ne mène, et rend leurs identifiants.

        Pour un chantier arrêté pour de bon (archivé) : plus personne ne reprendra ce travail, et
        aucune copie ne doit rester sur le disque. À appeler quand le moteur ne tourne pas.
        """
        with self.verrou:
            gardees = [t for t in self.chantier.taches if t.copie and t.id not in self._en_vol]
        for tache in gardees:
            self._jeter_copie_gardee(tache)
        return [t.id for t in gardees]

    def relancer_au_meme_niveau(self, demande_id: str) -> bool:
        """Répond à une demande de blocage par la relance au même niveau, comme son bouton.

        Le choix est désigné par son sens (`RELANCER_TEL`), jamais par sa place dans les options
        de la demande. Rend False, sans rien changer, si la demande n'existe pas, n'est pas un
        blocage ou n'attend plus de réponse ; le contrôle et la réponse se font sous le verrou.
        """
        with self.verrou:
            demande = next((d for d in self.chantier.demandes if d.get("id") == demande_id), None)
            if demande is None or demande.get("nature") != NATURE_BLOCAGE:
                return False
            if demande.get("reponse") is not None:
                return False
            self.repondre(demande_id, RELANCER_TEL)
        return True
