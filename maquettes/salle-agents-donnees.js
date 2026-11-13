/* Maquettes V1 : les données d'exemple et les morceaux communs aux trois pages
   (salle-agents-a.html, salle-agents-b.html, depot.html). Rien n'est lu sur le réseau.

   L'instant montré : 14:47, un chantier de douze tâches, six places d'écriture toutes prises.
   Le calendrier tient la règle des places du moteur (jamais plus de six tâches en écriture) :
   13:41 A et B partent ; 14:02 A entre dans main, C D E F partent ; 14:16 B entre, G et H partent ;
   14:25 C passe en relecture, I part ; 14:31 D passe en relecture, J part ; 14:41 D est refusée ;
   14:42 C, acceptée, bute sur un conflit à l'entrée, et F passe en relecture, ouvrier resté ouvert ;
   14:43 E passe en relecture et D reprend sa place ; 14:45 H passe en relecture et C reprend la sienne.
   K et L sont prêtes depuis 14:16 : une reprise passe avant une tâche neuve, elles attendent encore. */
const EXEMPLE = {
  projet: "Réservations de salles",
  heure: "14:47",
  branche: "main",
  places: 6,
  agentsMax: 9,
  budget: { plafond: 40, depense: 17.3 }, // bientôt : le budget en dollars du chantier
  orchestrateur: "Fable · élevé",
  /* etat : fusionnee, ecrit, corrige, conflit, ouvert, verif, toi, file.
     ouvrier / verificateur : l'agent en marche, son modèle, son effort, depuis combien de minutes. */
  taches: [
    { id: "A", titre: "Schéma des salles", etat: "fusionnee", modele: "Opus", effort: "élevé", cout: 1.84,
      depart: "13:41", entree: "14:02", commit: "a41c9e2", base: "3f9a1c7",
      depot: "Dans main depuis 14:02 (a41c9e2). Main n'avait pas bougé : entrée directe, branche supprimée." },
    { id: "B", titre: "Squelette de l'API", etat: "fusionnee", modele: "Sonnet", effort: "moyen", cout: 0.62,
      depart: "13:41", entree: "14:16", commit: "e9b2f40", base: "3f9a1c7",
      depot: "Dans main depuis 14:16 (e9b2f40), après fusion de main dans la branche et contrôles rejoués." },
    { id: "C", titre: "Annuler une réservation", etat: "conflit", modele: "Opus", effort: "élevé", cout: 2.91,
      ouvrier: { depuis: 2 }, depart: "14:02", base: "c58d1aa", fichiers: 4, conflit: "14:42",
      phase: "L'ouvrier reprend son travail après un refus (tentative 1)",
      detail: "Acceptée à 14:41, puis conflit à l'entrée dans main : src/routes.py.",
      depot: "Conflit à l'entrée (14:42) dans src/routes.py. Rien n'est entré : la copie est reposée sur main, l'ouvrier résout." },
    { id: "D", titre: "Courriel de confirmation", etat: "corrige", modele: "Opus", effort: "élevé", cout: 2.36,
      ouvrier: { depuis: 4 }, depart: "14:02", base: "7d03b5e", retard: 3, fichiers: 5,
      phase: "L'ouvrier reprend son travail après un refus (tentative 1)",
      detail: "Refusée à 14:41 par le vérificateur : le courriel part même si la réservation échoue.",
      depot: "5 fichiers modifiés, pas encore enregistrés. En retard de 3 enregistrements sur main." },
    { id: "E", titre: "Plafond par personne", etat: "verif", modele: "Opus", effort: "élevé", cout: 1.75,
      verificateur: { modele: "Fable", effort: "élevé", depuis: 4 }, depart: "14:02", base: "7d03b5e", retard: 3, fichiers: 3,
      phase: "Le vérificateur relit (Fable, effort élevé)",
      depot: "3 fichiers modifiés, relus dans .atelier/verifications/E. En retard de 3 enregistrements sur main." },
    { id: "F", titre: "Droits d'accès par rôle", etat: "ouvert", modele: "Opus", effort: "élevé", cout: 2.2,
      ouvrier: { depuis: 5 }, verificateur: { modele: "Fable", effort: "élevé", depuis: 5 }, depart: "14:02", base: "7d03b5e", retard: 3, fichiers: 7,
      phase: "Le vérificateur relit (Fable, effort élevé)",
      depot: "7 fichiers modifiés, relus dans .atelier/verifications/F. En retard de 3 enregistrements sur main." },
    { id: "G", titre: "Export PDF du planning", etat: "toi", modele: "Opus", effort: "élevé", cout: 1.15,
      ouvrier: { depuis: 7 }, depart: "14:16", base: "c58d1aa", fichiers: 2,
      phase: "L'ouvrier travaille (tentative 1)",
      detail: "Attend ton autorisation depuis 14:40 pour lancer « uv add reportlab ».",
      depot: "2 fichiers modifiés, pas encore enregistrés. L'ouvrier attend ton autorisation." },
    { id: "H", titre: "Recherche des salles", etat: "verif", modele: "Opus", effort: "élevé", cout: 0.87,
      verificateur: { modele: "Fable", effort: "élevé", depuis: 2 }, depart: "14:16", base: "c58d1aa", fichiers: 4,
      phase: "Le vérificateur relit (Fable, effort élevé)",
      depot: "4 fichiers modifiés, relus dans .atelier/verifications/H. À jour avec main." },
    { id: "I", titre: "Calcul des créneaux", etat: "ecrit", modele: "Opus", effort: "élevé", cout: 3.12,
      ouvrier: { depuis: 22 }, depart: "14:25", base: "c58d1aa", fichiers: 6,
      phase: "L'ouvrier travaille (tentative 1)", etape: "Étape 3/4 : créneaux à cheval sur minuit",
      depot: "6 fichiers modifiés, pas encore enregistrés. À jour avec main." },
    { id: "J", titre: "Import CSV", etat: "ecrit", modele: "Sonnet", effort: "moyen", cout: 0.48,
      ouvrier: { depuis: 16 }, depart: "14:31", base: "c58d1aa", fichiers: 2,
      phase: "L'ouvrier travaille (tentative 1)", etape: "Étape 2/3 : lecture du fichier CSV",
      depot: "2 fichiers modifiés, pas encore enregistrés. À jour avec main." },
    { id: "K", titre: "Rappel la veille", etat: "file", modele: "Sonnet", effort: "moyen", cout: 0, attend: 31,
      depot: "Pas encore de branche : tache/K sera créée à son départ." },
    { id: "L", titre: "Journal d'audit", etat: "file", modele: "Opus", effort: "élevé", cout: 0, attend: 31,
      depot: "Pas encore de branche : tache/L sera créée à son départ." },
  ],
  /* Ce qui se lit dans git dès maintenant. */
  depot: {
    distant: "github.com/exemple/reservations",
    origine: "7d03b5e", tete: "c58d1aa", avance: 3, retard: 0, dernierEnvoi: "14:02", envoiRate: "14:16",
    probleme: "Pas d'accès au réseau, ou nom de site mal écrit.", // la phrase réelle de expliquer_refus_git
    enregistrements: [
      { h: "c58d1aa", t: "14:16", m: "Cahier : B enregistrée", marque: "main" },
      { h: "e9b2f40", t: "14:16", m: "Merge commit '7d03b5e' into tache/B" },
      { h: "5b1e0d4", t: "14:16", m: "B : Squelette de l'API" },
      { h: "7d03b5e", t: "14:02", m: "Cahier : A enregistrée", marque: "origin/main" },
      { h: "a41c9e2", t: "14:02", m: "A : Schéma des salles" },
      { h: "3f9a1c7", t: "13:38", m: "Cahier du chantier" },
    ],
    partages: [
      { motif: "CHANGELOG.md", fusion: "union", phrase: "les lignes des deux côtés sont gardées. Réuni sans conflit à l'entrée de B." },
      { motif: "src/routes.py", fusion: "git", phrase: "un conflit revient à l'ouvrier, une fois par départ. C'est le cas de C." },
    ],
  },
  fil: [
    { t: "14:45", id: "C", m: "Conflit dans src/routes.py : l'ouvrier reprend sa place." },
    { t: "14:45", id: "H", m: "Vérificateur lancé (Fable, effort élevé)." },
    { t: "14:43", id: "D", m: "Refusée par le vérificateur : l'ouvrier corrige." },
    { t: "14:40", id: "G", m: "Demande une autorisation." },
  ],
};

