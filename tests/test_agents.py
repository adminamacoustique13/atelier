"""Tests des agents : `AgentClaude` sur un faux client SDK, et l'agent simulé.

Aucun appel réel à Claude, aucun processus lancé : le faux client vient de `tests/test_sdk.py`.
"""

import json
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

pytest.importorskip("claude_agent_sdk")

from claude_agent_sdk import PermissionResultAllow  # noqa: E402

from atelier import agents  # noqa: E402
from atelier.agents import (  # noqa: E402
    AgentClaude,
    AgentSimule,
    Resultat,
)
from atelier.consignes import ROLE_ORCHESTRATEUR  # noqa: E402
from atelier.controles import ControlesSimules  # noqa: E402
from atelier.guichet import Guichet, GuichetSimule  # noqa: E402
from atelier.modele import Chantier, Contrat, Tache  # noqa: E402
from atelier.moteur import Moteur  # noqa: E402
from atelier.sdk import SessionSDK  # noqa: E402
from tests.test_sdk import (  # noqa: E402
    BLOQUE,
    UUID,
    Fabrique,
    FauxGuichet,
    Permission,
    Reponse,
    attendre,
    fin,
    init,
    jusqu_a,
    outil,
    texte,
)

GARDE_S = 5  # aucun test ne doit pouvoir attendre plus longtemps que ça
ARRETE = "Arrêté par la personne responsable."
ECRITURE = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
OUVRIER = {"role": "ouvrier", "tache": "B", "tentative": 1}
VERIFICATEUR = {"role": "verificateur", "tache": "B", "tentative": 2}
USAGE = {"input_tokens": 100, "output_tokens": 20}


@pytest.fixture(autouse=True)
def aucun_fil_de_session_ne_reste():
    """Chaque session ouverte par un agent est fermée, quoi qu'il arrive."""
    yield
    fils = lambda: [f for f in threading.enumerate() if f.name.startswith("atelier-sdk-")]  # noqa: E731
    assert attendre(lambda: not fils(), 2), fils()


def claude(*scenarios, profil=None, **reglages_client):
    fabrique = Fabrique(*scenarios, **reglages_client)
    agent = AgentClaude(profil or {}, delai_max_s=GARDE_S, fabrique_client=fabrique)
    return agent, fabrique


def lancer(agent, contexte=OUVRIER, lecture_seule=False, dossier=None, modele="opus"):
    return agent.executer("Consigne.", modele, "high", dossier, lecture_seule, contexte)


def converser(agent, sur_texte=None, sur_outil=None, reprise=False):
    return agent.converser("Bonjour.", UUID, reprise, None, sur_texte, sur_outil, {})


def en_fond(fonction, *arguments):
    rendus = []
    fil = threading.Thread(target=lambda: rendus.append(fonction(*arguments)), daemon=True)
    fil.start()
    return fil, rendus


def du_type(evenements, type_):
    return [e["contenu"] for e in evenements if e["type"] == type_]


# --- Critère 1 : les résultats rendus par l'agent --------------------------------------------


@pytest.mark.parametrize(
    "result, is_error, attendu",
    [
        ("Fini.", False, Resultat(ok=True, texte="Fini.", cout_usd=0.12, tokens=120)),
        ("Quota dépassé.", True, Resultat(ok=False, erreur="Quota dépassé.", tokens=120)),
        ("", True, Resultat(ok=False, erreur="Erreur signalée par Claude Code.", tokens=120)),
    ],
)
def test_executer_rend_le_resultat_attendu(result, is_error, attendu):
    agent, _ = claude([init(), texte("Je "), outil("Read", {"file_path": "a.py"}),
                       fin(result=result, is_error=is_error, cout=0.12)])  # fmt: skip
    assert lancer(agent) == attendu


@pytest.mark.parametrize(
    "result, is_error, attendu",
    [
        ("Bonjour", False, Resultat(ok=True, texte="Bonjour", cout_usd=0.5, tokens=120)),
        ("", False, Resultat(ok=True, texte="Bonjour", cout_usd=0.5, tokens=120)),
        ("Non.", True, Resultat(ok=False, erreur="Non.", tokens=120)),
    ],
)
def test_converser_rend_le_resultat_attendu(result, is_error, attendu):
    agent, _ = claude([init(), outil("Read", {"file_path": "a.py"}), texte("Bon"), texte("jour"),
                       fin(result=result, is_error=is_error, cout=0.5)])  # fmt: skip
    textes, outils = [], []
    assert converser(agent, textes.append, outils.append) == attendu
    assert (textes, outils) == (["Bon", "jour"], ["Lit a.py"])


def test_executer_traduit_le_modele_et_garde_l_effort(tmp_path):
    agent, fabrique = claude([fin()], profil={"alias_modeles": {"opus": "claude-opus-4-9"}})
    assert lancer(agent, dossier=tmp_path).ok
    options = fabrique.clients[0].options
    assert (options.model, options.effort, options.cwd) == ("claude-opus-4-9", "high", tmp_path)
    assert options.system_prompt == {"type": "preset", "preset": "claude_code"}
    assert (options.session_id, options.resume) == (None, None)
    sans_alias, fabrique = claude([fin()])
    lancer(sans_alias, modele="sonnet")
    assert fabrique.clients[0].options.model == "sonnet"


