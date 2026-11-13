"""La copie gardée, côté contrôles : la reconnaître, et savoir si son contenu a changé.

`ControlesGit.copie_existante`, `empreinte` et `differences`, sur de vrais dépôts git rangés dans
`tmp_path` ; la préparation et le retrait d'une copie qui a disparu ou que git a oubliée ; et les
versions neutres des contrôles simulés, dont héritent les doubles des tests.
"""

import shutil
import subprocess
import threading
from pathlib import Path

import pytest

from atelier.controles import FICHIER_MARQUEURS, MARQUEURS, ControlesGit, ControlesSimules
from atelier.modele import Tache


def git(dossier, *arguments):
    return subprocess.run(
        ["git", *arguments], cwd=dossier, check=True, capture_output=True, text=True
    ).stdout


def nouveau_depot(dossier: Path) -> Path:
    dossier.mkdir(parents=True)
    git(dossier, "init", "-q", "-b", "main")
    git(dossier, "config", "user.name", "Essai")
    git(dossier, "config", "user.email", "essai@example.invalid")
    (dossier / "LISEZMOI.md").write_text("socle\n", "utf-8")
    (dossier / "garde.py").write_text("x = 1\n", "utf-8")
    (dossier / ".gitignore").write_text("*.log\n.atelier/\n", "utf-8")
    git(dossier, "add", "-A")
    git(dossier, "commit", "-q", "-m", "socle")
    return dossier


@pytest.fixture
def depot(tmp_path):
    return nouveau_depot(tmp_path / "projet")


def tache(identifiant="A"):
    return Tache(identifiant, f"Tâche {identifiant}", type="mecanique", perimetre=["*"])


def chemin_de_l_index(copie: Path) -> Path:
    chemin = Path(git(copie, "rev-parse", "--git-path", "index").strip())
    return chemin if chemin.is_absolute() else copie / chemin


def contenu(copie: Path) -> dict[str, bytes]:
    """Tous les fichiers de la copie et leur contenu, le lien `.git` compris."""
    return {
        str(p.relative_to(copie)): p.read_bytes() for p in sorted(copie.rglob("*")) if p.is_file()
    }


# --- copie_existante ------------------------------------------------------------------------


def test_une_copie_preparee_existe_et_rien_d_autre_n_en_est_une(depot, tmp_path):
    controles = ControlesGit(depot)
    copie = controles.preparer(tache())
    assert controles.copie_existante(copie) is True
    assert controles.copie_existante(str(copie)) is True  # le chemin tel que l'état le garde
    assert controles.copie_existante(depot) is False  # le projet lui-même n'est pas une copie
    assert controles.copie_existante("") is False and controles.copie_existante(None) is False
    assert controles.copie_existante(depot / ".atelier" / "arbres" / "B") is False  # absente
    vide = depot / ".atelier" / "arbres" / "C"
    vide.mkdir()
    assert controles.copie_existante(vide) is False  # un dossier que git ne connaît pas
    ailleurs = tmp_path / "ailleurs"
    ailleurs.mkdir()
    assert controles.copie_existante(ailleurs) is False


def test_une_copie_effacee_a_la_main_n_existe_plus(depot):
    controles = ControlesGit(depot)
    copie = controles.preparer(tache())
    shutil.rmtree(copie)
    assert controles.copie_existante(copie) is False


def test_la_copie_d_un_autre_depot_rangee_au_meme_endroit_n_est_pas_reconnue(depot, tmp_path):
    autre = nouveau_depot(tmp_path / "autre")
    intruse = depot / ".atelier" / "arbres" / "A"
    intruse.parent.mkdir(parents=True)
    git(autre, "worktree", "add", "-q", "--detach", str(intruse), "HEAD")
    assert ControlesGit(depot).copie_existante(intruse) is False
    assert ControlesGit(autre).copie_existante(intruse) is False  # pas rangée chez l'autre non plus


# --- empreinte et differences ---------------------------------------------------------------


def test_l_empreinte_ne_change_pas_sans_changement_et_ne_touche_ni_l_index_ni_la_copie(depot):
    controles = ControlesGit(depot)
    copie = controles.preparer(tache())
    (copie / "garde.py").write_text("x = 2\n", "utf-8")  # un travail en cours, non enregistré
    (copie / "neuf.py").write_text("y = 1\n", "utf-8")
    index = chemin_de_l_index(copie)
    index_avant, fichiers_avant = index.read_bytes(), contenu(copie)
    premiere = controles.empreinte(copie)
    seconde = controles.empreinte(copie)
    assert premiere and premiere == seconde
    assert index.read_bytes() == index_avant  # l'index de git est intact
    assert contenu(copie) == fichiers_avant  # rien n'est écrit dans la copie
    assert git(copie, "diff", "--cached", "--name-only") == ""  # rien n'a été indexé
    assert sorted(git(copie, "ls-files", "--others", "--exclude-standard").split()) == ["neuf.py"]


