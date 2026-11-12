# Cahier des charges — chantier « ménage », 2026-11-12

État général : en cours. Les sept premières tâches sont vérifiées et enregistrées ; le contrat a été amendé le 2026-11-12 pour traiter aussi les quatre points du bilan (tâches M5a à M13).

Source des constats : l'audit du 2026-11-12 (deux lecteurs en lecture seule sur 513bf22, constats principaux recontrôlés par l'orchestrateur sur `main`). Les chantiers précédents sont rangés dans `chantier/archives/`.

## Suivi

Compteur : 5 agents lancés dans le chantier (2 ouvriers, 1 vérificateur, plus les 2 lecteurs de l'audit, avant le contrat).

| Tâche | État | Ouvrier | Vérification | Tentatives | Preuve |
|---|---|---|---|---|---|
| M1. Python : code mort et commentaires faux | vérifié | Sonnet | bornée, Opus : accepté | 1 | 758 tests et contrôle de forme verts ; recherches refaites par le vérificateur |
| M2. Page : code mort et commentaires faux | vérifié | Sonnet | bornée, Opus : accepté | 1 | 758 tests, contrôle de forme et 365 vérifications dans le navigateur verts ; chaque retrait recherché à nouveau par le vérificateur |
| M3a. Archives et carte : table des efforts, format d'un coût | vérifié | Sonnet | mécanique, diff relu par l'orchestrateur | 1 | 764 tests (1 nouveau) ; égalité des deux formats prouvée par script sur 19 valeurs |
| M3b. Serveur et rythme : nom d'agent, coupe aux balises, phrases du profil | vérifié | Sonnet | mécanique, diff relu par l'orchestrateur | 1 | 764 tests (2 nouveaux) ; remplacements d'expressions identiques |
| M4. Serveur : une seule lecture et une seule écriture du profil | vérifié | Opus | complète, Fable : accepté | 1 | 761 tests (3 nouveaux, rouges sur le code de départ) ; 1 104 scénarios comparés avant/après sans différence ; 13 casses sur 14 vues par les tests |
| M6b. Page : envois au serveur, minuteries de message, tracés de fil | vérifié | Opus | bornée, Fable : accepté | 1 | 365 vérifications dans le navigateur ; 211 comparaisons avant/après par le vérificateur, pannes du serveur comprises, sans différence |
| M5a. Une base commune pour appeler git, adoptée par `projets`, `essai`, `carte` | vérifié | Opus | complète, Fable : accepté | 1 | 772 tests (7 nouveaux) ; 82 cas comparés avant/après, 78 identiques et 4 écarts attendus ou sans effet ; 20 casses de la base sur 21 vues par ses tests |
| M5b. La base git adoptée par `controles` et `mise_a_jour` | à lancer, après M5a | Opus | complète, Fable | | |
| M5c. `ARRET` et `ARRETE` : une seule constante ; `SANS_REPONSE` : deux noms | vérifié | Sonnet | mécanique, diff relu par l'orchestrateur | 1 | 765 tests (1 nouveau, rouge sur le code de départ) ; le texte de l'arrêt n'est plus écrit qu'une fois dans `atelier/` |
| M9. Profil : écriture d'un seul geste, réglage d'outils qu'on peut réessayer, valeur mal formée refusée | vérifié | Opus | complète, Fable : recalé puis corrigé | 2 | 795 tests dans sa copie ; 1 513 scénarios comparés ; 29 casses sur 32 vues ; recalé sur la valeur restée en mémoire, que la consigne n'avait pas vue |
| M9.1. La carte du code écrite par la fonction commune | vérifié | Sonnet | mécanique, diff relu | 1 | 820 tests (1 nouveau, rouge avant) |
| M11a. Le guichet simulé sort du produit et rejoint les tests | vérifié | Sonnet | mécanique, diff relu | 1 | déplacement à l'identique ; seules les lignes d'import des tests changent |
| M11b. Les clés envoyées à la page que personne ne lit | en cours | Opus | bornée, Opus | 1 | |
| V0. Vitesse : mesurer le temps de chaque phase d'une tâche | vérifié | Opus | bornée, Opus : accepté | 1 | 861 tests ; ancien et nouveau moteur identiques sur 11 plans ; mesures justes à 0,1 % |
| V1. Vitesse : un plan large, et sa largeur calculée | vérifié | Opus | complète, Fable : accepté | 1 | 873 tests ; vagues calculées identiques à celles du vrai moteur sur 36 plans |
| V2. Vitesse : les niveaux de vérification et le dosage de départ | vérifié | Opus | bornée, Opus : recalé puis corrigé | 2 | 844 tests ; le test du plafond de la relance seule éprouve de nouveau sa garde |
| V5. Vitesse : le pont lit les limites de l'abonnement et sait reprendre une session | en cours | Opus | complète, Fable | 1 | |
| V3. Vitesse, moteur : vérification proportionnée, reprise à chaud, places et régulateur | à lancer, après V0, V2, V5 | Opus | complète, Fable | | |
| M10. Les tests qui manquent : suivi de la carte, moteur | vérifié | Opus | bornée, Opus, par casses : accepté | 1 | 786 tests (14 nouveaux) ; les 12 casses de la consigne et 6 des 7 casses du vérificateur font échouer un test nouveau |
| M10.1. Carte : une mise à jour réussie efface l'ancien message d'erreur ; deux tests de plus | vérifié | Opus | mécanique, diff relu par l'orchestrateur | 1 | 788 tests (2 nouveaux : l'un rouge avant la correction, l'autre rouge sous la casse 7b) ; deux lignes dans `_mettre_a_jour` |
| M8. Page : un seul format de tokens, un seul libellé de l'orchestrateur, pannes de réseau dites à l'écran | vérifié | Opus | bornée, Fable : recalé puis seconde passe mécanique | 2 | essai nouveau PANNES-reseau 34 sur 34 (9 ECHEC sur la première passe) ; les sept autres essais à leurs comptes, CODE-carte excepté (instable, diagnostiqué) |
| M11. Le code qui ne vit que pour les tests : sorti du produit ou retiré | à lancer, après M5 et M9 | Opus | bornée, Fable | | |
| M12. `serveur.py` découpé en modules | à lancer, après M9 et M11 | Opus | complète, Fable | | |
| M13. La page découpée en fichiers | à lancer, après M8 | Opus | complète, Fable | | |
| M6a. Page : les petits calculs écrits plusieurs fois | vérifié | Opus | bornée, Opus : accepté | 1 | 758 tests, 365 vérifications dans le navigateur ; égalité avant/après prouvée par deux scripts indépendants (ouvrier, vérificateur) |
| M7. Moteur et carte : doublons internes | vérifié | Opus | complète, Fable : accepté | 1 | 758 tests inchangés et verts ; plus de 150 000 scénarios comparés avant/après sans écart ; 12 casses sur 28 vues par les tests, le reste couvert par la comparaison |

### Restes mineurs relevés par le vérificateur de M1, non corrigés
- `atelier/guichet.py:20`, `SCENARIO_EPUISE` : le texte parle encore du « scénario de démonstration ». C'est une chaîne du code d'un garde-fou, hors du périmètre de M1.
- La docstring de `_Marche` (`atelier/agents.py`) ne décrit pas `reveil`, `fin_emise` ni `couper`.

### Restes mineurs relevés par le vérificateur de M2, non corrigés
- L'en-tête des styles parle encore de « bleu nuit » alors que la variable `--nuit` a disparu ; la phrase reste juste comme description de la palette.
- Relevés par l'ouvrier : dans `stationsDe`, le commentaire « Coordonnées écran » précède `parallele` alors qu'il décrit `sol` et `lieu` ; la ligne de tête sur le refus (« jamais par une couleur de plus ») est en tension avec `.mode-refus`, en ambre.

### M6a : deux réunions refusées, à trancher par la personne responsable
- Un nombre de tokens s'affiche « 1,2M » dans les jauges du Chantier et « 1,23 M » dans la Salle : deux formats, donc pas de fonction commune sans changer l'écran.
- L'orchestrateur est écrit « Fable · élevé » à deux endroits et « Fable élevé », sans point médian, dans la Salle ; l'une des écritures est dans le HTML statique.
- Restes mineurs du vérificateur, repris dans la consigne de M6b : le nom `habitArret`, peu parlant, et deux commentaires empilés au-dessus de lui.

### M4 : défauts relevés par le vérificateur, antérieurs au chantier, non corrigés
Ils changeraient un comportement : ils attendent la décision de la personne responsable.
- L'écriture du profil n'est pas atomique : une panne en cours d'écriture laisse `chantier/profil.json` tronqué (les trois écritures, avant comme après M4).
- Un `commandes_permises` mal typé dans le fichier fait encore lever `_regler_outils`.
- Après un réglage d'outils refusé pour profil illisible, la demande reste marquée comme répondue : un second clic après correction ne fait rien.
- Les deux phrases de raison (« pas lisible », « pas pu être écrit ») sont écrites à trois endroits de `serveur.py`.
- Les tests existants ne voient pas une réécriture inutile du profil, ni un changement de son format (indentation, accents).

### M7 : ce que le vérificateur a relevé
- La réunion du calcul « monter puis vérifier le plafond » n'est que partielle, à raison : une garde différente s'intercale à chaque endroit, et tout réunir ferait lever une erreur là où le code rend aujourd'hui « non ».
- Le critère 1 comptait une ligne qui sert aussi, légitimement, au contexte des agents : consigne mal posée par l'orchestrateur, signalée par l'ouvrier.
- Tests qui manquent, antérieurs au chantier : une entrée d'historique ajoutée hors du verrou, le plafond dans `_relancer_seul`, et presque tout le suivi de la carte (texte du problème, relance de la veille, sauvegarde) ne feraient échouer aucun test.
- Doublon noté par l'ouvrier, non traité : `_rendre` et `_demander` construisent la même demande.

### M6b : restes mineurs du vérificateur, repris dans la consigne de M8
- Le paramètre `poser` de `messagePassager` porte le nom de la fonction globale `poser(id, html)`.
- Trois commentaires à préciser : celui de `trace` et `arrondi` (« ne rendent pas la même chaîne » est trop absolu), celui d'`envoyer` (elle ne sert pas qu'à la conversation), celui du bouton « Arrêter », qui décrit le mécanisme à deux clics de `arreter()` ; le titre « Projets » et la doc de `demander` sont fondus en un bloc.
- Une quatrième minuterie du même genre reste (`minuteMode`).
- Les essais du dépôt ne couvrent les pannes du serveur que pour deux adresses : la preuve de M6b sur ce point vit dans des scripts hors dépôt.

