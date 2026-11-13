# Cahier des charges — chantier « quatre trous » (2026-11-13)

État : en cours. Contrat : `chantier/CONTRAT.md`. Base : la branche de la demande n°11 (3464513), 1 763 tests verts, contrôle de forme propre. Les quatre tâches partent ensemble, chacune dans sa copie de travail, sur des fichiers distincts. Référence commune : la ligne « PC et autonomie » (5f2c337), lue mais jamais fusionnée.

| Tâche | État | Ouvrier | Vérification | Tentatives | Preuve |
|---|---|---|---|---|---|
| P1. Le serveur local refuse une demande venue d'un autre site | en cours | Opus, effort élevé | complète, Fable | 1 | |
| P2. Seul un vrai `true` du vérificateur vaut accord | en cours | Sonnet, effort moyen | mécanique : test qui échouait avant | 1 | |
| P3. Secrets illisibles et git en écriture refusés d'office à tout agent | en cours | Opus, effort élevé | complète, Fable | 1 | |
| P4. Un fichier au nom accentué est reconnu dans son périmètre | en cours | Sonnet, effort moyen | mécanique : test qui échouait avant | 1 | |

## P1. Le serveur local refuse une demande venue d'un autre site
Périmètre : `atelier/serveur.py` (la classe `Requetes` et `creer_serveur`), `tests/test_serveur_origine.py` (nouveau).
1. Une demande dont l'en-tête `Host` n'est ni `127.0.0.1:<port>` ni `localhost:<port>` est refusée (403), lecture comme écriture, sans rien exécuter.
2. Une demande qui porte un en-tête `Origin` autre que `http://127.0.0.1:<port>` ou `http://localhost:<port>` est refusée (403).
3. Une demande qui porte `Sec-Fetch-Site` autre que `same-origin` ou `none` est refusée (403).
4. Une écriture (POST) dont le `Content-Type` n'est pas `application/json` est refusée, sans rien exécuter.
5. Le serveur ne donne jamais d'accord à un autre site : aucun en-tête `Access-Control-Allow-*`, et `OPTIONS` n'aboutit pas.
6. Un corps illisible (longueur invalide, JSON invalide, JSON qui n'est pas un objet) reçoit une réponse 400 en JSON au lieu d'une connexion coupée.
7. Le tableau de bord marche comme avant : la suite et les huit essais de `chantier/essais/` restent verts, sans les modifier.

## P2. Seul un vrai `true` du vérificateur vaut accord
Périmètre : `atelier/consignes.py` (`lire_verdict`), `tests/test_consignes.py` (ajouts).
1. `"valide": true` vaut accord ; toute autre valeur (`"false"`, `"true"`, `1`, `"oui"`, `null`, une liste) vaut refus.
2. Le motif et le résumé donnés par le vérificateur sont gardés tels quels dans ce refus.
3. Un test échoue sur le code actuel avec `"valide": "false"` et passe après.

## P3. Secrets illisibles et git en écriture refusés d'office à tout agent
Périmètre : `atelier/agents.py`, `atelier/sdk.py`, `tests/test_securite.py` (nouveau), `LISEZMOI.md` (le passage sur les autorisations).
1. Une seule fonction donne les interdits d'un agent ; chaque lancement réel (ouvrier, vérificateur, orchestrateur) les transmet au SDK comme refus d'office, qui l'emportent sur toute permission et sur le guichet.
2. Les fichiers de secrets (liste d'origine, plus la clé de profil `secrets`) ne peuvent être ni lus ni écrits par les outils de fichiers, ni nommés dans une commande.
3. Une clé `secrets` mal formée est ignorée sans erreur, et la liste d'origine reste.
4. Toute commande git qui modifie le dépôt ou ses réglages est refusée à tout agent ; les lectures git déjà permises le restent.
5. Les contournements connus de la référence sont fermés : une option glissée avant le geste (`git branch -v -D x`, `git remote -v set-url …`).
6. La démonstration marche sans rien changer, et aucune commande de contrôle des profils existants n'est refusée.
7. LISEZMOI dit ce qui est refusé, comment régler `secrets`, et la limite : une barrière sur le texte des commandes, pas une isolation.

## P4. Un fichier au nom accentué est reconnu dans son périmètre
Périmètre : `atelier/controles.py` (la lecture des fichiers modifiés), `tests/test_perimetre_accents.py` (nouveau).
1. Dans un vrai dépôt git, une tâche dont le périmètre nomme `docs/été.md` et qui le modifie n'a aucun débord (le test échoue sur le code actuel).
2. Même résultat pour un nom avec une espace, un nom avec un guillemet, un fichier nouveau et un fichier renommé.
3. Un fichier accentué hors périmètre est signalé sous son vrai nom.
4. Le résultat ne dépend pas du réglage `core.quotePath` de la machine.
