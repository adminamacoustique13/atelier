# Fiche de relais V3-consignes : les consignes dont le moteur rapide aura besoin

Copie de travail partie de 35d8a12 (« Page : un seul format de tokens, et les pannes de réseau dites à l'écran »). Rien n'est commité. Le moteur n'appelle encore aucune des fonctions nouvelles : elles attendent V3a, V3b et V3e.

Les textes ci-dessous sont recopiés tels que le code les produit, pour une tâche d'essai `A — Titre A`, critères « Rend 42. » et « Rend 43. », périmètre `a.py, tests/test_a.py`, contrôles `pytest -q` et `ruff check .`. Chaque ligne de ces textes est une seule ligne dans la consigne réelle.

## Fait

### 1. `consigne_reprise` (V3a)

Message court donné à l'ouvrier repris dans sa propre session. Il dit ce qui a été refusé, avec le texte reçu en entier entre `[début]` et `[fin]` ; demande de corriger cela et rien d'autre, sans défaire ce qui était juste ; de relancer les contrôles ; de mettre à jour sa fiche de relais. Il ne répète rien de la consigne d'origine (un test vérifie qu'il fait moins de la moitié de celle-ci et ne reprend ni les critères ni les interdits). Une origine autre que les trois prévues lève `ValueError`. `complet` peut être un texte ou une liste de fichiers (rendue en `- \`fichier\``). Sans commande de contrôle au profil, la phrase des contrôles devient « Relance ensuite les tests qui portent sur ce que tu as corrigé. ».

Origine « verdict » :
```text
## Reprise de la tâche A après un refus
Le vérificateur a refusé ton livrable. Voici son verdict en entier :
[début]
Verdict entier...
{"valide": false}
[fin]

Corrige chaque point qu'il recale. Un vérificateur neuf contrôlera ensuite ces points, et vérifiera que tes corrections n'ont rien défait ; il ne refera pas le reste.

Ne change rien d'autre, et ne défais pas ce qui était juste : tout ton travail est encore dans ce dossier, et ce qui n'a pas été relevé n'est pas en cause. Chaque changement de plus serait à vérifier de nouveau et pourrait casser ce qui passait.

Relance ensuite les commandes de contrôle, jusqu'à ce qu'elles passent :
- `pytest -q`
- `ruff check .`
L'Atelier les rejoue après toi, avec le contrôle du périmètre, avant tout vérificateur.

Si tu tiens une fiche de relais (`chantier/relais/A.md`), mets-la à jour pour qu'elle décrive ton travail après correction. Si une commande t'est refusée, écris la ligne « EMPÊCHÉ : » comme le dit ta consigne.

Termine par un compte rendu court : ce que tu as corrigé, point par point, et ce qui reste.
```

Origine « perimetre » (avec `["b.py", "DECISIONS.md"]`) :
```text
## Reprise de la tâche A après un refus
Le contrôle du périmètre a refusé ton livrable : tu as modifié des fichiers qui n'en font pas partie :
[début]
- `b.py`
- `DECISIONS.md`
[fin]

Défais tes changements dans ces fichiers : `git diff -- <chemin>` te les montre, et `rm <chemin>` retire un fichier que tu as créé. Un fichier hors de ton périmètre fait refuser le livrable quoi qu'il contienne. Si une règle du projet te demandait d'y écrire, mets plutôt dans ta fiche de relais ce que tu y aurais mis ; si la tâche en a vraiment besoin, dis-le dans ton compte rendu.

Ne change rien d'autre, et ne défais pas ce qui était juste : tout ton travail est encore dans ce dossier, et ce qui n'a pas été relevé n'est pas en cause. Chaque changement de plus serait à vérifier de nouveau et pourrait casser ce qui passait.

Relance ensuite les commandes de contrôle, jusqu'à ce qu'elles passent :
- `pytest -q`
- `ruff check .`
L'Atelier les rejoue après toi, avec le contrôle du périmètre, avant tout vérificateur.

Si tu tiens une fiche de relais (`chantier/relais/A.md`), mets-la à jour pour qu'elle décrive ton travail après correction. Si une commande t'est refusée, écris la ligne « EMPÊCHÉ : » comme le dit ta consigne.

Termine par un compte rendu court : ce que tu as corrigé, point par point, et ce qui reste.
```

Origine « controles » :
```text
## Reprise de la tâche A après un refus
Les commandes de contrôle du projet échouent sur ton livrable. Voici la fin de leur sortie :
[début]
FAILED tests/test_a.py::test_42
[fin]

Trouve ce qui les fait échouer et corrige-le.

Ne change rien d'autre, et ne défais pas ce qui était juste : tout ton travail est encore dans ce dossier, et ce qui n'a pas été relevé n'est pas en cause. Chaque changement de plus serait à vérifier de nouveau et pourrait casser ce qui passait.

Relance ensuite les commandes de contrôle, jusqu'à ce qu'elles passent :
- `pytest -q`
- `ruff check .`
L'Atelier les rejoue après toi, avec le contrôle du périmètre, avant tout vérificateur.

Si tu tiens une fiche de relais (`chantier/relais/A.md`), mets-la à jour pour qu'elle décrive ton travail après correction. Si une commande t'est refusée, écris la ligne « EMPÊCHÉ : » comme le dit ta consigne.

Termine par un compte rendu court : ce que tu as corrigé, point par point, et ce qui reste.
```

