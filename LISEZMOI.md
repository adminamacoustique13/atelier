# Atelier

Un chef de chantier en code pour des agents Claude. Il lance les agents avec le modèle et l'effort choisis pour chaque tâche, contrôle leur travail, fait passer un vérificateur, monte d'un cran après un échec et s'arrête quand il sort du contrat.

Une seule dépendance : la bibliothèque `claude-agent-sdk` (voir « La dépendance et la connexion » plus bas). Il te faut aussi Python 3.10 ou plus, git, et un compte Claude connecté ou une clé API.

## Les commandes

```
python3 -m atelier demo
```
Ouvre le tableau de bord sur http://127.0.0.1:8765 avec des agents simulés. Rien n'est appelé, rien n'est dépensé.

```
python3 -m atelier planifier "ton objectif" --depot /chemin/du/projet
```
Demande à Claude de découper l'objectif en tâches et prépare le contrat. Appel réel.

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
- `commandes_permises` : les seules commandes qu'un agent a le droit de lancer (chaque entrée permet la commande et tout ce qui la suit : `uv` permet `uv add`, `uv run pytest`…). Sans cette clé, l'atelier permet `uv`, `python3`, `cargo`, `npm` et `npx`, de quoi installer les outils et lancer les tests ; un projet neuf est créé avec cette liste écrite dans son profil.

Tu n'as pas à modifier ce fichier à la main. Quand un chantier demande un outil qui n'est pas permis, ou pour fixer les contrôles, l'orchestrateur propose un réglage : il apparaît au tableau de bord comme une décision (« Accepter ce réglage » ou « Refuser »). Accepté, il prend effet tout de suite, même en plein chantier, et l'atelier l'enregistre dans le profil. Une tâche revenue faute d'outil se relance ensuite avec « Relancer au même niveau », sans monter le dosage.

L'orchestrateur, en conversation, n'a jamais ces commandes : il lit le dépôt et son historique, rien de plus. Seuls les ouvriers et les vérificateurs les lancent, chacun dans sa propre copie du dépôt.
- `dosage` (facultatif) : remplace la table de départ, par exemple `{"mecanique": ["sonnet", "low"]}`.

## Installer l'Atelier sur ton Mac, avec son icône dans le Dock

Sur un PC, le script d'installation ne marche pas : la marche à suivre est dans `LISEZMOI-PC.md`.

Une seule fois, dans le Terminal :

```
git clone https://github.com/adminamacoustique13/atelier.git ~/Atelier-appli
cd ~/Atelier-appli
./outils/installer-mac.sh
```

