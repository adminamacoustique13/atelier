"""Tests du pont (tâche M4) : le coût juste de chaque tour, et la nature de chaque échec.

Le faux client prend du temps à chaque étape et se conduit comme le vrai SDK sur ce qui compte
ici : une connexion sert plusieurs tours et annonce un coût cumulé depuis le début de la session ;
`receive_response` s'arrête au message de fin ; une interruption met fin au travail, puis Claude
Code envoie son message de fin, ou rien du tout. Aucun appel réel à Claude, aucun réseau.
"""

import asyncio
import threading
import time
from dataclasses import dataclass, field

import pytest

pytest.importorskip("claude_agent_sdk")

from claude_agent_sdk import (  # noqa: E402
    AssistantMessage,
    ClaudeAgentOptions,
    ResultError,
    ResultMessage,
    TextBlock,
)

from atelier import agents  # noqa: E402
from atelier import sdk as pont  # noqa: E402
from atelier.agents import (  # noqa: E402
    LIMITE_ATTEINTE,
    REPRISE_IMPOSSIBLE,
    SURCHARGE,
    AgentClaude,
    Resultat,
)
from atelier.sdk import SessionSDK  # noqa: E402
from tests.test_sdk import (  # noqa: E402
    OPUS_CHARGE,
    SERVEUR_LIMITE,
    UUID,
    VRAIE_LIMITE,
    attendre,
    erreur_api,
    init,
    limite,
    texte,
)

GARDE_S = 5  # aucun test ne doit pouvoir attendre plus longtemps que ça
DELAI_S = 0.15  # le délai d'interruption des tests où le message de fin ne vient pas
MARGE_S = 0.5  # ce que la boucle et les fils peuvent ajouter à un délai, machine chargée
ARRETE = "Arrêté par la personne responsable."
SANS_REPONSE = "Claude Code s'est arrêté sans répondre."
HORS_DELAI_S = 0.1  # le délai de l'agent des tests de délai dépassé
HORS_DELAI = "L'agent n'a pas fini dans le délai de 0.1 secondes."
REPRISE = {"session": UUID, "reprise": True, "reprise_exigee": True}
OUVRIER = {"role": "ouvrier", "tache": "B", "tentative": 1}
# Des textes de Claude Code 2.1.308, lus dans son programme.
AUTH = "Failed to authenticate: OAuth session expired and could not be refreshed"
JETON = ("API Error: Failed to refresh OAuth token: another Claude Code process is refreshing "
         "it or exited mid-refresh. This is usually transient; retry in a minute")  # fmt: skip
RESEAU = ("API Error: Connection to the API was lost (ECONNRESET). This is usually temporary "
          "— try again.")  # fmt: skip


# --- Messages du SDK ------------------------------------------------------------------------


def fin(cumul=0.1, erreur=False, texte_lu="Fini.", sous_type="success", statut=None,
        erreurs=None, session=UUID):  # fmt: skip
    """Le message de fin d'un tour ; `cumul` est le coût cumulé de la session."""
    return ResultMessage(
        subtype=sous_type, duration_ms=5, duration_api_ms=4, is_error=erreur, num_turns=1,
        session_id=session, total_cost_usd=cumul, result=texte_lu,
        usage={"input_tokens": 100, "output_tokens": 20}, errors=erreurs,
        api_error_status=statut,
    )  # fmt: skip


def interrompu(cumul):
    """Le message de fin que Claude Code envoie après une interruption."""
    message = fin(cumul, erreur=True, texte_lu=None, sous_type="error_during_execution")
    message.terminal_reason = "aborted_streaming"
    return message


def reponse(texte_lu="Je travaille.", erreur=None):
    """Une réponse de l'assistant ; avec `erreur`, celle par laquelle Claude Code dit une erreur."""
    return AssistantMessage(content=[TextBlock(text=texte_lu)], model="opus", error=erreur)


# --- Le faux client -------------------------------------------------------------------------

TRAVAIL = object()  # étape : l'agent travaille jusqu'à ce qu'on l'interrompe
DUREES = {"connect": 0.005, "query": 0.002, "etape": 0.002, "fin": 0.02, "interrupt": 0.005,
          "disconnect": 0.005}  # fmt: skip


