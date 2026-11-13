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


def test_cout_fr():
    assert archives.cout_fr(0) == "0,00 $"
    assert archives.cout_fr(1234.5) == "1234,50 $"
    assert archives.cout_fr(9.999) == "10,00 $"


# --- le temps passé : totaux du chantier et durées de chaque tâche ---------------------------


def chantier_mesure():
    c = chantier_type()
    a = c.taches[0]
    a.historique[0]["durees"] = {"attente": 45, "preparation": 5, "ouvrier": 115,
                                 "perimetre": 1, "controles": 34, "verificateur": 600}  # fmt: skip
    a.historique[1]["durees"] = {"preparation": 5, "ouvrier": 600, "perimetre": 0.4,
                                 "controles": 35, "verificateur": 480,
                                 "enregistrement": 3}  # fmt: skip
    b = c.taches[1]
    b.historique = [{"tentative": 1, "modele": "haiku", "effort": "low", "issue": "panne",
                     "detail": "", "durees": {"attente": 15, "preparation": 2}}]  # fmt: skip
    return c


def test_duree_fr():
    assert archives.duree_fr(0) == "0 s" and archives.duree_fr(0.4) == "0 s"
    assert archives.duree_fr(45) == "45 s" and archives.duree_fr(59.6) == "1 min"
    assert archives.duree_fr(200) == "3 min 20 s" and archives.duree_fr(180) == "3 min"
    assert archives.duree_fr(725) == "12 min"
    assert archives.duree_fr(3900) == "1 h 05 min"
    assert archives.duree_fr(-3) == "0 s"


def test_temps_par_groupe_rassemble_les_phases_et_ignore_un_historique_sans_mesure():
    c = chantier_mesure()
    assert archives.temps_par_groupe(c.taches[0]) == {
        "attendre": 45, "ecrire": 725, "controler": 70.4, "verifier": 1080,
        "enregistrer": 3, "autre": 0,
    }  # fmt: skip
    assert archives.temps_par_groupe(chantier_type().taches[0]) is None
    c.taches[1].historique[0]["durees"]["une_phase_nouvelle"] = 9
    assert archives.temps_par_groupe(c.taches[1])["autre"] == 9


def test_le_journal_donne_le_temps_du_chantier_et_de_chaque_tache():
    j = archives.journal(chantier_mesure(), "2026-11-12-094100", "Calcul", "2026-11-12T09:41", {})
    assert j["chiffres"][4:] == [
        ["Temps passé à attendre", "1 min"],
        ["Temps passé à écrire (préparation de la copie comprise)", "12 min"],
        ["Temps passé à contrôler", "1 min 10 s"],
        ["Temps passé à vérifier", "18 min"],
        ["Temps passé à enregistrer", "3 s"],
    ]
    a, b = j["temps"]
    assert (a["id"], a["tentatives"], b["id"], b["tentatives"]) == ("A", 2, "B", 3)
    assert a["texte"] == (
        "2 tentatives : attendre 45 s, écrire 12 min, contrôler 1 min 10 s, vérifier 18 min, "
        "enregistrer 3 s."
    )
    assert b["phases"]["attendre"] == "15 s" and b["phases"]["ecrire"] == "2 s"
    md = archives.journal_md(j)
    assert "- Temps passé à vérifier : 18 min" in md
    assert "## Le temps de chaque tâche" in md
    assert f"- A — Lecture des données : {a['texte']}" in md


def test_un_journal_sans_mesure_n_a_ni_lignes_ni_partie_de_temps():
    j = archives.journal(chantier_type(), "x", "", "2026-11-12T09:41", {})
    assert j["temps"] == [] and len(j["chiffres"]) == 4
    assert "Temps passé" not in archives.journal_md(j)
    del j["temps"]  # un journal.json écrit avant les mesures
    assert "## Le temps de chaque tâche" not in archives.journal_md(j)


def test_une_archive_mesuree_se_relit_avec_son_temps(tmp_path):
    j = archives.archiver(tmp_path, chantier_mesure(), "Calcul", {})
    relu = archives.lire(tmp_path, j["id"])
    assert relu["temps"] == j["temps"] and relu["chiffres"] == j["chiffres"]
    dossier = tmp_path / ".atelier" / "archives" / j["id"]
    assert "## Le temps de chaque tâche" in (dossier / "JOURNAL.md").read_text("utf-8")
