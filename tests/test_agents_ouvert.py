"""Tâche M3 : l'ouvrier reste ouvert après avoir rendu la main.

Un faux client aux durées non nulles (`tests.doubles.FabriqueMesuree`) compte, pour chaque
chemin, les connexions, les demandes et les déconnexions. Aucun appel réel à Claude, aucun réseau.
"""

import os
import threading
import time
from pathlib import Path

import pytest

pytest.importorskip("claude_agent_sdk")

from atelier.agents import (  # noqa: E402
    OUVERTS_MAX,
    REPRISE_IMPOSSIBLE,
    AgentClaude,
    AgentSimule,
    lire_garde,
)
from atelier.guichet import ARRETE  # noqa: E402
from tests.doubles import SESSION_MESUREE, FabriqueMesuree  # noqa: E402

GARDE_S = 5  # aucun test ne doit pouvoir attendre plus longtemps que ça
OUVRIER = {"role": "ouvrier", "tache": "B", "tentative": 1}
VERIFICATEUR = {"role": "verificateur", "tache": "B", "tentative": 1}
SUITE = "Les contrôles sont rouges : corrige."
DELAI = "L'agent n'a pas fini dans le délai de"


def fils_de_session():
    return [f for f in threading.enumerate() if f.name.startswith("atelier-sdk-")]


def attendre(condition, delai=GARDE_S):
    limite = time.monotonic() + delai
    while not condition():
        if time.monotonic() > limite:
            return False
        time.sleep(0.005)
    return True


@pytest.fixture
def claude():
    """Fabrique des agents réels sur un faux client mesuré ; tous libérés à la fin du test.

    Seuls comptent les fils de session nés pendant le test : ceux d'autres fichiers ne jouent pas.
    """
    deja = set(fils_de_session())
    crees = []

    def creer(*tours, profil=None, delai_max_s=GARDE_S, **durees):
        fabrique = FabriqueMesuree(*tours, **durees)
        agent = AgentClaude(profil or {}, delai_max_s=delai_max_s, fabrique_client=fabrique)
        evenements = []
        agent.sur_evenement = evenements.append
        crees.append(agent)
        return agent, fabrique, evenements

    creer.deja = deja
    yield creer
    for agent in crees:
        agent.liberer_tous()
    nes = lambda: set(fils_de_session()) - deja  # noqa: E731
    assert attendre(lambda: not nes(), 2), nes()


def lancer(agent, contexte=OUVRIER, reprendre=None, consigne="Consigne.", lecture_seule=False,
           dossier=None, garder=True):  # fmt: skip
    """Un appel qui demande à garder l'ouvrier ouvert (`garder=False` : l'appel d'avant M3)."""
    return agent.executer(consigne, "opus", "high", dossier, lecture_seule, contexte,
                          reprendre=reprendre, garder_ouvert=garder)  # fmt: skip


def suivre(agent, session, contexte=OUVRIER, consigne=SUITE, garder=True):
    return lancer(agent, contexte, reprendre=session, consigne=consigne, garder=garder)


def ancien_appel(agent, contexte=OUVRIER, reprendre=None, consigne="Consigne."):
    """L'appel exact d'avant la tâche M3, sans le paramètre `garder_ouvert`."""
    return agent.executer(consigne, "opus", "high", None, False, contexte, reprendre=reprendre)


def en_fond(fonction, *arguments, **nommes):
    rendus = []
    fil = threading.Thread(target=lambda: rendus.append(fonction(*arguments, **nommes)),
                           daemon=True)  # fmt: skip
    fil.start()
    return fil, rendus


def comptes(fabrique):
    return fabrique.connexions, fabrique.demandes, fabrique.deconnexions


def fins(evenements):
    return [e for e in evenements if e["type"] == "fin"]


# --- 1 et 2 : la suite donnée à l'ouvrier ouvert ------------------------------------------------


def test_la_suite_part_a_l_ouvrier_ouvert_dans_la_meme_conversation(claude):
    agent, fabrique, evenements = claude()

    premier = lancer(agent)
    assert premier.ok and premier.ouverte and premier.session == SESSION_MESUREE
    assert comptes(fabrique) == (1, 1, 0)  # rendu, et toujours connecté

    suite = suivre(agent, premier.session)
    assert suite.ok and suite.ouverte and suite.texte == "Fait 2."
    assert suite.session == SESSION_MESUREE  # sans `init` au second tour : lue dans la fin
    assert comptes(fabrique) == (1, 2, 0)  # une seule connexion, deux demandes
    assert fabrique.clients[0].demandes == ["Consigne.", SUITE]
    assert fabrique.clients[0].options.resume is None  # rien n'a été repris : la même conversation
    assert len(fins(evenements)) == 2  # un événement « fin » à chaque tour

    agent.liberer("B")
    assert comptes(fabrique) == (1, 2, 1)
    agent.liberer("B")  # une seconde fois : rien de plus
    assert comptes(fabrique) == (1, 2, 1)