class ClientMesure:
    """Un faux client SDK : un scénario par demande (`tours`), sur une même connexion. Les
    cumuls des messages de fin sont écrits dans les scénarios, comme Claude Code les annonce.

    `apres_interruption` : les messages que Claude Code envoie une fois interrompu (vide : il
    n'envoie rien, pas même son message de fin). Chaque étape prend du temps (`lent`).
    """

    def __init__(self, options, tours, apres_interruption=(), lent=None):
        self.options, self.tours = options, [list(tour) for tour in tours]
        self.apres_interruption = list(apres_interruption)
        self.lent = {**DUREES, **(lent or {})}
        self.consignes, self.interruptions, self.deconnecte = [], 0, False
        self.au_travail = threading.Event()  # posé quand l'agent attend d'être interrompu
        self._interrompu = asyncio.Event()
        self._tour = []

    async def connect(self):
        await asyncio.sleep(self.lent["connect"])

    async def query(self, consigne):
        await asyncio.sleep(self.lent["query"])
        self.consignes.append(consigne)
        self._tour = self.tours.pop(0) if self.tours else []

    async def receive_response(self):
        """Comme le vrai : les messages du tour, jusqu'au message de fin compris."""
        for etape in self._tour:
            await asyncio.sleep(self.lent["etape"])
            if isinstance(etape, BaseException):
                raise etape
            if etape is TRAVAIL:
                async for message in self._jusqu_a_l_interruption():
                    yield message
                return
            yield etape
            if isinstance(etape, ResultMessage):
                return

    async def _jusqu_a_l_interruption(self):
        self.au_travail.set()
        await self._interrompu.wait()
        for message in self.apres_interruption:
            await asyncio.sleep(self.lent["fin"])
            yield message
            if isinstance(message, ResultMessage):
                return
        await asyncio.Event().wait()  # plus rien ne vient

    async def interrupt(self):
        self.interruptions += 1
        await asyncio.sleep(self.lent["interrupt"])
        self._interrompu.set()

    async def disconnect(self):
        await asyncio.sleep(self.lent["disconnect"])
        self.deconnecte = True


class FabriqueMesure:
    """Rend un nouveau faux client à chaque connexion, avec les réglages suivants."""

    def __init__(self, *connexions):
        self.connexions, self.clients = list(connexions), []

    def __call__(self, options):
        reglages = self.connexions[min(len(self.clients), len(self.connexions) - 1)]
        self.clients.append(ClientMesure(options, **reglages))
        return self.clients[-1]


@pytest.fixture
def ouvrir():
    """Ouvre des sessions sur une fabrique de faux clients ; les ferme toutes à la fin."""
    sessions = []

    def ouvrir_session(*connexions, interruption_s=None, **reglages):
        fabrique = FabriqueMesure(*connexions)
        parametres = {"agent": "A-ouvrier-1", "modele": "opus", "effort": "high",
                      "fabrique_client": fabrique, "delai_max_s": GARDE_S}  # fmt: skip
        session = SessionSDK(**{**parametres, **reglages})
        session.delai_fin_s = None  # ici, l'attente du message de fin est celle du produit
        if interruption_s is not None:
            session.delai_interruption_s = interruption_s
        sessions.append(session)
        return session, fabrique

    yield ouvrir_session
    for session in sessions:
        session.fermer()


def arreter_en_cours(session, fabrique, consigne="Travaille."):
    """Lance un tour, attend que l'agent travaille et l'arrête.

    Rend le résultat et le temps écoulé entre l'arrêt et la main rendue.
    """
    rendus = []
    fil = threading.Thread(target=lambda: rendus.append(session.envoyer(consigne)), daemon=True)
    fil.start()
    assert attendre(lambda: fabrique.clients and fabrique.clients[-1].au_travail.is_set())
    debut = time.monotonic()
    session.arreter()
    fil.join(GARDE_S)
    duree = time.monotonic() - debut
    assert not fil.is_alive()
    return rendus[0], duree


# --- Critère 1 : le coût par tour -----------------------------------------------------------


def test_une_connexion_qui_sert_plusieurs_demandes_compte_chaque_tour_une_fois(ouvrir):
    """Le SDK annonce un cumul : chaque tour en rend sa part. Un cumul qui n'augmente pas,
    absent ou qui baisse rend 0, et un cumul qui baisse (un résultat remis à zéro) ne baisse
    pas la référence : le tour suivant ne recompte pas les précédents."""
    tours = [[init(), texte("a"), reponse(), fin(0.10)], [fin(0.25)], [fin(0.25)], [fin(None)],
             [fin(0.0)], [fin(0.30)]]  # fmt: skip
    session, fabrique = ouvrir({"tours": tours})
    rendus = [session.envoyer(f"Demande {n}.") for n in range(len(tours))]
    assert [r.cout_usd for r in rendus] == [0.10, 0.15, 0.0, 0.0, 0.0, 0.05]
    assert all(r.ok and r.nature == "" and not r.cout_incomplet for r in rendus)
    assert len(fabrique.clients) == 1  # une seule connexion a servi toutes les demandes


