# Relais D3b : le menu « Mode des ouvriers »

## 1. Fait
Choix de présentation : les cinq choix sont des boutons-pilules compacts sur une ligne ; l'explication du choix en vigueur est dessous, celle d'un autre choix la remplace au survol et au focus clavier (CSS seul, avec `:has()`, donc rien n'est redessiné et le focus ne bouge pas). Chaque bouton est aussi relié à son explication par `aria-describedby`.

1. Menu à cinq choix, onglet Chantier, carte entre la grille du haut et « La salle » : essai « cinq choix, dans l'ordre, avec les libellés du serveur » et « la carte est entre... » ; capture `D3-menu.png`.
2. Choix en vigueur en blanc (`aria-pressed="true"`), explication du serveur dessous, celle des autres au survol et à Tab : essais « en vigueur au départ », « explication affichée », « au survol », « au focus clavier » ; capture `D3-explication.png`.
3. Un clic envoie `{"mode": ...}` (essai pour chacun des quatre autres choix) ; la phrase du serveur s'affiche telle quelle ; le choix en vigueur suit la vue (relue ensuite avec `/api/etat`) ; double clic : une seule requête ; pendant l'envoi le bouton est marqué (`aria-busy`, pulsation) et la phrase « Envoi du mode « X » en cours » s'affiche, l'ancien choix restant en vigueur ; `fait: false`, réponse sans confirmation de la vue, réseau coupé et réponse 500 laissent l'ancien choix, avec une phrase (orange pour un échec) ; capture `D3-changement.png`.
4. `appliques` : une ligne orange par agent, « B-ouvrier-1 travaille en mode « Me demander », pas dans le mode choisi. » ; capture `D3-mode-reel.png`.
5. Sans `mode_ouvriers` (absent, nul, pas un objet, sans `choix`, `choix` vide) ou sans projet : carte cachée, aucune erreur ; un menu déjà affiché disparaît si le projet se ferme.
6. Même style que la page (boutons de 26 px de haut, texte de 12 px, couleurs existantes).
7. LISEZMOI : nouvelle section « Le mode des ouvriers », après « Les autorisations », avec les précisions du coordinateur (répétition : pas « sans rien modifier » ; arbitre : pas « chaque action » ; refus du mode `dontAsk` invisibles dans l'activité). Rien n'est dit d'un bouton « Mettre à jour ».
- Sécurité : tout texte passe par `propre()` ; essai avec agent, mode réel et libellé/explication de choix hostiles.
- Rafraîchissements : essai « deux relectures laissent le même nœud, avec son focus, et l'explication ouverte » (`poser()`). Après un redessin dû à un vrai changement, le focus clavier est rendu au même bouton (pas de cadre de focus après un clic souris).
- Fenêtre de 400 px : aucun débordement ni recoupement (mesuré) ; capture `D3-etroit.png`.
- Page des instantanés : 42 vues, menu visible ; un clic dit « Démonstration rejouée... », n'envoie rien, ne change rien.
- Essai : 82 vérifications, 3 passages de suite verts. Mutations constatées en échec : mauvais mode envoyé (15 échecs), choix affiché sans attendre la vue (1), ligne du mode réel absente (1), nom d'agent non échappé (2) ; page remise ensuite. `D2-tableau.js` : 95 vérifications, captures D2 remises. pytest 599 verts, ruff vert.

## 2. Fichiers touchés
`atelier/tableau/index.html`, `chantier/essais/D3-modes.js`, `chantier/captures/D3-{menu,explication,changement,mode-reel,etroit}.png`, `LISEZMOI.md` (section ajoutée), `chantier/relais/D3b.md`.

## 3. Contrats modifiés (pour la tâche « Mettre à jour »)
- Aucun contrat serveur modifié. La page lit `vue.mode_ouvriers` avec prudence (`modeDe(vue)`) et `changement_mode` dans la réponse de `POST /api/mode`.
- Ids ajoutés : `carte-mode` (la carte, `hidden` sans menu), `mode-ouvriers` (boutons et explications), `mode-ouvriers-etat` (zone `aria-live` : envoi, phrase, lignes du mode réel). Attention : `#mode` existait déjà (pastille « Démonstration »), ne pas le réutiliser. Classes : `.mode-btn`, `.expl`, `.mode-reel`, `.mode-refus`. Action `data-action="mode"`. Règle `.carte[hidden]` ajoutée.
- État JS : `modeEnvoi`, `modePhrase`, `minuteMode` ; fonctions `modeDe`, `modeHtml`, `modeEtatHtml`, `afficherMode`, `choisirMode`. `afficherMode` est appelée par `afficherChantier`.
- La phrase du serveur reste affichée 30 s (ou jusqu'au prochain clic).

## 4. Reste à faire
Rien pour D3b. Essai réel avec un vrai compte : tâche F.

## 5. Doutes et demandes
- Sur écran tactile, le survol n'existe pas : l'explication d'un autre choix n'y est lue qu'après le clic (qui choisit). Si cela gêne, passer à un clic d'aperçu avant validation.
- L'essai compare l'explication affichée à celle de la vue du serveur (lue à l'exécution), pas à un texte écrit en dur : les reformulations de D3a ne le cassent pas.
- Les explications actuelles du serveur pour « Me demander » et « Refuser sans demander » parlent de fichiers modifiés sans carte ; cohérent avec le LISEZMOI.
