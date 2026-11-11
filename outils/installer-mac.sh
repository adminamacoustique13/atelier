#!/usr/bin/env bash
# Installe l'Atelier sur un Mac : il démarre tout seul à l'ouverture de session, en arrière-plan,
# et se consulte dans une fenêtre d'appli ajoutée au Dock depuis Safari.
#
# À lancer depuis le dossier du dépôt cloné :   ./outils/installer-mac.sh
# Pour tout retirer ensuite :                   ./outils/desinstaller-mac.sh
#
# Rien n'est installé hors de ton dossier personnel, à part uv si tu ne l'as pas déjà.
# Le tableau de bord n'écoute que ton Mac (127.0.0.1) : il n'est pas visible depuis le réseau.

set -euo pipefail

DEPOT="$(cd "$(dirname "$0")/.." && pwd)"
ETIQUETTE="fr.atelier.serveur"
PORT="${ATELIER_PORT:-8765}"
ADRESSE="http://127.0.0.1:$PORT"
# ATELIER_ESSAI=<dossier> : essai à blanc, tout est écrit dans ce dossier et rien n'est lancé.
ESSAI="${ATELIER_ESSAI:-}"
MAISON="${ESSAI:-$HOME}"

dire() { printf '\n%s\n' "$*"; }
arreter() { printf '\nInstallation interrompue : %s\n' "$*" >&2; exit 1; }
xml() { sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g' <<<"$1"; }

if [ -z "$ESSAI" ] && [ "$(uname)" != "Darwin" ]; then
  arreter "ce script est fait pour macOS."
fi

# 1. Claude Code doit être installé : c'est lui qui fait travailler les agents.
CLAUDE="$(command -v claude || true)"
[ -n "$CLAUDE" ] || arreter "Claude Code est introuvable. Installe-le et connecte-toi (claude), puis relance ce script."

# 2. uv apporte la bonne version de Python (3.10 ou plus récente), sans toucher à celle du Mac.
UV="$(command -v uv || true)"
[ -n "$UV" ] || { [ -x "$HOME/.local/bin/uv" ] && UV="$HOME/.local/bin/uv"; } || true
if [ -z "$UV" ]; then
  dire "Installation de uv, qui fournira Python à l'Atelier…"
  if command -v brew >/dev/null; then
    brew install uv
  else
    curl -LsSf https://astral.sh/uv/install.sh | sh
  fi
  UV="$(command -v uv || echo "$HOME/.local/bin/uv")"
  [ -x "$UV" ] || arreter "uv n'a pas pu être installé."
fi

# 3. Le dossier où l'Atelier rangera les projets.
DEFAUT="$HOME/Atelier"
RACINE="${ATELIER_RACINE:-}"
if [ -z "$RACINE" ]; then
  printf '\nDans quel dossier l'"'"'Atelier doit-il ranger tes projets ?\n'
  printf 'Évite Dropbox, kDrive ou iCloud : la synchronisation abîme les dépôts git.\n'
  read -r -p "Dossier [$DEFAUT] : " RACINE </dev/tty || true
fi
RACINE="${RACINE:-$DEFAUT}"
RACINE="${RACINE/#\~/$HOME}"
mkdir -p "$RACINE"
RACINE="$(cd "$RACINE" && pwd)"

# 4. Préparer Python pour l'Atelier (télécharge la bonne version au besoin).
dire "Préparation de Python…"
if [ -z "$ESSAI" ]; then
  (cd "$DEPOT" && "$UV" run --quiet python -c "import sys; assert sys.version_info >= (3, 10)") \
    || arreter "Python 3.10 ou plus récent n'a pas pu être préparé."
fi

# 5. L'agent de lancement : macOS démarre l'Atelier à l'ouverture de session et le relance s'il s'arrête.
PLIST="$MAISON/Library/LaunchAgents/$ETIQUETTE.plist"
JOURNAL="$MAISON/Library/Logs/Atelier.log"
mkdir -p "$(dirname "$PLIST")" "$(dirname "$JOURNAL")"
# launchd démarre avec un PATH minimal : on lui donne celui où se trouvent claude, git et uv.
CHEMIN="$(dirname "$CLAUDE"):$(dirname "$UV"):/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

cat >"$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$ETIQUETTE</string>
  <key>ProgramArguments</key>
  <array>
    <string>$(xml "$UV")</string>
    <string>run</string>
    <string>--quiet</string>
    <string>python</string>
    <string>-m</string>
    <string>atelier</string>
    <string>servir</string>
    <string>--racine</string>
    <string>$(xml "$RACINE")</string>
    <string>--port</string>
    <string>$PORT</string>
  </array>
  <key>WorkingDirectory</key>
  <string>$(xml "$DEPOT")</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>$(xml "$CHEMIN")</string>
    <key>LANG</key>
    <string>fr_FR.UTF-8</string>
    <key>PYTHONUNBUFFERED</key>
    <string>1</string>
  </dict>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>ProcessType</key>
  <string>Interactive</string>
  <key>StandardOutPath</key>
  <string>$(xml "$JOURNAL")</string>
  <key>StandardErrorPath</key>
  <string>$(xml "$JOURNAL")</string>
</dict>
</plist>
EOF

if [ -n "$ESSAI" ]; then
  dire "Essai à blanc terminé : $PLIST"
  exit 0
fi

plutil -lint "$PLIST" >/dev/null || arreter "le fichier de lancement est invalide ($PLIST)."
launchctl bootout "gui/$(id -u)/$ETIQUETTE" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"

# 6. Attendre que le tableau de bord réponde, puis l'ouvrir dans Safari.
dire "Démarrage de l'Atelier…"
for _ in $(seq 1 60); do
  curl -fs "$ADRESSE/api/etat" >/dev/null 2>&1 && break
  sleep 0.5
done
curl -fs "$ADRESSE/api/etat" >/dev/null 2>&1 \
  || arreter "l'Atelier ne répond pas. Le journal est ici : $JOURNAL"

open -a Safari "$ADRESSE"

cat <<EOF

L'Atelier tourne, et redémarrera tout seul à chaque ouverture de session.
Les projets seront rangés dans : $RACINE

Dernière étape, pour avoir l'icône dans le Dock :
  dans la fenêtre Safari qui vient de s'ouvrir, menu Fichier, puis « Ajouter au Dock ».
L'Atelier aura alors sa propre icône et sa propre fenêtre, comme une appli.

En cas de souci, le journal est ici : $JOURNAL
EOF