def test_une_connexion_neuve_part_de_zero_ou_du_total_de_la_session_reprise(ouvrir):
    """Claude Code compte depuis le début de la session, et une session reprise repart du
    total qu'elle a gardé. Après une coupure, la connexion suivante reprend la session : son
    premier cumul porte les tours d'avant, et la dépense du tour coupé, qu'on n'avait pas vue
    (ce tour-là rendait un coût incomplet). Une session neuve, elle, part de zéro."""
    session, fabrique = ouvrir(
        {"tours": [[init(), fin(0.25)], [reponse(), RuntimeError("le CLI est tombé")]]},
        {"tours": [[init(), fin(0.40)], [RuntimeError("le CLI est retombé")]]},
        {"tours": [[fin(0.05)]]},
    )
    assert session.envoyer("Un.").cout_usd == 0.25
    coupe = session.envoyer("Deux.")
    assert (coupe.ok, coupe.cout_usd, coupe.cout_incomplet) == (False, 0.0, True)
    assert attendre(lambda: fabrique.clients[0].deconnecte)
    troisieme = session.envoyer("Trois.")
    assert len(fabrique.clients) == 2 and fabrique.clients[1].options.resume == UUID
    assert (troisieme.cout_usd, troisieme.cout_incomplet) == (0.15, False)
    # Coupé avant toute réponse de l'assistant : rien n'a été dépensé, le coût est complet.
    assert session.envoyer("Quatre.").cout_incomplet is False
    # L'appelant ouvre une session neuve sur le même pont : son cumul part de zéro.
    session.session, session.reprise = "une-autre-session", False
    assert session.envoyer("Cinq.").cout_usd == 0.05
    assert fabrique.clients[2].options.session_id == "une-autre-session"
    neuve, _ = ouvrir({"tours": [[init(), fin(0.30)]]})  # un autre pont, une session neuve
    assert neuve.envoyer("Un.").cout_usd == 0.30


AUTRE = "1c2d3e4f-5a6b-4c7d-8e9f-0a1b2c3d4e5f"  # une autre session Claude Code


def agent_sur(*cumuls):
    """Un `AgentClaude` dont chaque appel ouvre un pont neuf, qui annonce le cumul suivant."""
    fabrique = FabriqueMesure(*({"tours": [[init(), fin(c)]]} for c in cumuls))
    return AgentClaude({}, delai_max_s=GARDE_S, fabrique_client=fabrique), fabrique


def test_converser_par_trois_ponts_compte_chaque_message_une_fois():
    """Chaque message de la conversation ouvre un pont neuf, qui reprend la même session : il
    rend la différence avec le dernier cumul vu pour elle, pas le total de la conversation."""
    agent, fabrique = agent_sur(0.10, 0.25, 0.45)
    rendus = [agent.converser("Bonjour.", UUID, n > 0, None) for n in range(3)]
    assert [r.cout_usd for r in rendus] == [0.10, 0.15, 0.20]
    assert [c.options.resume for c in fabrique.clients] == [None, UUID, UUID]


def test_executer_qui_reprend_la_session_compte_chaque_tour_une_fois():
    agent, fabrique = agent_sur(0.10, 0.25, 0.45)
    rendus = [agent.executer("Consigne.", "opus", "high", None, False, OUVRIER)]
    rendus += [agent.executer("Reprends.", "opus", "high", None, False, OUVRIER, reprendre=UUID)
               for _ in range(2)]  # fmt: skip
    assert [(r.ok, r.cout_usd) for r in rendus] == [(True, 0.10), (True, 0.15), (True, 0.20)]
    assert [c.options.resume for c in fabrique.clients] == [None, UUID, UUID]


def test_deux_sessions_ne_se_melangent_pas(ouvrir):
    premiere, _ = ouvrir({"tours": [[fin(0.10)]]}, session=UUID)
    seconde, _ = ouvrir({"tours": [[fin(0.20, session=AUTRE)]]}, session=AUTRE)
    assert (premiere.envoyer("Un.").cout_usd, seconde.envoyer("Un.").cout_usd) == (0.10, 0.20)
    reprise_1, _ = ouvrir({"tours": [[fin(0.25)]]}, session=UUID, reprise=True)
    reprise_2, _ = ouvrir({"tours": [[fin(0.30, session=AUTRE)]]}, session=AUTRE, reprise=True)
    assert (reprise_1.envoyer("Deux.").cout_usd, reprise_2.envoyer("Deux.").cout_usd) == (
        0.15, 0.10
    )  # fmt: skip


