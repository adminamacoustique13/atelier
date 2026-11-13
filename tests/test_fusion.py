"""Les fichiers partagés : plusieurs tâches y travaillent en même temps, et leur fusion est prévue.

Le profil les déclare (clé `fichiers_partages`) ; le moteur et le plan ne les comptent pas dans
le chevauchement des périmètres ; à l'entrée dans la branche principale, un fichier en « union »
garde les lignes des deux côtés, et un conflit sur un fichier déclaré en « git » revient à
l'ouvrier. Un conflit sur tout autre fichier suit le chemin d'avant.
"""

import json
import subprocess
from pathlib import Path

import pytest

from atelier.agents import AgentSimule
from atelier.consignes import (
    REGLES_DECOUPAGE,
    conflits_en_clair,
    consigne_ouvrier,
    consigne_reprise,
    consigne_verificateur,
)
from atelier.controles import (
    FICHIER_UNIONS,
    MARQUEURS,
    SUPPRIME_PAR_LA_TACHE,
    SUPPRIME_SUR_LA_PRINCIPALE,
    ControlesGit,
    ControlesSimules,
    fichiers_partages,
    se_chevauchent,
)
from atelier.modele import Chantier, Contrat, Tache
from atelier.moteur import RELANCER_TEL, Moteur
from atelier.plan import forme_du_plan
from atelier.projets import ouvrir_depot

JOURNAL = "DECISIONS.md"
LIGNES_DE_MARQUEUR = ("<<<<<<<", "=======", ">>>>>>>")


def profil(fusion=None):
    """Un profil qui déclare le journal partagé, avec cette fusion (absente : celle par défaut)."""
    entree = {"motif": JOURNAL} if fusion is None else {"motif": JOURNAL, "fusion": fusion}
    return {"fichiers_partages": [entree]}


def chantier(taches):
    return Chantier(projet="essai", contrat=Contrat(objectif="Essai", valide=True), taches=taches)


def tache(identifiant, perimetre=None):
    """Une tâche qui touche le journal et son propre fichier, comme A et B des critères."""
    perimetre = perimetre or [JOURNAL, f"{identifiant.lower()}.py"]
    return Tache(identifiant, f"Tâche {identifiant}", type="mecanique", perimetre=perimetre)


def git(dossier, *arguments):
    return subprocess.run(
        ["git", *arguments], cwd=dossier, check=True, capture_output=True, text=True
    ).stdout


def depot_avec_journal(dossier):
    git(dossier, "init", "-q", "-b", "main")
    git(dossier, "config", "user.name", "Essai")
    git(dossier, "config", "user.email", "essai@example.invalid")
    (dossier / JOURNAL).write_text("# Journal\n", "utf-8")
    (dossier / "x.py").write_text("x = 0\n", "utf-8")
    git(dossier, "add", "-A")
    git(dossier, "commit", "-q", "-m", "socle")


def a_des_marqueurs(texte):
    return any(ligne.startswith(LIGNES_DE_MARQUEUR) for ligne in texte.splitlines())


class AgentQuiAjoute(AgentSimule):
    """L'agent simulé, qui ajoute sa ligne au bout des fichiers de son périmètre au lieu de les
    réécrire ; repris après un conflit, il résout les marqueurs en gardant les deux côtés, ou
    les laisse avec `resout=False`. Il garde chaque consigne reçue : (rôle, tâche, consigne)."""

    def __init__(self, resout=True, **champs):
        super().__init__(**champs)
        self.resout, self.consignes = resout, []

    def executer(self, consigne, *arguments, **options):
        contexte = options.get("contexte") or {}
        self.consignes.append((contexte.get("role"), contexte.get("tache"), consigne))
        return super().executer(consigne, *arguments, **options)

    def _ecrire(self, dossier, fichiers, marque):
        if dossier is None:
            return
        chemins = [Path(dossier) / nom for nom in fichiers]
        en_conflit = [c for c in chemins if c.exists() and a_des_marqueurs(c.read_text("utf-8"))]
        for chemin in en_conflit if self.resout else []:
            lignes = chemin.read_text("utf-8").splitlines(keepends=True)
            chemin.write_text("".join(x for x in lignes if not x.startswith(LIGNES_DE_MARQUEUR)))
        for chemin in [] if en_conflit else chemins:
            ancien = chemin.read_text("utf-8") if chemin.exists() else ""
            chemin.write_text(f"{ancien}{marque}\n", "utf-8")


