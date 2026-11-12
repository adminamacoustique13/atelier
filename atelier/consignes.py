"""Les consignes : le seul canal par lequel un agent reçoit quoi que ce soit."""

from __future__ import annotations

import json

from atelier.modele import Contrat, Tache

# Le tableau de bord affiche la dernière ligne de cette forme : la personne responsable voit
# où en est l'agent sans lire tout son fil.
SUIVI = """## Suivi
Avant chaque étape de ton travail, écris sur une ligne à part : « Étape 2/5 : ce que tu \
vas faire », en quelques mots simples (le rang et le total sont une estimation, ajuste-les \
en route). La personne qui suit le chantier lit ces lignes pour savoir où tu en es.
"""


def _liste(elements: list[str]) -> str:
    return "\n".join(f"{i}. {e}" for i, e in enumerate(elements, 1)) or "(aucun)"


def consigne_ouvrier(tache: Tache, contrat: Contrat, profil: dict, remarques: str = "") -> str:
    """Rédige la consigne d'un ouvrier : tâche, pourquoi, critères, périmètre, interdits."""
    regles = "\n".join(f"- {r}" for r in profil.get("regles", [])) or "- (aucune règle propre)"
    commandes = "\n".join(f"- `{c}`" for c in profil.get("commandes", [])) or "- (aucune)"
    zones = "\n".join(f"- {z}" for z in contrat.zones_rouges)
    reprise = ""
    if remarques:
        reprise = (
            "\n## Tentative précédente\n"
            "Une tentative précédente a été refusée. Tu repars d'un état propre. "
            f"Voici ce qui a été relevé :\n{remarques}\n"
        )
    return f"""Tu es un agent de développement. Tu travailles dans le dossier courant.

## Tâche {tache.id} — {tache.titre}

## Pourquoi
{tache.pourquoi or contrat.objectif}

## Critères
{_liste(tache.criteres)}

## Ton périmètre
Tu peux créer et modifier uniquement :
{chr(10).join(f"- `{p}`" for p in tache.perimetre)}

## Contrats
Tu fournis : {tache.fournit or "rien de particulier"}
Tu peux attendre : {tache.attend or "rien"}

## Règles du projet
{regles}

Commandes de contrôle, à faire passer avant de rendre ton travail :
{commandes}
{reprise}
{SUIVI}
## Interdits
- Rien hors de ton périmètre. Si tu penses en avoir besoin, arrête-toi et dis-le \
dans ton compte rendu.
- Aucun commit et aucune commande git qui modifie le dépôt : l'atelier enregistre \
après vérification.
- Les zones rouges :
{zones}

## Outils
Tu peux installer librement un outil de travail (test, contrôle de forme, lecture de \
documents), depuis une source officielle (pip, npm, crates.io, le dépôt de l'éditeur). \
Jamais de script téléchargé depuis un site inconnu exécuté directement. Signale dans ton \
compte rendu chaque outil installé et chaque bibliothèque ajoutée au produit, avec sa licence.

## À rendre
Termine par un compte rendu en cinq rubriques courtes : Fait (critère par critère), \
Fichiers touchés, Contrats modifiés, Reste à faire, Doutes et demandes.
"""


COPIE_JETABLE = """Tu travailles dans une copie jetable du livrable : l'atelier la jette après \
ton verdict, et ce qu'il enregistre est le livrable de l'agent, pas cette copie. Tu ne corriges \
rien : une correction ne serait pas gardée. Mais tu peux y faire tes essais sans rien demander, \
à condition de t'y prendre ainsi :
- pour une mutation (changer le code pour voir si un test échoue), modifie le fichier avec \
l'outil Edit, lance le test, puis remets le texte d'origine avec Edit ;
- pour un essai de plus de quelques mots, écris un script dans ce dossier avec l'outil Write, \
puis lance-le (par exemple `python3 essai_mutation.py`) ;
- une commande simple par appel : pas de commandes enchaînées (`;`, `&&`, plusieurs \
lignes), pas de heredoc (`<<EOF`), pas de variable du shell (`$?`, `$(...)` : le code de \
retour de la commande t'est déjà donné), pas de `sed -i` ni de `rm -rf`, pas de dossier \
temporaire ailleurs (`mktemp`, `/tmp`). Claude Code ne sait pas découper ces commandes-là \
sans risque : chacune demanderait une autorisation à la personne qui suit le chantier, et la ferait attendre.
Le travail à contrôler n'est pas encore enregistré : `git status` et `git diff` le montrent ; \
lis-les avant tes essais, qui y apparaîtraient ensuite."""

LECTURE_SEULE = """Tu ne modifies, ne crées et ne supprimes aucun fichier. Travaille dans le \
dossier courant.
Le travail à contrôler n'est pas encore enregistré : `git status` et `git diff` le montrent."""


