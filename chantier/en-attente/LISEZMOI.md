# Travail rendu, pas encore dans la branche

Chantier arrêté le 2026-11-13. Une tâche du moteur a été écrite et vérifiée, mais refusée pour un dernier point ; son travail est gardé ici sous forme de correctif, pour ne pas le perdre. Rien de ce dossier n'est appliqué au code.

## M3, l'ouvrier reste ouvert (`M3.patch`, base 8a6ba8a)
Refusée une fois. Le contrat est tenu avec les faux clients des tests ; le vérificateur a lu dans le vrai SDK deux comportements qu'ils cachent : le programme peut émettre des messages entre deux demandes (la suite rendrait alors le texte d'un tour précédent, avec un décalage définitif), et un programme mort entre deux demandes n'est vu qu'à l'écriture suivante (l'ouvrier reste rangé comme ouvert et la suite échoue sans repli). La correction est dans `atelier/sdk.py` : vider ce qui est arrivé avant d'envoyer une suite, et traiter un programme mort comme une reprise impossible. L'essai qui le montre : `M3-essai-du-verificateur.py.txt`. Mineurs : `M3-essai-mineurs.py.txt`.

## Pour les appliquer
Le correctif s'applique par `git apply --3way` ; il passe sans conflit sur la branche au commit a684c52. Sa fiche de relais est dedans (`chantier/relais/M3.md`). Le détail des verdicts est dans `chantier/CAHIER.md`.

Les essais portent l'extension `.txt` pour que le contrôle de forme du projet ne les lise pas : il faut la retirer pour les lancer.
