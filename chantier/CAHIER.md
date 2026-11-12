# Cahier des charges — chantier « débit » (2026-11-12)

Contrat : `chantier/CONTRAT.md`. Les trois tâches partent ensemble, chacune dans sa copie de travail ; elles touchent `atelier/moteur.py` dans des fonctions distinctes et sont réunies à l'intégration.

| Tâche | État | Ouvrier | Vérification | Tentatives | Preuve |
|---|---|---|---|---|---|
| F1. Fichiers partagés et leur fusion | revenue vers la personne responsable : seconde vérification refusée pour un point (une montée à tort après un arrêt puis « Relancer au même niveau »), enveloppe de deux passages atteinte | Opus | complète, Opus : refusé deux fois | 1 + 1 reprise | suite 1 697 dans sa copie, 25 tests de fusion |
| F2. V3f : six places, vérificateur hors place, réveil, régulateur | reprise à chaud (vérificateur : code juste, deux tests manquants, priorité inversée) | Opus | complète, Opus : refusé une fois | 1 + 1 reprise | suite 1 686 dans sa copie (2 tests de mesure réécrits et 1 retiré-remplacé, à juger par le vérificateur), 8 essais verts |
| F3.1. Un outil refusé ne bloque que si un contrôle du projet en a besoin ; même règle pour le vérificateur | vérifié | Opus | bornée, Opus : accepté | 1 + 1 retouche de mots | 16 tests nouveaux qui échouaient sur F3 ; 3 tests de F3 réécrits (critères changés) ; suite 1 707 |
| F5. Un plan trop étroit est élargi avant d'être proposé (la forme du plan, écrite en V1, n'était branchée nulle part) | reportée à un prochain chantier (arrêtée sur décision de la personne responsable) | Opus | | | |
| F4. Un chemin à crochets se reconnaît lui-même dans un périmètre (relevé par F1) | prête, entre derrière F1 (refaite sur sa seconde version) | Sonnet | mécanique : 3 tests qui échouaient avant | 1 | 4 tests ; suite F1+F3+F4 réunies : 1 712 verts, ruff propre |
| F3. V3b.1 : pas de blocage sur un outil refusé sans rapport ; relance par une méthode nommée | vérifié | Opus | bornée, Opus : accepté | 1 + 1 reprise | 19 tests nouveaux, 16 mutations sur 18 attrapées (les 2 autres sans effet réel) ; suite 1 691, 8 essais verts |

## F1. Fichiers partagés et leur fusion
Périmètre : `atelier/controles.py`, `atelier/plan.py`, `atelier/consignes.py` (`REGLES_DECOUPAGE`, message de reprise après conflit), `atelier/moteur.py` (`_prochaine`, `_enregistrer`, la reprise après conflit), tests nouveaux.
1. Clé de profil `fichiers_partages` : entrées `{"motif", "fusion": "union" | "git"}`, « git » par défaut ; une entrée mal formée est ignorée ; une seule fonction la lit.
2. Deux tâches dont les périmètres ne se rencontrent que sur des fichiers partagés partent ensemble ; sans déclaration, la seconde attend.
3. Le plan (`forme_du_plan`) applique la même règle, par la même fonction.
4. Fusion « union » par le pilote intégré de git, passé par `core.attributesFile`, sans rien écrire dans `.git/` ni commiter de `.gitattributes` ; deux lignes ajoutées en parallèle au journal entrent toutes les deux.
5. Conflit en fusion « git » : reprise à chaud de l'ouvrier sur les marqueurs, puis contrôles et vérificateur ; une seule fois par départ, sinon le comportement actuel.
6. La consigne de découpage dit qu'un fichier déclaré partagé peut être dans plusieurs périmètres parallèles ; un test la garde.
7. Sans la clé, rien ne change.

