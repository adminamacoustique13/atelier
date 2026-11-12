# Relais I — La course dans les contrôles git

## 1. Fait

1. **Critère 1.** Dans `atelier/controles.py`, les deux `git worktree remove --force` cités passent par `verrou_fusion` : celui de `preparer` (retrait d'un ancien arbre) et celui d'`annuler`. Le verrou n'entoure que la commande git (le test `arbre.exists()`, le `mkdir` et le `Path(dossier).exists()` restent dehors). Trois lignes ajoutées, aucune autre ligne touchée.
2. **Critère 2.** `tests/test_controles.py` (nouveau), test `test_preparer_et_annuler_en_parallele_ne_se_marchent_pas_dessus` : 3 fils, 6 tours chacun, tâches différentes (T0, T1, T2), vrai dépôt git dans `tmp_path`. Un tour sur deux l'arbre est annulé, l'autre fois il est laissé et la préparation suivante le retire : les deux chemins sont donc joués. Un double de `_git` ralentit chaque commande `git worktree` de 20 ms et compte combien tournent en même temps ; le test exige zéro erreur, un maximum de 1 commande à la fois, un verrou libre à la fin, et des attentes bornées à 30 s (un fil encore vivant fait échouer le test au lieu de le bloquer ; fils démons). Durée : environ 0,5 s.
   Deux tests de garde l'accompagnent : `test_annuler_sans_arbre_ne_fait_rien_et_ne_garde_pas_le_verrou` et `test_preparer_remplace_un_ancien_arbre_sans_garder_le_verrou`.
   Preuve sur une copie hors du dépôt avec le `controles.py` d'origine : le test nouveau échoue 20 fois sur 20 (le plus souvent sur le maximum de commandes simultanées, parfois sur une vraie erreur git `worktree remove ... No such file or directory`). Avec la correction : 0 échec sur 20.
3. **Critère 3.** Le test d'origine, lancé 200 fois de suite pendant que 8 boucles de calcul et 4 boucles de `pytest` (moteur, dosage) occupaient les 4 processeurs : **0 échec sur 200** avec la correction. Même charge sur la copie au code d'origine : **1 échec sur 200**, avec le message du vérificateur (`git worktree remove --force .../arbres/B : fatal: failed to read .git/worktrees/A/commondir: Success`). La charge est donc bien celle qui révèle le défaut.
4. **Critère 4. Aucun interblocage possible.** `verrou_fusion` est un `threading.Lock` non réentrant ; je l'ai gardé tel quel. Recherche faite dans tout `atelier/` (`grep verrou_fusion`, `grep controles`) :
   - `verrou_fusion` n'est nommé que dans `atelier/controles.py`. Ni `moteur.py`, ni `serveur.py`, ni `projets.py`, ni `__main__.py` ne le prennent.
   - Les seuls appelants de `preparer` et `annuler` sont `moteur.py:270` (`_lancer_ouvrier`), `:227` et `:251` (`_boucle`). Aucun n'est dans un `with self.verrou:` (le verrou du moteur, un autre objet) : ils sont après la fin des blocs `with`. Et même si le moteur tenait son verrou, `controles.py` ne prend jamais le verrou du moteur : pas de cycle possible.
   - Dans `controles.py`, les blocs qui tiennent `verrou_fusion` sont : `preparer` (l'ajout, puis maintenant le retrait, deux blocs séquentiels et séparés, aucun dans l'autre), `enregistrer` (merge, retrait, suppression de branche, cahier), `regler_outils`, `relier`, `envoyer`. Chemin par chemin :
     - `preparer` : retrait sous verrou, verrou rendu, puis `mkdir`, puis ajout sous verrou. Appelle seulement `_git`.
     - `annuler` : un seul bloc, appelle seulement `_git`.
     - `enregistrer` : appelle `_git` et `enregistrer_cahier` sous verrou (le retrait y est un `_git` direct, pas `annuler`) ; `enregistrer_cahier` -> `enregistrer_fichier` -> `_git`, sans verrou. `envoyer()` est appelé après la sortie du bloc.
     - `regler_outils` : `enregistrer_fichier` sous verrou, `envoyer()` après le bloc.
     - `relier` : sous verrou `enregistrer_cahier`, `distant`, `_git` ; `envoyer(lever=True)` après le bloc. `distant` ne prend pas de verrou.
     - `envoyer` : `distant()` hors verrou, puis `_git push` sous verrou ; l'appel est toujours fait hors de tout bloc par ses appelants.
     - `_git`, `_config`, `_arbre`, `distant`, `fichiers_modifies`, `mecaniques`, `enregistrer_fichier`, `enregistrer_cahier` ne prennent pas le verrou.
   - Conclusion : aucune fonction qui tient `verrou_fusion` n'appelle `preparer`, `annuler`, `enregistrer`, `regler_outils`, `relier` ni `envoyer`, seules fonctions à le prendre. Le verrou n'est donc jamais demandé par un fil qui le tient. Le test nouveau le confirme en pratique (fils joints dans le délai, verrou libre à la fin).
   - Rien de lent n'est ajouté sous le verrou : une commande `git worktree remove`, de même nature que celles qui y étaient déjà.

Contrôles : `python3 -m pytest -q` : 442 passent (430 de départ, 3 de mon fichier, le reste vient des travaux d'autres agents) ; `python3 -m ruff check .` : vert.

## 2. Fichiers touchés
`atelier/controles.py` (trois lignes), `tests/test_controles.py` (nouveau), `chantier/relais/I.md`.

## 3. Contrats modifiés
Aucun. Mêmes méthodes, mêmes signatures, mêmes messages d'erreur, même comportement hors prise du verrou.

## 4. Reste à faire
Rien dans mon périmètre.

## 5. Doutes et demandes
- Dans `atelier/controles.py`, `_config` (lignes 84-92) contient après son `return` trois lignes inaccessibles (exclusion de `.atelier/` dans `.git/info/exclude`) : du code mort, visiblement tombé là par accident, qui ressemble à un morceau d'une autre méthode. Je n'y ai pas touché (hors périmètre) ; à voir par l'orchestrateur.
- Le test nouveau remplace volontairement `_git` sur l'instance ; s'il est un jour renommé, le test devra suivre.
- `.gitignore`, `uv.lock` et `chantier/relais/D2.md` apparaissent dans l'état du dépôt : ce n'est pas moi.
