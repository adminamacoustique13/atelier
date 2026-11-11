"""Le serveur : autorisations, suivi de l'activité et arrêt, en mode simulé.

Aucun appel réel : des agents simulés, un guichet de l'atelier, et le vrai serveur HTTP sur
127.0.0.1. Chaque attente est bornée.
"""

import json
import sys
import threading
import time
import urllib.error
import urllib.request
from argparse import Namespace

import pytest

from atelier.__main__ import commande_instantanes, projet_simule
from atelier.agents import AgentClaude, AgentSimule, Resultat
from atelier.controles import ControlesSimules
from atelier.guichet import Guichet
from atelier.modele import Chantier, Contrat, Tache
from atelier.moteur import Moteur
from atelier.projets import Projets
from atelier.serveur import (
    ACCEPTER_OUTILS,
    Activite,
    Atelier,
    creer_serveur,
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
    assert set(demande) == {"id", "agent", "outil", "phrase", "regle", "detail"}
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
        "phrase": "Ce choix n'existe pas : réponds « une fois », « toujours » ou « non ».",
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
    assert agent == {
        "nom": "A-ouvrier-1",
        "tache": "A",
        "role": "ouvrier",
        "lignes": ["Lit la consigne"],
    }
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
    agent = AgentSimule({"A": ["bacle", "ok"]})
    moteur = moteur_de([tache("A")], agent=agent, controles=controles)
    controles.moteur = moteur
    moteur.executer()
    t = moteur.chantier.tache("A")
    assert [h["issue"] for h in t.historique] == ["bacle", "arretee"]
    assert [h["tentative"] for h in t.historique] == [1, 2]
    assert [a["role"] for a in agent.appels] == ["ouvrier", "verificateur"]
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
    # Le coût du tour arrêté est compté (celui d'un ouvrier simulé haiku : 0,02).
    attendu = {"ouvrier": 0.5, "verificateur": 0.52}[role]
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
