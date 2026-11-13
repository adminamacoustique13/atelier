"""Compléments du vérificateur : les cas qui manquent à tests/test_serveur_origine.py.

Chaque test tue une mutation qui survivait (voir le verdict). À fondre dans le fichier de l'ouvrier.
"""

import socket
import time

import pytest

from atelier.serveur import ROUTES
from tests.test_serveur_origine import TEXTE, refus_en_francais, refus_sans_effet, serveur  # noqa: F401


def brut(port, octets, attente=5):
    """Envoie des octets tels quels ; rend le code de la réponse."""
    with socket.create_connection(("127.0.0.1", port), timeout=attente) as connexion:
        connexion.sendall(octets)
        recu = b""
        while morceau := connexion.recv(65536):
            recu += morceau
    return int(recu.split(b" ", 2)[1])


@pytest.mark.parametrize(
    "hote",
    [
        "x127.0.0.1:{port}",
        "mechant.localhost:{port}",
        "127.0.0.1:{port}0",
        "localhost:{port}.mechant.example",
        "mechant.example@127.0.0.1:{port}",
        "localhost.:{port}",
    ],
)
def test_un_host_qui_contient_le_bon_nom_sans_l_etre_est_refuse(serveur, hote):  # noqa: F811
    hote = hote.format(port=serveur.port)
    refus_en_francais(*serveur.demander("GET", "/api/etat", hote=hote))
    refus_sans_effet(serveur, hote=hote)


@pytest.mark.parametrize("route", sorted(ROUTES))
def test_chaque_route_d_ecriture_passe_par_les_memes_refus(serveur, route):  # noqa: F811
    refus_en_francais(*serveur.poster(route, {}, hote="mechant.example"))
    refus_en_francais(*serveur.poster(route, {}, {"Origin": "http://mechant.example"}))
    refus_en_francais(*serveur.poster(route, {}, {"Sec-Fetch-Site": "cross-site"}))
    refus_en_francais(*serveur.poster(route, {}, {"Content-Type": "text/plain"}), attendu=415)


@pytest.mark.parametrize("chemin", ["/icone.png", "/polices/geist.woff2", "/manifest.webmanifest"])
def test_les_fichiers_de_la_page_passent_par_les_memes_refus(serveur, chemin):  # noqa: F811
    assert serveur.demander("GET", chemin)[0] == 200
    refus_en_francais(*serveur.demander("GET", chemin, hote="mechant.example"))
    refus_en_francais(*serveur.demander("GET", chemin, {"Origin": "http://mechant.example"}))


def test_deux_origin_sont_refusees_meme_si_l_une_est_le_tableau(serveur):  # noqa: F811
    port = serveur.port
    bonne = f"Origin: http://127.0.0.1:{port}\r\n"
    for paire in (bonne + "Origin: http://mechant.example\r\n", bonne + bonne):
        corps = b'{"texte": "x"}'
        tete = f"POST /api/message HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n{paire}"
        tete += f"Content-Type: application/json\r\nContent-Length: {len(corps)}\r\n\r\n"
        assert brut(port, tete.encode() + corps) == 403
    time.sleep(0.05)
    assert serveur.messages_recus() == []


@pytest.mark.parametrize(
    "nature",
    [
        "text/plain; application/json",
        "text/plain, application/json",
        "application/json, text/plain",
    ],
)
def test_un_type_qui_cite_json_sans_l_etre_est_refuse(serveur, nature):  # noqa: F811
    reponse = serveur.poster("/api/message", {"texte": TEXTE}, {"Content-Type": nature})
    refus_en_francais(*reponse, attendu=415)
    time.sleep(0.05)
    assert serveur.messages_recus() == []


def test_deux_content_type_dont_le_premier_n_est_pas_json_sont_refuses(serveur):  # noqa: F811
    port, corps = serveur.port, b'{"texte": "x"}'
    tete = f"POST /api/message HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nContent-Type: text/plain\r\n"
    tete += f"Content-Type: application/json\r\nContent-Length: {len(corps)}\r\n\r\n"
    assert brut(port, tete.encode() + corps) == 415
    time.sleep(0.05)
    assert serveur.messages_recus() == []


@pytest.mark.parametrize("longueur", [8 * 1024 * 1024 + 1, 9999999999])
def test_une_longueur_au_dela_de_la_borne_est_refusee_sans_attendre(serveur, longueur):  # noqa: F811
    entetes = {"Content-Type": "application/json", "Content-Length": str(longueur)}
    debut = time.monotonic()
    refus_en_francais(*serveur.demander("POST", "/api/message", entetes, b"{}"), attendu=400)
    assert time.monotonic() - debut < 2


def test_un_refus_arrive_entier_meme_apres_un_gros_corps(serveur):  # noqa: F811
    """Le corps refusé est lu : la réponse n'est pas perdue dans une connexion remise à zéro."""
    corps = b"a" * (4 * 1024 * 1024)
    entetes = {"Origin": "http://mechant.example", "Content-Type": "text/plain"}
    entetes["Content-Length"] = str(len(corps))
    refus_en_francais(*serveur.demander("POST", "/api/message", entetes, corps))