### M9 : un arbitrage de l'orchestrateur
L'ouvrier s'est arrêté avant d'écrire : un test né de M4 simulait un profil non écrit en bloquant l'écriture en place, ce que l'écriture d'un seul geste contourne. Arbitrage : ce cas de test, et lui seul, change sa façon de simuler l'échec ; ses vérifications restent. La phrase du fil reste celle que le test exige, et l'invitation à réessayer va dans une deuxième ligne.

### M5a : ce que le vérificateur a relevé, repris dans la consigne de M5b
- Écart accepté : `carte._git` passait le dépôt par `git -C`, la base passe par le dossier de travail. Sur un dossier supprimé, l'erreur garde son type mais pas son message ; les deux appelants l'avalent, rien d'observable ne change.
- Trois lancements de git vivent encore hors de la base : `projets.py` (`git config user.email`) et deux dans `controles.py`. Tant qu'ils restent, la première ligne de `git.py` (« le seul endroit ») est fausse.
- Un test manque : une variable passée par l'appelant doit primer sur celle du processus (`mise_a_jour` dépend de `LC_ALL=C`).
- Mineur : `IDENTITE_DE_REPLI` est une liste modifiable partagée ; un alias inutile et un commentaire inexact dans `essai.py`.

### M10 : un défaut du produit trouvé, et une casse encore invisible
- Défaut : `SuiviCarte._mettre_a_jour` ne vide pas `probleme` ; après une mise à jour en erreur, la suivante réussit mais l'ancien message reste affiché jusqu'à la prochaine analyse complète. Tâche M10.1, ajoutée par l'orchestrateur.
- Casse non vue (7b) : une erreur sur un seul lot d'explications, avalée alors que la synthèse réussit. Test à ajouter, dans M10.1.
- Mineur : quelques `assert a and b and c` donnent des messages d'échec confus.

