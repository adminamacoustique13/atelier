"""Le serveur : autorisations, suivi de l'activité et arrêt, en mode simulé.

Aucun appel réel : des agents simulés, un guichet de l'atelier, et le vrai serveur HTTP sur
127.0.0.1. Chaque attente est bornée.
"""

import json
import pathlib
import shutil
import sys
import threading
import time
import urllib.error
import urllib.request
from argparse import Namespace
from dataclasses import dataclass, field

import pytest

from atelier import mise_a_jour as mise_a_jour_module
from atelier import modele as modele_module
from atelier.__main__ import commande_instantanes, projet_simule
from atelier.agents import AgentClaude, AgentSimule, Resultat
from atelier.consignes import MARQUE_BLOCAGE, message_de_diagnostic
from atelier.controles import ControlesSimules
from atelier.guichet import ARRETE, Guichet
from atelier.mise_a_jour import Etat, MiseAJour, MiseAJourSimulee
from atelier.mise_a_jour import Resultat as ResultatMaj
from atelier.modele import Chantier, Contrat, Tache
from atelier.moteur import ABANDONNER, RELANCER_TEL, Moteur
from atelier.projets import Projets
from atelier.serveur import (
    ACCEPTER_OUTILS,
    DEBLOQUE,
    LANCEURS_GENERAUX,
    REFUSER_OUTILS,
    Activite,
    Atelier,
    SuiviMiseAJour,
    creer_serveur,
    lanceur_general,
    point_d_etape,
    statistiques,
)

OUTILS_DE_LA_DECISION = ["Relancer au même niveau", "Relancer un cran plus haut"]
OUTILS_DE_LA_DECISION += ["Abandonner cette tâche"]
COMMANDE_SIMULEE = {"command": "npm install left-pad"}
REGLE_SIMULEE = "Bash(npm install:*)"
PLAN = {"objectif": "But", "taches": [{"id": "A", "titre": "Un", "perimetre": ["a.py"]}]}


def attendre(condition, delai=5.0):
    """Rend True dès que la condition est vraie, False si le délai est écoulé."""
    limite = time.monotonic() + delai
    while time.monotonic() < limite:
        if condition():
            return True
        time.sleep(0.01)
    return False


def tache(identifiant, **champs):
    reglages = {"titre": f"Tâche {identifiant}", "type": "mecanique", "criteres": ["Ça marche."]}
    reglages["perimetre"] = [f"{identifiant.lower()}.py"]
    return Tache(id=identifiant, **{**reglages, **champs})


def chantier(taches, **contrat):
    reglages = {"objectif": "Essai", "valide": True, **contrat}
    return Chantier(projet="essai", contrat=Contrat(**reglages), taches=taches)


def atelier_simule(
    depot, taches=(), profil=None, agent=None, guichet=None, valide=True, controles=None, **champs
):
    c = chantier(list(taches), valide=valide)
    perimetres = {t.id: t.perimetre for t in c.taches}
    agent = agent or AgentSimule(perimetres=perimetres, **champs)
    controles = controles or ControlesSimules()
    return Atelier(depot, c, agent, controles, profil or {}, guichet=guichet)


class Tableau:
    """Un serveur HTTP réel sur la machine locale, pour un atelier."""

    def __init__(self, atelier, racine):
        self.atelier = atelier
        projets = Projets(racine, lambda dossier, nom: atelier)
        projets.ajouter(atelier)
        self.serveur = creer_serveur(projets, 0)
        self.port = self.serveur.server_address[1]
        threading.Thread(target=self.serveur.serve_forever, args=(0.01,), daemon=True).start()

    def appeler(self, chemin, corps=None, brut=None):
        donnees = brut if brut is not None else json.dumps(corps or {}).encode("utf-8")
        requete = urllib.request.Request(f"http://127.0.0.1:{self.port}{chemin}", data=donnees)
        requete.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(requete, timeout=5) as reponse:
                return reponse.status, json.loads(reponse.read())
        except urllib.error.HTTPError as erreur:
            return erreur.code, json.loads(erreur.read())

    def etat(self):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/api/etat", timeout=5) as r:
            return json.loads(r.read())

    def fermer(self):
        self.serveur.shutdown()
        self.serveur.server_close()
        agent, guichet = self.atelier.moteur.agent, self.atelier.guichet
        agent.delai_s = 0
        agent.arreter()
        for t in self.atelier.moteur.chantier.taches:
            agent.arreter(t.id)
        for demande in guichet.ouvertes() if guichet else []:
            guichet.repondre(demande["id"], "non")


@pytest.fixture
def tableau(tmp_path):
    ouverts = []

    def ouvrir(atelier):
        ouverts.append(Tableau(atelier, tmp_path))
        return ouverts[-1]

    yield ouvrir
    for ouvert in ouverts:
        ouvert.fermer()


def demander_en_fil(guichet, agent="Z-ouvrier-1", entree=None):
    """Dépose une demande au guichet depuis un fil à part ; rend la liste qui recevra la réponse."""
    reponses = []

    def demander():
        reponses.append(guichet.demander(agent, "Bash", entree or dict(COMMANDE_SIMULEE)))

    threading.Thread(target=demander, daemon=True).start()
    assert attendre(lambda: any(d["agent"] == agent for d in guichet.ouvertes()))
    return reponses


def demo_prete(tableau, depot):
    """La démonstration servie, le contrat validé : le premier ouvrier attend une réponse."""
    atelier = projet_simule(depot, "Démo", 0.0)
    vus = []
    suite = atelier.moteur.agent.sur_evenement
    atelier.moteur.agent.sur_evenement = lambda evenement: (vus.append(evenement), suite(evenement))
    serveur = tableau(atelier)
    serveur.appeler("/api/message", {"texte": "Construis un moteur."})
    assert attendre(lambda: not serveur.etat()["occupe"])
    serveur.appeler("/api/contrat/valider")
    assert attendre(lambda: serveur.etat()["autorisations"])
    return serveur, vus


# --- la vue -------------------------------------------------------------------------


def test_la_vue_porte_les_autorisations_et_les_agents_meme_au_repos(tableau, tmp_path):
    serveur = tableau(atelier_simule(tmp_path))
    etat = serveur.etat()
    assert etat["autorisations"] == [] and etat["agents"] == []


def test_un_vrai_agent_recoit_un_vrai_guichet_et_un_agent_simule_aucun(tmp_path):
    vrai = AgentClaude({})
    atelier = atelier_simule(tmp_path / "a", agent=vrai)
    assert isinstance(atelier.guichet, Guichet) and vrai.guichet is atelier.guichet
    assert vrai.sur_evenement == atelier.activite.ajouter

    simule = AgentSimule()
    sans = atelier_simule(tmp_path / "b", agent=simule)
    assert sans.guichet is None and simule.guichet is None
    assert simule.sur_evenement == sans.activite.ajouter

    donne = Guichet()
    avec = atelier_simule(tmp_path / "c", guichet=donne)
    assert avec.guichet is donne and avec.moteur.agent.guichet is donne

    pose = AgentSimule(guichet=donne)
    assert atelier_simule(tmp_path / "d", agent=pose).guichet is donne


def test_le_serveur_n_ecoute_que_sur_la_machine_locale(tableau, tmp_path):
    serveur = tableau(atelier_simule(tmp_path))
    assert serveur.serveur.server_address[0] == "127.0.0.1"


def test_les_routes_existantes_gardent_leur_reponse(tableau, tmp_path):
    serveur = tableau(atelier_simule(tmp_path))
    code, reponse = serveur.appeler("/api/message", {"texte": ""})
    assert code == 200 and "autorisation" not in reponse and "arret" not in reponse
    assert reponse["mode"] == "réel" and reponse["agents"] == []
    assert serveur.appeler("/api/inconnue", {})[0] == 404


# --- la démonstration et les autorisations ---------------------------------------------


def test_la_demonstration_depose_une_demande_et_elle_se_regle_de_bout_en_bout(tableau, tmp_path):
    serveur, vus = demo_prete(tableau, tmp_path / "demo")
    etat = serveur.etat()
    (demande,) = etat["autorisations"]
    assert set(demande) == {"id", "agent", "outil", "phrase", "regle", "detail", "regles_chantier"}
    assert demande["outil"] == "Bash" and demande["regle"] == REGLE_SIMULEE
    assert demande["detail"] == "npm install left-pad"
    assert "npm install left-pad" in demande["phrase"]
    assert demande["agent"].endswith("-ouvrier-1")
    (agent,) = [a for a in etat["agents"] if a["nom"] == demande["agent"]]
    assert agent["role"] == "ouvrier" and agent["tache"] == demande["agent"][: -len("-ouvrier-1")]
    assert agent["lignes"] == [
        "Lit la consigne",
        "En attente de ton autorisation : Lance npm install left-pad",
    ]
    assert "1 autorisation" in etat["point_d_etape"]

    code, reponse = serveur.appeler(
        "/api/autorisation", {"id": demande["id"], "choix": "une_fois", "message": "vas-y"}
    )
    assert code == 200
    assert reponse["autorisation"] == {"reglee": True, "phrase": "Autorisé cette fois."}
    assert reponse["autorisations"] == []
    assert attendre(lambda: not serveur.atelier.en_marche())
    assert serveur.etat()["agents"] == []
    textes = [e["contenu"] for e in vus if e["type"] == "texte"]
    assert "Réponse de la personne responsable : autorisé une fois. vas-y" in textes
    assert not (tmp_path / "demo" / "chantier" / "profil.json").exists()


def test_toujours_inscrit_la_regle_au_profil_de_la_demonstration(tableau, tmp_path):
    chemin = tmp_path / "demo" / "chantier" / "profil.json"
    chemin.parent.mkdir(parents=True)
    chemin.write_text(json.dumps({"nom": "X", "commandes_permises": ["uv"]}), "utf-8")
    serveur, vus = demo_prete(tableau, tmp_path / "demo")
    (demande,) = serveur.etat()["autorisations"]
    code, reponse = serveur.appeler(
        "/api/autorisation", {"id": demande["id"], "choix": "toujours", "message": ""}
    )
    assert code == 200 and reponse["autorisation"] == {
        "reglee": True,
        "phrase": "Autorisé pour ce projet : la règle Bash(npm install:*) est enregistrée "
        "dans le profil.",
    }
    assert json.loads(chemin.read_text("utf-8")) == {
        "nom": "X",
        "commandes_permises": ["uv"],
        "autorisations": [REGLE_SIMULEE],
    }
    assert serveur.atelier.moteur.profil["autorisations"] == [REGLE_SIMULEE]
    assert attendre(lambda: not serveur.atelier.en_marche())
    textes = [e["contenu"] for e in vus if e["type"] == "texte"]
    assert "Réponse de la personne responsable : autorisé pour ce projet." in textes


def test_toujours_ajoute_la_regle_une_seule_fois_et_la_fait_valoir_a_chaud(tableau, tmp_path):
    profil = {"autorisations": ["Read"]}
    agent = AgentSimule()
    agent.profil = profil  # comme le profil d'un vrai agent : le même objet que celui du moteur
    atelier = atelier_simule(tmp_path, agent=agent, profil=profil, guichet=Guichet())
    serveur = tableau(atelier)
    for rang in (1, 2):
        reponses = demander_en_fil(atelier.guichet, f"Z-ouvrier-{rang}")
        (demande,) = atelier.guichet.ouvertes()
        _, reponse = serveur.appeler(
            "/api/autorisation", {"id": demande["id"], "choix": "toujours"}
        )
        assert reponse["autorisation"]["reglee"] is True
        assert attendre(reponses.copy)
        assert reponses[0].choix == "toujours"
    chemin = tmp_path / "chantier" / "profil.json"
    texte = chemin.read_text("utf-8")
    assert texte.endswith("\n")
    assert json.loads(texte) == {"autorisations": ["Read", REGLE_SIMULEE]}
    assert profil["autorisations"] == ["Read", REGLE_SIMULEE]
    assert atelier.moteur.profil["autorisations"] == ["Read", REGLE_SIMULEE]


def test_toujours_sans_cle_ni_fichier_cree_la_liste(tableau, tmp_path):
    atelier = atelier_simule(tmp_path, guichet=Guichet())
    serveur = tableau(atelier)
    demander_en_fil(atelier.guichet)
    (demande,) = atelier.guichet.ouvertes()
    serveur.appeler("/api/autorisation", {"id": demande["id"], "choix": "toujours"})
    chemin = tmp_path / "chantier" / "profil.json"
    assert json.loads(chemin.read_text("utf-8")) == {"autorisations": [REGLE_SIMULEE]}


def test_un_profil_illisible_n_empeche_pas_l_autorisation_et_le_dit(tableau, tmp_path):
    chemin = tmp_path / "chantier" / "profil.json"
    chemin.parent.mkdir(parents=True)
    chemin.write_text("pas du json", "utf-8")
    atelier = atelier_simule(tmp_path, guichet=Guichet())
    serveur = tableau(atelier)
    reponses = demander_en_fil(atelier.guichet)
    (demande,) = atelier.guichet.ouvertes()
    _, reponse = serveur.appeler("/api/autorisation", {"id": demande["id"], "choix": "toujours"})
    assert reponse["autorisation"]["reglee"] is True
    assert reponse["autorisation"]["phrase"] == (
        "Autorisé cette fois, mais la règle n'a pas pu être enregistrée : "
        "le profil du projet (chantier/profil.json) n'est pas lisible, corrige-le."
    )
    assert attendre(lambda: reponses) and chemin.read_text("utf-8") == "pas du json"
    assert "autorisations" not in atelier.moteur.profil


def test_toujours_sans_regle_sure_laisse_la_demande_ouverte(tableau, tmp_path):
    atelier = atelier_simule(tmp_path, guichet=Guichet())
    serveur = tableau(atelier)
    reponses = demander_en_fil(atelier.guichet, entree={"command": "ls; rm x"})
    (demande,) = serveur.etat()["autorisations"]
    assert demande["regle"] == ""
    _, reponse = serveur.appeler("/api/autorisation", {"id": demande["id"], "choix": "toujours"})
    assert reponse["autorisation"] == {
        "reglee": False,
        "phrase": "Aucune règle sûre n'existe pour cette demande : "
        "autorise-la une fois, ou refuse-la.",
    }
    assert len(reponse["autorisations"]) == 1 and reponses == []
    assert not (tmp_path / "chantier" / "profil.json").exists()

    _, reponse = serveur.appeler(
        "/api/autorisation", {"id": demande["id"], "choix": "non", "message": "pas ça"}
    )
    assert reponse["autorisation"] == {"reglee": True, "phrase": "Refusé."}
    assert attendre(lambda: reponses)
    assert (reponses[0].choix, reponses[0].message) == ("non", "pas ça")


def test_une_demande_ou_un_choix_inconnu_ne_regle_rien(tableau, tmp_path):
    atelier = atelier_simule(tmp_path, guichet=Guichet())
    serveur = tableau(atelier)
    reponses = demander_en_fil(atelier.guichet)
    (demande,) = atelier.guichet.ouvertes()

    _, reponse = serveur.appeler("/api/autorisation", {"id": "inconnue", "choix": "une_fois"})
    assert reponse["autorisation"] == {
        "reglee": False,
        "phrase": "Cette demande n'existe plus : elle a déjà reçu une réponse, "
        "ou son agent s'est arrêté.",
    }
    _, reponse = serveur.appeler("/api/autorisation", {"id": demande["id"], "choix": "peut-être"})
    assert reponse["autorisation"] == {
        "reglee": False,
        "phrase": (
            "Ce choix n'existe pas : réponds « une fois », « toujours », "
            "« pendant ce chantier » ou « non »."
        ),
    }
    assert len(atelier.guichet.ouvertes()) == 1 and reponses == []

    serveur.appeler("/api/autorisation", {"id": demande["id"], "choix": "une_fois"})
    _, deuxieme = serveur.appeler("/api/autorisation", {"id": demande["id"], "choix": "non"})
    assert deuxieme["autorisation"]["reglee"] is False
    assert attendre(lambda: reponses) and reponses[0].choix == "une_fois"


def test_un_message_qui_n_est_pas_du_texte_est_ignore(tableau, tmp_path):
    atelier = atelier_simule(tmp_path, guichet=Guichet())
    serveur = tableau(atelier)
    reponses = demander_en_fil(atelier.guichet)
    (demande,) = atelier.guichet.ouvertes()
    serveur.appeler("/api/autorisation", {"id": demande["id"], "choix": "non", "message": 12})
    assert attendre(lambda: reponses) and reponses[0].message == ""


def test_sans_guichet_aucune_demande_n_est_reglee(tableau, tmp_path):
    serveur = tableau(atelier_simule(tmp_path))
    _, reponse = serveur.appeler("/api/autorisation", {"id": "x", "choix": "une_fois"})
    assert reponse["autorisation"]["reglee"] is False


def test_les_corps_incomplets_ou_illisibles_rendent_400(tableau, tmp_path):
    serveur = tableau(atelier_simule(tmp_path, guichet=Guichet()))
    attendu = {"erreur": "Demande introuvable ou incomplète."}
    assert serveur.appeler("/api/autorisation", {"id": "x"}) == (400, attendu)
    assert serveur.appeler("/api/autorisation", brut=b"[]") == (400, attendu)
    assert serveur.appeler("/api/arreter", brut=b"[1]") == (400, attendu)
    assert serveur.appeler("/api/arreter", brut=b"{pas du json") == (400, attendu)


# --- les lignes d'activité ----------------------------------------------------------------


def evenement(agent, genre, contenu):
    return {"agent": agent, "type": genre, "contenu": contenu}


def lignes_de(activite, nom):
    return next(a["lignes"] for a in activite.agents() if a["nom"] == nom)


def test_les_lignes_d_un_agent_sont_bornees_aux_trente_dernieres():
    activite = Activite()
    for rang in range(100):
        activite.ajouter(evenement("B-ouvrier-1", "texte", f"ligne {rang}\n"))
    lignes = lignes_de(activite, "B-ouvrier-1")
    assert len(lignes) == 30 and lignes[0] == "ligne 70" and lignes[-1] == "ligne 99"
    assert len(activite._lignes["B-ouvrier-1"]) == 30  # la mémoire aussi est bornée


def test_l_etape_annoncee_et_les_durees_de_chaque_agent():
    activite = Activite()
    temps = [100.0]
    activite.horloge = lambda: temps[0]
    activite.ajouter(evenement("B-ouvrier-1", "texte", "**Étape 1/3 : lire le périmètre**\n"))
    temps[0] = 130.0
    activite.ajouter(evenement("B-ouvrier-1", "outil", "Lit a.py"))
    activite.ajouter(evenement("B-ouvrier-1", "texte", "Étape : écrire les tests\nJe commence.\n"))
    temps[0] = 145.0
    (agent,) = activite.agents()
    assert agent["etape"] == "écrire les tests"
    assert (agent["depuis_s"], agent["calme_s"]) == (45, 15)
    activite.ajouter(evenement("B-ouvrier-1", "texte", "Étape 3/3 : relire\n"))
    assert activite.agents()[0]["etape"] == "3/3 · relire"
    activite.ajouter(evenement("B-ouvrier-1", "fin", "ok"))
    assert activite.agents() == [] and not activite._temps and not activite._etapes


def test_un_texte_coupe_en_morceaux_se_recompose_en_lignes():
    activite = Activite()
    for morceau in ("Bon", "jour\r\nsui", "te\n\n  \nfin", " de ligne"):
        activite.ajouter(evenement("B-ouvrier-1", "texte", morceau))
    assert lignes_de(activite, "B-ouvrier-1") == ["Bonjour", "suite", "fin de ligne"]


