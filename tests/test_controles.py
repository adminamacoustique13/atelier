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