### Objectif vitesse (amendement du 2026-11-12)
Le diagnostic complet est dans le fichier de travail de la session (`diagnostic-vitesse.md`) ; ses trois causes : le plan sort en file indienne ; la vérification complète part pour toute tâche ; un refus jette tout le travail. Décisions de l'orchestrateur, que la personne responsable peut revoir : la propriété « agent `mode_ouvriers` » lue par les seuls tests est gardée (c'est la lecture naturelle du mode choisi) ; les deux découpages (M12, M13) passent après la vitesse, leurs plans étant prêts.

### Vitesse, vague 2 (fiches détaillées dans le fichier de travail `fiches-V3-moteur.md`)
Ordre : V3a (reprise à chaud), V3b (refus répété et erreur d'environnement), V3d (montées par tâche, plafond), V3c (agent qui n'avance plus), V3e (vérification proportionnée), V3f (débit et régulateur). `moteur.py` n'a qu'un ouvrier à la fois ; en parallèle : le lot des consignes, `refus.py`, `places.py`, les retouches de `plan.py`, la correction de l'onglet Code. Décisions attendues de la personne responsable avant V3e et V3c : Fable pour toute vérification complète ou un modèle au-dessus ; les propositions R1 et R2 sur les cartes, qui reviennent sur deux décisions du journal.