def test_ouvrier_ferme_la_suite_reprend_par_la_session_comme_aujourd_hui(claude):
    agent, fabrique, _ = claude([], ["echec"])
    premier = lancer(agent)
    agent.liberer("B")
    assert comptes(fabrique) == (1, 1, 1)

    repris = suivre(agent, premier.session)  # reprise par session, qui finit en erreur
    assert (repris.ok, repris.erreur, repris.ouverte) == (False, "En erreur.", False)
    assert fabrique.clients[1].options.resume == SESSION_MESUREE
    assert fabrique.clients[1].demandes == [SUITE]
    assert comptes(fabrique) == (2, 2, 2)


def test_un_ouvrier_repris_par_la_session_reste_ouvert_a_son_tour(claude):
    agent, fabrique, _ = claude()
    premier = lancer(agent)
    agent.liberer("B")
    repris = suivre(agent, premier.session)
    assert repris.ok and repris.ouverte and fabrique.clients[1].options.resume == SESSION_MESUREE
    assert suivre(agent, repris.session).ok
    assert comptes(fabrique) == (2, 3, 1)


# --- 4 : arrêt, erreur, délai --------------------------------------------------------------------


def test_un_arret_pendant_un_tour_ferme_l_ouvrier(claude):
    agent, fabrique, _ = claude(["bloque"], ["ok", "bloque"])

    fil, rendus = en_fond(lancer, agent)  # arrêt pendant le premier tour
    assert attendre(lambda: fabrique.demandes == 1)
    assert agent.arreter("B") is True
    fil.join(GARDE_S)
    assert rendus[0].erreur == ARRETE and not rendus[0].ouverte
    assert comptes(fabrique) == (1, 1, 1)

    premier = lancer(agent)  # arrêt pendant la suite donnée à l'ouvrier ouvert
    assert premier.ouverte
    fil, rendus = en_fond(suivre, agent, premier.session)
    assert attendre(lambda: fabrique.demandes == 3)
    assert agent.arreter("B") is True
    fil.join(GARDE_S)
    assert rendus[0].erreur == ARRETE and not rendus[0].ouverte
    assert comptes(fabrique) == (2, 3, 2)  # la suite est partie sur la même connexion
    assert fabrique.clients[1].interruptions == 1


def test_un_arret_pendant_que_l_ouvrier_ouvert_attend_le_ferme(claude):
    agent, fabrique, evenements = claude()
    premier = lancer(agent)
    assert premier.ouverte

    assert agent.arreter("B") is False  # aucun agent en marche : rien à rendre arrêté
    assert attendre(lambda: fabrique.deconnexions == 1)
    assert comptes(fabrique) == (1, 1, 1)
    assert len(fins(evenements)) == 1  # aucun tour de plus, aucune « fin » de plus

    repris = suivre(agent, premier.session)  # plus ouvert : la reprise par session
    assert repris.ok and fabrique.clients[1].options.resume == SESSION_MESUREE
    assert comptes(fabrique) == (2, 2, 1)


def test_une_erreur_du_client_pendant_la_suite_ferme_l_ouvrier(claude):
    agent, fabrique, evenements = claude(["ok", "erreur"])
    premier = lancer(agent)

    suite = suivre(agent, premier.session)
    assert not suite.ok and not suite.ouverte and "connexion perdue" in suite.erreur
    assert comptes(fabrique) == (1, 2, 1)
    assert fins(evenements)[-1]["contenu"] == suite.erreur

    encore = suivre(agent, premier.session)  # fermé : reprise par session, nouvelle connexion
    assert encore.ok and fabrique.clients[1].options.resume == SESSION_MESUREE
    assert comptes(fabrique) == (2, 3, 1)


def test_une_fin_en_erreur_pendant_la_suite_ferme_l_ouvrier(claude):
    agent, fabrique, _ = claude(["ok", "echec"])
    premier = lancer(agent)
    suite = suivre(agent, premier.session)
    assert (suite.ok, suite.erreur, suite.ouverte) == (False, "En erreur.", False)
    assert comptes(fabrique) == (1, 2, 1)


def test_un_delai_depasse_pendant_la_suite_ferme_l_ouvrier(claude):
    agent, fabrique, _ = claude(["ok", "bloque"], delai_max_s=0.25)
    premier = lancer(agent)
    assert premier.ouverte

    debut = time.monotonic()
    suite = suivre(agent, premier.session)
    assert time.monotonic() - debut < GARDE_S
    assert suite.erreur.startswith(DELAI) and not suite.ouverte
    assert comptes(fabrique) == (1, 2, 1)
    assert fabrique.clients[0].interruptions == 1


# --- 1 : le plafond et le réglage du profil ------------------------------------------------------


