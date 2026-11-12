"""Les chantiers archivés : nom, dates, journal de ce qui a été livré ou non."""

import json

from atelier import archives
from atelier.modele import Chantier, Contrat, Tache


def chantier_type():
    c = Chantier(projet="essai", contrat=Contrat(objectif="Moteur de calcul", valide=True))
    c.ouvert_le = "2026-11-10T09:05"
    livree = Tache(id="A", titre="Lecture des données", etat="verifie", modele="opus",
                   effort="high", tentatives=2)  # fmt: skip
    livree.historique = [
        {"tentative": 1, "modele": "sonnet", "effort": "medium", "issue": "bacle", "detail": ""},
        {"tentative": 2, "modele": "opus", "effort": "high", "issue": "valide", "detail": ""},
    ]
    revenue = Tache(id="B", titre="Formule", etat="revenu", tentatives=3)
    c.taches = [livree, revenue, Tache(id="C", titre="Tests", etat="a_lancer"),
                Tache(id="D", titre="Export", etat="abandonnee")]  # fmt: skip
    c.demandes = [
        {"id": "B-1", "tache": "B", "question": "Tâche B, « Formule » : le plafond est atteint.",
         "options": [], "reponse": None},
        {"id": "D-2", "tache": "D", "question": "Tâche D, « Export » : arrêtée par toi.",
         "options": [], "reponse": "Abandonner cette tâche"},
    ]  # fmt: skip
    c.agents_lances, c.montees, c.cout_usd = 9, 1, 1.5
    c.noter("Fais-moi un moteur de calcul", auteur="toi")
    c.noter("Voici le découpage.", auteur="orchestrateur")
    c.noter("Vérifiée et enregistrée.", tache="A")
    return c


def test_date_fr():
    assert archives.date_fr("2026-11-12T09:41") == "12 novembre 2026 à 9 h 41"
    assert archives.date_fr("2026-08-01T14:05") == "1 août 2026 à 14 h 05"
    assert archives.date_fr("") == "" and archives.date_fr(None) == ""


def test_le_nom_est_nettoye_et_borne():
    assert archives.nettoyer_nom("  Un\nnom\t avec  espaces ") == "Un nom avec espaces"
    assert len(archives.nettoyer_nom("x" * 200)) == 80
    assert archives.nettoyer_nom(None) == "" and archives.nettoyer_nom(12) == ""


def test_le_nom_propose_vient_de_l_objectif_puis_du_premier_message_puis_de_la_date():
    c = chantier_type()
    assert archives.nom_propose(c) == "Moteur de calcul"
    c.contrat.objectif = ""
    assert archives.nom_propose(c) == "Fais-moi un moteur de calcul"
    c.evenements = []
    assert archives.nom_propose(c) == "Chantier du 10 novembre 2026"
    c.ouvert_le = ""
    assert archives.nom_propose(c) == "Chantier sans nom"
    c.contrat.objectif = "y" * 100
    assert archives.nom_propose(c) == "y" * 69 + "…"


def test_le_journal_dit_ce_qui_est_livre_et_ce_qui_ne_l_est_pas():
    j = archives.journal(chantier_type(), "2026-11-12-094100", "Calcul", "2026-11-12T09:41", {})
    assert j["nom"] == "Calcul" and j["objectif"] == "Moteur de calcul"
    assert j["ouvert_le"] == "10 novembre 2026 à 9 h 05"
    assert j["archive_le"] == "12 novembre 2026 à 9 h 41"
    assert j["bilan"] == "1 tâche livrée sur 4, 3 inachevées."
    detail = "Vérifiée à la tentative 2 (Opus, effort élevé)."
    assert j["livre"] == [{"id": "A", "titre": "Lecture des données", "detail": detail}]
    raisons = {t["id"]: (t["etat"], t["raison"]) for t in j["inacheve"]}
    assert raisons == {
        "B": ("Revenue vers toi", "le plafond est atteint."),
        "C": ("À lancer", "Pas commencée."),
        "D": ("Abandonnée", "Abandonnée par toi."),
    }
    assert j["decisions"] == [
        {"question": "Tâche B, « Formule » : le plafond est atteint.", "reponse": "Sans réponse"},
        {"question": "Tâche D, « Export » : arrêtée par toi.", "reponse": "Abandonner cette tâche"},
    ]
    assert j["chiffres"] == [["Tâches livrées", "1 sur 4"], ["Agents lancés", "9"],
                             ["Montées en gamme", "1"], ["Coût équivalent", "1,50 $"]]  # fmt: skip
    assert [e["auteur"] for e in j["fil"]] == ["Toi", "Orchestrateur", "Atelier"]


