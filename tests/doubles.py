"""Doubles de test du guichet : ils servent aux tests, jamais au produit."""

import asyncio

from atelier.guichet import CHOIX, Guichet, Reponse, _Demande

SCENARIO_EPUISE = "Le scénario de démonstration ne prévoit pas cette demande."


class GuichetSimule(Guichet):
    """Double de test du guichet : répond tout de suite, selon un scénario écrit d'avance.

    Le scénario est une liste de choix (« une_fois », « toujours », « chantier », « non ») ou de
    Reponse,
    consommée dans l'ordre. Une fois épuisé, le guichet répond « non ». La règle d'un
    « toujours » est toujours celle que le vrai guichet proposerait, jamais celle du scénario.
    Quand cette règle manque, le vrai guichet refuserait « toujours » et laisserait la demande
    ouverte ; le guichet simulé, qui doit répondre tout de suite, répond alors « une_fois ». De
    même pour « chantier », dont les règles sont toujours celles du vrai guichet.
    """

    def __init__(self, scenario=()):
        super().__init__()
        self._scenario = [r if isinstance(r, Reponse) else Reponse(r) for r in scenario]
        if any(r.choix not in CHOIX for r in self._scenario):
            raise ValueError("Le scénario contient un choix inconnu.")
        self.demandes: list[dict] = []

    def demander(self, agent: str, outil: str, entree: dict) -> Reponse:
        with self._verrou:
            demande = _Demande(self._nouvel_identifiant(), agent, outil, entree)
            self.demandes.append(demande.fiche())
            prevue = self._scenario.pop(0) if self._scenario else Reponse("non", SCENARIO_EPUISE)
        if prevue.choix == "chantier":
            if not demande.regles_chantier:
                return Reponse("une_fois", prevue.message, "")
            return Reponse("chantier", prevue.message, "", tuple(demande.regles_chantier))
        if prevue.choix != "toujours":
            return Reponse(prevue.choix, prevue.message, "")
        if not demande.regle:
            return Reponse("une_fois", prevue.message, "")
        return Reponse("toujours", prevue.message, demande.regle)


# --- Faux client du SDK aux durées non nulles, qui compte tout (tâche M3) ----------------------

SESSION_MESUREE = "5e55104e-0000-4000-8000-00000000c1a0"


class ClientMesure:
    """Faux `ClaudeSDKClient` qui prend son temps et compte connexions, demandes, déconnexions.

    `tours` dit ce que joue chaque demande de la connexion, dans l'ordre : "ok" (une réponse,
    puis le message de fin), "echec" (un message de fin en erreur), "erreur" (le client lève),
    "bloque" (ne rend plus la main). Au-delà de la liste, "ok". Une durée de déconnexion None :
    `disconnect` ne rend jamais la main. Il n'annonce sa session
    (`init`) qu'à la première demande de la connexion : rien ne doit dépendre d'un `init` à
    chaque tour ; chaque message de fin la porte, comme le vrai.
    Chaque geste prend du temps (`durees`), pour qu'un défaut d'arrêt ou d'ordre se voie.
    """

    def __init__(self, options, tours, durees, journal, rang):
        self.options, self.tours, self.durees = options, list(tours), durees
        self.journal, self.rang = journal, rang
        self.demandes: list[str] = []
        self.connexions = self.deconnexions = self.interruptions = 0

    def _noter(self, geste):
        self.journal.append((geste, self.rang))

    async def connect(self):
        await asyncio.sleep(self.durees["connexion"])
        self.connexions += 1
        self._noter("connexion")

    async def query(self, consigne):
        self.demandes.append(consigne)
        self._noter("demande")

    async def receive_response(self):
        from claude_agent_sdk import ResultMessage, StreamEvent, SystemMessage

        rang = len(self.demandes)
        jeu = self.tours[rang - 1] if rang <= len(self.tours) else "ok"
        if rang == 1:
            donnees = {"apiKeySource": "none", "session_id": SESSION_MESUREE}
            yield SystemMessage(subtype="init", data=donnees)
        await asyncio.sleep(self.durees["tour"])
        if jeu == "bloque":
            await asyncio.Event().wait()
        if jeu == "erreur":
            raise RuntimeError("connexion perdue")
        delta = {"type": "text_delta", "text": f"Réponse {rang}."}
        yield StreamEvent(uuid="u", session_id=SESSION_MESUREE, event={"delta": delta})
        yield ResultMessage(
            subtype="success", duration_ms=1, duration_api_ms=1, is_error=jeu == "echec",
            num_turns=1, session_id=SESSION_MESUREE, total_cost_usd=0.1,
            result="En erreur." if jeu == "echec" else f"Fait {rang}.",
            usage={"input_tokens": 10, "output_tokens": 5},
        )  # fmt: skip

    async def set_permission_mode(self, mode):
        self._noter("mode")

    async def interrupt(self):
        await asyncio.sleep(self.durees["interruption"])
        self.interruptions += 1

    async def disconnect(self):
        if self.durees["deconnexion"] is None:  # un programme qui ne répond plus
            self._noter("deconnexion sans reponse")
            await asyncio.Event().wait()
        await asyncio.sleep(self.durees["deconnexion"])
        self.deconnexions += 1
        self._noter("deconnexion")


class FabriqueMesuree:
    """Rend un `ClientMesure` à chaque connexion ; `tours[i]` est le jeu de la i-ème connexion
    (au-delà, une connexion qui ne joue que "ok"). Additionne les comptes de tous ses clients."""

    DUREES = {"connexion": 0.005, "tour": 0.02, "interruption": 0.005, "deconnexion": 0.01}

    def __init__(self, *tours, **durees):
        self.tours, self.durees = list(tours), {**self.DUREES, **durees}
        self.clients: list[ClientMesure] = []
        self.journal: list[tuple[str, int]] = []

    def __call__(self, options):
        rang = len(self.clients)
        tours = self.tours[rang] if rang < len(self.tours) else []
        self.clients.append(ClientMesure(options, tours, self.durees, self.journal, rang))
        return self.clients[-1]

    @property
    def connexions(self) -> int:
        return sum(c.connexions for c in self.clients)

    @property
    def demandes(self) -> int:
        return sum(len(c.demandes) for c in self.clients)

    @property
    def deconnexions(self) -> int:
        return sum(c.deconnexions for c in self.clients)
