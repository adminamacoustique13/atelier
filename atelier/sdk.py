"""Le pont vers l'Agent SDK : une session asynchrone, pilotée depuis des fils synchrones.

Le SDK de Claude est asynchrone ; le moteur et le serveur d'Atelier travaillent en fils.
Chaque `SessionSDK` fait donc tourner sa propre boucle asyncio dans un fil à elle, et le
reste du code n'en voit que des appels synchrones : `envoyer`, `arreter`, `fermer`.

Règles de concurrence, à garder en tête en relisant :
- tout ce qui touche au client SDK se passe dans la boucle de la session ;
- le guichet, qui bloque, est toujours appelé dans un fil à part, jamais dans la boucle ;
- `arreter` pose le drapeau du tour en cours (lisible de tout fil, attendable dans la boucle)
  et ferme les demandes ouvertes au guichet ; le tour rend alors l'arrêt sans attendre ;
- chaque client a aussi son drapeau, posé quand il est coupé : une demande venue d'un client
  coupé est refusée sans passer par le guichet, même si un nouveau tour a commencé ;
- à la fin de tout tour, réussi ou non, les demandes de l'agent sont fermées au guichet ;
- un client coupé est interrompu puis déconnecté dans une tâche à part, jamais annulée :
  le SDK doit pouvoir aller jusqu'au bout de sa fermeture (attente, SIGTERM, SIGKILL) ;
- `fermer` attend la fin du tour en cours (son verrou), puis celle des déconnexions, puis
  arrête la boucle ;
- `changer_mode` ne fait que confier le changement à la boucle (sous un petit verrou, qui
  protège aussi la création de la boucle et la fermeture) ; dans la boucle, la connexion et les
  changements de mode passent l'un après l'autre (un verrou asyncio), et le plus récent gagne.

Le mode réel : Claude Code le donne au départ (message `init`) et quand il change (message
`status`) ; le pont le garde dans `mode_applique` et émet un événement « mode » quand il n'est
pas celui demandé. Les refus de l'arbitre du mode auto se lisent dans les résultats d'outil en
erreur, puis dans `permission_denials` en fin de tour ; chacun est annoncé une seule fois.

Les limites de l'abonnement : le SDK émet un `RateLimitEvent` quand l'état d'une limite change.
Une alerte (`allowed_warning`) ou un refus (`rejected`) donne un événement « limite » ; rien ne
s'arrête pour autant. C'est à la fin du tour qu'on juge : un tour en échec après un refus, ou
signalé comme tel par Claude Code (message en erreur « rate_limit », statut HTTP 429), rend
`LIMITE_ATTEINTE`, avec la limite et l'heure où elle se lève. Un tour réussi reste réussi.
Un `rejected` pendant que le dépassement payant prend le relais n'est pas un refus.

La surcharge : Claude Code marque aussi « rate_limit » un serveur qui limite les requêtes sans que
la limite de l'abonnement soit atteinte ; son texte le dit (« not your usage limit », « is
experiencing high load »). Un tour en échec sur ce signe rend `SURCHARGE`, sauf si un vrai refus
de limite a été vu dans le même tour : la limite l'emporte.

Les outils refusés : chaque résultat de tour porte dans `refuses` la forme courte des outils
refusés pendant le tour, d'où que vienne le refus : le guichet ou le pont (sans guichet, réponse
« non », guichet en panne ; jamais un refus pour arrêt), l'arbitre du mode auto, et en fin de tour
`permission_denials`, quel que soit le mode. Un même appel n'est compté qu'une fois.

Les refus d'office (`refus_d_office`, voir `atelier.agents.interdits`, dont ceux de tout agent
s'ajoutent toujours à ceux qu'on donne) : ils vont à Claude Code dans un fichier de réglages
(`permissions.deny`), lisible par son seul propriétaire, écrit à la première connexion de la
session et effacé quand elle se ferme, une fois tous ses Claude Code sortis. Un fichier plutôt
que la ligne de commande : il y en a plus d'un millier, avec des guillemets et des barres
inverses, que la ligne de commande de Windows n'accepte pas toujours. Si ce fichier ne peut pas
être écrit, l'agent ne part pas.

La reprise exigée (`reprise_exigee`) : la session demandée doit être celle qui répond. Si Claude
Code part dans une autre, ou si le tour échoue avant que la session ait répondu (connexion
refusée, fin en erreur, aucune réponse), le tour rend `REPRISE_IMPOSSIBLE`.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import math
import os
import re
import tempfile
import threading
import warnings
from contextlib import suppress
from pathlib import Path

from atelier.agents import (
    LIMITE_ATTEINTE,
    LIMITE_INCONNUE,
    REFUSES_MAX,
    REPRISE_IMPOSSIBLE,
    SURCHARGE,
    Resultat,
    decrire_limite,
    decrire_outil,
    forme_courte,
    interdits,
    mode_valide,
)
from atelier.guichet import ARRETE

# Le SDK avertit, à chaque agent, que le guichet n'est pas consulté pour les outils permis
# d'avance (lecture, modifications dans la copie de travail). C'est voulu (voir DECISIONS.md,
# « les modifications de fichiers restent permises d'avance ») : l'avertissement ne ferait
# qu'encombrer le journal de l'Atelier.
warnings.filterwarnings("ignore", message="can_use_tool will not be invoked")

CLAUDE_SANS_REPONSE = "Claude Code s'est arrêté sans répondre."
SANS_GUICHET = "Aucun guichet n'est branché : l'autorisation est refusée."
REFUS = "La personne responsable a refusé cet outil."
INCOMPRIS = "Le guichet a rendu une réponse incomprise : l'outil est refusé."
INTERROMPU = "Le SDK de Claude s'est interrompu sans donner de raison."
MARGE_S = 30  # garde-fou au-delà du délai de l'agent, si la boucle elle-même ne répond plus
# Une règle Claude Code : un nom d'outil, suivi ou non d'un contenu non vide entre parenthèses.
FORME_REGLE = re.compile(r"([A-Za-z0-9_.:-]+)(?:\((.+)\))?")
# Le résultat d'un outil refusé par l'arbitre du mode auto, et la règle qui a joué.
# Un refus de l'arbitre commence par cette phrase ; la trouver au milieu d'une sortie de
# commande (un grep, un test en échec) ne fait pas un refus.
ARBITRE = "Permission for this action was denied by the Claude Code auto mode classifier"
REGLE_ARBITRE = re.compile(r"Reason:\s*\[([^\]\n]{1,80})\]")
SANS_RAISON = "raison non précisée"
INDISPONIBLE = "le mode auto n'est pas disponible pour son modèle"
MEMOIRE_MAX = 256  # appels et refus retenus par session : au-delà, les plus anciens sont oubliés
# Les états de limite du SDK (`RateLimitStatus`) qui donnent un événement, et leur nom ici.
STATUTS_LIMITE = {"allowed_warning": "alerte", "rejected": "atteinte"}
DEPASSEMENT_PERMIS = ("allowed", "allowed_warning")  # le dépassement payant prend le relais
STATUT_HTTP_LIMITE = 429  # « trop de requêtes » : la limite atteinte, vue par l'API
# Ce que dit Claude Code (2.1.308) d'une surcharge qu'il marque pourtant « rate_limit » :
# « Server is temporarily limiting requests (not your usage limit) », pour un 429 sans en-tête
# de limite de l'abonnement, et « Opus is experiencing high load… » (de même pour Fable).
SURCHARGES = ("not your usage limit", "is experiencing high load")
# La nature d'un échec, lue sur ce que le SDK et Claude Code (2.1.308) donnent de structuré :
# le champ `error` d'un message de l'assistant, le statut HTTP et le sous-type du message de fin.
ERREURS_CONNEXION = ("authentication_failed",)  # Claude Code : « login required — run /login »
STATUTS_CONNEXION = (401,)
FIN_BUDGET = "error_max_budget_usd"  # le plafond `max_budget_usd` est atteint
# Claude Code marque `server_error` une connexion à l'API perdue (ECONNRESET…), un flux coupé,
# l'API saturée et les erreurs 5xx, « usually temporary ».
ERREURS_PASSAGERES = ("server_error",)
STATUTS_PASSAGERS = (408, *range(500, 600))
# Faute de mieux, sur le texte : les signes d'une connexion à Claude perdue, et ceux d'une panne
# dans un texte d'erreur de l'API (« API Error: … »), pour un Claude Code qui ne marque rien.
SIGNES_CONNEXION = (
    "failed to authenticate", "authentication_error", "oauth session expired",
    "oauth token has expired", "not logged in", "run /login", "invalid api key",
)  # fmt: skip
PREFIXE_API = "api error"
SIGNES_PANNE = (
    "connection to the api was lost", "connection error", "request timed out", "econnreset",
    "socket hang up", "usually temporary",
)  # fmt: skip


class _RepriseRefusee(Exception):
    """Claude Code est parti dans une autre session que celle qu'il fallait reprendre."""


