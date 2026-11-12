"""Maquette générique de l'onglet Code : tout est calculé depuis la carte d'un projet et son code."""
import ast, json, html, math, re, sys, posixpath
from pathlib import Path
from collections import defaultdict
e = html.escape
S = json.load(open('/tmp/claude-0/sys.json'))
PALIERS = [1, 20, 50, 100, 150, 200, 300, 450, 650, 1000]
taille = lambda n: ''.join(f'<i class="{"on" if n >= p else ""}"></i>' for p in PALIERS)
court = lambda c: c.rstrip('/').split('/')[-1]

def etiquettes(depot, fichiers, liens):
    """Pour chaque lien a → b, les noms que a prend dans b (imports Python et JS), sans Claude."""
    noms = defaultdict(list); chemins = set(fichiers)
    for a, b in liens:
        texte = (Path(depot) / a).read_text(errors='ignore') if (Path(depot) / a).is_file() else ''
        if a.endswith('.py'):
            try: arbre = ast.parse(texte)
            except SyntaxError: continue
            paquet = posixpath.dirname(a)
            for n in ast.walk(arbre):
                if isinstance(n, ast.ImportFrom):
                    base = paquet
                    for _ in range(max(0, n.level - 1)): base = posixpath.dirname(base)
                    mod = (n.module or '').replace('.', '/')
                    cand = posixpath.join(base, mod) if n.level else mod
                    for nom in n.names:
                        for c in (cand + '.py', cand + '/__init__.py', posixpath.join(cand, nom.name) + '.py'):
                            if c == b: noms[(a, b)].append(nom.name if not c.endswith(nom.name + '.py') else nom.name + '/')
        else:
            for m in re.finditer(r"import\s+(?:\{([^}]*)\}|(\w+))\s+from\s+['\"]([^'\"]+)['\"]", texte):
                cible = posixpath.normpath(posixpath.join(posixpath.dirname(a), m.group(3)))
                if b.startswith(cible):
                    noms[(a, b)] += [x.strip().split(' as ')[0] for x in (m.group(1) or m.group(2)).split(',') if x.strip()]
    return {k: list(dict.fromkeys(v)) for k, v in noms.items()}

def niveau_depart(fichiers):
    """Descend tant qu'un seul dossier porte au moins 70 % des lignes de code : on part de là où vit le code."""
    pref = ''
    while True:
        par = defaultdict(int); tot = 0
        for f in fichiers:
            if f['genre'] != 'code' or not f['chemin'].startswith(pref): continue
            reste = f['chemin'][len(pref):]
            if '/' not in reste: par[None] += f['lignes']
            else: par[reste.split('/')[0]] += f['lignes']
            tot += f['lignes']
        dossiers = {k: v for k, v in par.items() if k}
        if not dossiers or not tot: return pref
        k, v = max(dossiers.items(), key=lambda x: x[1])
        if v / tot < 0.7: return pref
        pref += k + '/'

def bloc_de(chemin, pref):
    if not chemin.startswith(pref): return None
    reste = chemin[len(pref):]
    return pref + reste.split('/')[0] + ('/' if '/' in reste else '')

def niveau(carte, pref, noms):
    blocs = {}
    for f in carte['fichiers']:
        b = bloc_de(f['chemin'], pref)
        if b: blocs.setdefault(b, []).append(f)
    # Un fichier presque vide (un __init__.py d'une ligne) n'apprend rien : il reste dans l'explorateur.
    blocs = {b: fs for b, fs in blocs.items() if b.endswith('/') or fs[0]['lignes'] >= 8}
    aretes = defaultdict(list)
    for a, b in carte['liens']:
        ba, bb = bloc_de(a, pref), bloc_de(b, pref)
        if ba in blocs and bb in blocs and ba != bb: aretes[(ba, bb)] += noms.get((a, b), [])
    return blocs, {k: list(dict.fromkeys(v)) for k, v in aretes.items()}

