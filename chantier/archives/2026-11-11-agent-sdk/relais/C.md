# Relais C — Les agents passent par le SDK (seconde chance)

## 1. Fait
Les preuves sont dans `tests/test_agents.py` (56 cas, environ 2,5 s). Ils tournent sur le faux client de `tests/test_sdk.py`, importé tel quel, sans aucun appel réel ni processus lancé. Une fixture automatique vérifie après chaque test qu'aucun fil `atelier-sdk-*` ne survit. Les 35 tests d'origine passent sans modification.

1. **Mêmes `Resultat` qu'avant.**
   - `test_executer_rend_le_meme_resultat_que_claude_p` (succès, erreur, erreur sans texte) et `test_converser_rend_le_meme_resultat_que_claude_p` comparent chaque `Resultat` à celui que `lire_sortie_claude` ou `lire_flux_claude` tiraient du même tour écrit au format de `claude -p`. Le second vérifie aussi `sur_texte` et `sur_outil`.
   - Réglages transmis : `test_executer_traduit_le_modele_et_garde_l_effort`, `test_converser_garde_le_role_la_session_et_la_reprise`, `test_converser_transmet_le_dossier`, `test_le_delai_de_l_agent_est_transmis_au_pont`.
   - Fermeture : `test_chaque_session_est_fermee_meme_apres_une_erreur`.
   - Le moteur réel, sans changement : `test_le_moteur_conduit_un_chantier_avec_l_agent_du_sdk`.
2. **Événements des ouvriers et des vérificateurs.** `test_ouvriers_et_verificateurs_emettent_en_direct` (noms `B-ouvrier-1`, `B-verificateur-2`, `orchestrateur`), `test_la_conversation_emet_et_garde_ses_rappels`, `test_un_rappel_qui_leve_ne_gene_pas_l_agent`.
3. **Outils permis et guichet.**
   - Règles du profil : `test_outils_de_l_ouvrier_avec_les_autorisations_du_profil`, `test_sans_cle_autorisations_les_outils_sont_ceux_d_aujourd_hui`.
   - Seules les règles simples sont gardées, pour l'ouvrier comme pour le vérificateur : `test_seules_les_regles_simples_sont_retenues` (cas `Read,Write`, `Read Write`, `Bash(npm test:*),Write`, `Bash(a)(b)`, `Bash()`, retour à la ligne, parenthèse non fermée).
   - Clé mal formée (nombre, booléen, chaîne, dictionnaire, `None`) : `test_une_cle_autorisations_mal_formee_vaut_une_liste_vide`.
   - Guichet : `test_un_outil_non_permis_passe_par_le_guichet` (ouvrier, vérificateur, conversation).
4. **Pas d'outil d'écriture en lecture seule.** `test_le_verificateur_n_a_aucun_outil_d_ecriture`, `test_la_conversation_reste_en_lecture_seule_sans_les_commandes_du_projet`.
5. **Demande d'autorisation de l'agent simulé.**
   - La demande : `test_l_agent_simule_demande_une_autorisation_au_premier_ouvrier`, `test_ni_le_verificateur_ni_l_orchestrateur_ne_jouent_la_demande` (lancés en premier, ils ne la jouent pas), `test_la_demande_simulee_attend_la_vraie_reponse_du_guichet`, `test_sans_guichet_l_agent_simule_ne_demande_rien`, `test_la_demonstration_se_deroule_avec_une_demande_d_autorisation`.
   - L'arrêt : `test_arreter_l_agent_simule_pendant_son_delai`, `..._pendant_sa_demande`, `test_une_demande_deposee_juste_apres_l_arret_est_fermee_aussi`, `test_un_arret_sans_rien_en_marche_ne_touche_pas_l_agent_simule`, `test_arreter_la_conversation_simulee_puis_reprendre`.
6. **Plus de `claude -p`.** `test_plus_aucun_claude_p_n_est_lance` (`subprocess` est absent du fichier, et `run` et `Popen` sont piégés), `test_import_des_agents_ne_charge_pas_le_sdk`.
7. **Reliquats du pont** (`tests/test_sdk.py`). Chaque test échoue sur l'ancien pont : a. `test_une_demande_tardive_d_un_client_coupe_ne_va_jamais_au_guichet` ; b. `test_fermer_juste_avant_la_creation_de_la_boucle_libere_le_fil` ; c. `test_une_demande_annulee_par_claude_code_ne_reste_pas_ouverte`.

