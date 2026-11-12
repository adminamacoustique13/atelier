"""Le seul endroit d'où l'Atelier lance git.

L'Atelier tourne sans terminal : git ne doit jamais attendre une réponse au clavier, sinon il
resterait bloqué ou échouerait en silence. `lancer_git` s'en charge une fois pour toutes. Elle
ne décide pas de ce qu'est un échec : elle rend le résultat tel quel, et chaque module traduit
un code d'erreur, un délai dépassé ou un git introuvable dans sa propre convention.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Mapping
from pathlib import Path

# Le nom et l'adresse donnés à un commit quand la machine n'a pas d'identité git réglée.
# Un tuple, et non une liste : partagé entre modules, il ne doit pas pouvoir être modifié.
IDENTITE_DE_REPLI = ("-c", "user.name=Atelier", "-c", "user.email=atelier@localhost")


def lancer_git(
    dossier: Path,
    *arguments: str,
    delai: float | None = None,
    environnement: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Lance `git` avec ces arguments dans ce dossier et rend le résultat tel quel.

    Git est lancé sans shell, avec l'entrée fermée et `GIT_TERMINAL_PROMPT=0`, ce qui lui
    interdit toute question. Les sorties sont capturées en texte. Les variables de
    `environnement` s'ajoutent à celles du processus, mais ne peuvent pas rouvrir les
    questions au terminal. Sans `delai`, git a tout son temps.

    Un code de sortie non nul ne lève rien : il est dans `returncode`, le message dans
    `stderr`. Un délai dépassé lève `subprocess.TimeoutExpired`, un git introuvable ou un
    dossier inaccessible lève `OSError`.
    """
    variables = {**os.environ, **(environnement or {}), "GIT_TERMINAL_PROMPT": "0"}
    return subprocess.run(
        ["git", *arguments],
        cwd=dossier,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        env=variables,
        timeout=delai,
    )
