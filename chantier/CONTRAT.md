# Contrat de chantier — 2026-11-13 (chantier « quatre trous »)

Validé le 2026-11-13 par la personne responsable (« Occupe-toi déjà des points de 1 »), sur la comparaison du dépôt avec la ligne « PC et autonomie » reçue en fichier bundle (`chantier/pc-autonomie`, 5f2c337). Le chantier « débit », terminé, est rangé dans `chantier/archives/2026-11-12-debit/`.

## Objectif
Fermer quatre trous du dépôt que la ligne « PC et autonomie » a déjà fermés : le serveur local accepte une demande venue d'un autre site ; un verdict mal écrit vaut accord ; aucun agent n'est empêché de lire un fichier de secrets ni de modifier git ; un fichier au nom accentué est déclaré hors de son périmètre.

## Hors périmètre
- Tout le reste de la comparaison : les règles du moteur après un refus ou une panne, les contrôles après envoi, le verrou de branche, le socle Windows, le juge de commandes, le plan de pilotage.
- Les restes du chantier « débit » et les tâches reportées du chantier « ménage ».

## Enveloppe
- Tentatives par tâche au maximum : 2, la reprise à chaud comprise.
- Montées en gamme au maximum : 1.
- Pas de plafond sur le nombre d'agents (leçon du 2026-11-11) ; le compte est donné au bilan.

## Plafond d'escalade
Fable en effort élevé.

## Zones rouges
- Changer un choix d'architecture inscrit au journal.
- Supprimer des fichiers ou réécrire l'historique git.
- Faire entrer quoi que ce soit dans `main` sans la décision de la personne responsable.
- Toucher aux secrets ; ajouter une bibliothèque au produit.
- Modifier les tests ou les essais existants, sauf exception arbitrée et notée au journal.