# --- la clé du profil ------------------------------------------------------------------------


def test_le_profil_declare_ses_fichiers_partages_et_leur_fusion():
    lu = fichiers_partages(
        {"fichiers_partages": [{"motif": JOURNAL, "fusion": "union"}, {"motif": "docs/*.md"}]}
    )
    assert lu == {JOURNAL: "union", "docs/*.md": "git"}  # une fusion absente vaut « git »


def test_une_entree_mal_formee_est_ignoree_sans_planter():
    entrees = [
        "DECISIONS.md", None, 3, ["a.md"], {}, {"motif": ""}, {"motif": "   "},
        {"motif": 7}, {"motif": "mon journal.md"}, {"motif": "a.md", "fusion": "rebase"},
        {"motif": "b.md", "fusion": ["union"]}, {"motif": "#note.md"}, {"motif": "!x.md"},
        {"motif": " c.md ", "fusion": "union"},
    ]  # fmt: skip
    assert fichiers_partages({"fichiers_partages": entrees}) == {"c.md": "union"}
    for brut in ({}, {"fichiers_partages": None}, {"fichiers_partages": {"motif": "a"}}, None):
        assert fichiers_partages(brut) == {}


# --- le chevauchement, dans le moteur et dans le plan ----------------------------------------


def test_deux_perimetres_qui_ne_se_rencontrent_que_sur_un_fichier_partage_ne_se_chevauchent_pas():
    a, b = tache("A").perimetre, tache("B").perimetre
    assert se_chevauchent(a, b)
    assert not se_chevauchent(a, b, fichiers_partages(profil()))
    assert se_chevauchent(a + ["commun.py"], b + ["commun.py"], [JOURNAL])  # le reste compte
    assert se_chevauchent(["*"], a, [JOURNAL])  # un dossier entier retient toujours


def test_le_moteur_lance_ensemble_deux_taches_qui_partagent_un_fichier_declare():
    for reglage, ensemble in ((profil(), 2), ({}, 1)):
        c = chantier([tache("A"), tache("B")])
        agent = AgentSimule(delai_s=0.05, perimetres={t.id: t.perimetre for t in c.taches})
        actives = []

        def observer(taches=c.taches, actives=actives):
            actives.append(sum(t.etat in ("en_cours", "en_verification") for t in taches))

        Moteur(c, agent, ControlesSimules(), reglage, sur_changement=observer).executer()
        assert max(actives) == ensemble, reglage
        assert c.termine


def test_la_prochaine_tache_ignore_le_fichier_partage_et_seulement_lui():
    for reglage, prochaine in ((profil(), "B"), ({}, None)):
        c = chantier([tache("A"), tache("B")])
        m = Moteur(c, AgentSimule(), ControlesSimules(), reglage)
        c.tache("A").etat = "en_cours"
        assert getattr(m._prochaine(), "id", None) == prochaine, reglage


def test_le_plan_met_dans_la_meme_vague_deux_taches_qui_partagent_un_fichier_declare():
    plan = [{"id": t.id, "perimetre": t.perimetre} for t in (tache("A"), tache("B"))]
    assert forme_du_plan(plan, fichiers_partages(profil()))["vagues"] == [["A", "B"]]
    sans = forme_du_plan(plan)
    assert sans["vagues"] == [["A"], ["B"]]
    assert sans["retenues"] == ["B et A touchent toutes deux DECISIONS.md"]
    # Ce qui retient encore deux tâches est dit sans le fichier partagé.
    plan = [{"id": i, "perimetre": [JOURNAL, "commun.py"]} for i in "AB"]
    forme = forme_du_plan(plan, [JOURNAL])
    assert forme["retenues"] == ["B et A touchent toutes deux commun.py"]


# --- la fusion « union » ---------------------------------------------------------------------


