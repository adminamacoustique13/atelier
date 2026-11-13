"""L'état du dépôt pour le tableau de bord : `ControlesGit.etat_du_depot`.

Vrais dépôts git dans `tmp_path`, construits par les vraies commandes du produit (`preparer`,
`enregistrer`, `poser_conflits`) puis par `git` : la situation de la maquette `maquettes/depot.html`
en petit. Les valeurs attendues sont relues par des commandes git écrites ici, jamais par le code
qu'on éprouve.
"""

import hashlib
import json
import os
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from atelier import controles as module_controles
from atelier.controles import (
    BUDGET_LECTURE_S,
    COMMANDES_PAR_TACHE,
    DELAI_LECTURE_S,
    ENREGISTREMENTS_MONTRES,
    FICHIERS_NOMMES,
    ControlesGit,
    ControlesSimules,
    fichiers_partages,
)
from atelier.modele import Tache
from atelier.projets import exclure_etat

PARTAGES = [
    {"motif": "CHANGELOG.md", "fusion": "union"},
    {"motif": "src/routes.py", "fusion": "git"},
]
NOMS_SPECIAUX = ["docs/été.md", "notes de chantier.md", 'docs/dit "oui".md', "docs/l'été.md"]
# Tout ce que la lecture a le droit de lancer : des lectures, jamais une commande qui écrit ou
# qui va sur le réseau (fetch, ls-remote, pull, push, remote update, clone...).
LECTURES_PERMISES = {
    "rev-parse", "symbolic-ref", "log", "for-each-ref", "merge-base", "rev-list", "status",
}  # fmt: skip
REFUS = "git a refusé la commande"


def git(dossier, *arguments):
    return subprocess.run(
        ["git", *arguments], cwd=dossier, check=True, capture_output=True, text=True
    ).stdout


def court(dossier, revision):
    return git(dossier, "rev-parse", "--short", revision).strip()


def heure_de(dossier, revision):
    secondes = int(git(dossier, "log", "-1", "--format=%ct", revision))
    return datetime.fromtimestamp(secondes).strftime("%H:%M")


def commit_de(dossier, motif, *options):
    """Le commit (le plus récent) dont le message correspond à ce motif."""
    return git(dossier, "log", "-1", "--format=%H", f"--grep={motif}", *options).strip()


def tache(identifiant, etat="en_cours", titre=None):
    return Tache(identifiant, titre or f"Titre de {identifiant}", etat=etat)


def depot_de_base(dossier, profil=None):
    git(dossier, "init", "-q", "-b", "main")
    git(dossier, "config", "user.name", "Essai")
    git(dossier, "config", "user.email", "essai@example.invalid")
    exclure_etat(dossier)
    (dossier / "src").mkdir()
    (dossier / "chantier").mkdir()
    (dossier / "src" / "routes.py").write_text("def routes():\n    return 'socle'\n", "utf-8")
    (dossier / "CHANGELOG.md").write_text("# Changelog\n", "utf-8")
    (dossier / "chantier" / "CAHIER.md").write_text("# Cahier\n", "utf-8")
    texte = json.dumps(profil if profil is not None else {"fichiers_partages": PARTAGES})
    (dossier / "chantier" / "profil.json").write_text(texte, "utf-8")
    git(dossier, "add", "-A")
    git(dossier, "commit", "-q", "-m", "Cahier du chantier")


def enregistrer(controles, t, copie, ligne_de_cahier=True):
    """`enregistrer` du produit ; le cahier change à chaque entrée, comme dans un vrai chantier."""
    if ligne_de_cahier:
        cahier = controles.depot / "chantier" / "CAHIER.md"
        cahier.write_text(cahier.read_text("utf-8") + f"{t.id} enregistrée\n", "utf-8")
    return controles.enregistrer(t, copie)


def commit_direct(dossier, fichier, texte, message):
    chemin = dossier / fichier
    chemin.write_text(chemin.read_text("utf-8") + texte, "utf-8")
    git(dossier, "add", "--", fichier)
    git(dossier, "commit", "-q", "-m", message)


def construire(dossier):
    """La maquette en petit. A entrée directement, B entrée après fusion de la branche du
    chantier dans la sienne, C en conflit avec des marqueurs, D en cours (3 fichiers modifiés)
    et en retard de deux enregistrements, E pas encore partie. Un dépôt en ligne simulé par un
    dépôt nu local, trois enregistrements derrière la branche du chantier."""
    depot_de_base(dossier)
    controles = ControlesGit(dossier)
    a, b, c = (controles.preparer(tache(i)) for i in "ABC")
    (a / "a.py").write_text("A = 1\n", "utf-8")
    (a / "src" / "routes.py").write_text("def routes():\n    return 'A'\n", "utf-8")
    assert enregistrer(controles, tache("A"), a) == ""
    (b / "b.py").write_text("B = 1\n", "utf-8")
    assert enregistrer(controles, tache("B"), b) == ""
    (c / "src" / "routes.py").write_text("def routes():\n    return 'C'\n", "utf-8")
    assert enregistrer(controles, tache("C"), c, ligne_de_cahier=False) != ""  # conflit avec A
    d = controles.preparer(tache("D"))
    for nom in ("d1.py", "d2.py", "docs/été.md"):
        (d / nom).parent.mkdir(exist_ok=True)
        (d / nom).write_text("D\n", "utf-8")
    commit_direct(dossier, "CHANGELOG.md", "- un\n", "Outils du projet")
    commit_direct(dossier, "CHANGELOG.md", "- deux\n", "Journal du projet")
    assert controles.poser_conflits(tache("C"), c)
    entre_b = commit_de(dossier, "into tache/B", "--merges")
    en_ligne = dossier.parent / (dossier.name + "-en-ligne")
    git(dossier.parent, "init", "-q", "--bare", "-b", "main", en_ligne.name)
    git(dossier, "remote", "add", "origin", str(en_ligne))
    git(dossier, "push", "-q", "origin", f"{entre_b}:refs/heads/main")
    git(dossier, "fetch", "-q", "origin")
    git(dossier, "branch", "--set-upstream-to=origin/main", "main")
    taches = [tache("A", "verifie"), tache("B", "verifie"), tache("C", "en_cours"),
              tache("D", "en_cours"), tache("E", "a_lancer")]  # fmt: skip
    return SimpleNamespace(
        depot=dossier, controles=controles, taches=taches, copies={"C": c, "D": d},
        entre_b=entre_b, en_ligne=en_ligne,
    )  # fmt: skip


@pytest.fixture(scope="module")
def maquette(tmp_path_factory):
    """La situation commune des tests de lecture ; aucun d'eux ne la modifie (le critère 6 le
    vérifie, et les tests qui abîment quelque chose bâtissent la leur)."""
    scenario = construire(tmp_path_factory.mktemp("maquette"))
    scenario.etat = scenario.controles.etat_du_depot(scenario.taches)
    return scenario


@pytest.fixture
def maquette_jetable(tmp_path):
    return construire(tmp_path)


class Espion:
    """Remplace `lancer_git` du module : note chaque appel, et peut en faire échouer certains."""

    def __init__(self, monkeypatch, panne=None, comment="refus", pause=0.0):
        self.appels, self.panne, self.comment, self.pause = [], panne, comment, pause
        self.vrai = module_controles.lancer_git
        monkeypatch.setattr(module_controles, "lancer_git", self)

    def __call__(self, dossier, *arguments, **options):
        self.appels.append(SimpleNamespace(dossier=Path(dossier), arguments=arguments, **options))
        time.sleep(self.pause)
        if self.panne and self.panne(arguments):
            if self.comment == "delai":
                raise subprocess.TimeoutExpired(["git", *arguments], 1)
            if self.comment == "absent":
                raise FileNotFoundError("git")
            return subprocess.CompletedProcess(["git", *arguments], 128, "", "fatal: panne")
        return self.vrai(dossier, *arguments, **options)

    def sous_commandes(self):
        return {appel.arguments[0] for appel in self.appels}


