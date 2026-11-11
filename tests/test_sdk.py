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
    ToolUseBlock,
)

from atelier.agents import decrire_outil  # noqa: E402
from atelier.sdk import (  # noqa: E402
    SessionSDK,
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


def outil(nom, entree):
    return AssistantMessage(content=[ToolUseBlock(id="t1", name=nom, input=entree)], model="opus")


def init(source="none"):
    return SystemMessage(subtype="init", data={"apiKeySource": source, "session_id": UUID})


def fin(result="Fini.", is_error=False, cout=0.12):
    return ResultMessage(
        subtype="success", duration_ms=1, duration_api_ms=1, is_error=is_error, num_turns=1,
        session_id=UUID, total_cost_usd=cout, result=result,
        usage={"input_tokens": 100, "output_tokens": 20},
    )  # fmt: skip


# --- Faux client, fausse fabrique, faux guichet ----------------------------------------


@dataclass
class Permission:
    """Étape : le faux client demande une autorisation et attend la décision."""

    outil: str
    entree: dict
    detachee: bool = False  # comme le vrai SDK : la demande vit dans sa propre tâche


BLOQUE = object()  # étape du scénario : l'agent ne rend plus la main


class FauxClient:
    def __init__(self, options, scenario, lent=None, demande_pendant_interrupt=None):
        self.options, self.scenario, self.lent = options, scenario, lent or {}
        self.demande_pendant_interrupt = demande_pendant_interrupt
        self.consignes, self.decisions, self.fils, self.detachees = [], [], [], []
        self.connecte = self.interrompu = self.deconnecte = False
        self.travail_annule = self.deconnexion_annulee = False

    async def connect(self):
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
verrou, interrompu = threading.Lock(), threading.Event()

def dire(message):
    with verrou:
        sys.stdout.write(json.dumps(message) + "\n")
        sys.stdout.flush()

def tour():
    dire({"type": "system", "subtype": "init", "session_id": SESSION, "apiKeySource": "none"})
    for mot in ("Bon", "jour."):
        delta = {"type": "text_delta", "text": mot}
        dire({"type": "stream_event", "uuid": "s", "session_id": SESSION,
              "event": {"type": "content_block_delta", "index": 0, "delta": delta}})
    if BLOQUE:
        interrompu.wait()
    dire({"type": "result", "subtype": "success", "duration_ms": 1, "duration_api_ms": 1,
          "is_error": interrompu.is_set(), "num_turns": 1, "session_id": SESSION,
          "total_cost_usd": 0.25, "result": "Fini.",
          "usage": {"input_tokens": 100, "output_tokens": 20}})

for ligne in sys.stdin:
    message = json.loads(ligne)
    if message.get("type") == "control_request":
        if message["request"].get("subtype") == "interrupt":
            interrompu.set()
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

    def ouvrir_vrai(mode=""):
        def fabrique(options):
            env = {"FAUX_CLI_PID": str(pids), "FAUX_CLI_MODE": mode}
            return ClaudeSDKClient(dataclasses.replace(options, cli_path=str(script), env=env))

        session, _, evenements = ouvrir(fabrique_client=fabrique)
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
