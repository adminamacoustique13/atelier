/* Maquettes V1 : les données d'exemple et les morceaux communs aux trois pages
   (salle-agents-a.html, salle-agents-b.html, depot.html). Rien n'est lu sur le réseau.

   L'instant montré : 14:47, un chantier de douze tâches, six places d'écriture toutes prises.
   Le calendrier tient la règle des places du moteur (jamais plus de six tâches en écriture, neuf agents) :
   13:41 A et B partent ; 14:02 A entre dans main, C D E F partent ; 14:16 B entre, G et H partent ;
   14:25 C passe en relecture, I part ; 14:31 D passe en relecture, J part ; 14:38 J passe en relecture,
   K part ; 14:41 D est refusée et attend une place ; 14:42 F passe en relecture : son ouvrier reste ouvert
   mais rend sa place et son jeton (bientôt), D la prend ; C, acceptée, bute sur un conflit à l'entrée ;
   14:43 E passe en relecture, C prend sa place ; 14:44 J est refusée, son travail est gardé (bientôt) ;
   14:45 H passe en relecture, l'ouvrier de la sous-tâche J.1 prend sa place.
   L est prête depuis 14:16 : une reprise passe avant une tâche neuve, elle attend encore. */
const EXEMPLE = {
  projet: "Réservations de salles",
  heure: "14:47",
  branche: "main",
  places: 6,
  agentsMax: 9,
  budget: { plafond: 40, depense: 17.3 }, // bientôt : le budget en dollars du chantier
  orchestrateur: { modele: "Fable", effort: "élevé" },
  /* etat de la tâche : fusionnee, ecrit, corrige, conflit, verif, toi, file.
     agents : qui y travaille. role : ouvrier, sous (ouvrier de sous-tâche), verificateur.
     etat de l'agent : celui de la tâche, ou « ouvert » pour l'ouvrier qui attend un verdict.
     sansPlace : il ne tient ni place ni jeton, et ne compte pas parmi les agents en marche. */
  taches: [
    { id: "A", titre: "Schéma des salles", etat: "fusionnee", cout: 1.84, agents: [],
      depart: "13:41", entree: "14:02", commit: "a41c9e2",
      fait: "Main n'avait pas bougé : entrée directe. Branche supprimée." },
    { id: "B", titre: "Squelette de l'API", etat: "fusionnee", cout: 0.62, agents: [],
      depart: "13:41", entree: "14:16", commit: "e9b2f40",
      fait: "Main fusionnée dans la branche, contrôles rejoués." },
    { id: "C", titre: "Annuler une réservation", etat: "conflit", cout: 2.91, effort: "élevé",
      agents: [{ role: "ouvrier", etat: "conflit", modele: "Opus", effort: "élevé", depuis: 4 }],
      depart: "14:02", conflit: "14:42",
      phase: "L'ouvrier reprend son travail après un refus (tentative 1)",
      detail: "Acceptée à 14:41, puis conflit à l'entrée dans main : src/routes.py.",
      fait: "Conflit à l'entrée dans src/routes.py : rien n'est entré." },
    { id: "D", titre: "Courriel de confirmation", etat: "corrige", cout: 2.36, effort: "élevé",
      agents: [{ role: "ouvrier", etat: "corrige", modele: "Opus", effort: "élevé", depuis: 5 }],
      depart: "14:02", retard: 3,
      phase: "L'ouvrier reprend son travail après un refus (tentative 1)",
      detail: "Refusée à 14:41 par le vérificateur : le courriel part même si la réservation échoue.",
      fait: "5 fichiers modifiés, pas encore enregistrés." },
    { id: "E", titre: "Plafond par personne", etat: "verif", cout: 1.75, effort: "élevé",
      agents: [{ role: "verificateur", etat: "verif", modele: "Fable", effort: "élevé", depuis: 4 }],
      depart: "14:02", retard: 3,
      phase: "Le vérificateur relit (Fable, effort élevé)",
      fait: "3 fichiers, relus dans .atelier/verifications/E." },
    { id: "F", titre: "Droits d'accès", etat: "verif", cout: 2.2, effort: "élevé",
      agents: [{ role: "verificateur", etat: "verif", modele: "Fable", effort: "élevé", depuis: 5 },
        { role: "ouvrier", etat: "ouvert", modele: "Opus", effort: "élevé", depuis: 5, sansPlace: true, bientot: true }],
      depart: "14:02", retard: 3,
      phase: "Le vérificateur relit (Fable, effort élevé)",
      detail: "L'ouvrier reste ouvert pour recevoir le verdict. Il a rendu sa place et son jeton.",
      fait: "7 fichiers, relus dans .atelier/verifications/F." },
    { id: "G", titre: "Export PDF du planning", etat: "toi", cout: 1.15, effort: "élevé", demande: { heure: "14:40", commande: "uv add reportlab" },
      agents: [{ role: "ouvrier", etat: "toi", modele: "Opus", effort: "élevé", depuis: 7 }],
      depart: "14:16",
      phase: "L'ouvrier travaille (tentative 1)",
      detail: "Attend ton autorisation depuis 14:40 pour lancer « uv add reportlab ».",
      fait: "2 fichiers modifiés, pas encore enregistrés." },
    { id: "H", titre: "Recherche des salles", etat: "verif", cout: 0.87, effort: "élevé",
      agents: [{ role: "verificateur", etat: "verif", modele: "Fable", effort: "élevé", depuis: 2 }],
      depart: "14:16",
      phase: "Le vérificateur relit (Fable, effort élevé)",
      fait: "4 fichiers, relus dans .atelier/verifications/H." },
    { id: "I", titre: "Calcul des créneaux", etat: "ecrit", cout: 2.62, effort: "élevé",
      agents: [{ role: "ouvrier", etat: "ecrit", modele: "Opus", effort: "élevé", depuis: 22 }],
      depart: "14:25",
      phase: "L'ouvrier travaille (tentative 1)",
      fait: "6 fichiers modifiés, pas encore enregistrés." },
    { id: "J", titre: "Journal d'audit", etat: "ecrit", cout: 0.9, effort: "élevé",
      agents: [{ role: "sous", etat: "ecrit", mot: "écrit ce qui reste", modele: "Opus", effort: "élevé", depuis: 2, bientot: true }],
      depart: "14:31", refus: "14:44",
      phase: "Sous-tâche J.1 : ce qui reste après le refus",
      detail: "Refusée à 14:44 : les suppressions ne sont pas journalisées. Le travail est gardé ; la sous-tâche J.1 ne règle que ce reste.",
      fait: "3 fichiers gardés après le refus de 14:44." },
    { id: "K", titre: "Import CSV", etat: "ecrit", cout: 0.08, effort: "moyen",
      agents: [{ role: "ouvrier", etat: "ecrit", modele: "Sonnet", effort: "moyen", depuis: 9 }],
      depart: "14:38",
      phase: "L'ouvrier travaille (tentative 1)",
      fait: "1 fichier modifié, pas encore enregistré." },
    { id: "L", titre: "Rappel la veille", etat: "file", cout: 0, effort: "moyen", modele: "Sonnet", attend: 31, agents: [],
      fait: "Pas encore de branche : tache/L sera créée à son départ." },
  ],
  /* Ce qui se lit dans git dès maintenant. */
  depot: {
    distant: "github.com/exemple/reservations",
    origine: "7d03b5e", tete: "c58d1aa", avance: 3, dernierEnvoi: "14:02", envoiRate: "14:16",
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
      { motif: "CHANGELOG.md", fusion: "union", phrase: "Les lignes des deux côtés sont gardées. Réuni sans conflit à l'entrée de B." },
      { motif: "src/routes.py", fusion: "git", phrase: "Un conflit revient à l'ouvrier, une fois par départ. C'est le cas de C." },
    ],
  },
  fil: [
    { t: "14:45", id: "J", role: "sous", m: "Ouvrier de sous-tâche lancé sur ce qui reste.", bientot: true },
    { t: "14:45", id: "H", role: "verificateur", m: "Vérificateur lancé (Fable, effort élevé)." },
    { t: "14:43", id: "C", role: "ouvrier", m: "Conflit dans src/routes.py : l'ouvrier reprend une place." },
    { t: "14:42", id: "F", role: "ouvrier", creux: true, m: "L'ouvrier reste ouvert et rend sa place.", bientot: true },
  ],
};

