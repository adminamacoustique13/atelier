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
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import re
import threading
import warnings
from contextlib import suppress
from pathlib import Path

from atelier.agents import Resultat, decrire_outil, mode_valide

# Le SDK avertit, à chaque agent, que le guichet n'est pas consulté pour les outils permis
# d'avance (lecture, modifications dans la copie de travail). C'est voulu (voir DECISIONS.md,
# « les modifications de fichiers restent permises d'avance ») : l'avertissement ne ferait
# qu'encombrer le journal de l'Atelier.
warnings.filterwarnings("ignore", message="can_use_tool will not be invoked")

ARRET = "Arrêté par la personne responsable."
SANS_REPONSE = "Claude Code s'est arrêté sans répondre."
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


def lire_source(api_key_source) -> str:
    """Traduit le champ `apiKeySource` du SDK : « abonnement », « clé API », ou rien."""
    if not api_key_source:
        return ""
    return "abonnement" if api_key_source == "none" else "clé API"


def lire_resultat(final, morceaux: list[str]) -> Resultat:
    """Traduit le message de fin du SDK en résultat : texte, coût et tokens, ou échec."""
    if final is None:
        return Resultat(ok=False, erreur=SANS_REPONSE)
    usage = getattr(final, "usage", None) or {}
    tokens = int(usage.get("input_tokens") or 0) + int(usage.get("output_tokens") or 0)
    texte = str(getattr(final, "result", None) or "")
    if getattr(final, "is_error", False):
        return Resultat(ok=False, erreur=texte or "Erreur signalée par Claude Code.", tokens=tokens)
    cout = float(getattr(final, "total_cost_usd", None) or 0)
    return Resultat(ok=True, texte=texte or "".join(morceaux), cout_usd=cout, tokens=tokens)


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
    regle = regle_sdk(getattr(reponse, "regle", None)) if choix == "toujours" else None
    if regle is not None:
        mise_a_jour = PermissionUpdate(
            type="addRules", rules=[regle], behavior="allow", destination="session"
        )
        return PermissionResultAllow(updated_permissions=[mise_a_jour])
    if choix in ("une_fois", "toujours"):  # « toujours » sans règle sûre : cette fois seulement
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