Le script installe uv au besoin (avec l'installeur officiel, dans ton dossier personnel, par défaut `~/.local/bin` ; il fournit la bonne version de Python), puis la bibliothèque `claude-agent-sdk` par uv, dans le dossier `.venv` de l'Atelier. Rien n'est installé hors de ton dossier personnel, et il ne demande jamais `sudo`. Le fichier `uv.lock`, livré avec l'Atelier, fixe la version exacte de la bibliothèque qui a été testée. Le script te demande dans quel dossier ranger tes projets, puis règle macOS pour que l'Atelier démarre tout seul à chaque ouverture de session, en arrière-plan. Il ouvre enfin le tableau de bord dans Safari. À chaque démarrage, uv remet la bibliothèque à jour si l'Atelier en demande une autre version : après une mise à jour de l'Atelier, tu n'as rien à refaire.

Si la commande `claude` n'est pas installée, le script te prévient sans s'arrêter : l'Atelier n'en a pas besoin pour travailler, elle te sert seulement à te connecter à ton abonnement (lance `claude` une fois dans le Terminal).

Dernière étape : dans cette fenêtre Safari, menu Fichier, puis « Ajouter au Dock ». L'Atelier a alors sa propre icône et sa propre fenêtre.

Pour tout retirer : `./outils/desinstaller-mac.sh` (tes projets ne sont pas touchés). Le script ne supprime pas le dossier `.venv` où uv a rangé la bibliothèque ; pour le retirer toi-même : `rm -rf ~/Atelier-appli/.venv` (ou le `.venv` du dépôt où tu as installé l'Atelier). Le journal se trouve dans `~/Library/Logs/Atelier.log`.

Le tableau de bord n'écoute que ton Mac (127.0.0.1). Le Mac doit rester allumé et éveillé pendant un chantier.

## Mettre l'Atelier à jour

Quand une nouvelle version de l'Atelier est publiée en ligne (la branche `main` du dépôt a avancé), un bouton « Mettre à jour » apparaît dans l'en-tête du tableau de bord, à droite. L'Atelier le vérifie au plus une fois par heure ; sans nouveauté, le bouton n'est pas là. Un premier clic arme le bouton (« Confirmer la mise à jour »), un second lance la mise à jour : l'Atelier récupère le nouveau code dans son propre dossier (un `git pull --ff-only` de `main`), puis s'arrête et se laisse relancer par macOS, qui le redémarre sur le nouveau code. La page attend son retour sans afficher d'erreur. Si tu l'as lancé à la main dans le Terminal (`python3 -m atelier servir`), il ne reviendra pas tout seul : relance-le.

La mise à jour refuse parfois, et une phrase au fil et sous l'en-tête dit pourquoi : un agent travaille dans l'un des projets ouverts (réessaie quand il a fini) ; le dossier de l'Atelier contient des fichiers modifiés à la main ; le dossier n'est pas sur la branche `main` ; ou le dépôt en ligne ne répond pas. Dans tous ces cas rien ne change et l'Atelier continue de tourner. La mise à jour par le Terminal reste possible : dans le dossier de l'Atelier, `git pull`, puis relance-le. En démonstration, le bouton est visible mais simulé : rien n'est téléchargé et rien ne s'arrête. Cette mise à jour n'a pas été essayée sur un vrai Mac.

## La dépendance et la connexion

Les agents passent par `claude-agent-sdk`, la bibliothèque d'Anthropic (licence MIT). Elle embarque son propre Claude Code : l'Atelier ne lance donc pas de commande `claude` à part, et la bibliothèque n'envoie de données qu'à Claude. La connexion par ton abonnement est conservée : si tu es connecté à ton compte Claude sur ce Mac, c'est lui qui est utilisé.

À l'ouverture de chaque projet, l'Atelier écrit dans son fil ce qu'il sait de la facturation, et seulement cela. Il le fait en deux temps, et n'écrit une phrase que si elle a changé depuis la dernière du même genre : un simple redémarrage n'ajoute rien.

1. **À l'ouverture**, avant tout travail, il ne peut dire qu'une chose : une variable `ANTHROPIC_API_KEY` est-elle présente dans son environnement, ou non. Sans variable, il ne dit pas « abonnement » : une clé peut aussi venir d'un réglage de Claude Code ou d'une connexion faite avec une clé. Avec une variable, il prévient que c'est cette clé API qui sera facturée, et non ton abonnement. Il ne lit jamais sa valeur, seulement sa présence.
2. **Dès que le premier agent a commencé**, la bibliothèque dit d'où vient la connexion, et l'Atelier le répète dans le fil :
   - **abonnement** : aucune clé API n'est utilisée. Cela ne prouve pas que tu es connecté à ton compte (ou que tu passes par une passerelle d'entreprise) : le fil t'invite à le vérifier avec `claude` puis `/status` dans le Terminal ;
   - **clé API** : le travail est facturé à cette clé. Si aucune variable n'était visible, le fil le dit en clair (la clé vient d'un réglage de Claude Code ou d'une connexion faite avec une clé) et explique comment vérifier (`claude`, puis `/status`) et revenir à l'abonnement (`/login`, ou le retrait du réglage en cause) ;
   - **abonnement alors qu'une variable est présente** : le fil rapporte ce que dit la bibliothèque, sans conclure davantage, et te renvoie à `/status`.

En démonstration, le fil dit que les agents sont simulés et que rien n'est facturé.

### Retirer une variable `ANTHROPIC_API_KEY` oubliée

Lancé par l'agent de lancement (le cas normal après l'installation), l'Atelier n'hérite pas du shell de ton Terminal : une variable écrite dans `~/.zshrc` ou `~/.zprofile` ne l'atteint pas, et la retirer de ces fichiers ne change rien pour lui. Elle ne lui arrive que de deux façons.

- **Par `launchctl setenv`** (réglage de ta session macOS, pour tous les programmes lancés ensuite). Pour voir si elle est posée, sans afficher sa valeur : `[ -n "$(launchctl getenv ANTHROPIC_API_KEY)" ] && echo posée || echo absente`. Pour la retirer : `launchctl unsetenv ANTHROPIC_API_KEY`. Une variable posée par `launchctl setenv` ne survit pas à un redémarrage du Mac : si elle revient, c'est qu'une autre source la repose.
- **Par le Terminal, si tu lances l'Atelier à la main** (`python3 -m atelier servir`) : il hérite alors du Terminal. Pour voir : `[ -n "$ANTHROPIC_API_KEY" ] && echo posée || echo absente`. Pour la retirer : `unset ANTHROPIC_API_KEY`, et retire aussi sa ligne `export` de `~/.zshrc` pour qu'elle ne revienne pas.

