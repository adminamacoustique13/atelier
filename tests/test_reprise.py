"""Les pannes ordinaires : erreur de l'Atelier, redémarrage, état abîmé, test qui ne finit pas."""

import json
import subprocess
import time

import pytest

from atelier import modele
from atelier.agents import AgentSimule
from atelier.controles import DELAI_CONTROLES_S, ControlesGit, ControlesSimules, lire_delai
from atelier.modele import Chantier, Contrat, Tache
from atelier.moteur import PANNE, RELANCER_TEL, Moteur
from atelier.projets import lire_etat, ouvrir_depot


def chantier(taches):
    return Chantier(projet="Essai", contrat=Contrat(objectif="Essai", valide=True), taches=taches)


def tache(identifiant, **champs):
    champs.setdefault("perimetre", [f"{identifiant.lower()}.py"])
    return Tache(id=identifiant, titre=f"Tâche {identifiant}", **champs)


class ControlesEnPanne(ControlesSimules):
    """Des contrôles dont la préparation échoue pour une tâche, autant de fois que demandé."""

    def __init__(self, tache_en_panne, fois=1):
        self.tache_en_panne, self.reste = tache_en_panne, fois

    def preparer(self, tache):
        if tache.id == self.tache_en_panne and self.reste:
            self.reste -= 1
            raise RuntimeError("git worktree add : fatal: disque plein")
        return None


def test_une_erreur_de_l_atelier_rend_la_tache_sans_faire_tomber_le_moteur():
    c = chantier([tache("A"), tache("B"), tache("C", depend_de=["A"])])
    moteur = Moteur(c, AgentSimule(), ControlesEnPanne("A"))

    moteur.executer()  # ne lève pas : avant, l'erreur remontait et le fil du moteur mourait

    a, b, suite = c.taches
    assert (a.etat, b.etat, suite.etat) == ("revenu", "verifie", "a_lancer")
    assert a.historique[-1]["issue"] == PANNE
    assert "disque plein" in a.historique[-1]["detail"]
    (demande,) = [d for d in c.demandes if d["reponse"] is None]
    assert demande["tache"] == "A" and "erreur de l'Atelier" in demande["question"]
    assert not c.termine

    moteur.repondre(demande["id"], RELANCER_TEL)
    moteur.executer()
    assert c.termine and all(t.etat == "verifie" for t in c.taches)


def test_une_sauvegarde_qui_echoue_ne_defait_pas_une_tache_verifiee():
    c = chantier([tache("A")])
    pannes = []

    def sauver():
        dernier = c.evenements[-1]["texte"] if c.evenements else ""
        if dernier == "Vérifiée et enregistrée." and not pannes:
            pannes.append(1)
            raise OSError("No space left on device")

    Moteur(c, AgentSimule(), ControlesSimules(), sur_changement=sauver).executer()

    assert pannes and c.taches[0].etat == "verifie"
    assert not c.demandes
    assert any("No space left" in e["texte"] for e in c.evenements)


def test_au_chargement_les_taches_actives_reviennent_a_la_personne():
    c = chantier(
        [
            tache("A", etat="en_cours", tentatives=1, modele="sonnet", effort="low"),
            tache("B", etat="en_verification", tentatives=2, modele="sonnet", effort="low"),
            tache("C", depend_de=["A"]),
            tache("D", etat="verifie"),
        ]
    )
    relu = Chantier.depuis_dict(json.loads(json.dumps(c.en_dict())))  # comme relu sur le disque

    moteur = Moteur(relu, AgentSimule(), ControlesSimules(), {"reprise_auto": False})

    etats = {t.id: t.etat for t in relu.taches}
    assert etats == {"A": "revenu", "B": "revenu", "C": "a_lancer", "D": "verifie"}
    ouvertes = [d for d in relu.demandes if d["reponse"] is None]
    assert [d["tache"] for d in ouvertes] == ["A", "B"]
    assert all("s'est arrêté" in d["question"] for d in ouvertes)
    assert relu.tache("A").historique[-1]["issue"] == PANNE

    for demande in ouvertes:
        moteur.repondre(demande["id"], RELANCER_TEL)
    moteur.executer()
    assert relu.termine


def test_un_second_chargement_ne_redemande_rien():
    c = chantier([tache("A", etat="en_cours", tentatives=1)])
    Moteur(c, AgentSimule(), ControlesSimules(), {"reprise_auto": False})
    Moteur(c, AgentSimule(), ControlesSimules())
    assert len(c.demandes) == 1


def test_l_etat_est_ecrit_d_un_seul_geste(tmp_path, monkeypatch):
    chemin = tmp_path / ".atelier" / "etat.json"
    chantier([tache("A")]).sauver(chemin)
    avant = chemin.read_text("utf-8")
    assert [f.name for f in chemin.parent.iterdir()] == ["etat.json"]

    def coupure(source, cible):
        raise OSError("arrêt en pleine écriture")

    monkeypatch.setattr(modele.os, "replace", coupure)
    with pytest.raises(OSError):
        chantier([tache("A"), tache("B")]).sauver(chemin)

    assert chemin.read_text("utf-8") == avant  # l'ancien état est intact, pas tronqué
    assert len(Chantier.charger(chemin).taches) == 1


