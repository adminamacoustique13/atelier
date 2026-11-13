"""Le rythme des agents : les colonnes de 15 secondes que le tableau de bord dessine en points."""

from atelier.rythme import COLONNES, TRANCHE_S, Rythmes, poste, resumer
from atelier.serveur import Activite


class Horloge:
    def __init__(self, t: float = 1000 * TRANCHE_S):
        self.t = t

    def __call__(self) -> float:
        return self.t


def test_un_outil_compte_pour_un_et_le_texte_par_tranche_de_120_caracteres():
    horloge = Horloge()
    r = Rythmes(horloge)
    r.compter("A-ouvrier-1", "outil", "Lit a.py")
    r.compter("A-ouvrier-1", "texte", "x" * 60)
    r.compter("A-ouvrier-1", "texte", "x" * 60)
    courbe = r.vue()["en_direct"]["A-ouvrier-1"]
    assert (courbe["tache"], courbe["role"]) == ("A", "ouvrier")
    assert len(courbe["colonnes"]) == COLONNES
    assert courbe["colonnes"][-1] == 2.0 and sum(courbe["colonnes"][:-1]) == 0


def test_les_colonnes_avancent_avec_le_temps_et_les_vieilles_sortent():
    horloge = Horloge()
    r = Rythmes(horloge)
    r.compter("B-ouvrier-1", "outil", "Lit")
    horloge.t += 3 * TRANCHE_S
    r.compter("B-ouvrier-1", "outil", "Écrit")
    assert r.vue()["en_direct"]["B-ouvrier-1"]["colonnes"][-4:] == [1.0, 0.0, 0.0, 1.0]
    horloge.t += COLONNES * TRANCHE_S
    assert sum(r.vue()["en_direct"]["B-ouvrier-1"]["colonnes"]) == 0


def test_une_demande_ouverte_compte_ses_colonnes_d_attente_jusqu_a_la_reprise():
    horloge = Horloge()
    r = Rythmes(horloge)
    r.compter("A-ouvrier-1", "attente", "Lance npm install")
    assert r.vue()["en_direct"]["A-ouvrier-1"]["attente"] == 1
    horloge.t += 2.5 * TRANCHE_S
    assert r.vue()["en_direct"]["A-ouvrier-1"]["attente"] == 3
    r.compter("A-ouvrier-1", "texte", "Réponse de la personne responsable : autorisé.")
    assert r.vue()["en_direct"]["A-ouvrier-1"]["attente"] == 0


def test_la_fin_d_un_ouvrier_garde_le_resume_de_toute_sa_marche_pour_sa_tache():
    horloge = Horloge()
    r = Rythmes(horloge)
    for _ in range(40):
        r.compter("C-ouvrier-2", "outil", "Lit")
        horloge.t += TRANCHE_S
    r.compter("C-verificateur-2", "outil", "Lit")
    r.compter("C-ouvrier-2", "fin", "L'agent a terminé.")
    r.compter("C-verificateur-2", "fin", "L'agent a terminé.")
    r.compter("orchestrateur", "outil", "Cherche")
    r.compter("orchestrateur", "fin", "")
    vue = r.vue()
    assert vue["en_direct"] == {}
    assert vue["bilans"] == {"C": [2.0] * COLONNES}  # 40 tranches ramenées à 20 colonnes
    r.oublier_bilans()
    assert r.vue()["bilans"] == {}


def test_resumer_etire_une_marche_courte_et_somme_une_longue():
    assert resumer([], 4) == [0.0] * 4
    assert resumer([1, 3], 4) == [1, 1, 3, 3]
    assert resumer([1, 1, 2, 2, 3, 3], 3) == [2, 4, 6]


def test_l_activite_du_serveur_expose_les_courbes():
    activite = Activite()
    activite.ajouter({"agent": "A-ouvrier-1", "type": "outil", "contenu": "Lit la consigne"})
    rythme = activite.rythme()
    assert rythme["tranche_s"] == TRANCHE_S
    assert rythme["en_direct"]["A-ouvrier-1"]["colonnes"][-1] == 1.0
    activite.ajouter({"agent": "A-ouvrier-1", "type": "fin", "contenu": "fini"})
    assert set(activite.rythme()["bilans"]) == {"A"}
    activite.oublier_bilans()
    assert activite.rythme()["bilans"] == {}


def test_en_demonstration_les_agents_simules_jouent_des_gestes_en_patientant():
    from atelier.agents import GESTES_SIMULES, AgentSimule

    evenements = []
    agent = AgentSimule({}, delai_s=0.4, gestes_s=0.05)
    agent.sur_evenement = evenements.append
    agent.executer("consigne", "sonnet", "medium", None, contexte={"tache": "A", "role": "ouvrier"})
    outils = [e["contenu"] for e in evenements if e["type"] == "outil"]
    gestes = outils[1:]  # après « Lit la consigne »
    assert len(gestes) >= 3 and set(gestes) <= set(GESTES_SIMULES)
    sans = []
    AgentSimule({}, delai_s=0.1, sur_evenement=sans.append).executer(
        "consigne", "sonnet", "medium", None, contexte={"tache": "A", "role": "ouvrier"}
    )
    assert [e["type"] for e in sans] == ["outil", "fin"]  # sans gestes_s : rien de plus qu'avant


def test_poste_coupe_le_nom_en_tache_et_role():
    assert poste("B-ouvrier-1") == ("B", "ouvrier")
    assert poste("B.1-ouvrier-2") == ("B.1", "ouvrier")
    assert poste("REPARATION-1-ouvrier-1") == ("REPARATION-1", "ouvrier")


def test_poste_sans_tache_pour_un_nom_court_ou_vide():
    assert poste("chef-1") == ("", "chef-1")
    assert poste("chef") == ("", "chef")
    assert poste("") == ("", "")