Dans les deux cas, il faut ensuite relancer l'Atelier. Sous l'agent de lancement, dans le Terminal : `launchctl kickstart -k gui/$(id -u)/fr.atelier.serveur` (relancer `./outils/installer-mac.sh` fait la même chose). À la main : arrête-le avec Ctrl-C et relance la commande.

La clé peut aussi venir d'un réglage de Claude Code (un bloc `env` ou un `apiKeyHelper` dans `~/.claude/settings.json`) ou d'une connexion faite avec une clé : l'Atelier ne le voit alors pas dans son environnement, et c'est le fil qui le signale une fois le premier agent commencé. Regarde alors `claude` puis `/status`. Si tu t'étais connecté avec une clé, tape `/login` et choisis ton compte. Si la clé vient d'un réglage, retire ce réglage de `~/.claude/settings.json` (le bloc `env` ou la ligne `apiKeyHelper`) : `/login` n'y change rien.

## Les autorisations

Pour que l'Atelier tourne sans toi, les commandes courantes du travail sont permises d'avance, quel que soit le profil du projet :

- **à tous les agents**, orchestrateur compris : des commandes qui lisent sans rien changer (`ls`, `cat`, `head`, `tail`, `wc`, `grep`, `diff`, `tree`, `jq`...), git en lecture, et la recherche sur le web (`WebSearch`) ;
- **aux ouvriers et aux vérificateurs**, en plus : les outils de développement (`python`, `pip`, `pytest`, `ruff`, `mypy`, `black`, `node`, `tsc`, `pnpm`, `yarn`, `make`, `go`, `rustc`, `mkdir`, `touch`), qui s'ajoutent aux commandes permises du profil (`uv`, `python3`, `cargo`, `npm`, `npx` par défaut).

Ce qui reste hors de cette liste, exprès : `sed`, `awk`, `find`, `xargs`, `sort` et `rg`, qui savent lancer une autre commande ; `rm`, `mv`, `cp`, que le mode « Accepter les modifications » laisse déjà passer dans la copie de travail, et seulement là ; `curl`, `wget` et la lecture d'une page web (`WebFetch`), par où des données pourraient sortir. La liste est dans `atelier/agents.py` (`LECTURE_SHELL`, `COMMANDES_DEV`, `WEB_LECTURE`).

Quand un agent veut lancer une commande ou un outil que rien ne permet encore, il s'arrête et une carte d'autorisation apparaît dans le tableau de bord. Elle a trois boutons :

- **Autoriser une fois** : l'agent poursuit, mais la question reviendra la prochaine fois ;
- **Toujours pour ce projet** : l'Atelier retient une règle étroite et l'inscrit dans le profil du projet ;
- **Toujours pendant ce chantier**, à la place du précédent quand aucune règle étroite n'existe : l'Atelier retient une règle plus large, gardée dans l'état du chantier en cours. Elle vaut pour tous les agents du chantier, survit à un redémarrage de l'Atelier et s'efface quand le chantier est archivé (« Nouveau chantier ») ; le profil du projet n'est pas touché. Pour une chaîne de commandes (`pytest -q | sed -e ...`), chaque commande reçoit sa règle, la carte les montre toutes avant ton clic. Il n'y a pas de règle pour un lanceur pur (`bash`, `sh`, `sudo`, `env`, `xargs`, `eval`, `timeout`...), pour une substitution (`$(...)`) ni pour `git` sur son seul premier mot : il ne reste alors que « Autoriser une fois » et « Refuser » ;
- **Refuser**, avec une indication facultative que l'agent lit pour changer de méthode.

Attention à « Toujours pour ce projet » comme à « Toujours pendant ce chantier » : la règle retenue couvre toute commande qui commence de la même façon. Une règle de chantier porte souvent sur le seul premier mot (`Bash(sed:*)`, `Bash(curl:*)`) : elle permet alors tout ce que cette commande sait faire, jusqu'à la fin du chantier. Une règle sur un outil qui exécute du code (`python3 -m`, `npm run`) autorise en pratique n'importe quelle commande, puisque ce que l'outil lance dépend de ce qu'on lui donne ou du code du projet. Réserve ce bouton aux commandes simples, et préfère « Autoriser une fois » dans le doute. Un filtre écarte les lanceurs les plus connus, mais aucune liste ne les connaît tous.

