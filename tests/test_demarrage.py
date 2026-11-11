"""Le message de démarrage : ce qui sera facturé, dit en clair dans le fil."""

import argparse
import json
import subprocess
import threading

import pytest

from atelier import serveur
from atelier.__main__ import avec_annonce, monter_projets, projet_simule
from atelier.agents import AgentSimule
from atelier.controles import ControlesSimules
from atelier.modele import Chantier, Contrat
from atelier.serveur import (
    ANCIENNES_ANNONCES,
    ANNONCES,
    CONFIRMATIONS,
    DEPARTS,
    Atelier,
    annonce_de_depart,
    annonce_de_source,
    cle_api_presente,
)

DEMO = "Démonstration : les agents sont simulés, rien de réel n'est appelé et rien n'est facturé."
CLE_PRESENTE = (
    "Une variable ANTHROPIC_API_KEY est présente dans l'environnement de l'Atelier : si Claude "
    "l'utilise, c'est cette clé API qui sera facturée, et non ton abonnement. Pour la retirer, "
    "regarde d'abord comment l'Atelier a été lancé : le LISEZMOI explique où elle est posée et "
    "la commande exacte pour l'enlever, puis comment relancer l'Atelier."
)
ATTENDUE = (
    "Aucune variable ANTHROPIC_API_KEY dans l'environnement de l'Atelier. "
    "La source réelle de connexion sera dite dès que le premier agent aura commencé."
)
ABONNEMENT = (
    "Le SDK de Claude annonce qu'aucune clé API n'est utilisée : le travail est compté sur ton "
    "abonnement Claude. Si tu n'es pas connecté à ton compte, ou si tu passes par une passerelle "
    "d'entreprise, ouvre le Terminal, lance « claude » puis tape « /status » pour le vérifier."
)
ABONNEMENT_MALGRE_VARIABLE = (
    "Le SDK de Claude annonce qu'aucune clé API n'est utilisée, bien qu'une variable "
    "ANTHROPIC_API_KEY soit présente dans l'environnement de l'Atelier. Je n'en sais pas plus : "
    "pour vérifier ce qui est facturé, ouvre le Terminal, lance « claude » puis tape « /status »."
)
CLE = (
    "Confirmé par le SDK de Claude : une clé API est utilisée, comme la variable "
    "ANTHROPIC_API_KEY le laissait prévoir. C'est cette clé qui est facturée, et non ton "
    "abonnement Claude."
)
CLE_SANS_VARIABLE = (
    "Le SDK de Claude annonce qu'une clé API est utilisée, alors qu'aucune variable "
    "ANTHROPIC_API_KEY n'était visible : elle vient d'un réglage de Claude Code, ou d'une "
    "connexion faite avec une clé plutôt qu'avec ton abonnement. C'est cette clé qui est "
    "facturée, et non ton abonnement. Pour le vérifier, ouvre le Terminal, lance « claude » "
    "puis tape « /status ». Si tu t'es connecté avec une clé, tape « /login » et choisis ton "
    "compte ; si elle vient d'un réglage (un bloc « env » ou un « apiKeyHelper » de "
    "~/.claude/settings.json), retire ce réglage."
)
SECRET = "valeur-qui-ne-doit-jamais-apparaitre"


def atelier_reel(depot, agent=None):
    chantier = Chantier(projet="essai", contrat=Contrat(objectif="Essai"))
    return Atelier(depot, chantier, agent or AgentSimule(), ControlesSimules(), {})


def textes(atelier):
    return [e["texte"] for e in atelier.moteur.chantier.evenements]


def evenement(agent="A-ouvrier-1"):
    return {"agent": agent, "type": "outil", "contenu": "Lit la consigne"}


def test_la_presence_de_la_variable_se_lit_sans_garder_sa_valeur():
    assert cle_api_presente({}) is False
    assert cle_api_presente({"ANTHROPIC_API_KEY": ""}) is False
    assert cle_api_presente({"ANTHROPIC_API_KEY": "  "}) is False
    assert cle_api_presente({"ANTHROPIC_API_KEY": SECRET}) is True
    assert cle_api_presente({"AUTRE": SECRET}) is False