### 2. `consigne_reverification` (V3a)

Vérificateur neuf après une reprise : verdict précédent en entier, chaque point recalé à contrôler, corrections qui ne doivent rien défaire, le reste à ne pas refaire. La rubrique « Ce que tu rends » est identique à celle de la consigne complète (un test compare les deux). Elle dit aussi que l'Atelier vient de rejouer les contrôles (inutile de relancer toute la suite). Mutations permises sur les points corrigés.

Avec copie jetable :
```text
Tu es vérificateur. Un autre agent a corrigé son livrable après un refus : tu contrôles cette correction, sans rien corriger toi-même.
Tu travailles dans une copie jetable du livrable : l'atelier la jette après ton verdict, et ce qu'il enregistre est le livrable de l'agent, pas cette copie. Tu ne corriges rien : une correction ne serait pas gardée. Mais tu peux y faire tes essais sans rien demander, à condition de t'y prendre ainsi :
- pour une mutation (changer le code pour voir si un test échoue), modifie le fichier avec l'outil Edit, lance le test, puis remets le texte d'origine avec Edit ;
- pour un essai de plus de quelques mots, écris un script dans ce dossier avec l'outil Write, puis lance-le (par exemple `python3 essai_mutation.py`) ;
- une commande simple par appel : pas de commandes enchaînées (`;`, `&&`, plusieurs lignes), pas de heredoc (`<<EOF`), pas de variable du shell (`$?`, `$(...)` : le code de retour de la commande t'est déjà donné), pas de `sed -i` ni de `rm -rf`, pas de dossier temporaire ailleurs (`mktemp`, `/tmp`). Claude Code ne sait pas découper ces commandes-là sans risque : chacune demanderait une autorisation à la personne qui suit le chantier, et la ferait attendre.
Le travail à contrôler n'est pas encore enregistré : `git status` et `git diff` le montrent ; lis-les avant tes essais, qui y apparaîtraient ensuite.

## But de la tâche A — Titre A
Parce que.

## Critères demandés à l'agent
1. Rend 42.
2. Rend 43.

## Périmètre autorisé
a.py, tests/test_a.py
S'y ajoute toujours le dossier `chantier/relais/`, où l'agent écrit sa fiche de relais : ces fiches sont toujours permises et ne comptent jamais comme un débord de périmètre.

## Le verdict précédent
Un premier vérificateur a refusé ce livrable. L'agent a repris son travail dans la même copie pour corriger ce qui était relevé. Voici ce verdict en entier :
[début du verdict précédent]
Verdict précédent...
[fin du verdict précédent]

## Ce que tu dois faire
Ce que le verdict précédent n'a pas recalé a déjà été vérifié : le refaire coûterait une vérification entière sans rien t'apprendre. Ta vérification porte sur la correction. `git diff` montre tout le livrable, pas seulement la correction : sers-toi du verdict pour savoir où regarder.
1. Pour chaque point recalé, vérifie par toi-même qu'il est corrigé, en exécutant réellement le code quand c'est possible.
2. Vérifie que ces corrections n'ont rien défait : relis le code qu'elles touchent et ce qui en dépend, et lance les tests qui portent dessus. Si une correction ajoute ou change un test, vérifie qu'il peut échouer. Fais tes essais dans ce dossier, comme dit plus haut, en remettant chaque fichier.
3. Ne refais pas le reste de la vérification. Si tu vois pourtant en chemin un défaut qui bloquerait (comportement faux, perte de travail, faille), recale pour lui aussi.
4. L'Atelier a rejoué après la correction les commandes de contrôle du projet :
- `pytest -q`
- `ruff check .`
Elles passent : rien de ce que ces tests couvrent n'a cassé. Ne relance pas toute la suite, seulement les tests qui portent sur les points corrigés.

## Suivi
Avant chaque étape de ton travail, écris sur une ligne à part : « Étape 2/5 : ce que tu vas faire », en quelques mots simples (le rang et le total sont une estimation, ajuste-les en route). La personne qui suit le chantier lit ces lignes pour savoir où tu en es.

## Si tu es empêché
Si une commande t'est refusée ou qu'un outil te manque (commande non permise, programme absent, réseau coupé), écris dans ton verdict une ligne qui commence par « EMPÊCHÉ : », au tout début de la ligne, sans tiret ni puce devant, suivie de la commande et du message reçu, tel quel. Par exemple :
EMPÊCHÉ : uv run pytest -q — (le message reçu)
Reporte la même chose dans le champ "empeche" du JSON, même si tu as pu conclure par un autre moyen. Sans ce signe, l'Atelier prendrait ton refus pour un défaut du livrable et relancerait l'agent pour rien : la vérification suivante buterait au même endroit. Avec lui, il demande à la personne le bon réglage.

## Ce que tu rends
Un court verdict en français, puis, sur la toute dernière ligne, un objet JSON seul :
{"valide": true ou false, "motif": "bacle" ou "ne_sait_pas" ou "consigne", "resume": "une ou deux phrases"}

- "bacle" : une partie de la consigne a été négligée, l'agent aurait pu le faire.
- "ne_sait_pas" : l'agent s'est trompé sur le fond.
- "consigne" : les critères sont ambigus ou ne suffisent pas à prouver le but.
- "empeche" : à ajouter à l'objet seulement si tu as été empêché de vérifier, un élément par empêchement : "empeche": ["la commande — le message reçu"].
Sois strict : n'écris "valide": true que pour ce que tu as constaté toi-même.
```

