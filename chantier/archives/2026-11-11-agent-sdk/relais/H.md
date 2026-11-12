# Relais H — Le ménage de l'ancien câblage

## 1. Fait
1. **Critère 1.** `atelier/agents.py` ne contient plus `lire_flux_claude`, `lire_sortie_claude`, `_suivre`, ni le commentaire qui les présentait. Une recherche dans tout le dépôt a montré que seuls les tests en parlaient (le `_suivre` de `atelier/sdk.py` est une méthode du pont, sans rapport). Aucun import ni constante n'est devenu inutile (`json` sert encore à l'agent simulé ; ruff est vert).
2. **Critère 2.** Dans `tests/test_agents.py`, `test_executer_rend_le_resultat_attendu` (3 cas) et `test_converser_rend_le_resultat_attendu` (3 cas) comparent à des `Resultat` littéraux et à `["Bon", "jour"]` / `["Lit a.py"]`. Les mêmes 6 cas, les mêmes assertions ; le second test joue directement le flux du faux client (la fonction `flux_equivalents` et les lignes JSON, qui ne servaient qu'aux anciens lecteurs, sont retirées).
3. **Critère 3.** Les deux tests sont retirés de `tests/test_moteur.py`, avec l'import de `lire_sortie_claude`.

| Règle vérifiée par un test retiré | Test qui la couvre maintenant |
|---|---|
| Résultat en erreur : échec dont l'erreur porte le texte | `tests/test_sdk.py::test_fin_en_erreur` ; `tests/test_agents.py::test_executer_rend_le_resultat_attendu` et `test_converser_rend_le_resultat_attendu` (cas en erreur) |
| Succès : texte, coût, somme des tokens | `tests/test_sdk.py::test_fin_rend_texte_cout_et_tokens` ; `tests/test_agents.py::test_executer_rend_le_resultat_attendu` |
| Tour sans résultat final : échec | `tests/test_sdk.py::test_fin_sans_resultat` et `test_lire_resultat` |
| Texte relayé morceau par morceau | `tests/test_sdk.py::test_texte_relaye_morceau_par_morceau` ; `tests/test_agents.py::test_converser_rend_le_resultat_attendu` |
| Outil relayé sous forme courte (« Lit coeur/calcul.py ») | **nouveau** `tests/test_sdk.py::test_outil_de_lecture_relaye_sous_sa_forme_courte` ; aussi `test_outil_relaye_sous_forme_courte` |
| Message illisible ou inconnu ne casse rien | **nouveau** `tests/test_sdk.py::test_un_message_inconnu_ou_illisible_ne_casse_rien` (objet inconnu, message système autre que l'init, événement sans delta, delta sans texte) |

4. **Critère 4.** Les commentaires de `tests/test_agents.py` ne citent plus `claude -p` ; la docstring de `lire_resultat` dans `atelier/sdk.py` ne cite plus `lire_sortie_claude` (aucune ligne de code touchée). Les tests du critère 6 restent : `test_aucun_processus_n_est_lance_par_les_agents` (ancien `test_plus_aucun_claude_p_n_est_lance`, renommé) et `test_import_des_agents_ne_charge_pas_le_sdk`.

Preuve : `grep -rn "claude -p\|lire_flux_claude\|lire_sortie_claude" atelier/agents.py atelier/sdk.py tests/` ne rend rien (les caches `.pyc` mis à part). Suite complète : 371 tests verts avant, 371 après (deux retirés, deux ajoutés). Ruff vert. Import `atelier.agents, atelier.sdk, atelier.serveur, atelier.__main__` : ok.

## 2. Fichiers touchés
`atelier/agents.py`, `atelier/sdk.py` (une docstring), `tests/test_agents.py`, `tests/test_sdk.py` (deux tests ajoutés), `tests/test_moteur.py` (retrait des deux tests et de l'import seulement), `chantier/relais/H.md`.

## 3. Contrats modifiés
Aucun. `lire_flux_claude` et `lire_sortie_claude` n'étaient plus importés par le produit.

## 4. Reste à faire
Rien dans mon périmètre. `chantier/CAHIER.md` (lignes 247-252) décrit encore les anciens lecteurs comme présents : à tenir à jour par l'orchestrateur.

## 5. Doutes et demandes
Aucun. Docstrings de `agents.py` qui disent « Claude Code piloté par l'Agent SDK » : laissées, elles ne décrivent pas un lancement en ligne de commande.
