"""Les places et le régulateur d'abonnement, testés seuls avec une fausse heure (secondes Unix)."""

import ast
import math
import random
import time
from pathlib import Path

import pytest

from atelier import places as module
from atelier.places import Places

T0 = 1_800_000_000.0  # une fausse heure Unix ; rien ici ne lit l'heure du mur
MIN = 60.0


def heure_dite(t: float) -> str:
    return time.strftime("%H:%M", time.localtime(t))


def lancer(places: Places, noms, modele="sonnet", heure=T0) -> list[str]:
    """Fait partir les tâches nommées, dans l'ordre, tant qu'elles le peuvent ; rend les parties."""
    return [nom for nom in noms if places.partir(nom, modele, heure)]


# --- critère 1 : un module pur -------------------------------------------------------


def test_le_module_est_pur_sans_fil_ni_attente_ni_import_d_atelier_ni_lecture_de_l_heure():
    source = Path(module.__file__).read_text(encoding="utf-8")
    arbre = ast.parse(source)
    importes = set()
    for noeud in ast.walk(arbre):
        if isinstance(noeud, ast.Import):
            importes |= {alias.name.split(".")[0] for alias in noeud.names}
        elif isinstance(noeud, ast.ImportFrom):
            importes.add((noeud.module or "").split(".")[0])
    assert importes <= {"__future__", "math", "time", "dataclasses"}
    appels = {
        f"{n.func.value.id}.{n.func.attr}"
        for n in ast.walk(arbre)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and isinstance(n.func.value, ast.Name)
    }
    for interdit in ("time.time", "time.monotonic", "time.sleep", "time.perf_counter"):
        assert interdit not in appels
    assert "Unix" in module.__doc__ and "verrou" in module.__doc__
    assert "verrou" in Places.__doc__


# --- critère 2 : deux nombres réglables ----------------------------------------------


def test_sans_reglage_six_places_et_neuf_agents():
    places = Places()
    assert (places.paralleles, places.agents_max) == (6, 9)


@pytest.mark.parametrize("paralleles, attendu", [(6, 9), (4, 6), (1, 2), (2, 3), (3, 4), (10, 15)])
def test_agents_max_par_defaut_une_moitie_de_plus_et_au_moins_un_de_plus(paralleles, attendu):
    assert Places(paralleles).agents_max == attendu


@pytest.mark.parametrize(
    "valeur", ["six", "", "  ", None, True, False, math.nan, math.inf, -math.inf, [], {}, object()]
)
def test_un_reglage_mal_forme_prend_la_valeur_par_defaut_sans_erreur(valeur):
    places = Places(valeur, valeur)
    assert (places.paralleles, places.agents_max) == (6, 9)


@pytest.mark.parametrize("valeur", [0, -3, 0.5, "0", "-2", -math.pi])
def test_un_reglage_sous_un_est_ramene_a_un(valeur):
    places = Places(valeur, valeur)
    assert (places.paralleles, places.agents_max) == (1, 1)


def test_un_reglage_ecrit_en_texte_ou_a_virgule_est_lu():
    assert (Places("4", " 5 ").paralleles, Places("4", " 5 ").agents_max) == (4, 5)
    assert (Places(4.9).paralleles, Places(4.9).agents_max) == (4, 6)


def test_les_reglages_sont_relus_et_un_absent_reprend_sa_valeur_par_defaut():
    places = Places(2, 2)
    places.regler(8)
    assert (places.paralleles, places.agents_max) == (8, 12)
    places.regler(None, None)
    assert (places.paralleles, places.agents_max) == (6, 9)


# --- critère 3 : partir, passer en vérification, finir -------------------------------


def test_sans_reglage_six_taches_pretes_partent_ensemble_et_pas_une_septieme():
    places = Places()
    assert lancer(places, "ABCDEFG") == list("ABCDEF")
    assert not places.peut_partir("sonnet", T0)
    assert (places.en_ecriture(), places.agents_en_marche()) == (6, 6)


def test_avec_une_seule_place_b_part_pendant_que_a_est_verifiee_avec_son_jeton():
    places = Places(paralleles=1)  # sans réglage, une seule place donne 2 agents
    assert places.agents_max == 2
    assert lancer(places, "AB") == ["A"]
    assert places.en_verification("A", "opus", T0) is True
    assert places.a_son_jeton("A")
    assert places.partir("B", "sonnet", T0)  # l'ouvrier de B part pendant que A est vérifiée
    assert (places.en_ecriture(), places.agents_en_marche()) == (1, 2)


def test_un_verificateur_sans_jeton_attend_et_un_jeton_libere_va_a_lui_avant_un_ouvrier():
    places = Places(paralleles=6, agents_max=2)
    assert lancer(places, "AB") == ["A", "B"]
    places.rendre_jeton("A", T0)  # l'ouvrier de A a fini : place gardée pendant les contrôles
    assert lancer(places, "C") == ["C"]
    assert places.en_verification("A", "opus", T0) is False  # deux agents en marche déjà
    assert places.etat(T0)["verificateurs_en_attente"] == 1
    assert places.finir("B", T0) == ["A"]  # le jeton de B va au vérificateur de A
    assert places.a_son_jeton("A")
    assert not places.peut_partir("sonnet", T0)
    assert places.agents_en_marche() == 2


def test_un_verificateur_qui_attend_passe_avant_un_ouvrier_meme_sans_appel_a_servir():
    places = Places(paralleles=6, agents_max=1)
    assert lancer(places, "A") == ["A"]
    places.refus("A", "five_hour", T0 + 10 * MIN, T0)
    assert places.en_verification("A", "opus", T0) is False  # tout est suspendu
    apres = T0 + 11 * MIN
    assert not places.peut_partir("sonnet", apres)  # le seul jeton revient au vérificateur
    assert places.servir(apres) == ["A"]
    assert places.agents_en_marche() == 1


def test_les_verificateurs_sont_servis_du_plus_ancien_au_dernier():
    places = Places(paralleles=6, agents_max=1)
    lancer(places, "X")
    for nom in "ABC":
        places.en_verification(nom, "opus", T0)
    assert places.finir("X", T0) == ["A"]
    assert places.finir("A", T0) == ["B"]
    assert places.finir("B", T0) == ["C"]


