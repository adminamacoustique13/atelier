# Premier essai réel sur ton Mac (tâche F)

Aucune machine du chantier n'était connectée à un compte Claude. Cet essai est donc la première fois que les agents d'Atelier tournent pour de vrai par l'Agent SDK. Compte une vingtaine de minutes, sur un dépôt sans importance.

La branche contient tout le chantier : le pont vers le SDK, les cartes d'autorisation, l'activité en direct, les boutons « Arrêter », la nouvelle installation, l'annonce de ce qui est facturé, le menu « Mode des ouvriers » et le bouton « Mettre à jour ».

## D'abord : l'essai automatique (cinq minutes)

Depuis le 2026-11-12, une commande joue d'elle-même la plus grande partie de cet essai (connexion, ce qui est facturé, un ouvrier, les contrôles, le vérificateur, la fusion, une carte d'autorisation, l'arrêt d'un agent), sur un dépôt jetable :

```
cd ~/Atelier-appli
uv run python -m atelier essai
```

Elle affiche une ligne par étape (« ok », « ÉCHEC » ou « info ») et écrit son rapport dans `ESSAI.md`, dans le dossier qu'elle indique au départ. Envoie-moi ce rapport. Elle a déjà tourné dans le cloud, sur Linux : tout y est passé. Les sections ci-dessous restent utiles pour ce qu'elle ne couvre pas : l'installation, le redémarrage, le menu des modes, « Toujours pour ce projet », l'arrêt de l'orchestrateur et la mise à jour.

## Avant de commencer

1. Vérifie que tu es connecté à ton abonnement : ouvre le Terminal, lance `claude`, tape `/status`, puis quitte.
2. Choisis un dépôt sans importance, ou prévois d'en créer un neuf depuis le tableau de bord.

## 1. Mettre la nouvelle version sur ton Mac

Le chantier est fusionné dans `main` depuis le 2026-11-11. Dans le Terminal, depuis le dossier où Atelier est installé (par défaut `~/Atelier-appli`) :

```
cd ~/Atelier-appli
git checkout main
git pull --ff-only
./outils/installer-mac.sh
```

Relance bien le script d'installation, et pas seulement `git pull` : c'est lui qui installe la bibliothèque et vérifie qu'elle se charge.

À regarder pendant l'installation :

- le script dit où il a trouvé ou installé `uv`, puis installe la bibliothèque `claude-agent-sdk` ;
- il ne demande aucun mot de passe administrateur ;
- il se termine en ouvrant le tableau de bord.

S'il s'arrête, note la phrase exacte qu'il affiche.

Pour revenir à la version d'avant le chantier, à tout moment :

```
cd ~/Atelier-appli
git checkout 2858544
./outils/installer-mac.sh
```

Et pour revenir ensuite à la version courante : `git checkout main`, puis relance le script.

## 2. Ce qui est facturé

Ouvre ton dépôt d'essai dans le tableau de bord et lis le fil.

- Tu dois y lire : « Aucune variable ANTHROPIC_API_KEY dans l'environnement de l'Atelier. La source réelle de connexion sera dite dès que le premier agent aura commencé. »
- Écris un premier message à l'orchestrateur, par exemple : « Bonjour, dis-moi en deux phrases ce que tu vois dans ce dépôt. »
- Après sa réponse, le fil doit dire : « Le SDK de Claude annonce qu'aucune clé API n'est utilisée : le travail est compté sur ton abonnement Claude. »

Si le fil parle d'une clé API, à l'une ou l'autre étape, arrête-toi là et dis-le-moi : une clé serait facturée à la place de ton abonnement.

## 3. Une carte d'autorisation

Demande une petite tâche qui a besoin d'une commande non permise. Par exemple, comme objectif :

« Télécharge la page https://example.com avec la commande curl et écris son titre dans un fichier titre.txt. »

Valide le contrat proposé, puis regarde l'onglet Chantier.