En lecture seule (et sans commande de contrôle au profil), seuls changent le cadre, la fin du point 2 et le point 4 :
```text
Tu ne modifies, ne crées et ne supprimes aucun fichier. Travaille dans le dossier courant.
Le travail à contrôler n'est pas encore enregistré : `git status` et `git diff` le montrent.
Pour tes commandes, une commande simple par appel : [... COMMANDES_SIMPLES en entier ...]
...
2. [...] Si une correction ajoute ou change un test, vérifie qu'il peut échouer. Tu ne peux rien écrire ici : juge-le en lisant le test et en le lançant.
...
4. Le projet n'a pas de commande de contrôle : lance les tests qui portent sur les points corrigés.
```

### 3. `consigne_verificateur_bornee` (V3e)

Chaque critère, et seulement ce qui bloquerait (comportement faux, perte de travail ou de données, faille). La fin de la sortie des contrôles est coupée à `SORTIE_BORNEE = 1500` caractères par la fonction elle-même : le moteur peut lui passer la sortie brute. Ni relance de la suite, ni mutation ; le cadre de la copie jetable est une variante sans la ligne des mutations (`COPIE_JETABLE_SANS_MUTATION`), pour ne pas se contredire. Champ facultatif `remarques` en plus de `empeche`.

Avec copie jetable :
```text
Tu es vérificateur. Tu contrôles le livrable d'un autre agent, sans rien corriger. Ta vérification est bornée : tu contrôles chaque critère et tu ne cherches que ce qui bloquerait.
Tu travailles dans une copie jetable du livrable : l'atelier la jette après ton verdict, et ce qu'il enregistre est le livrable de l'agent, pas cette copie. Tu ne corriges rien : une correction ne serait pas gardée. Mais tu peux y faire tes essais sans rien demander, à condition de t'y prendre ainsi :
- pour un essai de plus de quelques mots, écris un script dans ce dossier avec l'outil Write, puis lance-le (par exemple `python3 essai.py`) ;
- une commande simple par appel : pas de commandes enchaînées (`;`, `&&`, plusieurs lignes), pas de heredoc (`<<EOF`), pas de variable du shell (`$?`, `$(...)` : le code de retour de la commande t'est déjà donné), pas de `sed -i` ni de `rm -rf`, pas de dossier temporaire ailleurs (`mktemp`, `/tmp`). Claude Code ne sait pas découper ces commandes-là sans risque : chacune demanderait une autorisation à la personne qui suit le chantier, et la ferait attendre.
Le travail à contrôler n'est pas encore enregistré : `git status` et `git diff` le montrent ; lis-les avant tes essais, qui y apparaîtraient ensuite.

## But de la tâche A — Titre A
Parce que.

## Critères demandés à l'agent
1. Rend 42.
2. Rend 43.

## Périmètre autorisé
a.py, tests/test_a.py
S'y ajoute toujours le dossier `chantier/relais/`, où l'agent écrit sa fiche de relais : ces fiches sont toujours permises et ne comptent jamais comme un débord de périmètre.

## Les contrôles déjà faits
L'Atelier vient de faire passer les commandes de contrôle du projet sur ce livrable, et elles passent :
- `pytest -q`
- `ruff check .`
Voici la fin de ce qu'elles ont affiché :
[début de la sortie]
....
12 passed in 0.3s
[fin de la sortie]
Ne relance pas toute la suite : elle vient de passer sur ce code, la relancer coûterait des minutes sans rien t'apprendre. Lance seulement le test précis dont tu as besoin pour voir un comportement.

## Ce que tu dois faire
Cette tâche a été jugée assez simple pour une vérification bornée : une vérification complète, mutations comprises, y coûterait plus de temps qu'elle n'en ferait gagner. Les tâches délicates la gardent.
1. Vérifie chaque critère par toi-même : lis le code qui le remplit et le test qui le prouve, et lance ce test, ou un essai court, quand la lecture ne suffit pas. Un critère sans preuve n'est pas rempli.
2. Ne cherche que ce qui bloquerait : un comportement faux, une perte de travail ou de données, une faille de sécurité. Le reste (style, nom, commentaire, cas improbable) ne recale pas : note-le dans "remarques".
3. Ne fais pas de mutation (changer le code pour voir si un test échoue) : juge en lisant si chaque test vérifie bien ce qu'il annonce.

## Suivi
Avant chaque étape de ton travail, écris sur une ligne à part : « Étape 2/5 : ce que tu vas faire », en quelques mots simples (le rang et le total sont une estimation, ajuste-les en route). La personne qui suit le chantier lit ces lignes pour savoir où tu en es.

## Si tu es empêché
Si une commande t'est refusée ou qu'un outil te manque (commande non permise, programme absent, réseau coupé), écris dans ton verdict une ligne qui commence par « EMPÊCHÉ : », au tout début de la ligne, sans tiret ni puce devant, suivie de la commande et du message reçu, tel quel. Par exemple :
EMPÊCHÉ : uv run pytest -q — (le message reçu)
Reporte la même chose dans le champ "empeche" du JSON, même si tu as pu conclure par un autre moyen. Sans ce signe, l'Atelier prendrait ton refus pour un défaut du livrable et relancerait l'agent pour rien : la vérification suivante buterait au même endroit. Avec lui, il demande à la personne le bon réglage.

## Ce que tu rends
Un court verdict en français, puis, sur la toute dernière ligne, un objet JSON seul :
{"valide": true ou false, "motif": "bacle" ou "ne_sait_pas" ou "consigne", "resume": "une ou deux phrases"}

- "bacle" : une partie de la consigne a été négligée, l'agent aurait pu le faire.
- "ne_sait_pas" : l'agent s'est trompé sur le fond.
- "consigne" : les critères sont ambigus ou ne suffisent pas à prouver le but.
- "empeche" : à ajouter à l'objet seulement si tu as été empêché de vérifier, un élément par empêchement : "empeche": ["la commande — le message reçu"].
- "remarques" : à ajouter à l'objet seulement pour des défauts mineurs, qui ne recalent pas, un élément par remarque : "remarques": ["..."].
Sois strict sur ce qui bloque : n'écris "valide": true que pour ce que tu as constaté toi-même. Une remarque ne recale pas : un livrable correct avec des remarques est valide.
```

