"""Le pont vers l'Agent SDK : une session asynchrone, pilotée depuis des fils synchrones.

Le SDK de Claude est asynchrone ; le moteur et le serveur d'Atelier travaillent en fils.
Chaque `SessionSDK` fait donc tourner sa propre boucle asyncio dans un fil à elle, et le
reste du code n'en voit que des appels synchrones : `envoyer`, `arreter`, `fermer`.

Règles de concurrence, à garder en tête en relisant :
- tout ce qui touche au client SDK se passe dans la boucle de la session ;
- le guichet, qui bloque, est toujours appelé dans un fil à part, jamais dans la boucle ;
- `arreter` pose le drapeau du tour en cours (lisible de tout fil, attendable dans la boucle)
  et ferme les demandes ouvertes au guichet ; le tour rend alors l'arrêt sans attendre ;
- un client coupé est interrompu puis déconnecté dans une tâche à part, jamais annulée :
  le SDK doit pouvoir aller jusqu'au bout de sa fermeture (attente, SIGTERM, SIGKILL) ;
- `fermer` attend la fin du tour en cours, puis celle des déconnexions, puis arrête la boucle.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import re
import threading
from contextlib import suppress
from pathlib import Path

from atelier.agents import Resultat, decrire_outil

ARRET = "Arrêté par la personne responsable."
SANS_REPONSE = "Claude Code s'est arrêté sans répondre."
SANS_GUICHET = "Aucun guichet n'est branché : l'autorisation est refusée."
REFUS = "La personne responsable a refusé cet outil."
INCOMPRIS = "Le guichet a rendu une réponse incomprise : l'outil est refusé."
INTERROMPU = "Le SDK de Claude s'est interrompu sans donner de raison."
MARGE_S = 30  # garde-fou au-delà du délai de l'agent, si la boucle elle-même ne répond plus
# Une règle Claude Code : un nom d'outil, suivi ou non d'un contenu non vide entre parenthèses.
FORME_REGLE = re.compile(r"([A-Za-z0-9_.:-]+)(?:\((.+)\))?")


def lire_source(api_key_source) -> str:
    """Traduit le champ `apiKeySource` du SDK : « abonnement », « clé API », ou rien."""
    if not api_key_source:
        return ""
    return "abonnement" if api_key_source == "none" else "clé API"


def lire_resultat(final, morceaux: list[str]) -> Resultat:
    """Traduit le message de fin du SDK en résultat, avec les règles de `lire_sortie_claude`."""
    if final is None:
        return Resultat(ok=False, erreur=SANS_REPONSE)
    usage = getattr(final, "usage", None) or {}
    tokens = int(usage.get("input_tokens") or 0) + int(usage.get("output_tokens") or 0)
    texte = str(getattr(final, "result", None) or "")
    if getattr(final, "is_error", False):
        return Resultat(ok=False, erreur=texte or "Erreur signalée par Claude Code.", tokens=tokens)
    cout = float(getattr(final, "total_cost_usd", None) or 0)
    return Resultat(ok=True, texte=texte or "".join(morceaux), cout_usd=cout, tokens=tokens)


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
        self.agent, self.modele, self.effort, self.dossier = agent, modele, effort, dossier
        self.outils_permis = list(outils_permis or [])
        self.outils_interdits = list(outils_interdits or [])
        self.mode_permission, self.role_ajoute = mode_permission, role_ajoute
        self.guichet, self.sur_evenement, self.delai_max_s = guichet, sur_evenement, delai_max_s
        self.session, self.reprise = session, reprise
        self.fabrique_client = fabrique_client
        self.source_connexion = ""
        self._client = None
        self._deconnexions: set[asyncio.Task] = set()
        self._boucle: asyncio.AbstractEventLoop | None = None
        self._fil: threading.Thread | None = None
        self._arret: _Arret | None = None
        self._occupee = threading.Lock()
        self._fermee = False

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
        if not resultat.ok:  # aucune demande ne doit rester ouverte au guichet après un échec
            self._annuler_au_guichet()
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
        if self._fermee:
            return
        self._fermee = True
        self.arreter()
        if self._boucle is None:
            return
        if threading.current_thread() is self._fil:  # appelé depuis un rappel : pas d'attente
            threading.Thread(target=self._liberer, daemon=True).start()
        else:
            self._liberer()

    def _liberer(self) -> None:
        """Attend la fin du tour en cours et des déconnexions, puis arrête la boucle.

        Si le tour ne rend pas la main (un rappel bloque la boucle), on n'attend pas plus.
        """
        boucle = self._boucle
        if self._occupee.acquire(timeout=self.delai_deconnexion_s):
            self._occupee.release()
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
        if self._boucle is None:
            self._boucle = asyncio.new_event_loop()
            self._fil = threading.Thread(
                target=self._boucle.run_forever, daemon=True, name=f"atelier-sdk-{self.agent}"
            )
            self._fil.start()
        return self._boucle

    def _emettre(self, type_: str, contenu: str) -> None:
        """Relaie un événement en direct ; une erreur du rappel ne touche pas la session."""
        if self.sur_evenement is None:
            return
        with suppress(Exception):
            self.sur_evenement({"agent": self.agent, "type": type_, "contenu": contenu})

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
            self._client = self._fabriquer()
            await self._client.connect()
        await self._client.query(consigne)
        morceaux: list[str] = []
        final = None
        async for message in self._client.receive_response():
            final = self._suivre(message, morceaux) or final
        return lire_resultat(final, morceaux)

    def _fabriquer(self):
        """Crée le client SDK. C'est ici, et seulement ici, qu'on charge la bibliothèque."""
        from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient

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
            can_use_tool=self._autoriser,
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
                    self._emettre("outil", decrire_outil({"name": bloc.name, "input": bloc.input}))
        elif isinstance(message, sdk.SystemMessage) and message.subtype == "init":
            self.source_connexion = lire_source(message.data.get("apiKeySource"))
            self._retenir_session(message.data.get("session_id"))
        elif isinstance(message, sdk.ResultMessage):
            self._retenir_session(message.session_id)
            return message
        return None

    def _retenir_session(self, identifiant) -> None:
        """Garde l'identifiant de session : après une coupure, on reprendra cette session."""
        if identifiant:
            self.session, self.reprise = identifiant, True

    async def _autoriser(self, outil: str, entree: dict, contexte=None):
        """Rappel `can_use_tool` du SDK : pose la question au guichet, sans bloquer la boucle.

        Hors d'un tour, ou après un arrêt, la demande est refusée sans déranger le guichet.
        Un arrêt pendant l'attente refuse aussitôt, sans attendre la réponse du guichet.
        """
        from claude_agent_sdk import PermissionResultDeny

        arret = self._arret
        self._emettre("attente", decrire_outil({"name": outil, "input": entree}))
        if self.guichet is None:
            return PermissionResultDeny(message=SANS_GUICHET)
        if arret is None or arret.pose.is_set():
            return PermissionResultDeny(message=ARRET, interrupt=True)
        demande = _dans_un_fil(self.guichet.demander, self.agent, outil, entree)
        veille = asyncio.ensure_future(arret.evenement.wait())
        try:
            await asyncio.wait({demande, veille}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            veille.cancel()
            if not demande.done():
                demande.cancel()
        if arret.pose.is_set() or demande.cancelled():
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
        self._couper()
        await self._attendre_deconnexions()
