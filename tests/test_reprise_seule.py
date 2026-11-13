"""La reprise seule après un arrêt de l'Atelier (M7).

Au chargement, une tâche laissée « en cours » ou « en vérification » redevient « à lancer », avec
une entrée `interrompue`, sans que rien ne parte. Seul le serveur la relance : contrat validé,
port pris, verrou du dépôt tenu, annonce au fil, puis délai. Jamais deux Ateliers sur le même
dépôt, jamais de relance sans contrat validé, jamais de boucle.
"""

import json
import subprocess
import sys
import threading
from argparse import Namespace
from pathlib import Path

import pytest

from atelier import __main__ as principal
from atelier.agents import AgentSimule
from atelier.controles import ControlesSimules
from atelier.modele import Chantier, Contrat, Tache
from atelier.moteur import (
    ARRETEE,
    DETAIL_INTERROMPUE,
    INTERROMPUE,
    INTERRUPTIONS_MAX,
    MOTIF_REPRISE_ANNULEE,
    MOTIF_TROP_D_ARRETS,
    PANNE,
    REPRISE_APRES_ARRET_S,
    Moteur,
)
from atelier.projets import Projets
from atelier.serveur import (
    Atelier,
    DepotOccupe,
    SuiviMiseAJour,
    VerrouDepot,
    creer_serveur,
    depot_verrouille,
    phrase_de_reprise,
    port_pris,
    prendre_le_depot,
)

RACINE = Path(__file__).resolve().parent.parent  # pour qu'un second processus importe l'Atelier
ANNULEE = "Reprise annulée : aucune tâche n'est repartie seule."
RELANCE = "Reprise après l'arrêt : je relance le chantier"


def chantier(taches, valide=True):
    return Chantier(projet="Essai", contrat=Contrat(objectif="Essai", valide=valide), taches=taches)


def tache(identifiant, **champs):
    champs.setdefault("perimetre", [f"{identifiant.lower()}.py"])
    champs.setdefault("modele", "sonnet")
    champs.setdefault("effort", "low")
    return Tache(id=identifiant, titre=f"Tâche {identifiant}", **champs)


def relu(c):
    """Le chantier tel qu'il serait relu sur le disque après un arrêt."""
    return Chantier.depuis_dict(json.loads(json.dumps(c.en_dict())))


def agent_pour(c, classe=AgentSimule):
    return classe(perimetres={t.id: t.perimetre for t in c.taches})


def textes(c):
    return [e["texte"] for e in c.evenements]


def interrompue(tentative):
    return {"tentative": tentative, "modele": "sonnet", "effort": "low", "issue": INTERROMPUE}


def sans_attendre(delais=None):
    """Une attente qui n'attend pas : elle note le délai demandé et dit si la reprise est
    annulée."""

    def attendre(delai_s, annulee):
        if delais is not None:
            delais.append(delai_s)
        return annulee.is_set()

    return attendre


def atelier_sur(depot, c, profil=None, mode="réel", verrouille=True, agent=None):
    """Un Atelier qui relit `c` comme après un arrêt, avec des agents simulés, et qui tient le
    verrou du dépôt comme le fait la fabrique de « servir »."""
    c = relu(c)
    depot.mkdir(parents=True, exist_ok=True)
    a = Atelier(depot, c, agent or agent_pour(c), ControlesSimules(), profil or {}, mode=mode)
    if verrouille:
        a.verrou_depot = prendre_le_depot(depot)
    return a


def finir(a):
    """Attend la fin du fil de la reprise, puis celle du moteur s'il est parti."""
    if a.fil_reprise is not None:
        a.fil_reprise.join(10)
        assert not a.fil_reprise.is_alive()
    if a.fil is not None:
        a.fil.join(10)
        assert not a.fil.is_alive()


def compter_les_tours(moteur):
    """Compte les boucles d'`executer` qui prennent vraiment la route."""
    tours, mener = [], moteur._mener

    def compte():
        tours.append(1)
        return mener()

    moteur._mener = compte
    return tours