Sans commande de contrôle au profil, la rubrique « Les contrôles déjà faits » devient : « Le projet n'a pas de commande de contrôle : l'Atelier n'a rien fait passer. Lance toi-même les tests qui prouvent les critères. » En lecture seule, le cadre est celui de la seconde vérification (lecture seule plus `COMMANDES_SIMPLES`).

### 4. Les champs facultatifs du verdict, et `lire_verdict`

- La consigne complète reçoit, sous les trois motifs, la ligne :
  `- "empeche" : à ajouter à l'objet seulement si tu as été empêché de vérifier, un élément par empêchement : "empeche": ["la commande — le message reçu"].`
  La ligne principale du JSON ne change pas : un vérificateur qui recopie le modèle n'y ajoutera pas un `empeche` vide.
- La consigne bornée reçoit aussi : `- "remarques" : à ajouter à l'objet seulement pour des défauts mineurs, qui ne recalent pas, un élément par remarque : "remarques": ["..."].`
- `lire_verdict` rend `remarques` et `empeche` (constante `CHAMPS_FACULTATIFS`) en **listes de textes**, s'ils sont là et non vides. Une chaîne seule devient une liste d'un élément ; une valeur vide, un nombre, un objet ou des éléments qui ne sont pas des textes sont ignorés et la clé n'apparaît pas. Un verdict d'aujourd'hui se lit exactement comme avant : trois clés, rien de plus (le test d'origine de `tests/test_moteur.py` passe sans changement, et un test nouveau le redit). Un verdict illisible (sans `valide`) garde son `empeche` s'il en a un : un vérificateur qui n'a pas pu conclure parce qu'il était empêché reste reconnaissable par V3b.

### 5. La ligne « EMPÊCHÉ : »

Constante `MARQUE_EMPECHE = "EMPÊCHÉ :"`, le même texte que `refus.MARQUE_EMPECHEMENT` dans la copie V3refus (lue sans y toucher). `refus.py` ne reconnaît la marque qu'en tout début de ligne, après `strip()` : une puce `- EMPÊCHÉ :` ne serait pas lue. Les consignes le disent donc (« au tout début de la ligne, sans tiret ni puce devant ») et donnent un exemple écrit tel qu'attendu. Le compte rendu lu par le moteur est le dernier message de l'agent (`final.result` dans `sdk.py`) : la consigne de l'ouvrier dit « compte rendu final ».

