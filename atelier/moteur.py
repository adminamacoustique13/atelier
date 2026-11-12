"""Le moteur : un chef de chantier en code.

Il lance les ouvriers, contrôle leur travail, fait passer le vérificateur, redonne la main à
l'ouvrier refusé dans sa session, monte d'un cran après un échec et s'arrête quand il sort du
contrat. Il bloque une tâche que relancer ne ferait pas avancer (un agent empêché, un même refus
qui se répète) et la rend à la personne avec une demande claire. Aucun modèle ne décide de ces
étapes : elles se déroulent de la même façon à chaque fois.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from contextlib import suppress
from dataclasses import dataclass, replace

from atelier import dosage, refus
from atelier.agents import REPRISE_IMPOSSIBLE
from atelier.consignes import (
    PREUVE_MAX_CARACTERES,
    PREUVES_MAX,
    consigne_ouvrier,
    consigne_planification,
    consigne_reprise,
    consigne_reverification,
    consigne_verificateur,
    dernier_json,
    lire_verdict,
)
from atelier.controles import hors_perimetre, se_chevauchent
from atelier.guichet import ARRETE
from atelier.modele import Chantier, Tache

ACTIFS = ("en_cours", "en_verification")
# L'issue d'une tentative coupée par une panne de l'Atelier lui-même (git, disque, redémarrage) :
# la tâche revient à la personne responsable, sans seconde chance ni montée.
PANNE = "panne"
MOTIF_REDEMARRAGE = (
    "l'Atelier s'est arrêté pendant qu'elle était en cours (redémarrage ou panne). Ce que "
    "l'agent avait fait sans l'enregistrer est perdu."
)
DETAIL_REDEMARRAGE = "Interrompue par un arrêt de l'Atelier."
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
MOTIFS_REPRIS = ("bacle", "ne_sait_pas")  # un verdict « consigne » revient à la personne
VERDICT_GARDE = 8000  # les derniers caractères du texte du vérificateur, gardés et transmis
SORTIE_REPRISE = 4000  # les derniers caractères de la sortie des contrôles, pour la reprise
# D'où vient un refus, écrit dans l'entrée d'historique (`origine`) ; "" pour une tentative
# acceptée, arrêtée ou coupée par une panne. « agent » : l'ouvrier, ou le vérificateur, s'est
# arrêté sur une erreur (délai, limite de l'abonnement, surcharge, panne de Claude Code).
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
# causes, selon la règle d'usage du cahier (« V3-refus »), chacune avec le nombre de refus que
# la demande cite pour que la personne voie s'ils disent vraiment la même chose.
NATURE_BLOCAGE = "blocage"
EMPECHE = "empeche"  # un agent signale ce qui l'empêche de travailler
SANS_CRAN = "sans_cran"  # un refus identique au précédent, et plus aucun cran pour monter
REPETE = "repete"  # trois refus de même forme de suite, même si un cran reste
REFUS_CITES = {EMPECHE: 1, SANS_CRAN: 2, REPETE: 3}
DETAIL_CITE = 300  # les derniers caractères d'un détail cité dans la question
NON_REFUS = ("valide", ARRETEE, PANNE)  # les issues d'historique qui ne sont pas des refus


@dataclass(frozen=True)
class Jugement:
    """Ce que le moteur conclut d'une passe de l'ouvrier : accepté (`motif` None) ou refusé.

    `complet` est ce que reçoit l'ouvrier repris : le verdict entier, la liste des fichiers hors
    périmètre, ou la fin de la sortie des contrôles. `verdict` est le texte du vérificateur de
    cette passe (ses `VERDICT_GARDE` derniers caractères), s'il a fini son tour. `reprenable` dit
    si l'ouvrier peut reprendre la main ; `reprise`, si la passe jugée était une reprise.
    `empechements` : ce que l'ouvrier ou le vérificateur ont signalé comme les empêchant de
    travailler (`refus.empechements`) ; `blocage` : la cause qui bloque la tâche, "" sinon.
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

    def pour_la_suite(self) -> str:
        """Ce que reçoit le départ neuf qui suit : le verdict entier s'il y en a un, sinon le
        détail du refus."""
        return self.verdict if self.origine == "verdict" and self.verdict.strip() else self.detail