def disposer(blocs, aretes, max_blocs=12, par_rangee=4):
    relies = {x for k in aretes for x in k}
    entrant = defaultdict(set); sortant = defaultdict(set)
    for a, b in aretes: entrant[b].add(a); sortant[a].add(b)
    n = len(relies)
    socle = sorted(b for b in relies if len(entrant[b]) >= max(3, math.ceil(0.3 * n)) and len(sortant[b]) <= 1)
    garde = [b for b in sorted(relies) if b not in socle]
    garde.sort(key=lambda b: (-(len(entrant[b]) + len(sortant[b])), b))
    autres = garde[max_blocs:]; garde = set(garde[:max_blocs])
    rang = {}
    def prof(b, vus=()):
        if b in rang: return rang[b]
        if b in vus: return 0
        r = 1 + max([prof(u, vus + (b,)) for u in sorted(entrant[b]) if u in garde] or [-1])
        rang[b] = r; return r
    for b in sorted(garde): prof(b)  # dans un ordre fixe : le schéma ne change pas d'un affichage à l'autre
    couches = defaultdict(list)
    for b in sorted(garde): couches[rang[b]].append(b)
    rangs, place = [], {}
    for r in sorted(couches):
        c = couches[r]
        c.sort(key=lambda b: (sum(place.get(u, 0) for u in entrant[b] if u in place) / max(1, len([u for u in entrant[b] if u in place])), b))
        for i in range(0, len(c), par_rangee):
            rangee = c[i:i + par_rangee]
            for j, b in enumerate(rangee): place[b] = j - (len(rangee) - 1) / 2
            rangs.append(rangee)
    isoles = sorted(set(blocs) - relies)
    return rangs, socle, autres, isoles

def reduire(aretes, garder):
    """Ne garde que les liens directs : a → c disparaît s'il existe déjà un chemin a → b → … → c."""
    succ = defaultdict(set)
    for a, b in aretes:
        if a in garder and b in garder: succ[a].add(b)
    def atteint(depart, cible, interdit):
        pile, vus = [x for x in succ[depart] if (depart, x) != interdit], set()
        while pile:
            x = pile.pop()
            if x == cible: return True
            if x in vus: continue
            vus.add(x); pile += list(succ[x])
        return False
    return {k: v for k, v in aretes.items() if k[0] in garder and k[1] in garder and not atteint(k[0], k[1], k)}

STYLE = open(Path(__file__).with_name('code.css')).read()

