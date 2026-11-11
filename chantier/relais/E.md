# Relais — Tâche E : installation et connexion

## 1. Fait
- **Critère 1 (installation par uv).** `outils/installer-mac.sh` fait `uv sync` dans le dépôt (la bibliothèque va dans `.venv`, chez la personne), puis vérifie `import claude_agent_sdk`. L'agent de lancement passe par `uv run`, qui resynchronise au démarrage. Rien hors du dossier personnel : branche `brew install uv` retirée, uv vient de l'installeur officiel ; le script dit où uv a été trouvé ou installé (plus de chemin supposé, `XDG_BIN_HOME` compris). Aucun `sudo`. Preuve : `bash -n` et `shellcheck` (0.11.0, `pip install shellcheck-py`, outil de travail) sans avertissement ; essai à blanc `ATELIER_ESSAI` rejoué. Compatible bash 3.2 (pas de `declare -A`, `mapfile`, `${var,,}`). L'avertissement sur `claude` ne propose plus de clé API.
- **Verrou de version (point 6).** `uv.lock` retiré de `.gitignore` et produit avec uv 0.11.32 (`uv lock --upgrade-package claude-agent-sdk==0.2.172`) : sdk 0.2.172, index public pypi.org seul. Vérifié sur une copie hors du dépôt, cache isolé : `uv sync --frozen` installe 0.2.172, et la suite (441 tests) y passe par `uv run --frozen --with pytest`. `uv sync` (script) et `uv run` (agent de lancement) lisent `uv.lock` par défaut, et ne le réécrivent que si `pyproject.toml` change. `pyproject.toml` non modifié. Le fichier `uv.lock` est à enregistrer par l'orchestrateur (nouveau fichier suivi).
- **Critères 2 et 3 (source et variable).** `Atelier.annoncer_connexion()` écrit à l'ouverture de chaque projet ce qui est su (variable présente ou non), puis la source réelle dès que le premier agent l'apprend. Phrases distinctes pour : démonstration ; variable présente ; variable absente (ne dit pas « abonnement ») ; abonnement ; abonnement malgré variable ; clé API avec variable ; clé API sans variable (la contradiction est dite, avec `/status` et `/login`). Dédoublonnage : un départ n'est écrit que s'il diffère du dernier départ ; une confirmation n'est écartée que si elle suit le dernier départ (sinon la promesse du départ resterait sans suite : test de l'enchaînement sans variable, avec variable, sans variable). Un redémarrage identique n'ajoute rien. La démonstration est testée : le fil s'arrête à sa phrase. Le conseil `/login` distingue connexion par clé et réglage de `~/.claude/settings.json` (`env`, `apiKeyHelper`) ; le LISEZMOI dit que `launchctl setenv` ne survit pas à un redémarrage ; le script dit de faire `uv self update` si `uv sync` échoue. Tests : 442.
- **Câblage testé (point 3).** `monter_projets()` isole le montage de `servir`. `tests/test_demarrage.py` (17 tests) : projet donné, découvert, créé ensuite, sur dépôts git temporaires ; variable posée par `monkeypatch.setenv` (valeur factice) ou retirée par `delenv` ; absence de la valeur dans le fil. Vérifié par mutation : retirer `avec_annonce` du `Projets(...)` fait échouer 2 tests, de `ajouter(...)` 1 test, remplacer `os.environ` par `{}` 3 tests.
- **Critère 4 et points 4, 7 (LISEZMOI).** Sections connexion (deux temps, tous les cas), « Retirer une variable ANTHROPIC_API_KEY oubliée » (agent de lancement n'hérite pas du shell ; `launchctl getenv`/`unsetenv` sans afficher la valeur ; Terminal : `unset` ; relance par `launchctl kickstart -k gui/$(id -u)/fr.atelier.serveur` ou en relançant le script), cartes (« Toujours » parfois absent), règles simples gardées et écartées avec exemples, « à l'ouverture de chaque projet », `.venv` laissé par la désinstallation avec la commande pour le retirer.
- **Critère 5 (restes).** Inchangé : plus de `subprocess`, plus de « Claude Code en ligne de commande ».
- Contrôles : `python3 -m pytest -q` trois fois, 441 passés ; ruff vert ; demo et instantanés vérifiés.

## 2. Fichiers touchés
`outils/installer-mac.sh`, `atelier/__main__.py`, `atelier/serveur.py`, `LISEZMOI.md`, `tests/test_demarrage.py`, `.gitignore`, `uv.lock` (nouveau), cette fiche.

## 3. Contrats modifiés
- `serveur.py` : `cle_api_presente(environnement=None)`, `annonce_de_depart(mode, cle_presente)`, `annonce_de_source(source, cle_presente)`, `Atelier.annoncer_connexion(environnement=None)` (le constructeur ne change pas).
- `__main__.py` : `avec_annonce(fabrique)`, `monter_projets(arguments)`. Toute nouvelle fabrique de projet doit passer par `avec_annonce`.

## 4. Reste à faire
Enregistrer `uv.lock`. `desinstaller-mac.sh` ne retire pas `.venv` (le LISEZMOI le dit) : hors périmètre, à décider.

## 5. Doutes et demandes
- « abonnement » (`"none"`) peut être un compte non connecté ou une passerelle : le fil le dit.
- La commande `launchctl kickstart -k` et le fait que `launchctl setenv` atteigne le job relancé sont écrits d'après la documentation de launchd, non essayés.
- Un nouveau SDK n'est pris qu'en changeant `uv.lock` volontairement (`uv lock --upgrade-package`) ; le garde-fou est le verrou, pas une borne haute.

**À essayer en vrai (tâche F)**
- Installation sur un Mac : `uv sync` crée `.venv` en 0.2.172, l'import passe, l'agent démarre à l'ouverture de session.
- Mise à jour d'Atelier (`git pull`) puis redémarrage : resynchronisation.
- `uv run` sous l'agent de lancement, y compris hors ligne (démarrage possible sans réseau quand rien n'a changé ?).
- Valeurs réelles d'`apiKeySource` : compte connecté ; compte non connecté ; variable posée par `launchctl setenv` ; `apiKeyHelper` ; connexion par clé (compte Console).
- Le Claude Code embarqué lit bien la connexion faite par la commande `claude`.
- La phrase affichée dans chacun de ces cas ; `launchctl getenv/unsetenv/kickstart` tels qu'écrits dans le LISEZMOI.
- `/login` ramène-t-il bien à l'abonnement après une connexion par clé ?
- Ce que donnent `launchctl getenv`, `setenv`, `unsetenv` et `kickstart` (la variable revient-elle après un redémarrage du Mac ?).
- Un ancien uv déjà présent : `uv sync` échoue-t-il sur `uv.lock`, et le message d'arrêt suffit-il ?
- Le script sans la commande `claude` installée : avertissement et suite.