### V5 : recalé une fois, seconde passe en cours
Deux défauts : le dépassement payant de l'abonnement (statut « rejected » mais requêtes acceptées) était lu comme un refus, ce qui aurait suspendu les lancements pour rien ; une reprise demandée avec une session vide repartait dans une session neuve sans le dire. Relevé pour le lot du pont de la vague 2 (pas dans la seconde passe) : Claude Code marque aussi « rate_limit » une surcharge du serveur qui n'est pas la limite de l'abonnement ; le moteur devra la traiter comme une pause courte, pas comme une suspension de 15 minutes.

### CC et V1b, entrées avec une vérification mécanique
- CC (onglet Code) : correction de trois lignes, prouvée par l'essai CODE-carte, qui échouait 10 fois sur 10 et passe 36 sur 36 (dix passages chez l'ouvrier, trois chez l'orchestrateur). Reste en option : rendre déterministe, dans la démonstration, la tâche qui attend une autorisation.
- V1b (phrase du plan) : vagues recomparées au vrai moteur avec l'outil du vérificateur de V1 ; reste le cas de deux tâches de même identifiant, où `possible` vaut faux alors que la phrase dit que le plan peut aller au bout (un test existant exige ce faux).

### V3-refus : la règle d'usage que le moteur (V3b) doit suivre
Mesuré par le second vérificateur : 0 faux positif sur 3 046 paires de refus réels différents, tirés des archives ; les trois refus de la tâche B de Sonarq sont reconnus. Mais 14 faux positifs sur 29 cas synthétiques (deux tests différents d'un même fichier, deux critères écrits sur le même modèle, deux codes ruff), et des reformulations au vocabulaire changé ne sont pas reconnues. Donc, pour V3b :
- ne jamais bloquer sur la seule ressemblance de mots quand un cran reste : la règle « trois refus identiques de suite » ne compte que des refus de même forme, ou un empêchement signalé ;
- un refus des contrôles automatiques se compare par l'ensemble des tests en échec et des codes de contrôle de forme, pas par le texte ;
- la demande de blocage cite les deux détails, pour que la personne voie une confusion ;
- amélioration essayée par le vérificateur, à reprendre : des vetos sur les identifiants (noms de tests, numéros de critère, codes ruff) ramènent les faux positifs synthétiques de 14 à 4 sans perdre le cas réel.

### Restes relevés par les vérificateurs de V0, V1 et M8
- V0 : le temps passé derrière une dépendance n'est pas mesuré ; le total des attentes est cumulé sur les tâches (à dire ainsi) ; « 25 h 00 min » au-delà d'un jour.
- V1 : la consigne ne dit pas quoi faire d'un fichier que chaque tâche doit toucher (le journal d'un projet) ; la phrase de `plan.py` devient illisible quand beaucoup de tâches partagent un fichier ; aucun test ne garde les consignes ; accords (« toutes deux », « A et A ») ; récursion sur une chaîne de 1 000 tâches.
- M8 : si le serveur refuse l'ouverture d'un projet (hors panne), le menu reste sur le projet refusé.

## Contrôles communs

Depuis la racine du dépôt, avec l'environnement de travail de la session (hors dépôt) :
- la suite de tests : `python -m pytest -q` (758 au départ) ;
- le contrôle de forme : `python -m ruff check .` ;
- les sept essais dans le navigateur : `node chantier/essais/<nom>.js`, 365 vérifications au départ (ACCUEIL 26, CODE 36, D2 95, D3 82, G 70, NC 29, VISUEL 27).

Les essais réécrivent des images de `chantier/captures/` : l'orchestrateur les remet en l'état après chaque passage, elles ne font partie d'aucun livrable.

