# Cahier des charges — chantier « ménage », 2026-11-12

État général : en cours. Première vague lancée (M1 et M2).

Source des constats : l'audit du 2026-11-12 (deux lecteurs en lecture seule sur 513bf22, constats principaux recontrôlés par l'orchestrateur sur `main`). Les chantiers précédents sont rangés dans `chantier/archives/`.

## Suivi

Compteur : 5 agents lancés dans le chantier (2 ouvriers, 1 vérificateur, plus les 2 lecteurs de l'audit, avant le contrat).

| Tâche | État | Ouvrier | Vérification | Tentatives | Preuve |
|---|---|---|---|---|---|
| M1. Python : code mort et commentaires faux | vérifié | Sonnet | bornée, Opus : accepté | 1 | 758 tests et contrôle de forme verts ; recherches refaites par le vérificateur |
| M2. Page : code mort et commentaires faux | vérifié | Sonnet | bornée, Opus : accepté | 1 | 758 tests, contrôle de forme et 365 vérifications dans le navigateur verts ; chaque retrait recherché à nouveau par le vérificateur |
| M3. Python : petits doublons | à lancer | Sonnet | bornée, Opus | | |
| M4. Serveur : une seule écriture du profil | à lancer | Opus | complète, Fable | | |
| M5. Une seule fonction pour appeler git | à lancer, attend une décision | Opus | complète, Fable | | |
| M6. Page : doublons | à lancer, après M2 | Opus | bornée, Opus | | |
| M7. Moteur et carte : doublons internes | à lancer, après M1 | Opus | complète, Fable | | |

### Restes mineurs relevés par le vérificateur de M1, non corrigés
- `atelier/guichet.py:20`, `SCENARIO_EPUISE` : le texte parle encore du « scénario de démonstration ». C'est une chaîne du code d'un garde-fou, hors du périmètre de M1.
- La docstring de `_Marche` (`atelier/agents.py`) ne décrit pas `reveil`, `fin_emise` ni `couper`.

### Restes mineurs relevés par le vérificateur de M2, non corrigés
- L'en-tête des styles parle encore de « bleu nuit » alors que la variable `--nuit` a disparu ; la phrase reste juste comme description de la palette.
- Relevés par l'ouvrier : dans `stationsDe`, le commentaire « Coordonnées écran » précède `parallele` alors qu'il décrit `sol` et `lieu` ; la ligne de tête sur le refus (« jamais par une couleur de plus ») est en tension avec `.mode-refus`, en ambre.

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

- **M3** : `archives.EFFORTS` reprend `dosage.EFFORTS_FR` ; `ARRET` et `ARRETE`, même texte sous deux noms, deviennent une seule constante ; le repli d'identité git écrit deux fois.
- **M4** : les trois « lire, modifier, réécrire `chantier/profil.json` » de `serveur.py` passent par une seule fonction, avec une seule gestion d'erreur.
- **M5** : les cinq fonctions `_git` deviennent une seule. Elle toucherait `atelier/controles.py`, un garde-fou : zone rouge, donc décision de la personne responsable avant de lancer.
- **M6** : dans la page, une seule façon d'envoyer une requête, un seul tracé de fil, une seule minuterie de message, un seul format de coût et de tokens.
- **M7** : dans `moteur.py`, l'historique d'une tentative et le calcul « monter puis vérifier le plafond » écrits une fois ; dans `carte.py`, le tronc commun de `_analyser` et `_mettre_a_jour`.

## Ce qui attend la personne responsable

- Le code qui ne vit que pour les tests : `GuichetSimule`, la propriété `mode_ouvriers` de `agents.py`, le champ `Etat.verifie`, les clés `ouvert`, `projet_cree`, `supprimes` et `nouveaux_absents`. Garder ou retirer avec les tests concernés.
- M5 (voir plus haut).
- Le découpage de `serveur.py` et de la page.
- La branche `claude/elegant-wozniak-hzzv8l`, devenue inutile.
- `chantier/PROFIL.md` parle encore de l'ambiance « verre fumé », remplacée le 2026-11-12.
