#!/usr/bin/env bash
# Installe l'Atelier sur un Mac : il démarre tout seul à l'ouverture de session, en arrière-plan,
# et se consulte dans une fenêtre d'appli ajoutée au Dock depuis Safari.
#
# Dans le Terminal :   bash installer-mac.sh   (depuis le dossier où se trouve ce fichier)
# Lancé seul, il télécharge l'Atelier dans ~/Atelier-appli ; lancé depuis le dépôt, il l'utilise.
# Pour tout retirer ensuite :                   ./outils/desinstaller-mac.sh
#
# Tout s'installe dans ton dossier personnel, sans sudo : uv (installeur officiel, si tu ne l'as pas
# déjà), puis la bibliothèque claude-agent-sdk (dans le dossier .venv de l'Atelier, via uv).
# Le tableau de bord n'écoute que ton Mac (127.0.0.1) : il n'est pas visible depuis le réseau.

set -euo pipefail

DEPOT="$(cd "$(dirname "$0")/.." && pwd)"
ETIQUETTE="fr.atelier.serveur"
PORT="${ATELIER_PORT:-8765}"
# ATELIER_ESSAI=<dossier> : essai à blanc, tout est écrit dans ce dossier et rien n'est lancé.
ESSAI="${ATELIER_ESSAI:-}"
MAISON="${ESSAI:-${HOME}}"