def test_agents_max_deux_avec_six_taches_pretes():
    places = Places(paralleles=6, agents_max=2)
    pretes, finies, pic = list("ABCDEF"), [], 0
    phases: dict[str, str] = {}
    for _ in range(100):
        for nom in list(pretes):
            if places.partir(nom, "sonnet", T0):
                pretes.remove(nom)
                phases[nom] = "ouvrier"
        pic = max(pic, places.agents_en_marche())
        assert places.agents_en_marche() <= 2
        en_marche = [n for n, p in phases.items() if places.a_son_jeton(n)]
        if not en_marche:
            break
        nom = en_marche[0]
        if phases[nom] == "ouvrier":
            phases[nom] = "verification"
            places.en_verification(nom, "opus", T0)
        else:
            del phases[nom]
            places.finir(nom, T0)
            finies.append(nom)
    assert pic == 2 and sorted(finies) == list("ABCDEF") and not pretes


def test_finir_une_tache_jamais_partie_ne_rend_aucun_compte_negatif():
    places = Places(paralleles=2, agents_max=2)
    assert places.finir("Z", T0) == []
    assert places.rendre_jeton("Z", T0) == []
    etat = places.etat(T0)
    assert (etat["en_ecriture"], etat["agents_en_marche"], etat["verificateurs_en_attente"]) == (
        0,
        0,
        0,
    )
    assert lancer(places, "ABC") == ["A", "B"]  # les places n'ont pas grandi
    places.finir("A", T0)
    places.finir("A", T0)
    assert (places.en_ecriture(), places.agents_en_marche()) == (1, 1)


def test_partir_deux_fois_ne_prend_ni_seconde_place_ni_second_jeton():
    places = Places(paralleles=2, agents_max=2)
    assert places.partir("A", "sonnet", T0) and places.partir("A", "sonnet", T0)
    assert (places.en_ecriture(), places.agents_en_marche()) == (1, 1)


def test_une_verification_d_une_tache_inconnue_attend_un_jeton_sans_rien_casser():
    places = Places(paralleles=1, agents_max=1)
    assert places.en_verification("Z", "opus", T0) is True  # un jeton libre : servi
    assert not places.peut_partir("sonnet", T0)
    places.finir("Z", T0)
    assert places.peut_partir("sonnet", T0)


@pytest.mark.parametrize("graine", range(20))
def test_dans_n_importe_quel_ordre_les_comptes_restent_dans_leurs_bornes(graine):
    hasard = random.Random(graine)
    places = Places(paralleles=hasard.randint(1, 4), agents_max=hasard.randint(1, 5))
    taches, modeles = list("ABCDEFGH"), ["sonnet", "opus", "claude-opus-4-1", ""]
    heure = T0
    for _ in range(400):
        heure += hasard.choice([0, 1, 30, 5 * MIN])
        nom, modele = hasard.choice(taches), hasard.choice(modeles)
        geste = hasard.randrange(8)
        if geste == 0:
            places.partir(nom, modele, heure)
        elif geste == 1:
            places.en_verification(nom, modele, heure)
        elif geste == 2:
            places.finir(nom, heure)
        elif geste == 3:
            places.rendre_jeton(nom, heure)
        elif geste == 4:
            places.servir(heure)
        elif geste == 5:
            places.refus(nom, hasard.choice(["five_hour", "seven_day_opus", None]), None, heure)
        elif geste == 6:
            places.alerte("five_hour", hasard.choice([None, heure + MIN]), heure)
        else:
            places.peut_partir(modele, heure, nom)
        etat = places.etat(heure)
        assert 0 <= etat["agents_en_marche"] <= places.agents_max
        assert 0 <= etat["en_ecriture"] <= places.paralleles
        assert 0 <= etat["verificateurs_en_attente"] <= len(taches)
        assert not any(places.a_son_jeton(t) for t in places._attente)


def test_un_plafond_abaisse_n_arrete_personne_mais_ne_donne_plus_rien():
    places = Places(paralleles=6, agents_max=6)
    lancer(places, "ABCD")
    places.regler(6, 2)
    assert places.agents_en_marche() == 4 and not places.peut_partir("sonnet", T0)
    for nom in "ABC":
        places.finir(nom, T0)
    assert places.peut_partir("sonnet", T0)


# --- critère 4 : l'alerte de limite --------------------------------------------------


def test_une_alerte_divise_les_places_par_deux_jusqu_a_l_heure_dite():
    places = Places()
    assert places.alerte("five_hour", T0 + 10 * MIN, T0) is True
    assert places.places_effectives(T0) == 3
    assert lancer(places, "ABCD") == list("ABC")
    assert places.places_effectives(T0 + 10 * MIN - 1) == 3
    assert places.places_effectives(T0 + 10 * MIN) == 6
    assert places.peut_partir("sonnet", T0 + 10 * MIN)


def test_une_alerte_n_arrete_aucun_agent_en_marche():
    places = Places()
    lancer(places, "ABCDEF")
    places.alerte("five_hour", None, T0)
    assert places.agents_en_marche() == 6 and places.en_ecriture() == 6
    places.finir("A", T0)
    assert not places.peut_partir("sonnet", T0)  # 5 écrivent encore, 3 places effectives


def test_une_alerte_sans_heure_dure_trente_minutes():
    places = Places()
    places.alerte("five_hour", None, T0)
    assert places.places_effectives(T0 + 30 * MIN - 1) == 3
    assert places.places_effectives(T0 + 30 * MIN) == 6


@pytest.mark.parametrize("paralleles, effectives", [(1, 1), (2, 1), (5, 2), (6, 3), (9, 4)])
def test_une_alerte_laisse_au_moins_une_place(paralleles, effectives):
    places = Places(paralleles)
    places.alerte("seven_day", None, T0)
    assert places.places_effectives(T0) == effectives


def test_une_alerte_repetee_dix_fois_n_est_nouvelle_qu_une_fois_et_ne_divise_qu_une_fois():
    places = Places()
    nouvelles = [places.alerte("five_hour", T0 + 2 * 3600, T0 + i) for i in range(10)]
    assert nouvelles == [True] + [False] * 9
    assert places.places_effectives(T0 + 10) == 3