def taches(*noms):
    return [{"role": "ouvrier", "tache": nom, "tentative": 1} for nom in noms]


def test_au_plafond_le_nouvel_ouvrier_rend_la_main_ferme(claude):
    agent, fabrique, _ = claude(profil={"ouverts_max": 2})
    a, b, c = (lancer(agent, contexte) for contexte in taches("A", "B", "C"))
    assert (a.ok, b.ok, c.ok) == (True, True, True)  # sans erreur
    assert (a.ouverte, b.ouverte, c.ouverte) == (True, True, False)
    assert comptes(fabrique) == (3, 3, 1) and fabrique.clients[2].deconnexions == 1
    assert not os.path.exists(fabrique.clients[2].options.settings)  # ses refus partent aussitôt
    assert os.path.exists(fabrique.clients[0].options.settings)

    agent.liberer("A")  # une place se libère
    d = lancer(agent, taches("D")[0])
    assert d.ouverte
    assert comptes(fabrique) == (4, 4, 2)


def test_un_plafond_mal_forme_vaut_la_valeur_par_defaut(claude):
    agent, fabrique, _ = claude(profil={"ouverts_max": "3"})  # les autres : `test_lire_garde`
    noms = [chr(ord("A") + i) for i in range(OUVERTS_MAX + 1)]
    rendus = [lancer(agent, contexte) for contexte in taches(*noms)]
    assert [r.ouverte for r in rendus] == [True] * OUVERTS_MAX + [False]
    assert comptes(fabrique) == (OUVERTS_MAX + 1, OUVERTS_MAX + 1, 1)


def test_un_plafond_nul_ne_garde_personne(claude):
    agent, fabrique, _ = claude(profil={"ouverts_max": 0})
    premier = lancer(agent)
    assert premier.ok and not premier.ouverte
    assert comptes(fabrique) == (1, 1, 1)
    assert not os.path.exists(fabrique.clients[0].options.settings)  # ses refus partent aussitôt
    agent.liberer_tous()  # rien d'ouvert : sans effet
    repris = suivre(agent, premier.session)  # la reprise par session
    assert fabrique.clients[1].options.resume == SESSION_MESUREE and not repris.ouverte
    assert comptes(fabrique) == (2, 2, 2)


@pytest.mark.parametrize(
    "profil, attendu",
    [
        ({}, (True, OUVERTS_MAX)),
        ({"ouvrier_ouvert": False, "ouverts_max": 2}, (False, 2)),
        ({"ouvrier_ouvert": "non", "ouverts_max": "2"}, (True, OUVERTS_MAX)),
        ({"ouvrier_ouvert": 0, "ouverts_max": -3}, (True, OUVERTS_MAX)),
        ({"ouvrier_ouvert": None, "ouverts_max": True}, (True, OUVERTS_MAX)),
        ({"ouvrier_ouvert": "false", "ouverts_max": 2.5}, (True, OUVERTS_MAX)),
        ({"ouverts_max": None}, (True, OUVERTS_MAX)),
        ({"ouverts_max": 0}, (True, 0)),
        (None, (True, OUVERTS_MAX)),
    ],
)
def test_lire_garde(profil, attendu):
    assert lire_garde(profil) == attendu


# --- Point 1 de la décision : sans `garder_ouvert`, l'appel d'avant ------------------------------


@pytest.mark.parametrize("appeler", ["ancien", "faux"])
def test_sans_garder_ouvert_rien_ne_change(claude, appeler):
    agent, fabrique, evenements = claude()
    if appeler == "ancien":
        premier = ancien_appel(agent)
    else:
        premier = lancer(agent, garder=False)
    fichier = fabrique.clients[0].options.settings
    assert premier.ok and not premier.ouverte
    assert comptes(fabrique) == (1, 1, 1)  # fermé dès qu'il rend la main
    assert not os.path.exists(fichier)  # ses refus d'office sont effacés
    assert not set(fils_de_session()) - claude.deja  # aucun fil de session ne reste

    repris = ancien_appel(agent, reprendre=premier.session)  # reprise par session, comme avant
    assert repris.ok and not repris.ouverte
    assert fabrique.clients[1].options.resume == SESSION_MESUREE
    assert comptes(fabrique) == (2, 2, 2)
    assert len(fins(evenements)) == 2
    agent.liberer("B")  # rien d'ouvert : sans effet
    agent.liberer_tous()
    assert comptes(fabrique) == (2, 2, 2)


@pytest.mark.parametrize("reglage", [True, False, "non"])
def test_le_reglage_ouvrier_ouvert_du_profil_n_est_pas_lu_par_l_agent(claude, reglage):
    agent, fabrique, _ = claude(profil={"ouvrier_ouvert": reglage})
    assert not ancien_appel(agent).ouverte  # vrai au profil : l'appel ne l'a pas demandé
    assert lancer(agent, {**OUVRIER, "tentative": 2}).ouverte  # faux au profil : demandé
    assert comptes(fabrique) == (2, 2, 1)