def test_sans_appel_a_annoncer_connexion_le_fil_ne_change_pas(tmp_path):
    atelier = atelier_reel(tmp_path)
    assert len(textes(atelier)) == 1  # seulement l'accueil


def test_demonstration_dit_que_rien_n_est_facture(tmp_path):
    atelier = projet_simule(tmp_path / "d", "Démo", 0.0)
    assert textes(atelier)[-1] == DEMO
    atelier.moteur.agent.source_connexion = "clé API"
    atelier.moteur.agent.sur_evenement(evenement())
    atelier.moteur.agent.sur_evenement(evenement("B-ouvrier-1"))
    assert textes(atelier)[-1] == DEMO  # aucune phrase de connexion, quelle qu'elle soit, ensuite


def test_sans_variable_le_fil_ne_dit_que_ce_qui_est_su(tmp_path):
    atelier = atelier_reel(tmp_path)
    atelier.annoncer_connexion({})
    assert textes(atelier)[-1] == ATTENDUE
    assert "abonnement" not in ATTENDUE


def test_avec_la_variable_le_fil_dit_que_la_cle_sera_facturee(tmp_path):
    atelier = atelier_reel(tmp_path)
    atelier.annoncer_connexion({"ANTHROPIC_API_KEY": SECRET})
    assert textes(atelier)[-1] == CLE_PRESENTE
    assert not any(SECRET in t for t in textes(atelier))


def test_l_environnement_du_processus_est_lu_par_defaut(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "valeur-factice")
    present = atelier_reel(tmp_path / "a")
    present.annoncer_connexion()
    assert textes(present)[-1] == CLE_PRESENTE
    assert not any("valeur-factice" in t for t in textes(present))
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    absent = atelier_reel(tmp_path / "b")
    absent.annoncer_connexion()
    assert textes(absent)[-1] == ATTENDUE


@pytest.mark.parametrize(
    "variable, source, attendu",
    [
        (False, "abonnement", ABONNEMENT),
        (True, "abonnement", ABONNEMENT_MALGRE_VARIABLE),
        (True, "clé API", CLE),
        (False, "clé API", CLE_SANS_VARIABLE),
    ],
)
def test_la_source_apprise_est_annoncee_une_seule_fois(tmp_path, variable, source, attendu):
    agent = AgentSimule()
    atelier = atelier_reel(tmp_path, agent)
    atelier.annoncer_connexion({"ANTHROPIC_API_KEY": SECRET} if variable else {})
    avant = len(textes(atelier))
    agent.sur_evenement(evenement())  # source encore inconnue : rien
    assert len(textes(atelier)) == avant
    agent.source_connexion = source
    agent.sur_evenement(evenement())
    agent.sur_evenement(evenement("B-ouvrier-1"))
    assert textes(atelier)[avant:] == [attendu]
    assert not any(SECRET in t for t in textes(atelier))


def test_un_redemarrage_identique_n_ajoute_rien_au_fil(tmp_path):
    chantier = Chantier(projet="essai", contrat=Contrat(objectif="Essai"))
    textes_vus = []
    for _ in range(2):
        agent = AgentSimule()
        atelier = Atelier(tmp_path, chantier, agent, ControlesSimules(), {})
        atelier.annoncer_connexion({})
        agent.source_connexion = "abonnement"
        agent.sur_evenement(evenement())
        textes_vus.append(textes(atelier))
    assert textes_vus[1] == textes_vus[0]
    assert textes_vus[0][-2:] == [ATTENDUE, ABONNEMENT]