class SessionSDK:
    """Une session de l'Agent SDK pour un agent d'Atelier, utilisable depuis n'importe quel fil."""

    delai_interruption_s = 2.0  # temps laissé à `interrupt` avant la déconnexion
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
    ):
        if not mode_valide(mode_permission):  # jamais bypassPermissions, ni un mode inconnu
            raise ValueError(f"Mode de permission refusé : {mode_permission!r}.")
        self.agent, self.modele, self.effort, self.dossier = agent, modele, effort, dossier
        self.outils_permis = list(outils_permis or [])
        self.outils_interdits = list(outils_interdits or [])
        self.mode_permission, self.role_ajoute = mode_permission, role_ajoute
        self.guichet, self.sur_evenement, self.delai_max_s = guichet, sur_evenement, delai_max_s
        self.session, self.reprise = session, reprise
        self.fabrique_client = fabrique_client
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
        self._refus = _Memoire()  # appels déjà annoncés comme refusés, ou passés par le guichet
        self._auto_vu = False  # le mode auto a-t-il valu pendant le tour ?

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
        if libre:
            with suppress(Exception):
                asyncio.run_coroutine_threadsafe(self._tout_deconnecter(), boucle).result(
                    timeout=self.delai_deconnexion_s + 5
                )
        boucle.call_soon_threadsafe(boucle.stop)
        self._fil.join(timeout=self.delai_deconnexion_s)
        if not boucle.is_running():
            boucle.close()

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
        """Fait travailler l'agent jusqu'à sa réponse, son arrêt ou la fin du délai."""
        travail = asyncio.ensure_future(self._travailler(consigne))
        attente = asyncio.ensure_future(arret.evenement.wait())
        try:
            await asyncio.wait(
                {travail, attente}, timeout=self.delai_max_s, return_when=asyncio.FIRST_COMPLETED
            )
        finally:
            attente.cancel()
        if arret.pose.is_set() or not travail.done():
            _oublier(travail)
            self._couper()
            if arret.pose.is_set():
                return Resultat(ok=False, erreur=ARRET)
            delai = f"{self.delai_max_s} secondes"
            return Resultat(ok=False, erreur=f"L'agent n'a pas fini dans le délai de {delai}.")
        return self._issue(travail)

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
        morceaux: list[str] = []
        final = None
        async for message in self._client.receive_response():
            final = self._suivre(message, morceaux) or final
        return lire_resultat(final, morceaux)

    def _fabriquer(self):
        """Crée le client SDK. C'est ici, et seulement ici, qu'on charge la bibliothèque."""
        from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient

        coupure = self._coupure = _Arret(self._boucle)

        async def autoriser(outil, entree, contexte=None):
            return await self._autoriser(outil, entree, contexte, coupure)

        prompt = {"type": "preset", "preset": "claude_code"}
        if self.role_ajoute:
            prompt["append"] = self.role_ajoute
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
            for bloc in message.content:
                if isinstance(bloc, sdk.ToolUseBlock):
                    forme = decrire_outil({"name": bloc.name, "input": bloc.input}, self.dossier)
                    self._appels.retenir(bloc.id, forme)
                    self._emettre("outil", forme)
        elif isinstance(message, sdk.UserMessage) and isinstance(message.content, list):
            resultats = [b for b in message.content if isinstance(b, sdk.ToolResultBlock)]
            for bloc in resultats:
                self._lire_refus(bloc)
        elif isinstance(message, sdk.SystemMessage):
            self._suivre_systeme(message)
        elif isinstance(message, sdk.ResultMessage):
            self._retenir_session(message.session_id)
            self._refus_du_tour(message.permission_denials)
            return message
        return None

    def _suivre_systeme(self, message) -> None:
        """Le départ (`init`) donne la source, la session et le mode ; `status`, un nouveau mode."""
        donnees = message.data if isinstance(message.data, dict) else {}
        if message.subtype == "init":
            self.source_connexion = lire_source(donnees.get("apiKeySource"))
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
                entree_outil = entree.get("tool_input")
                bloc = {"name": str(entree.get("tool_name") or "Outil"),
                        "input": entree_outil if isinstance(entree_outil, dict) else {}}
                self._annoncer_refus(entree["tool_use_id"], decrire_outil(bloc), SANS_RAISON)

    def _annoncer_refus(self, identifiant, forme: str, raison: str) -> None:
        if not identifiant or identifiant in self._refus:
            return
        self._refus.retenir(identifiant)
        self._emettre("refus", f"{forme or 'Un outil'} ({raison})", outil=forme, raison=raison)

    def _retenir_session(self, identifiant) -> None:
        """Garde l'identifiant de session : après une coupure, on reprendra cette session."""
        if identifiant:
            self.session, self.reprise = identifiant, True

    async def _autoriser(self, outil: str, entree: dict, contexte, coupure: _Arret):
        """Rappel `can_use_tool` du SDK : pose la question au guichet, sans bloquer la boucle.

        Hors d'un tour, après un arrêt, ou venue d'un client déjà coupé, la demande est refusée
        sans déranger le guichet. Un arrêt ou une coupure pendant l'attente refuse aussitôt,
        sans attendre la réponse du guichet.
        """
        from claude_agent_sdk import PermissionResultDeny

        # Une demande passée par ici n'est jamais un refus de l'arbitre, même refusée ensuite.
        self._refus.retenir(getattr(contexte, "tool_use_id", None) or id(contexte))
        if coupure.pose.is_set():  # l'ancien Claude Code, en train de s'interrompre
            return PermissionResultDeny(message=ARRET, interrupt=True)
        arret = self._arret
        self._emettre("attente", decrire_outil({"name": outil, "input": entree}, self.dossier))
        if self.guichet is None:
            return PermissionResultDeny(message=SANS_GUICHET)
        if arret is None or arret.pose.is_set():
            return PermissionResultDeny(message=ARRET, interrupt=True)
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
            return PermissionResultDeny(message=ARRET, interrupt=True)
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

    async def _deconnecter(self, client) -> None:
        with suppress(Exception):
            await asyncio.wait_for(client.interrupt(), self.delai_interruption_s)
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
