"""Faux client bâti comme le vrai ClaudeSDKClient 0.2.172 (lu dans le code) :
- un lecteur de fond range TOUT ce que le programme émet dans une file (query.py:388-506), tour ou pas ;
- receive_response lit cette file jusqu'au premier message de fin (client.py:566-605) ;
- query écrit sur l'entrée et lève CLIConnectionError si le programme est mort (subprocess_cli.py:1063-1087) ;
- à la mort du programme, le lecteur range une erreur puis la fin de flux (query.py:508-575).
Deux essais : (1) le programme meurt entre deux demandes ; (2) le programme joue de lui-même un tour entre
deux demandes (réveil par une tâche de fond, query.py:463-470) : un message de fin traîne dans la file."""
import asyncio, os, sys, time
sys.path.insert(0, os.path.dirname(__file__)); sys.path.insert(0, os.getcwd())
from faux import SESSION, fils
from atelier.agents import AgentClaude
from claude_agent_sdk import ResultMessage, StreamEvent, SystemMessage, CLIConnectionError, ProcessError

def fin(texte, erreur=False):
    return ResultMessage(subtype="success", duration_ms=1, duration_api_ms=1, is_error=erreur, num_turns=1, session_id=SESSION,
                         total_cost_usd=0.1, result=texte, usage={"input_tokens": 10, "output_tokens": 5})

class ClientFile:
    def __init__(self, options, scenario):
        self.options, self.scenario = options, scenario
        self.file, self.mort, self.demandes, self.connexions, self.deconnexions = None, False, [], 0, 0
    async def connect(self):
        self.file = asyncio.Queue(); self.connexions += 1
    async def _programme(self, rang, consigne):
        """Ce que le programme émet pour la demande `rang`, puis éventuellement de lui-même."""
        if rang == 1:
            await self.file.put(SystemMessage(subtype="init", data={"apiKeySource": "none", "session_id": SESSION, "permissionMode": self.options.permission_mode}))
        await asyncio.sleep(0.02)
        await self.file.put(StreamEvent(uuid="u", session_id=SESSION, event={"delta": {"type": "text_delta", "text": f"Réponse à « {consigne} »."}}))
        await self.file.put(fin(f"Fait : {consigne}"))
        if rang == 1 and self.scenario == "tour de fond":
            await asyncio.sleep(0.05)  # une tâche de fond finit : le programme reprend un tour de lui-même
            await self.file.put(StreamEvent(uuid="u2", session_id=SESSION, event={"delta": {"type": "text_delta", "text": "La tâche de fond a fini."}}))
            await self.file.put(fin("Tour de fond : rien de neuf."))
        if rang == 1 and self.scenario == "meurt":
            await asyncio.sleep(0.05)  # le programme sort (code 1) pendant l'attente
            self.mort = True
            await self.file.put(("erreur", ProcessError("Command failed with exit code 1", exit_code=1)))
            await self.file.put(("fin de flux", None))
    async def query(self, consigne):
        if self.mort:
            raise CLIConnectionError("Cannot write to terminated process (exit code: 1)")
        self.demandes.append(consigne)
        asyncio.ensure_future(self._programme(len(self.demandes), consigne))
    async def receive_response(self):
        while True:
            message = await self.file.get()
            if isinstance(message, tuple):
                if message[0] == "erreur":
                    raise message[1]
                return
            yield message
            if isinstance(message, ResultMessage):
                return
    async def set_permission_mode(self, mode): pass
    async def interrupt(self): pass
    async def disconnect(self): self.deconnexions += 1

O = {"role": "ouvrier", "tache": "B", "tentative": 1}
for scenario in ("rien", "meurt", "tour de fond"):
    clients = []
    def fabrique(options, scenario=scenario):
        clients.append(ClientFile(options, scenario)); return clients[-1]
    a = AgentClaude({}, delai_max_s=5, fabrique_client=fabrique)
    r1 = a.executer("Fais le travail", "opus", "high", None, False, O, garder_ouvert=True)
    time.sleep(0.2)  # les contrôles tournent ; l'ouvrier attend, ouvert
    print(f"--- scénario « {scenario} » : après le premier tour ouverte={r1.ouverte}, programme mort={clients[0].mort}, encore rangé comme ouvert={list(a._gardes)}")
    r2 = a.executer("Les contrôles sont rouges : corrige", "opus", "high", None, False, O, reprendre=r1.session, garder_ouvert=True)
    print(f"    la suite rend ok={r2.ok} ouverte={r2.ouverte} texte={r2.texte!r} erreur={r2.erreur!r}")
    if r2.ouverte:
        r3 = a.executer("Troisième demande", "opus", "high", None, False, O, reprendre=r1.session, garder_ouvert=True)
        print(f"    la demande d'après rend ok={r3.ok} texte={r3.texte!r}")
    a.liberer_tous()
    print(f"    connexions={sum(c.connexions for c in clients)} demandes={[c.demandes for c in clients]} déconnexions={sum(c.deconnexions for c in clients)} fils={fils()}")
