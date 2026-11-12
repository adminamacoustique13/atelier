import json
import subprocess
import threading

import pytest

from atelier.agents import AgentSimule, Resultat
from atelier.consignes import consigne_ouvrier, dernier_json, lire_verdict
from atelier.controles import ControlesGit, ControlesSimules, hors_perimetre, se_chevauchent
from atelier.modele import Chantier, Contrat, Tache
from atelier.moteur import (
    ABANDONNER,
    ORIGINES,
    RELANCER,
    RELANCER_TEL,
    ContratNonValide,
    Moteur,
)


def chantier(taches, **contrat):
    reglages = {"objectif": "Essai", "valide": True, **contrat}
    return Chantier(projet="essai", contrat=Contrat(**reglages), taches=taches)


def tache(identifiant, **champs):
    reglages = {"titre": f"Tâche {identifiant}", "type": "mecanique", "criteres": ["Ça marche."]}
    reglages["perimetre"] = [f"{identifiant.lower()}.py"]
    return Tache(id=identifiant, **{**reglages, **champs})


# Des raisons de refus qui ne se ressemblent pas : deux à deux, `refus.meme_refus` les distingue.
SUJETS = [
    "La fonction ne gère pas la liste vide.",
    "Le test ajouté compare la sortie à elle-même.",
    "Le fichier de configuration n'est pas relu au démarrage.",
    "La documentation contredit le comportement mesuré.",
    "Les messages d'erreur restent en anglais.",
    "Une division par zéro survient sur un tableau sans ligne.",
    "Le cache garde une valeur périmée après une modification.",
    "Les arrondis diffèrent du calcul de référence.",
    "La sauvegarde écrase la version précédente sans copie.",
    "Le journal ne note pas l'heure des événements.",
    "La page se recharge deux fois au premier affichage.",
    "Un import circulaire bloque le chargement du paquet.",
]


class AgentVarie(AgentSimule):
    """L'agent simulé, dont chaque refus du vérificateur donne une raison différente.

    L'agent simulé refuse toujours pour la même raison, mot pour mot : depuis V3b, une telle
    suite bloque la tâche. Les tests de l'escalade (seconde chance, montée, plafond, relance
    seule) la suivent avec des refus qui diffèrent, comme sur un vrai chantier qui avance.
    """

    def executer(self, consigne, modele, effort, dossier, lecture_seule=False, contexte=None,
                 copie_jetable=False, reprendre=None):  # fmt: skip
        resultat = super().executer(consigne, modele, effort, dossier, lecture_seule, contexte,
                                    copie_jetable, reprendre)  # fmt: skip
        verdict = dernier_json(resultat.texte) if contexte["role"] == "verificateur" else None
        if verdict and verdict.get("valide") is False:
            rang = sum(a["role"] == "verificateur" for a in self.appels)
            resultat.texte = json.dumps({**verdict, "resume": SUJETS[rang % len(SUJETS)]})
        return resultat


def moteur(c, scenario=None, varie=False):
    perimetres = {t.id: t.perimetre for t in c.taches}
    agent = (AgentVarie if varie else AgentSimule)(scenario or {}, perimetres=perimetres)
    return Moteur(c, agent, ControlesSimules()), agent


def departs(agent):
    """Le dosage de chaque départ neuf d'un ouvrier, sans les reprises à chaud."""
    return [(x["modele"], x["effort"]) for x in agent.appels
            if x["role"] == "ouvrier" and "reprise" not in x]  # fmt: skip


def traces(t):
    """L'historique d'une tâche, réduit au numéro, à l'issue et à la marque de reprise."""
    return [(e["tentative"], e["issue"], e["reprise"]) for e in t.historique]


def test_sans_contrat_valide_rien_ne_demarre():
    c = chantier([tache("A")], valide=False)
    with pytest.raises(ContratNonValide):
        moteur(c)[0].executer()


def test_le_moteur_dit_ou_en_est_chaque_tache_active():
    """Même quand aucun agent ne tourne (copie, contrôles, fusion), la phase est connue."""
    c = chantier([tache("A")])
    vues = []

    class Controles(ControlesSimules):
        commandes = ["python3 -m pytest -q"]

        def preparer(self, t):
            vues.append(m.phase(t.id)["texte"])

        def mecaniques(self, t, dossier):
            vues.append(m.phase(t.id)["texte"])
            return True, ""

        def enregistrer(self, t, dossier):
            vues.append(m.phase(t.id)["texte"])

    class Agent(AgentSimule):
        def executer(self, consigne, modele, effort, dossier, lecture_seule=False, contexte=None):
            vues.append(m.phase(contexte["tache"])["texte"])
            return super().executer(consigne, modele, effort, dossier, lecture_seule, contexte)

    m = Moteur(c, Agent({}, perimetres={"A": ["a.py"]}), Controles())
    m.executer()
    assert vues == [
        "Préparation de sa copie de travail",
        "L'ouvrier travaille (tentative 1)",
        "Contrôles automatiques : python3 -m pytest -q",
        "Le vérificateur relit (Opus, effort moyen)",
        "Enregistrement et fusion",
    ]
    assert m.phase("A") is None  # une tâche finie n'a plus de phase


def test_chantier_nominal_tout_est_verifie_dans_l_ordre_des_dependances():
    c = chantier([tache("A"), tache("B"), tache("C", depend_de=["A", "B"])])
    m, agent = moteur(c)
    m.executer()
    assert [t.etat for t in c.taches] == ["verifie"] * 3
    assert c.termine
    assert c.agents_lances == 6
    ouvriers = [a["tache"] for a in agent.appels if a["role"] == "ouvrier"]
    assert ouvriers.index("C") == 2


def test_chaque_agent_recoit_son_dosage_et_le_verificateur_est_au_dessus():
    c = chantier([tache("A"), tache("P", type="physique")])
    m, agent = moteur(c)
    m.executer()
    dosages = {(a["tache"], a["role"]): (a["modele"], a["effort"]) for a in agent.appels}
    assert dosages[("A", "ouvrier")] == ("sonnet", "low")
    assert dosages[("A", "verificateur")] == ("opus", "medium")
    assert dosages[("P", "ouvrier")] == ("fable", "max")
    assert dosages[("P", "verificateur")] == ("fable", "max")


def test_seconde_chance_puis_montee_d_un_cran():
    """Un refus à l'enregistrement ne se reprend pas : seconde chance au même niveau, puis un cran.

    (Une erreur d'agent, elle, ne fait plus monter : voir `test_une_erreur_d_agent_...`.)
    """
    c = chantier([tache("A")])
    controles = ControlesReglables(enregistrements=[
        "Conflit avec la branche principale.", "Les contrôles échouent une fois fusionné.",
    ])  # fmt: skip
    agent = AgentSimule(perimetres={"A": ["a.py"]})
    Moteur(c, agent, controles).executer()
    a = c.tache("A")
    assert a.etat == "verifie"
    assert a.tentatives == 3
    assert (a.modele, a.effort) == ("opus", "low")
    assert c.montees == 1
    ouvriers = [(x["modele"], x["effort"]) for x in agent.appels if x["role"] == "ouvrier"]
    assert ouvriers == [("sonnet", "low"), ("sonnet", "low"), ("opus", "low")]
    assert agent.reprises == []
    assert any("Seconde chance au même niveau" in e["texte"] for e in c.evenements)


def test_un_travail_bacle_monte_l_effort_pas_le_modele():
    c = chantier([tache("A")])
    m, _ = moteur(c, {"A": ["bacle", "ok"]})  # refusée, reprise refusée, puis un cran
    m.executer()
    assert (c.tache("A").modele, c.tache("A").effort) == ("sonnet", "medium")


def test_au_plafond_la_tache_revient_avec_une_seule_decision():
    c = chantier([tache("A")], plafond_modele="haiku", plafond_effort="low")
    m, _ = moteur(c, {"A": ["ne_sait_pas"]})
    m.executer()
    assert c.tache("A").etat == "revenu"
    assert not c.termine
    assert len(c.demandes) == 1
    assert c.demandes[0]["options"] == [RELANCER_TEL, RELANCER, ABANDONNER]


def test_relancer_au_meme_niveau_garde_le_dosage():
    c = chantier([tache("A")], plafond_modele="haiku", plafond_effort="low")
    m, _ = moteur(c, {"A": ["ne_sait_pas", "ne_sait_pas", "ok"]}, varie=True)
    m.executer()
    avant = (c.tache("A").modele, c.tache("A").effort)
    m.repondre(c.demandes[0]["id"], RELANCER_TEL)
    assert (c.tache("A").modele, c.tache("A").effort) == avant
    m.executer()
    assert c.tache("A").etat == "verifie"


def test_relancer_apres_decision_monte_d_un_cran_et_termine():
    c = chantier([tache("A")], plafond_modele="haiku", plafond_effort="low")
    m, agent = moteur(c, {"A": ["ne_sait_pas", "ne_sait_pas", "ok"]}, varie=True)
    m.executer()
    m.repondre(c.demandes[0]["id"], RELANCER)
    m.executer()
    assert c.tache("A").etat == "verifie"
    assert agent.appels[-1]["role"] == "verificateur"


def test_abandonner_ferme_la_tache():
    c = chantier([tache("A")], plafond_modele="haiku", plafond_effort="low")
    m, _ = moteur(c, {"A": ["ne_sait_pas"]})
    m.executer()
    m.repondre(c.demandes[0]["id"], ABANDONNER)
    m.executer()
    assert c.tache("A").etat == "abandonnee"
    assert c.termine


def test_une_sortie_de_perimetre_est_refusee_sans_passer_par_le_verificateur():
    c = chantier([tache("A")])
    m, agent = moteur(c, {"A": ["deborde", "ok"]})  # la reprise rejoue le débord
    m.executer()
    assert c.tache("A").historique[0]["issue"] == "deborde"
    assert "hors_perimetre.txt" in c.tache("A").historique[0]["detail"]
    assert [(e["issue"], e["reprise"]) for e in c.tache("A").historique] == [
        ("deborde", False), ("deborde", True), ("valide", False),
    ]  # fmt: skip
    assert [(a["role"], "reprise" in a) for a in agent.appels] == [
        ("ouvrier", False), ("ouvrier", True), ("ouvrier", False), ("verificateur", False),
    ]  # fmt: skip


def test_une_consigne_mal_posee_revient_tout_de_suite():
    c = chantier([tache("A")])
    m, _ = moteur(c, {"A": ["consigne"]})
    m.executer()
    assert c.tache("A").etat == "revenu"
    assert c.tache("A").tentatives == 1


def test_les_agents_ne_sont_pas_plafonnes_mais_comptes():
    c = chantier([tache(x) for x in "ABCDEFGH"])
    m, _ = moteur(c)
    m.executer()
    assert all(t.etat == "verifie" for t in c.taches)
    assert c.agents_lances == 16  # un ouvrier et un vérificateur par tâche
    # Un état sauvé avant le retrait du plafond se relit : l'ancien réglage est oublié.
    ancien = c.en_dict()
    ancien["contrat"]["max_agents"] = 12
    relu = Chantier.depuis_dict(ancien)
    assert relu.agents_lances == 16 and "max_agents" not in relu.en_dict()["contrat"]


def test_deux_taches_au_meme_perimetre_ne_tournent_jamais_ensemble():
    c = chantier([tache("A", perimetre=["commun.py"]), tache("B", perimetre=["commun.py"])])
    agent = AgentSimule(delai_s=0.05, perimetres={"A": ["commun.py"], "B": ["commun.py"]})
    actives_max = []

    def observer():
        actives_max.append(sum(t.etat in ("en_cours", "en_verification") for t in c.taches))

    Moteur(c, agent, ControlesSimules(), sur_changement=observer).executer()
    assert max(actives_max) == 1
    assert c.termine


def test_perimetres():
    assert hors_perimetre(["a.py", "b.py", "chantier/relais/A.md"], ["a.py"]) == ["b.py"]
    assert hors_perimetre(["src/x/y.py"], ["src/*"]) == []
    assert se_chevauchent(["src/*.py"], ["src/a.py"])
    assert not se_chevauchent(["a.py"], ["b.py"])


def test_un_verdict_illisible_vaut_refus():
    assert lire_verdict("Tout va bien, je crois.")["valide"] is False
    verdict = lire_verdict('Analyse faite.\n{"valide": true, "motif": "bacle", "resume": "OK"}')
    assert verdict == {"valide": True, "motif": "bacle", "resume": "OK"}


def test_la_consigne_porte_les_criteres_le_perimetre_et_les_remarques():
    t = tache("A", criteres=["Rend 42."], perimetre=["a.py"])
    texte = consigne_ouvrier(t, Contrat(objectif="But"), {"commandes": ["pytest -q"]}, "Trop lent.")
    assert "1. Rend 42." in texte and "`a.py`" in texte
    assert "`pytest -q`" in texte and "Trop lent." in texte
    assert "Aucun commit" in texte


