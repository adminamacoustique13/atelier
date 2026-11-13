# Fiches du moteur — second objectif du chantier (2026-11-13)

Plan rendu par l'architecte le 2026-11-13, sur la base 07561c1. Il porte dans le moteur d'ici sept règles de la ligne « PC et autonomie » (la « référence », 5f2c337, lue et jamais fusionnée). L'ossature d'ici est gardée : six places et régulateur, vérificateur hors place, objet `Jugement`, mesure des phases, demande « blocage », contrôles rejoués à chaque entrée, fichiers partagés par motifs, copie jetable du vérificateur, état écrit d'un seul geste, démonstration simulée.

Les sept règles, dans les mots de la personne responsable :
1. L'ouvrier reste ouvert après avoir rendu. Un contrôle rouge ou un oubli lui revient sans compter de refus. Cela remplace la reprise de session, qui n'a rien donné sur le PC.
2. Le travail refusé est gardé, et une sous-tâche ne règle que ce qui reste.
3. Le modèle ne monte que si le fond est faux, et une retouche n'est vérifiée que sur ce qu'elle touche.
4. Le vérificateur ne rejoue plus la suite de tests, et l'ouvrier rend une preuve par critère.
5. Après une panne ou un arrêt, le chantier patiente puis repart seul, travail gardé.
6. Les niveaux de vérification sont branchés, avec leur plancher : un calcul ne passe jamais sans vérificateur.
7. Le budget en dollars, corrigé pour compter aussi un agent coupé.

## Choix d'ensemble (les contrats entre les tâches)

### a. L'ouvrier ouvert
- Mécanisme : un `ClaudeSDKClient` gardé connecté, `connect()` une fois puis `query()` et `receive_response()` à chaque demande. `SessionSDK` le fait déjà (`sdk.py`) ; c'est `AgentClaude._travailler` qui ferme après chaque appel. La référence ne ferme pas, range la session par tâche et la ferme par `liberer`.
- Ici : l'agent garde l'ouvrier, et le moteur garde son appel `executer(reprendre=session)`, servi par l'ouvrier ouvert s'il l'est encore.
- La reprise par session reste comme repli quand l'ouvrier n'est plus ouvert. La règle « copie inchangée, le refus vaut » la rend sans coût là où elle ne donne rien.
- Arbitré à M3 : un ouvrier n'est gardé ouvert que si l'appelant le demande, appel par appel (`executer(..., garder_ouvert=True)`), et celui qui le demande le libère. Le moteur (M9) lit le réglage `ouvrier_ouvert` du profil, passe `garder_ouvert=True`, appelle `liberer(tache)` à la fin de chaque tâche hors de son verrou, et `liberer_tous()` à l'arrêt de l'Atelier.
- En attente d'un verdict, l'ouvrier ouvert ne tient ni place ni jeton et n'est pas compté en marche ; il est borné par `ouverts_max`. Un retour reprend place et jeton avant les tâches neuves.
- L'arrêt de la tâche, une suspension ou une erreur le ferment. À l'arrêt de l'Atelier il meurt, et la copie reste.

### b. Après un refus
Tout se décide sur des champs de `Jugement` (`origine`, `motif`, plus `lisible`, `nature`, `reste`, `fichiers`, `meme_defaut`, `fond_faux`), jamais sur un début de phrase, dans cet ordre :
1. arrêt, empêchement ou consigne : inchangé ;
2. même défaut deux fois de suite : demande « blocage », cause `meme_defaut`, qui remplace `sans_cran` et `repete` ;
3. reste nommé et copie gardée : sous-tâche ;
4. tentatives épuisées : tâche rendue ;
5. fond faux : montée ;
6. sinon : même niveau, sur la copie gardée.

Arbitré à M6 : une panne est neutre pour tout ce qui décide de la suite d'une tâche. Les entrées `attente_panne` sont sautées par `_fenetre`, `_passes_du_depart` et les statistiques ; le compte des pannes ne revient à zéro que lorsqu'un agent a réellement rendu un travail jugé, jamais sur une limite, une surcharge ou une connexion perdue.

### c. Reprise seule après un arrêt
Sûre à ces conditions : `tache.copie` est écrit dans l'état avant chaque départ ; le chargement ne fait que changer l'état, et le serveur relance seulement avec un contrat validé, le port pris et un verrou par dépôt tenu ; la relance est annoncée au fil et attend 30 s ; la tentative est rendue trois fois au plus par tâche ; une tâche « revenue » ne repart jamais seule ; la barrière du budget s'applique ; `reprise_auto: false` rétablit la règle d'avant.

