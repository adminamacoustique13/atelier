# Relais V3-places : les places et le régulateur d'abonnement, en module pur

Copie : `copie-V3places`, partie de « Page : un seul format de tokens, et les pannes de réseau dites à l'écran » (35d8a12). Aucun commit. Fiche suivie : V3f (décisions 1, 2, 4, 5, 6 ; critères 1 à 17 pour ce qui revient au module).

## Fait, critère par critère

1. **Module pur.** `atelier/places.py` n'importe que `math`, `time` (seulement pour écrire l'heure locale dans la phrase : `localtime`, `strftime`) et `dataclasses`. Il ne contient ni attente, ni fil, ni verrou, et ne lit jamais l'heure lui-même. **L'heure vient toujours de l'appelant, en secondes Unix** (comparable à `time.time()`), parce que `Resultat.fin_limite` et le champ `fin` de l'événement « limite » sont des heures Unix (V5, `resets_at` du SDK). La docstring du module et celle de `Places` disent que l'appelant tient son verrou autour de chaque appel. Un test lit le source (AST) : pas d'import hors de cette liste, aucun appel à `time.time`, `time.monotonic`, `time.sleep` ni `time.perf_counter`.
2. **Deux nombres.** `paralleles` vaut 6 par défaut. `agents_max` vaut par défaut `paralleles + max(1, paralleles // 2)`, soit 9 pour 6 places et 2 pour une seule (arbitrage de l'orchestrateur sur mon premier doute : il reste toujours un jeton pour qu'un vérificateur travaille pendant que la tâche suivante écrit). Ils sont lus par `lire_nombre` : un entier, un nombre à virgule (tronqué) ou un texte qui en contient un. Une valeur mal formée (texte illisible, None, booléen, NaN, infini, liste…) prend la valeur par défaut. Une valeur sous 1 devient 1. Aucune erreur n'est levée. `regler(paralleles, agents_max)` relit les deux à chaque tour ; un `agents_max` absent se recalcule depuis le nouveau `paralleles`.
3. **Le cours d'une tâche.**
   - `peut_partir` vérifie trois choses : une place d'écriture libre, un jeton qu'aucun vérificateur en attente ne doit recevoir avant, et aucune suspension pour le modèle.
   - `partir` prend la place et le jeton. Une tâche qui tient un jeton sans place et ne peut pas partir rend ce jeton (seconde passe, point 1).
   - `en_verification` rend la place d'écriture. Le jeton de l'ouvrier passe au vérificateur s'il y en a un et que son modèle n'est pas suspendu. Sinon le vérificateur attend dans une file, du plus ancien au dernier.
   - `finir` rend tout.
   - `rendre_jeton` rend le jeton seul : l'agent s'est arrêté, mais la tâche garde sa place.
   
   Un jeton libéré va d'abord aux vérificateurs qui attendent : `servir` est appelé par chaque geste qui rend un jeton. `peut_partir` met de côté les jetons dus aux vérificateurs qui attendent, même si l'appelant a oublié d'appeler `servir`.
   
   Les comptes sont tirés des marques de chaque tâche suivie (au plus une place et un jeton par tâche) : aucun ne peut devenir négatif. Finir une tâche inconnue ne fait rien. Partir deux fois ne prend ni deuxième place ni deuxième jeton. Un jeton n'est donné que s'il en reste un libre. Un test de 20 graines joue chacune 400 gestes au hasard, ordres faux compris, et vérifie les bornes après chaque geste.
4. **Alerte.** Pendant une alerte, `places_effectives` vaut `max(1, paralleles // 2)`, jusqu'à l'heure de remise à zéro annoncée ou pendant 30 minutes si elle est inconnue. Une heure mal formée, déjà passée ou égale à l'heure présente compte comme inconnue. Plusieurs alertes, même pour des limites différentes, ne divisent les places qu'une fois. `alerte` rend vrai si l'alerte est nouvelle :
   - nouvelle s'il n'y a aucune alerte en cours pour ce type de limite, ou si l'heure annoncée change ;
   - une alerte répétée sans heure n'est pas nouvelle, mais elle prolonge les 30 minutes.
   
   Les agents en marche ne sont pas touchés.