Tu peux aussi écrire des règles à l'avance dans `chantier/profil.json`, avec la clé `autorisations` : une liste de règles Claude Code, ajoutées aux outils permis de chaque agent. Elles ont la même forme que dans `.claude/settings.json`, mais l'Atelier ne garde que les règles simples : un nom d'outil, suivi ou non d'une seule paire de parenthèses au contenu non vide, sans virgule ni parenthèse à l'intérieur. Les autres sont écartées sans prévenir. Exemple gardée : `Bash(npm install:*)`. Exemple écartée : `Bash(git commit -m (test))` (parenthèse dans le contenu).

```json
{
  "autorisations": ["Bash(npm install:*)", "WebFetch(domain:docs.python.org)"]
}
```

La clé `commandes_permises` reste lue comme avant. En lecture seule (l'orchestrateur, les vérificateurs), les règles qui visent des outils d'écriture sont ignorées.

## Le mode des ouvriers

Dans l'onglet Chantier, la carte « Mode des ouvriers » te laisse choisir, en cinq boutons, ce que les ouvriers (les agents qui écrivent le code d'une tâche) font sans te demander. Le bouton en vigueur est en blanc, avec son explication dessous ; pour lire celle d'un autre, passe la souris dessus ou atteins-le à la touche Tab. Un clic envoie le choix : l'Atelier l'inscrit dans `chantier/profil.json` (clé `mode_ouvriers`), l'applique tout de suite aux ouvriers en marche, et affiche la phrase qu'il renvoie. Le bouton en vigueur ne change que lorsque l'Atelier confirme le choix. Si un ouvrier travaille en fait dans un autre mode que celui choisi (Claude Code a refusé le changement, ou l'ouvrier a fini sa répétition), une ligne ambre sous les boutons donne son nom et le mode réellement appliqué.

Un ouvrier a toujours, permis d'avance : la lecture, les modifications de fichiers de sa copie de travail, les commandes courantes décrites plus haut, les commandes permises du profil, et git en lecture. C'est un choix fait pour ne pas multiplier les cartes. Il vaut dans tous les modes : même en « Me demander », un ouvrier modifie les fichiers de sa copie sans carte. Les modes ne portent donc que sur le reste, les commandes surtout.

- **Me demander** : ce qui est permis d'avance passe sans carte, tout le reste demande une carte. Déplacer ou supprimer des fichiers par une commande (`rm`, `mv`) demande donc une carte ; `mkdir` et `touch`, permis d'avance, n'en demandent pas.
- **Accepter les modifications** : le mode par défaut, le comportement d'avant ce menu. Il se distingue du précédent par les fichiers que l'ouvrier crée, range ou supprime par une commande : cela passe sans carte.
- **Répétition** : les modifications de fichiers demandent une carte, mais les commandes permises d'avance par le profil (`python3`, `npm`, `npx`, `uv`...) tournent sans carte et peuvent écrire. Ce n'est donc pas une garantie que rien ne sera modifié. L'ouvrier prépare son plan, puis une dernière carte te demande s'il peut passer à l'exécution ; une fois accordée, il quitte ce mode. Tant que cette carte n'est pas accordée, la tâche ne produit rien, et le vérificateur la refusera.
- **Refuser sans demander** : comme « Me demander », mais ce qui aurait demandé une carte est refusé sans rien te demander, et ces refus n'apparaissent nulle part dans l'activité. L'ouvrier fait avec ce qui lui reste.
- **Laisser un arbitre décider** : un modèle, l'arbitre, approuve ou refuse à ta place ce qui aurait demandé une carte. Ce qui est permis d'avance passe sans lui, sauf les commandes qui exécutent du code (`python3`, `npm`, `uv`...), que Claude Code lui renvoie dans ce mode. Ses refus s'affichent dans l'activité de l'agent, avec la règle qui a joué. Après trois refus de suite ou vingt au total, il se met en pause et les demandes reviennent en cartes. Il n'est pas disponible pour tous les modèles : le fil dit alors quel mode est réellement appliqué.

Ce qui ne change jamais : le vérificateur et l'orchestrateur restent en lecture seule, quel que soit le choix. Le mode qui supprime tout garde-fou de Claude Code (`bypassPermissions`) n'est pas proposé ; s'il est écrit dans le profil, l'Atelier le refuse et travaille en « Accepter les modifications », en le disant dans le fil.

Rien de tout cela n'a été essayé avec un vrai compte : ces modes n'ont tourné que sur des faux clients et sur la démonstration. Le premier essai à faire sur ton Mac est de changer de mode pendant qu'un ouvrier travaille, sur un dépôt sans importance.

## Arrêter un agent

Le bouton « Arrêter » interrompt un agent en cours. Une tâche arrêtée te revient : elle n'a ni seconde chance ni montée en gamme, et tu la reprends avec « Relancer au même niveau ». Tu peux aussi arrêter la réponse de l'orchestrateur en pleine écriture : ce qu'il avait écrit est gardé, et la conversation continue au message suivant.

## Plusieurs projets

Le bouton « Nouveau projet », en haut, crée un projet depuis le tableau de bord : un dossier à son nom, avec son dépôt git et son profil, puis une conversation vide avec l'orchestrateur. La liste à côté du nom permet de passer d'un projet à l'autre ; un chantier lancé continue de tourner quand on regarde un autre projet.

Les nouveaux dossiers sont créés à côté du dépôt servi (dans son dossier parent), ou dans le dossier donné par `--racine`. Au démarrage, l'atelier y retrouve tous les dépôts git et les projets qui ont déjà un chantier.

### Un nouveau chantier dans le même projet

Un projet garde un seul chantier à la fois, avec sa conversation, son contrat et ses tâches, et l'orchestrateur se souvient de tout ce qui s'y est dit. Un redémarrage ou une mise à jour de l'Atelier reprend ce chantier tel quel. Quand il est fini et que tu veux en commencer un autre dans le même projet, ouvre l'onglet Chantier et clique « Nouveau chantier ».

Un petit formulaire te demande le nom du chantier qui se termine ; l'Atelier en propose un, tiré de son objectif. « Archiver et repartir » range alors ce chantier dans les archives du projet, et tu repars d'une page blanche : plus de tâches, un contrat vide, et un orchestrateur qui ne se souvient de rien. Le code du projet n'est pas touché. Le bouton refuse tant qu'un agent travaille ou que l'orchestrateur répond.

### Les chantiers archivés

Ils sont listés en bas de l'onglet Chantier, du plus récent au plus ancien, avec leur nom, leurs dates et leur bilan (« 3 tâches livrées sur 5 »). Un clic ouvre le journal du chantier :

- **Livré** : les tâches qui ont passé le vérificateur, et dont le travail est entré dans le code du projet ;
- **où est le travail livré** : sur ta machine seulement, ou aussi sur le dépôt en ligne si le projet y est relié, ou l'échec du dernier envoi ;
- **Pas terminé** : chaque tâche restée en route, avec son état et pourquoi ;
- **Tes décisions** : les questions que l'Atelier t'a posées, et ta réponse ;
- **les chiffres** : agents lancés, montées en gamme, coût équivalent ;
- **le fil complet** de la conversation, replié.

L'Atelier ne déploie rien : « livré » veut dire vérifié et entré dans le code du projet, pas mis en ligne sur un serveur.

Sur le disque, chaque archive est un dossier daté dans `.atelier/archives/` du projet, avec quatre fichiers : `JOURNAL.md` (le journal, lisible dans n'importe quel éditeur), `CAHIER.md`, `etat.json` (l'état complet) et `journal.json`. Le dossier `.atelier/` reste sur ta machine : il n'entre pas dans git. Le cahier du chantier, lui, est aussi dans l'historique git du projet.

### Reprendre un dépôt existant

La même fenêtre propose « Reprendre un dépôt existant » : on colle l'adresse du dépôt (par exemple `https://github.com/compte/projet`) et l'Atelier le récupère dans le dossier des projets, puis l'ouvre. Rien n'est modifié dans le dépôt lui-même : l'état interne de l'Atelier (`.atelier/`) est exclu de git sur cet ordinateur seulement, et le cahier du chantier (`chantier/CAHIER.md`) sera commité avec la première tâche, comme dans un projet neuf.

Un dépôt privé demande que git soit déjà connecté à GitHub sur l'ordinateur. Le plus simple, une fois pour toutes, dans le Terminal :

```
brew install gh
gh auth login
gh auth setup-git
```

`gh auth login` ouvre GitHub dans le navigateur pour autoriser l'ordinateur ; `gh auth setup-git` dit ensuite à git de passer par cette autorisation, y compris quand l'Atelier tourne en arrière-plan.

Un dépôt déjà présent ailleurs sur le Mac peut aussi être déplacé (ou cloné) dans le dossier des projets : il apparaît dans la liste au prochain démarrage de l'Atelier.

### Relier un projet à GitHub

Le bouton « Relier à un dépôt en ligne », en haut à côté du nom du projet, relie le projet à un dépôt GitHub (ou autre). Crée d'abord le dépôt vide sur GitHub, sans LISEZMOI ni licence, puis colle son adresse : l'Atelier y envoie tout ce qui est déjà enregistré. Ensuite, chaque tâche vérifiée y part toute seule, suivie du cahier du chantier. Le bouton devient « En ligne » ; si un envoi échoue, il passe à « Envoi en échec » avec l'explication, et le travail reste enregistré sur l'ordinateur en attendant.

L'orchestrateur lit l'historique git (journal, branches, adresse du dépôt en ligne) mais ne le modifie jamais : la liaison passe par ce bouton, pas par des commandes à taper.

## L'accueil

L'Atelier s'ouvre sur l'accueil (onglet « Accueil », ou un clic sur « Atelier » en haut à gauche). Il montre tous tes projets, du plus récemment touché au plus ancien, sans en démarrer aucun. Chaque carte dit :

- le nom du chantier en cours, une barre avec une case par tâche (blanche : livrée, bleu acier : en cours, contour clair : revenue vers toi) et où il en est : « Plan à valider », « Agents au travail », « Une question t'attend », « Terminé »… ;
- quand le projet a été touché pour la dernière fois, combien de chantiers passés il a, combien de fichiers sa carte du code compte, et son dépôt en ligne s'il en a un.

Deux boutons par projet :

- **Reprendre le chantier** : le projet s'ouvre là où tu l'as laissé, sur la conversation si le plan n'est pas encore validé, sur le tableau de bord sinon. C'est la même session : l'orchestrateur se souvient de la conversation.
- **Nouveau chantier** : une confirmation s'ouvre dans la carte, avec le nom proposé pour le chantier qui se termine. Il est archivé avec son journal, et le projet repart d'une conversation neuve. Refusé tant qu'un agent travaille ; la carte le dit.

En haut, « Nouveau projet » crée un projet, et « Récupérer un dépôt » (pas dans la démonstration) reprend un dépôt GitHub ou autre.

## Les onglets d'un projet

- **Conversation** : tu écris à l'orchestrateur. C'est une session Claude (modèle le plus capable, effort élevé) que l'atelier garde ouverte d'un message à l'autre et dont il affiche la réponse pendant qu'elle s'écrit. Elle lit le dépôt, elle n'écrit rien. Quand ton objectif est clair, elle rend un découpage, que l'atelier transforme en contrat à valider. Tant que le contrat n'est pas validé, tu peux lui demander de corriger le plan.
- **Chantier** : le tableau de bord, en modules numérotés comme les cadrans d'un appareil : 01 l'orchestrateur et son anneau de tâches vérifiées, 02 ce qui t'attend, 03 l'enveloppe, 04 la salle (un poste par tâche), 05 le dosage, 06 le détail des tâches, 07 le fil.
- **Salle** : le chantier vu d'en haut, en perspective. Chaque poste est une colonne posée dans un anneau au sol : sa hauteur dit l'effort, sa couleur l'état. Une route en S mène de l'orchestrateur à la livraison, étape après étape ; les tâches d'une même étape s'étalent de part et d'autre de la route. Chaque tronçon prend la couleur de l'étape où il mène. Le détail de qui attend qui reste dans le Plan. Ce qui t'attend reste ouvert dans un panneau à droite ; un clic sur l'étiquette d'une tâche l'ouvre dans le Plan.
- **Plan** : le câblage des tâches, de haut en bas. En haut l'orchestrateur, puis une rangée par étape (les tâches qui peuvent partir ensemble, côte à côte), en bas la livraison sur main ; « Toi » est en haut à droite. Un plan trop large pour l'écran se réduit de lui-même. Un fil blanc a été vérifié, un fil bleu acier est en cours, un fil en pointillés est à venir ; une tâche qui t'attend tire un fil ambre jusqu'au nœud « Toi ». Un clic sur une tâche montre ses critères, son périmètre, ses tentatives et, si elle t'attend, sa demande d'autorisation.
- **Code** : la carte du code du projet, décrite plus bas.

### Les couleurs et les courbes

Le tableau de bord n'a que cinq couleurs : noir et bleu nuit pour le fond, gris clair et blanc pour le texte, et l'ambre, réservé à ce qui t'attend (une autorisation, une décision, un contrat à valider). Le blanc dit « vérifié », un bleu acier (le bleu nuit éclairci) dit « en cours » ; un livrable refusé se reconnaît à ses points creux, sans couleur de plus. Les polices (Geist, Geist Mono et Doto, la police en points) sont livrées avec l'Atelier : le tableau marche sans connexion.

Chaque poste de la salle du Chantier porte une courbe en points : une colonne par tranche de 15 secondes, sur les 5 dernières minutes, d'autant plus haute que l'agent a agi pendant ces 15 secondes (un outil lancé compte pour un, du texte écrit pour un par 120 caractères). Tant qu'une demande attend ta réponse, les dernières colonnes passent en ambre, à plat : tu vois depuis combien de temps l'agent est bloqué. Quand la tâche est finie, sa courbe résume toute la marche de son ouvrier. Dans la démonstration, où un agent simulé ne travaille que quelques secondes, une colonne vaut une demi-seconde.

## La carte du code

L'onglet Code montre le code du projet comme un livre à étages. À gauche, l'explorateur : les dossiers et les fichiers, avec dix points pour la taille de chacun. Au milieu, la page de ce que tu as choisi : le projet (étage 0), un dossier, ou un fichier. Le fil d'Ariane et les ronds « Étage » remontent ; la recherche, en haut à droite, trouve un fichier, une fonction ou un mot, et y mène.

- **La page du projet, ou d'un dossier** : un portrait en une ou deux phrases, puis **la chaîne**, de haut en bas, dessinée comme le Plan : en haut ce qui se sert des autres, en bas ce dont les autres se servent. Sur chaque fil, le nom de ce qui passe d'un fichier à l'autre, lu dans le code (par exemple `Moteur` quand `serveur.py` prend `Moteur` dans `moteur.py`). La chaîne part de là où vit le code : tant qu'un seul dossier porte au moins 70 % des lignes de code, elle y descend, et le dit. Seuls les liens directs sont tracés ; un lien qui saute une rangée devient un petit renvoi (« ↓ consignes.py »). Ce dont presque tout le monde se sert est rangé dans **le socle**, en bas. Puis **ce qu'il y a dedans** : chaque dossier et chaque fichier, avec une phrase.
- **La page d'un fichier** : à quoi il sert, puis **où il se place** (au-dessus ceux qui s'en servent, au-dessous les quatre dont il prend le plus, et sur chaque fil ce qui passe), quatre chiffres (combien s'en servent, combien seraient touchés en remontant la chaîne, de combien il se sert, combien de fichiers de tests l'importent), **avant de le modifier** (calculé d'après les liens : qui s'en sert, quels tests l'importent ou qu'aucun ne le fait, s'il dépend d'un fichier qui dépend de lui, s'il est gros, si un agent le modifie ; s'y ajoutent les pièges que Claude a relevés dans le code), et **ses parties**, avec leur numéro de ligne.

