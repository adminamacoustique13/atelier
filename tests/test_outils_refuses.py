"""V3b.1 : un outil refusé seul ne bloque pas, et la relance d'un blocage se désigne par son sens.

Un outil refusé à l'ouvrier sans rapport avec la tâche (`git push`) ne doit pas priver un vrai
défaut de sa reprise à chaud : il est cité à l'ouvrier repris. Seul un outil qui lance le premier
mot d'une commande d'un contrôle du profil, quand ce contrôle n'est pas permis aux agents, bloque
tout de suite, comme ce qu'un agent signale.
"""

import json

import pytest

from atelier.moteur import ABANDONNER, RELANCER, RELANCER_TEL, Moteur
from atelier.serveur import ACCEPTER_OUTILS
from tests.test_moteur import (
    AgentParRang,
    ControlesComptes,
    blocages,
    chantier,
    moteur,
    tache,
    textes_du_fil,
    traces,
)
from tests.test_serveur import attendre, bloque_avec_reglage

GIT_PUSH = "Bash(git push)"
PROFIL_UV = {"commandes": ["uv run pytest -q", "ruff check ."]}  # ruff est permis, uv non
SOUS = {"commandes": ["cd sous && uv run pytest -q"]}  # un `cd` n'est jamais permis d'avance
REFUSEE_PUIS_ACCEPTEE = {("A", "verificateur"): ["bacle", "ok"]}


class AgentRefuse(AgentParRang):
    """Le pont refuse des outils à l'ouvrier, passe après passe (reprises comprises) : `refuses`
    donne ceux de chaque passe, `lignes` ce que l'ouvrier ajoute à son compte rendu. Par défaut,
    il n'écrit aucune ligne « EMPÊCHÉ : »."""

    def __init__(self, refuses, lignes=(), **champs):
        super().__init__(**champs)
        self.a_refuser, self.lignes = [list(r) for r in refuses], list(lignes)

    def executer(self, consigne, modele, effort, dossier, lecture_seule=False, contexte=None,
                 copie_jetable=False, reprendre=None):  # fmt: skip
        resultat = super().executer(consigne, modele, effort, dossier, lecture_seule, contexte,
                                    copie_jetable, reprendre)  # fmt: skip
        if contexte["role"] == "ouvrier" and self.a_refuser:
            resultat.refuses = self.a_refuser.pop(0)
            if self.lignes:
                resultat.texte += "\n" + self.lignes.pop(0)
        return resultat


def moteur_refuse(refuses, issues=None, profil=None, lignes=(), textes=None):
    c = chantier([tache("A")])
    agent = AgentRefuse(refuses, lignes, issues=issues or REFUSEE_PUIS_ACCEPTEE, textes=textes,
                        perimetres={"A": ["a.py"]})  # fmt: skip
    return c, Moteur(c, agent, ControlesComptes(), profil), agent


# --- un outil refusé seul ne bloque pas -------------------------------------------------------


def test_un_outil_refuse_sans_rapport_laisse_partir_la_reprise_a_chaud_qui_le_cite():
    """Le cas rejoué : `Bash(git push)` refusé et un verdict « bâclé » bloquaient la tâche."""
    c, m, agent = moteur_refuse([[GIT_PUSH]], profil=PROFIL_UV)
    m.executer()
    a = c.tache("A")
    assert blocages(c) == [] and a.etat == "verifie" and c.termine
    assert traces(a) == [(1, "bacle", False), (1, "valide", True)]
    (reprise,) = agent.reprises
    assert f"- `{GIT_PUSH}`" in reprise["message"]
    assert "Ces outils t'ont été refusés pendant ton travail" in reprise["message"]