def ouvrir(depot, variable, chantier=None):
    """Un démarrage de l'Atelier : le fil est relu dans `.atelier/etat.json`, s'il existe.

    Le test exhaustif passe le chantier déjà relu (voir `relire`) pour ne pas toucher au disque.
    """
    etat = depot / ".atelier" / "etat.json"
    if chantier is None and etat.exists():
        chantier = Chantier.charger(etat)
    if chantier is None:
        chantier = Chantier(projet="essai", contrat=Contrat(objectif="Essai"))
    agent = AgentSimule()
    atelier = Atelier(depot, chantier, agent, ControlesSimules(), {})
    atelier.annoncer_connexion({"ANTHROPIC_API_KEY": SECRET} if variable else {})
    return atelier


def apprendre(atelier, source):
    """La source arrive comme chez un vrai agent : posée sur l'agent, puis un événement."""
    atelier.moteur.agent.source_connexion = source
    atelier.moteur.agent.sur_evenement(evenement())
    atelier.moteur.agent.sur_evenement(evenement("B-ouvrier-1"))  # un second agent, en même temps


def annonces(fil):
    return [texte for texte in fil if texte in ANNONCES]


def test_les_annonces_de_connexion_sont_les_sept_phrases(tmp_path):
    departs = {DEMO, CLE_PRESENTE, ATTENDUE}
    confirmations = {ABONNEMENT, ABONNEMENT_MALGRE_VARIABLE, CLE, CLE_SANS_VARIABLE}
    assert set(DEPARTS) == departs
    assert set(CONFIRMATIONS) == confirmations
    assert ANNONCES == DEPARTS + CONFIRMATIONS + ANCIENNES_ANNONCES
    assert not set(ANCIENNES_ANNONCES) & (departs | confirmations)


def test_un_texte_retire_fait_reecrire_l_annonce(tmp_path, monkeypatch):
    # Une ancienne version a écrit des phrases au texte depuis changé : elles ne doivent pas
    # laisser le fil sur une annonce fausse. Ici, seuls ces deux textes auraient changé.
    ancien_depart = "Ancien texte : aucune variable ANTHROPIC_API_KEY."
    ancienne_cle = "Ancien texte : une clé API est utilisée."
    retires = (ancien_depart, ancienne_cle)
    monkeypatch.setattr(serveur, "ANCIENNES_ANNONCES", retires)
    monkeypatch.setattr(serveur, "ANNONCES", DEPARTS + CONFIRMATIONS + retires)
    etat = tmp_path / ".atelier" / "etat.json"
    apprendre(ouvrir(tmp_path, True), "abonnement")
    chantier = Chantier.charger(etat)
    chantier.noter(ancien_depart, auteur="orchestrateur")
    chantier.noter(ancienne_cle, auteur="orchestrateur")
    chantier.sauver(etat)
    atelier = ouvrir(tmp_path, True)
    apprendre(atelier, "abonnement")
    assert textes(atelier)[1:] == [
        CLE_PRESENTE,
        ABONNEMENT_MALGRE_VARIABLE,
        ancien_depart,
        ancienne_cle,
        CLE_PRESENTE,
        ABONNEMENT_MALGRE_VARIABLE,
    ]


def test_plusieurs_agents_apprennent_la_source_en_meme_temps(tmp_path):
    atelier = ouvrir(tmp_path, False)
    avant = len(textes(atelier))
    atelier.moteur.agent.source_connexion = "clé API"
    appels = []
    noter = atelier._noter_annonce
    atelier._noter_annonce = lambda *arguments: (appels.append(1), noter(*arguments))
    depart = threading.Barrier(8, timeout=5)

    def agent(numero):
        depart.wait()
        for _ in range(20):
            atelier.moteur.agent.sur_evenement(evenement(f"T{numero}-ouvrier-1"))

    fils = [threading.Thread(target=agent, args=(n,), daemon=True) for n in range(8)]
    for fil in fils:
        fil.start()
    for fil in fils:
        fil.join(timeout=5)
    assert not any(fil.is_alive() for fil in fils)
    assert textes(atelier)[avant:] == [CLE_SANS_VARIABLE]
    assert len(appels) == 1  # le fil est parcouru une fois par ouverture, pas à chaque événement


