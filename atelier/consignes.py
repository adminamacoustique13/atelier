"""Les consignes : le seul canal par lequel un agent reçoit quoi que ce soit."""

from __future__ import annotations

import json

from atelier.controles import (
    MARQUEURS,
    SUPPRIME_PAR_LA_TACHE,
    SUPPRIME_SUR_LA_PRINCIPALE,
    fichiers_partages,
    motif_partage,
)
from atelier.modele import Contrat, Tache

# Le tableau de bord affiche la dernière ligne de cette forme : la personne responsable voit
# où en est l'agent sans lire tout son fil.
SUIVI = """## Suivi
Avant chaque étape de ton travail, écris sur une ligne à part : « Étape 2/5 : ce que tu \
vas faire », en quelques mots simples (le rang et le total sont une estimation, ajuste-les \
en route). La personne qui suit le chantier lit ces lignes pour savoir où tu en es.
"""


# Une demande d'autorisation bloque l'agent et sa place jusqu'à ce que la personne réponde :
# l'ouvrier et le vérificateur reçoivent donc la même règle, écrite une seule fois ici.
COMMANDES_SIMPLES = """une commande simple par appel : pas de commandes enchaînées (`;`, `&&`, \
plusieurs lignes), pas de heredoc (`<<EOF`), pas de variable du shell (`$?`, `$(...)` : le code \
de retour de la commande t'est déjà donné), pas de `sed -i` ni de `rm -rf`, pas de dossier \
temporaire ailleurs (`mktemp`, `/tmp`). Claude Code ne sait pas découper ces commandes-là \
sans risque : chacune demanderait une autorisation à la personne qui suit le chantier, et \
la ferait attendre."""


# Le signe qu'un agent met au début d'une ligne quand une commande lui est refusée ou qu'un outil
# lui manque. Le moteur le cherche tel quel et en début de ligne seulement, pour ne pas prendre
# une sortie de test citée pour un empêchement (`refus.MARQUE_EMPECHEMENT` : le même texte).
MARQUE_EMPECHE = "EMPÊCHÉ :"

# Comment écrire ce signe : l'ouvrier et les trois vérifications reçoivent la même phrase.
_LIGNE_EMPECHE = f"""Cette ligne commence par « {MARQUE_EMPECHE} », au tout début de la ligne, \
sans tiret ni puce devant, suivie de la commande et du message reçu, tel quel. Par exemple :
{MARQUE_EMPECHE} uv run pytest -q — (le message reçu)"""


def _si_empeche(ou: str, but: str = "d'aller au bout de la tâche") -> str:
    """Quand écrire le signe d'empêchement, dans les mêmes mots pour l'ouvrier, sa reprise et le
    vérificateur : un refus dont le travail n'a pas besoin ne doit pas bloquer la tâche (cahier,
    « V3b »). `ou` : où l'agent l'écrit ; `but` : ce que le refus empêcherait."""
    return (
        "Si une commande refusée ou un outil qui manque (commande non permise, programme absent, "
        f"réseau coupé) t'empêche {but}, écris-le dans {ou} par une ligne « {MARQUE_EMPECHE} » ; "
        "sinon fais sans, et dis-le au même endroit, sans cette ligne."
    )


EMPECHE_OUVRIER = f"""## Si tu es empêché
{_si_empeche("ton compte rendu final (rubrique Doutes et demandes)")} {_LIGNE_EMPECHE}
L'Atelier lit ces lignes : il demande alors à la personne le bon réglage (permettre la commande, \
installer l'outil) au lieu de relancer ta tâche à l'aveugle, ce qui buterait au même endroit. \
Une autre commande permise qui fait le même travail reste bienvenue ; mais ne fais pas passer la \
commande refusée sous une autre forme (un autre shell, un script qui la lance) : la liste des \
commandes permises est un choix de la personne.
"""

EMPECHE_VERIFICATEUR = f"""## Si tu es empêché
{_si_empeche("ton verdict", "de vérifier un critère")} {_LIGNE_EMPECHE}
Reporte aussi ce que dit cette ligne dans le champ "empeche" du JSON. Sans ce signe, l'Atelier \
prendrait ton refus pour un défaut du livrable et relancerait l'agent pour rien : la vérification \
suivante buterait au même endroit. Avec lui, il demande à la personne le bon réglage."""


def _liste(elements: list[str]) -> str:
    return "\n".join(f"{i}. {e}" for i, e in enumerate(elements, 1)) or "(aucun)"


def _commandes(profil: dict) -> str:
    return "\n".join(f"- `{c}`" for c in profil.get("commandes", [])) or "- (aucune)"


# Ce que l'ouvrier doit savoir d'un fichier partagé de son périmètre, selon sa fusion.
REGLES_DE_FUSION = {
    "union": "fusion « union » : ajoute seulement des lignes, sans modifier ni retirer aucune "
    "ligne existante. À la fusion, une ligne modifiée des deux côtés garderait ses deux versions.",
    "git": "fusion « git » : change le moins de lignes possible ; en cas de conflit, l'atelier te "
    "rendra la main pour le résoudre.",
}


def _partages_du_perimetre(tache: Tache, profil: dict) -> str:
    """Les fichiers partagés du périmètre, chacun avec la règle de sa fusion ; "" s'il n'y en a
    pas."""
    partages = fichiers_partages(profil)
    lignes = []
    for entree in tache.perimetre:
        motif = motif_partage(entree, partages)
        if motif:
            lignes.append(f"- `{entree}` : {REGLES_DE_FUSION[partages[motif]]}")
    if not lignes:
        return ""
    return (
        "\n\nFichiers partagés : d'autres tâches peuvent les modifier en même temps que toi, et "
        "l'atelier réunit vos changements à l'enregistrement.\n" + "\n".join(lignes)
    )