Tout cela vaut pour n'importe quel projet : la mise en page, les liens et les noms qui passent sont calculés dans le code, sans Claude. Claude écrit les textes : l'explication de chaque fichier, les pièges, le portrait du projet et une phrase par dossier. Tant qu'il ne l'a pas fait (ou dans la démonstration), le portrait est le premier paragraphe du LISEZMOI, et un dossier est décrit par son plus gros fichier.

**Construire la carte.** Le bouton « Analyser le code » estime d'abord le travail : combien de fichiers, combien d'appels à Claude (Sonnet, effort faible, sur ton abonnement), synthèse comprise. Rien ne part avant « Lancer l'analyse ». Les dépendances et les parties sont lues dans le code lui-même, sans Claude ; seules les explications en français demandent Claude, par lots de huit fichiers, puis un dernier appel écrit le portrait du projet et la phrase de chaque dossier (refait seulement quand une explication a changé). Pendant qu'elles arrivent, chaque fichier montre une explication provisoire tirée de ses commentaires. La carte est gardée dans `.atelier/carte.json`.

**La carte suit le code.** Elle ne repart jamais de zéro : chaque fichier est reconnu à son empreinte git. Quand une nouvelle version arrive sur la branche du projet (une tâche fusionnée par l'Atelier, ou un commit fait ailleurs), un fil de fond la compare à la précédente en quinze secondes au plus, et seuls les fichiers nouveaux ou modifiés sont réexpliqués. Ils portent un rond creux et un badge « Nouveau » ou « Modifié » ; les fichiers supprimés sont listés dans la fiche.

**Ce qui est en train de changer clignote.** Les fichiers qu'un agent modifie dans sa copie de travail clignotent en bleu acier, dans l'explorateur, le plan (le dossier qui les contient aussi) et la vue d'un fichier, et la fiche dit quel agent y travaille. Le point bleu de l'onglet Code s'allume tant qu'un agent travaille.

**Ce qu'un agent écrit apparaît en brouillon.** Avant même la vérification, l'Atelier lit le code de la copie de travail de chaque agent, sans appeler Claude. Un fichier qu'il crée apparaît comme un bloc en pointillés bleus, marqué « Brouillon » ; un lien qu'il ajoute entre deux fichiers apparaît comme une flèche bleue en pointillés qui avance. Si le vérificateur refuse la tâche, ils disparaissent ; s'il l'accepte, ils entrent dans la carte pour de bon. Deux fichiers qui dépendent l'un de l'autre sont, eux, reliés en pointillés blancs.

Dans la démonstration, la carte montre le code de l'Atelier lui-même, expliqué par ses seuls commentaires : aucun appel à Claude. Les explications de Claude n'ont pas encore été essayées pour de vrai.

## Comment une tâche se déroule

1. L'atelier crée une copie de travail du dépôt réservée à la tâche.
2. L'ouvrier travaille dans cette copie, avec son modèle et son effort.
3. L'atelier contrôle le périmètre en lisant git, puis lance les commandes du profil.
4. Un vérificateur, un modèle au-dessus de l'ouvrier, juge le livrable sans pouvoir écrire.
5. Accepté : le travail est enregistré et fusionné. Refusé : il est jeté, et la tâche a une seconde chance, puis monte d'un cran, puis te revient.

## Ce qui est testé et ce qui ne l'est pas

Testé (`python3 -m pytest -q`) : le pont vers `claude-agent-sdk` sur un faux client, les cartes d'autorisation, l'arrêt d'un agent, l'annonce de la source de connexion, la reprise de session, la lecture du plan, la création et le changement de projet, le dosage, l'ordonnancement, les dépendances, les périmètres, la seconde chance, la montée en gamme, le plafond, l'enveloppe, les décisions, et le cycle git complet sur un vrai dépôt.

Pas encore essayé avec de vrais agents : aucune machine du chantier n'était connectée à un compte Claude. Le pont (`atelier/sdk.py`) et les agents (`atelier/agents.py`, classe `AgentClaude`) n'ont tourné que sur des faux clients, jamais sur le vrai Claude Code embarqué : ni les ouvriers, ni les vérificateurs, ni la conversation, ni les cartes d'autorisation, ni l'annonce de la source de connexion. C'est le premier essai à faire sur ton Mac, sur un dépôt sans importance.

## Les fichiers

| Fichier | Rôle |
|---|---|
| `atelier/dosage.py` | Table de départ, échelles, montée d'un cran, choix du vérificateur |
| `atelier/modele.py` | Tâche, contrat, chantier, et leur écriture en fichiers |
| `atelier/carte.py` | La carte du code : relevé des fichiers, dépendances, explications par Claude, suivi des nouvelles versions |
| `atelier/consignes.py` | Les consignes de l'ouvrier, du vérificateur et du découpage |
| `atelier/agents.py` | Les agents : celui qui passe par le pont vers Claude, et le simulateur |
| `atelier/sdk.py` | Le pont vers `claude-agent-sdk` : sessions, autorisations, arrêt |
| `atelier/guichet.py` | Le guichet des autorisations : demandes en attente, règles « toujours » et « pendant ce chantier », phrases des cartes |
| `atelier/controles.py` | Périmètre, commandes du profil, copies de travail et fusion git |
| `atelier/moteur.py` | Le chef de chantier |
| `atelier/projets.py` | Les projets ouverts : création, reprise d'un dépôt existant, liaison à un dépôt en ligne |
| `atelier/mise_a_jour.py` | La mise à jour de l'Atelier lui-même : vérification en ligne et `git pull` |
| `atelier/serveur.py` | Le serveur local du tableau de bord |
| `atelier/tableau/index.html` | Le tableau de bord |