### d. Formats
- `Tache` (types fixés par M1, alignés sur la référence) : `copie: str` ("" : aucune), `reste: dict` (`genre`, `points`, `fichiers`, `en_cours` ; vide quand rien ne reste), `sous_taches: int`, `releve: str`, `releve_sur: str`, `pannes: int`. `Tache.sous_tache_possible(maxi)` : `reste` non vide, `copie` non vide et `sous_taches < maxi`.
- `Resultat` (M1) : `ouverte: bool`, `nature: str` (chaîne libre, vide sans échec), `cout_incomplet: bool`, tous hors comparaison.
- `dosage` (M1) : `correcteur(modele, prevu="")`, `sous_tache(modele, prevu="", documents=False, rang=1)`, `que_des_documents(fichiers)`.
- `Contrat` : `max_cout_usd: float` (0 : pas de budget).
- Historique : issues `interrompue` et `attente_panne`, clés `retour`, `sous_tache`, `pendant`.
- Profil : `budget_usd`, `pauses_panne_s`, `ouvrier_ouvert`, `ouverts_max`, `retours_controles` (3), `complements` (1), `sous_taches` (2), `reprise_auto`, `reprise_apres_arret_s`.
- Un état écrit par le code actuel reste lisible : `depuis_dict` donne leur valeur par défaut aux clés absentes, et les clés inconnues sont ignorées.
- Consignes (signatures fixées par M2) : `consigne_ouvrier(tache, contrat, profil, remarques="", sur_place=False)` ; `consigne_verificateur(tache, contrat, profil, copie_jetable=False, conflits="", sortie_controles=None)` ; `consigne_verificateur_bornee(..., sortie_controles, verdict_complet=False)` ; `consigne_reverification(tache, contrat, profil, verdict_precedent, copie_jetable=False, sortie_controles=None, fichiers=None)` ; `consigne_sous_tache(tache, contrat, profil, reste: list[str], nom, genre="", fichiers=None)`. Passer `None`, pas `""`, à `sortie_controles` quand rien n'a été joué. Seul `genre="verdict"` fait dire que le reste est conforme. Une retouche suppose le reste déjà jugé par un vérificateur.
- `lire_verdict` : toujours `valide`, `motif` (`bacle`, `local`, `ne_sait_pas`, `consigne`), `resume` ; seulement s'ils sont remplis `reste`, `fichiers` (listes de textes) et `meme_defaut` (vrai).

### e. La page
Le coût « X $ sur Y $ », « travail gardé » sur une tâche revenue, le vérificateur selon le niveau, la demande de budget. Pauses et sous-tâches s'affichent déjà par la phase.

## Vagues
- V0 : M1, M2.
- V1 : M3 à M8.
- V2 : M9 à M12.
- V3 : M13, M14.

Chaque tâche part sur la base de la vague précédente sans attendre sa vérification. `agents.py` est touché par M1 (`Resultat`), M3, M4 (`_arrete`) et M12 (`_travailler`) ; `sdk.py` par M4 seule.

## M1. Formats
Tous lisent ces champs. Un état actuel doit rester lisible.
1. Un état sans les champs de (d) se charge avec leurs valeurs par défaut.
2. Une clé inconnue est ignorée au chargement.
3. `Tache.sous_tache_possible(maxi)` est vrai seulement avec des points, une copie et un compte sous `maxi`.
4. `Resultat` gagne `ouverte`, `nature` (arret, delai, limite, surcharge, reprise, connexion, budget, panne) et `cout_incomplet`, hors comparaison.
5. `dosage.correcteur`, `sous_tache` et `que_des_documents` rendent ce que rend la référence.

Périmètre : `modele.py`, `dosage.py`, `agents.py` (`Resultat`). Preuve : état figé écrit en clair dans `test_modele`, table de cas dans `test_dosage`. Sonnet, effort moyen ; vérification bornée.

## M2. Consignes
Deux refus sur quatre venaient d'une preuve absente. Le vérificateur rejouait cinq minutes de tests.
1. `consigne_ouvrier` exige une ligne par critère avec la preuve constatée ; avec `sur_place=True`, elle dit que le travail est resté dans le dossier.
2. `consigne_verificateur` et `consigne_reverification` avec `sortie_controles` interdisent de rejouer la suite et demandent de produire soi-même une preuve manquante ; sans ce paramètre, le texte est inchangé.
3. `lire_verdict` accepte `local` et rend `reste`, `fichiers` et `meme_defaut` seulement s'ils sont remplis.
4. `consigne_sous_tache(tache, contrat, profil, reste, nom)` ne donne que le reste.
5. `consigne_reverification(fichiers=…)` nomme les fichiers changés.

