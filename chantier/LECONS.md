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

## Le dosage des modèles

- **Règle** : Sonnet pour le travail cadré (retrait, script, textes, page, module isolé, branchement) ; Opus pour le gros du code, pour tout ce qui touche à la concurrence et pour toute logique à état, même petite ; Fable pour la conception, l'arbitrage, l'orchestration et ce qui est sensible (sécurité, facturation). Haiku n'est plus un point de départ pour du code.
- **Le vérificateur** : Fable pour une vérification complète ; pour une vérification bornée, un modèle au moins égal à celui de l'ouvrier, avec un contexte neuf.
- **Validée par** : la personne responsable, le 2026-11-11.
- **Preuve** : chantier « Agent SDK ». Sonnet en effort moyen a calé trois fois sur la logique à état de la tâche E, qu'Opus a réécrite en une passe. Sonnet est passé du premier coup sur H, D2.1, D3b, Ga et Gb. Aucune seconde passe d'Opus ne venait d'un manque de capacité. Haiku n'a pas été utilisé : la règle qui l'écarte vient du jugement de la personne responsable, pas d'un constat. Détail dans `chantier/DOSAGE.md`.
- **Portée** : ce dépôt. Le skill `orchestrateur-chantier` porte une autre table de départ tant qu'il n'est pas modifié.
- **À revoir** : le 2027-05-11, ou à la sortie d'une nouvelle génération de modèles.

## Relire la consigne avant de lancer une tâche délicate

- **Règle** : avant de lancer une tâche délicate, l'orchestrateur relit sa consigne en se demandant ce qui manque pour que la preuve prouve le but. Il passe au moins ces questions : que se passe-t-il à l'arrêt, sur une erreur, sur un délai dépassé ? Chaque règle est-elle énoncée en entier, ou seulement par un exemple ? La preuve contient-elle un cas adverse ? Un composant simulé cache-t-il un comportement du vrai (durées, erreurs, ordre des messages) ? Un test peut-il rester vert alors que la règle est cassée ?
- **Validée par** : la personne responsable, le 2026-11-11.
- **Preuve** : chantier « Agent SDK ». Presque chaque verdict de recalage a relevé un trou de la consigne, et chacun a coûté un aller-retour de 30 à 60 minutes : un faux client aux réponses instantanées (A), une liste d'exclusions demandée alors qu'elle ne peut pas être complète (B), le moment où un appel arrêté rend la main (C), l'arrêt effectif de l'agent (D1), un exemple de règle limité aux commandes (D2), une règle de non-répétition jamais énoncée (E, quatre tentatives), « contient » au lieu de « commence par » (D3a).
- **Portée** : ce dépôt.
- **À revoir** : le 2027-05-11.

## Couper une tâche qui traverse plus de trois fichiers

- **Règle** : une tâche qui touche plus de trois fichiers, ou à la fois le fond et la page, est coupée en deux : le fond d'abord (avec ce qu'il fournit, écrit dans sa fiche de relais), la page ensuite. Les deux moitiés sont dosées et vérifiées séparément, et la seconde peut partir dès que le contrat de la première est stable.
- **Validée par** : la personne responsable, le 2026-11-11.
- **Preuve** : chantier « Agent SDK ». D3 et G, coupées en un fond et une page, ont avancé en parallèle : Ga a pris trois minutes d'ouvrier et trois de vérification, D3b et Gb sont passées du premier coup. Les tâches d'un seul bloc (E, D1, D2) ont toutes demandé au moins deux passes.
- **Portée** : ce dépôt.
- **À revoir** : le 2027-05-11.
