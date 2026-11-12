# V1b — La forme du plan dite lisiblement, dans tous les cas

## Fait
- Phrase regroupée par fichier : une proposition par fichier partagé (« D et A touchent toutes deux X », « A, B et C touchent toutes X », « 10 tâches touchent X » au-delà de 5). Les dossiers recoupés sont regroupés par tâche gênante. `retenues` garde le détail paire par paire ; `attentes` et `chevauchements` (données) sont ajoutés à la forme, et `resumer` s'en sert.
- Accord « toutes deux » ; dépendances citées deux fois dédoublonnées ; plus longue chaîne sans récursion (pile) ; calcul des cycles ramené de cubique à quasi linéaire (une boucle de 2000 tâches prenait 60 s).
- Identifiants doubles : le moteur (`Moteur._prochaine`) choisit par objet tâche et ne compare l'identifiant que pour les dépendances (ensemble des identifiants vérifiés). Il lance donc les deux tâches, et ce qui dépend de l'identifiant part dès que l'une est vérifiée. Le module suit donc les tâches par rang dans le plan : les deux partent dans les vagues (avant, la seconde disparaissait des vagues). Le doublon reste dans `problemes` et dans la phrase, mais le plan n'est plus dit « impossible » : seul `jamais` non vide donne « ne peut pas aller au bout ».
- Les vagues des tâches à identifiants uniques sont inchangées. 882 tests verts, ruff vert.

## Fichiers touchés
`atelier/plan.py`, `tests/test_plan.py` (9 tests ajoutés ; voir Doutes pour 3 chaînes modifiées), cette fiche.

## Contrats
- `forme_du_plan` : nouvelles clés `attentes`, `chevauchements`. `possible` reste `not problemes and not jamais` (donc faux avec un identifiant double, comme le test existant l'exige). `problemes` peut contenir un défaut qui n'empêche pas d'aller au bout ; seule `jamais` dit l'impossibilité.
- `resumer(forme)` retombe sur `retenues` si la forme n'a pas `attentes`.
- `NOMMEES_AU_PLUS = 5` : seuil de nommage des tâches.

## Reste à faire
Rien dans le périmètre. Les attentes (« X attend Y ») ne sont pas regroupées : une chaîne longue donne une attente par tâche dans la phrase.

## Doutes
- Conflit de consigne : le critère 2 exige « toutes deux », mais trois tests existants affirmaient « tous deux » (`test_un_fichier_partage_separe...`, `test_une_dependance_et_un_chevauchement...`, plus la phrase complète de ce dernier). J'ai remplacé seulement ce mot dans ces chaînes attendues ; rien d'autre n'y change. À valider.
- Pour deux tâches, l'ordre reste « la retenue, puis la gênante » (« D et A ») comme les tests existants ; au-delà, ordre d'apparition, la gênante d'abord.
- Une tâche d'identifiant vide est maintenant, comme un doublon, un défaut non bloquant si elle part : la phrase dit « peut aller au bout, mais… ».

## Exemples (avant -> après)
1. Dix tâches sur DECISIONS.md : « Ce qui le retient : B et A touchent tous deux DECISIONS.md ; C et A touchent tous deux DECISIONS.md ; … » (45 paires) -> « Ce qui le retient : 10 tâches touchent DECISIONS.md. »
2. « Ce qui le retient : B attend A et A. » -> « Ce qui le retient : B attend A. »
3. Identifiant B en double : « Ce plan ne peut pas aller au bout. En cause : deux tâches portent l'identifiant B. La partie qui peut partir, 3 tâches, … ; B et B touchent tous deux autre.py. » -> « Ce plan peut aller au bout, mais il a un défaut à corriger : deux tâches portent l'identifiant B. Le moteur lance chacune de ces tâches ; ce qui dépend de cet identifiant part dès que l'une d'elles est vérifiée. Ce plan de 4 tâches tient en 2 vagues ; … »