def test_un_outil_et_une_attente_ont_leur_ligne_et_ferment_la_ligne_en_cours():
    activite = Activite()
    activite.ajouter(evenement("B-ouvrier-1", "texte", "Je regarde"))
    activite.ajouter(evenement("B-ouvrier-1", "outil", "Lit a.py"))
    activite.ajouter(evenement("B-ouvrier-1", "attente", "Lance npm test"))
    activite.ajouter(evenement("B-ouvrier-1", "texte", "Merci"))
    assert lignes_de(activite, "B-ouvrier-1") == [
        "Je regarde",
        "Lit a.py",
        "En attente de ton autorisation : Lance npm test",
        "Merci",
    ]


def test_la_fin_retire_l_agent_et_ses_lignes():
    activite = Activite()
    activite.ajouter(evenement("B-ouvrier-1", "outil", "Lit a.py"))
    activite.ajouter(evenement("C-ouvrier-1", "texte", "reste"))
    activite.ajouter(evenement("B-ouvrier-1", "fin", "Terminé."))
    assert [a["nom"] for a in activite.agents()] == ["C-ouvrier-1"]
    activite.ajouter(evenement("B-ouvrier-2", "outil", "Lit b.py"))
    assert lignes_de(activite, "B-ouvrier-2") == ["Lit b.py"]


def test_le_nom_de_l_agent_se_lit_par_la_droite():
    activite = Activite()
    for nom in ("B.1-ouvrier-2", "api-v2-verificateur-1", "orchestrateur"):
        activite.ajouter(evenement(nom, "outil", "x"))
    lus = [(a["nom"], a["tache"], a["role"]) for a in activite.agents()]
    assert lus == [
        ("B.1-ouvrier-2", "B.1", "ouvrier"),
        ("api-v2-verificateur-1", "api-v2", "verificateur"),
        ("orchestrateur", "", "orchestrateur"),
    ]


def test_une_ligne_trop_longue_est_coupee_et_un_texte_sans_fin_reste_borne():
    activite = Activite()
    activite.ajouter(evenement("B-ouvrier-1", "texte", "a" * 650 + "\n"))
    assert [len(ligne) for ligne in lignes_de(activite, "B-ouvrier-1")] == [300, 300, 50]
    for _ in range(100):
        activite.ajouter(evenement("C-ouvrier-1", "texte", "b" * 1000))
    lignes = lignes_de(activite, "C-ouvrier-1")
    assert len(lignes) <= 30 and all(len(ligne) <= 300 for ligne in lignes)
    assert len(activite._reste["C-ouvrier-1"]) < 300


def test_des_evenements_illisibles_sont_ignores():
    activite = Activite()
    for mauvais in (None, {}, {"agent": "x"}, "texte", {"agent": "x", "type": "texte"}):
        activite.ajouter(mauvais)
    assert activite.agents() == []
    activite.ajouter(evenement("x-ouvrier-1", "texte", 42))
    assert lignes_de(activite, "x-ouvrier-1") == ["42"]


def test_des_agents_en_parallele_ne_melangent_pas_leurs_lignes():
    activite = Activite()
    erreurs = []

    def ecrire(nom):
        try:
            for rang in range(200):
                activite.ajouter(evenement(nom, "texte", f"{nom} {rang}\n"))
                activite.agents()
        except Exception as erreur:  # noqa: BLE001 - le test doit voir toute erreur
            erreurs.append(erreur)

    fils = [threading.Thread(target=ecrire, args=(f"T{n}-ouvrier-1",)) for n in range(8)]
    for fil in fils:
        fil.start()
    for fil in fils:
        fil.join(10)
    assert not erreurs and not any(fil.is_alive() for fil in fils)
    for agent in activite.agents():
        attendues = [f"{agent['nom']} {rang}" for rang in range(170, 200)]
        assert agent["lignes"] == attendues


# --- le point d'étape et les statistiques -------------------------------------------------


def test_le_point_d_etape_attend_la_personne_pour_une_autorisation():
    c = chantier([tache("A", etat="en_cours")])
    assert point_d_etape(c, True) == (
        "0 tâches vérifiées sur 1, 1 en cours. Je n'ai pas besoin de toi pour l'instant."
    )
    assert point_d_etape(c, True, 1) == (
        "0 tâches vérifiées sur 1. J'ai besoin de toi pour 1 autorisation."
    )
    c.demandes.append({"id": "A-1", "tache": "A", "reponse": None})
    assert point_d_etape(c, True) == "0 tâches vérifiées sur 1. J'ai besoin de toi pour 1 décision."
    assert point_d_etape(c, True, 2) == (
        "0 tâches vérifiées sur 1. J'ai besoin de toi pour 1 décision et 2 autorisations."
    )


def test_les_statistiques_ne_comptent_pas_un_arret_comme_un_refus():
    arretee = tache("A", etat="revenu", historique=[{"issue": "arretee"}], tentatives=1)
    bacle = tache("B", etat="revenu", historique=[{"issue": "bacle"}], tentatives=1)
    (ligne,) = statistiques(chantier([arretee, bacle]))
    assert ligne["refus"] == 1 and ligne["premier_coup"] == 0


# --- l'arrêt d'une tâche ------------------------------------------------------------------


class ControlesEspions(ControlesSimules):
    """Des contrôles qui demandent l'arrêt de la tâche à un moment choisi.

    `action(tache)` fait la demande (par défaut `moteur.arreter`) ; sa réponse est gardée.
    """

    def __init__(self, moment, action=None):
        self.moment, self.action, self.moteur = moment, action, None
        self.reponses, self.annulees, self.enregistrees = [], [], []

    def _arreter(self, moment, tache):
        if moment == self.moment:
            action = self.action or (lambda t: self.moteur.arreter(t.id))
            self.reponses.append(action(tache))

    def preparer(self, tache):
        self._arreter("preparer", tache)

    def mecaniques(self, tache, dossier):
        self._arreter("mecaniques", tache)
        return True, ""

    def enregistrer(self, tache, dossier):
        self.enregistrees.append(tache.id)
        self._arreter("enregistrement", tache)

    def annuler(self, tache, dossier):
        self.annulees.append(tache.id)
        self._arreter("annuler", tache)


class AgentLentAuVerificateur(AgentSimule):
    """Le vérificateur met longtemps à répondre : on a le temps de l'arrêter."""

    def executer(self, consigne, modele, effort, dossier, lecture_seule=False, contexte=None):
        self.delai_s = 30 if (contexte or {}).get("role") == "verificateur" else 0
        return super().executer(consigne, modele, effort, dossier, lecture_seule, contexte)


class AgentArrete(AgentSimule):
    """Rend l'arrêt dans son résultat sans que le moteur l'ait demandé (arrêt direct)."""

    def __init__(self, role):
        super().__init__()
        self.role = role

    def executer(self, consigne, modele, effort, dossier, lecture_seule=False, contexte=None):
        if (contexte or {}).get("role") != self.role:
            return super().executer(consigne, modele, effort, dossier, lecture_seule, contexte)
        self.appels.append(contexte)
        erreur = "Arrêté par la personne responsable."
        return Resultat(ok=False, erreur=erreur, cout_usd=0.5, tokens=70)


def moteur_de(taches, agent=None, controles=None, sur_changement=None):
    c = chantier(taches)
    agent = agent or AgentSimule(perimetres={t.id: t.perimetre for t in taches})
    return Moteur(c, agent, controles or ControlesSimules(), sur_changement=sur_changement)


def moteur_arretant_a_la_note(debut):
    """Un moteur dont la tâche A est arrêtée dès que la note qui commence ainsi est écrite."""
    controles, reponses = ControlesEspions("jamais"), []

    def rappel():
        dernieres = [e["texte"] for e in moteur.chantier.evenements[-1:]]
        if not reponses and any(texte.startswith(debut) for texte in dernieres):
            reponses.append(moteur.arreter("A"))

    moteur = moteur_de([tache("A")], controles=controles, sur_changement=rappel)
    return moteur, controles, reponses


def notes(moteur):
    return [e["texte"] for e in moteur.chantier.evenements]


def verifier_retour_a_la_personne(moteur, identifiant="A"):
    """La tâche est revenue avec une seule décision, sans seconde chance ni montée."""
    t = moteur.chantier.tache(identifiant)
    assert t.etat == "revenu" and t.montees == 0 and moteur.chantier.montees == 0
    (demande,) = moteur.chantier.demandes
    assert demande["question"] == f"Tâche {identifiant}, « Tâche {identifiant} » : arrêtée par toi."
    assert demande["options"] == OUTILS_DE_LA_DECISION and demande["reponse"] is None
    assert t.historique[-1]["issue"] == "arretee"
    assert t.historique[-1]["detail"] == "Arrêtée par la personne responsable."
    texte = " ".join(notes(moteur))
    assert "Seconde chance" not in texte and "monte d'un cran" not in texte
    assert "J'ai besoin de toi : arrêtée par toi." in notes(moteur)
    assert moteur._arretees == set()


def test_arreter_une_tache_en_cours_la_rend_sans_seconde_chance(tableau, tmp_path):
    atelier = atelier_simule(tmp_path, [tache("A")], delai_s=30)
    serveur = tableau(atelier)
    atelier.lancer()
    assert attendre(lambda: [a["nom"] for a in serveur.etat()["agents"]] == ["A-ouvrier-1"])
    (agent,) = serveur.etat()["agents"]
    assert {k: agent[k] for k in ("nom", "tache", "role", "lignes")} == {
        "nom": "A-ouvrier-1",
        "tache": "A",
        "role": "ouvrier",
        "lignes": ["Lit la consigne"],
    }
    assert agent["etape"] == "" and agent["depuis_s"] >= 0 and agent["calme_s"] >= 0
    dosage = (atelier.moteur.chantier.tache("A").modele, atelier.moteur.chantier.tache("A").effort)

    code, reponse = serveur.appeler("/api/arreter", {"tache": "A"})
    assert code == 200
    assert reponse["arret"] == {"fait": True, "phrase": "Arrêt demandé pour la tâche A."}
    assert attendre(lambda: not atelier.en_marche())
    verifier_retour_a_la_personne(atelier.moteur)
    t = atelier.moteur.chantier.tache("A")
    assert t.tentatives == 1 and (t.modele, t.effort) == dosage
    assert atelier.moteur.chantier.agents_lances == 1
    assert [a["role"] for a in atelier.moteur.agent.appels] == ["ouvrier"]
    assert serveur.etat()["agents"] == []

    atelier.moteur.agent.delai_s = 0
    demande = atelier.moteur.chantier.demandes[0]["id"]
    serveur.appeler("/api/decision", {"id": demande, "choix": "Relancer au même niveau"})
    assert attendre(lambda: not atelier.en_marche())
    assert t.etat == "verifie" and t.tentatives == 2 and (t.modele, t.effort) == dosage


def test_arreter_un_verificateur_rend_la_tache_sans_jugement(tableau, tmp_path):
    atelier = atelier_simule(tmp_path, [tache("A")], agent=AgentLentAuVerificateur())
    serveur = tableau(atelier)
    atelier.lancer()
    assert attendre(lambda: [a["nom"] for a in serveur.etat()["agents"]] == ["A-verificateur-1"])
    assert serveur.appeler("/api/arreter", {"tache": "A"})[1]["arret"]["fait"] is True
    assert attendre(lambda: not atelier.en_marche())
    verifier_retour_a_la_personne(atelier.moteur)
    assert atelier.moteur.chantier.tache("A").verdict == ""
    assert atelier.moteur.chantier.agents_lances == 2


def test_un_arret_entre_l_ouvrier_et_le_verificateur_empeche_le_verificateur():
    controles = ControlesEspions("mecaniques")
    moteur = moteur_de([tache("A")], controles=controles)
    controles.moteur = moteur
    moteur.executer()
    assert controles.reponses == [True]  # aucun agent n'était en marche : le drapeau a tenu
    assert [a["role"] for a in moteur.agent.appels] == ["ouvrier"]
    assert moteur.chantier.agents_lances == 1
    verifier_retour_a_la_personne(moteur)


def test_un_arret_demande_avant_le_depart_de_l_ouvrier_le_retient():
    moteur = moteur_de([tache("A")])
    t = moteur.chantier.tache("A")
    t.etat = "en_cours"
    assert moteur.arreter("A") is True
    moteur._traiter(t)
    assert moteur.agent.appels == [] and moteur.chantier.agents_lances == 0
    assert t.etat == "revenu" and moteur._arretees == set()
    assert moteur.chantier.demandes[0]["options"] == OUTILS_DE_LA_DECISION


def test_un_arret_pour_une_tache_qui_n_est_pas_active_ne_fait_rien():
    moteur = moteur_de([tache("A"), tache("B", depend_de=["A"])])
    assert moteur.arreter("A") is False  # à lancer
    assert moteur.arreter("B") is False
    assert moteur.arreter("Z") is False  # inconnue
    assert moteur._arretees == set()
    moteur.executer()
    assert [t.etat for t in moteur.chantier.taches] == ["verifie", "verifie"]
    assert [t.tentatives for t in moteur.chantier.taches] == [1, 1]
    assert moteur.arreter("A") is False and moteur._arretees == set()


def test_un_arret_pendant_la_preparation_empeche_l_ouvrier():
    controles = ControlesEspions("preparer")
    agent = AgentSimule(delai_s=2)  # l'ouvrier, s'il partait, durerait deux secondes
    moteur = moteur_de([tache("A")], agent=agent, controles=controles)
    controles.moteur = moteur
    moteur.executer()
    assert controles.reponses == [True] and agent.appels == []
    assert controles.annulees == ["A"]  # la copie de travail est jetée
    assert moteur.chantier.agents_lances == 0  # un agent qui n'est pas parti ne compte pas
    assert moteur.chantier.tache("A").tentatives == 0
    verifier_retour_a_la_personne(moteur)
    assert moteur.chantier.tache("A").historique[-1]["tentative"] == 1


def test_un_arret_pendant_la_note_de_l_ouvrier_l_empeche_de_partir():
    moteur, controles, reponses = moteur_arretant_a_la_note("Ouvrier lancé")
    moteur.executer()
    assert reponses == [True] and moteur.agent.appels == []
    assert controles.annulees == ["A"] and moteur.chantier.agents_lances == 0
    verifier_retour_a_la_personne(moteur)


def test_un_arret_pendant_la_note_du_verificateur_l_empeche_de_partir():
    moteur, controles, reponses = moteur_arretant_a_la_note("Vérificateur lancé")
    moteur.executer()
    assert reponses == [True]
    assert [a["role"] for a in moteur.agent.appels] == ["ouvrier"]
    assert controles.annulees == ["A"]
    assert moteur.chantier.agents_lances == 1  # seul l'ouvrier est parti
    assert moteur.chantier.tache("A").tentatives == 1
    verifier_retour_a_la_personne(moteur)


def test_un_arret_apres_un_refus_garde_aussi_sa_trace_dans_l_historique():
    controles = ControlesEspions("annuler")
    agent = AgentSimule({"A": ["bacle", "ok"]})  # la reprise à chaud rejoue le refus
    moteur = moteur_de([tache("A")], agent=agent, controles=controles)
    controles.moteur = moteur
    moteur.executer()
    t = moteur.chantier.tache("A")
    # La copie n'est jetée qu'après la reprise refusée : c'est là que l'arrêt est demandé.
    assert controles.annulees == ["A"]
    assert [h["issue"] for h in t.historique] == ["bacle", "bacle", "arretee"]
    assert [h["tentative"] for h in t.historique] == [1, 1, 2]
    assert [h["reprise"] for h in t.historique] == [False, True, False]
    assert [a["role"] for a in agent.appels] == ["ouvrier", "verificateur"] * 2
    assert t.etat == "revenu" and t.tentatives == 1
    assert moteur.chantier.demandes[-1]["question"].endswith("arrêtée par toi.")


def test_un_arret_juste_apres_l_avis_du_verificateur_l_emporte_sur_l_enregistrement(monkeypatch):
    from atelier import moteur as module

    controles = ControlesEspions("jamais")
    moteur = moteur_de([tache("A")], controles=controles)
    lire = module.lire_verdict

    def lire_puis_arreter(texte):
        controles.reponses.append(moteur.arreter("A"))  # après la dernière relecture de `_juger`
        return lire(texte)

    monkeypatch.setattr(module, "lire_verdict", lire_puis_arreter)
    moteur.executer()
    assert controles.reponses == [True] and controles.enregistrees == []
    assert moteur.chantier.tache("A").historique[-1]["issue"] == "arretee"
    assert controles.annulees == ["A"]
    verifier_retour_a_la_personne(moteur)


def test_un_arret_pendant_l_enregistrement_est_trop_tard_et_le_dit():
    controles = ControlesEspions("enregistrement")
    moteur = moteur_de([tache("A")], controles=controles)
    controles.moteur = moteur
    moteur.executer()
    assert controles.reponses == [False]  # acceptée : l'arrêt ne fait rien
    assert moteur.chantier.tache("A").etat == "verifie"
    assert moteur.enregistree("A") and moteur.arreter("A") is False
    assert moteur._arretees == set() and moteur._enregistrement == set()
    assert not moteur.enregistree("Z")


def test_la_route_d_arret_passe_par_le_drapeau_du_moteur_quand_aucun_agent_ne_tourne(
    tableau, tmp_path
):
    controles = ControlesEspions("mecaniques")
    atelier = atelier_simule(tmp_path, [tache("A")], controles=controles)
    serveur = tableau(atelier)
    controles.action = lambda t: serveur.appeler("/api/arreter", {"tache": t.id})[1]["arret"]
    atelier.lancer()
    assert attendre(lambda: controles.reponses and not atelier.en_marche())
    assert controles.reponses == [{"fait": True, "phrase": "Arrêt demandé pour la tâche A."}]
    assert [a["role"] for a in atelier.moteur.agent.appels] == ["ouvrier"]
    verifier_retour_a_la_personne(atelier.moteur)


def test_la_route_d_arret_dit_qu_il_est_trop_tard_pendant_l_enregistrement(tableau, tmp_path):
    controles = ControlesEspions("enregistrement")
    atelier = atelier_simule(tmp_path, [tache("A")], controles=controles)
    serveur = tableau(atelier)
    controles.action = lambda t: serveur.appeler("/api/arreter", {"tache": t.id})[1]["arret"]
    atelier.lancer()
    assert attendre(lambda: controles.reponses and not atelier.en_marche())
    assert controles.reponses == [
        {
            "fait": False,
            "phrase": "La tâche A est déjà vérifiée : elle est enregistrée, "
            "trop tard pour l'arrêter.",
        }
    ]
    assert atelier.moteur.chantier.tache("A").etat == "verifie"
    _, apres = serveur.appeler("/api/arreter", {"tache": "A"})
    assert apres["arret"]["fait"] is False and "déjà vérifiée" in apres["arret"]["phrase"]


@pytest.mark.parametrize("role", ["ouvrier", "verificateur"])
def test_l_arret_se_lit_dans_le_resultat_meme_sans_drapeau(role):
    agent = AgentArrete(role)
    moteur = moteur_de([tache("A")], agent=agent)
    moteur.executer()
    verifier_retour_a_la_personne(moteur)
    # Le coût du tour arrêté est compté (celui d'un ouvrier simulé sonnet : 0,09).
    attendu = {"ouvrier": 0.5, "verificateur": 0.59}[role]
    assert moteur.chantier.tache("A").cout_usd == pytest.approx(attendu)
    assert moteur.chantier.tache("A").tentatives == 1


