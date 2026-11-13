# Contrat de chantier — 2026-11-13 (chantier « quatre trous »)

Validé le 2026-11-13 par la personne responsable (« Occupe-toi déjà des points de 1 »), sur la comparaison du dépôt avec la ligne « PC et autonomie » reçue en fichier bundle (`chantier/pc-autonomie`, 5f2c337). Le chantier « débit », terminé, est rangé dans `chantier/archives/2026-11-12-debit/`.

## Objectif
Fermer quatre trous du dépôt que la ligne « PC et autonomie » a déjà fermés : le serveur local accepte une demande venue d'un autre site ; un verdict mal écrit vaut accord ; aucun agent n'est empêché de lire un fichier de secrets ni de modifier git ; un fichier au nom accentué est déclaré hors de son périmètre.

## Second objectif (décision de la personne responsable, 2026-11-13 : « Tu pourras enchaîner sur tous les points de 2 »)
Porter dans le moteur sept règles de la ligne « PC et autonomie » : l'ouvrier reste ouvert après avoir rendu et reçoit un contrôle rouge ou un oubli sans compter de refus ; le travail refusé est gardé et une sous-tâche ne règle que ce qui reste ; le modèle ne monte que si le fond est faux et une retouche n'est vérifiée que sur ce qu'elle touche ; le vérificateur ne rejoue plus la suite et l'ouvrier rend une preuve par critère ; après une panne ou un arrêt le chantier patiente puis repart seul, travail gardé ; les niveaux de vérification sont branchés avec leur plancher ; le budget en dollars compte aussi un agent coupé. Les fiches des quatorze tâches sont dans `chantier/MOTEUR.md`.

Demandée en plus le même jour (« Lance la maquette en parallèle dès maintenant ») : une tâche V1 de maquettes, sans code du produit, pour la Salle avec plusieurs agents en même temps et pour l'état du dépôt git.

## Hors périmètre
- Les points 3 et 4 de la comparaison, à discuter ensuite avec la personne responsable : les contrôles après envoi, le verrou de branche, le socle Windows, le juge de commandes, le plan de pilotage, la forme des fichiers partagés.
- Coder dans le produit ce que montrent les maquettes, avant que la personne responsable en ait choisi une.
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
- Modifier les tests ou les essais existants, sauf exception arbitrée et notée au journal. Arbitré d'avance pour le second objectif : un test qui prouve une règle que la personne responsable a renversée (tâche interrompue rendue à la personne, copie jetée après un refus, seconde chance et montée pour un travail bâclé, vérificateur un modèle au-dessus pour une tâche courante) peut être réécrit par l'ouvrier, qui en rend la liste exacte dans sa fiche.
