# Relais M6a : les petits calculs écrits une seule fois

## Fait
Les comparaisons sont dans `scratchpad/essais-M6a/comparer.js` et `fable.js` (hors dépôt) : versions d'origine recopiées telles quelles, 502 comparaisons sur des entrées variées (non défini, null, 0, -0, négatifs, NaN, Infinity, chaînes, booléens, 999, 999,5, 1 000, 999 499, 999 500, 1e6 ± 1, 1e9, 1e21, demi-centimes…).
1. **Tokens : NON réunis.** Le calcul en ligne des jauges du Chantier et `millions()` de la Salle diffèrent sur des entrées réelles : précision (1 234 567 donne « 1,2M » d'un côté, « 1,23 M » de l'autre ; 9 990 000 donne « 10M » contre « 9,99 M ») et habillage (« M » collé contre `<small> M</small>`, de même pour « k »). Les réunir changerait l'écran.
2. **Coût : réuni.** Nouvelle fonction `montant(n)` (le nombre à deux décimales, sans unité) ; `euros(n)` devient `montant(n) + " $"`. Utilisée par `euros()`, la Salle (`${montant(vue.cout_usd)}<small> $</small>`, à la place du calcul en ligne) et les jauges du Chantier (`${montant(vue.cout_usd)}$`, à la place de `euros(...).replace(" $", "$")`). 0 écart sur les trois écritures.
3. **Tâches vérifiées : réuni.** `nombreVerifiees(vue)`, utilisée aux six endroits : `afficherConversation` (rail-anneau), `afficherChantier` (anneau), `graphe()` (le Plan), `stationsDe()` (le sol de la Salle), `afficherSalle`, `afficher`. 0 écart.
4. **En cours ou en vérification : réuni.** `tacheActive(t)`, utilisée dans `poste()`, `salle()`, `agentsHtml()` et `stationsDe()` (les trois derniers via `filter(tacheActive)`). 0 écart. Les tests sur un état nu (`etatFil`, `etatEtape`, `e === …`) ne portent pas sur une tâche et sont laissés.
5. **« Fable · élevé » : NON réuni.** Les trois endroits : le HTML statique de la carte Orchestrateur (hors périmètre), `stationsDe()` (« Fable · élevé ») et `afficherSalle()`, qui écrit « Orchestrateur · Fable élevé », sans point médian entre Fable et élevé. Une constante n'aurait donc servi qu'à un seul endroit du JavaScript.
6. **Page du Code : réuni.** `pageCodeHtml(enCours)`, placée juste avant `pageDossierHtml`, utilisée par `afficherCode()` et par le `ResizeObserver` de l'onglet Code. 0 écart, et `enCoursDe()` est toujours appelée une seule fois.
7. **Bouton d'arrêt : réuni.** `habitArret(cle)` rend `{ demande, confirme, libelle, titre }` ; `habillerArret()` et `boutonArret()` le lisent. Comparé sur le DOM (texte, disabled, title, classe) et le HTML produit, clés à guillemets et chevrons comprises : 0 écart.
8. Les identifiants, les classes et les fonctions globales attendues par les essais n'ont pas changé. Les nouvelles fonctions sont internes.
9. Aucun autre changement.

## Fichiers touchés
`atelier/tableau/index.html` (JavaScript seulement), `chantier/relais/M6a.md`.

## Contrats modifiés
Aucun.

## Reste à faire
Rien dans le périmètre.

## Doutes et demandes
- Tokens : décider d'un seul format (une décimale ou deux, avec ou sans `<small>`) ; ensuite seulement on pourra les réunir, avec un changement visible.
- « Fable · élevé » : il faudrait harmoniser la Salle (point médian) et autoriser l'écriture du HTML statique depuis une constante. Les deux sortent de ce périmètre.
- Remarqué sans y toucher : `euros()` porte un nom qui ne correspond pas à son unité, puisqu'elle affiche « $ ». Les deux formats de tokens affichent « 1000k » de 999 500 à 999 999, jamais « 1M ». Et `poste()` appelle sa variable `actif` et `salle()`/`stationsDe()` appellent la leur `actifs`, pour la même notion.

## Essais
ACCUEIL-projets 26 ok, CODE-carte 36 ok, D2-tableau 95 ok, D3-modes 82 ok, G-mise-a-jour 70 ok, NC-nouveau-chantier 29 ok, VISUEL-onglets 27 ok, aucun ECHEC (CODE-carte réussi du premier coup). Tests Python : 758 passed.
