# Fiche de relais V3-refus : reconnaître un refus qui se répète et un agent empêché

## Fait
1. `atelier/refus.py` : module pur, seul import `difflib` et `re`, aucun module d'Atelier.
2. `meme_refus` : même origine (absente des deux = égale), même issue, détail proche (minuscules, suites de chiffres remplacées par « # », espaces réduits, 600 derniers caractères du texte ainsi réduit, `SequenceMatcher`, seuil `SEUIL_RESSEMBLANCE = 0.9`). Détail vide des deux côtés : faux.
3. `refus_identiques_de_suite` : compte la dernière entrée et les précédentes qui sont le même refus qu'elle ; une entrée `valide` coupe la suite (dernière entrée valide : 0).
4. `empechements` : lignes commençant (après espaces) par « EMPÊCHÉ : » (on rend le texte qui suit), puis outils refusés, puis `empeche` du verdict (chaîne ou liste) ; sans doublon, dans l'ordre ; ne lève jamais.
5. `tests/test_refus.py` : 17 tests, cas adverses compris.
6. Preuve que les tests gardent les règles : seuil 0,9 changé en 0,3 : 2 tests échouent (`test_seuil_garde_les_refus_voisins_mais_differents`, `test_suite_coupee_par_un_refus_different`) ; « commence par » changé en « contient » : `test_empechement_au_milieu_d_une_ligne_ne_compte_pas` échoue. Code remis ensuite.

## Fichiers touchés
`atelier/refus.py` (nouveau), `tests/test_refus.py` (nouveau), `chantier/relais/V3-refus.md`.

## Contrats
```
SEUIL_RESSEMBLANCE = 0.9
CARACTERES_COMPARES = 600
MARQUE_EMPECHEMENT = "EMPÊCHÉ :"
def meme_refus(a: dict, b: dict) -> bool
def refus_identiques_de_suite(historique: list[dict]) -> int
def empechements(compte_rendu: str, refuses: list[str] | None, verdict: dict | None) -> list[str]
```

## Reste à faire
Le moteur doit s'en servir (fiche V3b) : règles de blocage, lecture du compte rendu, `Resultat.refuses`.

## Doutes
- Les 600 caractères sont pris après normalisation (sinon un « 9 » devenu « 10 » décalerait la fenêtre).
- Pour une suite, un seul refus non vide vaut 1 ; un historique de refus à détail vide vaut 1 aussi (jamais de répétition prouvée).
- `empechements` rend le texte après « EMPÊCHÉ : » (sans la marque) ; un texte vide est ignoré.

Tests : `pytest -q` : 890 passed (873 + 17). Contrôle de forme : `ruff check .` : All checks passed ; `ruff format --check` des deux fichiers : propre.

## Seconde passe
Règle retenue pour le détail (après l'origine et l'issue, inchangées) :
1. Veto : si les deux détails citent des fichiers (mot, point, extension) et que les ensembles diffèrent, ce n'est pas le même refus (toute origine, pas seulement « perimetre »).
2. Sinon, même refus si la forme (`SequenceMatcher`) atteint `SEUIL_RESSEMBLANCE = 0.9`,
3. ou si l'indice de Jaccard des mots significatifs (au moins `LETTRES_MIN_D_UN_MOT = 4` lettres, hors `MOTS_VIDES` dont « critère », « tenu », « livrable ») atteint `SEUIL_MOTS_COMMUNS = 0.3`, chaque détail portant au moins `MOTS_SIGNIFICATIFS_MIN = 3` mots.
Entrées mal formées : `meme_refus` rend faux, `refus_identiques_de_suite` rend 0 (ou compte seulement les entrées valides en fin de suite). Signatures inchangées.

| Paire | Jaccard | Forme | Même refus |
|---|---|---|---|
| A-B (vrais refus) | 0,36 | 0,55 | oui |
| B-C | 0,38 | 0,55 | oui |
| A-C | 0,88 | 0,92 | oui |
| format non tenu / test qui échoue | 0,00 | 0,25 | non |
| page téléphone / consigne redémarrage | 0,00 | 0,23 | non |
| uv.lock absent / tokens de la page | 0,00 | 0,65 | non |
| débord carte.py / moteur.py | 0,60 | 0,94 | non (veto fichiers) |
| tests FAILED test_carte / test_moteur | 0,60 | 0,92 | non (veto fichiers) |

Épreuves : retour à la forme seule : 2 tests échouent (les trois vrais refus ; les paires différentes). Normalisation des chiffres retirée : `test_numero_de_ligne_ou_duree_ne_change_pas_le_refus` échoue (exemples choisis pour l'exiger). Code remis ensuite.

Doute : la marge sur A-B et B-C est mince (0,36 et 0,38 contre un seuil de 0,3) ; les paires négatives sans fichier restent à 0,00, donc on peut relever un peu le seuil si le moteur voit des faux positifs. Deux refus sans fichier cité et de même vocabulaire mais de sujets différents ne sont pas distingués par construction.

Tests : `pytest -q` : 893 passed ; `ruff check .` vert ; `ruff format --check` propre.