def test_un_cumul_qui_retombe_rend_zero_et_ne_fait_pas_reculer_la_reference(ouvrir):
    couts = []
    for cumul, reprise in [(0.10, False), (0.45, True), (0.0, True), (None, True), (0.50, True)]:
        session, _ = ouvrir({"tours": [[fin(cumul)]]}, session=UUID, reprise=reprise)
        couts.append(session.envoyer("Fais.").cout_usd)
    assert couts == [0.10, 0.35, 0.0, 0.0, 0.05]


def test_deux_fils_sur_la_meme_session_ne_comptent_rien_deux_fois(ouvrir):
    """Deux ponts reprennent la même session en même temps ; puis le registre seul, sous la
    charge de huit fils : la somme des parts est toujours le plus haut cumul moins le départ."""
    depart, _ = ouvrir({"tours": [[fin(0.10)]]}, session=UUID)
    assert depart.envoyer("Un.").cout_usd == 0.10
    ponts = [ouvrir({"tours": [[fin(c)]]}, session=UUID, reprise=True)[0] for c in (0.25, 0.30)]
    rendus, depart_commun = [], threading.Barrier(len(ponts))

    def envoyer(pont_sdk):
        depart_commun.wait()
        rendus.append(pont_sdk.envoyer("Ensemble.").cout_usd)

    fils = [threading.Thread(target=envoyer, args=(p,), daemon=True) for p in ponts]
    for fil in fils:
        fil.start()
    for fil in fils:
        fil.join(GARDE_S)
    assert len(rendus) == 2 and round(sum(rendus), 9) == 0.20 and min(rendus) >= 0
    parts = []

    def annoncer(rang):
        for pas in range(200):
            parts.append(pont.cout_de_session("charge", (pas * 8 + rang + 1) / 100))

    fils = [threading.Thread(target=annoncer, args=(rang,), daemon=True) for rang in range(8)]
    for fil in fils:
        fil.start()
    for fil in fils:
        fil.join(GARDE_S)
    assert len(parts) == 1600 and min(parts) >= 0 and round(sum(parts), 6) == 16.0


def test_le_registre_des_cumuls_est_borne_et_oublie_les_plus_anciennes(monkeypatch):
    """Au-delà de sa taille, le registre oublie les sessions vues le moins récemment ; une
    session oubliée, comme après un redémarrage, compte son cumul entier (par excès)."""
    monkeypatch.setattr(pont._CUMULS, "maxi", 3)
    for nom in ("s1", "s2", "s3"):
        assert pont.cout_de_session(nom, 0.10, neuve=True) == 0.10
    assert pont.cout_de_session("s1", 0.15) == 0.05  # s1 redevient la plus récente
    assert pont.cout_de_session("s4", 0.10) == 0.10  # s2 sort
    assert pont.cout_de_session("s2", 0.30) == 0.30  # oubliée : son cumul entier
    assert pont.cout_de_session("s1", 0.20) == 0.05  # s1 est restée
    pont.vider_les_cumuls()  # comme un redémarrage de l'Atelier
    assert pont.cout_de_session("s1", 0.25) == 0.25
    # Une connexion qui ouvre la session part de zéro, même si l'identifiant est connu.
    assert pont.cout_de_session("s1", 0.05, neuve=True) == 0.05
    assert pont.cout_de_session("s1", 0.07) == 0.02


@pytest.mark.parametrize(
    "cumul, avant, attendu",
    [(0.10, 0.0, 0.10), (0.25, 0.10, 0.15), (0.25, 0.25, 0.0), (0.20, 0.25, 0.0),
     (None, 0.1, 0.0), (-1.0, 0.0, 0.0), (float("nan"), 0.0, 0.0), (float("inf"), 0.0, 0.0),
     (True, 0.0, 0.0), ("0.5", 0.0, 0.0), (3, 1.0, 2.0)],
)  # fmt: skip
def test_cout_du_tour(cumul, avant, attendu):
    assert pont.cout_du_tour(cumul, avant) == attendu


# --- Critère 2 : un tour fini en erreur porte son coût --------------------------------------