@pytest.fixture
def serveur(tmp_path):
    """Un vrai serveur du tableau de bord, qui a pris un port libre de 127.0.0.1."""
    s = creer_serveur(Projets(tmp_path, None), 0)
    yield s
    s.server_close()


# --- au chargement : le moteur change l'état, il ne lance rien -----------------------------------


def test_une_tache_en_cours_interrompue_redevient_a_lancer_et_rend_son_numero():
    c = relu(chantier([tache("A", etat="en_cours", tentatives=2), tache("B", depend_de=["A"])]))
    agent = agent_pour(c)

    m = Moteur(c, agent, ControlesSimules())

    a = c.tache("A")
    assert a.etat == "a_lancer" and a.tentatives == 1  # la tentative coupée ne compte pas
    (entree,) = a.historique
    assert entree["issue"] == INTERROMPUE and entree["tentative"] == 2
    assert entree["detail"] == DETAIL_INTERROMPUE and "pendant" not in entree
    assert c.demandes == [] and agent.appels == [] and c.agents_lances == 0
    assert not m.en_route and m.taches_interrompues() == ["A"]

    m.executer()  # quand le serveur la relance, elle reprend le numéro rendu
    assert a.etat == "verifie" and a.tentatives == 2
    assert [(e["tentative"], e["issue"]) for e in a.historique] == [
        (2, INTERROMPUE),
        (2, "valide"),
    ]


def test_une_tache_en_verification_avec_sa_copie_garde_son_numero():
    c = relu(chantier([tache("A", etat="en_verification", tentatives=2, copie="/copies/A")]))

    Moteur(c, agent_pour(c), ControlesSimules())

    a = c.tache("A")
    assert a.etat == "a_lancer" and a.tentatives == 2 and a.copie == "/copies/A"
    (entree,) = a.historique
    assert entree["issue"] == INTERROMPUE and entree["tentative"] == 2
    assert entree["pendant"] == "verification"
    assert c.demandes == []


def test_une_tache_en_verification_sans_copie_rend_son_numero():
    c = relu(chantier([tache("A", etat="en_verification", tentatives=1)]))

    Moteur(c, agent_pour(c), ControlesSimules())

    a = c.tache("A")
    assert a.etat == "a_lancer" and a.tentatives == 0
    (entree,) = a.historique
    assert entree["issue"] == INTERROMPUE and "pendant" not in entree


def test_la_quatrieme_interruption_rend_la_tache_a_la_personne():
    deja = [interrompue(1) for _ in range(INTERRUPTIONS_MAX - 1)]
    troisieme = relu(chantier([tache("A", etat="en_cours", tentatives=1, historique=deja)]))
    Moteur(troisieme, agent_pour(troisieme), ControlesSimules())
    assert troisieme.tache("A").etat == "a_lancer"  # trois interruptions : elle repart encore

    deja = [interrompue(1) for _ in range(INTERRUPTIONS_MAX)]
    c = relu(chantier([tache("A", etat="en_cours", tentatives=1, historique=deja)]))
    agent = agent_pour(c)
    m = Moteur(c, agent, ControlesSimules())

    a = c.tache("A")
    assert a.etat == "revenu" and a.tentatives == 1
    assert [e["issue"] for e in a.historique] == [INTERROMPUE] * INTERRUPTIONS_MAX + [PANNE]
    (demande,) = c.demandes
    assert demande["question"].endswith(MOTIF_TROP_D_ARRETS)
    assert "4 fois" in demande["question"] and "boucle" in demande["question"]
    assert m.taches_interrompues() == [] and agent.appels == []


def test_avec_reprise_auto_false_la_tache_revient_a_la_personne(tmp_path, serveur):
    c = chantier([tache("A", etat="en_cours", tentatives=1)])
    delais = []

    a = atelier_sur(tmp_path, c, {"reprise_auto": False})

    t = a.moteur.chantier.tache("A")
    assert t.etat == "revenu" and t.historique[-1]["issue"] == PANNE
    assert "s'est arrêté" in a.moteur.chantier.demandes[0]["question"]
    assert a.reprendre_apres_arret(serveur, sans_attendre(delais)) == []
    assert delais == [] and a.fil_reprise is None and not a.en_marche()


