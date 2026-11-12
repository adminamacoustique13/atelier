# Fiche de relais M5c : `ARRET` et `ARRETE`, une seule constante ; `SANS_REPONSE`, deux noms

Copie de travail partie de 04307a2. Rien n'est commité.

## Fait
- Pas de boucle d'import : `guichet.py` n'importe que la bibliothèque standard ; `sdk.py` importe `agents`, qui importe `guichet`.
- `sdk.py` n'a plus `ARRET` : il importe `ARRETE` de `guichet.py` et l'utilise aux quatre endroits d'avant. Le texte « Arrêté par la personne responsable. » n'est plus écrit qu'une fois dans `atelier/` (`guichet.py`).
- `SANS_REPONSE` de `sdk.py` devient `CLAUDE_SANS_REPONSE` (définition et un usage). Celle de `guichet.py` ne bouge pas.
- Test ajouté en fin de `tests/test_sdk.py` : `test_l_arret_rendu_par_le_pont_est_celui_que_le_moteur_reconnait` vérifie `sdk.ARRETE is guichet.ARRETE`. Sur le code de départ il échoue : `AttributeError: module 'atelier.sdk' has no attribute 'ARRETE'. Did you mean: 'ARRET'?` (1 failed).

## Fichiers touchés
`atelier/sdk.py`, `tests/test_sdk.py` (un ajout), `chantier/relais/M5c.md`.

## Contrats modifiés
Aucun. Les noms `sdk.ARRET` et `sdk.SANS_REPONSE` n'étaient utilisés par aucun autre module ni aucun test (les tests ont leurs propres constantes locales).

## Reste à faire
Rien.

## Doutes et demandes
- Sur le code de départ le test échoue parce que le nom `ARRETE` n'existe pas dans `sdk`, non parce que deux objets diffèrent ; l'effet est le même (rouge au départ, vert après).
- Non touché, noté : `tests/test_sdk.py` définit ses propres `ARRETE` et `SANS_REPONSE` (textes recopiés), comme `test_agents.py` et `test_guichet.py`. Les textes sont aussi recopiés en dur dans `test_serveur.py`, `test_agents.py` et `test_guichet.py`. Hors périmètre.

## Résultats
- `pytest -q` : 765 passed (764 + le nouveau test).
- `ruff check .` : All checks passed!