/* ---------- Les rôles : une silhouette, une teinte et un nom chacun ----------
   Orchestrateur : pyramide, gris clair. Ouvrier : colonne carrée, bleu acier. Vérificateur : colonne ronde
   cerclée d'une lentille, vert d'eau (la seule teinte ajoutée). Ouvrier de sous-tâche : la colonne de
   l'ouvrier, dont le bas n'est qu'un contour (le travail gardé) et le haut seul est plein. */
const GRIS = "#dcdcdc", BLEU = "#8297c4", VERT = "#79bfae", BLANC = "#ffffff", AMBRE = "#e8953a";
const NEUTRE = "rgba(220,220,220,.5)";
const ROLES = {
  orchestrateur: { nom: "Orchestrateur", pluriel: "Orchestrateur", teinte: GRIS },
  ouvrier: { nom: "Ouvrier", pluriel: "Ouvriers", teinte: BLEU },
  sous: { nom: 'Ouvrier de <span class="nb">sous-tâche</span>', pluriel: "Ouvriers de sous-tâche", teinte: BLEU },
  verificateur: { nom: "Vérificateur", pluriel: "Vérificateurs", teinte: VERT },
};
/* Le signe plat de chaque rôle : triangle, carré, carré entamé, anneau. Le même partout. */
/* Le nom simple de chaque rôle, pour les textes de survol. */
const NOMS = { orchestrateur: "Orchestrateur", ouvrier: "Ouvrier", sous: "Ouvrier de sous-tâche", verificateur: "Vérificateur" };
const MARQUES = {
  orchestrateur: '<path d="M6 1 11.2 10.6H.8z" fill="currentColor"/>',
  ouvrier: '<rect x="1.5" y="1.5" width="9" height="9" rx="1.2" fill="currentColor"/>',
  sous: '<rect x="2.2" y="2.2" width="7.6" height="7.6" rx="1" fill="none" stroke="currentColor" stroke-width="1.4"/><path d="M2.2 2.2h7.6v3.8H2.2z" fill="currentColor"/>',
  verificateur: '<circle cx="6" cy="6" r="3.9" fill="none" stroke="currentColor" stroke-width="2.1"/>',
  ouvert: '<rect x="2.2" y="2.2" width="7.6" height="7.6" rx="1" fill="none" stroke="currentColor" stroke-width="1.4" stroke-dasharray="2 1.6"/>',
};
const marque = (role, taille = 11, creux = false) =>
  `<svg class="marque" width="${taille}" height="${taille}" viewBox="0 0 12 12" style="color:${ROLES[role].teinte}" aria-hidden="true">${MARQUES[creux ? "ouvert" : role]}</svg>`;
