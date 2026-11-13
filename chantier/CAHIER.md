# Cahier des charges — chantier « quatre trous » (2026-11-13)

État : en cours. Contrat : `chantier/CONTRAT.md`. Base : la branche de la demande n°11 (3464513), 1 763 tests verts, contrôle de forme propre. Les quatre tâches partent ensemble, chacune dans sa copie de travail, sur des fichiers distincts. Référence commune : la ligne « PC et autonomie » (5f2c337), lue mais jamais fusionnée.

| Tâche | État | Ouvrier | Vérification | Tentatives | Preuve |
|---|---|---|---|---|---|
| P1. Le serveur local refuse une demande venue d'un autre site | vérifié | Opus, effort élevé | complète, Fable : accepté du premier coup, aucun défaut bloquant | 1 | 53 tests de l'ouvrier (44 échouaient avant) et 35 du vérificateur ; attaques réelles depuis Chrome sans aucune réponse 2xx ; 56 mutations, 43 tuées par l'ouvrier, toutes sauf deux avec les compléments ; suite 1 881, ruff propre, huit essais verts |
| P2. Seul un vrai `true` du vérificateur vaut accord | vérifié | Sonnet, effort moyen | mécanique : 8 tests échouaient sur l'ancien code (rejoués par l'orchestrateur) | 1 | 15 tests ajoutés ; suite 1 793, ruff propre ; enregistré 99a111e |
| P3. Secrets illisibles et git en écriture refusés d'office à tout agent | en cours | Opus, effort élevé | complète, Fable | 1 | |
| P4. Un fichier au nom accentué est reconnu dans son périmètre | vérifié | Sonnet, effort moyen | mécanique : 9 tests sur 15 échouaient sur l'ancien code (rejoués par l'orchestrateur) | 1 | 15 tests nouveaux ; suite 1 778 puis 1 793 avec P2, ruff propre ; enregistré 7b75090 |
| V1. Maquettes de la Salle à plusieurs agents et de l'état du dépôt (hors produit) | en cours | Fable, effort élevé | par la personne responsable, sur les images | 1 | |
| M1. Formats (état, résultat d'un agent, dosage) | en cours | Sonnet, effort moyen | bornée | 1 | |
| M2. Consignes (preuve par critère, contrôles non rejoués, sous-tâche, verdict local) | en cours | Sonnet, effort élevé | bornée | 1 | |
| M3. Agents : l'ouvrier reste ouvert | à lancer (vague 1) | Opus, effort élevé | complète | | |
| M4. Pont : coût juste et nature des échecs | à lancer (vague 1) | Opus, effort élevé | complète | | |
| M5. Vérification : niveaux, retouche, contrôles non rejoués | à lancer (vague 1) | Opus, effort élevé | complète | | |
| M6. Pannes d'agent : patienter | à lancer (vague 1) | Opus, effort élevé | complète | | |
| M7. Reprise seule après un arrêt | à lancer (vague 1) | Opus, effort élevé | complète | | |
| M8. Le travail refusé est gardé | à lancer (vague 1) | Opus, effort élevé | complète | | |
| M9. Retours à l'ouvrier ouvert | à lancer (vague 2) | Opus, effort élevé | complète | | |
| M10. Sous-tâche | à lancer (vague 2) | Opus, effort élevé | bornée | | |
| M11. Après un refus | à lancer (vague 2) | Opus, effort élevé | complète | | |
| M12. Budget | à lancer (vague 2) | Fable, effort élevé | complète | | |
| M13. Page | à lancer (vague 3) | Sonnet, effort moyen | bornée | | |
| M14. Épreuves d'ensemble et démonstration | à lancer (vague 3) | Sonnet, effort élevé | bornée | | |

Les fiches M1 à M14 (critères, périmètres, contrats, vagues, risques) sont dans `chantier/MOTEUR.md`.

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

## Écarts acceptés en route
- P4 : pour un renommage, `fichiers_modifies` rend désormais l'ancien et le nouveau nom (avant : le nouveau seul). La disparition de l'ancien fichier est bien une modification, et un ancien nom hors périmètre doit se voir.
- P1 : l'essai `G-mise-a-jour.js` envoyait à sa ligne 153 un POST sans `Content-Type`, exactement ce que la protection refuse ; l'orchestrateur a ajouté l'en-tête JSON à cette seule ligne (exception arbitrée, jugée juste par le vérificateur : la page n'envoie que du JSON). Les 35 tests du vérificateur entrent tels quels dans `tests/test_serveur_origine_complement.py`.

## Peut attendre (relevé par les vérificateurs)
- P1 : un lien cliqué depuis un autre site vers le tableau de bord est refusé (403), et le rechargement aussi : il faut retaper l'adresse. À adoucir pour la seule page, qui ne porte aucun secret. Une ligne de demande HTTP/0.9 lève une exception (rien n'est servi). Depuis le tableau seulement, un champ du mauvais type (`{"texte": 3}`) ou un JSON très imbriqué coupe la connexion, comme avant. Deux mutations survivent : une phrase de refus en anglais, un accord croisé sur un seul 404.

## Relevés des ouvriers, hors périmètre
- P4 : `atelier/essai.py:358` lit `git ls-files` sans `-z` puis coupe aux espaces ; sans effet aujourd'hui (l'essai ne livre que `calcul.py`).
- P2 : aucun autre booléen venu d'un agent n'est lu par sa seule vérité.

## Incident de lancement
Les quatre copies de travail des ouvriers ont été créées sur `main` (9d4cf2c) au lieu de la branche de travail. Vu avant toute modification : l'orchestrateur les a replacées sur a862a2f et a prévenu chaque ouvrier de relire ses fichiers. À refaire à chaque lancement en copie isolée : vérifier le commit de départ.

## Noté par la personne responsable pour la suite (hors de ce chantier)
- Visualisation, relevé le 2026-11-13 : la Salle (la vue en trois dimensions) ne montre pas le nombre réel d'agents au travail, et sa route en S est à revoir avec plusieurs agents en même temps ; l'état du dépôt git n'est visible nulle part (branches créées, fusions, demandes de fusion). Les maquettes (tâche V1) sont lancées le même jour, à la demande de la personne ; le code attend son choix.
- À discuter ensuite : les points 3 (tourner seul sur un vrai projet) et 4 (ce qui n'est pas à reprendre tel quel) de la comparaison.
