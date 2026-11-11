import json
import random
import re
import threading
import time

import pytest

from atelier.guichet import (
    Guichet,
    GuichetSimule,
    Reponse,
    detail_pour,
    phrase_pour,
    regle_pour,
)

GARDE_S = 5  # aucun fil de test ne doit attendre plus longtemps
SANS_REPONSE = "Pas de réponse de la personne responsable."
ARRETE = "Arrêté par la personne responsable."
CAS_PAR_CAS = " Cette commande ne peut être autorisée qu'au cas par cas."
NPM = {"command": "npm install left-pad"}


def lancer(guichet, agent, outil="Bash", entree=NPM):
    """Lance une demande dans son propre fil ; le résultat arrive dans le dictionnaire."""
    resultat = {}

    def corps():
        resultat["reponse"] = guichet.demander(agent, outil, entree)

    fil = threading.Thread(target=corps, daemon=True)
    fil.start()
    return fil, resultat


def attendre_ouvertes(guichet, nombre):
    limite = time.monotonic() + GARDE_S
    while len(guichet.ouvertes()) < nombre:
        assert time.monotonic() < limite, "les demandes ne sont jamais arrivées au guichet"
        time.sleep(0.002)
    return guichet.ouvertes()


def finir(fil):
    fil.join(GARDE_S)
    assert not fil.is_alive(), "un fil d'agent est resté bloqué"


def bash(commande):
    return regle_pour("Bash", {"command": commande})


# Règles « toujours » : Bash


@pytest.mark.parametrize("commande, regle", [
    ("npm install left-pad", "Bash(npm install:*)"),
    ("ls", "Bash(ls:*)"),
    ("  git   status  ", "Bash(git status:*)"),
    ("ls -la", "Bash(ls -la:*)"),
    ("python3 -m pytest -q", "Bash(python3 -m:*)"),
    ("npm run build", "Bash(npm run:*)"),
    ("python3 outils/script.py --vite", "Bash(python3 outils/script.py:*)"),
    ("./gradlew build", "Bash(./gradlew build:*)"),
    ('git commit -m "Un message"', "Bash(git commit:*)"),
])
def test_regle_bash_la_commande_et_ses_deux_premiers_mots(commande, regle):
    assert bash(commande) == regle


@pytest.mark.parametrize("operateur", [
    ";", "&", "&&", "|", "||", "<", ">", "`", "$", "$(", "(", ")", "\\", "\n", "\r", "\t", "\x00",
])
def test_regle_bash_aucune_regle_si_un_operateur_suit_les_deux_premiers_mots(operateur):
    assert bash("npm install x") == "Bash(npm install:*)"
    assert bash(f"npm install x{operateur} rm -rf /") == ""


@pytest.mark.parametrize("commande", [
    "ls; rm x", "cat f | sh", "echo `rm x`", "ls > fichier",
])
def test_regle_bash_aucune_regle_si_un_operateur_touche_les_deux_premiers_mots(commande):
    assert bash(commande) == ""


@pytest.mark.parametrize("commande", [
    "/bin/bash -lc 'rm -rf /'",
    "/usr/bin/env bash -c x",
    "/usr/bin/sudo rm x",
    "time bash -c x",
    "nice -n 10 rm x",
    "ionice -c 3 rm x",
    "setsid rm x",
    "stdbuf -o0 rm x",
    "strace rm x",
    "busybox sh",
    "ksh -c x",
    "csh -c x",
    "ash -c x",
    "ssh hote",
    "chroot / rm x",
    "find . -delete",
    "docker exec conteneur",
    "npm exec cowsay",
    "git -c alias.x=y x",
    "make -e",
    "sed -ne p",
    "python3 -Bc x",
    "python3 -u -c x",
    "python3.12 -c x",
    "node -p x",
    "node -e x",
    "node --eval x",
    "php -r x",
    "perl -ne x",
    "ruby -e x",
    "npx python3",
    "bash -c 'rm -rf /'",
    "sudo rm x",
    "env npm test",
    "xargs rm",
    "FOO=1 npm test",
    "'npm' install",
    "ls *",
    "",
    "   ",
])
def test_regle_bash_aucune_regle_pour_un_lanceur_ou_un_mot_douteux(commande):
    assert bash(commande) == ""


