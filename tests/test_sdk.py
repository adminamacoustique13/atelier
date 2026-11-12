"""Tests du pont vers l'Agent SDK : un faux client, et le vrai client sur un faux exécutable.

Aucun appel réel à Claude, aucun réseau, aucun compte.
"""

import asyncio
import dataclasses
import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import pytest

pytest.importorskip("claude_agent_sdk")

from claude_agent_sdk import (  # noqa: E402
    AssistantMessage,
    ClaudeSDKClient,
    PermissionResultAllow,
    PermissionResultDeny,
    ResultMessage,
    StreamEvent,
    SystemMessage,
    ToolPermissionContext,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

from atelier.agents import decrire_outil  # noqa: E402
from atelier.guichet import Guichet  # noqa: E402
from atelier.sdk import (  # noqa: E402
    SessionSDK,
    lire_refus,
    lire_resultat,
    lire_source,
    regle_sdk,
    traduire_reponse,
)

GARDE_S = 5  # aucun test ne doit pouvoir attendre plus longtemps que ça
AGENT = "A-ouvrier-1"
ARRETE = "Arrêté par la personne responsable."
SANS_GUICHET = "Aucun guichet n'est branché : l'autorisation est refusée."
SANS_REPONSE = "Claude Code s'est arrêté sans répondre."
INCOMPRIS = "Le guichet a rendu une réponse incomprise : l'outil est refusé."
REFUS = "La personne responsable a refusé cet outil."
UUID = "0b5c3d1e-7f2a-4c8b-9d6e-1a2b3c4d5e6f"


# --- Messages du SDK -------------------------------------------------------------------


def texte(morceau):
    delta = {"type": "text_delta", "text": morceau}
    return StreamEvent(uuid="u", session_id=UUID, event={"type": "x", "delta": delta})


def outil(nom, entree, identifiant="t1"):
    bloc = ToolUseBlock(id=identifiant, name=nom, input=entree)
    return AssistantMessage(content=[bloc], model="opus")


def init(source="none", mode=None):
    donnees = {"apiKeySource": source, "session_id": UUID}
    if mode is not None:
        donnees["permissionMode"] = mode
    return SystemMessage(subtype="init", data=donnees)


def statut(mode):
    """Le message par lequel Claude Code annonce un nouveau mode en cours de session."""
    return SystemMessage(subtype="status", data={"permissionMode": mode, "session_id": UUID})


def resultat_outil(identifiant, contenu, erreur=True):
    """Le résultat d'un outil, tel que l'agent le reçoit (un message « utilisateur »)."""
    bloc = ToolResultBlock(tool_use_id=identifiant, content=contenu, is_error=erreur)
    return UserMessage(content=[bloc])


def fin(result="Fini.", is_error=False, cout=0.12, refus=None):
    return ResultMessage(
        subtype="success", duration_ms=1, duration_api_ms=1, is_error=is_error, num_turns=1,
        session_id=UUID, total_cost_usd=cout, result=result,
        usage={"input_tokens": 100, "output_tokens": 20}, permission_denials=refus,
    )  # fmt: skip


# --- Faux client, fausse fabrique, faux guichet ----------------------------------------


@dataclass
class Permission:
    """Étape : le faux client demande une autorisation et attend la décision."""

    outil: str
    entree: dict
    detachee: bool = False  # comme le vrai SDK : la demande vit dans sa propre tâche


@dataclass
class Geste:
    """Étape : le faux client fait quelque chose de lui-même (`faire(client)`, asynchrone)."""

    faire: object


BLOQUE = object()  # étape du scénario : l'agent ne rend plus la main


INDISPONIBLE_SDK = "Cannot set permission mode to auto: auto mode unavailable for this model"


class FauxClient:
    def __init__(self, options, scenario, lent=None, demande_pendant_interrupt=None,
                 sans_auto=False):  # fmt: skip
        self.options, self.scenario, self.lent = options, scenario, lent or {}
        self.demande_pendant_interrupt = demande_pendant_interrupt
        self.sans_auto = sans_auto  # comme un modèle pour lequel le mode auto n'existe pas
        self.consignes, self.decisions, self.fils, self.detachees = [], [], [], []
        self.modes_demandes, self.modes, self.fils_modes = [], [], []
        self.connecte = self.interrompu = self.deconnecte = False
        self.travail_annule = self.deconnexion_annulee = False

    async def connect(self):
        await asyncio.sleep(self.lent.get("connect", 0))
        self.connecte = True

    async def query(self, consigne):
        self.consignes.append(consigne)
        self.fils.append(threading.current_thread())

    async def _demander(self, etape):
        contexte = ToolPermissionContext(tool_use_id="t1")
        decision = await self.options.can_use_tool(etape.outil, etape.entree, contexte)
        self.decisions.append(decision)

    async def receive_response(self):
        for etape in self.scenario:
            if isinstance(etape, Permission) and etape.detachee:
                self.detachees.append(asyncio.ensure_future(self._demander(etape)))
            elif isinstance(etape, Permission):
                await self._demander(etape)
            elif isinstance(etape, Geste):
                await etape.faire(self)
            elif etape is BLOQUE:
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    self.travail_annule = True
                    raise
            elif isinstance(etape, BaseException):
                raise etape
            else:
                yield etape

    async def set_permission_mode(self, mode):
        """Comme le vrai : asynchrone, et refusé pour le mode auto quand il n'existe pas."""
        self.modes_demandes.append(mode)
        self.fils_modes.append(threading.current_thread())
        await asyncio.sleep(self.lent.get("mode", 0))
        if self.sans_auto and mode == "auto":
            raise Exception(INDISPONIBLE_SDK)
        self.modes.append(mode)

    async def interrupt(self):
        await asyncio.sleep(self.lent.get("interrupt", 0))
        if self.demande_pendant_interrupt:
            await self._demander(self.demande_pendant_interrupt)
        self.interrompu = True

    async def disconnect(self):
        try:
            await asyncio.sleep(self.lent.get("disconnect", 0))
        except asyncio.CancelledError:
            self.deconnexion_annulee = True
            raise
        self.deconnecte = True


class Fabrique:
    """Rend un nouveau faux client à chaque connexion, avec le scénario suivant."""

    def __init__(self, *scenarios, **reglages_client):
        self.scenarios = list(scenarios) or [[fin()]]
        self.reglages_client, self.clients = reglages_client, []

    def __call__(self, options):
        scenario = self.scenarios[min(len(self.clients), len(self.scenarios) - 1)]
        self.clients.append(FauxClient(options, scenario, **self.reglages_client))
        return self.clients[-1]


@dataclass
class Reponse:
    choix: object
    message: object = ""
    regle: object = ""
    regles: object = ()


class FauxGuichet:
    """Rend la réponse prévue ; sans réponse prévue, ne répond pas (et ignore `annuler`)."""

    def __init__(self, reponse=None, panne=None, annuler_s=0.0):
        self.reponse, self.panne, self.annuler_s = reponse, panne, annuler_s
        self.demandes, self.annulations, self.fils = [], [], []
        self.demande_recue, self.liberer = threading.Event(), threading.Event()

    def demander(self, agent, outil, entree):
        self.demandes.append((agent, outil, entree))
        self.fils.append(threading.current_thread())
        self.demande_recue.set()
        if self.panne:
            raise self.panne
        if self.reponse is None:
            self.liberer.wait(GARDE_S)
            return Reponse("non", "Trop tard.")
        return self.reponse

    def annuler(self, agent):
        time.sleep(self.annuler_s)
        self.annulations.append(agent)


@pytest.fixture
def ouvrir():
    """Ouvre des sessions sur une fausse fabrique et les ferme toutes à la fin du test."""
    sessions = []

    def ouvrir_session(*scenarios, client=None, **reglages):
        fabrique, evenements = Fabrique(*scenarios, **(client or {})), []
        parametres = {
            "agent": AGENT, "modele": "opus", "effort": "high", "fabrique_client": fabrique,
            "sur_evenement": evenements.append, "delai_max_s": GARDE_S,
        }  # fmt: skip
        session = SessionSDK(**{**parametres, **reglages})
        sessions.append(session)
        return session, fabrique, evenements

    yield ouvrir_session
    for session in sessions:
        session.fermer()


def du_type(evenements, type_):
    return [e["contenu"] for e in evenements if e["type"] == type_]


def attendre(condition, delai=GARDE_S):
    limite = time.monotonic() + delai
    while not condition():
        if time.monotonic() > limite:
            return False
        time.sleep(0.005)
    return True


def en_fond(session, consigne="Travaille."):
    """Lance `envoyer` dans un fil ; rend le fil et la liste où son résultat arrivera."""
    rendus = []
    fil = threading.Thread(target=lambda: rendus.append(session.envoyer(consigne)), daemon=True)
    fil.start()
    return fil, rendus


def commence(fabrique):
    return attendre(lambda: fabrique.clients and fabrique.clients[-1].consignes)


# --- Critère 1 : ouverture de la session ------------------------------------------------


def test_options_transmises_au_sdk_dans_un_fil_propre(ouvrir, tmp_path):
    session, fabrique, _ = ouvrir(
        [fin()], dossier=tmp_path, outils_permis=["Read", "Bash(npm test:*)"],
        outils_interdits=["Write"], mode_permission="acceptEdits",
        role_ajoute="Tu es l'ouvrier de la tâche A.", session=UUID,
    )  # fmt: skip
    assert session.envoyer("La consigne.").ok
    client = fabrique.clients[0]
    options = client.options
    assert (options.model, options.effort, options.cwd) == ("opus", "high", tmp_path)
    assert options.allowed_tools == ["Read", "Bash(npm test:*)"]
    assert options.disallowed_tools == ["Write"]
    assert options.permission_mode == "acceptEdits"
    assert options.system_prompt == {
        "type": "preset", "preset": "claude_code", "append": "Tu es l'ouvrier de la tâche A."
    }
    assert options.include_partial_messages and options.can_use_tool is not None
    assert (options.session_id, options.resume) == (UUID, None)
    assert client.connecte and client.consignes == ["La consigne."]
    assert client.fils[0] is not threading.current_thread()
    assert client.fils[0].name == f"atelier-sdk-{AGENT}"


def test_reprise_et_role_vide(ouvrir):
    session, fabrique, _ = ouvrir([fin()], session=UUID, reprise=True)
    session.envoyer("Suite.")
    options = fabrique.clients[0].options
    assert (options.session_id, options.resume) == (None, UUID)
    assert options.system_prompt == {"type": "preset", "preset": "claude_code"}


def test_le_client_reste_ouvert_d_un_envoi_a_l_autre(ouvrir):
    session, fabrique, _ = ouvrir([fin()])
    session.envoyer("Un.")
    session.envoyer("Deux.")
    assert len(fabrique.clients) == 1
    assert fabrique.clients[0].consignes == ["Un.", "Deux."]


def test_import_paresseux_du_sdk():
    code = "import sys, atelier.sdk; print('claude_agent_sdk' in sys.modules)"
    racine = Path(__file__).resolve().parents[1]
    sortie = subprocess.run(
        [sys.executable, "-c", code], cwd=racine, capture_output=True, text=True, timeout=30
    )
    assert sortie.stdout.strip() == "False", sortie.stderr


def test_aucun_fil_ne_survit_aux_sessions_fermees(ouvrir):
    avant = set(threading.enumerate())
    for _ in range(3):
        guichet = FauxGuichet(Reponse("une_fois"))
        session, _, _ = ouvrir([Permission("Bash", {"command": "ls"}), fin()], guichet=guichet)
        assert session.envoyer("Va.").ok
        session.fermer()
    assert attendre(lambda: not [f for f in threading.enumerate() if f not in avant], 2)


# --- Critères 2 et 3 : texte et outils en direct ----------------------------------------


def test_texte_relaye_morceau_par_morceau(ouvrir):
    session, _, evenements = ouvrir([texte("Bon"), texte("jour."), fin(result="")])
    resultat = session.envoyer("Salue.")
    assert du_type(evenements, "texte") == ["Bon", "jour."]
    assert evenements[0] == {"agent": AGENT, "type": "texte", "contenu": "Bon"}
    assert resultat.texte == "Bonjour."  # texte final vide : les morceaux le remplacent


def test_outil_relaye_sous_forme_courte(ouvrir):
    entree = {"command": "npm test"}
    session, _, evenements = ouvrir([outil("Bash", entree), fin()])
    session.envoyer("Teste.")
    assert du_type(evenements, "outil") == ["Lance npm test"]
    assert du_type(evenements, "outil") == [decrire_outil({"name": "Bash", "input": entree})]


def test_outil_de_lecture_relaye_sous_sa_forme_courte(ouvrir):
    session, _, evenements = ouvrir([outil("Read", {"file_path": "coeur/calcul.py"}), fin()])
    session.envoyer("Lis.")
    assert du_type(evenements, "outil") == ["Lit coeur/calcul.py"]


def test_un_message_inconnu_ou_illisible_ne_casse_rien(ouvrir):
    autre = SystemMessage(subtype="autre", data={})
    sans_delta = StreamEvent(uuid="u", session_id=UUID, event={"type": "x"})
    delta_vide = StreamEvent(uuid="u", session_id=UUID, event={"delta": {"type": "text_delta"}})
    session, _, evenements = ouvrir(
        [init(), object(), autre, sans_delta, delta_vide, texte("Bon"), texte("jour"),
         fin(result="Bonjour")]  # fmt: skip
    )
    resultat = session.envoyer("Salue.")
    assert (resultat.ok, resultat.texte) == (True, "Bonjour")
    assert du_type(evenements, "texte") == ["Bon", "jour"] and du_type(evenements, "outil") == []


def test_un_rappel_qui_leve_ne_tue_pas_la_session(ouvrir):
    def rappel(_evenement):
        raise RuntimeError("Le tableau de bord est tombé.")

    session, _, _ = ouvrir([texte("a"), outil("Read", {"file_path": "x"}), fin()])
    session.sur_evenement = rappel
    assert session.envoyer("Va.").ok
    session.sur_evenement = None
    assert session.envoyer("Encore.").ok


# --- Critère 4 : autorisations ----------------------------------------------------------


def demander_npm(ouvrir, guichet):
    entree = {"command": "npm install"}
    session, fabrique, evenements = ouvrir([Permission("Bash", entree), fin()], guichet=guichet)
    resultat = session.envoyer("Installe.")
    return resultat, fabrique.clients[0], evenements


def test_autorisation_une_fois(ouvrir):
    guichet = FauxGuichet(Reponse("une_fois"))
    resultat, client, evenements = demander_npm(ouvrir, guichet)
    assert resultat.ok
    assert client.decisions == [PermissionResultAllow()]
    assert guichet.demandes == [(AGENT, "Bash", {"command": "npm install"})]
    assert du_type(evenements, "attente") == ["Lance npm install"]
    # Le guichet bloque : il est appelé hors de la boucle de la session.
    assert guichet.fils[0] is not client.fils[0]


def test_autorisation_toujours_renvoie_la_regle(ouvrir):
    guichet = FauxGuichet(Reponse("toujours", regle="Bash(npm install:*)"))
    _, client, _ = demander_npm(ouvrir, guichet)
    (decision,) = client.decisions
    assert isinstance(decision, PermissionResultAllow)
    (mise_a_jour,) = decision.updated_permissions
    assert mise_a_jour.to_dict() == {
        "type": "addRules", "destination": "session", "behavior": "allow",
        "rules": [{"toolName": "Bash", "ruleContent": "npm install:*"}],
    }  # fmt: skip


def test_autorisation_refusee_avec_le_message(ouvrir):
    guichet = FauxGuichet(Reponse("non", message="Utilise plutôt pnpm."))
    resultat, client, _ = demander_npm(ouvrir, guichet)
    assert resultat.ok  # l'agent lit le refus et continue
    assert client.decisions == [PermissionResultDeny(message="Utilise plutôt pnpm.")]


def test_sans_guichet_l_autorisation_est_refusee(ouvrir):
    _, client, evenements = demander_npm(ouvrir, None)
    assert client.decisions == [PermissionResultDeny(message=SANS_GUICHET)]
    assert du_type(evenements, "attente") == ["Lance npm install"]


@pytest.mark.parametrize("panne", [RuntimeError("guichet fermé"), SystemExit("guichet fermé")])
def test_un_guichet_en_panne_vaut_refus(ouvrir, panne):
    _, client, _ = demander_npm(ouvrir, FauxGuichet(panne=panne))
    (decision,) = client.decisions
    assert isinstance(decision, PermissionResultDeny) and "guichet fermé" in decision.message


def regles_de(decision):
    return [m.to_dict() for m in decision.updated_permissions or []]


@pytest.mark.parametrize(
    "reponse, attendu",
    [
        (Reponse("une_fois"), PermissionResultAllow()),
        (Reponse("une_fois", regle="Bash"), PermissionResultAllow()),
        (Reponse("non", message="Pas ça."), PermissionResultDeny(message="Pas ça.")),
        (Reponse("non"), PermissionResultDeny(message=REFUS)),
        (Reponse("non", message="   "), PermissionResultDeny(message=REFUS)),
        # « toujours » sans règle sûre : permis cette fois seulement, aucune règle enregistrée.
        (Reponse("toujours", regle=""), PermissionResultAllow()),
        (Reponse("toujours", regle="   "), PermissionResultAllow()),
        (Reponse("toujours", regle=None), PermissionResultAllow()),
        (Reponse("toujours", regle=42), PermissionResultAllow()),
        (Reponse("toujours", regle="Bash()"), PermissionResultAllow()),
        (Reponse("toujours", regle="Bash(npm install:*"), PermissionResultAllow()),
        (Reponse("toujours", regle="Bash(npm\ninstall:*)"), PermissionResultAllow()),
        # Choix inconnu ou absent : refus.
        (Reponse("oui"), PermissionResultDeny(message=INCOMPRIS)),
        (Reponse("TOUJOURS", regle="Bash"), PermissionResultDeny(message=INCOMPRIS)),
        (Reponse(None), PermissionResultDeny(message=INCOMPRIS)),
        (None, PermissionResultDeny(message=INCOMPRIS)),
        ({"choix": "une_fois"}, PermissionResultDeny(message=INCOMPRIS)),
    ],
)
def test_traduire_reponse(reponse, attendu):
    assert traduire_reponse(reponse) == attendu


def test_traduire_reponse_toujours_avec_regle():
    decision = traduire_reponse(Reponse("toujours", regle=" WebFetch(domain:example.com) "))
    assert isinstance(decision, PermissionResultAllow)
    assert regles_de(decision) == [{
        "type": "addRules", "destination": "session", "behavior": "allow",
        "rules": [{"toolName": "WebFetch", "ruleContent": "domain:example.com"}],
    }]  # fmt: skip
    assert regles_de(traduire_reponse(Reponse("toujours", regle="Read")))[0]["rules"] == [
        {"toolName": "Read", "ruleContent": None}
    ]


def test_traduire_reponse_chantier_ajoute_toutes_ses_regles_a_la_session():
    reponse = Reponse("chantier", regles=("Bash(make test:*)", "Bash(sed:*)"))
    assert regles_de(traduire_reponse(reponse)) == [{
        "type": "addRules", "destination": "session", "behavior": "allow",
        "rules": [{"toolName": "Bash", "ruleContent": "make test:*"},
                  {"toolName": "Bash", "ruleContent": "sed:*"}],
    }]  # fmt: skip


@pytest.mark.parametrize("regles", [(), ("Bash(sed:*)", "Bash("), None, "Bash(sed:*)", (42,)])
def test_traduire_reponse_chantier_douteux_permet_cette_fois_seulement(regles):
    assert traduire_reponse(Reponse("chantier", regles=regles)) == PermissionResultAllow()


@pytest.mark.parametrize(
    "regle, attendu",
    [
        ("Bash(npm install:*)", ("Bash", "npm install:*")),
        ("WebFetch(domain:example.com)", ("WebFetch", "domain:example.com")),
        ("mcp__serveur__outil", ("mcp__serveur__outil", None)),
        ("Read", ("Read", None)),
    ],
)
def test_regle_sdk(regle, attendu):
    valeur = regle_sdk(regle)
    assert (valeur.tool_name, valeur.rule_content) == attendu


@pytest.mark.parametrize("regle", ["", "   ", None, 42, "Bash()", "Bash(a", "Bash(a\nb)", "(x)"])
def test_regle_sdk_refuse_les_regles_vides_ou_mal_formees(regle):
    assert regle_sdk(regle) is None


# --- Critère 5 : arrêt ------------------------------------------------------------------


def test_arret_pendant_une_autorisation_en_attente(ouvrir):
    guichet = FauxGuichet()  # ne répondra pas avant d'être libéré, et ignore `annuler`
    session, fabrique, evenements = ouvrir(
        [init(), Permission("Bash", {"command": "rm -rf build"}), fin()],
        [fin(result="Repris.")],
        guichet=guichet,
    )
    fil, rendus = en_fond(session, "Nettoie.")
    try:
        assert guichet.demande_recue.wait(GARDE_S)
        assert session.envoyer("En même temps.").erreur == "Cet agent traite déjà une consigne."
        debut = time.monotonic()
        session.arreter()
        fil.join(GARDE_S)
        assert not fil.is_alive() and time.monotonic() - debut < 2
    finally:
        guichet.liberer.set()
    (resultat,) = rendus
    assert not resultat.ok and resultat.erreur == ARRETE
    assert AGENT in guichet.annulations
    premier = fabrique.clients[0]
    assert attendre(lambda: premier.interrompu and premier.deconnecte)
    assert not [d for d in premier.decisions if isinstance(d, PermissionResultAllow)]
    assert evenements[-1] == {"agent": AGENT, "type": "fin", "contenu": ARRETE}
    # L'envoi suivant rouvre un client qui reprend la même session.
    assert session.envoyer("Reprends.").texte == "Repris."
    assert fabrique.clients[1].options.resume == UUID
    assert len(guichet.demandes) == 1


def test_arret_pendant_une_demande_qui_vit_a_part(ouvrir):
    """Comme dans le vrai SDK, la demande vit dans sa propre tâche : l'arrêt la refuse."""
    guichet = FauxGuichet()
    entree = {"command": "npm install"}
    session, fabrique, _ = ouvrir([Permission("Bash", entree, detachee=True), BLOQUE],
                                  guichet=guichet)  # fmt: skip
    fil, rendus = en_fond(session)
    try:
        assert guichet.demande_recue.wait(GARDE_S)
        session.arreter()
        fil.join(GARDE_S)
        client = fabrique.clients[0]
        assert attendre(lambda: client.decisions, 1)  # sans attendre le guichet
    finally:
        guichet.liberer.set()
    assert rendus[0].erreur == ARRETE
    assert client.decisions == [PermissionResultDeny(message=ARRETE, interrupt=True)]


def test_apres_l_arret_aucune_demande_ne_part_au_guichet(ouvrir):
    """Claude Code demande encore une autorisation pendant qu'on l'interrompt."""
    guichet = FauxGuichet(Reponse("une_fois"))
    tardive = Permission("Bash", {"command": "npm publish"})
    session, fabrique, _ = ouvrir([BLOQUE], guichet=guichet,
                                  client={"demande_pendant_interrupt": tardive})  # fmt: skip
    fil, rendus = en_fond(session)
    assert commence(fabrique)
    session.arreter()
    fil.join(GARDE_S)
    client = fabrique.clients[0]
    assert attendre(lambda: client.interrompu)
    assert rendus[0].erreur == ARRETE
    assert guichet.demandes == []
    assert client.decisions == [PermissionResultDeny(message=ARRETE, interrupt=True)]


def test_arret_pendant_que_l_agent_travaille(ouvrir):
    session, fabrique, _ = ouvrir([texte("Je cherche"), BLOQUE])
    fil, rendus = en_fond(session, "Cherche.")
    assert commence(fabrique)
    session.arreter()
    fil.join(GARDE_S)
    client = fabrique.clients[0]
    assert rendus[0].erreur == ARRETE
    assert client.travail_annule  # la tâche de travail est bien annulée
    assert attendre(lambda: client.interrompu and client.deconnecte)


def test_arret_sans_rien_en_cours_est_sans_danger(ouvrir):
    guichet = FauxGuichet(Reponse("une_fois"))
    session, _, _ = ouvrir([fin()], guichet=guichet)
    session.arreter()
    assert session.envoyer("Va.").ok  # l'arrêt n'est pas mémorisé pour l'envoi suivant
    session.arreter()
    assert session.envoyer("Encore.").ok


def test_fermer_pendant_un_envoi(ouvrir):
    """Un guichet lent à annuler et un client lent à s'interrompre ne bloquent rien."""
    guichet = FauxGuichet(annuler_s=0.03)
    session, fabrique, _ = ouvrir([texte("a"), BLOQUE], guichet=guichet,
                                  client={"lent": {"interrupt": 0.2, "disconnect": 0.05}})
    fil, rendus = en_fond(session)
    assert commence(fabrique)
    time.sleep(0.02)
    fermeur = threading.Thread(target=session.fermer, daemon=True)
    fermeur.start()
    fil.join(GARDE_S)
    fermeur.join(GARDE_S)
    assert not fil.is_alive() and not fermeur.is_alive()
    assert rendus[0].erreur == ARRETE
    client = fabrique.clients[0]
    assert client.interrompu and client.deconnecte  # `fermer` a attendu la déconnexion
    assert not session._fil.is_alive()


def test_fermer_en_meme_temps_qu_un_envoi_ne_bloque_jamais(ouvrir):
    attendus = {ARRETE, "La session de cet agent est fermée."}
    for _ in range(20):
        session, _, _ = ouvrir([BLOQUE])
        fil, rendus = en_fond(session)
        session.fermer()
        fil.join(GARDE_S)
        assert not fil.is_alive() and rendus[0].erreur in attendus


def test_une_deconnexion_lente_n_est_jamais_annulee(ouvrir):
    session, fabrique, _ = ouvrir([BLOQUE], client={"lent": {"disconnect": 0.5}})
    session.delai_interruption_s = 0.05
    fil, rendus = en_fond(session)
    assert commence(fabrique)
    debut = time.monotonic()
    session.arreter()
    fil.join(GARDE_S)
    assert rendus[0].erreur == ARRETE
    assert time.monotonic() - debut < 0.3  # l'arrêt n'attend pas la déconnexion
    client = fabrique.clients[0]
    assert not client.deconnecte
    session.fermer()  # attend la fin des déconnexions avant d'arrêter la boucle
    assert client.deconnecte and not client.deconnexion_annulee


def test_l_envoi_suivant_attend_la_fin_de_la_deconnexion(ouvrir):
    session, fabrique, _ = ouvrir([BLOQUE], [fin()], client={"lent": {"disconnect": 0.3}})
    fil, _ = en_fond(session)
    assert commence(fabrique)
    session.arreter()
    fil.join(GARDE_S)
    assert session.envoyer("Reprends.").ok
    assert fabrique.clients[0].deconnecte and not fabrique.clients[0].deconnexion_annulee


# --- Les trois reliquats relevés par le vérificateur du pont ---------------------------


def test_une_demande_tardive_d_un_client_coupe_ne_va_jamais_au_guichet(ouvrir):
    """Reliquat a : l'envoi suivant est déjà parti quand l'ancien Claude Code, lent à
    s'interrompre, demande encore une autorisation. Elle est refusée sans le guichet."""
    guichet = FauxGuichet(Reponse("une_fois"))
    tardive = Permission("Bash", {"command": "npm publish"})
    reglages = {"lent": {"interrupt": 0.3}, "demande_pendant_interrupt": tardive}
    session, fabrique, _ = ouvrir([BLOQUE], [fin(result="Repris.")], guichet=guichet,
                                  client=reglages)  # fmt: skip
    fil, rendus = en_fond(session)
    assert commence(fabrique)
    session.arreter()
    fil.join(GARDE_S)
    assert rendus[0].erreur == ARRETE
    assert session.envoyer("Reprends.").texte == "Repris."  # part pendant l'interruption
    ancien = fabrique.clients[0]
    assert ancien.interrompu
    assert guichet.demandes == []
    assert ancien.decisions == [PermissionResultDeny(message=ARRETE, interrupt=True)]


def test_fermer_juste_avant_la_creation_de_la_boucle_libere_le_fil(ouvrir):
    """Reliquat b : `fermer` passe entre le contrôle de fermeture d'`envoyer` et la création
    de la boucle. Il attend la fin du tour, puis libère le fil de la session."""
    session, _, _ = ouvrir([fin()])
    demarrer, fermeurs = session._demarrer_boucle, []

    def demarrer_apres_fermer():
        fermeurs.append(threading.Thread(target=session.fermer, daemon=True))
        fermeurs[0].start()
        fermeurs[0].join(0.2)  # laisse à `fermer` le temps de passer, ou d'attendre le tour
        return demarrer()

    session._demarrer_boucle = demarrer_apres_fermer
    resultat = session.envoyer("Va.")
    fermeurs[0].join(GARDE_S)
    assert resultat.erreur == ARRETE
    assert not fermeurs[0].is_alive()
    assert attendre(lambda: not session._fil.is_alive(), 2)


def test_une_demande_annulee_par_claude_code_ne_reste_pas_ouverte(ouvrir):
    """Reliquat c : Claude Code retire lui-même sa demande, puis finit son tour sans erreur.
    À la fin du tour, plus aucune demande de l'agent n'est ouverte au guichet."""
    guichet = Guichet(delai_s=GARDE_S)

    async def retirer_la_demande(client):
        limite = time.monotonic() + GARDE_S
        while not guichet.ouvertes() and time.monotonic() < limite:
            await asyncio.sleep(0.005)
        for demande in client.detachees:
            demande.cancel()

    entree = {"command": "npm install"}
    session, _, _ = ouvrir(
        [Permission("Bash", entree, detachee=True), Geste(retirer_la_demande), fin()],
        guichet=guichet,
    )
    try:
        assert session.envoyer("Installe.").ok
        assert guichet.ouvertes() == []
    finally:
        guichet.annuler(AGENT)


# --- Critère 6 : fin de session ---------------------------------------------------------


def test_fin_rend_texte_cout_et_tokens(ouvrir):
    session, _, evenements = ouvrir([texte("Fi"), fin(result="Fini.", cout=0.35)])
    resultat = session.envoyer("Fais.")
    assert (resultat.ok, resultat.texte, resultat.cout_usd, resultat.tokens) == (
        True, "Fini.", 0.35, 120
    )  # fmt: skip
    assert evenements[-1] == {"agent": AGENT, "type": "fin", "contenu": "L'agent a terminé."}


def test_fin_en_erreur(ouvrir):
    session, _, evenements = ouvrir([fin(result="Quota dépassé.", is_error=True)])
    resultat = session.envoyer("Fais.")
    assert (resultat.ok, resultat.erreur, resultat.tokens) == (False, "Quota dépassé.", 120)
    assert du_type(evenements, "fin") == ["Quota dépassé."]


def test_fin_sans_resultat(ouvrir):
    session, _, _ = ouvrir([texte("Je commence")])
    assert session.envoyer("Fais.").erreur == SANS_REPONSE


def test_delai_depasse_ferme_aussi_la_demande_au_guichet(ouvrir):
    guichet = FauxGuichet()
    session, fabrique, _ = ouvrir([Permission("Bash", {"command": "ls"})], guichet=guichet,
                                  delai_max_s=0.2)  # fmt: skip
    debut = time.monotonic()
    try:
        resultat = session.envoyer("Fais.")
    finally:
        guichet.liberer.set()
    assert time.monotonic() - debut < 2
    assert resultat.erreur == "L'agent n'a pas fini dans le délai de 0.2 secondes."
    assert guichet.annulations == [AGENT]
    client = fabrique.clients[0]
    assert attendre(lambda: client.interrompu and client.deconnecte)


def test_erreur_du_sdk(ouvrir):
    guichet = FauxGuichet(Reponse("une_fois"))
    session, fabrique, _ = ouvrir([RuntimeError("connexion perdue")], [fin()], guichet=guichet)
    resultat = session.envoyer("Fais.")
    assert resultat.erreur == "Le SDK de Claude a échoué : connexion perdue"
    assert guichet.annulations == [AGENT]
    assert attendre(lambda: fabrique.clients[0].deconnecte)
    assert session.envoyer("Encore.").ok and len(fabrique.clients) == 2


def test_un_client_qui_leve_cancelled_error(ouvrir):
    session, fabrique, evenements = ouvrir([asyncio.CancelledError()], [fin()])
    resultat = session.envoyer("Fais.")
    assert resultat.erreur == "Le SDK de Claude s'est interrompu sans donner de raison."
    assert du_type(evenements, "fin") == [resultat.erreur]
    assert attendre(lambda: fabrique.clients[0].deconnecte)
    assert session.envoyer("Encore.").ok and len(fabrique.clients) == 2


def test_fermer(ouvrir):
    session, fabrique, _ = ouvrir([fin()])
    session.envoyer("Fais.")
    session.fermer()
    session.fermer()  # deux fois sans danger
    assert fabrique.clients[0].deconnecte
    assert session.envoyer("Encore.").erreur == "La session de cet agent est fermée."
    jamais_ouverte, _, _ = ouvrir()
    jamais_ouverte.fermer()


def test_fermer_depuis_un_rappel(ouvrir):
    session, fabrique, _ = ouvrir([texte("a"), BLOQUE])
    session.sur_evenement = lambda e: e["type"] == "texte" and session.fermer()
    debut = time.monotonic()
    assert session.envoyer("Fais.").erreur == ARRETE
    assert time.monotonic() - debut < 2
    assert attendre(lambda: not session._fil.is_alive())


def test_lire_resultat():
    assert lire_resultat(None, ["a"]).erreur == SANS_REPONSE
    assert lire_resultat(fin(result=""), ["a", "b"]).texte == "ab"
    assert lire_resultat(fin(result="", is_error=True), []).erreur == (
        "Erreur signalée par Claude Code."
    )


# --- Critère 7 : source de connexion ----------------------------------------------------


@pytest.mark.parametrize(
    "source, attendu",
    [("none", "abonnement"), ("ANTHROPIC_API_KEY", "clé API"), ("apiKeyHelper", "clé API"),
     ("/login managed key", "clé API"), ("", ""), (None, "")],
)  # fmt: skip
def test_lire_source(source, attendu):
    assert lire_source(source) == attendu


def test_source_de_connexion_lisible_depuis_le_pont(ouvrir):
    session, _, _ = ouvrir([init("none"), fin()])
    assert session.source_connexion == ""
    session.envoyer("Fais.")
    assert session.source_connexion == "abonnement"
    cle, _, _ = ouvrir([init("ANTHROPIC_API_KEY"), fin()])
    cle.envoyer("Fais.")
    assert cle.source_connexion == "clé API"


# --- Le vrai client du SDK, sur un faux exécutable `claude` -----------------------------

FAUX_CLI = r'''
import json, os, sys, threading
if "-v" in sys.argv[1:]:
    print("2.1.308 (Claude Code)")
    sys.exit(0)
with open(os.environ["FAUX_CLI_PID"], "a") as f:
    f.write(f"{os.getpid()}\n")
SESSION, BLOQUE = "UUID", os.environ.get("FAUX_CLI_MODE") == "bloque"
ATTEND_MODE = os.environ.get("FAUX_CLI_MODE") == "attend_mode"
verrou, interrompu, change = threading.Lock(), threading.Event(), threading.Event()
OPTION = "--permission-mode"
DEPART = sys.argv[sys.argv.index(OPTION) + 1] if OPTION in sys.argv else ""

def dire(message):
    with verrou:
        sys.stdout.write(json.dumps(message) + "\n")
        sys.stdout.flush()

def tour():
    dire({"type": "system", "subtype": "init", "session_id": SESSION, "apiKeySource": "none",
          "permissionMode": DEPART})
    for mot in ("Bon", "jour."):
        delta = {"type": "text_delta", "text": mot}
        dire({"type": "stream_event", "uuid": "s", "session_id": SESSION,
              "event": {"type": "content_block_delta", "index": 0, "delta": delta}})
    if BLOQUE:
        interrompu.wait()
    if ATTEND_MODE:  # le tour attend qu'un changement de mode soit accepté
        change.wait(5)
        dire({"type": "system", "subtype": "status", "session_id": SESSION,
              "permissionMode": "plan"})
    dire({"type": "result", "subtype": "success", "duration_ms": 1, "duration_api_ms": 1,
          "is_error": interrompu.is_set(), "num_turns": 1, "session_id": SESSION,
          "total_cost_usd": 0.25, "result": "Fini.",
          "usage": {"input_tokens": 100, "output_tokens": 20}})

for ligne in sys.stdin:
    message = json.loads(ligne)
    if message.get("type") == "control_request":
        demande = message["request"]
        if demande.get("subtype") == "interrupt":
            interrompu.set()
        if demande.get("subtype") == "set_permission_mode":
            with open(os.environ["FAUX_CLI_PID"] + ".modes", "a") as f:
                f.write(demande["mode"] + "\n")
            if demande["mode"] == "auto":
                dire({"type": "control_response", "response": {"subtype": "error",
                      "request_id": message["request_id"],
                      "error": "Cannot set permission mode to auto: "
                               "auto mode unavailable for this model"}})
                continue
            change.set()
        dire({"type": "control_response", "response": {"subtype": "success",
              "request_id": message["request_id"], "response": {}}})
    elif message.get("type") == "user":
        threading.Thread(target=tour, daemon=True).start()
'''.replace("UUID", UUID)


def vivant(pid):
    try:
        os.kill(pid, 0)
        with open(f"/proc/{pid}/stat") as f:
            return f.read().split()[2] != "Z"
    except (ProcessLookupError, FileNotFoundError):
        return False


@pytest.fixture
def vrai_client(tmp_path, ouvrir):
    """Ouvre une session sur le vrai `ClaudeSDKClient`, branché sur le faux exécutable."""
    script, pids = tmp_path / "claude", tmp_path / "pids"
    script.write_text(f"#!{sys.executable}\n{FAUX_CLI}", "utf-8")
    script.chmod(0o755)

    def ouvrir_vrai(mode="", **reglages):
        def fabrique(options):
            env = {"FAUX_CLI_PID": str(pids), "FAUX_CLI_MODE": mode}
            return ClaudeSDKClient(dataclasses.replace(options, cli_path=str(script), env=env))

        session, _, evenements = ouvrir(fabrique_client=fabrique, **reglages)
        return session, evenements, lambda: [int(p) for p in pids.read_text().split()]

    return ouvrir_vrai


def test_vrai_client_un_tour_complet(vrai_client):
    session, evenements, _ = vrai_client()
    resultat = session.envoyer("Salue.")
    assert (resultat.ok, resultat.texte, resultat.cout_usd, resultat.tokens) == (
        True, "Fini.", 0.25, 120
    )  # fmt: skip
    assert du_type(evenements, "texte") == ["Bon", "jour."]
    assert session.source_connexion == "abonnement"
    assert (session.session, session.reprise) == (UUID, True)


def test_vrai_client_l_arret_ne_laisse_pas_claude_code_vivant(vrai_client):
    session, evenements, lire_pids = vrai_client("bloque")
    fil, rendus = en_fond(session)
    assert attendre(lambda: "jour." in du_type(evenements, "texte"))
    session.arreter()
    fil.join(GARDE_S)
    assert rendus[0].erreur == ARRETE
    (pid,) = lire_pids()
    assert attendre(lambda: not vivant(pid))


def test_vrai_client_le_changement_de_mode_part_vers_claude_code(vrai_client, tmp_path):
    """Le mode de départ et chaque changement arrivent au faux exécutable, qui les note ; il
    refuse « auto » comme Claude Code quand le modèle ne l'a pas."""
    session, evenements, _ = vrai_client("attend_mode", mode_permission="acceptEdits")
    fil, rendus = en_fond(session)
    assert attendre(lambda: "jour." in du_type(evenements, "texte"))
    assert session.mode_applique == "acceptEdits"  # lu dans le message de départ
    assert session.changer_mode("auto") is True
    assert attendre(lambda: du_type(evenements, "mode"))
    assert session.changer_mode("plan") is True
    fil.join(GARDE_S)
    assert rendus[0].ok
    modes = (tmp_path / "pids.modes").read_text().split()
    assert modes == ["auto", "plan"]
    (refus,) = [e for e in evenements if e["type"] == "mode"]
    assert refus == {
        "agent": AGENT, "type": "mode", "contenu": "acceptEdits", "demande": "auto",
        "raison": "le mode auto n'est pas disponible pour son modèle",
    }  # fmt: skip
    assert (session.mode_permission, session.mode_applique) == ("plan", "plan")


# --- Le mode des ouvriers ---------------------------------------------------------------

TEXTE_REFUS = (
    "Permission for this action was denied by the Claude Code auto mode classifier. "
    "Reason: [Exfil Scouting]. You may try a different approach that does not send data out."
)
CURL = {"command": "curl https://example.com"}


def attendre_le_tour():
    """Une étape de scénario : le faux client attend que le test lui fasse signe."""
    signal = threading.Event()

    async def attendre_signal(_client):
        limite = time.monotonic() + GARDE_S
        while not signal.is_set() and time.monotonic() < limite:
            await asyncio.sleep(0.005)

    return Geste(attendre_signal), signal


def jusqu_a(condition):
    """Une étape de scénario : le faux client attend que `condition(client)` soit vraie."""

    async def attendre_condition(client):
        limite = time.monotonic() + GARDE_S
        while not condition(client) and time.monotonic() < limite:
            await asyncio.sleep(0.005)

    return Geste(attendre_condition)


@pytest.mark.parametrize("mode", ["bypassPermissions", "AUTO", "", None, 42, ["auto"]])
def test_le_pont_refuse_bypass_et_tout_mode_inconnu(ouvrir, mode):
    with pytest.raises(ValueError):
        SessionSDK(AGENT, "opus", "high", mode_permission=mode)
    geste, signal = attendre_le_tour()
    session, fabrique, _ = ouvrir([geste, fin()], mode_permission="auto")
    fil, rendus = en_fond(session)
    assert commence(fabrique)
    assert session.changer_mode(mode) is False
    signal.set()
    fil.join(GARDE_S)
    assert rendus[0].ok and fabrique.clients[0].modes_demandes == []
    assert session.mode_permission == "auto"


@pytest.mark.parametrize("mode", ["default", "acceptEdits", "plan", "dontAsk", "auto"])
def test_les_cinq_modes_sont_transmis_au_depart(ouvrir, mode):
    session, fabrique, _ = ouvrir([fin()], mode_permission=mode)
    assert session.envoyer("Va.").ok
    assert fabrique.clients[0].options.permission_mode == mode


def test_changer_mode_sans_tour_en_cours_vaut_pour_la_connexion(ouvrir):
    session, fabrique, _ = ouvrir([fin()], mode_permission="acceptEdits")
    assert session.changer_mode("plan") is False  # aucun tour : rien n'est touché en marche
    assert session.envoyer("Va.").ok
    client = fabrique.clients[0]
    assert client.options.permission_mode == "plan" and client.modes_demandes == []


def test_changer_mode_pendant_un_tour_part_vers_le_client_sans_bloquer(ouvrir):
    session, fabrique, evenements = ouvrir(
        [init(mode="acceptEdits"), jusqu_a(lambda c: c.modes), fin()],
        mode_permission="acceptEdits", client={"lent": {"mode": 0.3}},
    )  # fmt: skip
    fil, rendus = en_fond(session)
    assert attendre(lambda: session.mode_applique == "acceptEdits")
    debut = time.monotonic()
    assert session.changer_mode("dontAsk") is True
    assert time.monotonic() - debut < 0.1  # l'appelant n'attend pas Claude Code
    fil.join(GARDE_S)
    assert rendus[0].ok
    client = fabrique.clients[0]
    assert client.modes == ["dontAsk"]
    assert client.fils_modes[0].name == f"atelier-sdk-{AGENT}"  # dans la boucle de la session
    assert (session.mode_permission, session.mode_applique) == ("dontAsk", "dontAsk")
    assert du_type(evenements, "mode") == []  # un changement demandé et réussi ne dit rien


def test_un_changement_refuse_garde_le_mode_d_avant_et_dit_le_mode_reel(ouvrir):
    session, fabrique, evenements = ouvrir(
        [init(mode="acceptEdits"), jusqu_a(lambda c: c.modes_demandes), texte("Je continue."),
         fin()],
        mode_permission="acceptEdits", client={"sans_auto": True},
    )  # fmt: skip
    fil, rendus = en_fond(session)
    assert attendre(lambda: session.mode_applique == "acceptEdits")
    assert session.changer_mode("auto") is True
    fil.join(GARDE_S)
    assert rendus[0].ok and rendus[0].texte == "Fini."  # rien d'autre ne casse
    assert attendre(lambda: du_type(evenements, "mode"))
    (evenement,) = [e for e in evenements if e["type"] == "mode"]
    assert evenement == {
        "agent": AGENT, "type": "mode", "contenu": "acceptEdits", "demande": "auto",
        "raison": "le mode auto n'est pas disponible pour son modèle",
    }  # fmt: skip
    assert (session.mode_permission, session.mode_applique) == ("acceptEdits", "acceptEdits")


def test_changer_mode_sur_une_session_qui_s_arrete_ou_se_ferme(ouvrir):
    session, fabrique, _ = ouvrir([BLOQUE])
    fil, rendus = en_fond(session)
    assert commence(fabrique)
    session.arreter()
    assert session.changer_mode("plan") is False
    fil.join(GARDE_S)
    assert rendus[0].erreur == ARRETE
    session.fermer()
    assert session.changer_mode("auto") is False
    assert fabrique.clients[0].modes_demandes == []


def test_le_plus_recent_de_deux_changements_l_emporte(ouvrir):
    session, fabrique, _ = ouvrir(
        [jusqu_a(lambda c: c.modes[-1:] == ["auto"]), fin()], client={"lent": {"mode": 0.1}}
    )
    fil, rendus = en_fond(session)
    assert commence(fabrique)
    assert session.changer_mode("plan") and session.changer_mode("auto")
    fil.join(GARDE_S)
    assert rendus[0].ok and session.mode_permission == "auto"
    assert fabrique.clients[0].modes[-1] == "auto"


def test_un_changement_pendant_la_connexion_est_applique_apres_elle(ouvrir):
    session, fabrique, _ = ouvrir([jusqu_a(lambda c: c.modes), fin()], mode_permission="default",
                                  client={"lent": {"connect": 0.3}})  # fmt: skip
    fil, rendus = en_fond(session)
    assert attendre(lambda: fabrique.clients)
    client = fabrique.clients[0]
    assert not client.connecte  # le client est créé avec l'ancien mode, et se connecte
    assert session.changer_mode("auto") is True
    fil.join(GARDE_S)
    assert rendus[0].ok
    assert client.options.permission_mode == "default" and client.modes == ["auto"]
    assert session.mode_permission == "auto"


def test_une_demande_ouverte_au_guichet_survit_au_changement_de_mode(ouvrir):
    guichet = Guichet(delai_s=GARDE_S)
    session, fabrique, _ = ouvrir(
        [Permission("Bash", CURL), fin()], guichet=guichet, mode_permission="acceptEdits"
    )
    fil, rendus = en_fond(session)
    try:
        assert attendre(lambda: guichet.ouvertes())
        assert session.changer_mode("auto") is True
        client = fabrique.clients[0]
        assert attendre(lambda: client.modes == ["auto"])
        (demande,) = guichet.ouvertes()  # toujours ouverte
        assert guichet.repondre(demande["id"], "une_fois")
        fil.join(GARDE_S)
    finally:
        guichet.annuler(AGENT)
    assert rendus[0].ok and client.decisions == [PermissionResultAllow()]


def test_en_mode_auto_une_demande_arrive_au_guichet_et_la_reponse_revient(ouvrir):
    """L'arbitre en pause : Claude Code redemande par `can_use_tool`, donc par le guichet."""
    guichet = FauxGuichet(Reponse("non", message="Pas de réseau."))
    session, fabrique, evenements = ouvrir(
        [init(mode="auto"), Permission("Bash", CURL), fin()], guichet=guichet,
        mode_permission="auto",
    )  # fmt: skip
    assert session.envoyer("Va.").ok
    assert guichet.demandes == [(AGENT, "Bash", CURL)]
    assert fabrique.clients[0].decisions == [PermissionResultDeny(message="Pas de réseau.")]
    assert du_type(evenements, "attente") == ["Lance curl https://example.com"]


# --- Le mode réel -------------------------------------------------------------------------


def modes_dits(evenements):
    return [(e["contenu"], e["demande"], e["raison"]) for e in evenements if e["type"] == "mode"]


def test_le_depart_dans_le_mode_demande_ne_dit_rien(ouvrir):
    session, _, evenements = ouvrir([init(mode="plan"), fin()], mode_permission="plan")
    assert session.envoyer("Va.").ok
    assert session.mode_applique == "plan" and modes_dits(evenements) == []


def test_le_mode_auto_indisponible_au_depart_est_dit(ouvrir):
    session, _, evenements = ouvrir([init(mode="default"), fin()], mode_permission="auto")
    assert session.envoyer("Va.").ok
    assert session.mode_applique == "default"
    assert modes_dits(evenements) == [
        ("default", "auto", "le mode auto n'est pas disponible pour son modèle")
    ]


def test_une_retombee_en_cours_de_session_est_dite_une_fois_par_changement(ouvrir):
    session, _, evenements = ouvrir(
        [init(mode="auto"), statut("default"), statut("default"), statut("auto"), fin()],
        mode_permission="auto",
    )
    assert session.envoyer("Va.").ok
    assert modes_dits(evenements) == [("default", "auto", ""), ("auto", "auto", "")]
    assert session.mode_applique == "auto"


def test_la_fin_de_la_repetition_est_dite_avec_sa_raison(ouvrir):
    session, _, evenements = ouvrir([init(mode="plan"), statut("default"), fin()],
                                    mode_permission="plan")  # fmt: skip
    assert session.envoyer("Va.").ok
    assert modes_dits(evenements) == [
        ("default", "plan", "il a fini sa répétition et passe à l'exécution de son plan")
    ]


def test_un_statut_qui_accompagne_un_changement_demande_ne_dit_rien(ouvrir):
    session, _, evenements = ouvrir(
        [init(mode="acceptEdits"), jusqu_a(lambda c: c.modes_demandes), statut("auto"),
         jusqu_a(lambda c: c.modes), statut("auto"), fin()],
        mode_permission="acceptEdits", client={"lent": {"mode": 0.1}},
    )  # fmt: skip
    fil, rendus = en_fond(session)
    assert attendre(lambda: session.mode_applique == "acceptEdits")
    assert session.changer_mode("auto") is True
    fil.join(GARDE_S)
    assert rendus[0].ok and modes_dits(evenements) == []
    assert session.mode_applique == "auto"


def test_un_message_de_mode_illisible_ne_casse_rien(ouvrir):
    illisibles = [SystemMessage(subtype="status", data={"permissionMode": 42}),
                  SystemMessage(subtype="status", data={}), statut("")]  # fmt: skip
    session, _, evenements = ouvrir([*illisibles, fin()], mode_permission="auto")
    assert session.envoyer("Va.").ok
    assert session.mode_applique == "" and modes_dits(evenements) == []


# --- Les refus de l'arbitre ---------------------------------------------------------------


def refus_dits(evenements):
    return du_type(evenements, "refus")


def test_un_refus_de_l_arbitre_est_annonce_aussitot_et_une_seule_fois(ouvrir):
    autre = {"tool_name": "WebFetch", "tool_use_id": "t9", "tool_input": {"url": "https://x.y"}}
    denials = [{"tool_name": "Bash", "tool_use_id": "t7", "tool_input": CURL}, autre, autre]
    session, _, evenements = ouvrir(
        [init(mode="auto"), outil("Bash", CURL, "t7"), resultat_outil("t7", TEXTE_REFUS),
         texte("Je fais autrement."), fin(refus=denials)],
        mode_permission="auto",
    )  # fmt: skip
    assert session.envoyer("Va.").ok
    assert refus_dits(evenements) == [
        "Lance curl https://example.com (règle Exfil Scouting)",
        "WebFetch (raison non précisée)",
    ]
    types = [e["type"] for e in evenements]
    assert types.index("refus") < types.index("texte")  # aussitôt, pas en fin de tour
    (premier, _) = [e for e in evenements if e["type"] == "refus"]
    assert (premier["outil"], premier["raison"]) == (
        "Lance curl https://example.com", "règle Exfil Scouting"
    )  # fmt: skip


def test_un_refus_en_blocs_de_texte_est_reconnu(ouvrir):
    blocs = [{"type": "text", "text": TEXTE_REFUS}]
    session, _, evenements = ouvrir(
        [init(mode="auto"), outil("Bash", CURL, "t3"), resultat_outil("t3", blocs), fin()],
        mode_permission="auto",
    )  # fmt: skip
    session.envoyer("Va.")
    assert refus_dits(evenements) == ["Lance curl https://example.com (règle Exfil Scouting)"]


def test_un_echec_ordinaire_n_est_jamais_un_refus_de_l_arbitre(ouvrir):
    guichet = FauxGuichet(Reponse("non"))
    denials = [{"tool_name": "Bash", "tool_use_id": "t1", "tool_input": CURL}]
    session, _, evenements = ouvrir(
        [init(mode="auto"),
         outil("Bash", {"command": "npm test"}, "t2"),
         resultat_outil("t2", "Exit code 1\nnpm ERR! Test failed."),
         outil("Grep", {"pattern": "classifier"}, "t4"),
         resultat_outil("t4", TEXTE_REFUS, erreur=False),  # un texte lu, pas un refus
         Permission("Bash", CURL),  # refusé par la personne, au guichet
         resultat_outil("t1", "La personne responsable a refusé cet outil."),
         fin(refus=denials)],
        mode_permission="auto", guichet=guichet,
    )  # fmt: skip
    assert session.envoyer("Va.").ok
    assert refus_dits(evenements) == []


@pytest.mark.parametrize("mode", ["default", "acceptEdits", "plan", "dontAsk"])
def test_hors_du_mode_auto_les_refus_du_tour_ne_sont_pas_de_l_arbitre(ouvrir, mode):
    denials = [{"tool_name": "Bash", "tool_use_id": "t7", "tool_input": CURL}]
    session, _, evenements = ouvrir([init(mode=mode), fin(refus=denials)], mode_permission=mode)
    assert session.envoyer("Va.").ok
    assert refus_dits(evenements) == []


def test_un_refus_sans_identifiant_ou_mal_forme_ne_casse_rien(ouvrir):
    denials = [{"tool_name": "Bash", "tool_input": CURL}, "illisible", None,
               {"tool_name": "Bash", "tool_use_id": "t5", "tool_input": ["pas", "un", "objet"]}]
    session, _, evenements = ouvrir([init(mode="auto"), fin(refus=denials)],
                                    mode_permission="auto")  # fmt: skip
    assert session.envoyer("Va.").ok
    assert refus_dits(evenements) == ["Lance (raison non précisée)"]


def test_la_memoire_des_appels_et_des_refus_est_bornee(ouvrir):
    scenario = [outil("Read", {"file_path": f"f{n}.py"}, f"a{n}") for n in range(600)]
    scenario += [resultat_outil(f"a{n}", TEXTE_REFUS) for n in range(600)]
    session, _, evenements = ouvrir([init(mode="auto"), *scenario, fin()],
                                    mode_permission="auto")  # fmt: skip
    assert session.envoyer("Va.").ok
    assert len(session._appels) <= 256 and len(session._refus) <= 256
    assert len(refus_dits(evenements)) == 600


@pytest.mark.parametrize(
    "texte_lu, attendu",
    [
        (TEXTE_REFUS, "règle Exfil Scouting"),
        ("Permission for this action was denied by the Claude Code auto mode classifier. "
         "Reason: [Data Exfiltration].", "règle Data Exfiltration"),
        ("Permission for this action was denied by the Claude Code auto mode classifier.",
         "Permission for this action was denied by the Claude Code auto mode classifier."),
        ("Exit code 1", ""),
        ("Permission denied (publickey).", ""),
        (None, ""),
        (42, ""),
    ],
)  # fmt: skip
def test_lire_refus(texte_lu, attendu):
    assert lire_refus(texte_lu) == attendu


def test_raison_d_echec_et_texte_du_resultat():
    from atelier.sdk import raison_d_echec, texte_du_resultat

    assert raison_d_echec(Exception(INDISPONIBLE_SDK)) == (
        "le mode auto n'est pas disponible pour son modèle"
    )
    assert raison_d_echec(TimeoutError()) == "Claude Code n'a pas pris le changement (TimeoutError)"
    assert raison_d_echec(Exception("Control request timeout: set_permission_mode")) == (
        "Claude Code n'a pas pris le changement (Control request timeout: set_permission_mode)"
    )
    assert texte_du_resultat("a") == "a"
    assert texte_du_resultat([{"type": "text", "text": "a"}, "x", {"text": "b"}]) == "a\nb"
    assert texte_du_resultat(None) == "" and texte_du_resultat(42) == ""


def test_un_changement_trop_lent_ne_bloque_pas_la_boucle_et_reste_borne(ouvrir):
    session, fabrique, evenements = ouvrir(
        [init(mode="acceptEdits"), jusqu_a(lambda c: c.modes_demandes), texte("pendant"), fin()],
        mode_permission="acceptEdits", client={"lent": {"mode": 2}},
    )  # fmt: skip
    session.delai_mode_s = 0.2
    fil, rendus = en_fond(session)
    assert attendre(lambda: session.mode_applique == "acceptEdits")
    assert session.changer_mode("plan") is True
    fil.join(GARDE_S)
    assert rendus[0].ok and fabrique.clients[0].modes == []  # le tour a fini sans l'attendre
    assert attendre(lambda: modes_dits(evenements), 1)
    assert modes_dits(evenements) == [
        ("acceptEdits", "plan", "Claude Code n'a pas pris le changement (TimeoutError)")
    ]
    assert session.mode_permission == "acceptEdits"


def test_la_phrase_du_refus_au_milieu_d_une_sortie_ou_hors_du_mode_auto_n_est_pas_un_refus(
    ouvrir,
):
    """Un grep ou un test en échec peut afficher la phrase du refus (elle est dans ce dépôt) ;
    et sans mode auto pendant le tour, il n'y a pas d'arbitre pour refuser."""
    grep = {"command": "grep -rn classifier atelier tests && pytest -q"}
    sortie = f"Exit code 1\ntests/test_sdk.py:957:    {TEXTE_REFUS}\nFAILED tests/test_sdk.py::x"
    for mode in ("auto", "acceptEdits"):
        session, _, evenements = ouvrir(
            [init(mode=mode), outil("Bash", grep, "b1"), resultat_outil("b1", sortie), fin()],
            mode_permission=mode,
        )
        assert session.envoyer("Va.").ok
        assert refus_dits(evenements) == []
    for mode in ("acceptEdits", "default", "plan", "dontAsk"):
        session, _, evenements = ouvrir(
            [init(mode=mode), outil("Bash", CURL, "c1"), resultat_outil("c1", TEXTE_REFUS), fin()],
            mode_permission=mode,
        )
        assert session.envoyer("Va.").ok
        assert refus_dits(evenements) == []
    # Le même texte, en tête, quand le mode auto vaut : c'est un refus.
    session, _, evenements = ouvrir(
        [init(mode="auto"), outil("Bash", CURL, "c1"), resultat_outil("c1", "  " + TEXTE_REFUS),
         fin()],
        mode_permission="auto",
    )  # fmt: skip
    assert session.envoyer("Va.").ok
    assert refus_dits(evenements) == ["Lance curl https://example.com (règle Exfil Scouting)"]