@pytest.mark.parametrize("reprise, session_id, resume", [(False, UUID, None), (True, None, UUID)])
def test_converser_garde_le_role_la_session_et_la_reprise(reprise, session_id, resume):
    agent, fabrique = claude([fin()], profil={"alias_modeles": {"fable": "claude-fable-2"}})
    assert converser(agent, reprise=reprise).ok
    options = fabrique.clients[0].options
    assert (options.model, options.effort) == ("claude-fable-2", "high")
    assert options.system_prompt["append"] == ROLE_ORCHESTRATEUR
    assert (options.session_id, options.resume) == (session_id, resume)
    assert fabrique.clients[0].consignes == ["Bonjour."]


def test_converser_transmet_le_dossier(tmp_path):
    agent, fabrique = claude([fin()])
    assert agent.converser("Bonjour.", UUID, False, tmp_path).ok
    assert fabrique.clients[0].options.cwd == tmp_path


def test_le_delai_de_l_agent_est_transmis_au_pont():
    fabrique = Fabrique([BLOQUE])
    agent = AgentClaude({}, delai_max_s=0.2, fabrique_client=fabrique)
    fil, rendus = en_fond(lancer, agent)
    fil.join(2)
    if fil.is_alive():  # délai non transmis : on arrête l'agent pour ne pas bloquer le test
        agent.arreter("B")
        fil.join(GARDE_S)
    assert rendus[0].erreur == "L'agent n'a pas fini dans le délai de 0.2 secondes."


def test_chaque_session_est_fermee_meme_apres_une_erreur():
    agent, fabrique = claude([fin()], [RuntimeError("connexion perdue")], [fin()])
    assert lancer(agent).ok
    assert lancer(agent).erreur == "Le SDK de Claude a échoué : connexion perdue"
    assert converser(agent).ok
    assert len(fabrique.clients) == 3  # une session par appel
    assert all(client.deconnecte for client in fabrique.clients)


def test_le_moteur_conduit_un_chantier_avec_l_agent_du_sdk():
    verdict = json.dumps({"valide": True, "motif": "bacle", "resume": "Tout y est."})
    agent, fabrique = claude([fin(result="Fait.", cout=0.3)], [fin(result=verdict, cout=0.1)])
    tache = Tache(id="A", titre="Un", type="mecanique", criteres=["Ça marche."],
                  perimetre=["a.py"])  # fmt: skip
    c = Chantier(projet="essai", contrat=Contrat(objectif="Essai", valide=True), taches=[tache])
    Moteur(c, agent, ControlesSimules()).executer()
    assert c.termine and tache.etat == "verifie" and tache.verdict == "Tout y est."
    assert round(c.cout_usd, 2) == 0.4 and c.tokens == 240
    modes = [client.options.permission_mode for client in fabrique.clients]
    assert modes == ["acceptEdits", "default"]


# --- Critère 2 : les ouvriers et les vérificateurs émettent en direct -----------------------


@pytest.mark.parametrize(
    "contexte, nom",
    [(OUVRIER, "B-ouvrier-1"), (VERIFICATEUR, "B-verificateur-2"),
     ({"role": "orchestrateur"}, "orchestrateur"), (None, "orchestrateur")],
)  # fmt: skip
def test_ouvriers_et_verificateurs_emettent_en_direct(contexte, nom):
    agent, _ = claude([texte("Je lis."), outil("Read", {"file_path": "a.py"}), fin()])
    evenements = []
    agent.sur_evenement = evenements.append
    assert lancer(agent, contexte, lecture_seule=contexte is VERIFICATEUR).ok
    assert evenements == [
        {"agent": nom, "type": "texte", "contenu": "Je lis."},
        {"agent": nom, "type": "outil", "contenu": "Lit a.py"},
        {"agent": nom, "type": "fin", "contenu": "L'agent a terminé."},
    ]


def test_la_conversation_emet_et_garde_ses_rappels():
    agent, _ = claude([texte("Bon"), outil("Grep", {"pattern": "def"}), texte("jour"), fin()])
    evenements, textes, outils = [], [], []
    agent.sur_evenement = evenements.append
    assert converser(agent, textes.append, outils.append).ok
    assert (textes, outils) == (["Bon", "jour"], ["Cherche def"])
    assert [(e["agent"], e["type"]) for e in evenements] == [
        ("orchestrateur", "texte"), ("orchestrateur", "outil"), ("orchestrateur", "texte"),
        ("orchestrateur", "fin"),
    ]  # fmt: skip


def test_un_rappel_qui_leve_ne_gene_pas_l_agent():
    def rappel(_evenement):
        raise RuntimeError("Le tableau de bord est tombé.")

    agent, _ = claude([texte("a"), fin()])
    agent.sur_evenement = rappel
    assert lancer(agent).ok
    assert converser(agent, sur_texte=rappel, sur_outil=rappel).ok


# --- Critère 3 : outils permis, autorisations du profil, guichet ----------------------------


def test_outils_de_l_ouvrier_avec_les_autorisations_du_profil():
    regles = ["Bash(npm install:*)", "WebFetch(domain:example.com)", "Write"]
    profil = {"commandes_permises": ["npm"], "autorisations": [*regles, None, 42, "  "]}
    agent, fabrique = claude([fin()], profil=profil)
    lancer(agent)
    options = fabrique.clients[0].options
    assert options.allowed_tools == agent._outils(lecture_seule=False) + regles
    assert {"Read", "Glob", "Grep", "Bash(npm:*)", "Bash(git status:*)", "Edit"} <= set(
        options.allowed_tools
    )
    assert options.disallowed_tools == []
    assert options.permission_mode == "acceptEdits"


