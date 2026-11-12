import subprocess
import threading
import time
from types import SimpleNamespace

from atelier.controles import ControlesGit

FILS = 3
TOURS = 6
PAUSE_WORKTREE = 0.02  # ralentit chaque commande « git worktree » pour rendre la collision certaine
DELAI_MAXIMUM = 30  # secondes : le test échoue plutôt que de bloquer


def depot_d_essai(dossier):
    def git(*arguments):
        subprocess.run(["git", *arguments], cwd=dossier, check=True, capture_output=True)

    git("init", "-q", "-b", "main")
    git("config", "user.name", "Essai")
    git("config", "user.email", "essai@example.invalid")
    (dossier / "LISEZMOI.md").write_text("socle\n", "utf-8")
    git("add", "-A")
    git("commit", "-q", "-m", "socle")


def ralentir_les_commandes_worktree(controles):
    """Double de `_git` : ralentit `git worktree` et note combien tournent en même temps."""
    reel = controles._git
    etat = SimpleNamespace(en_cours=0, maximum=0, verrou=threading.Lock())

    def _git(*arguments, **options):
        if arguments[0] != "worktree":
            return reel(*arguments, **options)
        with etat.verrou:
            etat.en_cours += 1
            etat.maximum = max(etat.maximum, etat.en_cours)
        try:
            time.sleep(PAUSE_WORKTREE)
            return reel(*arguments, **options)
        finally:
            with etat.verrou:
                etat.en_cours -= 1

    controles._git = _git
    return etat


def test_preparer_et_annuler_en_parallele_ne_se_marchent_pas_dessus(tmp_path):
    depot_d_essai(tmp_path)
    controles = ControlesGit(tmp_path)
    etat = ralentir_les_commandes_worktree(controles)
    erreurs = []

    def tache_du_fil(numero):
        tache = SimpleNamespace(id=f"T{numero}")
        try:
            for tour in range(TOURS):
                dossier = controles.preparer(tache)
                assert dossier.is_dir()
                # Un tour sur deux, l'arbre est laissé là : la préparation suivante le retire.
                if tour % 2 == 0:
                    controles.annuler(tache, dossier)
        except Exception as erreur:  # toute erreur d'un fil doit être rapportée
            erreurs.append(f"T{numero} : {erreur}")

    fils = [
        threading.Thread(target=tache_du_fil, args=(numero,), daemon=True)
        for numero in range(FILS)
    ]
    for fil in fils:
        fil.start()
    limite = time.monotonic() + DELAI_MAXIMUM
    for fil in fils:
        fil.join(max(0.0, limite - time.monotonic()))

    assert not any(fil.is_alive() for fil in fils), "un fil est bloqué (interblocage ?)"
    assert erreurs == []
    # Toute commande « git worktree » passe par le verrou de fusion : jamais deux à la fois.
    assert etat.maximum == 1
    assert not controles.verrou_fusion.locked()


def test_annuler_sans_arbre_ne_fait_rien_et_ne_garde_pas_le_verrou(tmp_path):
    depot_d_essai(tmp_path)
    controles = ControlesGit(tmp_path)
    tache = SimpleNamespace(id="A")

    controles.annuler(tache, None)
    controles.annuler(tache, tmp_path / "absent")
    assert not controles.verrou_fusion.locked()

    dossier = controles.preparer(tache)
    assert not controles.verrou_fusion.locked()
    controles.annuler(tache, dossier)
    assert not dossier.exists()
    assert not controles.verrou_fusion.locked()


def test_preparer_remplace_un_ancien_arbre_sans_garder_le_verrou(tmp_path):
    depot_d_essai(tmp_path)
    controles = ControlesGit(tmp_path)
    tache = SimpleNamespace(id="A")

    premier = controles.preparer(tache)
    (premier / "reste.txt").write_text("à jeter\n", "utf-8")
    second = controles.preparer(tache)

    assert second == premier
    assert not (second / "reste.txt").exists()
    assert not controles.verrou_fusion.locked()