def test_avec_un_vrai_depot_git_le_travail_verifie_est_fusionne_et_le_reste_jete(tmp_path):
    def git(*arguments):
        subprocess.run(["git", *arguments], cwd=tmp_path, check=True, capture_output=True)

    git("init", "-q", "-b", "main")
    git("config", "user.name", "Essai")
    git("config", "user.email", "essai@example.invalid")
    (tmp_path / "LISEZMOI.md").write_text("socle\n", "utf-8")
    git("add", "-A")
    git("commit", "-q", "-m", "socle")

    c = chantier([tache("A"), tache("B"), tache("C", depend_de=["A"])])
    agent = AgentSimule({"B": ["deborde", "ok"]}, perimetres={t.id: t.perimetre for t in c.taches})
    controles = ControlesGit(tmp_path, commandes=["test -f LISEZMOI.md"])
    # Le vérificateur travaille dans une copie jetable, où il essaie une mutation.
    verifications, executer = [], agent.executer

    def executer_en_notant(consigne, modele, effort, dossier, lecture_seule=False, contexte=None,
                           copie_jetable=False, reprendre=None):  # fmt: skip
        if lecture_seule:
            verifications.append((dossier, copie_jetable, "copie jetable" in consigne))
            (dossier / "mutation.py").write_text("raise SystemExit(1)\n", "utf-8")
        return executer(consigne, modele, effort, dossier, lecture_seule, contexte,
                        reprendre=reprendre)  # fmt: skip

    agent.executer = executer_en_notant
    Moteur(c, agent, controles).executer()

    assert verifications and all(jetable and dite for _, jetable, dite in verifications)
    assert all(".atelier/verifications/" in str(d) and not d.exists() for d, _, _ in verifications)
    assert not (tmp_path / "mutation.py").exists()
    assert c.termine
    assert sorted(p.name for p in tmp_path.glob("*.py")) == ["a.py", "b.py", "c.py"]
    assert not (tmp_path / "hors_perimetre.txt").exists()
    historique = subprocess.run(
        ["git", "log", "--format=%s"], cwd=tmp_path, capture_output=True, text=True
    ).stdout
    for identifiant in "ABC":
        assert f"{identifiant} : Tâche {identifiant}" in historique
    etat = subprocess.run(
        ["git", "status", "--porcelain"], cwd=tmp_path, capture_output=True, text=True
    ).stdout
    assert etat.strip() == ""


def test_la_conversation_propose_un_plan_puis_le_chantier_se_deroule(tmp_path):
    from atelier.serveur import Atelier

    plan = {"taches": [{"id": "A", "titre": "Un", "type": "mecanique", "perimetre": ["a.py"]}]}
    vide = Chantier(projet="essai", contrat=Contrat(objectif=""))
    atelier = Atelier(tmp_path, vide, AgentSimule(plan=plan), ControlesSimules(), {})
    assert atelier.vue()["point_d_etape"].startswith("Aucun chantier")

    atelier.message("Construis un.")
    atelier.fil_message.join()
    vue = atelier.vue()
    assert [t["id"] for t in vue["taches"]] == ["A"]
    assert vue["contrat"]["objectif"] == "Construis un." and not vue["contrat"]["valide"]
    assert [e["auteur"] for e in vue["evenements"]] == [
        "orchestrateur",
        "toi",
        "orchestrateur",
        "moteur",
    ]
    assert "atelier-plan" not in vue["evenements"][2]["texte"]
    assert not vue["occupe"] and vue["brouillon"]["texte"] == ""

    atelier.valider_contrat()
    atelier.fil.join()
    assert atelier.vue()["taches"][0]["etat"] == "verifie"

    atelier.message("Merci.")
    atelier.fil_message.join()
    dernier = atelier.vue()["evenements"][-1]
    assert dernier["auteur"] == "orchestrateur" and "noté" in dernier["texte"]
    assert (tmp_path / "chantier" / "CAHIER.md").exists()
    appels = [a for a in atelier.moteur.agent.appels if a.get("role") == "conversation"]
    assert [a["reprise"] for a in appels] == [False, True]
    assert appels[0]["session"] == appels[1]["session"]


def test_un_plan_se_lit_meme_avec_des_objets_imbriques_et_des_champs_inconnus():
    from atelier.consignes import extraire_plan
    from atelier.moteur import taches_du_plan

    reponse = (
        'Voici {le plan}.\n```atelier-plan\n{"objectif": "But", "taches": ['
        '{"id": "A", "titre": "Un", "type": "physique", "inconnu": 1}, {"titre": "sans id"},'
        ' {"id": "B", "titre": "Deux", "type": "bizarre", "depend_de": ["A"]}]}\n```'
    )
    texte, plan = extraire_plan(reponse)
    assert texte == "Voici {le plan}." and plan["objectif"] == "But"
    taches = taches_du_plan(plan, {})
    assert [(t.id, t.type) for t in taches] == [("A", "physique"), ("B", "courante")]
    assert (taches[0].modele, taches[0].effort) == ("fable", "max")
    assert extraire_plan("Juste une réponse.") == ("Juste une réponse.", None)


def test_on_cree_un_projet_puis_on_revient_au_premier(tmp_path):
    import pytest

    from atelier.modele import ProjetImpossible
    from atelier.projets import Projets
    from atelier.serveur import Atelier

    def simule(dossier, nom):
        dossier.mkdir(parents=True)
        vide = Chantier(projet=nom, contrat=Contrat(objectif=""))
        return Atelier(dossier, vide, AgentSimule(), ControlesSimules(), {})

    projets = Projets(tmp_path, simule)
    projets.ajouter(simule(tmp_path / "premier", "Premier"))
    assert projets.creer("  Étude  d'été n°2 ") == "etude-d-ete-n2"
    vue = projets.vue()
    assert vue["projet"] == "Étude d'été n°2" and vue["racine"] == str(tmp_path)
    assert [(p["id"], p["courant"]) for p in vue["projets"]] == [
        ("premier", False),
        ("etude-d-ete-n2", True),
    ]
    assert (tmp_path / "etude-d-ete-n2" / ".atelier" / "etat.json").exists()
    for refuse in ("Étude d'été n°2", "premier", "  ", "!!!"):
        with pytest.raises(ProjetImpossible):
            projets.creer(refuse)
    projets.ouvrir("premier")
    assert projets.vue()["projet"] == "Premier"
    with pytest.raises(ProjetImpossible):
        projets.ouvrir("inconnu")


def test_un_vrai_projet_nait_avec_son_depot_git_et_son_profil(tmp_path):
    import subprocess

    from atelier.projets import Projets, creer_depot, ouvrir_depot

    projets = Projets(tmp_path, creer_depot, ouvrir_depot)
    cle = projets.creer("Mon projet")
    dossier = tmp_path / cle
    journal = subprocess.run(
        ["git", "log", "--oneline"], cwd=dossier, capture_output=True, text=True, check=True
    )
    assert "Création du projet" in journal.stdout
    assert '"nom": "Mon projet"' in (dossier / "chantier" / "profil.json").read_text("utf-8")
    assert projets.vue()["projet"] == "Mon projet" and projets.vue()["mode"] == "réel"

    autres = Projets(tmp_path, creer_depot, ouvrir_depot)
    autres.decouvrir()
    assert [p["id"] for p in autres.liste()] == ["mon-projet"]
    autres.ouvrir("mon-projet")
    assert autres.vue()["projet"] == "Mon projet"


def test_sans_projet_l_atelier_attend_qu_on_en_cree_un(tmp_path):
    import pytest

    from atelier.modele import ProjetImpossible
    from atelier.projets import Projets, creer_depot, ouvrir_depot

    projets = Projets(tmp_path, creer_depot, ouvrir_depot)
    projets.decouvrir()
    projets.ouvrir_le_premier()
    assert projets.vue() == {
        "aucun_projet": True,
        "projets": [],
        "racine": str(tmp_path),
        "mode": "réel",
    }
    with pytest.raises(ProjetImpossible):
        projets.atelier()
    projets.creer("Premier")
    assert projets.vue()["projet"] == "Premier"

    au_redemarrage = Projets(tmp_path, creer_depot, ouvrir_depot)
    au_redemarrage.decouvrir()
    au_redemarrage.ouvrir_le_premier()
    assert au_redemarrage.vue()["projet"] == "Premier"


def test_on_reprend_un_depot_existant_et_l_etat_reste_hors_de_son_historique(tmp_path):
    import subprocess

    import pytest

    from atelier.modele import ProjetImpossible
    from atelier.projets import Projets, creer_depot, ouvrir_depot

    def git(dossier, *args):
        identite = ["-c", "user.name=t", "-c", "user.email=t@t"]
        subprocess.run(["git", *identite, *args], cwd=dossier, check=True, capture_output=True)

    source = tmp_path / "ailleurs" / "Mon-Code.git"
    source.mkdir(parents=True)
    git(source, "init", "-q")
    (source / "LISEZMOI.md").write_text("bonjour\n")
    git(source, "add", "-A")
    git(source, "commit", "-q", "-m", "debut")

    racine = tmp_path / "racine"
    racine.mkdir()
    projets = Projets(racine, creer_depot, ouvrir_depot)
    assert projets.creer("Neuf") == "neuf"
    branche = subprocess.run(
        ["git", "branch", "--show-current"], cwd=racine / "neuf", capture_output=True, text=True
    ).stdout.strip()
    assert branche == "main"
    assert projets.cloner(f"  {source}/ ") == "mon-code"
    clone = racine / "mon-code"
    assert (clone / "LISEZMOI.md").read_text() == "bonjour\n"
    assert projets.vue()["projet"] == "mon-code"
    assert ".atelier/" in (clone / ".git" / "info" / "exclude").read_text()
    statut = subprocess.run(
        ["git", "status", "--porcelain"], cwd=clone, capture_output=True, text=True
    ).stdout
    # Le cahier est fait pour être versionné ; l'état interne, jamais.
    assert ".atelier" not in statut

    with pytest.raises(ProjetImpossible, match="existe déjà"):
        projets.cloner(str(source))
    for _ in range(2):  # un échec ne bloque pas un nouvel essai sous le même nom
        with pytest.raises(ProjetImpossible, match="Aucun dépôt|Git a refusé"):
            projets.cloner(str(tmp_path / "absent"))
    assert not projets.en_cours
    with pytest.raises(ProjetImpossible, match="Colle l'adresse"):
        projets.cloner("   ")

    autres = Projets(racine, creer_depot, ouvrir_depot)
    (racine / "pas-un-depot").mkdir()
    autres.decouvrir()
    assert sorted(p["id"] for p in autres.liste()) == ["mon-code", "neuf"]


def test_un_projet_relie_a_un_depot_en_ligne_y_envoie_chaque_tache(tmp_path, monkeypatch):
    import pytest

    # Un ordinateur où git ne connaît pas encore le nom de la personne.
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "aucune-config"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")

    def git(dossier, *args):
        return subprocess.run(
            ["git", *args], cwd=dossier, check=True, capture_output=True, text=True
        ).stdout

    projet, en_ligne = tmp_path / "projet", tmp_path / "en-ligne.git"
    projet.mkdir()
    git(projet, "init", "-q", "-b", "main")
    (projet / "LISEZMOI.md").write_text("socle\n", "utf-8")
    git(projet, "add", "-A")
    git(projet, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "socle")
    (projet / "chantier").mkdir()
    (projet / "chantier" / "CAHIER.md").write_text("# Cahier\n", "utf-8")
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(en_ligne))

    controles = ControlesGit(projet)
    assert controles.distant() == ""
    controles.relier(str(en_ligne))
    assert controles.distant() == str(en_ligne)
    assert "Cahier du chantier" in git(en_ligne, "log", "--format=%s", "main")

    c = chantier([tache("A")])
    # L'Atelier réécrit le cahier pendant le chantier.
    (projet / "chantier" / "CAHIER.md").write_text("# Cahier\n\nA en cours\n", "utf-8")
    Moteur(c, AgentSimule(perimetres={"A": ["a.py"]}), controles).executer()
    envoye = git(en_ligne, "log", "--format=%s", "main")
    assert "A : Tâche A" in envoye and "Cahier : A enregistrée" in envoye
    assert controles.envoi == ""
    assert git(projet, "status", "--porcelain", "--", "chantier").strip() == ""

    # Un dépôt en ligne qui a déjà son propre historique : refus expliqué, rien n'est perdu.
    autre = tmp_path / "autre"
    git(tmp_path, "clone", "-q", str(en_ligne), str(autre))
    (autre / "x.txt").write_text("x", "utf-8")
    git(autre, "add", "-A")
    git(autre, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "ailleurs")
    git(autre, "push", "-q", "origin", "main")
    with pytest.raises(ValueError, match="contient déjà"):
        controles.relier(str(en_ligne))
    assert "A : Tâche A" in git(projet, "log", "--format=%s")