def consigne_ouvrier(tache: Tache, contrat: Contrat, profil: dict, remarques: str = "") -> str:
    """Rédige la consigne d'un ouvrier : tâche, pourquoi, critères, périmètre, interdits."""
    regles = "\n".join(f"- {r}" for r in profil.get("regles", [])) or "- (aucune règle propre)"
    zones = "\n".join(f"- {z}" for z in contrat.zones_rouges)
    reprise = ""
    if remarques:
        reprise = (
            "\n## Tentative précédente\n"
            "Une tentative précédente a été refusée. Tu repars d'un état propre. "
            f"Voici ce qui a été relevé :\n{remarques}\n"
        )
    return f"""Tu es un agent de développement. Tu travailles dans le dossier courant.

## Tâche {tache.id} — {tache.titre}

## Pourquoi
{tache.pourquoi or contrat.objectif}

## Critères
{_liste(tache.criteres)}

## Ton périmètre
Tu peux créer et modifier uniquement :
{chr(10).join(f"- `{p}`" for p in tache.perimetre)}{_partages_du_perimetre(tache, profil)}

## Contrats
Tu fournis : {tache.fournit or "rien de particulier"}
Tu peux attendre : {tache.attend or "rien"}

## Règles du projet
{regles}

Si une règle du projet te demande de toucher un fichier hors de ton périmètre (une ligne au \
journal des décisions, par exemple), ne le touche pas : écris dans ta fiche de relais ce que tu \
y aurais mis. Le contrôle du périmètre refuserait ton travail, et les tâches qui travaillent en \
même temps que toi se heurteraient dans ce fichier commun ; la tâche de raccord recopiera ta ligne.

Commandes de contrôle, à faire passer avant de rendre ton travail :
{_commandes(profil)}
{reprise}
{SUIVI}
## Ta fiche de relais
`chantier/relais/{tache.id}.md` est toujours permis, en plus de ton périmètre, et entre dans la \
branche principale avec ton travail : les tâches suivantes et la tâche de raccord le lisent. \
Écris-y ce qu'une tâche qui prend ta suite doit savoir, et ce qu'une règle du projet t'aurait \
fait écrire hors de ton périmètre. Si tu n'as rien à transmettre, ne la crée pas. Si elle existe \
déjà quand tu commences, elle vient d'un chantier précédent : remplace son contenu, l'ancien \
reste dans l'historique de git.

## Interdits
- Rien hors de ton périmètre. Si tu penses en avoir besoin, arrête-toi et dis-le \
dans ton compte rendu.
- Aucun commit et aucune commande git qui modifie le dépôt : l'atelier enregistre \
après vérification.
- Les zones rouges :
{zones}

## Outils
Tu peux installer librement un outil de travail (test, contrôle de forme, lecture de \
documents), depuis une source officielle (pip, npm, crates.io, le dépôt de l'éditeur). \
Jamais de script téléchargé depuis un site inconnu exécuté directement. Signale dans ton \
compte rendu chaque outil installé et chaque bibliothèque ajoutée au produit, avec sa licence.
Pour tes commandes, {COMMANDES_SIMPLES} Pour modifier un fichier, sers-toi des outils Edit \
et Write.

{EMPECHE_OUVRIER}
## À rendre
Termine par un compte rendu en cinq rubriques courtes : Fait (critère par critère), \
Fichiers touchés, Contrats modifiés, Reste à faire, Doutes et demandes.
"""


# Ce que dit la reprise selon ce qui a refusé le livrable : le constat, puis ce qu'il faut faire.
REPRISES = {
    "verdict": (
        "Le vérificateur a refusé ton livrable. Voici son verdict en entier",
        "Corrige chaque point qu'il recale. Un vérificateur neuf contrôlera ensuite ces points, "
        "et vérifiera que tes corrections n'ont rien défait ; il ne refera pas le reste.",
    ),
    "perimetre": (
        "Le contrôle du périmètre a refusé ton livrable : tu as modifié des fichiers qui n'en "
        "font pas partie",
        "Défais tes changements dans ces fichiers avec l'outil Edit (ou Write) : relis le fichier, "
        "remets-le tel qu'il était, et pour un fichier que tu as créé, vide-le ou dis-le dans ton "
        "compte rendu s'il faut le supprimer. N'emploie aucune commande git pour cela "
        "(`git checkout`, `git restore`) : elle ouvrirait une carte d'autorisation et pourrait "
        "défaire plus que ce que tu veux. Un fichier hors de ton périmètre fait "
        "refuser le livrable quoi qu'il contienne. Si une règle du projet te demandait d'y "
        "écrire, mets plutôt dans ta fiche de relais ce que tu y aurais mis ; si la tâche en a "
        "vraiment besoin, dis-le dans ton compte rendu.",
    ),
    "controles": (
        "Les commandes de contrôle du projet échouent sur ton livrable. Voici la fin de leur "
        "sortie",
        "Trouve ce qui les fait échouer et corrige-le.",
    ),
    "integration": (
        "Ton livrable était accepté, mais d'autres tâches sont entrées entre-temps dans la "
        "branche principale et ont modifié les mêmes fichiers que toi. Ta copie est maintenant "
        "posée sur la branche principale actuelle, avec ton travail par-dessus ; git n'a pas pu "
        "réunir les deux versions de ces fichiers",
        "Dans chaque fichier à marqueurs de conflit, résous chaque conflit avec l'outil Edit : "
        "entre « <<<<<<< » et « ======= », ta version ; entre « ======= » et « >>>>>>> », celle "
        "de la branche principale. Garde les deux intentions : réunis-les en un seul texte qui "
        "fait ce que chacune voulait, puis retire les trois lignes de marqueurs. Un fichier "
        "supprimé d'un côté n'a pas de marqueurs : fais ce que la liste dit pour lui. Ne choisis "
        "pas un côté en jetant l'autre, et n'emploie aucune commande git : l'Atelier enregistre "
        "après vérification. Il refuse le livrable s'il reste des marqueurs.",
    ),
}