def test_deux_taches_paralleles_ajoutent_chacune_une_ligne_au_journal_en_union(tmp_path):
    depot_avec_journal(tmp_path)
    controles = ControlesGit(tmp_path, partages=fichiers_partages(profil("union")))
    assert not (tmp_path / FICHIER_UNIONS).exists()  # rien d'écrit avant une fusion
    a, b = controles.preparer(tache("A")), controles.preparer(tache("B"))
    for copie, ligne in ((a, "Décision de A\n"), (b, "Décision de B\n")):
        (copie / JOURNAL).write_text("# Journal\n" + ligne, "utf-8")

    assert controles.enregistrer(tache("A"), a) == ""
    assert controles.enregistrer(tache("B"), b) == ""  # aucun conflit

    journal = (tmp_path / JOURNAL).read_text("utf-8")
    assert "Décision de A\n" in journal and "Décision de B\n" in journal
    assert not a_des_marqueurs(journal)
    # Le réglage vit sous .atelier/ : rien dans .git/, aucun .gitattributes enregistré.
    assert (tmp_path / FICHIER_UNIONS).read_text("utf-8") == f"/{JOURNAL} merge=union\n"
    assert not (tmp_path / ".git" / "info" / "attributes").exists()
    assert ".gitattributes" not in git(tmp_path, "ls-files").split()


def test_l_union_ne_couvre_jamais_plus_que_le_motif_declare(tmp_path):
    depot_avec_journal(tmp_path)
    controles = ControlesGit(tmp_path, partages={JOURNAL: "union", "docs/*.md": "union"})
    controles._reglages("merge")  # écrit le fichier d'attributs, comme avant chaque fusion
    reglage = f"core.attributesFile={tmp_path / FICHIER_UNIONS}"
    chemins = [JOURNAL, f"sous/{JOURNAL}", "docs/a.md", "docs/sous/b.md"]
    lu = git(tmp_path, "-c", reglage, "check-attr", "merge", "--", *chemins)
    assert lu.splitlines() == [
        f"{JOURNAL}: merge: union", f"sous/{JOURNAL}: merge: unspecified",
        "docs/a.md: merge: union", "docs/sous/b.md: merge: unspecified",
    ]  # fmt: skip


def test_sans_union_le_meme_journal_bute_sur_un_conflit(tmp_path):
    depot_avec_journal(tmp_path)
    controles = ControlesGit(tmp_path, partages=fichiers_partages(profil()))
    a, b = controles.preparer(tache("A")), controles.preparer(tache("B"))
    (a / JOURNAL).write_text("# Journal\nDécision de A\n", "utf-8")
    (b / JOURNAL).write_text("# Journal\nDécision de B\n", "utf-8")
    assert controles.enregistrer(tache("A"), a) == ""
    assert controles.enregistrer(tache("B"), b).startswith("Conflit avec la branche principale")
    assert controles.unions == [] and not (tmp_path / FICHIER_UNIONS).exists()


def test_le_profil_d_un_projet_ouvert_regle_les_fusions_en_union(tmp_path):
    depot_avec_journal(tmp_path)
    (tmp_path / "chantier").mkdir()
    texte = json.dumps(profil("union"))
    (tmp_path / "chantier" / "profil.json").write_text(texte, "utf-8")
    atelier = ouvrir_depot(tmp_path)
    assert atelier.moteur.controles.unions == [JOURNAL]


# --- la fusion « git » : le conflit revient à l'ouvrier ----------------------------------------


def deux_copies_en_conflit(tmp_path, controles=None):
    """A entre avec sa ligne au journal ; la copie de B, qui y a écrit la sienne, bute dessus."""
    depot_avec_journal(tmp_path)
    controles = controles or ControlesGit(tmp_path)
    a, b = controles.preparer(tache("A")), controles.preparer(tache("B"))
    (a / JOURNAL).write_text("# Journal\nDécision de A\n", "utf-8")
    (b / JOURNAL).write_text("# Journal\nDécision de B\n", "utf-8")
    (b / "b.py").write_text("B = 1\n", "utf-8")
    assert controles.enregistrer(tache("A"), a) == ""
    assert controles.enregistrer(tache("B"), b) != ""
    return controles, b


def test_les_conflits_sont_poses_dans_la_copie_sur_la_branche_principale(tmp_path):
    controles, b = deux_copies_en_conflit(tmp_path)

    assert controles.poser_conflits(tache("B"), b) == {JOURNAL: MARQUEURS}
    journal = (b / JOURNAL).read_text("utf-8")
    assert all(m in journal for m in LIGNES_DE_MARQUEUR) and "Décision de A" in journal
    # La copie est posée sur la branche principale : seul le travail de B y est à enregistrer.
    assert git(b, "rev-parse", "HEAD") == git(tmp_path, "rev-parse", "HEAD")
    assert controles.fichiers_modifies(tache("B"), b, None) == [JOURNAL, "b.py"]
    assert not (Path(git(b, "rev-parse", "--git-dir").strip()) / "MERGE_HEAD").exists()