def test_une_panne_ordinaire_garde_sa_seconde_chance():
    moteur = moteur_de([tache("A")], agent=AgentSimule({"A": ["erreur", "ok"]}))
    moteur.executer()
    texte = " ".join(notes(moteur))
    assert "Seconde chance au même niveau" in texte
    assert moteur.chantier.tache("A").etat == "verifie"
    assert moteur.chantier.tache("A").historique[0]["issue"] == "ne_sait_pas"


# --- l'arrêt de la réponse de l'orchestrateur --------------------------------------------


def test_arreter_sans_tache_arrete_la_reponse_et_la_conversation_continue(tableau, tmp_path):
    agent = AgentSimule(plan=PLAN, delai_s=25)
    atelier = atelier_simule(tmp_path, agent=agent, valide=False)
    serveur = tableau(atelier)
    serveur.appeler("/api/message", {"texte": "Construis."})
    assert attendre(lambda: any(a["lignes"] for a in serveur.etat()["agents"]))
    (ecrit,) = serveur.etat()["agents"]
    assert ecrit["nom"] == "orchestrateur" and ecrit["role"] == "orchestrateur"
    assert ecrit["tache"] == ""

    code, reponse = serveur.appeler("/api/arreter", {})
    assert code == 200
    assert reponse["arret"] == {
        "fait": True,
        "phrase": "Arrêt demandé : la réponse en cours s'arrête.",
    }
    assert attendre(lambda: not serveur.etat()["occupe"])
    fil = atelier.moteur.chantier.evenements
    assert [e["auteur"] for e in fil] == ["orchestrateur", "toi", "orchestrateur", "orchestrateur"]
    assert fil[2]["texte"].startswith("J'ai")  # ce qui était déjà écrit n'est pas perdu
    assert fil[3]["texte"] == "(Réponse arrêtée par toi. Tu peux écrire la suite.)"
    assert not any("Je n'ai pas pu joindre" in e["texte"] for e in fil)
    assert not any("atelier-plan" in e["texte"] for e in fil)
    assert atelier.moteur.chantier.taches == [] and serveur.etat()["agents"] == []
    assert atelier.moteur.chantier.session

    agent.delai_s = 0
    serveur.appeler("/api/message", {"texte": "Merci."})
    assert attendre(lambda: not serveur.etat()["occupe"])
    appels = [a for a in agent.appels if a["role"] == "conversation"]
    assert [a["reprise"] for a in appels] == [False, True]
    assert appels[0]["session"] == appels[1]["session"]
    assert [t.id for t in atelier.moteur.chantier.taches] == ["A"]
    assert atelier.moteur.chantier.cout_usd == pytest.approx(1.6)
    assert atelier.moteur.chantier.tokens == 12000


def test_arreter_sans_rien_en_marche_ne_fait_rien(tableau, tmp_path):
    serveur = tableau(atelier_simule(tmp_path, [tache("A")]))
    _, reponse = serveur.appeler("/api/arreter", {})
    assert reponse["arret"] == {
        "fait": False,
        "phrase": "L'orchestrateur ne répond à rien en ce moment : rien à arrêter.",
    }
    _, reponse = serveur.appeler("/api/arreter", {"tache": "A"})
    assert reponse["arret"] == {
        "fait": False,
        "phrase": "La tâche A n'est ni en cours ni en vérification : rien à arrêter.",
    }
    _, reponse = serveur.appeler("/api/arreter", {"tache": 3})
    assert reponse["arret"]["fait"] is False
    assert serveur.etat()["taches"][0]["etat"] == "a_lancer"


# --- les instantanés ----------------------------------------------------------------------


def test_les_instantanes_se_terminent_vite_et_montrent_la_demande_ouverte(tmp_path, monkeypatch):
    # Un guichet à délai court : si rien ne répond à la demande, elle se ferme et rien ne reste.
    monkeypatch.setattr("atelier.__main__.Guichet", lambda: Guichet(delai_s=1))
    reglees, autoriser = [], Atelier.autoriser
    monkeypatch.setattr(
        Atelier,
        "autoriser",
        lambda self, *arguments: (reglees.append(autoriser(self, *arguments))) or reglees[-1],
    )
    sortie = tmp_path / "instantanes.html"
    fil = threading.Thread(
        target=commande_instantanes, args=(Namespace(sortie=str(sortie)),), daemon=True
    )
    fil.start()
    fil.join(30)
    assert not fil.is_alive()
    page = sortie.read_text("utf-8")
    debut = page.index("const INSTANTANES = ") + len("const INSTANTANES = ")
    vues, _ = json.JSONDecoder().raw_decode(page[debut:])
    ouvertes = [v for v in vues if v["autorisations"]]
    assert ouvertes and ouvertes[0]["autorisations"][0]["regle"] == REGLE_SIMULEE
    assert reglees == [{"reglee": True, "phrase": "Autorisé cette fois."}]  # réglée, pas expirée
    assert any(a["lignes"] for v in ouvertes for a in v["agents"])
    assert vues[-1]["autorisations"] == [] and vues[-1]["termine"] is True


# --- le fil, les verrous, la mémoire ------------------------------------------------------


def test_chaque_toujours_laisse_une_trace_au_fil_avec_la_regle_exacte(tableau, tmp_path):
    atelier = atelier_simule(tmp_path, guichet=Guichet())
    serveur = tableau(atelier)
    for choix in ("une_fois", "toujours"):
        demander_en_fil(atelier.guichet)
        (demande,) = atelier.guichet.ouvertes()
        serveur.appeler("/api/autorisation", {"id": demande["id"], "choix": choix})
        assert attendre(lambda: not atelier.guichet.ouvertes())
    textes = [e["texte"] for e in atelier.moteur.chantier.evenements]
    trace = "Autorisation retenue pour ce projet : Bash(npm install:*)."
    assert textes.count(trace) == 1
    etat = json.loads((tmp_path / ".atelier" / "etat.json").read_text("utf-8"))
    assert trace in [e["texte"] for e in etat["evenements"]]  # la trace est aussi enregistrée


def test_un_profil_qui_n_est_pas_un_objet_n_est_pas_ecrase(tableau, tmp_path):
    chemin = tmp_path / "chantier" / "profil.json"
    chemin.parent.mkdir(parents=True)
    chemin.write_text("[1, 2]", "utf-8")
    atelier = atelier_simule(tmp_path, guichet=Guichet())
    serveur = tableau(atelier)
    demander_en_fil(atelier.guichet)
    (demande,) = atelier.guichet.ouvertes()
    _, reponse = serveur.appeler("/api/autorisation", {"id": demande["id"], "choix": "toujours"})
    assert "n'est pas lisible" in reponse["autorisation"]["phrase"]
    assert chemin.read_text("utf-8") == "[1, 2]"
    assert not any("Autorisation retenue" in e["texte"] for e in reponse["evenements"])


def ecrire_pendant_que_le_verrou_est_tenu(atelier, ecriture, chemin):
    """Tient le verrou du profil, lance l'écriture dans un fil : rien ne doit être écrit."""
    with atelier._verrou_profil:
        fil = threading.Thread(target=ecriture, daemon=True)
        fil.start()
        fil.join(0.2)
        attendue = fil.is_alive() and not chemin.exists()
    fil.join(5)
    return attendue and not fil.is_alive() and chemin.exists()


def test_les_deux_ecritures_du_profil_passent_par_le_meme_verrou(tmp_path):
    atelier = atelier_simule(tmp_path / "a")
    chemin = atelier.depot / "chantier" / "profil.json"
    assert ecrire_pendant_que_le_verrou_est_tenu(
        atelier, lambda: atelier._inscrire_regle(REGLE_SIMULEE), chemin
    )

    atelier = atelier_simule(tmp_path / "b")
    chemin = atelier.depot / "chantier" / "profil.json"
    atelier._proposer_outils({"commandes_permises": ["make"]})
    demande = atelier.moteur.chantier.demandes[0]
    assert ecrire_pendant_que_le_verrou_est_tenu(
        atelier, lambda: atelier.decider(demande["id"], ACCEPTER_OUTILS), chemin
    )
    assert json.loads(chemin.read_text("utf-8"))["commandes_permises"] == ["make"]


class ControlesQuiNotent(ControlesSimules):
    """Des contrôles simulés qui retiennent chaque réglage d'outils reçu."""

    def __init__(self):
        super().__init__()
        self.reglages = []

    def regler_outils(self, profil: dict) -> None:
        self.reglages.append(profil)


ILLISIBLE = "le profil du projet (chantier/profil.json) n'est pas lisible, corrige-le."
NON_ECRIT = "le profil du projet (chantier/profil.json) n'a pas pu être écrit."


@pytest.mark.parametrize(
    ("contenu", "ecriture_refusee", "raison"),
    [
        ("[1, 2]", False, ILLISIBLE),
        ("pas du json", False, ILLISIBLE),
        ('{"commandes_permises": ["ls"]}', True, NON_ECRIT),
    ],
)
def test_un_reglage_d_outils_sur_un_profil_inutilisable_n_applique_rien_et_le_dit(
    tmp_path, monkeypatch, contenu, ecriture_refusee, raison
):
    chemin = tmp_path / "chantier" / "profil.json"
    chemin.parent.mkdir(parents=True)
    chemin.write_text(contenu, "utf-8")
    controles = ControlesQuiNotent()
    profil = {"commandes_permises": ["ls"]}
    atelier = atelier_simule(tmp_path, profil=profil, controles=controles)
    atelier._proposer_outils({"commandes_permises": ["make"], "commandes": ["make test"]})
    demande = atelier.moteur.chantier.demandes[0]
    if ecriture_refusee:
        remplacer = modele_module.os.replace

        def refuser_le_profil(source, cible):
            if pathlib.Path(cible) == chemin:
                raise PermissionError("écriture refusée")
            return remplacer(source, cible)

        monkeypatch.setattr(modele_module.os, "replace", refuser_le_profil)

    atelier.decider(demande["id"], ACCEPTER_OUTILS)

    assert chemin.read_text("utf-8") == contenu
    assert atelier.moteur.profil == {"commandes_permises": ["ls"]}
    assert controles.reglages == []
    textes = [e["texte"] for e in atelier.moteur.chantier.evenements]
    assert f"Réglage des outils non appliqué : {raison}" in textes
    assert not any(t.startswith("Outils réglés.") for t in textes)


def test_le_verrou_de_l_activite_protege_les_lectures_pendant_les_ecritures():
    ancien = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    activite, arret, erreurs = Activite(), threading.Event(), []
    for rang in range(30):
        activite.ajouter(evenement(f"T{rang}-ouvrier-1", "texte", "début"))

    def ecrire():
        rang = 30
        while not arret.is_set():
            activite.ajouter(evenement(f"T{rang}-ouvrier-1", "texte", "ligne\nsuite"))
            activite.ajouter(evenement(f"T{rang - 30}-ouvrier-1", "fin", ""))
            rang += 1

    def lire():
        try:
            for _ in range(2000):
                activite.agents()
        except Exception as erreur:  # noqa: BLE001 - le test doit voir toute erreur
            erreurs.append(erreur)

    try:
        fils = [threading.Thread(target=ecrire, daemon=True) for _ in range(2)]
        lecteurs = [threading.Thread(target=lire, daemon=True) for _ in range(2)]
        for fil in fils + lecteurs:
            fil.start()
        for fil in lecteurs:
            fil.join(30)
        arret.set()
        for fil in fils:
            fil.join(5)
    finally:
        sys.setswitchinterval(ancien)
    assert erreurs == []


def test_le_rappel_d_evenements_ne_fait_que_ranger(tmp_path):
    atelier = atelier_simule(tmp_path, [tache("A")])
    vues = []
    atelier.sur_vue = vues.append
    etat = tmp_path / ".atelier" / "etat.json"
    avant = etat.read_bytes()

    def interdit(*arguments, **options):
        raise AssertionError("le rappel d'événements ne doit ni afficher ni sauver")

    atelier.vue, atelier._sauver = interdit, interdit
    rappel = atelier.moteur.agent.sur_evenement
    tenu, libre = threading.Event(), threading.Event()

    def tenir_le_verrou():
        with atelier.moteur.verrou:
            tenu.set()
            libre.wait(5)

    threading.Thread(target=tenir_le_verrou, daemon=True).start()
    assert tenu.wait(5)

    def emettre():
        for genre in ("outil", "attente", "texte", "texte", "fin"):
            rappel(evenement("A-ouvrier-1", genre, "x\n"))
        rappel(evenement("A-ouvrier-2", "outil", "Lit a.py"))

    fil = threading.Thread(target=emettre, daemon=True)
    fil.start()
    fil.join(2)  # un rappel qui attendrait le verrou du moteur ne rendrait pas la main
    libre.set()
    assert not fil.is_alive()
    assert vues == [] and etat.read_bytes() == avant
    assert [a["nom"] for a in atelier.activite.agents()] == ["A-ouvrier-2"]


def test_un_morceau_demesure_est_coupe_avant_d_etre_traite(monkeypatch):
    activite, tailles = Activite(), []
    ranger = activite._ranger
    monkeypatch.setattr(
        activite, "_ranger", lambda nom, texte: (tailles.append(len(texte)), ranger(nom, texte))
    )
    activite.ajouter(evenement("B-ouvrier-1", "texte", "x" * 2_000_000 + "\nfin"))
    assert max(tailles) <= 30 * 300
    assert lignes_de(activite, "B-ouvrier-1")[-1] == "fin"
    activite.ajouter(evenement("C-ouvrier-1", "outil", "y" * 2_000_000))
    assert max(tailles) <= 30 * 300


def test_le_nombre_d_agents_gardes_est_borne_sans_evenement_fin():
    activite = Activite()
    for rang in range(100):
        activite.ajouter(evenement(f"T{rang}-ouvrier-1", "texte", "reste"))
    noms = [a["nom"] for a in activite.agents()]
    assert noms == [f"T{rang}-ouvrier-1" for rang in range(60, 100)]
    assert len(activite._reste) == 40 and len(activite._lignes) == 40


# --- le mode des ouvriers -------------------------------------------------------------

CHOIX_ATTENDUS = [
    ("default", "Me demander"),
    ("acceptEdits", "Accepter les modifications"),
    ("plan", "Répétition"),
    ("dontAsk", "Refuser sans demander"),
    ("auto", "Laisser un arbitre décider"),
]
REFUS_LIGNE = "Refusé par l'arbitre : Lance curl https://example.com (règle Data Exfiltration)."
RETOMBEE = (
    "A-ouvrier-1 devait travailler en mode « Laisser un arbitre décider », mais c'est le mode "
    "« Me demander » qui est appliqué."
)


def textes_du_fil(atelier):
    return [e["texte"] for e in atelier.moteur.chantier.evenements]


def lignes_de_la_vue(serveur, nom):
    return next((a["lignes"] for a in serveur.etat()["agents"] if a["nom"] == nom), [])


def test_la_vue_porte_le_mode_des_ouvriers_et_ses_cinq_choix(tableau, tmp_path):
    serveur = tableau(atelier_simule(tmp_path))
    mode = serveur.etat()["mode_ouvriers"]
    assert (mode["choisi"], mode["libelle"], mode["appliques"]) == (
        "acceptEdits",
        "Accepter les modifications",
        [],
    )
    assert [(c["mode"], c["libelle"]) for c in mode["choix"]] == CHOIX_ATTENDUS
    assert all(set(c) == {"mode", "libelle", "explication"} for c in mode["choix"])
    explications = {c["mode"]: c["explication"] for c in mode["choix"]}
    assert explications["plan"] == (
        "L'ouvrier prépare son plan et chaque modification de fichier te demande une carte, "
        "mais les commandes permises d'avance par le projet (comme python3 ou npm) tournent "
        "sans carte et peuvent écrire ; une dernière carte te demande s'il peut passer à "
        "l'exécution."
    )
    assert "refusé sans carte" in explications["dontAsk"]
    assert explications["auto"] == (
        "Un modèle approuve ou refuse à ta place ce qui t'aurait demandé une carte, ainsi que "
        "les commandes qui exécutent du code même permises d'avance (le reste passe sans lui) ; "
        "ses refus s'affichent dans l'activité de l'agent, et après trop de refus les demandes "
        "te reviennent en cartes."
    )
    assert all(e.endswith(".") and e.count(". ") == 0 for e in explications.values())
    assert "bypassPermissions" not in json.dumps(mode)


def test_la_route_du_mode_l_enregistre_au_profil_sans_toucher_au_reste(tableau, tmp_path):
    chemin = tmp_path / "chantier" / "profil.json"
    chemin.parent.mkdir(parents=True)
    chemin.write_text(json.dumps({"nom": "X", "autorisations": ["Read"]}), "utf-8")
    profil = {"nom": "X"}
    agent = AgentSimule()
    agent.profil = profil
    atelier = atelier_simule(tmp_path, agent=agent, profil=profil)
    serveur = tableau(atelier)
    code, reponse = serveur.appeler("/api/mode", {"mode": "auto"})
    phrase = (
        "Mode des ouvriers : « Laisser un arbitre décider ». "
        "Il vaudra pour les prochains ouvriers lancés."
    )
    assert code == 200 and reponse["changement_mode"] == {"fait": True, "phrase": phrase}
    assert reponse["mode"] == "réel"  # la vue garde sa clé « mode »
    assert reponse["mode_ouvriers"]["choisi"] == "auto"
    assert reponse["mode_ouvriers"]["libelle"] == "Laisser un arbitre décider"
    texte = chemin.read_text("utf-8")
    assert texte.endswith("\n")
    assert json.loads(texte) == {"nom": "X", "autorisations": ["Read"], "mode_ouvriers": "auto"}
    assert agent.mode_ouvriers == "auto"
    assert profil["mode_ouvriers"] == "auto" and atelier.moteur.profil["mode_ouvriers"] == "auto"
    assert textes_du_fil(atelier).count(phrase) == 1


@pytest.mark.parametrize(
    "mode, phrase",
    [
        (
            "bypassPermissions",
            "Le mode bypassPermissions, qui laisserait les agents tout faire "
            "sans rien demander, n'est pas proposé par l'Atelier : rien n'a changé.",
        ),
        (
            "AUTO",
            "Ce mode n'existe pas : choisis parmi « Me demander », « Accepter les "
            "modifications », « Répétition », « Refuser sans demander », « Laisser un arbitre "
            "décider ». Rien n'a changé.",
        ),
        (None, None),
        (42, None),
        (["auto"], None),
        ("", None),
    ],
)
def test_la_route_refuse_bypass_et_tout_mode_inconnu_sans_rien_ecrire(
    tableau, tmp_path, mode, phrase
):
    atelier = atelier_simule(tmp_path)
    serveur = tableau(atelier)
    avant = textes_du_fil(atelier)
    code, reponse = serveur.appeler("/api/mode", {"mode": mode})
    assert code == 200 and reponse["changement_mode"]["fait"] is False
    if phrase:
        assert reponse["changement_mode"]["phrase"] == phrase
    assert not (tmp_path / "chantier" / "profil.json").exists()
    assert atelier.moteur.agent.mode_ouvriers == "acceptEdits"
    assert reponse["mode_ouvriers"]["choisi"] == "acceptEdits"
    assert textes_du_fil(atelier) == avant


