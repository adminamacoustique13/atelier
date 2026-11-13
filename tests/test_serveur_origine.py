"""Le serveur ne répond qu'au tableau de bord : une page d'un autre site ne peut rien lui faire.

Le serveur n'écoute que 127.0.0.1, mais une page web ouverte dans le même navigateur peut lui
envoyer des demandes. Ces tests passent par le vrai serveur HTTP, sur un port libre, et écrivent
les en-têtes à la main (http.client) : rien n'est complété dans leur dos. Chaque refus est vérifié
sur l'état de l'atelier, pas seulement sur le code de la réponse.
"""

import http.client
import json
import threading
import time

import pytest

from atelier.agents import AgentSimule
from atelier.controles import ControlesSimules
from atelier.modele import Chantier, Contrat
from atelier.projets import Projets
from atelier.serveur import Atelier, creer_serveur

TEXTE = "Construis un moteur."
ABSENT = object()  # l'en-tête Host n'est pas envoyé du tout


class Serveur:
    """Le vrai serveur du tableau de bord, sur un port libre, pour un atelier simulé."""

    def __init__(self, depot):
        chantier = Chantier(projet="essai", contrat=Contrat(objectif="Essai"), taches=[])
        self.atelier = Atelier(depot, chantier, AgentSimule(), ControlesSimules(), {})
        projets = Projets(depot, lambda dossier, nom: self.atelier)
        projets.ajouter(self.atelier)
        self.serveur = creer_serveur(projets, 0)
        self.port = self.serveur.server_address[1]
        self.reponses = []  # chaque réponse reçue, pour vérifier les en-têtes de toutes
        threading.Thread(target=self.serveur.serve_forever, args=(0.01,), daemon=True).start()

    def demander(self, methode, chemin, entetes=None, corps=None, hote=None):
        """Envoie une demande aux en-têtes bruts ; rend (code, en-têtes, JSON ou texte)."""
        connexion = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            connexion.putrequest(methode, chemin, skip_host=True, skip_accept_encoding=True)
            hote = f"127.0.0.1:{self.port}" if hote is None else hote
            if hote is not ABSENT:
                connexion.putheader("Host", hote)
            for nom, valeur in (entetes or {}).items():
                connexion.putheader(nom, valeur)
            connexion.endheaders(corps)
            reponse = connexion.getresponse()
            code, brut = reponse.status, reponse.read()
            recus = {nom.lower(): valeur for nom, valeur in reponse.getheaders()}
        finally:
            connexion.close()
        self.reponses.append(recus)
        lu = json.loads(brut) if brut and "json" in recus.get("content-type", "") else brut
        return code, recus, lu

    def poster(self, chemin, donnees, entetes=None, hote=None):
        """Un POST au corps JSON ; le Content-Type est celui du tableau, sauf s'il est donné."""
        corps = json.dumps(donnees).encode("utf-8")
        tous = {"Content-Type": "application/json", **(entetes or {})}
        tous = {nom: valeur for nom, valeur in tous.items() if valeur is not None}
        tous["Content-Length"] = str(len(corps))
        return self.demander("POST", chemin, tous, corps, hote)

    def messages_recus(self):
        """Les messages de la personne responsable arrivés au fil du chantier."""
        evenements = self.atelier.moteur.chantier.evenements
        return [e["texte"] for e in evenements if e["auteur"] == "toi"]

    def fermer(self):
        self.serveur.shutdown()
        self.serveur.server_close()
        fil = self.atelier.fil_message
        if fil is not None:
            fil.join(5)


@pytest.fixture
def serveur(tmp_path):
    ouvert = Serveur(tmp_path)
    yield ouvert
    ouvert.fermer()


def refus_en_francais(code, recus, lu, attendu=403):
    """Le refus porte le code attendu et une phrase française en JSON, sans accord croisé."""
    assert code == attendu
    assert recus["content-type"].startswith("application/json")
    assert isinstance(lu, dict) and set(lu) == {"erreur"}
    phrase = lu["erreur"]
    assert phrase.endswith(".") and phrase[0].isupper() and len(phrase) < 90
    assert not any(ord(c) >= 0x1F000 or 0x2600 <= ord(c) <= 0x27BF for c in phrase)  # smiley
    assert not any(nom.startswith("access-control-") for nom in recus)


def refus_sans_effet(serveur, entetes=None, hote=None):
    """Un message envoyé avec ces en-têtes est refusé par un 403 et n'arrive jamais au fil."""
    refus_en_francais(*serveur.poster("/api/message", {"texte": TEXTE}, entetes, hote))
    time.sleep(0.05)
    assert serveur.messages_recus() == []
    assert not serveur.atelier.occupe


# --- le tableau de bord, lui, passe ------------------------------------------------------------


