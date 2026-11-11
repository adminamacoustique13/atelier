"""La mise à jour d'Atelier, sur de faux dépôts locaux : aucun accès au réseau."""

import os
import subprocess
import threading

import pytest

from atelier import mise_a_jour
from atelier.mise_a_jour import Etat, MiseAJour, MiseAJourSimulee, Resultat

ENV_GIT = {
    "GIT_AUTHOR_NAME": "Essai", "GIT_AUTHOR_EMAIL": "essai@example.org",
    "GIT_COMMITTER_NAME": "Essai", "GIT_COMMITTER_EMAIL": "essai@example.org",
}


def git(dossier, *arguments):
    r = subprocess.run(["git", *arguments], cwd=dossier, capture_output=True, text=True,
                       env=dict(os.environ, **ENV_GIT), timeout=30)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def commit(dossier, nom, texte):
    (dossier / nom).write_text(texte, "utf-8")
    git(dossier, "add", nom)
    git(dossier, "commit", "-q", "-m", f"{nom} {texte}")


class Horloge:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


@pytest.fixture
def depots(tmp_path):
    """Un dépôt nu (le dépôt en ligne), un clone qui joue Atelier, un clone d'un collègue."""
    nu = tmp_path / "en_ligne.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(nu))
    collegue = tmp_path / "collegue"
    git(tmp_path, "clone", "-q", str(nu), str(collegue))
    git(collegue, "checkout", "-q", "-b", "main")
    commit(collegue, "a.txt", "un")
    git(collegue, "push", "-q", "origin", "main")
    atelier = tmp_path / "atelier"
    git(tmp_path, "clone", "-q", str(nu), str(atelier))
    return nu, atelier, collegue


def publier(collegue, nom="b.txt", texte="deux"):
    commit(collegue, nom, texte)
    git(collegue, "push", "-q", "origin", "main")


def instantane(dossier):
    fichiers = {p.name: p.read_text("utf-8") for p in dossier.iterdir() if p.is_file()}
    return (git(dossier, "rev-parse", "HEAD"), git(dossier, "branch", "--show-current"), fichiers)


def maj_avec(dossier, horloge=None, intervalle=3600):
    return MiseAJour(dossier, intervalle_s=intervalle, horloge=horloge or Horloge())


def compter_git(monkeypatch):
    appels = []
    vrai = mise_a_jour._git

    def compteur(dossier, *arguments):
        appels.append(arguments[0])
        return vrai(dossier, *arguments)

    monkeypatch.setattr(mise_a_jour, "_git", compteur)
    return appels


# --- Vérifier -------------------------------------------------------------------------------


def test_a_jour_quand_rien_n_a_avance(depots):
    _, atelier, _ = depots
    assert maj_avec(atelier).verifier() == Etat(False, "Atelier est à jour.", True)


def test_disponible_quand_le_depot_en_ligne_a_avance(depots):
    _, atelier, collegue = depots
    publier(collegue)
    assert maj_avec(atelier).verifier() == Etat(
        True, "Une mise à jour d'Atelier est disponible.", True)


def test_dossier_en_avance_sur_le_depot_en_ligne_n_a_pas_de_mise_a_jour(depots):
    _, atelier, _ = depots
    commit(atelier, "local.txt", "x")
    assert maj_avec(atelier).verifier().disponible is False


def test_histoire_divergente_compte_comme_une_avance_en_ligne(depots):
    _, atelier, collegue = depots
    publier(collegue)
    commit(atelier, "local.txt", "x")
    assert maj_avec(atelier).verifier().disponible is True


def test_verifier_n_ecrit_rien_dans_le_dossier(depots):
    _, atelier, collegue = depots
    publier(collegue)
    avant = instantane(atelier)
    refs = git(atelier, "for-each-ref")
    maj_avec(atelier).verifier()
    assert instantane(atelier) == avant
    assert git(atelier, "for-each-ref") == refs


def test_entre_deux_interrogations_aucun_acces_et_meme_reponse(depots, monkeypatch):
    _, atelier, collegue = depots
    horloge = Horloge()
    maj = maj_avec(atelier, horloge)
    appels = compter_git(monkeypatch)
    premiere = maj.verifier()
    interrogations = len(appels)
    publier(collegue)  # le dépôt en ligne avance, mais l'intervalle n'est pas écoulé
    horloge.t += 3599
    assert maj.verifier() == premiere
    assert len(appels) == interrogations
    horloge.t += 1
    assert maj.verifier().disponible is True
    assert len(appels) > interrogations


def test_premier_appel_interroge_tout_de_suite(depots, monkeypatch):
    _, atelier, _ = depots
    appels = compter_git(monkeypatch)
    maj_avec(atelier).verifier()
    assert "ls-remote" in appels


