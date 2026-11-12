"""La carte du code : fichiers, dépendances, comparaison de versions, explications par lots."""

import json
import subprocess
import time

from atelier import carte
from atelier.agents import Resultat


def git(dossier, *arguments):
    identite = ["-c", "user.name=Essai", "-c", "user.email=essai@exemple.invalid"]
    subprocess.run(["git", *identite, *arguments], cwd=dossier, check=True, capture_output=True)


def depot(tmp_path, fichiers):
    git(tmp_path, "init", "-q", "-b", "main")
    ecrire(tmp_path, fichiers)
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-q", "-m", "départ")
    return tmp_path


def ecrire(dossier, fichiers):
    for chemin, texte in fichiers.items():
        (dossier / chemin).parent.mkdir(parents=True, exist_ok=True)
        (dossier / chemin).write_text(texte, "utf-8")


PROJET = {
    "app/__init__.py": "",
    "app/calcul.py": '"""Le calcul de la norme."""\n\nfrom app import outils\n\n\n'
    'def total(x):\n    """Additionne tout."""\n    return outils.somme(x)\n\n\n'
    "class Moteur:\n    pass\n",
    "app/outils.py": '"""Petits outils."""\n\n\ndef somme(x):\n    return sum(x)\n',
    "tests/test_calcul.py": "from app.calcul import total\n\n\ndef test_total():\n"
    "    assert total([1]) == 1\n",
    "web/index.html": '<title>Tableau</title>\n<script src="./app.js"></script>\n',
    "web/app.js": "// La page du tableau.\nimport { aide } from './aide';\n\n"
    "// Dessine la page.\nexport function dessiner() {}\nconst petit = (x) => x;\n",
    "web/aide.js": "export const aide = 1;\n",
    "LISEZMOI.md": "# Projet\n\nUn projet d'essai pour la carte.\n",
    "pyproject.toml": "[project]\nname = 'essai'\n",
    "image.png": "pas vraiment une image",
    "node_modules/x/index.js": "ignoré",
}


def test_le_genre_d_un_fichier():
    assert carte.genre("app/calcul.py") == "code"
    assert carte.genre("tests/test_calcul.py") == "tests"
    assert carte.genre("src/a.test.ts") == "tests"
    assert carte.genre("web/index.html") == "page"
    assert carte.genre("pyproject.toml") == "réglages"
    assert carte.genre("Dockerfile") == "réglages"
    assert carte.genre("LISEZMOI.md") == "documentation"
    assert carte.genre("donnees.bin") == "autre"


def test_les_fichiers_suivis_par_git_sans_les_binaires_ni_les_dossiers_ignores(tmp_path):
    fichiers = carte.lister_fichiers(depot(tmp_path, PROJET))
    assert "image.png" not in fichiers and not any(c.startswith("node_modules") for c in fichiers)
    assert "app/calcul.py" in fichiers and len(fichiers["app/calcul.py"]) == 40


def test_sans_git_le_dossier_est_parcouru(tmp_path):
    ecrire(tmp_path, PROJET)
    fichiers = carte.lister_fichiers(tmp_path)
    assert "app/calcul.py" in fichiers and "image.png" not in fichiers
    assert not any(c.startswith("node_modules") for c in fichiers)
    assert carte.commit_courant(tmp_path) == ""


def test_ce_que_le_fichier_dit_de_lui_meme():
    doc, pieces = carte.decrire("app/calcul.py", PROJET["app/calcul.py"])
    assert doc == "Le calcul de la norme."
    assert [(p["nom"], p["sorte"], p["doc"]) for p in pieces] == [
        ("total", "fonction", "Additionne tout."),
        ("Moteur", "classe", ""),
    ]
    doc, pieces = carte.decrire("web/app.js", PROJET["web/app.js"])
    assert doc == "La page du tableau."
    assert [(p["nom"], p["doc"]) for p in pieces] == [
        ("dessiner", "Dessine la page."),
        ("petit", ""),
    ]
    assert carte.decrire("LISEZMOI.md", PROJET["LISEZMOI.md"])[0] == (
        "Projet. Un projet d'essai pour la carte."
    )
    assert carte.decrire("a.py", "def (") == ("", [])
    assert carte.decrire("a.py", None) == ("", [])