@pytest.mark.parametrize("contexte, lecture_seule", [(OUVRIER, False), (VERIFICATEUR, True)])
def test_seules_les_regles_simples_sont_retenues(contexte, lecture_seule):
    douteuses = ["Read,Write", "Read Write", "Bash(npm test:*),Write", "Bash(a)(b)", "Bash()",
                 "Bash(npm\ntest:*)", "(Write)", "Bash(npm test:*"]  # fmt: skip
    agent, fabrique = claude([fin()], profil={"autorisations": [*douteuses, " Bash(npm test:*) "]})
    lancer(agent, contexte, lecture_seule)
    allowed = fabrique.clients[0].options.allowed_tools
    assert allowed == agent._outils(lecture_seule) + ["Bash(npm test:*)"]


@pytest.mark.parametrize("valeur", [42, True, "Write", {"Write": 1}, None])
def test_une_cle_autorisations_mal_formee_vaut_une_liste_vide(valeur):
    agent, fabrique = claude([fin()], [fin()], profil={"autorisations": valeur})
    assert lancer(agent).ok
    assert lancer(agent, VERIFICATEUR, lecture_seule=True).ok
    ouvrier, verificateur = (client.options for client in fabrique.clients)
    assert ouvrier.allowed_tools == agent._outils(False)
    assert verificateur.allowed_tools == agent._outils(True)


def test_sans_cle_autorisations_les_outils_sont_ceux_d_aujourd_hui():
    agent, fabrique = claude([fin()], [fin()], profil={"commandes_permises": ["uv"]})
    lancer(agent)
    lancer(agent, VERIFICATEUR, lecture_seule=True)
    ouvrier, verificateur = (client.options for client in fabrique.clients)
    assert ouvrier.allowed_tools == agent._outils(False)
    assert verificateur.allowed_tools == agent._outils(True)
    assert "Bash(uv:*)" in verificateur.allowed_tools


@pytest.mark.parametrize("contexte", [OUVRIER, VERIFICATEUR, "conversation"])
def test_un_outil_non_permis_passe_par_le_guichet(contexte):
    entree = {"url": "https://example.com/doc"}
    agent, fabrique = claude([Permission("WebFetch", entree), fin()])
    agent.guichet = guichet = FauxGuichet(Reponse("une_fois"))
    evenements = []
    agent.sur_evenement = evenements.append
    if contexte == "conversation":
        resultat, nom = converser(agent), "orchestrateur"
    else:
        resultat = lancer(agent, contexte, lecture_seule=contexte is VERIFICATEUR)
        nom = "B-ouvrier-1" if contexte is OUVRIER else "B-verificateur-2"
    assert resultat.ok
    assert guichet.demandes == [(nom, "WebFetch", entree)]
    assert fabrique.clients[0].decisions == [PermissionResultAllow()]
    assert du_type(evenements, "attente") == ["Lit la page https://example.com/doc"]


# --- Critère 4 : vérificateur et conversation sans outil d'écriture -------------------------


def test_le_verificateur_n_a_aucun_outil_d_ecriture():
    ecrivent = ["Write", " Edit(src/**) ", "MultiEdit", "NotebookEdit(carnet.ipynb)", "write"]
    lisent = ["Bash(npm test:*)", "Read(docs/**)"]
    agent, fabrique = claude([fin()], profil={"autorisations": ecrivent + lisent})
    lancer(agent, VERIFICATEUR, lecture_seule=True)
    options = fabrique.clients[0].options
    assert options.allowed_tools == agent._outils(lecture_seule=True) + lisent
    ecriture = {nom.lower() for nom in ECRITURE}
    assert not [o for o in options.allowed_tools if o.split("(")[0].strip().lower() in ecriture]
    assert set(options.disallowed_tools) >= ECRITURE
    assert options.permission_mode == "default"


def test_dans_sa_copie_jetable_le_verificateur_essaie_sans_carte():
    """Ses essais (un fichier modifié pour voir un test échouer) passent sans demander, puisque
    l'atelier jette la copie ; il ne suit pas pour autant le mode choisi pour les ouvriers."""
    agent, fabrique = claude([fin()], profil={"autorisations": ["Write", "Bash(npm test:*)"]})
    agent.changer_mode("default")
    agent.executer("Consigne.", "opus", "high", None, True, VERIFICATEUR, copie_jetable=True)
    options = fabrique.clients[0].options
    assert options.allowed_tools == agent._outils(False) + ["Write", "Bash(npm test:*)"]
    assert {"Edit", "Write"} <= set(options.allowed_tools)
    assert options.disallowed_tools == []
    assert options.permission_mode == "acceptEdits"
    assert agent.modes_appliques() == {}  # aucun poste d'ouvrier n'a été occupé


def test_une_regle_retenue_entre_deux_messages_vaut_des_le_suivant():
    profil = {"autorisations": []}
    agent, fabrique = claude([fin()], [fin()], profil=profil)
    converser(agent)
    assert "Bash(ls:*)" not in fabrique.clients[0].options.allowed_tools
    profil["autorisations"] = ["Bash(ls:*)"]  # « Toujours pour ce projet », écrit à chaud
    converser(agent, reprise=True)
    assert fabrique.clients[1].options.allowed_tools[-1] == "Bash(ls:*)"


def test_la_conversation_reste_en_lecture_seule_sans_les_commandes_du_projet():
    regles = ["Bash(npm install:*)", "Write", "WebFetch(domain:docs.python.org)", " Edit(src/**) "]
    profil = {"commandes_permises": ["npm"], "autorisations": regles}
    agent, fabrique = claude([fin()], profil=profil)
    converser(agent)
    options = fabrique.clients[0].options
    assert options.allowed_tools[:3] == ["Read", "Glob", "Grep"]
    # Les règles retenues par « Toujours » valent pour elle, sauf celles qui écrivent ;
    # les commandes permises d'office aux ouvriers (ici npm), non.
    retenues = ["Bash(npm install:*)", "WebFetch(domain:docs.python.org)"]
    assert options.allowed_tools[-2:] == retenues
    assert all(o.startswith("Bash(git ") for o in options.allowed_tools[3:-2])
    assert "Bash(npm:*)" not in options.allowed_tools
    assert "Bash(git status:*)" in options.allowed_tools
    assert set(options.disallowed_tools) >= ECRITURE
    assert options.permission_mode == "default"