def test_l_orchestrateur_propose_des_outils_et_un_clic_les_fait_valoir(tmp_path):
    import json
    from types import SimpleNamespace

    from atelier.projets import COMMANDES_PAR_DEFAUT, creer_depot, lire_profil
    from atelier.serveur import ACCEPTER_OUTILS

    atelier = creer_depot(tmp_path / "p", "P")
    assert atelier.moteur.profil["commandes_permises"] == COMMANDES_PAR_DEFAUT
    assert "Bash(uv:*)" in atelier.moteur.agent._outils(lecture_seule=False)

    # Un projet créé avant ce réglage, sans liste : les commandes par défaut valent.
    ancien = tmp_path / "ancien" / "chantier"
    ancien.mkdir(parents=True)
    (ancien / "profil.json").write_text('{"nom": "Ancien", "commandes": []}')
    assert lire_profil(ancien.parent)["commandes_permises"] == COMMANDES_PAR_DEFAUT

    bloc = {"commandes_permises": ["maturin"], "commandes": ["uv run pytest -q"], "pourquoi": "x"}
    texte = f"Il faut maturin.\n```atelier-outils\n{json.dumps(bloc)}\n```\nVoilà."
    atelier._recevoir("?", SimpleNamespace(ok=True, texte=texte, cout_usd=0, tokens=0))
    dit = [e for e in atelier.moteur.chantier.evenements if e.get("auteur") == "orchestrateur"]
    assert "atelier-outils" not in dit[-1]["texte"] and "Voilà." in dit[-1]["texte"]
    demande = atelier.moteur.chantier.demandes[-1]
    assert demande["nature"] == "outils" and "maturin" in demande["question"]

    atelier.decider(demande["id"], ACCEPTER_OUTILS)
    profil = json.loads((tmp_path / "p" / "chantier" / "profil.json").read_text())
    assert profil["commandes_permises"] == [*COMMANDES_PAR_DEFAUT, "maturin"]
    assert profil["commandes"] == ["uv run pytest -q"]
    assert "Bash(maturin:*)" in atelier.moteur.agent._outils(lecture_seule=False)
    assert atelier.moteur.controles.commandes == ["uv run pytest -q"]
    historique = subprocess.run(
        ["git", "log", "--format=%s"], cwd=tmp_path / "p", capture_output=True, text=True
    ).stdout
    assert "Outils du projet" in historique
    atelier.decider(demande["id"], ACCEPTER_OUTILS)  # un second clic ne refait rien
    assert historique.count("Outils du projet") == 1


def test_un_reglage_d_outils_rendu_avec_le_plan_n_est_pas_perdu(tmp_path):
    """Constaté au premier essai réel : le plan effaçait le réglage rendu juste avant lui."""
    import json
    from types import SimpleNamespace

    from atelier.projets import creer_depot

    atelier = creer_depot(tmp_path / "p", "P")
    outils = {"commandes": ["python3 -m pytest -q"], "pourquoi": "Rejouer les tests."}
    plan = {"objectif": "o", "taches": [{"id": "A", "titre": "t", "perimetre": ["a.py"]}]}
    texte = (
        f"Je fixe ce contrôle, puis je donne le plan.\n\n```atelier-outils\n{json.dumps(outils)}"
        f"\n```\n\n```atelier-plan\n{json.dumps(plan)}\n```"
    )
    atelier._recevoir("?", SimpleNamespace(ok=True, texte=texte, cout_usd=0, tokens=0))
    assert [t.id for t in atelier.moteur.chantier.taches] == ["A"]
    demandes = atelier.moteur.chantier.demandes
    assert [d["nature"] for d in demandes] == ["outils"]
    assert "python3 -m pytest -q" in demandes[0]["question"]

    # Un plan corrigé ensuite garde le réglage tant qu'il n'a pas de réponse, pas après.
    atelier._recevoir("?", SimpleNamespace(ok=True, texte=texte.split("```atelier-outils")[0]
                                           + f"```atelier-plan\n{json.dumps(plan)}\n```",
                                           cout_usd=0, tokens=0))  # fmt: skip
    assert len(atelier.moteur.chantier.demandes) == 1
    atelier.decider(demandes[0]["id"], "Refuser")
    seul_plan = f"```atelier-plan\n{json.dumps(plan)}\n```"
    atelier._recevoir("?", SimpleNamespace(ok=True, texte=seul_plan, cout_usd=0, tokens=0))
    assert atelier.moteur.chantier.demandes == []


def test_l_accueil_resume_chaque_projet_sans_le_demarrer(tmp_path):
    import subprocess

    from atelier.modele import Tache
    from atelier.projets import Projets, creer_depot, depot_en_ligne, ouvrir_depot

    projets = Projets(tmp_path, creer_depot, ouvrir_depot)
    projets.creer("Ancien")
    projets.creer("Récent")
    subprocess.run(["git", "remote", "add", "origin", "https://moi:jeton@github.com/moi/recent.git"],
                   cwd=tmp_path / "recent", check=True)  # fmt: skip
    atelier = projets.atelier()
    atelier.moteur.chantier.noter("Un calcul de charpente", auteur="toi")
    atelier.moteur.chantier.taches = [Tache("A", "Un"), Tache("B", "Deux")]
    atelier.moteur.chantier.taches[0].etat = "verifie"
    atelier.moteur.chantier.contrat.valide = True
    atelier._sauver()

    # Un autre atelier, au redémarrage : il découvre les projets sans en ouvrir aucun.
    autres = Projets(tmp_path, creer_depot, ouvrir_depot)
    autres.decouvrir()
    fiches = {f["id"]: f for f in autres.accueil()}
    assert set(fiches) == {"ancien", "recent"} and not autres.ateliers
    recent = fiches["recent"]
    assert recent["nom"] == "Récent"
    assert recent["chantier"]["nom"] == "Un calcul de charpente"
    assert recent["chantier"]["phrase"] == "1 tâche livrée sur 2."
    assert recent["chantier"]["taches"] == ["verifie", "a_lancer"]
    assert recent["en_ligne"] == "github.com/moi/recent"  # sans le jeton
    assert fiches["ancien"]["chantier"]["etat"] == "vide"
    assert depot_en_ligne(tmp_path / "ancien") == ""

    # Nouvelle session : l'ancien chantier est archivé, le projet repart d'un chantier vide.
    resultat = autres.nouvelle_session("recent", "Charpente, premier jet")
    assert resultat["fait"] and autres.courant == "recent"
    fiche = next(f for f in autres.accueil() if f["id"] == "recent")
    assert fiche["archives"] == 1 and fiche["chantier"]["etat"] == "vide" and fiche["courant"]
    assert autres.nouvelle_session("recent")["fait"] is False  # un chantier vide n'est pas archivé


# --- sans intervention : relance seule, intégration refusée, réparation de main -------------


def test_une_tache_epuisee_est_relancee_seule_un_cran_plus_haut():
    c = chantier([tache("A")], plafond_modele="fable", plafond_effort="high")
    m, agent = moteur(c, {"A": ["ne_sait_pas", "ne_sait_pas", "ne_sait_pas", "ok"]}, varie=True)
    m.executer()
    a = c.tache("A")
    assert a.etat == "verifie" and c.demandes == [] and c.termine
    assert a.relances_auto == 1 and a.tentatives == 4
    # Chaque départ a sa reprise, au même dosage, qui tient lieu de seconde chance.
    assert departs(agent) == [("sonnet", "low"), ("opus", "low"), ("fable", "low"),
                              ("fable", "medium")]  # fmt: skip
    assert [r["tentative"] for r in agent.reprises] == [1, 2, 3]
    texte = "Je relance seul un cran plus haut : Fable, effort moyen"
    assert any(texte in e["texte"] for e in c.evenements)


def test_la_relance_seule_n_a_lieu_qu_une_fois_puis_la_tache_revient():
    """Le plafond (Fable, effort max) laisse des crans libres : seule la borne des relances
    seules rend la tâche, après ses tentatives et non au plafond.

    Les refus diffèrent (V3b) : trois « bâclé » mot pour mot bloqueraient la tâche au troisième,
    avant toute relance seule.
    """
    c = chantier([tache("A")], plafond_modele="fable", plafond_effort="max", max_tentatives=2)
    m, agent = moteur(c, {"A": ["bacle"]}, varie=True)
    m.executer()
    a = c.tache("A")
    assert a.etat == "revenu" and len(c.demandes) == 1 and a.relances_auto == 1
    assert not c.termine
    # Une montée, la relance seule (une seule), une montée, puis le retour à la personne.
    assert departs(agent) == [("sonnet", "low"), ("sonnet", "medium"), ("sonnet", "high"),
                              ("sonnet", "xhigh")]  # fmt: skip
    assert a.tentatives == 4 and "4 tentatives sans succès" in c.demandes[0]["question"]
    assert sum("Je relance seul" in t for t in textes_du_fil(c)) == 1


def test_au_plafond_aucune_relance_seule():
    c = chantier([tache("A")], plafond_modele="haiku", plafond_effort="low")
    m, _ = moteur(c, {"A": ["ne_sait_pas"]}, varie=True)
    m.executer()
    assert c.tache("A").relances_auto == 0 and c.tache("A").etat == "revenu"


class ControlesReglables(ControlesSimules):
    """Des contrôles dont l'enregistrement et la branche principale répondent selon une liste."""

    def __init__(self, enregistrements=(), principale=()):
        self.enregistrements, self.principale = list(enregistrements), list(principale)
        self.enregistrees, self.controles_principale = [], 0

    def enregistrer(self, tache, dossier):
        probleme = self.enregistrements.pop(0) if self.enregistrements else ""
        if not probleme:
            self.enregistrees.append(tache.id)
        return probleme

    def controler_principale(self):
        self.controles_principale += 1
        return self.principale.pop(0) if self.principale else (True, "")


def test_une_integration_refusee_compte_comme_une_tentative_refusee():
    c = chantier([tache("A")])
    controles = ControlesReglables(enregistrements=["Conflit avec la branche principale."])
    agent = AgentSimule(perimetres={"A": ["a.py"]})
    Moteur(c, agent, controles).executer()
    a = c.tache("A")
    assert a.etat == "verifie" and a.tentatives == 2 and controles.enregistrees == ["A"]
    assert a.historique[0]["issue"] == "ne_sait_pas"
    assert a.historique[0]["detail"] == "Conflit avec la branche principale."
    assert a.historique[1]["issue"] == "valide"


def test_main_rouge_en_fin_de_chantier_lance_seule_une_reparation():
    c = chantier([tache("A")])
    controles = ControlesReglables(principale=[(False, "FAILED test_x.py::test_y")])
    Moteur(c, AgentSimule(perimetres={"A": ["a.py"]}), controles).executer()
    assert [t.id for t in c.taches] == ["A", "REPARATION-1"]
    reparation = c.tache("REPARATION-1")
    assert reparation.etat == "verifie" and reparation.ajoutee and reparation.perimetre == ["*"]
    assert "FAILED test_x.py::test_y" in reparation.pourquoi
    assert controles.controles_principale == 2 and c.termine and c.demandes == []
    textes = [e["texte"] for e in c.evenements]
    assert any("je lance seul la tâche REPARATION-1" in t for t in textes)
    assert textes[-1].startswith("Chantier terminé : 2 tâches vérifiées sur 2")


def test_les_reparations_sont_bornees_et_le_chantier_ne_se_dit_pas_fini():
    c = chantier([tache("A")])
    rouge = (False, "toujours rouge")
    controles = ControlesReglables(principale=[rouge] * 5)
    Moteur(c, AgentSimule(perimetres={"A": ["a.py"]}), controles).executer()
    assert [t.id for t in c.taches] == ["A", "REPARATION-1", "REPARATION-2"]
    assert not c.termine and controles.controles_principale == 3
    textes = [e["texte"] for e in c.evenements]
    assert any(t.startswith("Les contrôles échouent encore sur la branche principale après 2")
               for t in textes)  # fmt: skip
    assert textes[-1].startswith("Je m'arrête ici")


def test_pas_de_controle_de_main_tant_qu_une_tache_attend_une_decision():
    c = chantier([tache("A")], plafond_modele="haiku", plafond_effort="low")
    controles = ControlesReglables(principale=[(False, "rouge")])
    Moteur(c, AgentSimule({"A": ["ne_sait_pas"]}), controles).executer()
    assert controles.controles_principale == 0 and len(c.taches) == 1


# --- l'historique des tentatives, le verrou et le plafond d'escalade ---------------------------


