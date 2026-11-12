"""Tests de l'écriture d'un seul geste (atelier/modele.py)."""

import json

import pytest

from atelier import modele
from atelier.modele import Chantier, Contrat, ecrire_d_un_seul_geste


def test_ecrit_le_texte_tel_quel_et_cree_le_dossier(tmp_path):
    chemin = tmp_path / "dossier" / "neuf" / "fichier.json"
    ecrire_d_un_seul_geste(chemin, "Été « là »\nfin")
    assert chemin.read_bytes() == "Été « là »\nfin".encode()
    assert [f.name for f in chemin.parent.iterdir()] == ["fichier.json"]


def test_remplace_l_ancien_fichier_sans_rien_laisser_a_cote(tmp_path):
    chemin = tmp_path / "fichier.json"
    chemin.write_text("ancien texte bien plus long que le nouveau", "utf-8")
    ecrire_d_un_seul_geste(chemin, "neuf")
    assert chemin.read_text("utf-8") == "neuf"
    assert [f.name for f in tmp_path.iterdir()] == ["fichier.json"]


def test_une_mise_en_place_qui_echoue_laisse_l_ancien_fichier_intact(tmp_path, monkeypatch):
    chemin = tmp_path / "fichier.json"
    chemin.write_text("ancien", "utf-8")

    def coupure(source, cible):
        raise OSError("disque plein")

    monkeypatch.setattr(modele.os, "replace", coupure)
    with pytest.raises(OSError):
        ecrire_d_un_seul_geste(chemin, "neuf")
    assert chemin.read_text("utf-8") == "ancien"
    assert [f.name for f in tmp_path.iterdir()] == ["fichier.json"]


def test_une_ecriture_coupee_en_route_laisse_l_ancien_fichier_intact(tmp_path):
    chemin = tmp_path / "fichier.json"
    chemin.write_text("ancien", "utf-8")
    with pytest.raises(UnicodeEncodeError):  # un caractère impossible à écrire, au milieu
        ecrire_d_un_seul_geste(chemin, "début " * 5000 + "\udcff" + " fin")
    assert chemin.read_text("utf-8") == "ancien"
    assert [f.name for f in tmp_path.iterdir()] == ["fichier.json"]


def test_le_chantier_est_sauve_par_l_ecriture_d_un_seul_geste(tmp_path, monkeypatch):
    chantier = Chantier(projet="Café", contrat=Contrat(objectif="Écrire"))
    chemin = tmp_path / ".atelier" / "etat.json"
    chantier.sauver(chemin)
    attendu = json.dumps(chantier.en_dict(), ensure_ascii=False, indent=2)
    assert chemin.read_bytes() == attendu.encode()  # pas de saut de ligne final, comme avant

    appels = []
    monkeypatch.setattr(modele, "ecrire_d_un_seul_geste", lambda *a: appels.append(a))
    chantier.sauver(chemin)
    assert appels == [(chemin, attendu)]
