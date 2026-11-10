# Atelier

Un chef de chantier en code pour des agents Claude Code. Il lance les agents avec le modèle et l'effort choisis pour chaque tâche, contrôle leur travail, fait passer un vérificateur, monte d'un cran après un échec et s'arrête quand il sort du contrat.

Aucune dépendance : Python 3.10 ou plus, git, et Claude Code installé et connecté.

## Les commandes

```
python3 -m atelier demo
```
Ouvre le tableau de bord sur http://127.0.0.1:8765 avec des agents simulés. Rien n'est appelé, rien n'est dépensé.

```
python3 -m atelier planifier "ton objectif" --depot /chemin/du/projet
```
Demande à Claude Code de découper l'objectif en tâches et prépare le contrat. Appel réel.

```
python3 -m atelier servir --depot /chemin/du/projet
```
Ouvre le tableau de bord sur le vrai dépôt. Le chantier ne démarre que lorsque tu valides le contrat.

## Le profil du projet

Un fichier `chantier/profil.json` dans chaque dépôt :

```json
{
  "nom": "Mon projet",
  "description": "Ce que fait le projet, en une phrase.",
  "commandes": ["python3 -m pytest -q", "python3 -m ruff check ."],
  "commandes_permises": ["python3 -m pytest", "python3 -m ruff"],
  "regles": ["Chaque fonction publique naît avec ses tests."],
  "paralleles": 3
}
```

- `commandes` : les contrôles automatiques lancés par l'atelier après chaque livrable.
- `commandes_permises` : les seules commandes qu'un agent a le droit de lancer.
- `dosage` (facultatif) : remplace la table de départ, par exemple `{"mecanique": ["sonnet", "low"]}`.

## Les trois onglets

- **Conversation** : tu écris à l'orchestrateur. C'est une session Claude Code (modèle le plus capable, effort élevé) que l'atelier garde ouverte d'un message à l'autre et dont il affiche la réponse pendant qu'elle s'écrit. Elle lit le dépôt, elle n'écrit rien. Quand ton objectif est clair, elle rend un découpage, que l'atelier transforme en contrat à valider. Tant que le contrat n'est pas validé, tu peux lui demander de corriger le plan.
- **Chantier** : le tableau de bord (point d'étape, ce qui t'attend, dosage, enveloppe, tâches, fil).
- **Plan** : le graphe des tâches et de ce qui attend quoi. Un clic sur une tâche montre ses critères, son périmètre et ses tentatives.

## Comment une tâche se déroule

1. L'atelier crée une copie de travail du dépôt réservée à la tâche.
2. L'ouvrier travaille dans cette copie, avec son modèle et son effort.
3. L'atelier contrôle le périmètre en lisant git, puis lance les commandes du profil.
4. Un vérificateur, un modèle au-dessus de l'ouvrier, juge le livrable sans pouvoir écrire.
5. Accepté : le travail est enregistré et fusionné. Refusé : il est jeté, et la tâche a une seconde chance, puis monte d'un cran, puis te revient.

## Ce qui est testé et ce qui ne l'est pas

Testé (28 tests, `python3 -m pytest -q`) : la lecture du flux de Claude Code, la reprise de session, la lecture du plan, le dosage, l'ordonnancement, les dépendances, les périmètres, la seconde chance, la montée en gamme, le plafond, l'enveloppe, les décisions, et le cycle git complet sur un vrai dépôt.

Pas encore essayé avec de vrais agents : l'appel à Claude Code (`atelier/agents.py`, classe `AgentClaude`) est écrit d'après ses options réelles, mais n'a jamais tourné connecté. Même chose pour la session de la conversation (`converser`) : Claude Code accepte la ligne de commande, mais aucune vraie réponse n'a encore été reçue. C'est le premier essai à faire sur ta machine, sur un dépôt sans importance.

## Les fichiers

| Fichier | Rôle |
|---|---|
| `atelier/dosage.py` | Table de départ, échelles, montée d'un cran, choix du vérificateur |
| `atelier/modele.py` | Tâche, contrat, chantier, et leur écriture en fichiers |
| `atelier/consignes.py` | Les consignes de l'ouvrier, du vérificateur et du découpage |
| `atelier/agents.py` | Claude Code en ligne de commande, et le simulateur |
| `atelier/controles.py` | Périmètre, commandes du profil, copies de travail et fusion git |
| `atelier/moteur.py` | Le chef de chantier |
| `atelier/serveur.py` | Le serveur local du tableau de bord |
| `atelier/tableau/index.html` | Le tableau de bord |
