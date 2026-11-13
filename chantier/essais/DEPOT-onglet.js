/* Essai DEPOT : l'onglet « Dépôt » (les branches des tâches et leurs fusions) dans un navigateur sans écran.
 *
 * Lancer depuis la racine du dépôt :  node chantier/essais/DEPOT-onglet.js
 * Le script démarre lui-même `python3 -m atelier demo` (agents simulés, aucun appel réel) sur un port libre.
 * Partie 1 : l'onglet sur la démonstration telle que le serveur la donne (un dépôt d'exemple, sans git).
 * Partie 2 : un dépôt plus chargé (conflit, envoi en échec, fichiers partagés), posé dans la réponse de /api/etat
 * avec les clés que rend la lecture de git (chantier/relais/D1.md, prouvées par tests/test_depot.py).
 * Captures dans chantier/captures/DEPOT-*.png ; code de sortie non nul si une vérification échoue.
 */
const { chromium } = require("playwright");
const { spawn } = require("node:child_process");
const net = require("node:net");
const fs = require("node:fs");
const path = require("node:path");

const RACINE = path.resolve(__dirname, "..", "..");
const CAPTURES = path.resolve(__dirname, "..", "captures");
const PAUSE = (ms) => new Promise((r) => setTimeout(r, ms));
const serveurs = [];
let echecs = 0;

function verifier(nom, condition, detail) {
  if (condition) console.log(`ok     - ${nom}`);
  else { echecs += 1; console.log(`ECHEC  - ${nom}${detail !== undefined ? ` (${typeof detail === "string" ? detail : JSON.stringify(detail)})` : ""}`); }
}
function portLibre() {
  return new Promise((resolve, reject) => {
    const s = net.createServer();
    s.listen(0, "127.0.0.1", () => { const { port } = s.address(); s.close(() => resolve(port)); });
    s.on("error", reject);
  });
}
async function demarrer(delai) {
  const port = await portLibre();
  const processus = spawn("python3", ["-m", "atelier", "demo", "--port", String(port), "--delai", String(delai)], { cwd: RACINE, stdio: "ignore" });
  const serveur = { port, url: `http://127.0.0.1:${port}`, processus };
  serveurs.push(serveur);
  const limite = Date.now() + 20000;
  for (;;) {
    try { const r = await fetch(`${serveur.url}/api/etat`); if (r.ok) return serveur; } catch (e) { /* pas encore prêt */ }
    if (Date.now() > limite) throw new Error("La démonstration ne répond pas.");
    await PAUSE(150);
  }
}
const etat = async (serveur) => (await fetch(`${serveur.url}/api/etat`)).json();
async function jusqua(fonction, ms = 20000, pas = 150) {
  const limite = Date.now() + ms;
  for (;;) { const v = await fonction(); if (v) return v; if (Date.now() > limite) return null; await PAUSE(pas); }
}
const aller = (page, onglet) => page.evaluate((o) => { location.hash = `#${o}`; }, onglet);
const capture = (cible, nom) => cible.screenshot({ path: path.join(CAPTURES, `DEPOT-${nom}.png`) });
const texteDe = async (cible) => (await cible.innerText()).replace(/[  ]/g, " ").replace(/\s+/g, " ").trim();

/* Un dépôt chargé, avec les clés de la lecture de git : A entrée directement, B entrée après fusion, C en conflit,
   D en retard, les autres pas parties ; trois enregistrements pas encore en ligne ; deux fichiers partagés. */