def test_des_marqueurs_laisses_n_entrent_jamais_mais_un_soulignement_markdown_si(tmp_path):
    controles, b = deux_copies_en_conflit(tmp_path)
    controles.poser_conflits(tache("B"), b)
    avant = git(tmp_path, "rev-parse", "HEAD")

    probleme = controles.enregistrer(tache("B"), b)
    assert probleme.startswith(f"Des marqueurs de conflit restent dans : {JOURNAL}.")
    assert git(tmp_path, "rev-parse", "HEAD") == avant

    resolu = "# Journal\nDécision de A\nDécision de B\n\nTitre\n=======\n"
    (b / JOURNAL).write_text(resolu, "utf-8")
    assert controles.enregistrer(tache("B"), b) == ""
    assert (tmp_path / JOURNAL).read_text("utf-8") == resolu


def test_un_fichier_supprime_d_un_cote_est_rendu_sans_marqueurs_avec_ce_qu_il_faut_en_faire(
    tmp_path,
):
    depot_avec_journal(tmp_path)
    (tmp_path / "y.py").write_text("y = 0\n", "utf-8")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-q", "-m", "y")
    controles = ControlesGit(tmp_path)
    a, b = controles.preparer(tache("A")), controles.preparer(tache("B"))
    (a / "x.py").unlink()  # A supprime x.py et modifie y.py ; B fait l'inverse
    (a / "y.py").write_text("y = 'A'\n", "utf-8")
    (b / "x.py").write_text("x = 'B'\n", "utf-8")
    (b / "y.py").unlink()
    assert controles.enregistrer(tache("A"), a) == ""
    assert controles.enregistrer(tache("B"), b) != ""

    conflits = controles.poser_conflits(tache("B"), b)
    assert conflits == {"x.py": SUPPRIME_SUR_LA_PRINCIPALE, "y.py": SUPPRIME_PAR_LA_TACHE}
    assert (b / "y.py").read_text("utf-8") == "y = 'A'\n"  # la version de la principale
    texte = consigne_reprise(tache("B"), "integration", conflits_en_clair(conflits), {})
    assert "- `x.py` : supprimé sur la branche principale" in texte
    assert "Garde la suppression" in texte and "ne le fais pas revivre" in texte
    assert "- `y.py` : modifié sur la branche principale" in texte
    assert "ne le supprime pas de nouveau" in texte


def test_sans_conflit_rien_n_est_pose_et_la_copie_reste_telle_quelle(tmp_path):
    depot_avec_journal(tmp_path)
    controles = ControlesGit(tmp_path)
    a = controles.preparer(tache("A"))
    (a / "a.py").write_text("A = 1\n", "utf-8")
    git(a, "add", "-A")
    git(a, "commit", "-q", "-m", "A")
    avant = git(a, "rev-parse", "HEAD")
    assert controles.poser_conflits(tache("A"), a) == {}
    assert git(a, "rev-parse", "HEAD") == avant and git(a, "status", "--porcelain") == ""


def depart_en_conflit(tmp_path, agent):
    """A et B partent ensemble sur le journal partagé en « git » ; rend le chantier mené."""
    depot_avec_journal(tmp_path)
    c = chantier([tache("A"), tache("B")])
    agent.perimetres = {t.id: t.perimetre for t in c.taches}
    Moteur(c, agent, ControlesGit(tmp_path), profil("git")).executer()
    return c