Section ajoutée à la consigne de l'ouvrier (avant « À rendre ») :
```text
## Si tu es empêché
Si une commande t'est refusée ou qu'un outil te manque (commande non permise, programme absent, réseau coupé), écris dans ton compte rendu final une ligne qui commence par « EMPÊCHÉ : », au tout début de la ligne, sans tiret ni puce devant, suivie de la commande et du message reçu, tel quel. Par exemple :
EMPÊCHÉ : uv run pytest -q — (le message reçu)
L'Atelier lit ces lignes : il demande alors à la personne le bon réglage (permettre la commande, installer l'outil) au lieu de relancer ta tâche à l'aveugle, ce qui buterait au même endroit. Une autre commande permise qui fait le même travail reste bienvenue ; mais ne fais pas passer la commande refusée sous une autre forme (un autre shell, un script qui la lance) : la liste des commandes permises est un choix de la personne. Signale le refus dans les deux cas.
```

Section ajoutée aux trois consignes de vérification (après « Suivi ») :
```text
## Si tu es empêché
Si une commande t'est refusée ou qu'un outil te manque (commande non permise, programme absent, réseau coupé), écris dans ton verdict une ligne qui commence par « EMPÊCHÉ : », au tout début de la ligne, sans tiret ni puce devant, suivie de la commande et du message reçu, tel quel. Par exemple :
EMPÊCHÉ : uv run pytest -q — (le message reçu)
Reporte la même chose dans le champ "empeche" du JSON, même si tu as pu conclure par un autre moyen. Sans ce signe, l'Atelier prendrait ton refus pour un défaut du livrable et relancerait l'agent pour rien : la vérification suivante buterait au même endroit. Avec lui, il demande à la personne le bon réglage.
```

### 6. `message_de_diagnostic` et le paragraphe « Blocage » (V3b)

Le message commence par `MARQUE_BLOCAGE = "[Blocage signalé par l'atelier"`, que le paragraphe du rôle cite : l'orchestrateur reconnaît un message de l'atelier. Il cite la tâche (identifiant, titre, critères, périmètre), les `PREUVES_MAX = 5` derniers refus, chacun coupé à ses `PREUVE_MAX_CARACTERES = 2000` derniers caractères (la cause est à la fin d'un verdict ou d'une sortie de contrôles), et les empêchements. Une preuve peut être un texte ou une entrée d'historique (`tentative`, `origine`, `issue`, `detail`). Le bloc `atelier-outils` est décrit dans `ROLE_ORCHESTRATEUR` (clés `commandes_permises`, qui s'ajoute, et `commandes`, qui remplace la liste des contrôles ; le serveur en fait une demande « outils » par `extraire_outils` puis `_proposer_outils`) : le message y renvoie et précise les deux pièges, un lanceur général dans `commandes_permises` (il donnerait `Bash(bash:*)`) et une liste `commandes` partielle.

```text
[Blocage signalé par l'atelier : tâche A]
La tâche A — Titre A est bloquée : elle revient à la personne, et les autres tâches continuent. La relancer telle quelle ne changerait rien tant que la cause reste là.

Ce qu'elle devait faire :
1. Rend 42.
2. Rend 43.
Son périmètre : a.py, tests/test_a.py

Ses derniers refus, du plus ancien au plus récent :
1. tentative 1, controles, ne_sait_pas : uv: refusé
2. Les contrôles automatiques échouent : uv introuvable

Ce qui a empêché les agents de travailler :
- uv run pytest -q — Permission denied

Ce que l'atelier attend de toi :
1. Cherche la cause, en lecture seule : lis les refus, puis le code et les tests qu'ils citent. Une commande refusée, un outil absent, un critère impossible à tenir dans le périmètre, un test qui échoue pour une raison étrangère à la tâche ?
2. Si c'est une commande interdite aux agents, propose le réglage dans un bloc atelier-outils, sous la forme que décrit ton rôle ; l'état du chantier donne les commandes déjà permises. Dans « commandes_permises », mets le premier mot de la commande (par exemple uv), jamais un lanceur général (bash, sh, sudo, env, npx) : il permettrait aux agents de tout lancer. Ne mets « commandes » que si les contrôles eux-mêmes sont en cause, et alors leur liste entière, puisqu'elle remplace l'actuelle. Accepté, le réglage relance la tâche seule, au même niveau. Si c'est un outil absent de l'ordinateur, dis lequel : un réglage ne l'installe pas, sauf s'il suffit de permettre aux agents la commande qui l'installe.
3. Sinon, dis en quelques phrases simples ce qui bloque et ce que la personne peut faire : relancer au même niveau, relancer un cran plus haut, ou abandonner la tâche.
Permettre une commande reste la décision de la personne : dis-lui ce que le réglage permettrait aux agents, puis laisse-la choisir. Ne rends pas de bloc de plan : le plan ne change plus une fois le contrat validé.

```