5. **Refus pour limite.** `refus(tache, type_limite, fin, heure)` suspend les lancements jusqu'à `fin + 60`. Sans heure : 15, 30, 60 puis 60 minutes, à chaque refus qui arrive après la fin de la suspension précédente. Un refus qui arrive pendant une suspension de même portée vient d'un agent parti avant elle : il ne double pas l'attente, mais une heure annoncée plus tardive la prolonge. Ce qui ramène l'attente sans heure à 15 minutes : un agent qui a reçu son jeton après le dernier refus de cette portée et qui finit sans refus pour limite. Un agent parti avant la suspension ne compte pas.
   
   La portée de la suspension :
   - `seven_day_opus` suspend la famille « opus » (aussi `claude-opus-…`) et, par prudence, « fable » (`FAMILLES_SUSPENDUES`, seconde passe, point 3) ;
   - `seven_day_sonnet` ne suspend que « sonnet » ;
   - `five_hour`, `seven_day`, `overage`, `inconnue`, tout autre texte et toute valeur mal formée suspendent tout.
   
   Ce que le refus change pour la tâche :
   - rien n'est compté ;
   - un ouvrier refusé rend sa place et son jeton : il repartira par `partir` comme une tâche neuve (seconde passe, point 2) ;
   - un vérificateur refusé rend son jeton et repasse en tête de la file d'attente ;
   - `de_suite` compte les refus pour limite de suite de la tâche. Ce compte repart de zéro dès qu'un de ses agents finit sans refus. Au cinquième, `rendre` vaut vrai et le compte repart.
6. **État.** `etat(heure)` rend `places`, `places_effectives`, `en_ecriture`, `agents_max`, `agents_en_marche`, `verificateurs_en_attente`, `alerte_jusqu_a`, `reprise` (suspension de tout, sinon None), `suspensions` (famille vers heure, pour les limites propres à un modèle) et `phrase`. Exemples de phrase :
   - « 2 tâches en écriture sur 4 places, 2 agents en marche sur 2 au plus, 1 vérificateur en attente. »
   - « Une limite de l'abonnement est proche : 3 places au lieu de 6, l'alerte prend fin à 14:05. »
   - « Une limite de l'abonnement est atteinte : plus aucun lancement, ils reprennent à 14:06. »
   - « La limite propre à Opus est atteinte : plus aucun lancement d'Opus ni de Fable, ils reprennent le 19/11 à 14:06. » (la date est écrite quand le jour n'est pas le même)