def schema(rangs, socle, aretes, en_cours, largeur=1000, centre=None, resumes=None):
    L, H, GX, GY, M = 214, 94, 30, 96, 60
    pos = {}
    for r, rangee in enumerate(rangs):
        w = len(rangee) * L + (len(rangee) - 1) * GX; x0 = (largeur - w) / 2
        for i, b in enumerate(rangee): pos[b] = (x0 + i * (L + GX), 24 + r * (H + GY), r)
    hauteur = 24 + len(rangs) * (H + GY) - GY + 24 + (70 if socle else 0)
    vis = [(a, b, n) for (a, b), n in aretes.items() if a in pos and b in pos]
    sortants = defaultdict(list); entrants = defaultdict(list)
    for a, b, n in vis:
        sortants[a].append(b)
        if pos[b][2] - pos[a][2] == 1: entrants[b].append(a)
    port = {}
    for a, l in sortants.items():
        l.sort(key=lambda b: pos[b][0])
        for i, b in enumerate(l): port[(a, b, 's')] = pos[a][0] + L * (i + 1) / (len(l) + 1)
    for b, l in entrants.items():
        l.sort(key=lambda a: pos[a][0])
        for i, a in enumerate(l): port[(a, b, 'e')] = pos[b][0] + L * (i + 1) / (len(l) + 1)
    def arrondi(pts, r=9):
        d = f'M{pts[0][0]:.1f},{pts[0][1]:.1f}'
        for i in range(1, len(pts) - 1):
            (x0, y0), (x1, y1), (x2, y2) = pts[i - 1], pts[i], pts[i + 1]
            l1, l2 = math.hypot(x1 - x0, y1 - y0), math.hypot(x2 - x1, y2 - y1)
            rr = min(r, l1 / 2, l2 / 2)
            if not rr: continue
            a = (x1 - (x1 - x0) / l1 * rr, y1 - (y1 - y0) / l1 * rr); c = (x1 + (x2 - x1) / l2 * rr, y1 + (y2 - y1) / l2 * rr)
            d += f' L{a[0]:.1f},{a[1]:.1f} Q{x1:.1f},{y1:.1f} {c[0]:.1f},{c[1]:.1f}'
        return d + f' L{pts[-1][0]:.1f},{pts[-1][1]:.1f}'
    fils, etiq = '', ''
    cote = 0
    for k, (a, b, n) in enumerate(sorted(vis, key=lambda t: (pos[t[1]][2], pos[t[1]][0]))):
        xs, ys = port[(a, b, 's')], pos[a][1] + H
        xe, ye = port.get((a, b, 'e'), pos[b][0] + 107), pos[b][1]
        saut = pos[b][2] - pos[a][2]
        actif = a in en_cours or b in en_cours
        coul = 'var(--en-cours)' if actif else 'rgba(220,220,220,.42)'
        bus = ye - 34
        if saut != 1:  # un lien qui saute une rangée : un renvoi court plutôt qu'un fil qui fait le tour
            fils += f'<path d="M{xs:.1f},{ys} L{xs:.1f},{ys + 16}" fill="none" stroke="{coul}" stroke-width="1.2" stroke-dasharray="2 3"/>'
            noms_txt = (' · '.join(n[:1]) + ' ') if n else ''
            etiq += f'<span class="renvoi{" actif" if actif else ""}" style="left:{xs:.0f}px;top:{ys + 26}px">{"↓" if saut > 1 else "↑"} {e(court(b))}{f" <i>{e(noms_txt.strip())}</i>" if noms_txt else ""}</span>'
            continue
        pts = [(xs, ys), (xs, bus), (xe, bus), (xe, ye)]
        fils += f'<path d="{arrondi(pts)}" fill="none" stroke="{coul}" stroke-width="{1.6 if actif else 1.2}" marker-end="url(#pointe{"b" if actif else ""})"/>'
        if n:
            coupe = lambda x: x if len(x) <= 18 else x[:17] + '…'
            txt = coupe(n[0]) + (f' · {coupe(n[1])}' if len(n) > 1 and len(n[0]) + len(n[1]) <= 26 else '') + (f' +{len(n) - (2 if len(n) > 1 and len(n[0]) + len(n[1]) <= 26 else 1)}' if len(n) > 1 and not (len(n) == 2 and len(n[0]) + len(n[1]) <= 26) else '')
            lx, ly = xe, ye - 13 if saut == 1 else bus
            etiq += f'<span class="lab{" actif" if actif else ""}" style="left:{lx:.0f}px;top:{ly:.0f}px">{e(txt)}</span>'
    blocs = ''
    for b, (x, y, r) in pos.items():
        dossier = b.endswith('/'); ag = en_cours.get(b)
        cls = 'bloc' + (' travail' if ag else '') + (' centre' if b == centre else '')
        ic = '<i class="ic-dossier"></i>' if dossier else f'<span class="ic-genre">{e(posixpath.splitext(b)[1][1:3].upper() or "·")}</span>'
        blocs += f'''<div class="{cls}" style="left:{x:.0f}px;top:{y}px"><div class="n">{ic}<span class="nm">{e(court(b))}{"/" if dossier else ""}</span>{f'<span class="ag">● {e(ag)}</span>' if ag else ''}</div>
          <div class="r">{e(resumes[b][0])}</div><div class="pied"><span class="tp">{taille(resumes[b][1])}</span><span>{e(resumes[b][2])}</span></div></div>'''
    sc = ''
    if socle:
        sc = f'<div class="socle" style="top:{hauteur - 62}px"><span class="et">Le socle</span>' + ''.join(f'<b>{e(court(s))}{"/" if s.endswith("/") else ""}</b>' for s in socle) + '<span>tout le monde s\'en sert : les flèches vers eux sont sous-entendues.</span></div>'
    svg = f'''<svg width="{largeur}" height="{hauteur}"><defs>
      <marker id="pointe" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="rgba(220,220,220,.6)"/></marker>
      <marker id="pointeb" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#8297c4"/></marker></defs>{fils}</svg>'''
    return f'<div class="schema" style="height:{hauteur}px;width:{largeur}px">{svg}{blocs}{etiq}{sc}</div>'

def resume_bloc(b, fichiers):
    if b.endswith('/'):
        code = sorted(fichiers, key=lambda f: -f['lignes'])
        txt = code[0]['resume'] if len(code) == 1 else f"{len(fichiers)} fichiers, dont {court(code[0]['chemin'])} : {code[0]['resume'][0].lower()}{code[0]['resume'][1:]}"
        return (txt[:110] + ('…' if len(txt) > 110 else ''), sum(f['lignes'] for f in fichiers), f'{len(fichiers)} fich.')
    f = fichiers[0]; return (f['resume'][:110] + ('…' if len(f['resume']) > 110 else ''), f['lignes'], f'{f["lignes"]} l.')