Périmètre : `consignes.py`. Sonnet, effort élevé ; vérification bornée.

## M3. Agents : l'ouvrier reste ouvert
Huit reprises de session sur huit n'ont rien donné sur le PC.
1. Un ouvrier rendu sans erreur ni arrêt reste connecté (`ouverte`), sauf `ouvrier_ouvert: false` ou `ouverts_max` atteint.
2. `executer(reprendre=session)` sur lui donne une seule connexion et deux demandes au faux client ; sinon la reprise par session se fait comme aujourd'hui.
3. `liberer(tache)` et `liberer_tous()` déconnectent une fois, sans lever.
4. Un nouvel ouvrier pour la tâche, une erreur ou un arrêt ferment l'ouvrier ouvert.
5. `AgentSimule(garde_ouvert=True)` suit le même contrat, avec durées, « fin » par tour et jeu `suites` (« rien », « erreur ») ; par défaut il ne change pas.

Périmètre : `agents.py` (`AgentClaude.executer`, `_travailler`, `liberer`, `liberer_tous` ; `AgentSimule.executer`, `_ouvrir_session`). Preuve : un test par chemin (suite, arrêt en tour, arrêt en attente, erreur, délai, plafond, mode changé entre deux tours), avec un faux client à durées non nulles. Opus, effort élevé ; vérification complète.

## M4. Pont : coût juste et nature des échecs
Un agent en erreur ou coupé compte zéro. `total_cost_usd` est un cumul par connexion.
1. Deux tours de cumul 0,10 puis 0,25 rendent 0,10 et 0,15.
2. Un tour fini en erreur porte son coût.
3. Sur arrêt ou délai, le pont attend au plus `delai_interruption_s` le message de fin et porte son coût ; sans message, il pose `cout_incomplet` et ne bloque pas.
4. Chaque échec porte sa `nature` ; « connexion » se lit dans le pont seulement (`authentication_failed` ou signes du texte).
5. `budget_usd` devient `max_budget_usd` ; une fin `error_max_budget_usd` rend la nature « budget ».
6. `_arrete` garde le coût et la nature.

Périmètre : `sdk.py` (`lire_resultat`, `_derouler`, `_qualifier`, `_deconnecter`, `_fabriquer`, `_suivre_assistant`, `_suivre_fin`), `agents.py` (`_arrete`). Preuve : un test par chemin (arrêt, délai, avec et sans message de fin). Opus, effort élevé ; vérification complète.

## M5. Vérification : niveaux, retouche, contrôles non rejoués
Les niveaux ne sont appelés que par les tests. Un calcul ne doit jamais passer sans vérificateur.
1. Le niveau vient de `dosage.niveau_verification` ; bornée donne `consigne_verificateur_bornee` et le même modèle.
2. Mécanique : aucun vérificateur. Sans commande de contrôle au profil, elle devient bornée.
3. Délicate, physique ou réparation réglées « mecanique » au profil : le vérificateur complet part quand même.
4. Le vérificateur reçoit la sortie des contrôles.
5. Un refus lisible `bacle` ou `local` écrit `releve` et `releve_sur` ; la vérification suivante est une retouche bornée au niveau de l'ouvrier (complète pour les types du plancher), avec les fichiers changés.
6. `Jugement` porte les champs de (b).

Périmètre : `moteur.py` (`Jugement`, `_juger`, `_controler`, `_verifier`, `_avis`, `_lire_avis`, `_lancer_verificateur`, `_consigne_de_verification`, `_attendre_jeton`). Attend M2. Preuve : un test par niveau, plus le plancher, un arrêt avant un vérificateur borné, une limite pendant. Opus, effort élevé ; vérification complète.

## M6. Pannes d'agent : patienter
Une coupure ne dit rien du travail. Deux erreurs de suite rendaient la tâche.
1. Nature « panne » : rien n'est compté, place et jeton sont rendus, la relance part au même niveau après la pause (60, 300, 900, 1 800, puis 3 600 s).
2. Nature « connexion » : tous les lancements sont suspendus cinq minutes, et le fil dit une fois la phrase de reconnexion.
3. Vérificateur en panne : lui seul repart.
4. Pauses épuisées, nature vide ou « delai » : règle actuelle.
5. La phase dit la pause et son heure.
6. `agent.liberer` est appelé à chaque suspension.