def test_un_conflit_sur_un_fichier_partage_est_resolu_par_l_ouvrier_repris(tmp_path):
    agent = AgentQuiAjoute()
    c = depart_en_conflit(tmp_path, agent)

    assert c.termine and all(t.etat == "verifie" for t in c.taches)
    (reprise,) = agent.reprises  # une seule reprise : celle du conflit, dans sa session
    seconde = c.tache(reprise["tache"])
    assert (reprise["role"], reprise["tentative"]) == ("ouvrier", 1)
    message = reprise["message"]
    assert f"- `{JOURNAL}`" in message and "Garde les deux intentions" in message
    assert seconde.tentatives == 1  # pas de départ neuf : la reprise a suffi
    assert [(e["issue"], e["origine"], e["reprise"]) for e in seconde.historique] == [
        ("ne_sait_pas", "integration", False), ("valide", "", True),
    ]  # fmt: skip
    assert JOURNAL in seconde.historique[0]["detail"]
    journal = (tmp_path / JOURNAL).read_text("utf-8")
    assert "tâche A\n" in journal and "tâche B\n" in journal
    assert not a_des_marqueurs(journal)
    assert git(tmp_path, "status", "--porcelain", "--untracked-files=no") == ""
    # Le vérificateur qui suit la reprise sait quel fichier a été résolu, et quoi contrôler.
    *_, apres = [x for r, t, x in agent.consignes if r == "verificateur" and t == seconde.id]
    assert "## Conflit de fusion résolu" in apres and f"- `{JOURNAL}`" in apres


def test_un_ouvrier_repris_qui_laisse_les_marqueurs_ne_les_fait_pas_entrer(tmp_path):
    c = depart_en_conflit(tmp_path, AgentQuiAjoute(resout=False))

    assert c.termine and all(t.etat == "verifie" for t in c.taches)
    seconde = next(t for t in c.taches if t.tentatives == 2)  # refusée, puis repartie de main
    assert [(e["tentative"], e["reprise"]) for e in seconde.historique] == [
        (1, False), (1, True), (2, False),
    ]  # fmt: skip
    assert seconde.historique[1]["detail"].startswith("Des marqueurs de conflit restent")
    assert not a_des_marqueurs(git(tmp_path, "log", "-p", "main"))
    journal = (tmp_path / JOURNAL).read_text("utf-8")
    assert "tâche A\n" in journal and "tâche B\n" in journal


def test_sans_session_a_reprendre_le_conflit_suit_le_chemin_d_avant(tmp_path):
    class AgentSansMemoire(AgentQuiAjoute):
        def executer(self, *arguments, reprendre=None, **options):
            if reprendre is not None:
                self.oublier_sessions()
            return super().executer(*arguments, reprendre=reprendre, **options)

    c = depart_en_conflit(tmp_path, AgentSansMemoire())

    assert c.termine and all(t.etat == "verifie" for t in c.taches)
    seconde = next(t for t in c.taches if t.tentatives == 2)  # un départ neuf, de main
    assert [(e["tentative"], e["issue"]) for e in seconde.historique] == [
        (1, "ne_sait_pas"), (2, "valide"),
    ]  # fmt: skip
    journal = (tmp_path / JOURNAL).read_text("utf-8")
    assert "tâche A\n" in journal and "tâche B\n" in journal


def ajouter_a_x(depot):
    """Un commit sur la branche principale ajoute une ligne à `x.py`, là où l'ouvrier ajoute la
    sienne."""
    (depot / "x.py").write_text("x = 0\nprincipale\n", "utf-8")
    git(depot, "commit", "-q", "-am", "principale")


def supprimer_le_journal(depot):
    """Un commit sur la branche principale supprime le journal que l'ouvrier modifie."""
    git(depot, "rm", "-q", JOURNAL)
    git(depot, "commit", "-q", "-m", "plus de journal")


class AgentPendantQueLaPrincipaleBouge(AgentQuiAjoute):
    """Pendant que le premier ouvrier travaille, un commit sur la branche principale y fait
    `bouger(depot)` (par défaut `ajouter_a_x`)."""

    def __init__(self, depot, bouger=ajouter_a_x, **champs):
        super().__init__(**champs)
        self.depot, self.bouger, self.fait = depot, bouger, False

    def executer(self, consigne, *arguments, **options):
        if not self.fait and (options.get("contexte") or {}).get("role") == "ouvrier":
            self.fait = True
            self.bouger(self.depot)
        return super().executer(consigne, *arguments, **options)