# ---------- Critère 1 : la forme, qui part en JSON ----------


def types_permis(valeur):
    if isinstance(valeur, dict):
        return all(isinstance(k, str) and types_permis(v) for k, v in valeur.items())
    if isinstance(valeur, list):
        return all(types_permis(v) for v in valeur)
    return valeur is None or type(valeur) in (str, int, float, bool)


def test_l_etat_est_fait_de_textes_de_nombres_de_listes_et_de_dictionnaires(maquette):
    assert types_permis(maquette.etat)
    assert json.loads(json.dumps(maquette.etat)) == maquette.etat
    assert set(maquette.etat) == {"chantier", "taches", "en_ligne", "partages"}
    assert list(maquette.etat["taches"]) == ["A", "B", "C", "D", "E"]


def test_un_chemin_qui_se_glisserait_dans_l_etat_serait_refuse_par_la_verification(maquette):
    # Le détecteur de forme ci-dessus n'est pas aveugle : un `Path` ne passe pas.
    assert not types_permis({"copie": Path("x")})
    assert not types_permis({"noms": ("a", "b")})


def test_les_taches_sont_lues_par_leur_identifiant_titre_et_etat_sans_plus(tmp_path):
    depot_de_base(tmp_path)
    minimales = [SimpleNamespace(id="Z", titre="Une tâche", etat="a_lancer")]
    etat = ControlesGit(tmp_path).etat_du_depot(minimales)
    assert list(etat["taches"]) == ["Z"] and etat["taches"]["Z"]["probleme"] == ""


# ---------- Critère 2 : la branche du chantier et ses enregistrements ----------


def test_la_branche_du_chantier_est_celle_du_dossier_du_projet(maquette):
    assert maquette.etat["chantier"]["branche"] == "main"
    assert maquette.etat["chantier"]["detachee"] is False


def test_la_branche_du_chantier_n_est_jamais_un_nom_ecrit_en_dur(tmp_path):
    depot_de_base(tmp_path)
    git(tmp_path, "checkout", "-q", "-b", "chantier-reservations")
    etat = ControlesGit(tmp_path).etat_du_depot([])
    assert etat["chantier"]["branche"] == "chantier-reservations"
    assert etat["chantier"]["probleme"] == ""


def test_le_dernier_enregistrement_est_celui_de_git(maquette):
    dernier = maquette.etat["chantier"]["dernier"]
    assert dernier["id"] == court(maquette.depot, "HEAD")
    assert dernier["message"] == git(maquette.depot, "log", "-1", "--format=%s").strip()
    assert dernier["heure"] == heure_de(maquette.depot, "HEAD")
    assert datetime.fromisoformat(dernier["instant"]).strftime("%H:%M") == dernier["heure"]
    assert dernier == {**maquette.etat["chantier"]["derniers"][0]}


def test_huit_enregistrements_au_plus_du_plus_recent_au_plus_ancien(tmp_path):
    depot_de_base(tmp_path)
    for numero in range(14):
        commit_direct(tmp_path, "CHANGELOG.md", f"- {numero}\n", f"Ligne {numero}")
    derniers = ControlesGit(tmp_path).etat_du_depot([])["chantier"]["derniers"]
    attendus = git(tmp_path, "log", "-8", "--format=%h %s").splitlines()
    assert ENREGISTREMENTS_MONTRES == 8 == len(derniers)
    assert [f"{e['id']} {e['message']}" for e in derniers] == attendus
    assert derniers[0]["message"] == "Ligne 13" and derniers[-1]["message"] == "Ligne 6"


def test_un_enregistrement_dit_sa_tache_quand_son_message_la_dit(maquette):
    par_message = {e["message"]: e["tache"] for e in maquette.etat["chantier"]["derniers"]}
    assert par_message["Cahier : B enregistrée"] == "B"
    assert par_message["B : Titre de B"] == "B"
    fusion = next(m for m in par_message if m.startswith("Merge") and "tache/B" in m)
    assert par_message[fusion] == "B"
    assert par_message["Outils du projet"] == "" and par_message["Journal du projet"] == ""


def test_le_message_du_travail_nomme_sa_tache(tmp_path):
    controles = ControlesGit(tmp_path)
    depot_de_base(tmp_path)
    copie = controles.preparer(tache("A", titre="Schéma des salles"))
    (copie / "a.py").write_text("A = 1\n", "utf-8")
    assert enregistrer(controles, tache("A", titre="Schéma des salles"), copie) == ""
    schema = tache("A", titre="Schéma des salles")
    derniers = controles.etat_du_depot([schema])["chantier"]["derniers"]
    assert [(e["message"], e["tache"]) for e in derniers[:2]] == [
        ("Cahier : A enregistrée", "A"),
        ("A : Schéma des salles", "A"),
    ]
    assert derniers[2]["tache"] == ""  # « Cahier du chantier » ne concerne aucune tâche


def test_une_tache_inconnue_n_est_pas_attribuee_sur_la_seule_forme_du_message(tmp_path):
    depot_de_base(tmp_path)
    commit_direct(tmp_path, "CHANGELOG.md", "- x\n", "Z : un message de quelqu'un d'autre")
    derniers = ControlesGit(tmp_path).etat_du_depot([tache("A")])["chantier"]["derniers"]
    assert derniers[0]["tache"] == ""


# ---------- Critère 3 : ce que l'état dit de chaque tâche ----------


def test_une_tache_pas_encore_partie_n_a_ni_branche_ni_copie_et_pas_de_probleme(maquette):
    e = maquette.etat["taches"]["E"]
    assert e["branche"] == {"nom": "tache/E", "existe": False}
    assert e["copie"] == {"existe": False, "dossier": ".atelier/arbres/E"}
    assert e["depart"] is None and e["retard"] is None and e["entree"] is None
    assert e["modifies"] == {"nombre": 0, "noms": []} and e["conflits"] == []
    assert e["probleme"] == ""


def test_une_tache_en_cours_dit_sa_branche_sa_copie_son_depart_et_son_retard(maquette):
    d, depot = maquette.etat["taches"]["D"], maquette.depot
    assert d["branche"] == {"nom": "tache/D", "existe": True}
    assert d["copie"]["existe"] is True and d["copie"]["dossier"] == ".atelier/arbres/D"
    assert (depot / d["copie"]["dossier"]).is_dir()
    depart = git(depot, "merge-base", "main", "tache/D").strip()
    assert d["depart"]["id"] == court(depot, depart)
    assert d["depart"]["heure"] == heure_de(depot, depart)
    assert d["depart"]["message"] == "Cahier : B enregistrée"
    # Deux enregistrements sont entrés dans la branche du chantier depuis ce départ.
    assert d["retard"] == 2 == int(git(depot, "rev-list", "--count", f"{depart}..main"))
    assert d["entree"] is None and d["probleme"] == ""


def test_les_fichiers_modifies_et_pas_enregistres_sont_ceux_de_la_copie(maquette):
    d = maquette.etat["taches"]["D"]
    assert d["modifies"]["nombre"] == 3
    assert sorted(d["modifies"]["noms"]) == ["d1.py", "d2.py", "docs/été.md"]
    assert d["conflits"] == []