def test_un_tour_fini_en_erreur_porte_son_cout(ouvrir):
    raté = fin(0.18, erreur=True, texte_lu="Raté.")
    session, _ = ouvrir({"tours": [[fin(0.10)], [reponse(), raté]]})
    assert session.envoyer("Un.").cout_usd == 0.10
    resultat = session.envoyer("Deux.")
    assert (resultat.ok, resultat.erreur, resultat.tokens) == (False, "Raté.", 120)
    assert (resultat.cout_usd, resultat.cout_incomplet) == (0.08, False)
    lu = pont.lire_resultat(raté, [])
    assert (lu.ok, lu.erreur, lu.cout_usd) == (False, "Raté.", 0.18)


# --- Critère 3 : arrêt et délai dépassé -----------------------------------------------------


def test_un_arret_porte_le_cout_du_message_de_fin_qui_suit_l_interruption(ouvrir):
    session, fabrique = ouvrir(
        {"tours": [[fin(0.10)], [init(), reponse(), TRAVAIL]],
         "apres_interruption": [interrompu(0.42)]},
        interruption_s=3.0,
    )  # fmt: skip
    assert session.envoyer("Un.").cout_usd == 0.10
    resultat, duree = arreter_en_cours(session, fabrique)
    assert (resultat.ok, resultat.erreur, resultat.nature) == (False, ARRETE, "arret")
    assert (resultat.cout_usd, resultat.tokens, resultat.cout_incomplet) == (0.32, 120, False)
    assert duree < 1.0  # la main revient avec le message de fin, sans attendre les 3 s
    client = fabrique.clients[0]
    assert attendre(lambda: client.deconnecte)
    assert client.interruptions == 1  # interrompu une fois, pas une seconde à la déconnexion


@pytest.mark.parametrize("interruption", ["entendue", "sans_reponse"])
def test_un_arret_sans_message_de_fin_rend_la_main_dans_le_delai(ouvrir, interruption):
    """Claude Code n'envoie pas son message de fin, et peut-être pas même la réponse à
    l'interruption : la main revient au bout du délai, pas avant, pas beaucoup après."""
    lent = {"interrupt": 60} if interruption == "sans_reponse" else {}
    session, fabrique = ouvrir({"tours": [[init(), reponse(), TRAVAIL]], "lent": lent},
                               interruption_s=DELAI_S)  # fmt: skip
    resultat, duree = arreter_en_cours(session, fabrique)
    assert (resultat.erreur, resultat.nature) == (ARRETE, "arret")
    assert (resultat.cout_usd, resultat.cout_incomplet) == (0.0, True)
    assert DELAI_S - 0.03 <= duree < DELAI_S + MARGE_S
    assert attendre(lambda: fabrique.clients[0].deconnecte)


def test_l_attente_du_message_de_fin_se_regle_sans_raccourcir_l_interruption(ouvrir):
    """`delai_fin_s` borne l'attente du message de fin ; l'interruption, lente ici, garde sa
    propre borne (`delai_interruption_s`) et va jusqu'au bout, à part, avant la déconnexion."""
    session, fabrique = ouvrir({"tours": [[init(), reponse(), TRAVAIL]],
                                "lent": {"interrupt": 0.3}}, interruption_s=3.0)  # fmt: skip
    session.delai_fin_s = DELAI_S
    resultat, duree = arreter_en_cours(session, fabrique)
    assert (resultat.nature, resultat.cout_incomplet) == ("arret", True)
    assert DELAI_S - 0.03 <= duree < DELAI_S + MARGE_S  # pas les 3 s de l'interruption
    client = fabrique.clients[0]
    assert not client.deconnecte  # l'interruption (0,3 s) n'est pas finie : pas de coupure
    assert attendre(lambda: client.deconnecte) and client._interrompu.is_set()
    assert client.interruptions == 1


def test_un_arret_avant_le_depart_ne_lance_rien_et_ne_coute_rien(ouvrir, monkeypatch):
    """L'arrêt (la fermeture de la session) passe juste avant que le tour parte."""
    session, fabrique = ouvrir({"tours": [[fin(0.10)]]})
    demarrer, fermeurs = session._demarrer_boucle, []

    def fermer_puis_demarrer():
        fermeurs.append(threading.Thread(target=session.fermer, daemon=True))
        fermeurs[0].start()
        fermeurs[0].join(0.2)  # `fermer` pose son drapeau, puis attend la fin du tour
        return demarrer()

    monkeypatch.setattr(session, "_demarrer_boucle", fermer_puis_demarrer)
    resultat = session.envoyer("Fais.")
    fermeurs[0].join(GARDE_S)
    assert (resultat.erreur, resultat.nature) == (ARRETE, "arret")
    assert (resultat.cout_usd, resultat.cout_incomplet) == (0.0, False)
    assert fabrique.clients == []  # aucun Claude Code n'est parti