def test_une_alerte_sans_heure_repetee_prolonge_sans_etre_nouvelle():
    places = Places()
    assert [places.alerte(None, None, T0 + i * 10 * MIN) for i in range(3)] == [
        True,
        False,
        False,
    ]
    assert places.places_effectives(T0 + 20 * MIN + 30 * MIN - 1) == 3
    assert places.places_effectives(T0 + 50 * MIN) == 6


def test_une_alerte_est_nouvelle_pour_une_autre_limite_une_autre_heure_ou_apres_sa_fin():
    places = Places()
    assert places.alerte("five_hour", T0 + 600, T0)
    assert places.alerte("seven_day", T0 + 600, T0)  # une autre limite
    assert places.alerte("five_hour", T0 + 900, T0)  # une autre heure
    assert not places.alerte("five_hour", None, T0)  # la même, sans heure cette fois
    assert places.alerte("five_hour", T0 + 3600, T0 + 900)  # la précédente a pris fin
    assert places.places_effectives(T0) == 3  # deux limites : toujours une seule division


def test_plusieurs_alertes_en_cours_ne_divisent_les_places_qu_une_fois():
    places = Places(paralleles=9)
    for type_limite in ("five_hour", "seven_day", "seven_day_opus", "overage"):
        assert places.alerte(type_limite, T0 + 3600, T0)
    places.alerte(None, None, T0)
    assert places.places_effectives(T0 + 10 * MIN) == 4  # cinq alertes en cours : 9 // 2


@pytest.mark.parametrize("fin", ["demain", math.nan, math.inf, True, [], T0 - 1, T0])
def test_une_heure_mal_formee_ou_passee_compte_comme_inconnue_sans_erreur(fin):
    places = Places()
    assert places.alerte(42, fin, T0) is True
    assert places.places_effectives(T0 + 30 * MIN - 1) == 3
    assert places.places_effectives(T0 + 30 * MIN) == 6


# --- critère 5 : le refus pour limite ------------------------------------------------


def test_un_refus_suspend_tout_lancement_jusqu_a_la_remise_a_zero_plus_soixante_secondes():
    places = Places()
    lancer(places, "A")
    issue = places.refus("A", "five_hour", T0 + 10 * MIN, T0)
    reprise = T0 + 10 * MIN + 60
    assert issue["reprise"] == reprise and issue["portee"] == ""
    for modele in ("sonnet", "opus", "haiku", "fable"):
        assert not places.peut_partir(modele, reprise - 1)
        assert places.suspension(modele, reprise - 1) == reprise
        assert places.peut_partir(modele, reprise)
        assert places.suspension(modele, reprise) is None


def test_un_refus_suspend_aussi_les_verificateurs():
    places = Places(paralleles=6, agents_max=6)
    lancer(places, "AB")
    places.refus("A", "five_hour", T0 + 10 * MIN, T0)
    assert places.en_verification("B", "opus", T0) is False  # B a son jeton, mais pas de départ
    assert places.servir(T0 + 10 * MIN) == []
    assert places.servir(T0 + 11 * MIN) == ["B"]


def test_un_ouvrier_refuse_rend_sa_place_et_son_jeton_et_repart_comme_une_tache_neuve():
    places = Places(paralleles=2, agents_max=2)
    lancer(places, "AB")
    places.refus("A", "five_hour", T0 + MIN, T0)
    assert (places.en_ecriture(), places.agents_en_marche()) == (1, 1)
    assert places.partir("C", "sonnet", T0 + 2 * MIN)  # la place de A est libre
    assert not places.partir("A", "sonnet", T0 + 2 * MIN)  # A n'a rien gardé
    places.finir("C", T0 + 3 * MIN)
    assert places.partir("A", "sonnet", T0 + 3 * MIN)


def test_des_ouvriers_opus_refuses_ne_tiennent_pas_les_places_d_une_tache_sonnet():
    places = Places(paralleles=2)
    assert lancer(places, "AB", modele="opus") == ["A", "B"]
    for nom in "AB":
        places.refus(nom, "seven_day_opus", T0 + 7 * 24 * 3600, T0)
    assert (places.en_ecriture(), places.agents_en_marche()) == (0, 0)
    assert places.partir("C", "sonnet", T0 + MIN)


def test_un_verificateur_refuse_pour_limite_reprend_la_tete_de_la_file():
    places = Places(paralleles=6, agents_max=1)
    lancer(places, "A")
    assert places.en_verification("A", "opus", T0)
    places.en_verification("B", "opus", T0)  # B attend le seul jeton
    issue = places.refus("A", "five_hour", T0 + MIN, T0)
    assert issue["servis"] == [] and not places.a_son_jeton("A")
    assert places.etat(T0)["verificateurs_en_attente"] == 2
    assert places.servir(T0 + 2 * MIN) == ["A"]


def test_refus_pour_limite_sans_heure_quinze_trente_soixante_soixante_minutes():
    places = Places()
    heure, attentes = T0, []
    for _ in range(4):
        reprise = places.refus("A", None, None, heure)["reprise"]
        attentes.append((reprise - heure) / MIN)
        heure = reprise  # le refus suivant vient après la reprise
        assert places.partir("A", "sonnet", heure)
    assert attentes == [15, 30, 60, 60]


def test_un_refus_pendant_une_suspension_ne_double_pas_l_attente():
    places = Places()
    lancer(places, "AB")
    premier = places.refus("A", None, None, T0)
    second = places.refus("B", None, None, T0 + MIN)  # B était parti avant la suspension
    assert premier["nouvelle"] and not second["nouvelle"]
    assert second["reprise"] == premier["reprise"] == T0 + 15 * MIN


def test_un_refus_avec_heure_pendant_une_suspension_peut_la_prolonger():
    places = Places()
    lancer(places, "AB")
    places.refus("A", None, None, T0)
    issue = places.refus("B", "five_hour", T0 + 2 * 3600, T0 + MIN)
    assert issue["nouvelle"] and issue["reprise"] == T0 + 2 * 3600 + 60