## Vague 1 — le mort prouvé (deux périmètres disjoints, en parallèle)

### M1. Python : code mort et commentaires faux
- **Périmètre** : `atelier/carte.py`, `atelier/guichet.py`, `atelier/moteur.py`, `atelier/agents.py`. Quatre fichiers au lieu des trois de la leçon : cinq des six retouches tiennent en une ligne ou une docstring.
- **Critères** :
  1. La fonction `liens()` de `carte.py` n'existe plus ; `liens_et_noms` reste.
  2. `vue()` de `carte.py` ne rend plus la clé `portrait_claude` ; les clés `supprimes` et `nouveaux_absents` restent (des tests les lisent).
  3. La docstring de `GuichetSimule` dit qu'il sert aux tests, pas à la démonstration.
  4. Le commentaire au-dessus de `RELANCES_AUTO` dit le nombre réel de relances.
  5. La docstring de `_prendre_agent` ne parle plus du plafond retiré.
  6. Les docstrings de `agents.py` (module et `_Marche`) décrivent chaque champ de mode tel que le code s'en sert.
  7. Aucun autre changement ; aucun test modifié.
- **Preuve** : contrôles communs dans l'état de départ ; pour 1 et 2, la recherche qui montre l'absence d'usage.
- **Contrats** : ne fournit rien de nouveau ; retire une clé que personne ne lit.

### M2. Page : code mort et commentaires faux
- **Périmètre** : `atelier/tableau/index.html`.
- **Critères** :
  1. Les sept variables de couleur jamais lues et leur commentaire sont retirés.
  2. Les règles de style sans cible sont retirées : `.pages .m8`, `.noeud .port.g` et `.port.d`, `.voisins-toile`, `svg.fleches`.
  3. La branche `nouveau-projet` de `agir` est retirée.
  4. L'élément `#pastille-cout` et la ligne qui le vide sont retirés.
  5. La constante jamais lue de `afficher()` et le paramètre inutilisé de `afficherSansProjet` sont retirés.
  6. Les tests sur des éléments toujours présents sont retirés, après vérification que l'élément est bien écrit en dur dans la page.
  7. Les commentaires faux relevés par l'audit disent la vérité.
  8. Aucun autre changement ; rien de visible ne change.
- **Preuve** : contrôles communs dans l'état de départ, vérification par vérification ; pour chaque retrait, la recherche qui montre l'absence d'usage (page, `chantier/essais/`, `tests/`).

## Vague 2 — les doublons (détaillée au lancement, sur le code issu de la vague 1)

- **M3a et M3b** (faites) : la table des efforts, le format d'un coût, le découpage du nom d'un agent, la coupe du brouillon aux balises et les deux phrases du profil écrits une fois. Vérification mécanique seule, comme la leçon le prévoit pour des remplacements de quelques lignes prouvés à l'identique. `ARRET` et `ARRETE`, et le repli d'identité git, touchent des garde-fous : ils rejoignent la décision de M5.
- **M4** : les trois « lire, modifier, réécrire `chantier/profil.json` » de `serveur.py` passent par une seule fonction, avec une seule gestion d'erreur.
- **M5** : les cinq fonctions `_git` deviennent une seule. Elle toucherait `atelier/controles.py`, un garde-fou : zone rouge, donc décision de la personne responsable avant de lancer.
- **M6a** (faite) : les petits calculs de la page écrits une fois. **M6b** : une seule façon d'envoyer une requête, un seul tracé de fil, une seule minuterie de message, là où les versions font vraiment la même chose.
- **M7** : dans `moteur.py`, l'historique d'une tentative et le calcul « monter puis vérifier le plafond » écrits une fois ; dans `carte.py`, le tronc commun de `_analyser` et `_mettre_a_jour`.

## Ce qui attend la personne responsable

- Le code qui ne vit que pour les tests : `GuichetSimule`, la propriété `mode_ouvriers` de `agents.py`, le champ `Etat.verifie`, les clés `ouvert`, `projet_cree`, `supprimes` et `nouveaux_absents`. Garder ou retirer avec les tests concernés.
- M5 (voir plus haut).
- Le découpage de `serveur.py` et de la page.
- La branche `claude/elegant-wozniak-hzzv8l`, devenue inutile.
- `chantier/PROFIL.md` parle encore de l'ambiance « verre fumé », remplacée le 2026-11-12.
