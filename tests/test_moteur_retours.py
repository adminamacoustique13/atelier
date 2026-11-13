"""Le moteur branché sur l'ouvrier gardé ouvert : les retours dans un même départ.

Quand le profil le permet et que l'agent sait garder un ouvrier ouvert (`garde_les_ouvriers`),
le moteur le lui demande, lui redonne un contrôle rouge ou un manque sans ouvrir de départ neuf,
s'arrête au même échec ou devant une copie restée telle quelle, et le libère à la fin de la
tâche. Sans cela, rien ne change : une reprise par départ, comme avant.
"""

import pytest

from tests.test_moteur import tache, traces
from tests.test_moteur_niveaux import ACCORD, BACLE, PROFIL, Agent, Controles, monter, verdict


def rouge(nom):
    """Une sortie de contrôles en échec sur le test `nom` : deux noms, deux échecs différents."""
    return (False, f"$ pytest -q\nFAILED tests/test_a.py::{nom} - assert 1 == 2\n1 failed")


class AgentOuvert(Agent):
    """L'agent des tests de niveaux, qui sait garder un ouvrier ouvert : il note ce que le moteur
    lui demande à chaque appel d'ouvrier, et chaque tâche qu'on lui fait libérer."""

    def __init__(self, c, reponses=None, **champs):
        super().__init__(c, **champs)
        self.garde_les_ouvriers = True  # un champ de l'agent simulé, faux sans réglage
        self.vus, self.liberes, self.reponses = [], [], list(reponses or [])
        self.controles, self.sans_changement = None, []  # les retours qui ne changent rien

    def executer(self, consigne, modele, effort, dossier, lecture_seule=False, contexte=None,
                 copie_jetable=False, reprendre=None, garder_ouvert=None):  # fmt: skip
        role = (contexte or {}).get("role")
        self.vus.append((role, reprendre is not None, garder_ouvert))
        if role == "ouvrier":  # l'ouvrier change sa copie, sauf aux appels dits sans changement
            rang = sum(r == "ouvrier" for r, _, _ in self.vus)
            if rang not in self.sans_changement:
                self.controles.etat += 1
        resultat = super().executer(consigne, modele, effort, dossier, lecture_seule, contexte,
                                    copie_jetable, reprendre)  # fmt: skip
        if role == "ouvrier" and reprendre is not None and self.reponses:
            resultat.texte = self.reponses.pop(0)
        return resultat

    def liberer(self, tache_):
        self.liberes.append(tache_)

    def ouvriers(self):
        return [(repris, garde) for role, repris, garde in self.vus if role == "ouvrier"]


class ControlesCopie(Controles):
    """Les contrôles du double, dont l'empreinte suit ce que l'ouvrier change dans sa copie
    (`etat`, que l'agent fait avancer), et qui comptent les contrôles joués."""

    def __init__(self, **champs):
        super().__init__(**champs)
        self.etat, self.joues = 0, 0

    def mecaniques(self, t, dossier):
        self.joues += 1
        return super().mecaniques(t, dossier)

    def empreinte(self, dossier):
        return f"etat-{self.etat}"


def monter_ouvert(taches, profil=None, controles=None, **agent):
    from atelier.moteur import Moteur
    from tests.test_moteur import chantier

    c = chantier(taches)
    sans_changement = agent.pop("sans_changement", [])
    a = AgentOuvert(c, **agent)
    controles = controles or ControlesCopie()
    a.controles, a.sans_changement = controles, list(sans_changement)
    return c, Moteur(c, a, controles, profil or PROFIL), a, controles


def test_le_moteur_demande_a_garder_l_ouvrier_et_le_libere_a_la_fin_de_la_tache():
    a = tache("A", type="courante")
    c, m, agent, _ = monter_ouvert([a])
    m.executer()
    assert a.etat == "verifie"
    assert agent.vus == [("ouvrier", False, True), ("verificateur", False, None)]
    assert agent.liberes == ["A"]  # une fois, la tâche finie


def test_un_controle_rouge_revient_trois_fois_au_meme_ouvrier_sans_depart_neuf():
    a = tache("A", type="mecanique")
    rouges = [rouge("test_un"), rouge("test_deux"), rouge("test_trois")]
    c, m, agent, _ = monter_ouvert([a], controles=ControlesCopie(sorties=rouges))
    m.executer()
    assert a.etat == "verifie" and a.tentatives == 1 and c.montees == 0
    assert agent.ouvriers() == [(False, True), (True, True), (True, True), (True, True)]
    assert [(n, issue, repris) for n, issue, repris in traces(a)] == [
        (1, "ne_sait_pas", False),
        (1, "ne_sait_pas", True),
        (1, "ne_sait_pas", True),
        (1, "valide", True),
    ]