def test_un_agent_lance_apres_la_reprise_qui_finit_remet_l_attente_a_quinze_minutes():
    places = Places()
    lancer(places, "A")
    reprise = places.refus("A", None, None, T0)["reprise"]
    assert places.partir("A", "sonnet", reprise)
    places.finir("A", reprise + MIN)  # fini sans refus pour limite
    lancer(places, "B", heure=reprise + 2 * MIN)
    issue = places.refus("B", None, None, reprise + 3 * MIN)
    assert issue["reprise"] - (reprise + 3 * MIN) == 15 * MIN


def test_un_agent_lance_avant_la_suspension_qui_finit_ne_remet_pas_l_attente():
    places = Places()
    lancer(places, "AB")
    reprise = places.refus("A", None, None, T0)["reprise"]
    places.finir("B", T0 + MIN)  # parti avant le refus : ne prouve rien
    assert places.partir("A", "sonnet", reprise)
    issue = places.refus("A", None, None, reprise + MIN)
    assert issue["reprise"] - (reprise + MIN) == 30 * MIN


def test_une_limite_d_opus_suspend_aussi_fable_par_prudence():
    assert module.FAMILLES_SUSPENDUES["opus"] == ("opus", "fable")
    places = Places(paralleles=6, agents_max=1)
    places.refus("X", "seven_day_opus", T0 + 3600, T0)
    assert places.suspension("fable", T0) == T0 + 3600 + 60
    assert not places.peut_partir("fable", T0) and places.peut_partir("sonnet", T0)
    assert places.en_verification("A", "fable", T0) is False  # pas de jeton pour Fable
    assert places.servir(T0 + 3600 + 60) == ["A"]


def test_une_limite_d_opus_laisse_partir_une_tache_sonnet():
    places = Places()
    lancer(places, "A", modele="opus")
    issue = places.refus("A", "seven_day_opus", None, T0)
    assert issue["portee"] == "opus"
    assert not places.peut_partir("opus", T0 + MIN)
    assert not places.peut_partir("claude-opus-4-1", T0 + MIN)
    assert places.partir("B", "sonnet", T0 + MIN)
    assert places.suspension("sonnet", T0 + MIN) is None


def test_une_limite_de_sonnet_laisse_partir_opus_et_une_limite_commune_arrete_tout():
    places = Places()
    places.refus("A", "seven_day_sonnet", T0 + 3600, T0)
    assert places.peut_partir("opus", T0) and not places.peut_partir("sonnet", T0)
    places.refus("B", "overage", None, T0)
    assert not places.peut_partir("opus", T0)


def test_un_verificateur_d_un_modele_suspendu_ne_prend_pas_de_jeton():
    places = Places(paralleles=6, agents_max=1)
    lancer(places, "A")
    places.refus("X", "seven_day_opus", T0 + 3600, T0)
    assert places.en_verification("A", "opus", T0) is False  # son jeton est rendu
    assert places.partir("B", "sonnet", T0)  # l'ouvrier Sonnet le prend
    places.finir("B", T0 + 3600 + 59)
    assert not places.a_son_jeton("A")
    assert places.servir(T0 + 3600 + 60) == ["A"]


def test_une_surcharge_arrete_tout_lancement_deux_minutes_et_le_dit():
    places = Places()
    lancer(places, "AB")
    issue = places.surcharge("A", T0)
    assert (issue["portee"], issue["reprise"], issue["nouvelle"]) == ("surcharge", T0 + 120, True)
    assert places.en_ecriture() == 1  # l'ouvrier refusé rend sa place, B continue
    for modele in ("sonnet", "opus", "haiku", "fable"):
        assert not places.peut_partir(modele, T0 + 119)
    assert places.peut_partir("sonnet", T0 + 120)
    assert places.etat(T0)["suspensions"] == {"surcharge": T0 + 120}
    assert "Claude est surchargé pour un moment" in places.etat(T0)["phrase"]
    assert "limite de l'abonnement est atteinte" not in places.etat(T0)["phrase"]


def test_une_surcharge_pendant_la_pause_la_prolonge_sans_la_doubler():
    places = Places()
    places.surcharge("A", T0)
    issue = places.surcharge("B", T0 + 30)
    assert issue["reprise"] == T0 + 150 and issue["nouvelle"]
    assert places.surcharge("C", T0 + 200)["reprise"] == T0 + 320


@pytest.mark.parametrize(
    "type_limite",
    ["inconnue", "twelve_hour", "Seven_Day_Opus", "five_hour", "seven_day", "overage"],
)
def test_un_type_de_limite_en_texte_qui_ne_vise_pas_un_modele_suspend_tout(type_limite):
    places = Places()
    issue = places.refus("A", type_limite, None, T0)
    assert issue["portee"] == ""
    for modele in ("sonnet", "opus", "fable", "haiku"):
        assert not places.peut_partir(modele, T0 + MIN)
        assert places.suspension(modele, T0 + MIN) == T0 + 15 * MIN


@pytest.mark.parametrize("type_limite, fin", [(None, "x"), (12, math.nan), ("", True), ([], {})])
def test_un_refus_mal_forme_suspend_tout_quinze_minutes_sans_erreur(type_limite, fin):
    places = Places()
    issue = places.refus("A", type_limite, fin, T0)
    assert issue["portee"] == "" and issue["reprise"] == T0 + 15 * MIN


# --- critère 6 : l'état pour l'affichage ---------------------------------------------


def test_l_etat_dit_les_places_les_agents_et_les_verificateurs_en_attente():
    places = Places(paralleles=4, agents_max=2)
    lancer(places, "ABC")
    places.rendre_jeton("A", T0)
    lancer(places, "C")
    places.en_verification("A", "opus", T0)
    etat = places.etat(T0)
    assert {k: etat[k] for k in etat if k != "phrase"} == {
        "places": 4,
        "places_effectives": 4,
        "en_ecriture": 2,
        "agents_max": 2,
        "agents_en_marche": 2,
        "verificateurs_en_attente": 1,
        "alerte_jusqu_a": None,
        "reprise": None,
        "suspensions": {},
    }
    assert etat["phrase"] == (
        "2 tâches en écriture sur 4 places, 2 agents en marche sur 2 au plus, "
        "1 vérificateur en attente."
    )