def test_une_seule_confirmation_par_ouverture_meme_si_la_source_change(tmp_path):
    atelier = ouvrir(tmp_path, False)
    apprendre(atelier, "abonnement")
    apprendre(atelier, "clé API")  # la suivante attendra l'ouverture suivante
    assert annonces(textes(atelier)) == [ATTENDUE, ABONNEMENT]
    atelier = ouvrir(tmp_path, False)
    apprendre(atelier, "clé API")
    assert annonces(textes(atelier)) == [ATTENDUE, ABONNEMENT, CLE_SANS_VARIABLE]


def test_sans_variable_puis_avec_puis_sans_la_confirmation_promise_est_ecrite(tmp_path):
    # Enchaînement fautif de la deuxième tentative : la confirmation était écartée parce qu'elle
    # répétait la dernière confirmation, alors qu'un départ écrit depuis la promettait.
    apprendre(ouvrir(tmp_path, False), "abonnement")
    ouvrir(tmp_path, True)  # aucun agent ne travaille pendant ce démarrage
    atelier = ouvrir(tmp_path, False)
    apprendre(atelier, "abonnement")
    assert textes(atelier)[1:] == [ATTENDUE, ABONNEMENT, CLE_PRESENTE, ATTENDUE, ABONNEMENT]


def test_cle_puis_abonnement_puis_cle_le_fil_finit_sur_la_cle(tmp_path):
    # Enchaînement fautif de la troisième tentative : la troisième confirmation était écartée
    # parce qu'une confirmation identique existait depuis le dernier départ, et le fil restait
    # sur « compté sur ton abonnement » alors qu'une clé était facturée.
    for source in ("clé API", "abonnement", "clé API"):
        atelier = ouvrir(tmp_path, False)
        apprendre(atelier, source)
    assert textes(atelier)[1:] == [ATTENDUE, CLE_SANS_VARIABLE, ABONNEMENT, CLE_SANS_VARIABLE]


def test_un_redemarrage_identique_relu_sur_disque_n_ajoute_rien(tmp_path):
    for variable in (False, True):
        depot = tmp_path / str(variable)
        apprendre(ouvrir(depot, variable), "clé API")
        avant = textes(ouvrir(depot, variable))
        atelier = ouvrir(depot, variable)
        apprendre(atelier, "clé API")
        assert textes(atelier) == avant
        assert annonces(avant)[-1] == (CLE if variable else CLE_SANS_VARIABLE)


DEMARRAGES = [(v, s) for v in (False, True) for s in ("", "abonnement", "clé API")]


def promesse_en_attente(fil):
    """Vrai si une annonce de départ promettant la source suit la dernière confirmation."""
    depuis = []
    for texte in annonces(fil):
        depuis = [] if texte in CONFIRMATIONS else [*depuis, texte]
    return annonce_de_depart("réel", False) in depuis


def relire(sauve):
    """Le chantier tel qu'un démarrage le relit : le même aller-retour JSON que `etat.json`."""
    return Chantier.depuis_dict(json.loads(sauve)) if sauve else None


def verifier_un_demarrage(depot, sauve, demarrage, precedent):
    """Ouvre le projet sur l'état `sauve`, apprend la source, vérifie A, B, C et D.

    Rend l'état sauvé à la fin de ce démarrage, tel que `Chantier.sauver` l'écrirait.
    """
    variable, source = demarrage
    atelier = ouvrir(depot, variable, relire(sauve))
    fil_ouvert = textes(atelier)
    apprendre(atelier, source)
    fil = textes(atelier)
    if source:
        confirmation = annonce_de_source(source, variable)
        assert annonces(fil)[-1] == confirmation  # A
        if promesse_en_attente(fil_ouvert):
            assert fil == [*fil_ouvert, confirmation]  # D : la promesse est tenue
    else:
        assert fil == fil_ouvert  # une source inconnue n'écrit rien
    suite = annonces(fil)
    assert all(a != b for a, b in zip(suite, suite[1:], strict=False))  # B
    if precedent == demarrage:
        assert fil == [e["texte"] for e in relire(sauve).evenements]  # C : rien n'est ajouté
    return json.dumps(atelier.moteur.chantier.en_dict(), ensure_ascii=False)


