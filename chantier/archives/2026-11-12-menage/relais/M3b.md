# Fiche M3b

## Fait
1. Découpage du nom : `_poste` (rythme.py) et le `rsplit("-", 2)` de serveur.py sont la même expression ; comparés (script dans essais-M3b/cmp.py) sur trois morceaux, deux, un, vide, « B.1-ouvrier-2 », « REPARATION-1-ouvrier-1 » : identiques. Une seule fonction publique `poste` dans rythme.py, utilisée aux deux endroits. Deux tests ajoutés.
2. Coupe du brouillon : les deux endroits (`vue` et la réponse arrêtée) coupent pareil ; seul le second ajoute `.strip()` après. Coupe réunie dans `_avant_balises` (serveur.py), le second appel garde son `.strip()`. Même résultat sur textes sans balise, balise au début, à la fin, ouverte, deux balises.
3. Les trois écritures de chaque phrase étaient identiques au caractère près : constantes `PROFIL_ILLISIBLE` et `PROFIL_NON_ECRIT`, utilisées aux trois endroits.

## Fichiers touchés
atelier/rythme.py, atelier/serveur.py, tests/test_rythme.py (ajouts), cette fiche.

## Contrats modifiés
Aucun. `_poste` renommé `poste` (usage interne seulement).

## Reste à faire
Rien.

## Doutes et demandes
Aucun. `_avant_balises` est privée, couverte par les tests existants du serveur, sans test direct.

Tests : 763 passed. Contrôle de forme : All checks passed!