# --- Contrat fourni à D1 : arrêter ----------------------------------------------------------


def test_arreter_un_ouvrier_en_marche():
    agent, fabrique = claude([texte("Je cherche"), BLOQUE])
    evenements = []
    agent.sur_evenement = evenements.append
    fil, rendus = en_fond(lancer, agent)
    assert attendre(lambda: du_type(evenements, "texte"))
    assert agent.arreter("A") is False  # une autre tâche : rien à arrêter
    debut = time.monotonic()
    assert agent.arreter("B") is True
    fil.join(GARDE_S)
    assert not fil.is_alive() and time.monotonic() - debut < 2
    assert rendus == [Resultat(ok=False, erreur="Arrêté par la personne responsable.")]
    client = fabrique.clients[0]
    assert attendre(lambda: client.interrompu and client.deconnecte)
    assert du_type(evenements, "fin") == [ARRETE]


@pytest.mark.parametrize("nature", ["ouvrier", "conversation"])
def test_apres_un_arret_l_appel_rend_la_main_session_fermee(nature):
    """L'appel arrêté ne rend la main qu'une fois son client déconnecté et son fil libéré."""
    agent, fabrique = claude([texte("a"), BLOQUE], lent={"interrupt": 0.3, "disconnect": 0.4})
    evenements = []
    agent.sur_evenement = evenements.append
    if nature == "ouvrier":
        fil, rendus = en_fond(lancer, agent)
    else:
        fil, rendus = en_fond(converser, agent)
    assert attendre(lambda: du_type(evenements, "texte"))
    debut = time.monotonic()
    assert agent.arreter("B" if nature == "ouvrier" else None) is True
    assert time.monotonic() - debut < 0.5  # `arreter` ne bloque pas (fermeture : 0,7 s)
    fil.join(GARDE_S)
    assert rendus[0].erreur == ARRETE
    client = fabrique.clients[0]
    assert client.interrompu and client.deconnecte and not client.deconnexion_annulee
    assert not [f for f in threading.enumerate() if f.name.startswith("atelier-sdk-")]


def faire_arreter_au_dernier_moment(monkeypatch, agent, tache):
    """Demande l'arrêt au moment où l'appel décide de son résultat ; rend ce qu'`arreter` dit."""
    original, vus = agents._arrete, []

    def arreter_puis_decider(marche, resultat):
        vus.append(agent.arreter(tache))
        return original(marche, resultat)

    monkeypatch.setattr(agents, "_arrete", arreter_puis_decider)
    return vus


@pytest.mark.parametrize("simulee", [False, True])
def test_un_arret_qui_rend_vrai_donne_toujours_le_resultat_d_arret(monkeypatch, simulee):
    agent = simule()[0] if simulee else claude([fin(result="Fait.")])[0]
    vus = faire_arreter_au_dernier_moment(monkeypatch, agent, "B")
    resultat = lancer(agent)
    # Le poste est retiré avant la décision : l'arrêt arrive trop tard et le dit.
    assert vus == [False] and resultat.ok
    vus = faire_arreter_au_dernier_moment(monkeypatch, agent, None)
    assert converser(agent).ok and vus == [False]


@pytest.mark.parametrize("moment", ["envoyer", "_demarrer_boucle"])
def test_un_arret_juste_avant_le_tour_n_est_pas_perdu(monkeypatch, moment):
    """L'arrêt arrive avant que le pont ait posé son drapeau : il ne doit pas se perdre."""
    agent, _ = claude([BLOQUE])
    evenements, arrets = [], []
    agent.sur_evenement = evenements.append
    original = getattr(SessionSDK, moment)

    def arreter_d_abord(session, *arguments):
        arrets.append(agent.arreter("B"))
        return original(session, *arguments)

    monkeypatch.setattr(SessionSDK, moment, arreter_d_abord)
    debut = time.monotonic()
    resultat = lancer(agent)
    assert arrets == [True]
    assert resultat.erreur == ARRETE and not resultat.ok
    assert time.monotonic() - debut < 2
    assert du_type(evenements, "fin") == [ARRETE]


def test_un_arret_sans_rien_en_marche_est_sans_effet():
    agent, fabrique = claude([fin(result="Un.")], [fin(result="Deux.")])
    assert agent.arreter("B") is False
    assert agent.arreter() is False
    assert lancer(agent).texte == "Un."
    assert agent.arreter("B") is False  # après la fin : sans effet non plus
    assert converser(agent).texte == "Deux."
    assert len(fabrique.clients) == 2


def test_arreter_la_conversation_puis_le_message_suivant_marche():
    agent, fabrique = claude([texte("Je réfléchis"), BLOQUE], [fin(result="Repris.")])
    textes = []
    fil, rendus = en_fond(converser, agent, textes.append)
    assert attendre(lambda: textes)
    assert agent.arreter("B") is False  # aucune tâche en marche
    assert agent.arreter() is True
    fil.join(GARDE_S)
    assert rendus[0].erreur == ARRETE
    suite = converser(agent, reprise=True)
    assert suite.ok and suite.texte == "Repris."
    assert fabrique.clients[1].options.resume == UUID