/* Chaque état a son mot, son signe et son trait : jamais la couleur seule. */
const ETATS = {
  fusionnee: { mot: "dans main", signe: "fusionnee" },
  ecrit: { mot: "écrit", signe: "ecrit" },
  corrige: { mot: "corrige après refus", signe: "corrige" },
  conflit: { mot: "conflit de fusion", signe: "conflit" },
  ouvert: { mot: "reste ouvert", signe: "ouvert" },
  verif: { mot: "en relecture", signe: "verif" },
  toi: { mot: "t'attend", signe: "toi" },
  file: { mot: "attend une place", signe: "file" },
};
const SIGNES = {
  ecrit: '<path d="M3 13l.8-3.2L10.6 3 13 5.4l-6.8 6.8z"/><path d="M9 4.6l2.4 2.4"/>',
  corrige: '<path d="M4.2 7.2a4.4 4.4 0 1 1 1 4.2"/><path d="M3.4 3.6v3.6H7"/>',
  conflit: '<path d="M4 2v2.4c0 2.6 4 2.4 4 5"/><path d="M12 2v2.4c0 2.6-4 2.4-4 5"/><path d="M6.1 10.9l3.8 3.4M9.9 10.9l-3.8 3.4"/>',
  verif: '<circle cx="7" cy="7" r="4"/><path d="M10 10l3.6 3.6"/>',
  ouvert: '<circle cx="8" cy="8" r="5.6"/><path d="M6.5 5.8v4.4M9.5 5.8v4.4"/>',
  toi: '<path d="M8 2.8v6.4" stroke-width="2"/><circle cx="8" cy="12.6" r="1.1" fill="currentColor" stroke="none"/>',
  file: '<circle cx="8" cy="8" r="5.2" stroke-dasharray="2 2.5"/>',
  fusionnee: '<path d="M3.2 8.6l3.1 3.1 6.4-7"/>',
  porte: '<path d="M3 13.5V3.5h10v10"/><path d="M6.4 13.5V7.4h3.2v6.1"/>',
  orchestre: '<circle cx="8" cy="8" r="5.4" stroke-opacity=".3"/><path d="M8 2.6A5.4 5.4 0 0 1 13.4 8"/>',
  branche: '<circle cx="4.5" cy="3.6" r="1.6"/><circle cx="4.5" cy="12.4" r="1.6"/><circle cx="11.5" cy="5.6" r="1.6"/><path d="M4.5 5.2v5.6M11.5 7.2c0 2.6-7 1.4-7 3.6"/>',
  nuage: '<path d="M4.6 12.4a2.9 2.9 0 0 1-.3-5.8 3.9 3.9 0 0 1 7.5 1 2.4 2.4 0 0 1-.4 4.8z"/>',
};
const signe = (nom, taille = 14) =>
  `<svg class="signe" width="${taille}" height="${taille}" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${SIGNES[nom]}</svg>`;