7. **Tests.** `tests/test_places.py` : 53 fonctions, 112 cas (après la seconde passe), avec une fausse heure Unix (`T0 = 1 800 000 000`). Chaque critère a les siens. Les cas adverses demandés y sont :
   - `test_agents_max_deux_avec_six_taches_pretes` : pic à 2, les six vont au bout ;
   - `test_avec_une_seule_place_b_part_pendant_que_a_est_verifiee_avec_son_jeton` : `paralleles = 1` donne `agents_max = 2` (critère 2 de V3f) ;
   - `test_refus_pour_limite_sans_heure_quinze_trente_soixante_soixante_minutes` ;
   - `test_une_alerte_repetee_dix_fois_n_est_nouvelle_qu_une_fois_et_ne_divise_qu_une_fois` ;
   - `test_finir_une_tache_jamais_partie_ne_rend_aucun_compte_negatif` ;
   - `test_une_limite_d_opus_laisse_partir_une_tache_sonnet`.
   
   **Règles cassées une à une** (script hors copie, `scratchpad/verif-V3places/casser.py`, qui remet le fichier à l'identique, vérifié par `cmp`) :
   - la priorité au vérificateur supprimée (`_jetons_pour_ouvriers` ne retient plus les jetons dus) : 1 échec, `test_un_verificateur_qui_attend_passe_avant_un_ouvrier_meme_sans_appel_a_servir` ;
   - toute alerte dite nouvelle : 3 échecs, dont `test_une_alerte_repetee_dix_fois_…` ;
   - l'attente sans heure jamais doublée : 2 échecs, dont `test_refus_pour_limite_sans_heure_quinze_trente_soixante_soixante_minutes` ;
   - toute limite suspendant tous les modèles : 4 échecs, dont `test_une_limite_d_opus_laisse_partir_une_tache_sonnet`.
8. **Tests et forme.** Voir Résultats. Seuls les deux fichiers nouveaux et cette fiche sont ajoutés.

## Fichiers touchés
- `atelier/places.py` (nouveau)
- `tests/test_places.py` (nouveau)
- `chantier/relais/V3-places.md` (cette fiche)

## Contrats : ce que le moteur appellera

Toutes les heures sont en secondes Unix (`time.time()`, ou une fausse heure Unix injectée dans les tests). Ce n'est pas `self.horloge` du moteur, qui est monotone. Chaque appel se fait sous `self.verrou`. Les identifiants de tâche sont des `str` (`tache.id`). Les modèles sont ceux de `dosage` (« sonnet », « opus »…) ; un nom complet contenant la famille marche aussi.

```python
from atelier.places import Places, REFUS_LIMITE_MAX

places = Places(paralleles=None, agents_max=None)       # 6 et 9 par défaut
places.regler(profil.get("paralleles"), profil.get("agents_max"))   # à chaque tour

# départ d'un ouvrier (tâche neuve, ou reprise d'une tâche suivie : elle garde place et jeton)
places.peut_partir(modele, heure, tache=None) -> bool   # pure, ne rend rien
places.partir(tache_id, modele, heure) -> bool
#   False : rien n'est pris ; une tâche qui tenait un jeton sans place l'a rendu (il a pu
#   servir un vérificateur : réveiller ceux qui attendent)

# l'ouvrier a fini, la tâche passe en vérification avec un vérificateur de `modele`
places.en_verification(tache_id, modele, heure) -> bool # True : le vérificateur part tout de suite
places.a_son_jeton(tache_id) -> bool                    # le vérificateur qui attendait peut partir
places.servir(heure) -> list[str]                       # à chaque tour : vérificateurs servis

# un agent s'arrête sans que la tâche quitte les places (facultatif, voir Doute 6)
places.rendre_jeton(tache_id, heure) -> list[str]       # vérificateurs servis
# la tâche sort (vérifiée, rendue, arrêtée, abandonnée, panne)
places.finir(tache_id, heure) -> list[str]              # vérificateurs servis

# limites
places.alerte(type_limite, fin, heure) -> bool          # True : nouvelle, à dire au fil
places.refus(tache_id, type_limite, fin, heure) -> dict
#   {"portee": "" | "opus" | "sonnet", "reprise": float, "nouvelle": bool,
#    "de_suite": int, "rendre": bool, "servis": list[str]}
places.suspension(modele, heure) -> float | None        # heure de reprise pour ce modèle
places.prochaine_echeance(heure) -> float | None        # fin d'alerte ou de suspension la plus proche

# lecture
places.places_effectives(heure) -> int
places.en_ecriture() -> int
places.agents_en_marche() -> int
places.etat(heure) -> dict                              # pour moteur.debit() et point_d_etape
```

Branchements prévus (fiches V5 et V3f) :
- Événement `{"type": "limite", "statut": "alerte", "limite": t, "fin": f}` : appeler `places.alerte(t, f, heure)`. S'il rend vrai, une ligne au fil (`decrire_limite`). Un statut « atteinte » peut être ignoré : le refus arrive par le `Resultat`.
- `resultat.erreur == LIMITE_ATTEINTE` : `issue = places.refus(tache.id, resultat.type_limite, resultat.fin_limite, heure)`. Ne compter ni tentative, ni agent lancé, ni entrée d'historique. Si `issue["rendre"]`, rendre la tâche avec la raison. Sinon, attendre que `places.suspension(modele, heure)` vaille None, puis relancer :
  - un ouvrier par `partir` : il a rendu sa place et son jeton au refus, il repart comme une tâche neuve (session notée par le moteur) ;
  - un vérificateur, quand `a_son_jeton` est vrai (il est déjà en tête de file ; `servir` à chaque tour le sert).
- Après un vérificateur qui rejette, ou des contrôles rouges, l'ouvrier repart par `partir`, jamais en attendant sur `peut_partir` seul : si `partir` échoue, une tâche qui tenait un jeton sans place l'a rendu, et le moteur réessaie `partir` à chaque tour. C'est la condition de l'absence d'interblocage (seconde passe, point 1).
- À la fin de chaque agent, le moteur appelle `en_verification`, `partir`, `rendre_jeton` ou `finir` ; après tout appel qui rend un jeton (`partir` refusé compris), il réveille les vérificateurs qui attendent.
- Si `issue["nouvelle"]` : une ligne au fil avec `issue["reprise"]`.
- Attente de la boucle : au plus `min(PAS_VEILLE_S, prochaine_echeance(heure) - heure)`. Une suspension qui finit ne prévient personne : `servir(heure)` à chaque tour.
- Chaque tâche prête est essayée avec `partir`, pas seulement la première : une tâche Opus suspendue ne doit pas bloquer une tâche Sonnet derrière elle.
- `moteur.debit()` peut rendre `places.etat(heure)` tel quel, ou en partie.

## Reste à faire
- Le moteur (V3f) : un `Places` dans `Moteur`, une heure Unix injectable à côté de `self.horloge`, et les branchements ci-dessus dans `executer`, `_prochaine`, `_lancer_ouvrier`, `_lancer_verificateur`, `_juger`, `entendre` et `repondre`. `debit()` et `point_d_etape` lisent `etat`. Rien n'est relu après un redémarrage : un `Places` neuf, et le premier refus rétablit la suspension (critère 17 de V3f).
- Le serveur : afficher `etat()["phrase"]`, puis les réglages visibles de la vague 3.

## Doutes
1. **Tranché : la valeur par défaut d'`agents_max`.** La formule `paralleles + paralleles // 2` donnait 1 agent pour une seule place, et le critère 2 de V3f ne pouvait pas tenir. L'orchestrateur a choisi `paralleles + max(1, paralleles // 2)` : 2 pour une place, 9 pour six. C'est appliqué et testé.
2. **Heure Unix.** C'est l'unité du SDK, mais l'heure du mur peut sauter (réglage de l'horloge, mise en veille). Un saut en arrière allonge une suspension, un saut en avant la raccourcit.
3. **Choix gardé par l'orchestrateur : une heure de remise à zéro déjà passée** (ou égale à l'heure présente, ou mal formée) compte comme inconnue, pour l'alerte comme pour le refus. Un refus reçu juste avant la remise à zéro et traité juste après attendra donc 15 minutes au lieu de 60 secondes. L'autre choix aurait été `max(fin, heure) + 60`. Je l'ai écarté : une horloge locale en avance relancerait alors toutes les minutes jusqu'au cinquième refus.
4. **Tranché à la seconde passe : Fable est sous la limite propre à Opus.** Le premier choix (Fable hors de cette limite) a été renversé par l'orchestrateur : rien ne dit que Fable a sa propre fenêtre dans l'abonnement, et une tâche Fable qui continuerait de partir reviendrait à la personne au cinquième refus en quelques secondes. `FAMILLES_SUSPENDUES = {"opus": ("opus", "fable"), "sonnet": ("sonnet",)}` le dit. Si l'on apprend que Fable a sa propre fenêtre, il suffira de l'ôter de cette constante.
5. **Alerte d'une limite propre à un modèle.** Une alerte `seven_day_opus` divise quand même toutes les places : il n'y a pas de places par modèle. C'est prudent, mais cela coûte du débit aux tâches Sonnet.
6. **Le jeton pendant les contrôles.** Si le moteur n'appelle pas `rendre_jeton` à la fin de l'ouvrier, la tâche garde son jeton pendant le périmètre et les contrôles, puis le passe au vérificateur, comme le dit le critère (« garde »). `agents_en_marche` compte alors un agent qui ne tourne pas. Avec `rendre_jeton`, un autre agent tourne pendant les contrôles, mais le vérificateur attend son tour dans la file (il reste prioritaire). Les deux chemins sont testés. Je conseille le premier : plus simple, vérificateur sans attente.
7. **Tranché à la seconde passe : un ouvrier refusé rend sa place et son jeton.** Sinon, deux ouvriers Opus refusés tiendraient toutes les places pendant une limite propre à Opus et bloqueraient une tâche Sonnet pendant des jours. À la reprise, le moteur le relance par `partir` comme une tâche neuve ; c'est à lui de garder la session et la copie. `de_suite` est tenu à part : il survit, et ne repart qu'après un agent fini sans refus, ou au cinquième refus.
8. **Lectures de la demande qui ne sont pas écrites.**
   - « Refus de suite après une remise à zéro » : je l'ai lu comme les refus de suite d'une même tâche, celui de l'agent parti avant la suspension compris.
   - Ce qui ramène l'attente sans heure à 15 minutes (un agent parti après le dernier refus et fini sans refus) n'est écrit nulle part.
   - Une alerte d'abord sans heure, puis répétée avec une heure, est dite deux fois : l'heure apprise est une information nouvelle.
   - Un vérificateur refusé pour limite repasse en tête de la file d'attente, devant ceux qui attendaient : il tenait déjà son jeton.
   - Une tâche qui tient sa place et son jeton (contrôles rouges, jeton gardé) mais dont le modèle est suspendu garde les deux jusqu'à la reprise : `partir` ne rend un jeton que s'il est tenu sans place. Ce n'est pas un interblocage (une suspension court), mais sous la fenêtre de 7 jours d'Opus elle tiendrait une place ; le moteur peut appeler `finir` s'il préfère la remettre « à lancer ».
   - Un refus pendant une suspension de même portée ne double pas l'attente sans heure ; une heure annoncée plus tardive la prolonge.
   - Plusieurs alertes, même pour des limites différentes, ne divisent les places qu'une fois.