# --- Contrat fourni à D1 : attributs et source de connexion ---------------------------------


def test_attributs_par_defaut():
    for agent in (AgentClaude(), AgentSimule()):
        assert (agent.guichet, agent.sur_evenement, agent.source_connexion) == (None, None, "")


def test_source_de_connexion_connue_des_le_debut_du_tour():
    agent, _ = claude([init("ANTHROPIC_API_KEY"), texte("a"), BLOQUE], [init("none"), fin()])
    evenements = []
    agent.sur_evenement = evenements.append
    fil, _ = en_fond(lancer, agent)
    assert attendre(lambda: evenements)
    assert agent.source_connexion == "clé API"
    agent.arreter("B")
    fil.join(GARDE_S)
    lancer(agent)
    assert agent.source_connexion == "abonnement"


# --- Critère 6 : aucun processus lancé par agents.py --------------------------------------


def test_aucun_processus_n_est_lance_par_les_agents(monkeypatch):
    source = Path(agents.__file__).read_text("utf-8")
    assert "subprocess" not in source and '"-p"' not in source

    def interdit(*_arguments, **_reglages):
        raise AssertionError("Aucun processus ne doit être lancé par agents.py.")

    monkeypatch.setattr(subprocess, "run", interdit)
    monkeypatch.setattr(subprocess, "Popen", interdit)
    agent, _ = claude([fin()])
    assert lancer(agent).ok and converser(agent).ok


def test_import_des_agents_ne_charge_pas_le_sdk():
    code = (
        "import sys, atelier.agents; "
        "print('claude_agent_sdk' in sys.modules, 'atelier.sdk' in sys.modules)"
    )
    racine = Path(__file__).resolve().parents[1]
    sortie = subprocess.run(
        [sys.executable, "-c", code], cwd=racine, capture_output=True, text=True, timeout=30
    )
    assert sortie.stdout.strip() == "False False", sortie.stderr


# --- Critère 5 : l'agent simulé joue une demande d'autorisation -----------------------------


def simule(guichet=None, delai_s=0.0):
    agent = AgentSimule(perimetres={"A": ["a.py"], "B": ["b.py"]}, delai_s=delai_s)
    evenements = []
    agent.guichet, agent.sur_evenement = guichet, evenements.append
    return agent, evenements


def ouvrier(tache, tentative=1):
    return {"role": "ouvrier", "tache": tache, "tentative": tentative}


def test_l_agent_simule_demande_une_autorisation_au_premier_ouvrier():
    guichet = GuichetSimule(["une_fois"])
    agent, evenements = simule(guichet)
    assert lancer(agent, ouvrier("A")).ok
    assert lancer(agent, ouvrier("B")).ok
    assert lancer(agent, {"role": "verificateur", "tache": "A", "tentative": 1}, True).ok
    (demande,) = guichet.demandes
    assert (demande["agent"], demande["outil"], demande["detail"]) == (
        "A-ouvrier-1", "Bash", "npm install left-pad"
    )  # fmt: skip
    a = [(e["type"], e["contenu"]) for e in evenements if e["agent"] == "A-ouvrier-1"]
    assert a == [
        ("outil", "Lit la consigne"),
        ("attente", "Lance npm install left-pad"),
        ("texte", "Réponse de la personne responsable : autorisé une fois."),
        ("outil", "Lance npm install left-pad"),
        ("fin", "L'agent a terminé."),
    ]
    b = [e["type"] for e in evenements if e["agent"] == "B-ouvrier-1"]
    assert b == ["outil", "fin"]


def test_ni_le_verificateur_ni_l_orchestrateur_ne_jouent_la_demande():
    guichet = GuichetSimule(["une_fois"])
    agent, evenements = simule(guichet)
    assert lancer(agent, {"role": "verificateur", "tache": "A", "tentative": 1}, True).ok
    assert lancer(agent, {"role": "orchestrateur"}, True).ok
    assert converser(agent).ok
    assert guichet.demandes == [] and du_type(evenements, "attente") == []
    assert lancer(agent, ouvrier("B")).ok
    assert [d["agent"] for d in guichet.demandes] == ["B-ouvrier-1"]


def test_la_demande_simulee_attend_la_vraie_reponse_du_guichet():
    guichet = Guichet(delai_s=GARDE_S)
    agent, evenements = simule(guichet)
    fil, rendus = en_fond(lancer, agent, ouvrier("A"))
    try:
        assert attendre(lambda: guichet.ouvertes())
        assert not rendus  # l'ouvrier attend la réponse
        (demande,) = guichet.ouvertes()
        assert guichet.repondre(demande["id"], "non", "Utilise plutôt pnpm.")
        fil.join(GARDE_S)
    finally:
        guichet.annuler("A-ouvrier-1")
    assert rendus[0].ok
    assert du_type(evenements, "texte") == [
        "Réponse de la personne responsable : refusé. Utilise plutôt pnpm."
    ]
    assert du_type(evenements, "outil") == ["Lit la consigne"]  # la commande n'a pas été lancée


def test_sans_guichet_l_agent_simule_ne_demande_rien():
    agent, evenements = simule()
    resultat = lancer(agent, ouvrier("A"))
    assert resultat == Resultat(ok=True, texte="Compte rendu simulé.", cout_usd=0.35,
                                tokens=9000, fichiers=["a.py"])  # fmt: skip
    assert [e["type"] for e in evenements] == ["outil", "fin"]