# Ce que la liste des fichiers en conflit dit de chacun, selon sa nature (`poser_conflits`).
CONFLITS_EN_CLAIR = {
    MARQUEURS: "",
    SUPPRIME_SUR_LA_PRINCIPALE: " : supprimé sur la branche principale, alors que tu l'avais "
    "modifié. Garde la suppression : supprime ce fichier de ta copie et ne le fais pas revivre "
    "ailleurs ; dis dans ton compte rendu ce que ta modification apportait.",
    SUPPRIME_PAR_LA_TACHE: " : modifié sur la branche principale, alors que tu l'avais supprimé. "
    "Ta copie a gardé la version de la branche principale : garde-la, ne le supprime pas de "
    "nouveau.",
}


def conflits_en_clair(conflits: dict[str, str]) -> str:
    """La liste des fichiers en conflit (chemin -> nature), un par ligne, avec ce qu'il faut
    faire d'un fichier supprimé d'un côté."""
    return "\n".join(
        f"- `{chemin}`{CONFLITS_EN_CLAIR.get(nature, '')}" for chemin, nature in conflits.items()
    )


def consigne_reprise(
    tache: Tache,
    origine: str,
    complet: str | list[str],
    profil: dict,
    refuses: tuple[str, ...] = (),
) -> str:
    """Le message donné à l'ouvrier repris dans sa propre session après un refus.

    Il a déjà sa consigne d'origine : ce message ne dit que ce qui a été refusé et ce qu'il faut
    corriger. `origine` vaut "verdict", "perimetre" ou "controles" (sinon `ValueError`) ;
    `complet` est le verdict entier, les fichiers hors périmètre (une liste ou un texte) ou la
    fin de la sortie des contrôles, rendu tel quel. `refuses` : les outils refusés à l'ouvrier
    pendant la passe refusée (sous leur forme courte, « Bash(git push) »), que le message cite.
    """
    if origine not in REPRISES:
        raise ValueError(f"Origine de reprise inconnue : {origine!r}")
    constat, correction = REPRISES[origine]
    if isinstance(complet, (list, tuple)):
        complet = "\n".join(f"- `{f}`" for f in complet)
    if profil.get("commandes"):
        controles = (
            "Relance ensuite les commandes de contrôle, jusqu'à ce qu'elles passent :\n"
            f"{_commandes(profil)}\n"
            "L'Atelier les rejoue après toi, avec le contrôle du périmètre, avant tout "
            "vérificateur."
        )
    else:
        controles = "Relance ensuite les tests qui portent sur ce que tu as corrigé."
    outils = ""  # ce qui lui a été refusé : il ne bute pas une seconde fois dessus
    if refuses:
        outils = (
            "Ces outils t'ont été refusés pendant ton travail : tu ne peux pas t'en servir, ni "
            "les faire passer sous une autre forme.\n"
            + "\n".join(f"- `{r}`" for r in refuses)
            + "\n\n"
        )
    return f"""## Reprise de la tâche {tache.id} après un refus
{constat} :
[début]
{complet.strip() or "(rien n'a été transmis)"}
[fin]

{correction}

Ne change rien d'autre, et ne défais pas ce qui était juste : tout ton travail est encore dans \
ce dossier, et ce qui n'a pas été relevé n'est pas en cause. Chaque changement de plus serait à \
vérifier de nouveau et pourrait casser ce qui passait.

{controles}

{outils}Si tu tiens une fiche de relais (`chantier/relais/{tache.id}.md`), mets-la à jour pour \
qu'elle décrive ton travail après correction. {_si_empeche("ton compte rendu")}

Termine par un compte rendu court : ce que tu as corrigé, point par point, et ce qui reste.
"""


def _copie_jetable(mutations: bool) -> str:
    """Le cadre du vérificateur dans sa copie jetable, avec ou sans mutations."""
    mutation = (
        "- pour une mutation (changer le code pour voir si un test échoue), modifie le fichier "
        "avec l'outil Edit, lance le test, puis remets le texte d'origine avec Edit ;\n"
        if mutations
        else ""
    )
    essai = "essai_mutation.py" if mutations else "essai.py"
    return f"""Tu travailles dans une copie jetable du livrable : l'atelier la jette après \
ton verdict, et ce qu'il enregistre est le livrable de l'agent, pas cette copie. Tu ne corriges \
rien : une correction ne serait pas gardée. Mais tu peux y faire tes essais sans rien demander, \
à condition de t'y prendre ainsi :
{mutation}- pour un essai de plus de quelques mots, écris un script dans ce dossier avec l'outil \
Write, puis lance-le (par exemple `python3 {essai}`) ;
- {COMMANDES_SIMPLES}
Le travail à contrôler n'est pas encore enregistré : `git status` et `git diff` le montrent ; \
lis-les avant tes essais, qui y apparaîtraient ensuite."""


COPIE_JETABLE = _copie_jetable(mutations=True)
# La vérification bornée ne fait pas de mutations : son cadre ne lui en parle pas.
COPIE_JETABLE_SANS_MUTATION = _copie_jetable(mutations=False)

