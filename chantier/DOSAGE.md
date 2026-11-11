# Dosage : ce que les chantiers ont appris

Une ligne par type de tâche : le modèle et l'effort choisis, et ce qui s'est passé. L'orchestrateur le consulte avant de doser.

## Chantier « Agent SDK », 2026-11-11

| Tâche | Type | Ouvrier | Passes | Ce qu'on en retient |
|---|---|---|---|---|
| A, le pont vers le SDK | Contrat entre modules, concurrence | Opus, effort élevé | 2 | Bon niveau. La seconde passe venait d'une preuve mal posée : un faux client aux réponses instantanées cachait deux défauts d'arrêt. |
| B, le guichet | Concurrence, sécurité d'une règle | Opus, effort élevé | 3 | La concurrence est passée du premier coup. Les deux passes de plus venaient de la consigne, qui demandait une liste d'exclusions, incomplète par nature. |
| C, les agents sur le SDK | Remplacement d'un câblage, concurrence | Opus, effort élevé | 2 | Bon niveau. Le défaut restant tenait à une règle que la consigne n'énonçait pas. |
| D1, le serveur | Fonctionnalité avec tests clairs, touche au moteur | Sonnet, effort élevé | 2 | Suffisant. Le défaut restant tenait encore à une règle non énoncée. |
| H, le ménage | Retrait cadré | Sonnet, effort moyen | 1 | Du premier coup, en une minute et demie. |
| E, installation et facturation | Script, textes, petite logique à état | Sonnet, effort moyen, puis Opus, effort élevé | 4 | Sonnet en effort moyen a bien fait le script et les textes, et calé trois fois sur la logique à état. Opus l'a réécrite en une passe. Une logique à état, même petite, part sur Opus. |
| E.1, la source qui change | Logique à état, facturation | Opus, effort moyen | 1 | Du premier coup. |
| D2, le tableau de bord | Page, essai dans un navigateur | Sonnet, effort moyen | 2 | Suffisant. La seconde passe venait de défauts d'ergonomie que la preuve ne demandait pas d'éprouver. |
| D2.1, une ligne de style | Correction mécanique | Sonnet, effort faible | 1 | Du premier coup. |
| I, la course de `controles.py` | Correction de quatre lignes, concurrence | Sonnet, effort élevé | 1 | Du premier coup. La vérification complète était de trop : la correction avait déjà été essayée. |
| D3a, le mode des ouvriers | Sécurité des agents, quatre modules | Opus, effort élevé | 2 | Bon niveau. Rien de grave au premier verdict ; deux défauts courts. |
| D3b, le menu | Page | Sonnet, effort moyen | 1 | Du premier coup. |
| Ga, le module de mise à jour | Module isolé avec tests clairs | Sonnet, effort moyen | 1 | Du premier coup, en trois minutes. |
| Gb, le bouton de mise à jour | Branchement serveur et page | Sonnet, effort moyen | 1 | Du premier coup. |

## Ce qui ressort

- **Sonnet** tient le travail cadré : retrait, script, textes, page, module isolé, branchement. Il a calé sur une logique à état.
- **Opus** a porté le gros du code et tout ce qui touche à la concurrence. Aucune de ses secondes passes ne venait d'un manque de capacité.
- **Haiku** n'a pas été utilisé : ce chantier ne dit rien sur lui.
- **Fable** a servi à orchestrer et à vérifier. Comme vérificateur, il a trouvé les défauts les plus graves du chantier ; il a aussi coûté de 10 à 35 minutes par verdict.
- **Presque toutes les secondes passes venaient de la consigne**, pas du modèle : une règle non énoncée, une preuve qui ne pouvait pas voir le défaut, un exemple trop étroit. Monter le modèle n'y aurait rien changé.
- **Découper aide** : D3 et G, coupées en un fond et une page, ont avancé en parallèle et sont passées plus vite que les tâches d'un seul bloc.
- **La vérification proportionnée**, décidée en cours de route, a ramené une tâche courante de plus d'une demi-heure à quelques minutes (Ga : trois minutes d'ouvrier, trois de vérification).

## Le temps

Environ sept heures et demie de travail d'agents sur les douze premières tâches : deux heures et demie pour écrire, quatre heures pour vérifier, une heure vingt pour corriger après un verdict.