class VerrouSuivi:
    """Le verrou du moteur, qui sait dire si le fil courant le tient."""

    def __init__(self):
        self._verrou, self._tenant, self._profondeur = threading.RLock(), None, 0

    def __enter__(self):
        self._verrou.acquire()
        self._tenant = threading.get_ident()
        self._profondeur += 1

    def __exit__(self, *erreur):
        self._profondeur -= 1
        if not self._profondeur:
            self._tenant = None
        self._verrou.release()

    def tenu_ici(self):
        return self._tenant == threading.get_ident()


class HistoriqueSurveille(list):
    """Un historique qui note, à chaque ajout, si le verrou du moteur était tenu par l'auteur."""

    def __init__(self, verrou):
        super().__init__()
        self.verrou, self.sous_verrou = verrou, []

    def append(self, entree):
        self.sous_verrou.append(self.verrou.tenu_ici())
        super().append(entree)


def surveiller(m, t):
    m.verrou = VerrouSuivi()
    t.historique = HistoriqueSurveille(m.verrou)
    return t.historique


def test_chaque_tentative_jugee_est_tracee_sous_le_verrou_du_moteur():
    c = chantier([tache("A")])
    m, _ = moteur(c, {"A": ["ne_sait_pas", "ok"]})
    historique = surveiller(m, c.tache("A"))
    m.executer()
    assert [e["issue"] for e in historique] == ["ne_sait_pas", "ne_sait_pas", "valide"]
    assert [e["reprise"] for e in historique] == [False, True, False]
    assert historique.sous_verrou == [True, True, True]


def test_un_arret_avant_le_depart_de_l_ouvrier_est_trace_sous_le_verrou_avec_son_numero():
    c = chantier([tache("A")])

    class Controles(ControlesSimules):
        def preparer(self, t):  # l'arrêt arrive pendant la préparation de la copie
            assert m.arreter(t.id)

    m = Moteur(c, AgentSimule(perimetres={"A": ["a.py"]}), Controles())
    historique = surveiller(m, c.tache("A"))
    m.executer()
    assert c.tache("A").etat == "revenu" and c.tache("A").tentatives == 0
    assert [(e["tentative"], e["issue"]) for e in historique] == [(1, "arretee")]
    assert historique.sous_verrou == [True]


def test_une_tache_rendue_au_redemarrage_garde_le_numero_de_sa_derniere_tentative():
    t = tache("A", etat="en_cours", tentatives=2)
    m, _ = moteur(chantier([t]))
    assert t.etat == "revenu"
    assert [(e["tentative"], e["issue"]) for e in t.historique] == [(2, "panne")]


def test_une_panne_de_l_atelier_est_tracee_au_numero_de_la_tentative_en_cours():
    c = chantier([tache("A")])

    class Controles(ControlesSimules):
        def mecaniques(self, t, dossier):
            raise OSError("disque plein")

    Moteur(c, AgentSimule(perimetres={"A": ["a.py"]}), Controles()).executer()
    a = c.tache("A")
    assert a.etat == "revenu" and a.tentatives == 1
    assert [(e["tentative"], e["issue"]) for e in a.historique] == [(1, "panne")]
    assert "disque plein" in a.historique[0]["detail"]


def test_tout_en_haut_de_l_echelle_la_tache_revient_au_plafond_sans_panne():
    c = chantier([tache("P", type="physique")], plafond_modele="fable", plafond_effort="max")
    m, _ = moteur(c, {"P": ["ne_sait_pas"]}, varie=True)
    m.executer()
    p = c.tache("P")
    assert p.etat == "revenu" and p.tentatives == 2
    assert traces(p) == [(1, "ne_sait_pas", False), (1, "ne_sait_pas", True),
                         (2, "ne_sait_pas", False), (2, "ne_sait_pas", True)]  # fmt: skip
    assert "le plafond d'escalade du contrat est atteint" in c.demandes[-1]["question"]


def test_la_relance_seule_ne_depasse_jamais_le_plafond_du_contrat():
    c = chantier([tache("A")], plafond_modele="opus", plafond_effort="low", max_tentatives=2)
    m, agent = moteur(c, {"A": ["ne_sait_pas"]}, varie=True)
    m.executer()
    a = c.tache("A")
    assert a.etat == "revenu" and a.relances_auto == 0 and a.tentatives == 2
    ouvriers = [(x["modele"], x["effort"]) for x in agent.appels if x["role"] == "ouvrier"]
    assert ouvriers == [("sonnet", "low"), ("sonnet", "low"), ("opus", "low"), ("opus", "low")]
    assert "2 tentatives sans succès" in c.demandes[-1]["question"]


# --- la mesure du temps : chaque phase de chaque tentative, l'attente avant le départ ---------

PAS = {"preparer": 1.0, "ouvrier": 10.0, "mecaniques": 3.0, "verificateur": 20.0}
PAS |= {"enregistrer": 2.0, "annuler": 5.0}


class Horloge:
    """Une horloge de test : elle n'avance que quand on le lui dit, jamais avec le temps réel."""

    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def moteur_chronometre(c, scenario=None, paralleles=3, varie=False):
    """Un moteur dont chaque étape fait avancer l'horloge de test d'un pas connu (`PAS`)."""
    horloge = Horloge()

    class Controles(ControlesSimules):
        commandes = ["python3 -m pytest -q"]

        def preparer(self, t):
            horloge.t += PAS["preparer"]

        def mecaniques(self, t, dossier):
            horloge.t += PAS["mecaniques"]
            return True, ""

        def enregistrer(self, t, dossier):
            horloge.t += PAS["enregistrer"]
            return ""

        def annuler(self, t, dossier):
            horloge.t += PAS["annuler"]

    class Agent(AgentVarie if varie else AgentSimule):
        def executer(self, consigne, modele, effort, dossier, lecture_seule=False, contexte=None,
                     copie_jetable=False, reprendre=None):  # fmt: skip
            horloge.t += PAS[contexte["role"]]
            return super().executer(consigne, modele, effort, dossier, lecture_seule, contexte,
                                    copie_jetable, reprendre)  # fmt: skip

    agent = Agent(scenario or {}, perimetres={t.id: t.perimetre for t in c.taches})
    profil = {"paralleles": paralleles}
    return Moteur(c, agent, Controles(), profil, horloge=horloge), horloge


DUREES_ACCEPTEE = {"preparation": 1.0, "ouvrier": 10.0, "perimetre": 0.0, "controles": 3.0}
DUREES_ACCEPTEE |= {"verificateur": 20.0, "enregistrement": 2.0}
DUREE_ACCEPTEE = sum(DUREES_ACCEPTEE.values())  # 36 secondes


def test_chaque_phase_d_une_tentative_garde_sa_duree():
    c = chantier([tache("A")])
    m, _ = moteur_chronometre(c)
    m.executer()
    (entree,) = c.tache("A").historique
    assert entree["issue"] == "valide"
    assert entree["durees"] == {"attente": 0.0, **DUREES_ACCEPTEE}


def test_une_tentative_refusee_sa_reprise_et_la_suivante_ont_chacune_leurs_durees():
    c = chantier([tache("A")])
    m, _ = moteur_chronometre(c, {"A": ["bacle", "ok"]})
    m.executer()
    refusee, reprise, acceptee = c.tache("A").historique
    assert [(e["tentative"], e["issue"], e["reprise"]) for e in (refusee, reprise, acceptee)] == [
        (1, "bacle", False), (1, "bacle", True), (2, "valide", False),
    ]  # fmt: skip
    sans_enregistrement = {k: v for k, v in DUREES_ACCEPTEE.items() if k != "enregistrement"}
    assert refusee["durees"] == {"attente": 0.0, **sans_enregistrement}
    # La reprise n'a pas de préparation : la copie est gardée ; elle a sa phase, mesurée.
    assert reprise["durees"] == {"reprise": PAS["ouvrier"], "perimetre": 0.0, "controles": 3.0,
                                 "verificateur": 20.0}  # fmt: skip
    assert acceptee["durees"] == DUREES_ACCEPTEE  # l'attente n'appartient qu'au départ
    from atelier import archives

    temps = archives.temps_par_groupe(c.tache("A"))  # la reprise compte dans « écrire »
    assert temps["ecrire"] == 2 * (PAS["preparer"] + PAS["ouvrier"]) + PAS["ouvrier"]
    assert temps["autre"] == 0


def test_une_tache_qui_attend_sa_dependance_ne_compte_son_attente_qu_apres_sa_verification():
    """Prête dès que sa dépendance est vérifiée : le temps de la dépendance n'est pas une file."""
    c = chantier([tache("A"), tache("B", depend_de=["A"])])
    m, horloge = moteur_chronometre(c)
    m.executer()
    attente_b = c.tache("B").historique[0]["durees"]["attente"]
    assert attente_b == 0.0
    assert horloge.t == 1000.0 + 2 * DUREE_ACCEPTEE  # B est bien partie après les 36 s de A


def test_une_tache_bloquee_par_un_perimetre_attend_le_temps_de_la_tache_qui_le_tient():
    c = chantier([tache("A"), tache("C", perimetre=["a.py"])])
    m, _ = moteur_chronometre(c)
    m.executer()
    assert c.tache("A").historique[0]["durees"]["attente"] == 0.0
    assert c.tache("C").historique[0]["durees"]["attente"] == DUREE_ACCEPTEE


def test_une_tache_qui_attend_une_place_compte_le_temps_de_celle_qui_l_occupe():
    c = chantier([tache("A"), tache("B")])
    m, _ = moteur_chronometre(c, paralleles=1)
    m.executer()
    assert c.tache("B").historique[0]["durees"]["attente"] == DUREE_ACCEPTEE


def test_une_relance_decidee_par_la_personne_compte_son_attente_depuis_la_decision():
    c = chantier([tache("A", type="physique")], plafond_modele="fable", plafond_effort="max")
    m, horloge = moteur_chronometre(c, {"A": ["ne_sait_pas", "ne_sait_pas", "ok"]}, varie=True)
    m.executer()
    assert c.tache("A").etat == "revenu"
    horloge.t += 600  # la personne met dix minutes à répondre : ce n'est pas une file d'attente
    m.repondre(c.demandes[-1]["id"], RELANCER_TEL)
    horloge.t += 4
    m.executer()
    entrees = c.tache("A").historique
    assert [e["issue"] for e in entrees] == ["ne_sait_pas"] * 4 + ["valide"]
    assert [e["reprise"] for e in entrees] == [False, True, False, True, False]
    assert entrees[4]["durees"]["attente"] == 0.0  # le moteur relancé part aussitôt


def test_un_arret_pendant_la_preparation_garde_la_duree_de_la_preparation():
    c = chantier([tache("A")])
    horloge = Horloge()

    class Controles(ControlesSimules):
        def preparer(self, t):
            horloge.t += 7
            assert m.arreter(t.id)

    m = Moteur(c, AgentSimule(perimetres={"A": ["a.py"]}), Controles(), horloge=horloge)
    m.executer()
    (entree,) = c.tache("A").historique
    assert entree["issue"] == "arretee"
    assert entree["durees"] == {"attente": 0.0, "preparation": 7.0}


def test_la_phase_en_cours_se_lit_sur_l_horloge_du_moteur():
    c = chantier([tache("A")])
    horloge = Horloge()
    m = Moteur(c, AgentSimule(), ControlesSimules(), horloge=horloge)
    m._phase(c.tache("A"), "Contrôle du périmètre")
    horloge.t += 42
    assert m.phase("A") == {"texte": "Contrôle du périmètre", "depuis_s": 42}


def test_chaque_phrase_de_phase_retrouve_sa_cle():
    from atelier.moteur import PHASES, cle_de_phase

    for cle, modele in PHASES.items():
        assert cle_de_phase(modele.format("x") + "pytest -q") == cle
    assert cle_de_phase("Une phase que personne n'a déclarée") == "autre"


def test_une_tache_rendue_au_redemarrage_n_a_aucune_duree_mesuree():
    t = tache("A", etat="en_cours", tentatives=1)
    moteur(chantier([t]))
    assert t.historique[-1]["durees"] == {}


def test_les_durees_survivent_a_l_arret_et_un_etat_sans_durees_se_relit(tmp_path):
    c = chantier([tache("A")])
    m, _ = moteur_chronometre(c, {"A": ["bacle", "ok"]})
    m.executer()
    c.sauver(tmp_path / "etat.json")
    relu = Chantier.charger(tmp_path / "etat.json")
    assert [e["durees"] for e in relu.tache("A").historique] == [
        e["durees"] for e in c.tache("A").historique
    ]
    ancien = c.en_dict()
    for t in ancien["taches"]:
        for entree in t["historique"]:
            del entree["durees"]  # un état écrit avant les mesures
    vieux = Chantier.depuis_dict(ancien)
    assert [e["issue"] for e in vieux.tache("A").historique] == ["bacle", "bacle", "valide"]
    vieux.taches.append(tache("B"))
    moteur(vieux)[0].executer()  # et le moteur repart dessus
    assert vieux.tache("B").etat == "verifie" and "durees" in vieux.tache("B").historique[0]


