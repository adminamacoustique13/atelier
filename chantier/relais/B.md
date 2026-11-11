# Relais B — Le guichet des autorisations (troisième passe)

## 1. Fait
1. Liste des demandes ouvertes (id, agent, outil, phrase, règle, détail), dans l'ordre d'arrivée : `test_ouvertes_montre_la_phrase_la_regle_et_le_detail` (texte exact de la phrase lu dans `ouvertes()` pour Bash, WebFetch et Write, et la phrase « Cette commande ne peut être autorisée qu'au cas par cas. » d'une commande enchaînée), `test_identifiants_uniques_et_ouvertes_pret_pour_du_json`, `test_phrases_en_francais`, `test_phrase_garde_les_retours_a_la_ligne_visibles`, `test_detail_le_texte_complet_de_la_demande`, `test_detail_borne_dit_combien_de_caracteres_sont_coupes`.
2. `demander` ne bloque que le fil de l'agent : `test_deux_demandes_simultanees_repondues_dans_l_ordre_inverse`, `test_vingt_agents_en_parallele_recoivent_chacun_leur_reponse`.
3. `repondre` débloque la bonne demande et la retire ; choix inconnu, identifiant inconnu, déjà réglé ou qui n'est pas une chaîne rendent `False` sans exception : `test_reponses_invalides_ne_debloquent_rien`, `test_une_reponse_apres_le_delai_ne_debloque_rien`.
4. Règle « toujours » la plus étroite : `test_regle_bash_la_commande_et_ses_deux_premiers_mots`, `test_regle_webfetch_le_nom_de_domaine_seul`, `test_regle_autres_outils_le_nom_seul`. Prudence : `test_regle_bash_aucune_regle_si_un_operateur_suit_les_deux_premiers_mots` (un cas par caractère filtré, placé après les deux premiers mots), `test_regle_bash_aucune_regle_pour_un_lanceur_ou_un_mot_douteux` (tous les contournements signalés), `test_regle_bash_aucune_regle_quand_un_lanceur_precede_une_commande_simple`, `test_regle_bash_aucune_regle_pour_un_interpreteur_seul`, `test_regle_bash_aucune_regle_pour_un_lanceur_de_la_derniere_liste`, `test_regle_bash_les_noms_sont_compares_sans_tenir_compte_de_la_casse`, `test_regle_webfetch_aucune_regle_pour_une_adresse_douteuse`, `test_regle_webfetch_aucune_regle_pour_la_machine_ou_un_reseau_interne`, `test_toujours_refuse_pour_une_demande_sans_regle_sure`.
5. Délai dépassé, « non » et « Pas de réponse de la personne responsable. » (texte littéral) : `test_delai_depasse_la_demande_se_ferme_sur_non`, lancé dans un fil avec un `join` borné.
6. Guichet simulé : `test_guichet_simule_suit_son_scenario_puis_dit_non`, `test_guichet_simule_n_accorde_jamais_une_regle_que_le_vrai_n_aurait_pas_proposee`, `test_guichet_simule_refuse_un_scenario_inconnu`.
7. `annuler(agent)`, « Arrêté par la personne responsable. » (texte littéral) : `test_annuler_ferme_les_demandes_de_cet_agent_seulement`.

Robustesse (complément 6) : `test_demande_bizarre_reste_une_demande_normale_sans_regle` (entrée qui n'est pas un dictionnaire, `{"command": None}`, outil qui n'est pas une chaîne), `test_delai_doit_etre_positif` (0, -1, NaN), `test_delai_enorme_borne_et_demande_sans_fantome` (inf, 1e300, 10**400).