# --- l'intégration contrôlée avant d'entrer dans la branche principale ---------------------


def _git(dossier, *arguments):
    return subprocess.run(
        ["git", *arguments], cwd=dossier, check=True, capture_output=True, text=True
    ).stdout


def _tache(identifiant):
    return SimpleNamespace(id=identifiant, titre=f"Tâche {identifiant}")


def test_une_tache_entre_seule_sans_rejouer_les_controles(tmp_path):
    depot_d_essai(tmp_path)
    controles = ControlesGit(tmp_path, commandes=["test -f a.py"])
    dossier = controles.preparer(_tache("A"))
    (dossier / "a.py").write_text("a\n", "utf-8")
    appels = []
    reel = controles.mecaniques
    controles.mecaniques = lambda t, d: (appels.append(d), reel(t, d))[1]
    assert controles.enregistrer(_tache("A"), dossier) == ""
    assert appels == []  # la branche principale n'a pas bougé : rien à rejouer
    assert (tmp_path / "a.py").exists() and not dossier.exists()


def test_deux_taches_sures_seules_mais_rouges_ensemble_n_entrent_pas_toutes_deux(tmp_path):
    depot_d_essai(tmp_path)
    # Le contrôle ne passe que si a.py et b.py ne sont pas là en même temps.
    controles = ControlesGit(tmp_path, commandes=["test ! -f a.py -o ! -f b.py"])
    a, b = controles.preparer(_tache("A")), controles.preparer(_tache("B"))
    (a / "a.py").write_text("a\n", "utf-8")
    (b / "b.py").write_text("b\n", "utf-8")
    assert controles.enregistrer(_tache("A"), a) == ""
    probleme = controles.enregistrer(_tache("B"), b)
    assert probleme.startswith("Les contrôles échouent une fois ce travail mêlé")
    assert (tmp_path / "a.py").exists() and not (tmp_path / "b.py").exists()
    assert "B : Tâche B" not in _git(tmp_path, "log", "--format=%s")
    controles.annuler(_tache("B"), b)  # le moteur jette la tentative, comme pour tout refus
    assert not b.exists()


def test_un_conflit_avec_la_branche_principale_est_rendu_sans_rien_casser(tmp_path):
    depot_d_essai(tmp_path)
    controles = ControlesGit(tmp_path)
    a, b = controles.preparer(_tache("A")), controles.preparer(_tache("B"))
    (a / "LISEZMOI.md").write_text("version A\n", "utf-8")
    (b / "LISEZMOI.md").write_text("version B\n", "utf-8")
    assert controles.enregistrer(_tache("A"), a) == ""
    probleme = controles.enregistrer(_tache("B"), b)
    assert probleme.startswith("Conflit avec la branche principale")
    assert (tmp_path / "LISEZMOI.md").read_text("utf-8") == "version A\n"
    assert _git(b, "status", "--porcelain").strip() == ""  # la fusion ratée est défaite
    assert _git(tmp_path, "status", "--porcelain", "--untracked-files=no").strip() == ""


def test_la_branche_principale_se_controle_dans_une_copie_propre(tmp_path):
    depot_d_essai(tmp_path)
    commandes = ["test ! -f brouillon.txt", "test -f LISEZMOI.md"]
    controles = ControlesGit(tmp_path, commandes=commandes)
    (tmp_path / "brouillon.txt").write_text("pas enregistré\n", "utf-8")
    assert controles.controler_principale()[0] is True  # le brouillon non enregistré n'y est pas
    controles.commandes = ["test -f absent.txt"]
    passe, sortie = controles.controler_principale()
    assert not passe and "$ test -f absent.txt" in sortie
    assert not (tmp_path / ".atelier" / "arbres" / "_principale").exists()
    assert "arbres/_principale" not in _git(tmp_path, "worktree", "list")
    assert ControlesGit(tmp_path).controler_principale() == (True, "")  # sans commande
