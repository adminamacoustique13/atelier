"""Épreuves d'ensemble de la fiche M14 : trois parcours entiers, sur un vrai dépôt git.

Chaque épreuve traverse plusieurs règles du moteur à la fois, là où les autres fichiers de tests
les prouvent une par une : l'arrêt de l'Atelier en pleine vérification puis la reprise seule ; un
verdict « local », sa sous-tâche, la retouche vérifiée et l'entrée dans la branche ; un contrôle
rouge rendu à l'ouvrier resté ouvert, sous un budget. Les agents sont simulés, rien n'est appelé.
"""

import pytest

from atelier.agents import AgentSimule
from atelier.modele import Chantier
from atelier.moteur import INTERROMPUE, NATURE_BUDGET, RELANCER_TEL, Moteur
from atelier.serveur import Atelier, prendre_le_depot
from tests.test_moteur_garde import (
    PASSES,
    Controles,
    Ouvrier,
    assert_aucune_copie,
    chantier,
    depot,  # noqa: F401  (le dépôt git de chaque épreuve)
    fil,
    lignes_dans_la_principale,
    tache,
)
from tests.test_moteur_sous_tache import LOCAL, POINT, OuvrierDose, sous_taches
from tests.test_reprise_seule import finir, relu, sans_attendre, serveur  # noqa: F401

pytestmark = pytest.mark.montee_sur_le_fond  # la règle du produit sans réglage

RETOUCHE = "Tu es vérificateur. Un autre agent a corrigé son livrable après un refus"
DEUX_PASSES = f'n=$(grep -c passe {PASSES}); echo "lignes : $n"; test "$n" -ge 2'


def roles(agent):
    return [x.get("role") for x in agent.appels]


# --- 1. arrêt en vérification puis relance : rejugé sans ouvrier ---------------------------


def test_arretee_en_verification_puis_relancee_la_tache_est_rejugee_sans_ouvrier(depot, serveur):  # noqa: F811
    controles = Controles(depot)
    # Ce que l'Atelier avait écrit avant de s'arrêter : l'ouvrier a rendu, la vérification court.
    t = tache(etat="en_verification", tentatives=1, modele="sonnet", effort="low")
    copie = controles.preparer(t)
    (copie / PASSES).write_text("passe 0\n", "utf-8")
    (copie / "a.py").write_text("# fait\n", "utf-8")
    t.copie = str(copie)
    controles.preparees.clear()
    c = relu(chantier([t]))  # relu sur le disque à la réouverture

    agent = Ouvrier(chantier=c)
    a = Atelier(depot, c, agent, controles, {}, mode="réel")
    a.verrou_depot = prendre_le_depot(depot)
    relue = c.tache("A")
    assert relue.etat == "a_lancer" and relue.tentatives == 1  # le numéro est gardé
    assert relue.historique[-1]["issue"] == INTERROMPUE
    assert relue.historique[-1]["pendant"] == "verification"

    assert a.reprendre_apres_arret(serveur, sans_attendre()) == ["A"]
    finir(a)

    assert roles(agent) == ["verificateur"]  # aucun ouvrier : seul le jugement est refait
    assert relue.etat == "verifie" and relue.tentatives == 1
    assert controles.preparees == [] and lignes_dans_la_principale(depot) == ["passe 0"]
    assert (depot / "a.py").read_text("utf-8") == "# fait\n"
    assert_aucune_copie(depot, relue)
    sur_disque = Chantier.charger(depot / ".atelier" / "etat.json")
    assert sur_disque.tache("A").etat == "verifie"


# --- 2. verdict « local », sous-tâche, retouche vérifiée, entrée ---------------------------


class OuvrierJuge(OuvrierDose):
    """L'ouvrier dosé, qui garde en plus la consigne de chaque vérificateur."""

    def __init__(self, *arguments, **champs):
        super().__init__(*arguments, **champs)
        self.jugements = []

    def executer(self, consigne, modele, effort, dossier, lecture_seule=False, contexte=None,
                 copie_jetable=False, reprendre=None):  # fmt: skip
        if contexte.get("role") == "verificateur":
            self.jugements.append(consigne)
        return super().executer(consigne, modele, effort, dossier, lecture_seule, contexte,
                                copie_jetable, reprendre)  # fmt: skip


class OuvrierOuvert(Ouvrier):
    """L'ouvrier de `test_moteur_garde`, qui sait rester ouvert après avoir rendu la main : le
    moteur le lui demande (`garder_ouvert`), et la suite lui revient dans sa session."""

    def __init__(self, **champs):
        super().__init__(garde_les_ouvriers=True, **champs)

    def executer(self, consigne, modele, effort, dossier, lecture_seule=False, contexte=None,
                 copie_jetable=False, reprendre=None, garder_ouvert=False):  # fmt: skip
        if contexte.get("role") == "ouvrier":
            self._passer(consigne, dossier, contexte, reprendre)
        return AgentSimule.executer(self, consigne, modele, effort, dossier, lecture_seule,
                                    contexte, copie_jetable, reprendre, garder_ouvert)  # fmt: skip