def lire_source(api_key_source) -> str:
    """Traduit le champ `apiKeySource` du SDK : « abonnement », « clé API », ou rien."""
    if not api_key_source:
        return ""
    return "abonnement" if api_key_source == "none" else "clé API"


def lire_resultat(final, morceaux: list[str]) -> Resultat:
    """Traduit le message de fin du SDK en résultat : texte, coût et tokens, ou échec.

    Le coût est celui que porte le message (`total_cost_usd`), en erreur comme en succès : un
    tour raté a coûté lui aussi. C'est un cumul depuis le début de la session Claude Code ;
    la session du pont le ramène au tour (`cout_du_tour`).
    """
    if final is None:
        return Resultat(ok=False, erreur=CLAUDE_SANS_REPONSE)
    usage = getattr(final, "usage", None) or {}
    tokens = int(usage.get("input_tokens") or 0) + int(usage.get("output_tokens") or 0)
    texte = str(getattr(final, "result", None) or "")
    cout = cout_du_tour(getattr(final, "total_cost_usd", None), 0.0)
    if getattr(final, "is_error", False):
        erreur = texte or "Erreur signalée par Claude Code."
        return Resultat(ok=False, erreur=erreur, cout_usd=cout, tokens=tokens)
    return Resultat(ok=True, texte=texte or "".join(morceaux), cout_usd=cout, tokens=tokens)


def _montant(valeur) -> float | None:
    """Un montant lisible en dollars (un nombre fini, positif ou nul), ou None."""
    if isinstance(valeur, bool) or not isinstance(valeur, (int, float)):
        return None
    return float(valeur) if math.isfinite(valeur) and valeur >= 0 else None


def cout_du_tour(cumul, avant: float) -> float:
    """Ce qu'un tour a coûté, d'après le cumul de sa connexion et celui du tour d'avant.

    Claude Code annonce dans chaque message de fin le coût cumulé de la session : le tour en
    a coûté la différence. Un cumul absent, illisible, qui n'augmente pas ou qui baisse rend 0,
    jamais un coût négatif. Arrondi au milliardième de dollar, pour taire le bruit des flottants.
    """
    lu = _montant(cumul)
    if lu is None or lu <= avant:
        return 0.0
    return round(lu - avant, 9)


class _Cumuls:
    """Le registre « session Claude Code → plus haut cumul vu », commun au processus.

    Claude Code annonce dans chaque message de fin le coût cumulé de la session, et une session
    reprise, même par un autre pont (`executer(reprendre=…)`, chaque message de `converser`),
    repart du total qu'elle a gardé. Chaque tour rend donc la différence avec le plus haut cumul
    vu pour sa session, sous un verrou : deux fils sur une même session ne comptent rien deux
    fois. La référence ne baisse jamais (un résultat après plantage peut annoncer 0).

    Une session neuve (connexion qui l'ouvre) part de zéro, même si son identifiant est déjà
    connu : ce qu'on en savait ne vaut plus. Une session inconnue part de zéro aussi.

    Limite acceptée : le registre vit en mémoire. Après un redémarrage de l'Atelier il est vide,
    et le premier tour d'une session reprise compte son cumul entier : une erreur par excès, du
    côté sûr pour un budget. De même pour une session oubliée parce que le registre est plein :
    au-delà de `maxi` sessions, celles vues le moins récemment sont oubliées.
    """

    def __init__(self, maxi: int):
        self.maxi, self._vus, self._verrou = maxi, {}, threading.Lock()

    def part_du_tour(self, session: str, cumul, neuve: bool = False) -> float:
        lu = _montant(cumul)
        with self._verrou:
            avant = 0.0 if neuve else self._vus.get(session, 0.0)
            if neuve or lu is not None:
                self._vus.pop(session, None)  # remise au bout : la plus récemment vue
            if lu is not None:
                self._vus[session] = max(avant, lu)
                while len(self._vus) > self.maxi:
                    del self._vus[next(iter(self._vus))]
            return cout_du_tour(cumul, avant)

    def vider(self) -> None:
        with self._verrou:
            self._vus.clear()


# 4 096 sessions de ~200 octets chacune : moins d'un mégaoctet, pour des dizaines de chantiers
# (un agent lancé, une session ; un chantier de 30 tâches en ouvre de l'ordre de 150).
SESSIONS_RETENUES = 4096
_CUMULS = _Cumuls(SESSIONS_RETENUES)


def cout_de_session(session: str, cumul, neuve: bool = False) -> float:
    """Ce qu'un tour de cette session a coûté, d'après le cumul annoncé par son message de fin
    et le registre des cumuls du processus (`_Cumuls`), qu'il met à jour. `neuve` : le premier
    tour d'une connexion qui ouvre la session, qui part de zéro."""
    return _CUMULS.part_du_tour(session, cumul, neuve)


def vider_les_cumuls() -> None:
    """Oublie tous les cumuls retenus : chaque session repartira de zéro."""
    _CUMULS.vider()


def plafond_valide(budget) -> bool:
    """Dit si un plafond de dépense est à passer au SDK : un nombre fini strictement positif."""
    lu = _montant(budget)
    return lu is not None and lu > 0


def _statut_http(source) -> int | None:
    """Le statut HTTP de l'appel à l'API qui a échoué (`api_error_status`), s'il est donné."""
    statut = getattr(source, "api_error_status", None)
    return statut if isinstance(statut, int) and not isinstance(statut, bool) else None


def _textes_de_fin(source) -> list[str]:
    """Les textes d'une fin en erreur : `result` et `errors` (message de fin ou `ResultError`)."""
    erreurs = getattr(source, "errors", None)
    textes = [getattr(source, "result", None), *(erreurs if isinstance(erreurs, list) else [])]
    return [t for t in textes if isinstance(t, str)]


