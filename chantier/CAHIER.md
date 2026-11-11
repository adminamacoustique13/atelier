# Cahier du chantier « Agent SDK »

État général : toutes les tâches automatisées sont vérifiées, enregistrées et poussées sur la branche `chantier/agent-sdk`. Il reste la tâche F, le premier essai réel, qui revient à la personne responsable (voir `chantier/ESSAI-MAC.md`), puis sa décision de fusionner dans `main`. Le contrat a été amendé plusieurs fois le 2026-11-11 (voir `chantier/CONTRAT.md`).

## Suivi

Compteur final : 44 agents lancés (chaque reprise d'un agent compte pour un lancement), 1 montée en gamme sur 3 (tâche E, de Sonnet à Opus). État du dépôt à la clôture : 622 tests verts, contrôle de forme vert, trois essais dans le navigateur (247 vérifications), et plus aucune trace de l'ancien câblage hors de `chantier/` et de `DECISIONS.md`.

Niveau de vérification, depuis la décision de la personne responsable du 2026-11-11 (voir `chantier/LECONS.md`) : complète pour D3 et pour la quatrième tentative de E, déjà lancée ; bornée pour la seconde vérification de D2 et pour G ; mécanique seule pour les restes mineurs repris à la clôture. Une seconde passe ne corrige plus que ce qui a été recalé.

Ordre de la suite, revu le 2026-11-11 : C, puis D1 et H en parallèle, puis D2 et E en parallèle, puis D3, puis G. À la clôture, une recherche dans tout le dépôt confirme qu'il ne reste aucun lien avec l'ancien câblage.

| Tâche | État | Ouvrier | Vérificateur | Tentatives | Preuve |
|---|---|---|---|---|---|
| A | vérifié | Opus, effort élevé | Fable, effort élevé | 2 | 71 tests du pont verts, dont deux avec le vrai client du SDK sur un faux exécutable ; deux vérifications, 800 courses sans blocage |
| B | vérifié | Opus, effort élevé | Fable, effort élevé | 3 | 206 tests du guichet verts ; trois vérifications, dont 150 manches de 40 agents sans défaut et 448 formes de shell sans règle |
| C | vérifié | Opus, effort élevé | Fable, effort élevé | 2 | 371 tests verts ; deux vérifications, 94 casses du code essayées, 180 arrêts en boucle sans blocage ni fil restant |
| D1 | vérifié | Sonnet, effort élevé | Opus, effort élevé | 2 | 421 tests verts ; deux vérifications, ancien et nouveau moteur comparés sur 36 parties et 20 parties en parallèle sans écart |
| D2 | vérifié | Sonnet, effort moyen | Opus, effort moyen, puis vérification mécanique | 2 | Essai dans le navigateur : 89 vérifications passées deux fois de suite ; captures relues par l'orchestrateur |
| D2.1 | vérifié | Sonnet, effort faible | mécanique seule | 1 | Une ligne de style ; l'essai du tableau de bord passe de 89 à 95 vérifications ; capture relue par l'orchestrateur |
| D3a | vérifié | Opus, effort élevé | Fable, complète, puis vérification mécanique | 2 | 599 tests verts ; 19 valeurs refusées par la route et 9 profils écrits à la main sans faille ; 25 tours à cinq agents sans écart |
| D3b | vérifié | Sonnet, effort moyen | mécanique, avec relecture des captures | 1 | Essai dans le navigateur : 82 vérifications passées ; captures `D3-mode-reel.png` et `D3-etroit.png` relues par l'orchestrateur |
| E | vérifié, avec une limite connue reprise par E.1 | Opus, effort élevé (après Sonnet, effort moyen) | Fable, effort élevé | 4 | 449 tests verts ; la règle des annonces est prouvée sur 1 554 enchaînements par l'ouvrier et sur plus de 400 000 par le vérificateur, sans écart |
| E.1 | vérifié | Opus, effort moyen | Fable, complète mais étroite (facturation) | 1 | Validé du premier coup : 457 tests verts ; 29 870 enchaînements du vérificateur sans écart, et 111 110 pour R1 et R2 |
| Ga | vérifié | Sonnet, effort moyen | Opus, bornée | 1 | Validé du premier coup : 27 tests verts ; douze cas de dossier abîmé ou de phrase trompeuse essayés par le vérificateur, aucun défaut bloquant |
| Gb | vérifié | Sonnet, effort moyen | mécanique, avec relecture des captures | 1 | 622 tests verts ; essai dans le navigateur : 70 vérifications ; captures `G-confirmation.png` et `G-etroit.png` relues par l'orchestrateur |
| I | vérifié | Sonnet, effort élevé | Opus, effort élevé | 1 | Validé du premier coup : 0 échec sur 220 passages sous charge, contre 6 sur 212 avant la correction ; aucun interblocage possible |
| H | vérifié | Sonnet, effort moyen | Opus, effort moyen | 1 | Validé du premier coup : 371 tests verts, chaque règle des deux tests retirés cassée sur une copie et rattrapée par un test |
| F | revient à la personne responsable | | | | |

Point de départ contrôlé le 2026-11-11 : 35 tests verts, contrôle de forme vert.

### Clôture, le 2026-11-11
- Pas de passe générale de simplification : la personne responsable a demandé de ne plus alourdir le déroulement, et une réécriture de fin de chantier sur 8 600 lignes ajoutées aurait demandé une vérification de plus. Les restes ci-dessous sont proposés à sa décision.
- La carte du code (table « Les fichiers » du LISEZMOI) est à jour : `guichet.py`, `mise_a_jour.py` et `projets.py` y figurent.
- `chantier/DOSAGE.md` est écrit. `chantier/LECONS.md` porte cinq leçons validées par la personne responsable : deux en cours de route, trois à la clôture.

### Restes mineurs connus, non corrigés
Aucun ne touche aux droits des agents ni à la facturation.
- Activité : pendant la proposition d'un plan, la ligne de l'orchestrateur montre le texte brut du plan.
- Fil : les notes « Ouvrier lancé » et « Vérificateur lancé » sont écrites même quand l'agent ne part pas, après un arrêt.
- Modes : en passant de « Refuser sans demander » à l'arbitre pendant un tour, un refus du premier mode peut s'afficher comme un refus de l'arbitre ; les refus de « Refuser sans demander » n'apparaissent nulle part.
- Mise à jour : un agent qui démarrerait entre le contrôle « un agent travaille » et le `git pull` serait arrêté par le redémarrage ; pas de phrase dédiée pour un fichier non suivi en conflit.
- Guichet : « 1 caractères de plus » au singulier ; aucun test ne couvre `eval` dans la liste des lanceurs.
- Désinstallation : `outils/desinstaller-mac.sh` laisse le dossier `.venv` (le LISEZMOI le dit).
- Moteur : chaque « Relancer » ajoute deux agents à l'enveloppe du chantier servi, même après un arrêt avant le départ. Règle antérieure au chantier, dans une partie que le contrat protège.
- Contrôles : trois lignes mortes dans `_config` de `atelier/controles.py`. Fichier protégé par le contrat.
- Produit : Atelier enregistre le travail par git avec la configuration de la personne ; une signature des commits qui demande une saisie échouerait sans doute sous l'agent de lancement.
- Tests : quatre bornes de temps dans les tests du pont et des agents, jamais vues en échec.

### Historique de la tâche Gb
- Vérification mécanique : 622 tests verts trois fois de suite, l'essai du bouton relancé par l'orchestrateur (70 vérifications), deux captures relues. L'ouvrier a lu dans le script d'installation que l'agent de lancement relance Atelier après n'importe quelle sortie, et s'arrête donc par une sortie ordinaire.
- À transmettre à F : la liste « À essayer en vrai » de la fiche de relais Gb, reprise dans `chantier/ESSAI-MAC.md`.

### Historique de la tâche A
- Première vérification : recalé. Chemin nominal bon et fidèle au SDK (essayé avec le vrai `ClaudeSDKClient` sur un faux exécutable `claude`). Trois défauts : `fermer()` pendant un envoi peut bloquer l'appel une heure ; la déconnexion annulée au bout de cinq secondes peut laisser le processus Claude Code vivant ; un « toujours » avec une règle vide autorisait l'outil entier. Trou de la consigne relevé : un faux client aux `interrupt` et `disconnect` instantanés ne peut pas montrer ce qui dépend des durées réelles ; il fallait exiger un essai avec le vrai client sur un faux exécutable.
- Seconde chance (même ouvrier, même niveau), avec cet essai ajouté à la preuve.
- Seconde vérification : validé. Les trois défauts sont levés, sur le faux client comme sur le vrai. Limites acceptées : une réponse « une_fois » arrivée au moment exact de l'arrêt peut laisser passer l'outil juste avant l'interruption ; un rappel `sur_evenement` bloquant bloque `envoyer` jusqu'au garde-fou.
- Trois reliquats mineurs du pont, confiés à la tâche C (son périmètre est étendu à `atelier/sdk.py` et `tests/test_sdk.py` pour eux seuls) : le drapeau d'arrêt lié au client ; `fermer` qui attend le verrou avant de regarder la boucle ; `guichet.annuler` appelé à la fin de tout tour.
- Les deux tests avec le vrai client ne détectent pas les défauts 1 et 2 (leur faux exécutable obéit à la fermeture) : seuls les tests à faux client les détectent. À couvrir à l'essai réel F.
- Transmis à C : la liste « À savoir pour la tâche C » de la fiche de relais A.
- À transmettre à D1 : le rappel `sur_evenement` du serveur ne fait que déposer dans une file bornée, rien de lent.
- À transmettre à F : essayer « toujours » sur un outil entier ; un envoi qui suit un résultat en erreur (il peut échouer une fois avant de se reconnecter) ; l'arrêt d'un agent qui a des tâches de fond, pour vérifier que Claude Code meurt bien.

### Historique de la tâche C
- Première vérification : recalé de peu. Les sept critères sont remplis et prouvés (75 casses du code essayées, 64 détectées) ; ancienne ligne de commande et nouvelles options comparées point par point, mêmes décisions du moteur. Défaut : après un arrêt, l'appel rendait la main avant que la session soit fermée, et un fichier écrit par l'agent arrêté pouvait tomber dans la tentative suivante. Trou de la consigne : elle ne disait pas quand un appel arrêté doit rendre la main.
- Seconde chance (même ouvrier, même niveau) : la règle est écrite (au retour de l'appel, la session est fermée et le client déconnecté) ; le filtre de `autorisations` ne garde que les règles simples. L'ouvrier signale un échec isolé de deux tests, non reproduit en 140 passages : le vérificateur cherche un test instable.
- Seconde vérification : validé. Les sept points sont levés ; rien de cassé par la correction (aucun interblocage, aucun fil restant, `arreter` répond en 0,1 ms).
- Le test instable est trouvé, et il ne vient pas de C : `test_avec_un_vrai_depot_git_le_travail_verifie_est_fusionne_et_le_reste_jete` échoue environ une fois sur 70 sous charge, à cause d'une course dans `atelier/controles.py` (`git worktree remove` lancé hors du verrou de fusion, lignes 119-120 et 214-215). Elle existait avant le chantier. C'est un vrai défaut du code : il ferait tomber le fil du moteur quand une tâche est refusée pendant qu'une autre démarre. Correction essayée par le vérificateur sur une copie (prendre le verrou aux deux endroits) : 0 échec sur 200. Le fichier est un garde-fou, hors de l'objectif : question posée à la personne responsable.
- Restes mineurs, à reprendre à la clôture : quatre bornes de temps dans les tests du pont et des agents, jamais vues en échec ; aucun cas `Bash(a,b)` dans le test du filtre ; le filtre écarte sans le dire une règle écrite à la main qui contient une virgule.
- Transmis à D1 : la liste « À savoir pour la tâche D1 » de la fiche de relais C.
- À transmettre à F : la liste « À essayer en vrai » de la fiche de relais C.
- Limite connue, à dire dans le bilan : « sans outil d'écriture » veut dire sans les outils Edit, Write, MultiEdit et NotebookEdit. Le vérificateur garde, comme avant le chantier, les commandes permises du projet, dont certaines écrivent sur le disque.

### Historique de la tâche D1
- Première vérification : recalé pour un seul défaut. Les six critères sont remplis, les garde-fous du moteur sont intacts, les routes tiennent face aux requêtes mal formées, la règle d'un « toujours » vient toujours du guichet. Défaut : un arrêt tombant juste avant le départ d'un agent était noté, mais l'agent partait quand même et travaillait jusqu'au bout. Trou de la consigne : « rendue quel que soit le moment » garantissait l'issue, pas l'arrêt effectif de l'agent.
- Seconde chance (même ouvrier, même niveau) : le drapeau est relu juste avant chaque lancement d'agent ; un arrêt demandé avant la décision d'enregistrer l'emporte toujours, un arrêt demandé après est refusé avec une phrase claire ; chaque « toujours » laisse une phrase au fil.
- Seconde vérification : validé. Le redécoupage de deux fonctions du moteur est un simple déplacement de code (aucun écart sur 36 parties, plus 20 parties de cinq tâches en parallèle). Le « dernier mot sous verrou » ne peut pas créer d'interblocage.
- Restes mineurs, à reprendre à la clôture : les notes « Ouvrier lancé » et « Vérificateur lancé » sont écrites même quand l'agent ne part pas ; deux relectures du drapeau sont devenues redondantes.
- Constat à dire à la personne responsable dans le bilan : chaque « Relancer » ajoute deux agents à l'enveloppe du chantier servi, même après un arrêt avant le départ, où aucun agent n'a été lancé. La règle existait avant ce chantier.
- Transmis à D2 : la rubrique 3 de la fiche de relais D1.
- À transmettre à F : la reprise de la conversation après une première réponse arrêtée.

### Historique de la tâche E
- Première vérification : recalé. Le script d'installation, le ménage de l'ancien câblage et l'essentiel du LISEZMOI sont validés. Quatre défauts, tous sur ce qu'Atelier dit de la facturation : une phrase de départ qui annonçait « abonnement » sans le savoir ; une contradiction non relevée quand le SDK annonçait ensuite une clé ; un conseil (« retire la variable de ton environnement ») qui ne marche pas sous l'agent de lancement de macOS ; le câblage de `servir` non testé. Trou de la consigne : « un test du message avec les deux sources » se satisfaisait au niveau de la fonction.
- Seconde chance (même ouvrier, même niveau) : les quatre défauts sont levés ; `uv.lock` entre dans le dépôt et fixe `claude-agent-sdk` 0.2.172 ; l'annonce n'est écrite que si elle change.
- Seconde vérification : recalé pour deux défauts simples. Le dédoublonnage, ajouté à la demande de l'orchestrateur, pouvait écarter une confirmation promise par la phrase de départ ; un test de la démonstration ne cherchait pas la bonne phrase.
- Troisième passe, courte et bornée, au même niveau : le premier défaut vient d'une demande ajoutée par l'orchestrateur à la seconde passe, pas d'une incapacité de l'ouvrier. Pas de montée en gamme.
- Troisième vérification : recalé pour un seul défaut. Les deux défauts de la seconde vérification et les trois compléments sont levés ; un redémarrage sans changement n'ajoute plus rien au fil. Mais la nouvelle règle du dédoublonnage (`atelier/serveur.py`, `_noter_annonce`, lignes 289 à 297) remonte le fil jusqu'au dernier départ sans s'arrêter sur une confirmation différente : avec des sources successives « clé API », « abonnement », « clé API » sur trois démarrages, la troisième n'est pas écrite, et le fil se termine sur « compté sur ton abonnement » alors que la clé est facturée. Correction indiquée par le vérificateur : arrêter la boucle au premier texte de la famille trouvé, et écrire s'il diffère.
- Trois tentatives, le maximum du contrat : la tâche revient à la personne responsable. Dossier : cette rubrique, la fiche de relais E, et les trois verdicts résumés ci-dessus.
- Quatrième tentative, accordée par la personne responsable le 2026-11-11, un cran au-dessus : Opus, effort élevé, vérifié par Fable. Montée en gamme notée (1 sur 3). Cette fois la règle des annonces est écrite en toutes lettres dans la consigne, avec les invariants à tenir, et la preuve demandée est un test exhaustif de tous les enchaînements courts : les trois échecs venaient d'une règle que l'orchestrateur n'avait jamais énoncée complètement.
- Vérification de la quatrième tentative : validé sur les sept critères. La règle telle qu'énoncée est prouvée pour toute longueur d'enchaînement. Le vérificateur montre en revanche une limite de la règle elle-même : une source de connexion qui change pendant une même ouverture n'est redite qu'à l'ouverture suivante, parce qu'une seule confirmation est écrite par ouverture. Elle devient la tâche E.1.
- Les échecs intermittents de deux ou huit tests, vus plusieurs fois pendant le chantier, sont expliqués : les tests qui créent un vrai dépôt git héritent de la configuration git de la machine, qui signe ici chaque commit par un service extérieur, parfois injoignable. Ce n'est pas un défaut du produit.
- Transmis à F : la liste « À essayer en vrai » de la fiche de relais E, reprise dans `chantier/ESSAI-MAC.md`.
- Reste mineur, à reprendre à la clôture : `outils/desinstaller-mac.sh` ne retire pas le dossier `.venv` (le LISEZMOI le dit).

### Historique de la tâche I
- Vérification : validé du premier coup. Le verrou est pris aux deux endroits, aucun chemin ne le redemande, toute commande git lancée sous le verrou est bornée par un délai. Les commandes git restées hors du verrou ne touchent pas aux arbres des autres tâches.
- Réserve du vérificateur, sans effet sur le verdict : le test nouveau prouve que les commandes `worktree` sont mises en file, plutôt qu'il ne reproduit la panne elle-même ; la preuve que la panne a disparu vient du test d'origine sous charge.
- Reste mineur, à reprendre à la clôture : trois lignes mortes dans `_config` de `atelier/controles.py` (lignes 89 à 92), sans effet.

### Historique de la tâche D2
- Première vérification : recalé pour trois défauts. Validés : les cartes aux deux endroits, le refus avec son texte, la sécurité de l'affichage, le style, la page des instantanés. Défauts : la phrase qui explique la règle « toujours » ne disait rien hors des commandes Bash ; un double-clic sur « Arrêter » arrêtait sans confirmation ; l'activité déroulée montrait les lignes les plus anciennes et revenait en haut à chaque ligne. Trou de la consigne : son exemple de règle ne couvrait que Bash, et la preuve n'exigeait ni de cliquer « Toujours » ni d'éprouver le double-clic.
- Seconde chance (même ouvrier, même niveau) : les trois défauts sont corrigés, l'essai passe de 67 à 89 vérifications et couvre maintenant « Toujours », l'identifiant envoyé, le double-clic et le journal long.
- Seconde vérification, mécanique : l'essai relancé deux fois par l'orchestrateur, et les captures `D2-regles.png`, `D2-carte-conversation.png` et `D2-arret-confirmation.png` relues. Pas de vérificateur : décision de la personne responsable du 2026-11-11 de proportionner la vérification au risque. Tâche vérifiée.
- D2.1, ajoutée le 2026-11-11 sur un signalement de la personne responsable (capture de son écran) : dans la carte « Orchestrateur », l'anneau de progression chevauchait le texte quand l'objectif était long. Défaut antérieur au chantier : la règle `.tete-orch > div { min-width: 0 }` laissait rétrécir l'enveloppe de l'anneau. Corrigé par une ligne de style ; vérification mécanique seule.
- À transmettre à D3 : pendant la proposition d'un plan, la ligne d'activité de l'orchestrateur montre le texte brut du plan ; c'est au serveur de couper cette ligne.

### Historique de la tâche E.1
- Vérification étroite : validé du premier coup. Le défaut de règle est levé dans les deux sens, une source inchangée ne coûte rien, une écriture qui échoue est retentée, aucun interblocage n'est possible.
- Limite acceptée : la source est lue sur un attribut de l'agent commun à toutes ses sessions (`atelier/agents.py`). Deux sessions simultanées lancées de part et d'autre d'un changement de connexion peuvent se croiser ; le fil est alors corrigé par la session suivante. À reprendre si `agents.py` est rouvert : passer la source dans l'événement.
- À dire à la personne responsable : Atelier enregistre le travail par git avec sa configuration à elle. Une signature des commits qui demande une saisie échouerait sans doute sous l'agent de lancement, qui n'a pas de terminal. Ajouté à `chantier/ESSAI-MAC.md`.

### Historique de la tâche Ga
- Vérification bornée : validé du premier coup, en une dizaine de minutes. Le dossier d'Atelier reste intact dans tous les cas d'échec, `fait` n'est vrai que si le commit courant a changé, aucun identifiant ne fuit, aucune commande git ne peut rester bloquée.
- À transmettre à Gb : ne lancer qu'une mise à jour à la fois ; s'arrêter seulement si `fait` est vrai ; journaliser `detail` sans jamais l'afficher ; appeler `verifier` hors du fil qui répond aux requêtes (une interrogation peut durer 60 secondes) ; en démonstration, ne pas arrêter le serveur sur le `fait` du double simulé.
- Deux retouches du module confiées à Gb : tirer explicitement `origin main` (aujourd'hui le pull suit l'amont de `main`, alors que la vérification regarde `origin/main`) ; ne pas prendre « Cannot fast-forward to multiple branches » pour une histoire divergente.
- Restes mineurs, à reprendre à la clôture : pas de phrase dédiée pour un fichier non suivi en conflit ni pour une branche sans amont ; `GIT_SSH_COMMAND` écrase un réglage ssh propre à la personne.

### Historique de la tâche D3a
- Vérification complète : recalé de peu. Rien de grave : aucun agent n'obtient plus de droits que prévu, `bypassPermissions` est refusé partout, aucun interblocage, le changement de mode part vraiment vers Claude Code. Deux défauts : le fil ne redisait pas un écart de mode déjà dit quand il se reproduisait après un nouveau choix ; un échec ordinaire dont la sortie contenait la phrase du refus était pris pour un refus de l'arbitre (la consigne disait « contient » au lieu de « commence par »).
- Seconde passe (même ouvrier) : les deux défauts sont corrigés, avec trois tests qui échouaient avant ; les explications de « Répétition » et de l'arbitre sont rendues exactes. Vérification mécanique seule, par décision de la personne responsable de ne plus tout faire revérifier.
- Défaut mineur connu, non corrigé : si un même tour passe de « Refuser sans demander » à l'arbitre, un refus du premier mode peut être annoncé comme un refus de l'arbitre.
- Ce que chaque mode change réellement, établi par le vérificateur : en « Me demander », seules les commandes non permises d'avance demandent une carte ; en « Répétition », les modifications de fichiers demandent une carte mais les commandes permises du profil peuvent écrire ; en « Refuser sans demander », les refus n'apparaissent nulle part ; l'arbitre ne juge que ce qui aurait demandé une carte, plus les commandes qui exécutent du code.
- À transmettre à F : la liste « À essayer en vrai » de la fiche de relais D3a.

### Historique de la tâche B
- Première vérification : recalé. La concurrence tient (150 manches de 40 agents sans défaut). Trois défauts : filtre des lanceurs contournable (`/bin/bash -lc`, `time bash -c`), site affiché différent du site visité pour une adresse piégée, dix casses du code sur soixante-trois non détectées par les tests. Trous de la consigne relevés : aucune preuve adverse demandée pour la règle, phrase coupée sans accès au texte complet.
- Seconde chance (même ouvrier, même niveau) : les trois défauts et quatre compléments sont levés (clé `detail`, retour à la ligne visible, aucune exception, guichet simulé aligné). Seconde vérification : recalé de peu, sur deux contournements nouveaux (interpréteur seul, lanceurs absents de la liste) et un risque sur `localhost`.
- Troisième passe, courte et bornée, au même niveau : le vérificateur a montré qu'une liste d'exclusions ne sera jamais complète. C'est la consigne qui était en cause, pas l'ouvrier : pas de montée en gamme. On ferme les cas connus et on écrit le risque qui reste.
- Troisième vérification : code et tests validés (les six points faits et testés, rien de cassé). Seul défaut : deux phrases du paragraphe « Risque qui reste » de la fiche, reprises de la consigne de l'orchestrateur, qui les a corrigées lui-même ; l'affichage de la règle sur la carte devient le critère 7 de D2. Tâche vérifiée.
- Restes mineurs, à reprendre à la clôture : aucun test ne couvre `eval` dans la liste des lanceurs ; « 1 caractères de plus » au singulier dans la coupe de `detail`.
- À transmettre à D1 : `repondre` rend `False` aussi bien pour un « toujours » sans règle que pour un identifiant inconnu ; le serveur ne retire donc pas une carte sur `False`, il se fie à `ouvertes()`.
- À transmettre à D2 : masquer « Toujours pour ce projet » quand `regle` est vide ; afficher la règle exacte sur la carte ; afficher `detail` à la demande.
- À transmettre à A ou C : après un arrêt, le pont ne doit plus appeler `demander` (une demande arrivée après `annuler` attendrait tout le délai).

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
  7. Les trois reliquats du pont relevés à la seconde vérification de A sont corrigés, chacun avec son test (ajouté le 2026-11-11).
- **Périmètre** : `atelier/agents.py`, `tests/test_agents.py` (nouveau) ; étendu le 2026-11-11 à `atelier/sdk.py` et `tests/test_sdk.py` pour les trois reliquats du pont seulement
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
- **Périmètre** : `atelier/serveur.py`, `atelier/moteur.py` (l'arrêt seulement), `tests/test_serveur.py` (nouveau) ; étendu le 2026-11-11 à `atelier/__main__.py`, pour la seule commande `instantanes`, qui doit répondre à la demande simulée au lieu de l'attendre
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
  7. Chaque carte affiche la règle exacte que « Toujours pour ce projet » retiendrait (ajouté le 2026-11-11, après la vérification de B : c'est la seule vraie protection contre une règle trop large).
  8. Le choix « Toujours pour ce projet » n'apparaît pas quand la demande n'a pas de règle.
  9. Le texte complet de la demande (clé `detail`) s'affiche d'un clic sur la carte.
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
- **Découpage décidé le 2026-11-11 par l'orchestrateur**, pour deux raisons : la tâche traversait six fichiers et quatre modules, et la personne responsable a demandé depuis que le gros du code soit confié à Opus, Sonnet gardant le travail cadré.
  - **D3a, le fond** : le pont sait changer de mode à chaud et relaie les refus de l'arbitre et le mode réellement appliqué ; les agents appliquent le mode aux ouvriers seulement ; le serveur enregistre le choix, l'applique et le dit. Fichiers : `atelier/sdk.py`, `atelier/agents.py`, `atelier/serveur.py`, `atelier/guichet.py` (une phrase), et leurs tests. Opus, effort élevé ; vérification complète par Fable, parce que c'est ce qui décide de ce que les agents font sans demander.
  - **D3b, la page** : le menu « Mode des ouvriers » dans l'onglet Chantier, l'essai dans le navigateur, et la section du LISEZMOI. Fichiers : `atelier/tableau/index.html`, `chantier/essais/D3-modes.js`, `chantier/captures/D3-*.png`, `LISEZMOI.md`. Sonnet, effort moyen ; vérification bornée.
- **Décision de la personne responsable, le 2026-11-11** : dans tous les modes, les modifications de fichiers restent permises d'avance aux ouvriers. « Me demander » ne porte donc que sur ce qui n'est pas permis d'avance (les commandes surtout). Le menu doit le dire en clair dans l'explication de chaque choix.
- **Fait observé pendant ce chantier**, utile au critère 4 : quand l'arbitre du mode auto refuse une action, l'agent reçoit comme résultat de l'outil un texte qui commence par « Permission for this action was denied by the Claude Code auto mode classifier. Reason: [Exfil Scouting]. », le nom entre crochets étant la règle qui a joué.
- **Faits vérifiés le 2026-11-11** dans la documentation de Claude Code (pages « permission modes », « Agent SDK : permissions » et « Agent SDK : hooks ») et dans le SDK 0.2.172 :
  - `set_permission_mode` et les cinq modes existent. Le changement vaut tout de suite pour les demandes d'outil suivantes.
  - Refus de l'arbitre : l'agent en reçoit la raison dans le résultat de l'outil, le plus souvent le nom de la règle (par exemple `[Data Exfiltration]`). Le crochet `PermissionDenied`, qui annonce ces refus, n'existe que dans le SDK TypeScript, pas dans le SDK Python. Côté Python il reste le flux de messages (résultats d'outils) et le champ `permission_denials` du résultat final. La forme exacte de ces refus n'a pas pu être observée ici : à confirmer à l'essai réel F.
  - Mise en pause : après 3 refus de suite ou 20 au total, le mode auto se met en pause et Claude Code recommence à demander ; accepter la demande relance le mode auto. Ces seuils ne se règlent pas. La documentation ne décrit ce retour que pour le terminal et pour `claude -p` ; avec le rappel `can_use_tool` du pont, les demandes doivent arriver au guichet : à confirmer à l'essai réel F.
  - Mode auto indisponible au démarrage : la session démarre en `default`, et le message d'initialisation donne le mode réel dans `permissionMode`. En cours de session : `set_permission_mode("auto")` échoue avec « Cannot set permission mode to auto: auto mode unavailable for this model ».
  - Retombée en cours de session : un message système de sous-type `status`, avec `permissionMode` à `default`.
  - Modèles acceptés par le mode auto : Opus 4.6 ou plus récent, Sonnet 4.6 ou plus récent, Haiku 5.5, Fable.
  - En entrant en mode auto, Claude Code met de côté les règles larges qui permettent d'exécuter du code (`Bash(python*)`, les commandes de lancement des gestionnaires de paquets) : les commandes permises par défaut d'Atelier passeront donc devant l'arbitre. Elles reviennent en quittant le mode.
  - En mode `plan`, les modifications de fichiers arrivent au rappel `can_use_tool`, donc aux cartes d'autorisation, même si une règle les permet.
  - En mode `dontAsk`, tout ce qui aurait demandé une autorisation est refusé, sans passer par `can_use_tool`.
  - Une suppression de chemin critique (`rm -rf ~`) est refusée d'office en mode auto dans une session du SDK.

### E. Installation et connexion
- **Pourquoi** : sur ton Mac, Atelier doit installer la bibliothèque tout seul, et te dire clairement s'il facture ton abonnement ou une clé API.
- **Critères** :
  1. `outils/installer-mac.sh` installe la dépendance par uv, sans rien installer hors de ton dossier personnel.
  2. Au démarrage, Atelier affiche dans le fil la source de connexion : « abonnement » ou « clé API ».
  3. Si une variable `ANTHROPIC_API_KEY` est présente, le fil le signale en une phrase : c'est elle qui sera facturée, pas l'abonnement.
  4. Le LISEZMOI explique la nouvelle dépendance, les cartes d'autorisation, la clé `autorisations` et le bouton « Arrêter ».
- **Périmètre** : `outils/installer-mac.sh`, `atelier/__main__.py`, `LISEZMOI.md`
- **Contrats** : attend A (lecture de la source de connexion).
- **Dépendances** : A, et C depuis le 2026-11-11 : la source de connexion n'est connue qu'après l'ouverture d'une session, il faudra peut-être une fonction de sondage dans `atelier/sdk.py`, que C modifie. E sera lancée après D1, qui touche aussi `atelier/__main__.py`, et en parallèle de D2, sans fichier en commun.
- **Preuve** : `bash -n` et `shellcheck` sur le script, et un test du message de démarrage avec les deux sources simulées.
- **Départ** : Sonnet, effort moyen.

### G. Le bouton « Mettre à jour » — ajoutée le 2026-11-11 par la personne responsable, hors de l'objectif initial
- **Pourquoi** : mettre Atelier à jour d'un clic depuis le tableau de bord, sans passer par le terminal.
- **Critères** :
  1. Atelier vérifie, au plus une fois par heure, si la branche `main` a avancé sur le dépôt en ligne de son propre dossier.
  2. Quand `main` a avancé, le tableau de bord montre un bouton « Mettre à jour ».
  3. Un clic pendant qu'un agent travaille ne change rien, et le fil dit pourquoi.
  4. Un clic quand aucun agent ne travaille lance `git pull --ff-only` dans le dossier d'Atelier.
  5. Après un pull réussi, Atelier s'arrête, et l'agent de lancement (KeepAlive) le relance.
  6. Si le pull échoue, rien ne change et le fil explique pourquoi.
  7. En mode démonstration, la vérification et la mise à jour ont leur double simulé : rien n'est appelé.
- **Périmètre** : `atelier/mise_a_jour.py` (nouveau), `tests/test_mise_a_jour.py` (nouveau), `atelier/serveur.py` (une route et un champ de la vue), `atelier/tableau/index.html` (le bouton), `atelier/__main__.py` (le branchement au démarrage), `LISEZMOI.md` (un paragraphe). À resserrer au lancement.
- **Contrats** : n'attend rien des autres tâches ; passe après elles parce qu'elle touche aux mêmes fichiers que D1, D2, D3 et E.
- **Dépendances** : D3 et E (pour l'ordre des fichiers seulement)
- **Preuve** : un test avec un dépôt local qui sert de faux GitHub.
- **Départ** : Sonnet, effort moyen.
- **Découpage décidé le 2026-11-11 par l'orchestrateur**, pour faire avancer la tâche pendant que D3a occupe le serveur :
  - **Ga, le fond** : un module `atelier/mise_a_jour.py` qui sait vérifier (au plus une fois par heure) et mettre à jour (`git pull --ff-only`), avec son double simulé, sans rien savoir du serveur. Lancée en parallèle de D3a, sans fichier en commun.
  - **Gb, le branchement** : la route et le champ de la vue, le bouton dans la page, le branchement au démarrage et l'arrêt d'Atelier après une mise à jour réussie, le paragraphe du LISEZMOI. Après D3b.
- **Précisions fixées au lancement de Ga** : la mise à jour est refusée si le dossier d'Atelier n'est pas sur `main` ou s'il contient des modifications locales, avec une phrase qui dit lequel ; une vérification qui échoue ne fait pas croire qu'Atelier est à jour.
- **À préciser au lancement de Gb** : ce que fait le clic quand le dossier d'Atelier n'est pas sur `main` ou contient des modifications locales ; ce que dit le fil quand Atelier n'a pas été lancé par l'agent de lancement (il ne reviendrait pas tout seul) ; si le redémarrage installe bien une dépendance nouvelle.

### H. Le ménage de l'ancien câblage — demandée le 2026-11-11 par la personne responsable
- **Pourquoi** : une fois `claude -p` remplacé, il ne doit rester dans le dépôt aucun lien avec l'ancien câblage, ni code mort, ni phrase qui décrit Atelier comme lançant Claude Code en ligne de commande.
- **État des lieux au 2026-11-11** :
  - `atelier/agents.py` garde les anciens lecteurs `lire_flux_claude`, `lire_sortie_claude` et `_suivre`. Ils ne servent plus au produit ; ils sont restés parce que deux des 35 tests d'origine les testent (`test_lecture_de_la_sortie_de_claude_code` et `test_le_flux_de_claude_code_est_relaye_au_fil_de_l_eau`, dans `tests/test_moteur.py`), et que des tests de C comparent le pont à leur résultat.
  - `atelier/__main__.py` attrape encore `subprocess.SubprocessError`.
  - `atelier/sdk.py` cite `lire_sortie_claude` dans un commentaire.
  - `outils/installer-mac.sh` exige l'exécutable `claude`, et `LISEZMOI.md` décrit encore la ligne de commande : ces deux fichiers sont repris par la tâche E.
- **Critères** :
  1. `atelier/agents.py` ne contient plus `lire_flux_claude`, `lire_sortie_claude` ni `_suivre`, ni rien qui ne servait qu'à eux.
  2. Les tests qui comparaient le pont au résultat des anciens lecteurs comparent à des valeurs écrites en clair, sans perdre un seul cas.
  3. Les deux tests d'origine qui ne testaient que les anciens lecteurs sont retirés ; chaque règle qu'ils vérifiaient reste couverte par un test du pont.
  4. Aucun commentaire, aucune docstring, aucun message et aucune page de documentation ne décrit plus Atelier comme lançant Claude Code en ligne de commande.
  5. `subprocess` ne sert plus qu'à git et aux contrôles du projet.
- **Périmètre** : `atelier/agents.py`, `atelier/sdk.py` (commentaires seulement), `tests/test_agents.py`, `tests/test_sdk.py`, et `tests/test_moteur.py` pour le seul retrait des deux tests nommés ci-dessus. Le reste du ménage est réparti : `atelier/__main__.py`, `outils/installer-mac.sh` et `LISEZMOI.md` reviennent à la tâche E ; chaque tâche suivante reçoit la consigne de ne rien écrire qui renvoie à l'ancien câblage ; l'orchestrateur lance la recherche finale à la clôture.
- **Contrats** : ne change aucun comportement.
- **Dépendances** : C. Lancée en parallèle de D1, sans fichier en commun (revu le 2026-11-11, à la demande de la personne responsable de faire ce ménage sans attendre la fin).
- **Preuve** : une recherche dans le dépôt, hors `chantier/` et `DECISIONS.md`, ne trouve plus `claude -p`, `lire_flux_claude`, `lire_sortie_claude` ni « en ligne de commande » à propos de Claude Code ; la suite de tests et le contrôle de forme restent verts.
- **Départ** : Sonnet, effort moyen. C'est un retrait bien cadré, mais il touche aux tests.
- **Fait le 2026-11-11** : les trois anciens lecteurs et les deux tests d'origine sont retirés ; il reste 33 tests d'origine. L'état des lieux ci-dessus décrit la situation d'avant.
- **Restes relevés par le vérificateur, confiés à la tâche E** : `LISEZMOI.md` ligne 5 (« Aucune dépendance », devenu faux), ligne 109 (« la lecture du flux de Claude Code », et un nombre de tests périmé), ligne 111 (« Claude Code accepte la ligne de commande »), ligne 120 (« Claude Code en ligne de commande, et le simulateur ») ; `outils/installer-mac.sh` lignes 45 à 47 (exige la commande `claude`) ; `atelier/__main__.py` (attrape encore `subprocess.SubprocessError`).
- **Restes mineurs, à reprendre à la clôture** : le mot « CLI » dans quatre commentaires du pont et des agents ; le relevé de `atelier/serveur.py`, `atelier/moteur.py` et `atelier/__main__.py` est à refaire après D1.
- **Accord de la personne responsable, le 2026-11-11** : le retrait des deux tests d'origine (zone rouge levée pour eux seuls) et l'enveloppe portée à 36.

### E.1. La source de connexion qui change en cours de route — ajoutée le 2026-11-11 par l'orchestrateur
- **Pourquoi** : le fil ne doit jamais rester sur une phrase de facturation fausse. Aujourd'hui, si la personne change sa connexion pendant qu'Atelier tourne (par exemple avec `/login`, comme le fil le lui conseille), le fil continue de dire l'ancienne source jusqu'à la relance d'Atelier.
- **Critères** :
  1. Quand un agent apprend une source différente de la dernière confirmation écrite depuis l'ouverture, le fil écrit la nouvelle confirmation.
  2. Deux sessions simultanées qui annoncent des sources différentes ne font pas alterner le fil sans fin : chaque changement est écrit une fois.
  3. Si l'écriture d'une confirmation échoue, elle est retentée à l'événement suivant au lieu d'être perdue pour toute l'ouverture.
  4. Les tests qui créent un vrai dépôt git ne dépendent plus de la configuration git de la machine (un fichier `tests/conftest.py`, sans toucher aux tests d'origine).
- **Périmètre** : `atelier/serveur.py` (les annonces de connexion seulement), `tests/test_demarrage.py`, `tests/conftest.py` (nouveau)
- **Contrats** : ne change ni le texte des phrases ni les règles R1 et R2 pour une source qui ne change pas.
- **Dépendances** : E. Passe avant D3, qui touche aussi `atelier/serveur.py`.
- **Preuve** : le test exhaustif étendu à plusieurs sources par ouverture, avec un message intercalé entre deux annonces.
- **Départ** : Opus, effort moyen. Vérification complète mais étroite : c'est de la facturation.

### I. La course dans les contrôles git — ajoutée le 2026-11-11 avec l'accord de la personne responsable, hors de l'objectif initial
- **Pourquoi** : en cherchant un test instable, le vérificateur de C a trouvé un vrai défaut, antérieur au chantier. Quand une tâche est refusée pendant qu'une autre démarre ou s'enregistre, deux commandes git se marchent dessus et le fil du moteur peut tomber. Avec trois tâches en parallèle, cela finit par arriver.
- **Critères** :
  1. Les deux appels `git worktree remove` de `ControlesGit` (dans `annuler`, et le retrait fait par `preparer`) passent par le verrou de fusion.
  2. Un test nouveau reproduit la course : il échoue sur le code actuel et passe après la correction.
  3. Le test d'origine `test_avec_un_vrai_depot_git_le_travail_verifie_est_fusionne_et_le_reste_jete` ne tombe plus sous charge.
  4. Aucun interblocage : aucun chemin ne demande le verrou de fusion alors qu'il le tient déjà.
- **Périmètre** : `atelier/controles.py` (cette correction seulement), `tests/test_controles.py` (nouveau)
- **Contrats** : ne change aucun comportement.
- **Dépendances** : aucune. Lancée en parallèle de D2, sans fichier en commun.
- **Preuve** : le test nouveau, et 200 passages du test d'origine sous charge sans échec (7 échecs sur 400 avant la correction).
- **Départ** : Sonnet, effort élevé. La correction tient en deux lignes, mais c'est de la concurrence dans un garde-fou.

### F. Premier essai réel sur ton Mac — revient à la personne responsable
- **Pourquoi** : aucune machine du chantier n'est connectée à ton compte Claude. La seule preuve qu'Atelier marche vraiment, c'est un essai chez toi.
- **Ce que tu feras** (environ 15 minutes, sur un dépôt sans importance) :
  1. mettre Atelier à jour ;
  2. vérifier que le fil annonce « abonnement » ;
  3. demander une petite tâche qui a besoin d'une commande non permise ;
  4. accepter la carte « une fois », puis refuser la suivante avec une indication ;
  5. arrêter un agent en cours.
- **Dépendances** : toutes les tâches précédentes, G et H comprises.