9. **Pas de plafond haut** sur `paralleles` ni sur `agents_max` : 1 000 est accepté tel quel. Pendant une suspension, `places_effectives` ne tombe pas à 0 ; c'est la phrase qui dit la suspension.

## Seconde passe

Points recalés par le vérificateur ; le reste n'a pas bougé.

1. **Interblocage.** Le vérificateur a trouvé deux blocages. Dans l'un, des tâches tiennent les jetons et attendent une place (vérificateur qui rejette, puis `partir` sans place). Dans l'autre, des tâches tiennent les places et attendent un jeton (ouvrier refusé pour limite, ou contrôles rouges après `rendre_jeton`). Les deux attendaient pour toujours, sans suspension en cours. J'ai jugé et retenu son correctif : dans `partir`, une tâche qui tient un jeton sans place et ne peut pas partir rend son jeton (`_lacher_le_jeton`, qui passe par `rendre_jeton`, donc par `servir`), puis sort des places si elle ne tient plus rien. Je l'applique à tout échec, suspension comprise : un jeton gardé pendant une suspension ne servirait à rien. Pourquoi plus rien ne peut se bloquer quand rien ne tourne et qu'aucune suspension ne court :
   - les tâches qui tenaient un jeton sans place l'ont rendu à leur essai de `partir` ;
   - aucun jeton n'est donc tenu ;
   - les jetons vont d'abord aux vérificateurs qui attendent, qui avancent ;
   - sinon `_jetons_pour_ouvriers` vaut `agents_max ≥ 1`, et une tâche qui tient une place reçoit un jeton ;
   - sinon aucune place n'est tenue, et une tâche neuve part.

   Tests :
   - `test_le_scenario_d_interblocage_trouve_par_le_verificateur_ne_bloque_plus` : la suite du vérificateur, avec la règle du point 2 ;
   - `test_des_jetons_sans_place_et_des_places_sans_jeton_ne_se_bloquent_pas[1|6]` : le blocage qui restait possible après le point 2, avec 1 place et 2 agents, puis 6 places et 9 agents ;
   - `test_au_hasard_aucune_suite_conforme_au_contrat_ne_finit_en_interblocage` : un moteur conforme au contrat est joué au hasard sur 3 000 suites au plus, borné à 5 secondes (environ 4 s ici). Il tire une phase par tâche (prête, ouvrier, contrôles avec ou sans jeton rendu, attente de jeton, vérificateur, reprise, finie), des refus pour limite, des alertes et des ouvriers Sonnet vérifiés par Opus. Quand rien ne tourne, il avance l'heure jusqu'à la fin de toute alerte et de toute suspension, puis réessaie chaque tâche en attente. Si rien ne repart, c'est un interblocage.

   Mesures, hors des tests (`scratchpad/verif-V3places/compter.py`) :
   - module tel quel : 0 interblocage sur 20 000 suites ;
   - correctif ôté : 11 sur 3 000.

   L'essai privilégie les petites tailles (1 ou 2 places, 1 à 3 agents, 3 à 7 tâches), où un blocage demande peu de tâches. Aux tailles du profil, ses tirages n'en trouvaient presque jamais ; le cas à 6 places et 9 agents est couvert par le test paramétré.