@pytest.mark.parametrize("reglage", [{}, profil("git")], ids=["sans-partage", "journal-partage"])
def test_un_conflit_sur_un_fichier_non_declare_suit_le_chemin_d_avant(tmp_path, reglage):
    depot_avec_journal(tmp_path)
    perimetre = ["x.py"] if not reglage else [JOURNAL, "x.py"]
    c = chantier([tache("A", perimetre)])
    agent = AgentPendantQueLaPrincipaleBouge(tmp_path, perimetres={"A": perimetre})
    Moteur(c, agent, ControlesGit(tmp_path), reglage).executer()

    a = c.tache("A")
    assert a.etat == "verifie" and a.tentatives == 2 and agent.reprises == []
    assert a.historique[0]["detail"].startswith("Conflit avec la branche principale, où")
    assert not a_des_marqueurs((tmp_path / "x.py").read_text("utf-8"))


def test_un_fichier_en_union_qui_bute_quand_meme_n_est_pas_repris(tmp_path):
    """Modifié par la tâche et supprimé sur la branche principale, le journal en « union » bute
    quand même (l'union ne réunit que des contenus) : seul un fichier déclaré en « git » est
    repris, celui-ci suit le chemin d'avant."""
    depot_avec_journal(tmp_path)
    c = chantier([tache("A")])
    reglage = profil("union")
    agent = AgentPendantQueLaPrincipaleBouge(
        tmp_path, supprimer_le_journal, perimetres={"A": tache("A").perimetre}
    )
    controles = ControlesGit(tmp_path, partages=fichiers_partages(reglage))
    Moteur(c, agent, controles, reglage).executer()

    a = c.tache("A")
    assert a.etat == "verifie" and a.tentatives == 2 and agent.reprises == []
    assert a.historique[0]["detail"].startswith("Conflit avec la branche principale, où")
    assert (tmp_path / JOURNAL).read_text("utf-8") == "tâche A\n"  # le départ 2, sur main


class ControlesArretPuisConflit(ControlesSimules):
    """La personne arrête la tâche pendant sa première préparation ; ensuite, l'enregistrement
    bute une fois sur un conflit, sans rien à poser pour l'ouvrier."""

    def __init__(self):
        self.moteur, self.conflits = None, 1

    def preparer(self, tache):
        if self.moteur is not None:
            moteur, self.moteur = self.moteur, None
            moteur.arreter(tache.id)

    def enregistrer(self, tache, dossier):
        if self.conflits:
            self.conflits -= 1
            return "Conflit avec la branche principale."
        return ""


def test_un_arret_pendant_la_preparation_ne_compte_pas_comme_une_reprise():
    """L'arrêt est tracé sous le numéro du départ suivant : relancée au même niveau, la tâche
    garde sa seconde chance au même niveau après un refus qui ne se reprend pas."""
    c = chantier([tache("A", ["a.py"])])
    controles = ControlesArretPuisConflit()
    agent = AgentSimule(perimetres={"A": ["a.py"]})
    m = Moteur(c, agent, controles, {})
    controles.moteur = m
    m.executer()
    m.repondre(c.demandes[-1]["id"], RELANCER_TEL)
    m.executer()

    a = c.tache("A")
    assert [(e["tentative"], e["issue"]) for e in a.historique] == [
        (1, "arretee"), (1, "ne_sait_pas"), (2, "valide"),
    ]  # fmt: skip
    assert a.etat == "verifie" and c.montees == 0 and a.montees == 0
    departs = [(x["modele"], x["effort"]) for x in agent.appels
               if x["role"] == "ouvrier" and "reprise" not in x]  # fmt: skip
    assert len(departs) == 2 and departs[0] == departs[1]


class ControlesEnConflit(ControlesSimules):
    """Des contrôles simulés dont l'enregistrement bute sur un conflit les `conflits` premières
    fois ; ils comptent les conflits posés pour l'ouvrier."""

    def __init__(self, conflits):
        self.conflits, self.poses = conflits, 0

    def enregistrer(self, tache, dossier):
        if self.conflits:
            self.conflits -= 1
            return "Conflit avec la branche principale."
        return ""

    def poser_conflits(self, tache, dossier):
        self.poses += 1
        return {JOURNAL: MARQUEURS}


class AgentAuxVerdicts(AgentSimule):
    """L'agent simulé, dont les vérificateurs rendent tour à tour les issues de `verdicts`."""

    def __init__(self, verdicts, **champs):
        super().__init__(**champs)
        self.verdicts = list(verdicts)

    def _issue(self, contexte):
        if contexte.get("role") == "verificateur" and self.verdicts:
            return self.verdicts.pop(0)
        return "ok"


