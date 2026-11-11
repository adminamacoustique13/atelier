# Relais Ga — La mise à jour d'Atelier, côté fond

## 1. Fait

Tous les tests sont dans `tests/test_mise_a_jour.py` (27 tests, environ 2 s, dépôts nus et clones dans des dossiers temporaires, aucun accès au réseau).

1. **Critère 1** (une interrogation par heure au plus) : `test_entre_deux_interrogations_aucun_acces_et_meme_reponse` (fausse horloge : à 3599 s aucune commande git, à 3600 s une nouvelle interrogation), `test_premier_appel_interroge_tout_de_suite`, `test_deux_appels_simultanes_ne_lancent_qu_une_interrogation`, `test_verifier_n_ecrit_rien_dans_le_dossier`. « A avancé » : `test_disponible_quand_...`, `test_dossier_en_avance_...` (pas de mise à jour), `test_histoire_divergente_compte_...`.
2. **Critère 2** (pull et phrase de résultat) : `test_mise_a_jour_reussie`, `test_rien_a_tirer_ne_demande_pas_de_redemarrer`, et les tests d'échec du critère 5.
3. **Critère 3** (agent au travail) : `test_agent_au_travail_rien_n_est_lance` (`subprocess.run` piégé : rien n'est lancé).
4. **Critère 4** : `test_refus_hors_de_la_branche_main`, `test_refus_en_tete_detachee`, `test_refus_avec_modifications_locales_de_fichiers_suivis`, `test_un_fichier_non_suivi_ne_bloque_pas`.
5. **Critère 5** : `test_histoire_divergee_laisse_le_dossier_intact`, `test_depot_en_ligne_introuvable_...`, `test_reseau_coupe_...` (adresse locale fermée, avec identifiant factice absent du journal). Avant/après comparés : commit courant, branche, contenu des fichiers (et `git status` propre pour la divergence).
6. **Critère 6** : `test_double_simule_annonce_une_mise_a_jour_et_reussit_sans_git` (`subprocess.run` et `_git` piégés).
7. **Critère 7** : `test_chaque_appel_git_est_borne_sans_shell_ni_saisie` (liste d'arguments, pas de shell, délai borné, `stdin` fermé, `GIT_TERMINAL_PROMPT=0`, `GIT_EDITOR=true`), `test_git_qui_ne_repond_pas_est_coupe`.
8. Contrats : `test_verifier_ne_leve_jamais`, `test_mettre_a_jour_ne_leve_jamais`, `test_dossier_qui_n_est_pas_un_depot`, `test_apres_une_mise_a_jour_reussie_plus_rien_de_disponible`, `test_depot_injoignable_...`, `test_echec_garde_la_disponibilite_precedente_et_ne_reessaie_pas`.

## 2. Fichiers touchés
`atelier/mise_a_jour.py` (nouveau), `tests/test_mise_a_jour.py` (nouveau), `chantier/relais/Ga.md`.

## 3. Contrats modifiés
Interface livrée, conforme à la proposition, avec un champ en plus :
```python
from atelier.mise_a_jour import MiseAJour, MiseAJourSimulee, Etat, Resultat
MiseAJour(dossier, intervalle_s=3600, horloge=time.monotonic)
.verifier() -> Etat(disponible: bool, phrase: str, verifie: bool)
.mettre_a_jour(agent_au_travail: bool) -> Resultat(fait: bool, phrase: str, detail: str = "")
```
`detail` : sortie brute de git (anglais, adresses nettoyées de leur identifiant, 500 caractères au plus), pour le journal seulement. `MiseAJourSimulee()` : mêmes deux méthodes.

Précisions de comportement :
- `verifier` utilise `git ls-remote origin refs/heads/main` puis deux commandes locales en lecture seule ; rien n'est écrit. Si un autre fil interroge déjà, `verifier` rend sans attendre la réponse connue. Le premier appel interroge tout de suite ; avant toute interrogation réussie, la phrase est « La vérification n'a pas encore eu lieu. » (`verifie` faux).
- `mettre_a_jour` lance `git pull --ff-only` (remote et branche de suivi du dossier). Ordre des refus : agent, branche, modifications. Les fichiers non suivis ne bloquent pas.
- Le double simulé refuse aussi quand un agent travaille (même interface), et annonce toujours une mise à jour disponible, même après sa « mise à jour ».

Phrases possibles (`{cause}` vaut l'une des quatre causes en fin de liste) :
- « La vérification n'a pas encore eu lieu. »
- « Une mise à jour d'Atelier est disponible. »
- « Atelier est à jour. »
- « Impossible de vérifier pour l'instant : {cause}. » (ou « la branche main n'existe pas en ligne »)
- « Mise à jour impossible : un agent travaille. Réessaie quand il aura fini. »
- « Mise à jour impossible : le dossier d'Atelier n'est pas sur la branche main. »
- « Mise à jour impossible : le dossier d'Atelier contient des modifications qui ne viennent pas du dépôt en ligne. »
- « Mise à jour impossible : l'histoire du dossier d'Atelier a divergé de celle du dépôt en ligne. »
- « Mise à jour impossible : {cause}. »
- « Atelier est déjà à jour. » (pull sans changement : `fait` faux)
- « Atelier a été mis à jour. Il va redémarrer. » (`fait` vrai)
- « Mise à jour simulée : rien n'a changé. » (double)
- Causes : « le dépôt en ligne ne répond pas » (réseau, délai) ; « le dépôt en ligne est introuvable » ; « le dépôt en ligne demande un identifiant qu'Atelier n'a pas » ; « git n'a pas pu aller au bout » (autre cas).

## 4. Reste à faire
Gb : brancher sur le serveur, la page et le démarrage ; arrêter le processus quand `fait` est vrai ; appeler `verifier` dans un fil (une interrogation peut durer jusqu'à 60 s par commande git).

## 5. Doutes et demandes
- Le pull met à jour la référence de suivi `origin/main` (fetch) même s'il échoue ensuite ; commit courant, branche et fichiers restent identiques.
- Le dépôt distant est supposé s'appeler `origin` pour la vérification.
- `git pull` suit la configuration `pull.rebase` éventuelle de la personne ; `--ff-only` reste prioritaire en pratique sur git 2.43.