@pytest.mark.parametrize("valeur", ["non", "false", 0, None, [], {}])
def test_une_valeur_de_reprise_auto_qui_n_est_pas_un_booleen_vaut_vrai(valeur):
    c = relu(chantier([tache("A", etat="en_cours", tentatives=1)]))
    m = Moteur(c, agent_pour(c), ControlesSimules(), {"reprise_auto": valeur})
    assert m.reprise_auto() is True and c.tache("A").etat == "a_lancer"


@pytest.mark.parametrize(
    ("profil", "attendu"),
    [
        ({}, 30.0),
        ({"reprise_apres_arret_s": 0}, 0.0),
        ({"reprise_apres_arret_s": 12.5}, 12.5),
        ({"reprise_apres_arret_s": "10"}, 30.0),
        ({"reprise_apres_arret_s": -1}, 30.0),
        ({"reprise_apres_arret_s": True}, 30.0),
        ({"reprise_apres_arret_s": float("nan")}, 30.0),
        ({"reprise_apres_arret_s": float("inf")}, 30.0),
        ({"reprise_apres_arret_s": None}, 30.0),
    ],
)
def test_le_delai_de_reprise_se_lit_au_profil_et_vaut_trente_s_s_il_est_mal_forme(profil, attendu):
    m = Moteur(chantier([]), AgentSimule(), ControlesSimules(), profil)
    assert m.delai_de_reprise() == attendu
    assert REPRISE_APRES_ARRET_S == 30


def test_un_second_chargement_n_interrompt_pas_une_seconde_fois():
    c = relu(chantier([tache("A", etat="en_cours", tentatives=2)]))
    Moteur(c, agent_pour(c), ControlesSimules())
    m = Moteur(c, agent_pour(c), ControlesSimules())  # comme un arrêt pendant le délai
    a = c.tache("A")
    assert a.tentatives == 1 and [e["issue"] for e in a.historique] == [INTERROMPUE]
    assert m.taches_interrompues() == ["A"]  # elle attend toujours sa reprise


# --- la relance par le serveur ------------------------------------------------------------------


def test_la_relance_part_apres_l_annonce_et_le_delai(tmp_path, serveur):
    c = chantier(
        [
            tache("A", etat="en_cours", tentatives=1),
            tache("B", depend_de=["A"]),
            tache("D", etat="verifie"),
        ]
    )
    a = atelier_sur(tmp_path, c)
    fil_pendant_le_delai, delais = [], []

    def attendre(delai_s, annulee):
        delais.append(delai_s)
        fil_pendant_le_delai.extend(textes(a.moteur.chantier))
        assert a.moteur.chantier.agents_lances == 0  # rien n'est parti pendant le délai
        return annulee.is_set()

    assert a.reprendre_apres_arret(serveur, attendre) == ["A"]
    finir(a)

    annonce = phrase_de_reprise(["A"], 30)
    assert delais == [30.0] and fil_pendant_le_delai[-1] == annonce
    assert "1 tâche (A) repart seule" in annonce and "dans 30 secondes" in annonce
    fil = textes(a.moteur.chantier)
    assert fil.index(annonce) < fil.index(f"{RELANCE} (A).")
    assert all(t.etat == "verifie" for t in a.moteur.chantier.taches)
    sur_disque = Chantier.charger(tmp_path / ".atelier" / "etat.json")
    assert annonce in textes(sur_disque)