def test_vingt_noms_au_plus_mais_le_nombre_est_complet(tmp_path):
    depot_de_base(tmp_path)
    controles = ControlesGit(tmp_path)
    copie = controles.preparer(tache("D"))
    for numero in range(FICHIERS_NOMMES + 5):
        (copie / f"f{numero:02d}.py").write_text("x\n", "utf-8")
    d = controles.etat_du_depot([tache("D")])["taches"]["D"]
    assert FICHIERS_NOMMES == 20
    assert d["modifies"]["nombre"] == 25 and len(d["modifies"]["noms"]) == 20
    assert d["modifies"]["noms"] == [f"f{n:02d}.py" for n in range(20)]


def test_une_tache_en_conflit_dit_ses_fichiers_a_marqueurs(maquette):
    c = maquette.etat["taches"]["C"]
    assert c["conflits"] == ["src/routes.py"]
    assert c["modifies"]["noms"] == ["src/routes.py"]
    texte = (maquette.copies["C"] / "src" / "routes.py").read_text("utf-8")
    assert "<<<<<<< " in texte  # le fichier porte vraiment des marqueurs


def test_un_fichier_modifie_sans_marqueur_n_est_pas_en_conflit_et_un_soulignement_non_plus(
    maquette_jetable,
):
    m = maquette_jetable
    copie = m.copies["D"]
    (copie / "d1.py").write_text("Titre\n=======\n", "utf-8")  # le soulignement Markdown
    d = m.controles.etat_du_depot(m.taches)["taches"]["D"]
    assert d["conflits"] == []
    (copie / "d1.py").write_text("<<<<<<< HEAD\nx\n=======\ny\n>>>>>>> main\n", "utf-8")
    d = m.controles.etat_du_depot(m.taches)["taches"]["D"]
    assert d["conflits"] == ["d1.py"]
    # Une fois résolu, le marqueur ne se lit plus : l'état suit les fichiers, pas la mémoire.
    (copie / "d1.py").write_text("x\ny\n", "utf-8")
    assert m.controles.etat_du_depot(m.taches)["taches"]["D"]["conflits"] == []


def test_une_tache_entree_directement_dit_son_enregistrement_d_entree(maquette):
    a, depot = maquette.etat["taches"]["A"], maquette.depot
    travail = commit_de(depot, "^A : ")
    assert a["branche"]["existe"] is False and a["copie"]["existe"] is False
    assert a["entree"]["id"] == court(depot, travail)
    assert a["entree"]["message"] == "A : Titre de A"
    assert a["entree"]["heure"] == heure_de(depot, travail)
    assert a["entree"]["facon"] == "directe"
    assert a["depart"] is None and a["retard"] is None and a["probleme"] == ""


def test_une_tache_entree_apres_fusion_dit_l_enregistrement_de_la_fusion(maquette):
    b, depot = maquette.etat["taches"]["B"], maquette.depot
    assert b["entree"]["id"] == court(depot, maquette.entre_b)
    assert b["entree"]["message"].startswith("Merge") and "tache/B" in b["entree"]["message"]
    assert b["entree"]["facon"] == "apres_fusion"
    assert b["entree"]["heure"] == heure_de(depot, maquette.entre_b)
    # La fusion a bien deux parents : la branche du chantier est entrée dans celle de B.
    assert len(git(depot, "log", "-1", "--format=%P", maquette.entre_b).split()) == 2


def test_une_tache_sans_aucun_changement_n_a_pas_d_enregistrement_d_entree_a_deviner(tmp_path):
    depot_de_base(tmp_path)
    controles = ControlesGit(tmp_path)
    copie = controles.preparer(tache("F"))
    assert enregistrer(controles, tache("F"), copie) == ""  # rien à enregistrer : seul le cahier
    f = controles.etat_du_depot([tache("F", "verifie")])["taches"]["F"]
    # Seul son cahier dit qu'elle est entrée : ce n'est pas l'enregistrement de son travail.
    assert f["entree"] is None and "introuvable" in f["probleme"]
    derniers = controles.etat_du_depot([tache("F")])["chantier"]["derniers"]
    assert derniers[0]["message"] == "Cahier : F enregistrée" and derniers[0]["tache"] == "F"


def test_une_tache_entree_puis_relancee_n_est_plus_dite_entree(tmp_path):
    depot_de_base(tmp_path)
    controles = ControlesGit(tmp_path)
    copie = controles.preparer(tache("A"))
    (copie / "a.py").write_text("A = 1\n", "utf-8")
    assert enregistrer(controles, tache("A"), copie) == ""
    assert controles.etat_du_depot([tache("A", "verifie")])["taches"]["A"]["entree"] is not None
    controles.preparer(tache("A"))  # une nouvelle copie : le travail repart (état « en cours »)
    a = controles.etat_du_depot([tache("A")])["taches"]["A"]
    assert a["entree"] is None and a["copie"]["existe"] and a["branche"]["existe"]


def test_une_tache_qui_a_de_l_avance_sur_le_chantier_n_est_pas_entree(maquette_jetable):
    # A est entrée ; relancée (son état redevient « en cours »), elle a un enregistrement de plus
    # que le chantier n'a pas, et sa copie a disparu. Son ancienne entrée ne la fait pas passer
    # pour entrée.
    m = maquette_jetable
    assert m.controles.etat_du_depot(m.taches)["taches"]["A"]["entree"] is not None
    copie = m.controles.preparer(tache("A"))
    (copie / "a2.py").write_text("A2 = 1\n", "utf-8")
    git(copie, "add", "-A")
    git(copie, "commit", "-q", "-m", "A : Titre de A")
    shutil.rmtree(copie)
    git(m.depot, "worktree", "prune")
    a = m.controles.etat_du_depot([tache("A"), *m.taches[1:]])["taches"]["A"]
    assert a["branche"]["existe"] is True and a["entree"] is None
    assert a["depart"] is not None and a["retard"] == 0


# ---------- Critère 4 : l'avance sur le dépôt en ligne, lue sur le disque ----------


def test_l_avance_et_l_enregistrement_connu_du_depot_en_ligne(maquette):
    en_ligne, depot = maquette.etat["en_ligne"], maquette.depot
    assert en_ligne["suivie"] == "origin/main"
    assert en_ligne["avance"] == 3 == int(git(depot, "rev-list", "--count", "origin/main..main"))
    assert en_ligne["connu"]["id"] == court(depot, "origin/main")
    assert en_ligne["connu"]["id"] == court(depot, maquette.entre_b)
    attendu = git(depot, "log", "-1", "--format=%s", "origin/main").strip()
    assert en_ligne["connu"]["message"] == attendu
    assert en_ligne["connu"]["heure"] == heure_de(depot, "origin/main")
    assert en_ligne["probleme"] == ""


def test_sans_depot_en_ligne_tout_est_vide_sans_erreur(tmp_path):
    depot_de_base(tmp_path)
    en_ligne = ControlesGit(tmp_path).etat_du_depot([])["en_ligne"]
    assert en_ligne == {"suivie": "", "avance": None, "connu": None, "probleme": ""}


def test_un_depot_en_ligne_sans_branche_suivie_est_vide_sans_erreur(tmp_path):
    depot_de_base(tmp_path)
    git(tmp_path, "remote", "add", "origin", str(tmp_path / "nulle-part.git"))
    en_ligne = ControlesGit(tmp_path).etat_du_depot([])["en_ligne"]
    assert en_ligne == {"suivie": "", "avance": None, "connu": None, "probleme": ""}


def test_sans_reglage_de_suivi_origin_branche_est_lue_si_git_la_connait(maquette_jetable):
    m = maquette_jetable
    git(m.depot, "branch", "--unset-upstream")
    en_ligne = m.controles.etat_du_depot(m.taches)["en_ligne"]
    assert en_ligne["suivie"] == "origin/main" and en_ligne["avance"] == 3