def test_la_mesure_ne_change_rien_a_ce_que_le_moteur_fait():
    def deroule(chronometre):
        c = chantier([tache("A"), tache("B", depend_de=["A"]), tache("C", perimetre=["a.py"])])
        scenario = {"A": ["bacle", "ok"], "C": ["ne_sait_pas", "ok"]}
        m, agent = moteur_chronometre(c, scenario, 1) if chronometre else moteur(c, scenario)
        if not chronometre:
            m.profil = {"paralleles": 1}
        m.executer()
        appels = [(x["role"], x.get("tache"), x["modele"]) for x in m.agent.appels]
        sans = [[{k: v for k, v in e.items() if k != "durees"} for e in t.historique]
                for t in c.taches]  # fmt: skip
        return appels, [e["texte"] for e in c.evenements], [t.etat for t in c.taches], sans

    assert deroule(True) == deroule(False)


# --- la reprise à chaud après un refus ------------------------------------------------------

ESSAIS = "Détail de mes essais : " + "rien de plus. " * 40
VERDICT_LONG = (
    "Je recale ce livrable pour deux points.\n"
    "1. Le critère 1 n'est pas tenu : la fonction ne gère pas la liste vide.\n"
    "2. Le test ajouté ne peut pas échouer : il compare la sortie à elle-même.\n"
    f"{ESSAIS}\n"
    '{"valide": false, "motif": "bacle", "resume": "Deux points ne sont pas tenus."}'
)


class AgentParRang(AgentSimule):
    """Lit l'issue au rang de l'appel, par tâche et par rôle, reprises comprises.

    L'agent simulé rejoue à la reprise l'issue de sa tentative : celui-ci peut faire finir une
    reprise autrement que la passe refusée. Il garde chaque consigne reçue et note chaque agent
    dans `journal` ; un vérificateur rend, appel après appel, le texte de `textes` s'il y en a un.
    """

    def __init__(self, issues=None, textes=None, journal=None, **champs):
        super().__init__(**champs)
        self.issues, self.textes = issues or {}, {k: list(v) for k, v in (textes or {}).items()}
        self.journal = journal if journal is not None else []
        self.rangs, self.consignes = {}, []

    def _issue(self, contexte):
        cle = (contexte.get("tache", ""), contexte.get("role", ""))
        rang = self.rangs.get(cle, 0)
        self.rangs[cle] = rang + 1
        suite = self.issues.get(cle) or ["ok"]
        return suite[min(rang, len(suite) - 1)]

    def executer(self, consigne, modele, effort, dossier, lecture_seule=False, contexte=None,
                 copie_jetable=False, reprendre=None):  # fmt: skip
        role = (contexte or {}).get("role")
        self.consignes.append((role, reprendre is not None, consigne))
        self.journal.append("reprise" if reprendre is not None else role)
        resultat = super().executer(consigne, modele, effort, dossier, lecture_seule, contexte,
                                    copie_jetable, reprendre)  # fmt: skip
        textes = self.textes.get((contexte or {}).get("tache"))
        if role == "verificateur" and textes:
            texte = textes.pop(0)
            resultat.texte = resultat.texte if texte is None else texte
        return resultat


class ControlesComptes(ControlesSimules):
    """Des contrôles simulés qui notent chaque étape, et chaque copie préparée ou jetée.

    `sorties` : ce que rendent les contrôles automatiques, appel après appel, puis ils passent.
    """

    commandes = ["pytest -q"]

    def __init__(self, sorties=(), journal=None):
        self.sorties = list(sorties)
        self.journal = journal if journal is not None else []
        self.preparees, self.annulees, self.tentatives_vues = [], [], []

    def preparer(self, t):
        self.preparees.append(t.id)

    def fichiers_modifies(self, t, dossier, resultat):
        self.journal.append("perimetre")
        self.tentatives_vues.append(t.tentatives)
        return super().fichiers_modifies(t, dossier, resultat)

    def mecaniques(self, t, dossier):
        self.journal.append("controles")
        return self.sorties.pop(0) if self.sorties else (True, "")

    def annuler(self, t, dossier):
        self.annulees.append(t.id)


def moteur_a_reprises(taches, issues=None, textes=None, sorties=(), agent_cls=AgentParRang,
                      **contrat):  # fmt: skip
    journal = []
    c = chantier(taches, **contrat)
    agent = agent_cls(issues, textes, journal, perimetres={t.id: t.perimetre for t in taches})
    controles = ControlesComptes(sorties, journal)
    return c, Moteur(c, agent, controles), agent, controles


def textes_du_fil(c):
    return [e["texte"] for e in c.evenements]


def consignes_de(agent, role):
    return [consigne for r, _, consigne in agent.consignes if r == role]


def test_un_refus_du_verificateur_est_repris_a_chaud_et_le_livrable_entre():
    c, m, agent, controles = moteur_a_reprises(
        [tache("A")], {("A", "verificateur"): ["bacle", "ok"]}, {"A": [VERDICT_LONG]}
    )
    m.executer()
    a = c.tache("A")
    assert a.etat == "verifie" and c.termine
    assert a.tentatives == 1 and c.agents_lances == 4  # un départ, quatre agents
    assert controles.preparees == ["A"] and controles.annulees == []  # la même copie, gardée
    assert controles.tentatives_vues == [1, 1]  # la reprise ne compte pas de tentative
    (reprise,) = agent.reprises
    assert (reprise["session"], reprise["role"], reprise["tentative"]) == (
        "session-simulee-1", "ouvrier", 1,
    )  # fmt: skip
    assert VERDICT_LONG in reprise["message"]  # le verdict en entier, pas son résumé
    # Périmètre puis contrôles sont rejoués avant le second vérificateur, au même dosage.
    assert controles.journal == ["ouvrier", "perimetre", "controles", "verificateur",
                                 "reprise", "perimetre", "controles", "verificateur"]  # fmt: skip
    verificateurs = [(x["modele"], x["effort"]) for x in agent.appels
                     if x["role"] == "verificateur"]  # fmt: skip
    assert verificateurs == [("opus", "medium")] * 2
    premiere, seconde = consignes_de(agent, "verificateur")
    assert "[début du verdict précédent]" not in premiere
    assert "[début du verdict précédent]" in seconde and VERDICT_LONG in seconde
    assert traces(a) == [(1, "bacle", False), (1, "valide", True)]
    assert [e["origine"] for e in a.historique] == ["verdict", ""]
    assert a.historique[0]["verdict"] == VERDICT_LONG
    assert '"valide": true' in a.historique[1]["verdict"]
    fil = " ".join(textes_du_fil(c))
    assert "Je redonne la main au même ouvrier" in fil and "Seconde chance" not in fil
    assert "Vérificateur lancé sur la correction (Opus, effort moyen)." in textes_du_fil(c)


def test_une_reprise_refusee_jette_la_copie_une_fois_et_monte_d_un_cran():
    c, m, agent, controles = moteur_a_reprises(
        [tache("A")], {("A", "verificateur"): ["bacle", "bacle", "ok"]}, {"A": [None, VERDICT_LONG]}
    )
    suites, apres_echec = [], m._apres_echec
    m._apres_echec = lambda *arguments: suites.append(arguments) or apres_echec(*arguments)
    m.executer()
    a = c.tache("A")
    assert a.etat == "verifie" and a.tentatives == 2 and c.montees == 1
    assert controles.annulees == ["A"] and controles.preparees == ["A", "A"]
    assert len(suites) == 1 and suites[0][-1] is True  # une seule décision, après la reprise
    assert departs(agent) == [("sonnet", "low"), ("sonnet", "medium")]
    assert traces(a) == [(1, "bacle", False), (1, "bacle", True), (2, "valide", False)]
    # Le départ neuf reçoit le verdict entier de la seconde vérification.
    depart_neuf = [cons for role, repris, cons in agent.consignes if role == "ouvrier"][-1]
    assert VERDICT_LONG in depart_neuf
    assert any(t.startswith("Refusée après sa reprise.") and "Je monte d'un cran : Sonnet, "
               "effort moyen." in t for t in textes_du_fil(c))  # fmt: skip


def test_un_debord_est_repris_avec_la_liste_des_fichiers_hors_perimetre():
    c, m, agent, controles = moteur_a_reprises([tache("A")], {("A", "ouvrier"): ["deborde", "ok"]})
    m.executer()
    a = c.tache("A")
    assert a.etat == "verifie" and a.tentatives == 1
    (reprise,) = agent.reprises
    assert "- `hors_perimetre.txt`" in reprise["message"]
    assert "Le contrôle du périmètre a refusé ton livrable" in reprise["message"]
    assert [(role, repris) for role, repris, _ in agent.consignes] == [
        ("ouvrier", False), ("ouvrier", True), ("verificateur", False),
    ]  # fmt: skip
    (verification,) = consignes_de(agent, "verificateur")
    assert "[début du verdict précédent]" not in verification  # la vérification complète
    assert traces(a) == [(1, "deborde", False), (1, "valide", True)]
    assert [e["origine"] for e in a.historique] == ["perimetre", ""]
    assert controles.preparees == ["A"] and controles.annulees == []


def test_des_controles_rouges_sont_repris_avec_la_fin_de_leur_sortie():
    sortie = "DEBUT-COUPE " + "x" * 5000 + " FAILED tests/test_a.py::test_rend"
    c, m, agent, controles = moteur_a_reprises([tache("A")], sorties=[(False, sortie)])
    m.executer()
    a = c.tache("A")
    assert a.etat == "verifie" and a.tentatives == 1
    (reprise,) = agent.reprises
    assert sortie[-4000:] in reprise["message"] and "DEBUT-COUPE" not in reprise["message"]
    assert controles.journal == ["ouvrier", "perimetre", "controles",
                                 "reprise", "perimetre", "controles", "verificateur"]  # fmt: skip
    (verification,) = consignes_de(agent, "verificateur")
    assert "[début du verdict précédent]" not in verification
    assert traces(a) == [(1, "ne_sait_pas", False), (1, "valide", True)]
    assert [e["origine"] for e in a.historique] == ["controles", ""]


class AgentOublieux(AgentParRang):
    """Perd la session de l'ouvrier avant sa reprise : oubliée, ou jamais connue."""

    maniere = "oubliee"

    def executer(self, consigne, modele, effort, dossier, lecture_seule=False, contexte=None,
                 copie_jetable=False, reprendre=None):  # fmt: skip
        resultat = super().executer(consigne, modele, effort, dossier, lecture_seule, contexte,
                                    copie_jetable, reprendre)  # fmt: skip
        if self.maniere == "oubliee" and contexte["role"] == "verificateur":
            self.oublier_sessions()
        if self.maniere == "inconnue" and contexte["role"] == "ouvrier":
            resultat.session = ""
        return resultat


@pytest.mark.parametrize("maniere", ["oubliee", "inconnue"])
def test_une_session_perdue_garde_la_suite_d_un_refus_sans_reprise(maniere):
    c, m, agent, controles = moteur_a_reprises(
        [tache("A")], {("A", "verificateur"): ["bacle", "ok"]}, {"A": [VERDICT_LONG]},
        agent_cls=AgentOublieux,
    )  # fmt: skip
    agent.maniere = maniere
    m.executer()
    a = c.tache("A")
    assert a.etat == "verifie" and a.tentatives == 2  # le seul départ de plus : la seconde chance
    assert agent.reprises == []  # demandée, mais impossible
    assert [x.get("reprise") for x in agent.appels if x["role"] == "ouvrier"][1] is not None
    assert c.agents_lances == 4  # la reprise impossible ne compte pas
    assert traces(a) == [(1, "bacle", False), (2, "valide", False)]  # ni entrée de plus
    assert "reprise" not in a.historique[1]["durees"]
    assert controles.annulees == ["A"] and controles.preparees == ["A", "A"]
    fil = textes_du_fil(c)
    assert sum("ne peut pas être reprise" in t for t in fil) == 1
    assert any("Seconde chance au même niveau" in t for t in fil)
    assert VERDICT_LONG in consignes_de(agent, "ouvrier")[-1]  # le départ neuf a le verdict


def test_au_plafond_la_reprise_refusee_d_un_premier_depart_repart_au_meme_niveau():
    c = chantier([tache("A")], plafond_modele="sonnet", plafond_effort="low")
    m, agent = moteur(c, {"A": ["bacle", "ok"]}, varie=True)
    m.executer()
    a = c.tache("A")
    assert a.etat == "verifie" and a.tentatives == 2 and c.montees == 0
    assert departs(agent) == [("sonnet", "low"), ("sonnet", "low")]
    assert any("je repars de zéro au même niveau" in t for t in textes_du_fil(c))