@pytest.mark.parametrize("geste", ["modification", "fichier_nouveau", "suppression"])
def test_l_empreinte_change_avec_le_contenu_et_differences_dit_quels_fichiers(depot, geste):
    controles = ControlesGit(depot)
    copie = controles.preparer(tache())
    avant = controles.empreinte(copie)
    if geste == "modification":
        (copie / "garde.py").write_text("x = 3\n", "utf-8")
        attendus = ["garde.py"]
    elif geste == "fichier_nouveau":  # non suivi par git, et pas ignoré
        (copie / "dossier").mkdir()
        (copie / "dossier" / "neuf.py").write_text("y = 1\n", "utf-8")
        attendus = ["dossier/neuf.py"]
    else:
        (copie / "garde.py").unlink()
        attendus = ["garde.py"]
    apres = controles.empreinte(copie)
    assert apres != avant
    assert controles.differences(copie, avant, apres) == attendus
    assert controles.differences(copie, avant) == attendus  # sans `apres` : la copie maintenant
    assert controles.differences(copie, apres, apres) == []


def test_l_empreinte_revient_avec_le_contenu_et_ignore_les_fichiers_ignores(depot):
    controles = ControlesGit(depot)
    copie = controles.preparer(tache())
    avant = controles.empreinte(copie)
    (copie / "trace.log").write_text("bruit\n", "utf-8")  # ignoré par le projet
    assert controles.empreinte(copie) == avant
    (copie / "garde.py").write_text("x = 9\n", "utf-8")
    assert controles.empreinte(copie) != avant
    (copie / "garde.py").write_text("x = 1\n", "utf-8")  # le contenu d'origine revient
    assert controles.empreinte(copie) == avant
    git(copie, "add", "-A")  # indexer sans rien changer au contenu ne change pas l'empreinte
    assert controles.empreinte(copie) == avant


def test_differences_sans_empreinte_de_depart_ne_compare_rien(depot):
    controles = ControlesGit(depot)
    copie = controles.preparer(tache())
    (copie / "garde.py").write_text("x = 4\n", "utf-8")
    assert controles.differences(copie, "") == []
    assert controles.differences(copie, "", controles.empreinte(copie)) == []


def test_un_renommage_compte_sous_ses_deux_noms(depot):
    controles = ControlesGit(depot)
    copie = controles.preparer(tache())
    avant = controles.empreinte(copie)
    (copie / "garde.py").rename(copie / "renomme.py")
    assert controles.differences(copie, avant) == ["garde.py", "renomme.py"]


# --- préparer et retirer une copie qui a disparu ou que git a oubliée ------------------------


def test_une_copie_effacee_a_la_main_n_empeche_pas_d_en_preparer_une_neuve(depot):
    controles = ControlesGit(depot)
    copie = controles.preparer(tache())
    (copie / "travail.py").write_text("perdu = True\n", "utf-8")
    shutil.rmtree(copie)  # git la croit encore là, et garde la branche de la tâche
    neuve = controles.preparer(tache())
    assert neuve == copie and controles.copie_existante(neuve)
    assert not (neuve / "travail.py").exists()


def test_un_dossier_que_git_ne_connait_pas_est_remplace_ou_retire_sans_lever(depot):
    controles = ControlesGit(depot)
    arbre = depot / ".atelier" / "arbres" / "A"
    arbre.mkdir(parents=True)
    (arbre / "reste.txt").write_text("vieux\n", "utf-8")
    copie = controles.preparer(tache())
    assert copie == arbre and controles.copie_existante(copie)
    assert not (copie / "reste.txt").exists()
    autre = depot / ".atelier" / "arbres" / "B"
    autre.mkdir()
    controles.annuler(tache("B"), autre)  # pas une copie git : retirée quand même
    assert not autre.exists()


def test_annuler_une_copie_gardee_la_retire_et_git_l_oublie(depot):
    controles = ControlesGit(depot)
    copie = controles.preparer(tache())
    (copie / "travail.py").write_text("garde = True\n", "utf-8")
    controles.annuler(tache(), copie)
    assert not copie.exists() and not controles.copie_existante(copie)
    assert git(depot, "worktree", "list", "--porcelain").count("worktree ") == 1


# --- les versions neutres des contrôles simulés ----------------------------------------------


def test_les_controles_simules_ne_gardent_jamais_de_copie(tmp_path):
    controles = ControlesSimules()
    assert controles.copie_existante(tmp_path) is False
    assert controles.empreinte(tmp_path) == ""
    assert controles.differences(tmp_path, "a", "b") == []
    assert controles.differences(tmp_path, "a") == []


# --- seconde passe : chemins impossibles, empreinte qui ne lève jamais, place de la copie -----