const duree = (m) => `${m} min`;
const dollars = (n) => n.toFixed(2).replace(".", ",");
const E = EXEMPLE;
const T = Object.fromEntries(E.taches.map((t) => [t.id, t]));
const ouvriers = E.taches.filter((t) => t.ouvrier);
const verificateurs = E.taches.filter((t) => t.verificateur);
const enFile = E.taches.filter((t) => t.etat === "file");
const fusionnees = E.taches.filter((t) => t.etat === "fusionnee");
const attendues = E.taches.filter((t) => t.etat === "toi");
const pluriel = (n, mot) => `${n} ${mot}${n > 1 ? "s" : ""}`;

/* L'en-tête du tableau de bord, avec l'onglet de la page. « Dépôt » est l'onglet proposé : il ne
   s'affiche que sur sa maquette. */
function entete(actif, piste) {
  const onglets = ["Accueil", "Conversation", "Chantier", "Salle", "Plan", "Code", ...(actif === "Dépôt" ? ["Dépôt"] : [])];
  return `<header class="tete"><span class="mot">ATELIER</span><span class="projet">${E.projet}</span>
    <nav aria-label="Onglets">${onglets.map((o) => `<a${o === actif ? ' class="on" aria-current="page"' : ""}>${o}${o === "Conversation" ? '<i class="pt"></i>' : ""}</a>`).join("")}</nav>
    <span class="pousse"></span><span class="vif"><i></i>${ouvriers.length + verificateurs.length} agents en marche</span><span class="demo">${piste}</span></header>`;
}

