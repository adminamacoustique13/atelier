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

```
python3 -m atelier essai
```
L'essai réel : un petit chantier joué de bout en bout avec de vrais agents, sur un dépôt jetable (voir « L'essai réel » plus bas). Appel réel, quelques minutes, de l'ordre de 0,40 $ en coût équivalent.

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
- `delai_controles_s` (facultatif) : le temps laissé à chacune de ces commandes, en secondes ; 1800 (trente minutes) sans cette clé. Passé ce délai, la commande est arrêtée avec tout ce qu'elle avait lancé, et la tentative compte comme refusée.
- `commandes_permises` : les seules commandes qu'un agent a le droit de lancer (chaque entrée permet la commande et tout ce qui la suit : `uv` permet `uv add`, `uv run pytest`…). Sans cette clé, l'atelier permet `uv`, `python3`, `cargo`, `npm` et `npx`, de quoi installer les outils et lancer les tests ; un projet neuf est créé avec cette liste écrite dans son profil.

Tu n'as pas à modifier ce fichier à la main. Quand un chantier demande un outil qui n'est pas permis, ou pour fixer les contrôles, l'orchestrateur propose un réglage : il apparaît au tableau de bord comme une décision (« Accepter ce réglage » ou « Refuser »). Accepté, il prend effet tout de suite, même en plein chantier, et l'atelier l'enregistre dans le profil. Une tâche revenue faute d'outil se relance ensuite avec « Relancer au même niveau », sans monter le dosage.

L'orchestrateur, en conversation, n'a jamais ces commandes : il lit le dépôt et son historique, rien de plus. Seuls les ouvriers et les vérificateurs les lancent, chacun dans sa propre copie du dépôt.
- `dosage` (facultatif) : remplace la table de départ, par exemple `{"mecanique": ["sonnet", "low"]}`.
- `fichiers_partages` (facultatif) : les fichiers que plusieurs tâches peuvent modifier en même temps, expliqués juste dessous.

### Les fichiers partagés

D'habitude, deux tâches qui peuvent toucher le même fichier ne travaillent jamais en même temps : la seconde attend que la première soit vérifiée et enregistrée. Pour un fichier que toutes les tâches touchent un peu (un journal des décisions, une liste de changements), c'est une file d'attente pour rien. Déclare-le partagé :

```json
"fichiers_partages": [
  {"motif": "DECISIONS.md", "fusion": "union"},
  {"motif": "docs/index.md", "fusion": "git"}
]
```

Un fichier partagé ne retient plus personne : les tâches qui l'ont dans leur périmètre partent ensemble, et l'atelier réunit leurs changements quand chacune entre dans la branche principale.

- `"union"` : les lignes ajoutées des deux côtés sont toutes gardées, sans jamais de conflit. C'est fait pour un fichier où l'on ne fait qu'ajouter des lignes. Une ligne modifiée des deux côtés garderait ses deux versions : les ouvriers ont pour consigne de seulement ajouter.
- `"git"` (la valeur sans `fusion`) : git fusionne comme d'habitude. S'il bute sur un conflit, l'ouvrier reprend la main dans sa session pour le résoudre, une fois par départ, puis son travail repasse les contrôles et le vérificateur. Un livrable où restent des marqueurs de conflit n'entre jamais.

Le motif suit les mêmes règles que les périmètres (`docs/*.md`, par exemple) pour savoir quelles tâches partent ensemble. À la fusion, git le lit à sa façon : un `*` n'y traverse pas les dossiers, et `docs/*` y couvre `docs/a.md` mais pas `docs/a/b.md`, qui n'est alors pas fusionné en union. Une entrée mal écrite est ignorée. La liste est lue à l'ouverture du projet. Rien n'est écrit dans `.git/` ni enregistré dans le dépôt : le réglage de git vit dans `.atelier/`.

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

La clé `commandes_permises` reste lue comme avant. Pour l'orchestrateur, en lecture seule, les règles qui visent des outils d'écriture sont ignorées.

### Refusé d'office

