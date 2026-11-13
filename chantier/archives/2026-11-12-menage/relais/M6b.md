# Relais M6b : envois au serveur, minuteries de message, tracés de fil

## Fait
Essais hors dépôt dans `scratchpad/essais-M6b/` : `traces.js` (trace contre arrondi), `pannes.js` (la page d'avant, `index-avant.html`, puis la mienne, sur le serveur de démonstration avec les routes interceptées : réponse 500, connexion coupée, réponse 200 qui n'est pas du JSON ; sorties `avant.json` et `apres.json`, identiques à l'octet).

1. **Envois : un seul `fetch` POST.** Nouvelle fonction de base `posterJson(adresse, corps)` (POST, en-tête JSON, `JSON.stringify(corps)`, rend la promesse de `fetch` sans rien en faire). `envoyer`, `envoyerSansAfficher` et `demander` s'en servent, chacune avec un commentaire d'une phrase sur ce qui la distingue. Les deux `fetch` en ligne de `mettreAJour` et `nouveauChantier` faisaient exactement ce que fait `envoyerSansAfficher` : ils l'appellent désormais. Les `fetch` GET de `/api/etat` (`charger`, `ouvrirNouveauChantier`) ne sont pas des envois et restent tels quels.

| Fonction | Corps envoyé | 200 en JSON | Erreur (500…) | Panne de réseau | 200 pas en JSON | Avant = après |
|---|---|---|---|---|---|---|
| `envoyer` | `corps \|\| {}` ; rien en mode rejoué | affiche la vue, la rend | rend null, n'affiche rien | lève (TypeError) | lève (SyntaxError) | oui |
| `envoyerSansAfficher` | `corps \|\| {}` | rend le JSON | null | null | null | oui |
| `demander` | `corps` tel quel | `{ ok: true, donnees }` | `{ ok: false, donnees }` (JSON lu quand même) | lève | lève | oui |
| `mettreAJour` (était en ligne) | `"{}"` (= `JSON.stringify({})`) | suite habituelle | « La demande n'est pas partie… » | idem | idem | oui |
| `nouveauChantier` (était en ligne) | `{ nom }` | suite habituelle | « La demande n'est pas partie… », formulaire ouvert | idem | idem | oui |

   Seule nuance : dans `nouveauChantier`, la lecture du champ `#nom-chantier` sort du `try` ; ce champ est du HTML statique, toujours présent, donc rien ne change.
2. **Minuteries : motif écrit une fois.** `messagePassager(poser, montrer, dureeParDefaut)` rend une fonction qui pose le texte, annule sa propre minuterie, programme l'effacement si le texte et la durée ne sont pas vides, puis montre. `dire` (avisTexte, `rafraichir`, 9 s), `direMaj` (majPhrase, `afficherMaj(derniere)`, 15 s) et `direNouveauChantier` (ncPhrase, `afficherNouveauChantier`, 20 s) en sont trois instances, chacune avec sa minuterie fermée dans la sienne (les variables `minuteAvis`, `minutePhrase`, `minuteNcPhrase` disparaissent). Vérifié dans `pannes.js` : chaque message s'efface à son délai sans toucher aux autres, une durée 0 le garde.
3. **Tracés : NON réunis.** `traces.js` extrait les deux fonctions de la page et compare 24 entrées (coude simple, points alignés, confondus, négatifs, décimaux, rayon plus grand que les segments ; rayons par défaut, 9, 10, 50) : **0 identique, 24 différentes**. Exemple : `[[0,0],[0,50],[80,50],[80,100]]`, rayon 9 : trace rend `M0,0 L0,41 Q0,50 9,50 …`, arrondi rend `M0.0,0.0 L0.0,41.0 Q0.0,50.0 9.0,50.0 …` (arrondi écrit au dixième ; rayons par défaut 10 et 9). Chacune porte maintenant un commentaire qui dit cette différence ; `arrondir` aussi (elle rend des points échantillonnés, pas un chemin SVG).
4. `habitArret` devient `aspectArret` (deux appels) ; sa variable locale `habit` devient `aspect` dans les deux fonctions qui l'appellent, pour que la lecture suive. Le commentaire « Le bouton « Arrêter »… » est remonté au-dessus de `habillerArret`.
5. Adresses, corps, en-têtes et identifiants inchangés (journal des POST identique avant et après) ; `charger`, `chargerAccueil`, `afficherArchives`, `afficher`, `INSTANTANES`, `pas` intacts ; les gardes `rejoue` sont à leur place, avant tout envoi.

## Fichiers touchés
- `atelier/tableau/index.html` (JavaScript seulement).
- `chantier/relais/M6b.md` (cette fiche).

## Contrats modifiés
Aucun à l'extérieur de la page. Dans la page : `dire`, `direMaj`, `direNouveauChantier` sont des `const` et non plus des déclarations `function` (elles ne sont donc plus propriétés de `window`) ; aucun essai ni le serveur ne les appelle par là. Nouvelles fonctions `posterJson`, `messagePassager`.

## Reste à faire
Rien pour cette tâche.

## Doutes et demandes
- `dire("")` programmait avant un effacement inutile (un `rafraichir()` 9 s plus tard) ; il ne le fait plus, comme `direMaj` et `direNouveauChantier`. Rien de visible : le texte est déjà vide. Tous les appels passent un texte non vide (littéral ou phrase du serveur).
- Une quatrième minuterie du même genre existe, `modePhrase`/`minuteMode` dans `choisirMode` (objet `{ texte, fait }`, annulée avant l'envoi) : hors liste, non touchée.
- Défauts remarqués et laissés : une panne de réseau dans `demander` n'est rattrapée nulle part (rejet non traité ; sur le formulaire de clonage, le bouton resterait inactif sur « Récupération en cours… », et de même pour « Envoi en cours… » de la liaison) ; une réponse d'erreur qui n'est pas du JSON fait aussi lever `demander`. `envoyer("/api/message")` et `envoyer` pour valider ou décider ne rattrapent pas non plus une panne (rejet non traité, rien à l'écran).
- Le commentaire de section « Projets : … » et celui de `demander` ont été réunis en un seul bloc, pour ne pas recréer deux commentaires empilés.

Essais (un par un) : ACCUEIL-projets 26 ok, CODE-carte 36 ok (une première passe s'est arrêtée à 28 sans aucun ECHEC, délai dépassé ; relancé, 36), D2-tableau 95, D3-modes 82, G-mise-a-jour 70, NC-nouveau-chantier 29, VISUEL-onglets 27 ; aucun ECHEC. Tests Python : 758 passés.
