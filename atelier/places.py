"""Les places et le régulateur d'abonnement : qui peut partir, et quand plus rien ne part.

Deux nombres réglables bornent le travail :
- `paralleles` (6 par défaut) : le plus grand nombre de tâches en cours d'écriture (ouvrier,
  contrôle du périmètre, contrôles du profil). Une tâche en vérification rend sa place.
- `agents_max` (par défaut `paralleles + max(1, paralleles // 2)`, soit 9 pour 6 places) : le
  plus grand nombre d'agents en marche au même instant, ouvriers et vérificateurs. Ce n'est pas
  un plafond du total lancé. Même avec une seule place, il reste un jeton pour qu'un
  vérificateur travaille pendant que la tâche suivante écrit.

Un agent en marche tient un jeton. Un jeton libéré va d'abord au vérificateur qui attend depuis
le plus longtemps, avant tout nouvel ouvrier : finir une tâche libère un périmètre et des
dépendances.

Le régulateur lit les limites de l'abonnement Claude, telles que le SDK les nomme
(`five_hour`, `seven_day`, `seven_day_opus`, `seven_day_sonnet`, `overage`) :
- une alerte (limite proche) divise par deux les places effectives, au moins une, jusqu'à l'heure
  de remise à zéro, ou 30 minutes si elle est inconnue ; les agents en marche finissent ;
- un refus pour limite suspend tout lancement jusqu'à la remise à zéro plus 60 secondes ; heure
  inconnue : 15 minutes, puis 30, puis 60 à chaque refus suivant. Une limite propre à un modèle
  ne suspend que lui : `seven_day_sonnet` Sonnet, `seven_day_opus` Opus et, par prudence, Fable
  (`FAMILLES_SUSPENDUES`). L'ouvrier refusé rend sa place et son jeton : il repartira comme une
  tâche neuve quand la suspension se lèvera ; le vérificateur refusé reprend la tête de la file.
  Un refus pour limite n'est jamais un échec de la tâche : rien n'est compté contre elle ;
- Claude surchargé (pas une limite de l'abonnement) : plus aucun lancement pendant deux minutes
  (`surcharge`).
Une heure de remise à zéro mal formée ou déjà passée compte comme inconnue.

Aucun interblocage, si l'appelant tient le contrat : à la fin de chaque agent, il appelle
`en_verification`, `partir`, `rendre_jeton` ou `finir`, et une tâche qui veut repartir écrire
passe par `partir`, pas par `peut_partir` seul. Une tâche qui tient un jeton sans place et ne
peut pas partir rend alors son jeton. Quand plus rien ne tourne et qu'aucune suspension ne court,
aucun jeton n'est donc tenu : ils vont aux vérificateurs qui attendent, puis aux tâches qui
tiennent une place, puis aux tâches neuves.

L'heure est toujours fournie par l'appelant, en secondes Unix (comparable à `time.time()`),
l'unité de `Resultat.fin_limite` et de l'événement « limite ». Jamais l'horloge monotone du
moteur : les heures de remise à zéro du SDK sont des heures Unix.

Module pur : ni attente, ni fil, ni verrou, ni import d'un autre module d'Atelier. L'appelant
(le moteur) tient son propre verrou autour de chaque appel, lectures comprises.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass

PARALLELES = 6  # tâches en cours d'écriture, sans réglage
ALERTE_SANS_HEURE_S = 30 * 60  # durée d'une alerte dont l'heure de remise à zéro est inconnue
MARGE_REPRISE_S = 60  # attente après l'heure de remise à zéro annoncée
ATTENTE_SANS_HEURE_S = 15 * 60  # premier refus sans heure ; doublé à chaque refus suivant
ATTENTE_SANS_HEURE_MAX_S = 60 * 60
PAUSE_SURCHARGE_S = 2 * 60  # plus aucun lancement quand Claude est surchargé
TOUS = ""  # la portée d'une suspension qui vaut pour tous les modèles
SURCHARGE = "surcharge"  # la portée de la pause pour surcharge, qui vaut aussi pour tous
LIMITE_INCONNUE = "inconnue"
LIMITES_PAR_MODELE = {"seven_day_opus": "opus", "seven_day_sonnet": "sonnet"}
# Les familles que suspend une limite propre à un modèle. Celle d'Opus suspend aussi Fable, par
# prudence : rien ne dit que Fable a sa propre fenêtre dans l'abonnement, et une tâche Fable qui
# continuerait de partir reviendrait à la personne au cinquième refus, en quelques secondes.
FAMILLES_SUSPENDUES = {"opus": ("opus", "fable"), "sonnet": ("sonnet",)}
FAMILLES = ("opus", "sonnet", "haiku", "fable")
FAMILLES_FR = {"opus": "Opus", "sonnet": "Sonnet", "haiku": "Haiku", "fable": "Fable"}


def lire_nombre(valeur, defaut: int) -> int:
    """Un réglage lu sans erreur : entier d'au moins 1 ; mal formé, `defaut` ; sous 1, 1.

    Accepte un entier, un nombre à virgule (tronqué) ou un texte qui en contient un.
    """
    if isinstance(valeur, str):
        try:
            valeur = float(valeur.strip())
        except ValueError:
            return defaut
    if isinstance(valeur, bool) or not isinstance(valeur, (int, float)):
        return defaut
    if not math.isfinite(valeur):
        return defaut
    return max(1, int(valeur))


def agents_max_par_defaut(paralleles: int) -> int:
    """Le plafond d'agents en marche sans réglage : une moitié de plus, au moins un de plus.

    Le jeton de plus sert un vérificateur pendant que la tâche suivante écrit.
    """
    return paralleles + max(1, paralleles // 2)


def famille(modele) -> str:
    """La famille d'un modèle : « opus » pour « opus » comme pour « claude-opus-4-1 »."""
    texte = modele.lower() if isinstance(modele, str) else ""
    return next((nom for nom in FAMILLES if nom in texte), texte)