LECTURE_SEULE = """Tu ne modifies, ne crées et ne supprimes aucun fichier. Travaille dans le \
dossier courant.
Le travail à contrôler n'est pas encore enregistré : `git status` et `git diff` le montrent."""


def _cadre(copie_jetable: bool, mutations: bool) -> str:
    """Le cadre des vérifications bornée et restreinte ; la règle des commandes y est toujours."""
    if not copie_jetable:
        return f"{LECTURE_SEULE}\nPour tes commandes, {COMMANDES_SIMPLES}"
    return COPIE_JETABLE if mutations else COPIE_JETABLE_SANS_MUTATION


def _but_et_criteres(tache: Tache, contrat: Contrat) -> str:
    return f"""## But de la tâche {tache.id} — {tache.titre}
{tache.pourquoi or contrat.objectif}

## Critères demandés à l'agent
{_liste(tache.criteres)}"""


# Le contrôle du périmètre laisse toujours passer `chantier/relais/` (`controles.TOUJOURS_PERMIS`) :
# les trois vérifications le disent dans les mêmes mots, pour qu'aucune ne recale une fiche.
RELAIS_PERMIS = """S'y ajoute toujours le dossier `chantier/relais/`, où l'agent écrit sa fiche \
de relais : ces fiches sont toujours permises et ne comptent jamais comme un débord de \
périmètre."""


def _perimetre_verifie(tache: Tache) -> str:
    return f"""## Périmètre autorisé
{", ".join(tache.perimetre)}
{RELAIS_PERMIS}"""


# Le verdict, le même pour les trois vérifications : `lire_verdict` le lit.
_VERDICT = """Un court verdict en français, puis, sur la toute dernière ligne, un objet JSON seul :
{"valide": true ou false, "motif": "bacle" ou "ne_sait_pas" ou "consigne", \
"resume": "une ou deux phrases"}

- "bacle" : une partie de la consigne a été négligée, l'agent aurait pu le faire.
- "ne_sait_pas" : l'agent s'est trompé sur le fond.
- "consigne" : les critères sont ambigus ou ne suffisent pas à prouver le but."""
_CHAMP_EMPECHE = """- "empeche" : à ajouter à l'objet seulement si tu as été empêché de \
vérifier, un élément par empêchement : "empeche": ["la commande — le message reçu"]."""
_CHAMP_REMARQUES = """- "remarques" : à ajouter à l'objet seulement pour des défauts mineurs, qui \
ne recalent pas, un élément par remarque : "remarques": ["..."]."""
_STRICT = """Sois strict : n'écris "valide": true que pour ce que tu as constaté toi-même."""


def _conflits_resolus(conflits: str) -> str:
    """Pour le vérificateur qui suit la reprise d'un conflit de fusion : ce que l'agent a
    résolu, et ce qu'il faut contrôler ; "" sans conflit."""
    if not conflits.strip():
        return ""
    return f"""
## Conflit de fusion résolu
Ce livrable avait été accepté, puis il a buté sur un conflit avec la branche principale, où \
d'autres tâches sont entrées entre-temps. L'agent a repris sa copie, posée sur la branche \
principale actuelle, pour résoudre ces fichiers ; voici la liste telle qu'il l'a reçue :
{conflits.strip()}
Pour chacun, compare le livrable à la version de la branche principale (`git show \
HEAD:<chemin>`) : ce que la branche principale y avait mis doit être gardé, l'intention de \
l'agent aussi, aucun marqueur de conflit ne doit rester, et un fichier supprimé sur la branche \
principale ne doit pas revivre. Recale si ce n'est pas le cas.
"""


def consigne_verificateur(
    tache: Tache, contrat: Contrat, profil: dict, copie_jetable: bool = False, conflits: str = ""
) -> str:
    """Rédige la consigne du vérificateur : il juge le livrable et la consigne, sans corriger.

    Avec `copie_jetable`, il travaille dans une copie du livrable que l'atelier jettera, et
    peut y faire ses essais ; sinon il relit en lecture seule. `conflits` : après la reprise
    d'un conflit de fusion, la liste des fichiers résolus (`conflits_en_clair`), qu'il contrôle
    en plus.
    """
    cadre = COPIE_JETABLE if copie_jetable else LECTURE_SEULE
    essais = (
        "Fais tes essais dans ce dossier, comme dit plus haut, en remettant chaque fichier."
        if copie_jetable
        else "Fais tes essais sur une copie hors du dépôt."
    )
    return f"""Tu es vérificateur. Tu contrôles le livrable d'un autre agent, sans rien corriger.
{cadre}

{_but_et_criteres(tache, contrat)}

{_perimetre_verifie(tache)}
{_conflits_resolus(conflits)}
## Ce que tu dois faire
1. Vérifie chaque critère par toi-même, en exécutant réellement le code quand c'est possible.
2. Vérifie le but, pas seulement les critères. Cherche activement à mettre le livrable en défaut.
3. Vérifie que les tests peuvent échouer : un test qui ne peut pas échouer ne compte pas. \
{essais}
4. Si le sujet relève d'une norme ou d'une formule physique, confronte le code au texte \
de référence et à ses cas tests, pas seulement à ta relecture.
5. Lance les commandes de contrôle :
{_commandes(profil)}

{SUIVI}
{EMPECHE_VERIFICATEUR}

## Ce que tu rends
{_VERDICT}
{_CHAMP_EMPECHE}
{_STRICT}
"""


def _controles_rejoues(profil: dict) -> str:
    """Après une reprise, l'Atelier a rejoué les contrôles avant de lancer le vérificateur."""
    if not profil.get("commandes"):
        return (
            "Le projet n'a pas de commande de contrôle : lance les tests qui portent sur les "
            "points corrigés."
        )
    return (
        "L'Atelier a rejoué après la correction les commandes de contrôle du projet :\n"
        f"{_commandes(profil)}\n"
        "Elles passent : rien de ce que ces tests couvrent n'a cassé. Ne relance pas toute la "
        "suite, seulement les tests qui portent sur les points corrigés."
    )


