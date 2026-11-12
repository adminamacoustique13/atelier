/* Essai Gb : le bouton « Mettre à jour » du tableau de bord, dans un navigateur sans écran.
 *
 * Lancer depuis la racine du dépôt :  node chantier/essais/G-mise-a-jour.js
 * Le script démarre lui-même `python3 -m atelier demo` (double simulé : ni git ni réseau, rien ne s'arrête),
 * fabrique d'autres vues et d'autres réponses en interceptant les requêtes de la page, écrit les captures
 * dans chantier/captures/G-*.png, arrête les serveurs quoi qu'il arrive, et sort avec un code non nul si une
 * vérification échoue. Il attend des états de la page, pas des durées.
 */
const { chromium } = require("playwright");
const { spawn, spawnSync } = require("node:child_process");
const net = require("node:net");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const RACINE = path.resolve(__dirname, "..", "..");
const CAPTURES = path.resolve(__dirname, "..", "captures");
const PAUSE = (ms) => new Promise((r) => setTimeout(r, ms));
const serveurs = [];
let echecs = 0, reussies = 0;

function verifier(nom, condition, detail) {
  if (condition) { reussies += 1; console.log(`ok     - ${nom}`); }
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
async function jusqua(fonction, ms = 15000, pas = 100) {
  const limite = Date.now() + ms;
  for (;;) {
    const v = await fonction();
    if (v) return v;
    if (Date.now() > limite) return null;
    await PAUSE(pas);
  }
}
const capture = (cible, nom, options = {}) => cible.screenshot({ path: path.join(CAPTURES, `G-${nom}.png`), ...options });

async function ouvrir(browser, url, options = {}) {
  const contexte = await browser.newContext({ viewport: { width: 1280, height: 800 }, deviceScaleFactor: 2, ...options });
  const page = await contexte.newPage();
  const erreurs = [], requetes = [];
  page.on("pageerror", (e) => erreurs.push(String(e)));
  page.on("console", (m) => { if (m.type() === "error" && !/Failed to load resource|ERR_FAILED|Fetch API cannot load file:/.test(m.text())) erreurs.push(m.text()); });
  page.on("request", (r) => { if (r.method() === "POST") requetes.push({ url: new URL(r.url()).pathname, corps: r.postData() ? JSON.parse(r.postData()) : null }); });
  if (url) await page.goto(url);
  return { page, contexte, erreurs, requetes };
}

/* Une page dont /api/etat et /api/mise-a-jour sont fabriqués :
   `faux.vue` est rendue telle quelle ; `faux.coupe` vrai : /api/etat échoue ; `faux.reponse` fabrique la réponse du POST. */
async function ouvrirFausse(browser, url, vue, options = {}) {
  const faux = { vue, coupe: false, reponse: null, coupures: 0 };
  const o = await ouvrir(browser, null, options);
  await o.page.route("**/api/etat", (route) => {
    if (faux.coupe) { faux.coupures += 1; return route.abort("connectionrefused"); }
    return route.fulfill({ json: faux.vue });
  });
  await o.page.route("**/api/mise-a-jour", (route) => faux.reponse(route));
  await o.page.goto(url);
  return { ...o, faux };
}

const copie = (vue, changements) => Object.assign(JSON.parse(JSON.stringify(vue)), changements);
const bouton = (page) => page.locator("#maj");
const texteBouton = (page) => bouton(page).innerText();
const phrase = (page) => page.locator("#maj-phrase").innerText();
const nPosts = (requetes) => requetes.filter((r) => r.url === "/api/mise-a-jour").length;
/* Arme le bouton, attend que le délai de double-clic soit passé (un état de la page), puis confirme. */
async function armerPuisConfirmer(page) {
  await bouton(page).click();
  await page.waitForFunction(() => document.getElementById("maj").textContent === "Confirmer la mise à jour");
  await page.waitForFunction(() => performance.now() - majArmeeLe > DELAI_CONFIRMATION + 50);
  await bouton(page).click();
}
const PHRASE_AGENT = "Mise à jour impossible : un agent travaille. Réessaie quand il aura fini.";
const PHRASE_REDEMARRE = "Atelier a été mis à jour. Il redémarre ; s'il ne revient pas dans quelques secondes, relance-le à la main.";

async function main() {
  fs.mkdirSync(CAPTURES, { recursive: true });
  const browser = await chromium.launch();
  const s = await demarrer(3);
  const base = await etat(s);

  /* ---------- 1. La démonstration, de bout en bout ---------- */
  console.log("\n== Partie 1 : `atelier demo` et son double simulé");
  {
    verifier("la vue du serveur porte le champ mise_a_jour", base.mise_a_jour && typeof base.mise_a_jour.phrase === "string" && typeof base.mise_a_jour.disponible === "boolean", base.mise_a_jour);
    const { page, contexte, erreurs, requetes } = await ouvrir(browser, s.url);
    await page.waitForSelector("#maj:not([hidden])", { timeout: 15000 });
    verifier("le bouton est visible en démonstration (le double annonce une mise à jour)", await bouton(page).isVisible());
    verifier("il s'appelle « Mettre à jour »", (await texteBouton(page)) === "Mettre à jour", await texteBouton(page));
    verifier("il est dans l'en-tête", await page.evaluate(() => document.getElementById("maj").closest("header.tete") !== null));
    verifier("aucune phrase n'est affichée avant un clic", !(await page.locator("#maj-phrase").isVisible()));
    await page.mouse.move(5, 5);
    await capture(page, "bouton", { clip: { x: 0, y: 0, width: 1280, height: 90 } });

    await bouton(page).click();
    await page.waitForFunction(() => document.getElementById("maj").textContent === "Confirmer la mise à jour");
    verifier("le premier clic arme le bouton : « Confirmer la mise à jour »", (await texteBouton(page)) === "Confirmer la mise à jour");
    verifier("le bouton armé est marqué comme tel (classe confirme)", await bouton(page).evaluate((b) => b.classList.contains("confirme")));
    verifier("le premier clic n'envoie rien", nPosts(requetes) === 0, requetes);
    await page.mouse.move(5, 5);
    await capture(page, "confirmation", { clip: { x: 0, y: 0, width: 1280, height: 90 } });
    const desarme = await jusqua(async () => (await texteBouton(page)) === "Mettre à jour", 9000);
    verifier("le bouton se désarme seul", Boolean(desarme));
    verifier("et rien n'est parti entre-temps", nPosts(requetes) === 0, requetes);

    await bouton(page).dblclick();
    await page.waitForFunction(() => document.getElementById("maj").textContent === "Confirmer la mise à jour");
    verifier("un double-clic ne confirme pas : le bouton reste armé", (await texteBouton(page)) === "Confirmer la mise à jour");
    verifier("un double-clic n'envoie rien", nPosts(requetes) === 0, requetes);

    await page.waitForFunction(() => performance.now() - majArmeeLe > DELAI_CONFIRMATION + 50);
    await bouton(page).click();
    const attendue = "Mise à jour simulée : rien n'a changé.";
    await page.waitForFunction((t) => document.getElementById("maj-phrase").textContent.includes(t), attendue, { timeout: 10000 });
    verifier("le second clic envoie exactement un POST /api/mise-a-jour au corps vide", nPosts(requetes) === 1 && JSON.stringify(requetes.find((r) => r.url === "/api/mise-a-jour").corps) === "{}", requetes);
    verifier("la phrase du serveur est affichée telle quelle", (await phrase(page)) === attendue, await phrase(page));
    verifier("la démonstration ne dit pas qu'Atelier redémarre", !/redémarre/.test(await page.locator("body").innerText()));
    verifier("aucun message d'erreur alarmant", !/ne répond pas/.test(await page.locator("#rail-point").innerText()));
    await page.mouse.move(5, 5);
    await capture(page, "phrase", { clip: { x: 0, y: 0, width: 1280, height: 110 } });
    await jusqua(async () => (await etat(s)).evenements.some((e) => e.texte === attendue), 5000);
    const apres = await etat(s);
    verifier("la phrase est écrite au fil du projet ouvert", apres.evenements.some((e) => e.texte === attendue));
    verifier("la démonstration tourne toujours après le clic", s.processus.exitCode === null && apres.mode === "démonstration");
    verifier("le double annonce toujours une mise à jour : le bouton reste", apres.mise_a_jour.disponible === true && (await bouton(page).isVisible()));
    verifier("le bouton est de nouveau utilisable", (await bouton(page).isEnabled()) && (await texteBouton(page)) === "Mettre à jour");
    verifier("aucune erreur dans la page", erreurs.length === 0, erreurs);
    await contexte.close();

    const direct = await fetch(`${s.url}/api/mise-a-jour`, { method: "POST" });
    const corps = await direct.json();
    verifier("la route répond la vue plus mise_a_jour_faite {fait, phrase}", direct.status === 200 && corps.mise_a_jour_faite.fait === true && corps.mise_a_jour_faite.phrase === attendue && Array.isArray(corps.taches), corps.mise_a_jour_faite);
    verifier("et la démonstration tourne encore après cet appel direct", s.processus.exitCode === null && (await etat(s)).mode === "démonstration");
  }

  /* ---------- 2. Des vues et des réponses fabriquées ---------- */
  console.log("\n== Partie 2 : vues fabriquées");
  for (const [nom, vue] of [
    ["disponible faux", copie(base, { mise_a_jour: { disponible: false, phrase: "Atelier est à jour." } })],
    ["champ absent", (() => { const v = copie(base, {}); delete v.mise_a_jour; return v; })()],
    ["champ nul", copie(base, { mise_a_jour: null })],
    ["champ qui n'est pas un objet", copie(base, { mise_a_jour: "oui" })],
    ["disponible qui n'est pas un booléen", copie(base, { mise_a_jour: { disponible: "true", phrase: "" } })],
    ["disponible sans phrase ni projet", { aucun_projet: true, projets: [], racine: "/x", mode: "réel", mise_a_jour: { disponible: false, phrase: "" } }],
  ]) {
    const { page, contexte, erreurs } = await ouvrirFausse(browser, s.url, vue);
    await page.waitForSelector("#projet, .accueil", { state: "attached" });
    await jusqua(async () => page.evaluate(() => derniere !== null), 8000);
    verifier(`${nom} : pas de bouton`, !(await bouton(page).isVisible()) && (await page.locator("#maj[hidden]").count()) === 1);
    verifier(`${nom} : aucune erreur dans la page`, erreurs.length === 0, erreurs);
    await contexte.close();
  }
  {
    const vue = { aucun_projet: true, projets: [], racine: "/x", mode: "réel", mise_a_jour: { disponible: true, phrase: "" } };
    const { page, contexte, erreurs } = await ouvrirFausse(browser, s.url, vue);
    await page.waitForSelector("#maj:not([hidden])");
    verifier("sans projet ouvert, le bouton apparaît quand disponible est vrai", await bouton(page).isVisible());
    verifier("sans projet ouvert, aucune erreur dans la page", erreurs.length === 0, erreurs);
    await contexte.close();
  }

  /* Un refus du serveur : la phrase, et le bouton reste */
  {
    const vue = copie(base, { mode: "réel", mise_a_jour: { disponible: true, phrase: "Une mise à jour d'Atelier est disponible." } });
    const { page, contexte, erreurs, requetes, faux } = await ouvrirFausse(browser, s.url, vue);
    let corpsRecu = null;
    faux.reponse = (route) => { corpsRecu = route.request().postData(); return route.fulfill({ json: { ...vue, mise_a_jour_faite: { fait: false, phrase: PHRASE_AGENT } } }); };
    await page.waitForSelector("#maj:not([hidden])");
    await armerPuisConfirmer(page);
    await page.waitForFunction((t) => document.getElementById("maj-phrase").textContent === t, PHRASE_AGENT);
    verifier("fait faux : la phrase du serveur est affichée telle quelle", (await phrase(page)) === PHRASE_AGENT, await phrase(page));
    verifier("fait faux : le bouton reste, utilisable", (await bouton(page).isVisible()) && (await bouton(page).isEnabled()) && (await texteBouton(page)) === "Mettre à jour");
    verifier("fait faux : la page ne parle pas de redémarrage", !/redémarre/i.test(await page.locator("body").innerText()));
    verifier("fait faux : le corps envoyé est vide", corpsRecu === "{}" && nPosts(requetes) === 1, corpsRecu);
    verifier("fait faux : aucune erreur dans la page", erreurs.length === 0, erreurs);
    await contexte.close();
  }

  /* Une phrase hostile n'est jamais prise pour du HTML */
  {
    const hostile = '<img src=x onerror="window.__piege=1"><b>gras</b>';
    const vue = copie(base, { mode: "réel", mise_a_jour: { disponible: true, phrase: "" } });
    const { page, contexte, erreurs, faux } = await ouvrirFausse(browser, s.url, vue);
    faux.reponse = (route) => route.fulfill({ json: { ...vue, mise_a_jour_faite: { fait: false, phrase: hostile } } });
    await page.waitForSelector("#maj:not([hidden])");
    await armerPuisConfirmer(page);
    await page.waitForFunction(() => document.getElementById("maj-phrase").textContent.includes("gras"));
    verifier("une phrase hostile s'affiche comme du texte", (await phrase(page)) === hostile && (await page.locator("#maj-phrase img, #maj-phrase b").count()) === 0, await phrase(page));
    verifier("et ne lance aucun script", (await page.evaluate(() => window.__piege)) === undefined && erreurs.length === 0, erreurs);
    await contexte.close();
  }

  /* Une réponse qui ne vient pas : la page le dit et reste utilisable */
  {
    const vue = copie(base, { mode: "réel", mise_a_jour: { disponible: true, phrase: "" } });
    const { page, contexte, faux } = await ouvrirFausse(browser, s.url, vue);
    faux.reponse = (route) => route.fulfill({ status: 500, json: { erreur: "boum" } });
    await page.waitForSelector("#maj:not([hidden])");
    await armerPuisConfirmer(page);
    await page.waitForFunction(() => /n'est pas partie/.test(document.getElementById("maj-phrase").textContent));
    verifier("réponse 500 : la page dit que la demande n'est pas partie, le bouton reste", (await bouton(page).isEnabled()) && /n'est pas partie/.test(await phrase(page)), await phrase(page));
    await contexte.close();
  }

  /* Le redémarrage : fait vrai, puis un serveur qui ne répond plus, puis qui revient */
  console.log("\n== Partie 3 : le redémarrage");
  {
    const vue = copie(base, { mode: "réel", mise_a_jour: { disponible: true, phrase: "Une mise à jour d'Atelier est disponible." } });
    const { page, contexte, erreurs, requetes, faux } = await ouvrirFausse(browser, s.url, vue);
    faux.reponse = (route) => {
      faux.coupe = true; // le serveur s'arrête juste après avoir répondu
      return route.fulfill({ json: { ...vue, mise_a_jour_faite: { fait: true, phrase: PHRASE_REDEMARRE } } });
    };
    await page.waitForSelector("#maj:not([hidden])");
    await armerPuisConfirmer(page);
    await page.waitForFunction((t) => document.getElementById("maj-phrase").textContent.includes(t), PHRASE_REDEMARRE);
    verifier("fait vrai : la phrase du serveur est affichée", (await phrase(page)).startsWith(PHRASE_REDEMARRE), await phrase(page));
    verifier("fait vrai : la page dit qu'Atelier redémarre", /Atelier redémarre/.test(await phrase(page)));
    const coupe = await jusqua(async () => faux.coupures >= 3, 15000);
    verifier("le serveur ne répond plus (au moins trois relectures refusées)", Boolean(coupe), faux.coupures);
    const pendant = await page.locator("body").innerText();
    verifier("pendant la coupure : aucune erreur alarmante", !/ne répond pas|Relance l'atelier|erreur|échec/i.test(await page.locator("#rail-point").innerText()) && !/Le moteur ne répond pas/.test(pendant), await page.locator("#rail-point").innerText());
    verifier("pendant la coupure : le bouton est grisé, « Redémarrage »", (await bouton(page).isDisabled()) && (await texteBouton(page)) === "Redémarrage", await texteBouton(page));
    verifier("pendant la coupure : la page affichée est restée en place", await page.evaluate(() => document.querySelector(".app") !== null && !document.querySelector(".app").classList.contains("sans-projet")));
    await page.mouse.move(5, 5);
    await capture(page, "redemarrage", { clip: { x: 0, y: 0, width: 1280, height: 130 } });
    verifier("un clic sur le bouton grisé n'envoie rien de plus", nPosts(requetes) === 1, requetes.length);
    faux.vue = copie(base, { mode: "réel", mise_a_jour: { disponible: false, phrase: "Atelier est à jour." } });
    faux.coupe = false;
    await page.waitForFunction(() => document.getElementById("maj").hidden === true && /revenu/.test(document.getElementById("maj-phrase").textContent), null, { timeout: 15000 });
    verifier("au retour : la page reprend, le bouton disparaît", await page.locator("#maj[hidden]").count() === 1);
    verifier("au retour : une phrase le dit, plus de « redémarre »", /Atelier est revenu/.test(await phrase(page)) && !/Atelier redémarre/.test(await phrase(page)), await phrase(page));
    verifier("au retour : la page n'affiche toujours aucune erreur", erreurs.length === 0, erreurs);
    const relu = await jusqua(async () => page.evaluate(() => derniere && derniere.mise_a_jour.disponible === false), 8000);
    verifier("au retour : la page lit de nouveau la vue du serveur", Boolean(relu));
    await contexte.close();
  }
  /* Sans cause d'attente (serveur coupé sans mise à jour), l'erreur habituelle reste */
  {
    const vue = copie(base, { mode: "réel", mise_a_jour: { disponible: true, phrase: "" } });
    const { page, contexte, faux } = await ouvrirFausse(browser, s.url, vue);
    await page.waitForSelector("#maj:not([hidden])");
    faux.coupe = true;
    const alarme = await jusqua(async () => /ne répond pas/.test(await page.locator("#rail-point").innerText()), 10000);
    verifier("hors mise à jour, un serveur coupé garde son message habituel", Boolean(alarme), await page.locator("#rail-point").innerText());
    await contexte.close();
  }

  /* ---------- 4. Fenêtre étroite ---------- */
  console.log("\n== Partie 4 : fenêtre de 400 pixels");
  {
    const { page, contexte, erreurs } = await ouvrir(browser, s.url, { viewport: { width: 400, height: 800 } });
    await page.waitForSelector("#maj:not([hidden])", { timeout: 15000 });
    await bouton(page).scrollIntoViewIfNeeded();
    const mesure = await page.evaluate(() => {
      const tete = document.querySelector("header.tete");
      const boites = [...tete.children].filter((e) => !e.hidden && getComputedStyle(e).display !== "none").map((e) => { const r = e.getBoundingClientRect(); return { l: r.left, r: r.right, h: r.top, b: r.bottom, nom: e.id || e.className }; });
      const recoupe = [];
      for (let i = 0; i < boites.length; i++) for (let j = i + 1; j < boites.length; j++) {
        const a = boites[i], b = boites[j];
        if (a.l < b.r - 0.5 && b.l < a.r - 0.5 && a.h < b.b - 0.5 && b.h < a.b - 0.5) recoupe.push([a.nom, b.nom]);
      }
      const m = document.getElementById("maj").getBoundingClientRect(), t = tete.getBoundingClientRect();
      return { recoupe, defilement: document.documentElement.scrollWidth - window.innerWidth, boutonDansEntete: m.top >= t.top - 0.5 && m.bottom <= t.bottom + 0.5, boutonVisible: m.left >= 0 && m.right <= window.innerWidth + 0.5 };
    });
    verifier("à 400 px, aucun élément de l'en-tête n'en recoupe un autre", mesure.recoupe.length === 0, mesure.recoupe);
    verifier("à 400 px, la page ne défile pas de côté", mesure.defilement <= 0, mesure);
    verifier("à 400 px, le bouton est dans l'en-tête et à l'écran (une fois amené par le défilement de l'en-tête)", mesure.boutonDansEntete && mesure.boutonVisible, mesure);
    await bouton(page).click();
    await page.waitForFunction(() => document.getElementById("maj").textContent === "Confirmer la mise à jour");
    const confirmation = await page.evaluate(() => { const m = document.getElementById("maj").getBoundingClientRect(), t = document.querySelector("header.tete").getBoundingClientRect(); return m.right <= t.right + 0.5 || document.querySelector("header.tete").scrollWidth > document.querySelector("header.tete").clientWidth; });
    verifier("à 400 px, le bouton armé reste dans l'en-tête", confirmation);
    await page.waitForFunction(() => performance.now() - majArmeeLe > DELAI_CONFIRMATION + 50);
    await bouton(page).click();
    await page.waitForFunction(() => document.getElementById("maj-phrase").textContent.includes("simulée"));
    const phraseDansLaPage = await page.evaluate(() => { const p = document.getElementById("maj-phrase").getBoundingClientRect(); return p.left >= 0 && p.right <= window.innerWidth + 0.5 && document.getElementById("maj-phrase").scrollWidth <= document.getElementById("maj-phrase").clientWidth + 1; });
    verifier("à 400 px, la phrase tient dans la largeur", phraseDansLaPage);
    await page.mouse.move(2, 2);
    await capture(page, "etroit", { clip: { x: 0, y: 0, width: 400, height: 150 } });
    verifier("aucune erreur dans la page étroite", erreurs.length === 0, erreurs);
    await contexte.close();
  }

  /* ---------- 5. La page autonome des instantanés ---------- */
  console.log("\n== Partie 5 : la page des instantanés");
  {
    const fichier = path.join(fs.mkdtempSync(path.join(os.tmpdir(), "atelier-g-")), "instantanes.html");
    const r = spawnSync("python3", ["-m", "atelier", "instantanes", fichier], { cwd: RACINE, encoding: "utf8" });
    verifier("la commande instantanes réussit", r.status === 0, r.stderr);
    const { page, contexte, erreurs, requetes } = await ouvrir(browser, `file://${fichier}`, { viewport: { width: 1280, height: 800 } });
    const nombre = await page.evaluate(() => INSTANTANES.length);
    verifier("la page rejoue ses 43 vues enregistrées", nombre === 43, nombre);
    await jusqua(async () => page.evaluate(() => rejoue === true), 8000);
    verifier("sans champ mise_a_jour dans les vues, aucun bouton", !(await bouton(page).isVisible()));
    await page.evaluate(() => { INSTANTANES.forEach((v) => { v.mise_a_jour = { disponible: true, phrase: "" }; }); afficher(INSTANTANES[pas]); });
    verifier("avec un champ vrai, le bouton apparaît", await bouton(page).isVisible());
    await armerPuisConfirmer(page);
    await page.waitForFunction(() => /Démonstration rejouée/.test(document.getElementById("maj-phrase").textContent));
    verifier("un clic confirmé dit que la démonstration rejouée n'a rien à mettre à jour", /Démonstration rejouée/.test(await phrase(page)), await phrase(page));
    verifier("et n'envoie aucune requête", requetes.length === 0, requetes);
    verifier("aucune erreur dans la page autonome", erreurs.length === 0, erreurs);
    await contexte.close();
  }

  await browser.close();
}

function arreterServeurs() {
  for (const s of serveurs) { try { s.processus.kill("SIGKILL"); } catch (e) { /* déjà arrêté */ } }
}
process.on("exit", arreterServeurs);

main().then(() => {
  console.log(echecs ? `\n${echecs} vérification(s) en échec sur ${reussies + echecs}.` : `\nToutes les vérifications passent : ${reussies} sur ${reussies}.`);
  arreterServeurs();
  process.exit(echecs ? 1 : 0);
}).catch((erreur) => {
  console.error("\nECHEC  - l'essai s'est interrompu :", erreur);
  arreterServeurs();
  process.exit(1);
});