def test_une_tache_revenue_bloquee_ou_arretee_avant_l_arret_ne_repart_jamais(tmp_path, serveur):
    arretee = {"tentative": 1, "issue": ARRETEE, "detail": "Arrêtée par la personne responsable."}
    c = chantier(
        [
            tache("R", etat="revenu", tentatives=3, historique=[interrompue(3)]),
            tache("K", etat="revenu", tentatives=1),
            tache("S", etat="revenu", tentatives=1, historique=[arretee]),
            tache("B", etat="en_cours", tentatives=1),
        ]
    )
    c.demandes = [
        {"id": f"{i}-1", "tache": i, "question": "?", "options": [], "reponse": None}
        for i in ("R", "K", "S")
    ]
    c.demandes[1]["nature"] = "blocage"
    a = atelier_sur(tmp_path, c)

    assert a.moteur.taches_interrompues() == ["B"]
    assert a.reprendre_apres_arret(serveur, sans_attendre()) == ["B"]
    finir(a)

    etats = {t.id: t.etat for t in a.moteur.chantier.taches}
    assert etats == {"R": "revenu", "K": "revenu", "S": "revenu", "B": "verifie"}
    assert {x["tache"] for x in a.moteur.agent.appels} == {"B"}
    assert all(d["reponse"] is None for d in a.moteur.chantier.demandes)


def test_sans_contrat_valide_rien_ne_repart(tmp_path, serveur):
    a = atelier_sur(tmp_path, chantier([tache("A", etat="en_cours", tentatives=1)], valide=False))
    delais = []

    assert a.reprendre_apres_arret(serveur, sans_attendre(delais)) == []

    finir(a)
    assert delais == [] and a.fil_reprise is None and a.fil is None
    assert a.moteur.chantier.agents_lances == 0
    assert not any("repart" in t for t in textes(a.moteur.chantier))


def test_en_demonstration_rien_ne_repart(tmp_path, serveur):
    c = chantier([tache("A", etat="en_cours", tentatives=1)])
    a = atelier_sur(tmp_path, c, mode="démonstration")
    assert a.reprendre_apres_arret(serveur, sans_attendre()) == []
    assert a.fil_reprise is None and a.moteur.chantier.agents_lances == 0


def test_sans_port_pris_ou_sans_verrou_tenu_rien_ne_repart(tmp_path, serveur):
    c = chantier([tache("A", etat="en_cours", tentatives=1)])
    sans_verrou = atelier_sur(tmp_path / "un", c, verrouille=False)
    assert sans_verrou.reprendre_apres_arret(serveur, sans_attendre()) == []

    a = atelier_sur(tmp_path / "deux", c)
    assert a.reprendre_apres_arret(None, sans_attendre()) == []
    ferme = creer_serveur(Projets(tmp_path, None), 0)
    ferme.server_close()
    assert a.reprendre_apres_arret(ferme, sans_attendre()) == []
    a.verrou_depot.relacher()
    assert a.reprendre_apres_arret(serveur, sans_attendre()) == []
    assert a.fil_reprise is None and sans_verrou.fil_reprise is None
    assert a.moteur.chantier.agents_lances == 0


def test_le_port_pris_est_celui_d_un_serveur_ouvert_sur_127_0_0_1(tmp_path, serveur):
    assert port_pris(serveur)
    assert not port_pris(None) and not port_pris(object())
    ferme = creer_serveur(Projets(tmp_path, None), 0)
    ferme.server_close()
    assert not port_pris(ferme)


def test_un_chantier_sans_tache_interrompue_n_annonce_ni_n_attend_rien(tmp_path, serveur):
    c = chantier([tache("A"), tache("D", etat="verifie"), tache("R", etat="revenu")])
    a = atelier_sur(tmp_path, c)
    avant, delais = textes(a.moteur.chantier), []

    assert a.reprendre_apres_arret(serveur, sans_attendre(delais)) == []

    assert delais == [] and a.fil_reprise is None and a.fil is None
    assert textes(a.moteur.chantier) == avant


# --- « Arrêter » pendant le délai, double appel, clic pendant le délai, erreur ------------------