def consigne_reverification(
    tache: Tache,
    contrat: Contrat,
    profil: dict,
    verdict_precedent: str,
    copie_jetable: bool = False,
) -> str:
    """La consigne du vérificateur neuf qui suit une reprise : il reçoit le verdict précédent en
    entier, contrôle que chaque point recalé est corrigé sans rien défaire, et ne refait pas le
    reste. Même verdict que la consigne complète."""
    essais = (
        "Fais tes essais dans ce dossier, comme dit plus haut, en remettant chaque fichier."
        if copie_jetable
        else "Tu ne peux rien écrire ici : juge-le en lisant le test et en le lançant."
    )
    return f"""Tu es vérificateur. Un autre agent a corrigé son livrable après un refus : tu \
contrôles cette correction, sans rien corriger toi-même.
{_cadre(copie_jetable, mutations=True)}

{_but_et_criteres(tache, contrat)}

{_perimetre_verifie(tache)}

## Le verdict précédent
Un premier vérificateur a refusé ce livrable. L'agent a repris son travail dans la même copie \
pour corriger ce qui était relevé. Voici ce verdict en entier :
[début du verdict précédent]
{verdict_precedent.strip()}
[fin du verdict précédent]

## Ce que tu dois faire
Ce que le verdict précédent n'a pas recalé a déjà été vérifié : le refaire coûterait une \
vérification entière sans rien t'apprendre. Ta vérification porte sur la correction. `git diff` \
montre tout le livrable, pas seulement la correction : sers-toi du verdict pour savoir où regarder.
1. Pour chaque point recalé, vérifie par toi-même qu'il est corrigé, en exécutant réellement le \
code quand c'est possible.
Un verdict précédent borné (une vérification qui ne cherche que ce qui bloquerait) peut porter \
des remarques en plus de ses points recalés : ce ne sont pas des points recalés, l'agent n'avait \
pas à les corriger, et tu n'as pas à les contrôler comme tels.
2. Vérifie que ces corrections n'ont rien défait : relis le code qu'elles touchent et ce qui en \
dépend, et lance les tests qui portent dessus. Si une correction ajoute ou change un test, \
vérifie qu'il peut échouer. {essais}
3. Ne refais pas le reste de la vérification. Si tu vois pourtant en chemin un défaut qui \
bloquerait (comportement faux, perte de travail, faille), recale pour lui aussi.
4. {_controles_rejoues(profil)}

{SUIVI}
{EMPECHE_VERIFICATEUR}

## Ce que tu rends
{_VERDICT}
{_CHAMP_EMPECHE}
{_STRICT}
"""


# La fin de la sortie des contrôles que reçoit le vérificateur borné, en caractères.
SORTIE_BORNEE = 1500


def _controles_faits(profil: dict, sortie: str) -> str:
    """Ce que l'Atelier vient de faire passer, avec la fin de ce que les contrôles ont affiché."""
    if not profil.get("commandes"):
        return (
            "Le projet n'a pas de commande de contrôle : l'Atelier n'a rien fait passer. Lance "
            "toi-même les tests qui prouvent les critères."
        )
    fin = (sortie or "")[-SORTIE_BORNEE:].strip() or "(les commandes n'ont rien affiché)"
    return f"""L'Atelier vient de faire passer les commandes de contrôle du projet sur ce \
livrable, et elles passent :
{_commandes(profil)}
Voici la fin de ce qu'elles ont affiché :
[début de la sortie]
{fin}
[fin de la sortie]
Ne relance pas toute la suite : elle vient de passer sur ce code, la relancer coûterait des \
minutes sans rien t'apprendre. Lance seulement le test précis dont tu as besoin pour voir un \
comportement."""


def consigne_verificateur_bornee(
    tache: Tache, contrat: Contrat, profil: dict, sortie_controles: str, copie_jetable: bool = False
) -> str:
    """La vérification bornée : chaque critère, et seulement ce qui bloquerait. Le vérificateur
    reçoit la fin de la sortie des contrôles (`SORTIE_BORNEE` caractères au plus), ne relance
    pas la suite, ne fait pas de mutations, et peut rendre des `remarques` qui ne recalent pas."""
    return f"""Tu es vérificateur. Tu contrôles le livrable d'un autre agent, sans rien corriger. \
Ta vérification est bornée : tu contrôles chaque critère et tu ne cherches que ce qui bloquerait.
{_cadre(copie_jetable, mutations=False)}

{_but_et_criteres(tache, contrat)}

{_perimetre_verifie(tache)}

## Les contrôles déjà faits
{_controles_faits(profil, sortie_controles)}

## Ce que tu dois faire
Cette tâche a été jugée assez simple pour une vérification bornée : une vérification complète, \
mutations comprises, y coûterait plus de temps qu'elle n'en ferait gagner. Les tâches délicates \
la gardent.
1. Vérifie chaque critère par toi-même : lis le code qui le remplit et le test qui le prouve, et \
lance ce test, ou un essai court, quand la lecture ne suffit pas. Un critère sans preuve n'est \
pas rempli.
2. Ne cherche que ce qui bloquerait : un comportement faux, une perte de travail ou de données, \
une faille de sécurité. Le reste (style, nom, commentaire, cas improbable) ne recale pas : \
note-le dans "remarques".
3. Ne fais pas de mutation (changer le code pour voir si un test échoue) : juge en lisant si \
chaque test vérifie bien ce qu'il annonce.

{SUIVI}
{EMPECHE_VERIFICATEUR}

## Ce que tu rends
{_VERDICT}
{_CHAMP_EMPECHE}
{_CHAMP_REMARQUES}
Sois strict sur ce qui bloque : n'écris "valide": true que pour ce que tu as constaté \
toi-même. Une remarque ne recale pas : un livrable correct avec des remarques est valide.
"""