# --- 1 : jamais le vérificateur ni l'orchestrateur -----------------------------------------------


def test_ni_le_verificateur_ni_l_orchestrateur_ne_restent_ouverts(claude):
    agent, fabrique, _ = claude()
    assert lancer(agent).ouverte  # l'ouvrier de B attend son verdict

    relu = lancer(agent, VERIFICATEUR, lecture_seule=True)
    jetable = agent.executer("Vérifie.", "opus", "high", None, True, VERIFICATEUR,
                             copie_jetable=True, garder_ouvert=True)  # fmt: skip
    parle = agent.converser("Bonjour.", SESSION_MESUREE, False, None)
    sans_tache = lancer(agent, {})
    assert all(r.ok and not r.ouverte for r in (relu, jetable, parle, sans_tache))
    assert [c.deconnexions for c in fabrique.clients] == [0, 1, 1, 1, 1]
    assert comptes(fabrique) == (5, 5, 4)  # l'ouvrier de B est resté ouvert pendant ce temps


# --- 3 : liberer, deux fois, depuis un autre fil, pendant un tour --------------------------------


def test_liberer_deux_fois_ensemble_ou_pour_une_tache_inconnue_ne_leve_jamais(claude):
    agent, fabrique, _ = claude()
    assert lancer(agent).ouverte

    fils = [threading.Thread(target=agent.liberer, args=("B",)) for _ in range(4)]
    for fil in fils:
        fil.start()
    for fil in fils:
        fil.join(GARDE_S)
    for tache in ("B", "inconnue", None, "", ["pas", "hachable"], 42):
        agent.liberer(tache)
    agent.liberer_tous()
    assert comptes(fabrique) == (1, 1, 1)  # déconnecté une seule fois


def test_liberer_pendant_un_tour_ne_l_interrompt_pas_et_le_ferme_a_la_fin(claude):
    agent, fabrique, _ = claude(tour=0.4)
    premier = lancer(agent)
    assert premier.ouverte

    fil, rendus = en_fond(suivre, agent, premier.session)
    assert attendre(lambda: fabrique.demandes == 2)
    debut = time.monotonic()
    autre, _ = en_fond(agent.liberer, "B")  # depuis un autre fil, en plein tour
    autre.join(GARDE_S)
    assert time.monotonic() - debut < 0.3  # n'attend pas la fin du tour
    assert fabrique.deconnexions == 0  # le tour continue, rien n'est coupé
    fil.join(GARDE_S)
    assert rendus[0].ok and not rendus[0].ouverte  # rendu fermé, sans erreur
    assert comptes(fabrique) == (1, 2, 1) and fabrique.clients[0].interruptions == 1
    agent.liberer("B")
    assert comptes(fabrique) == (1, 2, 1)


def test_liberer_tous_pendant_un_premier_tour_le_ferme_a_la_fin(claude):
    agent, fabrique, _ = claude(tour=0.2)
    fil, rendus = en_fond(lancer, agent)
    assert attendre(lambda: fabrique.demandes == 1)
    agent.liberer_tous()
    fil.join(GARDE_S)
    assert rendus[0].ok and not rendus[0].ouverte
    assert comptes(fabrique) == (1, 1, 1)


def test_aucun_programme_claude_ne_reste_apres_liberer_tous(claude):
    agent, fabrique, _ = claude()
    nes = lambda: set(fils_de_session()) - claude.deja  # noqa: E731
    rendus = [lancer(agent, contexte) for contexte in taches("A", "B", "C")]
    assert all(r.ouverte for r in rendus) and len(nes()) == 3

    agent.liberer_tous()
    assert [c.deconnexions for c in fabrique.clients] == [1, 1, 1]  # chacun une fois
    assert attendre(lambda: not nes(), 0.5)
    agent.liberer_tous()
    assert comptes(fabrique) == (3, 3, 3)


# --- Point 7 de la décision : `liberer` rend la main en un temps borné ---------------------------


def test_liberer_rend_la_main_en_temps_borne_et_liberer_tous_attend_la_fin(claude):
    assert AgentClaude.delai_liberer_s == 5.0  # la borne du produit
    agent, fabrique, _ = claude(deconnexion=0.6)  # un programme lent à sortir
    agent.delai_liberer_s = 0.2
    nes = lambda: set(fils_de_session()) - claude.deja  # noqa: E731
    premier = lancer(agent)
    fichier = fabrique.clients[0].options.settings

    debut = time.monotonic()
    agent.liberer("B")
    assert time.monotonic() - debut < 0.45  # rendu à la borne, avant la fin de la déconnexion
    assert fabrique.deconnexions == 0 and os.path.exists(fichier)  # elle finit derrière

    assert premier.ouverte
    agent.liberer_tous()  # à l'arrêt de l'Atelier : attend jusqu'au bout
    assert fabrique.clients[0].deconnexions == 1
    assert not os.path.exists(fichier) and attendre(lambda: not nes(), 0.5)