def test_copie_existante_ne_leve_jamais_et_lit_le_chemin_resolu(depot):
    controles = ControlesGit(depot)
    copie = controles.preparer(tache())
    racine = depot / ".atelier" / "arbres"
    for cas in ["a\0b", str(copie) + "\0", "a" * 5000, "/", str(racine), str(copie / "sous")]:
        assert controles.copie_existante(cas) is False, repr(cas)
    assert controles.copie_existante(str(racine / "x" / ".." / "A"))  # même dossier, autre écriture
    assert controles.copie_existante(str(copie) + "/")


def test_l_empreinte_ne_leve_jamais_et_rend_vide_quand_elle_ne_sait_pas(depot, tmp_path):
    controles = ControlesGit(depot)
    simple = tmp_path / "simple"
    simple.mkdir()
    for cas in [simple, tmp_path / "absent", Path("a\0b")]:
        assert controles.empreinte(cas) == "", cas  # « inconnue », jamais « inchangée »
    copie = controles.preparer(tache())
    assert controles.differences(copie, "") == []
    assert controles.differences(copie, "0" * 40, "f" * 40) == []  # illisibles : rien de sûr


def test_l_empreinte_ne_leve_pas_pendant_qu_un_autre_fil_ecrit_dans_la_copie(depot):
    controles = ControlesGit(depot)
    copie = controles.preparer(tache())
    fin, rendues, erreurs = threading.Event(), [], []

    def ecrire():
        n = 0
        while not fin.is_set():
            n += 1
            (copie / f"tmp_{n % 7}.txt").write_text(f"{n}\n", "utf-8")
            (copie / "garde.py").write_text(f"x = {n}\n", "utf-8")
            (copie / f"tmp_{(n + 3) % 7}.txt").unlink(missing_ok=True)

    fil = threading.Thread(target=ecrire, daemon=True)
    fil.start()
    try:
        for _ in range(60):
            try:
                rendues.append(controles.empreinte(copie))
            except Exception as erreur:  # la règle : jamais
                erreurs.append(erreur)
    finally:
        fin.set()
        fil.join(10)
    assert erreurs == []
    assert all(e == "" or len(e) == 40 for e in rendues)
    assert len(controles.empreinte(copie)) == 40  # la copie au repos se calcule de nouveau


def test_la_place_de_la_copie_est_celle_que_prepare_l_atelier(depot):
    controles = ControlesGit(depot)
    assert controles.place_de_la_copie(tache()) == controles.preparer(tache())
    assert controles.place_de_la_copie(tache("B")) == depot / ".atelier" / "arbres" / "B"
    assert ControlesSimules().place_de_la_copie(tache()) is None


# --- la liste des marqueurs de conflit : elle survit à un redémarrage, meurt avec la copie ----


JOURNAL = "JOURNAL.md"


def copie_en_conflit(depot):
    """La copie de A, où une fusion de l'Atelier vient de poser des marqueurs dans le journal,
    comme `enregistrer` puis `poser_conflits` le font quand une autre tâche est entrée."""
    (depot / JOURNAL).write_text("début\n", "utf-8")
    git(depot, "add", "-A")
    git(depot, "commit", "-q", "-m", "journal")
    controles = ControlesGit(depot, partages={JOURNAL: "git"})
    copie = controles.preparer(tache())
    (copie / JOURNAL).write_text("début\nligne de A\n", "utf-8")
    git(copie, "add", "-A")
    git(copie, "commit", "-q", "-m", "A")
    (depot / JOURNAL).write_text("début\nligne de B\n", "utf-8")
    git(depot, "commit", "-q", "-am", "B")
    assert controles.poser_conflits(tache(), copie) == {JOURNAL: MARQUEURS}
    assert "<<<<<<< " in (copie / JOURNAL).read_text("utf-8")
    return controles, copie


def fichier_des_marqueurs(copie: Path) -> Path:
    propre = Path(git(copie, "rev-parse", "--git-dir").strip())
    return (propre if propre.is_absolute() else copie / propre) / FICHIER_MARQUEURS


def test_la_liste_des_marqueurs_survit_a_un_redemarrage_hors_des_fichiers_du_projet(depot):
    _, copie = copie_en_conflit(depot)
    liste = fichier_des_marqueurs(copie)
    assert liste.exists() and copie not in liste.parents  # dans le dossier git de la copie
    assert git(copie, "status", "--porcelain").split() == ["M", JOURNAL]  # rien d'autre
    neufs = ControlesGit(depot, partages={JOURNAL: "git"})  # l'Atelier a redémarré
    probleme = neufs.enregistrer(tache(), copie)
    assert probleme.startswith(f"Des marqueurs de conflit restent dans : {JOURNAL}.")
    assert "ligne de A" not in (depot / JOURNAL).read_text("utf-8")  # rien n'est entré
    (copie / JOURNAL).write_text("début\nligne de B\nligne de A\n", "utf-8")  # résolu
    assert ControlesGit(depot, partages={JOURNAL: "git"}).enregistrer(tache(), copie) == ""
    assert "ligne de A" in git(depot, "show", f"HEAD:{JOURNAL}")
    assert not liste.exists()  # le travail est entré : la liste est partie avec la copie