def test_une_seule_reprise_de_fusion_par_depart_et_elle_ne_fait_pas_monter():
    c = chantier([tache("A")])
    controles = ControlesEnConflit(conflits=2)
    agent = AgentAuxVerdicts([], perimetres={"A": tache("A").perimetre})
    Moteur(c, agent, controles, profil()).executer()

    a = c.tache("A")
    assert a.etat == "verifie" and controles.poses == 1 and len(agent.reprises) == 1
    assert [(e["tentative"], e["origine"], e["reprise"]) for e in a.historique] == [
        (1, "integration", False), (1, "integration", True), (2, "", False),
    ]  # fmt: skip
    # Le second conflit donne une seconde chance au même niveau, comme avant les reprises.
    assert c.montees == 0 and a.montees == 0
    departs = [(x["modele"], x["effort"]) for x in agent.appels
               if x["role"] == "ouvrier" and "reprise" not in x]  # fmt: skip
    assert len(departs) == 2 and departs[0] == departs[1]


def test_une_reprise_apres_un_verdict_n_empeche_pas_celle_d_un_conflit():
    c = chantier([tache("A")])
    controles = ControlesEnConflit(conflits=1)
    agent = AgentAuxVerdicts(["bacle"], perimetres={"A": tache("A").perimetre})
    Moteur(c, agent, controles, profil()).executer()

    a = c.tache("A")
    assert a.etat == "verifie" and a.tentatives == 1 and len(agent.reprises) == 2
    assert [(e["origine"], e["reprise"]) for e in a.historique] == [
        ("verdict", False), ("integration", True), ("", True),
    ]  # fmt: skip


# --- les consignes ---------------------------------------------------------------------------


def test_la_reprise_d_un_conflit_nomme_les_fichiers_et_garde_les_deux_intentions():
    conflits = conflits_en_clair({JOURNAL: MARQUEURS, "b.py": MARQUEURS})
    texte = consigne_reprise(tache("B"), "integration", conflits, {})
    assert f"- `{JOURNAL}`\n- `b.py`" in texte
    assert "marqueurs de conflit" in texte and "Garde les deux intentions" in texte
    assert "n'emploie aucune commande git" in texte


def test_l_ouvrier_sait_quels_fichiers_de_son_perimetre_sont_partages_et_comment():
    t = tache("A")
    contrat = Contrat(objectif="But")
    union = consigne_ouvrier(t, contrat, profil("union"))
    assert "Fichiers partagés : d'autres tâches peuvent les modifier en même temps" in union
    assert f"- `{JOURNAL}` : fusion « union » : ajoute seulement des lignes" in union
    assert "sans modifier ni retirer aucune ligne existante" in union
    assert "- `a.py` :" not in union
    assert f"- `{JOURNAL}` : fusion « git »" in consigne_ouvrier(t, contrat, profil("git"))
    sans = consigne_ouvrier(t, contrat, {})
    assert "Fichiers partagés" not in sans
    assert sans == consigne_ouvrier(t, contrat, {"fichiers_partages": []})


def test_le_verificateur_ne_parle_de_conflit_que_s_il_y_en_a_eu_un():
    t, contrat = tache("B"), Contrat(objectif="But")
    assert "Conflit de fusion" not in consigne_verificateur(t, contrat, {}, True)
    texte = consigne_verificateur(t, contrat, {}, True, conflits_en_clair({JOURNAL: MARQUEURS}))
    assert "## Conflit de fusion résolu\n" in texte and f"- `{JOURNAL}`" in texte
    assert "`git show HEAD:<chemin>`" in texte and "ne doit pas revivre" in texte


def test_le_decoupage_met_un_fichier_partage_dans_plusieurs_taches_paralleles():
    assert (
        "Un fichier déclaré partagé peut figurer dans le périmètre de plusieurs tâches parallèles"
        in REGLES_DECOUPAGE
    )
    assert "`chantier/profil.json`, clé « fichiers_partages »" in REGLES_DECOUPAGE
    assert (
        "Les trois règles qui suivent, et la tâche de raccord, ne valent que pour un fichier "
        "commun non déclaré." in REGLES_DECOUPAGE
    )
