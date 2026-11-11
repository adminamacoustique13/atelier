# Relais — Tâche A : le pont vers l'Agent SDK (seconde chance)

## 1. Fait
Tous les tests sont dans `tests/test_sdk.py` (71 tests, environ 2,5 s). Ils utilisent un faux client, sauf deux qui font tourner le vrai `ClaudeSDKClient` sur un faux exécutable `claude` écrit dans le dossier temporaire du test. Aucun réseau, aucun compte. Le fichier entier se saute si `claude_agent_sdk` n'est pas installé.

Critères d'origine :
1. Ouverture de session dans un fil à part : `test_options_transmises_au_sdk_dans_un_fil_propre`, `test_reprise_et_role_vide` (avec un UUID), `test_le_client_reste_ouvert_d_un_envoi_a_l_autre`, `test_import_paresseux_du_sdk`, `test_aucun_fil_ne_survit_aux_sessions_fermees`.
2. Texte : `test_texte_relaye_morceau_par_morceau`.
3. Outils : `test_outil_relaye_sous_forme_courte`, `test_un_rappel_qui_leve_ne_tue_pas_la_session`.
4. Autorisations : `test_autorisation_une_fois`, `test_autorisation_toujours_renvoie_la_regle`, `test_autorisation_refusee_avec_le_message`, `test_sans_guichet_l_autorisation_est_refusee`, `test_un_guichet_en_panne_vaut_refus` (y compris `SystemExit`), `test_traduire_reponse` (17 cas), `test_traduire_reponse_toujours_avec_regle`, `test_regle_sdk`, `test_regle_sdk_refuse_les_regles_vides_ou_mal_formees`.
5. Arrêt : `test_arret_pendant_une_autorisation_en_attente`, `test_arret_pendant_une_demande_qui_vit_a_part`, `test_apres_l_arret_aucune_demande_ne_part_au_guichet`, `test_arret_pendant_que_l_agent_travaille` (la tâche de travail est annulée), `test_arret_sans_rien_en_cours_est_sans_danger`. Le texte est comparé au littéral « Arrêté par la personne responsable. ».
6. Fin : `test_fin_rend_texte_cout_et_tokens`, `test_fin_en_erreur`, `test_fin_sans_resultat`, `test_delai_depasse_ferme_aussi_la_demande_au_guichet`, `test_erreur_du_sdk`, `test_un_client_qui_leve_cancelled_error`, `test_fermer`, `test_fermer_depuis_un_rappel`, `test_lire_resultat`.
7. Source de connexion : `test_lire_source`, `test_source_de_connexion_lisible_depuis_le_pont`.

Défauts relevés par le vérificateur :
- Défaut 1 (`fermer` pendant un `envoyer`) : `fermer` attend que le tour en cours rende la main (verrou de la session, avec une borne), puis la fin des déconnexions, avant d'arrêter la boucle. Tests : `test_fermer_pendant_un_envoi` (guichet qui met 30 ms à annuler, `interrupt` de 0,2 s ; ce test échoue sur l'ancien code) et `test_fermer_en_meme_temps_qu_un_envoi_ne_bloque_jamais` (20 courses). J'ai aussi rejoué R5c et E1c à E1e du vérificateur : l'arrêt est rendu en 0,1 s, la déconnexion a lieu, aucun envoi ne finit sur le garde-fou.
- Défaut 2 (Claude Code laissé vivant) : `disconnect` tourne dans une tâche détachée qui n'est jamais annulée ni bornée par le pont. Seul `interrupt` est borné (`delai_interruption_s`, 2 s). Le `Resultat` d'arrêt n'attend pas cette tâche. L'envoi suivant et `fermer` attendent la fin des déconnexions, sans les annuler, dans la limite de `delai_deconnexion_s` (30 s). Tests : `test_une_deconnexion_lente_n_est_jamais_annulee`, `test_l_envoi_suivant_attend_la_fin_de_la_deconnexion`, `test_vrai_client_l_arret_ne_laisse_pas_claude_code_vivant`. Rejoué R3, R3b, R4 et R4c : aucun processus ne survit, et le SDK va jusqu'au SIGTERM.
- Défaut 3 (« toujours » avec une règle vide) : une règle vide, faite d'espaces, `None`, qui n'est pas une chaîne ou mal formée (`Bash()`, parenthèse non fermée, retour à la ligne) vaut « une_fois », sans aucune mise à jour de permissions. Un choix inconnu vaut un refus, avec le message « Le guichet a rendu une réponse incomprise : l'outil est refusé. ».

Compléments :
- 4 : hors d'un tour ou après `arreter()`, une demande est refusée sans appeler `guichet.demander`. Une demande en cours est refusée dès l'arrêt (`PermissionResultDeny(message=ARRET, interrupt=True)`), sans attendre le guichet. `guichet.annuler` est rappelé, dans un fil à part, pour fermer une demande déposée au même moment.
- 5 : toute fin en échec (délai, erreur du SDK, arrêt, résultat en erreur) appelle `guichet.annuler(agent)`.
- 6 : un client qui lève `CancelledError` donne « Le SDK de Claude s'est interrompu sans donner de raison. », et le client est coupé.
- 7 et 8 : faits (voir les tests ci-dessus). Deux tests avec le vrai client : `test_vrai_client_un_tour_complet` et `test_vrai_client_l_arret_ne_laisse_pas_claude_code_vivant`.