def arbre(carte, choisi, ouverts, en_cours):
    lignes = []
    def rendre(pref, prof):
        enfants = defaultdict(list)
        for f in carte['fichiers']:
            b = bloc_de(f['chemin'], pref)
            if b: enfants[b].append(f)
        for b in sorted(enfants, key=lambda x: (not x.endswith('/'), x.lower())):
            if b.endswith('/'):
                o = b in ouverts
                lignes.append(f'<div class="l d" style="padding-left:{6 + prof * 14}px"><span class="c">{"▾" if o else "▸"}</span><span>{e(court(b))}</span><span class="cpt">{len(enfants[b])}</span></div>')
                if o: rendre(b, prof + 1)
            else:
                ag = f'<span class="a">● {e(en_cours[b])}</span>' if b in en_cours else ''
                lignes.append(f'<div class="l{" on" if b == choisi else ""}" style="padding-left:{20 + prof * 14}px;grid-template-columns:1fr 40px"><span>{e(court(b))}{ag}</span><span class="n">{taille(enfants[b][0]["lignes"])}</span></div>')
    rendre('', 0)
    return f'<aside class="panneau"><span class="et">Fichiers · {len(carte["fichiers"])}</span><div class="arbre">{"".join(lignes[:40])}</div></aside>'

def page(nom_projet, corps, gauche, hauteur):
    tete = S["tete"]["Code"].replace('MOTEUR DE CALCUL', e(nom_projet.upper())).replace('Moteur de calcul', e(nom_projet))
    return f'''<!DOCTYPE html><html lang="fr"><head><meta charset="utf-8"><title>Atelier · Code</title>{S["fonts"]}<style>{STYLE}</style></head>
<body style="height:{hauteur}px">{tete}<main class="vue" style="height:{hauteur - 92}px">{gauche}<section class="panneau page">{corps}</section></main></body></html>'''

def barre(ariane, etage):
    pts = ''.join(f'<span class="{"on" if i == etage else ""}">{x}</span>' for i, x in enumerate(['0', '1', '2', '3+']))
    return f'<div class="barre"><span class="ariane">{ariane}</span><div class="etages">ÉTAGE&nbsp;{pts}</div><div class="cherche">⌕ Chercher un fichier, une fonction, un mot…</div></div>'