def test_le_reglage_de_suivi_prime_sur_le_nom_origin_branche(maquette_jetable):
    m = maquette_jetable
    git(m.depot, "update-ref", "refs/remotes/origin/principale", "HEAD~3")
    git(m.depot, "branch", "--set-upstream-to=origin/principale", "main")
    en_ligne = m.controles.etat_du_depot(m.taches)["en_ligne"]
    assert en_ligne["suivie"] == "origin/principale"
    assert en_ligne["avance"] == 3  # HEAD~3 : trois enregistrements derrière
    assert en_ligne["connu"]["id"] == court(m.depot, "HEAD~3")


def test_un_suivi_regle_mais_dont_la_branche_n_est_pas_sur_le_disque_le_dit(maquette_jetable):
    m = maquette_jetable
    git(m.depot, "update-ref", "-d", "refs/remotes/origin/main")
    en_ligne = m.controles.etat_du_depot(m.taches)["en_ligne"]
    assert en_ligne["suivie"] == "" and en_ligne["avance"] is None and en_ligne["connu"] is None
    assert en_ligne["probleme"]


def test_la_lecture_n_interroge_jamais_le_reseau(maquette_jetable, monkeypatch):
    m = maquette_jetable
    git(m.depot, "remote", "set-url", "origin", "https://localhost:9/introuvable.git")
    espion = Espion(monkeypatch)
    etat = m.controles.etat_du_depot(m.taches)
    assert espion.appels and espion.sous_commandes() <= LECTURES_PERMISES
    assert etat["en_ligne"]["avance"] == 3  # l'adresse en ligne n'a servi à rien
    assert all(a.environnement["GIT_OPTIONAL_LOCKS"] == "0" for a in espion.appels)


# ---------- Critère 5 : les fichiers partagés du profil ----------


def test_les_fichiers_partages_sont_ceux_du_profil_et_leur_fusion(maquette):
    assert maquette.etat["partages"] == {
        "fichiers": [
            {"motif": "CHANGELOG.md", "fusion": "union"},
            {"motif": "src/routes.py", "fusion": "git"},
        ],
        "probleme": "",
    }


def test_les_fichiers_partages_passent_par_la_fonction_du_produit(tmp_path):
    depot_de_base(tmp_path, profil={})
    profil = {"fichiers_partages": [
        {"motif": "A.md"},  # fusion absente : « git »
        {"motif": "B.md", "fusion": "union"},
        {"motif": "a b.md"},  # un espace : ignoré
        {"motif": "C.md", "fusion": "autre"},  # fusion inconnue : ignorée
        {"motif": "#D.md"}, "pas un objet",
    ]}  # fmt: skip
    etat = ControlesGit(tmp_path).etat_du_depot([], profil)
    attendu = [{"motif": m, "fusion": f} for m, f in fichiers_partages(profil).items()]
    assert attendu == [{"motif": "A.md", "fusion": "git"}, {"motif": "B.md", "fusion": "union"}]
    assert etat["partages"]["fichiers"] == attendu


def test_sans_profil_donne_le_fichier_du_projet_est_lu_a_chaque_lecture(tmp_path):
    depot_de_base(tmp_path, profil={})
    controles = ControlesGit(tmp_path)
    assert controles.etat_du_depot([])["partages"] == {"fichiers": [], "probleme": ""}
    texte = json.dumps({"fichiers_partages": [{"motif": "NOTES.md", "fusion": "union"}]})
    (tmp_path / "chantier" / "profil.json").write_text(texte, "utf-8")
    assert controles.etat_du_depot([])["partages"]["fichiers"] == [
        {"motif": "NOTES.md", "fusion": "union"}
    ]


def test_un_profil_illisible_donne_aucun_fichier_et_une_phrase_sans_toucher_au_reste(tmp_path):
    depot_de_base(tmp_path)
    (tmp_path / "chantier" / "profil.json").write_text("{pas du json", "utf-8")
    etat = ControlesGit(tmp_path).etat_du_depot([tache("A")])
    assert etat["partages"]["fichiers"] == [] and "illisible" in etat["partages"]["probleme"]
    assert etat["chantier"]["branche"] == "main" and etat["chantier"]["probleme"] == ""


# ---------- Critère 6 : la lecture ne change rien ----------


def instantane(depot):
    """Tout ce qui s'observe du projet et de ses copies : `git status` et les références de
    chacun, puis chaque fichier (contenu et date), `.git` compris, copies comprises."""
    fichiers = {}
    for chemin in sorted(Path(depot).rglob("*")):
        if chemin.is_file() and not chemin.is_symlink():
            contenu = hashlib.sha256(chemin.read_bytes()).hexdigest()
            fichiers[str(chemin.relative_to(depot))] = (contenu, chemin.stat().st_mtime_ns)
    copies = sorted((Path(depot) / ".atelier" / "arbres").glob("*"))
    statuts = {}
    for dossier in [Path(depot), *copies]:
        sortie = git(dossier, "--no-optional-locks", "status", "--porcelain", "-z", "-uall")
        references = git(dossier, "for-each-ref", "--format=%(refname) %(objectname)")
        statuts[str(dossier)] = (sortie, references)
    return fichiers, statuts


def rendre_les_index_perimes(depot):
    """Change la date de chaque fichier suivi sans toucher à son contenu : un `git status`
    ordinaire réécrirait alors l'index pour rafraîchir ses dates."""
    for dossier in [Path(depot), *sorted((Path(depot) / ".atelier" / "arbres").glob("*"))]:
        for nom in git(dossier, "ls-files").splitlines():
            os.utime(dossier / nom, ns=(1_000_000_000_000_000_000, 1_000_000_000_000_000_000))


def test_le_piege_est_arme_un_git_status_ordinaire_reecrit_l_index(tmp_path):
    # Garde du critère 6 : sans ce piège, « rien n'a changé » pourrait être vrai de tout.
    depot_de_base(tmp_path)
    rendre_les_index_perimes(tmp_path)
    avant = (tmp_path / ".git" / "index").read_bytes()
    git(tmp_path, "status", "--porcelain")
    assert (tmp_path / ".git" / "index").read_bytes() != avant


def test_la_lecture_ne_change_ni_l_index_ni_les_fichiers_ni_les_branches_ni_les_reglages(
    maquette_jetable,
):
    m = maquette_jetable
    rendre_les_index_perimes(m.depot)
    avant = instantane(m.depot)
    etat = m.controles.etat_du_depot(m.taches)
    assert etat["taches"]["D"]["retard"] == 2  # la lecture a vraiment eu lieu
    assert instantane(m.depot) == avant
    # ... et deux lectures de suite donnent le même état.
    assert m.controles.etat_du_depot(m.taches) == etat
    assert instantane(m.depot) == avant


def test_l_instantane_voit_un_changement_meme_minuscule(maquette_jetable):
    # La comparaison du critère 6 n'est pas aveugle : un réglage de plus, une branche de plus.
    m = maquette_jetable
    avant = instantane(m.depot)
    git(m.depot, "config", "essai.reglage", "1")
    assert instantane(m.depot) != avant
    avant = instantane(m.depot)
    git(m.depot, "branch", "tache/Z")
    assert instantane(m.depot) != avant


