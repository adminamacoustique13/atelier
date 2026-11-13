"""Le budget du chantier en dollars.

Au-delà du budget, plus aucun ouvrier ne part : la tâche revient à la personne, travail gardé,
et la relancer accorde une rallonge d'un cinquième. Chaque agent reçoit ce qui reste comme
plafond, quand il sait le tenir. Sans budget, rien ne change.
"""

import pytest

from atelier.agents import Resultat
from atelier.moteur import COUT_INCOMPLET, NATURE_BUDGET, RELANCER_TEL, Moteur
from tests.test_moteur import chantier, tache
from tests.test_moteur_niveaux import PROFIL, Agent, Controles
from tests.test_moteur_retours import rouge

COUT = 1.0  # ce que coûte chaque agent du double


class AgentCher(Agent):
    """L'agent des tests de niveaux, dont chaque appel coûte `COUT` dollars. `sait_plafonner` :
    il accepte un plafond (`budget_usd`) et note celui qu'il reçoit. `coupes` : les rangs
    d'appels d'ouvrier coupés par leur plafond (nature « budget »). `incomplets` : les rangs
    d'appels dont le coût est dit incomplet."""

    def __init__(self, c, sait_plafonner=True, coupes=(), incomplets=(), **champs):
        super().__init__(c, **champs)
        self.plafonne_la_depense = sait_plafonner
        self.plafonds, self.coupes, self.incomplets, self.rang = [], set(coupes), set(incomplets), 0

    def executer(self, consigne, modele, effort, dossier, lecture_seule=False, contexte=None,
                 copie_jetable=False, reprendre=None, **en_plus):  # fmt: skip
        if not self.plafonne_la_depense:
            assert "budget_usd" not in en_plus  # jamais donné à qui ne sait pas le tenir
        self.plafonds.append(en_plus.get("budget_usd"))
        self.rang += 1
        resultat = super().executer(consigne, modele, effort, dossier, lecture_seule, contexte,
                                    copie_jetable, reprendre)  # fmt: skip
        resultat.cout_usd = COUT
        resultat.cout_incomplet = self.rang in self.incomplets
        if self.rang in self.coupes:
            return Resultat(ok=False, erreur="Plafond de dépense atteint.", cout_usd=COUT,
                            session=resultat.session, nature="budget")  # fmt: skip
        return resultat


def monter_cher(taches, profil=None, controles=None, contrat=None, **agent):
    c = chantier(taches, **(contrat or {}))
    a = AgentCher(c, **agent)
    profil = PROFIL if profil is None else profil
    return c, Moteur(c, a, controles or Controles(), profil), a


def budgets(c):
    return [d for d in c.demandes if d.get("nature") == NATURE_BUDGET]


def en_file():
    """Deux tâches courantes, B après A : chacune coûte un ouvrier et un vérificateur."""
    return [tache("A", type="courante"), tache("B", type="courante", depend_de=["A"])]


def test_sans_budget_rien_ne_change():
    c, m, agent = monter_cher(en_file())
    m.executer()
    assert [t.etat for t in c.taches] == ["verifie", "verifie"]
    assert budgets(c) == [] and agent.plafonds == [None] * 4 and c.cout_usd == 4 * COUT


def test_au_dela_du_budget_plus_aucun_ouvrier_ne_part_et_la_tache_revient():
    a, b = en_file()
    c, m, agent = monter_cher([a, b], {**PROFIL, "budget_usd": 1.5})
    m.executer()
    assert a.etat == "verifie"  # son vérificateur est allé au bout : le travail fait est jugé
    assert b.etat == "revenu" and b.tentatives == 0  # aucun ouvrier n'est parti pour B
    (demande,) = budgets(c)
    assert demande["tache"] == "B" and "budget du chantier est atteint" in demande["question"]
    assert "2.00 $ dépensés pour 1.50 $" in demande["question"]
    assert c.cout_usd == 2 * COUT and c.contrat.max_cout_usd == 1.5