/* Le libellé fixe d'un rôle : son signe et son nom en toutes lettres, dans sa teinte. */
const libelle = (role, creux = false, nom = ROLES[role].nom) => `<span class="role r-${role}">${marque(role, 11, creux)}<span>${nom}</span></span>`;
const BIENTOT = '<i class="bientot">bientôt</i>';

/* Chaque état a son mot, son signe et son trait d'anneau : jamais la couleur seule, jamais la silhouette. */
const ETATS = {
  fusionnee: { mot: "dans main", signe: "fusionnee" },
  ecrit: { mot: "écrit", signe: "ecrit" },
  corrige: { mot: "corrige après refus", signe: "corrige" },
  conflit: { mot: "conflit de fusion", signe: "conflit" },
  ouvert: { mot: "attend, sans place", signe: "ouvert" },
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
  suit: '<circle cx="8" cy="8" r="5.4" stroke-opacity=".35"/><path d="M8 2.6A5.4 5.4 0 0 1 13.4 8"/>',
  branche: '<circle cx="4.5" cy="3.6" r="1.6"/><circle cx="4.5" cy="12.4" r="1.6"/><circle cx="11.5" cy="5.6" r="1.6"/><path d="M4.5 5.2v5.6M11.5 7.2c0 2.6-7 1.4-7 3.6"/>',
  nuage: '<path d="M4.6 12.4a2.9 2.9 0 0 1-.3-5.8 3.9 3.9 0 0 1 7.5 1 2.4 2.4 0 0 1-.4 4.8z"/>',
};
const signe = (nom, taille = 14) =>
  `<svg class="signe" width="${taille}" height="${taille}" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${SIGNES[nom]}</svg>`;

const duree = (m) => `${m} min`;
const dollars = (n) => n.toFixed(2).replace(".", ",");
const pluriel = (n, mot) => `${n} ${mot}${n > 1 ? "s" : ""}`;
/* ---------- Second jeu : l'épreuve de charge, 32 places (adresse « ?charge=32 ») ----------
   Le profil règle `paralleles` à 32 : 32 places d'écriture, et 32 + 32 // 2 = 48 agents en marche au plus.
   Soixante tâches à 16:20 : 10 dans main, 32 en écriture (dont 2 qui t'attendent, 3 en correction après
   refus, 2 en reprise de conflit, 2 confiées à un ouvrier de sous-tâche), 12 en relecture, 6 prêtes qui
   attendent une place. 10 + 32 + 12 + 6 = 60 : il ne reste aucune tâche pas encore partie. */