def test_un_verdict_local_mene_a_une_sous_tache_puis_a_une_retouche_verifiee_et_a_l_entree(depot):  # noqa: F811
    c = chantier([tache()])
    agent = OuvrierJuge({"A": ["bacle", "ok"]}, {1: LOCAL}, chantier=c, en_trop={3: "b.py"})
    controles = Controles(depot)
    Moteur(c, agent, controles).executer()
    a = c.tache("A")

    assert a.etat == "verifie" and a.tentatives == 1 and a.sous_taches == 1
    depart, retour, sous = agent.passages
    assert not depart["reprise"] and retour["reprise"] and not sous["reprise"]
    assert "## Sous-tâche A-a, de la tâche A" in sous["consigne"] and POINT in sous["consigne"]
    assert sous["dossier"] == depart["dossier"] and controles.preparees == ["A"]  # travail gardé
    assert sous["trouve"] == "passe 1\npasse 2\n"
    # Trois jugements : le travail entier, sa correction, puis la retouche de la sous-tâche.
    premier, correction, retouche = agent.jugements
    assert not premier.startswith(RETOUCHE)
    assert correction.startswith(RETOUCHE) and retouche.startswith(RETOUCHE)
    assert POINT in retouche  # le verdict précédent, en entier, borne ce qu'il regarde
    assert sous_taches(a) == ["", "", "A-a"]
    assert [e["issue"] for e in a.historique] == ["local", "local", "valide"]
    assert lignes_dans_la_principale(depot) == ["passe 1", "passe 2", "passe 3"]
    assert (depot / "b.py").exists()  # le fichier nommé par le vérificateur est entré aussi
    assert c.demandes == [] and c.montees == 0
    assert any(t.startswith("Sous-tâche A-a lancée") for t in fil(c))
    assert_aucune_copie(depot, a)


# --- 3. contrôle rouge rendu à l'ouvrier ouvert, sous budget -------------------------------


def ouvert_sous_budget(depot, budget):  # noqa: F811
    c = chantier([tache()])
    agent = OuvrierOuvert(chantier=c)
    controles = Controles(depot, [DEUX_PASSES])
    profil = {"commandes": [DEUX_PASSES], "budget_usd": budget}
    return c, Moteur(c, agent, controles, profil), agent, controles


def test_un_controle_rouge_revient_a_l_ouvrier_ouvert_sans_nouveau_depart(depot):  # noqa: F811
    c, m, agent, controles = ouvert_sous_budget(depot, 5.0)
    m.executer()
    a = c.tache("A")
    assert a.etat == "verifie" and a.tentatives == 1 and a.sous_taches == 0
    depart, retour = agent.passages
    assert retour["reprise"] and retour["dossier"] == depart["dossier"]
    assert len(agent.suivis) == 1  # la suite est allée à l'ouvrier resté ouvert, pas à un neuf
    assert "lignes : 1" in agent.suivis[0]["message"]  # il reçoit la sortie du contrôle rouge
    assert agent.fermes == [depart_session(agent)]  # libéré une fois la tâche finie
    assert 0 < c.cout_usd < 5.0 and c.contrat.max_cout_usd == 5.0
    assert c.demandes == []
    assert lignes_dans_la_principale(depot) == ["passe 1", "passe 2"]
    assert_aucune_copie(depot, a)


def depart_session(agent):
    return agent.suivis[0]["session"]


def test_budget_atteint_le_controle_rouge_ne_revient_pas_et_la_tache_revient_travail_garde(depot):  # noqa: F811
    c, m, agent, controles = ouvert_sous_budget(depot, 0.05)  # moins que le premier ouvrier
    m.executer()
    a = c.tache("A")
    assert a.etat == "revenu" and a.copie  # le travail reste dans sa copie
    assert len(agent.passages) == 1 and agent.suivis == []  # ni retour ni nouveau départ
    (demande,) = c.demandes
    assert demande["nature"] == NATURE_BUDGET
    assert "Travail gardé" in demande["question"]
    avant = c.contrat.max_cout_usd

    m.repondre(demande["id"], RELANCER_TEL)  # la relance accorde un cinquième de plus
    assert c.contrat.max_cout_usd > avant and c.contrat.max_cout_usd > c.cout_usd
    m.executer()
    assert a.etat == "verifie"
    suite = agent.passages[1]
    assert suite["dossier"] == agent.passages[0]["dossier"] and suite["trouve"] == "passe 1\n"
    assert "## Sous-tâche A-a" in suite["consigne"]  # elle ne règle que le contrôle rouge
    assert lignes_dans_la_principale(depot) == ["passe 1", "passe 2"]
    assert_aucune_copie(depot, a)