def test_un_verrou_de_l_index_tenu_par_une_autre_commande_ne_change_ni_l_etat_ni_le_verrou(
    maquette_jetable,
):
    # Une autre commande git est en train d'écrire (elle tient `index.lock`) dans le projet et
    # dans la copie de D : la lecture rend le même état, sans lui disputer le verrou.
    m = maquette_jetable
    libre = m.controles.etat_du_depot(m.taches)
    verrous = [
        m.depot / ".git" / "index.lock",
        Path(git(m.copies["D"], "rev-parse", "--absolute-git-dir").strip()) / "index.lock",
    ]
    for verrou in verrous:
        verrou.write_text("tenu par une autre commande\n", "utf-8")
    rendre_les_index_perimes(m.depot)
    avant = instantane(m.depot)
    tenu = m.controles.etat_du_depot(m.taches)
    assert tenu == libre
    assert all(v.read_text("utf-8") == "tenu par une autre commande\n" for v in verrous)
    assert instantane(m.depot) == avant


# ---------- Critère 7 : elle ne lève jamais, et le dit pour la partie touchée seulement ----------


def sans_la_partie(etat, *parties):
    """L'état sans ces parties : ce qui doit rester identique quand une autre partie échoue."""
    return {cle: valeur for cle, valeur in etat.items() if cle not in parties}


def test_un_dossier_qui_n_est_pas_un_depot(tmp_path):
    (tmp_path / "chantier").mkdir()
    profil = {"fichiers_partages": [{"motif": "NOTES.md", "fusion": "union"}]}
    (tmp_path / "chantier" / "profil.json").write_text(json.dumps(profil), "utf-8")
    etat = ControlesGit(tmp_path).etat_du_depot([tache("A")])
    assert etat["chantier"]["probleme"] == "Ce dossier n'est pas un dépôt git."
    assert etat["chantier"]["branche"] == "" and etat["chantier"]["derniers"] == []
    assert list(etat["taches"]) == ["A"] and etat["taches"]["A"]["entree"] is None
    assert etat["en_ligne"]["suivie"] == "" and etat["en_ligne"]["avance"] is None
    assert etat["partages"]["fichiers"] == [{"motif": "NOTES.md", "fusion": "union"}]
    assert types_permis(etat)


def test_un_dossier_qui_n_existe_pas(tmp_path):
    controles = ControlesGit(tmp_path)
    shutil.rmtree(tmp_path)
    etat = controles.etat_du_depot([tache("A")])
    assert etat["chantier"]["probleme"] and etat["taches"]["A"]["probleme"]
    assert etat["chantier"]["dernier"] is None


def test_un_depot_sans_aucun_enregistrement(tmp_path):
    git(tmp_path, "init", "-q", "-b", "main")
    etat = ControlesGit(tmp_path).etat_du_depot([tache("A", "a_lancer"), tache("B", "en_cours")])
    assert etat["chantier"]["branche"] == "main"
    assert etat["chantier"]["dernier"] is None and etat["chantier"]["derniers"] == []
    assert etat["chantier"]["probleme"] == "Ce dépôt n'a encore aucun enregistrement."
    assert etat["taches"]["A"]["probleme"] == ""  # pas partie : rien d'anormal
    assert "tache/B" in etat["taches"]["B"]["probleme"]
    assert etat["en_ligne"]["suivie"] == "" and types_permis(etat)


def test_une_copie_disparue_ne_touche_que_sa_tache(maquette_jetable):
    m = maquette_jetable
    avant = m.controles.etat_du_depot(m.taches)
    shutil.rmtree(m.copies["D"])  # sans `git worktree remove` : la branche, elle, reste
    etat = m.controles.etat_du_depot(m.taches)
    d = etat["taches"]["D"]
    assert d["copie"]["existe"] is False and d["branche"]["existe"] is True
    assert "copie" in d["probleme"] and d["modifies"] == {"nombre": 0, "noms": []}
    assert d["depart"] == avant["taches"]["D"]["depart"] and d["retard"] == 2
    for ailleurs in "ABCE":
        assert etat["taches"][ailleurs] == avant["taches"][ailleurs]
    assert sans_la_partie(etat, "taches") == sans_la_partie(avant, "taches")


def test_une_branche_de_tache_supprimee_ne_touche_que_sa_tache(maquette_jetable):
    m = maquette_jetable
    avant = m.controles.etat_du_depot(m.taches)
    git(m.depot, "update-ref", "-d", "refs/heads/tache/D")  # la copie, elle, reste
    etat = m.controles.etat_du_depot(m.taches)
    d = etat["taches"]["D"]
    assert d["branche"]["existe"] is False and d["copie"]["existe"] is True
    assert "tache/D" in d["probleme"] and d["depart"] is None and d["retard"] is None
    assert d["modifies"] == {"nombre": 0, "noms": []}  # une copie sans branche : rien de fiable
    for ailleurs in "ABCE":
        assert etat["taches"][ailleurs] == avant["taches"][ailleurs]
    assert sans_la_partie(etat, "taches") == sans_la_partie(avant, "taches")


def test_une_tache_en_route_sans_branche_ni_copie_le_dit(maquette_jetable):
    m = maquette_jetable
    etat = m.controles.etat_du_depot([*m.taches, tache("F", "en_verification")])
    assert "tache/F" in etat["taches"]["F"]["probleme"]
    assert etat["taches"]["E"]["probleme"] == ""  # « à lancer » : rien d'anormal


def test_une_tete_detachee_ne_touche_que_la_branche_du_chantier(maquette_jetable):
    m = maquette_jetable
    avant = m.controles.etat_du_depot(m.taches)
    git(m.depot, "checkout", "-q", "--detach")
    etat = m.controles.etat_du_depot(m.taches)
    assert etat["chantier"]["branche"] == "" and etat["chantier"]["detachee"] is True
    assert "aucune branche" in etat["chantier"]["probleme"]
    assert etat["chantier"]["dernier"] == avant["chantier"]["dernier"]  # ils se lisent encore
    assert etat["chantier"]["derniers"] == avant["chantier"]["derniers"]
    assert etat["taches"] == avant["taches"]
    assert etat["en_ligne"] == {"suivie": "", "avance": None, "connu": None, "probleme": ""}


PANNES = {
    "les enregistrements": lambda a: a[0] == "log" and any(x.startswith("--max-count") for x in a),
    "les branches": lambda a: a[0] == "for-each-ref" and "refs/heads/tache/" in a,
    "le point commun": lambda a: a[0] == "merge-base",
    "le retard": lambda a: a[0] == "rev-list" and "--left-right" in a,
    "les fichiers modifies": lambda a: a[0] == "status",
    "l'avance en ligne": lambda a: a[:2] == ("rev-list", "--count"),
    "la branche suivie": lambda a: a[0] == "for-each-ref" and "--format=%(upstream)" in a,
}  # fmt: skip
# Pour chaque panne : les parties qui peuvent changer, et les tâches qui doivent rester telles
# quelles (celles qui n'ont ni branche ni copie ne lancent aucune des commandes en panne).
EFFETS = {
    "les enregistrements": (("chantier", "taches"), "CDE"),
    "les branches": (("taches",), ""),
    "le point commun": (("taches",), "ABE"),
    "le retard": (("taches",), "ABE"),
    "les fichiers modifies": (("taches",), "ABE"),
    "l'avance en ligne": (("en_ligne",), "ABCDE"),
    "la branche suivie": (("en_ligne",), "ABCDE"),
}


def phrases_de_probleme(etat):
    """Chaque phrase de `probleme` de l'état, avec sa partie."""
    trouvees = [(cle, etat[cle]["probleme"]) for cle in ("chantier", "en_ligne", "partages")]
    trouvees += [(f"taches/{i}", f["probleme"]) for i, f in etat["taches"].items()]
    return [(partie, phrase) for partie, phrase in trouvees if phrase]