def test_la_demonstration_se_deroule_avec_une_demande_d_autorisation():
    taches = [Tache(id=i, titre=i, type="mecanique", criteres=["Ça marche."],
                    perimetre=[f"{i.lower()}.py"]) for i in "ABC"]  # fmt: skip
    c = Chantier(projet="démo", contrat=Contrat(objectif="Essai", valide=True), taches=taches)
    guichet = GuichetSimule(["toujours"])
    agent, evenements = simule(guichet)
    agent.perimetres = {t.id: t.perimetre for t in taches}
    Moteur(c, agent, ControlesSimules()).executer()
    assert c.termine and len(guichet.demandes) == 1
    attendu = "Réponse de la personne responsable : autorisé pour ce projet."
    assert du_type(evenements, "texte") == [attendu]
    assert len(du_type(evenements, "fin")) == 6  # trois ouvriers et trois vérificateurs


# --- L'agent simulé sait être arrêté --------------------------------------------------------


def test_arreter_l_agent_simule_pendant_son_delai():
    agent, evenements = simule(delai_s=30)
    fil, rendus = en_fond(lancer, agent, ouvrier("A"))
    assert attendre(lambda: evenements)
    debut = time.monotonic()
    assert agent.arreter("A") is True
    fil.join(GARDE_S)
    assert time.monotonic() - debut < 2
    assert rendus == [Resultat(ok=False, erreur="Arrêté par la personne responsable.")]
    assert evenements[-1] == {"agent": "A-ouvrier-1", "type": "fin", "contenu": ARRETE}


def test_arreter_l_agent_simule_pendant_sa_demande():
    guichet = Guichet(delai_s=GARDE_S)
    agent, evenements = simule(guichet)
    fil, rendus = en_fond(lancer, agent, ouvrier("A"))
    assert attendre(lambda: guichet.ouvertes())
    assert agent.arreter("A") is True
    fil.join(GARDE_S)
    assert rendus[0].erreur == ARRETE
    assert guichet.ouvertes() == []
    assert du_type(evenements, "texte") == []  # aucune réponse n'a été lue


def test_une_demande_deposee_juste_apres_l_arret_est_fermee_aussi():
    class GuichetLent(Guichet):
        def demander(self, agent, outil, entree):
            time.sleep(0.1)  # l'arrêt et son annulation passent avant le dépôt
            return super().demander(agent, outil, entree)

    guichet = GuichetLent(delai_s=GARDE_S)
    agent, evenements = simule(guichet)
    fil, rendus = en_fond(lancer, agent, ouvrier("A"))
    assert attendre(lambda: du_type(evenements, "attente"))
    assert agent.arreter("A") is True
    fil.join(GARDE_S)
    assert rendus[0].erreur == ARRETE
    # L'appel ne rend la main qu'une fois la demande tardive déposée puis fermée.
    assert not [f for f in threading.enumerate() if f.name == "atelier-demande-A-ouvrier-1"]
    assert guichet.ouvertes() == []


def test_un_arret_sans_rien_en_marche_ne_touche_pas_l_agent_simule():
    agent, _ = simule()
    assert agent.arreter("A") is False and agent.arreter() is False
    assert lancer(agent, ouvrier("A")).ok
    assert converser(agent).ok


def test_arreter_la_conversation_simulee_puis_reprendre():
    agent, evenements = simule(delai_s=25)  # 0,04 s par mot
    textes = []
    fil, rendus = en_fond(converser, agent, textes.append)
    assert attendre(lambda: textes)
    assert agent.arreter() is True
    fil.join(GARDE_S)
    assert rendus[0].erreur == ARRETE
    assert du_type(evenements, "fin") == [ARRETE]
    agent.delai_s = 0
    suite = converser(agent)
    assert suite.ok and suite.texte.startswith("C'est noté.")
    assert du_type(evenements, "fin") == [ARRETE, "L'agent a terminé."]


# --- Le mode des ouvriers -------------------------------------------------------------------

MODES = ["default", "acceptEdits", "plan", "dontAsk", "auto"]
CONVERSATION = {"role": "conversation"}


@pytest.mark.parametrize("mode", MODES)
def test_l_ouvrier_demarre_dans_le_mode_du_profil(mode):
    agent, fabrique = claude([fin()], profil={"mode_ouvriers": mode})
    assert agent.mode_ouvriers == mode
    assert lancer(agent).ok
    assert fabrique.clients[0].options.permission_mode == mode


@pytest.mark.parametrize("valeur", ["bypassPermissions", "AUTO", "", None, 42, ["auto"], {}])
def test_un_mode_inconnu_ou_bypass_dans_le_profil_vaut_accept_edits(valeur):
    agent, fabrique = claude([fin()], profil={"mode_ouvriers": valeur})
    assert lancer(agent).ok
    assert agent.mode_ouvriers == "acceptEdits"
    assert fabrique.clients[0].options.permission_mode == "acceptEdits"


@pytest.mark.parametrize("mode", MODES)
def test_verificateur_et_conversation_restent_en_lecture_seule_quel_que_soit_le_mode(mode):
    agent, fabrique = claude([fin()], profil={"mode_ouvriers": "plan"})
    agent.changer_mode(mode)
    assert lancer(agent, VERIFICATEUR, lecture_seule=True).ok and converser(agent).ok
    for client in fabrique.clients:
        assert client.options.permission_mode == "default"
        assert set(client.options.disallowed_tools) >= ECRITURE


@pytest.mark.parametrize("simulee", [False, True])
@pytest.mark.parametrize("mode", ["bypassPermissions", "Auto", None, 3])
def test_changer_mode_refuse_bypass_et_tout_mode_inconnu(simulee, mode):
    agent = AgentSimule() if simulee else claude([fin()])[0]
    agent.changer_mode("plan")
    with pytest.raises(ValueError):
        agent.changer_mode(mode)
    assert agent.mode_ouvriers == "plan"


