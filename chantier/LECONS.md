# Leçons du projet Atelier

Leçons validées par la personne responsable. L'orchestrateur les lit à l'ouverture de chaque chantier et les applique.

## Pas de plafond sur le nombre d'agents lancés

- **Règle** : le contrat d'un chantier ne fixe plus de nombre maximal d'agents lancés. L'orchestrateur tient le compte des lancements et le donne à chaque point d'étape. Il ne s'arrête pas pour demander une rallonge.
- **Ce qui reste** : la limite de tentatives par tâche (au-delà, la tâche revient à la personne responsable) et la limite de montées en gamme. L'orchestrateur signale en clair toute tâche qui dépasse sa deuxième tentative.
- **Validée par** : la personne responsable, le 2026-11-11, pour ce chantier et pour les suivants.
- **Preuve** : pendant le chantier « Agent SDK », le plafond a été relevé quatre fois dans la même journée (de 18 à 24, 36, puis 44), avec un accord à chaque fois. Presque chaque tâche a demandé une seconde passe, que le calcul de départ (deux agents par tâche, plus la moitié) ne prévoyait pas.
- **Portée** : ce dépôt. La même règle est écrite dans le skill `orchestrateur-chantier`, qui vit hors de ce dépôt : tant qu'il n'est pas modifié, elle s'applique ailleurs.
- **À revoir** : le 2027-05-11, ou plus tôt si un chantier consomme beaucoup plus que prévu sans que la personne responsable l'ait vu venir.