def test_au_quatrieme_controle_rouge_le_depart_s_arrete_la():
    a = tache("A", type="mecanique")
    rouges = [rouge(f"test_{i}") for i in range(4)]
    c, m, agent, _ = monter_ouvert([a], controles=ControlesCopie(sorties=rouges))
    m.executer()
    premier_depart = [repris for n, _, repris in traces(a) if n == 1]
    assert premier_depart == [False, True, True, True]  # trois retours, pas un de plus
    assert a.tentatives >= 2 or a.etat == "revenu"  # la suite est celle d'un refus ordinaire


def test_le_meme_echec_deux_fois_de_suite_arrete_les_retours():
    a = tache("A", type="mecanique")
    rouges = [rouge("test_un"), rouge("test_un"), rouge("test_un")]
    c, m, agent, _ = monter_ouvert([a], controles=ControlesCopie(sorties=rouges))
    m.executer()
    premier_depart = [repris for n, _, repris in traces(a) if n == 1]
    assert premier_depart == [False, True]  # un seul retour : il a redonné le même échec


@pytest.mark.parametrize(("reglage", "retours"), [(1, 1), (0, 0), ("trois", 3), (True, 3)])
def test_le_profil_regle_le_nombre_de_retours_d_un_controle_rouge(reglage, retours):
    a = tache("A", type="mecanique")
    rouges = [rouge(f"test_{i}") for i in range(5)]
    profil = {**PROFIL, "retours_controles": reglage}
    c, m, agent, _ = monter_ouvert([a], profil, ControlesCopie(sorties=rouges))
    m.executer()
    assert sum(repris for n, _, repris in traces(a) if n == 1) == retours


def test_un_manque_releve_par_le_verificateur_revient_une_seule_fois():
    a = tache("A", type="courante")
    autre = verdict(reste=["Autre chose : documenter la fonction."], fichiers=["a.py"])
    c, m, agent, _ = monter_ouvert([a], textes={"A": [BACLE, autre, ACCORD]})
    m.executer()
    premier_depart = [repris for n, _, repris in traces(a) if n == 1]
    assert premier_depart == [False, True]  # un complément, puis le départ s'arrête


def test_une_copie_restee_telle_quelle_laisse_valoir_le_refus_sans_rien_rejouer():
    a = tache("A", type="mecanique")
    controles = ControlesCopie(sorties=[rouge("test_un")])
    c, m, agent, _ = monter_ouvert(
        [a], controles=controles, sans_changement=[2],
        reponses=["Je ne vois rien à corriger, tout est déjà fait."],
    )  # fmt: skip
    joues_au_constat, noter = [], m._noter

    def constater(texte, t=None):
        if "sans rien changer" in texte:
            joues_au_constat.append(controles.joues)
        return noter(texte, t)

    m._noter = constater
    m.executer()
    assert [repris for n, _, repris in traces(a) if n == 1] == [False]  # aucune passe de plus
    assert joues_au_constat == [1]  # les contrôles n'ont pas été rejoués pour ce retour
    dit = [e["texte"] for e in c.evenements if "sans rien changer" in e["texte"]]
    assert len(dit) == 1 and "Je ne vois rien à corriger" in dit[0]
    assert agent.ouvriers()[1] == (True, True)  # le retour est bien parti, une fois


def test_une_copie_qui_a_change_est_jugee_comme_d_habitude():
    a = tache("A", type="mecanique")
    c, m, agent, _ = monter_ouvert([a], controles=ControlesCopie(sorties=[rouge("test_un")]))
    m.executer()
    assert a.etat == "verifie" and [r for n, _, r in traces(a) if n == 1] == [False, True]


def test_le_profil_peut_couper_l_ouvrier_ouvert_et_tout_redevient_comme_avant():
    a = tache("A", type="mecanique")
    rouges = [rouge(f"test_{i}") for i in range(3)]
    profil = {**PROFIL, "ouvrier_ouvert": False}
    c, m, agent, _ = monter_ouvert([a], profil, ControlesCopie(sorties=rouges))
    m.executer()
    assert all(garde is None for _, _, garde in agent.vus)  # jamais demandé
    assert [repris for n, _, repris in traces(a) if n == 1] == [False, True]  # une reprise
    assert agent.liberes == []


def test_un_agent_qui_ne_sait_pas_garder_ne_recoit_jamais_la_demande():
    a = tache("A", type="mecanique")
    c, m, agent, _ = monter([a], PROFIL, Controles(sorties=[rouge("test_un"), rouge("test_deux")]))
    m.executer()  # l'agent des autres tests n'accepte pas `garder_ouvert` : il lèverait
    assert [repris for n, _, repris in traces(a) if n == 1] == [False, True]


def test_l_ouvrier_est_libere_meme_quand_la_tache_revient_a_la_personne():
    a = tache("A", type="courante")
    c, m, agent, _ = monter_ouvert([a], issues={("A", "ouvrier"): ["erreur"] * 6})
    m.executer()
    assert a.etat == "revenu" and agent.liberes.count("A") >= 1