def test_l_etat_dit_l_alerte_et_la_suspension_avec_leur_heure():
    places = Places()
    places.alerte("five_hour", T0 + 20 * MIN, T0)
    places.refus("A", "five_hour", T0 + 30 * MIN, T0)
    etat = places.etat(T0)
    assert etat["places_effectives"] == 3 and etat["alerte_jusqu_a"] == T0 + 20 * MIN
    assert etat["reprise"] == T0 + 31 * MIN
    assert "0 tâche en écriture sur 3 places" in etat["phrase"]
    alerte = f"3 places au lieu de 6, l'alerte prend fin à {heure_dite(T0 + 20 * MIN)}."
    suspension = f"plus aucun lancement, ils reprennent à {heure_dite(T0 + 31 * MIN)}."
    assert alerte in etat["phrase"] and suspension in etat["phrase"]


def test_l_etat_dit_la_suspension_propre_a_un_modele_et_sa_date_si_elle_tombe_un_autre_jour():
    places = Places()
    fin = T0 + 3 * 24 * 3600
    places.refus("A", "seven_day_opus", fin, T0)
    etat = places.etat(T0)
    assert etat["reprise"] is None and etat["suspensions"] == {"opus": fin + 60}
    date = time.strftime("le %d/%m à %H:%M", time.localtime(fin + 60))
    attendu = "La limite propre à Opus est atteinte : plus aucun lancement d'Opus ni de Fable,"
    assert f"{attendu} ils reprennent {date}." in etat["phrase"]


def test_l_etat_oublie_ce_qui_a_pris_fin():
    places = Places()
    places.alerte("five_hour", T0 + MIN, T0)
    places.refus("A", "seven_day_sonnet", T0 + MIN, T0)
    etat = places.etat(T0 + 2 * MIN + 1)
    assert etat["alerte_jusqu_a"] is None and etat["suspensions"] == {}
    assert etat["phrase"].count(".") == 1


def test_la_prochaine_echeance_est_la_fin_la_plus_proche():
    places = Places()
    assert places.prochaine_echeance(T0) is None
    places.alerte("five_hour", T0 + 20 * MIN, T0)
    places.refus("A", "seven_day_opus", T0 + 5 * MIN, T0)
    assert places.prochaine_echeance(T0) == T0 + 6 * MIN
    assert places.prochaine_echeance(T0 + 6 * MIN) == T0 + 20 * MIN
    assert places.prochaine_echeance(T0 + 20 * MIN) is None


# --- seconde passe : aucun interblocage ----------------------------------------------


def test_le_scenario_d_interblocage_trouve_par_le_verificateur_ne_bloque_plus():
    places = Places(paralleles=1)  # 2 agents
    places.refus("X", "seven_day_opus", T0 + 3600, T0)  # une limite propre à Opus en cours
    assert places.en_verification("A", "opus", T0) is False
    assert places.en_verification("C", "opus", T0) is False
    assert places.partir("W", "sonnet", T0)
    places.refus("W", "five_hour", T0 + 10 * MIN, T0 + MIN)  # W rend sa place et son jeton
    reprise = T0 + 2 * 3600
    assert places.servir(reprise) == ["A", "C"]
    # A et C rejettent le livrable : leurs ouvriers veulent repartir, W aussi
    assert places.partir("A", "sonnet", reprise)  # la place de W était libre
    assert not places.partir("C", "sonnet", reprise)  # aucune place : C rend son jeton
    assert not places.partir("W", "sonnet", reprise)  # la place est à A, qui avance
    assert (places.en_ecriture(), places.agents_en_marche()) == (1, 1)
    assert places.en_verification("A", "opus", reprise)  # A rend sa place
    assert places.partir("W", "sonnet", reprise)


@pytest.mark.parametrize("paralleles", [1, 6])  # 2 agents, puis 9
def test_des_jetons_sans_place_et_des_places_sans_jeton_ne_se_bloquent_pas(paralleles):
    places = Places(paralleles)
    verificateurs = [f"V{i}" for i in range(places.agents_max)]
    ouvriers = [f"W{i}" for i in range(paralleles)]
    places.refus("X", "seven_day_opus", T0 + MIN, T0)
    for nom in verificateurs:
        assert places.en_verification(nom, "opus", T0) is False  # Opus suspendu : ils attendent
    for nom in ouvriers:
        assert places.partir(nom, "sonnet", T0)
        places.rendre_jeton(nom, T0)  # l'ouvrier a fini, ses contrôles tournent
    apres = T0 + 2 * MIN
    assert places.servir(apres) == verificateurs  # tous les jetons vont aux vérificateurs
    # les contrôles sont rouges et les vérificateurs rejettent : tout le monde veut écrire
    for nom in verificateurs:
        assert not places.partir(nom, "sonnet", apres)  # aucune place : il rend son jeton
    for nom in ouvriers:
        assert places.partir(nom, "sonnet", apres)  # les places tenues reçoivent un jeton
    assert (places.en_ecriture(), places.agents_en_marche()) == (paralleles, paralleles)


# Tirages réalistes : l'ouvrier est souvent Sonnet, son vérificateur un modèle au-dessus, et la
# limite d'Opus est la plus fréquente.
TYPES_DE_LIMITE = ["seven_day_opus", "seven_day_opus", "five_hour", "seven_day_sonnet", None]
MODELES_OUVRIERS = ["sonnet", "sonnet", "opus", "fable"]
MODELES_VERIFICATEURS = ["opus", "opus", "fable", "sonnet"]
QUI_AVANCENT = {"ouvrier", "controles", "verificateur"}  # phases qui finissent d'elles-mêmes


def refuser(places, hasard, nom, heure) -> None:
    """Un refus pour limite tiré au hasard : jamais un échec, la tâche attend la reprise."""
    fin = hasard.choice([None, heure + MIN, heure + 10 * MIN, heure + 3600])
    places.refus(nom, hasard.choice(TYPES_DE_LIMITE), fin, heure)


def apres_ouvrier(places, hasard, nom, heure) -> str:
    tirage = hasard.random()
    if tirage < 0.15:
        refuser(places, hasard, nom, heure)
        return "prete"
    if tirage < 0.75:
        places.rendre_jeton(nom, heure)  # le moteur peut rendre le jeton pendant les contrôles
    return "controles"