const EXEMPLE_32 = (() => {
  const lots = {
    A: ["Schéma des salles", "Squelette de l'API", "Migrations de la base", "Journal des requêtes", "Lecture de la configuration", "Gestion des erreurs", "Modèle des créneaux", "Modèle des comptes", "Jeu de données d'essai", "Tests de bout en bout"],
    B: ["Calcul des créneaux", "Annuler une réservation", "Réservation récurrente", "Plafond par personne", "Liste d'attente", "Conflits de créneaux", "Fuseaux horaires", "Jours fériés", "Durée minimale", "Salles combinées", "Options de matériel", "Verrou de réservation"],
    C: ["Droits d'accès", "Connexion par courriel", "Mot de passe oublié", "Double authentification", "Profils d'équipe", "Invitations", "Délégation", "Suppression de compte", "Sessions actives", "Export des données"],
    D: ["Tarifs par salle", "Devis", "Facture en PDF", "Remboursement", "Codes de réduction", "Calcul de la TVA", "Relance d'impayé", "Acompte", "Rapprochement bancaire", "Export comptable"],
    E: ["Recherche des salles", "Vue calendrier", "Fiche d'une salle", "Formulaire de réservation", "Tableau de bord", "Courriel de confirmation", "Rappel la veille", "Export du planning", "Import CSV", "Accessibilité au clavier"],
    F: ["Journal d'audit", "Sauvegarde nocturne", "Limite de débit", "Supervision", "Purge des anciennes données", "Traductions", "Aide en ligne", "Notes de version"],
  };
  const O = ["Opus", "élevé"], So = ["Sonnet", "moyen"], Fa = ["Fable", "max"], Fv = ["Fable", "élevé"], Ov = ["Opus", "moyen"];
  /* id : [modèle et effort, minutes, état de l'agent, rôle]. Sans état : il écrit. */
  const places = {
    B1: [O, 31], B2: [O, 18], B3: [O, 6, "corrige"], B4: [So, 12], B5: [O, 27], B6: [O, 3, "conflit"], B7: [Fa, 12], B8: [So, 9],
    B9: [So, 4], B10: [O, 7, "ecrit", "sous"], B11: [O, 22], B12: [O, 15], C1: [O, 41], C2: [O, 9, "corrige"], C3: [So, 14], C4: [O, 8, "toi"],
    C5: [So, 19], C6: [So, 6], C7: [O, 2, "ecrit", "sous"], C8: [O, 24], D1: [O, 5, "conflit"], D2: [So, 11], D3: [So, 13, "toi"], D4: [O, 29],
    D5: [So, 16], D6: [Fa, 20], D7: [O, 10], E1: [O, 17], E2: [O, 33], E3: [So, 8], E4: [O, 4, "corrige"], E5: [O, 21],
  };
  const relues = { C9: [Fv, 6], C10: [Ov, 3], D8: [Fv, 11], D9: [Fv, 2], D10: [Ov, 5], E6: [Ov, 8], E7: [Ov, 1], E8: [Fv, 14], E9: [Ov, 4], E10: [Fv, 7], F1: [Fv, 9], F2: [Ov, 2] };
  const file = { F3: [So, 26], F4: [O, 26], F5: [So, 19], F6: [So, 11], F7: [So, 7], F8: [So, 3] };
  const demandes = { C4: { heure: "16:12", commande: "uv add pyotp" }, D3: { heure: "16:07", commande: "uv add reportlab" } };
  const prix = { Opus: 0.11, Sonnet: 0.03, Fable: 0.19 };
  const taches = [];
  let rang = 0;
  for (const [lot, titres] of Object.entries(lots)) {
    titres.forEach((titre, i) => {
      const id = lot + (i + 1), t = { id, titre, agents: [] };
      rang += 1;
      if (lot === "A") Object.assign(t, { etat: "fusionnee", entree: `14:${String(8 + rang * 5).padStart(2, "0")}`, commit: (0x3a91c07 + rang * 0x51d3b).toString(16).slice(0, 7), cout: 1.4 + (rang % 4) * 0.55 });
      else if (places[id]) {
        const [[modele, effort], depuis, etat = "ecrit", role = "ouvrier"] = places[id];
        const a = { role, etat, modele, effort, depuis };
        if (role === "sous") Object.assign(a, { mot: "écrit ce qui reste", bientot: true });
        Object.assign(t, { etat, effort, agents: [a], demande: demandes[id], cout: Math.round((depuis * prix[modele] + (etat === "corrige" || etat === "conflit" || role === "sous" ? 2.1 : 0)) * 100) / 100 });
      } else if (relues[id]) {
        const [[modele, effort], depuis] = relues[id];
        Object.assign(t, { etat: "verif", effort: "élevé", agents: [{ role: "verificateur", etat: "verif", modele, effort, depuis }], cout: Math.round((1.9 + depuis * prix[modele]) * 100) / 100 });
      } else {
        const [[modele, effort], attend] = file[id];
        Object.assign(t, { etat: "file", modele, effort, attend, cout: 0 });
      }
      taches.push(t);
    });
  }
  const depense = Math.round(taches.reduce((s, t) => s + t.cout, 0) * 100) / 100;
  return {
    projet: "Réservations de salles", heure: "16:20", branche: "main", places: 32, agentsMax: 48,
    budget: { plafond: 300, depense }, orchestrateur: { modele: "Fable", effort: "élevé" }, taches,
    fil: [
      { t: "16:19", id: "E7", role: "verificateur", m: "Vérificateur lancé (Opus, effort moyen)." },
      { t: "16:18", id: "C7", role: "sous", m: "Ouvrier de sous-tâche lancé sur ce qui reste.", bientot: true },
      { t: "16:17", id: "B6", role: "ouvrier", m: "Conflit dans src/routes.py : l'ouvrier reprend une place." },
      { t: "16:12", id: "C4", role: "ouvrier", m: "Demande une autorisation." },
    ],
  };
})();
/* Le jeu affiché : le chantier de douze tâches, ou l'épreuve de charge avec « ?charge=32 » dans l'adresse. */
const CHARGE = new URLSearchParams(location.search).get("charge") === "32";
const E = CHARGE ? EXEMPLE_32 : EXEMPLE;
const T = Object.fromEntries(E.taches.map((t) => [t.id, t]));
const tous = E.taches.flatMap((t) => t.agents.map((a) => ({ ...a, t })));
/* Les comptes, tous tirés des données : six ouvriers sur six places (dont un de sous-tâche), trois
   vérificateurs, neuf agents en marche ; l'ouvrier resté ouvert n'en est pas. */
const enPlace = tous.filter((a) => a.role !== "verificateur" && !a.sansPlace);
const deSousTache = enPlace.filter((a) => a.role === "sous");
const relecteurs = tous.filter((a) => a.role === "verificateur");
const sansPlace = tous.filter((a) => a.sansPlace);
const enMarche = enPlace.length + relecteurs.length;
const enFile = E.taches.filter((t) => t.etat === "file");
const fusionnees = E.taches.filter((t) => t.etat === "fusionnee");
const attendues = E.taches.filter((t) => t.etat === "toi");
const motDe = (a) => a.mot || ETATS[a.etat].mot;