function charge(vue) {
  const enr = (id, message, heure, minute) => ({ id, message, heure, instant: `2026-11-13T14:${minute}:00+00:00` });
  const vide = (id) => ({ branche: { nom: `tache/${id}`, existe: false }, copie: { existe: false, dossier: `.atelier/arbres/${id}` },
    depart: null, retard: null, modifies: { nombre: 0, noms: [] }, conflits: [], entree: null, probleme: "" });
  const [a, b, c, d] = vue.taches;
  const taches = Object.fromEntries(vue.taches.map((t) => [t.id, vide(t.id)]));
  taches[a.id].entree = { ...enr("a41c9e2", `${a.id} : ${a.titre}`, "14:02", "02"), facon: "directe" };
  taches[b.id].entree = { ...enr("e9b2f40", `Merge commit '7d03b5e' into tache/${b.id}`, "14:16", "16"), facon: "apres_fusion" };
  Object.assign(taches[c.id], { branche: { nom: `tache/${c.id}`, existe: true }, copie: { existe: true, dossier: `.atelier/arbres/${c.id}` },
    depart: enr("7d03b5e", "Cahier : A enregistrée", "14:02", "02"), retard: 0, modifies: { nombre: 1, noms: ["src/routes.py"] }, conflits: ["src/routes.py"] });
  Object.assign(taches[d.id], { branche: { nom: `tache/${d.id}`, existe: true }, copie: { existe: true, dossier: `.atelier/arbres/${d.id}` },
    depart: enr("7d03b5e", "Cahier : A enregistrée", "14:02", "02"), retard: 3, modifies: { nombre: 5, noms: ["d1.py"] } });
  Object.assign(a, { etat: "verifie", etat_fr: "Vérifiée", phase: undefined });
  Object.assign(b, { etat: "verifie", etat_fr: "Vérifiée", phase: undefined });
  Object.assign(c, { etat: "en_cours", etat_fr: "En cours", phase: { texte: "L'ouvrier résout un conflit de fusion", depuis_s: 12 } });
  Object.assign(d, { etat: "en_verification", etat_fr: "En vérification", verification: "complete", phase: { texte: "Le vérificateur relit", depuis_s: 40 } });
  vue.taches.slice(4).forEach((t) => Object.assign(t, { etat: "a_lancer", etat_fr: "À lancer", phase: undefined }));
  const derniers = [enr("c58d1aa", `Cahier : ${b.id} enregistrée`, "14:16", "16"), taches[b.id].entree, enr("5b1e0d4", `${b.id} : ${b.titre}`, "14:16", "16"),
    enr("7d03b5e", `Cahier : ${a.id} enregistrée`, "14:02", "02"), taches[a.id].entree];
  vue.depot = { chantier: { branche: "main", detachee: false, dernier: derniers[0], derniers, probleme: "" }, taches,
    en_ligne: { suivie: "origin/main", avance: 3, connu: derniers[3], probleme: "" },
    partages: { fichiers: [{ motif: "CHANGELOG.md", fusion: "union" }, { motif: "src/routes.py", fusion: "git" }], probleme: "" } };
  vue.distant = { adresse: "github.com/exemple/reservations", probleme: "Pas d'accès au réseau, ou nom de site mal écrit." };
  vue.autorisations = [];
  return vue;
}