def test_un_programme_qui_ne_repond_plus_ne_bloque_ni_liberer_ni_liberer_tous(
    claude, monkeypatch
):  # fmt: skip
    from atelier.sdk import SessionSDK

    monkeypatch.setattr(SessionSDK, "delai_deconnexion_s", 0.4)  # la borne du pont, raccourcie
    agent, fabrique, _ = claude(deconnexion=None)  # `disconnect` ne rend jamais la main
    agent.delai_liberer_s = 0.2
    nes = lambda: set(fils_de_session()) - claude.deja  # noqa: E731
    assert lancer(agent).ouverte

    debut = time.monotonic()
    agent.liberer("B")
    assert time.monotonic() - debut < 0.6
    debut = time.monotonic()
    agent.liberer_tous()  # attend la fermeture lancée par `liberer`, bornée par le pont
    assert time.monotonic() - debut < GARDE_S
    assert ("deconnexion sans reponse", 0) in fabrique.journal
    assert attendre(lambda: not nes(), 1)  # le fil de la session est fini


# --- Point 4 de la décision : la suite servie, puis fermée sans `garder_ouvert` ------------------


def test_une_suite_sans_garder_ouvert_est_servie_puis_fermee(claude):
    agent, fabrique, evenements = claude()
    premier = lancer(agent)
    suite = suivre(agent, premier.session, garder=False)
    assert suite.ok and not suite.ouverte and suite.texte == "Fait 2."
    assert comptes(fabrique) == (1, 2, 1)  # même conversation, une seule déconnexion
    assert fabrique.clients[0].options.resume is None
    assert not os.path.exists(fabrique.clients[0].options.settings)
    agent.liberer("B")
    assert comptes(fabrique) == (1, 2, 1) and len(fins(evenements)) == 2


# --- 5 : nouvel ouvrier, autre session, mode ou droits changés -----------------------------------


def avant(journal, premier, second):
    return journal.index(premier) < journal.index(second)


def test_un_nouvel_ouvrier_pour_la_meme_tache_ferme_d_abord_l_ancien(claude):
    agent, fabrique, _ = claude()
    assert lancer(agent).ouverte
    second = lancer(agent, {**OUVRIER, "tentative": 2})
    assert second.ouverte
    assert avant(fabrique.journal, ("deconnexion", 0), ("connexion", 1))
    assert comptes(fabrique) == (2, 2, 1)


def test_une_reprise_d_une_autre_session_ferme_l_ouvert_et_reprend_par_la_session(claude):
    agent, fabrique, _ = claude()
    assert lancer(agent).ouverte
    autre = "11111111-2222-4333-8444-555555555555"
    repris = suivre(agent, autre)  # le faux client répond sur sa session : reprise refusée
    assert repris.erreur == REPRISE_IMPOSSIBLE
    assert fabrique.clients[1].options.resume == autre
    assert avant(fabrique.journal, ("deconnexion", 0), ("connexion", 1))
    assert comptes(fabrique) == (2, 2, 2)


def changer_le_mode(agent):
    assert agent.changer_mode("default") == 0  # aucun ouvrier en marche


def changer_les_regles(agent):
    agent.regles_chantier = lambda: ["Bash(uv sync)"]


def changer_les_secrets(agent):
    agent.profil["secrets"] = ["*.sqlite"]


@pytest.mark.parametrize("changer", [changer_le_mode, changer_les_regles, changer_les_secrets])
def test_un_mode_ou_des_droits_changes_entre_deux_tours_ferment_l_ouvrier(claude, changer):
    agent, fabrique, _ = claude()
    premier = lancer(agent)
    assert premier.ouverte

    changer(agent)
    repris = suivre(agent, premier.session)
    assert repris.ok and repris.ouverte  # repris par la session, avec les nouveaux droits
    nouveau = fabrique.clients[1].options
    assert nouveau.resume == SESSION_MESUREE
    assert avant(fabrique.journal, ("deconnexion", 0), ("connexion", 1))
    assert comptes(fabrique) == (2, 2, 1)
    assert fabrique.clients[0].demandes == ["Consigne."]  # l'ancien n'a rien reçu de plus
    if changer is changer_le_mode:
        assert nouveau.permission_mode == "default"
    if changer is changer_les_regles:
        assert "Bash(uv sync)" in nouveau.allowed_tools


def test_un_mode_change_pendant_le_tour_et_applique_garde_l_ouvrier(claude):
    agent, fabrique, _ = claude(tour=0.2)
    fil, rendus = en_fond(lancer, agent)
    assert attendre(lambda: fabrique.demandes == 1)
    assert agent.changer_mode("default") == 1  # appliqué à chaud au client en marche
    fil.join(GARDE_S)
    assert rendus[0].ouverte
    assert suivre(agent, rendus[0].session).ok  # même conversation : déjà dans le bon mode
    assert comptes(fabrique) == (1, 2, 0)


