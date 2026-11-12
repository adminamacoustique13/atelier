"""Le rythme de chaque agent : combien il agit, tranche de 15 secondes par tranche de 15 secondes.

Le tableau de bord en tire une petite courbe par poste. Une colonne vaut une tranche ; sa hauteur
dit combien l'agent a agi pendant ces 15 secondes : un outil lancé compte pour un, du texte écrit
compte pour un par tranche de 120 caractères (les textes arrivent par petits morceaux, mot à mot
pour l'orchestrateur : compter les morceaux gonflerait la courbe). Une demande d'autorisation
ouverte marque le début d'une attente, que le tableau peint en ambre jusqu'à la réponse.

Pour un agent en marche, la courbe montre les 5 dernières minutes. Quand un ouvrier finit, toute
sa marche est résumée en autant de colonnes et gardée pour sa tâche : le poste d'une tâche
vérifiée montre ainsi le profil de tout son travail.

La démonstration, où un agent simulé ne travaille que quelques secondes, prend des tranches plus
courtes : la vue dit leur durée (`tranche_s`).

Tout reste en mémoire et borné : les tranches d'un agent (2 heures au plus), le nombre d'agents
suivis et le nombre de résumés gardés.
"""

from __future__ import annotations

import math
import time
from collections import OrderedDict

TRANCHE_S = 15  # secondes par colonne
COLONNES = 20  # colonnes par courbe : 5 minutes en direct
HISTOIRE_MAX = 480  # tranches gardées par agent : 2 heures
SUIVIS_MAX = 40  # agents suivis en même temps
BILANS_MAX = 200  # résumés de tâches gardés
CARACTERES_PAR_ACTION = 120  # du texte écrit : une action par tranche de 120 caractères
GENRES_ACTION = {"outil": 1.0, "refus": 1.0, "attente": 1.0, "mode": 0.0}


def _poste(nom: str) -> tuple[str, str]:
    """Rend (tâche, rôle) d'après le nom d'un agent, « B-ouvrier-1 » ; sans tâche pour le chef."""
    morceaux = nom.rsplit("-", 2)
    return (morceaux[0], morceaux[1]) if len(morceaux) == 3 else ("", nom)


def resumer(valeurs: list[float], colonnes: int = COLONNES) -> list[float]:
    """Ramène des tranches à `colonnes` colonnes : sommées si plus longues, étirées sinon."""
    n = len(valeurs)
    if not n:
        return [0.0] * colonnes
    if n >= colonnes:
        bornes = [math.floor(i * n / colonnes) for i in range(colonnes + 1)]
        return [round(sum(valeurs[bornes[i] : bornes[i + 1]]), 2) for i in range(colonnes)]
    return [round(valeurs[math.floor(i * n / colonnes)], 2) for i in range(colonnes)]


class Rythmes:
    """Les tranches d'activité des agents en marche, et le résumé de chaque tâche finie.

    Pas de verrou ici : l'appelant (`Activite`) en tient déjà un autour de chaque appel.
    """

    def __init__(self, horloge=time.monotonic, tranche_s: float = TRANCHE_S):
        self.horloge, self.tranche_s = horloge, tranche_s
        self._tranches: OrderedDict[str, dict[int, float]] = OrderedDict()
        self._attentes: dict[str, float] = {}  # agent -> instant où sa demande a été posée
        self._bilans: OrderedDict[str, list[float]] = OrderedDict()  # tâche -> courbe résumée

    def _tranche(self) -> int:
        return int(self.horloge() // self.tranche_s)

    def compter(self, nom: str, genre: str, contenu: str) -> None:
        """Compte un événement d'agent ; « fin » clôt sa marche et résume celle d'un ouvrier."""
        if genre == "fin":
            return self._finir(nom)
        tranches = self._tranches.setdefault(nom, {})
        self._tranches.move_to_end(nom)
        while len(self._tranches) > SUIVIS_MAX:
            ancien, _ = self._tranches.popitem(last=False)
            self._attentes.pop(ancien, None)
        if genre == "texte":
            poids = len(contenu) / CARACTERES_PAR_ACTION
        else:
            poids = GENRES_ACTION.get(genre, 1.0)
        ici = self._tranche()
        tranches[ici] = tranches.get(ici, 0.0) + poids
        for vieille in [t for t in tranches if t <= ici - HISTOIRE_MAX]:
            del tranches[vieille]
        if genre == "attente":
            self._attentes[nom] = self.horloge()
        elif genre in ("texte", "outil", "refus"):
            self._attentes.pop(nom, None)  # l'agent a repris : la demande a eu sa réponse

    def _finir(self, nom: str) -> None:
        tranches = self._tranches.pop(nom, None)
        self._attentes.pop(nom, None)
        tache, role = _poste(nom)
        if not tranches or not tache or role != "ouvrier":
            return
        debut, fin = min(tranches), max(tranches)
        self._bilans[tache] = resumer([tranches.get(t, 0.0) for t in range(debut, fin + 1)])
        self._bilans.move_to_end(tache)
        while len(self._bilans) > BILANS_MAX:
            self._bilans.popitem(last=False)

    @staticmethod
    def _colonnes(tranches: dict[int, float], ici: int) -> list[float]:
        return [round(tranches.get(t, 0.0), 2) for t in range(ici - COLONNES + 1, ici + 1)]

    def oublier_bilans(self) -> None:
        """Un nouveau chantier repart sans les courbes de l'ancien."""
        self._bilans.clear()

    def vue(self) -> dict:
        """Les courbes à montrer : `en_direct` par agent en marche, `bilans` par tâche finie.

        Chaque courbe en direct porte `attente`, le nombre de dernières colonnes passées à
        attendre une réponse (0 sans demande ouverte).
        """
        ici, maintenant = self._tranche(), self.horloge()
        en_direct = {}
        for nom, tranches in self._tranches.items():
            tache, role = _poste(nom)
            depuis = self._attentes.get(nom)
            attente = 0
            if depuis is not None:
                attente = min(COLONNES, math.ceil((maintenant - depuis) / self.tranche_s) or 1)
            en_direct[nom] = {
                "tache": tache,
                "role": role,
                "colonnes": self._colonnes(tranches, ici),
                "attente": attente,
            }
        return {"tranche_s": self.tranche_s, "en_direct": en_direct, "bilans": dict(self._bilans)}