def test_arreter_pendant_le_delai_annule_la_reprise(tmp_path, serveur):
    a = atelier_sur(tmp_path, chantier([tache("A", etat="en_cours", tentatives=2)]))
    retours = []

    def attendre(delai_s, annulee):
        retours.append(a.annuler_reprise())  # la personne clique pendant le délai
        return annulee.is_set()

    assert a.reprendre_apres_arret(serveur, attendre) == ["A"]
    finir(a)

    assert retours == [{"fait": True, "phrase": ANNULEE}]
    c = a.moteur.chantier
    assert c.agents_lances == 0 and a.moteur.agent.appels == [] and a.fil is None
    t = c.tache("A")
    assert t.etat == "revenu" and t.historique[-1]["issue"] == INTERROMPUE  # travail gardé
    (demande,) = c.demandes
    assert demande["question"].endswith(MOTIF_REPRISE_ANNULEE)
    assert ANNULEE in textes(c) and not any(RELANCE in x for x in textes(c))
    assert a.annuler_reprise()["fait"] is False  # plus rien à annuler
    sur_disque = Chantier.charger(tmp_path / ".atelier" / "etat.json")
    assert sur_disque.tache("A").etat == "revenu"
    rouvert = Moteur(sur_disque, AgentSimule(), ControlesSimules())
    assert rouvert.taches_interrompues() == []  # elle ne repartira pas seule plus tard


def test_le_bouton_arreter_de_la_page_annule_la_reprise_annoncee(tmp_path, serveur):
    a = atelier_sur(tmp_path, chantier([tache("A", etat="en_cours", tentatives=2)]))
    vues, retours = [], []

    def attendre(delai_s, annulee):
        vues.append(a.vue()["reprise_en_attente"])  # la page montre alors « Arrêter »
        retours.append(a.arreter())  # le clic : la demande d'arrêt sans tâche
        return annulee.is_set()

    a.reprendre_apres_arret(serveur, attendre)
    finir(a)
    assert vues == [True] and retours == [{"fait": True, "phrase": ANNULEE}]
    assert a.vue()["reprise_en_attente"] is False
    assert a.moteur.chantier.tache("A").etat == "revenu" and a.moteur.agent.appels == []


def test_sans_reprise_annoncee_arreter_garde_son_sens_d_avant(tmp_path):
    a = atelier_sur(tmp_path, chantier([tache("A")]))
    assert a.vue()["reprise_en_attente"] is False
    assert a.arreter() == {
        "fait": False,
        "phrase": "L'orchestrateur ne répond à rien en ce moment : rien à arrêter.",
    }


def test_arreter_apres_la_relance_ne_rend_rien(tmp_path, serveur):
    a = atelier_sur(tmp_path, chantier([tache("A", etat="en_cours", tentatives=1)]))
    a.reprendre_apres_arret(serveur, sans_attendre())
    finir(a)
    assert a.annuler_reprise()["fait"] is False
    assert a.moteur.chantier.tache("A").etat == "verifie" and a.moteur.chantier.demandes == []


def test_deux_appels_de_suite_ne_lancent_qu_une_reprise(tmp_path, serveur):
    a = atelier_sur(tmp_path, chantier([tache("A", etat="en_cours", tentatives=1)]))
    tours, libre = compter_les_tours(a.moteur), threading.Event()

    def attendre(delai_s, annulee):
        assert libre.wait(5)
        return annulee.is_set()

    assert a.reprendre_apres_arret(serveur, attendre) == ["A"]
    assert a.reprendre_apres_arret(serveur, attendre) == []  # pendant le délai
    libre.set()
    finir(a)
    assert a.reprendre_apres_arret(serveur, attendre) == []  # après la relance

    fil = textes(a.moteur.chantier)
    assert sum(x.startswith("L'Atelier s'était arrêté") for x in fil) == 1
    assert sum(x.startswith(RELANCE) for x in fil) == 1
    assert tours == [1] and a.moteur.chantier.tache("A").etat == "verifie"


class AgentRetenu(AgentSimule):
    """Un agent simulé dont chaque appel attend un feu vert : le moteur reste en marche."""

    def __init__(self, *arguments, **reglages):
        super().__init__(*arguments, **reglages)
        self.parti, self.libre = threading.Event(), threading.Event()

    def executer(self, *arguments, **reglages):
        self.parti.set()
        assert self.libre.wait(5)
        return super().executer(*arguments, **reglages)