# --- 6 : le fichier des refus d'office vit avec l'ouvrier ouvert ----------------------------------


def reglages_de(client):
    return Path(client.options.settings)


def fermer_par_liberer(agent, fabrique, session):
    agent.liberer("B")


def fermer_par_liberer_tous(agent, fabrique, session):
    agent.liberer_tous()


def fermer_par_arret_en_attente(agent, fabrique, session):
    agent.arreter("B")  # ferme dans un fil à part : le fichier part après la déconnexion
    assert attendre(lambda: not os.path.exists(fabrique.clients[0].options.settings))


def fermer_par_erreur(agent, fabrique, session):
    assert not suivre(agent, session).ok


def fermer_par_nouvel_ouvrier(agent, fabrique, session):
    lancer(agent, {**OUVRIER, "tentative": 2})


def fermer_par_mode_change(agent, fabrique, session):
    agent.changer_mode("plan")
    suivre(agent, session)


@pytest.mark.parametrize(
    "fermer",
    [fermer_par_liberer, fermer_par_liberer_tous, fermer_par_arret_en_attente, fermer_par_erreur,
     fermer_par_nouvel_ouvrier, fermer_par_mode_change],
)  # fmt: skip
def test_le_fichier_des_refus_vit_avec_l_ouvrier_ouvert_et_part_a_sa_fermeture(claude, fermer):
    agent, fabrique, _ = claude(["ok", "ok", "erreur"])
    premier = lancer(agent)
    fichier = reglages_de(fabrique.clients[0])
    assert premier.ouverte and fichier.is_file()
    assert suivre(agent, premier.session).ok  # un tour de plus : toujours là, le même
    assert fichier.is_file() and fabrique.connexions == 1

    fermer(agent, fabrique, premier.session)
    assert fabrique.clients[0].deconnexions == 1
    assert not fichier.exists()


# --- AgentSimule, appelé avec garder_ouvert=True : le même contrat --------------------------------

DELAI_SIMULE = 0.02


def simule(**reglages):
    evenements = []
    reglages = {"delai_s": DELAI_SIMULE, **reglages}
    agent = AgentSimule(perimetres={"B": ["b.py"]}, sur_evenement=evenements.append, **reglages)
    return agent, evenements


def test_l_agent_simule_garde_l_ouvrier_et_lui_donne_la_suite(tmp_path):
    agent, evenements = simule(suites={"B": ["", "rien", "erreur"]})
    premier = lancer(agent, dossier=tmp_path)
    assert premier.ok and premier.ouverte
    contenu = (tmp_path / "b.py").read_text("utf-8")

    debut = time.monotonic()
    suite = suivre(agent, premier.session)
    assert time.monotonic() - debut >= DELAI_SIMULE  # une suite prend du temps, comme un tour
    assert suite.ok and suite.ouverte and suite.session == premier.session
    assert agent.suivis == [{"tache": "B", "role": "ouvrier", "tentative": 1,
                             "session": premier.session, "message": SUITE}]  # fmt: skip
    assert agent.reprises == [] and agent.fermes == []

    rien = lancer(agent, reprendre=premier.session, consigne="Encore.", dossier=tmp_path)
    assert rien.ok and rien.ouverte and rien.fichiers == []
    assert (tmp_path / "b.py").read_text("utf-8") == contenu  # rien n'a changé : « rien »

    echec = suivre(agent, premier.session)
    assert not echec.ok and not echec.ouverte and agent.fermes == [premier.session]
    assert len(fins(evenements)) == 4  # un événement « fin » à chaque tour

    repli = suivre(agent, premier.session)  # fermé : la reprise par session, comme aujourd'hui
    assert repli.ok and len(agent.reprises) == 1 and len(agent.suivis) == 3


def test_une_suite_par_defaut_reecrit_le_perimetre(tmp_path):
    agent, _ = simule()
    premier = lancer(agent, dossier=tmp_path)
    avant_suite = (tmp_path / "b.py").read_text("utf-8")
    suite = lancer(agent, reprendre=premier.session, consigne=SUITE, dossier=tmp_path)
    assert suite.fichiers == ["b.py"] and len(agent.suivis) == 1
    assert (tmp_path / "b.py").read_text("utf-8") != avant_suite


def test_l_agent_simule_arrete_pendant_la_suite_ou_pendant_l_attente():
    agent, _ = simule()
    premier = lancer(agent)
    agent.delai_s = 1.0
    fil, rendus = en_fond(suivre, agent, premier.session)
    assert attendre(lambda: len(agent.suivis) == 1)
    time.sleep(0.05)
    assert agent.arreter("B") is True
    fil.join(GARDE_S)
    assert rendus[0].erreur == ARRETE and not rendus[0].ouverte
    assert agent.fermes == [premier.session]

    agent.delai_s = DELAI_SIMULE
    second = lancer(agent)
    assert second.ouverte
    assert agent.arreter("B") is False
    assert attendre(lambda: agent.fermes == [premier.session, second.session])