def test_la_route_du_mode_sans_cle_rend_400(tableau, tmp_path):
    serveur = tableau(atelier_simule(tmp_path))
    erreur = {"erreur": "Demande introuvable ou incomplète."}
    assert serveur.appeler("/api/mode", {}) == (400, erreur)


@pytest.mark.parametrize("contenu", ["pas du json", "[1, 2]"])
def test_un_profil_illisible_n_empeche_pas_le_choix_et_le_dit(tableau, tmp_path, contenu):
    chemin = tmp_path / "chantier" / "profil.json"
    chemin.parent.mkdir(parents=True)
    chemin.write_text(contenu, "utf-8")
    atelier = atelier_simule(tmp_path)
    serveur = tableau(atelier)
    _, reponse = serveur.appeler("/api/mode", {"mode": "plan"})
    assert reponse["changement_mode"] == {
        "fait": True,
        "phrase": "Mode des ouvriers : « Répétition ». Il vaudra pour les prochains ouvriers "
        "lancés. Il n'a pas pu être enregistré et sera oublié au redémarrage : le profil du "
        "projet (chantier/profil.json) n'est pas lisible, corrige-le.",
    }
    assert chemin.read_text("utf-8") == contenu
    assert atelier.moteur.agent.mode_ouvriers == "plan"


def test_l_ecriture_du_mode_passe_par_le_verrou_du_profil(tmp_path):
    atelier = atelier_simule(tmp_path)
    chemin = atelier.depot / "chantier" / "profil.json"
    assert ecrire_pendant_que_le_verrou_est_tenu(
        atelier, lambda: atelier.changer_mode("auto"), chemin
    )
    assert json.loads(chemin.read_text("utf-8")) == {"mode_ouvriers": "auto"}


def test_le_mode_du_profil_vaut_a_l_ouverture(tmp_path):
    atelier = atelier_simule(tmp_path, profil={"mode_ouvriers": "dontAsk"})
    assert atelier.moteur.agent.mode_ouvriers == "dontAsk"
    assert atelier.vue()["mode_ouvriers"]["choisi"] == "dontAsk"
    assert not any("mode" in t for t in textes_du_fil(atelier))


@pytest.mark.parametrize(
    "valeur, montre",
    [
        ("bypassPermissions", "« bypassPermissions »"),
        ("Auto", "« Auto »"),
        (42, "illisible"),
        (None, "illisible"),
    ],
)
def test_un_mode_refuse_dans_le_profil_vaut_accept_edits_et_le_fil_le_dit_une_fois(
    tmp_path, valeur, montre
):
    c = chantier([])
    profil = {"mode_ouvriers": valeur}
    atelier = Atelier(tmp_path, c, AgentSimule(), ControlesSimules(), profil)
    phrase = (
        "Le profil du projet (chantier/profil.json) demande pour les ouvriers un mode que "
        f"l'Atelier ne connaît pas ou refuse ({montre}) : ils travaillent en mode "
        "« Accepter les modifications »."
    )
    assert textes_du_fil(atelier).count(phrase) == 1
    assert atelier.moteur.agent.mode_ouvriers == "acceptEdits"
    assert atelier.vue()["mode_ouvriers"]["choisi"] == "acceptEdits"
    Atelier(tmp_path, c, AgentSimule(), ControlesSimules(), profil)  # rouvert tel quel
    assert textes_du_fil(atelier).count(phrase) == 1


def test_le_mode_change_a_chaud_pendant_qu_un_ouvrier_simule_tourne(tableau, tmp_path):
    """Le mode passe en auto pendant que l'ouvrier travaille : il joue un refus de l'arbitre,
    puis retombe en « default » ; la conversation, en marche au même instant, n'est pas touchée."""
    atelier = atelier_simule(tmp_path, [tache("A")], delai_s=30, retombee=True)
    serveur = tableau(atelier)
    atelier.lancer()
    assert attendre(lambda: lignes_de_la_vue(serveur, "A-ouvrier-1") == ["Lit la consigne"])
    atelier.moteur.agent.plan = None
    serveur.appeler("/api/message", {"texte": "Où en est-on ?"})
    assert attendre(lambda: lignes_de_la_vue(serveur, "orchestrateur"))
    code, reponse = serveur.appeler("/api/mode", {"mode": "auto"})
    assert code == 200 and reponse["changement_mode"] == {
        "fait": True,
        "phrase": "Mode des ouvriers : « Laisser un arbitre décider ». "
        "Il vaut aussi, dès maintenant, pour l'ouvrier en marche.",
    }
    assert attendre(lambda: len(lignes_de_la_vue(serveur, "A-ouvrier-1")) == 3)
    assert lignes_de_la_vue(serveur, "A-ouvrier-1") == [
        "Lit la consigne",
        REFUS_LIGNE,
        "Mode réellement appliqué : Me demander.",
    ]
    assert attendre(lambda: RETOMBEE in textes_du_fil(atelier))
    etat = serveur.etat()
    assert etat["mode_ouvriers"]["choisi"] == "auto"
    assert etat["mode_ouvriers"]["appliques"] == [
        {"agent": "A-ouvrier-1", "mode": "default", "libelle": "Me demander"}
    ]
    assert not any("orchestrateur" in t and "mode" in t for t in textes_du_fil(atelier))

    # Revenir au mode « default » : l'ouvrier est déjà dans ce mode, rien de plus n'est dit.
    _, reponse = serveur.appeler("/api/mode", {"mode": "default"})
    assert reponse["mode_ouvriers"]["appliques"] == []
    assert attendre(lambda: atelier.moteur.agent.modes_appliques() == {"A-ouvrier-1": "default"})
    assert textes_du_fil(atelier).count(RETOMBEE) == 1
    code, reponse = serveur.appeler("/api/arreter", {"tache": "A"})
    assert reponse["arret"]["fait"] is True


def test_une_seule_phrase_par_agent_et_par_changement_de_mode_reel(tmp_path):
    atelier = atelier_simule(tmp_path)
    rappel = atelier.moteur.agent.sur_evenement
    mode = {
        "agent": "B-ouvrier-1",
        "type": "mode",
        "contenu": "default",
        "demande": "auto",
        "raison": "le mode auto n'est pas disponible pour son modèle",
    }
    for _ in range(3):
        rappel(mode)
    rappel({**mode, "contenu": "auto", "raison": ""})
    rappel(mode)
    rappel(evenement("B-ouvrier-1", "fin", "L'agent a terminé."))
    rappel(mode)  # une nouvelle session du même nom : elle a droit à sa phrase
    phrase = (
        "B-ouvrier-1 devait travailler en mode « Laisser un arbitre décider », mais c'est le mode "
        "« Me demander » qui est appliqué : le mode auto n'est pas disponible pour son modèle."
    )
    fil = textes_du_fil(atelier)
    assert fil.count(phrase) == 3
    assert (
        fil.count(
            "B-ouvrier-1 travaille de nouveau dans le mode demandé, « Laisser un arbitre décider »."
        )
        == 1
    )
    etat = json.loads((tmp_path / ".atelier" / "etat.json").read_text("utf-8"))
    assert phrase in [e["texte"] for e in etat["evenements"]]  # la phrase est enregistrée


def test_un_vrai_agent_dit_au_fil_que_le_mode_auto_est_indisponible(tmp_path):
    """Le vrai `AgentClaude`, sur un faux client du SDK qui démarre en « default »."""
    from tests.test_sdk import Fabrique, fin, init

    fabrique = Fabrique([init(mode="default"), fin()])
    agent = AgentClaude({"mode_ouvriers": "auto"}, delai_max_s=5, fabrique_client=fabrique)
    atelier = atelier_simule(tmp_path, agent=agent, profil={"mode_ouvriers": "auto"})
    atelier.annoncer_connexion({})
    contexte = {"role": "ouvrier", "tache": "A", "tentative": 1}
    assert agent.executer("Va.", "opus", "high", None, False, contexte).ok
    assert agent.executer(
        "Vérifie.", "opus", "high", None, True, {**contexte, "role": "verificateur"}
    ).ok
    phrase = (
        "A-ouvrier-1 devait travailler en mode « Laisser un arbitre décider », mais c'est le mode "
        "« Me demander » qui est appliqué : le mode auto n'est pas disponible pour son modèle."
    )
    assert textes_du_fil(atelier).count(phrase) == 1
    assert not any("verificateur" in t for t in textes_du_fil(atelier))
    assert [c.options.permission_mode for c in fabrique.clients] == ["auto", "default"]


def test_en_mode_auto_la_pause_de_l_arbitre_ramene_les_cartes(tableau, tmp_path):
    atelier = atelier_simule(tmp_path, [tache("A")], guichet=Guichet(), pause_arbitre=True)
    serveur = tableau(atelier)
    serveur.appeler("/api/mode", {"mode": "auto"})
    vus = []
    suite = atelier.moteur.agent.sur_evenement
    atelier.moteur.agent.sur_evenement = lambda e: (vus.append(e), suite(e))
    atelier.lancer()
    assert attendre(lambda: serveur.etat()["autorisations"])
    (demande,) = serveur.etat()["autorisations"]
    assert demande["detail"] == "curl https://example.com"
    assert demande["phrase"] == (
        "A-ouvrier-1 veut lancer la commande « curl https://example.com ». "
        "Cette commande peut être autorisée pour ce chantier, pas pour de bon."
    )
    lignes = lignes_de_la_vue(serveur, "A-ouvrier-1")
    assert lignes.count(REFUS_LIGNE) == 3
    _, reponse = serveur.appeler("/api/autorisation", {"id": demande["id"], "choix": "une_fois"})
    assert reponse["autorisation"]["reglee"] is True
    assert attendre(lambda: serveur.etat()["autorisations"])  # puis la demande d'exemple
    (suivante,) = serveur.etat()["autorisations"]
    serveur.appeler("/api/autorisation", {"id": suivante["id"], "choix": "non"})
    assert attendre(lambda: not atelier.en_marche())
    textes = [e["contenu"] for e in vus if e["type"] == "texte"]
    assert textes[0] == "Réponse de la personne responsable : autorisé une fois."


def test_les_lignes_de_refus_et_de_mode_sont_lisibles():
    activite, dits = Activite(), []
    activite.sur_mode = dits.append
    activite.ajouter(evenement("B-ouvrier-1", "texte", "Je cherche"))
    activite.ajouter(evenement("B-ouvrier-1", "refus", "Lance curl https://x.y (règle Z)"))
    mode = {**evenement("B-ouvrier-1", "mode", "default"), "demande": "auto"}
    activite.ajouter(mode)
    activite.ajouter(mode)
    activite.ajouter(evenement("B-ouvrier-1", "mode", "plan"))  # sans mode demandé
    assert lignes_de(activite, "B-ouvrier-1") == [
        "Je cherche",
        "Refusé par l'arbitre : Lance curl https://x.y (règle Z).",
        "Mode réellement appliqué : Me demander.",
        "Mode réellement appliqué : Me demander.",
        "Mode réellement appliqué : Répétition.",
    ]
    assert [e["contenu"] for e in dits] == ["default", "plan"]
    activite.ajouter(evenement("B-ouvrier-1", "mode", "bizarre"))
    assert lignes_de(activite, "B-ouvrier-1")[-1] == "Mode réellement appliqué : bizarre."
    assert activite._modes and activite.ajouter(evenement("B-ouvrier-1", "fin", "")) is None
    assert activite._modes == {}


def test_le_rappel_de_mode_qui_leve_ne_casse_pas_l_activite():
    activite = Activite()

    def casse(_evenement):
        raise RuntimeError("le fil est tombé")

    activite.sur_mode = casse
    activite.ajouter(evenement("B-ouvrier-1", "mode", "default"))
    assert lignes_de(activite, "B-ouvrier-1") == ["Mode réellement appliqué : Me demander."]


def test_les_phrases_du_mode_des_ouvriers():
    from atelier.serveur import libelle_mode, phrase_mode_change, phrase_mode_reel

    assert phrase_mode_change("plan", 3) == (
        "Mode des ouvriers : « Répétition ». Il vaut aussi, dès maintenant, pour les 3 ouvriers "
        "en marche."
    )
    assert phrase_mode_reel("B-ouvrier-1", "", "dontAsk") == (
        "Mode réellement appliqué à B-ouvrier-1 : « Refuser sans demander »."
    )
    assert phrase_mode_reel("B-ouvrier-1", "plan", "default", "il a fini sa répétition") == (
        "B-ouvrier-1 devait travailler en mode « Répétition », mais c'est le mode « Me demander » "
        "qui est appliqué : il a fini sa répétition."
    )
    assert libelle_mode("acceptEdits") == "Accepter les modifications"
    assert libelle_mode("x" * 100) == "x" * 40 and libelle_mode(["auto"]) == "['auto']"


def ouvrier_claude_en_marche(tmp_path, fabrique, profil):
    """Un vrai `AgentClaude` sur un faux client, et son ouvrier B lancé dans un fil."""
    agent = AgentClaude(dict(profil), delai_max_s=10, fabrique_client=fabrique)
    atelier = atelier_simule(tmp_path, agent=agent, profil=dict(profil))
    atelier.annoncer_connexion({})
    contexte = {"role": "ouvrier", "tache": "B", "tentative": 1}
    fil = threading.Thread(
        target=lambda: agent.executer("Va.", "opus", "high", None, False, contexte), daemon=True
    )
    fil.start()
    return atelier, agent, fil


def test_le_meme_ecart_de_mode_est_redit_apres_chaque_changement_demande(tmp_path):
    """Auto refusé, puis acceptEdits, puis auto refusé de nouveau : le fil le redit."""
    from tests.test_sdk import BLOQUE, Fabrique, init

    fabrique = Fabrique([init(mode="acceptEdits"), BLOQUE], sans_auto=True)
    atelier, agent, fil = ouvrier_claude_en_marche(tmp_path, fabrique, {})
    ecart = (
        "B-ouvrier-1 devait travailler en mode « Laisser un arbitre décider », mais c'est le mode "
        "« Accepter les modifications » qui est appliqué : le mode auto n'est pas disponible pour "
        "son modèle."
    )
    try:
        assert attendre(lambda: agent.modes_appliques() == {"B-ouvrier-1": "acceptEdits"})
        atelier.changer_mode("auto")
        assert attendre(lambda: textes_du_fil(atelier).count(ecart) == 1)
        atelier.changer_mode("acceptEdits")
        atelier.changer_mode("auto")
        assert attendre(lambda: textes_du_fil(atelier).count(ecart) == 2)
        assert textes_du_fil(atelier)[-1] == ecart
        assert fabrique.clients[0].modes_demandes == ["auto", "auto"]
    finally:
        agent.arreter("B")
        fil.join(5)


def test_une_retombee_qui_revient_apres_un_nouveau_choix_est_redite(tmp_path):
    """Retombée, retour, retombée, puis la personne choisit de nouveau auto et l'ouvrier
    retombe encore : chaque retombée est dite."""
    from tests.test_sdk import Fabrique, fin, init, jusqu_a, statut

    pas = {"n": 0}

    def etape(n):
        return jusqu_a(lambda _client: pas["n"] >= n)

    fabrique = Fabrique(
        [
            init(mode="auto"),
            etape(1),
            statut("default"),
            etape(2),
            statut("auto"),
            etape(3),
            statut("default"),
            etape(4),
            statut("default"),
            etape(5),
            fin(),
        ]
    )
    atelier, agent, fil = ouvrier_claude_en_marche(tmp_path, fabrique, {"mode_ouvriers": "auto"})
    retombee = (
        "B-ouvrier-1 devait travailler en mode « Laisser un arbitre décider », mais c'est le mode "
        "« Me demander » qui est appliqué."
    )
    try:
        assert attendre(lambda: agent.modes_appliques() == {"B-ouvrier-1": "auto"})
        for n, attendu in ((1, 1), (2, 1), (3, 2)):
            pas["n"] = n
            assert attendre(lambda a=attendu: textes_du_fil(atelier).count(retombee) == a)
        atelier.changer_mode("auto")  # l'ouvrier repasse en auto
        assert attendre(lambda: agent.modes_appliques() == {"B-ouvrier-1": "auto"})
        pas["n"] = 4
        assert attendre(lambda: textes_du_fil(atelier).count(retombee) == 3)
        assert textes_du_fil(atelier)[-1] == retombee
    finally:
        pas["n"] = 5
        fil.join(5)


# --- La mise à jour d'Atelier : aucun git, aucun réseau, aucun arrêt réel -----------------------

PHRASE_REDEMARRAGE = (
    "Atelier a été mis à jour. Il redémarre ; s'il ne revient pas dans quelques secondes, "
    "relance-le à la main."
)
PHRASE_DEJA_EN_COURS = "Une mise à jour est déjà en cours. Patiente un instant."
PHRASE_AGENT = "Mise à jour impossible : un agent travaille. Réessaie quand il aura fini."


class FausseMiseAJour:
    """Joue l'objet de mise à jour : note chaque appel, rend ce qu'on lui a préparé."""

    def __init__(self, disponible=True, resultat=None, bloquer=None):
        self.disponible = disponible
        self.resultat = resultat or ResultatMaj(True, "Atelier a été mis à jour. Il va redémarrer.")
        self.bloquer = bloquer  # un événement : mettre_a_jour attend qu'on le libère
        self.verifications = []  # le fil de chaque appel de verifier
        self.mises_a_jour = []  # l'argument « agent au travail » de chaque appel
        self.entree = threading.Event()

    def verifier(self):
        self.verifications.append(threading.current_thread())
        return Etat(self.disponible, "Une mise à jour d'Atelier est disponible.")

    def mettre_a_jour(self, agent_au_travail):
        self.mises_a_jour.append(agent_au_travail)
        self.entree.set()
        if self.bloquer:
            self.bloquer.wait(5)
        return self.resultat


@pytest.fixture(autouse=True)
def pas_de_vrai_git_pour_la_mise_a_jour(monkeypatch):
    """Garde-fou : aucun test de ce fichier ne peut lancer git dans le module de mise à jour."""

    def interdit(*arguments, **options):
        pytest.fail("un test a appelé git pour la mise à jour")

    monkeypatch.setattr(mise_a_jour_module, "_git", interdit)


class TableauMaj(Tableau):
    """Un serveur HTTP réel avec des projets (zéro, un ou plusieurs) et un suivi de mise à jour."""

    def __init__(self, ateliers, racine, suivi):
        self.atelier = ateliers[0] if ateliers else None
        projets = Projets(racine, lambda dossier, nom: None)
        for atelier in ateliers:
            projets.ajouter(atelier)
        self.serveur = creer_serveur(projets, 0, suivi)
        self.port = self.serveur.server_address[1]
        threading.Thread(target=self.serveur.serve_forever, args=(0.01,), daemon=True).start()

    def fermer(self):
        self.serveur.shutdown()
        self.serveur.server_close()


@pytest.fixture
def maj_servie(tmp_path):
    """Monte un serveur dont le suivi tient une fausse mise à jour ; nettoie à la fin."""
    ouverts = []

    def monter(faux=None, ateliers=None, arreter="espion", demarrer=True):
        faux = faux or FausseMiseAJour()
        arrets = []
        if arreter == "espion":
            arreter = lambda: arrets.append(1)  # noqa: E731
        suivi = SuiviMiseAJour(faux, arreter, pause_s=1000)
        if ateliers is None:
            ateliers = [atelier_simule(tmp_path / "un")]
        tableau = TableauMaj(ateliers, tmp_path, suivi)
        ouverts.append((tableau, suivi))
        if demarrer:
            suivi.demarrer()
            assert attendre(lambda: suivi.etat is not None)
        return tableau, suivi, faux, arrets

    yield monter
    for tableau, suivi in ouverts:
        suivi.finir()
        tableau.fermer()


