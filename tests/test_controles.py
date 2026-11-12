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


def test_les_fichiers_fabriques_par_les_tests_ne_sortent_pas_du_perimetre(tmp_path):
    """Constaté au premier essai réel : pytest créait un __pycache__, compté hors périmètre,
    puis enregistré avec la tâche quand c'est le vérificateur qui l'avait créé."""
    from atelier.controles import hors_perimetre
    from atelier.projets import exclure_etat

    depot_d_essai(tmp_path)
    (tmp_path / ".git" / "info" / "exclude").write_text("# mes réglages\n*.log\n", "utf-8")
    exclure_etat(tmp_path)
    exclure_etat(tmp_path)  # une seconde ouverture n'ajoute rien
    exclusions = (tmp_path / ".git" / "info" / "exclude").read_text("utf-8")
    assert exclusions.startswith("# mes réglages\n*.log\n")
    assert exclusions.count("__pycache__/") == 1

    controles = ControlesGit(tmp_path)
    tache = SimpleNamespace(id="A", titre="Calcul")
    dossier = controles.preparer(tache)
    (dossier / "calcul.py").write_text("x = 1\n", "utf-8")
    fabriques = ("__pycache__/calcul.cpython-313.pyc", ".pytest_cache/v/x", "node_modules/a.js")
    for fabrique in fabriques:
        (dossier / fabrique).parent.mkdir(parents=True, exist_ok=True)
        (dossier / fabrique).write_text("fabriqué", "utf-8")
    modifies = controles.fichiers_modifies(tache, dossier, None)
    assert modifies == ["calcul.py"] and hors_perimetre(modifies, ["calcul.py"]) == []

    controles.enregistrer(tache, dossier)
    suivis = subprocess.run(["git", "ls-files"], cwd=tmp_path, capture_output=True, text=True)
    assert suivis.stdout.split() == ["LISEZMOI.md", "calcul.py"]


def test_la_copie_du_verificateur_montre_le_livrable_et_n_atteint_rien(tmp_path):
    from atelier.projets import exclure_etat

    def git(dossier, *arguments):
        return subprocess.run(["git", *arguments], cwd=dossier, capture_output=True,
                              text=True, check=True).stdout  # fmt: skip

    depot_d_essai(tmp_path)
    (tmp_path / "ancien.py").write_text("a = 1\n", "utf-8")
    (tmp_path / ".gitignore").write_text("node_modules/\n.env\n", "utf-8")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-q", "-m", "base")
    exclure_etat(tmp_path)
    controles = ControlesGit(tmp_path)
    tache = SimpleNamespace(id="A", titre="Calcul")
    dossier = controles.preparer(tache)
    (dossier / "LISEZMOI.md").write_text("socle modifié\n", "utf-8")
    (dossier / "src").mkdir()
    (dossier / "src" / "nouveau.py").write_text("b = 2\n", "utf-8")
    (dossier / "ancien.py").unlink()
    (dossier / "node_modules" / "lib").mkdir(parents=True)
    (dossier / "node_modules" / "lib" / "index.js").write_text("x", "utf-8")
    (dossier / ".env").write_text("CLE=1\n", "utf-8")
    (dossier / "__pycache__").mkdir()
    (dossier / "__pycache__" / "a.pyc").write_text("x", "utf-8")

    copie = controles.copie_de_verification(tache, dossier)
    assert copie != dossier and copie.is_dir()
    # Le même livrable, vu de la même façon par git.
    assert git(copie, "status", "--porcelain") == git(dossier, "status", "--porcelain")
    assert git(copie, "diff") == git(dossier, "diff")
    # Les dépendances installées sont reliées, les caches non.
    assert (copie / "node_modules" / "lib").is_symlink() and (copie / ".env").is_symlink()
    assert (copie / "node_modules" / "lib" / "index.js").read_text() == "x"
    assert not (copie / "__pycache__").exists()

    # Ses essais n'atteignent pas la copie de l'ouvrier, ni ce qui est enregistré.
    (copie / "src" / "nouveau.py").write_text("b = 'muté'\n", "utf-8")
    (copie / "essai.py").write_text("print(1)\n", "utf-8")
    controles.jeter_copie(copie)
    assert not copie.exists() and str(copie) not in git(tmp_path, "worktree", "list")
    assert (dossier / "src" / "nouveau.py").read_text() == "b = 2\n"
    controles.enregistrer(tache, dossier)
    assert "essai.py" not in git(tmp_path, "ls-files").split()
    assert (tmp_path / "src" / "nouveau.py").read_text() == "b = 2\n"

    # Une copie laissée par un arrêt brutal est remplacée à la vérification suivante.
    dossier = controles.preparer(SimpleNamespace(id="B"))
    premiere = controles.copie_de_verification(SimpleNamespace(id="B"), dossier)
    (premiere / "reste.txt").write_text("x", "utf-8")
    seconde = controles.copie_de_verification(SimpleNamespace(id="B"), dossier)
    assert seconde == premiere and not (seconde / "reste.txt").exists()
    controles.jeter_copie(seconde)


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
