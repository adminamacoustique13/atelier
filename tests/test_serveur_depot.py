"""L'état du dépôt donné à la page pour l'onglet « Dépôt » (fiche D2, côté serveur).

`SuiviDepot` garde la dernière lecture et n'en relance une que lorsqu'elle a vieilli ; avec un
vrai dépôt git, la lecture se fait dans un fil à part, et la vue ne l'attend jamais. Les attentes
de ces tests portent sur un état (la fin d'un fil, un signal), jamais sur une durée.
"""

import subprocess
import threading

from atelier.agents import AgentSimule
from atelier.controles import ControlesGit
from atelier.serveur import DEPOT_FRAIS_S, DEPOT_PLANCHER_S, Atelier, SuiviDepot
from tests.test_moteur import chantier, tache
from tests.test_serveur import atelier_simule


class Horloge:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def compteur(valeurs):
    """Une lecture qui rend, appel après appel, les valeurs données ; note chaque appel."""
    appels = []

    def lire():
        appels.append(1)
        valeur = valeurs[min(len(appels), len(valeurs)) - 1]
        if isinstance(valeur, Exception):
            raise valeur
        return valeur

    return lire, appels


# --- la lecture sur place (état d'exemple, sans git) ----------------------------------------


def test_la_lecture_est_gardee_tant_qu_elle_est_fraiche_puis_refaite():
    horloge = Horloge()
    lire, appels = compteur([{"n": 1}, {"n": 2}])
    suivi = SuiviDepot(lire, en_fond=False, horloge=horloge)
    assert suivi.etat() == {"n": 1} and suivi.etat() == {"n": 1} and len(appels) == 1
    horloge.t += DEPOT_FRAIS_S - 0.1
    assert suivi.etat() == {"n": 1} and len(appels) == 1
    horloge.t += 0.2
    assert suivi.etat() == {"n": 2} and len(appels) == 2


def test_une_lecture_qui_leve_garde_la_precedente_et_n_est_retentee_qu_apres_le_delai():
    horloge = Horloge()
    lire, appels = compteur([{"n": 1}, RuntimeError("git ne répond pas"), {"n": 3}])
    suivi = SuiviDepot(lire, en_fond=False, horloge=horloge)
    assert suivi.etat() == {"n": 1}
    horloge.t += DEPOT_FRAIS_S
    assert suivi.etat() == {"n": 1} and len(appels) == 2  # l'échec ne vide pas la page
    assert suivi.etat() == {"n": 1} and len(appels) == 2  # ni ne relance à chaque vue
    horloge.t += DEPOT_FRAIS_S
    assert suivi.etat() == {"n": 3}


def test_un_changement_du_chantier_fait_relire_sans_attendre_le_delai():
    lire, appels = compteur([{"n": 1}, {"n": 2}, {"n": 3}])
    suivi = SuiviDepot(lire, en_fond=False, horloge=Horloge())
    assert suivi.etat() == {"n": 1}
    suivi.perimer()
    assert suivi.etat() == {"n": 2} and suivi.etat() == {"n": 2} and len(appels) == 2


def test_en_fond_deux_lectures_restent_separees_meme_si_le_chantier_change_sans_cesse():
    horloge = Horloge()
    lire, appels = compteur([{"n": 1}, {"n": 2}])
    suivi = SuiviDepot(lire, en_fond=True, horloge=horloge)
    suivi.etat()
    assert suivi.attendre(10)
    suivi.perimer()
    assert suivi.etat() == {"n": 1} and suivi.attendre(10) and len(appels) == 1  # trop tôt
    horloge.t += DEPOT_PLANCHER_S
    suivi.etat()
    assert suivi.attendre(10) and suivi.etat() == {"n": 2}


def test_un_changement_d_etat_du_chantier_perime_le_depot_de_la_vue(tmp_path):
    atelier = atelier_simule(tmp_path, [tache("A")])
    assert atelier.vue()["depot"]["taches"]["A"]["entree"] is None
    atelier.moteur.executer()  # la tâche est vérifiée : chaque étape a sauvé l'état
    assert atelier.vue()["depot"]["taches"]["A"]["entree"] is not None  # sans attendre 5 s


def test_sans_rien_a_lire_l_etat_reste_vide():
    lire, appels = compteur([None])
    suivi = SuiviDepot(lire, en_fond=False, horloge=Horloge())
    assert suivi.etat() is None and suivi.etat() is None and len(appels) == 1