@pytest.mark.parametrize("comment", ["refus", "delai", "absent"])
@pytest.mark.parametrize("partie", list(PANNES))
def test_une_commande_git_en_echec_ou_trop_lente_ne_touche_que_sa_partie(
    maquette, monkeypatch, partie, comment
):
    avant = maquette.etat
    assert phrases_de_probleme(avant) == []
    Espion(monkeypatch, PANNES[partie], comment)
    etat = maquette.controles.etat_du_depot(maquette.taches)  # ne lève rien
    touchees, intactes = EFFETS[partie]
    assert types_permis(etat) and etat != avant
    for autre in set(avant) - set(touchees):
        assert etat[autre] == avant[autre], f"{autre} ne devrait pas changer pour {partie}"
    for ident in intactes:
        assert etat["taches"][ident] == avant["taches"][ident]
    problemes = phrases_de_probleme(etat)
    assert problemes and all(p.split("/")[0] in touchees for p, _ in problemes)
    if comment == "delai":
        assert all("à temps" in phrase for _, phrase in problemes)
    if comment == "absent":
        assert all("inaccessible" in phrase for _, phrase in problemes)


def test_la_panne_des_fichiers_modifies_garde_le_depart_et_le_retard(maquette, monkeypatch):
    Espion(monkeypatch, PANNES["les fichiers modifies"])
    d = maquette.controles.etat_du_depot(maquette.taches)["taches"]["D"]
    assert d["modifies"] == {"nombre": 0, "noms": []} and d["probleme"]
    assert d["depart"] == maquette.etat["taches"]["D"]["depart"] and d["retard"] == 2


def test_la_panne_de_l_historique_laisse_les_taches_en_cours_lisibles(maquette, monkeypatch):
    Espion(monkeypatch, PANNES["les enregistrements"])
    etat = maquette.controles.etat_du_depot(maquette.taches)
    assert etat["chantier"]["derniers"] == [] and etat["chantier"]["dernier"] is None
    assert etat["taches"]["D"] == maquette.etat["taches"]["D"]
    assert etat["taches"]["A"]["entree"] is None  # sans historique, l'entrée ne se retrouve pas


def test_un_git_qui_ne_rend_jamais_la_main_est_arrete_au_delai(tmp_path, monkeypatch):
    # Un vrai faux `git` qui dort : le délai du produit l'arrête, rien n'est levé.
    depot_de_base(tmp_path)
    controles = ControlesGit(tmp_path)
    faux = tmp_path.parent / "faux-git"
    faux.mkdir()
    (faux / "git").write_text("#!/bin/sh\nexec sleep 30\n", "utf-8")
    (faux / "git").chmod(0o755)
    monkeypatch.setenv("PATH", f"{faux}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setattr(module_controles, "DELAI_LECTURE_S", 0.2)
    depart = time.perf_counter()
    etat = controles.etat_du_depot([tache("A")])
    assert time.perf_counter() - depart < 5
    assert "à temps" in etat["chantier"]["probleme"] and etat["taches"]["A"]["probleme"]


def test_le_budget_de_la_lecture_borne_sa_duree_meme_quand_chaque_commande_est_lente(
    maquette, monkeypatch
):
    monkeypatch.setattr(module_controles, "BUDGET_LECTURE_S", 0.25)
    Espion(monkeypatch, pause=0.08)
    depart = time.perf_counter()
    etat = maquette.controles.etat_du_depot(maquette.taches)
    assert time.perf_counter() - depart < 1.0
    assert "trop de temps" in json.dumps(etat, ensure_ascii=False) and types_permis(etat)


def test_git_introuvable_ne_leve_rien(maquette, monkeypatch):
    monkeypatch.setenv("PATH", str(maquette.depot / "nulle-part"))
    etat = maquette.controles.etat_du_depot(maquette.taches)
    assert etat["chantier"]["probleme"] and list(etat["taches"]) == list("ABCDE")
    assert etat["partages"]["fichiers"] == maquette.etat["partages"]["fichiers"]


def test_une_erreur_imprevue_dans_la_lecture_ne_fait_pas_tomber_l_appelant(maquette, monkeypatch):
    def casse(self):
        raise RuntimeError("imprévu")

    monkeypatch.setattr(module_controles._LectureDepot, "lire", casse)
    etat = maquette.controles.etat_du_depot(maquette.taches)
    assert "RuntimeError" in etat["chantier"]["probleme"] and types_permis(etat)
    assert list(etat["taches"]) == list("ABCDE")


# ---------- Critère 8 : la lecture est bornée ----------


def test_chaque_commande_a_un_delai_et_aucune_n_ecrit(maquette, monkeypatch):
    espion = Espion(monkeypatch)
    maquette.controles.etat_du_depot(maquette.taches)
    assert espion.appels
    assert all(0 < a.delai <= DELAI_LECTURE_S for a in espion.appels)
    assert BUDGET_LECTURE_S >= DELAI_LECTURE_S
    assert espion.sous_commandes() <= LECTURES_PERMISES


def douze_taches(dossier):
    depot_de_base(dossier)
    controles = ControlesGit(dossier)
    taches = [tache(f"T{n:02d}", "verifie" if n < 4 else "en_cours") for n in range(12)]
    for t in taches:
        copie = controles.preparer(t)
        for numero in range(3):
            (copie / f"{t.id.lower()}_{numero}.py").write_text("x = 1\n", "utf-8")
        if t.etat == "verifie":
            assert enregistrer(controles, t, copie) == ""
    return controles, taches


def test_le_nombre_de_commandes_par_tache_est_fixe_et_petit(tmp_path, monkeypatch):
    controles, taches = douze_taches(tmp_path)
    espion = Espion(monkeypatch)
    controles.etat_du_depot(taches)
    pour_douze = len(espion.appels)
    espion.appels.clear()
    controles.etat_du_depot(taches[:6])
    pour_six = len(espion.appels)
    espion.appels.clear()
    controles.etat_du_depot([])
    sans_tache = len(espion.appels)
    assert COMMANDES_PAR_TACHE == 4
    # Six tâches de plus coûtent au plus six fois le plafond, quel que soit leur état.
    assert 0 < pour_douze - pour_six <= 6 * COMMANDES_PAR_TACHE
    assert pour_douze <= sans_tache + 12 * COMMANDES_PAR_TACHE
    # Une tâche entrée (sans branche ni copie) ne lance aucune commande.
    espion.appels.clear()
    controles.etat_du_depot(taches[:4])
    assert len(espion.appels) == sans_tache


def test_douze_taches_se_lisent_en_moins_d_une_seconde(tmp_path):
    controles, taches = douze_taches(tmp_path)
    controles.etat_du_depot(taches)  # une première lecture réchauffe les caches du système
    depart = time.perf_counter()
    etat = controles.etat_du_depot(taches)
    duree = time.perf_counter() - depart
    print(f"\nlecture de douze tâches : {duree * 1000:.0f} ms")
    assert duree < 1.0
    assert etat["taches"]["T05"]["modifies"]["nombre"] == 3 and etat["taches"]["T00"]["entree"]


# ---------- Critère 9 : les noms de fichiers tels qu'ils sont sur le disque ----------


@pytest.mark.parametrize("quote_path", ["true", "false"])
def test_les_noms_accentues_espaces_et_guillemets_sont_rendus_tels_quels(tmp_path, quote_path):
    depot_de_base(tmp_path)
    git(tmp_path, "config", "core.quotePath", quote_path)
    controles = ControlesGit(tmp_path)
    copie = controles.preparer(tache("D"))
    for nom in NOMS_SPECIAUX:
        (copie / nom).parent.mkdir(parents=True, exist_ok=True)
        (copie / nom).write_text("neuf\n", "utf-8")
    d = controles.etat_du_depot([tache("D")])["taches"]["D"]
    assert sorted(d["modifies"]["noms"]) == sorted(NOMS_SPECIAUX)
    assert d["modifies"]["nombre"] == len(NOMS_SPECIAUX)
    assert all((copie / nom).exists() for nom in d["modifies"]["noms"])
    assert not any(nom.startswith('"') or "\\3" in nom for nom in d["modifies"]["noms"])


def test_un_fichier_accentue_a_marqueurs_est_nomme_tel_qu_il_est(tmp_path):
    depot_de_base(tmp_path)
    controles = ControlesGit(tmp_path)
    copie = controles.preparer(tache("D"))
    (copie / "docs").mkdir()
    (copie / "docs" / "été.md").write_text("<<<<<<< HEAD\na\n=======\nb\n>>>>>>> main\n", "utf-8")
    d = controles.etat_du_depot([tache("D")])["taches"]["D"]
    assert d["conflits"] == ["docs/été.md"]


def test_un_renommage_accentue_donne_l_ancien_et_le_nouveau_nom(tmp_path):
    depot_de_base(tmp_path)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "été.md").write_text("x\n", "utf-8")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-q", "-m", "docs")
    controles = ControlesGit(tmp_path)
    copie = controles.preparer(tache("D"))
    git(copie, "mv", "docs/été.md", "docs/hiver d'été.md")
    noms = controles.etat_du_depot([tache("D")])["taches"]["D"]["modifies"]["noms"]
    assert sorted(noms) == ["docs/hiver d'été.md", "docs/été.md"]


