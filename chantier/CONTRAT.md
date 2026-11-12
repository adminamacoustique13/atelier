# Contrat de chantier — 2026-11-12

Validé le 2026-11-12 par la personne responsable (« Tu vas pouvoir lancer le ménage »), une fois les trois branches en cours fusionnées dans `main` (9d4cf2c).

Amendé le 2026-11-12 par la personne responsable (« gère les 4 points ») : les quatre points laissés pour le bilan entrent dans le chantier, et c'est l'orchestrateur qui tranche leurs détails.
1. Les deux incohérences d'affichage de la page (format d'un nombre de tokens, libellé de l'orchestrateur) : un seul format, ce qui change l'écran à ces deux endroits.
2. Les défauts antérieurs au chantier relevés en route (écriture du profil interrompue, réglage d'outils qu'on ne peut pas réessayer, valeur mal formée dans le profil, bouton bloqué quand le réseau tombe) : ils sont corrigés, chacun avec un test qui échoue avant.
3. Les tests qui manquent sur le suivi de la carte et sur le moteur : ils sont écrits.
4. Ce que le contrat protégeait. Trois zones rouges sont levées, pour ces tâches seulement : toucher `atelier/controles.py` et `atelier/guichet.py` pour réunir les fonctions qui appellent git et les constantes en double, sans changer ce qu'ils décident ; modifier ou retirer les tests qui ne servent qu'à du code retiré ou déplacé ; découper `atelier/serveur.py` et `atelier/tableau/index.html` en plusieurs fichiers, décision d'architecture inscrite au journal.

Le reste du contrat ne change pas : rien n'entre dans `main` sans sa décision, aucune bibliothèque ajoutée, aucun secret touché.

## Objectif
Retirer le code mort prouvé, corriger les commentaires qui ne disent plus la vérité et réunir les doublons, sans changer aucun comportement, pour un code d'une clarté absolue.

## Hors périmètre
- Découper `atelier/serveur.py` et `atelier/tableau/index.html` en plusieurs fichiers : la décision revient à la personne responsable, après ce chantier.
- Renommer en masse (les noms surchargés relevés par l'audit).
- Retirer du code qui ne vit que pour les tests, ou une clé que seuls des tests lisent : chaque cas lui est présenté avant.
- Toute nouvelle fonction du produit.

## Enveloppe
- Tentatives par tâche au maximum : 2
- Montées en gamme au maximum : 1
- Le nombre d'agents lancés n'est pas plafonné ; il est compté et donné à chaque point d'étape.

## Plafond d'escalade
Opus en effort élevé pour un ouvrier ; Fable pour un vérificateur.

## Zones rouges
- Changer un choix d'architecture inscrit au journal.
- Supprimer des fichiers ou réécrire l'historique git.
- Déployer ou pousser en production ; fusionner dans `main` (le travail reste sur la branche `claude/practical-meitner-ti380p` jusqu'à sa décision).
- Toucher aux secrets.
- Ajouter une bibliothèque au produit.
- Modifier les tests existants ou les scripts d'essai de `chantier/essais/`. Seule exception possible, après accord : un test qui ne sert qu'à du code retiré.
- Modifier les garde-fous eux-mêmes (`atelier/controles.py`, `atelier/guichet.py` pour ce qui décide d'une autorisation) autrement que par un commentaire ou une docstring.

## Preuve commune
Point de départ, relevé sur 9d4cf2c : 758 tests verts, contrôle de forme vert, 365 vérifications dans le navigateur sans échec (sept scripts de `chantier/essais/`). Chaque tâche rend ces trois contrôles dans le même état, et chaque suppression est précédée d'une recherche qui montre que plus rien ne s'en sert.
