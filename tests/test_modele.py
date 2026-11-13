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


# --- M1 : les champs nouveaux, la lecture d'un ancien état, les clés inconnues -----------------

# Un état écrit tel quel par le code d'avant M1 (relevé d'un vrai `Chantier.sauver`) : aucun des
# champs nouveaux, ni `max_cout_usd` au contrat.
ETAT_D_AVANT = {
    "projet": "essai",
    "contrat": {
        "objectif": "Un essai",
        "hors_perimetre": "",
        "max_tentatives": 3,
        "max_montees": 2,
        "plafond_modele": "opus",
        "plafond_effort": "high",
        "zones_rouges": ["Toucher aux secrets"],
        "valide": True,
    },
    "taches": [
        {
            "id": "A",
            "titre": "Première",
            "type": "courante",
            "pourquoi": "",
            "criteres": ["Un critère"],
            "perimetre": ["a.py"],
            "depend_de": [],
            "fournit": "",
            "attend": "",
            "etat": "en_cours",
            "modele": "sonnet",
            "effort": "medium",
            "tentatives": 1,
            "rallonge": 0,
            "relances_auto": 0,
            "montees": 0,
            "ajoutee": False,
            "verdict": "",
            "cout_usd": 0.0,
            "tokens": 0,
            "historique": [{"issue": "refuse"}],
        }
    ],
    "agents_lances": 0,
    "montees": 0,
    "cout_usd": 0.0,
    "tokens": 0,
    "evenements": [{"heure": "05:04:37", "tache": "A", "texte": "Départ", "auteur": "moteur"}],
    "demandes": [],
    "termine": False,
    "session": "",
    "autorisations_chantier": [],
    "debit": {},
    "ouvert_le": "2026-11-13T05:04",
}


def _copie_de_l_etat():
    return json.loads(json.dumps(ETAT_D_AVANT))


def test_un_etat_d_avant_se_charge_avec_les_valeurs_par_defaut(tmp_path):
    chemin = tmp_path / "etat.json"
    chemin.write_text(json.dumps(ETAT_D_AVANT, ensure_ascii=False), "utf-8")
    chantier = Chantier.charger(chemin)
    tache = chantier.tache("A")
    # Ce que l'ancien état disait est lu tel quel...
    assert (tache.titre, tache.etat, tache.tentatives) == ("Première", "en_cours", 1)
    assert tache.historique == [{"issue": "refuse"}]
    assert chantier.contrat.objectif == "Un essai" and chantier.contrat.valide is True
    # ... et chaque champ nouveau prend sa valeur par défaut.
    assert tache.copie == "" and tache.releve == "" and tache.releve_sur == ""
    assert tache.reste == {} and tache.sous_taches == 0 and tache.pannes == 0
    assert chantier.contrat.max_cout_usd == 0


def test_un_etat_rempli_fait_l_aller_et_retour_sans_perte(tmp_path):
    chantier = Chantier.depuis_dict(_copie_de_l_etat())
    tache = chantier.tache("A")
    tache.copie = "/tmp/copies/A"
    tache.reste = {"genre": "local", "points": ["Le point 3"], "fichiers": ["a.py"]}
    tache.sous_taches = 2
    tache.releve = "Il manque un résumé"
    tache.releve_sur = "abc123"
    tache.pannes = 3
    chantier.contrat.max_cout_usd = 12.5
    chemin = tmp_path / "etat.json"
    chantier.sauver(chemin)
    relu = Chantier.charger(chemin)
    assert relu == chantier
    relue = relu.tache("A")
    assert relue.copie == "/tmp/copies/A" and relue.sous_taches == 2 and relue.pannes == 3
    assert relue.reste == {"genre": "local", "points": ["Le point 3"], "fichiers": ["a.py"]}
    assert (relue.releve, relue.releve_sur) == ("Il manque un résumé", "abc123")
    assert relu.contrat.max_cout_usd == 12.5
    # Réécrit une seconde fois : le même texte, rien ne se perd ni ne se déforme.
    second = tmp_path / "second.json"
    relu.sauver(second)
    assert second.read_text("utf-8") == chemin.read_text("utf-8")


@pytest.mark.parametrize("ou", ["chantier", "contrat", "tache"])
def test_une_cle_inconnue_est_ignoree_au_chargement(ou):
    donnees = _copie_de_l_etat()
    cible = {
        "chantier": donnees,
        "contrat": donnees["contrat"],
        "tache": donnees["taches"][0],
    }[ou]
    cible["champ_d_une_version_future"] = {"x": 1}
    chantier = Chantier.depuis_dict(donnees)
    assert chantier.tache("A").titre == "Première"
    assert chantier.contrat.objectif == "Un essai"
    assert "champ_d_une_version_future" not in json.dumps(chantier.en_dict())


def test_une_cle_inconnue_ne_cache_pas_les_cles_connues():
    donnees = _copie_de_l_etat()
    donnees["contrat"].update({"max_cout_usd": 4.0, "inconnue": 1})
    donnees["taches"][0].update({"pannes": 2, "copie": "/c", "inconnue": 1})
    chantier = Chantier.depuis_dict(donnees)
    assert chantier.contrat.max_cout_usd == 4.0
    assert chantier.tache("A").pannes == 2 and chantier.tache("A").copie == "/c"


@pytest.mark.parametrize(
    ("reste", "copie", "sous_taches", "maxi", "attendu"),
    [
        ({"points": ["p"]}, "/c", 0, 2, True),  # les trois conditions
        ({"points": ["p"]}, "/c", 1, 2, True),
        (["p"], "/c", 0, 1, True),  # un reste en liste compte aussi : non vide suffit
        ({}, "/c", 0, 2, False),  # rien ne reste, seul
        ([], "/c", 0, 2, False),
        ({"points": ["p"]}, "", 0, 2, False),  # pas de copie gardée, seul
        ({"points": ["p"]}, "/c", 2, 2, False),  # compte égal à maxi, seul : strictement sous
        ({"points": ["p"]}, "/c", 3, 2, False),  # compte au-dessus de maxi
        ({"points": ["p"]}, "/c", 0, 0, False),  # maxi à 0 : coupé
        ({}, "", 5, 2, False),  # aucune condition
    ],
)
def test_sous_tache_possible_demande_trois_conditions(reste, copie, sous_taches, maxi, attendu):
    tache = modele.Tache(id="A", titre="t", reste=reste, copie=copie, sous_taches=sous_taches)
    assert tache.sous_tache_possible(maxi) is attendu
