# Cahier du chantier « Agent SDK »

État général : contrat validé le 2026-11-11. Sous-plan 1 en cours : A et B sont lancées en parallèle.

## Suivi

Enveloppe : 3 agents lancés sur 18, 0 montée en gamme sur 3. Avec la tâche D3 ajoutée le 2026-11-11, il reste 11 lancements prévus : la marge passe de 6 à 4.

| Tâche | État | Ouvrier | Vérificateur | Tentatives | Preuve |
|---|---|---|---|---|---|
| A | en cours | Opus, effort élevé | Fable, effort élevé | 1 | |
| B | en vérification | Opus, effort élevé | Fable, effort élevé | 1 | 43 tests du guichet verts, contrôle de forme vert, périmètre respecté |
| C | à lancer | Opus, effort élevé | Fable, effort élevé | 0 | |
| D1 | à lancer | Sonnet, effort élevé | Opus, effort élevé | 0 | |
| D2 | à lancer | Sonnet, effort moyen | Opus, effort moyen | 0 | |
| D3 | à lancer | Sonnet, effort élevé | Opus, effort élevé | 0 | |
| E | à lancer | Sonnet, effort moyen | Opus, effort moyen | 0 | |
| F | revient à la personne responsable | | | | |

Point de départ contrôlé le 2026-11-11 : 35 tests verts, contrôle de forme vert.

## Contrats communs, fixés avant le lancement

Ces trois points sont décidés ici pour que les tâches A et B puissent avancer en parallèle sans se marcher dessus.

**1. Le guichet.** Un objet qui reçoit les demandes d'autorisation et rend une décision :

```python
guichet.demander(agent: str, outil: str, entree: dict) -> Reponse
Reponse(choix: "une_fois" | "toujours" | "non", message: str = "", regle: str = "")
```

- L'appel bloque le fil de l'agent jusqu'à la réponse ou jusqu'au délai de l'agent.
- Passé ce délai, la réponse est « non », avec le message : « Pas de réponse de la personne responsable. »
- `regle` est la règle Claude Code à retenir quand le choix est « toujours » (par exemple `Bash(npm install:*)`).

**2. Les événements en direct.** Chaque agent émet des événements simples, sous forme de dictionnaires :

```python
{"agent": "B-ouvrier-1", "type": "texte" | "outil" | "attente" | "fin", "contenu": str}
```

Ils sont relayés par un rappel `sur_evenement(evenement)`, fourni par le serveur.

**3. Les autorisations retenues.** Une nouvelle clé `autorisations` dans `chantier/profil.json` du projet servi : une liste de règles Claude Code, ajoutées aux outils permis de chaque agent.
- « Toujours » ajoute la règle à cette liste.
- Ce sont les mêmes règles que celles qu'on écrirait dans `.claude/settings.json`.
- La clé existante `commandes_permises` reste lue comme avant.

## Précisions fixées au lancement

Vérification faite sur `claude-agent-sdk` 0.2.172 avant de lancer A : `ClaudeSDKClient`, `can_use_tool`, `interrupt`, `effort`, `include_partial_messages` et `apiKeySource` existent tous sous ces noms. Aucune correction de nom n'a été nécessaire.

**4. Qui importe qui.** `atelier/sdk.py` importe `Resultat` et `decrire_outil` depuis `atelier/agents.py`. En retour, `agents.py` (tâche C) importera `atelier.sdk` à l'intérieur de ses méthodes, pas en tête de fichier, pour éviter un import en boucle. La bibliothèque `claude_agent_sdk` n'est importée qu'à l'ouverture d'une session réelle : la démonstration et les tests ne l'appellent jamais.

**5. L'arrêt pendant une attente.** Le guichet offre en plus `annuler(agent)`, qui ferme sur « non » les demandes ouvertes de cet agent, avec le message « Arrêté par la personne responsable. ». Le pont l'appelle dans `arreter()`. Sans cela, une carte d'autorisation resterait affichée pour un agent déjà arrêté.