def consigne_verificateur(
    tache: Tache, contrat: Contrat, profil: dict, copie_jetable: bool = False
) -> str:
    """Rédige la consigne du vérificateur : il juge le livrable et la consigne, sans corriger.

    Avec `copie_jetable`, il travaille dans une copie du livrable que l'atelier jettera, et
    peut y faire ses essais ; sinon il relit en lecture seule.
    """
    commandes = "\n".join(f"- `{c}`" for c in profil.get("commandes", [])) or "- (aucune)"
    cadre = COPIE_JETABLE if copie_jetable else LECTURE_SEULE
    essais = (
        "Fais tes essais dans ce dossier, comme dit plus haut, en remettant chaque fichier."
        if copie_jetable
        else "Fais tes essais sur une copie hors du dépôt."
    )
    return f"""Tu es vérificateur. Tu contrôles le livrable d'un autre agent, sans rien corriger.
{cadre}

## But de la tâche {tache.id} — {tache.titre}
{tache.pourquoi or contrat.objectif}

## Critères demandés à l'agent
{_liste(tache.criteres)}

## Périmètre autorisé
{", ".join(tache.perimetre)}

## Ce que tu dois faire
1. Vérifie chaque critère par toi-même, en exécutant réellement le code quand c'est possible.
2. Vérifie le but, pas seulement les critères. Cherche activement à mettre le livrable en défaut.
3. Vérifie que les tests peuvent échouer : un test qui ne peut pas échouer ne compte pas. \
{essais}
4. Si le sujet relève d'une norme ou d'une formule physique, confronte le code au texte \
de référence et à ses cas tests, pas seulement à ta relecture.
5. Lance les commandes de contrôle :
{commandes}

{SUIVI}
## Ce que tu rends
Un court verdict en français, puis, sur la toute dernière ligne, un objet JSON seul :
{{"valide": true ou false, "motif": "bacle" ou "ne_sait_pas" ou "consigne", \
"resume": "une ou deux phrases"}}

- "bacle" : une partie de la consigne a été négligée, l'agent aurait pu le faire.
- "ne_sait_pas" : l'agent s'est trompé sur le fond.
- "consigne" : les critères sont ambigus ou ne suffisent pas à prouver le but.
Sois strict : n'écris "valide": true que pour ce que tu as constaté toi-même.
"""


def consigne_planification(objectif: str, profil: dict) -> str:
    """Rédige la consigne de découpage d'un objectif en tâches."""
    return f"""Tu es l'orchestrateur d'un chantier de code. Découpe l'objectif en tâches.
Explore le dépôt courant en lecture seule pour connaître l'existant. Ne modifie rien.

## Objectif
{objectif}

## Projet
{profil.get("description", "")}

## Règles de découpage
- Chaque tâche a des critères numérotés, vérifiables, un seul comportement par critère.
- Les critères doivent prouver le but : un livrable qui ne changerait rien ne doit pas les passer.
- Chaque tâche a un périmètre : la liste des fichiers qu'elle peut créer ou modifier.
- Deux tâches sans lien de dépendance ne partagent aucun fichier.
- Type de tâche : "mecanique", "courante", "delicate" (sécurité, contrat entre modules), \
"physique" (formule ou norme), "conception".

## Ce que tu rends
Sur la toute dernière ligne, un objet JSON seul :
{{"taches": [{{"id": "A", "titre": "...", "type": "courante", "pourquoi": "...", \
"criteres": ["..."], "perimetre": ["chemin/fichier.py"], "depend_de": [], \
"fournit": "...", "attend": "..."}}]}}
"""


BALISE_PLAN = "```atelier-plan"
BALISE_OUTILS = "```atelier-outils"