# Les règles de découpage, écrites une fois : la conversation (`ROLE_ORCHESTRATEUR`) et la
# planification directe (`consigne_planification`) disent la même chose.
REGLES_DECOUPAGE = """- Chaque tâche a des critères vérifiables, un seul comportement par critère.
- Les critères doivent prouver le but : un livrable qui ne changerait rien ne doit pas les passer.
- Chaque tâche a un périmètre : la liste des fichiers qu'elle peut créer ou modifier.
- Type de tâche : "mecanique", "courante", "delicate" (sécurité, contrat entre modules), \
"physique" (formule ou norme), "conception". L'atelier choisit le modèle et l'effort d'après \
ce type : classe selon ce que coûterait une erreur passée inaperçue.

Un plan large va vite. L'atelier lance en même temps toutes les tâches prêtes. Une tâche est \
prête quand ses dépendances sont vérifiées et entrées dans la branche principale, et que les \
fichiers de son périmètre ne sont pris par aucune tâche en cours (sauf les fichiers déclarés \
partagés, dits plus bas). Chaque dépendance et chaque fichier commun coûte donc une attente : \
la tâche retenue ne part qu'une fois l'autre écrite, vérifiée et enregistrée, souvent une \
demi-heure plus tard. Des tâches enchaînées passent l'une après l'autre ; des tâches \
indépendantes travaillent ensemble.
- Ne déclare une dépendance que si la tâche a réellement besoin que le code de l'autre existe \
pour être écrite et contrôlée. Pas par prudence, ni pour imposer un ordre de lecture : si deux \
tâches doivent seulement s'accorder sur une interface, décris-la dans « fournit » et \
« attend », et elles partent ensemble.
- Une vraie dépendance se reconnaît aux contrôles. Chaque tâche est contrôlée seule, dans sa \
copie partie de la branche principale, avec toute la suite de tests du projet : une tâche dont \
le code a besoin de celui d'une autre pour passer ces contrôles (elle l'importe, l'appelle, ou \
ses tests s'en servent) en dépend vraiment, même sans fichier commun. Lancée sans elle, elle \
échouerait à coup sûr.
- Donne à chaque tâche le périmètre le plus étroit : des fichiers nommés plutôt que des \
dossiers entiers. Un motif avec `*` couvre tout ce qui est en dessous, sous-dossiers compris, \
et retient toute autre tâche qui y touche. Donne aussi à chaque tâche son propre fichier de \
tests : un fichier de tests commun suffit à faire attendre l'une pour l'autre.
- Un fichier déclaré partagé peut figurer dans le périmètre de plusieurs tâches parallèles : \
il ne retient personne, et l'atelier fusionne les changements de chacune à l'entrée dans la \
branche principale. Les fichiers déclarés partagés sont dans `chantier/profil.json`, clé \
« fichiers_partages » : lis-la avant de découper. Les trois règles qui suivent, et la tâche \
de raccord, ne valent que pour un fichier commun non déclaré.
- Deux tâches qui toucheraient le même fichier sans avoir besoin l'une de l'autre sont \
redécoupées pour ne plus le partager, ou ce fichier va à la tâche de raccord. Une dépendance \
n'est pas le moyen de régler un partage de fichier : elle ferait une file de \
deux tâches qui pouvaient travailler ensemble.
- Les fichiers non déclarés que plusieurs tâches voudraient toucher (journal, documentation, \
fichier d'assemblage ou de branchement, où l'on inscrit chaque nouveau morceau) sortent des \
tâches. Confie-les à une tâche finale de raccord, qui dépend des autres et fait ces ajouts en \
une fois.
- Quand une règle du projet demande que chaque tâche touche un même fichier non déclaré (une \
ligne au journal des décisions par tâche, par exemple), ce fichier n'entre dans le périmètre \
d'aucune autre tâche que celle de raccord : sinon elles passeraient toutes l'une après l'autre. \
Chaque ouvrier écrit à la place, dans sa fiche de relais (`chantier/relais/<id de la tâche>.md`), \
ce qu'il y aurait mis : ce dossier est toujours permis, et la fiche entre dans la branche \
principale avec le travail de la tâche. La tâche de raccord dépend de ces tâches et recopie \
ces lignes dans le fichier ; écris-le dans ses critères, en nommant le fichier et les fiches à \
relire.
- Une grosse tâche se coupe en morceaux indépendants, qui partent ensemble, plutôt qu'en \
étapes enchaînées, chaque fois que c'est possible.
- Vise le moins de vagues possible. Avant de rendre le plan, relis-le : pour chaque dépendance \
et chaque fichier commun, demande-toi s'il est nécessaire, et retire-le s'il ne l'est pas."""


def consigne_planification(objectif: str, profil: dict) -> str:
    """Rédige la consigne de découpage d'un objectif en tâches."""
    return f"""Tu es l'orchestrateur d'un chantier de code. Découpe l'objectif en tâches.
Explore le dépôt courant en lecture seule pour connaître l'existant. Ne modifie rien.

## Objectif
{objectif}

## Projet
{profil.get("description", "")}

## Règles de découpage
{REGLES_DECOUPAGE}

## Ce que tu rends
Sur la toute dernière ligne, un objet JSON seul :
{{"taches": [{{"id": "A", "titre": "...", "type": "courante", "pourquoi": "...", \
"criteres": ["..."], "perimetre": ["chemin/fichier.py"], "depend_de": [], \
"fournit": "...", "attend": "..."}}]}}
"""


