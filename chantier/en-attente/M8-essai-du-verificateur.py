"""Seconde vérification de M8 (B1) : la liste des fichiers à marqueurs, écrite dans le dossier git
de la copie (`.git/worktrees/<tâche>/atelier-marqueurs.json`), tient-elle quand on la malmène ?

Même chemin que `test_marqueurs_redemarrage.py` : conflit posé dans la copie, reprise qui ne le
résout pas et casse les contrôles, copie gardée, Atelier coupé ; entre la coupure et le
redémarrage, `entre_temps(depot, copie)` malmène la copie ou sa liste. Après le redémarrage,
l'ouvrier répare les contrôles sans résoudre le conflit et le vérificateur valide."""

import os
import threading
from pathlib import Path

import pytest
from outils import Agent, Controles, creer_depot, fil, git, monter, tache

from atelier.controles import ControlesGit
from atelier.modele import Chantier
from atelier.moteur import RELANCER_TEL, Moteur

JOURNAL = "JOURNAL.md"
PROFIL = {"fichiers_partages": [{"motif": JOURNAL, "fusion": "git"}]}
COMMANDES = ["test -f a_ok.txt"]


def liste(depot):
    return depot / ".git" / "worktrees" / "A" / "atelier-marqueurs.json"


def jusqu_au_redemarrage(tmp_path, entre_temps, ouvrier2=None):
    depot = creer_depot(tmp_path, {JOURNAL: "début\n"})
    etat = tmp_path / "etat.json"
    coupe, fige = threading.Event(), threading.Event()

    def ouvrier(p):
        d = p["dossier"]
        if p["rang"] == 1:
            (d / JOURNAL).write_text("début\nligne de A\n", "utf-8")
            (d / "a_ok.txt").write_text("ok\n", "utf-8")
        elif p["reprendre"] is not None:
            (d / "a_ok.txt").unlink(missing_ok=True)
        else:
            coupe.set()
            fige.wait()
            raise SystemExit

    def verif(p):
        if p["rang"] == 1:
            (depot / JOURNAL).write_text("début\nligne de B\n", "utf-8")
            git(depot, "commit", "-q", "-am", "B : une autre tâche est entrée")
        return True

    agent = Agent(ouvrier, verif)
    c, m, controles = monter(
        depot, [tache(perimetre=("a_*", JOURNAL))], agent, COMMANDES, PROFIL, etat, max_tentatives=4
    )
    threading.Thread(target=m.executer, daemon=True).start()
    assert coupe.wait(30)
    copie = agent.passages[-1]["dossier"]
    assert "<<<<<<< " in (copie / JOURNAL).read_text("utf-8") and liste(depot).is_file()
    entre_temps(depot, copie)
    relu = Chantier.charger(etat)

    def defaut(p):
        (p["dossier"] / "a_ok.txt").write_text("ok\n", "utf-8")

    agent2 = Agent(ouvrier2 or defaut, lambda p: True)
    m2 = Moteur(relu, agent2, Controles(depot, COMMANDES, PROFIL), profil=PROFIL)
    a = relu.tache("A")
    if a.etat == "revenu":
        m2.repondre(relu.demandes[-1]["id"], RELANCER_TEL)
    m2.executer()
    reprise = bool(agent2.passages) and agent2.passages[0]["dossier"] == copie
    return depot, relu, reprise, git(depot, "show", f"HEAD:{JOURNAL}")


def illisible(depot, copie):
    liste(depot).write_text('["JOURNAL.md"', "utf-8")  # JSON abîmé


def pas_une_liste(depot, copie):
    liste(depot).write_text('{"fichiers": ["JOURNAL.md"]}', "utf-8")


def vide_(depot, copie):
    liste(depot).write_text("", "utf-8")


def sans_droit(depot, copie):
    os.chmod(liste(depot), 0)


def effacee(depot, copie):
    liste(depot).unlink()


def repair(depot, copie):
    git(depot, "worktree", "repair")
    git(depot, "worktree", "prune")
    git(copie, "worktree", "repair")


def rien(depot, copie):
    pass


@pytest.mark.parametrize("entre_temps", [rien, repair, illisible, pas_une_liste, vide_, sans_droit,
                                         effacee], ids=lambda f: f.__name__)  # fmt: skip
def test_liste_malmenee_les_marqueurs_n_entrent_pas(tmp_path, entre_temps):
    if entre_temps is sans_droit and os.geteuid() == 0:
        pytest.skip("root lit tout")
    depot, c, reprise, journal = jusqu_au_redemarrage(tmp_path, entre_temps)
    print(entre_temps.__name__, "| copie reprise :", reprise, "| état :", c.tache("A").etat,
          "| marqueurs dans main :", "<<<<<<< " in journal)  # fmt: skip
    assert "<<<<<<< " not in journal, "des marqueurs de conflit sont entrés dans main"


def test_fichier_a_marqueurs_renomme_par_l_ouvrier(tmp_path):
    def ouvrier2(p):
        d = p["dossier"]
        (d / "a_ok.txt").write_text("ok\n", "utf-8")
        (d / "a_journal_bis.md").write_text((d / JOURNAL).read_text("utf-8"), "utf-8")
        git(d, "checkout", "-q", "--", JOURNAL)  # JOURNAL.md rendu propre, marqueurs déplacés

    depot, c, reprise, journal = jusqu_au_redemarrage(tmp_path, rien, ouvrier2)
    bis = depot / "a_journal_bis.md"
    assert not (bis.exists() and "<<<<<<< " in bis.read_text("utf-8")), "marqueurs entrés sous un autre nom"


def test_deux_fusions_de_suite_sur_la_meme_copie(tmp_path):
    depot = creer_depot(tmp_path, {"x.md": "x\n", "y.md": "y\n"})
    controles = ControlesGit(depot, partages={"x.md": "git", "y.md": "git"})
    t = tache(perimetre=("x.md", "y.md"))
    d = controles.preparer(t)
    (d / "x.md").write_text("x de A\n")
    (depot / "x.md").write_text("x de B\n")
    git(depot, "commit", "-qam", "B1")
    assert "Conflit" in controles.enregistrer(t, d)
    assert controles.poser_conflits(t, d) == {"x.md": "marqueurs"}
    assert "x.md" in controles.enregistrer(t, d)  # marqueurs restants : arrêté
    (d / "x.md").write_text("x résolu\n")
    (d / "y.md").write_text("y de A\n")
    (depot / "y.md").write_text("y de B\n")
    git(depot, "commit", "-qam", "B2")
    assert "Conflit" in controles.enregistrer(t, d)
    assert controles.poser_conflits(t, d) == {"y.md": "marqueurs"}
    neufs = ControlesGit(depot, partages={"x.md": "git", "y.md": "git"})  # comme après un redémarrage
    print("liste :", liste(depot).read_text())
    assert "y.md" in neufs.enregistrer(t, d)
    (d / "x.md").write_text("<<<<<<< revenu\n")  # x.md n'est plus dans la liste : est-il encore gardé ?
    (d / "y.md").write_text("y résolu\n")
    probleme = neufs.enregistrer(t, d)
    print("x.md à marqueurs après la seconde fusion :", repr(probleme[:80]))