- Une carte orange doit apparaître, dans le fil et dans l'onglet Chantier. Elle dit quel agent veut lancer quelle commande, et montre la règle que « Toujours pour ce projet » retiendrait.
- Clique « Autoriser une fois ». L'agent doit reprendre son travail.
- À la carte suivante, clique « Refuser », écris une indication dans le champ (par exemple : « N'utilise pas curl, écris simplement Example Domain dans le fichier. »), puis valide. L'agent doit en tenir compte.

Si aucune carte n'apparaît alors que l'agent semble attendre, note ce que montre sa ligne d'activité.

## 4. Arrêter un agent

Pendant qu'un agent travaille :

- clique « Arrêter » sur sa ligne, puis « Confirmer l'arrêt » ;
- la tâche doit te revenir en quelques secondes, avec le motif « arrêtée par toi » et le choix « Relancer au même niveau » ;
- une trentaine de secondes plus tard, vérifie dans le Terminal qu'il ne reste pas de programme Claude orphelin : `ps aux | grep -i claude | grep -v grep`. Compare avec ce que la même commande affichait avant l'essai.

## 5. Arrêter l'orchestrateur

- Écris un message qui appelle une longue réponse, et clique « Arrêter » à côté de la zone de saisie pendant qu'il répond, puis confirme.
- Ce qu'il avait déjà écrit doit rester dans le fil.
- Écris un nouveau message : la conversation doit continuer, et il doit se souvenir de ce qui précède.

## 6. Si tu as encore cinq minutes

- **« Toujours pour ce projet »** sur une commande simple : la règle doit apparaître dans le fil (« Autorisation retenue pour ce projet : ... »), puis dans le fichier `chantier/profil.json` du dépôt d'essai, et la même commande ne doit plus redemander.
- **Un redémarrage** : ferme ta session du Mac et rouvre-la. Atelier doit revenir tout seul, et le fil ne doit pas répéter les phrases de connexion.

## 7. Le mode des ouvriers (dix minutes de plus)

Dans l'onglet Chantier, la carte « Mode des ouvriers » montre cinq choix. Le mode en vigueur est en blanc ; passe la souris sur un autre pour lire son explication.

- **Laisser un arbitre décider.** Choisis-le, puis lance une petite tâche. Regarde si le fil dit que ce mode n'est pas appliqué (il n'existe pas pour tous les modèles). S'il est appliqué, regarde si un refus de l'arbitre apparaît dans l'activité de l'agent, avec le nom de la règle entre parenthèses.
- **Répétition.** Choisis-le et lance une tâche : une modification de fichier doit te présenter une carte, puis une dernière carte doit te demander si l'ouvrier peut passer à l'exécution.
- **Un changement en cours de route.** Pendant qu'un ouvrier travaille, change de mode : le fil doit le dire en une phrase, et l'ouvrier doit continuer.
- Reviens ensuite à « Accepter les modifications », le mode d'avant ce menu.

Ce qui ne doit jamais arriver : l'orchestrateur qui modifie un fichier, ou un vérificateur qui modifie le travail de l'ouvrier (il fait ses essais dans une copie jetable), quel que soit le mode.

## 8. Le bouton « Mettre à jour »

Il n'apparaît dans l'en-tête que si `main` a avancé en ligne par rapport à ton dossier, et au plus une heure après. Tu ne le verras donc qu'après la fusion de la branche du chantier dans `main`, sur un Mac resté sur une version plus ancienne. Le jour où il apparaît :

- clique-le, puis « Confirmer la mise à jour » ;
- la page doit dire qu'Atelier redémarre, puis reprendre toute seule en une dizaine de secondes ;
- s'il refuse, la phrase doit dire pourquoi (un agent travaille, le dossier a été modifié à la main, le dossier n'est pas sur `main`).

## Ce que j'aimerais que tu me rapportes

- Les phrases de connexion telles que le fil les a écrites.
- Si les cartes sont apparues, et si « une fois » puis le refus avec indication ont eu l'effet attendu.
- Le temps que met une tâche à revenir après un arrêt, et s'il est resté un programme Claude.
- Toute phrase qui t'a paru fausse, obscure ou en trop.
- Tout ce qui t'a surpris, même si tu ne sais pas si c'est un défaut.

## Ce que seul ton Mac peut confirmer

Rien de ce qui suit n'a pu être essayé pendant le chantier. Tu n'as pas à tout vérifier : c'est la liste de ce qui reste une hypothèse, pour que tu saches où regarder si quelque chose cloche.

- **La connexion.** Le Claude Code embarqué par la bibliothèque reprend bien ta connexion faite avec `claude` ; ce que le SDK annonce comme source (abonnement ou clé) dans ton cas.
- **L'installation.** `uv sync` installe la version verrouillée de la bibliothèque sur ton Mac ; Atelier redémarre à l'ouverture de session, y compris sans réseau.
- **L'arrêt.** Après « Arrêter », le programme Claude Code de l'agent meurt bien, même s'il avait lancé des tâches de fond ; la conversation reprend après une réponse arrêtée, y compris si c'était la toute première.
- **Les autorisations.** Un outil interdit à l'orchestrateur n'arrive jamais sur une carte ; « Toujours pour ce projet » sur un outil entier est accepté par Claude Code ; tes réglages personnels de `~/.claude` peuvent permettre des outils sans carte, quel que soit le mode.
- **L'arbitre.** La forme exacte de ses refus ; son retour aux cartes après trois refus de suite ; le message quand il n'est pas disponible.
- **La répétition.** Les cartes pour les modifications, la carte de passage à l'exécution, et le mode appliqué ensuite.
- **La mise à jour.** Le délai réel du redémarrage par macOS, et l'installation d'une dépendance nouvelle au redémarrage.
- **Les commandes `launchctl`** du LISEZMOI.

## Deux points d'attention

- Si tes commits git sont signés par une clé qui demande une saisie (une phrase secrète, une clé matérielle), dis-le-moi avant l'essai : Atelier enregistre le travail vérifié par git, sans terminal pour répondre à cette demande, et cela n'a pas pu être essayé.
- Les commandes `launchctl` du LISEZMOI ont été écrites d'après la documentation de macOS, sans avoir pu être essayées : dis-moi si l'une d'elles ne marche pas.
