# Contrat de chantier — 2026-11-11

Validé le 2026-11-11 par la personne responsable.

## Objectif
Faire piloter les agents d'Atelier par l'Agent SDK au lieu de `claude -p`. Chaque agent travaille alors en direct sous les yeux de la personne responsable, peut lui demander une autorisation depuis le tableau de bord (une fois, toujours pour ce projet, ou non avec une indication), et peut être arrêté d'un bouton.

## La décision que ce contrat te demande
Valider ce contrat revient à changer la toute première décision du journal : « moteur sans dépendance, au-dessus de Claude Code en ligne de commande ». Atelier dépendra désormais d'une bibliothèque, `claude-agent-sdk` :
- licence MIT ;
- éditée par Anthropic ;
- elle embarque son propre Claude Code ;
- elle n'envoie de données qu'à Claude, comme aujourd'hui.

Ce qui ne change pas : la connexion par ton abonnement, le modèle et l'effort par agent, la copie de travail par tâche, le vérificateur séparé, la montée en gamme, l'état dans des fichiers.

## Hors périmètre
- Raymonde, Pupitre et AMA-OS (ils viendront après, sur le même modèle).
- Les sous-agents propres au SDK : Atelier continue de lancer lui-même chaque agent, pour garder la main sur le dosage et la vérification.
- Le mode `auto` de Claude Code (un modèle qui accorde les autorisations à ta place).
- L'accès depuis le téléphone et toute écoute réseau au-delà de la machine.
- Les droits d'écriture de l'orchestrateur en conversation : il reste en lecture seule.
- La logique de dosage, d'escalade et de vérification (`dosage.py`, `consignes.py`, et l'enchaînement dans `moteur.py`), en dehors de ce que la tâche D1 y ajoute pour l'arrêt.

## Enveloppe
- Agents lancés au maximum : 18 (6 tâches automatisées, un ouvrier et un vérificateur chacune, plus la moitié en marge)
- Tentatives par tâche au maximum : 3 (le premier essai, la seconde chance, puis un cran au-dessus)
- Montées en gamme au maximum : 3 sur l'ensemble du chantier

## Plafond d'escalade
Je peux monter seul jusqu'au modèle frontière (Fable) en effort élevé. L'effort max demande ton accord.

## Zones rouges
- Changer un choix d'architecture inscrit au journal, en dehors de celui que ce contrat te demande de changer.
- Supprimer des fichiers ou réécrire l'historique git.
- Pousser sur la branche principale. Le chantier vit sur la branche `chantier/agent-sdk`, et c'est toi qui décides de la fusion.
- Toucher aux secrets, aux clés API ou aux identifiants de connexion.
- Ajouter au produit une bibliothèque autre que `claude-agent-sdk`, si sa licence n'est pas permissive ou si elle envoie des données à l'extérieur.
- Modifier les 35 tests existants ou les garde-fous (contrôle de périmètre, plafond, enveloppe, vérificateur).
- Retirer le mode démonstration ou l'agent simulé.
- Faire écouter le serveur ailleurs que sur 127.0.0.1.