@pytest.mark.parametrize(
    ("refuse", "profil", "bloquee"),
    [
        ("Bash(uv sync)", PROFIL_UV, True),  # le cas `uv` : le contrôle `uv run pytest -q`
        ("Bash(uv)", PROFIL_UV, True),
        ("Bash(ruff format .)", PROFIL_UV, False),  # `ruff check .` est permis aux agents
        ("Bash(uvx ruff check .)", PROFIL_UV, False),  # un autre premier mot
        (GIT_PUSH, PROFIL_UV, False),
        ("Bash(uv sync)", {}, False),  # sans commande de contrôle dans le profil
        ("Edit(uv)", PROFIL_UV, False),  # un autre outil que Bash
        # Un contrôle permis aux agents : l'ouvrier lance les tests lui-même.
        ("Bash(python script.py)", {"commandes": ["python -m pytest -q"]}, False),
        ("Bash(uv sync)", {**PROFIL_UV, "commandes_permises": ["uv"]}, False),
        # Chaque commande de la chaîne du contrôle compte, sans `cd …` ni variable devant.
        ("Bash(cd /tmp && ls)", SOUS, False),
        ("Bash(uv sync)", SOUS, True),
        ("Bash(uv sync)", {"commandes": ["FOO=1 uv run pytest"]}, True),
        ("Bash(uv sync)", {"commandes": ["ruff check . ; uv run pytest -q"]}, True),
        # L'outil refusé se lit de même : l'ouvrier a lancé le contrôle tel qu'il est écrit.
        ("Bash(cd sous && uv run pytest -q)", SOUS, True),
        ("Bash(FOO=1 uv sync)", PROFIL_UV, True),
    ],
)
def test_un_outil_refuse_ne_bloque_que_s_il_lance_un_controle_non_permis_aux_agents(
    refuse, profil, bloquee
):
    c, m, agent = moteur_refuse([[refuse]], profil=profil)
    m.executer()
    a = c.tache("A")
    if not bloquee:
        assert blocages(c) == [] and len(agent.reprises) == 1 and a.etat == "verifie"
        return
    assert agent.reprises == [] and a.tentatives == 1 and a.etat == "revenu"
    (demande,) = blocages(c)
    assert demande["empechements"] == [refuse]
    assert (
        f"elle est bloquée parce qu'un agent a été empêché de travailler : « {refuse} »"
        in demande["question"]
    )


def test_un_outil_refuse_que_l_ouvrier_signale_aussi_mot_pour_mot_bloque_comme_sa_ligne():
    c, m, agent = moteur_refuse([[GIT_PUSH]], lignes=[f"EMPÊCHÉ : {GIT_PUSH}"])
    m.executer()
    assert agent.reprises == [] and c.tache("A").etat == "revenu"
    (demande,) = blocages(c)
    assert demande["empechements"] == [GIT_PUSH]


@pytest.mark.parametrize("par", ["ligne", "champ"])
def test_un_outil_refuse_que_le_verificateur_signale_mot_pour_mot_bloque(par):
    verdict = {"valide": False, "motif": "bacle", "resume": "Les tests n'ont pas été lancés."}
    texte = json.dumps({**verdict, "empeche": [GIT_PUSH]} if par == "champ" else verdict)
    if par == "ligne":
        texte = f"EMPÊCHÉ : {GIT_PUSH}\n{texte}"
    c, m, agent = moteur_refuse([[GIT_PUSH]], textes={"A": [texte]})
    m.executer()
    assert agent.reprises == [] and c.tache("A").etat == "revenu"
    (demande,) = blocages(c)
    assert demande["empechements"] == [GIT_PUSH]


def test_une_chaine_se_lit_commande_par_commande_sans_cd_ni_variable_devant():
    from atelier.moteur import _formes_lancees

    assert _formes_lancees("cd sous && FOO=1 BAR= uv run pytest -q | tee x ; ruff check .") == [
        "Bash(uv run pytest -q)", "Bash(tee x)", "Bash(ruff check .)",
    ]  # fmt: skip
    assert _formes_lancees("cd sous") == [] and _formes_lancees("") == []


def test_seuls_les_outils_refuses_de_la_passe_reprise_sont_cites():
    # Deux outils refusés au départ ; la reprise refusée n'en a aucun : rien ne bloque.
    issues = {("A", "verificateur"): ["bacle", "bacle", "ok"]}
    c, m, agent = moteur_refuse([[GIT_PUSH, "WebFetch(https://x.y)"], []], issues)
    m.executer()
    premiere = agent.reprises[0]["message"]
    assert f"- `{GIT_PUSH}`\n- `WebFetch(https://x.y)`\n" in premiere
    assert all("t'ont été refusés" not in r["message"] for r in agent.reprises[1:])
    assert blocages(c) == [] and c.tache("A").etat == "verifie"


WEBFETCH = "WebFetch(https://x.y)"