2. **L'ouvrier refusé rend sa place et son jeton** (`_arreter_pour_limite`). La docstring du module, celle de `refus` et la section « Branchements prévus » le disent ; le doute 7 est tranché. Tests :
   - `test_un_ouvrier_refuse_rend_sa_place_et_son_jeton_et_repart_comme_une_tache_neuve`, qui remplace le test de la place gardée ;
   - `test_des_ouvriers_opus_refuses_ne_tiennent_pas_les_places_d_une_tache_sonnet`.
3. **Fable sous la limite d'Opus.** La constante nommée est `FAMILLES_SUSPENDUES = {"opus": ("opus", "fable"), "sonnet": ("sonnet",)}`, avec la raison en commentaire. Elle est lue par la fonction publique `portees(modele)`, dont se servent `suspension` et la remise à 15 minutes. La phrase de `etat` dit « plus aucun lancement d'Opus ni de Fable ». Test : `test_une_limite_d_opus_suspend_aussi_fable_par_prudence` (un vérificateur Fable n'est pas servi). Le test de la phrase est mis à jour.
4. **Deux casses qui passaient.**
   - Places divisées une fois par alerte en cours : `test_plusieurs_alertes_en_cours_ne_divisent_les_places_qu_une_fois`, avec cinq alertes en cours ensemble et 9 places, ce qui donne 4.
   - Un type de limite inconnu écrit en texte qui ne suspendrait rien : `test_un_type_de_limite_en_texte_qui_ne_vise_pas_un_modele_suspend_tout`, avec `inconnue`, `twelve_hour`, `Seven_Day_Opus`, `five_hour`, `seven_day` et `overage`. Chacun suspend tout, Opus, Sonnet, Fable et Haiku compris.

**Règles cassées une à une, après la seconde passe** (`scratchpad/verif-V3places/casser.py` ; le module est remis à l'identique, vérifié par `cmp`) :

| Règle cassée | Échecs | Dont |
|---|---|---|
| Priorité au vérificateur | 1 | |
| Alerte répétée | 3 | |
| Doublement sans heure | 2 | |
| Toute limite suspend tout | 9 | |
| Jeton sans place gardé (le correctif ôté) | 4 | le scénario du vérificateur, les deux cas paramétrés, l'essai au hasard |
| Ouvrier refusé qui garde sa place | 4 | les deux tests du point 2, le scénario du vérificateur |
| Fable hors de la limite d'Opus | 2 | |
| Places divisées une fois par alerte en cours | 1 | le test nouveau |
| Type inconnu en texte qui ne suspend rien | 12 | dont les six cas nouveaux |

## Résultats
- Tests : `985 passed in 42.81s` (873 au départ, 112 cas dans `tests/test_places.py`).
- Forme : `ruff check .` : `All checks passed!` (100 caractères, complexité 10). Les deux fichiers nouveaux sont aussi conformes à `ruff format`.
- Règles cassées : voir le tableau de la seconde passe. Chaque casse fait échouer au moins un test.