def test_qui_se_sert_de_qui(tmp_path):
    k = carte.relever(depot(tmp_path, PROJET))
    assert k["liens"] == [
        ["app/calcul.py", "app/__init__.py"],
        ["app/calcul.py", "app/outils.py"],
        ["tests/test_calcul.py", "app/calcul.py"],
        ["web/app.js", "web/aide.js"],
        ["web/index.html", "web/app.js"],
    ]


def test_les_imports_relatifs_python(tmp_path):
    projet = {
        "pkg/__init__.py": "",
        "pkg/a.py": "from . import b\nfrom .sous.c import f\n",
        "pkg/b.py": "",
        "pkg/sous/__init__.py": "",
        "pkg/sous/c.py": "from .. import b\ndef f():\n    pass\n",
    }
    k = carte.relever(depot(tmp_path, projet))
    assert ["pkg/a.py", "pkg/b.py"] in k["liens"] and ["pkg/a.py", "pkg/sous/c.py"] in k["liens"]
    assert ["pkg/sous/c.py", "pkg/b.py"] in k["liens"]


def test_une_nouvelle_version_ne_releve_que_ce_qui_a_change(tmp_path):
    d = depot(tmp_path, PROJET)
    premiere = carte.relever(d)
    assert premiere["changements"]["nouveaux"] == []  # une première analyse ne marque rien
    premiere["fichiers"]["app/outils.py"]["explication"] = {
        "sha": premiere["fichiers"]["app/outils.py"]["sha"],
        "resume": "Gardée.",
        "detail": "",
        "pieces": {},
    }
    premiere["fichiers"]["app/calcul.py"]["explication"] = {
        "sha": premiere["fichiers"]["app/calcul.py"]["sha"],
        "resume": "Périmée.",
        "detail": "",
        "pieces": {},
    }
    ecrire(d, {"app/calcul.py": PROJET["app/calcul.py"] + "\n# changé\n", "app/neuf.py": "x = 1\n"})
    (d / "web/aide.js").unlink()
    git(d, "add", "-A")
    git(d, "commit", "-q", "-m", "suite")
    seconde = carte.relever(d, premiere)
    assert seconde["changements"]["nouveaux"] == ["app/neuf.py"]
    assert seconde["changements"]["modifies"] == ["app/calcul.py"]
    assert seconde["changements"]["supprimes"] == ["web/aide.js"]
    assert seconde["version"] == premiere["version"] + 1 and seconde["commit"] != premiere["commit"]
    assert carte.a_jour(seconde["fichiers"]["app/outils.py"])
    assert not carte.a_jour(seconde["fichiers"]["app/calcul.py"])
    assert "app/calcul.py" in carte.a_expliquer(seconde)
    assert "app/outils.py" not in carte.a_expliquer(seconde)
    assert carte.bilan_changements(seconde["changements"]) == (
        "3 fichiers : 1 nouveau, 1 modifié, 1 supprimé"
    )
    assert carte.bilan_changements({}) == ""


def test_les_lots_restent_petits(tmp_path):
    projet = {f"m{i}.py": f"x = {i}\n" for i in range(20)}
    projet["gros.py"] = "x = 1\n" * 5000
    d = depot(tmp_path, projet)
    paquets = carte.lots(d, sorted(projet))
    assert all(len(p) <= carte.FICHIERS_PAR_LOT for p in paquets)
    assert sum(len(p) for p in paquets) == 21
    (gros,) = [texte for p in paquets for chemin, texte in p if chemin == "gros.py"]
    assert len(gros) < carte.EXTRAIT_MAX + 100 and "caractères de plus, non montrés" in gros