def test_la_page_l_etat_et_un_message_du_tableau_passent(serveur):
    port = serveur.port
    code, recus, page = serveur.demander("GET", "/")
    assert code == 200 and recus["content-type"].startswith("text/html") and b"<html" in page
    navigateur = {"Sec-Fetch-Site": "same-origin", "Origin": f"http://127.0.0.1:{port}"}
    code, _, etat = serveur.demander("GET", "/api/etat", {"Sec-Fetch-Site": "same-origin"})
    assert code == 200 and "evenements" in etat
    code, _, vue = serveur.poster("/api/message", {"texte": TEXTE}, navigateur)
    assert code == 200 and "evenements" in vue
    assert serveur.messages_recus() == [TEXTE]


def test_le_nom_localhost_passe_quelle_que_soit_sa_casse(serveur):
    port = serveur.port
    assert serveur.demander("GET", "/api/etat", hote=f"LOCALHOST:{port}")[0] == 200
    assert serveur.demander("GET", "/api/etat", hote=f"localhost:{port}")[0] == 200
    origine = {"Origin": f"http://LocalHost:{port}", "Sec-Fetch-Site": "same-origin"}
    code, _, _ = serveur.poster("/api/message", {"texte": TEXTE}, origine, f"LocalHost:{port}")
    assert code == 200 and serveur.messages_recus() == [TEXTE]


def test_une_adresse_tapee_dans_la_barre_du_navigateur_passe(serveur):
    assert serveur.demander("GET", "/", {"Sec-Fetch-Site": "none"})[0] == 200


def test_un_json_avec_son_jeu_de_caracteres_passe(serveur):
    entetes = {"Content-Type": "application/json; charset=utf-8"}
    assert serveur.poster("/api/message", {"texte": TEXTE}, entetes)[0] == 200
    assert serveur.messages_recus() == [TEXTE]


# --- l'en-tête Host : seul le tableau de bord, au bon port ----------------------------------


@pytest.mark.parametrize(
    "hote",
    [
        "127.0.0.1.mechant.example:{port}",
        "mechant.example",
        "mechant.example:{port}",
        "127.0.0.1:{autre}",
        "localhost:{autre}",
        "127.0.0.1",
        "localhost",
        "",
    ],
)
def test_un_host_qui_n_est_pas_le_tableau_est_refuse(serveur, hote):
    hote = hote.format(port=serveur.port, autre=serveur.port + 1)
    refus_en_francais(*serveur.demander("GET", "/api/etat", hote=hote))
    refus_en_francais(*serveur.demander("GET", "/", hote=hote))
    refus_sans_effet(serveur, hote=hote)


def test_un_host_absent_est_refuse(serveur):
    refus_en_francais(*serveur.demander("GET", "/api/etat", hote=ABSENT))
    refus_sans_effet(serveur, hote=ABSENT)


def test_deux_host_dont_un_seul_est_le_tableau_sont_refuses(serveur):
    entetes = {"Host": "mechant.example"}  # s'ajoute au Host du tableau
    refus_en_francais(*serveur.demander("GET", "/api/etat", entetes))
    refus_sans_effet(serveur, entetes)


# --- l'en-tête Origin : seul le tableau de bord, mot pour mot ------------------------------


@pytest.mark.parametrize(
    "origine",
    [
        "null",
        "http://mechant.example",
        "http://127.0.0.1:{autre}",
        "http://localhost:{autre}",
        "https://127.0.0.1:{port}",
        "http://127.0.0.1:{port}/",
        "http://127.0.0.1.mechant.example:{port}",
        "http://127.0.0.1",
        "",
    ],
)
def test_une_origine_qui_n_est_pas_le_tableau_est_refusee(serveur, origine):
    origine = origine.format(port=serveur.port, autre=serveur.port + 1)
    refus_en_francais(*serveur.demander("GET", "/api/etat", {"Origin": origine}))
    refus_sans_effet(serveur, {"Origin": origine})


# --- l'en-tête Sec-Fetch-Site : ni un autre site, ni un site voisin -------------------------


@pytest.mark.parametrize("site", ["cross-site", "same-site", "autre"])
def test_un_navigateur_qui_dit_venir_d_un_autre_site_est_refuse(serveur, site):
    refus_en_francais(*serveur.demander("GET", "/api/etat", {"Sec-Fetch-Site": site}))
    refus_sans_effet(serveur, {"Sec-Fetch-Site": site})


# --- une écriture s'écrit en JSON ------------------------------------------------------------


def test_un_message_en_texte_brut_au_corps_json_ne_change_rien(serveur):
    """Ce qu'un formulaire ou un fetch « simple » d'un autre site peut envoyer sans permission."""
    avant = serveur.demander("GET", "/api/etat")[2]["evenements"]
    entetes = {"Content-Type": "text/plain"}
    refus_en_francais(*serveur.poster("/api/message", {"texte": TEXTE}, entetes), attendu=415)
    time.sleep(0.05)
    assert serveur.messages_recus() == [] and not serveur.atelier.occupe
    assert serveur.demander("GET", "/api/etat")[2]["evenements"] == avant


