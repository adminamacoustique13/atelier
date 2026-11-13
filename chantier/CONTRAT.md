# Contrat de chantier — 2026-11-12 (chantier « débit »)

Validé le 2026-11-12 par la personne responsable (« Lance »), sur la proposition de l'orchestrateur : un chantier court, trois ouvriers en parallèle dès le départ. Le chantier « ménage », arrêté sur sa décision, est rangé dans `chantier/archives/2026-11-12-menage/`.

## Objectif
Maximiser en continu le nombre d'agents qui travaillent ensemble dans l'Atelier : des fichiers partagés par plusieurs tâches parallèles, avec une fusion prévue ; six places d'écriture, les vérificateurs hors place et un régulateur qui suit les limites de l'abonnement ; plus aucun arrêt pour un outil refusé sans rapport avec le travail.

## Hors périmètre
- Les tâches reportées du chantier « ménage » : V3c (l'agent qui n'avance plus), V3d (montées par tâche), V3e (vérification proportionnée branchée dans le moteur), P2 (signes de vie), les découpages de `atelier/serveur.py` et de la page.
- L'affichage des places et des fichiers partagés dans la page : une tâche suivante.

## Enveloppe
- Tentatives par tâche au maximum : 2, la reprise à chaud comprise.
- Montées en gamme au maximum : 1.
- Agents : trois ouvriers, trois vérificateurs, la moitié en marge, soit neuf.

## Plafond d'escalade
Opus pour les ouvriers et les vérificateurs (les crédits de Fable sont épuisés pour cette session).

## Zones rouges
- Changer un choix d'architecture inscrit au journal. Exception décidée par la personne responsable : un fichier déclaré partagé peut entrer dans le périmètre de plusieurs tâches parallèles (la règle de la tâche de raccord ne vaut plus que pour un fichier commun non déclaré).
- Supprimer des fichiers ou réécrire l'historique git.
- Faire entrer quoi que ce soit dans `main` sans sa décision.
- Toucher aux secrets ; ajouter une bibliothèque au produit.
- Modifier les tests ou les essais existants, sauf exception arbitrée et notée au journal.