def test_les_explications_recues_sont_rangees_et_les_fausses_ecartees(tmp_path):
    k = carte.relever(depot(tmp_path, PROJET))
    lot = [("app/calcul.py", ""), ("app/outils.py", ""), ("web/app.js", "")]
    texte = carte.consigne(lot, k)
    assert "=== Fichier : app/calcul.py\nParties : total, Moteur" in texte
    reponse = {
        "fichiers": [
            {
                "chemin": "app/calcul.py",
                "resume": "Calcule la norme.",
                "detail": "Il additionne.",
                "pieces": [{"nom": "total", "role": "Fait la somme."}, "pas un objet"],
            },
            {"chemin": "app/outils.py", "resume": "  "},
            {"chemin": "inconnu.py", "resume": "Rien."},
            "pas un objet",
        ]
    }
    assert carte.appliquer(k, lot, reponse) == 1
    assert k["fichiers"]["app/calcul.py"]["explication"]["pieces"] == {"total": "Fait la somme."}
    assert k["fichiers"]["app/outils.py"]["explication"] is None
    assert carte.appliquer(k, lot, None) == 0


def test_la_vue_montre_l_explication_a_jour_sinon_le_commentaire(tmp_path):
    k = carte.relever(depot(tmp_path, PROJET))
    lot = [("app/calcul.py", "")]
    carte.appliquer(k, lot, {"fichiers": [{"chemin": "app/calcul.py", "resume": "Calcule."}]})
    v = carte.vue(k, {"app/outils.py": ["A-ouvrier-1"], "app/futur.py": ["A-ouvrier-1"]})
    fiches = {f["chemin"]: f for f in v["fichiers"]}
    assert fiches["app/calcul.py"]["resume"] == "Calcule." and fiches["app/calcul.py"]["explique"]
    assert (
        fiches["app/outils.py"]["resume"] == "Petits outils." and fiches["app/outils.py"]["attente"]
    )
    assert fiches["app/outils.py"]["en_cours"] == ["A-ouvrier-1"]
    assert fiches["app/__init__.py"]["resume"] == "Un fichier de code Python, de 0 lignes."
    assert fiches["pyproject.toml"]["resume"].startswith("Un fichier de réglages")
    assert v["nouveaux_absents"] == ["app/futur.py"]
    assert fiches["app/calcul.py"]["pieces"][0] == {
        "nom": "total",
        "ligne": 6,
        "sorte": "fonction",
        "role": "Additionne tout.",
    }


class FauxExplicateur:
    reel = True

    def __init__(self):
        self.consignes = []

    def expliquer(self, texte):
        self.consignes.append(texte)
        chemins = [
            ligne.split(": ", 1)[1]
            for ligne in texte.splitlines()
            if ligne.startswith("=== Fichier")
        ]
        return {"fichiers": [{"chemin": c, "resume": f"Sert à {c}."} for c in chemins]}, 0.01


def attendre(condition, delai=10.0):
    limite = time.monotonic() + delai
    while time.monotonic() < limite:
        if condition():
            return True
        time.sleep(0.02)
    return False


def test_le_suivi_analyse_explique_puis_ne_reexplique_que_le_fichier_change(tmp_path):
    d = depot(tmp_path, PROJET)
    faux = FauxExplicateur()
    suivi = carte.SuiviCarte(d, faux)
    assert suivi.resume()["etat"] == "absente"
    estimation = suivi.estimer()
    assert (
        estimation["fichiers"] == 9 and estimation["a_expliquer"] == 7 and estimation["appels"] == 1
    )
    assert suivi.analyser() is True
    assert attendre(lambda: not suivi.occupe())
    resume = suivi.resume()
    assert resume["etat"] == "prete" and resume["expliques"] == 7 and resume["a_expliquer"] == 0
    assert resume["cout"] == "0,01 $" and resume["changements"] == ""
    assert json.loads((d / ".atelier" / "carte.json").read_text("utf-8"))["commit"]
    # Rien n'a changé : la veille ne fait rien.
    assert suivi.verifier() is False
    # Une nouvelle version : seul le fichier changé repart chez Claude.
    ecrire(d, {"app/outils.py": PROJET["app/outils.py"] + "\n\ndef produit(x):\n    return x\n"})
    git(d, "commit", "-q", "-am", "produit")
    assert suivi.verifier() is True
    assert attendre(lambda: not suivi.occupe())
    assert "=== Fichier : app/outils.py" in faux.consignes[-1]
    assert faux.consignes[-1].count("=== Fichier") == 1
    resume = suivi.resume({"app/outils.py": ["B-ouvrier-1"]})
    assert resume["changements"] == "1 fichier : 1 modifié" and resume["expliques"] == 7
    assert resume["en_cours"] == [{"chemin": "app/outils.py", "agents": ["B-ouvrier-1"]}]
    # Une carte relue sur le disque reprend là où elle en était.
    assert carte.SuiviCarte(d, FauxExplicateur()).resume()["version"] == resume["version"]
    suivi.finir()