@pytest.mark.parametrize("avec_fin", [True, False])
def test_un_delai_depasse_attend_le_message_de_fin_au_plus_le_delai(ouvrir, avec_fin):
    apres = [interrompu(0.2)] if avec_fin else []
    session, fabrique = ouvrir(
        {"tours": [[init(), reponse(), TRAVAIL]], "apres_interruption": apres},
        delai_max_s=HORS_DELAI_S, interruption_s=3.0 if avec_fin else DELAI_S,
    )  # fmt: skip
    debut = time.monotonic()
    resultat = session.envoyer("Travaille.")
    duree = time.monotonic() - debut
    assert (resultat.ok, resultat.erreur, resultat.nature) == (False, HORS_DELAI, "delai")
    if avec_fin:
        assert (resultat.cout_usd, resultat.cout_incomplet) == (0.2, False)
        assert duree < HORS_DELAI_S + 1.0  # sans attendre les 3 s du délai d'interruption
    else:
        assert (resultat.cout_usd, resultat.cout_incomplet) == (0.0, True)
        assert HORS_DELAI_S + DELAI_S - 0.03 <= duree < HORS_DELAI_S + DELAI_S + MARGE_S
    assert attendre(lambda: fabrique.clients[0].deconnecte)
    assert fabrique.clients[0].interruptions == 1


def test_l_agent_arrete_rend_le_cout_et_la_nature_jusqu_au_bout(monkeypatch):
    """Par `AgentClaude.arreter`, comme le moteur : le pont, puis `_arrete`."""
    monkeypatch.setattr(SessionSDK, "delai_fin_s", None)  # l'attente du produit (2 s au plus)
    fabrique = FabriqueMesure({"tours": [[init(), reponse(), TRAVAIL]],
                               "apres_interruption": [interrompu(0.42)]})  # fmt: skip
    agent = AgentClaude({}, delai_max_s=GARDE_S, fabrique_client=fabrique)
    rendus = []
    fil = threading.Thread(daemon=True, target=lambda: rendus.append(
        agent.executer("Consigne.", "opus", "high", None, False, OUVRIER)))  # fmt: skip
    fil.start()
    assert attendre(lambda: fabrique.clients and fabrique.clients[0].au_travail.is_set())
    assert agent.arreter("B") is True
    fil.join(GARDE_S)
    (resultat,) = rendus
    assert (resultat.erreur, resultat.nature) == (ARRETE, "arret")
    assert (resultat.cout_usd, resultat.cout_incomplet) == (0.42, False)


# --- Critère 4 : la nature de chaque échec --------------------------------------------------


@dataclass
class Cas:
    """Un tour joué par la table : ses étapes, arrêté ou non ; l'erreur attendue, si dite."""

    etapes: list
    erreur: str | None = None
    apres: list = field(default_factory=list)
    arreter: bool = False
    reglages: dict = field(default_factory=dict)


def jouer(ouvrir, cas: Cas) -> Resultat:
    session, fabrique = ouvrir({"tours": [cas.etapes], "apres_interruption": cas.apres},
                               **cas.reglages)  # fmt: skip
    if cas.arreter:
        return arreter_en_cours(session, fabrique)[0]
    return session.envoyer("Fais.")


def erreur_de_fin(texte_lu, statut=None, sous_type="success", erreurs=None, cumul=0.1):
    return fin(cumul, erreur=True, texte_lu=texte_lu, sous_type=sous_type, statut=statut,
               erreurs=erreurs)  # fmt: skip


def panne_reseau(**reglages):
    return Cas([init(), reponse(RESEAU, "server_error"), erreur_de_fin(RESEAU)], **reglages)


BUDGET = erreur_de_fin(None, sous_type="error_max_budget_usd", cumul=0.5,
                       erreurs=["Reached maximum budget ($0.50)"])  # fmt: skip
TOURS_MAX = erreur_de_fin(None, sous_type="error_max_turns",
                          erreurs=["Reached maximum number of turns (40)"])  # fmt: skip
PAS_SU_FAIRE = erreur_de_fin(
    None,
    sous_type="error_during_execution",
    erreurs=["les tests réseau échouent : connection error, request timed out, socket hang up"],
)
TRAVAIL_INTERROMPU = Cas([init(), reponse(), TRAVAIL], apres=[interrompu(0.3)])

