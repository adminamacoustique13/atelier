"""L'essai réel lui-même ne tourne qu'avec de vrais agents : ici, ses pièces sans appel."""

import io
import os
import subprocess
import sys

from atelier.controles import se_chevauchent
from atelier.essai import Rapport, creer_projet_d_essai, plan_d_essai, programmes_claude
from atelier.moteur import taches_du_plan


def test_le_rapport_echoue_des_qu_une_etape_echoue_et_s_ecrit_en_markdown():
    rapport = Rapport(sortie=io.StringIO())
    rapport.noter(True, "Une étape", "détail")
    rapport.noter(None, "Une information")
    assert rapport.reussi
    rapport.noter(False, "Une autre")
    assert not rapport.reussi
    texte = rapport.markdown()
    assert "des étapes ont échoué" in texte and "- [ok] Une étape : détail" in texte
    assert "ÉCHEC Une autre" in rapport.sortie.getvalue()


def test_le_plan_d_essai_a_deux_taches_qui_peuvent_tourner_ensemble(tmp_path):
    creer_projet_d_essai(tmp_path / "p", "python3")
    from atelier.projets import lire_profil

    profil = lire_profil(tmp_path / "p")
    taches = taches_du_plan(plan_d_essai("python3"), profil)
    assert [t.id for t in taches] == ["A", "B"]
    assert not se_chevauchent(taches[0].perimetre, taches[1].perimetre)
    assert all((t.modele, t.effort) == ("sonnet", "low") for t in taches)  # petits modèles
    assert profil["commandes"] and "calcul" in profil["commandes"][0]
    propre = subprocess.run(["git", "status", "--porcelain"], cwd=tmp_path / "p",
                            capture_output=True, text=True).stdout  # fmt: skip
    assert propre == ""


def test_les_programmes_claude_sont_cherches_parmi_les_descendants():
    enfant = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(5)  # claude"])
    try:
        assert any(str(enfant.pid) in p for p in programmes_claude(os.getpid()))
    finally:
        enfant.kill()
        enfant.wait()
    assert not any(str(enfant.pid) in p for p in programmes_claude(os.getpid()))


def test_la_commande_essai_existe():
    sortie = subprocess.run([sys.executable, "-m", "atelier", "essai", "--help"],
                            capture_output=True, text=True)  # fmt: skip
    assert sortie.returncode == 0 and "--sans-arret" in sortie.stdout
