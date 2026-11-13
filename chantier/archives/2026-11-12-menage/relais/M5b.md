# Relais M5b : `controles.py` et `mise_a_jour.py` passent par `lancer_git`

## Fait

1. **Inventaire avant modification** (commit de départ 0fd706f). Aucun lancement ne lit l'entrée standard ni n'attend de saisie : les commits ont tous `-m`, les fusions `--no-edit` ou `--ff-only`, `GIT_TERMINAL_PROMPT=0` partout sauf dans les trois lancements écrits à la main, qui ne posent pas de question non plus (`config`, `merge-base`).
   - `controles.py`, par `ControlesGit._git` : `worktree remove --force <arbre>`, `worktree add -q -B tache/<id> <arbre> HEAD`, `worktree add -q --detach <copie> HEAD` (avec et sans `dossier`), `status --porcelain -z --untracked-files=all`, `status --porcelain -z --ignored`, `worktree prune`, `status --porcelain --untracked-files=all`, `add -A`, `status --porcelain`, `commit -q -m "<id> : <titre>"`, `rev-parse HEAD`, `merge -q --ff-only tache/<id>`, `branch -q -D tache/<id>`, `merge -q --no-edit <base>`, `merge --abort`, `add -- <chemin>`, `diff --cached --name-only -- <chemin>`, `commit -q -m <message> -- <chemin>`, `remote get-url origin`, `remote add|set-url origin <adresse>`, `push -q -u origin HEAD` (délai 300).
   - `controles.py`, à la main : `_config` (`config <clé>`), `_ancetre` (`merge-base --is-ancestor <base> HEAD`).
   - `mise_a_jour.py`, par `_git` : `ls-remote origin refs/heads/main`, `cat-file -e <commit>^{commit}`, `merge-base --is-ancestor <commit> HEAD`, `symbolic-ref --short -q HEAD`, `status --porcelain --untracked-files=no`, `rev-parse HEAD` (deux fois), `pull --ff-only origin main`.
   - `projets.py` : par `_git`, `init -q -b main`, `add -A`, `[identité] commit -q -m "Création du projet"`, `clone --quiet -- <adresse> <dossier>` (délai 600) ; à la main, `config user.email`.
2. `ControlesGit._git` appelle `lancer_git(dossier or self.depot, *signe, *arguments, delai=delai)`. Identité seulement devant `commit` et `merge`, mêmes messages de `RuntimeError`, `OSError` non rattrapée comme avant.
3. `mise_a_jour._git` passe ses cinq variables par `environnement` et son délai par `delai`. Le triplet rendu est le même dans tous les cas.
4. `_config`, `_ancetre` et le `config user.email` de `creer_depot` passent par `lancer_git`, toujours sans délai et sans rattraper d'erreur. Une seule différence voulue, qui vient de la base : l'entrée est maintenant fermée et `GIT_TERMINAL_PROMPT=0` (avant : entrée héritée, environnement hérité). `ControlesGit._git` ferme aussi l'entrée, qu'il héritait avant. `lancer_commande` n'a pas changé.
5. `IDENTITE_DE_REPLI` est maintenant un tuple. `controles.py` s'en sert, `self.identite` est un tuple (`()` par défaut). `projets.py` part de `()`. `essai.py` n'a plus l'alias, et son commentaire dit maintenant que le rapport cite la commande et son code, pas le message de git.
6. `grep -n "subprocess" atelier/*.py` : il reste un seul lancement de git, dans `git.py`. Les autres lancements sont `Popen` dans `lancer_commande` (`controles.py`), le contrôle du profil (`essai.py:368`) et `ps` (`essai.py:133`, ce n'est pas git). Les autres mentions restantes sont des `except subprocess.TimeoutExpired` / `CalledProcessError`.
7. Nouveau test `test_une_variable_supplementaire_prime_sur_celle_du_processus` (LC_ALL). Quand j'ai inversé l'ordre dans `lancer_git` (`{**environnement, **os.environ, ...}`), il a échoué ; j'ai remis l'ordre d'origine et il passe.
8. Le script `/tmp/claude-0/-home-user-atelier/d04ea8ab-c665-54ab-9a3a-d57048e9c6b4/scratchpad/essais-M5b/comparer.py` charge les originaux copiés dans `essais-M5b/origine/`. Il compare résultat, exception et cause, arguments reçus par git et délai (plus l'environnement pour `_git` et `mise_a_jour`), dans un dépôt avec puis sans identité. Cas couverts : réussite, échec avec message, échec sans message, délai simulé, git introuvable simulé, dossier inexistant, plus les arguments exacts de `commit`, `merge` et `add`. Résultat : **52 cas, 0 écart**.
9. Le mode démonstration répond 200. Je n'ai modifié aucun test existant.

## Fichiers touchés
`atelier/controles.py`, `atelier/mise_a_jour.py` (son `import os` est retiré, devenu inutile), `atelier/projets.py`, `atelier/essai.py`, `atelier/git.py` (la constante seule ; la docstring n'a pas eu besoin de changer), `tests/test_git.py` (un ajout), cette fiche.

## Contrats modifiés
`IDENTITE_DE_REPLI` est maintenant un tuple, et non plus une liste. `ControlesGit.identite` aussi. `lancer_git` n'a pas changé.

## Reste à faire
Rien dans le périmètre.

## Doutes et demandes
- Dans `controles.py`, `_git`, `_config` et `_ancetre` ont maintenant l'entrée fermée ; `_config` et `_ancetre` ont aussi `GIT_TERMINAL_PROMPT=0`. Cela vient de la base et c'est voulu. Comme aucune de ces commandes ne lit l'entrée, leur résultat ne change pas.
- Vu en passant, laissé tel quel : `projets._git` rattrape `subprocess.CalledProcessError` et lit son `stderr`. Pour `essai`, le rapport n'affiche pas le message de git.

## Résultats
- Tests : `773 passed in 31.20s` (772 d'origine + 1 nouveau).
- Contrôle de forme : `All checks passed!`