def lire_nature(fin=None, erreur_api=None, *textes) -> str:
    """La nature d'un échec qui n'est ni un arrêt, ni un délai, ni une limite, ni une surcharge,
    ni une reprise impossible (le pont les décide avant) : « connexion », « budget », « panne »,
    ou "" quand rien ne la dit (un agent qui n'a pas su faire, une erreur inconnue).

    `fin` est le message de fin du SDK, ou une `ResultError` qui en porte les champs ;
    `erreur_api`, le champ `error` d'un message de l'assistant ; `textes`, ceux de l'erreur.
    Le structuré passe avant le texte : une erreur passagère que Claude Code marque
    `server_error` reste une panne, même si son texte parle de connexion (« OAuth »). Le texte
    ne fait une panne que si rien de structuré ne dit le contraire (ni statut HTTP, ni erreur
    de l'assistant autre que « unknown »).
    """
    statut = _statut_http(fin)
    if erreur_api in ERREURS_CONNEXION or statut in STATUTS_CONNEXION:
        return "connexion"
    if getattr(fin, "subtype", None) == FIN_BUDGET:
        return "budget"
    if erreur_api in ERREURS_PASSAGERES or (statut is not None and statut in STATUTS_PASSAGERS):
        return "panne"
    lus = " ".join(t for t in (*textes, *_textes_de_fin(fin)) if isinstance(t, str)).lower()
    if any(signe in lus for signe in SIGNES_CONNEXION):
        return "connexion"
    muet = statut is None and erreur_api in (None, "unknown")  # rien de structuré
    if muet and PREFIXE_API in lus and any(signe in lus for signe in SIGNES_PANNE):
        return "panne"
    return ""


def lire_refus(texte) -> str:
    """La raison d'un refus de l'arbitre du mode auto, ou "" si le texte n'en est pas un.

    Le texte doit commencer par la phrase du refus. La raison est la règle nommée entre
    crochets après « Reason: » ; à défaut, le début du texte.
    """
    if not isinstance(texte, str) or not texte.lstrip().startswith(ARBITRE):
        return ""
    trouve = REGLE_ARBITRE.search(texte)
    if trouve:
        return f"règle {trouve[1].strip()}"
    return " ".join(texte.split())[:120]


def lire_limite(info) -> dict | None:
    """Traduit un `RateLimitInfo` du SDK : statut, limite, heure de remise à zéro, consommation.

    Rend None pour un état sans alerte ni refus (`allowed`) ou illisible. L'heure est en secondes
    Unix ; une valeur qui ne peut être qu'en millisecondes est ramenée en secondes.
    """
    statut = STATUTS_LIMITE.get(getattr(info, "status", None))
    if statut is None:
        return None
    limite = getattr(info, "rate_limit_type", None)
    fin = getattr(info, "resets_at", None)
    if not isinstance(fin, (int, float)) or isinstance(fin, bool) or fin <= 0:
        fin = None
    elif fin > 1e11:  # au-delà de l'an 5000 en secondes : ce sont des millisecondes
        fin = fin / 1000
    part = getattr(info, "utilization", None)
    part = part if isinstance(part, (int, float)) and not isinstance(part, bool) else None
    limite = limite if isinstance(limite, str) and limite else LIMITE_INCONNUE
    return {"statut": statut, "limite": limite, "fin": fin, "utilisation": part}


def depassement_en_service(info) -> bool:
    """Dit si le dépassement payant a pris le relais d'une limite atteinte.

    Claude Code (2.1.308) calcule `isUsingOverage` ainsi : statut `rejected` et dépassement
    `allowed` ou `allowed_warning`. Le SDK donne ce champ dans `raw` et le dépassement dans
    `overage_status` : l'un ou l'autre suffit. Les requêtes passent alors normalement.
    """
    brut = getattr(info, "raw", None)
    if isinstance(brut, dict) and brut.get("isUsingOverage") is True:
        return True
    depassement = getattr(info, "overage_status", None)
    return getattr(info, "status", None) == "rejected" and depassement in DEPASSEMENT_PERMIS


def est_surcharge(texte) -> bool:
    """Dit si le texte d'une erreur « rate_limit » est celui d'une surcharge du serveur, et non
    d'une limite de l'abonnement atteinte."""
    return isinstance(texte, str) and any(signe in texte.lower() for signe in SURCHARGES)


def _bloc_refuse(entree: dict) -> dict:
    """L'outil d'une entrée de `permission_denials` (`tool_name`, `tool_input`), comme un bloc."""
    entree_outil = entree.get("tool_input")
    return {"name": str(entree.get("tool_name") or "Outil"),
            "input": entree_outil if isinstance(entree_outil, dict) else {}}  # fmt: skip


def texte_du_resultat(contenu) -> str:
    """Le texte d'un résultat d'outil : une chaîne, ou une liste de blocs de texte."""
    if isinstance(contenu, str):
        return contenu
    if isinstance(contenu, list):
        return "\n".join(str(b.get("text", "")) for b in contenu if isinstance(b, dict))
    return ""


def raison_d_echec(erreur) -> str:
    """Pourquoi `set_permission_mode` a échoué, en français quand le cas est connu."""
    texte = " ".join(str(erreur).split())
    if "auto mode unavailable" in texte:
        return INDISPONIBLE
    return f"Claude Code n'a pas pris le changement ({texte[:160] or type(erreur).__name__})"


class _Memoire(dict):
    """Un dictionnaire borné : au-delà de MEMOIRE_MAX entrées, les plus anciennes partent."""

    def retenir(self, cle, valeur=None) -> None:
        self[cle] = valeur
        while len(self) > MEMOIRE_MAX:
            del self[next(iter(self))]


def ecrire_refus(regles) -> str | None:
    """Écrit des règles de refus dans un nouveau fichier de réglages Claude Code ; rend son chemin.

    Le fichier, propre à l'appel et lisible par son seul propriétaire, porte `permissions.deny`.
    Rend None s'il n'y a aucune règle (une entrée qui n'est pas une chaîne pleine est écartée).
    Lève OSError si le fichier ne peut pas être écrit : un agent ne part jamais sans ses refus.
    """
    lues = [r for r in regles or [] if isinstance(r, str) and r.strip()]
    if not lues:
        return None
    descripteur, chemin = tempfile.mkstemp(prefix="atelier-refus-", suffix=".json")
    try:
        with os.fdopen(descripteur, "w", encoding="utf-8") as fichier:
            json.dump({"permissions": {"deny": lues}}, fichier, ensure_ascii=False, indent=1)
    except BaseException:  # un fichier à moitié écrit ne doit servir à personne
        with suppress(OSError):
            os.remove(chemin)
        raise
    return chemin


def regle_sdk(regle):
    """Transforme une règle Claude Code, comme `Bash(npm install:*)`, en règle du SDK.

    Rend None si la règle est vide, n'est pas une chaîne ou est mal formée : dans ce cas,
    aucune règle sûre n'existe, et l'outil ne sera permis qu'au cas par cas.
    """
    from claude_agent_sdk.types import PermissionRuleValue  # absent de l'export principal

    trouve = FORME_REGLE.fullmatch(regle.strip()) if isinstance(regle, str) else None
    if trouve is None:
        return None
    return PermissionRuleValue(tool_name=trouve[1], rule_content=trouve[2])


def traduire_reponse(reponse):
    """Traduit la réponse du guichet en décision pour le SDK. Tout doute vaut un refus."""
    from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny, PermissionUpdate

    choix = getattr(reponse, "choix", None)
    if choix == "toujours":
        regles = [regle_sdk(getattr(reponse, "regle", None))]
    elif choix == "chantier":
        lues = getattr(reponse, "regles", ())
        regles = [regle_sdk(r) for r in lues] if isinstance(lues, (list, tuple)) else []
    else:
        regles = []
    if regles and None not in regles:  # une seule règle douteuse, et aucune n'est retenue
        mise_a_jour = PermissionUpdate(
            type="addRules", rules=regles, behavior="allow", destination="session"
        )
        return PermissionResultAllow(updated_permissions=[mise_a_jour])
    if choix in ("une_fois", "toujours", "chantier"):  # sans règle sûre : cette fois seulement
        return PermissionResultAllow()
    if choix == "non":
        message = getattr(reponse, "message", "")
        return PermissionResultDeny(message=message if _texte_plein(message) else REFUS)
    return PermissionResultDeny(message=INCOMPRIS)