def test_un_ouvrier_lance_apres_le_choix_demarre_dans_le_mode_choisi():
    agent, fabrique = claude([fin()])
    assert agent.mode_ouvriers == "acceptEdits"
    assert agent.changer_mode("plan") == 0  # aucun ouvrier en marche : le choix est retenu
    assert lancer(agent).ok
    assert fabrique.clients[0].options.permission_mode == "plan"


def roles(fabrique):
    """Retrouve, d'après ses options, l'ouvrier, le vérificateur et la conversation."""
    par_role = {}
    for client in fabrique.clients:
        options = client.options
        if options.system_prompt.get("append"):
            par_role["conversation"] = client
        elif options.disallowed_tools:
            par_role["verificateur"] = client
        else:
            par_role["ouvrier"] = client
    return par_role


def test_le_changement_a_chaud_ne_touche_que_les_ouvriers_en_marche():
    agent, fabrique = claude([BLOQUE])
    autre = {"role": "verificateur", "tache": "C", "tentative": 1}
    fils = [en_fond(lancer, agent), en_fond(lancer, agent, autre, True), en_fond(converser, agent)]
    assert attendre(lambda: len(fabrique.clients) == 3 and all(c.consignes for c in
                                                                fabrique.clients))  # fmt: skip
    try:
        assert agent.changer_mode("auto") == 1
        par_role = roles(fabrique)
        assert attendre(lambda: par_role["ouvrier"].modes == ["auto"])
        assert agent.modes_appliques() == {"B-ouvrier-1": "auto"}
        time.sleep(0.05)  # laisse aux autres le temps d'un changement qui ne doit pas venir
        assert par_role["verificateur"].modes_demandes == []
        assert par_role["conversation"].modes_demandes == []
    finally:
        for tache in ("B", "C", None):
            agent.arreter(tache)
        for fil, _ in fils:
            fil.join(GARDE_S)
    assert agent.modes_appliques() == {}


def test_un_ouvrier_qui_demarre_pendant_un_changement_finit_dans_le_mode_choisi():
    """Le changement arrive juste avant, pendant ou juste après l'inscription de l'ouvrier :
    à la fin, l'ouvrier travaille toujours dans le mode choisi."""
    for rang in range(30):
        mode = MODES[rang % len(MODES)]
        signal = threading.Event()
        agent, fabrique = claude([jusqu_a(lambda _c, s=signal: s.is_set()), fin()])
        agent.changer_mode("acceptEdits" if mode != "acceptEdits" else "default")
        fil, rendus = en_fond(lancer, agent)
        time.sleep((rang % 4) / 1000)
        agent.changer_mode(mode)
        signal.set()
        fil.join(GARDE_S)
        assert rendus[0].ok
        (client,) = fabrique.clients
        modes = [client.options.permission_mode, *client.modes]
        assert modes[-1] == mode, (rang, modes)


def test_un_changement_entre_la_lecture_du_mode_et_l_inscription_n_est_pas_perdu(monkeypatch):
    """Le pire moment : la session est créée avec l'ancien mode, le changement arrive avant
    que l'ouvrier soit inscrit. L'inscription relit le mode sous le verrou des postes."""
    agent, fabrique = claude([fin()])
    creer = SessionSDK.__init__

    def creer_puis_changer(session, *arguments, **reglages):
        creer(session, *arguments, **reglages)
        assert agent.changer_mode("plan") == 0  # l'ouvrier n'est pas encore inscrit

    monkeypatch.setattr(SessionSDK, "__init__", creer_puis_changer)
    assert lancer(agent).ok
    assert fabrique.clients[0].options.permission_mode == "plan"


def test_le_mode_reel_d_un_ouvrier_se_lit_pendant_son_travail():
    agent, fabrique = claude([init(mode="default"), jusqu_a(lambda c: c.modes == ["plan"]),
                              fin()], profil={"mode_ouvriers": "auto"})  # fmt: skip
    evenements = []
    agent.sur_evenement = evenements.append
    fil, rendus = en_fond(lancer, agent)
    assert attendre(lambda: agent.modes_appliques() == {"B-ouvrier-1": "default"})
    (dit,) = [e for e in evenements if e["type"] == "mode"]
    assert (dit["agent"], dit["contenu"], dit["demande"]) == ("B-ouvrier-1", "default", "auto")
    assert dit["raison"] == "le mode auto n'est pas disponible pour son modèle"
    assert agent.changer_mode("plan") == 1
    fil.join(GARDE_S)
    assert rendus[0].ok and agent.modes_appliques() == {}


def test_un_ouvrier_qui_attend_au_guichet_garde_sa_demande_pendant_le_changement():
    guichet = Guichet(delai_s=GARDE_S)
    agent, fabrique = claude([Permission("Bash", {"command": "npm publish"}), fin()])
    agent.guichet = guichet
    fil, rendus = en_fond(lancer, agent)
    try:
        assert attendre(lambda: guichet.ouvertes())
        assert agent.changer_mode("dontAsk") == 1
        assert attendre(lambda: fabrique.clients[0].modes == ["dontAsk"])
        (demande,) = guichet.ouvertes()
        assert guichet.repondre(demande["id"], "une_fois")
        fil.join(GARDE_S)
    finally:
        guichet.annuler("B-ouvrier-1")
    assert rendus[0].ok and fabrique.clients[0].decisions == [PermissionResultAllow()]


# --- L'agent simulé et le mode des ouvriers -----------------------------------------------

REFUS_SIMULE = "Lance curl https://example.com (règle Data Exfiltration)"