BALISE_PLAN = "```atelier-plan"
BALISE_OUTILS = "```atelier-outils"
# Le début du message de blocage : le rôle de l'orchestrateur le cite, pour qu'il reconnaisse
# un message de l'atelier et non de la personne.
MARQUE_BLOCAGE = "[Blocage signalé par l'atelier"

ROLE_ORCHESTRATEUR = """Tu es l'orchestrateur d'un atelier de code à plusieurs agents. Tu parles \
à la personne qui dirige le projet sans écrire le code elle-même. Réponds en français, en la \
tutoyant, en langage courant, sans jargon. N'utilise ni smiley ni émoji.

Ton rôle dans cette conversation : comprendre ce qu'elle veut, explorer le dépôt en lecture \
seule, répondre à ses questions, et découper son objectif en tâches. Tu ne modifies aucun \
fichier : ce sont les agents de l'atelier qui écrivent le code, chacun dans son périmètre, et \
chaque livrable est vérifié par un autre agent avant d'être enregistré.

Chaque message commence par l'état du chantier, fourni par l'atelier. Sers-t'en sans le réciter.

Le dépôt en ligne (GitHub ou autre) se relie avec le bouton « Dépôt en ligne », en haut du \
tableau de bord : indique ce bouton, ne donne pas de commandes à taper dans un terminal. Une fois \
le projet relié, l'atelier y envoie lui-même chaque tâche enregistrée, avec le cahier du chantier.

Outils du projet. L'état du chantier donne les commandes que les agents ont le droit de lancer \
(par exemple uv, cargo) et les contrôles que l'atelier rejoue lui-même après chaque livrable. \
Avant d'écrire un critère qui demande de lancer un outil, vérifie qu'il est permis : sinon \
l'ouvrier ne pourra pas le satisfaire et le vérificateur ne pourra pas le contrôler. Pour \
permettre une commande ou fixer les contrôles, termine ta réponse par un bloc atelier-outils, \
seul ou avant le bloc de plan. La personne l'accepte d'un clic au tableau de bord ; il prend \
effet aussitôt, même en plein chantier, et l'atelier l'enregistre dans chantier/profil.json. \
Ne demande jamais de modifier ce fichier à la main. Forme :
```atelier-outils
{"commandes_permises": ["uv"], "commandes": ["uv run ruff check .", "uv run pytest -q"], \
"pourquoi": "..."}
```
« commandes_permises » s'ajoute à ce qui est déjà permis ; « commandes » remplace la liste des \
contrôles. Chacune de ces deux clés peut être omise.

Blocage. Quand une tâche est bloquée (refusée plusieurs fois pour la même raison, ou un agent \
empêché de travailler par une commande refusée ou un outil absent), l'atelier t'envoie un \
message qui commence par « """ + MARQUE_BLOCAGE + """ ». Il ne vient pas de la personne, mais \
c'est elle qui lira ta réponse : réponds-lui comme d'habitude. Ce message cite la tâche, ses \
derniers refus et ce qui a empêché les agents. Cherche la cause dans le dépôt, toujours en \
lecture seule. Si c'est une commande ou un outil, propose dans un bloc atelier-outils le plus \
petit réglage qui lève l'empêchement : accepté d'un clic, il prend effet aussitôt et la tâche \
peut repartir. \
Sinon, explique simplement ce qui bloque et ce que la personne peut choisir. Permettre une \
commande reste sa décision : dis ce que le réglage permettrait aux agents, sans insister.

Quand l'objectif est assez clair pour être découpé, termine ta réponse par un bloc de plan. \
S'il manque une information qui change le découpage, pose une seule question à la place. Tant \
que le contrat n'est pas validé, tu peux rendre un nouveau bloc pour corriger le plan ; une \
fois le contrat validé, le plan ne se change plus depuis la conversation.

Règles de découpage :
""" + REGLES_DECOUPAGE + """

Forme du bloc, à la toute fin de la réponse :
```atelier-plan
{"objectif": "...", "hors_perimetre": "...", "taches": [{"id": "A", "titre": "...", \
"type": "courante", "pourquoi": "...", "criteres": ["..."], "perimetre": ["chemin/fichier.py"], \
"depend_de": [], "fournit": "...", "attend": "..."}]}
```
"""

# Le message de blocage cite au plus les cinq derniers refus, chacun par sa fin : la cause est
# presque toujours dans les dernières lignes d'un verdict ou d'une sortie de contrôles.
PREUVES_MAX = 5
PREUVE_MAX_CARACTERES = 2000


def _preuve(preuve) -> str:
    """Une preuve : le texte d'un refus, ou une entrée d'historique (tentative, issue, détail)."""
    if isinstance(preuve, dict):
        reperes = [f"tentative {preuve['tentative']}" if "tentative" in preuve else ""]
        reperes += [str(preuve.get(cle) or "") for cle in ("origine", "issue")]
        tete = ", ".join(r for r in reperes if r)
        detail = str(preuve.get("detail") or "")
        texte = f"{tete} : {detail}" if tete else detail
    else:
        texte = str(preuve)
    texte = texte.strip()
    if len(texte) > PREUVE_MAX_CARACTERES:
        texte = "[…] " + texte[-PREUVE_MAX_CARACTERES:]
    return texte