def apres_controles(places, hasard, nom, heure) -> str:
    tirage = hasard.random()
    if tirage < 0.5:
        verifie = places.en_verification(nom, hasard.choice(MODELES_VERIFICATEURS), heure)
        return "verificateur" if verifie else "attend_jeton"
    if tirage < 0.95:
        return "reprise"  # contrôles rouges : l'ouvrier repart dans sa copie
    places.finir(nom, heure)
    return "finie"


def apres_verificateur(places, hasard, nom, heure) -> str:
    tirage = hasard.random()
    if tirage < 0.15:
        places.finir(nom, heure)
        return "finie"
    if tirage < 0.85:
        return "reprise"  # rejet : l'ouvrier repart, la tâche tient encore son jeton
    refuser(places, hasard, nom, heure)
    return "attend_jeton"


FINS_D_AGENT = {
    "ouvrier": apres_ouvrier,
    "controles": apres_controles,
    "verificateur": apres_verificateur,
}


def avancer(places, hasard, nom, phase, modele, heure) -> str:
    """Un pas d'un moteur conforme au contrat pour la tâche `nom` ; rend sa nouvelle phase."""
    if phase in ("prete", "reprise"):
        return "ouvrier" if places.partir(nom, modele, heure) else phase
    if phase == "attend_jeton":
        return "verificateur" if places.a_son_jeton(nom) else phase
    if phase in FINS_D_AGENT:
        return FINS_D_AGENT[phase](places, hasard, nom, heure)
    return phase


def relancer_tout(places, phases, modeles, heure) -> bool:
    """Le moteur attend la fin des alertes et suspensions, puis réessaie chaque tâche en attente.

    Rend vrai si au moins une tâche est repartie.
    """
    for _ in range(len(phases) + 2):
        places.servir(heure)
        for nom, phase in phases.items():
            if phase in ("prete", "reprise", "attend_jeton"):
                phases[nom] = avancer(places, None, nom, phase, modeles[nom], heure)
        if any(p in QUI_AVANCENT for p in phases.values()):
            return True
    return False


def interblocage(graine: int) -> str:
    """Joue une suite d'appels conforme au contrat ; rend la description d'un interblocage."""
    hasard = random.Random(graine)
    places = Places(hasard.randint(1, 2), hasard.choice([None, 1, 2, 3]))
    phases = {f"T{i}": "prete" for i in range(hasard.randint(3, 7))}
    modeles = {nom: hasard.choice(MODELES_OUVRIERS) for nom in phases}
    heure = T0
    for _ in range(120):
        heure += hasard.choice([0, 1, 30, MIN, 5 * MIN])
        if hasard.random() < 0.05:
            places.alerte(hasard.choice(TYPES_DE_LIMITE), hasard.choice([None, heure + MIN]), heure)
        places.servir(heure)
        nom = hasard.choice([n for n, p in phases.items() if p != "finie"])
        phases[nom] = avancer(places, hasard, nom, phases[nom], modeles[nom], heure)
        if all(p == "finie" for p in phases.values()):
            return ""
        if not any(p in QUI_AVANCENT for p in phases.values()):
            while (echeance := places.prochaine_echeance(heure)) is not None:
                heure = echeance  # même un jour plus tard : plus aucune suspension en cours
            if not relancer_tout(places, phases, modeles, heure):
                return f"graine {graine} : {phases}, {places.etat(heure)['phrase']}"
    return ""


def test_au_hasard_aucune_suite_conforme_au_contrat_ne_finit_en_interblocage():
    debut, graine, trouves = time.monotonic(), 0, []
    while graine < 3000 and time.monotonic() - debut < 5:
        if bloque := interblocage(graine):
            trouves.append(bloque)
        graine += 1
    assert not trouves, trouves[:3]
    assert graine >= 300  # assez de suites jouées pour que l'essai dise quelque chose


# --- les pannes d'agent : la tâche patiente seule (M6) ---------------------------------------


def test_une_pause_rend_place_et_jeton_et_ne_retient_que_sa_tache():
    places = Places(paralleles=2, agents_max=2)
    assert lancer(places, "AB") == ["A", "B"]
    issue = places.pause("A", T0 + MIN, T0)
    assert issue == {"reprise": T0 + MIN, "servis": []}
    assert (places.en_ecriture(), places.agents_en_marche()) == (1, 1)
    assert places.partir("C", "sonnet", T0)  # la place de A va à une autre tâche
    assert places.suspension("sonnet", T0) is None  # ce n'est pas une limite
    assert places.en_pause("A", T0) == T0 + MIN and places.en_pause("C", T0) is None
    places.finir("C", T0)
    assert not places.peut_partir("sonnet", T0 + MIN - 1, "A")
    assert not places.partir("A", "sonnet", T0 + MIN - 1)
    assert places.partir("A", "sonnet", T0 + MIN)  # la pause est finie : elle repart
    assert places.en_pause("A", T0 + MIN) is None


def test_un_verificateur_en_pause_sort_de_la_file_et_n_est_servi_qu_apres_sa_pause():
    places = Places(paralleles=2, agents_max=1)
    lancer(places, "A")
    assert places.en_verification("A", "opus", T0)  # le jeton de l'ouvrier passe au vérificateur
    issue = places.pause("A", T0 + MIN, T0)
    assert issue["reprise"] == T0 + MIN and places.agents_en_marche() == 0
    assert places.etat(T0)["verificateurs_en_attente"] == 0
    assert places.partir("B", "sonnet", T0)  # le jeton rendu va à un ouvrier
    places.rendre_jeton("B", T0)
    assert places.en_verification("A", "opus", T0 + 1) is False  # encore en pause : il attend
    assert places.servir(T0 + MIN - 1) == []
    assert places.peut_partir("sonnet", T0 + MIN - 1)  # en pause, il ne retient pas les ouvriers
    assert not places.peut_partir("sonnet", T0 + MIN)  # sa pause finie, son tour vient d'abord
    assert places.servir(T0 + MIN) == ["A"]