@pytest.mark.parametrize(
    "nature",
    [
        None,
        "text/plain;charset=utf-8",
        "application/x-www-form-urlencoded",
        "multipart/form-data; boundary=x",
        "application/jsonp",
        "text/json",
        "application/json-patch+json",
    ],
)
def test_une_ecriture_qui_n_est_pas_du_json_est_refusee(serveur, nature):
    reponse = serveur.poster("/api/message", {"texte": TEXTE}, {"Content-Type": nature})
    refus_en_francais(*reponse, attendu=415)
    time.sleep(0.05)
    assert serveur.messages_recus() == []


def test_une_ecriture_sans_corps_ni_type_est_refusee(serveur):
    """Un fetch(…, {method: "POST"}) d'un autre site n'a ni corps ni Content-Type."""
    entetes = {"Content-Length": "0"}
    refus_en_francais(*serveur.demander("POST", "/api/contrat/valider", entetes), attendu=415)
    assert not serveur.atelier.moteur.chantier.contrat.valide


# --- aucun accord donné à un autre site --------------------------------------------------------


def test_une_demande_preliminaire_n_aboutit_pas(serveur):
    port = serveur.port
    for origine in (f"http://127.0.0.1:{port}", "http://mechant.example"):
        entetes = {
            "Origin": origine,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        }
        code, recus, lu = serveur.demander("OPTIONS", "/api/message", entetes)
        assert not 200 <= code < 300
        refus_en_francais(code, recus, lu, attendu=code)


@pytest.mark.parametrize("methode", ["PUT", "DELETE", "PATCH"])
def test_les_autres_sortes_de_demande_sont_refusees_en_francais(serveur, methode):
    code, recus, lu = serveur.demander(methode, "/api/message", {"Content-Length": "0"})
    assert code == 405
    refus_en_francais(code, recus, lu, attendu=405)


@pytest.mark.parametrize("methode", ["TRACE", "HEAD", "BIDULE"])
def test_une_sorte_de_demande_inconnue_n_aboutit_pas(serveur, methode):
    code, recus, lu = serveur.demander(methode, "/api/etat")
    assert code == 501 and recus["content-type"].startswith("application/json")
    assert not any(nom.startswith("access-control-") for nom in recus)
    if methode != "HEAD":  # une réponse à HEAD n'a pas de corps
        refus_en_francais(code, recus, lu, attendu=501)


def test_aucune_reponse_ne_porte_d_accord_croise(serveur):
    port = serveur.port
    serveur.demander("GET", "/")
    serveur.demander("GET", "/api/etat", {"Origin": f"http://127.0.0.1:{port}"})
    serveur.demander("GET", "/api/etat", {"Origin": "http://mechant.example"})
    serveur.poster("/api/message", {"texte": TEXTE})
    serveur.poster("/api/message", {"texte": TEXTE}, {"Content-Type": "text/plain"})
    serveur.demander("OPTIONS", "/api/message", {"Origin": "http://mechant.example"})
    serveur.demander("GET", "/inconnue")
    assert len(serveur.reponses) == 7
    for recus in serveur.reponses:
        assert not any(nom.startswith("access-control-") for nom in recus), recus


# --- un corps illisible reçoit une réponse, pas une connexion coupée ---------------------------


@pytest.mark.parametrize("longueur", ["abc", "-1", "1.5", "0x10", "99999999999999"])
def test_une_longueur_illisible_rend_400_en_francais(serveur, longueur):
    entetes = {"Content-Type": "application/json", "Content-Length": longueur}
    debut = time.monotonic()
    reponse = serveur.demander("POST", "/api/message", entetes, b'{"texte": "x"}')
    refus_en_francais(*reponse, attendu=400)
    assert time.monotonic() - debut < 2  # répondu tout de suite, sans attendre un corps
    assert serveur.messages_recus() == []


def test_un_corps_en_morceaux_est_refuse_sans_etre_pris_pour_un_corps_vide(serveur):
    entetes = {"Content-Type": "application/json", "Transfer-Encoding": "chunked"}
    corps = b"2\r\n{}\r\n0\r\n\r\n"
    reponse = serveur.demander("POST", "/api/contrat/valider", entetes, corps)
    refus_en_francais(*reponse, attendu=400)
    assert not serveur.atelier.moteur.chantier.contrat.valide


@pytest.mark.parametrize("corps", [b"{pas du json", b"[1, 2]", b'"texte"', b"\xff\xfe"])
def test_un_corps_qui_n_est_pas_un_objet_json_rend_400_en_francais(serveur, corps):
    entetes = {"Content-Type": "application/json", "Content-Length": str(len(corps))}
    refus_en_francais(*serveur.demander("POST", "/api/message", entetes, corps), attendu=400)
    assert serveur.messages_recus() == []