def portees(modele) -> set[str]:
    """Les portées de suspension qui touchent `modele` : TOUS, la surcharge, et la limite propre
    à sa famille."""
    nom = famille(modele)
    return {TOUS, SURCHARGE} | {p for p, familles in FAMILLES_SUSPENDUES.items() if nom in familles}


def portee_de_limite(type_limite) -> str:
    """Le modèle que vise une limite (« opus » pour `seven_day_opus`), sinon TOUS."""
    if not isinstance(type_limite, str):
        return TOUS
    return LIMITES_PAR_MODELE.get(type_limite, TOUS)


def _fin_a_venir(fin, heure: float) -> float | None:
    """L'heure de remise à zéro si c'est un nombre fini encore à venir, sinon None."""
    if isinstance(fin, bool) or not isinstance(fin, (int, float)):
        return None
    if not math.isfinite(fin) or fin <= heure:
        return None
    return float(fin)


def heure_dite(quand: float, heure: float) -> str:
    """« à 14:05 » le même jour, « le 19/11 à 14:05 » un autre jour (heure locale)."""
    cible, maintenant = time.localtime(quand), time.localtime(heure)
    if cible[:3] == maintenant[:3]:
        return time.strftime("à %H:%M", cible)
    return time.strftime("le %d/%m à %H:%M", cible)


def _compte(nombre: int, mot: str) -> str:
    """« 0 tâche », « 1 tâche », « 2 tâches »."""
    return f"{nombre} {mot}{'s' if nombre > 1 else ''}"


@dataclass
class _Tache:
    """Ce que les places savent d'une tâche suivie."""

    modele: str = ""  # le modèle de son agent : l'ouvrier, puis le vérificateur
    ecrit: bool = False  # elle tient une place d'écriture
    jeton: bool = False  # elle tient un jeton d'agent
    rang: int = 0  # le rang du dernier lancement qui lui a donné son jeton