def test_la_livraison_est_dite_selon_le_depot_en_ligne():
    c = chantier_type()

    def en_ligne(**contexte):
        return archives.journal(c, "x", "", "2026-11-12T09:41", contexte)["en_ligne"]

    assert en_ligne(mode="démonstration") == "Démonstration : rien n'a été livré pour de vrai."
    assert en_ligne() == (
        "Le travail livré est entré dans le code du projet, sur sa branche courante, sur ta "
        "machine. Aucun dépôt en ligne n'est relié au projet."
    )
    assert en_ligne(distant="https://github.com/a/b") == (
        "Le travail livré est entré dans le code du projet, sur sa branche courante, et il a été "
        "envoyé sur le dépôt en ligne (https://github.com/a/b)."
    )
    assert en_ligne(distant="https://github.com/a/b", probleme="accès refusé.") == (
        "Le travail livré est entré dans le code du projet, sur sa branche courante, mais le "
        "dernier envoi vers le dépôt en ligne a échoué : accès refusé."
    )
    c.taches[0].etat = "revenu"
    assert en_ligne() == "Rien n'a été livré : aucune tâche n'a passé le vérificateur."


def test_archiver_ecrit_quatre_fichiers_et_lister_les_retrouve(tmp_path):
    j = archives.archiver(tmp_path, chantier_type(), "Calcul", {"mode": "réel"})
    dossier = tmp_path / ".atelier" / "archives" / j["id"]
    assert sorted(p.name for p in dossier.iterdir()) == [
        "CAHIER.md", "JOURNAL.md", "etat.json", "journal.json",
    ]  # fmt: skip
    md = (dossier / "JOURNAL.md").read_text("utf-8")
    assert md.startswith("# Calcul\n") and "## Livré" in md and "## Pas terminé" in md
    assert "- A — Lecture des données. Vérifiée à la tentative 2 (Opus, effort élevé)." in md
    assert json.loads((dossier / "journal.json").read_text("utf-8")) == j
    second = archives.archiver(tmp_path, chantier_type(), "Second", {})
    assert [r["nom"] for r in archives.lister(tmp_path)] == ["Second", "Calcul"]
    assert archives.lire(tmp_path, second["id"])["nom"] == "Second"


def test_une_archive_d_avant_les_journaux_se_lit_quand_meme(tmp_path):
    dossier = tmp_path / ".atelier" / "archives" / "2026-11-11-213721"
    ancien = chantier_type().en_dict()
    del ancien["ouvert_le"]  # les premières archives n'avaient pas cette date
    dossier.mkdir(parents=True)
    (dossier / "etat.json").write_text(json.dumps(ancien), "utf-8")
    (resume,) = archives.lister(tmp_path)
    assert resume == {
        "id": "2026-11-11-213721",
        "nom": "Moteur de calcul",
        "ouvert_le": "",
        "archive_le": "11 novembre 2026 à 21 h 37",
        "bilan": "1 tâche livrée sur 4, 3 inachevées.",
    }
    assert not (dossier / "journal.json").exists()  # la lecture n'écrit rien


def test_une_archive_illisible_ou_un_identifiant_piege_ne_lit_rien(tmp_path):
    dossier = tmp_path / ".atelier" / "archives" / "2026-11-11-213721"
    dossier.mkdir(parents=True)
    (dossier / "etat.json").write_text("pas du json", "utf-8")
    assert archives.lister(tmp_path) == []
    for piege in ("../../etc", "2026-11-11-213721/../x", None, 12, ""):
        assert archives.lire(tmp_path, piege) is None
    assert archives.lister(tmp_path / "absent") == []