@pytest.mark.parametrize("commande", [
    "python3", "node", "perl", "ruby", "php", "awk", "deno", "bun", "/usr/bin/python3.12",
    "Python3", "NODE",
])
def test_regle_bash_aucune_regle_pour_un_interpreteur_seul(commande):
    assert bash(commande) == ""


@pytest.mark.parametrize("commande", [
    "uv run x", "poetry run x", "pipenv run x", "conda run x", "nix run x", "uvx x",
    "pipx run x", "hatch run x", "pdm run x", "docker run x", "docker ps", "podman run x",
    "npx x", "bunx x", "npm x y", "npm exec y", "pnpm dlx y", "pnpm exec y", "yarn dlx y",
    "bun x y", "ts-node a.ts", "tsx a.ts", "caffeinate x", "xvfb-run x", "timeout 5 x",
    "gtimeout 5 x", "rlwrap x", "unbuffer x", "valgrind x", "firejail x", "gosu moi x",
    "emacs --batch", "watch x", "parallel x", "flock f x", "doas x", "su moi", "runuser x",
    "git -C dossier status", "git -c alias.x=y x", "git -c a",
])
def test_regle_bash_aucune_regle_pour_un_lanceur_de_la_derniere_liste(commande):
    assert bash(commande) == ""


@pytest.mark.parametrize("commande", [
    "ENV -i x", "Env x", "SUDO rm x", "/USR/BIN/ENV x", "Bash x", "Uv Run x", "GIT -C d x",
    "PYTHON3 -c x",
])
def test_regle_bash_les_noms_sont_compares_sans_tenir_compte_de_la_casse(commande):
    assert bash(commande) == ""


@pytest.mark.parametrize("lanceur", [
    "time", "nice", "ionice", "setsid", "stdbuf", "strace", "busybox", "ksh", "csh", "ash",
    "ssh", "chroot", "sudo", "doas", "env", "xargs", "timeout", "watch", "nohup", "bash", "sh",
    "zsh", "/usr/bin/time", "/bin/sh",
])
def test_regle_bash_aucune_regle_quand_un_lanceur_precede_une_commande_simple(lanceur):
    assert bash("rm build") == "Bash(rm build:*)"
    assert bash(f"{lanceur} rm build") == ""
    assert bash(f"npm {lanceur}") == ""


# Règles « toujours » : WebFetch et les autres outils


def test_regle_webfetch_le_nom_de_domaine_seul():
    entree = {"url": "https://Example.com:8080/page?q=1", "prompt": "Résume."}
    assert regle_pour("WebFetch", entree) == "WebFetch(domain:example.com)"
    assert regle_pour("WebFetch", {"url": "https://docs.python.org/3/"}) \
        == "WebFetch(domain:docs.python.org)"


@pytest.mark.parametrize("url", [
    "http://localhost:3000/",
    "http://LOCALHOST/",
    "http://intranet/",
    "http://foo.localhost/",
    "http://metadata.google.internal/computeMetadata/v1/",
    "http://imprimante.local/",
])
def test_regle_webfetch_aucune_regle_pour_la_machine_ou_un_reseau_interne(url):
    assert regle_pour("WebFetch", {"url": url}) == ""
    assert phrase_pour("A", "WebFetch", {"url": url}) == f"A veut consulter l'adresse « {url} »."


@pytest.mark.parametrize("url", [
    "https://evil.com\\@example.com/",
    "https://utilisateur@example.com/",
    "https://example.com/@quelquun",
    "https://exa mple.com/",
    "https://example.com\t/",
    "https://example.com\x00/",
    "http://0x7f.1/",
    "http://127.0.0.1/",
    "http://2130706433/",
    "http://[::1]/",
    "http://exemple%2ecom/",
    "file:///etc/passwd",
    "ftp://example.com/",
    "pas une adresse",
    "",
])
def test_regle_webfetch_aucune_regle_pour_une_adresse_douteuse(url):
    assert regle_pour("WebFetch", {"url": url}) == ""
    assert "site" not in phrase_pour("A", "WebFetch", {"url": url})


