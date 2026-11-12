# Fiche de relais M3a : archives et carte, deux petits doublons

## Fait
1. Table des efforts : vérifié par `assert` que `archives.EFFORTS == dosage.EFFORTS_FR` (égales). `dosage.py` n'importe que `__future__` : pas de boucle. `archives.py` importe désormais `EFFORTS_FR` depuis `dosage.py` et n'a plus sa table.
2. Format du coût : script `/tmp/claude-0/-home-user-atelier/d04ea8ab-c665-54ab-9a3a-d57048e9c6b4/scratchpad/essais-M3a/compare.py`, 19 valeurs (0, -0.0, 0.001, 0.005, 0.994, 0.995, 1, 9.999, 1234.5, négatives, 1e9, 2.675, None, clé absente) : 0 différence (None lève TypeError des deux côtés ; clé absente donne « 0,00 $ »). Écrit une fois dans `archives.cout_fr(montant)`, utilisée par `archives.journal` et par `carte.resume` (`carte.py` importait déjà `archives`, `archives` n'importe pas `carte` : pas de boucle).
3. Aucun texte ni fichier changé : chaînes identiques.
4. Tests existants non modifiés.
5. Aucun autre changement.

## Fichiers touchés
`atelier/archives.py`, `atelier/carte.py`, `tests/test_archives.py` (ajout de `test_cout_fr`, fonction publique nouvelle), `chantier/relais/M3a.md`. `dosage.py` intact.

## Contrats modifiés
Aucun. Nouvelle fonction publique : `archives.cout_fr`.

## Reste à faire
Rien.

## Doutes et demandes
Aucun.

Tests : 762 passed (761 + le nouveau). Contrôle de forme : All checks passed!