**6. Les quatre types d'événements.** C'est le pont qui émet aussi « attente » (quand une demande part au guichet) et « fin » (quand l'appel se termine), en plus de « texte » et « outil ».

**7. La conversation suivie.** Le pont accepte un identifiant de session et une reprise (options `session_id` et `resume` du SDK), parce que la conversation de l'orchestrateur se poursuit d'un message à l'autre.

**8. Le texte ajouté au rôle.** Le SDK n'a pas d'option `append_system_prompt` : le texte passe par `system_prompt={"type": "preset", "preset": "claude_code", "append": ...}`.

## Sous-plan 1 — Le socle

### A. Le pont vers l'Agent SDK
- **Pourquoi** : le moteur et le serveur d'Atelier fonctionnent en fils synchrones, alors que le SDK est asynchrone. Il faut un pont unique, testé, pour que le reste du code n'ait pas à le savoir.
- **Critères** :
  1. Un nouveau module `atelier/sdk.py` ouvre une session SDK avec le modèle, l'effort, le dossier de travail, les outils permis et interdits, le mode de permission et le texte ajouté au rôle, et la fait tourner dans son propre fil.
  2. Le texte de l'agent est relayé morceau par morceau par `sur_evenement`, avec le type « texte ».
  3. Chaque outil lancé est relayé par `sur_evenement`, avec le type « outil », sous la forme courte déjà produite par `decrire_outil`.
  4. Une demande d'autorisation du SDK appelle `guichet.demander`. « une_fois » laisse passer l'outil, « toujours » le laisse passer et renvoie la règle au SDK, « non » le refuse avec le message, que l'agent lit.
  5. Une méthode `arreter()` interrompt l'agent. L'appel en cours rend alors un `Resultat` en échec, avec l'erreur « Arrêté par la personne responsable. »
  6. La fin de session rend un `Resultat` avec le texte final, le coût et les tokens, au même format qu'aujourd'hui.
  7. La source de connexion annoncée par le SDK au démarrage (abonnement ou clé API) est lisible depuis le pont.
- **Périmètre** : `atelier/sdk.py`, `tests/test_sdk.py`, `pyproject.toml` (ajout de la dépendance seulement)
- **Contrats** : fournit le pont décrit ci-dessus ; attend le guichet (contrat commun 1), qu'il remplace dans ses tests par un faux guichet.
- **Dépendances** : aucune
- **Preuve** : des tests avec un faux client SDK (aucun appel réel) couvrent chaque critère, dont un test où l'arrêt survient pendant qu'une autorisation est en attente.
- **Départ** : Opus, effort élevé. C'est un contrat entre modules, avec de la concurrence : une erreur ici bloquerait des agents sans bruit.

### B. Le guichet des autorisations
- **Pourquoi** : c'est la pièce qui manque à toutes tes apps. Une demande doit pouvoir attendre ta réponse sans bloquer les autres agents.
- **Critères** :
  1. Un nouveau module `atelier/guichet.py` tient la liste des demandes ouvertes, chacune avec un identifiant, l'agent, l'outil et une phrase en français qui dit ce que l'agent veut faire.
  2. `demander` bloque seulement le fil de l'agent concerné ; deux agents peuvent attendre en même temps.
  3. `repondre(identifiant, choix, message)` débloque la bonne demande et la retire de la liste.
  4. Pour « toujours », la règle proposée est la plus étroite qui couvre la demande : la commande et ses deux premiers mots pour Bash, le nom du domaine pour WebFetch, le nom de l'outil seul sinon.
  5. Au-delà du délai, la demande se ferme sur « non », avec le message du contrat commun 1.
  6. Un guichet simulé, pour la démonstration, répond selon un scénario écrit d'avance.
- **Périmètre** : `atelier/guichet.py`, `tests/test_guichet.py`
- **Contrats** : fournit le guichet (contrat commun 1) ; n'attend rien.
- **Dépendances** : aucune (en parallèle de A, sans fichier en commun)
- **Preuve** : des tests à plusieurs fils, dont deux demandes simultanées répondues dans l'ordre inverse, et un délai dépassé.
- **Départ** : Opus, effort élevé.

## Sous-plan 2 — Le branchement

### C. Les agents passent par le SDK
- **Pourquoi** : c'est le remplacement de `claude -p` lui-même. Le reste du moteur ne doit voir aucune différence.
- **Critères** :
  1. `AgentClaude.executer` et `AgentClaude.converser` passent par le pont de A et rendent des `Resultat` identiques à ceux d'aujourd'hui pour un même scénario.
  2. Les ouvriers et les vérificateurs émettent eux aussi leurs événements en direct (aujourd'hui, seule la conversation le fait).
  3. Les outils permis restent ceux d'aujourd'hui, plus les règles de la clé `autorisations`. Un outil non permis passe par le guichet au lieu d'être refusé d'office.
  4. Le vérificateur et la conversation restent sans aucun outil d'écriture, même si une règle « toujours » le permettrait.
  5. L'agent simulé sait jouer une demande d'autorisation, pour que la démonstration en montre une.
  6. Plus aucun `claude -p` n'est lancé par `agents.py`.
- **Périmètre** : `atelier/agents.py`, `tests/test_agents.py` (nouveau)
- **Contrats** : attend A et B ; fournit à D1 un agent qui accepte `sur_evenement`, un guichet et `arreter(tache)`.
- **Dépendances** : A, B
- **Preuve** : `tests/test_agents.py` (avec le faux client SDK de A) et les 35 tests existants restent verts sans modification.
- **Départ** : Opus, effort élevé.

### D1. Le serveur : autorisations, suivi et arrêt
- **Pourquoi** : relier le guichet et les événements au tableau de bord, et donner un sens clair à « arrêter ».
- **Critères** :
  1. La vue `/api/etat` contient les demandes d'autorisation ouvertes et, pour chaque agent en marche, ses dernières lignes d'activité (au plus 30).
  2. `POST /api/autorisation` avec `id`, `choix` et `message` répond au guichet.
  3. « Toujours » ajoute la règle à la clé `autorisations` du profil et l'enregistre dans `chantier/profil.json`, comme le fait déjà un réglage accepté.
  4. `POST /api/arreter` avec une tâche arrête son agent. La tâche revient à la personne responsable avec le motif « arrêtée par toi », sans seconde chance ni montée en gamme. La décision « Relancer au même niveau » reste proposée.
  5. `POST /api/arreter` sans tâche arrête la réponse en cours de l'orchestrateur, et la conversation reste utilisable ensuite.
  6. En mode démonstration, une demande d'autorisation simulée apparaît et se règle de bout en bout.
- **Périmètre** : `atelier/serveur.py`, `atelier/moteur.py` (l'arrêt seulement), `tests/test_serveur.py` (nouveau)
- **Contrats** : attend C ; fournit à D2 les champs de la vue et les deux routes.
- **Dépendances** : C
- **Preuve** : des tests du serveur en mode simulé, qui appellent les routes et lisent la vue.
- **Départ** : Sonnet, effort élevé. Les tests sont clairs, mais l'arrêt touche au moteur.

### D2. Le tableau de bord : cartes, activité en direct, bouton stop
- **Pourquoi** : c'est ce que tu verras et ce sur quoi tu cliqueras.
- **Critères** :
  1. Une demande ouverte s'affiche comme une carte, dans le fil de la conversation et dans l'onglet Chantier. Elle dit en une phrase qui demande quoi, avec trois choix : « Autoriser une fois », « Toujours pour ce projet », « Refuser ».
  2. « Refuser » ouvre un champ facultatif « Dis-lui plutôt quoi faire », dont le texte part dans `message`.
  3. Dans la salle, chaque poste d'agent montre sa dernière ligne d'activité, et un clic déroule ses 30 dernières lignes.
  4. Chaque agent en marche a un bouton « Arrêter », discret, qui demande une confirmation d'un clic avant d'agir.
  5. L'orchestrateur, pendant qu'il répond, a son bouton « Arrêter » à côté de la zone de saisie.
  6. Le style reste celui du verre fumé déjà en place : mêmes tailles de texte, l'orange pour ce qui attend une décision, rien de surdimensionné.
- **Périmètre** : `atelier/tableau/index.html`
- **Contrats** : attend D1.
- **Dépendances** : D1
- **Preuve** : un essai automatique dans un navigateur sans écran, sur `python3 -m atelier demo`. On y règle une demande simulée et on arrête un agent simulé, captures d'écran à l'appui pour toi.
- **Départ** : Sonnet, effort moyen.

### D3. Le mode des ouvriers — ajoutée le 2026-11-11 par la personne responsable
- **Pourquoi** : choisir depuis le tableau de bord jusqu'où les ouvriers avancent sans te demander, y compris en laissant un arbitre (le mode `auto` de Claude Code) décider à ta place. La tâche touche à la sécurité des agents.
- **Le menu** : « Mode des ouvriers », dans l'onglet Chantier, avec cinq choix :
  - « Me demander » (`default`) ;
  - « Accepter les modifications » (`acceptEdits`) ;
  - « Répétition » (`plan`) ;
  - « Refuser sans demander » (`dontAsk`) ;
  - « Laisser un arbitre décider » (`auto`).
- **Critères** :
  1. Le choix est enregistré dans `chantier/profil.json` et appliqué à chaud aux agents en marche par `set_permission_mode`.
  2. Le vérificateur et l'orchestrateur restent en lecture seule, quel que soit le choix.
  3. Pas de bypass.
  4. En mode auto, chaque action refusée par l'arbitre apparaît dans le fil de l'agent, avec la raison du refus.
  5. Si le mode auto n'est pas disponible pour le modèle d'un agent, ou si le SDK le fait retomber en mode `default`, le fil le dit en une phrase, et le menu indique le mode réellement appliqué.
  6. Quand l'arbitre se met en pause après trop de refus, les demandes repassent par les cartes d'autorisation, sans rien perdre.
- **Périmètre** : `atelier/sdk.py`, `atelier/agents.py`, `atelier/serveur.py`, `atelier/tableau/index.html`, et leurs tests (`tests/test_sdk.py`, `tests/test_agents.py`, `tests/test_serveur.py`). À resserrer au lancement, selon ce que C, D1 et D2 auront livré.
- **Contrats** : attend le pont (A), les agents (C), les routes et la vue (D1), les cartes (D2).
- **Dépendances** : D2
- **Preuve** : des tests du serveur avec un agent simulé, qui changent le mode pendant qu'il tourne et simulent un refus de l'arbitre puis une retombée en `default` ; et l'essai dans le navigateur sans écran.
- **Départ** : Sonnet, effort élevé. La tâche touche à la sécurité des agents.
- **À vérifier avant le lancement** : sur le SDK installé, comment un refus de l'arbitre, sa mise en pause et une retombée en `default` sont annoncés. `set_permission_mode` et les cinq modes existent bien dans la version 0.2.172.

### E. Installation et connexion
- **Pourquoi** : sur ton Mac, Atelier doit installer la bibliothèque tout seul, et te dire clairement s'il facture ton abonnement ou une clé API.
- **Critères** :
  1. `outils/installer-mac.sh` installe la dépendance par uv, sans rien installer hors de ton dossier personnel.
  2. Au démarrage, Atelier affiche dans le fil la source de connexion : « abonnement » ou « clé API ».
  3. Si une variable `ANTHROPIC_API_KEY` est présente, le fil le signale en une phrase : c'est elle qui sera facturée, pas l'abonnement.
  4. Le LISEZMOI explique la nouvelle dépendance, les cartes d'autorisation, la clé `autorisations` et le bouton « Arrêter ».
- **Périmètre** : `outils/installer-mac.sh`, `atelier/__main__.py`, `LISEZMOI.md`
- **Contrats** : attend A (lecture de la source de connexion).
- **Dépendances** : A
- **Preuve** : `bash -n` et `shellcheck` sur le script, et un test du message de démarrage avec les deux sources simulées.
- **Départ** : Sonnet, effort moyen.

### F. Premier essai réel sur ton Mac — revient à la personne responsable
- **Pourquoi** : aucune machine du chantier n'est connectée à ton compte Claude. La seule preuve qu'Atelier marche vraiment, c'est un essai chez toi.
- **Ce que tu feras** (environ 15 minutes, sur un dépôt sans importance) :
  1. mettre Atelier à jour ;
  2. vérifier que le fil annonce « abonnement » ;
  3. demander une petite tâche qui a besoin d'une commande non permise ;
  4. accepter la carte « une fois », puis refuser la suivante avec une indication ;
  5. arrêter un agent en cours.
- **Dépendances** : toutes les tâches précédentes.
