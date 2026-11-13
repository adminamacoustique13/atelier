# Cahier des charges — chantier « quatre trous » (2026-11-13)

État : en cours. Contrat : `chantier/CONTRAT.md`. Base : la branche de la demande n°11 (3464513), 1 763 tests verts, contrôle de forme propre. Les quatre tâches partent ensemble, chacune dans sa copie de travail, sur des fichiers distincts. Référence commune : la ligne « PC et autonomie » (5f2c337), lue mais jamais fusionnée.

| Tâche | État | Ouvrier | Vérification | Tentatives | Preuve |
|---|---|---|---|---|---|
| P1. Le serveur local refuse une demande venue d'un autre site | vérifié | Opus, effort élevé | complète, Fable : accepté du premier coup, aucun défaut bloquant | 1 | 53 tests de l'ouvrier (44 échouaient avant) et 35 du vérificateur ; attaques réelles depuis Chrome sans aucune réponse 2xx ; 56 mutations, 43 tuées par l'ouvrier, toutes sauf deux avec les compléments ; suite 1 881, ruff propre, huit essais verts |
| P2. Seul un vrai `true` du vérificateur vaut accord | vérifié | Sonnet, effort moyen | mécanique : 8 tests échouaient sur l'ancien code (rejoués par l'orchestrateur) | 1 | 15 tests ajoutés ; suite 1 793, ruff propre ; enregistré 99a111e |
| P3. Secrets illisibles et git en écriture refusés d'office à tout agent | reprise rendue, en seconde vérification | Opus, effort élevé | complète, Fable : refusé une fois | 1 + 1 reprise | git classé en entier (26 lectures permises, tout le reste refusé, un test lit la liste du git installé) ; tous les lancements d'agent recensés ; 505 tests de sécurité ; 1 394 règles, rejouées sans écart sur les vraies fonctions de Claude Code |
| P4. Un fichier au nom accentué est reconnu dans son périmètre | vérifié | Sonnet, effort moyen | mécanique : 9 tests sur 15 échouaient sur l'ancien code (rejoués par l'orchestrateur) | 1 | 15 tests nouveaux ; suite 1 778 puis 1 793 avec P2, ruff propre ; enregistré 7b75090 |
| V1. Maquettes de la Salle à plusieurs agents et de l'état du dépôt (hors produit) | choisie par la personne responsable le 2026-11-13 : piste B (les postes), et l'onglet « Dépôt » | Fable, effort élevé | par la personne responsable, sur les images | 1 + 1 reprise | trois pages, second jeu à 32 places, quatorze images ; fiche `chantier/relais/V1.md` |
| D1. Lecture de l'état du dépôt dans git, pour l'onglet « Dépôt » (fond) | refusée une fois, en reprise à chaud | Sonnet, effort élevé | bornée, Opus : refusé pour un seul défaut (une tâche dite « entrée » sur le seul début d'un message, le critère 3 ne disant pas comment reconnaître une entrée) | 1 + 1 reprise | 79 tests ; aucune écriture, y compris index périmé ; douze tâches en 0,14 s |
| D2. Onglet « Dépôt » : la vue du serveur, la page, un essai | à lancer après M13 (même fonction `vue`, même page) | Sonnet, effort moyen | bornée | | |
| S1. Fond de la Salle : par tâche, la place et le jeton tenus, ce qu'attend une tâche à lancer, l'ouvrier ouvert, la sous-tâche, le budget | à lancer après la vague 2 (elle fixe ces données) | Opus, effort élevé | bornée | | |
| S2. Page de la Salle, piste B, de 6 à 32 places, avec ses essais | à lancer après S1 | Sonnet, effort élevé | bornée, puis les images montrées à la personne responsable | | |
| M1. Formats (état, résultat d'un agent, dosage) | vérifié | Sonnet, effort moyen | mécanique et lecture du diff par l'orchestrateur, à la place de la vérification bornée prévue : 16 tests sur 21 échouaient sur l'ancien code, les trois fonctions de dosage sont identiques à la référence (arbres de syntaxe comparés), aucun test existant touché | 1 | 59 tests ajoutés, 3 mutations tuées par l'ouvrier ; suite 1 940 avec P1, ruff propre |
| M2. Consignes (preuve par critère, contrôles non rejoués, sous-tâche, verdict local) | vérifié | Sonnet, effort élevé | bornée, Opus : refusé une fois (deux phrases qui rendaient le vérificateur complaisant, venues des critères 3 et 5 de l'orchestrateur), accepté à la seconde passe par le même vérificateur repris à chaud | 1 + 1 retouche de consigne + 1 reprise | 140 tests ajoutés ; textes par défaut figés par empreinte, recalculée par le vérificateur ; chaque phrase fautive remise fait tomber des tests |
| M3. Agents : l'ouvrier reste ouvert | rendue, en reprise d'arbitrage | Opus, effort élevé | complète, Fable, après la reprise | 1 + 1 reprise (arbitrage : un ouvrier n'est gardé ouvert que si l'appelant le demande, `executer(..., garder_ouvert=True)`, parce que rien ne libère encore les ouvriers avant M9 et que la garde des tests existants a raison ; `liberer` borné dans le temps) | 50 tests, tous en échec sur la base ; 10 mutations tuées |
| M4. Pont : coût juste et nature des échecs | rendue après une reprise d'arbitrage, à vérifier | Opus, effort élevé | complète, Fable | 1 + 1 reprise (trois arbitrages : trois tests existants mis à jour, suite ramenée de 72 à 47 s, registre des cumuls par session) | 70 tests, tous en échec sur la base ; 15 mutations tuées |
| M5. Vérification : niveaux, retouche, contrôles non rejoués | rendue, à vérifier | Opus, effort élevé | complète, Fable | 1 | 34 tests, tous en échec sur la base ; 15 mutations tuées ; huit essais verts ; sept tests existants réécrits (21 cas, liste dans la fiche) ; à la réunion avec M6, un de ses tests attend sans fin (une « panne » simulée déclenche la patience) : à régler dans le test |
| M6. Pannes d'agent : patienter | refusée une fois, en reprise à chaud | Opus, effort élevé | complète, Fable : refusé (une panne faisait compter une montée et défaisait la règle de blocage, faute des deux filtres que l'ouvrier avait demandés ; une alternance de pannes et de surcharges tournait sans fin, à cause du critère 2 de l'orchestrateur) | 1 + 1 reprise | 68 tests ; 41 mutations, 38 tuées ; aucun interblocage ni place perdue |
| M7. Reprise seule après un arrêt | vérifié | Opus, effort élevé | complète, Fable : accepté du premier coup, aucun défaut bloquant ; vrais lancements à deux processus, dix courses, cinq arrêts brutaux | 1 | 43 tests ; 31 mutations, 22 tuées (les autres sont des trous de tests, le code est juste) ; suite 2 123, ruff propre, huit essais verts ; reste : « Arrêter » n'annule pas encore la relance annoncée (page, M13) |
| M8. Le travail refusé est gardé | reprise rendue, en seconde vérification | Opus, effort élevé | complète, Fable : refusé une fois | 1 + 1 reprise | 54 tests ; la liste des marqueurs de conflit vit à côté de la copie et survit à un redémarrage ; copies jetées avant « nouveau chantier » ; une tâche ne reprend que sa propre copie |
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
- M2 : pour le moteur (M5, M9, M10). Passer `genre="verdict"` à `consigne_sous_tache` pour un reste venu d'un verdict `bacle` ou `local`, jamais le motif. Une retouche (`consigne_reverification` avec `fichiers`) suppose le reste déjà jugé par un vérificateur : après une sous-tâche de genre `controles` ou vide, lancer une vérification ordinaire. Une ligne « EMPÊCHÉ : » peut désormais nommer un fichier demandé par un point à régler, et pas seulement une commande refusée. « Aucun autre fichier n'est permis » ne rappelle pas que la fiche de relais reste permise.

## Raccords demandés par les ouvriers de la vague 1 (à confier aux vagues 2 et 3)
- M6 : `attente_panne` doit être sauté par `_fenetre` (M11), par `_passes_du_depart` (M9) et par `serveur.statistiques` (M13) ; `archives.GROUPES` doit apprendre la phase « panne » (M13). Qui réécrit `_boucle` garde l'appel à `_suspendre` sur chaque résultat d'ouvrier et le `tentatives -= 1` qui suit un vrai.
- M7 : brancher « Arrêter » sur le délai de relance (`Atelier.annuler_reprise()` existe ; il manque `Atelier.arreter`, la vue et la page : M13) ; rendre aussi le numéro d'une sous-tâche coupée (M10) ; `interrompue` hors des preuves d'un blocage (M11) ; `_demander` ne dit pas « travail gardé » pour une tâche arrêtée par l'Atelier puis rendue avec sa copie.
- M8 : `serveur.nouveau_chantier` doit appeler `moteur.jeter_les_copies_gardees()` avant d'archiver (M13) ; `_reprise` dit encore « je jette sa copie » (M9) ; les marqueurs de conflit suivis en mémoire se perdent au redémarrage (à juger par le vérificateur de M8).
- M7 (vérificateur) : à reprendre dans une tâche de raccord. Le fichier de verrou supprimé à la main laisse s'ouvrir un second Atelier (comparer l'inode avant de relancer) ; `reprise_auto: false` posé après une interruption déjà notée laisse la tâche « à lancer » sans demande ; une tâche suspendue pour limite rend son numéro deux fois ; une condition perdue pendant le délai laisse l'annonce sans démenti ; au lancement seul le projet ouvert reprend, un autre reprend quand on l'ouvre quel que soit l'âge de son état ; passer aussi `test_une_tache_rendue_au_redemarrage_n_a_aucune_duree_mesuree` à `reprise_auto: false` ; sept trous de tests (dont `reprise_auto` ignoré côté serveur et les conditions non relues en fin de délai).

## Relevés des ouvriers, hors périmètre
- P3 : pendant sa reprise, l'ouvrier a effacé 171 fichiers `atelier-refus-*.json` du dossier temporaire commun, sans savoir s'ils étaient tous à lui (une seconde suppression a été refusée par l'arbitre). Fichiers jetables de tests ; à retenir : les tests du pont doivent écrire leurs réglages dans un dossier à eux.
- V1 : la maquette suppose qu'un ouvrier resté ouvert garde sa place d'écriture ; le plan du moteur dit le contraire (ni place ni jeton pendant qu'il attend). À corriger dans l'exemple au moment du code : cinq places prises, pas six. La vue du serveur donne déjà `debit` (places, agents en marche, suspensions), que la page n'affiche nulle part.
- P4 : `atelier/essai.py:358` lit `git ls-files` sans `-z` puis coupe aux espaces ; sans effet aujourd'hui (l'essai ne livre que `calcul.py`).
- P2 : aucun autre booléen venu d'un agent n'est lu par sa seule vérité.

## Bases de travail de la vague 1
Les tâches partent sans attendre les vérifications en cours. M6 et M7 partent de 7d41ef1 (M1 enregistrée). M3 et M4, qui touchent `agents.py` et `sdk.py`, partent d'une base locale non poussée qui ajoute P3 (8a6ba8a). M8 part de la même base plus M2 (c21b72e). Seul le travail vérifié entre dans la branche poussée ; si une vérification fait changer P3 ou M2, les tâches parties dessus sont réunies sur la version corrigée.

## Incident de lancement
Les quatre copies de travail des ouvriers ont été créées sur `main` (9d4cf2c) au lieu de la branche de travail. Vu avant toute modification : l'orchestrateur les a replacées sur a862a2f et a prévenu chaque ouvrier de relire ses fichiers. À refaire à chaque lancement en copie isolée : vérifier le commit de départ.

## Noté par la personne responsable pour la suite (hors de ce chantier)
- Visualisation, relevé le 2026-11-13 : la Salle (la vue en trois dimensions) ne montre pas le nombre réel d'agents au travail, et sa route en S est à revoir avec plusieurs agents en même temps ; l'état du dépôt git n'est visible nulle part (branches créées, fusions, demandes de fusion). Les maquettes (tâche V1) sont lancées le même jour, à la demande de la personne ; le code attend son choix.
- À discuter ensuite : les points 3 (tourner seul sur un vrai projet) et 4 (ce qui n'est pas à reprendre tel quel) de la comparaison.