# --- la lecture en fond (un vrai dépôt git) --------------------------------------------------


def test_en_fond_la_vue_n_attend_pas_la_lecture_et_une_seule_court_a_la_fois():
    partie, finir, appels = threading.Event(), threading.Event(), []

    def lire():
        appels.append(1)
        partie.set()
        assert finir.wait(10)
        return {"n": len(appels)}

    suivi = SuiviDepot(lire, en_fond=True, horloge=Horloge())
    assert suivi.etat() is None  # rendu tout de suite, la lecture court derrière
    assert partie.wait(10)
    assert suivi.etat() is None and suivi.etat() is None and len(appels) == 1
    assert suivi.attendre(0) is False
    finir.set()
    assert suivi.attendre(10) is True
    assert suivi.etat() == {"n": 1} and len(appels) == 1


def test_en_fond_une_lecture_vieillie_est_refaite_et_l_ancienne_reste_affichee():
    horloge = Horloge()
    lire, appels = compteur([{"n": 1}, {"n": 2}])
    suivi = SuiviDepot(lire, en_fond=True, horloge=horloge)
    suivi.etat()
    assert suivi.attendre(10) and suivi.etat() == {"n": 1}
    horloge.t += DEPOT_FRAIS_S
    assert suivi.etat() == {"n": 1}  # l'ancienne, pendant que la nouvelle se lit
    assert suivi.attendre(10) and suivi.etat() == {"n": 2}


# --- dans la vue de l'atelier ---------------------------------------------------------------


def test_la_vue_d_une_demonstration_porte_un_depot_d_exemple_pour_chaque_tache(tmp_path):
    atelier = atelier_simule(tmp_path, [tache("A", etat="verifie"), tache("B")])
    depot = atelier.vue()["depot"]
    assert set(depot) == {"chantier", "taches", "en_ligne", "partages"}
    assert set(depot["taches"]) == {"A", "B"}
    assert depot["taches"]["A"]["entree"] is not None and depot["taches"]["B"]["entree"] is None


def test_la_vue_d_une_demonstration_donne_une_branche_a_une_tache_en_route(tmp_path):
    atelier = atelier_simule(tmp_path, [tache("A"), tache("B", etat="revenu")])
    atelier.moteur.chantier.tache("A").etat = "en_cours"  # son ouvrier vient de partir
    taches = atelier.vue()["depot"]["taches"]
    assert taches["A"]["branche"]["existe"] is True and taches["A"]["modifies"]["nombre"] >= 1
    assert taches["B"]["branche"]["existe"] is False


def test_l_etat_d_exemple_accepte_une_tache_sans_perimetre():
    from types import SimpleNamespace

    from atelier.controles import etat_du_depot_d_exemple

    etat = etat_du_depot_d_exemple([SimpleNamespace(id="A", titre="Lecture", etat="en_cours")])
    assert etat["taches"]["A"]["modifies"]["noms"] == ["coeur/a.py"]


def test_la_vue_d_un_vrai_depot_le_lit_en_fond_puis_le_porte(tmp_path):
    def git(*arguments):
        subprocess.run(["git", *arguments], cwd=tmp_path, check=True, capture_output=True)

    git("init", "-q", "-b", "main")
    git("config", "user.name", "Essai")
    git("config", "user.email", "essai@example.invalid")
    (tmp_path / "LISEZMOI.md").write_text("socle\n", "utf-8")
    git("add", "-A")
    git("commit", "-q", "-m", "socle")
    c = chantier([tache("A")])
    atelier = Atelier(tmp_path, c, AgentSimule(), ControlesGit(tmp_path), {})
    assert atelier.suivi_depot.en_fond is True
    atelier.vue()  # lance la lecture, sans l'attendre
    assert atelier.suivi_depot.attendre(20)
    depot = atelier.vue()["depot"]
    assert depot["chantier"]["branche"] == "main" and depot["chantier"]["probleme"] == ""
    assert depot["chantier"]["dernier"]["message"] == "socle"
    assert depot["taches"]["A"]["branche"] == {"nom": "tache/A", "existe": False}


def test_des_controles_qui_ne_savent_pas_lire_le_depot_laissent_la_page_sans_depot(tmp_path):
    class Muets:
        commandes = []

        def controler_principale(self):
            return True, ""

    atelier = atelier_simule(tmp_path, [tache("A")], controles=Muets())
    assert atelier.vue()["depot"] is None