def test_une_pause_mal_formee_ou_deja_passee_ne_retient_pas_la_tache_mais_rend_sa_place():
    places = Places(paralleles=1)
    for reprise in (None, "demain", math.nan, math.inf, T0, T0 - 1, True):
        lancer(places, "A")
        assert places.pause("A", reprise, T0)["reprise"] is None
        assert places.en_ecriture() == 0 and places.en_pause("A", T0) is None
        assert places.peut_partir("sonnet", T0, "A")


def test_finir_efface_la_pause_et_une_tache_inconnue_peut_patienter():
    places = Places()
    assert places.pause("Z", T0 + MIN, T0)["servis"] == []  # jamais partie : rien à rendre
    assert places.en_pause("Z", T0) == T0 + MIN
    places.finir("Z", T0)
    assert places.en_pause("Z", T0) is None and places.prochaine_echeance(T0) is None


def test_une_limite_pendant_une_pause_s_y_ajoute_et_la_plus_tardive_l_emporte():
    places = Places()
    places.pause("A", T0 + 5 * MIN, T0)
    places.refus("B", "five_hour", None, T0 + MIN)  # 15 minutes, sans heure
    assert places.suspension("sonnet", T0 + MIN, "A") == T0 + 16 * MIN
    assert places.suspension("sonnet", T0 + MIN) == T0 + 16 * MIN
    assert not places.peut_partir("sonnet", T0 + 6 * MIN, "A")  # la pause est finie, pas la limite
    autre = Places()
    autre.pause("A", T0 + 30 * MIN, T0)
    autre.refus("B", "seven_day_opus", T0 + MIN, T0)
    assert autre.suspension("opus", T0, "A") == T0 + 30 * MIN  # la pause est la plus tardive
    assert autre.suspension("opus", T0) == T0 + 2 * MIN
    assert autre.suspension("sonnet", T0) is None


def test_la_prochaine_echeance_compte_les_pauses():
    places = Places()
    places.pause("A", T0 + 5 * MIN, T0)
    places.surcharge("B", T0)
    assert places.prochaine_echeance(T0) == T0 + 2 * MIN
    assert places.prochaine_echeance(T0 + 2 * MIN) == T0 + 5 * MIN
    assert places.prochaine_echeance(T0 + 5 * MIN) is None


def test_l_etat_dit_les_pauses_et_les_oublie_a_leur_fin():
    places = Places()
    lancer(places, "AB")
    places.pause("A", T0 + MIN, T0)
    etat = places.etat(T0)
    assert etat["pauses"] == {"A": T0 + MIN} and etat["en_ecriture"] == 1
    attendu = "Une tâche patiente après une panne de son agent : elle repart à "
    assert etat["phrase"].endswith(f"{attendu}{heure_dite(T0 + MIN)}.")
    places.pause("B", T0 + 5 * MIN, T0)
    assert places.etat(T0)["phrase"].endswith(
        "2 tâches patientent après une panne de leur agent : la première repart à "
        f"{heure_dite(T0 + MIN)}."
    )
    assert places.etat(T0 + 2 * MIN)["pauses"] == {"B": T0 + 5 * MIN}
    fin = places.etat(T0 + 5 * MIN)
    assert "pauses" not in fin and "panne" not in fin["phrase"]


def test_une_connexion_perdue_suspend_tous_les_modeles_cinq_minutes():
    places = Places()
    lancer(places, "AB")
    issue = places.connexion("A", T0)
    assert (issue["portee"], issue["reprise"]) == ("connexion", T0 + 5 * MIN)
    assert issue["nouvelle"] and issue["premiere"] and module.PAUSE_CONNEXION_S == 5 * MIN
    assert places.en_ecriture() == 1  # l'ouvrier sans connexion rend sa place, B continue
    for modele in ("sonnet", "opus", "haiku", "fable", ""):
        assert places.suspension(modele, T0 + 5 * MIN - 1) == T0 + 5 * MIN
        assert not places.peut_partir(modele, T0 + 5 * MIN - 1)
    assert places.peut_partir("sonnet", T0 + 5 * MIN)
    etat = places.etat(T0)
    assert etat["suspensions"] == {"connexion": T0 + 5 * MIN} and etat["reprise"] is None
    assert etat["phrase"].endswith(
        "La connexion à Claude est perdue : plus aucun lancement, un nouvel essai part à "
        f"{heure_dite(T0 + 5 * MIN)}."
    )


def test_une_connexion_perdue_n_est_premiere_qu_une_fois_jusqu_a_ce_qu_elle_revienne():
    places = Places()
    assert places.connexion_retablie() is False
    assert places.connexion("A", T0)["premiere"]
    deuxieme = places.connexion("B", T0 + MIN)  # une autre tâche, pendant la pause
    assert not deuxieme["premiere"] and deuxieme["reprise"] == T0 + 6 * MIN
    troisieme = places.connexion("A", T0 + 6 * MIN)  # le nouvel essai échoue encore
    assert not troisieme["premiere"] and troisieme["nouvelle"]
    assert troisieme["reprise"] == T0 + 11 * MIN
    assert places.connexion_retablie() is True and places.connexion_retablie() is False
    assert places.connexion("A", T0 + 20 * MIN)["premiere"]  # perdue de nouveau : à redire


def test_un_verificateur_sans_connexion_reprend_la_tete_de_la_file():
    places = Places(paralleles=6, agents_max=1)
    lancer(places, "A")
    assert places.en_verification("A", "opus", T0)
    places.connexion("A", T0)
    assert places.agents_en_marche() == 0 and places._attente == ["A"]
    assert places.servir(T0 + 5 * MIN - 1) == []
    assert places.servir(T0 + 5 * MIN) == ["A"]


GESTES_AVEC_PANNES = (
    lambda p, h, nom, modele, heure: p.partir(nom, modele, heure),
    lambda p, h, nom, modele, heure: p.en_verification(nom, modele, heure),
    lambda p, h, nom, modele, heure: p.finir(nom, heure),
    lambda p, h, nom, modele, heure: p.rendre_jeton(nom, heure),
    lambda p, h, nom, modele, heure: p.servir(heure),
    lambda p, h, nom, modele, heure: p.pause(nom, heure + h.choice([0, 1, MIN, 3600]), heure),
    lambda p, h, nom, modele, heure: p.connexion(nom, heure),
    lambda p, h, nom, modele, heure: p.connexion_retablie(),
    lambda p, h, nom, modele, heure: p.refus(nom, h.choice(["five_hour", None]), None, heure),
    lambda p, h, nom, modele, heure: p.peut_partir(modele, heure, nom),
)


