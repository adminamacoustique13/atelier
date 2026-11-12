# Installer l'Atelier sur un PC

L'Atelier a été écrit et installé sur Mac. Le script d'installation (`outils/installer-mac.sh`) ne marche que sur macOS. Sur un PC, il faut le lancer à la main : cinq commandes, décrites ici.

À savoir avant de commencer :

- **Rien n'a été essayé sur un PC.** Tous les tests ont tourné sous Linux. La première voie ci-dessous (WSL) est celle qui s'en rapproche le plus.
- **Il te faut ton propre compte Claude**, avec Claude Code installé et connecté. L'Atelier utilise ta connexion, et c'est ton abonnement qui est compté.
- **Commence par la démonstration** (étape 4) : elle ne se connecte à rien et ne coûte rien.

## Quelle voie choisir

L'Atelier doit tourner au même endroit que ton Claude Code, parce qu'il reprend sa connexion.

- Ton Claude Code tourne dans **WSL** (un terminal Ubuntu sur ton PC) : suis la voie A. C'est la voie recommandée.
- Ton Claude Code tourne **directement sous Windows** (PowerShell) : suis la voie B.

Pour le savoir : ouvre le terminal où tu lances d'habitude `claude`. Si c'est Ubuntu ou un autre Linux, c'est WSL.

## Voie A : dans WSL (recommandée)

Dans ton terminal Ubuntu :

1. **Installe git et uv**, si tu ne les as pas. uv fournit Python et installe la bibliothèque dont l'Atelier a besoin.

   ```
   sudo apt update && sudo apt install -y git curl
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

   Ferme puis rouvre le terminal, pour que la commande `uv` soit reconnue.

2. **Vérifie ta connexion à Claude** : lance `claude`, tape `/status`, puis quitte.

3. **Déplie le fichier `atelier.bundle`** que tu as reçu. Remplace le chemin par l'endroit où il se trouve ; le dossier Téléchargements de Windows se lit depuis WSL sous `/mnt/c/Users/<ton nom>/Downloads`.

   ```
   git clone /mnt/c/Users/<ton nom>/Downloads/atelier.bundle ~/atelier
   cd ~/atelier
   uv sync
   ```

   `uv sync` installe la bibliothèque `claude-agent-sdk` dans le dossier `.venv` de l'Atelier. Rien n'est installé ailleurs.

4. **Lance la démonstration** :

   ```
   uv run python -m atelier demo
   ```

   Puis ouvre http://127.0.0.1:8765 dans ton navigateur Windows. Les agents sont simulés : tu peux tout essayer, les cartes d'autorisation, les boutons « Arrêter », le menu des modes. Pour arrêter : Ctrl+C dans le terminal.

5. **Lance l'Atelier pour de vrai**, sur un dépôt git sans importance pour commencer :

   ```
   uv run python -m atelier servir --depot /chemin/de/ton/depot
   ```

   Ou, pour créer tes projets depuis le tableau de bord, dans un dossier de ton choix :

   ```
   uv run python -m atelier servir --racine ~/projets
   ```

## Voie B : directement sous Windows

Dans PowerShell :

1. **Installe git** (https://git-scm.com/download/win) et **uv** :

   ```
   powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
   ```

   Ferme puis rouvre PowerShell.

2. **Vérifie ta connexion à Claude** : lance `claude`, tape `/status`, puis quitte.

3. **Déplie le fichier** :

   ```
   git clone $HOME\Downloads\atelier.bundle $HOME\atelier
   cd $HOME\atelier
   uv sync
   ```

4. **Lance la démonstration**, puis l'Atelier, comme aux étapes 4 et 5 de la voie A, avec des chemins Windows :

   ```
   uv run python -m atelier demo
   uv run python -m atelier servir --depot C:\chemin\de\ton\depot
   ```

Cette voie est la moins sûre : les commandes que l'Atelier permet d'avance aux agents (`python3`, `npm`, `uv`...) portent leurs noms Linux et Mac, et la préparation des copies de travail par git n'a jamais tourné sous Windows. Si la démonstration marche mais que les vrais agents butent, passe par WSL.

## Ce que tu dois regarder au premier lancement réel

- **Ce qui est facturé.** Le fil commence par dire s'il voit une variable `ANTHROPIC_API_KEY`. Après ton premier message à l'orchestrateur, il doit ajouter : « Le SDK de Claude annonce qu'aucune clé API n'est utilisée : le travail est compté sur ton abonnement Claude. » S'il parle d'une clé API, arrête-toi : une clé serait facturée à la place de ton abonnement.
- **Les cartes d'autorisation.** Quand un agent veut lancer une commande qui n'est pas permise d'avance, une carte orange te le demande. « Toujours pour ce projet » retient une règle large : la carte te montre laquelle avant ton clic.

Le fichier `LISEZMOI.md` explique le reste : le contrat, les quatre onglets (dont la carte du code), les autorisations, le mode des ouvriers.

## Ce qui n'existe pas sur PC

- **Pas de démarrage automatique** ni d'icône : tu relances la commande `servir` quand tu veux t'en servir, et tu gardes le terminal ouvert.
- **Le bouton « Mettre à jour »** ne te servira pas : il compare ton dossier au fichier `atelier.bundle`, pas au dépôt en ligne. Pour passer à une version plus récente, demande un nouveau fichier, puis :

  ```
  cd ~/atelier
  git pull /chemin/du/nouveau/atelier.bundle main
  uv sync
  ```

## Pour tout retirer

Supprime le dossier `atelier` (`rm -rf ~/atelier` dans WSL). Tes projets ne sont pas touchés.