def test_regle_autres_outils_le_nom_seul():
    assert regle_pour("Write", {"file_path": "a.py"}) == "Write"
    assert regle_pour("Edit", None) == "Edit"
    assert regle_pour("Outil(bizarre)", {}) == ""
    assert regle_pour(42, {}) == ""
    assert regle_pour("WebFetch", {}) == ""


# Phrases et détail pour la personne responsable


def test_phrases_en_francais():
    phrase = phrase_pour("B-ouvrier-1", "Bash", {"command": "npm install left-pad"}, "x")
    assert phrase == "B-ouvrier-1 veut lancer la commande « npm install left-pad »."
    web = phrase_pour("B-ouvrier-1", "WebFetch", {"url": "https://example.com/page"})
    assert web == "B-ouvrier-1 veut consulter le site example.com."
    ruse = phrase_pour("A", "WebFetch", {"url": "https://evil.com\\@example.com/"})
    assert ruse == "A veut consulter l'adresse « https://evil.com\\@example.com/ »."
    ecrire = phrase_pour("A", "Write", {"file_path": "atelier/x.py"})
    assert ecrire == "A veut écrire le fichier « atelier/x.py »."
    assert phrase_pour("A", "Tache", {}) == "A veut utiliser l'outil Tache."


def test_phrase_coupe_proprement_une_longue_commande_et_signale_le_cas_par_cas():
    commande = "echo " + "mot " * 200 + "&& rm x"
    phrase = phrase_pour("A", "Bash", {"command": commande}, "")
    assert len(phrase) < 260
    assert "[...] »." in phrase
    assert phrase.endswith(CAS_PAR_CAS)


def test_phrase_garde_les_retours_a_la_ligne_visibles():
    phrase = phrase_pour("A", "Bash", {"command": "cat notes.txt\nrm -rf ~/projets"})
    assert phrase == ("A veut lancer la commande « cat notes.txt [retour à la ligne] "
                      "rm -rf ~/projets »." + CAS_PAR_CAS)
    assert "\x1b" not in phrase_pour("A", "Bash", {"command": "ls \x1b[2J"})


def test_detail_le_texte_complet_de_la_demande():
    longue = "rm -rf build " + "x" * 200 + " /"
    assert detail_pour("Bash", {"command": longue}) == longue
    assert detail_pour("WebFetch", {"url": "https://example.com/a", "prompt": "p"}) \
        == "https://example.com/a"
    assert detail_pour("Edit", {"file_path": "a.py", "old_string": "x"}) == "a.py"
    assert json.loads(detail_pour("Grep", {"pattern": "def", "path": "src"})) \
        == {"pattern": "def", "path": "src"}
    assert detail_pour("Bash", {"command": "x" * 4000}) == "x" * 4000


def test_detail_borne_dit_combien_de_caracteres_sont_coupes():
    enorme = "x" * 2_000_000
    detail = detail_pour("Write", {"file_path": enorme})
    assert detail == "x" * 4000 + " [suite coupée : 1996000 caractères de plus]"
    assert len(detail_pour("Grep", {"pattern": enorme})) < 4100
    assert detail_pour("Bash", "rm -rf /") == '"rm -rf /"'


# Le guichet en fils parallèles


def test_deux_demandes_simultanees_repondues_dans_l_ordre_inverse():
    guichet = Guichet(delai_s=GARDE_S * 2)
    fil_1, res_1 = lancer(guichet, "B-ouvrier-1")
    attendre_ouvertes(guichet, 1)
    fil_2, res_2 = lancer(guichet, "C-ouvrier-1", "WebFetch", {"url": "https://example.com/"})
    ouvertes = attendre_ouvertes(guichet, 2)
    assert [d["agent"] for d in ouvertes] == ["B-ouvrier-1", "C-ouvrier-1"]
    assert ouvertes[1]["regle"] == "WebFetch(domain:example.com)"

    assert guichet.repondre(ouvertes[1]["id"], "toujours")
    finir(fil_2)
    assert res_2["reponse"] == Reponse("toujours", "", "WebFetch(domain:example.com)")
    assert fil_1.is_alive() and "reponse" not in res_1
    assert [d["agent"] for d in guichet.ouvertes()] == ["B-ouvrier-1"]

    assert guichet.repondre(ouvertes[0]["id"], "non", "Utilise plutôt pip.")
    finir(fil_1)
    assert res_1["reponse"] == Reponse("non", "Utilise plutôt pip.", "")
    assert guichet.ouvertes() == []


