import subprocess
import threading

import pytest

from atelier.agents import AgentSimule
from atelier.consignes import consigne_ouvrier, lire_verdict
from atelier.controles import ControlesGit, ControlesSimules, hors_perimetre, se_chevauchent
from atelier.modele import Chantier, Contrat, Tache
from atelier.moteur import ABANDONNER, RELANCER, RELANCER_TEL, ContratNonValide, Moteur


def chantier(taches, **contrat):
    reglages = {"objectif": "Essai", "valide": True, **contrat}
    return Chantier(projet="essai", contrat=Contrat(**reglages), taches=taches)


def tache(identifiant, **champs):
    reglages = {"titre": f"Tâche {identifiant}", "type": "mecanique", "criteres": ["Ça marche."]}
    reglages["perimetre"] = [f"{identifiant.lower()}.py"]
    return Tache(id=identifiant, **{**reglages, **champs})


def moteur(c, scenario=None):
    agent = AgentSimule(scenario or {}, perimetres={t.id: t.perimetre for t in c.taches})
    return Moteur(c, agent, ControlesSimules()), agent


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
    c = chantier([tache("A")])
    m, agent = moteur(c, {"A": ["ne_sait_pas", "ne_sait_pas", "ok"]})
    m.executer()
    a = c.tache("A")
    assert a.etat == "verifie"
    assert a.tentatives == 3
    assert (a.modele, a.effort) == ("opus", "low")
    assert c.montees == 1
    ouvriers = [(x["modele"], x["effort"]) for x in agent.appels if x["role"] == "ouvrier"]
    assert ouvriers == [("sonnet", "low"), ("sonnet", "low"), ("opus", "low")]


def test_un_travail_bacle_monte_l_effort_pas_le_modele():
    c = chantier([tache("A")])
    m, _ = moteur(c, {"A": ["bacle", "bacle", "ok"]})
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
    m, _ = moteur(c, {"A": ["ne_sait_pas", "ne_sait_pas", "ok"]})
    m.executer()
    avant = (c.tache("A").modele, c.tache("A").effort)
    m.repondre(c.demandes[0]["id"], RELANCER_TEL)
    assert (c.tache("A").modele, c.tache("A").effort) == avant
    m.executer()
    assert c.tache("A").etat == "verifie"


def test_relancer_apres_decision_monte_d_un_cran_et_termine():
    c = chantier([tache("A")], plafond_modele="haiku", plafond_effort="low")
    m, agent = moteur(c, {"A": ["ne_sait_pas", "ne_sait_pas", "ok"]})
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
    m, agent = moteur(c, {"A": ["deborde", "ok"]})
    m.executer()
    assert c.tache("A").historique[0]["issue"] == "deborde"
    assert "hors_perimetre.txt" in c.tache("A").historique[0]["detail"]
    assert [a["role"] for a in agent.appels] == ["ouvrier", "ouvrier", "verificateur"]


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
                           copie_jetable=False):  # fmt: skip
        if lecture_seule:
            verifications.append((dossier, copie_jetable, "copie jetable" in consigne))
            (dossier / "mutation.py").write_text("raise SystemExit(1)\n", "utf-8")
        return executer(consigne, modele, effort, dossier, lecture_seule, contexte)

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
    m, agent = moteur(c, {"A": ["ne_sait_pas", "ne_sait_pas", "ne_sait_pas", "ok"]})
    m.executer()
    a = c.tache("A")
    assert a.etat == "verifie" and c.demandes == [] and c.termine
    assert a.relances_auto == 1 and a.tentatives == 4
    ouvriers = [(x["modele"], x["effort"]) for x in agent.appels if x["role"] == "ouvrier"]
    assert ouvriers == [("sonnet", "low"), ("sonnet", "low"), ("opus", "low"), ("fable", "low")]
    assert any("Je relance seul un cran plus haut : Fable" in e["texte"] for e in c.evenements)


def test_la_relance_seule_n_a_lieu_qu_une_fois_puis_la_tache_revient():
    c = chantier([tache("A")], plafond_modele="fable", plafond_effort="high")
    m, _ = moteur(c, {"A": ["ne_sait_pas"]})
    m.executer()
    a = c.tache("A")
    assert a.etat == "revenu" and len(c.demandes) == 1 and a.relances_auto == 1
    assert not c.termine


def test_au_plafond_aucune_relance_seule():
    c = chantier([tache("A")], plafond_modele="haiku", plafond_effort="low")
    m, _ = moteur(c, {"A": ["ne_sait_pas"]})
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
    assert [e["issue"] for e in historique] == ["ne_sait_pas", "valide"]
    assert historique.sous_verrou == [True, True]


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
    m, _ = moteur(c, {"P": ["ne_sait_pas"]})
    m.executer()
    p = c.tache("P")
    assert p.etat == "revenu" and p.tentatives == 2
    assert [e["issue"] for e in p.historique] == ["ne_sait_pas", "ne_sait_pas"]
    assert "le plafond d'escalade du contrat est atteint" in c.demandes[-1]["question"]


def test_la_relance_seule_ne_depasse_jamais_le_plafond_du_contrat():
    c = chantier([tache("A")], plafond_modele="opus", plafond_effort="low")
    m, agent = moteur(c, {"A": ["ne_sait_pas"]})
    m.executer()
    a = c.tache("A")
    assert a.etat == "revenu" and a.relances_auto == 0 and a.tentatives == 3
    ouvriers = [(x["modele"], x["effort"]) for x in agent.appels if x["role"] == "ouvrier"]
    assert ouvriers == [("sonnet", "low"), ("sonnet", "low"), ("opus", "low")]
    assert "3 tentatives sans succès" in c.demandes[-1]["question"]