ARRET = Jugement(ARRETEE, DETAIL_ARRET)


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


def _raison_de_blocage(jugement: Jugement, cites: list[dict]) -> str:
    """La raison écrite dans la question d'une demande de blocage : la cause en une phrase, puis
    les détails des refus comparés, pour que la personne voie une éventuelle confusion."""
    details = [f"« {_court(e.get('detail'), DETAIL_CITE)} »" for e in cites] or ["« »"]
    if jugement.blocage == EMPECHE:
        empeches = jugement.empechements[:PREUVES_MAX]
        liste = " ; ".join(f"« {_court(e, DETAIL_CITE)} »" for e in empeches)
        return (
            f"elle est bloquée parce qu'un agent a été empêché de travailler : {liste}. La "
            "relancer telle quelle buterait au même endroit tant que la cause reste là. Le "
            f"refus : {details[-1]}."
        )
    if jugement.blocage == REPETE:
        cause = (
            "parce qu'elle a été refusée trois fois de suite pour la même raison : la relancer, "
            "même un cran plus haut, a peu de chances d'y changer quelque chose."
        )
    elif jugement.origine == "agent":
        cause = (
            "parce que les agents se sont arrêtés deux fois de suite sur la même erreur, et "
            "qu'une erreur d'agent ne fait pas monter d'un cran : la relancer telle quelle ne "
            "changerait rien."
        )
    else:
        cause = (
            "parce qu'elle a été refusée deux fois de suite pour la même raison, et que le "
            "contrat ne permet plus de monter d'un cran : la relancer telle quelle ne changerait "
            "rien."
        )
    return (
        f"elle est bloquée {cause} Les refus comparés : {' ; '.join(details)}. Si tu vois qu'ils "
        "ne disent pas la même chose, relance-la au même niveau."
    )


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