def test_ouvertes_montre_la_phrase_la_regle_et_le_detail():
    guichet = Guichet(delai_s=GARDE_S * 2)
    longue = "rm -rf build " + "x" * 200 + " /"
    fils = [
        lancer(guichet, "A", "Bash", {"command": "npm install left-pad"}),
        lancer(guichet, "B", "WebFetch", {"url": "https://example.com/page", "prompt": "p"}),
        lancer(guichet, "C", "Write", {"file_path": "atelier/x.py", "content": "x"}),
        lancer(guichet, "D", "Bash", {"command": longue}),
        lancer(guichet, "E", "Bash", {"command": "npm install x && rm -rf /"}),
    ]
    fiches = {d["agent"]: d for d in attendre_ouvertes(guichet, 5)}
    assert fiches["A"]["phrase"] == "A veut lancer la commande « npm install left-pad »."
    assert fiches["A"]["regle"] == "Bash(npm install:*)"
    assert fiches["A"]["detail"] == "npm install left-pad"
    assert fiches["B"]["phrase"] == "B veut consulter le site example.com."
    assert fiches["B"]["detail"] == "https://example.com/page"
    assert fiches["C"]["phrase"] == "C veut écrire le fichier « atelier/x.py »."
    assert (fiches["C"]["regle"], fiches["C"]["detail"]) == ("Write", "atelier/x.py")
    assert fiches["D"]["phrase"].endswith("[...] ».")
    assert fiches["D"]["detail"] == longue
    assert fiches["E"]["phrase"] == ("E veut lancer la commande « npm install x && rm -rf / »."
                                     " Cette commande ne peut être autorisée qu'au cas par cas.")
    assert fiches["E"]["regle"] == ""
    for agent in "ABCDE":
        guichet.annuler(agent)
    for fil, _ in fils:
        finir(fil)


def test_delai_depasse_la_demande_se_ferme_sur_non():
    guichet = Guichet(delai_s=0.2)
    debut = time.monotonic()
    fil, res = lancer(guichet, "A", "Bash", {"command": "ls"})
    finir(fil)
    assert time.monotonic() - debut > 0.15
    assert res["reponse"] == Reponse("non", "Pas de réponse de la personne responsable.", "")
    assert guichet.ouvertes() == []


def test_une_reponse_apres_le_delai_ne_debloque_rien():
    guichet = Guichet(delai_s=0.2)
    fil, res = lancer(guichet, "A")
    id_demande = attendre_ouvertes(guichet, 1)[0]["id"]
    finir(fil)
    assert res["reponse"].message == SANS_REPONSE
    assert not guichet.repondre(id_demande, "une_fois")


def test_reponses_invalides_ne_debloquent_rien():
    guichet = Guichet(delai_s=GARDE_S * 2)
    fil, res = lancer(guichet, "A")
    id_demande = attendre_ouvertes(guichet, 1)[0]["id"]
    assert not guichet.repondre(id_demande, "peut-etre")
    assert not guichet.repondre(id_demande, "")
    assert not guichet.repondre(id_demande, ["non"])
    assert not guichet.repondre("inconnu", "une_fois")
    assert not guichet.repondre([id_demande], "non")
    assert not guichet.repondre({"id": id_demande}, "non")
    assert not guichet.repondre(None, "non")
    assert fil.is_alive() and len(guichet.ouvertes()) == 1
    assert guichet.repondre(id_demande, "une_fois", "D'accord.")
    assert not guichet.repondre(id_demande, "non")
    finir(fil)
    assert res["reponse"] == Reponse("une_fois", "D'accord.", "")