Périmètre : `moteur.py` (`_suspendre`, `_malgre_les_limites`, `_apres_erreur_d_agent`, `_attendre`), `places.py` (`pause`, `connexion`, `suspension`, `prochaine_echeance`, `etat`). Preuve : un test par chemin (ouvrier, vérificateur, arrêt pendant la pause, limite pendant la pause, pauses épuisées) et les essais au hasard de `test_places`. Opus, effort élevé ; vérification complète.

## M7. Reprise seule après un arrêt
La personne a renversé la décision du 2026-11-12. Les conditions de (c) la rendent sûre.
1. Une tâche active redevient « à lancer » avec une entrée `interrompue` et son numéro rendu, trois fois au plus.
2. Arrêtée en vérification avec sa copie, elle reçoit `pendant: "verification"` et garde son numéro.
3. `reprise_auto: false` : la tâche est rendue à la personne.
4. Le serveur relance seulement avec contrat validé, port pris et verrou du dépôt tenu, après l'annonce et le délai.
5. Une tâche « revenue » ne part pas.
6. Un arrêt pendant le délai : rien ne part.

Périmètre : `moteur.py` (`_reprendre`, `_demander`), `serveur.py` (`Atelier.reprendre_apres_arret`, verrou), `__main__.py` (`commande_servir`, `avec_annonce`). Preuve : un test par chemin, dont un second Atelier sur le même dépôt. Exception aux tests existants : trois tests de `test_reprise` et trois de `test_moteur` passent à `reprise_auto: false`, car la règle par défaut est renversée. Opus, effort élevé ; vérification complète.