def generer(nom, depot, carte, en_cours, fichier_choisi, portrait):
    F = {f['chemin']: f for f in carte['fichiers']}
    noms = etiquettes(depot, F, carte['liens'])
    pref = niveau_depart(carte['fichiers'])
    blocs, aretes = niveau(carte, pref, noms)
    rangs, socle, autres, isoles = disposer(blocs, aretes)
    montres = {b for r in rangs for b in r}
    aretes = reduire(aretes, montres)
    resumes = {b: resume_bloc(b, fs) for b, fs in blocs.items()}
    en_cours_b = {}
    for c, ag in en_cours.items():
        b = bloc_de(c, pref)
        if b: en_cours_b[b] = ag
    tot = sum(f['lignes'] for f in carte['fichiers'])
    ouverts = {p for p in [pref] if p} | {bloc_de(fichier_choisi, '')}
    # étage 0
    # Ce qu'il y a dedans : le premier niveau qui contient plusieurs choses.
    base = ''
    while True:
        dedans_racine = defaultdict(list)
        for f in carte['fichiers']:
            b = bloc_de(f['chemin'], base)
            if b: dedans_racine[b].append(f)
        if len(dedans_racine) != 1 or not next(iter(dedans_racine)).endswith('/'): break
        base = next(iter(dedans_racine))
    lignes = ''.join(f'<div class="ligne"><span class="ic">{"▸" if b.endswith("/") else e(posixpath.splitext(b)[1][1:3].upper() or "·")}</span><span class="nm">{e(b[len(base):])}</span><span class="ds">{e(resume_bloc(b, fs)[0])}</span><span class="ct">{resume_bloc(b, fs)[2]}</span></div>'
                     for b, fs in sorted(dedans_racine.items(), key=lambda x: (not x[0].endswith('/'), x[0].lower())))
    note = (f'On part de <code>{e(pref)}</code> : c\'est là que vit {round(100 * sum(f["lignes"] for f in carte["fichiers"] if f["genre"] == "code" and f["chemin"].startswith(pref)) / max(1, sum(f["lignes"] for f in carte["fichiers"] if f["genre"] == "code")))} % du code.' if pref else '')
    sch = schema(rangs, socle, aretes, en_cours_b, resumes=resumes)
    reste = []
    if autres: reste.append(f'{len(autres)} autres éléments moins reliés, rangés dans l\'explorateur')
    if isoles: reste.append(f'{len(isoles)} éléments sans lien avec les autres ({", ".join(court(i) for i in isoles[:4])}{"…" if len(isoles) > 4 else ""})')
    corps0 = f'''{barre(f'<b>{e(nom)}</b>', 0)}<div class="corps"><h1 class="titre">{e(nom)}</h1>
<div class="puces"><span>racine du dépôt</span><span class="p">{len(carte["fichiers"])} fichiers</span><span class="p">{tot:,} lignes</span>{f'<span class="p bleu">● {len(en_cours)} fichiers en cours de modification</span>' if en_cours else ''}</div>
<p class="portrait">{portrait}</p><div class="ecrit">{"Écrit par Claude d'après le code" if portrait else ""}</div>
<div class="sec">La chaîne <i>de haut en bas : qui se sert de qui · sur chaque flèche, ce qui passe</i></div>
{f'<p class="note">{note}</p>' if note else ''}{sch}
<p class="legende">En haut, ce qui se sert des autres ; en bas, ce dont les autres se servent. Sur chaque flèche, ce que le fichier du haut prend dans celui du bas, lu dans le code. En bleu : là où un agent travaille en ce moment.{(" " + " ; ".join(reste) + ".") if reste else ""}</p>
<div class="sec">Ce qu'il y a dedans <i>{len(dedans_racine)}</i></div><div class="dedans">{lignes}</div></div>'''
    open(f'/home/user/atelier/maquettes/code-{nom}-projet.html', 'w').write(page(nom, corps0, arbre(carte, None, ouverts, en_cours), 260 + len(rangs) * 176 + (70 if socle else 0) + 900 + len(dedans_racine) * 52))
    # étage fichier
    f = F[fichier_choisi]; c = fichier_choisi
    appelants = sorted({a for a, b in carte['liens'] if b == c}); deps = sorted({b for a, b in carte['liens'] if a == c})
    tests = [a for a in appelants if F[a]['genre'] == 'tests']; appel = [a for a in appelants if a not in tests]
    blocs2 = {c: [f]} | {x: [F[x]] for x in appel + deps}
    ar2 = {(a, c): noms.get((a, c), []) for a in appel} | {(c, d): noms.get((c, d), []) for d in deps}
    # Les quatre dépendances dont il prend le plus ; les autres, en une ligne sous le schéma.
    utiles = [d for d in deps if F[d]['lignes'] >= 8]
    utiles.sort(key=lambda d: -len(noms.get((c, d), [])))
    principales, autres_deps = utiles[:4], utiles[4:]
    appel = appel[:4]
    blocs2 = {c: [f]} | {x: [F[x]] for x in appel + principales}
    ar2 = {(a, c): noms.get((a, c), []) for a in appel} | {(c, d): noms.get((c, d), []) for d in principales}
    rangs2 = [r for r in [appel, [c], sorted(principales)] if r]
    res2 = {b: resume_bloc(b, fs) for b, fs in blocs2.items()}
    sch2 = schema(rangs2, [], ar2, {k: v for k, v in en_cours.items() if k in blocs2}, centre=c, resumes=res2)
    # tous ceux qui seraient touchés, en remontant
    touches, file = set(), [c]
    while file:
        x = file.pop()
        for a, b in carte['liens']:
            if b == x and a not in touches and a != c: touches.add(a); file.append(a)
    mutuels = [d for d in deps if (d, c) in {tuple(l) for l in carte['liens']}]
    faits = [f'<li><b>{len(appel)} fichier{"s" if len(appel) > 1 else ""} s\'en {"servent" if len(appel) > 1 else "sert"} directement</b>{" (" + ", ".join(f"<code>{e(court(a))}</code>" for a in appel[:5]) + ")" if appel else ""}, et {len(touches)} en tout en remontant la chaîne.</li>']
    faits.append(f'<li>{"<b>" + str(len(tests)) + " fichier" + ("s" if len(tests) > 1 else "") + " de tests l\'importent</b> : " + ", ".join(f"<code>{e(court(t))}</code>" for t in tests) + ". Lance-les après une modification." if tests else "<b>Aucun fichier de tests ne l\'importe</b> : une modification ne sera rattrapée par aucun test."}</li>')
    if mutuels: faits.append(f'<li><b>Il dépend de {", ".join(f"<code>{e(court(m))}</code>" for m in mutuels)}, qui dépend de lui</b> : les deux se modifient ensemble.</li>')
    if f['lignes'] > 600: faits.append(f'<li>C\'est un gros fichier : <b>{f["lignes"]} lignes, {len(f["pieces"])} parties</b>. Repère la partie à changer avant d\'ouvrir.</li>')
    if c in en_cours: faits.append(f'<li><b>{e(en_cours[c])} le modifie en ce moment</b> dans sa copie de travail : attends sa fusion pour éviter un conflit.</li>')
    pieces = [p for p in f['pieces'] if not p['nom'].startswith('_')][:8]
    glyph = {'fonction': 'ƒ', 'classe': 'C', 'méthode': 'm', 'interface': 'I', 'type': 'T'}
    pc = ''.join(f'<div class="piece"><div class="h"><span class="s">{glyph.get(p.get("sorte"), "ƒ")}</span><span class="nm">{e(p["nom"])}</span><span class="lg">ligne {p["ligne"]}</span></div><div class="rl">{e(p.get("role") or "Pas encore expliquée.")}</div></div>' for p in pieces)
    langue = {'.py': 'Python', '.ts': 'TypeScript', '.js': 'JavaScript'}.get(posixpath.splitext(c)[1], f['genre'])
    corps1 = f'''{barre(" / ".join(e(x) for x in [nom] + c.split("/")[:-1]) + f" / <b>{e(court(c))}</b>", min(3, c.count("/") + 1))}
<div class="corps"><h1 class="titre">{e(court(c))}</h1><div class="puces"><span class="p">{langue}</span><span class="p">{f["lignes"]} lignes</span><span class="p">{len(f["pieces"])} partie{"s" if len(f["pieces"]) > 1 else ""}</span><span class="p">copier le chemin</span></div>
<p class="portrait">{e(f["resume"])}</p>{f'<p class="detail">{e(f["detail"])}</p>' if f.get("detail") else ''}
{f'<div class="encours"><i></i><span><b>{e(en_cours[c])}</b> modifie ce fichier en ce moment, dans sa copie de travail.</span></div>' if c in en_cours else ''}
<div class="sec">Où il se place <i>en haut qui s'en sert · en bas ce qu'il prend · sur chaque flèche, quoi</i></div>{sch2}
{f'<p class="legende">Il prend aussi dans {", ".join(f"<code>{e(court(d))}</code>" for d in autres_deps)}.</p>' if autres_deps else ''}
<div class="impact"><div><b>{len(appel)}</b><span>s'en servent</span></div><div><b>{len(touches)}</b><span>touchés en tout</span></div><div><b>{len(deps)}</b><span>dont il se sert</span></div><div><b>{len(tests)}</b><span>fichiers de tests</span></div></div>
<div class="sec">Avant de le modifier <i>calculé d'après les liens</i></div><div class="prudence"><span class="g">!</span><ul>{"".join(faits)}</ul></div>
<div class="sec">Ses parties <i>{len(f["pieces"])}{" · les 8 premières" if len(pieces) == 8 else ""}</i></div><div class="parties">{pc}</div></div>'''
    open(f'/home/user/atelier/maquettes/code-{nom}-fichier.html', 'w').write(page(nom, corps1, arbre(carte, c, ouverts | {posixpath.dirname(c) + "/"}, en_cours), 1150 + len(rangs2) * 176 + len(pieces) // 2 * 110))
    print(nom, 'départ', repr(pref), 'rangs', [len(r) for r in rangs], 'socle', socle, 'autres', len(autres), 'isolés', len(isoles))

def portrait_lisezmoi(depot):
    for n in ('LISEZMOI.md', 'README.md', 'readme.md'):
        p = Path(depot) / n
        if p.is_file():
            for bloc in p.read_text().split('\n\n'):
                b = bloc.strip()
                if b and not b.startswith('#'): return e(b.split('\n')[0])
    return ''

ca = json.load(open('/tmp/claude-0/carte-atelier.json'))
generer('atelier', '/home/user/atelier', ca, {'atelier/serveur.py': 'B', 'atelier/moteur.py': 'A'}, 'atelier/serveur.py', portrait_lisezmoi('/home/user/atelier'))
cs = json.load(open('/tmp/claude-0/carte-sdk.json'))
generer('claude-agent-sdk', '/tmp/claude-0/sdkproj', cs, {}, 'claude_agent_sdk/client.py', '')