def taches_du_plan(plan: dict, profil: dict) -> list[Tache]:
    """Construit les tâches d'un plan rendu par l'orchestrateur, et dose chacune."""
    taches = []
    for brut in plan.get("taches") or []:
        if not isinstance(brut, dict) or not brut.get("id") or not brut.get("titre"):
            continue
        tache = Tache(**{cle: brut[cle] for cle in CHAMPS_DU_PLAN if cle in brut})
        if tache.type not in dosage.TYPES_FR:
            tache.type = "courante"
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
    ):
        self.chantier = chantier
        # Une horloge monotone, en secondes : remplaçable dans les tests, jamais l'heure du mur.
        self.horloge = horloge or time.monotonic
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
        for tache in chantier.taches:
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

    def _partir(self, tache: Tache) -> None:
        """Sous le verrou, au départ d'une tâche : note son attente depuis qu'elle est prête.

        Prête : au lancement du moteur, à la vérification de sa dernière dépendance, ou à la
        relance décidée par la personne responsable, selon ce qui vient en dernier.
        """
        moments = [self._lance_a, self._relancee_a.pop(tache.id, self._lance_a)]
        moments += [self._verifiee_a.get(d, self._lance_a) for d in tache.depend_de]
        self._attentes[tache.id] = max(0.0, self.horloge() - max(moments))

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

        `en_plus` : des clés ajoutées à la demande (celles d'un blocage). Rend la demande.
        """
        with self.verrou:
            tache.etat = "revenu"
            demande = {
                "id": f"{tache.id}-{len(self.chantier.demandes) + 1}",
                "tache": tache.id,
                "question": f"Tâche {tache.id}, « {tache.titre} » : {raison}",
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
        """Au chargement : rend les tâches qu'un arrêt de l'Atelier a laissées actives.

        Un moteur neuf n'a encore lancé aucun agent : une tâche « en cours » ou « en
        vérification » vient donc d'un état relu, et plus rien ne travaille pour elle. Sans cela
        elle ne repartirait jamais, et retiendrait celles qui dépendent d'elle ou partagent son
        périmètre. Rien n'est sauvé ici : celui qui monte le moteur sauve ensuite.
        """
        with self.verrou:
            for tache in self.chantier.taches:
                if tache.etat in ACTIFS:
                    self._demander(tache, MOTIF_REDEMARRAGE, DETAIL_REDEMARRAGE)

    def _panne(self, tache: Tache, erreur: Exception) -> None:
        """Rend à la personne responsable une tâche coupée par une erreur de l'Atelier.

        Une étape git qui échoue, un disque plein, un agent qui lève : la tâche revient avec
        l'erreur écrite en clair, et les autres tâches continuent. Une tâche déjà vérifiée ou
        déjà rendue garde son état : l'erreur (souvent la sauvegarde) est seulement écrite au fil.
        """
        detail = " ".join(f"{type(erreur).__name__} : {erreur}".split())[:500]
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

    def _prochaine(self) -> Tache | None:
        """Rend une tâche prête : dépendances vérifiées, périmètre libre."""
        taches = self.chantier.taches
        verifiees = {t.id for t in taches if t.etat == "verifie"}
        actives = [t for t in taches if t.etat in ACTIFS]
        for tache in taches:
            if tache.etat != "a_lancer" or not set(tache.depend_de) <= verifiees:
                continue
            if any(se_chevauchent(tache.perimetre, a.perimetre) for a in actives):
                continue
            return tache
        return None

    def executer(self) -> None:
        """Lance tout ce qui peut l'être, en parallèle, jusqu'à ce que plus rien ne bouge."""
        if not self.chantier.contrat.valide:
            raise ContratNonValide("Le contrat de chantier n'est pas validé.")
        paralleles = int(self.profil.get("paralleles", 3))
        self._lance_a = self.horloge()
        with ThreadPoolExecutor(max_workers=paralleles) as bassin:
            en_vol: set = set()
            while True:
                with self.verrou:
                    while len(en_vol) < paralleles and (tache := self._prochaine()):
                        tache.etat = "en_cours"
                        self._partir(tache)
                        en_vol.add(bassin.submit(self._traiter, tache))
                if not en_vol and not self._reparer_si_besoin():
                    break
                if not en_vol:
                    continue  # une réparation vient d'être ajoutée : elle part au tour suivant
                finis, en_vol = wait(en_vol, return_when=FIRST_COMPLETED)
                for fini in finis:
                    fini.result()
        self._conclure()

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

    def _boucle(self, tache: Tache) -> None:
        """Mène la tâche de départ neuf en départ neuf, jusqu'à ce qu'elle soit vérifiée ou rendue.

        Chaque départ a sa reprise à chaud : la copie de travail n'est jetée (`annuler`) que pour
        repartir de zéro ou rendre la tâche.
        """
        remarques = ""
        while True:
            if self._arretee(tache):  # arrêt demandé avant le départ de l'ouvrier
                return self._arret_avant_depart(tache)
            self._prendre_agent()
            dossier, resultat = self._lancer_ouvrier(tache, remarques)
            if resultat is None:  # arrêt demandé pendant la préparation : l'ouvrier n'est pas parti
                self.controles.annuler(tache, dossier)
                return self._arret_avant_depart(tache)
            jugement = self._passe(tache, dossier, resultat)
            jugement = self._reprises(tache, dossier, resultat.session, jugement)
            if jugement.motif is None:
                return self._verifiee(tache, jugement)
            self.controles.annuler(tache, dossier)
            remarques = jugement.pour_la_suite()
            if not self._suite(tache, jugement):
                return None

    def _verifiee(self, tache: Tache, jugement: Jugement) -> None:
        """La tâche est vérifiée ; un empêchement signalé en chemin est seulement noté au fil."""
        with self.verrou:
            tache.etat = "verifie"
        self._noter("Vérifiée et enregistrée.", tache)
        if jugement.empechements:
            liste = " ; ".join(f"« {_court(e, DETAIL_CITE)} »" for e in jugement.empechements)
            self._noter(
                f"Un agent a signalé un empêchement pendant cette tâche : {liste}. Le livrable a "
                "quand même été accepté et enregistré. Si cette commande doit servir aux agents, "
                "tu peux la leur permettre dans les outils du projet.",
                tache,
            )

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
        return self._apres_echec(tache, jugement.motif, jugement.detail, jugement.reprise)

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
        que le pont lui a refusés, devant ce que le vérificateur a signalé."""
        refuses = getattr(resultat, "refuses", None)
        ouvrier = refus.empechements(getattr(resultat, "texte", ""), refuses, None)
        tous = tuple(dict.fromkeys([*ouvrier, *jugement.empechements]))
        return replace(jugement, empechements=tous)

    def _enregistrer(self, tache: Tache, dossier, jugement: Jugement) -> Jugement:
        """Fait entrer le livrable accepté dans la branche principale ; rend le jugement final."""
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
        return replace(jugement, motif="ne_sait_pas", detail=probleme, origine="integration")

    # --- la reprise à chaud ---------------------------------------------------------

    def _reprises(self, tache: Tache, dossier, session: str, jugement: Jugement) -> Jugement:
        """Redonne la main à l'ouvrier refusé, au plus `REPRISES_PAR_DEPART` fois pour ce départ.

        Rend le jugement de la dernière passe : celui de la reprise, ou le refus d'origine si
        aucune reprise n'a pu partir (refus qui ne se reprend pas, session perdue).
        """
        for _ in range(REPRISES_PAR_DEPART):
            if not jugement.reprenable:
                break
            jugement = self._reprise(tache, dossier, session, jugement)
        return jugement

    def _reprise(self, tache: Tache, dossier, session: str, refus: Jugement) -> Jugement:
        """Une reprise à chaud : l'ouvrier refusé corrige dans sa session et sa copie, puis sa
        passe est jugée comme les autres (périmètre, contrôles, vérificateur)."""
        self._noter(
            f"Refusée. {refus.detail} Je redonne la main au même ouvrier, dans sa copie et sa "
            "session, pour qu'il corrige.",
            tache,
        )
        resultat = self._lancer_reprise(tache, dossier, session, refus)
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

    def _lancer_reprise(self, tache: Tache, dossier, session: str, refus: Jugement):
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
            consigne_reprise(tache, refus.origine, refus.complet, self.profil),
            tache.modele,
            tache.effort,
            dossier,
            contexte={"role": "ouvrier", "tache": tache.id, "tentative": tache.tentatives},
            reprendre=session,
        )
        self._compter(tache, resultat)
        if resultat.erreur == REPRISE_IMPOSSIBLE:
            with self.verrou:
                self.chantier.agents_lances -= 1
                self._mesure.pop(tache.id, None)
        return resultat

    def _lancer_ouvrier(self, tache: Tache, remarques: str):
        """Prépare le travail et lance l'ouvrier ; rend (dossier, résultat).

        Le résultat est None si l'arrêt a été demandé pendant la préparation : l'agent n'est
        alors pas lancé, et ni le compte des agents ni celui des tentatives ne le gardent.
        """
        with self.verrou:
            tache.tentatives += 1
            tache.etat = "en_cours"
        self._noter(
            f"Ouvrier lancé ({dosage.libelle(tache.modele, tache.effort)}), "
            f"tentative {tache.tentatives}.",
            tache,
        )
        self._phase(tache, PHASES["preparation"])
        dossier = self.controles.preparer(tache)
        if self._arretee(tache):  # relu juste avant l'appel : rien de lent ne s'intercale
            with self.verrou:
                tache.tentatives -= 1
                self.chantier.agents_lances -= 1
            return dossier, None
        self._phase(tache, PHASES["ouvrier"].format(tache.tentatives))
        resultat = self.agent.executer(
            consigne_ouvrier(tache, self.chantier.contrat, self.profil, remarques),
            tache.modele,
            tache.effort,
            dossier,
            contexte={"role": "ouvrier", "tache": tache.id, "tentative": tache.tentatives},
        )
        self._compter(tache, resultat)
        return dossier, resultat

    def _arret_avant_depart(self, tache: Tache) -> None:
        """Rend la tâche arrêtée avant qu'un ouvrier n'ait travaillé, en gardant la trace."""
        with self.verrou:
            self._tracer(tache, ARRETEE, DETAIL_ARRET, decalage=1)
        self._rendre(tache, MOTIF_ARRET)

    def _juger(
        self, tache: Tache, resultat, dossier, precedent: Jugement | None = None
    ) -> Jugement:
        """Juge une passe de l'ouvrier : périmètre, contrôles, puis vérificateur.

        Rend un `Jugement` sans motif si le livrable est accepté. `precedent` est le refus qui a
        conduit à une reprise : venu du vérificateur, il appelle une vérification restreinte.
        """
        if self._arretee(tache, resultat):
            return ARRET
        if not resultat.ok:
            detail = f"L'agent s'est arrêté sur une erreur : {resultat.erreur}"
            return Jugement("ne_sait_pas", detail, "agent")
        refus = self._controler(tache, dossier, resultat)
        if refus is not None:
            return refus
        if self._arretee(tache):  # aucun agent n'est en marche : le vérificateur ne part pas
            return ARRET
        return self._verifier(tache, dossier, precedent)

    def _controler(self, tache: Tache, dossier, resultat) -> Jugement | None:
        """Contrôle le périmètre puis lance les contrôles ; rend le refus, ou None s'ils passent.

        Ces deux refus se reprennent à chaud : l'ouvrier a fini son tour et le message existe.
        """
        self._phase(tache, PHASES["perimetre"])
        modifies = self.controles.fichiers_modifies(tache, dossier, resultat)
        dehors = hors_perimetre(modifies, tache.perimetre)
        if dehors:
            detail = "Fichiers modifiés hors périmètre : " + ", ".join(dehors) + "."
            return Jugement("deborde", detail, "perimetre", list(dehors), reprenable=True)
        commandes = getattr(self.controles, "commandes", None) or []
        if commandes:
            self._phase(tache, PHASES["controles"] + " ; ".join(commandes))
        passe, sortie = self.controles.mecaniques(tache, dossier)
        if passe:
            return None
        detail = "Les contrôles automatiques échouent :\n" + sortie[-1500:]
        fin = sortie[-SORTIE_REPRISE:]
        return Jugement("ne_sait_pas", detail, "controles", fin, reprenable=True)

    def _verifier(self, tache: Tache, dossier, precedent: Jugement | None) -> Jugement:
        """Fait relire le livrable par un vérificateur neuf et lit son verdict.

        Un vérificateur en erreur ou au verdict illisible est relancé une fois, neuf, sur la même
        copie de l'ouvrier, avant de valoir refus ; sauf s'il signale un empêchement, sur lequel
        un second buterait aussi.
        """
        avis = self._avis(tache, dossier, precedent)
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
            avis = self._avis(tache, dossier, precedent)
            if avis is None or self._arretee(tache, avis):
                return ARRET
        return self._lire_avis(tache, avis)

    def _avis(self, tache: Tache, dossier, precedent: Jugement | None):
        """Compte et lance un vérificateur ; rend son avis, ou None (arrêt avant son départ)."""
        self._prendre_agent()
        return self._lancer_verificateur(tache, dossier, precedent)

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

    def _lire_avis(self, tache: Tache, avis) -> Jugement:
        """Le jugement que porte l'avis du vérificateur.

        Seul un verdict lisible qui recale pour « bâclé » ou « ne sait pas » se reprend à chaud :
        un verdict illisible, ou une consigne mal posée, ne se reprend pas. Un vérificateur en
        erreur est une erreur d'agent (origine « agent ») : elle ne fera pas monter d'un cran.
        """
        empeches = self._empeches_du_verificateur(avis)
        verdict = lire_verdict(avis.texte) if avis.ok else lire_verdict("")
        texte = (avis.texte or "")[-VERDICT_GARDE:] if avis.ok else ""
        with self.verrou:
            tache.verdict = verdict["resume"]
        if verdict["valide"]:
            return Jugement(None, verdict["resume"], verdict=texte, empechements=empeches)
        if not avis.ok:
            detail = f"Le vérificateur s'est arrêté sur une erreur : {avis.erreur}"
            return Jugement("ne_sait_pas", detail, "agent", empechements=empeches)
        lisible = "valide" in (dernier_json(avis.texte or "") or {})
        reprenable = lisible and verdict["motif"] in MOTIFS_REPRIS
        motif, resume = verdict["motif"], verdict["resume"]
        return Jugement(motif, resume, "verdict", texte, texte, reprenable, False, empeches)

    def _lancer_verificateur(self, tache: Tache, dossier, precedent: Jugement | None = None):
        """Lance le vérificateur ; rend son avis, ou None si l'arrêt a été demandé avant son départ.

        Dans ce cas l'agent n'est pas lancé et ne compte pas parmi les agents lancés. Après la
        reprise d'un refus du vérificateur, c'est un vérificateur neuf, au même dosage, avec la
        consigne restreinte : le verdict précédent en entier, et seulement les points recalés.
        """
        with self.verrou:
            tache.etat = "en_verification"
        modele, effort = dosage.verificateur(tache.modele, tache.effort)
        restreinte = precedent is not None and precedent.origine == "verdict"
        objet = " sur la correction" if restreinte else ""
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
                self._consigne_de_verification(tache, precedent if restreinte else None, copie),
                modele,
                effort,
                copie or dossier,
                lecture_seule=True,
                contexte={"role": "verificateur", "tache": tache.id, "tentative": tache.tentatives},
                **en_plus,
            )
        finally:
            if copie:
                self.controles.jeter_copie(copie)
        self._compter(tache, avis)
        return avis

    def _consigne_de_verification(self, tache: Tache, precedent: Jugement | None, copie) -> str:
        """La consigne complète, ou la consigne restreinte qui suit la reprise d'un verdict."""
        contrat, jetable = self.chantier.contrat, bool(copie)
        if precedent is None:
            return consigne_verificateur(tache, contrat, self.profil, jetable)
        return consigne_reverification(tache, contrat, self.profil, precedent.verdict, jetable)

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

    def _apres_echec(self, tache: Tache, motif: str, detail: str, repris: bool = False) -> bool:
        """Décide de la suite après un refus. Rend False si la tâche s'arrête là.

        `repris` : le refus vient de la reprise à chaud de ce départ. Elle tient lieu de seconde
        chance au même niveau : le départ neuf qui suit monte d'un cran si le contrat le permet,
        sinon repart au même niveau si c'était le premier départ, sinon la tâche revient.
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
        """Après une erreur d'agent (délai, limite, surcharge, panne de Claude Code) : jamais de
        montée, qui paierait un modèle plus cher pour une panne. Seconde chance au même niveau ;
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
        personne, ou seule un cran plus haut). Un refus d'avant ne compte pas contre la suite."""
        return [e for e in tache.historique if (e.get("tentative") or 0) > tache.rallonge]

    def _cause_de_blocage(self, tache: Tache, jugement: Jugement) -> str:
        """Sous le verrou, la passe tracée : la cause qui bloque la tâche, ou "".

        La règle d'usage du cahier (« V3-refus ») : un agent qui signale un empêchement bloque
        tout de suite ; un refus identique au précédent bloque quand plus aucun cran ne reste ;
        trois refus de même forme de suite bloquent même si un cran reste (la seule
        ressemblance de mots n'y suffit pas).
        """
        if jugement.motif in (None, ARRETEE):
            return ""
        if jugement.empechements:
            return EMPECHE
        fenetre = self._fenetre(tache)
        identique = len(fenetre) >= 2 and refus.meme_refus(fenetre[-2], fenetre[-1])
        if identique and not self._cran_disponible(tache, jugement):
            return SANS_CRAN
        if refus.refus_de_meme_forme_de_suite(fenetre) >= 3:
            return REPETE
        return ""

    def _cran_disponible(self, tache: Tache, jugement: Jugement) -> bool:
        """Sous le verrou : dit si l'escalade pourrait encore monter d'un cran après ce refus.

        Jamais après une erreur d'agent. Tentatives épuisées, seule la relance seule monterait.
        """
        if jugement.origine == "agent":
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
            cites = self._fenetre(tache)[-REFUS_CITES[jugement.blocage] :]
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
        """Applique la décision de la personne responsable sur une tâche qui lui est revenue."""
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
                tache.etat = "a_lancer"
                self._relancee_a[tache.id] = self.horloge()  # la mesure de l'attente seulement
            else:
                tache.etat = "abandonnee"
        self._noter(f"Décision reçue : {choix.lower()}.", tache)