async function main() {
  fs.mkdirSync(CAPTURES, { recursive: true });
  const browser = await chromium.launch();
  const serveur = await demarrer(3);
  const contexte = await browser.newContext({ viewport: { width: 1280, height: 800 }, deviceScaleFactor: 2 });
  const page = await contexte.newPage();
  const erreurs = [];
  page.on("pageerror", (e) => erreurs.push(String(e)));
  page.on("console", (m) => { if (m.type() === "error" && !/Failed to load resource/.test(m.text())) erreurs.push(m.text()); });
  await page.goto(serveur.url + "#conversation");

  /* ---------- 1. L'onglet sur la démonstration ---------- */
  console.log("\n== Partie 1 : l'onglet sur la démonstration");
  const lien = page.locator('.onglets a[data-onglet="depot"]');
  verifier("la barre d'onglets a un onglet « Dépôt », après « Code »", (await page.locator(".onglets a").allInnerTexts()).map((t) => t.trim().split(/\s/)[0].toLowerCase()).join(" ").endsWith("code dépôt"), await page.locator(".onglets a").allInnerTexts());
  await lien.click();
  await page.waitForFunction(() => document.getElementById("vue-depot").classList.contains("active"), null, { timeout: 5000 }).catch(() => {});
  verifier("un clic ouvre la vue du dépôt", (await page.evaluate(() => location.hash)) === "#depot" && await page.locator("#vue-depot").isVisible());
  verifier("l'onglet est marqué comme la page en cours", (await lien.getAttribute("aria-current")) === "page");
  await page.waitForSelector("#dp-bandeau .dp-phrase p");
  verifier("avant tout plan, la page dit qu'il n'y a aucune branche de tâche", /Aucune tâche au plan/.test(await texteDe(page.locator("#dp-bandeau"))), await texteDe(page.locator("#dp-bandeau")));

  await aller(page, "conversation");
  await page.fill("#message", "Moteur de calcul : formules de la norme, validées sur les cas de référence.");
  await page.click("#envoi");
  await page.waitForSelector('#colonne button[data-action="valider"]', { timeout: 30000 });
  await page.click('#colonne button[data-action="valider"]');
  await page.waitForSelector("#colonne .autorisation", { timeout: 30000 });
  const vrai = await jusqua(async () => { const e = await etat(serveur); return e.depot && Object.values(e.depot.taches).some((g) => g.branche.existe) ? e : null; });
  verifier("le serveur donne l'état du dépôt, une fiche par tâche", Boolean(vrai) && Object.keys(vrai.depot.taches).length === vrai.taches.length, vrai && Object.keys(vrai.depot.taches));
  await aller(page, "depot");
  await page.waitForSelector("#dp-graphe .dp-rang", { timeout: 15000 });
  await jusqua(async () => (await page.locator("#dp-graphe .dp-qui .role").count()) > 0, 15000);
  const rangs = await page.locator("#dp-graphe .dp-rang b").allInnerTexts();
  verifier("la branche du chantier ouvre le graphe", rangs[0] === "main", rangs);
  verifier("chaque tâche a sa ligne, nommée par sa branche", vrai.taches.every((t) => rangs.includes(`tache/${t.id}`)), rangs);
  verifier("une branche en cours dit qui y travaille, par son rôle", (await page.locator("#dp-graphe .dp-qui .role").count()) >= 1, await texteDe(page.locator("#dp-graphe")));
  verifier("le graphe est dessiné (la branche du chantier, les branches des tâches)", (await page.locator("#dp-graphe > svg path").count()) >= 1 && (await page.locator("#dp-graphe > svg line").count()) >= 2);
  const cote = await texteDe(page.locator("#dp-cote"));
  verifier("la colonne dit qu'aucune branche en ligne n'est suivie", /Aucune branche en ligne n'est suivie/.test(cote), cote);
  verifier("ce qui viendrait de GitHub est annoncé « à venir », sans rien inventer", /GitHub · à venir/i.test(cote) && /ce que l'Atelier ne fait pas/.test(cote), cote);
  verifier("sans conflit ni envoi en échec, l'onglet n'a pas de point", !(await page.locator("#pt-depot.allume").count()));
  await capture(page.locator("#vue-depot"), "demonstration");

  /* ---------- 2. Un dépôt chargé : entrées, conflit, retard, envoi en échec, partagés ---------- */
  console.log("\n== Partie 2 : un dépôt chargé");
  let lecture = true;
  await page.route("**/api/etat", async (route) => {
    const reponse = await route.fetch();
    const vue = charge(await reponse.json());
    if (!lecture) vue.depot = null;
    await route.fulfill({ response: reponse, json: vue });
  });
  await page.waitForFunction(() => /dont 1 reprend un conflit/.test(document.getElementById("dp-bandeau").innerText), null, { timeout: 15000 });
  const bandeau = await texteDe(page.locator("#dp-bandeau"));
  verifier("la phrase compte les tâches entrées, les branches en cours et le conflit", /2 tâches sont dans main, 2 branches sont en cours, dont 1 reprend un conflit\./.test(bandeau), bandeau);
  const comptes = await page.locator("#dp-bandeau .dp-compte").evaluateAll((liste) => liste.map((c) => [c.querySelector("span").innerText.trim().toLowerCase(), c.querySelector("b").innerText.replace(/\s+/g, " ").trim(), c.classList.contains("souci")]));
  verifier("les cinq comptes sont justes", JSON.stringify(comptes.map((c) => c[1])) === JSON.stringify([`2 / ${vrai.taches.length}`, "2", "1", String(vrai.taches.length - 4), "3"]), comptes);
  verifier("le conflit et le retard d'envoi sont en ambre, pas le reste", JSON.stringify(comptes.map((c) => c[2])) === JSON.stringify([false, false, true, false, true]), comptes);
  verifier("le dernier compte dit « pas encore en ligne »", comptes[4][0] === "pas encore en ligne", comptes[4]);
  verifier("un conflit ou un envoi en échec allume le point de l'onglet", (await page.locator("#pt-depot.allume").count()) === 1);
  const lignes = await page.locator("#dp-graphe .dp-dit").evaluateAll((l) => l.map((e) => e.innerText.replace(/\s+/g, " ").trim()));
  const [a, b, c, d] = vrai.taches;
  const ligneDe = (id) => lignes[(rangs2.indexOf(`tache/${id}`))];
  const rangs2 = await page.locator("#dp-graphe .dp-rang b").allInnerTexts();
  verifier("origin/main ouvre le graphe, avant la branche du chantier", rangs2[0] === "origin/main" && rangs2[1] === "main", rangs2.slice(0, 3));
  verifier("le dépôt en ligne dit son retard", /main a 3 enregistrements d'avance/.test(lignes[0]), lignes[0]);
  verifier("une entrée directe se dit, avec son heure et son enregistrement", /dans main depuis 14:02 · a41c9e2/.test(ligneDe(a.id)) && /Entrée directe/.test(ligneDe(a.id)), ligneDe(a.id));
  verifier("une entrée après fusion se dit aussi", /dans main depuis 14:16 · e9b2f40/.test(ligneDe(b.id)) && /d'abord été fusionnée dans la branche/.test(ligneDe(b.id)), ligneDe(b.id));
  verifier("la branche en conflit nomme le fichier, et qui le résout", /OUVRIER/i.test(ligneDe(c.id)) && /Conflit à l'entrée dans src\/routes\.py : rien n'est entré\./.test(ligneDe(c.id)), ligneDe(c.id));
  verifier("la branche en retard le dit, avec ses fichiers modifiés et son vérificateur", /VÉRIFICATEUR/i.test(ligneDe(d.id)) && /5 fichiers modifiés, pas encore enregistrés\. En retard de 3 sur main\./.test(ligneDe(d.id)), ligneDe(d.id));
  verifier("une tâche pas partie n'a pas de branche", /pas partie, aucun agent/.test(lignes[lignes.length - 1]) && /sera créée à son départ/.test(lignes[lignes.length - 1]), lignes[lignes.length - 1]);
  const titres = await page.locator("#dp-graphe .dp-titre").allInnerTexts();
  verifier("trois groupes : dans main, pas encore dans main, sans branche", titres.map((t) => t.replace(/\s+/g, "").toLowerCase()).join("|") === `2dansmain|2pasencoredansmain|${vrai.taches.length - 4}sansbranche`, titres);
  const cote2 = await texteDe(page.locator("#dp-cote"));
  verifier("l'envoi en échec est dit en clair, avec ce qui n'est pas perdu", /Le dernier envoi a échoué\./.test(cote2) && /Pas d'accès au réseau/.test(cote2) && /garde ses 3 enregistrements d'avance/.test(cote2), cote2);
  verifier("les derniers enregistrements marquent ceux qui ne sont pas en ligne", (await page.locator("#dp-cote .dp-enr li.pas-en-ligne").count()) === 3 && (await page.locator("#dp-cote .dp-enr li.seuil").count()) === 1);
  verifier("les fichiers partagés disent leur fusion", /CHANGELOG\.md · fusion « union »/.test(cote2) && /src\/routes\.py · fusion « git »/.test(cote2) && /Un conflit revient à l'ouvrier/.test(cote2), cote2);
  await capture(page.locator("#vue-depot"), "charge");

  /* ---------- 3. Lecture en cours, fenêtre étroite ---------- */
  console.log("\n== Partie 3 : lecture en cours, fenêtre étroite");
  await page.setViewportSize({ width: 820, height: 900 });
  await PAUSE(1500);
  const debord = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  verifier("à 820 pixels de large, la page ne déborde pas", debord <= 0, debord);
  verifier("le graphe reste lisible : il défile dans son cadre", await page.evaluate(() => { const c = document.querySelector(".dp-cadre"); return c.scrollWidth >= c.clientWidth && getComputedStyle(c).overflowX === "auto"; }));
  await capture(page, "etroit");
  lecture = false;
  await page.waitForFunction(() => /Lecture du dépôt en cours/.test(document.getElementById("dp-bandeau").innerText), null, { timeout: 15000 });
  verifier("tant que git n'a pas été lu, la page le dit et ne dessine rien", (await page.locator("#dp-graphe .dp-rang").count()) === 0);

  verifier("aucune erreur dans la page", erreurs.length === 0, erreurs);
  await contexte.close();
  await browser.close();
}

function arreterServeurs() {
  for (const s of serveurs) { try { s.processus.kill("SIGKILL"); } catch (e) { /* déjà arrêté */ } }
}
process.on("exit", arreterServeurs);

main().then(() => {
  console.log(echecs ? `\n${echecs} vérification(s) en échec.` : "\nToutes les vérifications passent.");
  arreterServeurs();
  process.exit(echecs ? 1 : 0);
}).catch((erreur) => {
  console.error("\nECHEC  - l'essai s'est interrompu :", erreur);
  arreterServeurs();
  process.exit(1);
});
