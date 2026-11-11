#!/usr/bin/env bash
# Arrête l'Atelier et retire son démarrage automatique.
# Tes projets, le dépôt de l'Atelier et uv ne sont pas touchés.
# Pour retirer l'icône du Dock : clic droit dessus, Options, puis « Supprimer du Dock ».

set -uo pipefail

ETIQUETTE="fr.atelier.serveur"
PLIST="${HOME}/Library/LaunchAgents/${ETIQUETTE}.plist"

launchctl bootout "gui/$(id -u)/${ETIQUETTE}" 2>/dev/null || true
if [ -f "${PLIST}" ]; then
  rm "${PLIST}"
  echo "L'Atelier est arrêté et ne démarrera plus tout seul."
else
  echo "Le démarrage automatique de l'Atelier n'était pas installé."
fi
echo "Le journal reste ici, si besoin : ${HOME}/Library/Logs/Atelier.log"
