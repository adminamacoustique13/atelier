# Fiche de relais M5a : une base commune pour appeler git

## Fait
1. `atelier/git.py` contient `lancer_git`, la base : sans shell, `stdin` fermé (`DEVNULL`), `GIT_TERMINAL_PROMPT=0`, sortie capturée en texte, délai réglable (aucun par défaut), variables supplémentaires possibles. Elle rend le `CompletedProcess` tel quel, même sur un code d'erreur, et laisse remonter `TimeoutExpired` et `OSError`. `tests/test_git.py` (7 tests, vrai dépôt dans `tmp_path`) : succès, échec (code et message rendus, rien n'est levé), délai dépassé (faux git qui dort), délai absent par défaut et entrée fermée, `GIT_TERMINAL_PROMPT` à 0 même si le processus ou l'appelant met 1, variable supplémentaire transmise (lue par un alias `!printenv`), git introuvable qui lève `OSError`.
2. Tous les appels à `_git`. Aucun ne lit son entrée standard ni n'attend de saisie (le commit a toujours `-m`).
   - `projets.py` : `creer_depot` : `init -q -b main` ; `add -A` ; `[identité] commit -q -m "Création du projet"`. `Projets` (clonage) : `clone --quiet -- <adresse> <dossier>`, `delai=600`.
   - `essai.py` : `creer_projet_d_essai` : `init -q -b main` ; `add -A` ; `<identité> commit -q -m "Création du projet d'essai"`. `livraison` : `ls-files` ; `log --format=%s`.
   - `carte.py` : `commit_courant` : `rev-parse HEAD`. `lister_fichiers` : `ls-files -s -z`.
3. Les trois `_git` passent par `lancer_git` et gardent leur traduction : `projets` lève `ProjetImpossible` (mêmes phrases, `strip()` gardé, délai `delai`) grâce à `check_returncode()` ; `essai` laisse passer `CalledProcessError` (même commande, code, sorties), sans délai ; `carte` lève `OSError` (« git a échoué » si pas de message), délai 60. Script `/tmp/claude-0/-home-user-atelier/d04ea8ab-c665-54ab-9a3a-d57048e9c6b4/scratchpad/essais-M5a/comparer.py` (origines recopiées du commit 04307a2) : 3 modules x 5 cas (succès, échec avec message, échec sans message, délai dépassé simulé, git introuvable simulé), **0 écart** sur la valeur rendue ou l'exception (type, message, et pour `CalledProcessError` code, commande et sorties). Délais transmis identiques (projets 120 puis 7 sur demande, essai aucun, carte 60). Seules différences relevées, celles voulues : `stdin` fermé pour `projets` et `essai`, `GIT_TERMINAL_PROMPT=0` pour `essai`.
4. `IDENTITE_DE_REPLI` dans `atelier/git.py`, utilisée par `projets.py` et `essai.py`.
5. `controles.py` et `mise_a_jour.py` non modifiés.
6. Aucun test existant modifié ; tous verts ; ruff vert. `python -m atelier demo` démarre et le tableau répond (HTTP 200).
7. Rien d'autre ; dans `carte.py`, seuls `_git` et une ligne d'import ont changé.

## Fichiers touchés
`atelier/git.py` (nouveau), `tests/test_git.py` (nouveau), `atelier/projets.py`, `atelier/essai.py`, `atelier/carte.py`, `chantier/relais/M5a.md`.

## Contrats modifiés
- Base : `atelier.git.lancer_git(dossier: Path, *arguments: str, delai: float | None = None, environnement: Mapping[str, str] | None = None) -> subprocess.CompletedProcess[str]`.
- Garanties : lance `["git", *arguments]` avec `cwd=dossier`, sans shell, `stdin=DEVNULL`, `capture_output=True`, `text=True`, `timeout=delai`. Environnement : celui du processus, puis `environnement` par-dessus, puis `GIT_TERMINAL_PROMPT=0` toujours (l'appelant ne peut pas le rouvrir). Rend le résultat quel que soit le code de sortie (`returncode`, `stdout`, `stderr` intacts, `args == ["git", *arguments]`, donc `check_returncode()` lève la même `CalledProcessError` qu'un `check=True`). Lève `subprocess.TimeoutExpired` si le délai est dépassé, `OSError` si git est introuvable ou le dossier inaccessible ; rien d'autre n'est intercepté.
- Constante : `atelier.git.IDENTITE_DE_REPLI = ["-c", "user.name=Atelier", "-c", "user.email=atelier@localhost"]` (une liste : à déplier avec `*`, ne pas la modifier).

## Reste à faire
M5b : adopter `lancer_git` dans `controles.py` (et `IDENTITE_DE_REPLI`) et dans `mise_a_jour.py` (ses variables `GIT_ASKPASS`, `GIT_EDITOR`, etc. passent par `environnement`).

## Doutes et demandes
- `carte._git` lançait `git -C <dépôt>` sans `cwd` ; la base utilise `cwd`. Seule conséquence : pour un dossier inexistant, l'`OSError` vient de Python (`[Errno 2] ... '/nulle/part'`) et non de git (« cannot change to »). Même type, et les deux appelants l'avalent (`commit_courant` rend `""`, `lister_fichiers` parcourt le dossier, vérifié). À accepter, ou à corriger par une option de la base.
- Noté sans y toucher : `projets.creer_depot` lance encore `git config user.email` par `subprocess.run` direct (ce n'est pas un `_git`), et `essai.py` garde deux `subprocess.run` hors git (`ps`, contrôle Python). Le premier pourrait passer par la base dans une tâche suivante.

Tests : `pytest -q` : 771 passed in 33.15s. Contrôle de forme : `ruff check .` : All checks passed!