def fil_de(atelier):
    return [e["texte"] for e in atelier.moteur.chantier.evenements]


def test_la_vue_porte_la_mise_a_jour_lue_dans_l_etat_garde(maj_servie):
    tableau, suivi, _, _ = maj_servie()
    assert tableau.etat()["mise_a_jour"] == {
        "disponible": True,
        "phrase": "Une mise à jour d'Atelier est disponible.",
    }
    suivi.etat = Etat(False, "Atelier est à jour.")
    assert tableau.etat()["mise_a_jour"] == {"disponible": False, "phrase": "Atelier est à jour."}


def test_avant_la_premiere_reponse_le_bouton_n_apparait_pas(maj_servie):
    tableau, _, faux, _ = maj_servie(demarrer=False)
    assert tableau.etat()["mise_a_jour"] == {"disponible": False, "phrase": ""}
    assert faux.verifications == []


def test_seul_le_fil_demon_appelle_verifier_jamais_la_vue(maj_servie):
    tableau, _, faux, _ = maj_servie()
    for _ in range(3):
        tableau.etat()
        tableau.appeler("/api/message", {"texte": ""})
    assert len(faux.verifications) == 1
    fil = faux.verifications[0]
    assert fil.daemon and fil is not threading.current_thread()


def test_la_mise_a_jour_est_dans_la_vue_meme_sans_projet(maj_servie):
    tableau, _, _, _ = maj_servie(ateliers=[])
    vue = tableau.etat()
    assert vue["aucun_projet"] is True
    assert vue["mise_a_jour"]["disponible"] is True


def test_un_serveur_sans_suivi_dit_pas_de_mise_a_jour_et_refuse_la_route(tableau, tmp_path):
    serveur = tableau(atelier_simule(tmp_path / "un"))
    assert serveur.etat()["mise_a_jour"] == {"disponible": False, "phrase": ""}
    code, reponse = serveur.appeler("/api/mise-a-jour")
    assert code == 400 and "erreur" in reponse


@pytest.mark.parametrize("cas", ["chantier", "orchestrateur"])
def test_un_agent_au_travail_empeche_la_mise_a_jour_et_le_fil_dit_pourquoi(
    maj_servie, cas, tmp_path
):
    atelier = atelier_simule(tmp_path / "un")
    liberer = threading.Event()
    if cas == "chantier":
        atelier.fil = threading.Thread(target=liberer.wait, args=(5,), daemon=True)
        atelier.fil.start()
    else:
        atelier.occupe = True
    faux = FausseMiseAJour(resultat=ResultatMaj(False, PHRASE_AGENT))
    tableau, _, faux, arrets = maj_servie(faux, [atelier])
    try:
        code, vue = tableau.appeler("/api/mise-a-jour")
    finally:
        liberer.set()
    assert code == 200
    assert faux.mises_a_jour == [True]
    assert vue["mise_a_jour_faite"] == {"fait": False, "phrase": PHRASE_AGENT}
    assert fil_de(atelier)[-1] == PHRASE_AGENT
    assert arrets == []


def test_un_agent_dans_un_autre_projet_ouvert_compte_aussi(maj_servie, tmp_path):
    affiche = atelier_simule(tmp_path / "affiche")
    autre = atelier_simule(tmp_path / "autre")
    autre.occupe = True
    faux = FausseMiseAJour(resultat=ResultatMaj(False, PHRASE_AGENT))
    tableau, _, faux, arrets = maj_servie(faux, [affiche, autre])
    tableau.appeler("/api/mise-a-jour")
    assert faux.mises_a_jour == [True]
    assert fil_de(affiche)[-1] == PHRASE_AGENT
    assert PHRASE_AGENT not in fil_de(autre)
    assert arrets == []


def test_sans_agent_au_travail_la_mise_a_jour_est_lancee_puis_le_processus_s_arrete(maj_servie):
    recue = threading.Event()
    constats = []
    arrets = []

    def arreter():
        constats.append(recue.wait(5))  # la réponse a-t-elle atteint la page avant l'arrêt ?
        arrets.append(1)

    faux = FausseMiseAJour()
    tableau, _, faux, _ = maj_servie(faux, arreter=arreter)
    code, vue = tableau.appeler("/api/mise-a-jour")  # reçue pendant que l'arrêt attend
    recue.set()
    assert code == 200
    assert vue["mise_a_jour_faite"] == {"fait": True, "phrase": PHRASE_REDEMARRAGE}
    assert vue["mise_a_jour"]["disponible"] is True  # la vue complète accompagne la réponse
    assert faux.mises_a_jour == [False]
    assert attendre(lambda: arrets == [1])
    assert constats == [True]
    assert fil_de(tableau.atelier)[-1] == PHRASE_REDEMARRAGE


def test_un_echec_ne_change_rien_ne_s_arrete_pas_et_le_fil_explique(maj_servie, capsys):
    phrase = "Mise à jour impossible : le dépôt en ligne ne répond pas."
    faux = FausseMiseAJour(resultat=ResultatMaj(False, phrase, "fatal: unable to access 'x'"))
    tableau, _, faux, arrets = maj_servie(faux)
    code, vue = tableau.appeler("/api/mise-a-jour")
    assert code == 200
    assert vue["mise_a_jour_faite"] == {"fait": False, "phrase": phrase}
    assert fil_de(tableau.atelier)[-1] == phrase
    assert arrets == []
    assert tableau.etat()["en_marche"] is False  # Atelier continue de répondre


def test_le_detail_va_au_journal_et_jamais_dans_la_vue_ni_le_fil(maj_servie, capsys):
    detail = "fatal: détail brut de git"
    faux = FausseMiseAJour(resultat=ResultatMaj(False, "Mise à jour impossible : git.", detail))
    tableau, _, _, _ = maj_servie(faux)
    _, vue = tableau.appeler("/api/mise-a-jour")
    assert detail in capsys.readouterr().err
    assert detail not in json.dumps(vue, ensure_ascii=False)
    assert detail not in json.dumps(fil_de(tableau.atelier), ensure_ascii=False)


def test_une_seule_mise_a_jour_a_la_fois(maj_servie):
    liberer = threading.Event()
    faux = FausseMiseAJour(bloquer=liberer)
    tableau, _, faux, arrets = maj_servie(faux)
    premiere = []
    fil = threading.Thread(
        target=lambda: premiere.append(tableau.appeler("/api/mise-a-jour")), daemon=True
    )
    fil.start()
    assert faux.entree.wait(5)
    code, vue = tableau.appeler("/api/mise-a-jour")  # pendant la première : rend tout de suite
    assert code == 200
    assert vue["mise_a_jour_faite"] == {"fait": False, "phrase": PHRASE_DEJA_EN_COURS}
    assert faux.mises_a_jour == [False]
    liberer.set()
    fil.join(5)
    assert premiere[0][1]["mise_a_jour_faite"]["fait"] is True
    assert attendre(lambda: arrets == [1])
    assert faux.mises_a_jour == [False]  # le second clic n'a rien lancé


def test_sans_fonction_d_arret_le_serveur_ne_s_arrete_pas_meme_si_fait_est_vrai(maj_servie):
    tableau, _, faux, _ = maj_servie(arreter=None)
    code, vue = tableau.appeler("/api/mise-a-jour")
    assert code == 200
    # Le double de la démonstration rend « fait » vrai : la phrase est la sienne, sans redémarrage.
    assert vue["mise_a_jour_faite"] == {
        "fait": True,
        "phrase": "Atelier a été mis à jour. Il va redémarrer.",
    }


def test_la_demonstration_passe_par_le_double_simule_et_ne_s_arrete_pas(tmp_path):
    atelier = projet_simule(tmp_path / "demo", "Démo", 0.0)
    suivi = SuiviMiseAJour(MiseAJourSimulee(), pause_s=1000)
    serveur = TableauMaj([atelier], tmp_path, suivi)
    try:
        suivi.demarrer()
        assert attendre(lambda: serveur.etat()["mise_a_jour"]["disponible"])
        code, vue = serveur.appeler("/api/mise-a-jour")
        assert code == 200
        assert vue["mise_a_jour_faite"] == {
            "fait": True,
            "phrase": "Mise à jour simulée : rien n'a changé.",
        }
        assert "Mise à jour simulée : rien n'a changé." in fil_de(atelier)
        assert suivi.arreter is None
        assert serveur.etat()["mise_a_jour"]["disponible"] is True  # le double l'annonce toujours
    finally:
        suivi.finir()
        serveur.fermer()


def test_la_route_sans_projet_ouvert_n_ecrit_au_fil_de_personne(maj_servie):
    # Aucune ligne du fil n'est écrite sans projet ouvert, et rien ne plante.
    faux = FausseMiseAJour(resultat=ResultatMaj(False, "Atelier est déjà à jour."))
    tableau, _, _, arrets = maj_servie(faux, ateliers=[])
    code, vue = tableau.appeler("/api/mise-a-jour")
    assert code == 200
    assert vue["mise_a_jour_faite"] == {"fait": False, "phrase": "Atelier est déjà à jour."}
    assert arrets == []


def monter_commande(monkeypatch, tmp_path):
    """Remplace le serveur et les projets : on lit seulement ce que la commande y branche."""
    from atelier import __main__ as principal

    pris = {}

    class FauxServeur:
        def serve_forever(self):
            pass

    def fabriquer(projets, port, suivi=None):
        pris["suivi"] = suivi
        return FauxServeur()

    monkeypatch.setattr(principal, "creer_serveur", fabriquer)
    monkeypatch.setattr(SuiviMiseAJour, "demarrer", lambda self: pris.setdefault("demarre", True))
    monkeypatch.setattr(principal, "monter_projets", lambda a: (Projets(tmp_path, None), tmp_path))
    return principal, pris


def test_servir_vise_le_dossier_d_atelier_et_s_arrete_par_la_fonction_d_arret(
    monkeypatch, tmp_path
):
    principal, pris = monter_commande(monkeypatch, tmp_path)
    principal.commande_servir(Namespace(port=0))
    suivi = pris["suivi"]
    assert isinstance(suivi.maj, MiseAJour)
    racine = pathlib.Path(principal.__file__).resolve().parent.parent
    assert suivi.maj.dossier == racine and (racine / "atelier").is_dir()
    assert suivi.arreter is principal.arreter_le_processus
    assert pris["demarre"] is True


def test_la_demonstration_recoit_le_double_simule_sans_fonction_d_arret(monkeypatch, tmp_path):
    principal, pris = monter_commande(monkeypatch, tmp_path)
    monkeypatch.setattr(principal, "atelier_de_demonstration", lambda d: atelier_simule(tmp_path))
    principal.commande_demo(Namespace(port=0, delai=0.0))
    suivi = pris["suivi"]
    assert isinstance(suivi.maj, MiseAJourSimulee) and suivi.arreter is None


def test_la_fonction_d_arret_sort_avec_le_code_zero_apres_avoir_vide_les_sorties(monkeypatch):
    from atelier import __main__ as principal

    sorties = []
    monkeypatch.setattr(principal.os, "_exit", lambda code: sorties.append(code))
    principal.arreter_le_processus()
    assert sorties == [0]


# --- Un nouveau chantier dans le même projet -----------------------------------------------


def test_un_nouveau_chantier_archive_l_ancien_et_repart_de_zero(tableau, tmp_path):
    atelier = atelier_simule(tmp_path, [tache("A")])
    serveur = tableau(atelier)
    atelier.message("Premier objectif")
    assert attendre(lambda: not atelier.occupe)
    ancienne_session = atelier.moteur.chantier.session
    assert ancienne_session

    code, vue = serveur.appeler("/api/chantier/nouveau")

    assert code == 200 and vue["nouveau_chantier"]["fait"] is True
    phrase = vue["nouveau_chantier"]["phrase"]
    assert phrase == (
        "Nouveau chantier ouvert. Le précédent, « Essai », est archivé : aucune tâche livrée "
        "sur 1, 1 inachevée. Son journal se relit dans l'onglet Chantier, sous « Chantiers "
        "archivés ». Le code du projet n'a pas changé."
    )
    nouveau = atelier.moteur.chantier
    assert nouveau.taches == [] and nouveau.session == "" and nouveau.contrat.valide is False
    assert nouveau.contrat.objectif == "" and nouveau.projet == "essai"
    textes = [e["texte"] for e in nouveau.evenements]
    accueil = "Bonjour. Dis-moi ce que tu veux construire, je te proposerai un découpage."
    assert textes == [accueil, phrase]
    assert vue["taches"] == [] and "Premier objectif" not in json.dumps(vue, ensure_ascii=False)
    # L'ancien chantier est lisible dans son archive, et l'état sur disque est le nouveau.
    (archive,) = (tmp_path / ".atelier" / "archives").iterdir()
    ancien = json.loads((archive / "etat.json").read_text("utf-8"))
    assert ancien["session"] == ancienne_session and [t["id"] for t in ancien["taches"]] == ["A"]
    assert "Premier objectif" in [e["texte"] for e in ancien["evenements"]]
    assert (archive / "CAHIER.md").read_text("utf-8").startswith("# Cahier des charges")
    courant = json.loads((tmp_path / ".atelier" / "etat.json").read_text("utf-8"))
    assert courant["taches"] == [] and courant["session"] == ""


def test_apres_un_nouveau_chantier_l_orchestrateur_repart_d_une_session_neuve(tmp_path):
    atelier = atelier_simule(tmp_path)
    atelier.message("Premier objectif")
    assert attendre(lambda: not atelier.occupe)
    ancienne_session = atelier.moteur.chantier.session
    assert atelier.nouveau_chantier()["fait"] is True
    atelier.message("Second objectif")
    assert attendre(lambda: not atelier.occupe)
    nouvelle_session = atelier.moteur.chantier.session
    assert nouvelle_session and nouvelle_session != ancienne_session
    dernier = atelier.moteur.agent.appels[-1]
    assert dernier["session"] == nouvelle_session and dernier["reprise"] is False


def test_un_nouveau_chantier_est_refuse_tant_que_l_orchestrateur_repond(tmp_path):
    atelier = atelier_simule(tmp_path, [tache("A")])
    atelier.message("Objectif")
    assert attendre(lambda: not atelier.occupe)
    avant = atelier.moteur.chantier
    atelier.occupe = True
    resultat = atelier.nouveau_chantier()
    atelier.occupe = False
    assert resultat == {
        "fait": False,
        "phrase": "Un agent travaille ou l'orchestrateur répond : attends qu'il ait fini, "
        "ou arrête-le, avant d'ouvrir un nouveau chantier.",
    }
    assert atelier.moteur.chantier is avant
    assert not (tmp_path / ".atelier" / "archives").exists()


def test_un_nouveau_chantier_est_refuse_tant_qu_un_agent_travaille(tableau, tmp_path):
    atelier = atelier_simule(tmp_path, [tache("A")], delai_s=5)
    tableau(atelier)
    atelier.lancer()
    assert attendre(atelier.en_marche)
    avant = atelier.moteur.chantier
    assert atelier.nouveau_chantier()["fait"] is False
    assert atelier.moteur.chantier is avant
    assert not (tmp_path / ".atelier" / "archives").exists()


def test_un_chantier_encore_vide_n_est_pas_archive(tmp_path):
    atelier = atelier_simule(tmp_path)
    resultat = atelier.nouveau_chantier()
    assert resultat == {
        "fait": False,
        "phrase": "Ce chantier est encore vide : il n'y a rien à archiver.",
    }
    assert not (tmp_path / ".atelier" / "archives").exists()


def test_deux_nouveaux_chantiers_de_suite_gardent_deux_archives(tmp_path):
    atelier = atelier_simule(tmp_path)
    for objectif in ("Un", "Deux"):
        atelier.message(objectif)
        assert attendre(lambda: not atelier.occupe)
        assert atelier.nouveau_chantier()["fait"] is True
    archives = sorted((tmp_path / ".atelier" / "archives").iterdir())
    assert len(archives) == 2
    objectifs = [
        [e["texte"] for e in json.loads((a / "etat.json").read_text("utf-8"))["evenements"]]
        for a in archives
    ]
    assert "Un" in objectifs[0] and "Deux" in objectifs[1]


def test_le_nouveau_fil_redit_ce_qui_est_su_de_la_facturation(tmp_path):
    atelier = atelier_simule(tmp_path)
    atelier.annoncer_connexion({})
    atelier.message("Objectif")
    assert attendre(lambda: not atelier.occupe)
    assert atelier.nouveau_chantier()["fait"] is True
    textes = [e["texte"] for e in atelier.moteur.chantier.evenements]
    assert any(t.startswith("Aucune variable ANTHROPIC_API_KEY") for t in textes) or any(
        t.startswith("Une variable ANTHROPIC_API_KEY") for t in textes
    )


def test_le_chantier_archive_porte_le_nom_choisi_et_apparait_dans_la_vue(tableau, tmp_path):
    atelier = atelier_simule(tmp_path, [tache("A")])
    serveur = tableau(atelier)
    atelier.message("Objectif")
    assert attendre(lambda: not atelier.occupe)
    _, vue = serveur.appeler("/api/chantier/nouveau", {"nom": "  Refonte\ndu   tableau  "})
    assert vue["nouveau_chantier"]["fait"] is True
    (archive,) = vue["archives"]
    assert archive["nom"] == "Refonte du tableau"
    assert archive["bilan"] == "Aucune tâche livrée sur 1, 1 inachevée."
    assert archive["archive_le"] and " à " in archive["archive_le"]
    assert archive["ouvert_le"] and " à " in archive["ouvert_le"]
    # Le journal se lit par la route, et un identifiant inconnu ou piégé ne lit rien.
    _, lu = serveur.appeler("/api/archives/lire", {"id": archive["id"]})
    assert lu["archive"]["trouvee"] is True
    assert lu["archive"]["journal"]["nom"] == "Refonte du tableau"
    for piege in ("../etat", "2026-01-01-000000", ["x"], ""):
        _, lu = serveur.appeler("/api/archives/lire", {"id": piege})
        assert lu["archive"] == {
            "trouvee": False,
            "phrase": "Cette archive est introuvable ou illisible.",
        }


def test_sans_nom_le_chantier_archive_prend_son_objectif(tmp_path):
    atelier = atelier_simule(tmp_path, [tache("A")])
    atelier.moteur.chantier.contrat.objectif = "Moteur de calcul de la norme"
    atelier.message("Bonjour")
    assert attendre(lambda: not atelier.occupe)
    assert atelier.vue()["nom_propose"] == "Moteur de calcul de la norme"
    assert atelier.nouveau_chantier()["fait"] is True
    assert atelier.vue()["archives"][0]["nom"] == "Moteur de calcul de la norme"


# --- La carte du code ----------------------------------------------------------------------


def test_la_vue_porte_l_etat_de_la_carte_et_un_projet_neuf_n_a_pas_encore_de_carte(tmp_path):
    atelier = atelier_simule(tmp_path)
    resume = atelier.vue()["carte"]
    assert resume["etat"] == "absente" and resume["en_cours"] == [] and resume["auto"] is True


