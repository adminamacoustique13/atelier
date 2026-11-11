# Premier essai réel sur ton Mac (tâche F)

Aucune machine du chantier n'était connectée à un compte Claude. Cet essai est donc la première fois que les agents d'Atelier tournent pour de vrai par l'Agent SDK. Compte une vingtaine de minutes, sur un dépôt sans importance.

Ce que la branche contient à ce stade : le pont vers le SDK, les cartes d'autorisation, l'activité en direct, les boutons « Arrêter », la nouvelle installation et l'annonce de ce qui est facturé. Ce qu'elle ne contient pas encore : le menu « Mode des ouvriers » et le bouton « Mettre à jour ».

## Avant de commencer

1. Vérifie que tu es connecté à ton abonnement : ouvre le Terminal, lance `claude`, tape `/status`, puis quitte.
2. Choisis un dépôt sans importance, ou prévois d'en créer un neuf depuis le tableau de bord.

## 1. Mettre la branche du chantier sur ton Mac

Ta branche `main` n'est pas touchée. Dans le Terminal, depuis le dossier où Atelier est installé (par défaut `~/Atelier-appli`) :

```
cd ~/Atelier-appli
git fetch origin chantier/agent-sdk
git checkout chantier/agent-sdk
./outils/installer-mac.sh
```

À regarder pendant l'installation :

- le script dit où il a trouvé ou installé `uv`, puis installe la bibliothèque `claude-agent-sdk` ;
- il ne demande aucun mot de passe administrateur ;
- il se termine en ouvrant le tableau de bord.

S'il s'arrête, note la phrase exacte qu'il affiche.

Pour revenir à la version d'avant, à tout moment :

```
cd ~/Atelier-appli
git checkout main
./outils/installer-mac.sh
```

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

## Ce que j'aimerais que tu me rapportes

- Les phrases de connexion telles que le fil les a écrites.
- Si les cartes sont apparues, et si « une fois » puis le refus avec indication ont eu l'effet attendu.
- Le temps que met une tâche à revenir après un arrêt, et s'il est resté un programme Claude.
- Toute phrase qui t'a paru fausse, obscure ou en trop.
- Tout ce qui t'a surpris, même si tu ne sais pas si c'est un défaut.

## Deux points d'attention

- Si tes commits git sont signés par une clé qui demande une saisie (une phrase secrète, une clé matérielle), dis-le-moi avant l'essai : Atelier enregistre le travail vérifié par git, sans terminal pour répondre à cette demande, et cela n'a pas pu être essayé.
- Les commandes `launchctl` du LISEZMOI ont été écrites d'après la documentation de macOS, sans avoir pu être essayées : dis-moi si l'une d'elles ne marche pas.