def test_un_clic_pendant_le_delai_ne_met_pas_le_moteur_en_marche_deux_fois(tmp_path, serveur):
    c = chantier(
        [  # même périmètre : B attend que A ait fini, toujours « à lancer » à la fin du délai
            tache("A", etat="en_cours", tentatives=1, perimetre=["commun.py"]),
            tache("B", etat="en_cours", tentatives=1, perimetre=["commun.py"]),
        ]
    )
    agent = agent_pour(c, AgentRetenu)
    a = atelier_sur(tmp_path, c, agent=agent)
    tours = compter_les_tours(a.moteur)

    def attendre(delai_s, annulee):
        a.lancer()  # la personne fait partir le moteur pendant le délai
        assert agent.parti.wait(5)
        return annulee.is_set()

    assert a.reprendre_apres_arret(serveur, attendre) == ["A", "B"]
    a.fil_reprise.join(10)
    fil = textes(a.moteur.chantier)
    assert "Le chantier tourne déjà : les tâches attendues (B) repartent avec lui." in fil
    assert not any(x.startswith(RELANCE) for x in fil)
    agent.libre.set()
    finir(a)
    assert tours == [1]
    assert [t.etat for t in a.moteur.chantier.taches] == ["verifie", "verifie"]


def test_une_erreur_pendant_le_delai_ne_lance_rien(tmp_path, serveur):
    a = atelier_sur(tmp_path, chantier([tache("A", etat="en_cours", tentatives=1)]))

    def attendre(delai_s, annulee):
        raise RuntimeError("horloge en panne")

    assert a.reprendre_apres_arret(serveur, attendre) == ["A"]
    finir(a)

    c = a.moteur.chantier
    assert c.agents_lances == 0 and a.fil is None and c.tache("A").etat == "revenu"
    assert any("horloge en panne" in x and "Rien n'est reparti seul." in x for x in textes(c))


def test_la_phrase_d_annonce_dit_combien_de_taches_et_dans_combien_de_secondes():
    assert phrase_de_reprise(["A"], 30) == (
        "L'Atelier s'était arrêté pendant le chantier : 1 tâche (A) repart seule dans 30 secondes."
    )
    deux = phrase_de_reprise(["A", "B"], 1)
    assert deux.endswith("2 tâches (A, B) repartent seules dans 1 seconde.")
    assert phrase_de_reprise(["A", "B"], 0).endswith("(A, B) repartent seules tout de suite.")


# --- le verrou par dépôt ------------------------------------------------------------------------


def fabrique_simulee(ouvertures):
    """Une fabrique de projet comme `ouvrir_depot`, mais avec des agents simulés."""

    def ouvrir(depot):
        ouvertures.append(depot)
        c = Chantier.charger(depot / ".atelier" / "etat.json")
        return Atelier(depot, c, agent_pour(c), ControlesSimules(), {"reprise_apres_arret_s": 0})

    return ouvrir


def test_un_second_atelier_sur_le_meme_depot_ne_touche_a_rien(tmp_path, serveur, monkeypatch):
    monkeypatch.setattr(principal.LANCEMENT, "serveur", None)
    chantier([tache("A", etat="en_cours", tentatives=1)]).sauver(tmp_path / ".atelier/etat.json")
    ouvertures = []
    premier = principal.avec_annonce(fabrique_simulee(ouvertures))(tmp_path)
    etat = tmp_path / ".atelier" / "etat.json"
    octets, moment = etat.read_bytes(), etat.stat().st_mtime_ns

    with pytest.raises(DepotOccupe) as refus:
        principal.avec_annonce(fabrique_simulee(ouvertures))(tmp_path)

    assert "un autre Atelier travaille déjà sur le projet" in str(refus.value)
    assert tmp_path.name in str(refus.value) and "je ne relance rien" in str(refus.value)
    assert ouvertures == [tmp_path]  # le second n'a même pas relu l'état
    assert etat.read_bytes() == octets and etat.stat().st_mtime_ns == moment
    assert premier.verrou_depot.tenu
    assert premier.reprendre_apres_arret(serveur, sans_attendre()) == ["A"]  # le premier, lui
    finir(premier)
    assert premier.moteur.chantier.tache("A").etat == "verifie"