def test_la_carte_s_analyse_et_se_lit_par_les_routes(tableau, tmp_path):
    (tmp_path / "app.py").write_text('"""Le coeur du projet."""\n\n\ndef lancer():\n    pass\n')
    (tmp_path / "outil.py").write_text("import app\n")
    atelier = atelier_simule(tmp_path)
    serveur = tableau(atelier)
    _, vue = serveur.appeler("/api/carte/estimer")
    # Deux fichiers de code, et le cahier que l'Atelier écrit dans chaque projet.
    assert vue["estimation"]["fichiers"] == 3 and vue["estimation"]["appels"] == 0
    assert vue["estimation"]["phrase"] == (
        "3 fichiers. Les explications sont tirées des commentaires du code."
    )
    _, vue = serveur.appeler("/api/carte/analyser")
    assert vue["analyse"] == {
        "fait": True,
        "phrase": "Analyse lancée : la carte se remplit au fil des explications.",
    }
    assert attendre(lambda: not atelier.carte.occupe())
    assert serveur.etat()["carte"]["etat"] == "prete"
    _, vue = serveur.appeler("/api/carte/lire")
    fiches = {f["chemin"]: f for f in vue["carte_complete"]["fichiers"]}
    assert fiches["app.py"]["resume"] == "Le coeur du projet."
    assert vue["carte_complete"]["liens"] == [["outil.py", "app.py"]]
    atelier.carte.finir()


def test_une_seconde_analyse_pendant_la_premiere_est_refusee(tmp_path):
    atelier = atelier_simule(tmp_path)
    porte = threading.Event()
    atelier.carte._fil = threading.Thread(target=porte.wait, daemon=True)
    atelier.carte._fil.start()
    assert atelier.analyser_carte() == {"fait": False, "phrase": "L'analyse est déjà en cours."}
    porte.set()


def test_en_demonstration_la_carte_est_celle_de_l_atelier_et_ses_taches_font_clignoter(tmp_path):
    atelier = projet_simule(tmp_path / "demo", "Démo", 0.0)
    assert atelier.carte.depot == pathlib.Path(__file__).resolve().parent.parent
    phrase = atelier.estimer_carte()["phrase"]
    assert phrase.startswith("Démonstration : la carte montre le code de l'Atelier, ")
    atelier.carte.carte = {
        "fichiers": {
            "a.py": {"genre": "code"},
            "b.py": {"genre": "code"},
            "c.md": {"genre": "documentation"},
        },
        "liens": [],
    }
    atelier.moteur.chantier.taches = [tache("A", etat="en_cours"), tache("B", etat="a_lancer")]
    en_cours = atelier.en_cours()
    assert set(en_cours) <= {"a.py", "b.py"} and en_cours
    assert all(agents == ["tâche A"] for agents in en_cours.values())
    # La tâche en cours écrit aussi un nouveau fichier, relié à ceux qu'elle modifie.
    prov = atelier.provisoire()
    assert [f["chemin"] for f in prov["fichiers"]] == ["atelier/brouillon_a.py"]
    assert prov["fichiers"][0]["agents"] == ["tâche A"]
    assert all("atelier/brouillon_a.py" in lien for lien in prov["liens"]) and prov["liens"]


def test_les_fichiers_en_cours_viennent_de_la_copie_de_travail_de_chaque_tache(tmp_path):
    class Controles(ControlesSimules):
        def _arbre(self, t):
            return tmp_path / "arbres" / t.id

        def fichiers_modifies(self, t, dossier, resultat):
            return {"A": ["app.py", "neuf.py"], "B": ["app.py"]}[t.id]

    (tmp_path / "arbres" / "A").mkdir(parents=True)
    (tmp_path / "arbres" / "B").mkdir(parents=True)
    atelier = atelier_simule(tmp_path, controles=Controles())
    atelier.moteur.chantier.taches = [
        tache("A", etat="en_cours"),
        tache("B", etat="en_verification"),
        tache("C", etat="verifie"),
    ]
    atelier.activite.ajouter({"agent": "A-ouvrier-1", "type": "outil", "contenu": "Modifie app.py"})
    assert atelier.en_cours() == {"app.py": ["A-ouvrier-1", "tâche B"], "neuf.py": ["A-ouvrier-1"]}


def test_le_travail_en_cours_ajoute_a_la_carte_ses_fichiers_et_liens_provisoires(tmp_path):
    class Controles(ControlesSimules):
        def _arbre(self, t):
            return tmp_path / "arbres" / t.id

        def fichiers_modifies(self, t, dossier, resultat):
            return ["app.py", "neuf.py"]

    arbre = tmp_path / "arbres" / "A"
    arbre.mkdir(parents=True)
    (arbre / "app.py").write_text("import neuf\nimport outils\n", "utf-8")
    (arbre / "neuf.py").write_text('"""Calcule les formules."""\n', "utf-8")
    atelier = atelier_simule(tmp_path, controles=Controles())
    atelier.carte.carte = {
        "fichiers": {"app.py": {"genre": "code"}, "outils.py": {"genre": "code"}},
        "liens": [["app.py", "outils.py"]],
    }
    atelier.moteur.chantier.taches = [tache("A", etat="en_cours")]
    prov = atelier.provisoire()
    assert prov["fichiers"] == [
        {"chemin": "neuf.py", "genre": "code", "lignes": 1,
         "resume": "Calcule les formules.", "agents": ["tâche A"]}
    ]  # fmt: skip
    assert prov["liens"] == [["app.py", "neuf.py"]]  # le lien déjà connu n'est pas répété


def test_creer_un_projet_et_lire_l_accueil_par_le_tableau(tmp_path):
    from atelier.modele import Chantier as C

    depot = tmp_path / "premier"
    depot.mkdir()
    tableau = Tableau(atelier_simule(depot), tmp_path)
    try:

        def creer(dossier, nom):
            dossier.mkdir()
            vide = C(projet=nom, contrat=Contrat(objectif=""))
            return Atelier(dossier, vide, AgentSimule(), ControlesSimules(), {})

        tableau.serveur.RequestHandlerClass.projets._creer = creer
        code, vue = tableau.appeler("/api/projets/creer", {"nom": "Deuxième"})
        assert code == 200 and vue["projet"] == "Deuxième"
        code, vue = tableau.appeler("/api/accueil")
        assert code == 200 and {p["id"] for p in vue["accueil"]} == {"premier", "deuxieme"}
        code, vue = tableau.appeler("/api/projets/nouvelle-session", {"id": "premier"})
        assert code == 200 and vue["nouveau_chantier"]["fait"] is False  # rien à archiver
        assert vue["projet"] == "essai"  # le projet est ouvert quand même
    finally:
        tableau.fermer()


# --- « Toujours pendant ce chantier » ------------------------------------------------------


def test_pendant_ce_chantier_retient_les_regles_au_chantier_pas_au_profil(tableau, tmp_path):
    atelier = atelier_simule(tmp_path, guichet=Guichet())
    serveur = tableau(atelier)
    reponses = demander_en_fil(atelier.guichet, entree={"command": "cd src && sed -e x f"})
    (demande,) = serveur.etat()["autorisations"]
    assert demande["regle"] == "" and demande["regles_chantier"] == ["Bash(sed:*)"]
    _, reponse = serveur.appeler("/api/autorisation", {"id": demande["id"], "choix": "chantier"})
    assert reponse["autorisation"] == {
        "reglee": True,
        "phrase": "Autorisé pendant ce chantier : Bash(sed:*). Ces règles s'effaceront quand le "
        "chantier sera archivé ; le profil du projet n'est pas touché.",
    }
    assert attendre(lambda: reponses) and reponses[0].regles == ("Bash(sed:*)",)
    assert atelier.moteur.chantier.autorisations_chantier == ["Bash(sed:*)"]
    assert atelier.moteur.agent.regles_chantier() == ["Bash(sed:*)"]
    assert not (tmp_path / "chantier" / "profil.json").exists()
    etat = json.loads((tmp_path / ".atelier" / "etat.json").read_text("utf-8"))
    assert etat["autorisations_chantier"] == ["Bash(sed:*)"]
    textes = [e["texte"] for e in atelier.moteur.chantier.evenements]
    assert "Autorisation retenue pendant ce chantier : Bash(sed:*)." in textes

    # Une seconde fois : pas de doublon.
    demander_en_fil(atelier.guichet, entree={"command": "sed -e y g"})
    (demande,) = serveur.etat()["autorisations"]
    serveur.appeler("/api/autorisation", {"id": demande["id"], "choix": "chantier"})
    assert atelier.moteur.chantier.autorisations_chantier == ["Bash(sed:*)"]


def test_pendant_ce_chantier_sans_regle_possible_laisse_la_demande_ouverte(tableau, tmp_path):
    atelier = atelier_simule(tmp_path, guichet=Guichet())
    serveur = tableau(atelier)
    reponses = demander_en_fil(atelier.guichet, entree={"command": "bash -c 'rm x'"})
    (demande,) = serveur.etat()["autorisations"]
    assert demande["regles_chantier"] == []
    _, reponse = serveur.appeler("/api/autorisation", {"id": demande["id"], "choix": "chantier"})
    assert reponse["autorisation"] == {
        "reglee": False,
        "phrase": "Aucune règle n'est possible pour cette demande, même pour ce chantier : "
        "autorise-la une fois, ou refuse-la.",
    }
    assert reponses == [] and atelier.moteur.chantier.autorisations_chantier == []


def test_les_regles_du_chantier_partent_avec_lui_et_reviennent_au_redemarrage(tmp_path):
    atelier = atelier_simule(tmp_path, [tache("A")], guichet=Guichet())
    demander_en_fil(atelier.guichet, entree={"command": "sed -e x f"})
    (demande,) = atelier.guichet.ouvertes()
    assert atelier.autoriser(demande["id"], "chantier")["reglee"] is True
    # Au redémarrage, l'état relu garde les règles du chantier en cours.
    relu = Chantier.charger(tmp_path / ".atelier" / "etat.json")
    assert relu.autorisations_chantier == ["Bash(sed:*)"]
    # Un nouveau chantier repart sans elles ; l'archive les garde dans son état.
    atelier.message("Un objectif")
    assert attendre(lambda: not atelier.occupe)
    assert atelier.nouveau_chantier()["fait"] is True
    assert atelier.moteur.chantier.autorisations_chantier == []
    assert atelier.moteur.agent.regles_chantier() == []
    (archive,) = (tmp_path / ".atelier" / "archives").iterdir()
    ancien = json.loads((archive / "etat.json").read_text("utf-8"))
    assert ancien["autorisations_chantier"] == ["Bash(sed:*)"]


def test_un_etat_d_avant_se_relit_sans_regles_de_chantier(tmp_path):
    donnees = chantier([]).en_dict()
    del donnees["autorisations_chantier"]
    assert Chantier.depuis_dict(donnees).autorisations_chantier == []


# --- le profil écrit d'un seul geste, le réglage d'outils qu'on peut réessayer ---------------

PROFIL_D_AVANT = '{"nom": "Café", "commandes_permises": ["ls"], "autorisations": ["Read"]}'
REESSAYER = "La demande reste ouverte : accepte-la à nouveau une fois le profil corrigé."


def ecrire_sans_lever(ecriture):
    """Lance une écriture du profil ; une erreur levée ne compte pas, seul le fichier compte."""
    try:
        ecriture()
    except (ValueError, OSError):
        pass


def par_les_outils(atelier, texte):
    atelier._proposer_outils({"commandes_permises": [texte]})
    atelier.decider(atelier.moteur.chantier.demandes[-1]["id"], ACCEPTER_OUTILS)


ECRITURES_DU_PROFIL = {
    "_regler_outils": par_les_outils,
    "_inscrire_regle": lambda atelier, texte: atelier._inscrire_regle(f"Bash({texte}:*)"),
    "_ecrire_au_profil": lambda atelier, texte: atelier._ecrire_au_profil("mode_ouvriers", texte),
}


@pytest.mark.parametrize("ecriture", sorted(ECRITURES_DU_PROFIL))
@pytest.mark.parametrize("coupure", ["en_ecrivant", "en_mettant_en_place"])
def test_une_ecriture_du_profil_interrompue_laisse_le_profil_d_avant_intact(
    tmp_path, monkeypatch, ecriture, coupure
):
    chemin = tmp_path / "chantier" / "profil.json"
    chemin.parent.mkdir(parents=True)
    chemin.write_text(PROFIL_D_AVANT, "utf-8")
    atelier = atelier_simule(tmp_path, profil={"commandes_permises": ["ls"]})
    texte = "make"
    if coupure == "en_ecrivant":
        texte = "make \udcff"  # un caractère impossible à écrire : l'écriture s'arrête en route
    else:
        remplacer = modele_module.os.replace

        def arret_de_la_machine(source, cible):
            if pathlib.Path(cible) == chemin:
                raise OSError("arrêt de la machine")
            return remplacer(source, cible)

        monkeypatch.setattr(modele_module.os, "replace", arret_de_la_machine)

    ecrire_sans_lever(lambda: ECRITURES_DU_PROFIL[ecriture](atelier, texte))

    assert chemin.read_bytes() == PROFIL_D_AVANT.encode("utf-8")
    assert [f.name for f in chemin.parent.iterdir() if f.name.startswith("profil")] == [
        "profil.json"
    ]


def reglage_propose(depot, contenu, **outils):
    """Un profil écrit tel quel, un réglage d'outils proposé : rend ce qu'il faut pour le régler."""
    chemin = depot / "chantier" / "profil.json"
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(contenu, "utf-8")
    controles = ControlesQuiNotent()
    atelier = atelier_simule(depot, profil={"commandes_permises": ["ls"]}, controles=controles)
    atelier._proposer_outils({"commandes_permises": ["make"], **outils})
    return atelier, chemin, controles, atelier.moteur.chantier.demandes[0]


def demande_montree(vue, demande):
    (montree,) = [d for d in vue["demandes"] if d["id"] == demande["id"]]
    return montree


def deux_lignes_dans_l_ordre(textes, raison):
    rang = textes.index(f"Réglage des outils non appliqué : {raison}")
    return textes[rang + 1] == REESSAYER


@pytest.mark.parametrize("contenu", ["[1, 2]", "pas du json"])
def test_un_reglage_non_applique_redevient_en_attente_et_s_applique_au_second_clic(
    tableau, tmp_path, contenu
):
    atelier, chemin, controles, demande = reglage_propose(tmp_path, contenu, commandes=["make t"])
    serveur = tableau(atelier)
    decision = {"id": demande["id"], "choix": ACCEPTER_OUTILS}

    _, vue = serveur.appeler("/api/decision", decision)

    montree = demande_montree(vue, demande)
    assert montree["reponse"] is None
    assert montree["options"] == [ACCEPTER_OUTILS, REFUSER_OUTILS]
    assert deux_lignes_dans_l_ordre([e["texte"] for e in vue["evenements"]], ILLISIBLE)
    assert chemin.read_text("utf-8") == contenu and controles.reglages == []

    chemin.write_text('{"nom": "Café"}', "utf-8")  # la personne responsable corrige le profil
    _, vue = serveur.appeler("/api/decision", decision)

    assert demande_montree(vue, demande)["reponse"] == ACCEPTER_OUTILS
    attendu = {"nom": "Café", "commandes_permises": ["ls", "make"], "commandes": ["make t"]}
    assert json.loads(chemin.read_text("utf-8")) == attendu
    assert controles.reglages == [attendu]
    assert atelier.moteur.profil == {"commandes_permises": ["ls", "make"], "commandes": ["make t"]}
    textes = [e["texte"] for e in vue["evenements"]]
    assert sum(t.startswith("Outils réglés.") for t in textes) == 1


def test_un_reglage_non_ecrit_redevient_en_attente_et_s_applique_au_second_clic(
    tmp_path, monkeypatch
):
    atelier, chemin, controles, demande = reglage_propose(tmp_path, '{"nom": "Café"}')
    remplacer, pannes = modele_module.os.replace, [OSError("disque plein")]

    def disque_plein(source, cible):
        if pathlib.Path(cible) == chemin and pannes:
            raise pannes.pop()
        return remplacer(source, cible)

    monkeypatch.setattr(modele_module.os, "replace", disque_plein)
    atelier.decider(demande["id"], ACCEPTER_OUTILS)

    assert demande["reponse"] is None
    assert deux_lignes_dans_l_ordre(textes_du_fil(atelier), NON_ECRIT)
    assert chemin.read_text("utf-8") == '{"nom": "Café"}' and controles.reglages == []

    atelier.decider(demande["id"], ACCEPTER_OUTILS)

    assert demande["reponse"] == ACCEPTER_OUTILS
    assert json.loads(chemin.read_text("utf-8"))["commandes_permises"] == ["ls", "make"]
    assert len(controles.reglages) == 1


def test_un_reglage_ecarte_reste_repondu(tmp_path):
    atelier, chemin, controles, demande = reglage_propose(tmp_path, '{"nom": "Café"}')
    atelier.decider(demande["id"], REFUSER_OUTILS)
    atelier.decider(demande["id"], ACCEPTER_OUTILS)
    assert demande["reponse"] == REFUSER_OUTILS
    assert chemin.read_text("utf-8") == '{"nom": "Café"}' and controles.reglages == []
    assert REESSAYER not in textes_du_fil(atelier)


def test_deux_clics_en_meme_temps_n_appliquent_le_reglage_qu_une_fois(tmp_path):
    atelier, chemin, controles, demande = reglage_propose(tmp_path, '{"nom": "Café"}')
    depart = threading.Barrier(2)

    def cliquer():
        depart.wait()
        atelier.decider(demande["id"], ACCEPTER_OUTILS)

    fils = [threading.Thread(target=cliquer) for _ in range(2)]
    for fil in fils:
        fil.start()
    for fil in fils:
        fil.join(5)
    assert len(controles.reglages) == 1
    assert sum(t.startswith("Outils réglés.") for t in textes_du_fil(atelier)) == 1


@pytest.mark.parametrize(
    "contenu",
    [
        '{"commandes_permises": "make"}',
        '{"commandes_permises": 5}',
        '{"commandes_permises": null}',
        '{"commandes_permises": ["ls", 3]}',
        '{"commandes": "make test"}',
        '{"commandes": [1]}',
        '{"commandes": {"a": "b"}}',
    ],
)
def test_une_liste_de_commandes_mal_formee_rend_le_profil_illisible(tmp_path, contenu):
    atelier, chemin, controles, demande = reglage_propose(tmp_path, contenu)

    atelier.decider(demande["id"], ACCEPTER_OUTILS)

    assert chemin.read_text("utf-8") == contenu
    assert atelier.moteur.profil == {"commandes_permises": ["ls"]}
    assert controles.reglages == []
    assert demande["reponse"] is None
    assert deux_lignes_dans_l_ordre(textes_du_fil(atelier), ILLISIBLE)
    assert not any(t.startswith("Outils réglés.") for t in textes_du_fil(atelier))


def test_une_regle_deja_au_profil_ne_le_reecrit_pas(tmp_path):
    chemin = tmp_path / "chantier" / "profil.json"
    chemin.parent.mkdir(parents=True)
    contenu = '{"autorisations": ["Bash(npm install:*)"]}'
    chemin.write_text(contenu, "utf-8")
    atelier_simule(tmp_path)._inscrire_regle(REGLE_SIMULEE)
    assert chemin.read_text("utf-8") == contenu


def test_une_regle_deja_au_profil_vaut_quand_meme_a_chaud(tmp_path):
    chemin = tmp_path / "chantier" / "profil.json"
    chemin.parent.mkdir(parents=True)
    chemin.write_text('{"autorisations": ["Bash(npm install:*)"]}', "utf-8")
    profil = {"autorisations": ["Read"]}
    agent = AgentSimule()
    agent.profil = profil
    atelier = atelier_simule(tmp_path, agent=agent, profil=profil)
    atelier._inscrire_regle(REGLE_SIMULEE)
    assert atelier.moteur.profil["autorisations"] == [REGLE_SIMULEE]