# Chaque ligne : la nature, un cas qui la porte, et des cas adverses (qui lui ressemblent, ou
# ressemblent à une autre nature) avec la nature qu'ils doivent porter.
TABLE = [
    ("arret", Cas(TRAVAIL_INTERROMPU.etapes, ARRETE, TRAVAIL_INTERROMPU.apres, arreter=True), [
        # une interruption que personne n'a demandée n'est pas un arrêt
        (Cas([init(), reponse(), interrompu(0.3)]), ""),
    ]),
    ("delai", Cas(TRAVAIL_INTERROMPU.etapes, HORS_DELAI, TRAVAIL_INTERROMPU.apres,
                  reglages={"delai_max_s": HORS_DELAI_S}), [
        # un délai dépassé côté API est une panne, pas le délai de l'agent
        (Cas([init(), erreur_de_fin("API Error: Request timed out.")]), "panne"),
    ]),
    ("limite", Cas([init(), limite("rejected"), erreur_de_fin("Limit reached")], LIMITE_ATTEINTE), [
        # une limite dont le texte ressemble à une panne reste une limite
        (Cas([init(), erreur_api(VRAIE_LIMITE),
              erreur_de_fin("API Error: 429 · this is usually temporary", 429)],
             LIMITE_ATTEINTE), "limite"),
        # une alerte de limite suivie d'un échec ordinaire n'est pas une limite
        (Cas([init(), limite("allowed_warning"), TOURS_MAX]), ""),
    ]),
    ("surcharge", Cas([init(), erreur_api(OPUS_CHARGE), erreur_de_fin(OPUS_CHARGE)], SURCHARGE), [
        # un vrai refus de limite l'emporte sur le texte d'une surcharge
        (Cas([init(), limite("rejected"), erreur_api(SERVEUR_LIMITE),
              erreur_de_fin(SERVEUR_LIMITE, 429)], LIMITE_ATTEINTE), "limite"),
        # une erreur 529 que Claude Code ne marque pas « rate_limit » est une panne
        (Cas([init(), reponse("API Error: Repeated 529 Overloaded errors", "server_error"),
              erreur_de_fin("API Error: Repeated 529 Overloaded errors", 529)]), "panne"),
    ]),
    ("reprise", Cas([erreur_de_fin("No conversation found with session ID", cumul=0.0)],
                    REPRISE_IMPOSSIBLE, reglages=REPRISE), [
        # la connexion perdue avant que la session réponde : la vraie cause est dite
        (Cas([reponse(AUTH, "authentication_failed"), erreur_de_fin(AUTH, 401)],
             REPRISE_IMPOSSIBLE, reglages=REPRISE), "connexion"),
        # une panne après que la session a répondu n'est pas une reprise impossible
        (panne_reseau(reglages=REPRISE), "panne"),
    ]),
    ("connexion", Cas([init(), reponse(AUTH, "authentication_failed"), erreur_de_fin(AUTH)],
                      AUTH), [
        # une panne passagère qui parle d'OAuth n'est pas une connexion perdue
        (Cas([init(), reponse(JETON, "server_error"), erreur_de_fin(JETON)]), "panne"),
    ]),
    ("connexion", Cas([init(), erreur_de_fin("API Error: 401 Unauthorized", 401)]), []),
    ("connexion", Cas([init(), erreur_de_fin("Invalid API key · Please run /login")]), []),
    ("connexion", Cas([RuntimeError("Not logged in · Please run /login")]), []),
    ("budget", Cas([init(), reponse(), BUDGET]), [
        (Cas([init(), reponse(), TOURS_MAX]), ""),  # trop de tours n'est pas le budget
    ]),
    ("budget", Cas([init(), ResultError("Claude Code returned an error result", data={
        "subtype": "error_max_budget_usd", "is_error": True})]), []),
    ("panne", panne_reseau(erreur=RESEAU), [
        (Cas([init(), reponse(), PAS_SU_FAIRE]), ""),  # un agent qui n'a pas su faire
        (Cas([init(), erreur_de_fin("API Error: 400 bad request · usually temporary", 400)]), ""),
        (Cas([init(), texte("Je commence")], SANS_REPONSE), ""),  # aucun message de fin
        (Cas([RuntimeError("boum")]), ""),  # une erreur que rien ne dit
    ]),
    ("panne", Cas([init(), erreur_de_fin("API Error: 500 Internal server error", 500)]), []),
    ("panne", Cas([init(), ResultError("Claude Code returned an error result", data={
        "subtype": "success", "is_error": True, "api_error_status": 503})]), []),
]  # fmt: skip


