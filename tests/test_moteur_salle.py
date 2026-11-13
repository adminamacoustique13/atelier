"""Ce que le moteur donne à la Salle du tableau de bord pour chaque tâche (fiche S1) : la place
et le jeton tenus, ce qu'attend une tâche à lancer, l'ouvrier resté ouvert, la sous-tâche.

Les états en cours de route sont lus depuis l'agent simulé, au moment où il travaille : le moteur
est alors arrêté sur lui, rien n'attend une durée.
"""

import pytest

from atelier.agents import AgentSimule
from atelier.controles import ControlesSimules
from atelier.moteur import ATTENTES, Moteur
from atelier.places import Places
from tests.test_moteur import chantier, tache
from tests.test_serveur import atelier_simule


class Temoin(AgentSimule):
    """L'agent simulé, qui note ce que dit `Moteur.salle()` à chacun de ses appels."""

    def __init__(self, **champs):
        super().__init__(**champs)
        self.moteur, self.vues = None, []

    def executer(self, consigne, modele, effort, dossier, lecture_seule=False, contexte=None,
                 copie_jetable=False, reprendre=None, garder_ouvert=False):  # fmt: skip
        if self.moteur is not None:
            self.vues.append((contexte.get("tache"), contexte.get("role"), self.moteur.salle()))
        return super().executer(consigne, modele, effort, dossier, lecture_seule, contexte,
                                copie_jetable, reprendre, garder_ouvert)  # fmt: skip


def monter(taches, profil=None):
    c = chantier(taches)
    agent = Temoin(perimetres={t.id: t.perimetre for t in c.taches})
    m = Moteur(c, agent, ControlesSimules(), profil)
    agent.moteur = m
    return c, m, agent


def vue_pendant(agent, tache_, role):
    return next(salle for t, r, salle in agent.vues if (t, r) == (tache_, role))


# --- la place et le jeton ---------------------------------------------------------------------


def test_une_tache_tient_sa_place_et_son_jeton_pendant_que_son_ouvrier_travaille():
    c, m, agent = monter([tache("A", type="courante")])
    assert m.salle()["A"]["place"] is False and m.salle()["A"]["jeton"] is False
    m.executer()
    pendant = vue_pendant(agent, "A", "ouvrier")["A"]
    assert pendant["place"] is True and pendant["jeton"] is True and pendant["attend"] == ""
    assert vue_pendant(agent, "A", "verificateur")["A"]["jeton"] is True
    apres = m.salle()["A"]
    assert apres["place"] is False and apres["jeton"] is False


def test_les_places_disent_ce_que_tient_une_tache():
    places = Places(2, 3)
    assert places.tient("A") == (False, False)
    assert places.partir("A", "sonnet", 0.0) is True
    assert places.tient("A") == (True, True) and places.tient("B") == (False, False)
    places.finir("A", 1.0)
    assert places.tient("A") == (False, False)


# --- ce qu'attend une tâche à lancer ------------------------------------------------------------


def test_avant_le_lancement_une_tache_prete_attend_le_depart_du_chantier():
    c, m, _ = monter([tache("A")])
    assert m.salle()["A"] == {
        "place": False, "jeton": False, "attend": "depart", "attend_de": [],
        "attend_fr": "Partira quand le chantier sera lancé.", "ouvrier_ouvert": False,
        "sous_tache": "",
    }  # fmt: skip


def test_une_tache_attend_les_taches_dont_elle_depend_tant_qu_elles_ne_sont_pas_verifiees():
    c, m, agent = monter([tache("A"), tache("B", depend_de=["A"])])
    avant = m.salle()["B"]
    assert (avant["attend"], avant["attend_de"]) == ("dependance", ["A"])
    assert avant["attend_fr"] == "Attend A, à vérifier d'abord."
    m.executer()
    assert vue_pendant(agent, "A", "ouvrier")["B"]["attend"] == "dependance"
    assert vue_pendant(agent, "B", "ouvrier")["B"]["attend"] == ""  # A vérifiée, B est partie


def test_une_tache_attend_celle_qui_ecrit_dans_son_perimetre():
    c, m, agent = monter([tache("A"), tache("B", perimetre=["a.py"])])
    m.executer()
    b = vue_pendant(agent, "A", "ouvrier")["B"]
    assert (b["attend"], b["attend_de"]) == ("perimetre", ["A"])
    assert b["attend_fr"] == "Attend A : même périmètre, une seule tâche y écrit à la fois."


def test_une_tache_attend_une_place_quand_elles_sont_toutes_prises():
    c, m, agent = monter([tache("A"), tache("B")], {"paralleles": 1})
    m.executer()
    b = vue_pendant(agent, "A", "ouvrier")["B"]
    assert (b["attend"], b["attend_de"]) == ("place", [])
    assert c.tache("B").etat == "verifie"  # elle est partie ensuite