# ---------- Reprise : une entrée se reconnaît à l'état de la tâche et au message exact ----------


def test_un_enregistrement_d_une_personne_ne_fait_pas_entrer_une_tache_a_lancer(maquette_jetable):
    m = maquette_jetable
    commit_direct(m.depot, "CHANGELOG.md", "- bricolage\n", "E : bricolage d'une personne")
    etat = m.controles.etat_du_depot(m.taches)  # E est « à lancer », sans branche ni copie
    e = etat["taches"]["E"]
    assert e["entree"] is None and e["probleme"] == ""
    assert etat["chantier"]["derniers"][0]["message"] == "E : bricolage d'une personne"
    assert etat["chantier"]["derniers"][0]["tache"] == ""


def test_une_tache_entree_dont_l_enregistrement_manque_n_a_pas_d_entree_devinee(maquette_jetable):
    m = maquette_jetable
    commit_direct(m.depot, "CHANGELOG.md", "- bricolage\n", "E : bricolage d'une personne")
    taches = [*m.taches[:4], tache("E", "verifie")]  # le chantier dit E entrée : git ne le dit pas
    e = m.controles.etat_du_depot(taches)["taches"]["E"]
    assert e["entree"] is None and "introuvable" in e["probleme"]


def test_une_tache_qui_n_est_pas_dite_entree_n_a_jamais_d_entree_quel_que_soit_l_historique(
    maquette_jetable,
):
    m = maquette_jetable
    en_cours = [tache(t.id, "en_cours", t.titre) for t in m.taches]
    etat = m.controles.etat_du_depot(en_cours)
    assert [f["entree"] for f in etat["taches"].values()] == [None] * 5
    assert m.controles.etat_du_depot(m.taches)["taches"]["A"]["entree"] is not None


def test_un_enregistrement_d_une_personne_apres_l_entree_n_est_pas_l_entree(maquette_jetable):
    m = maquette_jetable
    avant = m.controles.etat_du_depot(m.taches)["taches"]["A"]["entree"]
    commit_direct(m.depot, "CHANGELOG.md", "- retouche\n", "A : retouche d'une personne")
    commit_direct(m.depot, "CHANGELOG.md", "- et un\n", "A : Titre de A")  # même message, plus tard
    etat = m.controles.etat_du_depot(m.taches)
    assert etat["taches"]["A"]["entree"] == avant  # le plus ancien enregistrement exact
    derniers = {e["message"]: e["tache"] for e in etat["chantier"]["derniers"]}
    assert derniers["A : retouche d'une personne"] == ""


def test_une_entree_n_est_pas_prise_pour_celle_d_une_tache_dont_l_identifiant_est_un_prefixe(
    tmp_path,
):
    depot_de_base(tmp_path)
    controles = ControlesGit(tmp_path)
    copie = controles.preparer(tache("A"))
    (copie / "a.py").write_text("A = 1\n", "utf-8")
    assert enregistrer(controles, tache("A"), copie) == ""  # A est entrée, A1 ne l'est pas
    taches = [tache("A", "verifie"), tache("A1", "a_lancer"), tache("A2", "verifie")]
    etat = controles.etat_du_depot(taches)
    assert etat["taches"]["A"]["entree"]["message"] == "A : Titre de A"
    assert etat["taches"]["A1"]["entree"] is None and etat["taches"]["A1"]["probleme"] == ""
    assert "introuvable" in etat["taches"]["A2"]["probleme"]  # dite entrée, mais jamais enregistrée
    attribues = {e["message"]: e["tache"] for e in etat["chantier"]["derniers"]}
    assert attribues["A : Titre de A"] == "A" and attribues["Cahier : A enregistrée"] == "A"


def test_l_inverse_aussi_la_tache_a_prefixe_court_n_est_pas_dite_entree_par_l_autre(tmp_path):
    depot_de_base(tmp_path)
    controles = ControlesGit(tmp_path)
    copie = controles.preparer(tache("A1"))
    (copie / "a1.py").write_text("A1 = 1\n", "utf-8")
    assert enregistrer(controles, tache("A1"), copie) == ""
    etat = controles.etat_du_depot([tache("A", "verifie"), tache("A1", "verifie")])
    assert etat["taches"]["A1"]["entree"]["message"] == "A1 : Titre de A1"
    assert etat["taches"]["A"]["entree"] is None and etat["taches"]["A"]["probleme"]
    attribues = {e["message"]: e["tache"] for e in etat["chantier"]["derniers"]}
    assert attribues["Cahier : A1 enregistrée"] == "A1" and attribues["A1 : Titre de A1"] == "A1"


def test_un_titre_qui_contient_deux_points_se_reconnait_entier(tmp_path):
    depot_de_base(tmp_path)
    controles = ControlesGit(tmp_path)
    t = tache("A", "verifie", "Plan : première étape")
    copie = controles.preparer(t)
    (copie / "a.py").write_text("A = 1\n", "utf-8")
    assert enregistrer(controles, t, copie) == ""
    etat = controles.etat_du_depot([t])
    assert etat["taches"]["A"]["entree"]["message"] == "A : Plan : première étape"
    assert etat["taches"]["A"]["entree"]["facon"] == "directe"
    assert etat["chantier"]["derniers"][1]["tache"] == "A"
    # Le titre est lu en entier : avec un autre titre, ce n'est plus le message de l'Atelier.
    autre = controles.etat_du_depot([tache("A", "verifie", "Plan")])
    assert autre["taches"]["A"]["entree"] is None and autre["taches"]["A"]["probleme"]
    assert autre["chantier"]["derniers"][1]["tache"] == ""


def test_la_limite_des_enregistrements_lus_donne_une_phrase_et_non_une_entree_devinee(
    maquette, monkeypatch
):
    monkeypatch.setattr(module_controles, "ENREGISTREMENTS_LUS", 3)
    etat = maquette.controles.etat_du_depot(maquette.taches)
    a = etat["taches"]["A"]
    assert a["entree"] is None and "introuvable" in a["probleme"] and "3" in a["probleme"]
    assert len(etat["chantier"]["derniers"]) == 3
    assert etat["taches"]["D"] == maquette.etat["taches"]["D"]