def test_l_agent_simule_au_plafond_et_mode_change():
    agent, _ = simule(ouverts_max=1)
    a = lancer(agent, {**OUVRIER, "tache": "A"})
    b = lancer(agent)
    assert (a.ouverte, b.ouverte) == (True, False) and agent.fermes == [b.session]

    agent.changer_mode("default")
    repris = suivre(agent, a.session, {**OUVRIER, "tache": "A"})
    assert repris.ok and agent.suivis == [] and len(agent.reprises) == 1  # par la session
    assert agent.fermes == [b.session, a.session]


def test_l_agent_simule_ne_garde_ni_verificateur_ni_orchestrateur_et_ferme_l_ancien():
    agent, _ = simule()
    premier = lancer(agent)
    assert not lancer(agent, VERIFICATEUR, lecture_seule=True).ouverte
    assert not lancer(agent, {"role": "orchestrateur"}).ouverte
    assert agent.fermes == []  # l'ouvrier de B attend toujours
    second = lancer(agent, {**OUVRIER, "tentative": 2})
    assert second.ouverte and agent.fermes == [premier.session]


def test_l_agent_simule_liberer_deux_fois_depuis_un_autre_fil_et_pendant_un_tour():
    agent, _ = simule()
    premier = lancer(agent)
    fils = [threading.Thread(target=agent.liberer, args=("B",)) for _ in range(3)]
    for fil in fils:
        fil.start()
    for fil in fils:
        fil.join(GARDE_S)
    agent.liberer("inconnue")
    agent.liberer(None)
    assert agent.fermes == [premier.session]

    agent.delai_s = 0.2
    fil, rendus = en_fond(lancer, agent)
    assert attendre(lambda: agent._en_tour)
    agent.liberer_tous()  # pendant un tour : fermé à la fin, sans l'interrompre
    fil.join(GARDE_S)
    assert rendus[0].ok and not rendus[0].ouverte
    assert agent.fermes == [premier.session, rendus[0].session]

    agent.delai_s = DELAI_SIMULE
    ouverts = [lancer(agent, {**OUVRIER, "tache": t}) for t in "CDE"]
    agent.liberer_tous()
    agent.liberer_tous()
    assert sorted(agent.fermes[2:]) == sorted(r.session for r in ouverts)  # chacun une fois


@pytest.mark.parametrize("appeler", ["ancien", "faux"])
def test_sans_garder_ouvert_l_agent_simule_ne_change_pas(appeler):
    agent, evenements = simule(suites={"B": ["erreur"]})
    if appeler == "ancien":
        premier = ancien_appel(agent)
        repris = ancien_appel(agent, reprendre=premier.session)
    else:
        premier = lancer(agent, garder=False)
        repris = suivre(agent, premier.session, garder=False)
    assert premier.ok and not premier.ouverte
    assert repris.ok and not repris.ouverte and len(agent.reprises) == 1
    assert agent.suivis == [] and agent.fermes == []
    agent.liberer("B")
    agent.liberer_tous()
    assert agent.fermes == [] and len(fins(evenements)) == 2


def test_l_agent_simule_sert_une_suite_sans_garder_ouvert_puis_la_ferme():
    agent, evenements = simule()
    premier = lancer(agent)
    suite = suivre(agent, premier.session, garder=False)
    assert suite.ok and not suite.ouverte and suite.session == premier.session
    assert len(agent.suivis) == 1 and agent.reprises == []  # la même conversation
    assert agent.fermes == [premier.session]  # fermée une fois
    agent.liberer("B")
    assert agent.fermes == [premier.session] and len(fins(evenements)) == 2


# --- Un client bâti comme le vrai : une file que le programme remplit de lui-même ------------