def verifier_les_pauses(places, hasard, taches, modeles, heure) -> None:
    """Une tâche en pause ne tient ni place ni jeton, ne peut pas partir, et l'état la dit."""
    en_pause = {t: places.en_pause(t, heure) for t in taches}
    en_pause = {t: fin for t, fin in en_pause.items() if fin is not None}
    assert places.etat(heure).get("pauses", {}) == en_pause
    for nom, fin in en_pause.items():
        suivie = places._taches.get(nom)
        assert suivie is None or not (suivie.ecrit or suivie.jeton)
        assert not places.peut_partir(hasard.choice(modeles), heure, nom)
        assert places.suspension(hasard.choice(modeles), heure, nom) >= fin
        assert heure < places.prochaine_echeance(heure) <= fin


@pytest.mark.parametrize("graine", range(20))
def test_au_hasard_avec_pannes_une_tache_en_pause_ne_tient_ni_place_ni_jeton(graine):
    hasard = random.Random(graine)
    places = Places(paralleles=hasard.randint(1, 4), agents_max=hasard.randint(1, 5))
    taches, modeles = list("ABCDEFGH"), ["sonnet", "opus", "claude-opus-4-1", ""]
    heure = T0
    for _ in range(400):
        heure += hasard.choice([0, 1, 30, MIN, 5 * MIN])
        nom, modele = hasard.choice(taches), hasard.choice(modeles)
        hasard.choice(GESTES_AVEC_PANNES)(places, hasard, nom, modele, heure)
        etat = places.etat(heure)
        assert 0 <= etat["agents_en_marche"] <= places.agents_max
        assert 0 <= etat["en_ecriture"] <= places.paralleles
        assert not any(places.a_son_jeton(t) for t in places._attente)
        verifier_les_pauses(places, hasard, taches, modeles, heure)


def avancer_avec_pannes(places, hasard, nom, phase, modele, heure, verifs) -> str:
    """Un pas d'un moteur conforme au contrat, pannes et connexion perdue comprises.

    Une fin d'agent peut être une panne (la tâche patiente : « pause_ouvrier »,
    « pause_verificateur ») ou une connexion perdue (comme un refus pour limite). À la fin de sa
    pause, l'ouvrier repart écrire et le vérificateur repasse en vérification. Sans `hasard`
    (relance après les échéances), seules les pauses finies avancent.
    """
    if phase.startswith("pause_"):
        if places.en_pause(nom, heure) is not None:
            return phase
        if phase == "pause_ouvrier":
            return avancer(places, hasard, nom, "reprise", modele, heure)
        verifie = places.en_verification(nom, verifs[nom], heure)
        return "verificateur" if verifie else "attend_jeton"
    if phase in ("ouvrier", "verificateur") and hasard is not None:
        tirage = hasard.random()
        if tirage < 0.12:
            verifs[nom] = hasard.choice(MODELES_VERIFICATEURS)
            places.pause(nom, heure + hasard.choice([0, 1, MIN, 5 * MIN, 3600]), heure)
            return f"pause_{phase}"
        if tirage < 0.18:
            places.connexion(nom, heure)
            return "prete" if phase == "ouvrier" else "attend_jeton"
        if tirage < 0.25:
            places.connexion_retablie()
    return avancer(places, hasard, nom, phase, modele, heure)


def _pause_qui_tient(places, phases) -> str:
    """Une tâche en pause qui tient une place ou un jeton, "" s'il n'y en a pas."""
    for nom, phase in phases.items():
        suivie = places._taches.get(nom)
        if phase.startswith("pause_") and suivie is not None and (suivie.ecrit or suivie.jeton):
            return nom
    return ""


def _relancer_apres_les_pauses(places, phases, modeles, heure, verifs) -> bool:
    """Après les échéances : les pauses finies avancent, puis le moteur réessaie le reste."""
    for nom, phase in phases.items():
        if phase.startswith("pause_"):
            phases[nom] = avancer_avec_pannes(places, None, nom, phase, modeles[nom], heure, verifs)
    if any(p in QUI_AVANCENT for p in phases.values()):
        return True
    return relancer_tout(places, phases, modeles, heure)


def interblocage_avec_pannes(graine: int) -> str:
    """Comme `interblocage`, avec des pannes et des connexions perdues ; une tâche en pause qui
    tient une place ou un jeton compte aussi comme un défaut."""
    hasard = random.Random(graine)
    places = Places(hasard.randint(1, 2), hasard.choice([None, 1, 2, 3]))
    phases = {f"T{i}": "prete" for i in range(hasard.randint(3, 7))}
    modeles = {nom: hasard.choice(MODELES_OUVRIERS) for nom in phases}
    verifs: dict[str, str] = {}
    heure = T0
    for _ in range(160):
        heure += hasard.choice([0, 1, 30, MIN, 5 * MIN])
        places.servir(heure)
        nom = hasard.choice([n for n, p in phases.items() if p != "finie"])
        phases[nom] = avancer_avec_pannes(
            places, hasard, nom, phases[nom], modeles[nom], heure, verifs
        )
        if tient := _pause_qui_tient(places, phases):
            return f"graine {graine} : {tient} en pause tient une place ou un jeton"
        if all(p == "finie" for p in phases.values()):
            return ""
        if not any(p in QUI_AVANCENT for p in phases.values()):
            while (echeance := places.prochaine_echeance(heure)) is not None:
                heure = echeance
            if not _relancer_apres_les_pauses(places, phases, modeles, heure, verifs):
                return f"graine {graine} : {phases}, {places.etat(heure)['phrase']}"
    return ""


def test_au_hasard_avec_pannes_aucune_suite_conforme_ne_finit_en_interblocage():
    debut, graine, trouves = time.monotonic(), 0, []
    while graine < 3000 and time.monotonic() - debut < 5:
        if bloque := interblocage_avec_pannes(graine):
            trouves.append(bloque)
        graine += 1
    assert not trouves, trouves[:3]
    assert graine >= 300