/* L'en-tête du tableau de bord, avec l'onglet de la page. « Dépôt » est l'onglet proposé : il ne
   s'affiche que sur sa maquette. */
function entete(actif, piste) {
  const onglets = ["Accueil", "Conversation", "Chantier", "Salle", "Plan", "Code", ...(actif === "Dépôt" ? ["Dépôt"] : [])];
  return `<header class="tete"><span class="mot">ATELIER</span><span class="projet">${E.projet}</span>
    <nav aria-label="Onglets">${onglets.map((o) => `<a${o === actif ? ' class="on" aria-current="page"' : ""}>${o}${o === "Conversation" ? '<i class="pt"></i>' : ""}</a>`).join("")}</nav>
    <span class="pousse"></span><span class="vif"><i></i>${enMarche} agents en marche</span><span class="demo">${piste}</span></header>`;
}

/* Le bandeau de la Salle : la phrase, puis un compte par rôle avec son signe, puis les autres comptes. */
function bandeau() {
  const n = (k, quoi) => Array.from({ length: k }, () => quoi).join("");
  const part = Math.round((E.budget.depense / E.budget.plafond) * 100);
  const dense = enPlace.length > 12 ? " dense" : "", taille = dense ? 7 : 9;
  return `<section class="bandeau panneau${dense}" aria-label="Les agents en ce moment">
    <div class="resume"><span class="etiquette">En ce moment · ${E.heure} · ${enMarche} agents sur ${E.agentsMax}</span>
      <p class="phrase">${enPlace.length} ouvriers sur ${E.places} places, ${pluriel(relecteurs.length, "vérificateur")}, ${pluriel(enFile.length, "tâche")} en attente.</p></div>
    <div class="cpt"><span class="etiquette r-ouvrier">Ouvriers</span><b>${marque("ouvrier", 15)}<span class="points">${enPlace.length}</span><small>/ ${E.places}${dense ? "" : " places"}</small></b>
      <span class="cases${dense}">${n(enPlace.length - deSousTache.length, marque("ouvrier", taille))}${n(deSousTache.length, marque("sous", taille))}</span><span class="sous">${dense ? "places · " : ""}dont ${deSousTache.length} de sous-tâche</span></div>
    <div class="cpt"><span class="etiquette r-verificateur">Vérificateurs</span><b>${marque("verificateur", 15)}<span class="points">${relecteurs.length}</span></b>
      <span class="cases${dense}">${n(relecteurs.length, marque("verificateur", taille))}</span><span class="sous">hors place</span></div>
    <div class="cpt"><span class="etiquette r-orchestrateur">Orchestrateur</span><b>${marque("orchestrateur", 15)}<span class="points">1</span></b>
      <span class="cases">${marque("orchestrateur", 9)}</span><span class="sous">suit ${enMarche} agents</span></div>
    <div class="cpt"><span class="etiquette">En attente</span><b><span class="points">${enFile.length}</span></b><span class="cases">${n(enFile.length, '<i class="vide"></i>')}</span><span class="sous">d'une place</span></div>
    <div class="cpt attend"><span class="etiquette">T'attend</span><b><span class="points">${attendues.length}</span></b><span class="cases"></span><span class="sous">${attendues.map((t) => t.id).join(", ")}${attendues.length > 1 ? "" : " · autorisation"}</span></div>
    <div class="cpt"><span class="etiquette">Dans ${E.branche}</span><b><span class="points">${fusionnees.length}</span><small>/ ${E.taches.length}</small></b><span class="cases fin${dense}">${n(fusionnees.length, '<i class="pris"></i>')}${n(E.taches.length - fusionnees.length, "<i></i>")}</span></div>
    <div class="cpt"><span class="etiquette">Budget ${BIENTOT}</span><b><span class="points">${dollars(E.budget.depense)}</span><small>/ ${E.budget.plafond} $</small></b><span class="jauge"><i style="width:${part}%"></i></span></div>
  </section>`;
}