/* Le bandeau de la Salle : la phrase d'abord, puis les comptes, chacun avec son dessin. */
function bandeau() {
  const cases = (n, total, classe = "") => Array.from({ length: total }, (_, i) => `<i class="${i < n ? "pris" : ""} ${classe}"></i>`).join("");
  const part = Math.round((E.budget.depense / E.budget.plafond) * 100);
  return `<section class="bandeau panneau" aria-label="Les agents en ce moment">
    <div class="resume"><span class="etiquette">En ce moment · ${E.heure}</span>
      <p class="phrase">${ouvriers.length} ouvriers sur ${E.places} places, ${pluriel(verificateurs.length, "vérificateur")}, ${enFile.length} tâches en attente.</p>
      <p class="calme">Toutes les places sont prises. Une autorisation t'attend.</p></div>
    <div class="cpt"><span class="etiquette">Places d'écriture</span><b><span class="points">${ouvriers.length}</span><small>/ ${E.places}</small></b><span class="cases">${cases(ouvriers.length, E.places)}</span></div>
    <div class="cpt"><span class="etiquette">Agents en marche</span><b><span class="points">${ouvriers.length + verificateurs.length}</span><small>/ ${E.agentsMax}</small></b><span class="cases">${cases(ouvriers.length, ouvriers.length)}<em></em>${cases(verificateurs.length, verificateurs.length, "rond")}</span><span class="sous">${ouvriers.length} ouvriers, ${pluriel(verificateurs.length, "vérificateur")}</span></div>
    <div class="cpt"><span class="etiquette">En attente</span><b><span class="points">${enFile.length}</span></b><span class="cases">${cases(0, enFile.length, "vide")}</span><span class="sous">d'une place</span></div>
    <div class="cpt attend"><span class="etiquette">T'attend</span><b><span class="points">${attendues.length}</span></b><span class="sous">${attendues.map((t) => t.id).join(", ")} · autorisation</span></div>
    <div class="cpt"><span class="etiquette">Dans ${E.branche}</span><b><span class="points">${fusionnees.length}</span><small>/ ${E.taches.length}</small></b><span class="cases fin">${cases(fusionnees.length, E.taches.length)}</span></div>
    <div class="cpt"><span class="etiquette">Budget <i class="bientot">bientôt</i></span><b><span class="points">${dollars(E.budget.depense)}</span><small>/ ${E.budget.plafond} $</small></b><span class="jauge"><i style="width:${part}%"></i></span></div>
  </section>`;
}

/* La colonne de droite des deux pistes : ce qui t'attend, ce qui n'est pas encore dans le moteur, le fil. */
function cote(lecture) {
  const g = attendues[0];
  return `<aside class="cote">
    <section class="panneau attente"><div class="entre"><span class="etiquette ambre">● Ce qui t'attend</span><span class="etiquette">14:40</span></div>
      <p class="fort"><b class="id">${g.id}</b> L'ouvrier veut lancer <code>uv add reportlab</code></p>
      <p class="calme">${g.titre}. Il garde sa place d'écriture tant que tu n'as pas répondu.</p>
      <div class="boutons"><span class="btn attend">Une fois</span><span class="btn">Toujours</span><span class="btn">Refuser</span></div></section>
    <section class="panneau lire"><span class="etiquette">Lecture</span><ul class="lecture">${lecture}</ul></section>
    <section class="panneau suite"><span class="etiquette">Fil</span><ul class="fil">${E.fil.map((f) => `<li><time>${f.t}</time><b>${f.id}</b><span>${f.m}</span></li>`).join("")}</ul></section>
  </aside>`;
}