class Places:
    """Les places d'écriture, les jetons d'agent et les suspensions pour limite.

    Pas de verrou ici : l'appelant (le moteur) tient le sien autour de chaque appel. Toutes les
    heures sont en secondes Unix et viennent de l'appelant.

    Une tâche suivie tient au plus une place et un jeton. Les comptes sont tirés de ces deux
    marques : aucun ne peut devenir négatif, quel que soit l'ordre des appels. Une tâche
    inconnue est ignorée par `finir` et `rendre_jeton`.
    """

    def __init__(self, paralleles=PARALLELES, agents_max=None):
        self._taches: dict[str, _Tache] = {}
        self._attente: list[str] = []  # les vérificateurs sans jeton, du plus ancien au dernier
        self._alertes: dict[str, tuple[float | None, float]] = {}  # type -> (annoncée, jusqu'à)
        self._suspensions: dict[str, float] = {}  # portée -> heure de reprise
        self._paliers: dict[str, int] = {}  # portée -> refus sans heure depuis le dernier succès
        self._refus_au_rang: dict[str, int] = {}  # portée -> rang du dernier lancement au refus
        self._rang = 0  # le nombre de jetons donnés depuis le début
        self.regler(paralleles, agents_max)

    def regler(self, paralleles=PARALLELES, agents_max=None) -> None:
        """Relit les deux nombres ; absent ou mal formé, la valeur par défaut ; sous 1, 1.

        Un plafond abaissé n'arrête aucun agent : il ne donne plus de jeton ni de place tant que
        le compte n'est pas redescendu dessous.
        """
        self.paralleles = lire_nombre(paralleles, PARALLELES)
        self.agents_max = lire_nombre(agents_max, agents_max_par_defaut(self.paralleles))

    # --- comptes ------------------------------------------------------------------

    def en_ecriture(self) -> int:
        """Le nombre de tâches qui tiennent une place d'écriture."""
        return sum(t.ecrit for t in self._taches.values())

    def agents_en_marche(self) -> int:
        """Le nombre de jetons tenus : agents en marche, ou sur le point de l'être."""
        return sum(t.jeton for t in self._taches.values())

    def a_son_jeton(self, tache: str) -> bool:
        """Dit si `tache` tient un jeton d'agent (son vérificateur peut partir)."""
        etat = self._taches.get(tache)
        return etat is not None and etat.jeton

    def places_effectives(self, heure: float) -> int:
        """Les places de l'instant : la moitié (au moins une) pendant une alerte de limite."""
        if any(heure < jusqu for _, jusqu in self._alertes.values()):
            return max(1, self.paralleles // 2)
        return self.paralleles

    def suspension(self, modele: str, heure: float) -> float | None:
        """L'heure de reprise des lancements de `modele`, ou None s'ils sont permis."""
        visees = portees(modele) & self._suspensions.keys()
        reprises = [self._suspensions[p] for p in visees if heure < self._suspensions[p]]
        return max(reprises, default=None)

    def prochaine_echeance(self, heure: float) -> float | None:
        """La prochaine heure où une alerte ou une suspension prend fin, ou None."""
        heures = [jusqu for _, jusqu in self._alertes.values()] + list(self._suspensions.values())
        return min((h for h in heures if h > heure), default=None)

    def _jetons_libres(self) -> int:
        return max(0, self.agents_max - self.agents_en_marche())

    def _servable(self, tache: str, heure: float) -> bool:
        return self.suspension(self._taches[tache].modele, heure) is None

    def _jetons_pour_ouvriers(self, heure: float, sauf: str | None) -> int:
        """Les jetons libres une fois servis les vérificateurs qui attendent et peuvent partir."""
        servables = sum(1 for t in self._attente if t != sauf and self._servable(t, heure))
        return self._jetons_libres() - servables

    # --- le cours d'une tâche -----------------------------------------------------

    def peut_partir(self, modele: str, heure: float, tache: str | None = None) -> bool:
        """Dit si un ouvrier de `modele` peut partir maintenant.

        Il faut une place d'écriture libre, un jeton qu'aucun vérificateur en attente ne doit
        recevoir avant lui, et aucune suspension pour ce modèle. Pour une tâche déjà suivie
        (`tache`), la place ou le jeton qu'elle tient déjà comptent comme acquis. Ne change rien :
        une tâche qui tient un jeton et veut repartir écrire appelle `partir`, qui le rend au
        besoin.
        """
        etat = self._taches.get(tache) if tache is not None else None
        if self.suspension(modele, heure) is not None:
            return False
        if not (etat and etat.ecrit) and self.en_ecriture() >= self.places_effectives(heure):
            return False
        return bool(etat and etat.jeton) or self._jetons_pour_ouvriers(heure, tache) > 0

    def partir(self, tache: str, modele: str, heure: float) -> bool:
        """Fait partir l'ouvrier de `tache` s'il le peut : place et jeton pris ; sinon rien.

        Vaut aussi pour une tâche suivie qui repart écrire (reprise après des contrôles rouges ou
        après une vérification) : elle garde ce qu'elle tient déjà. Mais une tâche qui tient un
        jeton sans place et ne peut pas partir rend son jeton (son agent a fini), qui va aux
        vérificateurs qui attendent : sans cela, des tâches qui tiennent les jetons en attendant
        une place et des tâches qui tiennent les places en attendant un jeton se bloqueraient
        pour toujours. L'appelant réveille alors les vérificateurs (`a_son_jeton`).
        """
        if not self.peut_partir(modele, heure, tache):
            self._lacher_le_jeton(tache, heure)
            return False
        etat = self._taches.setdefault(tache, _Tache())
        if etat.jeton:
            self._reussite(etat)  # son agent précédent a fini sans refus pour limite
        self._retirer_de_l_attente(tache)
        etat.modele, etat.ecrit = modele, True
        self._donner_jeton(etat)
        return True

    def en_verification(self, tache: str, modele: str, heure: float) -> bool:
        """`tache` passe en vérification avec un vérificateur de `modele`.

        Elle rend sa place d'écriture. Elle garde son jeton pour le vérificateur si elle en
        tient un et que ce modèle n'est pas suspendu ; sinon elle attend son tour, après les
        vérificateurs qui attendaient déjà. Rend vrai si le vérificateur peut partir tout de
        suite ; sinon `a_son_jeton` le dira plus tard, après `servir`, `rendre_jeton` ou `finir`.
        """
        etat = self._taches.setdefault(tache, _Tache())
        etat.ecrit = False
        if etat.jeton:
            self._reussite(etat)  # l'ouvrier a fini sans refus pour limite
        etat.modele = modele
        if etat.jeton and self.suspension(modele, heure) is None:
            self._donner_jeton(etat)  # le jeton de l'ouvrier passe à son vérificateur
            return True
        etat.jeton = False
        if tache not in self._attente:
            self._attente.append(tache)
        self.servir(heure)
        return etat.jeton

    def servir(self, heure: float) -> list[str]:
        """Donne les jetons libres aux vérificateurs qui attendent, du plus ancien au dernier.

        Un vérificateur dont le modèle est suspendu passe son tour sans bloquer les autres.
        Rend les tâches servies : leur vérificateur peut partir. À appeler à chaque tour de la
        boucle du moteur (une suspension qui finit ne prévient personne) ; les appels qui
        rendent un jeton l'appellent d'eux-mêmes.
        """
        servis = []
        for tache in list(self._attente):
            if self._jetons_libres() <= 0:
                break
            if self._servable(tache, heure):
                self._attente.remove(tache)
                self._donner_jeton(self._taches[tache])
                servis.append(tache)
        return servis

    def rendre_jeton(self, tache: str, heure: float) -> list[str]:
        """L'agent de `tache` s'est arrêté ; elle garde sa place. Rend les tâches servies."""
        etat = self._taches.get(tache)
        if etat is not None and etat.jeton:
            self._reussite(etat)
            etat.jeton = False
        return self.servir(heure)

    def finir(self, tache: str, heure: float) -> list[str]:
        """`tache` quitte les places (vérifiée, rendue, arrêtée…). Rend les tâches servies."""
        etat = self._taches.pop(tache, None)
        self._retirer_de_l_attente(tache)
        if etat is not None and etat.jeton:
            self._reussite(etat)
        return self.servir(heure)

    def _lacher_le_jeton(self, tache: str, heure: float) -> None:
        """`tache` tient un jeton sans place et ne peut pas repartir : elle le rend."""
        etat = self._taches.get(tache)
        if etat is None or etat.ecrit or not etat.jeton:
            return
        self.rendre_jeton(tache, heure)
        if tache not in self._attente:
            del self._taches[tache]  # plus rien de tenu : elle repartira comme une tâche neuve

    def _donner_jeton(self, etat: _Tache) -> None:
        self._rang += 1
        etat.jeton, etat.rang = True, self._rang

    def _retirer_de_l_attente(self, tache: str) -> None:
        if tache in self._attente:
            self._attente.remove(tache)

    def _reussite(self, etat: _Tache) -> None:
        """Un agent a fini sans refus pour limite : l'attente sans heure repart de 15 minutes pour
        chaque portée dont la suspension était déjà levée quand il a reçu son jeton."""
        for portee in portees(etat.modele):
            if etat.rang > self._refus_au_rang.get(portee, 0):
                self._paliers.pop(portee, None)

    # --- le régulateur ------------------------------------------------------------

    def alerte(self, type_limite, fin, heure: float) -> bool:
        """Une limite de l'abonnement est proche. Rend vrai si l'alerte est nouvelle.

        Nouvelle : aucune alerte en cours pour ce type de limite, ou une autre heure de remise
        à zéro annoncée. Le fil ne la dit qu'une fois par limite et par heure. Une alerte
        répétée ne divise pas les places une fois de plus ; sans heure, elle prolonge les
        30 minutes. Les valeurs mal formées comptent comme inconnues, sans erreur.
        """
        self._alertes = {k: v for k, v in self._alertes.items() if heure < v[1]}
        cle = type_limite if isinstance(type_limite, str) and type_limite else LIMITE_INCONNUE
        annoncee = _fin_a_venir(fin, heure)
        ancienne = self._alertes.get(cle)
        if ancienne is None or (annoncee is not None and annoncee != ancienne[0]):
            jusqu = annoncee if annoncee is not None else heure + ALERTE_SANS_HEURE_S
            self._alertes[cle] = (annoncee, jusqu)
            return True
        if annoncee is None and ancienne[0] is None:
            self._alertes[cle] = (None, max(ancienne[1], heure + ALERTE_SANS_HEURE_S))
        return False

    def refus(self, tache: str, type_limite, fin, heure: float) -> dict:
        """L'agent de `tache` a été refusé pour limite : suspend les lancements visés.

        Rien n'est compté contre la tâche. Un ouvrier refusé rend sa place et son jeton : à la
        reprise, `partir` le relancera comme une tâche neuve, sans quoi des ouvriers refusés
        tiendraient les places pendant toute une limite propre à leur modèle. Un vérificateur
        refusé rend son jeton et reprend la tête de la file : `servir` lui en rendra un à la
        reprise. Rend :
        - `portee` : TOUS (« ») ou la famille visée (« opus », « sonnet ») ;
        - `reprise` : l'heure Unix où les lancements visés reprennent ;
        - `nouvelle` : vrai si la suspension commence ou change d'heure (à dire au fil) ;
        - `servis` : les vérificateurs qui reçoivent un jeton (modèle non suspendu).
        """
        portee = portee_de_limite(type_limite)
        return self._suspendre(tache, portee, self._reprise_apres_refus(portee, fin, heure), heure)

    def surcharge(self, tache: str, heure: float) -> dict:
        """L'agent de `tache` a été refusé parce que Claude est surchargé, sans limite de
        l'abonnement atteinte : plus aucun lancement pendant `PAUSE_SURCHARGE_S`, que prolonge
        une surcharge suivante. Le reste comme `refus`, qui dit ce qu'elle rend (portée
        SURCHARGE)."""
        avant = self._suspensions.get(SURCHARGE)
        reprise = heure + PAUSE_SURCHARGE_S
        return self._suspendre(tache, SURCHARGE, max(reprise, avant or reprise), heure)

    def _suspendre(self, tache: str, portee: str, reprise: float, heure: float) -> dict:
        """Suspend `portee` jusqu'à `reprise` et retire l'agent refusé de `tache` (`refus`)."""
        avant = self._suspensions.get(portee)
        self._suspensions[portee] = reprise
        self._refus_au_rang[portee] = self._rang
        self._arreter_pour_limite(tache)
        return {
            "portee": portee,
            "reprise": reprise,
            "nouvelle": avant is None or heure >= avant or reprise != avant,
            "servis": self.servir(heure),
        }

    def _arreter_pour_limite(self, tache: str) -> None:
        """L'agent de `tache` a été refusé : l'ouvrier sort des places, le vérificateur attend."""
        etat = self._taches.get(tache)
        if etat is not None and etat.ecrit:
            del self._taches[tache]  # place et jeton rendus
            self._retirer_de_l_attente(tache)
            return
        if etat is None or not etat.jeton:
            return
        etat.jeton = False
        if tache not in self._attente:
            self._attente.insert(0, tache)

    def _reprise_apres_refus(self, portee: str, fin, heure: float) -> float:
        """L'heure de reprise : remise à zéro plus 60 s, ou 15, 30 puis 60 minutes sans heure.

        Un refus qui arrive pendant une suspension de même portée vient d'un agent lancé avant
        elle : il ne double pas l'attente, il peut seulement la prolonger jusqu'à son heure.
        """
        avant = self._suspensions.get(portee)
        en_cours = avant is not None and heure < avant
        annoncee = _fin_a_venir(fin, heure)
        if annoncee is not None:
            reprise = annoncee + MARGE_REPRISE_S
            return max(reprise, avant) if en_cours else reprise
        if en_cours:
            return avant
        palier = self._paliers.get(portee, 0)
        self._paliers[portee] = min(palier + 1, 8)
        return heure + min(ATTENTE_SANS_HEURE_S * 2**palier, ATTENTE_SANS_HEURE_MAX_S)

    # --- pour l'affichage ---------------------------------------------------------

    def etat(self, heure: float) -> dict:
        """Les places et le régulateur pour l'affichage, avec une phrase en français.

        `reprise` est l'heure Unix de reprise d'une suspension de tous les modèles pour limite
        (None sans elle) ; `suspensions` donne les autres (portée -> heure Unix) : celles propres
        à un modèle (sa famille) et la pause pour surcharge (SURCHARGE).
        """
        suspensions = {p: r for p, r in self._suspensions.items() if heure < r}
        alertes = [jusqu for _, jusqu in self._alertes.values() if heure < jusqu]
        etat = {
            "places": self.paralleles,
            "places_effectives": self.places_effectives(heure),
            "en_ecriture": self.en_ecriture(),
            "agents_max": self.agents_max,
            "agents_en_marche": self.agents_en_marche(),
            "verificateurs_en_attente": len(self._attente),
            "alerte_jusqu_a": max(alertes, default=None),
            "reprise": suspensions.pop(TOUS, None),
            "suspensions": suspensions,
        }
        etat["phrase"] = _phrase(etat, heure)
        return etat


def _phrase(etat: dict, heure: float) -> str:
    """La phrase de `Places.etat` : les comptes, puis l'alerte et les suspensions en cours."""
    phrases = [
        f"{_compte(etat['en_ecriture'], 'tâche')} en écriture sur "
        f"{_compte(etat['places_effectives'], 'place')}, "
        f"{_compte(etat['agents_en_marche'], 'agent')} en marche sur {etat['agents_max']} au "
        f"plus, {_compte(etat['verificateurs_en_attente'], 'vérificateur')} en attente."
    ]
    if etat["alerte_jusqu_a"] is not None:
        phrases.append(
            f"Une limite de l'abonnement est proche : {_compte(etat['places_effectives'], 'place')}"
            f" au lieu de {etat['places']}, l'alerte prend fin "
            f"{heure_dite(etat['alerte_jusqu_a'], heure)}."
        )
    if etat["reprise"] is not None:
        phrases.append(phrase_de_suspension(TOUS, etat["reprise"], heure))
    for portee, reprise in sorted(etat["suspensions"].items()):
        phrases.append(phrase_de_suspension(portee, reprise, heure))
    return " ".join(phrases)


def phrase_de_suspension(portee: str, reprise: float, heure: float) -> str:
    """La phrase d'une suspension en cours : une limite de tous les modèles (TOUS), la pause
    pour surcharge (SURCHARGE), ou une limite propre à un modèle."""
    quand = heure_dite(reprise, heure)
    if portee == TOUS:
        return (
            "Une limite de l'abonnement est atteinte : plus aucun lancement, ils reprennent "
            f"{quand}."
        )
    if portee == SURCHARGE:
        return (
            "Claude est surchargé pour un moment (ce n'est pas une limite de l'abonnement) : plus "
            f"aucun lancement, ils reprennent {quand}."
        )
    touchees = " ni ".join(_de(f) for f in FAMILLES_SUSPENDUES.get(portee, (portee,)))
    return (
        f"La limite propre à {FAMILLES_FR.get(portee, portee)} est atteinte : plus aucun "
        f"lancement {touchees}, ils reprennent {quand}."
    )


def _de(famille_: str) -> str:
    """« d'Opus », « de Fable »."""
    nom = FAMILLES_FR.get(famille_, famille_)
    return f"d'{nom}" if nom[:1].lower() in "aeiouy" else f"de {nom}"