def test_toujours_refuse_pour_une_demande_sans_regle_sure():
    guichet = Guichet(delai_s=GARDE_S * 2)
    fil, res = lancer(guichet, "A", "Bash", {"command": "npm install x && rm -rf /"})
    demande = attendre_ouvertes(guichet, 1)[0]
    assert demande["regle"] == ""
    assert not guichet.repondre(demande["id"], "toujours")
    assert fil.is_alive()
    assert guichet.repondre(demande["id"], "une_fois")
    finir(fil)
    assert res["reponse"] == Reponse("une_fois", "", "")


@pytest.mark.parametrize("outil, entree, phrase", [
    ("Bash", "rm -rf /", "A veut utiliser l'outil Bash."),
    ("Bash", {"command": None}, "A veut utiliser l'outil Bash."),
    ("Bash", None, "A veut utiliser l'outil Bash."),
    ("WebFetch", {"url": 3}, "A veut utiliser l'outil WebFetch."),
    (42, {"command": "ls"}, "A veut utiliser l'outil 42."),
    (["Bash"], {}, "A veut utiliser l'outil ['Bash']."),
])
def test_demande_bizarre_reste_une_demande_normale_sans_regle(outil, entree, phrase):
    guichet = Guichet(delai_s=GARDE_S * 2)
    fil, res = lancer(guichet, "A", outil, entree)
    fiche = attendre_ouvertes(guichet, 1)[0]
    assert (fiche["phrase"], fiche["regle"]) == (phrase, "")
    assert json.loads(json.dumps(fiche)) == fiche
    assert not guichet.repondre(fiche["id"], "toujours")
    assert guichet.repondre(fiche["id"], "non")
    finir(fil)
    assert res["reponse"] == Reponse("non", "", "")


def test_annuler_ferme_les_demandes_de_cet_agent_seulement():
    guichet = Guichet(delai_s=GARDE_S * 2)
    fils = [lancer(guichet, "A"), lancer(guichet, "A", "Write", {"file_path": "x"})]
    autre, res_autre = lancer(guichet, "B")
    attendre_ouvertes(guichet, 3)
    assert guichet.annuler("A") == 2
    for fil, res in fils:
        finir(fil)
        assert res["reponse"] == Reponse("non", "Arrêté par la personne responsable.", "")
    assert [d["agent"] for d in guichet.ouvertes()] == ["B"]
    assert autre.is_alive()
    assert guichet.annuler("personne") == 0
    assert guichet.annuler("B") == 1
    finir(autre)
    assert res_autre["reponse"].message == ARRETE


def test_identifiants_uniques_et_ouvertes_pret_pour_du_json():
    guichet = Guichet(delai_s=GARDE_S * 2)
    fils = [lancer(guichet, f"agent-{n}") for n in range(5)]
    ouvertes = attendre_ouvertes(guichet, 5)
    ids = [d["id"] for d in ouvertes]
    assert len(set(ids)) == 5
    assert all(re.fullmatch(r"[A-Za-z0-9_-]+", i) for i in ids)
    assert json.loads(json.dumps(ouvertes)) == ouvertes
    assert set(ouvertes[0]) == {"id", "agent", "outil", "phrase", "regle", "detail"}
    for n in range(5):  # nettoyage : on libère tous les fils
        guichet.annuler(f"agent-{n}")
    for fil, _ in fils:
        finir(fil)


def test_vingt_agents_en_parallele_recoivent_chacun_leur_reponse():
    guichet = Guichet(delai_s=GARDE_S * 2)
    fils = {f"agent-{n}": lancer(guichet, f"agent-{n}") for n in range(20)}
    ouvertes = attendre_ouvertes(guichet, 20)
    random.shuffle(ouvertes)
    repondeurs = [
        threading.Thread(target=guichet.repondre, args=(d["id"], "non", d["agent"]))
        for d in ouvertes
    ]
    for r in repondeurs:
        r.start()
    for r in repondeurs:
        finir(r)
    for agent, (fil, res) in fils.items():
        finir(fil)
        assert res["reponse"] == Reponse("non", agent, "")
    assert guichet.ouvertes() == []