**Contrat D1 (arrêt).**
- `test_arreter_un_ouvrier_en_marche`.
- `test_apres_un_arret_l_appel_rend_la_main_session_fermee` (défaut 1 de la vérification ; ouvrier et conversation) : le client est lent à s'interrompre et à se déconnecter, et au retour de l'appel arrêté il est déconnecté et le fil de session est libéré.
- `test_un_arret_qui_rend_vrai_donne_toujours_le_resultat_d_arret` (défaut 2 ; `AgentClaude` et agent simulé, `executer` et `converser`) : l'arrêt est forcé au moment où l'appel décide de son résultat.
- `test_un_arret_juste_avant_le_tour_n_est_pas_perdu`, `test_un_arret_sans_rien_en_marche_est_sans_effet`, `test_arreter_la_conversation_puis_le_message_suivant_marche`, `test_attributs_par_defaut`, `test_source_de_connexion_connue_des_le_debut_du_tour`.

**Défauts de la vérification.** Les essais `arret2.py` et `debordement.py` ont été rejoués sur une copie de cette version.
- L'ancien client est déconnecté avant que l'appel arrêté rende la main (1,31 s, puis seulement le client suivant). Le vrai Claude Code factice est mort au retour de l'appel.
- `arreter` rend False dans la fenêtre forcée.
- La tentative 2 de l'essai de débordement est validée.