/* La colonne de droite des deux pistes : ce qui t'attend, les rôles, le fil. */
function cote() {
  /* Une demande seule se dit en une phrase ; plusieurs, en deux lignes chacune : qui et pour quelle tâche, puis la commande. */
  const demandes = attendues.map((g) => (attendues.length > 1
    ? `<div class="demande courte"><p class="fort"><b class="id">${g.id}</b>${libelle("ouvrier")} ${g.titre}</p><p class="calme">veut lancer <code>${g.demande.commande}</code> · ${g.demande.heure}</p>`
    : `<div class="demande"><p class="fort"><b class="id">${g.id}</b>${libelle("ouvrier")} veut lancer <code>${g.demande.commande}</code></p><p class="calme">${g.titre}. Il garde sa place d'écriture tant que tu n'as pas répondu.</p>`)
    + `<div class="boutons"><span class="btn attend">Une fois</span><span class="btn">Toujours</span><span class="btn">Refuser</span></div></div>`).join("");
  return `<aside class="cote">
    <section class="panneau attente"><div class="entre"><span class="etiquette ambre">● Ce qui t'attend${attendues.length > 1 ? " · " + attendues.length : ""}</span><span class="etiquette">${attendues[0].demande.heure}</span></div>
      ${demandes}</section>
    <section class="panneau lire"><span class="etiquette">Les rôles</span><ul class="lecture">${CHARGE ? LEGENDE.slice(0, LEGENDE.lastIndexOf('<li class="mots">')) + `<li class="mots">À cette charge, l'étiquette se réduit à la tâche et à la durée : le rôle se lit à la silhouette. L'étiquette complète s'ouvre au survol ou au clic.</li>` : LEGENDE}</ul></section>
    <section class="panneau suite"><span class="etiquette">Fil</span><ul class="fil">${E.fil.slice(0, CHARGE ? 3 : 9).map(filHtml).join("")}</ul></section>
  </aside>`;
}
const filHtml = (f) => `<li><time>${f.t}</time><b>${f.id}</b>${marque(f.role, 10, f.creux)}<span>${f.m}${f.bientot ? " " + BIENTOT : ""}</span></li>`;

/* ---------- Le dessin en perspective ---------- */
const HAUTEUR = { moyen: 1.3, "élevé": 1.8, max: 2.4 };
function melange(hex, t) {
  const fond = [14, 18, 32], c = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));
  return `rgb(${c.map((v, i) => Math.round(fond[i] + (v - fond[i]) * t)).join(",")})`;
}
const ecran = (px, py, S) => (dx, dy, z) => `${(px + (dx - dy) * S * 0.866).toFixed(1)},${(py + (dx + dy) * S * 0.5 - z * S).toFixed(1)}`;
/* L'ouvrier : une colonne carrée posée en (px, py). genre : plein, contour (il attend, sans place),
   pointille (la tâche n'est pas partie). */
function colonne(px, py, S, w, h, c, genre = "plein") {
  const P = ecran(px, py, S);
  const dessus = [P(-w, -w, h), P(w, -w, h), P(w, w, h), P(-w, w, h)].join(" ");
  const gauche = [P(-w, w, 0), P(w, w, 0), P(w, w, h), P(-w, w, h)].join(" ");
  const droite = [P(w, -w, 0), P(w, w, 0), P(w, w, h), P(w, -w, h)].join(" ");
  if (genre === "pointille") return [gauche, droite, dessus].map((f) => `<polygon points="${f}" fill="#0e1220" stroke="rgba(220,220,220,.34)" stroke-dasharray="3 3"/>`).join("");
  if (genre === "contour") return [gauche, droite, dessus].map((f) => `<polygon points="${f}" fill="#0e1220" stroke="${c}" stroke-width="1.2" stroke-dasharray="5 3" stroke-linejoin="round"/>`).join("");
  if (genre === "socle") return [gauche, droite].map((f) => `<polygon points="${f}" fill="#0e1220" stroke="${c}" stroke-width="1.2" stroke-linejoin="round"/>`).join("");
  const [ax, ay] = P(w, w, 0).split(","), [bx, by] = P(w, w, h).split(",");
  return `<polygon points="${gauche}" fill="${melange(c, 0.44)}"/><polygon points="${droite}" fill="${melange(c, 0.27)}"/>
    <polygon points="${dessus}" fill="${c}" opacity=".5" filter="url(#flou)"/><polygon points="${dessus}" fill="${c}"/>
    <line x1="${ax}" y1="${ay}" x2="${bx}" y2="${by}" stroke="#fff" stroke-opacity=".45"/>`;
}
/* L'ouvrier de sous-tâche : le bas en contour (le travail gardé), le haut seul plein (ce qui reste). */
function sousTacheDessin(px, py, S, h, c = BLEU) {
  const bas = h * 0.56;
  return colonne(px, py, S, 0.42, bas, c, "socle") + colonne(px, py - bas * S, S, 0.42, h - bas, c);
}
/* Le vérificateur : une colonne ronde, cerclée d'une lentille. */
function verificateurDessin(px, py, S, c = VERT, degrade = "rond") {
  const h = 1.5, a = 0.25 * S * 1.2247, b = 0.25 * S * 0.7071, haut = py - h * S;
  const la = S * 0.56, lb = S * 0.32, ly = haut + S * 0.2;
  const lentille = (avant) => `<path d="M${(px - la).toFixed(1)},${ly.toFixed(1)} A${la.toFixed(1)},${lb.toFixed(1)} 0 0 ${avant ? 0 : 1} ${(px + la).toFixed(1)},${ly.toFixed(1)}" fill="none" stroke="${c}" stroke-width="${Math.max(1.4, S * 0.06).toFixed(1)}"/>`;
  return `${lentille(false)}<path d="M${(px - a).toFixed(1)},${haut.toFixed(1)} L${(px - a).toFixed(1)},${py.toFixed(1)} A${a.toFixed(1)},${b.toFixed(1)} 0 0 0 ${(px + a).toFixed(1)},${py.toFixed(1)} L${(px + a).toFixed(1)},${haut.toFixed(1)} Z" fill="url(#${degrade})"/>
    <ellipse cx="${px.toFixed(1)}" cy="${haut.toFixed(1)}" rx="${a.toFixed(1)}" ry="${b.toFixed(1)}" fill="${c}"/>${lentille(true)}`;
}
/* L'orchestrateur : une pyramide. */
function orchestrateurDessin(px, py, S, c = GRIS) {
  const P = ecran(px, py, S), w = 0.5, h = 1.45, sommet = P(0, 0, h);
  const [sx, sy] = sommet.split(","), [ax, ay] = P(w, w, 0).split(",");
  return `<polygon points="${P(-w, w, 0)} ${P(w, w, 0)} ${sommet}" fill="${melange(c, 0.52)}"/><polygon points="${P(w, -w, 0)} ${P(w, w, 0)} ${sommet}" fill="${melange(c, 0.3)}"/>
    <line x1="${ax}" y1="${ay}" x2="${sx}" y2="${sy}" stroke="#fff" stroke-opacity=".6"/><circle cx="${sx}" cy="${sy}" r="${(S * 0.07).toFixed(1)}" fill="${c}"/>`;
}
/* Le repère ambre au-dessus d'un agent qui t'attend. */
const repere = (px, y) => `<path d="M${px},${y - 6} l5,6 -5,6 -5,-6z" fill="${AMBRE}"/><path d="M${px},${y - 6} l5,6 -5,6 -5,-6z" fill="${AMBRE}" opacity=".5" filter="url(#flou)"/>`;
/* L'anneau au sol, en deux moitiés : l'arrière passe derrière la silhouette, l'avant devant. Son trait dit
   l'état, sa teinte suit le rôle : tirets épais (écrit), points creux (corrige après refus), deux anneaux
   décalés (conflit), plein épais et ambre (t'attend), fin (relecture), pointillé (attend), plein blanc (dans main). */
function anneau(px, py, rx, etat, avant, c = BLEU) {
  const ry = rx * 0.577;
  if (etat === "toi") c = AMBRE;
  if (etat === "fusionnee") c = BLANC;
  const demi = (k, dx = 0) => `M${(px + dx - rx * k).toFixed(1)},${py.toFixed(1)} A${(rx * k).toFixed(1)},${(ry * k).toFixed(1)} 0 0 ${avant ? 0 : 1} ${(px + dx + rx * k).toFixed(1)},${py.toFixed(1)}`;
  const arc = (k, extra, dx) => `<path d="${demi(k, dx)}" fill="none" stroke="${c}" ${extra}/>`;
  if (etat === "file") return `<path d="${demi(1)}" fill="none" stroke="${GRIS}" stroke-width="1" opacity=".4" stroke-dasharray="3 4"/>`;
  if (etat === "ouvert") return arc(0.8, 'stroke-width="1" opacity=".7" stroke-dasharray="3 4"');
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
  if (etat === "toi") return arc(1, 'stroke-width="1.5" opacity=".9"') + arc(0.68, 'stroke-width="3.2" opacity=".8"');
  if (etat === "ecrit") return arc(1, 'stroke-width="1.5" opacity=".8"') + arc(0.68, 'stroke-width="3" opacity=".55" stroke-dasharray="12 7"');
  if (etat === "fusionnee") return arc(1, 'stroke-width="1.5" opacity=".85"') + arc(0.68, 'stroke-width="1" opacity=".5"');
  return arc(1, 'stroke-width="1.2" opacity=".7"'); // relecture
}
/* Un agent à son poste : l'anneau de son état, la silhouette de son rôle. */
function agentDessin(a, px, py, S, rx) {
  const c = ROLES[a.role].teinte, h = HAUTEUR[a.effort];
  if (a.role === "verificateur") return anneau(px, py, rx * 0.8, a.etat, false, c) + verificateurDessin(px, py, S) + anneau(px, py, rx * 0.8, a.etat, true, c);
  if (a.sansPlace) return anneau(px, py, rx, "ouvert", false, c) + colonne(px, py, S, 0.34, 1.15, c, "contour") + anneau(px, py, rx, "ouvert", true, c);
  const halo = a.etat === "toi" ? `<ellipse cx="${px}" cy="${py}" rx="${rx * 1.3}" ry="${rx * 0.75}" fill="${AMBRE}" opacity=".17" filter="url(#halo)"/>` : "";
  const corps = a.role === "sous" ? sousTacheDessin(px, py, S, h, c) : colonne(px, py, S, 0.42, h, c);
  return halo + anneau(px, py, rx, a.etat, false, c) + corps + anneau(px, py, rx, a.etat, true, c) + (a.etat === "toi" ? repere(px, py - h * S - (S < 25 ? 12 : 24)) : "");
}
const degradeRond = (id) => `<linearGradient id="${id}" x1="0" x2="1"><stop offset="0" stop-color="${melange(VERT, 0.3)}"/><stop offset=".34" stop-color="${melange(VERT, 0.66)}"/><stop offset="1" stop-color="${melange(VERT, 0.2)}"/></linearGradient>`;
const DEFS = `<defs><filter id="flou" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="4"/></filter>
  <filter id="halo" x="-100%" y="-100%" width="300%" height="300%"><feGaussianBlur stdDeviation="11"/></filter>
  ${degradeRond("rond")}
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

/* ---------- Les étiquettes : le rôle toujours en première ligne, puis la tâche, l'état, le modèle ---------- */
/* Le bloc d'un agent dans une étiquette. titre : la ligne de la tâche, absente pour un second agent. */
function blocAgent(a, titre = "", coupe = false) {
  const sans = a.sansPlace;
  return `<div class="qui">${libelle(a.role, sans)}${a.bientot ? BIENTOT : ""}</div>${titre}
    <div class="m ${a.etat}">${signe(ETATS[a.etat].signe, 13)}<span>${motDe(a)}</span></div>
    ${sans ? "" : `<div class="d">${a.modele} ${a.effort}${coupe ? "<br>" : " · "}<b>${duree(a.depuis)}</b></div>`}`;
}
const titreDe = (t) => `<div class="t"><b class="id">${t.id}</b>${t.titre}</div>`;
/* Une ligne des listes en écran étroit : le signe de l'état, la tâche, puis un bloc par agent, son rôle en tête. */
function ligne(t) {
  const e = ETATS[t.etat];
  const sansAgent = t.etat === "fusionnee" ? `<p class="mot">dans ${E.branche}</p><small>entrée à ${t.entree} · ${t.commit}</small>`
    : t.etat === "file" ? `<p class="mot">attend une place</p><small>${t.modele} · ${t.effort} · prête depuis ${duree(t.attend)}</small>` : "";
  const agents = t.agents.map((a) => `<div class="agent"><span class="qui">${libelle(a.role, a.sansPlace)}${a.bientot ? BIENTOT : ""}</span>
      <span class="mot ${a.etat}">${motDe(a)}</span><small>${a.modele} · ${a.effort} · ${duree(a.depuis)}</small></div>`).join("");
  return `<li class="ligne ${t.etat}"><span class="noeud">${signe(e.signe)}</span><div><p><b class="id">${t.id}</b>${t.titre}</p>
    ${sansAgent}${agents}${t.detail ? `<small class="detail">${t.detail}</small>` : ""}</div></li>`;
}
/* À forte charge, l'étiquette se réduit à l'essentiel : le signe de l'état s'il sort de l'ordinaire, la tâche,
   la durée. Le rôle se lit à la silhouette ; l'étiquette complète vient au survol (ici dans `title`). */
function etqMini(t, x, y, pile = false) {
  const a = t.agents[0], etat = a ? a.etat : t.etat;
  const temps = a ? a.depuis : t.attend, sgn = pile || ["ecrit", "fusionnee"].includes(etat) ? "" : signe(ETATS[etat].signe, 11);
  const survol = a ? `${NOMS[a.role]} · ${t.titre} · ${motDe(a)} · ${a.modele} ${a.effort} · ${duree(a.depuis)}` : `${t.titre} · ${ETATS[etat].mot}`;
  return `<div class="mini ${etat}${pile ? " pile" : ""}" style="left:${x}px;top:${y}px" title="${survol}">${sgn}<b>${t.id}</b>${temps ? `<span>${temps} min</span>` : ""}</div>`;
}
/* La ligne courte d'une liste étroite, à forte charge : l'état, la tâche, le signe du rôle, la durée. */
function ligneCourte(t) {
  const a = t.agents[0], etat = a ? a.etat : t.etat;
  const fin = a ? `${marque(a.role, 11)}<small>${a.modele} · ${duree(a.depuis)}</small>` : t.etat === "file" ? `<small>prête · ${duree(t.attend)}</small>` : `<small>${t.entree}</small>`;
  return `<li class="ligne courte ${etat}"><span class="noeud">${signe(ETATS[etat].signe, 12)}</span><p><b class="id">${t.id}</b>${t.titre}${etat !== "ecrit" && a ? ` <em class="mot ${etat}">${motDe(a)}</em>` : ""}</p>${fin}</li>`;
}
/* Les rôles, une ligne chacun : la silhouette, la teinte, le nom. */
const mini = (dessin, l = 26, h = 30) => `<svg width="${l}" height="${h}" viewBox="${-l / 2} ${-h + 7} ${l} ${h}">${dessin}</svg>`;
const LEGENDE = `<li>${mini(orchestrateurDessin(0, 0, 13))}${libelle("orchestrateur")}<span>suit le chantier</span></li>
  <li>${mini(colonne(0, 0, 13, 0.42, 1.4, BLEU))}${libelle("ouvrier")}<span>écrit, sur une place</span></li>
  <li>${mini(sousTacheDessin(0, 0, 13, 1.4))}${libelle("sous")}<span>${BIENTOT}</span></li>
  <li>${mini(`<defs>${degradeRond("rond-legende")}</defs>` + verificateurDessin(0, 0, 13, VERT, "rond-legende"))}${libelle("verificateur")}<span>relit, hors place</span></li>
  <li class="mots">Sous-tâche : elle ne règle que ce qui reste d'un travail refusé. Contour en tirets : l'agent attend, sans place. Pointillé gris : la tâche n'est pas partie.</li>`;
/* Écran étroit : l'onglet de la page reste en vue dans l'en-tête, qui défile. */
window.addEventListener("load", () => { const a = document.querySelector(".tete .on"); if (a) a.scrollIntoView({ inline: "center", block: "nearest" }); });