class ClientFile:
    """Faux client bâti comme le vrai `ClaudeSDKClient` : un lecteur de fond range tout ce que le
    programme émet dans une file, tour demandé ou non ; `receive_response` lit cette file jusqu'au
    premier message de fin ; `receive_messages` la lit sans s'arrêter ; `query` lève quand le
    programme est mort ; à sa mort, la file reçoit l'erreur puis la fin de flux.

    `scenario` dit ce qui arrive après la première demande, pendant que l'ouvrier attend :
    "rien", "tour de fond" (le programme joue un tour de lui-même), "meurt".
    """

    def __init__(self, options, scenario):
        reprise = getattr(options, "resume", None)
        self.options, self.scenario = options, "rien" if reprise else scenario
        self.session = reprise or SESSION_MESUREE
        self.file, self.mort, self.demandes = None, False, []
        self.connexions = self.deconnexions = 0

    async def connect(self):
        import asyncio

        self.file = asyncio.Queue()
        self.connexions += 1

    def _fin(self, texte):
        from claude_agent_sdk import ResultMessage

        return ResultMessage(
            subtype="success", duration_ms=1, duration_api_ms=1, is_error=False, num_turns=1,
            session_id=self.session, total_cost_usd=0.1, result=texte,
            usage={"input_tokens": 10, "output_tokens": 5},
        )  # fmt: skip

    async def _programme(self, rang, consigne):
        import asyncio

        from claude_agent_sdk import ProcessError, SystemMessage

        if rang == 1:
            donnees = {"apiKeySource": "none", "session_id": self.session}
            await self.file.put(SystemMessage(subtype="init", data=donnees))
        await asyncio.sleep(0.02)
        await self.file.put(self._fin(f"Fait : {consigne}"))
        if rang != 1 or self.scenario == "rien":
            return
        await asyncio.sleep(0.03)
        if self.scenario == "tour de fond":  # une tâche de fond finit : un tour de lui-même
            await self.file.put(self._fin("Tour de fond : rien de neuf."))
        if self.scenario == "meurt":  # le programme sort pendant l'attente
            self.mort = True
            await self.file.put(ProcessError("Command failed with exit code 1", exit_code=1))
            await self.file.put(None)

    async def query(self, consigne):
        import asyncio

        from claude_agent_sdk import CLIConnectionError

        if self.mort:
            raise CLIConnectionError("Cannot write to terminated process (exit code: 1)")
        self.demandes.append(consigne)
        asyncio.ensure_future(self._programme(len(self.demandes), consigne))

    async def receive_messages(self):
        while True:
            message = await self.file.get()
            if message is None:
                return
            if isinstance(message, BaseException):
                raise message
            yield message

    async def receive_response(self):
        from claude_agent_sdk import ResultMessage

        async for message in self.receive_messages():
            yield message
            if isinstance(message, ResultMessage):
                return

    async def set_permission_mode(self, mode):
        pass

    async def interrupt(self):
        pass

    async def disconnect(self):
        self.deconnexions += 1


@pytest.fixture
def comme_le_vrai():
    deja = set(fils_de_session())
    crees = []

    def creer(scenario):
        clients = []

        def fabrique(options):
            clients.append(ClientFile(options, scenario))
            return clients[-1]

        agent = AgentClaude({}, delai_max_s=GARDE_S, fabrique_client=fabrique)
        crees.append(agent)
        return agent, clients

    yield creer
    for agent in crees:
        agent.liberer_tous()
    assert attendre(lambda: not (set(fils_de_session()) - deja), 2)


def test_sans_rien_entre_deux_la_suite_part_dans_la_meme_conversation(comme_le_vrai):
    agent, clients = comme_le_vrai("rien")
    premier = lancer(agent)
    time.sleep(0.1)  # les contrôles tournent ; l'ouvrier attend, ouvert
    suite = lancer(agent, reprendre=premier.session, consigne=SUITE)
    assert (suite.ok, suite.texte, suite.ouverte) == (True, f"Fait : {SUITE}", True)
    assert len(clients) == 1 and clients[0].demandes == ["Consigne.", SUITE]


def test_un_tour_joue_de_lui_meme_entre_deux_demandes_ne_decale_pas_les_reponses(comme_le_vrai):
    agent, clients = comme_le_vrai("tour de fond")
    premier = lancer(agent)
    time.sleep(0.1)  # le tour de fond a fini : son message de fin traîne dans la file
    suite = lancer(agent, reprendre=premier.session, consigne=SUITE)
    assert (suite.ok, suite.texte) == (True, f"Fait : {SUITE}")  # pas « Tour de fond »
    troisieme = lancer(agent, reprendre=premier.session, consigne="Troisième demande.")
    assert troisieme.texte == "Fait : Troisième demande."  # aucun décalage ensuite
    assert len(clients) == 1 and clients[0].connexions == 1


def test_un_programme_mort_pendant_l_attente_se_replie_sur_la_reprise_de_session(comme_le_vrai):
    agent, clients = comme_le_vrai("meurt")
    premier = lancer(agent)
    assert premier.ouverte
    time.sleep(0.1)  # le programme sort pendant que l'ouvrier attend
    suite = lancer(agent, reprendre=premier.session, consigne=SUITE)
    assert (suite.ok, suite.texte) == (True, f"Fait : {SUITE}")  # servie par un nouvel ouvrier
    assert len(clients) == 2 and clients[1].options.resume == premier.session
    assert clients[0].demandes == ["Consigne."] and clients[1].demandes == [SUITE]
    assert clients[0].deconnexions == 1  # le mort est fermé, pas rangé comme ouvert
    assert suite.session == premier.session and suite.ouverte