## M8. Le travail refusé est gardé
Un travail juste sans preuve a été refait en 27 minutes.
1. Après un refus d'origine contrôles, verdict ou agent, ou une suspension, la copie reste, et `tache.copie` est sauvé avant le départ.
2. Le départ suivant la réutilise, sans `preparer`, avec la consigne `sur_place`.
3. Débord, arrêt par la personne, abandon : la copie est jetée.
4. Copie disparue : départ propre, dit au fil.
5. Dernière entrée `pendant: "verification"` et copie présente : pas d'ouvrier, seulement contrôles et vérification.
6. `_rendre` ajoute « travail gardé ».
7. `ControlesGit` gagne `copie_existante`, `empreinte` (sans toucher l'index) et `differences`, avec des doubles neutres.

Périmètre : `moteur.py` (`_boucle`, `_lancer_ouvrier`, `_rendre`, `_arret_avant_depart`, `_verifiee`, `repondre`), `controles.py`. Exception aux tests existants : les tests « copie jetée » après un refus. Opus, effort élevé ; vérification complète.

## M9. Retours à l'ouvrier ouvert
Sept refus sur treize étaient un contrôle rouge ou un oubli.
1. Un contrôle rouge revient avec sa sortie, trois fois au plus, et s'arrête au même échec (`refus.meme_forme`).
2. Un manque (`bacle` ou `local` lisible) revient une fois ; un fond faux, jamais.
3. La passe suivie d'un retour est marquée `retour: true` ; ni tentative ni agent n'est compté.
4. Empreinte inchangée : le refus vaut, rien n'est rejoué, et la réponse de l'ouvrier va au fil (300 signes).
5. Ouvrier fermé : repli sur la session, puis sur le refus actuel.
6. Toute fin de tâche appelle `liberer`.
7. Le retour attend place et jeton ; un arrêt pendant cette attente ne lance rien.

Périmètre : `moteur.py` (`_reprises`, `_reprise`, `_lancer_reprise`, `_traiter`). Dépend de M3, M5, M8. Preuve : un test par chemin, avec `garde_ouvert=True` et des durées. Opus, effort élevé ; vérification complète.

## M10. Sous-tâche
Six refus sur quatorze visaient un travail bon à un morceau près.
1. Un refus des contrôles, ou un verdict `bacle` ou `local`, écrit `reste` ; un autre refus l'efface.
2. Un départ avec `sous_tache_possible` envoie `consigne_sous_tache`, ne compte pas de tentative, dose par `dosage.sous_tache` sous le plafond et trace `sous_tache: "A-a"`.
3. Les fichiers nommés par le vérificateur sont permis pour ce tour.
4. Une suspension rend le numéro de la sous-tâche.
5. `sous_taches: 0` coupe ; une relance par la personne remet le compte à zéro.

Périmètre : `moteur.py` (`_boucle`, `_lancer_ouvrier`, `_controler`, `_tracer`, `repondre`). Dépend de M2, M5, M8. Opus, effort élevé ; vérification bornée.

## M11. Après un refus
Treize refus, cinq montées, aucune pour un fond faux.
1. L'ordre de (b) est tenu.
2. Seul `fond_faux` monte, sous le plafond et `max_montees` ; la relance seule aussi.
3. Le même défaut se reconnaît par `refus.meme_forme` (contrôles, périmètre), par `jugement.meme_defaut` (retouche) ou par deux natures « delai ». Les entrées `retour`, `attente_panne` et `interrompue` ne comptent pas.
4. Le détail reformulé donne la même décision.

Périmètre : `moteur.py` (`_suite`, `_apres_echec`, `_monter`, `_relancer_seul`, `_fenetre`, `_cause_de_blocage`, `_cran_disponible`, `_bloquer`, `_raison_de_blocage`). Exception aux tests existants : seconde chance, effort monté pour un travail bâclé, `sans_cran`, `repete`. Opus, effort élevé ; vérification complète.

## M12. Budget
La limite doit valoir pendant le travail et compter les agents coupés.
1. `budget_usd` du profil devient `contrat.max_cout_usd` à l'adoption du plan.
2. Budget atteint : aucun agent ne part (ouvrier, vérificateur, retour, sous-tâche), la phase dit « budget », et une seule demande `nature: budget` est posée.
3. « Ajouter un cinquième » relève le budget, l'écrit au fil et fait repartir ; « Arrêter là » rend les tâches.
4. Chaque agent part avec le reste comme plafond ; une nature « budget » ne compte rien contre la tâche.
5. `cout_incomplet` est dit au fil.
6. Budget 0 : rien ne change.

Périmètre : `moteur.py` (`_attendre`, `_faire_partir_les_neuves`, `_compter`, `_prendre_agent`, `repondre_budget`), `serveur.py` (`decider`, adoption du plan), `agents.py` (`_travailler`, double). Preuve : un test par point de lancement, deux agents qui franchissent ensemble, un arrêt en attente. Fable, effort élevé (facturation) ; vérification complète.

## M13. Page
Les quatre éléments de (e), un critère chacun. Périmètre : `serveur.py` (`vue`), `tableau/index.html`, un neuvième essai. Sonnet, effort moyen ; vérification bornée.

## M14. Épreuves d'ensemble et démonstration
1. Arrêt en vérification puis relance : rejugé sans ouvrier.
2. Verdict `local`, sous-tâche, retouche vérifiée, entrée.
3. Contrôle rouge rendu à l'ouvrier ouvert sous budget.
4. La démonstration joue un retour et une sous-tâche.
5. Les huit essais restent verts.

Périmètre : `__main__.py` (`plan_de_demonstration`, `projet_simule`), tests. Sonnet, effort élevé ; vérification bornée.

## Risques et incertitudes relevés par l'architecte
- Cumul du coût : vérifié par lecture du SDK (`types.py`), pas par un essai réel. La référence a ce défaut en plus de ceux signalés.
- Message de fin chiffré après `interrupt` : supposé, d'où `cout_incomplet`.
- `max_budget_usd` sur plusieurs tours : supposé. Le dépassement reste borné par le nombre d'agents en marche.
- Claude Code orphelin à la mort de l'Atelier : supposé mourir avec lui, d'où le délai avant la reprise.
- Verrou par dépôt sous Windows : supposé. Ne pas tester un PID par `os.kill`.
- Ouvrier ouvert sous Windows : jamais essayé, selon le journal de la référence.
- Réunions : M9, M10 et M11 partagent le contrat `retour` et `reste`, que seule M14 prouve de bout en bout. M8 et M10 touchent les mêmes fonctions, en vagues successives.
- Tests existants : chaque ouvrier rend la liste exacte des tests à changer avant d'y toucher. M5 en changera aussi (vérificateur « au-dessus » pour une tâche courante).
- Non porté, volontairement : niveau posé par tâche dans le plan (la voie par où la référence perd le plancher), rencontre avant vérification, bilan écrit par l'atelier, périmètre souple, effort plafonné du vérificateur, enveloppe d'agents.
- Journal : la ligne « moteur » du 2026-11-12 sur la reprise après panne est à remplacer à la réunion.
