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
| M5a. Une base commune pour appeler git, adoptée par `projets`, `essai`, `carte` | en cours | Opus | complète, Fable | 1 | |
| M5b. La base git adoptée par `controles` et `mise_a_jour` | à lancer, après M5a | Opus | complète, Fable | | |
| M5c. `ARRET` et `ARRETE` : une seule constante ; `SANS_REPONSE` : deux noms | en cours | Sonnet | bornée, Opus | 1 | |
| M9. Profil : écriture d'un seul geste, réglage d'outils qu'on peut réessayer, valeur mal formée refusée | en cours | Opus | complète, Fable | 1 | |
| M10. Les tests qui manquent : suivi de la carte, moteur | en cours | Opus | bornée, Fable (par casses) | 1 | |
| M8. Page : un seul format de tokens, un seul libellé de l'orchestrateur, pannes de réseau dites à l'écran | à lancer, après M6b | Opus | bornée, Fable | | |
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