def test_au_plafond_un_second_depart_refuse_apres_sa_reprise_revient():
    c = chantier([tache("A")], plafond_modele="sonnet", plafond_effort="low")
    m, agent = moteur(c, {"A": ["bacle"]}, varie=True)
    m.executer()
    a = c.tache("A")
    assert a.etat == "revenu" and a.tentatives == 2 and len(c.demandes) == 1
    assert departs(agent) == [("sonnet", "low"), ("sonnet", "low")]
    assert [r["tentative"] for r in agent.reprises] == [1, 2]
    assert "le plafond d'escalade du contrat est atteint" in c.demandes[0]["question"]


def test_avec_un_vrai_depot_la_reprise_retrouve_le_travail_de_la_premiere_passe(tmp_path):
    def git(*arguments):
        subprocess.run(["git", *arguments], cwd=tmp_path, check=True, capture_output=True)

    git("init", "-q", "-b", "main")
    git("config", "user.name", "Essai")
    git("config", "user.email", "essai@example.invalid")
    (tmp_path / "LISEZMOI.md").write_text("socle\n", "utf-8")
    git("add", "-A")
    git("commit", "-q", "-m", "socle")
    vus, dossiers, preparees, annulees = [], [], [], []

    class Agent(AgentParRang):
        def executer(self, consigne, modele, effort, dossier, lecture_seule=False, contexte=None,
                     copie_jetable=False, reprendre=None):  # fmt: skip
            if contexte["role"] == "ouvrier" and reprendre is None:
                dossiers.append(dossier)
                (dossier / "a_premiere.py").write_text("# première passe\n", "utf-8")
            if reprendre is not None:
                vus.append((dossier, (dossier / "a_premiere.py").read_text("utf-8")))
            return super().executer(consigne, modele, effort, dossier, lecture_seule, contexte,
                                    copie_jetable, reprendre)  # fmt: skip

    class Controles(ControlesGit):
        def preparer(self, t):
            preparees.append(t.id)
            return super().preparer(t)

        def annuler(self, t, dossier):
            annulees.append(t.id)
            return super().annuler(t, dossier)

    c = chantier([tache("A", perimetre=["a.py", "a_premiere.py"])])
    agent = Agent({("A", "verificateur"): ["bacle", "ok"]}, perimetres={"A": ["a.py"]})
    Moteur(c, agent, Controles(tmp_path, commandes=["test -f a_premiere.py"])).executer()
    assert vus == [(dossiers[0], "# première passe\n")]  # même dossier, travail encore là
    assert preparees == ["A"] and annulees == []
    assert c.tache("A").etat == "verifie"
    assert traces(c.tache("A")) == [(1, "bacle", False), (1, "valide", True)]
    assert (tmp_path / "a_premiere.py").read_text("utf-8") == "# première passe\n"
    assert (tmp_path / "a.py").exists()


def test_un_ouvrier_repris_qui_deborde_est_refuse_sans_seconde_verification():
    issues = {("A", "verificateur"): ["bacle", "ok"], ("A", "ouvrier"): ["ok", "deborde", "ok"]}
    c, m, agent, controles = moteur_a_reprises([tache("A")], issues)
    m.executer()
    a = c.tache("A")
    assert a.etat == "verifie" and a.tentatives == 2
    assert [(role, repris) for role, repris, _ in agent.consignes] == [
        ("ouvrier", False), ("verificateur", False), ("ouvrier", True),
        ("ouvrier", False), ("verificateur", False),
    ]  # fmt: skip
    assert traces(a) == [(1, "bacle", False), (1, "deborde", True), (2, "valide", False)]
    assert [e["origine"] for e in a.historique] == ["verdict", "perimetre", ""]
    assert {e["origine"] for e in a.historique} <= {"", *ORIGINES}
    assert controles.annulees == ["A"]
    assert departs(agent) == [("sonnet", "low"), ("opus", "low")]
    assert "[début du verdict précédent]" not in consignes_de(agent, "verificateur")[-1]


def test_des_controles_rouges_apres_la_reprise_retiennent_le_verificateur():
    sorties = [(True, ""), (False, "FAILED après la correction")]
    c, m, agent, controles = moteur_a_reprises(
        [tache("A")], {("A", "verificateur"): ["bacle", "ok"]}, sorties=sorties
    )
    m.executer()
    a = c.tache("A")
    assert controles.journal == [
        "ouvrier", "perimetre", "controles", "verificateur",
        "reprise", "perimetre", "controles",
        "ouvrier", "perimetre", "controles", "verificateur",
    ]  # fmt: skip
    assert traces(a) == [(1, "bacle", False), (1, "ne_sait_pas", True), (2, "valide", False)]
    assert [e["origine"] for e in a.historique] == ["verdict", "controles", ""]
    assert "FAILED après la correction" in a.historique[1]["detail"]


def test_un_arret_pendant_la_reprise_rend_la_tache_et_jette_la_copie():
    c, m, agent, controles = moteur_a_reprises([tache("A")], {("A", "verificateur"): ["bacle"]})
    arrets = []

    def entendre(evenement):  # l'ouvrier repris vient de prendre son poste
        if agent.reprises and evenement["type"] == "outil" and not arrets:
            arrets.append(m.arreter("A"))

    agent.sur_evenement = entendre
    m.executer()
    a = c.tache("A")
    assert arrets == [True]
    assert a.etat == "revenu" and a.tentatives == 1 and a.montees == 0
    assert [(role, repris) for role, repris, _ in agent.consignes] == [
        ("ouvrier", False), ("verificateur", False), ("ouvrier", True),
    ]  # fmt: skip
    assert traces(a) == [(1, "bacle", False), (1, "arretee", True)]
    assert controles.annulees == ["A"]
    (demande,) = c.demandes
    assert demande["question"].endswith("arrêtée par toi.")
    fil = " ".join(textes_du_fil(c))
    assert "Seconde chance" not in fil and "monte d'un cran" not in fil
    assert m._arretees == set()


def test_un_arret_entre_le_refus_et_la_reprise_l_empeche_de_partir():
    reponses = []

    def rappel():
        dernier = c.evenements[-1]["texte"] if c.evenements else ""
        if not reponses and "Je redonne la main" in dernier:
            reponses.append(m.arreter("A"))

    c = chantier([tache("A")])
    agent, controles = AgentSimule({"A": ["bacle"]}, perimetres={"A": ["a.py"]}), ControlesComptes()
    m = Moteur(c, agent, controles, sur_changement=rappel)
    historique = surveiller(m, c.tache("A"))
    m.executer()
    a = c.tache("A")
    assert reponses == [True] and agent.reprises == []
    assert [x["role"] for x in agent.appels] == ["ouvrier", "verificateur"]
    assert c.agents_lances == 2 and a.tentatives == 1 and a.montees == 0
    assert traces(a) == [(1, "bacle", False), (1, "arretee", True)]
    assert historique.sous_verrou == [True, True]
    assert controles.annulees == ["A"] and a.etat == "revenu"
    assert c.demandes[-1]["question"].endswith("arrêtée par toi.")
    fil = " ".join(textes_du_fil(c))
    assert "Seconde chance" not in fil and "monte d'un cran" not in fil


class AgentReprisEnEchec(AgentParRang):
    """L'ouvrier repris finit sur une erreur donnée : délai dépassé, par exemple."""

    erreur = ""

    def executer(self, consigne, modele, effort, dossier, lecture_seule=False, contexte=None,
                 copie_jetable=False, reprendre=None):  # fmt: skip
        resultat = super().executer(consigne, modele, effort, dossier, lecture_seule, contexte,
                                    copie_jetable, reprendre)  # fmt: skip
        if reprendre is not None and self.erreur:
            return Resultat(ok=False, erreur=self.erreur, session=resultat.session)
        return resultat


@pytest.mark.parametrize("erreur", ["", "Claude Code n'a pas répondu dans le délai de 3600 s."])
def test_un_ouvrier_repris_qui_finit_en_erreur_ou_au_delai_vaut_reprise_refusee(erreur):
    issues = {("A", "verificateur"): ["bacle", "ok"], ("A", "ouvrier"): ["ok", "erreur", "ok"]}
    c, m, agent, controles = moteur_a_reprises([tache("A")], issues, agent_cls=AgentReprisEnEchec)
    agent.erreur = erreur
    m.executer()
    a = c.tache("A")
    assert a.etat == "verifie" and a.tentatives == 2
    assert traces(a) == [(1, "bacle", False), (1, "ne_sait_pas", True), (2, "valide", False)]
    assert [e["origine"] for e in a.historique] == ["verdict", "agent", ""]
    assert (erreur or "Arrêt simulé de l'agent.") in a.historique[1]["detail"]
    assert controles.journal.count("verificateur") == 2  # aucun après la reprise en erreur
    # Une erreur d'agent ne fait pas monter d'un cran (V3b) : le départ neuf reste au même niveau.
    assert controles.annulees == ["A"] and departs(agent) == [("sonnet", "low")] * 2
    assert c.montees == 0
    assert any(t.startswith("Refusée après sa reprise.") and "Seconde chance au même niveau" in t
               for t in textes_du_fil(c))  # fmt: skip


def test_jamais_deux_reprises_pour_un_meme_depart():
    c = chantier([tache("A")], plafond_modele="fable", plafond_effort="high")
    m, agent = moteur(c, {"A": ["ne_sait_pas"]}, varie=True)
    m.executer()
    a = c.tache("A")
    assert a.etat == "revenu" and a.tentatives >= 4
    # Une reprise par départ, ni plus ni moins, chacune au numéro de son départ.
    assert [r["tentative"] for r in agent.reprises] == list(range(1, a.tentatives + 1))
    assert sum(e["reprise"] for e in a.historique) == a.tentatives


def test_apres_un_redemarrage_en_pleine_reprise_la_tache_repart_d_une_copie_propre():
    c = chantier([tache("A")])
    instantanes = []

    class Agent(AgentSimule):
        def executer(self, consigne, modele, effort, dossier, lecture_seule=False, contexte=None,
                     copie_jetable=False, reprendre=None):  # fmt: skip
            if reprendre is not None and not instantanes:
                instantanes.append(c.en_dict())  # l'état sauvé pendant la reprise
            return super().executer(consigne, modele, effort, dossier, lecture_seule, contexte,
                                    copie_jetable, reprendre)  # fmt: skip

    agent = Agent({"A": ["bacle", "ok"]}, perimetres={"A": ["a.py"]})
    Moteur(c, agent, ControlesSimules()).executer()
    relu = Chantier.depuis_dict(instantanes[0])
    t = relu.tache("A")
    assert t.etat == "en_cours" and traces(t) == [(1, "bacle", False)]
    neuf, controles = AgentSimule(perimetres={"A": ["a.py"]}), ControlesComptes()
    m = Moteur(relu, neuf, controles)  # le redémarrage : la tâche revient à la personne
    assert t.etat == "revenu" and traces(t)[-1] == (1, "panne", False)
    assert neuf.appels == []  # rien n'est relancé seul
    m.repondre(relu.demandes[-1]["id"], RELANCER_TEL)
    m.executer()
    assert t.etat == "verifie" and t.tentatives == 2
    assert controles.preparees == ["A"]  # une copie propre
    assert "reprise" not in neuf.appels[0] and neuf.reprises == []  # une session neuve


class AgentVerificateurEnErreur(AgentParRang):
    """Les `en_erreur` premiers vérificateurs s'arrêtent sur une erreur, même avec un verdict.

    Deux par défaut : le premier, puis celui que le moteur relance une fois sur la même copie.
    """

    en_erreur = 2

    def executer(self, consigne, modele, effort, dossier, lecture_seule=False, contexte=None,
                 copie_jetable=False, reprendre=None):  # fmt: skip
        resultat = super().executer(consigne, modele, effort, dossier, lecture_seule, contexte,
                                    copie_jetable, reprendre)  # fmt: skip
        premier = sum(role == "verificateur" for role, _, _ in self.consignes) <= self.en_erreur
        if contexte["role"] == "verificateur" and premier:
            texte = '{"valide": false, "motif": "bacle", "resume": "Inachevé."}'
            return Resultat(ok=False, erreur="Panne du vérificateur.", texte=texte)
        return resultat


CAS_SANS_REPRISE = ["erreur_agent", "consigne", "verdict_illisible", "verificateur_en_erreur"]
CAS_SANS_REPRISE += ["integration"]