def test_une_tache_en_pause_apres_une_panne_le_dit():
    c, m, _ = monter([tache("A")])
    heure = m.heure()
    with m.verrou:
        m.places.pause("A", heure + 300, heure)
    assert m.salle()["A"]["attend"] == "pause"


def test_une_tache_suspendue_pour_limite_le_dit():
    c, m, _ = monter([tache("A"), tache("B")])
    heure = m.heure()
    with m.verrou:
        m.places.refus("A", "five_hour", heure + 600, heure)
    assert {p["attend"] for p in m.salle().values()} == {"limite"}


def test_seule_une_tache_a_lancer_dit_ce_qu_elle_attend():
    c, m, _ = monter([tache("A", etat="verifie"), tache("B", etat="revenu", depend_de=["Z"])])
    assert [p["attend"] for p in m.salle().values()] == ["", ""]


@pytest.mark.parametrize(
    "noms, phrase",
    [
        (["A"], "Attend A, à vérifier d'abord."),
        (["A", "B"], "Attend A et B, à vérifier d'abord."),
        (["A", "B", "C"], "Attend A, B et C, à vérifier d'abord."),
    ],
)
def test_la_phrase_nomme_toutes_les_taches_attendues(noms, phrase):
    taches = [tache(n) for n in noms] + [tache("Z", depend_de=noms)]
    assert monter(taches)[1].salle()["Z"]["attend_fr"] == phrase


def test_chaque_attente_a_sa_phrase():
    assert set(ATTENTES) == {"", "dependance", "perimetre", "pause", "limite", "depart", "place"}
    assert all(phrase.endswith(".") for cle, phrase in ATTENTES.items() if cle)


# --- l'ouvrier resté ouvert, la sous-tâche ------------------------------------------------------


def test_l_agent_simule_dit_quels_ouvriers_sont_restes_ouverts():
    agent = AgentSimule(perimetres={"A": ["a.py"]}, garde_les_ouvriers=True)
    contexte = {"role": "ouvrier", "tache": "A", "tentative": 1}
    assert agent.ouvriers_ouverts() == []
    resultat = agent.executer("Fais.", "sonnet", "low", None, contexte=contexte, garder_ouvert=True)
    assert resultat.ouverte is True and agent.ouvriers_ouverts() == ["A"]
    agent.liberer("A")
    assert agent.ouvriers_ouverts() == []


def test_la_salle_signale_l_ouvrier_reste_ouvert():
    c, m, agent = monter([tache("A"), tache("B")])
    agent.ouvriers_ouverts = lambda: ["A"]
    salle = m.salle()
    assert salle["A"]["ouvrier_ouvert"] is True and salle["B"]["ouvrier_ouvert"] is False


def test_un_agent_qui_ne_dit_rien_ou_repond_mal_ne_fait_pas_tomber_la_salle():
    class Muet:
        pass

    c = chantier([tache("A")])
    assert Moteur(c, Muet(), ControlesSimules()).salle()["A"]["ouvrier_ouvert"] is False

    def casse():
        raise RuntimeError("agent indisponible")

    c2, m2, agent = monter([tache("A")])
    agent.ouvriers_ouverts = casse
    assert m2.salle()["A"]["ouvrier_ouvert"] is False


def test_la_salle_nomme_la_sous_tache_en_cours():
    a = tache("A", copie="/quelque/part", reste={"genre": "verdict", "points": ["x"],
                                                  "en_cours": "A-a"})  # fmt: skip
    assert monter([a, tache("B")])[1].salle()["A"]["sous_tache"] == "A-a"
    assert monter([tache("B")])[1].salle()["B"]["sous_tache"] == ""


def test_lire_la_salle_ne_change_ni_les_places_ni_le_fil():
    c, m, _ = monter([tache("A"), tache("B", depend_de=["A"])])
    avant = (m.places.etat(m.heure()), list(c.evenements), [t.etat for t in c.taches])
    m.salle()
    m.salle()
    assert (m.places.etat(m.heure()), list(c.evenements), [t.etat for t in c.taches]) == avant


# --- dans la vue de l'atelier -------------------------------------------------------------------


def test_la_vue_de_l_atelier_porte_la_salle_de_chaque_tache(tmp_path):
    atelier = atelier_simule(tmp_path, [tache("A"), tache("B", depend_de=["A"])])
    salle = atelier.vue()["salle"]
    assert set(salle) == {"A", "B"}
    assert salle["A"]["attend"] == "depart" and salle["B"]["attend_de"] == ["A"]