def test_la_liste_des_marqueurs_disparait_quand_la_copie_est_jetee(depot):
    controles, copie = copie_en_conflit(depot)
    liste = fichier_des_marqueurs(copie)
    assert liste.exists()
    controles.annuler(tache(), copie)
    assert not liste.exists() and not copie.exists()
    neuve = controles.preparer(tache())  # même chemin, copie neuve
    assert not fichier_des_marqueurs(neuve).exists()
    # Un fichier du projet qui porte ces signes pour une bonne raison ne bloque pas.
    (neuve / "a_exemple.md").write_text("<<<<<<< HEAD\nexemple\n>>>>>>> autre\n", "utf-8")
    for instance in (controles, ControlesGit(depot, partages={JOURNAL: "git"})):
        assert instance._marqueurs_restants(tache(), neuve) == []
    assert controles.enregistrer(tache(), neuve) == ""
    assert (depot / "a_exemple.md").exists()


@pytest.mark.parametrize(
    "abimee",
    ['["JOURNAL.md"', '{"fichiers": ["JOURNAL.md"]}', "", '["JOURNAL.md", 3]', "null"],
    ids=["tronquee", "pas_une_liste", "vide", "element_qui_n_est_pas_un_texte", "nulle"],
)
def test_une_liste_de_marqueurs_illisible_ne_laisse_rien_entrer_apres_un_redemarrage(depot, abimee):
    _, copie = copie_en_conflit(depot)
    fichier_des_marqueurs(copie).write_text(abimee, "utf-8")
    neufs = ControlesGit(depot, partages={JOURNAL: "git"})  # après un redémarrage
    assert neufs._marqueurs_restants(tache(), copie) is None
    probleme = neufs.enregistrer(tache(), copie)
    assert "illisible" in probleme and "Rien n'entre" in probleme
    assert "<<<<<<< " not in git(depot, "show", f"HEAD:{JOURNAL}")
    assert "ligne de A" not in git(depot, "show", f"HEAD:{JOURNAL}")


def test_une_liste_illisible_n_arrete_pas_l_instance_qui_a_pose_les_marqueurs(depot):
    """Le raccourci en mémoire suffit tant que l'Atelier n'a pas redémarré : la liste abîmée sur
    le disque ne retient pas un travail dont les marqueurs sont connus et résolus."""
    controles, copie = copie_en_conflit(depot)
    fichier_des_marqueurs(copie).write_text("", "utf-8")
    assert controles._marqueurs_restants(tache(), copie) == [JOURNAL]
    (copie / JOURNAL).write_text("début\nligne de B\nligne de A\n", "utf-8")  # résolu
    assert controles.enregistrer(tache(), copie) == ""
    assert "ligne de A" in git(depot, "show", f"HEAD:{JOURNAL}")


def test_sans_liste_ecrite_une_copie_ordinaire_entre_comme_avant(depot):
    controles = ControlesGit(depot)
    copie = controles.preparer(tache())
    (copie / "garde.py").write_text("x = 2\n", "utf-8")
    assert not fichier_des_marqueurs(copie).exists()
    assert ControlesGit(depot)._marqueurs_restants(tache(), copie) == []
    assert ControlesGit(depot).enregistrer(tache(), copie) == ""


def test_conflit_pose_suit_la_copie_et_part_avec_elle(depot):
    ordinaire = ControlesGit(depot)
    simple = ordinaire.preparer(tache("B"))
    assert not ordinaire.conflit_pose(simple)  # une copie sans conflit
    controles, copie = copie_en_conflit(depot)
    assert controles.conflit_pose(copie)
    neufs = ControlesGit(depot, partages={JOURNAL: "git"})  # après un redémarrage
    assert neufs.conflit_pose(copie)
    (copie / JOURNAL).write_text("début\nligne de B\nligne de A\n", "utf-8")  # résolu
    assert controles.conflit_pose(copie)  # résolu ou non, la copie reste marquée
    controles.annuler(tache(), copie)
    assert not controles.conflit_pose(controles.preparer(tache()))  # copie neuve, sans marque


def test_conflit_pose_dit_oui_dans_le_doute_et_non_pour_les_controles_simules(depot, tmp_path):
    assert ControlesGit(depot).conflit_pose(tmp_path / "pas-une-copie") is True
    assert ControlesSimules().conflit_pose(tmp_path) is False
    assert ControlesGit(depot).conflit_pose(None) is False