def test_relancer_une_tache_arretee_par_le_budget_accorde_un_cinquieme():
    a, b = en_file()
    c, m, agent = monter_cher([a, b], {**PROFIL, "budget_usd": 1.5})
    m.executer()
    m.repondre(budgets(c)[0]["id"], RELANCER_TEL)
    assert c.contrat.max_cout_usd == 2.4  # un cinquième de plus que ce qui est déjà dépensé
    assert any("Budget relevé d'un cinquième" in e["texte"] for e in c.evenements)
    m.executer()
    assert b.tentatives == 1  # l'ouvrier de B est parti sous le budget relevé


def test_une_seconde_relance_ne_rallonge_pas_un_budget_deja_releve():
    taches = [tache("A", type="courante"), tache("B", type="courante", depend_de=["A"]),
              tache("C", type="courante", depend_de=["A"])]  # fmt: skip
    c, m, agent = monter_cher(taches, {**PROFIL, "budget_usd": 1.5, "paralleles": 1})
    m.executer()
    assert len(budgets(c)) == 2
    for demande in budgets(c):
        m.repondre(demande["id"], RELANCER_TEL)
    assert c.contrat.max_cout_usd == 2.4  # relevé une fois, pas deux


def test_chaque_agent_recoit_ce_qui_reste_comme_plafond():
    c, m, agent = monter_cher([tache("A", type="courante")], {**PROFIL, "budget_usd": 10})
    m.executer()
    assert agent.plafonds == [10.0, 9.0]  # l'ouvrier, puis le vérificateur


def test_un_agent_qui_ne_sait_pas_plafonner_ne_recoit_rien_mais_la_barriere_tient():
    a, b = en_file()
    c, m, agent = monter_cher([a, b], {**PROFIL, "budget_usd": 1.5}, sait_plafonner=False)
    m.executer()
    assert agent.plafonds == [None, None] and b.etat == "revenu" and len(budgets(c)) == 1


def test_un_ouvrier_coupe_par_son_plafond_ne_compte_pas_contre_la_tache():
    a = tache("A", type="courante")
    c, m, agent = monter_cher([a], {**PROFIL, "budget_usd": 5}, coupes={1})
    m.executer()
    assert a.etat == "revenu" and a.tentatives == 0 and c.montees == 0
    assert len(budgets(c)) == 1 and c.cout_usd == COUT  # ce qu'il a coûté est compté
    assert not any(e["issue"] not in ("valide",) for e in a.historique)  # aucun refus tracé


@pytest.mark.parametrize("reglage", [0, -3, "dix", True, None, [10]])
def test_un_budget_absent_ou_mal_forme_vaut_aucun_budget(reglage):
    c, m, agent = monter_cher(en_file(), {**PROFIL, "budget_usd": reglage})
    m.executer()
    assert [t.etat for t in c.taches] == ["verifie", "verifie"] and budgets(c) == []
    assert agent.plafonds == [None] * 4


def test_le_budget_du_contrat_l_emporte_sur_celui_du_profil():
    a, b = en_file()
    profil, contrat = {**PROFIL, "budget_usd": 1.5}, {"max_cout_usd": 100.0}
    c, m, agent = monter_cher([a, b], profil, contrat=contrat)
    m.executer()
    assert b.etat == "verifie" and budgets(c) == [] and c.contrat.max_cout_usd == 100.0


def test_un_cout_incomplet_est_dit_au_fil():
    c, m, agent = monter_cher([tache("A", type="courante")], incomplets={1})
    m.executer()
    assert sum(e["texte"] == COUT_INCOMPLET for e in c.evenements) == 1


def test_au_dela_du_budget_un_controle_rouge_ne_revient_pas_a_l_ouvrier():
    a = tache("A", type="mecanique")
    controles = Controles(sorties=[rouge("test_un")])
    c, m, agent = monter_cher([a], {**PROFIL, "budget_usd": 0.5}, controles)
    m.executer()
    assert agent.rang == 1  # un seul agent : ni retour à l'ouvrier, ni nouveau départ
    assert a.etat == "revenu" and len(budgets(c)) == 1