**Solidité des tests.** Vingt et une altérations du code ont été essayées sur une copie (douze au premier passage, neuf à celui-ci). Chacune fait échouer au moins un test. Les neuf de ce passage : aucune attente de la fermeture, la décision prise avant le retrait du poste (pour `AgentClaude`, l'agent simulé et sa conversation), aucun dossier en conversation, aucun délai transmis, aucun filtre des règles simples, une clé qui n'est pas une liste, et la demande simulée jouée par un autre rôle que l'ouvrier.

## 2. Fichiers touchés
- `atelier/agents.py`
- `atelier/sdk.py` (les trois reliquats seulement, rien de plus à ce passage)
- `tests/test_agents.py` (nouveau)
- `tests/test_sdk.py` : un type d'étape `Geste` pour le faux client, et les trois tests des reliquats
- `chantier/relais/C.md`

## 3. Contrats modifiés
Interface fournie à D1, la même sur `AgentClaude` et `AgentSimule` (signatures de `executer` et `converser` inchangées) :
```python
agent.guichet            # None par défaut ; transmis au pont à chaque appel
agent.sur_evenement      # None par défaut ; lu au début de chaque appel
agent.arreter(tache: str | None = None) -> bool   # sans tâche (ou ""), vise l'orchestrateur
agent.source_connexion   # "abonnement", "clé API" ou "" ; mise à jour dès le premier événement
AgentClaude(profil=None, delai_max_s=3600, fabrique_client=None)  # fabrique : pour les tests
```
- **Quand `executer` ou `converser` rend la main, sa session est fermée et son client déconnecté, y compris après un arrêt.**
  - Chaque appel ouvre sa propre session du pont, comme un `claude -p` par appel ; la conversation reprend sa session par `resume`.
  - `arreter` ne bloque pas : il pose le drapeau de l'appel et ferme la session dans un fil à part (`atelier-arret-<agent>`). `fermer` n'oublie pas un arrêt arrivé avant le tour, contrairement à `SessionSDK.arreter`.
  - C'est l'appel arrêté qui attend la fin de cette fermeture : il rend la main après la sortie de Claude Code (au plus ce que bornent `fermer` et le pont, soit 2 s d'interruption et 30 s de déconnexion).
- **Si `arreter` a rendu True pour un appel, cet appel rend `Resultat(ok=False, erreur="Arrêté par la personne responsable.")`, toujours.**
  - La décision est prise après le retrait du poste.
  - Un arrêt arrivé après la fin du tour, mais pendant la fermeture, donne aussi l'arrêt. Le coût et les tokens du tour sont alors gardés.
- Chaque appel émet exactement un événement « fin ». Si le pont n'a pas commencé de tour, c'est l'agent qui l'émet.
- Un appel sans tâche (la planification par `python3 -m atelier planifier`) et la conversation partagent le nom `orchestrateur` et la cible de `arreter()`.
- **Outils.**
  - Seules les entrées simples de `autorisations` sont gardées : une chaîne faite d'un nom d'outil, suivi ou non d'une seule paire de parenthèses au contenu non vide, sans virgule, sans parenthèse ni caractère de contrôle à l'intérieur. Les espaces autour sont retirés.
  - Une clé qui n'est pas une liste vaut une liste vide.
  - En lecture seule, `Edit`, `Write`, `MultiEdit` et `NotebookEdit` sont interdits (avant : `Edit` et `Write`), et les règles qui les visent sont retirées, sans tenir compte de la casse.
- **Agent simulé.**
  - À chaque appel, il émet « outil » (« Lit la consigne »), puis « fin ».
  - Au premier ouvrier, et seulement à un ouvrier, si un guichet est attaché : « attente » (« Lance npm install left-pad »), puis « texte » (« Réponse de la personne responsable : autorisé une fois. », « autorisé pour ce projet. » ou « refusé. », suivi de l'indication), puis « outil » si la commande est permise.
  - En conversation, il émet « texte » mot à mot.
- **Écarts de texte d'erreur avec `claude -p`**, sans effet sur le moteur.
  - Tour sans résultat : « Claude Code s'est arrêté sans répondre. ».
  - Panne : « Le SDK de Claude a échoué : ... ».
  - Délai dépassé : « L'agent n'a pas fini dans le délai de N secondes. ».
  - Pour un ouvrier, un `result` vide est remplacé par le texte reçu en direct.
- **Pont, côté interne** : `can_use_tool` est une fonction propre à chaque client, et `guichet.annuler(agent)` est appelé à la fin de chaque tour.
- `--no-session-persistence` est abandonné, comme décidé.

### À savoir pour la tâche D1
- Un ouvrier arrêté et un vérificateur arrêté sont lus aujourd'hui par le moteur comme un échec ordinaire (« ne_sait_pas »). D1 doit reconnaître l'arrêt dans les deux branches du jugement et rendre la tâche à la personne responsable.
- Entre l'ouvrier et le vérificateur d'une même tâche (pendant les contrôles du moteur), aucun agent n'est en marche : `arreter(tache)` rend False et le vérificateur démarrerait ensuite. D1 doit garder son propre drapeau d'arrêt par tâche.
- Se fier au `Resultat`, pas à l'événement « fin ».
- Après un arrêt de la conversation, le serveur afficherait « Je n'ai pas pu joindre Claude Code. Arrêté par la personne responsable. ». Si c'était le premier message, il repartirait sur une session neuve.
- Les noms d'agent se relisent par la droite (`rsplit("-", 2)`) : un identifiant de tâche peut contenir un tiret ou un point.
- L'attente au guichet compte dans le délai de l'agent.
- N'écrire dans `autorisations` que des règles simples : les autres sont ignorées.
- Un vrai `Guichet` posé sur l'agent simulé ferait attendre `python3 -m atelier instantanes` jusqu'au délai du guichet.
- Après un arrêt, l'appel arrêté met le temps de la sortie de Claude Code à rendre la main : le fil du moteur ou du serveur qui l'attend reste occupé ce temps-là.

### À essayer en vrai (tâche F)
- Un outil interdit n'arrive jamais au guichet, et l'interdit l'emporte sur une règle « toujours ».
- La reprise d'une session après un tour arrêté.
- Le temps que met Claude Code à mourir après une interruption.
- L'avertissement `CanUseToolShadowedWarning`, écrit à chaque session (les outils entiers comme `Read` sont permis alors que `can_use_tool` est branché).

## 4. Reste à faire
- D1 : poser `agent.guichet` et `agent.sur_evenement`, et traiter l'arrêt dans le moteur (voir la liste ci-dessus).
- D3 : le mode de permission des ouvriers est fixé à `acceptEdits` dans `executer`. Il faudra un réglage pour le menu des modes.
- D2 : pour WebFetch et les autres outils sans geste connu, l'événement « attente » ne donne que le nom de l'outil. La phrase du guichet est plus parlante pour la carte.

## 5. Doutes et demandes
- « Un outil interdit n'arrive jamais au guichet » repose sur Claude Code. Le faux client ne peut pas le montrer : les tests prouvent seulement que la liste d'interdits est transmise.
- Comme le veut le contrat, le vérificateur reçoit les règles `Bash(...)` de `autorisations`, dont certaines écrivent sur le disque (`Bash(npm install:*)`). Si l'on veut un vérificateur strictement en lecture, il faudra en décider.
- Pont : quand un arrêt refuse une demande en attente, `_autoriser` lance `guichet.annuler(agent)` dans un fil à part. Ce fil pourrait fermer la demande d'un nouveau tour du même nom, et seul `orchestrateur` est réutilisé. Le cas est rare et existait déjà : je n'y ai pas touché.
- Aucune demande hors périmètre.
