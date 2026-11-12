# CC — L'onglet Code montre toujours le fichier où un agent travaille

## Fait
- `disposerCode` prend un quatrième paramètre `enCours` (Map, vide par défaut). Un bloc vivant (fichier en cours ou brouillon d'agent, ou dossier qui en contient un) passe avant les autres dans le tri qui précède la coupe à 12. Les brouillons sont couverts : `enCoursDe` y met déjà les fichiers provisoires, et le bloc fantôme porte le chemin du brouillon.
- L'appel dans `pageDossierHtml` transmet `enCours`.
- Légende : « 1 autre élément » / « N autres éléments » (le pluriel s'accorde maintenant sur les deux mots).
- Sans travail en cours, `vif` vaut 0 partout : le tri est celui d'avant (même ordre, mêmes blocs).

## Fichiers touchés
- `atelier/tableau/index.html` (JavaScript seulement)
- `chantier/relais/CC.md`

## Contrats modifiés
- `disposerCode(blocs, aretes, parRangee, enCours = new Map())` : paramètre ajouté, optionnel.

## Essais
- CODE-carte, dix passages : 36, 36, 36, 36, 36, 36, 36, 36, 36, 36 (aucun ECHEC)
- ACCUEIL-projets 26, D2-tableau 95, D3-modes 82, G-mise-a-jour 70, NC-nouveau-chantier 29, PANNES-reseau 34, VISUEL-onglets 27 (aucun ECHEC)
- pytest : 873 verts

## Reste à faire
- Option du diagnostic non faite : rendre déterministe la tâche qui attend dans la démonstration.

## Doutes
- Aucun sur la correction. Un bloc vivant peut prendre la place d'un bloc plus relié dans les 12 ; c'est voulu.
