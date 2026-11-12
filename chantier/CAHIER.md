# Cahier des charges — chantier « débit » (2026-11-12)

Contrat : `chantier/CONTRAT.md`. Les trois tâches partent ensemble, chacune dans sa copie de travail ; elles touchent `atelier/moteur.py` dans des fonctions distinctes et sont réunies à l'intégration.

| Tâche | État | Ouvrier | Vérification | Tentatives | Preuve |
|---|---|---|---|---|---|
| F1. Fichiers partagés et leur fusion | en vérification | Opus | complète, Opus | 1 | |
| F2. V3f : six places, vérificateur hors place, réveil, régulateur | en cours | Opus | complète, Opus | 1 | |
| F4. Un chemin à crochets se reconnaît lui-même dans un périmètre (relevé par F1) | en cours | Sonnet | mécanique, tests qui échouent avant | 1 | |
| F3. V3b.1 : pas de blocage sur un outil refusé sans rapport ; relance par une méthode nommée | reprise à chaud (consigne de l'ouvrier sur « EMPÊCHÉ ») | Opus | bornée, Opus | 1 | |

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