def test_tous_les_enchainements_de_un_a_quatre_demarrages(tmp_path, monkeypatch):
    """Parcourt l'arbre des enchaînements de un à quatre démarrages, sans réseau ni agent.

    Chaque nœud est un enchaînement : son dernier démarrage part de l'état laissé par son
    préfixe, déjà vérifié, si bien que chaque enchaînement est vérifié démarrage par démarrage.
    L'état passe d'un démarrage au suivant par le même JSON que `.atelier/etat.json`, mais en
    mémoire : l'écriture sur disque est coupée ici, et éprouvée par les tests nommés plus haut.
    """
    monkeypatch.setattr(Atelier, "_sauver", lambda atelier: None)
    parcourus = 0
    a_visiter = [((), "")]  # (enchaînement, état sauvé à sa fin ; vide avant le premier)
    while a_visiter:
        enchainement, sauve = a_visiter.pop()
        if len(enchainement) == 4:
            continue
        precedent = enchainement[-1] if enchainement else None
        for demarrage in DEMARRAGES:
            suite = verifier_un_demarrage(tmp_path, sauve, demarrage, precedent)
            parcourus += 1
            a_visiter.append(((*enchainement, demarrage), suite))
    assert parcourus == 6 + 6**2 + 6**3 + 6**4  # 1554 enchaînements


def test_un_changement_d_environnement_est_ecrit_au_redemarrage(tmp_path):
    chantier = Chantier(projet="essai", contrat=Contrat(objectif="Essai"))
    for variable in ({}, {"ANTHROPIC_API_KEY": SECRET}, {}):
        atelier = Atelier(tmp_path, chantier, AgentSimule(), ControlesSimules(), {})
        atelier.annoncer_connexion(variable)
    assert textes(atelier)[-3:] == [ATTENDUE, CLE_PRESENTE, ATTENDUE]


def test_le_rappel_d_activite_continue_de_servir_le_tableau(tmp_path):
    agent = AgentSimule()
    atelier = atelier_reel(tmp_path, agent)
    atelier.annoncer_connexion({})
    agent.sur_evenement(evenement())
    (en_marche,) = atelier.activite.agents()
    assert en_marche["lignes"] == ["Lit la consigne"]


def test_la_fabrique_enveloppee_annonce(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    atelier = avec_annonce(atelier_reel)(tmp_path)
    assert textes(atelier)[-1] == ATTENDUE


# --- Le vrai chemin de « servir » : projet donné, projet découvert, projet créé ----------


def depot_git(dossier):
    dossier.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=dossier, check=True)
    return dossier


def arguments_servir(racine, depot=None):
    return argparse.Namespace(depot=str(depot) if depot else None, racine=str(racine), port=0)


def test_servir_annonce_pour_le_projet_donne(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "valeur-factice")
    depot = depot_git(tmp_path / "racine" / "donne")
    projets, _ = monter_projets(arguments_servir(tmp_path / "racine", depot))
    assert textes(projets.atelier())[-1] == CLE_PRESENTE


def test_servir_annonce_pour_un_projet_decouvert(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    depot_git(tmp_path / "racine" / "decouvert")
    projets, _ = monter_projets(arguments_servir(tmp_path / "racine"))
    assert projets.courant == "decouvert"
    assert textes(projets.atelier())[-1] == ATTENDUE


def test_servir_annonce_pour_un_projet_cree_ensuite(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "valeur-factice")
    projets, _ = monter_projets(arguments_servir(tmp_path / "racine"))
    cle = projets.creer("Nouveau projet")
    assert textes(projets.ateliers[cle])[-1] == CLE_PRESENTE
