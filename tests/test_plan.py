"""La forme d'un plan : vagues, largeur, ce qui le retient, plans impossibles."""

from atelier.modele import Tache
from atelier.plan import forme_du_plan, resumer


def t(ident, depend_de=(), perimetre=None):
    """Une tâche du plan, telle que l'orchestrateur l'écrit, avec son propre fichier par défaut."""
    return {"id": ident, "depend_de": list(depend_de), "perimetre": perimetre or [f"{ident}.py"]}


LETTRES = "ABCDEFGHIJ"


def test_dix_taches_independantes_font_une_vague():
    forme = forme_du_plan([t(i) for i in LETTRES])
    assert forme["vagues"] == [list(LETTRES)]
    assert forme["nb_vagues"] == 1 and forme["plus_grande_vague"] == 10
    assert forme["plus_longue_chaine"] == 1 and forme["retenues"] == []
    assert forme["possible"] is True
    assert forme["phrase"] == (
        "Ce plan de 10 tâches tient en une seule vague : "
        "toutes ses tâches travaillent en même temps."
    )


def test_une_chaine_de_dix_fait_dix_vagues():
    taches = [t(LETTRES[0])] + [t(LETTRES[i], [LETTRES[i - 1]]) for i in range(1, 10)]
    forme = forme_du_plan(taches)
    assert forme["vagues"] == [[i] for i in LETTRES]
    assert forme["nb_vagues"] == 10 and forme["plus_grande_vague"] == 1
    assert forme["plus_longue_chaine"] == 10
    assert "B attend A" in forme["retenues"] and "J attend I" in forme["retenues"]
    assert "10 vagues ; une seule tâche travaille à la fois" in forme["phrase"]
    assert "plus longue chaîne de dépendances compte 10 tâches" in forme["phrase"]


def test_un_fichier_partage_separe_deux_taches_sans_dependance():
    taches = [t("A", perimetre=["a.py", "docs/LISEZMOI.md"]), t("B"),
              t("D", perimetre=["d.py", "docs/LISEZMOI.md"])]
    forme = forme_du_plan(taches)
    assert forme["vagues"] == [["A", "B"], ["D"]]
    assert forme["retenues"] == ["D et A touchent toutes deux docs/LISEZMOI.md"]
    assert forme["phrase"].endswith(
        "Ce qui le retient : D et A touchent toutes deux docs/LISEZMOI.md."
    )


def test_un_perimetre_de_dossier_bloque_tout_ce_qui_est_dessous():
    taches = [t("A", perimetre=["atelier/*"]), t("B", perimetre=["atelier/sous/b.py"]),
              t("C", perimetre=["atelier/c.py"]), t("D", perimetre=["tests/test_d.py"])]
    forme = forme_du_plan(taches)
    assert forme["vagues"] == [["A", "D"], ["B", "C"]]
    assert "B (atelier/sous/b.py) et A (atelier/*) peuvent toucher les mêmes fichiers" in (
        forme["retenues"]
    )


def test_l_ordre_du_plan_departage_deux_taches_qui_se_chevauchent():
    premier = forme_du_plan([t("A", perimetre=["x.py"]), t("B", perimetre=["x.py"])])
    second = forme_du_plan([t("B", perimetre=["x.py"]), t("A", perimetre=["x.py"])])
    assert premier["vagues"] == [["A"], ["B"]]
    assert second["vagues"] == [["B"], ["A"]]


def test_une_tache_prete_qui_chevauche_attend_sans_bloquer_les_suivantes():
    # Comme le moteur : B, gênée par A, n'empêche pas C, libre, de partir avec A.
    forme = forme_du_plan([t("A", perimetre=["x.py"]), t("B", perimetre=["x.py"]), t("C")])
    assert forme["vagues"] == [["A", "C"], ["B"]]


def test_une_dependance_et_un_chevauchement_se_cumulent_et_sont_dits():
    taches = [t("A"), t("B", perimetre=["docs/LISEZMOI.md"]), t("C", ["A"]),
              t("D", perimetre=["docs/LISEZMOI.md"]), t("E", ["C", "A"])]
    forme = forme_du_plan(taches)
    assert forme["vagues"] == [["A", "B"], ["C", "D"], ["E"]]
    assert forme["retenues"] == [
        "C attend A", "E attend C et A", "D et B touchent toutes deux docs/LISEZMOI.md"
    ]
    assert forme["plus_longue_chaine"] == 3
    assert forme["phrase"] == (
        "Ce plan de 5 tâches tient en 3 vagues ; jusqu'à 2 tâches travaillent en même temps. "
        "Sa plus longue chaîne de dépendances compte 3 tâches. Ce qui le retient : C attend A ; "
        "E attend C et A ; D et B touchent toutes deux docs/LISEZMOI.md."
    )


def test_un_cycle_est_signale_sans_boucler():
    forme = forme_du_plan([t("A", ["C"]), t("B", ["A"]), t("C", ["B"]), t("D"), t("E", ["E"])])
    assert forme["possible"] is False
    assert forme["vagues"] == [["D"]]
    assert forme["jamais"] == ["A", "B", "C", "E"]
    assert "A, C et B s'attendent en boucle" in forme["problemes"]
    assert "E dépend d'elle-même" in forme["problemes"]
    assert forme["phrase"].startswith(
        "Ce plan ne peut pas aller au bout : A, B, C et E ne partiraient jamais. En cause : "
    )