def joues(evenements, nom):
    return [(e["type"], e["contenu"]) for e in evenements if e["agent"] == nom]


def test_hors_du_mode_auto_l_agent_simule_ne_change_rien():
    for mode in ("default", "acceptEdits", "plan", "dontAsk"):
        agent, evenements = simule()
        agent.retombee = agent.pause_arbitre = True
        agent.changer_mode(mode)
        assert lancer(agent, ouvrier("A")).ok
        assert joues(evenements, "A-ouvrier-1") == [
            ("outil", "Lit la consigne"), ("fin", "L'agent a terminé.")
        ]  # fmt: skip


def test_en_mode_auto_le_premier_ouvrier_simule_joue_un_refus_de_l_arbitre():
    agent, evenements = simule()
    agent.changer_mode("auto")
    assert lancer(agent, ouvrier("A")).ok and lancer(agent, ouvrier("B")).ok
    assert lancer(agent, {"role": "verificateur", "tache": "A", "tentative": 1}, True).ok
    assert joues(evenements, "A-ouvrier-1") == [
        ("outil", "Lit la consigne"), ("refus", REFUS_SIMULE), ("fin", "L'agent a terminé.")
    ]  # fmt: skip
    assert du_type(evenements, "refus") == [REFUS_SIMULE]  # un seul ouvrier le joue
    assert du_type(evenements, "mode") == []


def test_l_agent_simule_joue_une_retombee_apres_le_refus():
    agent, evenements = simule()
    agent.retombee = True
    agent.changer_mode("auto")
    assert lancer(agent, ouvrier("A")).ok
    assert joues(evenements, "A-ouvrier-1")[1:3] == [("refus", REFUS_SIMULE), ("mode", "default")]
    (retombee,) = [e for e in evenements if e["type"] == "mode"]
    assert (retombee["demande"], retombee["raison"]) == ("auto", "")


def test_l_agent_simule_joue_la_pause_de_l_arbitre_puis_le_guichet():
    guichet = GuichetSimule(["une_fois", "non"])
    agent, evenements = simule(guichet)
    agent.pause_arbitre = True
    agent.changer_mode("auto")
    assert lancer(agent, ouvrier("A")).ok
    assert [d["detail"] for d in guichet.demandes] == [
        "curl https://example.com", "npm install left-pad"
    ]  # fmt: skip
    assert joues(evenements, "A-ouvrier-1")[:7] == [
        ("outil", "Lit la consigne"),
        ("refus", REFUS_SIMULE), ("refus", REFUS_SIMULE), ("refus", REFUS_SIMULE),
        ("attente", "Lance curl https://example.com"),
        ("texte", "Réponse de la personne responsable : autorisé une fois."),
        ("outil", "Lance curl https://example.com"),
    ]  # fmt: skip


def test_l_agent_simule_suit_un_changement_de_mode_en_marche():
    agent, evenements = simule(delai_s=GARDE_S)
    verificateur = {"role": "verificateur", "tache": "A", "tentative": 1}
    fils = [en_fond(lancer, agent, ouvrier("B")), en_fond(lancer, agent, verificateur, True)]
    assert attendre(lambda: len(du_type(evenements, "outil")) == 2)
    try:
        assert agent.modes_appliques() == {"B-ouvrier-1": "acceptEdits"}
        assert agent.changer_mode("auto") == 1  # le vérificateur n'est pas touché
        assert attendre(lambda: du_type(evenements, "refus") == [REFUS_SIMULE])
        assert agent.modes_appliques() == {"B-ouvrier-1": "auto"}
        assert [e["agent"] for e in evenements if e["type"] == "refus"] == ["B-ouvrier-1"]
    finally:
        agent.arreter("A")
        agent.arreter("B")
        for fil, _ in fils:
            fil.join(GARDE_S)


@pytest.mark.parametrize(
    "valeur, attendu",
    [("auto", "auto"), ("plan", "plan"), ("bypassPermissions", "acceptEdits"),
     ("Default", "acceptEdits"), (None, "acceptEdits"), (["auto"], "acceptEdits")],
)  # fmt: skip
def test_lire_mode(valeur, attendu):
    assert agents.lire_mode(valeur) == attendu
    assert agents.mode_valide(valeur) is (valeur == attendu)


def test_les_gestes_disent_quel_fichier_et_quelle_commande():
    """Constaté au premier essai réel : l'activité n'affichait que « Write », « Write »."""
    from atelier.agents import decrire_outil

    racine = "/projets/p/.atelier/arbres/A"
    ecrit = {"name": "Write", "input": {"file_path": f"{racine}/coeur/calcul.py", "content": "x"}}
    assert decrire_outil(ecrit, racine) == "Écrit coeur/calcul.py"
    assert decrire_outil(ecrit) == f"Écrit {racine}/coeur/calcul.py"
    modifie = {"name": "Edit", "input": {"file_path": "/ailleurs/a.py"}}
    assert decrire_outil(modifie, racine) == "Modifie /ailleurs/a.py"
    commande = {"command": "python3 -m pytest -q\ngit status", "description": "Lancer les tests"}
    assert decrire_outil({"name": "Bash", "input": commande}) == (
        "Lancer les tests — python3 -m pytest -q ; git status"
    )
    assert decrire_outil({"name": "Bash", "input": {"command": "ls"}}) == "Lance ls"
    sous_agent = {"name": "Task", "input": {"description": "Lire les tests"}}
    assert decrire_outil(sous_agent) == "Confie à un sous-agent : Lire les tests"
    assert decrire_outil({"name": "Inconnu", "input": None}) == "Inconnu"