Paragraphe ajouté à `ROLE_ORCHESTRATEUR`, entre « Outils du projet » et le bloc de plan :
```text
Blocage. Quand une tâche est bloquée (refusée plusieurs fois pour la même raison, ou un agent empêché de travailler par une commande refusée ou un outil absent), l'atelier t'envoie un message qui commence par « [Blocage signalé par l'atelier ». Il ne vient pas de la personne, mais c'est elle qui lira ta réponse : réponds-lui comme d'habitude. Ce message cite la tâche, ses derniers refus et ce qui a empêché les agents. Cherche la cause dans le dépôt, toujours en lecture seule. Si c'est une commande ou un outil, propose dans un bloc atelier-outils le plus petit réglage qui lève l'empêchement : accepté d'un clic, il prend effet aussitôt et la tâche peut repartir. Sinon, explique simplement ce qui bloque et ce que la personne peut choisir. Permettre une commande reste sa décision : dis ce que le réglage permettrait aux agents, sans insister.
```
Ce paragraphe vaut dès aujourd'hui, avant le serveur de V3b : il dit « accepté d'un clic, il prend effet aussitôt et la tâche peut repartir », vrai aujourd'hui comme après V3b. Le message de diagnostic, envoyé seulement par V3b, dit lui « Accepté, le réglage relance la tâche seule, au même niveau » (décision 5 de V3b).

### 7. Le fichier commun, la vraie dépendance, et l'ouvrier

**Vérification faite avant d'écrire la règle.** `ControlesGit.enregistrer` fait `git add -A` dans la copie de la tâche, enregistre, puis fusionne en avance rapide dans la branche principale ; `.gitignore` n'exclut pas `chantier/relais/` ; `hors_perimetre` ajoute `TOUJOURS_PERMIS = ("chantier/relais/*",)` au périmètre. La fiche entre donc bien dans la branche principale. Un test nouveau le prouve avec un vrai dépôt git (`test_la_fiche_de_relais_d_une_tache_entre_dans_la_branche_principale`) : la règle repose sur ce fait, il ne doit pas changer sans qu'on le voie. Une tâche de raccord, qui dépend des autres, part d'une copie de la branche principale où leurs fiches sont déjà.