def test_deux_appels_simultanes_ne_lancent_qu_une_interrogation(depots, monkeypatch):
    _, atelier, _ = depots
    maj = maj_avec(atelier)
    appels = []
    entree, sortie = threading.Event(), threading.Event()
    vrai = mise_a_jour._git

    def lent(dossier, *arguments):
        appels.append(arguments[0])
        entree.set()
        sortie.wait(10)
        return vrai(dossier, *arguments)

    monkeypatch.setattr(mise_a_jour, "_git", lent)
    fil = threading.Thread(target=maj.verifier, daemon=True)
    fil.start()
    assert entree.wait(10)
    pendant = maj.verifier()  # rend tout de suite la réponse connue, sans interroger
    assert pendant.verifie is False
    assert appels == ["ls-remote"]
    sortie.set()
    fil.join(10)
    assert not fil.is_alive()
    assert appels.count("ls-remote") == 1
    assert maj.verifier().verifie is True


def test_depot_injoignable_ne_fait_pas_croire_a_un_atelier_a_jour(depots, monkeypatch):
    _, atelier, _ = depots
    git(atelier, "remote", "set-url", "origin", "http://127.0.0.1:1/rien.git")
    maj = maj_avec(atelier)
    etat = maj.verifier()
    assert etat == Etat(
        False, "Impossible de vérifier pour l'instant : le dépôt en ligne ne répond pas.", False)


def test_echec_garde_la_disponibilite_precedente_et_ne_reessaie_pas(depots, monkeypatch):
    nu, atelier, collegue = depots
    horloge = Horloge()
    maj = maj_avec(atelier, horloge)
    publier(collegue)
    assert maj.verifier().disponible is True
    git(atelier, "remote", "set-url", "origin", str(nu) + ".disparu")
    horloge.t += 3600
    appels = compter_git(monkeypatch)
    etat = maj.verifier()
    assert etat == Etat(
        True, "Impossible de vérifier pour l'instant : le dépôt en ligne est introuvable.", True)
    n = len(appels)
    horloge.t += 3599
    assert maj.verifier() == etat
    assert len(appels) == n


def test_verifier_ne_leve_jamais(depots, monkeypatch):
    _, atelier, _ = depots

    def casse(*_):
        raise RuntimeError("panne")

    maj = maj_avec(atelier)
    monkeypatch.setattr(mise_a_jour, "_git", casse)
    assert maj.verifier().verifie is False


def test_dossier_qui_n_est_pas_un_depot(tmp_path):
    etat = maj_avec(tmp_path / "absent").verifier()
    assert etat.disponible is False and etat.verifie is False
    assert etat.phrase.startswith("Impossible de vérifier pour l'instant")


# --- Mettre à jour --------------------------------------------------------------------------


def test_mise_a_jour_reussie(depots):
    _, atelier, collegue = depots
    publier(collegue)
    maj = maj_avec(atelier)
    assert maj.verifier().disponible is True
    resultat = maj.mettre_a_jour(False)
    assert resultat.fait is True
    assert resultat.phrase == "Atelier a été mis à jour. Il va redémarrer."
    assert (atelier / "b.txt").read_text("utf-8") == "deux"
    assert git(atelier, "rev-parse", "HEAD") == git(collegue, "rev-parse", "HEAD")


def test_apres_une_mise_a_jour_reussie_plus_rien_de_disponible(depots, monkeypatch):
    _, atelier, collegue = depots
    publier(collegue)
    maj = maj_avec(atelier)
    maj.verifier()
    maj.mettre_a_jour(False)
    appels = compter_git(monkeypatch)
    assert maj.verifier() == Etat(False, "Atelier est à jour.", True)
    assert appels == []
    assert maj_avec(atelier).verifier().disponible is False


def test_rien_a_tirer_ne_demande_pas_de_redemarrer(depots):
    _, atelier, _ = depots
    resultat = maj_avec(atelier).mettre_a_jour(False)
    assert (resultat.fait, resultat.phrase) == (False, "Atelier est déjà à jour.")


def test_agent_au_travail_rien_n_est_lance(depots, monkeypatch):
    _, atelier, collegue = depots
    publier(collegue)
    avant = instantane(atelier)

    def interdit(*_, **__):
        raise AssertionError("git lancé malgré un agent au travail")

    monkeypatch.setattr(subprocess, "run", interdit)
    resultat = maj_avec(atelier).mettre_a_jour(True)
    assert resultat == Resultat(
        False, "Mise à jour impossible : un agent travaille. Réessaie quand il aura fini.")
    monkeypatch.undo()
    assert instantane(atelier) == avant


def test_refus_hors_de_la_branche_main(depots):
    _, atelier, collegue = depots
    publier(collegue)
    git(atelier, "checkout", "-q", "-b", "autre")
    avant = instantane(atelier)
    resultat = maj_avec(atelier).mettre_a_jour(False)
    assert resultat.fait is False
    assert resultat.phrase == (
        "Mise à jour impossible : le dossier d'Atelier n'est pas sur la branche main.")
    assert instantane(atelier) == avant


def test_refus_en_tete_detachee(depots):
    _, atelier, _ = depots
    git(atelier, "checkout", "-q", "--detach")
    resultat = maj_avec(atelier).mettre_a_jour(False)
    assert resultat.fait is False
    assert "n'est pas sur la branche main" in resultat.phrase