def _texte_plein(valeur) -> bool:
    return isinstance(valeur, str) and bool(valeur.strip())


def _dans_un_fil(fonction, *arguments) -> asyncio.Future:
    """Lance une fonction bloquante dans un fil à part et rend un futur qu'on peut attendre.

    Le fil est un démon : un guichet qui ne répond jamais ne retient pas la fin du programme.
    """
    futur: concurrent.futures.Future = concurrent.futures.Future()

    def travailler():
        with suppress(concurrent.futures.InvalidStateError):  # futur annulé entre-temps
            try:
                futur.set_result(fonction(*arguments))
            except Exception as erreur:
                futur.set_exception(erreur)
            except BaseException as erreur:  # même SystemExit : il ne doit pas tuer la boucle
                futur.set_exception(RuntimeError(repr(erreur)))

    threading.Thread(target=travailler, daemon=True, name="atelier-guichet").start()
    return asyncio.wrap_future(futur)


def _oublier(tache: asyncio.Future) -> None:
    """Annule une tâche dont on ne veut plus le résultat, sans laisser d'erreur orpheline."""
    tache.cancel()
    tache.add_done_callback(lambda t: t.cancelled() or t.exception())


class _Arret:
    """Le drapeau d'arrêt d'un tour : lisible depuis tout fil, attendable dans la boucle."""

    def __init__(self, boucle: asyncio.AbstractEventLoop):
        self.boucle, self.pose, self.evenement = boucle, threading.Event(), asyncio.Event()

    def poser(self) -> None:
        self.pose.set()
        with suppress(RuntimeError):  # boucle déjà fermée : il n'y a plus rien à réveiller
            self.boucle.call_soon_threadsafe(self.evenement.set)


DELAI_VIDAGE_S = 0.05  # attente d'un message resté en file, avant d'envoyer une suite
VIDAGE_MAX = 10_000  # messages jetés au plus avant une suite : une borne, jamais atteinte en vrai


