# Leçons du projet Atelier

Leçons validées par la personne responsable. L'orchestrateur les lit à l'ouverture de chaque chantier et les applique.

## Pas de plafond sur le nombre d'agents lancés

- **Règle** : le contrat d'un chantier ne fixe plus de nombre maximal d'agents lancés. L'orchestrateur tient le compte des lancements et le donne à chaque point d'étape. Il ne s'arrête pas pour demander une rallonge.
- **Ce qui reste** : la limite de tentatives par tâche (au-delà, la tâche revient à la personne responsable) et la limite de montées en gamme. L'orchestrateur signale en clair toute tâche qui dépasse sa deuxième tentative.
- **Validée par** : la personne responsable, le 2026-11-11, pour ce chantier et pour les suivants.
- **Preuve** : pendant le chantier « Agent SDK », le plafond a été relevé quatre fois dans la même journée (de 18 à 24, 36, puis 44), avec un accord à chaque fois. Presque chaque tâche a demandé une seconde passe, que le calcul de départ (deux agents par tâche, plus la moitié) ne prévoyait pas.
- **Portée** : ce dépôt. La personne responsable a aussi retiré le plafond du skill `orchestrateur-chantier`, qui vit hors de ce dépôt, le 2026-11-11 : la règle vaut donc pour ses autres projets.
- **À revoir** : le 2027-05-11, ou plus tôt si un chantier consomme beaucoup plus que prévu sans que la personne responsable l'ait vu venir.

## La vérification se proportionne au risque

- **Règle** : l'orchestrateur choisit le niveau de vérification de chaque livrable d'après ce que coûterait un défaut passé inaperçu, et l'écrit dans le cahier.
  - **Complète** : le vérificateur éprouve les tests en cassant le code, refait ses propres essais et cherche activement à mettre le livrable en défaut. Pour ce qui touche à la sécurité, à la concurrence, à la facturation, aux garde-fous ou à un contrat entre modules.
  - **Bornée** : le vérificateur contrôle les critères et ne cherche que ce qui bloquerait (un comportement faux, une perte de travail, une faille). Il liste les remarques mineures sans recaler. Pour les tâches courantes et les secondes vérifications, qui ne portent que sur ce qui a été corrigé.
  - **Mécanique seule** : les contrôles du profil, le contrôle du périmètre et la lecture du diff par l'orchestrateur, sans vérificateur. Pour une correction de quelques lignes déjà prouvée par un test qui échouait avant, ou déjà essayée par un vérificateur, et pour la documentation.
- **Seconde passe** : elle corrige ce qui a été recalé, et rien d'autre. L'orchestrateur n'y ajoute aucune demande nouvelle ; une idée venue en route devient une tâche à part, ou une ligne du bilan.
- **Validée par** : la personne responsable, le 2026-11-11, pour ce chantier et pour les suivants.
- **Preuve** : pendant le chantier « Agent SDK », chaque vérification complète a pris de 10 à 35 minutes, et presque chaque tâche en a demandé deux ou plus. Une correction de quatre lignes, déjà essayée par un vérificateur sur une copie, a reçu une vérification complète de plus. La tâche E a connu quatre tentatives pour une fonction que l'orchestrateur avait ajoutée à la seconde passe. En face, les vérifications complètes ont trouvé de vrais défauts sur le pont, les agents, l'arrêt et la facturation : c'est là qu'elles restent utiles.
- **Portée** : ce dépôt. La vérification est décrite dans le skill `orchestrateur-chantier` (section « La vérification »), qui vit hors de ce dépôt : tant qu'il n'est pas modifié, l'ancienne règle s'applique ailleurs.
- **À revoir** : le 2027-05-11, ou plus tôt si un défaut sérieux passe une vérification bornée ou mécanique.