Deux choses sont refusées à tout agent (ouvrier, vérificateur, orchestrateur, et l'agent qui écrit les explications de la carte du code), dans tous les modes, sans carte : ce refus passe avant toute permission, avant une règle « Toujours » retenue par toi et avant le guichet. Les règles sont dans `atelier/agents.py` (fonction `interdits`) ; elles vont à Claude Code dans un fichier de réglages propre à chaque agent, lisible par toi seul et effacé quand l'agent a fini. Le pont vers Claude Code les ajoute de lui-même à toute session, même ouverte sans elles.

- **Les fichiers de secrets** : ni lus ni écrits par les outils de fichiers (`Read`, `Grep`, `Glob`, `Edit`, `Write`), où qu'ils soient sur le disque, et refusés dans une commande qui les nomme (`cat .env`, `git show HEAD:.env`, `curl -d @.env ...`). La liste d'origine : `.env` et `.env.*` ; les clés privées (`*.pem`, `*.key`, `*.p12`, `*.pfx`, `id_rsa*`, `id_ed25519*`, `id_ecdsa*`, `id_dsa*`) ; les fichiers de données `credentials` et `secrets`, sans extension ou en `.json`, `.yml`, `.yaml`, `.toml`, `.ini`, `.env`, `.txt`, `.csv`, `.xml`, `.cfg`, `.conf`, `.properties` ; les fichiers et dossiers cachés `.credentials*` et `.secrets*` ; `.git-credentials`, `.netrc`, `.npmrc`, `.pypirc` ; les dossiers `.ssh`, `.aws`, `.gnupg` ; et sur l'ordinateur `~/.config/gh`, `~/.claude/.credentials.json`. Un fichier de code ou de documentation dont le nom contient ces mots reste ouvert (`CredentialsForm.tsx`, `src/secrets.py`, `docs/secrets.md`). Les quatre modèles `.env.example`, `.env.sample`, `.env.template` et `.env.dist` restent ouverts aux outils de fichiers ; tout autre nom en `.env.` est fermé (`.env.local`, `.env.production`, `.env.examples`, `.env.example.local`...). Une commande, elle, ne peut nommer aucun `.env`, modèles compris : pour lire un modèle, l'agent passe par l'outil de lecture. Une redirection vers un secret (`echo x > .env`) est refusée par la règle d'écriture du fichier.
- **Git pour autre chose que lire** : tout git est refusé, sauf ses lectures. Restent permises d'avance `git status`, `git diff`, `git log`, `git show`, `git ls-files`, `git rev-parse`, `git remote -v`, `git remote get-url` et `git branch` seul ; d'autres lectures ne sont pas refusées mais demandent une carte (`git blame`, `git grep`, `git cat-file`, `git shortlog`, `git describe`, `git merge-base`, `git ls-tree`, `git rev-list`, `git for-each-ref`...). Tout le reste des commandes de git est refusé, extensions connues comprises (`git lfs`, `git svn`, `git subtree`, `git flow`, `git filter-repo`) et toute commande qu'un programme `git-xxx` installé sur l'ordinateur ajoute à git. `git branch` suivi de quoi que ce soit est refusé, même pour lire (`git branch -a`) : la branche courante se lit par `git status` ou `git rev-parse --abbrev-ref HEAD`. `git remote` qui ajoute ou modifie est refusé (`git remote -v set-url ...`). Une lecture qui écrirait un fichier ou lancerait un programme est refusée aussi (`git diff --output=...`, `git grep -O...`, `git help --web`). Toute commande git qui commence par une option est refusée, même pour lire (`git -C dossier status`, `git --no-pager log`) : écris `git log`. Git écrit dans une autre casse (`GIT`, `Git`), par un chemin (`/usr/bin/git`) ou en `git.exe` est refusé en entier. L'Atelier seul enregistre le travail, après vérification.

Pour ajouter tes propres secrets, mets dans `chantier/profil.json` la clé `secrets`, une liste de motifs : un nom (`"base.sqlite"`), une fin de nom (`"*.sqlite"`), un chemin dans le projet (`"config/prod.yaml"`) ou sur l'ordinateur (`"~/Documents/paie/**"`). Ils s'ajoutent à la liste d'origine, qui reste toujours. Une valeur mal formée est ignorée sans erreur : pas une liste, un élément qui n'est pas du texte, un texte vide, ou un motif avec une espace, une virgule, une parenthèse, une lettre accentuée, ou sans lettre ni chiffre (`"**"`).

```json
{
  "secrets": ["*.sqlite", "config/prod.yaml"]
}
```

La limite, à connaître : c'est une barrière sur le texte des commandes et sur les outils de fichiers, pas une isolation. Claude Code compare des règles au texte que l'agent écrit (après avoir retiré lui-même les variables posées devant et les lanceurs comme `env`, `xargs` ou `timeout`), et ne voit pas ce qu'une commande fait vraiment. Passent encore, par exemple : un joker du shell (`cat .en*`, `cat ~/.ss?/config`) ; un programme permis qui lit le fichier lui-même (`python3 -c "print(open('.e'+'nv').read())"`, ou un script du projet qui lit `.env`) ; git lancé par un programme permis (`python3 -c "import subprocess; subprocess.run(['git', 'push'])"`, `make deploy` si le Makefile pousse ; `sh -c "git push"` n'est pas refusé non plus, mais `sh` n'étant pas permis, il demande une carte) ; un alias git déjà posé dans tes réglages ou ceux du dépôt (`git ci` pour `git commit`) ; un nom de secret écrit dans une casse mélangée (`cat .eNv`) ou découpé (`cat .e""nv`) ; un fichier de données au nom moins courant (`credentials_prod.yml`, à ajouter par la clé `secrets`) ; un nom en `.env.` dont le caractère qui suit un début de modèle est une ponctuation rare (`.env.-x`, `.env.(x`). Écrire dans le dossier `.git/` avec un outil de fichiers n'est pas refusé. Sous Windows, les règles `Bash` ne valent pas pour l'outil PowerShell de Claude Code : un agent qui passerait par lui échapperait à ces refus de commandes (les outils de fichiers restent fermés). Pour ne pas gêner le travail ordinaire, un mot seul n'est refusé dans une commande que comme nom de fichier : `grep -rn credentials app/` passe, `ls credentials` non ; à l'inverse, `grep -rn "credentials" app/`, entre guillemets, est refusé. Ne laisse donc pas de vrai secret dans un dossier où travaillent les agents si tu peux l'éviter.

## Le mode des ouvriers

Dans l'onglet Chantier, la carte « Mode des ouvriers » te laisse choisir, en cinq boutons, ce que les ouvriers (les agents qui écrivent le code d'une tâche) font sans te demander. Le bouton en vigueur est en blanc, avec son explication dessous ; pour lire celle d'un autre, passe la souris dessus ou atteins-le à la touche Tab. Un clic envoie le choix : l'Atelier l'inscrit dans `chantier/profil.json` (clé `mode_ouvriers`), l'applique tout de suite aux ouvriers en marche, et affiche la phrase qu'il renvoie. Le bouton en vigueur ne change que lorsque l'Atelier confirme le choix. Si un ouvrier travaille en fait dans un autre mode que celui choisi (Claude Code a refusé le changement, ou l'ouvrier a fini sa répétition), une ligne ambre sous les boutons donne son nom et le mode réellement appliqué.

Un ouvrier a toujours, permis d'avance : la lecture, les modifications de fichiers de sa copie de travail, les commandes courantes décrites plus haut, les commandes permises du profil, et git en lecture. C'est un choix fait pour ne pas multiplier les cartes. Il vaut dans tous les modes : même en « Me demander », un ouvrier modifie les fichiers de sa copie sans carte. Les modes ne portent donc que sur le reste, les commandes surtout.

- **Me demander** : ce qui est permis d'avance passe sans carte, tout le reste demande une carte. Déplacer ou supprimer des fichiers par une commande (`rm`, `mv`) demande donc une carte ; `mkdir` et `touch`, permis d'avance, n'en demandent pas.
- **Accepter les modifications** : le mode par défaut, le comportement d'avant ce menu. Il se distingue du précédent par les fichiers que l'ouvrier crée, range ou supprime par une commande : cela passe sans carte.
- **Répétition** : les modifications de fichiers demandent une carte, mais les commandes permises d'avance par le profil (`python3`, `npm`, `npx`, `uv`...) tournent sans carte et peuvent écrire. Ce n'est donc pas une garantie que rien ne sera modifié. L'ouvrier prépare son plan, puis une dernière carte te demande s'il peut passer à l'exécution ; une fois accordée, il quitte ce mode. Tant que cette carte n'est pas accordée, la tâche ne produit rien, et le vérificateur la refusera.
- **Refuser sans demander** : comme « Me demander », mais ce qui aurait demandé une carte est refusé sans rien te demander, et ces refus n'apparaissent nulle part dans l'activité. L'ouvrier fait avec ce qui lui reste.
- **Laisser un arbitre décider** : un modèle, l'arbitre, approuve ou refuse à ta place ce qui aurait demandé une carte. Ce qui est permis d'avance passe sans lui, sauf les commandes qui exécutent du code (`python3`, `npm`, `uv`...), que Claude Code lui renvoie dans ce mode. Ses refus s'affichent dans l'activité de l'agent, avec la règle qui a joué. Après trois refus de suite ou vingt au total, il se met en pause et les demandes reviennent en cartes. Il n'est pas disponible pour tous les modèles : le fil dit alors quel mode est réellement appliqué.

Ce qui ne change jamais : l'orchestrateur reste en lecture seule, et le vérificateur ne peut rien changer au travail de l'ouvrier (il fait ses essais dans une copie jetable, voir « Comment une tâche se déroule »), quel que soit le choix. Le mode qui supprime tout garde-fou de Claude Code (`bypassPermissions`) n'est pas proposé ; s'il est écrit dans le profil, l'Atelier le refuse et travaille en « Accepter les modifications », en le disant dans le fil.

Rien de tout cela n'a été essayé avec un vrai compte : ces modes n'ont tourné que sur des faux clients et sur la démonstration. Le premier essai à faire sur ton Mac est de changer de mode pendant qu'un ouvrier travaille, sur un dépôt sans importance.

## Arrêter un agent

Le bouton « Arrêter » interrompt un agent en cours. Une tâche arrêtée te revient : elle n'a ni seconde chance ni montée en gamme, et tu la reprends avec « Relancer au même niveau ». Tu peux aussi arrêter la réponse de l'orchestrateur en pleine écriture : ce qu'il avait écrit est gardé, et la conversation continue au message suivant.

## Après une panne ou un redémarrage

Si l'Atelier s'arrête pendant un chantier (redémarrage du Mac, plantage, mise à jour, arrêt à la main), le chantier repart seul à la réouverture du projet, sans t'attendre. Les tâches qui étaient en cours ou en vérification redeviennent « à lancer » ; leur historique note l'interruption, et la tentative coupée ne compte pas (une tâche arrêtée en vérification, dont l'ouvrier avait rendu son travail, garde son numéro). Le fil annonce combien de tâches repartent et dans combien de secondes, puis l'Atelier attend trente secondes (clé `reprise_apres_arret_s` du profil) avant de les relancer. Ce qui était déjà vérifié est dans git et y reste.

Cette reprise ne part qu'à ces conditions : le contrat du chantier est validé, l'Atelier a pris son port, et il tient le verrou du dépôt. Ce verrou est un verrou de fichier du système, sur `.atelier/verrou`, que le système relâche quand l'Atelier s'arrête, même sur un plantage. Un second Atelier lancé sur le même projet ne l'ouvre pas : il dit en clair qu'un autre Atelier y travaille déjà, ne relance rien et ne touche pas au chantier. En démonstration, rien ne repart seul.

Ne repartent jamais seules : une tâche qui t'était déjà revenue, bloquée ou arrêtée par toi avant l'arrêt de l'Atelier ; une tâche interrompue pour la quatrième fois, qui te revient avec sa décision pour que l'Atelier ne tourne pas en boucle. Pour revenir à l'ancienne règle, où chaque tâche interrompue te revient avec sa décision et où rien ne part sans ta réponse, mets `"reprise_auto": false` dans `chantier/profil.json`. Le bouton « Arrêter » de la page n'est pas encore branché sur le délai de la reprise : l'annulation existe côté serveur (les tâches te reviennent alors sans être reparties), son bouton viendra ensuite.

Une erreur de l'Atelier lui-même pendant une tâche (une commande git qui échoue, un disque plein) fait la même chose pour cette tâche seule : elle te revient avec l'erreur écrite en clair, et les autres tâches continuent.

L'état du chantier (`.atelier/etat.json`) est écrit dans un fichier voisin puis mis à sa place d'un seul geste : un arrêt en pleine écriture laisse l'ancien état lisible. Si ce fichier est malgré tout illisible à l'ouverture, l'Atelier le met de côté sous le nom `.atelier/etat-illisible-<date>.json`, ouvre un chantier vide et le dit dans le fil ; le code, son historique git et les chantiers archivés ne sont pas touchés.

Ce que cela ne couvre pas : un programme Claude resté en marche après un plantage de l'Atelier n'est pas arrêté, et l'Atelier ne se relance pas tout seul après une mise en veille prolongée du Mac.

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

### Où en est un agent

Sous la salle du Chantier, chaque agent en marche a sa ligne : sa tâche, son rôle, et ce qu'il vient de faire, en clair (« Modifie calcul.py », « Lit tests/test_calcul.py », ou la description que Claude Code donne d'une commande, suivie de la commande). Juste dessous :

- **la phase** de la tâche, tenue par l'Atelier, et depuis combien de temps elle dure : « Préparation de sa copie de travail », « L'ouvrier travaille (tentative 2) », « Contrôle du périmètre », « Contrôles automatiques : » suivi des commandes, « Le vérificateur relit », « Enregistrement et fusion » ;
- **l'étape** que l'agent annonce lui-même (« Étape 2/4 · écrire les tests ») : sa consigne lui demande d'écrire une telle ligne avant chaque étape. Le total est son estimation, il peut l'ajuster en route ;
- « **dernière action il y a …** » quand l'agent n'a rien fait depuis plus de 20 secondes (il réfléchit, ou il piétine), et « **t'attend depuis …** », en ambre, quand il attend ta réponse à une carte.

Une tâche active sans agent en marche (l'Atelier prépare sa copie, lance les contrôles ou fusionne) a aussi sa ligne, marquée « atelier ». La phase apparaît encore sous l'état de la tâche dans le détail des tâches (06), et sur son poste dans la salle.

Les agents de Claude Code, lancés par la bibliothèque, n'ont pas d'outil de liste de tâches qu'on pourrait lire : l'étape annoncée est ce qui s'en rapproche le plus.

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
4. Un vérificateur, un modèle au-dessus de l'ouvrier, juge le livrable dans une copie jetable : l'atelier recopie le livrable à côté, le vérificateur y fait ses essais sans te demander (modifier un fichier pour voir si un test échoue, écrire un script d'essai), puis la copie est jetée. Il ne touche jamais la copie de l'ouvrier, et ce qui est enregistré est le travail de l'ouvrier, pas le sien. Les dépendances installées par l'ouvrier (`node_modules`, `.venv`...) sont reliées dans la copie, pas recopiées. Sa consigne lui fait modifier les fichiers avec l'outil d'édition, écrire ses scripts d'essai dans un fichier et lancer une commande simple à la fois : Claude Code demande toujours une autorisation pour une commande enchaînée sur plusieurs lignes, un heredoc, une variable du shell (`$?`) ou une écriture hors de la copie (un dossier dans `/tmp`). S'il s'y prend autrement, une carte peut donc encore apparaître ; l'essai réel (`python3 -m atelier essai`) le signale.
5. Accepté : avant d'entrer dans la branche principale, le travail est rejoué sur elle. Si d'autres tâches y sont entrées depuis le départ de l'ouvrier, l'atelier fusionne la branche principale dans la copie de la tâche et relance les commandes du profil sur ce mélange. Tout passe : le travail entre dans la branche principale, et elle ne contient jamais que du code contrôlé tel quel. Un conflit ou un contrôle rouge : rien n'entre, et la tâche est traitée comme refusée, avec la sortie des contrôles dans les remarques de la tentative suivante.
6. Refusé : le travail n'est pas jeté. Il reste dans la copie de la tâche, et la suite le reprend au lieu de tout refaire.
   - **Le même ouvrier corrige d'abord.** Avec de vrais agents, l'ouvrier reste ouvert après avoir rendu la main : un contrôle rouge lui revient avec sa sortie, jusqu'à trois fois (`retours_controles` au profil), et un manque relevé par le vérificateur une fois (`complements`). Si le même échec revient, ou s'il rend la main sans rien changer dans sa copie, l'atelier n'insiste pas. `"ouvrier_ouvert": false` au profil coupe cela : il reste alors une reprise par essai, dans la session de l'ouvrier.
   - **Le modèle ne monte que si le fond est jugé faux.** Quand le vérificateur dit que l'agent ne sait pas faire, l'essai suivant part un cran plus haut, si le plafond d'escalade du contrat le permet. Un manque, un contrôle rouge ou un fichier touché hors périmètre se corrigent au même niveau. `"montee": "refus"` au profil rétablit l'ancienne règle : une seconde chance, puis un cran de plus après tout refus.
   - **Le même refus deux fois de suite arrête la tâche** : elle te revient avec la cause, pendant que les autres continuent.
   - **À bout de tentatives, elle te revient**, travail gardé. Seule une tâche dont le fond est jugé faux est relancée seule une fois de plus, un cran plus haut.

**La réparation de la branche principale.** Quand toutes les tâches sont vérifiées, l'atelier relance les commandes du profil sur la branche principale, dans une copie propre (sans les fichiers en cours d'édition ni les copies des tâches). Si elles échouent, il ajoute seul une tâche « Réparer les contrôles de la branche principale » (`REPARATION-1`), qui reçoit leur sortie et peut toucher tout le dépôt, sans retirer ni affaiblir de test. Elle suit le même chemin qu'une autre tâche : ouvrier, contrôles, vérificateur. Au plus deux réparations par chantier : si les contrôles restent rouges, le fil le dit et le chantier ne se dit pas terminé.

Ce qui te revient encore : une tâche arrêtée par toi, une consigne que le vérificateur juge mal posée, une tâche au plafond d'escalade après sa relance seule, et les cartes d'autorisation.

## L'essai réel

`python3 -m atelier essai` (ou `uv run python -m atelier essai` dans le dossier de l'Atelier) vérifie, sur la machine où l'Atelier est installé, ce que les tests ne peuvent pas montrer. Il crée un dépôt jetable dans un dossier temporaire (ou celui de `--dossier`), sans toucher à tes projets, puis :

1. vérifie que la bibliothèque se charge, dans la version testée ;
2. écrit un message à l'orchestrateur et attend sa réponse, puis dit ce qui est facturé selon le SDK (abonnement ou clé API) ;
3. lance un chantier de deux tâches, sur Sonnet en effort faible : A (une fonction `moyenne`) doit traverser tout le chantier, ouvrier, contrôles, vérificateur, fusion ; B est arrêtée par le bouton « Arrêter » dès que son ouvrier travaille (`--sans-arret` pour s'en passer) ;
4. accepte une fois chaque carte d'autorisation, et les liste ;
5. vérifie que le vérificateur a fait ses essais sans demander de carte, que le travail de A est dans `main`, sans fichier en trop, qu'il marche, et qu'aucun programme Claude ne reste après la fin.

Chaque étape s'affiche « ok », « ÉCHEC » ou « info », et le tout est écrit dans `ESSAI.md`, dans le dossier de l'essai. La commande sort en erreur si une étape a échoué. Compte trois à cinq minutes.

## Ce qui est testé et ce qui ne l'est pas

Testé (`python3 -m pytest -q`) : le pont vers `claude-agent-sdk` sur un faux client, les cartes d'autorisation, l'arrêt d'un agent, l'annonce de la source de connexion, la reprise de session, la lecture du plan, la création et le changement de projet, le dosage, l'ordonnancement, les dépendances, les périmètres, la seconde chance, la montée en gamme, le plafond, l'enveloppe, les décisions, la relance seule, la réparation de la branche principale, et le cycle git complet sur un vrai dépôt, dont l'intégration contrôlée de deux tâches qui ne passent pas ensemble et un conflit.

Essayé avec de vrais agents le 2026-11-12, sur une machine Linux du cloud (pas encore sur un Mac), par `python3 -m atelier essai` et par un chantier piloté depuis le tableau de bord : la conversation de l'orchestrateur, le plan, les ouvriers, les contrôles, le vérificateur, la fusion, les cartes d'autorisation (« une fois »), l'arrêt d'un ouvrier, l'annonce de la source de connexion (abonnement). Ce premier essai a trouvé deux défauts, corrigés depuis : un réglage d'outils rendu avec le plan était perdu, et les fichiers `__pycache__` créés en lançant les tests faisaient refuser la tâche ou entraient dans `main`.

Pas encore essayé avec de vrais agents : l'installation et le redémarrage sur Mac, le bouton « Mettre à jour », les modes des ouvriers autres que « Accepter les modifications », « Toujours pour ce projet », la reprise après une réponse arrêtée de l'orchestrateur. Sur ton Mac, commence par `python3 -m atelier essai` : il couvre en quelques minutes ce qui a été essayé dans le cloud.

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
| `atelier/essai.py` | L'essai réel de bout en bout, avec de vrais agents (`python3 -m atelier essai`) |
| `atelier/tableau/index.html` | Le tableau de bord |