Deux puces ajoutées à `REGLES_DECOUPAGE` (donc aux deux textes de l'orchestrateur), la première après « Ne déclare une dépendance... », la seconde après la puce de la tâche de raccord :
```text
- Une vraie dépendance se reconnaît aux contrôles. Chaque tâche est contrôlée seule, dans sa copie partie de la branche principale, avec toute la suite de tests du projet : une tâche dont le code a besoin de celui d'une autre pour passer ces contrôles (elle l'importe, l'appelle, ou ses tests s'en servent) en dépend vraiment, même sans fichier commun. Lancée sans elle, elle échouerait à coup sûr.
- Quand une règle du projet demande que chaque tâche touche un même fichier (une ligne au journal des décisions par tâche, par exemple), ce fichier n'entre dans le périmètre d'aucune tâche : sinon elles passeraient toutes l'une après l'autre. Chaque ouvrier écrit à la place, dans sa fiche de relais (`chantier/relais/<id de la tâche>.md`), ce qu'il y aurait mis : ce dossier est toujours permis, et la fiche entre dans la branche principale avec le travail de la tâche. La tâche de raccord dépend de ces tâches et recopie ces lignes dans le fichier ; écris-le dans ses critères, en nommant le fichier et les fiches à relire.
```

Ajouté à la consigne de l'ouvrier, après « Règles du projet » puis après « Suivi » :
```text
Si une règle du projet te demande de toucher un fichier hors de ton périmètre (une ligne au journal des décisions, par exemple), ne le touche pas : écris dans ta fiche de relais ce que tu y aurais mis. Le contrôle du périmètre refuserait ton travail, et les tâches qui travaillent en même temps que toi se heurteraient dans ce fichier commun ; la tâche de raccord recopiera ta ligne.

## Ta fiche de relais
`chantier/relais/A.md` est toujours permis, en plus de ton périmètre, et entre dans la branche principale avec ton travail : les tâches suivantes et la tâche de raccord le lisent. Écris-y ce qu'une tâche qui prend ta suite doit savoir, et ce qu'une règle du projet t'aurait fait écrire hors de ton périmètre. Si tu n'as rien à transmettre, ne la crée pas. Si elle existe déjà quand tu commences, elle vient d'un chantier précédent : remplace son contenu, l'ancien reste dans l'historique de git.
```
La consigne de l'ouvrier ne parlait jusqu'ici d'aucune fiche de relais : elle est introduite ici, facultative (voir Doutes).

### 7 bis. Les fiches de relais ne sont jamais un débord (accord de l'orchestrateur, après le premier rendu)

Constante partagée `RELAIS_PERMIS`, écrite une fois comme `COMMANDES_SIMPLES`, placée sous la ligne du périmètre dans les trois consignes de vérification (complète, bornée, seconde vérification), par la même fonction `_perimetre_verifie` :
```text
S'y ajoute toujours le dossier `chantier/relais/`, où l'agent écrit sa fiche de relais : ces fiches sont toujours permises et ne comptent jamais comme un débord de périmètre.
```
Test : `test_les_trois_verifications_savent_que_la_fiche_de_relais_n_est_pas_un_debord` (copie jetable et lecture seule) vérifie que la rubrique « Périmètre autorisé » de chacune vaut exactement le périmètre suivi de `RELAIS_PERMIS`. Montré en échec : la consigne complète remise à son ancienne rubrique, `2 failed, 39 passed` (les deux cas du paramètre), puis texte remis.

### 8. `tests/test_consignes.py`

41 cas : la reprise (verdict entier, fichiers en liste ou en texte, sortie des contrôles, brièveté pour chaque origine, origine inconnue, profil sans contrôles) ; la seconde vérification (verdict entier, points recalés, rien défait, pas le reste, même rubrique de verdict que la complète) ; la vérification bornée (fin de sortie de 1 500 caractères exactement, rien avant ; pas de relance, pas de mutation, cadre sans mutation, `remarques`) ; la marque et la ligne « EMPÊCHÉ » chez l'ouvrier et dans les trois vérifications, en copie jetable et en lecture seule ; `REGLES_DECOUPAGE` dans les deux textes de l'orchestrateur ; `COMMANDES_SIMPLES` chez l'ouvrier et les vérificateurs ; les deux règles nouvelles du découpage et celle de l'ouvrier ; la fiche toujours permise et entrée dans la branche principale ; la lecture du verdict avec et sans `remarques` et `empeche`, six valeurs mal formées, le verdict illisible ; le message de diagnostic (contenu, cinq dernières preuves, preuve coupée par le début, sans empêchement) ; le paragraphe « Blocage » ; la phrase des fiches de relais dans les trois vérifications.

**Trois tests montrés en échec quand on retire ce qu'ils gardent** (retrait à la main, test lancé, texte remis, puis contrôle que les sorties des consignes sont redevenues identiques) :
- sortie non bornée (`fin = (sortie or "").strip() ...` au lieu de `[-SORTIE_BORNEE:]`) : `FAILED tests/test_consignes.py::test_la_verification_bornee_recoit_la_fin_de_la_sortie_bornee_a_1500_caracteres`, `1 failed, 38 passed` ;
- puce du fichier commun retirée de `REGLES_DECOUPAGE` : `FAILED tests/test_consignes.py::test_le_decoupage_sort_le_fichier_commun_des_taches_et_le_confie_au_raccord`, `1 failed, 38 passed` ;
- boucle des champs facultatifs retirée de `lire_verdict` : `FAILED ...::test_le_verdict_rend_remarques_et_empeche_quand_ils_sont_la` et `FAILED ...::test_un_verdict_illisible_garde_son_empechement`, `2 failed, 37 passed`.

### 9. Rien ne change pour le moteur d'aujourd'hui

- Signatures inchangées : `consigne_ouvrier`, `consigne_verificateur`, `consigne_planification`, `lire_verdict`, `extraire_plan`, `extraire_outils`, `dernier_json`, `message_avec_etat`, et les constantes `SUIVI`, `COMMANDES_SIMPLES`, `COPIE_JETABLE`, `LECTURE_SEULE`, `REGLES_DECOUPAGE`, `ROLE_ORCHESTRATEUR`, `BALISE_PLAN`, `BALISE_OUTILS`.
- J'ai comparé, avant et après, la sortie de chaque consigne existante (script hors de la copie, `diff` ligne à ligne). `COPIE_JETABLE` : identique, octet pour octet, bien qu'elle soit maintenant bâtie par `_copie_jetable(mutations=True)`. Consigne complète du vérificateur, en copie jetable comme en lecture seule : seulement trois ajouts, la section « Si tu es empêché » (5 lignes, après « Suivi »), la ligne du champ `empeche`, et la phrase `RELAIS_PERMIS` sous le périmètre (ajoutée après accord de l'orchestrateur). Consigne de l'ouvrier, planification, rôle de l'orchestrateur : seulement des ajouts, aucune ligne retirée ni changée.
- Aucun test existant n'a été modifié : je n'ai remplacé aucune phrase, seulement ajouté. Il n'y a donc pas d'« avant et après » à donner.

## Fichiers touchés
- `atelier/consignes.py`
- `tests/test_consignes.py` (nouveau)
- `chantier/relais/V3-consignes.md` (cette fiche)

## Contrats

```python
def consigne_reprise(tache: Tache, origine: str, complet: str | list[str], profil: dict) -> str
    # origine : "verdict", "perimetre" ou "controles", sinon ValueError.
    # complet est rendu en entier : au moteur de le borner (V3a : 8 000 / 4 000 caractères).
def consigne_reverification(tache: Tache, contrat: Contrat, profil: dict,
                            verdict_precedent: str, copie_jetable: bool = False) -> str
def consigne_verificateur_bornee(tache: Tache, contrat: Contrat, profil: dict,
                                 sortie_controles: str, copie_jetable: bool = False) -> str
    # coupe elle-même sortie_controles à ses SORTIE_BORNEE derniers caractères.
def message_de_diagnostic(tache: Tache, preuves: list, empechements: list[str]) -> str
    # preuves : textes ou entrées d'historique, du plus ancien au plus récent ;
    # seules les PREUVES_MAX dernières sont citées, chacune coupée à PREUVE_MAX_CARACTERES.
def lire_verdict(texte: str) -> dict
    # inchangé, plus "remarques": list[str] et "empeche": list[str] quand ils sont là et non vides.
```
Constantes nouvelles : `MARQUE_EMPECHE = "EMPÊCHÉ :"`, `MARQUE_BLOCAGE = "[Blocage signalé par l'atelier"`, `SORTIE_BORNEE = 1500`, `PREUVES_MAX = 5`, `PREUVE_MAX_CARACTERES = 2000`, `CHAMPS_FACULTATIFS = ("remarques", "empeche")`, `REPRISES` (constat et correction par origine), `EMPECHE_OUVRIER`, `EMPECHE_VERIFICATEUR`, `COPIE_JETABLE_SANS_MUTATION`, `RELAIS_PERMIS`.

## Reste à faire
- **V3a** : appeler `consigne_reprise` avec, selon l'origine, le texte entier du vérificateur (`avis.texte`, que `lire_verdict` ne rend pas : le moteur doit le garder), la liste `dehors` de `_juger`, ou la fin de la sortie de `mecaniques` ; appeler `consigne_reverification` avec le texte entier du premier vérificateur.
- **V3b** : lire `verdict.get("empeche")` (liste) ; si le moteur passe aussi le texte du vérificateur à `refus.empechements`, la ligne « EMPÊCHÉ : » de son verdict compte en plus. Le serveur envoie `message_de_diagnostic` dans la conversation (par `_interroger`, qui y ajoute l'état du chantier, où figurent les commandes permises). Garder `MARQUE_EMPECHE` et `refus.MARQUE_EMPECHEMENT` égales ; une fois les deux entrés, `consignes.py` peut importer la constante de `refus.py`, qui n'importe rien d'Atelier.
- **V3e** : appeler `consigne_verificateur_bornee` avec la sortie brute de `mecaniques` ; faire quelque chose de `verdict.get("remarques")` (fil ou historique) ; compter les fichiers modifiés **hors** `chantier/relais/` pour la règle « mécanique seule sans fichier modifié », sinon une fiche de relais suffirait à passer pour un livrable.

## Doutes
1. **La fiche de relais n'existait pas pour l'ouvrier du produit.** Sa consigne demandait un compte rendu dans la réponse, jamais de fichier. Je l'ai introduite **facultative** : il l'écrit quand il a quelque chose à transmettre, et toujours quand une règle du projet lui ferait toucher un fichier hors périmètre. La reprise dit donc « Si tu tiens une fiche de relais, mets-la à jour ». Je ne l'ai pas rendue obligatoire : chaque tâche ajouterait un fichier au dépôt de la personne. L'orchestrateur a confirmé ce choix. Pour la rendre obligatoire, une phrase suffit dans « Ta fiche de relais ».
2. **Réglé après accord de l'orchestrateur** : un vérificateur complet aurait pu recaler une fiche de relais comme « hors périmètre ». Les trois vérifications portent maintenant `RELAIS_PERMIS` (voir 7 bis).
3. **Une fiche d'un chantier précédent au même identifiant.** Les archives ne rangent pas `chantier/relais/`. La consigne dit de remplacer son contenu, l'ancien restant dans l'historique de git. Une tâche de raccord qui relirait la fiche d'une tâche qui n'en a pas écrit lirait l'ancienne ; ses critères nomment les fiches à relire, mais le risque reste.
4. **Le vérificateur complet en lecture seule** ne reçoit pas `COMMANDES_SIMPLES`, et sa consigne dit « Fais tes essais sur une copie hors du dépôt », ce qui contredit « pas de dossier temporaire ailleurs ». C'était déjà ainsi ; figé par le critère 9. Les deux consignes nouvelles, en lecture seule, ont `COMMANDES_SIMPLES` et ne parlent pas de copie ailleurs.
5. **`rm <chemin>` dans la reprise après débord** passe sans carte dans le mode par défaut des ouvriers (« Accepter les modifications ») ; dans le mode « default », il en ouvrirait une. `git restore` aurait demandé une carte dans tous les modes (il n'est pas dans `GIT_LECTURE`).
6. **Les tâches qui ne doivent s'accorder que sur une interface** : la puce nouvelle (« une tâche dont le code a besoin de celui d'une autre pour passer ces contrôles en dépend vraiment ») complète celle qui les fait partir ensemble ; les deux ne se contredisent que si les tests d'une tâche appellent le code de l'autre, ce qui est justement le cas d'une vraie dépendance.

## Résultats

- Tests : `/tmp/claude-0/-home-user-atelier/d04ea8ab-c665-54ab-9a3a-d57048e9c6b4/scratchpad/venv/bin/python -m pytest -q` : **914 passed** (873 d'avant, inchangés, et 41 nouveaux).
- Contrôle de forme : `... -m ruff check .` : **All checks passed!**