def test_une_dependance_inconnue_est_signalee():
    forme = forme_du_plan([t("A"), t("B", ["Z"]), t("C", ["B"])])
    assert forme["possible"] is False
    assert forme["problemes"] == ["B dépend de Z, qui n'est pas dans le plan"]
    assert forme["jamais"] == ["B", "C"] and forme["vagues"] == [["A"]]
    assert "B dépend de Z, qui n'est pas dans le plan" in forme["phrase"]
    assert "La partie qui peut partir, une tâche, tient en une vague." in forme["phrase"]


def test_un_identifiant_double_est_signale():
    forme = forme_du_plan([t("A"), t("A", perimetre=["autre.py"])])
    assert forme["possible"] is False
    assert "deux tâches portent l'identifiant A" in forme["problemes"]


def test_accepte_les_taches_du_modele_et_un_plan_vide():
    taches = [Tache("A", "Un", perimetre=["a.py"]), Tache("B", "Deux", perimetre=["b.py"],
                                                          depend_de=["A"])]
    assert forme_du_plan(taches)["vagues"] == [["A"], ["B"]]
    vide = forme_du_plan([])
    assert vide["vagues"] == [] and vide["phrase"] == "Ce plan ne contient aucune tâche."


def test_le_resume_se_recalcule_depuis_la_forme():
    forme = forme_du_plan([t("A")])
    assert resumer(forme) == forme["phrase"]
    assert forme["phrase"] == "Ce plan d'une seule tâche tient en une vague."


# --- lecture de la phrase : regroupement, accords, doublons, grandes chaînes, identifiants doubles


def test_dix_taches_sur_un_meme_fichier_donnent_une_seule_proposition():
    forme = forme_du_plan([t(i, perimetre=["DECISIONS.md"]) for i in LETTRES])
    assert forme["vagues"] == [[i] for i in LETTRES]
    assert len(forme["retenues"]) >= 45  # le détail paire par paire reste dans `retenues`
    assert forme["phrase"].count("DECISIONS.md") == 1
    assert "10 tâches touchent DECISIONS.md" in forme["phrase"]
    assert len(forme["phrase"]) < 300


def test_quelques_taches_sur_un_fichier_sont_nommees_une_fois():
    forme = forme_du_plan([t(i, perimetre=["DECISIONS.md"]) for i in "ABC"])
    assert "A, B et C touchent toutes DECISIONS.md" in forme["phrase"]
    assert forme["phrase"].count("DECISIONS.md") == 1


def test_un_plan_de_vingt_taches_reste_un_resume():
    taches = [t(f"T{i}", perimetre=["DECISIONS.md", f"zone{i % 4}/*"]) for i in range(20)]
    forme = forme_du_plan(taches)
    assert forme["phrase"].count("DECISIONS.md") == 1
    assert len(forme["phrase"]) < 500


def test_les_accords_sont_au_feminin_et_au_singulier_ou_pluriel_justes():
    forme = forme_du_plan([t("A", perimetre=["x.md"]), t("D", perimetre=["x.md"])])
    assert forme["retenues"] == ["D et A touchent toutes deux x.md"]
    assert "D et A touchent toutes deux x.md" in forme["phrase"]
    assert "tous deux" not in forme["phrase"]
    assert "une seule tâche travaille à la fois" in forme["phrase"]
    seul = forme_du_plan([t("A"), t("B", perimetre=["a.py"])])
    assert "tient en une seule vague" in seul["phrase"]
    inconnu = forme_du_plan([t("A", ["Y", "Z"])])
    assert "A dépend de Y et Z, qui ne sont pas dans le plan" in inconnu["phrase"]


def test_une_dependance_citee_deux_fois_n_est_dite_qu_une_fois():
    forme = forme_du_plan([t("A"), t("B", ["A", "A"])])
    assert forme["retenues"] == ["B attend A"]
    assert "B attend A et A" not in forme["phrase"]
    assert forme["vagues"] == [["A"], ["B"]] and forme["possible"] is True


def test_une_chaine_de_mille_taches_dans_le_desordre_ne_deborde_pas():
    n = 1500
    taches = [t(f"T{i}", [f"T{i - 1}"] if i else []) for i in range(n)]
    for ordre in (taches, taches[::-1]):
        forme = forme_du_plan(ordre)
        assert forme["plus_longue_chaine"] == n and forme["nb_vagues"] == n
        assert forme["possible"] is True


def test_une_boucle_n_allonge_pas_la_chaine_et_ne_deborde_pas():
    forme = forme_du_plan([t(f"T{i}", [f"T{(i + 1) % 2000}"]) for i in range(2000)])
    assert forme["possible"] is False and forme["vagues"] == []


def test_un_identifiant_double_est_dit_sans_pretendre_que_le_plan_echoue():
    # Le moteur choisit ses tâches une à une par objet, non par identifiant : il lance les deux B.
    forme = forme_du_plan([t("A"), t("B"), t("B", perimetre=["autre.py"]), t("C", ["B"])])
    assert forme["vagues"] == [["A", "B", "B"], ["C"]]
    assert forme["problemes"] == ["deux tâches portent l'identifiant B"]
    assert forme["jamais"] == []
    assert "deux tâches portent l'identifiant B" in forme["phrase"]
    assert "ne peut pas aller au bout" not in forme["phrase"]
    assert forme["phrase"].startswith("Ce plan peut aller au bout, mais il a un défaut")
    assert "Ce plan de 4 tâches tient en 2 vagues" in forme["phrase"]


def test_un_identifiant_double_n_efface_pas_la_seconde_tache_des_vagues():
    forme = forme_du_plan([t("A", perimetre=["x.py"]), t("A", perimetre=["x.py"])])
    assert forme["vagues"] == [["A"], ["A"]]
    assert forme["jamais"] == []