@pytest.mark.parametrize("delai", [0, -1, float("nan")])
def test_delai_doit_etre_positif(delai):
    with pytest.raises(ValueError):
        Guichet(delai_s=delai)


@pytest.mark.parametrize("delai", [float("inf"), 1e300, 10**400])
def test_delai_enorme_borne_et_demande_sans_fantome(delai):
    guichet = Guichet(delai_s=delai)
    assert guichet.delai_s <= 24 * 3600
    fil, res = lancer(guichet, "A")
    fiche = attendre_ouvertes(guichet, 1)[0]
    assert guichet.repondre(fiche["id"], "une_fois")
    finir(fil)
    assert res["reponse"] == Reponse("une_fois", "", "")
    assert guichet.ouvertes() == []


# Le guichet simulé


def test_guichet_simule_suit_son_scenario_puis_dit_non():
    guichet = GuichetSimule(["une_fois", "toujours", Reponse("non", "Pas ça.")])
    entree = {"command": "npm install left-pad"}
    assert guichet.demander("A", "Bash", entree) == Reponse("une_fois", "", "")
    assert guichet.demander("A", "Bash", entree) == Reponse("toujours", "", "Bash(npm install:*)")
    assert guichet.demander("A", "Write", {"file_path": "x"}) == Reponse("non", "Pas ça.", "")
    epuise = guichet.demander("A", "Read", {"file_path": "x"})
    assert epuise == Reponse("non", "Le scénario de démonstration ne prévoit pas cette demande.")
    assert [d["outil"] for d in guichet.demandes] == ["Bash", "Bash", "Write", "Read"]
    assert guichet.ouvertes() == [] and not guichet.repondre("d1", "non")


def test_guichet_simule_n_accorde_jamais_une_regle_que_le_vrai_n_aurait_pas_proposee():
    guichet = GuichetSimule([
        "toujours",
        Reponse("toujours", "", "Bash(*)"),
        Reponse("toujours", "Vu.", "Bash(npm:*)"),
    ])
    assert guichet.demander("A", "Bash", {"command": "ls && rm x"}) == Reponse("une_fois")
    assert guichet.demander("A", "Bash", {"command": "ls; rm x"}) == Reponse("une_fois")
    reponse = guichet.demander("A", "Bash", {"command": "npm install x"})
    assert reponse == Reponse("toujours", "Vu.", "Bash(npm install:*)")


def test_guichet_simule_refuse_un_scenario_inconnu():
    with pytest.raises(ValueError):
        GuichetSimule(["oui"])


# La fin d'une répétition (mode plan) : l'ouvrier demande à passer à l'exécution


def test_la_fin_de_repetition_se_dit_en_clair_sans_regle_toujours():
    plan = "1. Écrire calcul.py.\n2. Lancer les tests."
    guichet = Guichet(delai_s=GARDE_S)
    fil, res = lancer(guichet, "B-ouvrier-1", "ExitPlanMode", {"plan": plan})
    (fiche,) = attendre_ouvertes(guichet, 1)
    assert fiche["phrase"] == (
        "B-ouvrier-1 a fini sa répétition et demande à passer à l'exécution de son plan."
    )
    assert (fiche["outil"], fiche["regle"], fiche["detail"]) == ("ExitPlanMode", "", plan)
    assert not guichet.repondre(fiche["id"], "toujours")  # jamais pour de bon
    assert guichet.repondre(fiche["id"], "une_fois")
    finir(fil)
    assert res["reponse"] == Reponse("une_fois", "", "")


def test_la_fin_de_repetition_sans_plan_lisible():
    assert regle_pour("ExitPlanMode", {"plan": "x"}) == ""
    assert detail_pour("ExitPlanMode", {}) == "{}"
    assert phrase_pour("A-ouvrier-2", "ExitPlanMode", None) == (
        "A-ouvrier-2 a fini sa répétition et demande à passer à l'exécution de son plan."
    )