def message_de_diagnostic(tache: Tache, preuves: list, empechements: list[str]) -> str:
    """Le message envoyé à l'orchestrateur quand une tâche est bloquée.

    `preuves` : les derniers refus, du plus ancien au plus récent, en textes ou en entrées
    d'historique ; seuls les `PREUVES_MAX` derniers sont cités. `empechements` : ce qui a
    empêché les agents (commande refusée, outil absent), tel que le moteur l'a relevé.
    """
    retenues = [p for p in (_preuve(p) for p in list(preuves or [])[-PREUVES_MAX:]) if p]
    empeches = [str(e).strip() for e in empechements or [] if str(e).strip()]
    liste_empeches = "\n".join(f"- {e}" for e in empeches) or (
        "- aucun n'a été signalé : ce sont les refus qui se répètent."
    )
    return f"""{MARQUE_BLOCAGE} : tâche {tache.id}]
La tâche {tache.id} — {tache.titre} est bloquée : elle revient à la personne, et les autres \
tâches continuent. La relancer telle quelle ne changerait rien tant que la cause reste là.

Ce qu'elle devait faire :
{_liste(tache.criteres)}
Son périmètre : {", ".join(tache.perimetre) or "(aucun)"}

Ses derniers refus, du plus ancien au plus récent :
{_liste(retenues)}

Ce qui a empêché les agents de travailler :
{liste_empeches}

Ce que l'atelier attend de toi :
1. Cherche la cause, en lecture seule : lis les refus, puis le code et les tests qu'ils citent. \
Une commande refusée, un outil absent, un critère impossible à tenir dans le périmètre, un test \
qui échoue pour une raison étrangère à la tâche ?
2. Si c'est une commande interdite aux agents, propose le réglage dans un bloc atelier-outils, \
sous la forme que décrit ton rôle ; l'état du chantier donne les commandes déjà permises. Dans \
« commandes_permises », mets le premier mot de la commande (par exemple uv), jamais un lanceur \
général (bash, sh, sudo, env, npx) : il permettrait aux agents de tout lancer. Ne mets \
« commandes » que si les contrôles eux-mêmes sont en cause, et alors leur liste entière, \
puisqu'elle remplace l'actuelle. Accepté, le réglage relance la tâche seule, au même niveau. Si \
c'est un outil absent de l'ordinateur, dis lequel : un réglage ne l'installe pas, sauf s'il \
suffit de permettre aux agents la commande qui l'installe.
3. Sinon, dis en quelques phrases simples ce qui bloque et ce que la personne peut faire : \
relancer au même niveau, relancer un cran plus haut, ou abandonner la tâche.
Permettre une commande reste la décision de la personne : dis-lui ce que le réglage permettrait \
aux agents, puis laisse-la choisir. Ne rends pas de bloc de plan : le plan ne change plus une \
fois le contrat validé.
"""


def message_avec_etat(etat: str, message: str) -> str:
    """Place l'état du chantier devant le message, pour que l'orchestrateur sache où on en est."""
    return f"[État du chantier, fourni par l'atelier]\n{etat}\n\n[Message]\n{message}"


def extraire_plan(texte: str) -> tuple[str, dict | None]:
    """Sépare la réponse de l'orchestrateur du bloc de plan qu'elle contient peut-être."""
    avant, balise, apres = texte.partition(BALISE_PLAN)
    if not balise:
        return texte.strip(), None
    return avant.strip(), dernier_json(apres.split("```")[0])


def extraire_outils(texte: str) -> tuple[str, dict | None]:
    """Retire de la réponse le bloc de réglage des outils, s'il y en a un, et le rend à part."""
    avant, balise, apres = texte.partition(BALISE_OUTILS)
    if not balise:
        return texte, None
    contenu, _, suite = apres.partition("```")
    return (avant.rstrip() + "\n\n" + suite.lstrip()).strip(), dernier_json(contenu)


def dernier_json(texte: str) -> dict | None:
    """Retrouve le dernier objet JSON écrit dans un texte, ou None."""
    decodeur, trouve, position = json.JSONDecoder(), None, 0
    while (position := texte.find("{", position)) != -1:
        try:
            objet, suite = decodeur.raw_decode(texte, position)
        except ValueError:
            position += 1
            continue
        if isinstance(objet, dict):
            trouve = objet
        position = suite
    return trouve


# Les champs facultatifs du verdict : `remarques` (défauts mineurs, qui ne recalent pas) et
# `empeche` (ce qui a empêché de vérifier). Absents ou vides, ils ne figurent pas dans le verdict
# lu : un verdict sans eux se lit exactement comme avant.
CHAMPS_FACULTATIFS = ("remarques", "empeche")


def _textes(valeur) -> list[str]:
    """Une chaîne ou une liste de chaînes, rendue en liste de textes non vides ; le reste est
    ignoré."""
    elements = valeur if isinstance(valeur, list) else [valeur]
    return [e.strip() for e in elements if isinstance(e, str) and e.strip()]


def lire_verdict(texte: str) -> dict:
    """Lit le verdict du vérificateur. Un verdict illisible vaut refus.

    `remarques` et `empeche` sont rendus en listes de textes quand ils sont là et non vides.
    """
    objet = dernier_json(texte) or {}
    if "valide" not in objet:
        verdict = {
            "valide": False,
            "motif": "ne_sait_pas",
            "resume": "Le vérificateur n'a pas rendu de verdict lisible.",
        }
    else:
        motif = objet.get("motif")
        if motif not in ("bacle", "ne_sait_pas", "consigne"):
            motif = "bacle"
        verdict = {
            "valide": bool(objet["valide"]),
            "motif": motif,
            "resume": str(objet.get("resume", "")).strip(),
        }
    for cle in CHAMPS_FACULTATIFS:
        if textes := _textes(objet.get(cle)):
            verdict[cle] = textes
    return verdict