## F2. V3f : six places, vérificateur hors place, réveil, régulateur
Périmètre : `atelier/moteur.py` (`executer`, `_partir`, le réveil, les résultats « limite » et « surcharge »), `atelier/places.py`, tests nouveaux. Fiche de référence : section V3f des fiches du moteur (gardée hors dépôt par l'orchestrateur), avec trois précisions : un réveil propre à V3f (échéance des places, décision de la personne) puisque V3c n'est pas faite ; une limite ou une surcharge ne compte jamais comme un échec ; `paralleles` vaut 6 par défaut.
1. Un vérificateur au travail ne retient pas de place d'écriture.
2. Une limite atteinte suspend les départs jusqu'à l'échéance, puis la tâche repart sans tentative comptée.
3. Une échéance qui tombe sans qu'aucun agent finisse relance les départs.
4. L'état des places est rangé dans l'état sauvé du chantier.
5. Suite et essais inchangés.

## F3. V3b.1 : pas de blocage sur un outil refusé sans rapport
Périmètre : `atelier/moteur.py` (`_avec_empechements`, `_cause_de_blocage`, la question de blocage, `relancer_au_meme_niveau`), `atelier/refus.py`, `consignes.consigne_reprise`, `serveur._regler_outils`, tests nouveaux.
1. `Bash(git push)` refusé et un verdict « bâclé » donnent une reprise à chaud, pas un blocage.
2. Les outils refusés sont cités dans le message de reprise.
3. Un outil refusé dont le premier mot est celui d'une commande de contrôle du profil bloque tout de suite.
4. « EMPÊCHÉ : » et `empeche` bloquent comme avant.
5. `Moteur.relancer_au_meme_niveau(demande_id) -> bool`, utilisée par le serveur à la place de `options[0]`.
6. La question d'un blocage pour refus répété dit le vrai nombre de refus.
7. Suite et essais inchangés.

## F4. Un chemin à crochets se reconnaît lui-même dans un périmètre
Ajoutée en route : défaut antérieur relevé par F1. `fnmatch` lit `[slug]` comme une classe de caractères, donc `app/[slug]/page.tsx` est déclaré hors de son propre périmètre, et deux tâches sur ce fichier partent ensemble. Périmètre : trois fonctions de `atelier/controles.py`, tests nouveaux. Part sur la base F1 non encore vérifiée.

## Écarts acceptés en route
- F1, critère 5 : la copie de la tâche reçoit le résultat de la fusion, marqueurs compris, comme un changement non enregistré posé sur la branche principale actuelle, au lieu d'une fusion git restée en cours (le test existant qui veut qu'une fusion ratée soit défaite reste vert ; le périmètre et le vérificateur ne voient que le travail de la tâche).
- F3 : la consigne générale de l'ouvrier (`EMPECHE_OUVRIER`) entre dans son périmètre, pour qu'un outil refusé sans rapport ne soit plus signalé « EMPÊCHÉ ».

## Retours des vérificateurs
- F1, refusé (premier passage) : tout conflit était repris à chaud, même sur un fichier non déclaré ; rien de mécanique n'empêchait des marqueurs d'entrer dans la branche principale ; un second conflit dans un départ faisait monter d'un cran. Ma consigne ne couvrait pas ces cas (critère 7 mesuré seulement par les tests existants, qui ne font passer aucun conflit par le moteur). Reprise à chaud avec ces trois points et cinq retouches (motif ancré dans le fichier d'attributs, motifs `#` et `!` rejetés, règle d'ajout seul dite à l'ouvrier et dans LISEZMOI, vérificateur prévenu du conflit résolu, conflit modifié/supprimé nommé).
- F3, accepté. Réserves sur le but, reprises en F3.1 : la règle du « premier mot » bloque à tort quand un contrôle commence par `python -m` ou `cd … &&` ; la consigne du vérificateur lui fait encore signaler toute commande refusée ; la règle de `EMPECHE_OUVRIER` est en deux phrases. Laissé pour plus tard : `decider` et `repondre` acceptent une seconde réponse (défaut antérieur : un clic tardif écrase la relance automatique).
- Réunion d'essai F1 (seconde version) + F2 + F3 sur la branche : trois conflits de texte dans `moteur.py` (un import, la signature de `_prochaine`, la fin de `repondre`), tous des ajouts des deux côtés ; une fois réunis, 1 730 tests verts et ruff propre.
- Restes de raccord relevés par F2, pour après les vérifications : la reprise après conflit de fusion (F1) doit prendre une place et passer par la suspension ; `Atelier.en_marche()` doit lire `moteur.en_route` ; `archives.GROUPES` ne connaît pas les phases `place`, `jeton`, `pause`.
- F1, refusé (seconde passe) pour un seul point : `_repris_hors_fusion` prend l'entrée « arrêtée », tracée sous le numéro du départ suivant, pour une reprise, et fait monter d'un cran une tâche arrêtée pendant sa préparation puis relancée au même niveau. Correction et test donnés par le vérificateur. Peut attendre : un test pour un fichier « union » qui bute quand même ; LISEZMOI doit dire que `*` ne traverse pas les dossiers pour git.
- F3.1, accepté. Peut attendre : R1, un contrôle avec `cd` (monorepo) n'est jamais jugé permis, donc un outil refusé de la même famille y bloque à tort (remède : juger la permission commande par commande) ; R2 à R6 mineurs (égalité exacte avec un contrôle, `env`/`sudo` en tête, redirections, un commentaire, une table de booléens). Deux tests git de `test_moteur.py` ont échoué une fois chez le vérificateur sous charge, puis passé cinq fois : instables, à surveiller.
- F2, refusé (premier passage) : aucun défaut de concurrence trouvé, mais une reprise à chaud sans `_malgre_les_limites` ou sans place passerait les tests ; une tâche déjà en vol qui attend une place passe après toutes les tâches neuves (une tâche refusée et ce qui dépend d'elle attendent la fin du plan). Reprise avec ces points, la pause de surcharge et la phase « jeton » testées, `_de_suite` et `rendre` retirés de `places.py` avec leurs tests (exception arbitrée : ces tests ne servent qu'à du code retiré), `archives.GROUPES`, `Atelier.en_marche()` et le retour en arrière de `_partir`.