@pytest.mark.parametrize("cas", CAS_SANS_REPRISE)
def test_ces_refus_ne_se_reprennent_pas(cas):
    perimetres, agent_cls, controles = {"A": ["a.py"]}, AgentParRang, ControlesComptes()
    issues, textes = {}, {}
    if cas == "erreur_agent":
        issues = {("A", "ouvrier"): ["erreur", "ok"]}
    elif cas == "consigne":
        issues = {("A", "verificateur"): ["consigne"]}
    elif cas == "verdict_illisible":  # deux : le vérificateur illisible est relancé une fois
        textes = {"A": ["J'ai relu, mais je n'ai pas eu le temps de conclure."] * 2}
    elif cas == "verificateur_en_erreur":
        agent_cls = AgentVerificateurEnErreur
    else:
        controles = ControlesReglables(enregistrements=["Conflit avec la branche principale."])
    agent = agent_cls(issues, textes, perimetres=perimetres)
    c = chantier([tache("A")])
    Moteur(c, agent, controles).executer()
    assert agent.reprises == []
    assert not any("reprise" in x for x in agent.appels)
    fil = " ".join(textes_du_fil(c))
    assert "Je redonne la main" not in fil
    if cas == "consigne":
        assert c.tache("A").etat == "revenu" and c.tache("A").tentatives == 1
    else:
        assert "Seconde chance au même niveau" in fil and c.tache("A").etat == "verifie"
        assert c.tache("A").tentatives == 2


def test_le_verdict_garde_et_transmis_est_borne_a_ses_8000_derniers_caracteres():
    long = "DEBUT-COUPE " + "constat " * 1500
    long += '\n{"valide": false, "motif": "bacle", "resume": "Trop long."}'
    c, m, agent, _ = moteur_a_reprises(
        [tache("A")], {("A", "verificateur"): ["bacle", "ok"]}, {"A": [long]}
    )
    m.executer()
    assert len(long) > 8000
    assert c.tache("A").historique[0]["verdict"] == long[-8000:]
    message = agent.reprises[0]["message"]
    assert long[-8000:].strip() in message and "DEBUT-COUPE" not in message
    seconde = consignes_de(agent, "verificateur")[1]
    assert long[-8000:].strip() in seconde and "DEBUT-COUPE" not in seconde


# --- le blocage : une tâche que relancer ne ferait pas avancer (V3b) ------------------------

UV = "Bash(uv sync)"
EMPECHEMENT_UV = "uv sync — l'outil a été refusé : je ne peux pas aller plus loin."
CLES_D_UNE_DEMANDE = {"id", "tache", "question", "options", "reponse"}


def blocages(c):
    return [d for d in c.demandes if d.get("nature") == "blocage"]


def moteur_empeche(taches, scenario=None, empeches=None, agent_cls=AgentSimule):
    c = chantier(taches)
    perimetres = {t.id: t.perimetre for t in taches}
    agent = agent_cls(scenario or {}, perimetres=perimetres, empeches=empeches or {"A": [UV]})
    controles = ControlesComptes()
    return c, Moteur(c, agent, controles), agent, controles


def test_un_ouvrier_empeche_bloque_la_tache_sans_reprise_ni_depart_neuf():
    c, m, agent, controles = moteur_empeche([tache("A")], {"A": ["ne_sait_pas"]})
    assert m.sur_blocage is None
    m.executer()
    a = c.tache("A")
    assert [x["role"] for x in agent.appels] == ["ouvrier", "verificateur"]  # un seul ouvrier
    assert agent.reprises == [] and a.tentatives == 1 and a.montees == 0
    assert a.etat == "revenu" and not c.termine
    assert controles.preparees == ["A"] and controles.annulees == ["A"]
    assert traces(a) == [(1, "ne_sait_pas", False)]  # le blocage n'ajoute pas d'entrée
    (demande,) = c.demandes
    assert set(demande) == CLES_D_UNE_DEMANDE | {"nature", "preuves", "empechements"}
    assert (demande["nature"], demande["tache"], demande["reponse"]) == ("blocage", "A", None)
    assert demande["id"] == "A-1"
    assert demande["options"] == [RELANCER_TEL, RELANCER, ABANDONNER]
    assert demande["empechements"] == [EMPECHEMENT_UV, UV]
    assert demande["preuves"] == [
        "Tentative 1, vérificateur : Le calcul est faux sur un cas de référence."
    ]
    question = demande["question"]
    assert question.startswith(
        "Tâche A, « Tâche A » : elle est bloquée parce qu'un agent a été empêché de travailler : "
        f"« {EMPECHEMENT_UV[:-1]} » ; « Bash(uv sync) ». La relancer telle quelle buterait"
    )
    assert question.endswith("Le refus : « Le calcul est faux sur un cas de référence ».")
    fil = textes_du_fil(c)
    assert "Seconde chance" not in " ".join(fil) and "Je redonne la main" not in " ".join(fil)
    assert f"J'ai besoin de toi : {question.split(' : ', 1)[1]}" in fil


EMPECHE_PAR_LE_VERDICT = (
    "Je n'ai pas pu lancer les tests.\n"
    '{"valide": false, "motif": "ne_sait_pas", "resume": "Rien ne prouve que les tests '
    'passent.", "empeche": ["uv run pytest -q — refusé"]}'
)
EMPECHE_SANS_VERDICT = "EMPÊCHÉ : uv run pytest -q — refusé\nJe ne peux pas conclure."


@pytest.mark.parametrize("texte", [EMPECHE_PAR_LE_VERDICT, EMPECHE_SANS_VERDICT])
def test_un_verificateur_empeche_bloque_la_tache_sans_etre_relance(texte):
    c, m, agent, controles = moteur_a_reprises([tache("A")], textes={"A": [texte]})
    m.executer()
    a = c.tache("A")
    assert controles.journal == ["ouvrier", "perimetre", "controles", "verificateur"]
    assert agent.reprises == [] and a.tentatives == 1 and a.etat == "revenu"
    (demande,) = blocages(c)
    assert demande["empechements"] == ["uv run pytest -q — refusé"]
    assert "relance un" not in " ".join(textes_du_fil(c))


def test_trois_refus_identiques_de_suite_bloquent_meme_si_un_cran_reste():
    c = chantier([tache("A")], plafond_modele="fable", plafond_effort="high")
    m, agent = moteur(c, {"A": ["ne_sait_pas"]})
    m.executer()
    a = c.tache("A")
    assert traces(a) == [(1, "ne_sait_pas", False), (1, "ne_sait_pas", True),
                         (2, "ne_sait_pas", False)]  # fmt: skip
    assert departs(agent) == [("sonnet", "low"), ("opus", "low")]  # le cran vers Fable restait
    assert [r["tentative"] for r in agent.reprises] == [1]  # le troisième refus n'est pas repris
    assert a.montees == 1 and a.etat == "revenu"
    (demande,) = blocages(c)
    assert "refusée trois fois de suite pour la même raison" in demande["question"]
    assert demande["question"].count("« Le calcul est faux sur un cas de référence »") == 3
    assert len(demande["preuves"]) == 3 and demande["empechements"] == []


# Les trois vrais refus de la tâche B du chantier mesuré (2026-11-11) : A et B, B et C ne se
# ressemblent que par leurs mots ; A et C ont la même forme.
SONARQ = [
    "uv.lock est absent du dépôt et les versions de ruff, pytest et pre-commit ne sont figées "
    "nulle part, donc le critère 1 n'est pas tenu",
    "uv.lock est absent et les dépendances de développement ne sont pas figées, et rien ne "
    "montre que uv sync, ruff check et pytest passent",
    "uv.lock est absent, donc les versions de ruff, pytest et pre-commit ne sont figées "
    "nulle part et le critère 1 n'est pas tenu",
]


def verdict_refuse(resume, motif="ne_sait_pas"):
    return json.dumps({"valide": False, "motif": motif, "resume": resume}, ensure_ascii=False)


def test_trois_refus_qui_ne_se_ressemblent_que_par_les_mots_ne_bloquent_pas_si_un_cran_reste():
    c, m, agent, _ = moteur_a_reprises(
        [tache("A")], textes={"A": [verdict_refuse(r) for r in SONARQ]},
        plafond_modele="fable", plafond_effort="high",
    )  # fmt: skip
    m.executer()
    a = c.tache("A")
    assert blocages(c) == [] and a.etat == "verifie"
    assert traces(a) == [(1, "ne_sait_pas", False), (1, "ne_sait_pas", True),
                         (2, "ne_sait_pas", False), (2, "valide", True)]  # fmt: skip
    assert departs(agent) == [("sonnet", "low"), ("opus", "low")]


@pytest.mark.parametrize(
    "contrat", [{"plafond_modele": "sonnet", "plafond_effort": "low"}, {"max_montees": 0}]
)
def test_deux_refus_identiques_sans_cran_disponible_bloquent(contrat):
    c = chantier([tache("A")], **contrat)
    m, agent = moteur(c, {"A": ["bacle"]})
    m.executer()
    a = c.tache("A")
    assert traces(a) == [(1, "bacle", False), (1, "bacle", True)]  # le départ et sa reprise
    assert [x["role"] for x in agent.appels].count("ouvrier") == 2
    assert a.tentatives == 1 and c.montees == 0 and a.etat == "revenu"
    (demande,) = blocages(c)
    question = demande["question"]
    assert "refusée deux fois de suite pour la même raison" in question
    assert "le contrat ne permet plus de monter d'un cran" in question
    assert question.count("« Un critère de la consigne a été négligé »") == 2
    assert question.endswith("relance-la au même niveau.")


def test_un_refus_identique_laisse_partir_la_relance_seule_qui_monte_d_un_cran():
    c = chantier([tache("A")], plafond_modele="fable", plafond_effort="high", max_tentatives=1)
    m, agent = moteur(c, {"A": ["ne_sait_pas"]})
    m.executer()
    a = c.tache("A")
    assert a.relances_auto == 1  # tentatives épuisées : le cran restant était la relance seule
    assert departs(agent) == [("sonnet", "low"), ("opus", "low")]
    assert [r["tentative"] for r in agent.reprises] == [1, 2]
    (demande,) = blocages(c)
    assert "deux fois de suite" in demande["question"] and len(demande["preuves"]) == 4


SORTIE_UN = "....F\nFAILED tests/test_a.py::test_un - assert 1 == 2\n1 failed, 4 passed in 0.12s"
SORTIE_DEUX = "....F\nFAILED tests/test_a.py::test_deux - assert 3 == 4\n1 failed, 4 passed in 0.3s"
SORTIE_UN_AUTREMENT = (  # le même test échoue, avec une tout autre sortie
    "tests/test_a.py:41: in test_un\n    resultat = calculer(donnees_de_reference())\n"
    "coeur/calcul.py:12: in calculer\n    return table[cle]\nE   KeyError: 'pression'\n"
    "FAILED tests/test_a.py::test_un - KeyError: 'pression'\n1 failed, 4 passed in 0.40s"
)


@pytest.mark.parametrize(("seconde", "bloquee"), [(SORTIE_DEUX, False),
                                                  (SORTIE_UN_AUTREMENT, True)])  # fmt: skip
def test_deux_refus_des_controles_se_comparent_par_les_tests_en_echec(seconde, bloquee):
    c, m, _, _ = moteur_a_reprises([tache("A")], sorties=[(False, SORTIE_UN), (False, seconde)],
                                   plafond_modele="sonnet", plafond_effort="low")  # fmt: skip
    m.executer()
    a = c.tache("A")
    assert traces(a)[:2] == [(1, "ne_sait_pas", False), (1, "ne_sait_pas", True)]
    assert [e["origine"] for e in a.historique[:2]] == ["controles"] * 2
    if bloquee:
        assert a.etat == "revenu" and a.tentatives == 1 and len(blocages(c)) == 1
    else:  # au plafond, la reprise refusée d'un premier départ repart au même niveau
        assert a.etat == "verifie" and a.tentatives == 2 and blocages(c) == []
        assert any("je repars de zéro au même niveau" in t for t in textes_du_fil(c))


def test_le_rappel_recoit_la_demande_hors_du_verrou_une_fois_qu_elle_est_sauvee():
    sauvees, recues = [], []
    c, m, _, _ = moteur_empeche([tache("A")], {"A": ["ne_sait_pas"]})
    m.sur_changement = lambda: sauvees.append(len(c.demandes))
    m.verrou = VerrouSuivi()
    m.sur_blocage = lambda demande: recues.append((demande, m.verrou.tenu_ici(), list(sauvees)))
    m.executer()
    ((demande, sous_verrou, avant),) = recues
    assert demande is c.demandes[-1] and demande["nature"] == "blocage"
    assert not sous_verrou
    assert avant and avant[-1] == 1  # sauvée avec sa demande avant que le rappel ne parte


