"""Le moteur : un chef de chantier en code.

Il lance les ouvriers, contrôle leur travail, fait passer le vérificateur, monte d'un cran
après un échec et s'arrête quand il sort du contrat. Aucun modèle ne décide de ces étapes :
elles se déroulent de la même façon à chaque fois.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from contextlib import suppress

from atelier import dosage
from atelier.consignes import (
    consigne_ouvrier,
    consigne_planification,
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


class Moteur:
    """Conduit un chantier du contrat validé jusqu'à la dernière tâche vérifiée."""

    def __init__(
        self,
        chantier: Chantier,
        agent,
        controles,
        profil: dict | None = None,
        sur_changement: Callable[[], None] | None = None,
    ):
        self.chantier = chantier
        self.agent = agent
        self.controles = controles
        self.profil = profil or {}
        self.sur_changement = sur_changement or (lambda: None)
        self.verrou = threading.RLock()
        self._arretees: set[str] = set()  # les tâches dont l'arrêt est demandé, pas encore pris
        self._enregistrement: set[str] = set()  # acceptées : l'arrêt vient trop tard
        for tache in chantier.taches:
            if not tache.modele:
                tache.modele, tache.effort = dosage.depart(tache.type, self.profil.get("dosage"))
        self._reprendre()

    # --- petits outils -------------------------------------------------------------

    def _noter(self, texte: str, tache: Tache | None = None) -> None:
        with self.verrou:
            self.chantier.noter(texte, tache.id if tache else "")
        self.sur_changement()

    def _prendre_agent(self) -> None:
        """Compte un lancement d'agent. Il n'y a pas de plafond : le compte sert au bilan."""
        with self.verrou:
            self.chantier.agents_lances += 1

    def _compter(self, tache: Tache, resultat) -> None:
        with self.verrou:
            tache.cout_usd += resultat.cout_usd
            tache.tokens += resultat.tokens
            self.chantier.cout_usd += resultat.cout_usd
            self.chantier.tokens += resultat.tokens

    def _rendre(self, tache: Tache, raison: str) -> None:
        """Rend une tâche à la personne responsable, avec une seule décision à prendre."""
        with self.verrou:
            tache.etat = "revenu"
            self.chantier.demandes.append(
                {
                    "id": f"{tache.id}-{len(self.chantier.demandes) + 1}",
                    "tache": tache.id,
                    "question": f"Tâche {tache.id}, « {tache.titre} » : {raison}",
                    "options": [RELANCER_TEL, RELANCER, ABANDONNER],
                    "reponse": None,
                }
            )
        self._noter(f"J'ai besoin de toi : {raison}", tache)

    # --- les pannes de l'Atelier lui-même ------------------------------------------

    def _demander(self, tache: Tache, raison: str, detail: str) -> None:
        """Sous le verrou : rend la tâche après une panne, avec sa trace et sa décision."""
        tache.etat = "revenu"
        tache.historique.append(
            {
                "tentative": tache.tentatives,
                "modele": tache.modele,
                "effort": tache.effort,
                "issue": PANNE,
                "detail": detail,
            }
        )
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
        with ThreadPoolExecutor(max_workers=paralleles) as bassin:
            en_vol: set = set()
            while True:
                with self.verrou:
                    while len(en_vol) < paralleles and (tache := self._prochaine()):
                        tache.etat = "en_cours"
                        en_vol.add(bassin.submit(self._traiter, tache))
                if not en_vol:
                    break
                finis, en_vol = wait(en_vol, return_when=FIRST_COMPLETED)
                for fini in finis:
                    fini.result()
        self._conclure()

    def _conclure(self) -> None:
        taches = self.chantier.taches
        with self.verrou:
            self.chantier.termine = all(t.etat in ("verifie", "abandonnee") for t in taches)
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

    def _boucle(self, tache: Tache) -> None:
        remarques = ""
        while True:
            if self._arretee(tache):  # arrêt demandé avant le départ de l'ouvrier
                return self._arret_avant_depart(tache)
            self._prendre_agent()
            dossier, resultat = self._lancer_ouvrier(tache, remarques)
            if resultat is None:  # arrêt demandé pendant la préparation : l'ouvrier n'est pas parti
                self.controles.annuler(tache, dossier)
                return self._arret_avant_depart(tache)
            motif, detail = self._juger(tache, resultat, dossier)
            if motif is None:
                with self.verrou:  # dernier mot : un arrêt demandé jusqu'ici l'emporte
                    if self._arretee(tache):
                        motif, detail = ARRETEE, DETAIL_ARRET
                    else:
                        self._enregistrement.add(tache.id)
            with self.verrou:
                tache.historique.append(
                    {
                        "tentative": tache.tentatives,
                        "modele": tache.modele,
                        "effort": tache.effort,
                        "issue": motif or "valide",
                        "detail": detail,
                    }
                )
            if motif is None:
                self.controles.enregistrer(tache, dossier)
                with self.verrou:
                    tache.etat = "verifie"
                return self._noter("Vérifiée et enregistrée.", tache)
            self.controles.annuler(tache, dossier)
            remarques = detail
            if not self._apres_echec(tache, motif, detail):
                return None

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
        dossier = self.controles.preparer(tache)
        if self._arretee(tache):  # relu juste avant l'appel : rien de lent ne s'intercale
            with self.verrou:
                tache.tentatives -= 1
                self.chantier.agents_lances -= 1
            return dossier, None
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
            tache.historique.append(
                {
                    "tentative": tache.tentatives + 1,
                    "modele": tache.modele,
                    "effort": tache.effort,
                    "issue": ARRETEE,
                    "detail": DETAIL_ARRET,
                }
            )
        self._rendre(tache, MOTIF_ARRET)

    def _juger(self, tache: Tache, resultat, dossier) -> tuple[str | None, str]:
        """Rend (None, résumé) si le livrable est accepté, sinon (motif, détail)."""
        if self._arretee(tache, resultat):
            return ARRETEE, DETAIL_ARRET
        if not resultat.ok:
            return "ne_sait_pas", f"L'agent s'est arrêté sur une erreur : {resultat.erreur}"
        modifies = self.controles.fichiers_modifies(tache, dossier, resultat)
        dehors = hors_perimetre(modifies, tache.perimetre)
        if dehors:
            return "deborde", "Fichiers modifiés hors périmètre : " + ", ".join(dehors) + "."
        passe, sortie = self.controles.mecaniques(tache, dossier)
        if not passe:
            return "ne_sait_pas", "Les contrôles automatiques échouent :\n" + sortie[-1500:]
        if self._arretee(tache):  # aucun agent n'est en marche : le vérificateur ne part pas
            return ARRETEE, DETAIL_ARRET
        self._prendre_agent()
        avis = self._lancer_verificateur(tache, dossier)
        if avis is None or self._arretee(tache, avis):
            return ARRETEE, DETAIL_ARRET
        verdict = lire_verdict(avis.texte) if avis.ok else lire_verdict("")
        with self.verrou:
            tache.verdict = verdict["resume"]
        if verdict["valide"]:
            return None, verdict["resume"]
        return verdict["motif"], verdict["resume"]

    def _lancer_verificateur(self, tache: Tache, dossier):
        """Lance le vérificateur ; rend son avis, ou None si l'arrêt a été demandé avant son départ.

        Dans ce cas l'agent n'est pas lancé et ne compte pas parmi les agents lancés.
        """
        with self.verrou:
            tache.etat = "en_verification"
        modele, effort = dosage.verificateur(tache.modele, tache.effort)
        self._noter(f"Vérificateur lancé ({dosage.libelle(modele, effort)}).", tache)
        if self._arretee(tache):  # relu juste avant l'appel : rien de lent ne s'intercale
            with self.verrou:
                self.chantier.agents_lances -= 1
            return None
        avis = self.agent.executer(
            consigne_verificateur(tache, self.chantier.contrat, self.profil),
            modele,
            effort,
            dossier,
            lecture_seule=True,
            contexte={"role": "verificateur", "tache": tache.id, "tentative": tache.tentatives},
        )
        self._compter(tache, avis)
        return avis

    def _apres_echec(self, tache: Tache, motif: str, detail: str) -> bool:
        """Décide de la suite après un refus. Rend False si la tâche s'arrête là."""
        contrat = self.chantier.contrat
        if motif == ARRETEE:  # ni seconde chance ni montée : la personne reprend la main
            self._rendre(tache, MOTIF_ARRET)
            return False
        if motif == "consigne":
            self._rendre(tache, f"le vérificateur juge la consigne mal posée. {detail}")
            return False
        if tache.tentatives >= contrat.max_tentatives + tache.rallonge:
            self._rendre(tache, f"{tache.tentatives} tentatives sans succès. {detail}")
            return False
        if tache.tentatives - tache.rallonge == 1:
            self._noter(f"Refusée. {detail} Seconde chance au même niveau.", tache)
            return True
        suivant = dosage.monter(tache.modele, tache.effort, motif)
        plafond = (contrat.plafond_modele, contrat.plafond_effort)
        with self.verrou:
            trop_de_montees = self.chantier.montees >= contrat.max_montees
        if suivant is None or trop_de_montees or not dosage.dans_plafond(*suivant, plafond):
            self._rendre(tache, f"le plafond d'escalade du contrat est atteint. {detail}")
            return False
        with self.verrou:
            tache.modele, tache.effort = suivant
            tache.montees += 1
            self.chantier.montees += 1
        self._noter(f"Refusée. {detail} Je monte d'un cran : {dosage.libelle(*suivant)}.", tache)
        return True

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
            else:
                tache.etat = "abandonnee"
        self._noter(f"Décision reçue : {choix.lower()}.", tache)