## 2. Fichiers touchés
- `atelier/sdk.py` (nouveau)
- `tests/test_sdk.py` (nouveau)
- `pyproject.toml` : `dependencies = ["claude-agent-sdk>=0.2.172"]` dans `[project]`
- `chantier/relais/A.md` (cette fiche)

## 3. Contrats modifiés
Interface livrée :
```python
from atelier.sdk import SessionSDK
session = SessionSDK(
    agent, modele, effort, dossier=None, outils_permis=None, outils_interdits=None,
    mode_permission="default", role_ajoute="", guichet=None, sur_evenement=None,
    delai_max_s=3600, session=None, reprise=False, fabrique_client=None,
)
session.envoyer(consigne) -> Resultat   # synchrone, ne lève jamais
session.arreter()                        # depuis n'importe quel fil, sans danger à vide
session.fermer()                         # idempotent ; attend le tour en cours et les déconnexions
session.source_connexion                 # "abonnement", "clé API" ou ""
session.delai_interruption_s = 2.0       # réglable : borne de `interrupt` lors d'une coupure
session.delai_deconnexion_s = 30.0       # réglable : attente maximale des déconnexions
```
Écarts avec la première version :
- `traduire_reponse(reponse)` et `regle_sdk(regle)` ne prennent plus l'argument `outil`. `regle_sdk` rend `None` pour une règle vide ou mal formée.
- Nouvelles constantes : `INCOMPRIS`, `INTERROMPU`. Celles qui existaient restent : `ARRET`, `SANS_REPONSE`, `SANS_GUICHET`, `REFUS`.
- `envoyer` sur une session fermée rend « La session de cet agent est fermée. ». Un second `envoyer` pendant un premier rend « Cet agent traite déjà une consigne. », sans événement « fin ».
- Événement « fin » : « L'agent a terminé. » en cas de succès, sinon le texte de l'erreur.

Inchangé depuis la première version : `fabrique_client(options)` reçoit un vrai `ClaudeAgentOptions` ; `modele` est passé tel quel (les alias restent à traduire par l'appelant) ; le preset `claude_code` est toujours donné ; après une coupure, l'envoi suivant reprend la session (`resume`) avec l'identifiant annoncé par le SDK ; `session` et `reprise` sont mis à jour en conséquence.

### À savoir pour la tâche C
- `can_use_tool` n'est appelé que si Claude Code conclut « demander ». Il ne l'est jamais pour un outil entier présent dans `outils_permis`, ni en mode `bypassPermissions` ou `dontAsk`, ni pour les règles des réglages utilisateur et projet, qui sont chargés par défaut.
- L'identifiant de session doit être un UUID.
- Un arrêt lancé avant qu'`envoyer` ait posé son drapeau est perdu : l'appelant doit garder sa propre demande d'arrêt.
- `sur_evenement` tourne dans la boucle de la session (texte, outil, attente) : un rappel lent retarde l'arrêt, et un rappel bloquant bloque `envoyer` jusqu'au garde-fou (`delai_max_s` + 30 s). Le rappel « fin » tourne dans le fil de l'appelant.
- Une session jamais fermée garde un fil.
- Le coût d'un tour arrêté est perdu.
- Après un résultat en erreur, si Claude Code sort, l'envoi suivant peut échouer une fois avant de se reconnecter. À essayer en vrai.
- « none » comme source veut dire « pas de clé API » : c'est l'abonnement, mais ce peut aussi être un jeton de passerelle ou un compte non connecté (à savoir pour la tâche E).

## 4. Reste à faire
- Tâche C : brancher `AgentClaude.executer` et `converser` sur `SessionSDK` (alias de modèle, choix des outils, rôle de l'orchestrateur, fermeture des sessions).
- Tâche E : lire `session.source_connexion`. Elle n'est connue qu'après le premier message `init`, donc une fois le premier envoi commencé.

## 5. Doutes et demandes
- Si la personne répond « une_fois » au moment exact de l'arrêt, l'outil peut être permis juste avant que l'interruption parte (1 cas sur 300 dans E7j du vérificateur). La réponse est alors arrivée avant l'arrêt. Je laisse ce cas tel quel.
- « toujours » avec une règle qui vise un autre outil que celui demandé (par exemple `Edit(src/**)` pour `Write`) est transmis tel quel : Claude Code range plusieurs outils sous une même règle. C'est au guichet de proposer une règle juste.
- `claude -p` était lancé avec `--no-session-persistence` dans `executer`. Le SDK n'a pas d'option dédiée (il faudrait `extra_args`). À trancher en tâche C.
- `PermissionRuleValue` n'est pas exporté par `claude_agent_sdk` 0.2.172 : il est importé depuis `claude_agent_sdk.types`.
- Les scripts du vérificateur qui appellent `traduire_reponse(reponse, "Bash")` doivent passer à un seul argument.