def test_refus_avec_modifications_locales_de_fichiers_suivis(depots):
    _, atelier, collegue = depots
    publier(collegue)
    (atelier / "a.txt").write_text("modifié ici", "utf-8")
    avant = instantane(atelier)
    resultat = maj_avec(atelier).mettre_a_jour(False)
    assert resultat.fait is False
    assert resultat.phrase == (
        "Mise à jour impossible : le dossier d'Atelier contient des modifications "
        "qui ne viennent pas du dépôt en ligne.")
    assert instantane(atelier) == avant


def test_un_fichier_non_suivi_ne_bloque_pas(depots):
    _, atelier, collegue = depots
    publier(collegue)
    (atelier / "brouillon.txt").write_text("à moi", "utf-8")
    assert maj_avec(atelier).mettre_a_jour(False).fait is True
    assert (atelier / "brouillon.txt").read_text("utf-8") == "à moi"


def test_histoire_divergee_laisse_le_dossier_intact(depots):
    _, atelier, collegue = depots
    publier(collegue)
    commit(atelier, "local.txt", "x")
    avant = instantane(atelier)
    resultat = maj_avec(atelier).mettre_a_jour(False)
    assert resultat.fait is False
    assert resultat.phrase == (
        "Mise à jour impossible : l'histoire du dossier d'Atelier a divergé de celle "
        "du dépôt en ligne.")
    assert instantane(atelier) == avant
    assert git(atelier, "status", "--porcelain") == ""


def test_depot_en_ligne_introuvable_laisse_le_dossier_intact(depots):
    nu, atelier, _ = depots
    git(atelier, "remote", "set-url", "origin", str(nu) + ".disparu")
    avant = instantane(atelier)
    resultat = maj_avec(atelier).mettre_a_jour(False)
    assert resultat.fait is False
    assert resultat.phrase == "Mise à jour impossible : le dépôt en ligne est introuvable."
    assert instantane(atelier) == avant


def test_reseau_coupe_laisse_le_dossier_intact_et_le_journal_sans_identifiant(depots):
    _, atelier, _ = depots
    git(atelier, "remote", "set-url", "origin", "http://nom:secret@127.0.0.1:1/rien.git")
    avant = instantane(atelier)
    resultat = maj_avec(atelier).mettre_a_jour(False)
    assert resultat.fait is False
    assert resultat.phrase == "Mise à jour impossible : le dépôt en ligne ne répond pas."
    assert instantane(atelier) == avant
    assert "secret" not in resultat.detail and "nom:" not in resultat.detail


def test_mettre_a_jour_ne_leve_jamais(tmp_path):
    resultat = maj_avec(tmp_path / "absent").mettre_a_jour(False)
    assert resultat.fait is False
    assert resultat.phrase.startswith("Mise à jour impossible")


# --- Git ne bloque jamais -------------------------------------------------------------------


def test_chaque_appel_git_est_borne_sans_shell_ni_saisie(depots, monkeypatch):
    _, atelier, collegue = depots
    publier(collegue)
    vus = []
    vrai = subprocess.run

    def espion(commande, **options):
        vus.append((commande, options))
        return vrai(commande, **options)

    monkeypatch.setattr(subprocess, "run", espion)
    maj = maj_avec(atelier)
    maj.verifier()
    maj.mettre_a_jour(False)
    assert vus
    for commande, options in vus:
        assert isinstance(commande, list) and commande[0] == "git"
        assert not options.get("shell")
        assert 0 < options["timeout"] <= 120
        assert options["stdin"] == subprocess.DEVNULL
        assert options["env"]["GIT_TERMINAL_PROMPT"] == "0"
        assert options["env"]["GIT_EDITOR"] == "true"


def test_git_qui_ne_repond_pas_est_coupe(depots, monkeypatch):
    _, atelier, _ = depots

    def lent(commande, **options):
        raise subprocess.TimeoutExpired(commande, options["timeout"])

    monkeypatch.setattr(subprocess, "run", lent)
    maj = maj_avec(atelier)
    assert maj.verifier().phrase == (
        "Impossible de vérifier pour l'instant : le dépôt en ligne ne répond pas.")
    assert maj.mettre_a_jour(False).phrase.startswith("Mise à jour impossible")


# --- Le double simulé -----------------------------------------------------------------------


def test_double_simule_annonce_une_mise_a_jour_et_reussit_sans_git(monkeypatch):
    def interdit(*_, **__):
        raise AssertionError("git ou réseau lancé par le double")

    monkeypatch.setattr(subprocess, "run", interdit)
    monkeypatch.setattr(mise_a_jour, "_git", interdit)
    simulee = MiseAJourSimulee()
    assert simulee.verifier() == Etat(True, "Une mise à jour d'Atelier est disponible.", True)
    assert simulee.mettre_a_jour(False) == Resultat(
        True, "Mise à jour simulée : rien n'a changé.")
    assert simulee.mettre_a_jour(True).fait is False