def test_le_profil_est_ecrit_en_deux_espaces_avec_les_accents_en_clair(tmp_path):
    chemin = tmp_path / "chantier" / "profil.json"
    chemin.parent.mkdir(parents=True)
    chemin.write_text('{"nom": "Café"}', "utf-8")
    atelier = atelier_simule(tmp_path)
    atelier._ecrire_au_profil("mode_ouvriers", "auto")
    attendu = '{\n  "nom": "Café",\n  "mode_ouvriers": "auto"\n}\n'
    assert chemin.read_bytes() == attendu.encode("utf-8")
    atelier._inscrire_regle("Bash(échafaud:*)")
    attendu = (
        '{\n  "nom": "Café",\n  "mode_ouvriers": "auto",\n'
        '  "autorisations": [\n    "Bash(échafaud:*)"\n  ]\n}\n'
    )
    assert chemin.read_bytes() == attendu.encode("utf-8")


def test_le_dossier_chantier_est_cree_quand_il_manque(tmp_path):
    atelier = atelier_simule(tmp_path)
    shutil.rmtree(tmp_path / "chantier", ignore_errors=True)
    atelier._inscrire_regle(REGLE_SIMULEE)
    chemin = tmp_path / "chantier" / "profil.json"
    assert json.loads(chemin.read_text("utf-8")) == {"autorisations": [REGLE_SIMULEE]}


@pytest.mark.parametrize("valeur", ["make", 5, None, ["ls", 3]])
def test_une_valeur_mal_formee_en_memoire_compte_comme_absente_au_second_clic(
    tableau, tmp_path, valeur
):
    from atelier.projets import creer_depot, ouvrir_depot

    depot = tmp_path / "projet"
    creer_depot(depot, "Projet")
    chemin = depot / "chantier" / "profil.json"
    chemin.write_text(json.dumps({"nom": "Projet", "commandes_permises": valeur}), "utf-8")
    atelier = ouvrir_depot(depot)  # le profil en mémoire porte la valeur mal formée
    serveur = tableau(atelier)
    atelier._proposer_outils({"commandes_permises": ["pytest"]})
    decision = {"id": atelier.moteur.chantier.demandes[-1]["id"], "choix": ACCEPTER_OUTILS}

    statut, vue = serveur.appeler("/api/decision", decision)
    assert statut == 200
    assert deux_lignes_dans_l_ordre([e["texte"] for e in vue["evenements"]], ILLISIBLE)

    chemin.write_text('{"nom": "Projet"}', "utf-8")  # la personne retire la clé du fichier
    statut, vue = serveur.appeler("/api/decision", decision)

    assert statut == 200
    assert json.loads(chemin.read_text("utf-8"))["commandes_permises"] == ["pytest"]
    assert atelier.moteur.profil["commandes_permises"] == ["pytest"]
    textes = [e["texte"] for e in vue["evenements"]]
    assert sum(t.startswith("Outils réglés.") for t in textes) == 1


# --- le blocage : l'orchestrateur en cherche la cause, un clic relance la tâche --------------


@dataclass
class OrchestrateurQuiCherche(AgentSimule):
    """Un faux orchestrateur : garde chaque message reçu et rend, dans l'ordre, les réponses
    prévues (un texte, ou un `Resultat` rendu tel quel ; au-delà, un simple mot).

    Tant que `porte` est fermée, chaque réponse attend, comme une réponse qui s'écrit ; un arrêt
    demandé par l'atelier la coupe. Les ouvriers et vérificateurs restent ceux d'`AgentSimule`.
    """

    reponses: list = field(default_factory=list)
    messages: list = field(default_factory=list)
    porte: object = None

    def converser(self, message, session, reprise, dossier, sur_texte=None, sur_outil=None,
                  contexte=None):  # fmt: skip
        self.messages.append(message)
        prevue = self.reponses.pop(0) if self.reponses else "C'est noté."
        with self._postes.occuper(None, "orchestrateur") as marche:
            if sur_texte:
                sur_texte("Je cherche la cause. ")
            while self.porte is not None and not self.porte.is_set():
                if marche.arret.wait(0.01):
                    break
            arrete = marche.arret.is_set()
        if arrete:
            return Resultat(ok=False, erreur=ARRETE, cout_usd=0.1, tokens=100)
        if isinstance(prevue, Resultat):
            return prevue
        return Resultat(ok=True, texte=prevue, cout_usd=0.5, tokens=1000)


DIAGNOSTIC_UV = (
    "La commande uv est refusée aux agents : c'est elle qui bloque la tâche B.\n\n"
    "```atelier-outils\n"
    '{"commandes_permises": ["uv"], "pourquoi": "Les tests se lancent avec uv."}\n'
    "```"
)
PREUVES = ["tentative 1, ne_sait_pas : uv: commande refusée"] * 2
EMPECHEMENTS = ["uv sync — permission refusée"]
BLOCAGE_OUVERT = "sa demande reste ouverte, avec ses options."


def atelier_bloquable(depot, taches=None, profil=None, controles=None, **orchestrateur):
    """Un atelier dont l'orchestrateur est faux : A est vérifiée, B (et C) peuvent se bloquer."""
    taches = taches or [tache("A", etat="verifie"), tache("B"), tache("C")]
    perimetres = {t.id: t.perimetre for t in taches}
    agent = OrchestrateurQuiCherche(perimetres=perimetres, **orchestrateur)
    return atelier_simule(depot, taches, profil=profil, agent=agent, controles=controles)


def bloquer(atelier, identifiant="B", preuves=PREUVES, empechements=EMPECHEMENTS):
    """Fait ce que fera le moteur : rend la tâche avec une demande de blocage, sous son verrou,
    puis appelle son rappel `sur_blocage` hors du verrou. Rend la demande."""
    moteur = atelier.moteur
    with moteur.verrou:
        bloquee = moteur.chantier.tache(identifiant)
        bloquee.etat = "revenu"
        demande = {
            "id": f"{identifiant}-{len(moteur.chantier.demandes) + 1}",
            "tache": identifiant,
            "nature": "blocage",
            "question": f"Tâche {identifiant}, « {bloquee.titre} » : la même erreur revient.",
            "options": list(OUTILS_DE_LA_DECISION),
            "reponse": None,
            "preuves": list(preuves),
            "empechements": list(empechements),
        }
        moteur.chantier.demandes.append(demande)
    moteur.sur_blocage(demande)
    return demande


def reglages_d_outils(atelier):
    return [d for d in atelier.moteur.chantier.demandes if d.get("nature") == "outils"]


def diagnostic_rendu(atelier, nombre=1):
    """Attend que la conversation soit libre et que `nombre` messages soient partis."""
    agent = atelier.moteur.agent
    return attendre(lambda: len(agent.messages) == nombre and not atelier.occupe)


def tete(message):
    """La première ligne du message lui-même, après l'état du chantier."""
    return message.split("[Message]\n", 1)[1].splitlines()[0]


def test_le_serveur_branche_son_rappel_de_blocage_sur_chaque_moteur(tmp_path):
    atelier = atelier_bloquable(tmp_path)
    assert atelier.moteur.sur_blocage == atelier._sur_blocage

    # Après un nouveau chantier, le même moteur garde le rappel, et un blocage y est diagnostiqué.
    atelier.message("Premier objectif")
    assert diagnostic_rendu(atelier)
    assert atelier.nouveau_chantier()["fait"] is True
    assert atelier.moteur.sur_blocage == atelier._sur_blocage
    atelier.moteur.chantier.taches = [tache("B")]
    bloquer(atelier, "B")
    assert diagnostic_rendu(atelier, 2)
    assert MARQUE_BLOCAGE in atelier.moteur.agent.messages[-1]

    # Un moteur adopté reçoit le rappel lui aussi.
    autre = Moteur(chantier([tache("D")]), atelier.moteur.agent, ControlesSimules())
    atelier.moteur = autre
    assert autre.sur_blocage == atelier._sur_blocage


def test_un_blocage_fait_chercher_la_cause_une_seule_fois_sans_attendre_la_personne(tmp_path):
    atelier = atelier_bloquable(tmp_path)
    agent = atelier.moteur.agent
    demande = bloquer(atelier, "B")

    assert diagnostic_rendu(atelier)
    (message,) = agent.messages
    attendu = message_de_diagnostic(atelier.moteur.chantier.tache("B"), PREUVES, EMPECHEMENTS)
    assert message.startswith("[État du chantier, fourni par l'atelier]\n")
    assert message.endswith(f"[Message]\n{attendu}")
    assert "Commandes permises aux agents : aucune" in message  # l'état dit ce qui est permis
    # Le même blocage signalé de nouveau, même par une copie de la demande : rien ne repart.
    atelier.moteur.sur_blocage(demande)
    atelier.moteur.sur_blocage(dict(demande))
    assert not attendre(lambda: len(agent.messages) > 1 or atelier.occupe, 0.3)
    fil = atelier.moteur.chantier.evenements
    phrase = (
        "La tâche B est bloquée : je demande à l'orchestrateur d'en chercher la cause, "
        "sans t'attendre."
    )
    assert [e["texte"] for e in fil].count(phrase) == 1
    assert not any(e["auteur"] == "toi" for e in fil)  # le message ne vient pas de la personne
    assert MARQUE_BLOCAGE not in json.dumps(fil, ensure_ascii=False)


def test_le_rappel_rend_la_main_tout_de_suite_au_fil_du_moteur(tmp_path):
    porte = threading.Event()
    atelier = atelier_bloquable(tmp_path, porte=porte)
    rendu = threading.Event()

    def fil_du_moteur():
        bloquer(atelier, "B")
        rendu.set()

    threading.Thread(target=fil_du_moteur, daemon=True).start()
    assert rendu.wait(1.0)  # la réponse de l'orchestrateur, elle, attend toujours
    assert attendre(lambda: atelier.moteur.agent.messages) and atelier.occupe
    porte.set()
    assert diagnostic_rendu(atelier)


def test_conversation_occupee_le_diagnostic_part_a_la_fin_de_la_reponse(tmp_path):
    porte = threading.Event()
    atelier = atelier_bloquable(tmp_path, porte=porte)
    agent = atelier.moteur.agent
    atelier.message("Où en est-on ?")
    assert attendre(lambda: agent.messages)

    bloquer(atelier, "B")
    assert not attendre(lambda: len(agent.messages) > 1, 0.3)  # la réponse en cours d'abord

    porte.set()
    assert diagnostic_rendu(atelier, 2)
    assert agent.messages[0].endswith("[Message]\nOù en est-on ?")
    assert MARQUE_BLOCAGE in agent.messages[1]


def test_une_reponse_de_la_personne_avant_le_diagnostic_l_annule(tmp_path):
    porte = threading.Event()
    atelier = atelier_bloquable(tmp_path, porte=porte)
    atelier.message("Où en est-on ?")
    assert attendre(lambda: atelier.moteur.agent.messages)
    demande = bloquer(atelier, "B")
    atelier.decider(demande["id"], ABANDONNER)  # la personne tranche avant la fin de la réponse
    porte.set()
    assert diagnostic_rendu(atelier, 1)
    assert not attendre(lambda: len(atelier.moteur.agent.messages) > 1, 0.3)
    assert demande["diagnostic"] == "sans_objet"


def test_deux_blocages_font_deux_messages_dans_l_ordre(tmp_path):
    porte = threading.Event()
    atelier = atelier_bloquable(tmp_path, porte=porte)
    agent = atelier.moteur.agent
    for identifiant in ("B", "C"):  # deux fils du moteur, l'un après l'autre
        fil = threading.Thread(target=bloquer, args=(atelier, identifiant), daemon=True)
        fil.start()
        fil.join(1)
    assert attendre(lambda: agent.messages)
    assert not attendre(lambda: len(agent.messages) > 1, 0.3)  # jamais deux à la fois
    porte.set()
    assert diagnostic_rendu(atelier, 2)
    assert [tete(m) for m in agent.messages] == [
        f"{MARQUE_BLOCAGE} : tâche B]",
        f"{MARQUE_BLOCAGE} : tâche C]",
    ]


def test_deux_blocages_au_meme_instant_ont_chacun_un_message(tmp_path):
    porte = threading.Event()
    atelier = atelier_bloquable(tmp_path, porte=porte)
    agent = atelier.moteur.agent
    depart = threading.Barrier(2)

    def fil_du_moteur(identifiant):
        depart.wait()
        bloquer(atelier, identifiant)

    fils = [threading.Thread(target=fil_du_moteur, args=(i,), daemon=True) for i in "BC"]
    for fil in fils:
        fil.start()
    for fil in fils:
        fil.join(2)
    assert attendre(lambda: agent.messages)
    assert not attendre(lambda: len(agent.messages) > 1, 0.3)
    porte.set()
    assert diagnostic_rendu(atelier, 2)
    assert sorted(tete(m) for m in agent.messages) == [
        f"{MARQUE_BLOCAGE} : tâche B]",
        f"{MARQUE_BLOCAGE} : tâche C]",
    ]


def test_un_bloc_d_outils_du_diagnostic_devient_une_demande_liee_au_blocage(tableau, tmp_path):
    atelier = atelier_bloquable(tmp_path, reponses=[DIAGNOSTIC_UV])
    serveur = tableau(atelier)
    demande = bloquer(atelier, "B")
    assert diagnostic_rendu(atelier)

    etat = serveur.etat()
    (reglage,) = [d for d in etat["demandes"] if d["nature"] == "outils"]
    assert reglage["pour_blocage"] == demande["id"] and reglage["tache"] is None
    assert reglage["options"] == [ACCEPTER_OUTILS, REFUSER_OUTILS] and reglage["reponse"] is None
    assert reglage["outils"] == {"commandes_permises": ["uv"], "commandes": None}
    assert reglage["question"] == (
        "L'orchestrateur propose de régler les outils du projet. Commandes permises aux agents : "
        "uv. Pourquoi : Les tests se lancent avec uv. Ce réglage débloque la tâche B : si tu "
        "l'acceptes, je la relance seul, au même niveau."
    )
    (montree,) = [d for d in etat["demandes"] if d["id"] == demande["id"]]
    assert montree["reponse"] is None and montree["options"] == OUTILS_DE_LA_DECISION
    textes = [e["texte"] for e in etat["evenements"]]
    assert "La commande uv est refusée aux agents : c'est elle qui bloque la tâche B." in textes
    assert not any("atelier-outils" in t for t in textes)
    assert etat["point_d_etape"].endswith("J'ai besoin de toi pour 2 décisions.")


def bloque_avec_reglage(depot, profil_ecrit):
    """B bloquée, l'orchestrateur a proposé de permettre uv : rend ce qu'il faut pour décider."""
    chemin = depot / "chantier" / "profil.json"
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(profil_ecrit, "utf-8")
    controles = ControlesQuiNotent()
    taches = [tache("A", etat="verifie"), tache("B")]
    atelier = atelier_bloquable(
        depot, taches, {"commandes_permises": ["python3"]}, controles, reponses=[DIAGNOSTIC_UV]
    )
    demande = bloquer(atelier, "B")
    assert diagnostic_rendu(atelier)
    (reglage,) = reglages_d_outils(atelier)
    return atelier, chemin, controles, demande, reglage


def test_accepter_le_reglage_l_applique_puis_relance_seul_la_tache(tableau, tmp_path):
    atelier, chemin, controles, demande, reglage = bloque_avec_reglage(
        tmp_path, '{"nom": "Café", "commandes_permises": ["python3"]}'
    )
    serveur = tableau(atelier)
    b = atelier.moteur.chantier.tache("B")
    niveau = (b.modele, b.effort)

    statut, _ = serveur.appeler("/api/decision", {"id": reglage["id"], "choix": ACCEPTER_OUTILS})

    assert statut == 200
    attendu = {"nom": "Café", "commandes_permises": ["python3", "uv"]}
    assert json.loads(chemin.read_text("utf-8")) == attendu  # le réglage, comme aujourd'hui
    assert controles.reglages == [attendu]
    assert atelier.moteur.profil["commandes_permises"] == ["python3", "uv"]
    assert reglage["reponse"] == ACCEPTER_OUTILS and demande["reponse"] == RELANCER_TEL
    assert attendre(lambda: b.etat == "verifie" and not atelier.en_marche())  # sans second clic
    assert (b.modele, b.effort) == niveau
    textes = textes_du_fil(atelier)
    rang = textes.index(
        "Outils réglés. Commandes permises aux agents : python3, uv. Je relance seul la tâche B, "
        "au même niveau."
    )
    assert textes[rang + 1] == "Décision reçue : relancer au même niveau."
    ouvriers = [a for a in atelier.moteur.agent.appels if a.get("role") == "ouvrier"]
    assert [a["tache"] for a in ouvriers] == ["B"]


def test_un_profil_illisible_au_moment_d_accepter_ne_relance_pas_la_tache(tmp_path):
    atelier, chemin, controles, demande, reglage = bloque_avec_reglage(tmp_path, "pas du json")

    atelier.decider(reglage["id"], ACCEPTER_OUTILS)

    assert reglage["reponse"] is None  # rouverte, comme aujourd'hui
    assert deux_lignes_dans_l_ordre(textes_du_fil(atelier), ILLISIBLE)
    assert demande["reponse"] is None and atelier.moteur.chantier.tache("B").etat == "revenu"
    assert not atelier.en_marche() and controles.reglages == []

    chemin.write_text('{"nom": "Café"}', "utf-8")  # la personne corrige le profil
    atelier.decider(reglage["id"], ACCEPTER_OUTILS)
    assert demande["reponse"] == RELANCER_TEL
    assert attendre(lambda: atelier.moteur.chantier.tache("B").etat == "verifie")


def test_refuser_le_reglage_laisse_le_blocage_ouvert_avec_ses_options(tmp_path):
    atelier, chemin, controles, demande, reglage = bloque_avec_reglage(tmp_path, '{"nom": "Café"}')

    atelier.decider(reglage["id"], REFUSER_OUTILS)

    assert reglage["reponse"] == REFUSER_OUTILS
    assert demande["reponse"] is None and demande["options"] == OUTILS_DE_LA_DECISION
    assert atelier.moteur.chantier.tache("B").etat == "revenu" and not atelier.en_marche()
    assert chemin.read_text("utf-8") == '{"nom": "Café"}' and controles.reglages == []
    assert textes_du_fil(atelier)[-1] == (
        f"Réglage des outils écarté : rien n'a changé. La tâche B reste bloquée : {BLOCAGE_OUVERT}"
    )
    # Le blocage se décide toujours par ses propres options.
    atelier.decider(demande["id"], RELANCER_TEL)
    assert attendre(lambda: atelier.moteur.chantier.tache("B").etat == "verifie")


def test_un_reglage_accepte_apres_une_reponse_au_blocage_ne_relance_rien(tmp_path):
    atelier, chemin, controles, demande, reglage = bloque_avec_reglage(tmp_path, '{"nom": "Café"}')
    atelier.decider(demande["id"], ABANDONNER)

    atelier.decider(reglage["id"], ACCEPTER_OUTILS)

    assert demande["reponse"] == ABANDONNER
    assert atelier.moteur.chantier.tache("B").etat == "abandonnee"
    assert json.loads(chemin.read_text("utf-8"))["commandes_permises"] == ["python3", "uv"]
    assert textes_du_fil(atelier)[-1] == (
        "Outils réglés. Commandes permises aux agents : python3, uv. Je ne relance rien : le "
        "blocage n'attend plus ta réponse."
    )