## Quatrième tentative

**Ce qui a changé**
- `atelier/serveur.py` : `_noter_annonce` est réécrite en quatre lignes. Elle cherche, en remontant le fil, la dernière annonce prise dans la famille qu'on lui donne, et n'écrit la phrase que si cette annonce n'est pas elle. Le départ se compare à `DEPARTS` (R1) ; la confirmation à `ANNONCES = DEPARTS + CONFIRMATIONS + ANCIENNES_ANNONCES`, toutes familles confondues (R2). La boucle à cas particuliers des tentatives précédentes a disparu. Docstring d'`annoncer_connexion` mise à jour. Texte des phrases, détection de la variable et drapeau `_source_annoncee` inchangés.
- Nouveau tuple `ANCIENNES_ANNONCES`, vide aujourd'hui (voir plus bas, « Changement de texte d'une phrase »).
- `outils/installer-mac.sh` : le message d'arrêt de `uv sync` dit maintenant « mets-le à jour avec « uv self update », ou avec « brew upgrade uv » s'il a été installé par Homebrew ». `bash -n` et `shellcheck` 0.11.0 sans avertissement, aucune construction nouvelle (bash 3.2).

**La règle telle qu'elle est implémentée**
- R1 : à l'ouverture, le départ est écrit sauf si la dernière annonce du fil prise dans `DEPARTS` (et les textes retirés) est ce même départ. Aucun départ dans le fil : il est écrit.
- R2 : à la première source connue de l'ouverture, la confirmation est écrite sauf si la dernière annonce de connexion du fil, toutes familles confondues, est cette même confirmation. Comme départs et confirmations ont des textes distincts, « la dernière annonce est une confirmation au texte identique » revient à « la dernière annonce est la phrase ».
- Source vide : `annonce_de_source` rend une chaîne vide et rien n'est écrit. Démonstration : départ selon R1, et `_sur_evenement` n'est jamais branché, donc aucune confirmation.
- Une confirmation par ouverture : le drapeau `_source_annoncee` est relu et posé sous `moteur.verrou` (verrou réentrant) avant l'écriture. Le premier test sans verrou garde le chemin répété léger : après la confirmation, chaque événement ne fait plus que ranger l'activité. Sous le verrou, il n'y a que la remontée du fil (une fois par ouverture) et l'ajout d'une ligne. Le `_sauver` qui suit est hors de ce bloc ; il prend le verrou comme partout ailleurs.
- Pourquoi les invariants tiennent par construction. B : deux départs consécutifs identiques sont exclus par R1, deux confirmations consécutives identiques par R2, et un départ ne vaut jamais une confirmation. A : la confirmation de l'ouverture est soit écrite (elle est alors la dernière, puisqu'aucun départ ne vient après l'ouverture), soit écartée parce qu'elle est déjà la dernière. C : après une ouverture, le dernier départ est celui de cette ouverture et, si une source a été apprise, la dernière annonce est sa confirmation : une ouverture identique ne trouve rien à écrire. D : une promesse écrite depuis la dernière confirmation fait de la dernière annonce un départ, donc R2 écrit la confirmation.