def test_servir_sur_un_depot_deja_tenu_s_arrete_en_clair(tmp_path, monkeypatch):
    depot = tmp_path / "projet"
    chantier([tache("A", etat="en_cours", tentatives=1)]).sauver(depot / ".atelier/etat.json")
    etat = depot / ".atelier" / "etat.json"
    octets = etat.read_bytes()
    monkeypatch.setattr(SuiviMiseAJour, "demarrer", lambda self: None)
    monkeypatch.setattr(principal, "creer_serveur", lambda *a: pytest.fail("port pris"))

    with VerrouDepot(depot), pytest.raises(SystemExit) as sortie:
        principal.commande_servir(Namespace(depot=str(depot), racine=None, port=0))

    assert str(sortie.value).startswith("Atelier ne peut pas démarrer : un autre Atelier")
    assert etat.read_bytes() == octets


SECOND_ATELIER = """
import sys
from pathlib import Path
from atelier.__main__ import avec_annonce
from atelier.projets import ouvrir_depot
try:
    avec_annonce(ouvrir_depot)(Path(sys.argv[1]))
except Exception as erreur:
    print(type(erreur).__name__, erreur)
    sys.exit(3)
print("ouvert")
"""


def test_un_second_atelier_dans_un_vrai_second_processus_est_refuse(tmp_path, monkeypatch):
    monkeypatch.setattr(principal.LANCEMENT, "serveur", None)
    chantier([tache("A", etat="en_cours", tentatives=1)]).sauver(tmp_path / ".atelier/etat.json")
    premier = principal.avec_annonce(fabrique_simulee([]))(tmp_path)
    etat = tmp_path / ".atelier" / "etat.json"
    octets = etat.read_bytes()

    second = subprocess.run(
        [sys.executable, "-c", SECOND_ATELIER, str(tmp_path)],
        cwd=RACINE, capture_output=True, text=True, timeout=60,
    )  # fmt: skip

    assert second.returncode == 3, second.stderr
    assert second.stdout.startswith("DepotOccupe un autre Atelier travaille déjà")
    assert etat.read_bytes() == octets and premier.verrou_depot.tenu


def test_le_verrou_est_relache_a_la_fermeture_puis_repris(tmp_path):
    assert not depot_verrouille(tmp_path)
    assert not (tmp_path / ".atelier").exists()  # la question ne crée rien
    with VerrouDepot(tmp_path) as verrou:
        assert verrou.tenu and depot_verrouille(tmp_path)
        autre = VerrouDepot(tmp_path)
        assert not autre.prendre() and not autre.tenu  # même dans le même processus
        with pytest.raises(DepotOccupe):
            prendre_le_depot(tmp_path)
    assert not verrou.tenu and not depot_verrouille(tmp_path)
    assert autre.prendre() and autre.tenu and depot_verrouille(tmp_path)
    autre.relacher()
    autre.relacher()  # sans effet la seconde fois
    assert not depot_verrouille(tmp_path)


TENIR_LE_VERROU = """
import sys
from atelier.serveur import VerrouDepot
verrou = VerrouDepot(sys.argv[1])
print("pris" if verrou.prendre() else "refuse", flush=True)
sys.stdin.readline()
"""


def test_le_verrou_est_relache_par_le_systeme_a_la_mort_du_processus(tmp_path):
    enfant = subprocess.Popen(
        [sys.executable, "-c", TENIR_LE_VERROU, str(tmp_path)],
        cwd=RACINE, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
    )  # fmt: skip
    try:
        assert enfant.stdout.readline().strip() == "pris"
        assert depot_verrouille(tmp_path) and not VerrouDepot(tmp_path).prendre()
    finally:
        enfant.kill()  # tué sans rien relâcher : seul le système peut le faire
        enfant.wait(30)
        enfant.stdout.close()
        enfant.stdin.close()
    repris = VerrouDepot(tmp_path)
    assert repris.prendre()
    repris.relacher()


