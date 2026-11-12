"""Les chantiers archivés d'un projet : leur nom, leurs dates et leur journal.

Un chantier archivé vit dans `.atelier/archives/<identifiant>/`, avec quatre fichiers :
`etat.json` (l'état complet), `CAHIER.md` (le cahier), `journal.json` (le journal que lit le
tableau de bord) et `JOURNAL.md` (le même, lisible sans l'Atelier). Une archive d'avant les
journaux, qui n'a que `etat.json`, reçoit un journal reconstruit à la lecture.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from atelier.modele import ETATS_FR, Chantier, ecrire_cahier

NOM_MAX = 80
MOIS = (
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
)  # fmt: skip
AUTEURS = {"toi": "Toi", "orchestrateur": "Orchestrateur", "moteur": "Atelier"}
EFFORTS = {"low": "faible", "medium": "moyen", "high": "élevé", "xhigh": "très élevé", "max": "max"}
IDENTIFIANT = re.compile(r"^\d{4}-\d{2}-\d{2}-\d{6}(-\d+)?$")


def date_fr(iso: str) -> str:
    """« 2026-11-12T09:41 » devient « 12 novembre 2026 à 9 h 41 » ; vide si la date manque."""
    try:
        moment = datetime.fromisoformat(iso)
    except (TypeError, ValueError):
        return ""
    return f"{moment.day} {MOIS[moment.month - 1]} {moment.year} à {moment.hour} h {moment:%M}"


def nettoyer_nom(nom) -> str:
    """Un nom sur une ligne, sans caractère de contrôle, de 80 caractères au plus."""
    if not isinstance(nom, str):
        return ""
    nom = " ".join("".join(c if c.isprintable() else " " for c in nom).split())
    return nom[:NOM_MAX].rstrip()


def nom_propose(chantier: Chantier) -> str:
    """Le nom proposé pour un chantier : son objectif, sinon le premier message, sinon sa date."""
    premier = next((e["texte"] for e in chantier.evenements if e.get("auteur") == "toi"), "")
    for source in (chantier.contrat.objectif, premier):
        nom = nettoyer_nom(source.split("\n")[0] if isinstance(source, str) else "")
        if nom:
            return nom if len(nom) < 70 else nom[:69].rstrip() + "…"
    jour = date_fr(chantier.ouvert_le).split(" à ")[0]
    return f"Chantier du {jour}" if jour else "Chantier sans nom"


def _livree(tache) -> dict:
    derniere = tache.historique[-1] if tache.historique else {}
    modele = str(derniere.get("modele") or tache.modele).capitalize()
    effort = EFFORTS.get(derniere.get("effort") or tache.effort, tache.effort)
    tentative = derniere.get("tentative") or tache.tentatives or 1
    detail = f"Vérifiée à la tentative {tentative}"
    if modele:
        detail += f" ({modele}, effort {effort})" if effort else f" ({modele})"
    return {"id": tache.id, "titre": tache.titre, "detail": detail + "."}


def _raison(chantier: Chantier, tache) -> str:
    if tache.etat == "a_lancer":
        return "Pas commencée."
    if tache.etat == "abandonnee":
        return "Abandonnée par toi."
    question = next(
        (d["question"] for d in reversed(chantier.demandes) if d.get("tache") == tache.id), ""
    )
    if tache.etat == "revenu" and question:
        return question.split(" : ", 1)[-1]
    derniere = tache.historique[-1] if tache.historique else {}
    return str(derniere.get("detail") or ETATS_FR.get(tache.etat, tache.etat))[:300]


def _inachevee(chantier: Chantier, tache) -> dict:
    etat = ETATS_FR.get(tache.etat, tache.etat)
    return {"id": tache.id, "titre": tache.titre, "etat": etat, "raison": _raison(chantier, tache)}


def _en_ligne(mode: str, distant: str, probleme: str, livrees: int) -> str:
    if mode == "démonstration":
        return "Démonstration : rien n'a été livré pour de vrai."
    if not livrees:
        return "Rien n'a été livré : aucune tâche n'a passé le vérificateur."
    base = "Le travail livré est entré dans le code du projet, sur sa branche courante"
    if not distant:
        return base + ", sur ta machine. Aucun dépôt en ligne n'est relié au projet."
    if probleme:
        return f"{base}, mais le dernier envoi vers le dépôt en ligne a échoué : {probleme}"
    return f"{base}, et il a été envoyé sur le dépôt en ligne ({distant})."


def _bilan(livrees: int, total: int) -> str:
    if not total:
        return "Aucune tâche découpée."
    reste = total - livrees
    if livrees == 0:
        phrase = f"Aucune tâche livrée sur {total}"
    else:
        phrase = f"{livrees} tâche{'s' if livrees > 1 else ''} livrée{'s' if livrees > 1 else ''}"
        phrase += f" sur {total}"
    return phrase + (f", {reste} inachevée{'s' if reste > 1 else ''}." if reste else ".")


def journal(chantier: Chantier, ident: str, nom: str, archive_le: str, contexte: dict) -> dict:
    """Le journal d'un chantier : ce qui a été livré, ce qui reste, les décisions, le fil.

    `contexte` peut porter `mode`, `distant` (l'adresse du dépôt en ligne) et `probleme` (le
    dernier problème d'envoi), tels qu'ils étaient au moment de l'archivage.
    """
    livrees = [_livree(t) for t in chantier.taches if t.etat == "verifie"]
    inachevees = [_inachevee(chantier, t) for t in chantier.taches if t.etat != "verifie"]
    cout = f"{chantier.cout_usd:.2f}".replace(".", ",") + " $"
    return {
        "id": ident,
        "nom": nettoyer_nom(nom) or nom_propose(chantier),
        "objectif": chantier.contrat.objectif,
        "ouvert_le": date_fr(chantier.ouvert_le),
        "archive_le": date_fr(archive_le),
        "bilan": _bilan(len(livrees), len(chantier.taches)),
        "chiffres": [
            ["Tâches livrées", f"{len(livrees)} sur {len(chantier.taches)}"],
            ["Agents lancés", str(chantier.agents_lances)],
            ["Montées en gamme", str(chantier.montees)],
            ["Coût équivalent", cout],
        ],
        "en_ligne": _en_ligne(
            contexte.get("mode", ""), contexte.get("distant", ""),
            contexte.get("probleme", ""), len(livrees),
        ),  # fmt: skip
        "livre": livrees,
        "inacheve": inachevees,
        "decisions": [
            {"question": d.get("question", ""), "reponse": d.get("reponse") or "Sans réponse"}
            for d in chantier.demandes
        ],
        "fil": [
            {"heure": e.get("heure", ""), "auteur": AUTEURS.get(e.get("auteur"), "Atelier"),
             "texte": e.get("texte", "")}
            for e in chantier.evenements
        ],  # fmt: skip
    }


def journal_md(j: dict) -> str:
    """Le journal en Markdown, pour le lire sans l'Atelier."""
    lignes = [f"# {j['nom']}", ""]
    if j["ouvert_le"]:
        lignes.append(f"Ouvert le {j['ouvert_le']}.")
    lignes += [f"Archivé le {j['archive_le']}.", "", f"Objectif : {j['objectif'] or 'non fixé'}"]
    lignes += ["", f"**{j['bilan']}**", "", j["en_ligne"], "", "## Livré", ""]
    lignes += [f"- {t['id']} — {t['titre']}. {t['detail']}" for t in j["livre"]] or ["Rien."]
    lignes += ["", "## Pas terminé", ""]
    inacheve = [f"- {t['id']} — {t['titre']} ({t['etat']}) : {t['raison']}" for t in j["inacheve"]]
    lignes += inacheve or ["Rien : tout a été livré."]
    lignes += ["", "## Tes décisions", ""]
    decisions = [f"- {d['question']} → {d['reponse']}" for d in j["decisions"]]
    lignes += decisions or ["Aucune."]
    lignes += ["", "## Les chiffres", ""] + [f"- {nom} : {valeur}" for nom, valeur in j["chiffres"]]
    lignes += ["", "## Le fil complet", ""]
    lignes += [f"- {e['heure']} · {e['auteur']} : {e['texte']}" for e in j["fil"]]
    return "\n".join(lignes) + "\n"


def resume(j: dict) -> dict:
    """Ce que la liste des archives montre d'un journal."""
    return {k: j[k] for k in ("id", "nom", "ouvert_le", "archive_le", "bilan")}


def archiver(depot: Path, chantier: Chantier, nom: str = "", contexte: dict | None = None) -> dict:
    """Range le chantier dans un dossier daté et rend son journal."""
    racine = Path(depot) / ".atelier" / "archives"
    maintenant = datetime.now()
    ident, rang = maintenant.strftime("%Y-%m-%d-%H%M%S"), 1
    while (racine / ident).exists():  # deux archives dans la même seconde
        rang += 1
        ident = f"{maintenant:%Y-%m-%d-%H%M%S}-{rang}"
    dossier = racine / ident
    j = journal(chantier, ident, nom, maintenant.isoformat(timespec="minutes"), contexte or {})
    chantier.sauver(dossier / "etat.json")
    ecrire_cahier(chantier, dossier / "CAHIER.md")
    (dossier / "journal.json").write_text(json.dumps(j, ensure_ascii=False, indent=2), "utf-8")
    (dossier / "JOURNAL.md").write_text(journal_md(j), "utf-8")
    return j


def lire(depot: Path, ident) -> dict | None:
    """Le journal d'une archive, ou None si elle n'existe pas ou ne se lit pas."""
    if not isinstance(ident, str) or not IDENTIFIANT.match(ident):
        return None  # jamais de chemin construit à partir d'un texte quelconque
    dossier = Path(depot) / ".atelier" / "archives" / ident
    try:
        return json.loads((dossier / "journal.json").read_text("utf-8"))
    except (OSError, ValueError):
        pass
    try:  # une archive d'avant les journaux : on le reconstruit sans rien écrire
        chantier = Chantier.charger(dossier / "etat.json")
    except (OSError, ValueError, TypeError, KeyError):
        return None
    archive_le = datetime.strptime(ident[:17], "%Y-%m-%d-%H%M%S").isoformat(timespec="minutes")
    return journal(chantier, ident, "", archive_le, {})


def lister(depot: Path) -> list[dict]:
    """Les archives du projet, de la plus récente à la plus ancienne."""
    racine = Path(depot) / ".atelier" / "archives"
    if not racine.is_dir():
        return []
    noms = sorted((d.name for d in racine.iterdir() if d.is_dir()), reverse=True)
    journaux = (lire(depot, nom) for nom in noms)
    return [resume(j) for j in journaux if j]
