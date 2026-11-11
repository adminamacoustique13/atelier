# Profil du projet Atelier

## Ce que fait le projet
Un chef de chantier en code pour des agents Claude : il lance chaque agent avec le modèle et l'effort choisis, contrôle son travail, fait passer un vérificateur, monte d'un cran après un échec et s'arrête quand il sort du contrat.

## Commandes de contrôle
Lancées après chaque livrable, depuis la racine du dépôt :

- `python3 -m pytest -q` : la suite de tests (35 tests au départ de ce profil, tous verts)
- `python3 -m ruff check .` : le contrôle de forme (vert au départ)

## Mode de périmètre
Strict : un agent ne modifie rien hors de son périmètre. S'il en a besoin, il le demande dans sa fiche de relais.

## Règles du projet
- Chaque fonction publique naît avec ses tests.
- Le mode démonstration (`python3 -m atelier demo`) doit continuer de marcher sans rien appeler ni rien dépenser : tout ce qui est réel a son double simulé.
- Les textes affichés à la personne responsable sont en français, en phrases complètes, sans smiley ni émoji.
- Le tableau de bord reste sobre et dense, dans l'ambiance verre fumé déjà en place : pas d'éléments surdimensionnés ni d'allure de jouet.
- Le serveur n'écoute que sur la machine elle-même (127.0.0.1).
- Complexité maximale d'une fonction : 10 (réglée dans `pyproject.toml`).