**Tests ajoutés ou modifiés** (`tests/test_demarrage.py` : 22 fonctions de test au lieu de 15, soit 25 tests exécutés au lieu de 18, une fonction étant paramétrée en 4 cas ; le « 17 » de la consigne ne correspond pas au fichier trouvé ; 449 tests en tout au lieu de 442)
- `ouvrir(depot, variable)` simule un démarrage : chantier relu dans `.atelier/etat.json`, nouvelle instance d'`Atelier`, environnement passé à `annoncer_connexion`. `apprendre(atelier, source)` pose `source_connexion` sur l'agent simulé puis envoie un événement de deux agents, comme le fait le SDK.
- Test renommé, pas corrigé : `test_une_confirmation_promise_n_est_jamais_ecartee` devient `test_sans_variable_puis_avec_puis_sans_la_confirmation_promise_est_ecrite`. C'est le même enchaînement (échec de la deuxième tentative), avec le même fil attendu en littéral, désormais relu sur disque à chaque démarrage. Aucun test existant ne figeait un comportement contraire à la règle.
- `test_cle_puis_abonnement_puis_cle_le_fil_finit_sur_la_cle` : l'échec de la troisième tentative, avec le fil attendu en littéral.
- `test_un_redemarrage_identique_relu_sur_disque_n_ajoute_rien` : invariant C, avec et sans variable, en passant par le fichier.
- `test_les_annonces_de_connexion_sont_les_sept_phrases` : contenu de `DEPARTS`, `CONFIRMATIONS` et `ANNONCES`.
- `test_un_texte_retire_fait_reecrire_l_annonce` : un départ et une confirmation au texte retiré, placés en fin de fil, font réécrire les deux annonces.
- `test_plusieurs_agents_apprennent_la_source_en_meme_temps` : 8 fils, 20 événements chacun. Une seule confirmation est écrite, et `_noter_annonce` n'est appelée qu'une fois.
- `test_une_seule_confirmation_par_ouverture_meme_si_la_source_change` : la deuxième source d'une même ouverture n'est écrite qu'à l'ouverture suivante.
- `test_tous_les_enchainements_de_un_a_quatre_demarrages` : 1554 enchaînements (6 + 36 + 216 + 1296), parcourus en arbre. Chaque enchaînement repart de l'état laissé par son préfixe, qui a déjà été vérifié. À chaque démarrage, le test vérifie A, B, C (contre l'état à la fin du démarrage précédent), D (la promesse « sera dite » en attente : la confirmation est ajoutée) et qu'une source vide n'écrit rien. Il dure 0,10 à 0,11 s. L'état passe d'un démarrage à l'autre par le même aller-retour JSON que `Chantier.sauver` et `Chantier.charger`, mais en mémoire (`_sauver` est neutralisé dans ce seul test) : sur disque, il prenait 25 s, à cause d'environ 2 ms par ouverture de fichier ici. Le passage par le vrai fichier est couvert par les tests nommés.

**Casses essayées** (copie hors du dépôt, `tests/test_demarrage.py` lancé sur chacune)
- Logique de la deuxième tentative (confirmation comparée à la dernière confirmation) : le test exhaustif (invariant A) et le test nommé correspondant échouent.
- Logique de la troisième tentative (l'ancienne boucle remise telle quelle) : le test exhaustif (A) et `test_cle_puis_abonnement_puis_cle...` échouent.
- R1 cassée (départ toujours écrit) : le test exhaustif (C) et 4 autres tests échouent.
- R2 cassée (confirmation toujours écrite) : le test exhaustif (B) et les 2 tests de redémarrage identique échouent.
- Textes retirés ignorés : `test_un_texte_retire...` échoue.
- Drapeau jamais posé : le test concurrent (fil parcouru à chaque événement) et `test_une_seule_confirmation_par_ouverture...` échouent. R2 seule aurait masqué la casse dans le fil.

**Changement de texte d'une phrase**
Une ancienne phrase dont le texte a changé n'est plus reconnue : si toutes changent, la prochaine annonce est réécrite une fois de trop. Si une seule change, l'annonce reconnue d'avant peut égaler la phrase à écrire, et le fil resterait sur l'ancien texte devenu faux : c'est une annonce manquante. Exemple : abonnement, puis clé à l'ancien texte, puis abonnement de nouveau, écarté. D'où `ANCIENNES_ANNONCES` : qui change une phrase y met l'ancien texte. Il compte alors comme annonce dans R1 et R2 sans jamais valoir une phrase actuelle, si bien que le pire cas redevient une annonce de trop. La garantie repose sur cette consigne, écrite au-dessus du tuple ; aucun test ne peut la faire respecter.

**Doutes**
- Une source qui changerait au cours d'une même ouverture n'est dite qu'à l'ouverture suivante. C'est l'unicité par ouverture déjà validée, et en pratique la source suit l'environnement du processus, mais le fil serait faux d'ici là.
- Un fil écrit par une tentative précédente peut déjà contenir deux annonces consécutives identiques ou une confirmation manquante. La règle ne réécrit pas l'historique : elle repart juste à l'ouverture suivante.
- La remontée du fil sous le verrou est linéaire en sa longueur, une fois par ouverture et par famille. C'est négligeable pour des milliers de lignes.