@pytest.mark.parametrize(
    ("refuses", "constat", "fin"),
    [
        ([GIT_PUSH], "Un outil a été refusé", "Si cette commande doit servir aux agents, tu peux "
         "la leur permettre dans les outils du projet."),
        ([GIT_PUSH, "Bash(curl x.y)"], "Des outils ont été refusés", "Si ces commandes doivent "
         "servir aux agents, tu peux les leur permettre dans les outils du projet."),
        ([WEBFETCH], "Un outil a été refusé", "Si cet outil doit servir aux agents, tu peux le "
         "leur permettre."),
        ([GIT_PUSH, WEBFETCH], "Des outils ont été refusés", "Si ces outils doivent servir aux "
         "agents, tu peux les leur permettre."),
    ],
)  # fmt: skip
def test_un_livrable_accepte_malgre_des_outils_refuses_les_nomme_sans_parler_d_empechement(
    refuses, constat, fin
):
    c, m, _ = moteur_refuse([refuses], issues={("A", "verificateur"): ["ok"]})
    m.executer()
    assert c.tache("A").etat == "verifie" and blocages(c) == []
    fil = textes_du_fil(c)
    liste = " ; ".join(f"« {r} »" for r in refuses)
    assert fil[fil.index("Vérifiée et enregistrée.") + 1] == (
        f"{constat} à l'ouvrier pendant cette tâche : {liste}. Le livrable a quand même été "
        f"accepté et enregistré. {fin}"
    )
    assert not any("signalé un empêchement" in texte for texte in fil)


# --- la question dit le vrai nombre de refus --------------------------------------------------


def test_le_troisieme_refus_identique_sans_cran_est_compte_trois_fois():
    c = chantier([tache("A")], plafond_modele="opus", plafond_effort="low")
    m, _ = moteur(c, {"A": ["ne_sait_pas"]})
    m.executer()
    a = c.tache("A")
    assert traces(a) == [(1, "ne_sait_pas", False), (1, "ne_sait_pas", True),
                         (2, "ne_sait_pas", False)]  # fmt: skip
    (demande,) = blocages(c)
    question = demande["question"]
    assert (
        "elle est bloquée parce qu'elle a été refusée trois fois de suite pour la même raison, "
        "et que le contrat ne permet plus de monter d'un cran" in question
    )
    assert question.count("« Le calcul est faux sur un cas de référence »") == 3


# --- relancer au même niveau, par le sens de l'option -----------------------------------------


def bloquee_sans_cran(scenario=None):
    """A refusée deux fois pour la même raison, sans cran pour monter : une demande de blocage.

    `scenario` ajoute d'autres tâches, avec leurs issues."""
    scenario = {"A": ["bacle"], **(scenario or {})}
    c = chantier([tache(t) for t in scenario], plafond_modele="sonnet", plafond_effort="low")
    m, _ = moteur(c, scenario)
    m.executer()
    (demande,) = blocages(c)
    return c, m, demande


def test_relancer_au_meme_niveau_trouve_l_option_par_son_sens_pas_par_sa_place():
    c, m, demande = bloquee_sans_cran()
    demande["options"] = [ABANDONNER, RELANCER, RELANCER_TEL]
    a = c.tache("A")
    niveau = (a.modele, a.effort)
    assert m.relancer_au_meme_niveau(demande["id"]) is True
    assert demande["reponse"] == RELANCER_TEL
    assert a.etat == "a_lancer" and (a.modele, a.effort) == niveau
    assert textes_du_fil(c)[-1] == "Décision reçue : relancer au même niveau."
    m.executer()
    assert a.etat == "revenu" and a.tentatives == 2 and (a.modele, a.effort) == niveau


def test_relancer_au_meme_niveau_rend_faux_sans_rien_changer_hors_d_un_blocage_qui_attend():
    c, m, demande = bloquee_sans_cran({"B": ["consigne"]})  # B revient sans être bloquée
    (ordinaire,) = [d for d in c.demandes if d["tache"] == "B"]
    assert "nature" not in ordinaire
    m.repondre(demande["id"], ABANDONNER)
    avant = (textes_du_fil(c), [dict(d) for d in c.demandes])
    for identifiant in ("inconnue", ordinaire["id"], demande["id"]):
        assert m.relancer_au_meme_niveau(identifiant) is False
    assert (textes_du_fil(c), c.demandes) == avant
    assert [t.etat for t in c.taches] == ["abandonnee", "revenu"]


def test_le_serveur_releve_un_blocage_au_meme_niveau_meme_si_ses_options_changent_d_ordre(
    tmp_path,
):
    atelier, _, _, demande, reglage = bloque_avec_reglage(tmp_path, '{"nom": "Café"}')
    demande["options"] = [ABANDONNER, RELANCER, RELANCER_TEL]
    b = atelier.moteur.chantier.tache("B")
    niveau = (b.modele, b.effort)

    atelier.decider(reglage["id"], ACCEPTER_OUTILS)

    assert demande["reponse"] == RELANCER_TEL
    assert attendre(lambda: b.etat == "verifie" and not atelier.en_marche())
    assert (b.modele, b.effort) == niveau