def test_une_fusion_d_une_personne_n_est_pas_une_fusion_de_l_atelier(tmp_path):
    depot_de_base(tmp_path)
    controles = ControlesGit(tmp_path)
    copie = controles.preparer(tache("A"))
    (copie / "a.py").write_text("A = 1\n", "utf-8")
    assert enregistrer(controles, tache("A"), copie, ligne_de_cahier=False) == ""
    travail = court(tmp_path, "HEAD")  # sans cahier, la tête du chantier est l'enregistrement de A
    git(tmp_path, "checkout", "-q", "-b", "autre", "HEAD~1")
    (tmp_path / "autre.py").write_text("x = 1\n", "utf-8")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-q", "-m", "autre")
    git(tmp_path, "checkout", "-q", "main")
    git(tmp_path, "merge", "-q", "--no-ff", "autre", "-m", "Merge branch 'autre'")
    a = controles.etat_du_depot([tache("A", "verifie")])["taches"]["A"]
    assert a["entree"]["id"] == travail and a["entree"]["facon"] == "directe"


# ---------- Reprise : les noms de git, sans confusion avec un tag ou un fichier ----------


def test_un_tag_du_meme_nom_que_la_branche_d_une_tache_ne_la_fait_pas_disparaitre(
    maquette_jetable,
):
    m = maquette_jetable
    avant = m.controles.etat_du_depot(m.taches)
    git(m.depot, "tag", "tache/D", "HEAD~3")  # même nom que la branche, et un autre commit
    git(m.depot, "tag", "tache/E")  # un tag n'est pas la branche d'une tâche pas encore partie
    etat = m.controles.etat_du_depot(m.taches)
    assert etat["taches"]["D"] == avant["taches"]["D"] and etat["taches"]["D"]["retard"] == 2
    assert etat["taches"]["E"]["branche"]["existe"] is False
    assert etat == avant


def test_un_tag_du_meme_nom_que_la_branche_du_chantier_ne_trouble_pas_la_lecture(maquette_jetable):
    m = maquette_jetable
    avant = m.controles.etat_du_depot(m.taches)
    git(m.depot, "tag", "main", "HEAD~4")
    git(m.depot, "tag", "origin/main", "HEAD~5")
    assert m.controles.etat_du_depot(m.taches) == avant


@pytest.mark.parametrize("nom", ["HEAD", "main", "tache", "origin"])
def test_un_fichier_au_nom_d_une_revision_ne_empeche_pas_la_lecture(maquette_jetable, nom):
    m = maquette_jetable
    avant = m.controles.etat_du_depot(m.taches)
    (m.depot / nom).write_text("un fichier\n", "utf-8")
    assert m.controles.etat_du_depot(m.taches) == avant
    assert avant["chantier"]["dernier"] is not None and avant["en_ligne"]["avance"] == 3


def test_un_delai_de_git_sur_la_branche_ne_se_dit_pas_tete_detachee(maquette_jetable, monkeypatch):
    m = maquette_jetable
    Espion(monkeypatch, lambda a: a[0] == "symbolic-ref", "delai")
    chantier = m.controles.etat_du_depot(m.taches)["chantier"]
    assert chantier["detachee"] is False and chantier["branche"] == ""
    assert "à temps" in chantier["probleme"] and "détachée" not in chantier["probleme"]
    assert chantier["dernier"] is not None  # les enregistrements, eux, se lisent


# ---------- Reprise : une tâche sans identifiant est sautée ----------


def test_une_tache_sans_identifiant_est_sautee_et_la_lecture_ne_leve_rien(tmp_path):
    depot_de_base(tmp_path)
    controles = ControlesGit(tmp_path)
    sans = [
        SimpleNamespace(titre="sans id"), SimpleNamespace(id=None, titre="vide"),
        SimpleNamespace(id="", titre="chaîne vide"), tache("A"),
    ]  # fmt: skip
    etat = controles.etat_du_depot(sans)
    assert list(etat["taches"]) == ["A"] and etat["chantier"]["branche"] == "main"
    assert controles.etat_du_depot(None)["taches"] == {}
    # Même chose quand rien n'est lisible (le chemin de secours, qui lit aussi les tâches).
    controles = ControlesGit(tmp_path)
    shutil.rmtree(tmp_path / ".git")
    etat = controles.etat_du_depot(sans)
    assert list(etat["taches"]) == ["A"] and etat["chantier"]["probleme"]


# ---------- Le double de la démonstration ----------


def forme(valeur):
    """La forme d'un état : les clés de chaque dictionnaire, les listes ramenées à leur contenu."""
    if isinstance(valeur, dict):
        return {k: forme(v) for k, v in valeur.items()}
    return "liste" if isinstance(valeur, list) else type(valeur).__name__


def taches_de_la_demonstration():
    from atelier.__main__ import plan_de_demonstration

    plan, _ = plan_de_demonstration()
    etats = {"A": "verifie", "B": "verifie", "B.1": "en_cours", "C": "en_verification"}
    return [
        Tache(t["id"], t["titre"], perimetre=t["perimetre"], etat=etats.get(t["id"], "a_lancer"))
        for t in plan["taches"]
    ]


def test_le_double_de_la_demonstration_rend_la_meme_forme_sans_git(maquette, monkeypatch):
    def interdit(*arguments, **options):
        raise AssertionError("la démonstration ne lance rien")

    monkeypatch.setattr(module_controles, "lancer_git", interdit)
    monkeypatch.setattr(subprocess, "run", interdit)
    monkeypatch.setattr(subprocess, "Popen", interdit)
    taches = taches_de_la_demonstration()
    etat = ControlesSimules().etat_du_depot(taches)
    assert types_permis(etat) and json.loads(json.dumps(etat)) == etat
    assert set(etat) == set(maquette.etat)
    for cle in ("chantier", "en_ligne", "partages"):
        assert set(etat[cle]) == set(maquette.etat[cle])
    assert set(etat["chantier"]["dernier"]) == set(maquette.etat["chantier"]["dernier"])
    assert set(etat["chantier"]["derniers"][0]) == set(maquette.etat["chantier"]["derniers"][0])
    reel, double = maquette.etat["taches"], etat["taches"]
    for cle in ("branche", "copie", "modifies"):
        assert set(double["B.1"][cle]) == set(reel["D"][cle])
    assert all(set(fiche) == set(reel["D"]) for fiche in double.values())
    assert set(double["B.1"]["depart"]) == set(reel["D"]["depart"])
    assert set(double["A"]["entree"]) == set(reel["A"]["entree"])
    assert list(double) == [t.id for t in taches]


def test_le_double_est_coherent_avec_le_plan_de_demonstration():
    taches = taches_de_la_demonstration()
    etat = ControlesSimules().etat_du_depot(taches)["taches"]
    assert [etat[i]["entree"]["facon"] for i in "AB"] == ["directe", "apres_fusion"]
    assert etat["A"]["entree"]["message"].startswith("A : ")
    assert etat["B.1"]["branche"]["existe"] and etat["B.1"]["copie"]["existe"]
    assert etat["B.1"]["modifies"]["noms"] == ["coeur/b_1.py"] and etat["B.1"]["retard"] == 2
    assert etat["C"]["branche"]["existe"] and etat["D"]["branche"]["existe"] is False
    assert etat["D"]["entree"] is None and etat["D"]["probleme"] == ""
    derniers = ControlesSimules().etat_du_depot(taches)["chantier"]["derniers"]
    assert [e["tache"] for e in derniers] == ["B", "A"]
