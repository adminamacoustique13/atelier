"""Le moteur : un chef de chantier en code.

Il lance les ouvriers, contrôle leur travail, fait passer le vérificateur, monte d'un cran
après un échec et s'arrête quand il sort du contrat. Aucun modèle ne décide de ces étapes :
elles se déroulent de la même façon à chaque fois.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

from atelier import dosage
from atelier.consignes import (
    consigne_ouvrier,
    consigne_planification,
    consigne_verificateur,
    dernier_json,
    lire_verdict,
)
from atelier.controles import hors_perimetre, se_chevauchent
from atelier.modele import Chantier, Tache

ACTIFS = ("en_cours", "en_verification")
RELANCER, ABANDONNER = "Relancer un cran plus haut", "Abandonner cette tâche"


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
        for tache in chantier.taches:
            if not tache.modele:
                tache.modele, tache.effort = dosage.depart(tache.type, self.profil.get("dosage"))

    # --- petits outils -------------------------------------------------------------

    def _noter(self, texte: str, tache: Tache | None = None) -> None:
        with self.verrou:
            self.chantier.noter(texte, tache.id if tache else "")
        self.sur_changement()

    def _prendre_agent(self) -> bool:
        """Compte un lancement d'agent. Refuse si l'enveloppe du contrat est épuisée."""
        with self.verrou:
            if self.chantier.agents_lances >= self.chantier.contrat.max_agents:
                return False
            self.chantier.agents_lances += 1
            return True

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
                    "options": [RELANCER, ABANDONNER],
                    "reponse": None,
                }
            )
        self._noter(f"J'ai besoin de toi : {raison}", tache)

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
        remarques = ""
        while True:
            if not self._prendre_agent():
                return self._rendre(tache, "l'enveloppe d'agents du contrat est épuisée.")
            with self.verrou:
                tache.tentatives += 1
                tache.etat = "en_cours"
            self._noter(
                f"Ouvrier lancé ({dosage.libelle(tache.modele, tache.effort)}), "
                f"tentative {tache.tentatives}.",
                tache,
            )
            dossier = self.controles.preparer(tache)
            resultat = self.agent.executer(
                consigne_ouvrier(tache, self.chantier.contrat, self.profil, remarques),
                tache.modele,
                tache.effort,
                dossier,
                contexte={"role": "ouvrier", "tache": tache.id, "tentative": tache.tentatives},
            )
            self._compter(tache, resultat)
            motif, detail = self._juger(tache, resultat, dossier)
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

    def _juger(self, tache: Tache, resultat, dossier) -> tuple[str | None, str]:
        """Rend (None, résumé) si le livrable est accepté, sinon (motif, détail)."""
        if not resultat.ok:
            return "ne_sait_pas", f"L'agent s'est arrêté sur une erreur : {resultat.erreur}"
        modifies = self.controles.fichiers_modifies(tache, dossier, resultat)
        dehors = hors_perimetre(modifies, tache.perimetre)
        if dehors:
            return "deborde", "Fichiers modifiés hors périmètre : " + ", ".join(dehors) + "."
        passe, sortie = self.controles.mecaniques(tache, dossier)
        if not passe:
            return "ne_sait_pas", "Les contrôles automatiques échouent :\n" + sortie[-1500:]
        if not self._prendre_agent():
            return "enveloppe", "L'enveloppe d'agents est épuisée avant la vérification."
        with self.verrou:
            tache.etat = "en_verification"
        modele, effort = dosage.verificateur(tache.modele, tache.effort)
        self._noter(f"Vérificateur lancé ({dosage.libelle(modele, effort)}).", tache)
        avis = self.agent.executer(
            consigne_verificateur(tache, self.chantier.contrat, self.profil),
            modele,
            effort,
            dossier,
            lecture_seule=True,
            contexte={"role": "verificateur", "tache": tache.id, "tentative": tache.tentatives},
        )
        self._compter(tache, avis)
        verdict = lire_verdict(avis.texte) if avis.ok else lire_verdict("")
        with self.verrou:
            tache.verdict = verdict["resume"]
        if verdict["valide"]:
            return None, verdict["resume"]
        return verdict["motif"], verdict["resume"]

    def _apres_echec(self, tache: Tache, motif: str, detail: str) -> bool:
        """Décide de la suite après un refus. Rend False si la tâche s'arrête là."""
        contrat = self.chantier.contrat
        if motif == "enveloppe":
            self._rendre(tache, "l'enveloppe d'agents du contrat est épuisée.")
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
            if choix == RELANCER:
                dernier = tache.historique[-1]["issue"] if tache.historique else ""
                suivant = dosage.monter(tache.modele, tache.effort, dernier)
                if suivant:
                    tache.modele, tache.effort = suivant
                tache.rallonge = tache.tentatives
                tache.etat = "a_lancer"
                self.chantier.contrat.max_agents += 2
            else:
                tache.etat = "abandonnee"
        self._noter(f"Décision reçue : {choix.lower()}.", tache)