# --- le lancement : port d'abord, reprise ensuite ----------------------------------------------


def test_un_projet_ouvert_apres_la_prise_du_port_reprend_seul(tmp_path, serveur, monkeypatch):
    chantier([tache("A", etat="en_cours", tentatives=1)]).sauver(tmp_path / ".atelier/etat.json")
    monkeypatch.setattr(principal.LANCEMENT, "serveur", serveur)

    a = principal.avec_annonce(fabrique_simulee([]))(tmp_path)  # attente réelle, de 0 s
    finir(a)

    fil = textes(a.moteur.chantier)
    assert phrase_de_reprise(["A"], 0) in fil and f"{RELANCE} (A)." in fil
    assert a.moteur.chantier.tache("A").etat == "verifie"


def test_un_projet_ouvert_avant_la_prise_du_port_attend(tmp_path, monkeypatch):
    chantier([tache("A", etat="en_cours", tentatives=1)]).sauver(tmp_path / ".atelier/etat.json")
    monkeypatch.setattr(principal.LANCEMENT, "serveur", None)
    a = principal.avec_annonce(fabrique_simulee([]))(tmp_path)
    assert a.fil_reprise is None and a.fil is None and a.verrou_depot.tenu
    assert a.moteur.taches_interrompues() == ["A"]


def test_servir_prend_le_port_avant_de_reprendre(tmp_path, monkeypatch):
    chantier([tache("A", etat="en_cours", tentatives=1)]).sauver(tmp_path / ".atelier/etat.json")
    monkeypatch.setattr(principal.LANCEMENT, "serveur", None)
    a = principal.avec_annonce(fabrique_simulee([]))(tmp_path)
    projets = Projets(tmp_path.parent, None)
    projets.ajouter(a)
    vus, servis = [], []
    reprendre = a.reprendre_apres_arret

    def reprendre_en_notant(serveur, attendre=None):
        vus.append((port_pris(serveur), principal.LANCEMENT.serveur is serveur))
        return reprendre(serveur, attendre)

    def creer(projets, port, suivi=None):
        s = creer_serveur(projets, port, suivi)
        s.serve_forever = lambda: servis.append(list(vus))
        servis.append(s)
        return s

    a.reprendre_apres_arret = reprendre_en_notant
    monkeypatch.setattr(SuiviMiseAJour, "demarrer", lambda self: None)
    monkeypatch.setattr(principal, "monter_projets", lambda arguments: (projets, tmp_path))
    monkeypatch.setattr(principal, "creer_serveur", creer)

    principal.commande_servir(Namespace(port=0))
    finir(a)
    servis[0].server_close()

    assert vus == [(True, True)] and servis[1] == [(True, True)]  # reprise avant de servir
    assert principal.LANCEMENT.serveur is None
    assert a.moteur.chantier.tache("A").etat == "verifie"


def test_servir_sans_port_ne_reprend_rien(tmp_path, monkeypatch):
    chantier([tache("A", etat="en_cours", tentatives=1)]).sauver(tmp_path / ".atelier/etat.json")
    monkeypatch.setattr(principal.LANCEMENT, "serveur", None)
    a = principal.avec_annonce(fabrique_simulee([]))(tmp_path)
    projets = Projets(tmp_path.parent, None)
    projets.ajouter(a)

    def creer(projets, port, suivi=None):
        raise OSError(98, "Address already in use")

    monkeypatch.setattr(SuiviMiseAJour, "demarrer", lambda self: None)
    monkeypatch.setattr(principal, "monter_projets", lambda arguments: (projets, tmp_path))
    monkeypatch.setattr(principal, "creer_serveur", creer)

    with pytest.raises(SystemExit) as sortie:
        principal.commande_servir(Namespace(port=8799))

    assert "le port 8799 n'a pas pu être pris (Address already in use)" in str(sortie.value)
    assert a.fil_reprise is None and a.moteur.chantier.agents_lances == 0
    assert principal.LANCEMENT.serveur is None