dire() { printf '\n%s\n' "$*"; }
arreter() { printf '\nInstallation interrompue : %s\n' "$*" >&2; exit 1; }
xml() { sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g' <<<"$1"; }

if [ -z "${ESSAI}" ] && [ "$(uname)" != "Darwin" ]; then
  arreter "ce script est fait pour macOS."
fi

# 0. Lancé seul (par exemple depuis Téléchargements) : on récupère d'abord l'Atelier, puis on
#    relance la copie qui se trouve dans le dépôt. Un dépôt déjà présent est simplement mis à jour.
if [ ! -f "${DEPOT}/atelier/__main__.py" ]; then
  DESTINATION="${ATELIER_DOSSIER:-${HOME}/Atelier-appli}"
  command -v git >/dev/null || arreter "git est introuvable. Installe les outils de développement d'Apple (xcode-select --install)."
  if [ -d "${DESTINATION}/.git" ]; then
    dire "Mise à jour de l'Atelier dans ${DESTINATION}…"
    git -C "${DESTINATION}" pull --ff-only --quiet || arreter "la mise à jour de ${DESTINATION} a échoué."
  else
    dire "Téléchargement de l'Atelier dans ${DESTINATION}…"
    git clone --quiet https://github.com/adminamacoustique13/atelier.git "${DESTINATION}" \
      || arreter "le téléchargement de l'Atelier a échoué."
  fi
  exec bash "${DESTINATION}/outils/installer-mac.sh" ${1+"$@"}
fi

# 1. La commande « claude » n'est pas ce qui fait travailler les agents : la bibliothèque
#    claude-agent-sdk (étape 4) embarque son propre Claude Code. Elle sert à te connecter à ton
#    abonnement Claude (lance « claude » dans le Terminal, une fois). Son absence n'arrête rien :
#    on prévient seulement, car sans connexion (ni clé API) les agents ne pourront pas travailler.
CLAUDE="$(command -v claude || true)"
if [ -z "${CLAUDE}" ]; then
  dire "La commande « claude » est introuvable. Ce n'est pas bloquant : l'Atelier embarque son propre Claude Code."
  dire "Elle te sert à te connecter à ton abonnement Claude. Installe-la (https://claude.com/claude-code), puis lance « claude » une fois pour te connecter à ton compte."
fi

# 2. uv apporte la bonne version de Python (3.10 ou plus récente), sans toucher à celle du Mac.
UV="$(command -v uv || true)"
[ -n "${UV}" ] || { [ -x "${HOME}/.local/bin/uv" ] && UV="${HOME}/.local/bin/uv"; } || true
if [ -z "${UV}" ]; then
  dire "Installation de uv avec l'installeur officiel (dans ton dossier personnel), qui fournira Python à l'Atelier…"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  UV="$(command -v uv || echo "${HOME}/.local/bin/uv")"
  [ -x "${UV}" ] || arreter "uv n'a pas pu être installé."
  dire "uv a été installé dans ${UV}."
else
  dire "uv trouvé : ${UV}."
fi

# 3. Le dossier où l'Atelier rangera les projets.
DEFAUT="${HOME}/Atelier"

# Un chemin glissé depuis le Finder arrive avec des « \ » devant les espaces et un espace final.
nettoyer() {
  local c
  c="$(printf '%s' "$1" | sed -e 's/\\\(.\)/\1/g')"
  c="${c#"${c%%[![:space:]]*}"}"
  c="${c%"${c##*[![:space:]]}"}"
  case "${c}" in
    \"*\" | \'*\') c="${c:1:${#c}-2}" ;;
  esac
  c="${c/#\~/${HOME}}"
  printf '%s' "${c}"
}

# Les dossiers que macOS protège (un programme lancé en arrière-plan n'a pas le droit d'y lire)
# et ceux qu'un service de synchronisation surveille ne conviennent pas.
probleme_de() {
  case "$1/" in
    "${HOME}/Documents/"* | "${HOME}/Desktop/"* | "${HOME}/Downloads/"*)
      echo "macOS interdit à un programme lancé en arrière-plan de lire Documents, Bureau et Téléchargements." ;;
    "${HOME}/Library/Mobile Documents/"* | "${HOME}/Library/CloudStorage/"* | *Dropbox* | *kDrive*)
      echo "ce dossier est synchronisé, et la synchronisation abîme les dépôts git." ;;
  esac
}

RACINE="$(nettoyer "${ATELIER_RACINE:-}")"
while [ -z "${ATELIER_RACINE:-}" ]; do
  printf '\nDans quel dossier l'"'"'Atelier doit-il ranger tes projets ?\n'
  printf 'Tape son chemin, glisse-le ici depuis le Finder, ou appuie sur Entrée pour garder le choix proposé.\n'
  printf 'À éviter : Documents, Bureau, Téléchargements, iCloud, Dropbox et kDrive.\n'
  REPONSE=""
  read -r -p "Dossier [${DEFAUT}] : " REPONSE </dev/tty || true
  RACINE="$(nettoyer "${REPONSE}")"
  RACINE="${RACINE:-${DEFAUT}}"
  PROBLEME="$(probleme_de "${RACINE}")"
  [ -z "${PROBLEME}" ] && break
  printf '\nCe dossier ne convient pas : %s\nChoisis-en un autre, par exemple %s.\n' "${PROBLEME}" "${DEFAUT}"
done
RACINE="${RACINE:-${DEFAUT}}"
mkdir -p "${RACINE}"
RACINE="$(cd "${RACINE}" && pwd)"

# 4. Préparer Python et la bibliothèque claude-agent-sdk (déclarée dans pyproject.toml). uv les
#    installe dans le dossier .venv de l'Atelier, donc chez toi, sans sudo. L'agent de lancement
#    passe lui aussi par « uv run », qui remet cette installation à jour au démarrage : une mise
#    à jour de l'Atelier qui change la dépendance est donc reprise sans rien refaire ici. Le fichier
#    uv.lock, versionné avec l'Atelier, fixe la version exacte de la bibliothèque (testée) ; « uv sync »
#    et « uv run » le lisent par défaut.
dire "Préparation de Python et de la bibliothèque claude-agent-sdk…"
if [ -z "${ESSAI}" ]; then
  (cd "${DEPOT}" && "${UV}" sync --quiet) \
    || arreter "uv n'a pas pu installer les dépendances de l'Atelier. Internet est-il coupé ? Si uv est ancien, mets-le à jour avec « uv self update », ou avec « brew upgrade uv » s'il a été installé par Homebrew, puis relance ce script."
  (cd "${DEPOT}" && "${UV}" run --quiet python -c "import sys, claude_agent_sdk; assert sys.version_info >= (3, 10)") \
    || arreter "Python 3.10 ou plus récent, ou la bibliothèque claude-agent-sdk, n'a pas pu être préparé."
fi

# 5. Un port libre pour le tableau de bord. On arrête d'abord une version précédente de l'Atelier,
#    puis on cherche à partir de 8765 un port qu'aucun autre programme n'occupe.
if [ -z "${ESSAI}" ]; then
  launchctl bootout "gui/$(id -u)/${ETIQUETTE}" 2>/dev/null || true
  sleep 1
fi
if [ -z "${ATELIER_PORT:-}" ] && command -v lsof >/dev/null; then
  while lsof -nP -iTCP:"${PORT}" -sTCP:LISTEN >/dev/null 2>&1; do
    OCCUPANT="$(lsof -nP -iTCP:"${PORT}" -sTCP:LISTEN 2>/dev/null | awk 'NR==2 {print $1}')"
    printf 'Le port %s est déjà pris par « %s » : essai du suivant.\n' "${PORT}" "${OCCUPANT:-un autre programme}"
    PORT=$((PORT + 1))
    [ "${PORT}" -le 8800 ] || arreter "aucun port libre entre 8765 et 8800."
  done
fi
ADRESSE="http://127.0.0.1:${PORT}"

# 6. L'agent de lancement : macOS démarre l'Atelier à l'ouverture de session et le relance s'il s'arrête.
PLIST="${MAISON}/Library/LaunchAgents/${ETIQUETTE}.plist"
JOURNAL="${MAISON}/Library/Logs/Atelier.log"
mkdir -p "$(dirname "${PLIST}")" "$(dirname "${JOURNAL}")"
# launchd démarre avec un PATH minimal : on lui donne celui où se trouvent git et uv.
CHEMIN="$(dirname "${UV}"):/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

cat >"${PLIST}" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${ETIQUETTE}</string>
  <key>ProgramArguments</key>
  <array>
    <string>$(xml "${UV}")</string>
    <string>run</string>
    <string>--quiet</string>
    <string>python</string>
    <string>-m</string>
    <string>atelier</string>
    <string>servir</string>
    <string>--racine</string>
    <string>$(xml "${RACINE}")</string>
    <string>--port</string>
    <string>${PORT}</string>
  </array>
  <key>WorkingDirectory</key>
  <string>$(xml "${DEPOT}")</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>$(xml "${CHEMIN}")</string>
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
  <string>$(xml "${JOURNAL}")</string>
  <key>StandardErrorPath</key>
  <string>$(xml "${JOURNAL}")</string>
</dict>
</plist>
EOF

if [ -n "${ESSAI}" ]; then
  dire "Essai à blanc terminé : ${PLIST}"
  exit 0
fi

plutil -lint "${PLIST}" >/dev/null || arreter "le fichier de lancement est invalide (${PLIST})."
launchctl bootstrap "gui/$(id -u)" "${PLIST}"

# 7. Attendre que le tableau de bord réponde, puis l'ouvrir dans Safari.
dire "Démarrage de l'Atelier…"
# Le premier démarrage peut prendre un peu de temps : uv prépare Python.
for _ in $(seq 1 120); do
  curl -fs --max-time 2 "${ADRESSE}/api/etat" >/dev/null 2>&1 && break
  sleep 0.5
done
if ! curl -fs --max-time 2 "${ADRESSE}/api/etat" >/dev/null 2>&1; then
  printf '
Voici la fin du journal (%s) :

' "${JOURNAL}"
  tail -n 25 "${JOURNAL}" 2>/dev/null || printf '(journal vide)
'
  arreter "l'Atelier ne répond pas. Envoie ces lignes à Claude."
fi

open -a Safari "${ADRESSE}"

cat <<EOF

L'Atelier tourne, et redémarrera tout seul à chaque ouverture de session.
Les projets seront rangés dans : ${RACINE}

Dernière étape, pour avoir l'icône dans le Dock :
  dans la fenêtre Safari qui vient de s'ouvrir, menu Fichier, puis « Ajouter au Dock ».
L'Atelier aura alors sa propre icône et sa propre fenêtre, comme une appli.

En cas de souci, le journal est ici : ${JOURNAL}
EOF