class SessionSDK:
    """Une session de l'Agent SDK pour un agent d'Atelier, utilisable depuis n'importe quel fil."""

    delai_interruption_s = 2.0  # temps laissé à `interrupt` avant la déconnexion
    # Attente du message de fin après une interruption (pour porter le coût du tour) ; None :
    # `delai_interruption_s`. Distincte pour que les tests puissent la raccourcir sans raccourcir
    # l'interruption elle-même (voir tests/conftest.py).
    delai_fin_s: float | None = None
    delai_deconnexion_s = 30.0  # borne large : le SDK peut mettre ~20 s à finir un CLI rétif
    delai_mode_s = 10.0  # borne de `set_permission_mode`

    def __init__(
        self,
        agent: str,
        modele: str,
        effort: str,
        dossier: Path | str | None = None,
        outils_permis: list[str] | None = None,
        outils_interdits: list[str] | None = None,
        mode_permission: str = "default",
        role_ajoute: str = "",
        guichet=None,
        sur_evenement=None,
        delai_max_s: float = 3600,
        session: str | None = None,
        reprise: bool = False,
        fabrique_client=None,
        reprise_exigee: bool = False,
        refus_d_office: list[str] | None = None,
        budget_usd: float | None = None,
    ):
        if not mode_valide(mode_permission):  # jamais bypassPermissions, ni un mode inconnu
            raise ValueError(f"Mode de permission refusé : {mode_permission!r}.")
        self.agent, self.modele, self.effort, self.dossier = agent, modele, effort, dossier
        self.outils_permis = list(outils_permis or [])
        self.outils_interdits = list(outils_interdits or [])
        # Les refus d'office, et le fichier de réglages qui les porte une fois écrit. Ceux de
        # tout agent (`interdits()`) s'y ajoutent toujours : une session ouverte sans eux, par
        # un lancement oublié, part quand même avec eux.
        self.refus_d_office = list(dict.fromkeys([*(refus_d_office or []), *interdits()]))
        self._reglages: str | None = None
        self.mode_permission, self.role_ajoute = mode_permission, role_ajoute
        self.guichet, self.sur_evenement, self.delai_max_s = guichet, sur_evenement, delai_max_s
        self.session, self.reprise = session, reprise
        self.fabrique_client = fabrique_client
        # La session qu'il faut reprendre, et non une autre ; vue : elle a répondu.
        self._a_reprendre = session if reprise and reprise_exigee else None
        self._session_vue = False
        # Les limites du tour : la dernière annoncée (alerte ou refus), et le refus.
        self._limite: dict | None = None
        self._limite_refusee = False
        self._surcharge = False  # un signe de surcharge du serveur, pendant le tour
        # Le plafond de dépense de l'agent, passé au SDK (`max_budget_usd`) ; None : aucun.
        self.budget_usd = budget_usd
        # Le coût : la connexion ouvre-t-elle sa session (son premier tour part de zéro) ? Puis
        # pour le tour en cours sa part, son message de fin, une dépense vue (une réponse de
        # l'assistant) et l'erreur de l'API. Les cumuls vivent dans le registre `_CUMULS`.
        self._session_neuve = True
        self._cout_tour, self._fin, self._depense_vue = 0.0, None, False
        self._erreur_api, self._texte_api = None, ""
        # Les outils refusés du tour (formes courtes), et les appels déjà comptés ou écartés.
        self._refuses: list[str] = []
        self._refuses_vus = _Memoire()
        self.source_connexion = ""
        self._client = None
        self._coupure: _Arret | None = None  # le drapeau du client ouvert, posé à sa coupure
        self._deconnexions: set[asyncio.Task] = set()
        self._boucle: asyncio.AbstractEventLoop | None = None
        self._fil: threading.Thread | None = None
        self._arret: _Arret | None = None
        self._occupee = threading.Lock()
        self._fermee = False
        # Le mode : demandé (`mode_permission`), réel (`mode_applique`, "" tant qu'il est inconnu).
        self.mode_applique = ""
        self._verrou_mode = threading.Lock()  # protège `_numero_mode`, la boucle et `_fermee`
        self._numero_mode = 0  # chaque changement reçoit un numéro : seul le plus récent compte
        self._mode_en_cours: str | None = None  # le mode en train d'être demandé au client
        self._verrou_client = asyncio.Lock()  # connexion et changements, l'un après l'autre
        self._changements: set[asyncio.Task] = set()
        self._appels = _Memoire()  # identifiant d'appel d'outil -> sa forme courte
        self._formes = _Memoire()  # identifiant d'appel d'outil -> « Bash(uv sync) »
        self._refus = _Memoire()  # appels déjà annoncés comme refusés, ou passés par le guichet
        self._auto_vu = False  # le mode auto a-t-il valu pendant le tour ?
        # Vrai quand une suite demandée sur cette connexion déjà servie n'a pas pu partir : le
        # programme n'était plus là. L'appelant se replie alors sur la reprise par session.
        self.suite_perdue = False

    # --- Côté fils synchrones -------------------------------------------------------------

    def envoyer(self, consigne: str) -> Resultat:
        """Envoie une consigne à l'agent et attend la fin de son tour. Ne lève jamais."""
        if not self._occupee.acquire(blocking=False):
            return Resultat(ok=False, erreur="Cet agent traite déjà une consigne.")
        try:
            if self._fermee:  # lu sous le verrou, que `fermer` attend avant d'arrêter la boucle
                return Resultat(ok=False, erreur="La session de cet agent est fermée.")
            resultat = self._executer(consigne)
        finally:
            self._occupee.release()
        self._annuler_au_guichet()  # un tour terminé ne garde aucune demande ouverte
        self._emettre("fin", "L'agent a terminé." if resultat.ok else resultat.erreur)
        return resultat

    def arreter(self) -> None:
        """Interrompt l'agent en cours. Sans effet s'il n'y a rien en cours."""
        arret = self._arret
        if arret is not None:
            arret.poser()
        self._annuler_au_guichet()

    def fermer(self) -> None:
        """Arrête l'agent s'il travaille, se déconnecte du SDK et libère le fil de la session."""
        with self._verrou_mode:
            if self._fermee:
                return
            self._fermee = True
        self.arreter()
        if self._fil is not None and threading.current_thread() is self._fil:
            # Appelé depuis un rappel, dans la boucle : on n'y attend pas la fin du tour.
            threading.Thread(target=self._liberer, daemon=True).start()
        else:
            self._liberer()

    def changer_mode(self, mode) -> bool:
        """Change le mode de permission de l'agent, depuis n'importe quel fil. Ne lève jamais.

        Rend True si un tour est en cours et que le changement lui est confié : la boucle de la
        session l'applique aussitôt (`set_permission_mode`, avec un délai borné), sans bloquer
        l'appelant. Rend False pour un mode refusé, une session qui s'arrête ou se ferme, et une
        session sans tour en cours ; dans ce dernier cas, le mode vaudra pour la connexion
        suivante, ou est appliqué au client resté ouvert entre deux tours.
        """
        if not mode_valide(mode):
            return False
        with self._verrou_mode:
            arret = self._arret
            if self._fermee or (arret is not None and arret.pose.is_set()):
                return False
            self._numero_mode += 1
            boucle = self._boucle
            if boucle is None:  # rien n'est encore lancé : la connexion prendra ce mode
                self.mode_permission = mode
                return False
            changement = self._changer(mode, self._numero_mode)
            try:
                asyncio.run_coroutine_threadsafe(changement, boucle)
            except RuntimeError:  # boucle déjà fermée
                changement.close()
                return False
        return arret is not None

    def _liberer(self) -> None:
        """Attend la fin du tour en cours et des déconnexions, puis arrête la boucle.

        Le verrou est attendu avant de regarder la boucle : un `envoyer` entré juste avant
        `fermer` a pu la créer entre-temps. Si le tour ne rend pas la main (un rappel bloque la
        boucle), on n'attend pas plus.
        """
        libre = self._occupee.acquire(timeout=self.delai_deconnexion_s)
        if libre:
            self._occupee.release()
        boucle = self._boucle
        if boucle is None:
            return
        sortis = False  # tous les Claude Code de la session sont-ils sortis ?
        if libre:
            with suppress(Exception):
                asyncio.run_coroutine_threadsafe(self._tout_deconnecter(), boucle).result(
                    timeout=self.delai_deconnexion_s + 5
                )
                sortis = not self._deconnexions
        boucle.call_soon_threadsafe(boucle.stop)
        self._fil.join(timeout=self.delai_deconnexion_s)
        if not boucle.is_running():
            boucle.close()
        if sortis:  # un Claude Code encore en vie pourrait relire ses réglages : on les laisse
            self._effacer_reglages()

    def _effacer_reglages(self) -> None:
        chemin, self._reglages = self._reglages, None
        if chemin:
            with suppress(OSError):
                os.remove(chemin)

    def _executer(self, consigne: str) -> Resultat:
        """Confie le tour à la boucle de la session et l'attend, avec un garde-fou."""
        boucle = self._demarrer_boucle()
        self._arret = arret = _Arret(boucle)
        if self._fermee:  # `fermer` est passé juste avant que le drapeau soit posé
            arret.poser()
        try:
            futur = asyncio.run_coroutine_threadsafe(self._tour(consigne, arret), boucle)
            return futur.result(timeout=self.delai_max_s + MARGE_S)
        except concurrent.futures.TimeoutError:
            futur.cancel()
            return Resultat(ok=False, erreur="La session de l'agent ne répond plus.")
        except Exception as erreur:
            return Resultat(ok=False, erreur=f"Le SDK de Claude a échoué : {erreur}")
        finally:
            self._arret = None

    def _demarrer_boucle(self) -> asyncio.AbstractEventLoop:
        with self._verrou_mode:  # `changer_mode` voit la boucle, ou la session sans boucle
            if self._boucle is None:
                self._boucle = asyncio.new_event_loop()
                self._fil = threading.Thread(
                    target=self._boucle.run_forever, daemon=True, name=f"atelier-sdk-{self.agent}"
                )
                self._fil.start()
            return self._boucle

    def _emettre(self, type_: str, contenu: str, **en_plus) -> None:
        """Relaie un événement en direct ; une erreur du rappel ne touche pas la session."""
        if self.sur_evenement is None:
            return
        with suppress(Exception):
            self.sur_evenement({"agent": self.agent, "type": type_, "contenu": contenu, **en_plus})

    def _annuler_au_guichet(self) -> None:
        if self.guichet is not None:
            with suppress(Exception):
                self.guichet.annuler(self.agent)

    # --- Côté boucle asynchrone -----------------------------------------------------------

    async def _tour(self, consigne: str, arret: _Arret) -> Resultat:
        """Fait travailler l'agent jusqu'à sa réponse, son arrêt ou la fin du délai.

        Quelle qu'en soit l'issue, le résultat porte les outils refusés pendant le tour.
        """
        self._limite, self._limite_refusee, self._surcharge = None, False, False
        self._refuses, self._refuses_vus = [], _Memoire()
        resultat = await self._derouler(consigne, arret)
        resultat.refuses = list(self._refuses)
        return resultat

    async def _derouler(self, consigne: str, arret: _Arret) -> Resultat:
        """Le tour : son résultat porte ce qu'il a coûté (`cout_du_tour`) et, en échec, sa
        nature. Un arrêt arrivé avant le départ ne lance rien : il n'a rien coûté."""
        self._cout_tour, self._fin, self._depense_vue = 0.0, None, False
        self._erreur_api, self._texte_api = None, ""
        if arret.pose.is_set():
            return Resultat(ok=False, erreur=ARRETE, nature="arret")
        travail = asyncio.ensure_future(self._travailler(consigne))
        attente = asyncio.ensure_future(arret.evenement.wait())
        try:
            await asyncio.wait(
                {travail, attente}, timeout=self.delai_max_s, return_when=asyncio.FIRST_COMPLETED
            )
        finally:
            attente.cancel()
        if arret.pose.is_set() or not travail.done():
            return await self._interrompre(travail, arret)
        exception = None if travail.cancelled() else travail.exception()
        return self._chiffrer(self._qualifier(self._issue(travail), exception))

    async def _interrompre(self, travail: asyncio.Future, arret: _Arret) -> Resultat:
        """Un arrêt ou un délai dépassé : Claude Code est interrompu, et son message de fin
        attendu au plus `delai_interruption_s` (ou `delai_fin_s` s'il est réglé), pour porter le
        coût du tour. Sans lui, la main est rendue quand même, `cout_incomplet` posé. Le client
        est ensuite coupé ; son interruption, bornée par `delai_interruption_s`, finit à part.

        Pendant l'attente, une demande nouvelle de ce client est refusée sans le guichet ; une
        demande déjà au guichet y reste, et le tour fini la ferme comme d'habitude.
        """
        client, self._client = self._client, None
        coupure, self._coupure = self._coupure, None
        if coupure is not None:
            coupure.pose.set()  # le drapeau seul : les demandes en attente ne sont pas réveillées
        interruption = None
        if client is not None and not travail.done():
            interruption = asyncio.ensure_future(
                asyncio.wait_for(client.interrupt(), self.delai_interruption_s)
            )
            attente = self.delai_interruption_s if self.delai_fin_s is None else self.delai_fin_s
            await asyncio.wait({travail}, timeout=attente)
        resultat = self._resultat_interrompu(travail, arret)
        if not travail.done():
            _oublier(travail)
        if coupure is not None:
            coupure.poser()
        if client is not None:
            tache = asyncio.ensure_future(self._deconnecter(client, interruption))
            self._deconnexions.add(tache)
            tache.add_done_callback(self._deconnexions.discard)
        return resultat

    def _resultat_interrompu(self, travail: asyncio.Future, arret: _Arret) -> Resultat:
        """L'arrêt ou le délai dépassé, avec le coût du tour et ses tokens s'ils sont connus."""
        if arret.pose.is_set():
            erreur, nature = ARRETE, "arret"
        else:
            delai = f"{self.delai_max_s} secondes"
            erreur, nature = f"L'agent n'a pas fini dans le délai de {delai}.", "delai"
        fini = travail.done() and not travail.cancelled() and travail.exception() is None
        tokens = travail.result().tokens if fini and self._fin is not None else 0
        return Resultat(ok=False, erreur=erreur, nature=nature, cout_usd=self._cout_tour,
                        tokens=tokens, cout_incomplet=self._fin is None)  # fmt: skip

    def _chiffrer(self, resultat: Resultat) -> Resultat:
        """Le coût d'un tour allé à son terme : sa part du cumul annoncé. Sans message
        de fin après une réponse de l'assistant (une dépense), le coût est incomplet."""
        resultat.cout_usd = self._cout_tour
        resultat.cout_incomplet = self._fin is None and self._depense_vue
        return resultat

    def _qualifier(self, resultat: Resultat, exception: BaseException | None = None) -> Resultat:
        """Un échec dû à une limite, à une surcharge, ou à une session qu'on n'a pas pu
        reprendre, le dit. La limite passe avant la surcharge. Tout échec reçoit sa nature
        (`lire_nature` pour la connexion, le budget et la panne) ; une connexion perdue reste
        « connexion » même quand la session exigée n'a pas répondu."""
        if resultat.ok:
            return resultat
        reste = {"cout_usd": resultat.cout_usd, "tokens": resultat.tokens}
        if self._limite_refusee:
            limite = self._limite or {"limite": LIMITE_INCONNUE, "fin": None}
            return Resultat(ok=False, erreur=LIMITE_ATTEINTE, type_limite=limite["limite"],
                            fin_limite=limite["fin"], nature="limite", **reste)  # fmt: skip
        if self._surcharge:
            return Resultat(ok=False, erreur=SURCHARGE, nature="surcharge", **reste)
        source = self._fin if self._fin is not None else exception
        nature = lire_nature(source, self._erreur_api, resultat.erreur, self._texte_api)
        if self._a_reprendre and not self._session_vue:
            nature = nature if nature == "connexion" else "reprise"
            return Resultat(ok=False, erreur=REPRISE_IMPOSSIBLE, nature=nature, **reste)
        resultat.nature = nature
        return resultat

    def _issue(self, travail: asyncio.Future) -> Resultat:
        """Lit l'issue d'un travail terminé ; en cas d'erreur, le client est coupé."""
        if travail.cancelled():  # le client a levé CancelledError de lui-même
            self._couper()
            return Resultat(ok=False, erreur=INTERROMPU)
        erreur = travail.exception()
        if erreur is not None:
            self._couper()
            return Resultat(ok=False, erreur=f"Le SDK de Claude a échoué : {erreur}")
        return travail.result()

    async def _travailler(self, consigne: str) -> Resultat:
        if self._client is None:
            await self._attendre_deconnexions()  # l'ancien Claude Code doit être sorti
            async with self._verrou_client:  # un changement de mode attend la connexion
                self._client = self._fabriquer()
                await self._client.connect()
            self._auto_vu = (self.mode_applique or self.mode_permission) == "auto"
            await self._client.query(consigne)
        else:  # une suite, sur la connexion gardée ouverte depuis le tour d'avant
            self._auto_vu = (self.mode_applique or self.mode_permission) == "auto"
            await self._envoyer_la_suite(consigne)
        morceaux: list[str] = []
        final = None
        async for message in self._client.receive_response():
            final = self._suivre(message, morceaux) or final
        return lire_resultat(final, morceaux)

    async def _envoyer_la_suite(self, consigne: str) -> None:
        """Envoie une suite à un Claude Code resté connecté depuis le tour d'avant.

        Deux choses ont pu arriver pendant qu'il attendait, que le SDK ne dit qu'à la lecture ou
        à l'écriture suivante. Il a pu jouer un tour de lui-même (une tâche de fond qui finit le
        réveille) : ces messages sont jetés d'abord, sinon la réponse lue serait celle de ce
        tour, et toutes les suivantes seraient décalées d'un cran. Il a pu mourir : la suite ne
        peut alors pas partir, `suite_perdue` le dit, et l'erreur remonte.

        Limite connue : un tour de fond encore en cours au moment de l'envoi n'est pas vu.
        """
        try:
            await self._vider()
            await self._client.query(consigne)
        except BaseException:
            self.suite_perdue = True
            raise

    async def _vider(self) -> None:
        """Jette ce que Claude Code a émis depuis le dernier tour lu. Un client sans lecture
        continue (`receive_messages`) n'a pas de file : rien à vider. Une fin de flux veut dire
        que le programme est sorti."""
        lire = getattr(self._client, "receive_messages", None)
        if lire is None:
            return
        flux = lire().__aiter__()
        try:
            for _ in range(VIDAGE_MAX):
                try:
                    await asyncio.wait_for(flux.__anext__(), DELAI_VIDAGE_S)
                except asyncio.TimeoutError:
                    return  # plus rien en attente
                except StopAsyncIteration:
                    raise RuntimeError("Claude Code est sorti pendant l'attente.") from None
        finally:
            with suppress(Exception):
                await flux.aclose()

    def _fabriquer(self):
        """Crée le client SDK. C'est ici, et seulement ici, qu'on charge la bibliothèque."""
        from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient

        coupure = self._coupure = _Arret(self._boucle)
        # Claude Code compte le coût depuis le début de la session : une connexion qui en ouvre
        # une part de zéro ; une connexion qui la reprend repart du total gardé, donc du dernier
        # cumul vu pour elle dans le registre du processus (`cout_de_session`).
        self._session_neuve = not self.reprise
        # Le plafond de dépense, seulement s'il y en a un : sinon le SDK garde son défaut.
        plafond = {"max_budget_usd": self.budget_usd} if plafond_valide(self.budget_usd) else {}

        async def autoriser(outil, entree, contexte=None):
            return await self._autoriser(outil, entree, contexte, coupure)

        prompt = {"type": "preset", "preset": "claude_code"}
        if self.role_ajoute:
            prompt["append"] = self.role_ajoute
        if self._reglages is None and self.refus_d_office:
            try:
                self._reglages = ecrire_refus(self.refus_d_office)
            except OSError as erreur:  # sans ses refus, l'agent ne part pas
                ecrits = "les refus d'office n'ont pas pu être écrits"
                raise RuntimeError(f"{ecrits} ({erreur})") from None
        options = ClaudeAgentOptions(
            model=self.modele,
            effort=self.effort,
            cwd=self.dossier,
            allowed_tools=self.outils_permis,
            disallowed_tools=self.outils_interdits,
            permission_mode=self.mode_permission,
            can_use_tool=autoriser,
            include_partial_messages=True,
            system_prompt=prompt,
            session_id=None if self.reprise else self.session,
            resume=self.session if self.reprise else None,
            settings=self._reglages,  # les refus d'office, en `permissions.deny`
            **plafond,
        )
        return (self.fabrique_client or ClaudeSDKClient)(options)

    def _suivre(self, message, morceaux: list[str]):
        """Relaie un message du SDK ; rend le message de fin s'il en est un."""
        import claude_agent_sdk as sdk

        if isinstance(message, sdk.StreamEvent):
            delta = (message.event or {}).get("delta") or {}
            if delta.get("type") == "text_delta" and delta.get("text"):
                morceaux.append(delta["text"])
                self._emettre("texte", delta["text"])
        elif isinstance(message, sdk.AssistantMessage):
            self._suivre_assistant(message)
        elif isinstance(message, sdk.UserMessage) and isinstance(message.content, list):
            resultats = [b for b in message.content if isinstance(b, sdk.ToolResultBlock)]
            for bloc in resultats:
                self._lire_refus(bloc)
        elif isinstance(message, sdk.SystemMessage):
            self._suivre_systeme(message)
        elif isinstance(message, sdk.RateLimitEvent):
            self._suivre_limite(message.rate_limit_info)
        elif isinstance(message, sdk.ResultMessage):
            self._suivre_fin(message)
            return message
        return None

    def _suivre_fin(self, message) -> None:
        """Le message de fin : la session, les refus du tour, et le signe d'une limite atteinte
        (statut HTTP 429) ou d'une surcharge (son texte) dans un tour en échec. Le coût du tour
        est sa part du cumul annoncé, en erreur comme en succès (`_noter_cout`)."""
        self._noter_cout(message)
        self._retenir_session(message.session_id)
        self._refus_du_tour(message.permission_denials)
        self._refuses_du_tour(message.permission_denials)
        if not message.is_error:
            return
        if est_surcharge(message.result):
            self._surcharge = True
        elif getattr(message, "api_error_status", None) == STATUT_HTTP_LIMITE:
            self._limite_refusee = True

    def _noter_cout(self, message) -> None:
        """Retient le message de fin du tour et ce que le tour a coûté : la différence entre le
        cumul annoncé (`total_cost_usd`, compté par Claude Code depuis le début de la session) et
        le plus haut cumul vu avant pour la session, dans ce pont ou un autre (`cout_de_session`).
        Un cumul plus bas (remis à zéro dans un résultat d'erreur au démarrage ou après un
        plantage) compte 0 et ne baisse pas la référence."""
        self._fin = message
        cle = getattr(message, "session_id", None) or self.session or f"pont-{id(self)}"
        cumul = getattr(message, "total_cost_usd", None)
        self._cout_tour = cout_de_session(cle, cumul, neuve=self._session_neuve)
        self._session_neuve = False

    def _suivre_assistant(self, message) -> None:
        """Annonce les outils appelés ; une réponse en erreur « rate_limit » est un refus pour
        limite, ou une surcharge si son texte le dit. Toute réponse en erreur retient son champ
        `error` et son texte, pour la nature de l'échec ; une autre réponse est une dépense."""
        import claude_agent_sdk as sdk

        erreur = getattr(message, "error", None)
        if not erreur:
            self._depense_vue = True
        else:
            lu = " ".join(b.text for b in message.content if isinstance(b, sdk.TextBlock))
            self._erreur_api, self._texte_api = erreur, lu
            if erreur == "rate_limit" and est_surcharge(lu):
                self._surcharge = True
            elif erreur == "rate_limit":
                self._limite_refusee = True
        for bloc in message.content:
            if isinstance(bloc, sdk.ToolUseBlock):
                appel = {"name": bloc.name, "input": bloc.input}
                forme = decrire_outil(appel, self.dossier)
                self._appels.retenir(bloc.id, forme)
                self._formes.retenir(bloc.id, forme_courte(appel, self.dossier))
                self._emettre("outil", forme)

    def _suivre_limite(self, info) -> None:
        """Retient et annonce une alerte ou un refus de limite ; rien ne s'arrête ici.

        Quand le dépassement payant a pris le relais, le `rejected` n'est pas un refus : rien
        n'est annoncé, et un refus vu plus tôt dans le tour ne compte plus.
        """
        if depassement_en_service(info):
            self._limite_refusee = False
            return
        limite = lire_limite(info)
        if limite is None:
            return
        self._limite = limite
        self._limite_refusee = self._limite_refusee or limite["statut"] == "atteinte"
        texte = decrire_limite(limite["statut"], limite["limite"], limite["fin"],
                               limite["utilisation"])  # fmt: skip
        self._emettre("limite", texte, **limite)

    def _suivre_systeme(self, message) -> None:
        """Le départ (`init`) donne la source, la session et le mode ; `status`, un nouveau mode."""
        donnees = message.data if isinstance(message.data, dict) else {}
        if message.subtype == "init":
            self.source_connexion = lire_source(donnees.get("apiKeySource"))
            self._verifier_reprise(donnees.get("session_id"))
            self._retenir_session(donnees.get("session_id"))
        mode = donnees.get("permissionMode")
        if message.subtype in ("init", "status") and isinstance(mode, str) and mode:
            self._noter_mode_reel(mode, depart=message.subtype == "init")

    def _noter_mode_reel(self, reel: str, depart: bool) -> None:
        """Tient `mode_applique` à jour ; dit le mode réel s'il n'est pas celui demandé, ou
        s'il change sans qu'on l'ait demandé."""
        avant, self.mode_applique = self.mode_applique, reel
        self._auto_vu = reel == "auto" or (self._auto_vu and not depart)
        if reel == avant or reel == self._mode_en_cours:
            return
        if not avant and reel == self.mode_permission:
            return  # le départ dans le mode demandé : rien à dire
        raison = ""
        if depart and self.mode_permission == "auto" and reel == "default":
            raison = INDISPONIBLE
        elif avant == "plan":
            raison = "il a fini sa répétition et passe à l'exécution de son plan"
        self._emettre("mode", reel, demande=self.mode_permission, raison=raison)

    def _lire_refus(self, bloc) -> None:
        """Annonce aussitôt un résultat d'outil qui est un refus de l'arbitre du mode auto.

        Seulement si le mode auto a valu pendant le tour : sans arbitre, il n'y a pas de refus.
        """
        refus = bloc.is_error and self._auto_vu
        raison = lire_refus(texte_du_resultat(bloc.content)) if refus else ""
        if raison:
            self._annoncer_refus(bloc.tool_use_id, self._appels.get(bloc.tool_use_id, ""), raison)
            if self._formes.get(bloc.tool_use_id):  # sinon, `permission_denials` le dira
                self._noter_refuse(bloc.tool_use_id, self._formes[bloc.tool_use_id])

    def _refus_du_tour(self, refus) -> None:
        """En fin de tour, annonce les refus de `permission_denials` qui ne l'ont pas été.

        Seulement si le mode auto a valu pendant le tour : sinon ces refus viennent du guichet
        ou des règles, pas de l'arbitre. Un refus sans identifiant n'est pas annoncé : rien ne
        dirait qu'il ne l'a pas déjà été.
        """
        if not self._auto_vu or not isinstance(refus, list):
            return
        for entree in refus[:MEMOIRE_MAX]:
            if isinstance(entree, dict) and entree.get("tool_use_id"):
                bloc = _bloc_refuse(entree)
                self._annoncer_refus(entree["tool_use_id"], decrire_outil(bloc), SANS_RAISON)

    def _refuses_du_tour(self, refus) -> None:
        """En fin de tour, retient les outils de `permission_denials`, quel que soit le mode.

        Claude Code y range chaque outil refusé pendant le tour, par une règle, le mode, l'arbitre
        ou le guichet ; ceux déjà comptés (par leur identifiant) ne le sont pas deux fois.
        """
        if not isinstance(refus, list):
            return
        for entree in refus[:MEMOIRE_MAX]:
            if isinstance(entree, dict):
                identifiant = entree.get("tool_use_id")
                identifiant = identifiant if isinstance(identifiant, str) else None
                self._noter_refuse(identifiant, forme_courte(_bloc_refuse(entree), self.dossier))

    def _noter_refuse(self, identifiant, forme: str) -> None:
        """Retient un outil refusé pendant le tour : sa forme courte, une fois, REFUSES_MAX au plus.

        Un appel déjà compté ne l'est pas deux fois (refusé au guichet, il revient dans
        `permission_denials`). Une forme vide note seulement l'appel, qui ne comptera plus.
        """
        if identifiant:
            if identifiant in self._refuses_vus:
                return
            self._refuses_vus.retenir(identifiant)
        if forme and forme not in self._refuses and len(self._refuses) < REFUSES_MAX:
            self._refuses.append(forme)

    def _annoncer_refus(self, identifiant, forme: str, raison: str) -> None:
        if not identifiant or identifiant in self._refus:
            return
        self._refus.retenir(identifiant)
        self._emettre("refus", f"{forme or 'Un outil'} ({raison})", outil=forme, raison=raison)

    def _verifier_reprise(self, identifiant) -> None:
        """Avec une reprise exigée, la session annoncée au départ doit être celle demandée."""
        if not self._a_reprendre or not identifiant or self._session_vue:
            return
        if identifiant != self._a_reprendre:
            raise _RepriseRefusee(f"Claude Code est parti dans la session {identifiant}.")
        self._session_vue = True

    def _retenir_session(self, identifiant) -> None:
        """Garde l'identifiant de session : après une coupure, on reprendra cette session."""
        if identifiant:
            self.session, self.reprise = identifiant, True

    async def _autoriser(self, outil: str, entree: dict, contexte, coupure: _Arret):
        """Rappel `can_use_tool` du SDK : la décision de `_decider`, et l'outil refusé retenu.

        Un refus pour arrêt (ARRETE) n'est pas un outil refusé : l'appel est seulement noté,
        pour que `permission_denials` ne le compte pas non plus.
        """
        decision = await self._decider(outil, entree, contexte, coupure)
        if getattr(decision, "behavior", None) == "deny":
            pour_arret = getattr(decision, "message", "") == ARRETE
            appel = {"name": outil, "input": entree}
            forme = "" if pour_arret else forme_courte(appel, self.dossier)
            self._noter_refuse(getattr(contexte, "tool_use_id", None), forme)
        return decision

    async def _decider(self, outil: str, entree: dict, contexte, coupure: _Arret):
        """Pose la question au guichet, sans bloquer la boucle, et rend la décision du SDK.

        Hors d'un tour, après un arrêt, ou venue d'un client déjà coupé, la demande est refusée
        sans déranger le guichet. Un arrêt ou une coupure pendant l'attente refuse aussitôt,
        sans attendre la réponse du guichet.
        """
        from claude_agent_sdk import PermissionResultDeny

        # Une demande passée par ici n'est jamais un refus de l'arbitre, même refusée ensuite.
        self._refus.retenir(getattr(contexte, "tool_use_id", None) or id(contexte))
        if coupure.pose.is_set():  # l'ancien Claude Code, en train de s'interrompre
            return PermissionResultDeny(message=ARRETE, interrupt=True)
        arret = self._arret
        self._emettre("attente", decrire_outil({"name": outil, "input": entree}, self.dossier))
        if self.guichet is None:
            return PermissionResultDeny(message=SANS_GUICHET)
        if arret is None or arret.pose.is_set():
            return PermissionResultDeny(message=ARRETE, interrupt=True)
        demande = _dans_un_fil(self.guichet.demander, self.agent, outil, entree)
        veilles = {asyncio.ensure_future(a.evenement.wait()) for a in (arret, coupure)}
        try:
            await asyncio.wait({demande, *veilles}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for veille in veilles:
                veille.cancel()
            if not demande.done():
                demande.cancel()
        if arret.pose.is_set() or coupure.pose.is_set() or demande.cancelled():
            threading.Thread(target=self._annuler_au_guichet, daemon=True).start()
            return PermissionResultDeny(message=ARRETE, interrupt=True)
        if demande.exception() is not None:
            return PermissionResultDeny(
                message=f"Le guichet n'a pas pu répondre : {demande.exception()}"
            )
        return traduire_reponse(demande.result())

    def _couper(self) -> None:
        """Retire le client et le déconnecte à part ; le prochain envoi rouvrira la session."""
        client, self._client = self._client, None
        coupure, self._coupure = self._coupure, None
        if coupure is not None:
            coupure.poser()
        if client is not None:
            tache = asyncio.ensure_future(self._deconnecter(client))
            self._deconnexions.add(tache)
            tache.add_done_callback(self._deconnexions.discard)

    async def _deconnecter(self, client, interruption: asyncio.Future | None = None) -> None:
        """Interrompt le client (au plus `delai_interruption_s`), puis le déconnecte.

        Déjà interrompu (`interruption`, la tâche lancée par `_interrompre`), il ne l'est pas
        une seconde fois : on attend seulement la fin de cette interruption, bornée elle aussi.
        """
        if interruption is None:
            with suppress(Exception):
                await asyncio.wait_for(client.interrupt(), self.delai_interruption_s)
        else:
            await asyncio.wait({interruption})
            if not interruption.cancelled():
                interruption.exception()  # lue : une interruption ratée ne fait pas de bruit
        with suppress(Exception):
            await client.disconnect()  # jamais annulé ni borné ici : voir l'en-tête du module

    async def _attendre_deconnexions(self) -> None:
        """Attend, sans les annuler, la fin des déconnexions en cours (borne large)."""
        if self._deconnexions:
            await asyncio.wait(set(self._deconnexions), timeout=self.delai_deconnexion_s)

    async def _tout_deconnecter(self) -> None:
        for changement in list(self._changements):
            changement.cancel()
        self._couper()
        await self._attendre_deconnexions()

    async def _changer(self, mode: str, numero: int) -> None:
        """Applique un changement de mode dans la boucle ; un changement plus récent l'emporte.

        Sans client connecté, le mode vaudra pour la prochaine connexion. Si Claude Code refuse
        (mode auto indisponible, délai dépassé), le mode demandé reste celui d'avant et un
        événement « mode » dit le mode réel.
        """
        tache = asyncio.current_task()
        self._changements.add(tache)
        try:
            async with self._verrou_client:
                if numero == self._numero_mode:
                    await self._appliquer_mode(mode)
        finally:
            self._changements.discard(tache)

    async def _appliquer_mode(self, mode: str) -> None:
        client = self._client
        if client is None:
            self.mode_permission = mode
            return
        if mode == self.mode_permission == self.mode_applique:
            return
        self._mode_en_cours = mode
        try:
            await asyncio.wait_for(client.set_permission_mode(mode), self.delai_mode_s)
        except Exception as erreur:
            reel = self.mode_applique or self.mode_permission
            self._emettre("mode", reel, demande=mode, raison=raison_d_echec(erreur))
            return
        finally:
            self._mode_en_cours = None
        self.mode_permission = self.mode_applique = mode
        self._auto_vu = self._auto_vu or mode == "auto"