@pytest.mark.parametrize(
    ("reponse", "phrase", "issue"),
    [
        (
            Resultat(ok=False, erreur="Claude Code ne répond pas."),
            "Le diagnostic du blocage de la tâche B a échoué, faute de joindre Claude Code "
            f"(Claude Code ne répond pas.) : {BLOCAGE_OUVERT}",
            "echec",
        ),
        (
            "Je ne vois aucune commande en cause : le critère 2 se contredit avec le périmètre.",
            "Le diagnostic du blocage de la tâche B ne propose aucun réglage d'outils "
            f"utilisable : {BLOCAGE_OUVERT}",
            "sans_proposition",
        ),
        (
            'Voici.\n\n```atelier-outils\n{"autre": ["uv"]}\n```',
            "Le diagnostic du blocage de la tâche B ne propose aucun réglage d'outils "
            f"utilisable : {BLOCAGE_OUVERT}",
            "sans_proposition",
        ),
    ],
)
def test_un_diagnostic_qui_echoue_ou_ne_propose_rien_laisse_le_blocage_ouvert(
    tmp_path, reponse, phrase, issue
):
    atelier = atelier_bloquable(tmp_path, reponses=[reponse])
    demande = bloquer(atelier, "B")

    assert diagnostic_rendu(atelier)

    assert reglages_d_outils(atelier) == []
    assert demande["reponse"] is None and demande["options"] == OUTILS_DE_LA_DECISION
    assert demande["diagnostic"] == issue
    assert textes_du_fil(atelier).count(phrase) == 1
    assert textes_du_fil(atelier)[-1] == phrase
    assert atelier.moteur.chantier.tache("B").etat == "revenu"


def test_arreter_la_conversation_pendant_un_diagnostic_garde_le_blocage_ouvert(tmp_path):
    porte = threading.Event()
    atelier = atelier_bloquable(tmp_path, porte=porte, reponses=[DIAGNOSTIC_UV])
    demande = bloquer(atelier, "B")
    assert attendre(lambda: atelier.moteur.agent.messages)

    assert attendre(lambda: atelier.arreter()["fait"])

    assert attendre(lambda: not atelier.occupe)
    textes = textes_du_fil(atelier)
    assert textes[-3:] == [
        "Je cherche la cause.",  # ce qui était écrit n'est pas perdu
        "(Réponse arrêtée par toi. Tu peux écrire la suite.)",
        f"Diagnostic du blocage de la tâche B arrêté : {BLOCAGE_OUVERT}",
    ]
    assert reglages_d_outils(atelier) == []
    assert demande["reponse"] is None and demande["options"] == OUTILS_DE_LA_DECISION
    porte.set()


INTERROMPU = (
    "Le diagnostic du blocage de la tâche B n'avait pas abouti quand l'Atelier s'est arrêté, et "
    "je ne le relance pas seul : sa demande reste ouverte, avec ses options. Écris-moi si tu "
    "veux que l'orchestrateur en cherche la cause."
)


def test_le_diagnostic_en_cours_est_garde_dans_l_etat_sauve(tmp_path):
    porte = threading.Event()
    atelier = atelier_bloquable(tmp_path, porte=porte)
    bloquer(atelier, "B")
    assert attendre(lambda: atelier.moteur.agent.messages)
    relu = Chantier.charger(tmp_path / ".atelier" / "etat.json")
    assert relu.demandes[-1]["diagnostic"] == "en_cours"
    porte.set()
    assert diagnostic_rendu(atelier)


@pytest.mark.parametrize("etat_du_diagnostic", ["en_attente", "en_cours", None])
def test_apres_un_redemarrage_un_diagnostic_sans_reponse_n_est_pas_relance(
    tmp_path, etat_du_diagnostic
):
    avant = atelier_bloquable(tmp_path / "avant")
    with avant.moteur.verrou:  # un blocage noté, comme le moteur le laisse, sans son rappel
        avant.moteur.chantier.tache("B").etat = "revenu"
        demande = {"id": "B-1", "tache": "B", "nature": "blocage", "question": "Bloquée.",
                   "options": list(OUTILS_DE_LA_DECISION), "reponse": None,
                   "preuves": PREUVES, "empechements": EMPECHEMENTS}  # fmt: skip
        if etat_du_diagnostic:
            demande["diagnostic"] = etat_du_diagnostic
        avant.moteur.chantier.demandes.append(demande)
    avant._sauver()
    etat = tmp_path / "avant" / ".atelier" / "etat.json"

    agent = OrchestrateurQuiCherche()
    relu = Atelier(tmp_path / "apres", Chantier.charger(etat), agent, ControlesSimules(), {})

    assert not attendre(lambda: agent.messages or relu.occupe, 0.3)
    assert textes_du_fil(relu).count(INTERROMPU) == 1
    (relue,) = relu.moteur.chantier.demandes
    assert relue["reponse"] is None and relue["options"] == OUTILS_DE_LA_DECISION
    # Un second redémarrage ne le redit pas.
    sauve = tmp_path / "apres" / ".atelier" / "etat.json"
    encore = Atelier(tmp_path / "apres", Chantier.charger(sauve), agent, ControlesSimules(), {})
    assert textes_du_fil(encore).count(INTERROMPU) == 1 and agent.messages == []


def test_apres_un_redemarrage_un_reglage_propose_reste_seul_a_decider(tmp_path):
    atelier, chemin, controles, demande, reglage = bloque_avec_reglage(tmp_path, '{"nom": "Café"}')
    etat = tmp_path / ".atelier" / "etat.json"
    agent = OrchestrateurQuiCherche(perimetres={"B": ["b.py"]})
    relu = Atelier(tmp_path, Chantier.charger(etat), agent, ControlesSimules(), {})
    assert INTERROMPU not in textes_du_fil(relu)
    (relu_reglage,) = reglages_d_outils(relu)
    relu.decider(relu_reglage["id"], ACCEPTER_OUTILS)  # le lien survit : un clic relance encore
    assert relu.moteur.chantier.demandes[0]["reponse"] == RELANCER_TEL
    assert attendre(lambda: relu.moteur.chantier.tache("B").etat == "verifie")


QUESTION_UV = (
    "Les contrôles que l'atelier rejoue après chaque livrable lancent des commandes que les "
    "agents n'ont pas le droit de lancer : « uv run pytest -q ». Sans elles, un ouvrier ne peut "
    "pas vérifier lui-même son travail, et sa tâche risque d'être refusée pour rien. Je te "
    "propose de permettre aux agents : uv. Le chantier démarre quand même."
)


def test_a_la_validation_une_commande_de_controle_non_permise_pose_la_question(tmp_path):
    profil = {
        "commandes": ["uv run pytest -q", "python3 -m ruff check .", "make test"],
        "commandes_permises": ["python3"],
    }
    atelier = atelier_simule(tmp_path, [tache("A")], profil=profil, valide=False)
    au_lancement = []
    lancer = atelier.lancer
    atelier.lancer = lambda: (au_lancement.append(list(atelier.moteur.chantier.demandes)), lancer())

    atelier.valider_contrat()

    (avant,) = au_lancement  # la demande existe avant le premier lancement du moteur
    (reglage,) = avant
    assert reglage["nature"] == "outils" and reglage["question"] == QUESTION_UV
    assert reglage["outils"] == {"commandes_permises": ["uv"], "commandes": None}
    assert reglage["options"] == [ACCEPTER_OUTILS, REFUSER_OUTILS] and "pour_blocage" not in reglage
    # Le moteur démarre quand même, et la demande reste visible.
    assert attendre(lambda: atelier.moteur.chantier.tache("A").etat == "verifie")
    assert attendre(lambda: not atelier.en_marche())
    assert atelier.vue()["demandes"][0]["reponse"] is None
    # Une seconde validation ne repose pas la question.
    atelier.valider_contrat()
    assert len(reglages_d_outils(atelier)) == 1
    # L'accepter permet uv, sans toucher aux contrôles.
    atelier.decider(reglage["id"], ACCEPTER_OUTILS)
    chemin = tmp_path / "chantier" / "profil.json"
    assert json.loads(chemin.read_text("utf-8")) == {"commandes_permises": ["python3", "uv"]}
    assert atelier.moteur.profil["commandes"] == profil["commandes"]


def test_a_la_validation_des_controles_permis_ne_changent_rien(tmp_path):
    profil = {"commandes": ["python3 -m pytest -q", "make lint"], "commandes_permises": ["python3"]}
    atelier = atelier_simule(tmp_path, [tache("A")], profil=profil, valide=False)
    avant = textes_du_fil(atelier)
    atelier.lancer = lambda: None
    atelier.valider_contrat()
    assert atelier.moteur.chantier.demandes == []
    assert textes_du_fil(atelier) == [*avant, "Contrat validé. Je lance le chantier."]


def test_a_la_validation_un_lanceur_general_n_est_jamais_propose(tmp_path):
    profil = {"commandes": ["bash scripts/verifier.sh", "FOO=1 pytest", "uv run pytest"]}
    atelier = atelier_simule(tmp_path, [tache("A")], profil=profil, valide=False)
    atelier.lancer = lambda: None
    atelier.valider_contrat()
    (reglage,) = reglages_d_outils(atelier)
    assert reglage["outils"]["commandes_permises"] == ["uv"]
    assert (
        "Pour « bash scripts/verifier.sh » ; « FOO=1 pytest », je ne sais pas proposer de "
        "réglage sûr : demande à l'orchestrateur de s'en occuper."
    ) in reglage["question"]

    # Sans rien à proposer d'un clic, aucune demande : le fil le dit.
    profil = {"commandes": ["sudo make install"]}
    atelier = atelier_simule(tmp_path / "b", [tache("A")], profil=profil, valide=False)
    atelier.lancer = lambda: None
    atelier.valider_contrat()
    assert atelier.moteur.chantier.demandes == []
    assert textes_du_fil(atelier)[-1].startswith("Les contrôles que l'atelier rejoue")
    assert textes_du_fil(atelier)[-1].endswith(
        "Pour « sudo make install », je ne sais pas proposer de réglage sûr : demande à "
        "l'orchestrateur de s'en occuper. Le chantier démarre quand même."
    )


def test_un_signal_mal_forme_ne_leve_pas_et_une_tache_inconnue_est_dite(tmp_path):
    atelier = atelier_bloquable(tmp_path)
    reglage = atelier._proposer_outils({"commandes_permises": ["make"]})
    for signal in (None, "B-1", {"id": "inconnue"}, reglage):  # rien de tout cela ne part
        atelier.moteur.sur_blocage(signal)
    assert not attendre(lambda: atelier.moteur.agent.messages or atelier.occupe, 0.3)

    with atelier.moteur.verrou:  # une demande de blocage dont la tâche n'existe pas
        demande = {"id": "Z-9", "tache": "Z", "nature": "blocage", "question": "Bloquée.",
                   "options": list(OUTILS_DE_LA_DECISION), "reponse": None}  # fmt: skip
        atelier.moteur.chantier.demandes.append(demande)
    atelier.moteur.sur_blocage(demande)
    assert attendre(lambda: demande.get("diagnostic") == "echec" and not atelier.occupe)
    assert atelier.moteur.agent.messages == [] and demande["reponse"] is None
    assert textes_du_fil(atelier)[-1].startswith(
        "Le diagnostic du blocage de la tâche Z a échoué sur une erreur de l'Atelier ("
    )
    assert textes_du_fil(atelier)[-1].endswith(f") : {BLOCAGE_OUVERT}")


# --- seconde passe : les lanceurs généraux, et la demande liée qui survit à un nouveau plan ----

LANCEURS = sorted(LANCEURS_GENERAUX)
SOUS_SON_NOM_OU_SON_CHEMIN = ["{}", "/usr/bin/{}"]


@pytest.mark.parametrize("forme", SOUS_SON_NOM_OU_SON_CHEMIN)
@pytest.mark.parametrize("lanceur", LANCEURS)
def test_chaque_lanceur_est_reconnu_sous_son_nom_et_sous_un_chemin(lanceur, forme):
    assert lanceur_general(forme.format(lanceur))
    assert lanceur_general(forme.format(lanceur).upper() + ".exe")
    assert lanceur_general(f"uv run {forme.format(lanceur)}")  # caché derrière un autre mot


@pytest.mark.parametrize(
    "commande",
    ["python3 -c", "/usr/bin/python3.12 -c", "node -e", "node --eval", "perl -pe", "php -r",
     "uv run python -c", "/opt/bin/ruby -e", "npm exec", "'/bin/bash'"],
)  # fmt: skip
def test_un_interprete_qui_execute_du_code_est_un_lanceur(commande):
    assert lanceur_general(commande)


@pytest.mark.parametrize(
    "commande",
    ["uv", "uv run", "python3", "/usr/bin/python3", "python3 -m pytest -q", "node", "make",
     "cargo", "pytest", "/usr/local/bin/uv", "ruff"],
)  # fmt: skip
def test_une_commande_ordinaire_n_est_pas_un_lanceur(commande):
    assert not lanceur_general(commande)


@pytest.mark.parametrize("forme", SOUS_SON_NOM_OU_SON_CHEMIN)
@pytest.mark.parametrize("lanceur", LANCEURS)
def test_a_la_validation_aucun_lanceur_n_est_propose(tmp_path, lanceur, forme):
    commande = f"{forme.format(lanceur)} -c x"
    profil = {"commandes": [commande, "uv run pytest"]}
    atelier = atelier_simule(tmp_path, [tache("A")], profil=profil, valide=False)
    atelier.lancer = lambda: None
    atelier.valider_contrat()
    (reglage,) = reglages_d_outils(atelier)
    assert reglage["outils"]["commandes_permises"] == ["uv"]
    assert f"Pour « {commande} », je ne sais pas proposer de réglage sûr" in reglage["question"]


@pytest.mark.parametrize("forme", SOUS_SON_NOM_OU_SON_CHEMIN)
@pytest.mark.parametrize("lanceur", LANCEURS)
def test_un_diagnostic_qui_propose_un_lanceur_n_offre_rien_d_un_clic(tmp_path, lanceur, forme):
    propose = forme.format(lanceur)
    bloc = json.dumps({"commandes_permises": ["uv", propose]})
    atelier = atelier_bloquable(tmp_path, reponses=[f"Voici.\n\n```atelier-outils\n{bloc}\n```"])
    demande = bloquer(atelier, "B")

    assert diagnostic_rendu(atelier)

    assert reglages_d_outils(atelier) == []
    assert demande["reponse"] is None and demande["options"] == OUTILS_DE_LA_DECISION
    assert demande["diagnostic"] == "lanceur" and "reglage" not in demande
    assert textes_du_fil(atelier)[-1] == (
        f"Le diagnostic du blocage de la tâche B propose de permettre aux agents « {propose} », "
        "ce qui leur permettrait de tout lancer : je ne te le propose pas d'un clic, et "
        f"{BLOCAGE_OUVERT}"
    )
    assert atelier.moteur.chantier.tache("B").etat == "revenu"


def test_une_demande_d_outils_ordinaire_n_est_pas_filtree(tmp_path):
    atelier = atelier_simule(tmp_path)
    reglage = atelier._proposer_outils({"commandes_permises": ["bash"]})
    assert reglage["outils"] == {"commandes_permises": ["bash"], "commandes": None}
    assert reglage["question"] == (
        "L'orchestrateur propose de régler les outils du projet. Commandes permises aux agents : "
        "bash."
    )


def test_un_reglage_lie_garde_par_un_nouveau_plan_ne_relance_pas_le_nouveau_blocage(tmp_path):
    taches = [tache("A", etat="verifie"), tache("B")]
    atelier = atelier_bloquable(tmp_path, taches, reponses=[DIAGNOSTIC_UV, DIAGNOSTIC_UV])
    with atelier.moteur.verrou:  # deux décisions déjà prises : le blocage de B sera « B-3 »
        for rang in (1, 2):
            atelier.moteur.chantier.demandes.append(
                {"id": f"A-{rang}", "tache": "A", "question": "?", "reponse": RELANCER_TEL,
                 "options": list(OUTILS_DE_LA_DECISION)}
            )  # fmt: skip
    ancien = bloquer(atelier, "B")
    assert ancien["id"] == "B-3" and diagnostic_rendu(atelier)
    (vieux,) = reglages_d_outils(atelier)
    atelier.decider(ancien["id"], ABANDONNER)  # B abandonnée, le réglage laissé sans réponse
    with atelier.moteur.verrou:
        atelier.moteur.chantier.termine = True  # A vérifiée, B abandonnée : chantier terminé

    nouveau_plan = {"objectif": "Suite", "taches": [{"id": "B", "titre": "Encore B",
                                                      "perimetre": ["b.py"]}]}  # fmt: skip
    atelier._adopter(nouveau_plan, "Suite")

    assert atelier.moteur.chantier.demandes == [vieux]  # gardé, mais délié
    assert "pour_blocage" not in vieux and DEBLOQUE not in vieux["question"]
    assert vieux["question"] == (
        "L'orchestrateur propose de régler les outils du projet. Commandes permises aux agents : "
        "uv. Pourquoi : Les tests se lancent avec uv."
    )
    # Le réglage des contrôles à la validation, puis un nouveau blocage qui reprend « B-3 ».
    atelier._proposer_outils({"commandes_permises": ["make"]})
    with atelier.moteur.verrou:
        atelier.moteur.chantier.contrat.valide = True
    nouveau = bloquer(atelier, "B")
    assert nouveau["id"] == ancien["id"] == "B-3"
    assert diagnostic_rendu(atelier, 2)
    (lie,) = [d for d in reglages_d_outils(atelier) if d.get("pour_blocage")]
    assert lie["id"] not in {vieux["id"], "outils-2"}  # deux demandes ne se confondent pas

    atelier.decider(vieux["id"], ACCEPTER_OUTILS)  # l'ancienne demande ne relance rien

    assert vieux["reponse"] == ACCEPTER_OUTILS and nouveau["reponse"] is None
    assert atelier.moteur.chantier.tache("B").etat == "revenu" and not atelier.en_marche()
    assert textes_du_fil(atelier)[-1].endswith(
        "Une tâche revenue vers toi peut maintenant être relancée."
    )

    atelier.decider(lie["id"], ACCEPTER_OUTILS)  # celle du nouveau blocage, si
    assert nouveau["reponse"] == RELANCER_TEL
    assert attendre(lambda: atelier.moteur.chantier.tache("B").etat == "verifie")


@pytest.mark.parametrize(
    "alteration",
    [
        {"reglage": "outils-99"},  # le blocage désigne une autre demande d'outils
        {"diagnostic": "sans_proposition"},  # son diagnostic n'a rien proposé
        {"diagnostic": "interrompu"},
    ],
)
def test_une_demande_d_outils_ne_relance_que_le_blocage_qui_l_a_fait_naitre(tmp_path, alteration):
    atelier, chemin, controles, demande, reglage = bloque_avec_reglage(tmp_path, '{"nom": "Café"}')
    with atelier.moteur.verrou:  # même identifiant, mais ce blocage n'a pas fait naître le réglage
        demande.update(alteration)

    atelier.decider(reglage["id"], ACCEPTER_OUTILS)

    assert demande["reponse"] is None and atelier.moteur.chantier.tache("B").etat == "revenu"
    assert not atelier.en_marche()
    assert textes_du_fil(atelier)[-1] == (
        "Outils réglés. Commandes permises aux agents : python3, uv. Je ne relance rien : le "
        "blocage n'attend plus ta réponse."
    )