@pytest.mark.parametrize(
    "nature, cas, adverses", TABLE, ids=[f"{n}-{i}" for i, (n, _, _) in enumerate(TABLE)]
)
def test_chaque_echec_porte_sa_nature(ouvrir, nature, cas, adverses):
    resultat = jouer(ouvrir, cas)
    assert (resultat.ok, resultat.nature) == (False, nature)
    if cas.erreur is not None:  # les textes d'erreur ne changent pas
        assert resultat.erreur == cas.erreur
    for adverse, attendue in adverses:
        lu = jouer(ouvrir, adverse)
        assert (lu.ok, lu.nature) == (False, attendue), adverse
        if adverse.erreur is not None:
            assert lu.erreur == adverse.erreur


def test_un_budget_atteint_porte_son_cout(ouvrir):
    session, _ = ouvrir({"tours": [[fin(0.10)], [init(), reponse(), BUDGET]]})
    session.envoyer("Un.")
    resultat = session.envoyer("Deux.")
    assert (resultat.nature, resultat.cout_usd, resultat.cout_incomplet) == ("budget", 0.4, False)


@pytest.mark.parametrize(
    "fin_lue, erreur_api_lue, textes, attendue",
    [(None, "authentication_failed", (), "connexion"), (None, "server_error", (), "panne"),
     (None, "server_error", (AUTH,), "panne"), (None, "unknown", (RESEAU,), "panne"),
     (None, "invalid_request", (RESEAU,), ""), (None, None, ("Raté.",), ""),
     (BUDGET, None, (), "budget"), (TOURS_MAX, None, (), ""),
     (erreur_de_fin("x", 401), None, (), "connexion"), (erreur_de_fin("x", 502), None, (), "panne"),
     (erreur_de_fin("x", 408), None, (), "panne"), (erreur_de_fin("x", 404), None, (), ""),
     (erreur_de_fin("API Error: Request timed out."), None, (), "panne"),
     (PAS_SU_FAIRE, None, (), ""),
     (None, None, ("Not logged in · Please run /login",), "connexion")],
)  # fmt: skip
def test_lire_nature(fin_lue, erreur_api_lue, textes, attendue):
    assert pont.lire_nature(fin_lue, erreur_api_lue, *textes) == attendue


# --- Critère 5 : le plafond de dépense ------------------------------------------------------


def test_le_plafond_de_depense_devient_max_budget_usd(ouvrir):
    assert "max_budget_usd" in {f.name for f in ClaudeAgentOptions.__dataclass_fields__.values()}
    vus = {}
    reglages = {"transmis": {"budget_usd": 0.75}, "nul": {"budget_usd": 0}, "absent": {},
                "None": {"budget_usd": None}, "négatif": {"budget_usd": -1.0},
                "booléen": {"budget_usd": True}}  # fmt: skip
    for nom, reglage in reglages.items():
        session, fabrique = ouvrir({"tours": [[fin(0.1)]]}, **reglage)
        assert session.envoyer("Fais.").ok
        vus[nom] = fabrique.clients[0].options.max_budget_usd
    assert vus == {"transmis": 0.75, "nul": None, "absent": None, "None": None,
                   "négatif": None, "booléen": None}  # fmt: skip


@pytest.mark.parametrize(
    "budget, attendu",
    [(0.75, True), (2, True), (0, False), (0.0, False), (None, False), (-1, False),
     (True, False), ("1", False), (float("nan"), False), (float("inf"), False)],
)  # fmt: skip
def test_plafond_valide(budget, attendu):
    assert pont.plafond_valide(budget) is attendu


# --- Critère 6 : `_arrete` garde le coût et la nature ---------------------------------------


def test_l_arret_garde_le_cout_et_dit_sa_nature():
    marche = agents._Marche("A-ouvrier-1")
    rendu = Resultat(ok=True, texte="Fait.", cout_usd=0.42, tokens=120, cout_incomplet=True)
    assert agents._arrete(marche, rendu) is rendu  # sans arrêt demandé, rien ne change
    marche.arret.set()
    arrete = agents._arrete(marche, rendu)
    assert (arrete.ok, arrete.erreur, arrete.cout_usd, arrete.tokens) == (False, ARRETE, 0.42, 120)
    assert (arrete.nature, arrete.cout_incomplet) == ("arret", True)
    coupe = Resultat(ok=False, erreur=ARRETE, cout_usd=0.3, nature="arret", cout_incomplet=True)
    lu = agents._arrete(marche, coupe)
    assert (lu.cout_usd, lu.nature, lu.cout_incomplet) == (0.3, "arret", True)