Contrôle des tests : les 55 nouveaux cas de la troisième passe échouent sur le code de la seconde. Sur une copie, 38 altérations du code (chaque caractère du filtre retiré, textes des messages changés, phrase ou détail vidés, chemin non retiré, deuxième mot non examiné, lanceurs retirés de la liste, filtre d'adresse affaibli, délai non borné, règle du scénario acceptée...) font toutes échouer au moins un test. Tous les `join` ont un garde-fou de 5 s.

## 2. Fichiers touchés
- `atelier/guichet.py` (nouveau)
- `tests/test_guichet.py` (nouveau, 206 tests, moins d'une seconde)
- `chantier/relais/B.md`

## 3. Contrats modifiés
Contrat commun respecté tel quel. Interface livrée :
```python
from atelier.guichet import Guichet, GuichetSimule, Reponse, regle_pour, phrase_pour, detail_pour
Reponse(choix, message="", regle="")             # dataclass
Guichet(delai_s=3600)       # ValueError si delai_s n'est pas > 0 (NaN compris) ; borné à 24 h
guichet.demander(agent, outil, entree) -> Reponse            # ne lève pas, même sur entrée bizarre
guichet.ouvertes() -> list[dict]
    # {"id", "agent", "outil", "phrase", "regle", "detail"} : six chaînes
guichet.repondre(identifiant, choix, message="") -> bool     # ne lève pas
guichet.annuler(agent) -> int
GuichetSimule(scenario=())                       # sous-classe de Guichet
guichet_simule.demandes                          # fiches de toutes les demandes reçues
regle_pour(outil, entree) -> str                 # "" quand aucune règle sûre
phrase_pour(agent, outil, entree, regle="") -> str
detail_pour(outil, entree) -> str
```
- **`detail`** (nouveau) : le texte complet. La commande entière pour Bash, l'adresse entière pour WebFetch, le chemin pour Write, Edit ou Read. Sinon l'entrée en JSON (ou sa représentation Python si elle ne passe pas en JSON). Le tableau de bord l'affiche à la demande. Au-delà de 4 000 caractères, il est coupé et se termine par « [suite coupée : N caractères de plus] ».
- **Phrase** : coupée à 160 caractères, avec « [...] ». Un retour à la ligne y devient « [retour à la ligne] ». Les autres caractères de contrôle deviennent « ? ». Pour une commande Bash sans règle, la phrase ajoute « Cette commande ne peut être autorisée qu'au cas par cas. ». Si l'entrée ne permet pas de dire ce qui est demandé, la phrase est prudente : « A veut utiliser l'outil Bash. ».
- **Pas de « toujours » sans règle sûre** (écart conservé) : `regle` vide, `repondre(id, "toujours")` rend `False`, la demande reste ouverte. Le tableau de bord masque le bouton « toujours » quand `regle` est vide.
- **Filtre Bash choisi** : pas de règle dès qu'un doute existe, en quatre contrôles successifs.
  1. **Caractères.** Aucun caractère qui enchaîne, redirige ou substitue (`; & | < > ` $ ( ) \`), ni aucun caractère de contrôle (retour à la ligne, tabulation compris), où qu'il soit dans la commande.
  2. **Forme des deux premiers mots.** Lettres ASCII, chiffres et `. / @ + - _` seulement. Pas de guillemet, de joker ni de `=`.
  3. **Nom de chaque mot.** On compare chacun des deux mots par son nom, en minuscules, sans chemin ni numéro de version (`/USR/BIN/Python3.12` donne `python` ; sur macOS, `ENV` lance `env`).
     - Aucun ne doit être un lanceur (liste `LANCEURS`) : shells, `sudo` et ses semblables, `env`, `time`, `nice`, `timeout`, `xargs`, `find`, `exec`, `ssh`, `docker`, `podman`, `npx`, `bunx`, `uvx`, `ts-node`, `tsx`, `caffeinate`, `xvfb-run`, `valgrind`, `firejail`, `gosu`, `emacs`...
     - La paire des deux mots ne doit pas lancer une commande quelconque (liste `PAIRES`) : `uv run`, `poetry run`, `pipenv run`, `conda run`, `nix run`, `pipx run`, `hatch run`, `pdm run`, `npm x`, `pnpm dlx`, `pnpm exec`, `yarn dlx`, `bun x`, `git -c` ou `git -C`...
     - Un interpréteur seul n'a pas de règle (`python3` seul couvrirait `python3 -c ...`). Le second mot ne doit pas non plus être un interpréteur.
  4. **Option en deuxième mot.** Après un interpréteur, seul un nom de script ou `-m` est accepté, ce qui conserve `Bash(python3 -m:*)` du contrat ; toute autre option est refusée (`-Bc`, `-u`, `-p`, `-r`, `--eval`...). Après une autre commande, on refuse un groupe d'options courtes contenant `c` ou `e` (`-lc`, `-ne`, `-c`) et les options longues `--eval`, `--command`, `--exec`, `--execute`, `--print`, `--run`.

  J'ai gardé une liste d'exclusions, mais la règle « interpréteur suivi d'une option : non, sauf `-m` » est plus solide qu'une liste d'options : elle ferme aussi `python3 -u -c x` et `node --experimental-x -e x`. Je n'ai pas trouvé de liste d'autorisation aussi courte qui respecte le contrat des « deux premiers mots ».
- **Filtre WebFetch** : il faut une adresse en `http` ou `https`, sans `\`, `@`, espace ni caractère de contrôle, et dont l'hôte est un nom de domaine ordinaire. Un nom ordinaire, ce sont au moins deux étiquettes `[a-z0-9-]` et une dernière étiquette alphabétique (ou `xn--`), ce qui exclut les adresses IP, les formes numériques comme `0x7f.1` ou `2130706433`, IPv6 et `%`. La machine elle-même et les réseaux internes n'ont jamais de règle : hôte sans point (`localhost`, `intranet`), ou finissant par `.localhost`, `.local`, `.internal`, `.lan` ou `.home.arpa`, car la règle ignore le port et ouvrirait tous les services locaux. Sinon : pas de domaine, pas de règle, et la phrase montre l'adresse brute.
- **Guichet simulé** : la règle d'un « toujours » est toujours celle que le vrai guichet proposerait, jamais celle écrite dans le scénario. Quand cette règle manque, le vrai guichet refuserait « toujours » et garderait la demande ouverte ; le simulé, qui doit répondre tout de suite, répond « une_fois ». Scénario épuisé : « non », « Le scénario de démonstration ne prévoit pas cette demande. ».
- **Concurrence** : inchangée. Seule nouveauté, la fermeture après l'attente est passée dans un `finally`, pour qu'aucune demande fantôme ne reste dans `ouvertes()` si l'attente était interrompue.

## 4. Reste à faire
- Rien pour B. Le serveur (D1) peut afficher `detail` et masquer « toujours » quand `regle` est vide.

## 5. Doutes et demandes
- La largeur des « deux premiers mots » (`python3 -m`, `npm run`) reste celle du contrat, sans cas particulier.
- Le filtre Bash refuse plus large qu'il ne faut : `$HOME`, `tar -cvf`, `conda env`, toute commande `docker` n'ont pas de règle « toujours ». C'est voulu : une demande de plus vaut mieux qu'une règle trop large.

**Risque qui reste.** Le filtre écarte les lanceurs que l'on connaît, pas tous : il existe toujours un outil, un alias ou un script maison qui sait lancer une autre commande, et aucune liste ne les connaîtra tous. De plus, une règle « toujours » sur un outil qui exécute du code autorise en pratique n'importe quelle commande. Pour `npm run`, `cargo run` ou `make`, c'est tout ce que le code du projet voudra faire, aujourd'hui comme après une modification par un agent. Pour `python3 -m`, c'est immédiat et sans rapport avec le projet : `python3 -m timeit` suivi d'un bout de code lance déjà ce qu'on veut, même dans un projet sain. D'autres lanceurs restent ouverts, par exemple `go run`, `kubectl run`, `mise x`, `screen -dm` et `arch -x86_64`. Côté WebFetch, un nom public qui pointe vers la machine elle-même (`127.0.0.1.nip.io`) garde une règle. La vraie protection est ailleurs, et elle n'existe pas encore : il faut que la carte d'autorisation montre la règle exacte avant le clic (c'est un critère de la tâche D2), pour que la personne responsable ne clique « toujours » que si elle accepte tout ce que cette règle couvre.

*Ce paragraphe a été corrigé par l'orchestrateur après la troisième vérification : deux phrases, reprises de sa consigne, étaient l'une fausse (la carte n'affiche pas encore la règle), l'autre trompeuse (`python3 -m` ne dépend pas du code du projet).*
