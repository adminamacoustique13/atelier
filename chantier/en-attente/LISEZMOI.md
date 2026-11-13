# Travail rendu, pas encore dans la branche

Chantier arrêté le 2026-11-13. Deux tâches du moteur ont été écrites et vérifiées, mais refusées pour un dernier point ; leur travail est gardé ici sous forme de correctifs, pour ne pas le perdre. Rien de ce dossier n'est appliqué au code.

## M8, le travail refusé est gardé (`M8.patch`, base c21b72e)
Refusée deux fois. Tout est corrigé sauf un cas : après un redémarrage, si le fichier qui porte la liste des fichiers à marqueurs de conflit (`.git/worktrees/<tâche>/atelier-marqueurs.json`) est tronqué, vide ou mal formé, `_marqueurs_poses` (dans `atelier/controles.py`) rend la liste en mémoire, vide à ce moment, et des marqueurs peuvent entrer dans la branche. Correction attendue : une liste illisible fait rendre un problème à `enregistrer`, et rien n'entre. L'essai qui le montre : `M8-essai-du-verificateur.py`, cas `illisible`, `pas_une_liste` et `vide_`.

## M3, l'ouvrier reste ouvert (`M3.patch`, base 8a6ba8a)
Refusée une fois. Le contrat est tenu avec les faux clients des tests ; le vérificateur a lu dans le vrai SDK deux comportements qu'ils cachent : le programme peut émettre des messages entre deux demandes (la suite rendrait alors le texte d'un tour précédent, avec un décalage définitif), et un programme mort entre deux demandes n'est vu qu'à l'écriture suivante (l'ouvrier reste rangé comme ouvert et la suite échoue sans repli). La correction est dans `atelier/sdk.py` : vider ce qui est arrivé avant d'envoyer une suite, et traiter un programme mort comme une reprise impossible. L'essai qui le montre : `M3-essai-du-verificateur.py`. Mineurs : `M3-essai-mineurs.py`.

## Pour les appliquer
Les deux correctifs s'appliquent par `git apply --3way` ; M3 passe sans conflit sur la branche au commit a684c52, M8 a été réuni sans conflit avec M6 et M7. Les fiches de relais sont dans les correctifs (`chantier/relais/M3.md`, `chantier/relais/M8.md`). Le détail des verdicts est dans `chantier/CAHIER.md`.