def test_sans_claude_rien_n_est_demande_et_la_carte_se_lit_quand_meme(tmp_path):
    d = depot(tmp_path, PROJET)
    suivi = carte.SuiviCarte(d)
    assert suivi.estimer()["appels"] == 0
    suivi.analyser()
    assert attendre(lambda: not suivi.occupe())
    fiches = {f["chemin"]: f for f in suivi.vue()["fichiers"]}
    assert fiches["app/calcul.py"]["resume"] == "Le calcul de la norme."
    assert not fiches["app/calcul.py"]["explique"]
    suivi.finir()


def test_un_echec_de_claude_est_dit_sans_rien_casser(tmp_path):
    class EnPanne:
        reel = True

        def expliquer(self, texte):
            return None, 0.0

    d = depot(tmp_path, PROJET)
    suivi = carte.SuiviCarte(d, EnPanne())
    suivi.analyser()
    assert attendre(lambda: not suivi.occupe())
    resume = suivi.resume()
    assert resume["etat"] == "prete" and resume["a_expliquer"] == 7
    assert resume["probleme"].startswith("Claude n'a pas pu écrire une partie des explications")
    suivi.finir()


def test_l_explicateur_claude_passe_par_le_pont_sans_aucun_outil(tmp_path, monkeypatch):
    vus = {}

    class FausseSession:
        def __init__(self, agent, modele, effort, **reglages):
            vus.update(agent=agent, modele=modele, effort=effort, **reglages)

        def envoyer(self, texte):
            vus["texte"] = texte
            return Resultat(ok=True, texte='Voici : {"fichiers": []}', cout_usd=0.02)

        def fermer(self):
            vus["ferme"] = True

    import atelier.sdk

    monkeypatch.setattr(atelier.sdk, "SessionSDK", FausseSession)
    reponse, cout = carte.ExplicateurClaude(tmp_path).expliquer("consigne")
    assert reponse == {"fichiers": []} and cout == 0.02 and vus["ferme"] is True
    assert vus["modele"] == "sonnet" and vus["effort"] == "low"
    assert vus["outils_permis"] == [] and vus["mode_permission"] == "dontAsk"
    assert "Bash" in vus["outils_interdits"] and "Write" in vus["outils_interdits"]


def test_provisoire_lit_la_copie_de_travail_sans_rien_ecrire(tmp_path):
    from atelier.carte import provisoire

    (tmp_path / "web").mkdir()
    (tmp_path / "web" / "index.html").write_text('<script src="neuf.js"></script>', "utf-8")
    (tmp_path / "web" / "neuf.js").write_text("// Dessine le plan.\nexport const a = 1;\n", "utf-8")
    carte = {"fichiers": {"web/index.html": {"genre": "page"}}, "liens": []}
    brouillon = {"agents": ["B-ouvrier-1"], "dossier": tmp_path,
                 "fichiers": ["web/index.html", "web/neuf.js", "parti.py"]}  # fmt: skip
    prov = provisoire(carte, [brouillon])
    assert [f["chemin"] for f in prov["fichiers"]] == ["web/neuf.js"]
    assert prov["fichiers"][0]["agents"] == ["B-ouvrier-1"]
    assert prov["liens"] == [["web/index.html", "web/neuf.js"]]
    assert provisoire(None, [brouillon]) == {"fichiers": [], "liens": []}
    assert provisoire(carte, []) == {"fichiers": [], "liens": []}
    assert sorted(p.name for p in tmp_path.iterdir()) == ["web"]