/* ---------- Le dessin en perspective : la même colonne de lumière que la Salle actuelle ---------- */
const BLEU = "#8297c4", BLANC = "#ffffff", AMBRE = "#e8953a", GRIS = "#dcdcdc";
const COULEUR = { fusionnee: BLANC, ecrit: BLEU, corrige: BLEU, conflit: BLEU, ouvert: BLEU, verif: BLEU, toi: AMBRE, file: GRIS };
const HAUTEUR = { moyen: 1.3, "élevé": 1.8 };
function melange(hex, t) {
  const fond = [14, 18, 32], c = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));
  return `rgb(${c.map((v, i) => Math.round(fond[i] + (v - fond[i]) * t)).join(",")})`;
}
/* Une colonne posée en (px, py) à l'écran. genre : plein, contour (ouvert, en veille), pointille (pas partie). */
function colonne(px, py, S, w, h, c, genre = "plein") {
  const P = (dx, dy, z) => `${(px + (dx - dy) * S * 0.866).toFixed(1)},${(py + (dx + dy) * S * 0.5 - z * S).toFixed(1)}`;
  const dessus = [P(-w, -w, h), P(w, -w, h), P(w, w, h), P(-w, w, h)].join(" ");
  const gauche = [P(-w, w, 0), P(w, w, 0), P(w, w, h), P(-w, w, h)].join(" ");
  const droite = [P(w, -w, 0), P(w, w, 0), P(w, w, h), P(w, -w, h)].join(" ");
  if (genre === "pointille") return [gauche, droite, dessus].map((f) => `<polygon points="${f}" fill="#0e1220" stroke="rgba(220,220,220,.34)" stroke-dasharray="3 3"/>`).join("");
  if (genre === "contour") return [gauche, droite].map((f) => `<polygon points="${f}" fill="#0e1220" stroke="${c}" stroke-opacity=".8" stroke-linejoin="round"/>`).join("") + `<polygon points="${dessus}" fill="${melange(c, 0.3)}" stroke="${c}" stroke-linejoin="round"/>`;
  const [ax, ay] = P(w, w, 0).split(","), [bx, by] = P(w, w, h).split(",");
  return `<polygon points="${gauche}" fill="${melange(c, 0.42)}"/><polygon points="${droite}" fill="${melange(c, 0.26)}"/>
    <polygon points="${dessus}" fill="${c}" opacity=".5" filter="url(#flou)"/><polygon points="${dessus}" fill="${c}"/>
    <line x1="${ax}" y1="${ay}" x2="${bx}" y2="${by}" stroke="#fff" stroke-opacity=".45"/>`;
}
/* L'anneau au sol, en deux moitiés : l'arrière passe derrière la colonne, l'avant devant.
   Son trait dit l'état : tirets épais (écrit), points creux (refus), deux anneaux décalés (conflit),
   plein épais (t'attend), pointillé fin (pas partie), fin (relecture), plein (dans main). */
function anneau(px, py, rx, etat, avant) {
  const ry = rx * 0.577, c = COULEUR[etat];
  const demi = (k, dx = 0) => `M${(px + dx - rx * k).toFixed(1)},${py.toFixed(1)} A${(rx * k).toFixed(1)},${(ry * k).toFixed(1)} 0 0 ${avant ? 0 : 1} ${(px + dx + rx * k).toFixed(1)},${py.toFixed(1)}`;
  const arc = (k, extra, dx) => `<path d="${demi(k, dx)}" fill="none" stroke="${c}" ${extra}/>`;
  if (etat === "file") return arc(1, 'stroke-width="1" opacity=".4" stroke-dasharray="3 4"');
  if (etat === "corrige") {
    let points = "";
    for (let i = 0; i < 16; i++) {
      const a = (i / 16) * 2 * Math.PI + 0.2, y = Math.sin(a);
      if (avant !== y > 0) continue;
      points += `<circle cx="${(px + Math.cos(a) * rx).toFixed(1)}" cy="${(py + y * ry).toFixed(1)}" r="2.3" fill="#0b0f1b" stroke="${c}" stroke-width="1.2"/>`;
    }
    return points + arc(0.6, 'stroke-width="1" opacity=".5"');
  }
  if (etat === "conflit") return arc(0.8, 'stroke-width="1.5" opacity=".95"', -8) + arc(0.8, 'stroke-width="1.5" opacity=".95"', 8);
  if (etat === "toi") return arc(1, 'stroke-width="1.5" opacity=".9"') + arc(0.68, 'stroke-width="3.2" opacity=".75"');
  if (etat === "ecrit") return arc(1, 'stroke-width="1.5" opacity=".8"') + arc(0.68, 'stroke-width="3" opacity=".55" stroke-dasharray="12 7"');
  if (etat === "fusionnee") return arc(1, 'stroke-width="1.5" opacity=".85"') + arc(0.68, 'stroke-width="1" opacity=".5"');
  return arc(1, 'stroke-width="1.2" opacity=".7"'); // ouvert, verif
}
/* Le vérificateur : une colonne fine, cerclée d'une lentille. */
function verificateurDessin(px, py, S, c = BLEU) {
  const h = 1.55, haut = py - h * S * 0.8;
  return `${colonne(px, py, S, 0.2, h, c)}<ellipse cx="${px.toFixed(1)}" cy="${haut.toFixed(1)}" rx="${(S * 0.46).toFixed(1)}" ry="${(S * 0.26).toFixed(1)}" fill="none" stroke="${c}" stroke-width="1.6"/>`;
}
const DEFS = `<defs><filter id="flou" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="4"/></filter>
  <filter id="halo" x="-100%" y="-100%" width="300%" height="300%"><feGaussianBlur stdDeviation="11"/></filter>
  <radialGradient id="fondu" cx="50%" cy="52%" r="62%"><stop offset="0" stop-color="#fff"/><stop offset=".75" stop-color="#fff" stop-opacity=".55"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></radialGradient>
  <mask id="masque"><rect width="100%" height="100%" fill="url(#fondu)"/></mask></defs>`;