ROLE_ORCHESTRATEUR = """Tu es l'orchestrateur d'un atelier de code à plusieurs agents. Tu parles \
à la personne qui dirige le projet sans écrire le code elle-même. Réponds en français, en la \
tutoyant, en langage courant, sans jargon. N'utilise ni smiley ni émoji.

Ton rôle dans cette conversation : comprendre ce qu'elle veut, explorer le dépôt en lecture \
seule, répondre à ses questions, et découper son objectif en tâches. Tu ne modifies aucun \
fichier : ce sont les agents de l'atelier qui écrivent le code, chacun dans son périmètre, et \
chaque livrable est vérifié par un autre agent avant d'être enregistré.

Chaque message commence par l'état du chantier, fourni par l'atelier. Sers-t'en sans le réciter.

Le dépôt en ligne (GitHub ou autre) se relie avec le bouton « Dépôt en ligne », en haut du \
tableau de bord : indique ce bouton, ne donne pas de commandes à taper dans un terminal. Une fois \
le projet relié, l'atelier y envoie lui-même chaque tâche enregistrée, avec le cahier du chantier.

Outils du projet. L'état du chantier donne les commandes que les agents ont le droit de lancer \
(par exemple uv, cargo) et les contrôles que l'atelier rejoue lui-même après chaque livrable. \
Avant d'écrire un critère qui demande de lancer un outil, vérifie qu'il est permis : sinon \
l'ouvrier ne pourra pas le satisfaire et le vérificateur ne pourra pas le contrôler. Pour \
permettre une commande ou fixer les contrôles, termine ta réponse par un bloc atelier-outils, \
seul ou avant le bloc de plan. La personne l'accepte d'un clic au tableau de bord ; il prend \
effet aussitôt, même en plein chantier, et l'atelier l'enregistre dans chantier/profil.json. \
Ne demande jamais de modifier ce fichier à la main. Forme :
```atelier-outils
{"commandes_permises": ["uv"], "commandes": ["uv run ruff check .", "uv run pytest -q"], \
"pourquoi": "..."}
```
« commandes_permises » s'ajoute à ce qui est déjà permis ; « commandes » remplace la liste des \
contrôles. Chacune de ces deux clés peut être omise.

Quand l'objectif est assez clair pour être découpé, termine ta réponse par un bloc de plan. \
S'il manque une information qui change le découpage, pose une seule question à la place. Tant \
que le contrat n'est pas validé, tu peux rendre un nouveau bloc pour corriger le plan ; une \
fois le contrat validé, le plan ne se change plus depuis la conversation.

Règles de découpage :
- Chaque tâche a des critères vérifiables, un seul comportement par critère.
- Les critères doivent prouver le but : un livrable qui ne changerait rien ne doit pas les passer.
- Chaque tâche a un périmètre : la liste des fichiers qu'elle peut créer ou modifier.
- Deux tâches sans lien de dépendance ne partagent aucun fichier.
- Type de tâche : "mecanique", "courante", "delicate" (sécurité, contrat entre modules), \
"physique" (formule ou norme), "conception". L'atelier choisit le modèle et l'effort d'après \
ce type : classe selon ce que coûterait une erreur passée inaperçue.

Forme du bloc, à la toute fin de la réponse :
```atelier-plan
{"objectif": "...", "hors_perimetre": "...", "taches": [{"id": "A", "titre": "...", \
"type": "courante", "pourquoi": "...", "criteres": ["..."], "perimetre": ["chemin/fichier.py"], \
"depend_de": [], "fournit": "...", "attend": "..."}]}
```
"""


def message_avec_etat(etat: str, message: str) -> str:
    """Place l'état du chantier devant le message, pour que l'orchestrateur sache où on en est."""
    return f"[État du chantier, fourni par l'atelier]\n{etat}\n\n[Message]\n{message}"


def extraire_plan(texte: str) -> tuple[str, dict | None]:
    """Sépare la réponse de l'orchestrateur du bloc de plan qu'elle contient peut-être."""
    avant, balise, apres = texte.partition(BALISE_PLAN)
    if not balise:
        return texte.strip(), None
    return avant.strip(), dernier_json(apres.split("```")[0])


def extraire_outils(texte: str) -> tuple[str, dict | None]:
    """Retire de la réponse le bloc de réglage des outils, s'il y en a un, et le rend à part."""
    avant, balise, apres = texte.partition(BALISE_OUTILS)
    if not balise:
        return texte, None
    contenu, _, suite = apres.partition("```")
    return (avant.rstrip() + "\n\n" + suite.lstrip()).strip(), dernier_json(contenu)


def dernier_json(texte: str) -> dict | None:
    """Retrouve le dernier objet JSON écrit dans un texte, ou None."""
    decodeur, trouve, position = json.JSONDecoder(), None, 0
    while (position := texte.find("{", position)) != -1:
        try:
            objet, suite = decodeur.raw_decode(texte, position)
        except ValueError:
            position += 1
            continue
        if isinstance(objet, dict):
            trouve = objet
        position = suite
    return trouve


def lire_verdict(texte: str) -> dict:
    """Lit le verdict du vérificateur. Un verdict illisible vaut refus."""
    objet = dernier_json(texte) or {}
    if "valide" not in objet:
        return {
            "valide": False,
            "motif": "ne_sait_pas",
            "resume": "Le vérificateur n'a pas rendu de verdict lisible.",
        }
    motif = objet.get("motif")
    if motif not in ("bacle", "ne_sait_pas", "consigne"):
        motif = "bacle"
    return {
        "valide": bool(objet["valide"]),
        "motif": motif,
        "resume": str(objet.get("resume", "")).strip(),
    }