def test_un_etat_illisible_est_mis_de_cote_et_le_projet_s_ouvre(tmp_path):
    etat = tmp_path / ".atelier" / "etat.json"
    etat.parent.mkdir()
    etat.write_text('{"projet": "Essai", "contrat": {"objectif": "tron', "utf-8")

    c = lire_etat(tmp_path, "Essai")

    assert c.projet == "Essai" and not c.taches
    assert "illisible" in c.evenements[-1]["texte"]
    (ecarte,) = [f for f in etat.parent.iterdir() if f.name.startswith("etat-illisible-")]
    assert ecarte.read_text("utf-8").endswith('"tron')  # mis de côté, pas effacé
    assert ecarte.name in c.evenements[-1]["texte"]
    assert not etat.exists()


def test_sans_etat_ou_avec_un_etat_sain_rien_n_est_mis_de_cote(tmp_path):
    assert not lire_etat(tmp_path, "Essai").evenements
    chantier([tache("A")]).sauver(tmp_path / ".atelier" / "etat.json")
    assert [t.id for t in lire_etat(tmp_path, "Essai").taches] == ["A"]
    assert [f.name for f in (tmp_path / ".atelier").iterdir()] == ["etat.json"]


def depot_git(dossier):
    def git(*arguments):
        subprocess.run(["git", *arguments], cwd=dossier, check=True, capture_output=True)

    git("init", "-q", "-b", "main")
    git("config", "user.name", "Essai")
    git("config", "user.email", "essai@example.invalid")
    (dossier / "LISEZMOI.md").write_text("socle\n", "utf-8")
    git("add", "-A")
    git("commit", "-q", "-m", "socle")


def test_un_projet_rouvert_apres_un_arret_rend_sa_tache_et_le_sauve(tmp_path):
    depot_git(tmp_path)
    interrompu = chantier([tache("A", etat="en_cours", tentatives=1), tache("B", depend_de=["A"])])
    interrompu.sauver(tmp_path / ".atelier" / "etat.json")
    (tmp_path / "chantier").mkdir()
    (tmp_path / "chantier" / "profil.json").write_text('{"reprise_auto": false}', "utf-8")

    atelier = ouvrir_depot(tmp_path)

    assert atelier.moteur.chantier.tache("A").etat == "revenu"
    assert not atelier.en_marche()  # rien ne repart seul
    sur_disque = Chantier.charger(tmp_path / ".atelier" / "etat.json")
    assert sur_disque.tache("A").etat == "revenu" and len(sur_disque.demandes) == 1


def test_un_etat_illisible_n_empeche_pas_d_ouvrir_le_projet(tmp_path):
    depot_git(tmp_path)
    (tmp_path / ".atelier").mkdir()
    (tmp_path / ".atelier" / "etat.json").write_text("", "utf-8")

    atelier = ouvrir_depot(tmp_path)

    assert any("illisible" in e["texte"] for e in atelier.moteur.chantier.evenements)
    assert Chantier.charger(tmp_path / ".atelier" / "etat.json").projet == tmp_path.name


def test_une_commande_de_controle_qui_ne_finit_pas_est_arretee(tmp_path):
    depot_git(tmp_path)
    temoin = tmp_path / "temoin"
    controles = ControlesGit(
        tmp_path, commandes=["echo debut; (sleep 3; touch temoin) & sleep 30"], delai_s=0.5
    )

    depart = time.monotonic()
    passe, journal = controles.mecaniques(None, tmp_path)

    assert not passe and time.monotonic() - depart < 5
    assert "debut" in journal and "Pas de réponse après 0.5 secondes" in journal
    time.sleep(3.5)
    assert not temoin.exists()  # ce que la commande avait lancé est arrêté avec elle


def test_les_commandes_de_controle_gardent_leur_sortie_et_leur_verdict(tmp_path):
    depot_git(tmp_path)
    commandes = ["echo oui", "echo non >&2; exit 3", "echo jamais"]
    passe, journal = ControlesGit(tmp_path, commandes=commandes).mecaniques(None, tmp_path)
    assert not passe
    assert journal == "$ echo oui\noui\n\n$ echo non >&2; exit 3\nnon\n"
    verte = ControlesGit(tmp_path, commandes=["true"])
    assert verte.mecaniques(None, tmp_path) == (True, "$ true\n")


@pytest.mark.parametrize("valeur", [None, 0, -5, "600", True, [60]])
def test_un_delai_absent_ou_faux_vaut_trente_minutes(valeur):
    assert lire_delai(valeur) == DELAI_CONTROLES_S


def test_le_delai_des_controles_se_lit_dans_le_profil(tmp_path):
    depot_git(tmp_path)
    controles = ControlesGit(tmp_path, delai_s=90)
    assert controles.delai_s == 90
    controles.regler_outils({"commandes": ["true"], "delai_controles_s": 5.5})
    assert controles.delai_s == 5.5
    controles.regler_outils({"commandes": ["true"]})
    assert controles.delai_s == DELAI_CONTROLES_S