/* La grille du sol, en losanges, effacée vers les bords. */
function grille(l, h, pas = 30) {
  let lignes = "";
  const dx = pas * 0.866, dy = pas * 0.5, n = Math.ceil((l + h * 1.8) / dx);
  for (let i = -n; i <= n; i++) {
    lignes += `<line x1="${(i * 2 * dx).toFixed(1)}" y1="0" x2="${(i * 2 * dx + (h / dy) * dx).toFixed(1)}" y2="${h}"/><line x1="${(i * 2 * dx).toFixed(1)}" y1="0" x2="${(i * 2 * dx - (h / dy) * dx).toFixed(1)}" y2="${h}"/>`;
  }
  return `<g mask="url(#masque)" stroke="rgba(255,255,255,.05)">${lignes}</g>`;
}
/* Une ligne des listes en écran étroit : le signe, la tâche, son état en mots, qui y travaille et depuis quand. */
function ligne(t) {
  const e = ETATS[t.etat];
  const v = t.verificateur ? `<small>${signe("verif", 12)} relu par ${t.verificateur.modele} · ${t.verificateur.effort} · ${duree(t.verificateur.depuis)}</small>` : "";
  const qui = t.etat === "fusionnee" ? `entrée à ${t.entree} · ${t.commit}`
    : t.etat === "file" ? `${t.modele} · ${t.effort} · prête depuis ${duree(t.attend)}`
    : t.etat === "verif" ? "l'ouvrier a fini, sa place est rendue"
    : t.etat === "ouvert" ? `${t.modele} · ${t.effort} · garde sa place`
    : `${t.modele} · ${t.effort} · ${duree(t.ouvrier.depuis)}`;
  return `<li class="ligne ${t.etat}"><span class="noeud">${signe(e.signe)}</span><div><p><b class="id">${t.id}</b>${t.titre}</p>
    <p class="mot">${e.mot}${t.etat === "ouvert" ? ' <i class="bientot">bientôt</i>' : ""}</p><small>${qui}</small>${v}${t.detail ? `<small class="detail">${t.detail}</small>` : ""}</div></li>`;
}
/* La lecture du dessin, la même pour les deux pistes. */
const LECTURE = `<li><svg width="22" height="26" viewBox="-11 -22 22 28">${colonne(0, 0, 13, 0.42, 1.3, BLEU)}</svg><span>Colonne large : un ouvrier. Sa hauteur dit l'effort.</span></li>
  <li><svg width="22" height="28" viewBox="-11 -24 22 30">${verificateurDessin(0, 0, 14)}</svg><span>Colonne fine cerclée : un vérificateur. Il ne prend pas de place.</span></li>
  <li><svg width="22" height="26" viewBox="-11 -22 22 28">${colonne(0, 0, 13, 0.42, 1.3, GRIS, "pointille")}</svg><span>Pointillé : la tâche n'est pas encore partie.</span></li>
  <li class="mots"><i class="bientot">bientôt</i> Décidé pour le chantier suivant, pas encore dans le moteur.</li>`;
/* Écran étroit : l'onglet de la page reste en vue dans l'en-tête, qui défile. */
window.addEventListener("load", () => { const a = document.querySelector(".tete .on"); if (a) a.scrollIntoView({ inline: "center", block: "nearest" }); });