def test_un_rappel_qui_leve_est_note_au_fil_et_le_moteur_continue():
    c, m, _, _ = moteur_empeche([tache("A"), tache("B"), tache("C", depend_de=["A"])],
                                {"A": ["ne_sait_pas", "ok"]})  # fmt: skip

    def rappel(demande):
        raise RuntimeError("diagnostic   impossible")

    m.sur_blocage = rappel
    m.executer()
    assert [t.etat for t in c.taches] == ["revenu", "verifie", "a_lancer"]
    note = ("La suite donnée au blocage a échoué (RuntimeError : diagnostic impossible). La "
            "demande reste ouverte : tu peux y répondre comme d'habitude.")  # fmt: skip
    assert note in textes_du_fil(c)
    assert all(e["issue"] != "panne" for e in c.tache("A").historique)
    (demande,) = c.demandes
    assert demande["reponse"] is None
    m.repondre(demande["id"], RELANCER_TEL)
    m.executer()
    assert [t.etat for t in c.taches] == ["verifie"] * 3 and c.termine


def test_une_tache_independante_va_au_bout_pendant_le_blocage():
    bloquee = threading.Event()

    class Agent(AgentSimule):
        def executer(self, consigne, modele, effort, dossier, lecture_seule=False, contexte=None,
                     copie_jetable=False, reprendre=None):  # fmt: skip
            if (contexte["tache"], contexte["role"]) == ("B", "ouvrier"):
                bloquee.wait(5)  # B travaille encore quand A est bloquée
            return super().executer(consigne, modele, effort, dossier, lecture_seule, contexte,
                                    copie_jetable, reprendre)  # fmt: skip

    c, m, _, _ = moteur_empeche([tache("A"), tache("B"), tache("C", depend_de=["A"])],
                                {"A": ["ne_sait_pas"]}, agent_cls=Agent)  # fmt: skip
    m.sur_blocage = lambda demande: bloquee.set()
    m.executer()
    assert bloquee.is_set()
    assert [t.etat for t in c.taches] == ["revenu", "verifie", "a_lancer"]
    fil = [(e["tache"], e["texte"]) for e in c.evenements]
    rendue = next(i for i, (t, x) in enumerate(fil) if t == "A" and x.startswith("J'ai besoin"))
    assert fil.index(("B", "Vérifiée et enregistrée.")) > rendue


@pytest.mark.parametrize("choix", [RELANCER_TEL, RELANCER, ABANDONNER])
def test_repondre_a_un_blocage_fait_ce_que_fait_l_option_d_aujourd_hui(choix):
    from dataclasses import asdict

    c = chantier([tache("A")], plafond_modele="sonnet", plafond_effort="low")
    m, _ = moteur(c, {"A": ["bacle"]})
    m.executer()
    (demande,) = blocages(c)
    ordinaire = Chantier.depuis_dict(c.en_dict())  # le même état, avec une demande d'avant V3b
    for cle in ("nature", "preuves", "empechements"):
        del ordinaire.demandes[-1][cle]
    autre, _ = moteur(ordinaire)
    m.repondre(demande["id"], choix)
    autre.repondre(demande["id"], choix)
    assert asdict(c.tache("A")) == asdict(ordinaire.tache("A"))
    assert demande["reponse"] == choix and textes_du_fil(c)[-1] == textes_du_fil(ordinaire)[-1]


def test_relancer_au_meme_niveau_apres_un_blocage_repart_avec_sa_reprise_a_chaud():
    issues = {("A", "verificateur"): ["bacle", "bacle", "bacle", "ok"]}
    c, m, agent, controles = moteur_a_reprises([tache("A")], issues, plafond_modele="sonnet",
                                               plafond_effort="low")  # fmt: skip
    m.executer()
    a = c.tache("A")
    assert a.etat == "revenu" and traces(a) == [(1, "bacle", False), (1, "bacle", True)]
    m.repondre(blocages(c)[0]["id"], RELANCER_TEL)
    m.executer()
    assert a.etat == "verifie" and a.tentatives == 2 and c.termine
    # Le premier refus après la relance est le même qu'avant : il ne prive pas de la reprise.
    assert traces(a)[2:] == [(2, "bacle", False), (2, "valide", True)]
    assert [r["tentative"] for r in agent.reprises] == [1, 2]
    assert controles.preparees == ["A", "A"] and departs(agent) == [("sonnet", "low")] * 2


def test_deux_erreurs_d_agent_identiques_bloquent_sans_monter():
    c = chantier([tache("A")])
    m, agent = moteur(c, {"A": ["erreur", "erreur", "ok"]})
    m.executer()
    a = c.tache("A")
    assert a.etat == "revenu" and a.tentatives == 2 and c.montees == 0
    assert departs(agent) == [("sonnet", "low")] * 2 and agent.reprises == []
    assert [e["origine"] for e in a.historique] == ["agent", "agent"]
    assert any("Seconde chance au même niveau" in t for t in textes_du_fil(c))
    (demande,) = blocages(c)
    assert "les agents se sont arrêtés deux fois de suite sur la même erreur" in demande["question"]


@pytest.mark.parametrize(("limites", "nature"), [(["surcharge", "refus"], None),
                                                 (["refus", "refus"], "blocage")])  # fmt: skip
def test_une_limite_ou_une_surcharge_sont_des_erreurs_d_agent_sans_montee(limites, nature):
    from atelier.agents import LIMITE_ATTEINTE, SURCHARGE

    c = chantier([tache("A")])
    agent = AgentSimule(perimetres={"A": ["a.py"]}, limites={"A": limites})
    Moteur(c, agent, ControlesSimules()).executer()
    a = c.tache("A")
    assert a.etat == "revenu" and a.tentatives == 2 and c.montees == 0
    assert departs(agent) == [("sonnet", "low")] * 2
    assert [e["origine"] for e in a.historique] == ["agent"] * 2
    erreurs = {"surcharge": SURCHARGE, "refus": LIMITE_ATTEINTE}
    assert [erreurs[x] in e["detail"] for x, e in zip(limites, a.historique, strict=True)] == [
        True, True,
    ]  # fmt: skip
    (demande,) = c.demandes
    assert demande.get("nature") == nature
    if nature is None:
        assert "deux erreurs d'agent de suite" in demande["question"]


def test_une_erreur_d_agent_apres_un_refus_repart_au_meme_niveau():
    issues = {("A", "verificateur"): ["bacle", "bacle", "ok"],
              ("A", "ouvrier"): ["ok", "ok", "erreur", "ok"]}  # fmt: skip
    c, m, agent, _ = moteur_a_reprises([tache("A")], issues)
    m.executer()
    a = c.tache("A")
    assert a.etat == "verifie" and a.tentatives == 3
    assert departs(agent) == [("sonnet", "low"), ("sonnet", "medium"), ("sonnet", "medium")]
    assert c.montees == 1  # la seule montée suit le refus du vérificateur, pas l'erreur


def test_une_erreur_d_agent_au_bout_des_tentatives_ne_relance_pas_seule_plus_haut():
    c = chantier([tache("A")], max_tentatives=1)
    m, agent = moteur(c, {"A": ["erreur", "ok"]})
    m.executer()
    a = c.tache("A")
    assert a.etat == "revenu" and a.relances_auto == 0 and c.montees == 0
    assert departs(agent) == [("sonnet", "low")]
    assert "1 tentatives sans succès" in c.demandes[-1]["question"]


@pytest.mark.parametrize("en_erreur", [1, 2])
def test_un_verificateur_en_erreur_est_relance_une_fois_sur_la_meme_copie(en_erreur):
    c, m, agent, controles = moteur_a_reprises([tache("A")], agent_cls=AgentVerificateurEnErreur)
    agent.en_erreur = en_erreur
    m.executer()
    a = c.tache("A")
    assert controles.journal[:5] == ["ouvrier", "perimetre", "controles", "verificateur",
                                     "verificateur"]  # fmt: skip
    assert controles.preparees[0] == "A" and agent.reprises == []
    relance = ("Le vérificateur s'est arrêté sur une erreur (Panne du vérificateur) : j'en "
               "relance un, une seule fois, sur la même copie.")  # fmt: skip
    assert textes_du_fil(c).count(relance) == 1
    if en_erreur == 1:  # le second vérificateur accepte : le livrable entre, rien n'est jeté
        assert traces(a) == [(1, "valide", False)] and controles.annulees == []
        assert c.agents_lances == 3
    else:  # deux erreurs : une erreur d'agent, sans montée
        assert traces(a) == [(1, "ne_sait_pas", False), (2, "valide", False)]
        assert a.historique[0]["origine"] == "agent"
        assert a.historique[0]["detail"] == (
            "Le vérificateur s'est arrêté sur une erreur : Panne du vérificateur."
        )
        assert departs(agent) == [("sonnet", "low")] * 2 and controles.annulees == ["A"]


def test_un_verdict_illisible_est_relance_une_fois_sur_la_meme_copie():
    texte = "J'ai relu, mais je n'ai pas eu le temps de conclure."
    c, m, agent, controles = moteur_a_reprises([tache("A")], textes={"A": [texte]})
    m.executer()
    assert controles.journal == ["ouvrier", "perimetre", "controles", "verificateur",
                                 "verificateur"]  # fmt: skip
    assert traces(c.tache("A")) == [(1, "valide", False)] and controles.annulees == []
    assert ("Le vérificateur n'a pas rendu de verdict lisible : j'en relance un, une seule fois, "
            "sur la même copie.") in textes_du_fil(c)  # fmt: skip


def test_un_empechement_sur_un_livrable_accepte_n_empeche_pas_l_enregistrement():
    c = chantier([tache("A")])
    controles = ControlesReglables()
    agent = AgentSimule(perimetres={"A": ["a.py"]}, empeches={"A": [UV]})
    Moteur(c, agent, controles).executer()
    assert c.tache("A").etat == "verifie" and controles.enregistrees == ["A"] and c.termine
    assert c.demandes == []
    fil = textes_du_fil(c)
    note = fil[fil.index("Vérifiée et enregistrée.") + 1]
    assert note == (
        f"Un agent a signalé un empêchement pendant cette tâche : « {EMPECHEMENT_UV[:-1]} » ; "
        "« Bash(uv sync) ». Le livrable a quand même été accepté et enregistré. Si cette "
        "commande doit servir aux agents, tu peux la leur permettre dans les outils du projet."
    )


def test_un_arret_l_emporte_sur_un_empechement():
    class Controles(ControlesComptes):
        def mecaniques(self, t, dossier):
            assert m.arreter(t.id)  # aucun agent ne tourne : le drapeau retient le vérificateur
            return super().mecaniques(t, dossier)

    c = chantier([tache("A")])
    agent = AgentSimule(perimetres={"A": ["a.py"]}, empeches={"A": [UV]})
    m = Moteur(c, agent, Controles())
    m.sur_blocage = rappels = []  # ne doit jamais servir
    m.executer()
    a = c.tache("A")
    assert blocages(c) == [] and rappels == []
    assert traces(a) == [(1, "arretee", False)] and a.etat == "revenu"
    assert c.demandes[-1]["question"].endswith("arrêtée par toi.")


def test_une_demande_de_blocage_reste_ouverte_apres_un_redemarrage_sans_rappel(tmp_path):
    c, m, _, _ = moteur_empeche([tache("A")], {"A": ["ne_sait_pas"]})
    m.executer()
    c.sauver(tmp_path / "etat.json")
    relu = Chantier.charger(tmp_path / "etat.json")
    rappels, neuf = [], AgentSimule(perimetres={"A": ["a.py"]})
    redemarre = Moteur(relu, neuf, ControlesSimules())
    redemarre.sur_blocage = rappels.append
    redemarre.executer()
    assert rappels == [] and neuf.appels == []
    assert relu.demandes == c.demandes and relu.demandes[0]["reponse"] is None
    assert relu.demandes[0]["nature"] == "blocage" and relu.tache("A").etat == "revenu"


def test_les_preuves_sont_les_cinq_derniers_refus_et_chacune_est_bornee():
    from atelier.moteur import REPETE, Jugement

    t = tache("A")
    long = "DEBUT-COUPE " + "x" * 3000 + " FAILED fin"
    issues = ["ne_sait_pas", "valide", "panne", "arretee", "bacle", "deborde", "bacle",
              "ne_sait_pas", "ne_sait_pas"]  # fmt: skip
    t.historique = [
        {"tentative": i + 1, "issue": issue, "detail": f"refus {i + 1}", "origine": "verdict"}
        for i, issue in enumerate(issues)
    ]
    t.historique[-1]["detail"] = long
    c = chantier([t])
    m, _ = moteur(c)
    m._bloquer(t, Jugement("ne_sait_pas", long, "verdict", blocage=REPETE))
    (demande,) = c.demandes
    assert [p.split(" : ")[0] for p in demande["preuves"]] == [
        f"Tentative {i}, vérificateur" for i in (5, 6, 7, 8, 9)
    ]
    assert demande["preuves"][-1] == "Tentative 9, vérificateur : […] " + long[-2000:]
    assert "DEBUT-COUPE" not in demande["question"]
    assert "« […] " + "x" * 289 + " FAILED fin »" in demande["question"]  # 300 caractères
