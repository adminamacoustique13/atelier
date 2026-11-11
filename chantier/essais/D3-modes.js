/* Essai D3b : le menu « Mode des ouvriers » du tableau de bord, dans un navigateur sans écran.
 *
 * Lancer depuis la racine du dépôt :  node chantier/essais/D3-modes.js
 * Le script démarre lui-même `python3 -m atelier demo` (agents simulés, aucun appel réel), joue le scénario,
 * écrit les captures dans chantier/captures/D3-*.png, arrête les serveurs quoi qu'il arrive,
 * et sort avec un code non nul si une vérification échoue. Il attend des états de la page, pas des durées
 * (seule exception : laisser passer deux relectures du serveur pour constater que rien ne bouge).
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
const aller = (page, onglet) => page.evaluate((o) => { location.hash = `#${o}`; }, onglet);
/* Le haut de l'onglet Chantier, jusqu'à la fin de « La salle » : le menu dans son contexte, rien de coupé. */
const captureHaut = async (page, nom) => {
  const bas = await page.evaluate(() => { const c = document.getElementById("carte-mode").nextElementSibling.getBoundingClientRect(); return Math.ceil(c.bottom) + 10; });
  await page.screenshot({ path: path.join(CAPTURES, `D3-${nom}.png`), clip: { x: 0, y: 0, width: 1280, height: Math.min(bas, 800) } });
};
const capture = (cible, nom) => cible.screenshot({ path: path.join(CAPTURES, `D3-${nom}.png`) });
const bouton = (page, libelle) => page.locator("#mode-ouvriers button.mode-btn", { hasText: new RegExp(`^${libelle}$`) });
const pressé = async (page, libelle) => (await bouton(page, libelle).getAttribute("aria-pressed")) === "true";
const enVigueur = (page) => page.locator('#mode-ouvriers button.mode-btn[aria-pressed="true"]').allInnerTexts();
const explicationVisible = (page) => page.locator("#mode-ouvriers .expl").evaluateAll((l) => l.filter((e) => getComputedStyle(e).display !== "none").map((e) => e.textContent));

async function ouvrir(browser, url, options = {}) {
  const contexte = await browser.newContext({ viewport: { width: 1280, height: 800 }, deviceScaleFactor: 2, ...options });
  const page = await contexte.newPage();
  const erreurs = [], requetes = [];
  page.on("pageerror", (e) => erreurs.push(String(e)));
  page.on("console", (m) => { if (m.type() === "error" && !/Failed to load resource/.test(m.text())) erreurs.push(m.text()); });
  page.on("request", (r) => { if (r.method() === "POST") requetes.push({ url: new URL(r.url()).pathname, corps: r.postData() ? JSON.parse(r.postData()) : null }); });
  await page.goto(url);
  return { page, contexte, erreurs, requetes };
}

/* Une page dont /api/etat est fabriqué : `etatFaux.vue` est rendu tel quel ; `reponseMode` fabrique la réponse de POST /api/mode. */
async function ouvrirFausse(browser, url, vue, options = {}) {
  const etatFaux = { vue, reponseMode: null, mode: null };
  const o = await ouvrir(browser, "about:blank", options);
  await o.page.route("**/api/etat", (route) => route.fulfill({ json: etatFaux.vue }));
  await o.page.route("**/api/mode", async (route) => {
    etatFaux.mode = JSON.parse(route.request().postData());
    await etatFaux.reponseMode(route);
  });
  await o.page.goto(url);
  return { ...o, etatFaux };
}

const MODES = [
  ["default", "Me demander"], ["acceptEdits", "Accepter les modifications"], ["plan", "Répétition"],
  ["dontAsk", "Refuser sans demander"], ["auto", "Laisser un arbitre décider"],
];
const avecMode = (vue, choisi, appliques = []) => {
  const copie = JSON.parse(JSON.stringify(vue));
  copie.mode_ouvriers.choisi = choisi;
  copie.mode_ouvriers.libelle = MODES.find((m) => m[0] === choisi)[1];
  copie.mode_ouvriers.appliques = appliques;
  return copie;
};

async function main() {
  fs.mkdirSync(CAPTURES, { recursive: true });
  const browser = await chromium.launch();
  const s = await demarrer(3);
  const base = await etat(s);

  /* ---------- 1. Le menu sur la démonstration ---------- */
  console.log("\n== Partie 1 : le menu sur `atelier demo`");
  {
    const { page, contexte, erreurs, requetes } = await ouvrir(browser, s.url);
    verifier("la vue du serveur porte le menu", Boolean(base.mode_ouvriers) && base.mode_ouvriers.choix.length === 5);
    verifier("le menu est caché hors de l'onglet Chantier", !(await page.locator("#carte-mode").isVisible()));
    await aller(page, "chantier");
    await page.waitForSelector("#mode-ouvriers button.mode-btn");
    verifier("le titre de la carte est « Mode des ouvriers »", (await page.locator("#carte-mode h2").textContent()) === "Mode des ouvriers");
    const libelles = await page.locator("#mode-ouvriers button.mode-btn").allInnerTexts();
    verifier("cinq choix, dans l'ordre, avec les libellés du serveur", libelles.join("|") === MODES.map((m) => m[1]).join("|") && libelles.join("|") === base.mode_ouvriers.choix.map((c) => c.libelle).join("|"), libelles);
    verifier("la carte est entre la grille du haut et « La salle »", await page.evaluate(() => {
      const c = document.getElementById("carte-mode");
      return c.previousElementSibling.classList.contains("grille") && /La salle/.test(c.nextElementSibling.textContent);
    }));
    verifier("au départ, « Accepter les modifications » est en vigueur et seul en vigueur", (await enVigueur(page)).join("|") === "Accepter les modifications", await enVigueur(page));
    const attendue = base.mode_ouvriers.choix.find((c) => c.mode === "acceptEdits").explication;
    const visible = await explicationVisible(page);
    verifier("l'explication du serveur, et d'elle seule, est affichée sous le menu", visible.length === 1 && visible[0].includes(attendue) && visible[0].startsWith("Accepter les modifications"), visible);
    verifier("aucune ligne de mode réel quand aucun ouvrier ne diverge", (await page.locator("#mode-ouvriers-etat .mode-reel").count()) === 0);
    const taille = await page.evaluate(() => {
      const b = document.querySelector("#mode-ouvriers button.mode-btn");
      const t = (e) => getComputedStyle(e).fontSize;
      return { bouton: t(b), hauteur: b.getBoundingClientRect().height, explication: t(document.querySelector("#mode-ouvriers .expl.vigueur")), taches: t(document.querySelector("#attente").parentElement.querySelector("p, h2")) };
    });
    verifier("les boutons restent compacts (au plus 28 px de haut, texte de 12 px)", taille.hauteur <= 28 && taille.bouton === "12px", taille);
    await page.mouse.move(5, 5);
    await captureHaut(page, "menu");

    // Les autres explications : au survol, puis au clavier
    await page.locator("#mode-ouvriers button.mode-btn", { hasText: /^Répétition$/ }).hover();
    const survol = await explicationVisible(page);
    const attenduePlan = base.mode_ouvriers.choix.find((c) => c.mode === "plan").explication;
    verifier("au survol d'un autre choix, son explication remplace celle du choix en vigueur", survol.length === 1 && survol[0].includes(attenduePlan), survol);
    await captureHaut(page, "explication");
    await page.mouse.move(5, 5);
    verifier("la souris partie, l'explication du choix en vigueur revient", (await explicationVisible(page))[0].startsWith("Accepter les modifications"));
    await page.locator("#mode-ouvriers button.mode-btn").first().focus();
    await page.keyboard.press("Tab");
    await page.keyboard.press("Tab");
    const auClavier = await explicationVisible(page);
    const attendueFocus = base.mode_ouvriers.choix[2].explication;
    verifier("au focus clavier (Tab), l'explication du bouton atteint s'affiche", auClavier.length === 1 && auClavier[0].includes(attendueFocus), auClavier);
    verifier("chaque bouton est décrit par son explication (aria-describedby)", await page.evaluate(() =>
      [...document.querySelectorAll("#mode-ouvriers button.mode-btn")].every((b) => document.getElementById(b.getAttribute("aria-describedby"))?.textContent.length > 20)));

    // Les relectures du serveur ne font ni clignoter, ni perdre le focus
    await page.evaluate(() => { const b = document.querySelectorAll("#mode-ouvriers button.mode-btn")[2]; b.__marque = "meme-noeud"; });
    let lectures = 0;
    page.on("response", (r) => { if (new URL(r.url()).pathname === "/api/etat") lectures += 1; });
    await jusqua(async () => lectures >= 2, 8000);
    const apresLectures = await page.evaluate(() => ({ marque: document.activeElement.__marque, texte: document.activeElement.textContent }));
    verifier("deux relectures du serveur laissent le même bouton, avec son focus", lectures >= 2 && apresLectures.marque === "meme-noeud" && apresLectures.texte === "Répétition", { lectures, apresLectures });
    verifier("et laissent l'explication ouverte", (await explicationVisible(page))[0].includes(attendueFocus));
    await page.mouse.move(5, 5);
    await page.evaluate(() => document.activeElement.blur());

    // Un clic sur chacun des quatre autres choix
    const reponses = [];
    page.on("response", async (r) => { if (new URL(r.url()).pathname === "/api/mode") reponses.push(await r.json()); });
    let capturee = false;
    for (const [mode, libelle] of [["default", "Me demander"], ["plan", "Répétition"], ["dontAsk", "Refuser sans demander"], ["auto", "Laisser un arbitre décider"]]) {
      const avant = requetes.filter((r) => r.url === "/api/mode").length, nReponses = reponses.length;
      await bouton(page, libelle).click();
      await jusqua(async () => reponses.length > nReponses, 8000);
      const envoyees = requetes.filter((r) => r.url === "/api/mode").slice(avant);
      verifier(`« ${libelle} » envoie exactement {"mode": "${mode}"}`, envoyees.length === 1 && JSON.stringify(envoyees[0].corps) === JSON.stringify({ mode }), envoyees);
      const reponse = reponses[reponses.length - 1];
      verifier(`« ${libelle} » : la réponse du serveur dit que c'est fait`, Boolean(reponse) && reponse.changement_mode.fait === true && reponse.mode_ouvriers.choisi === mode, reponse && reponse.changement_mode);
      await jusqua(async () => (await pressé(page, libelle)), 8000);
      const surLaPage = await enVigueur(page);
      const duServeur = (await etat(s)).mode_ouvriers;
      verifier(`« ${libelle} » : le choix en vigueur affiché est celui que la vue annonce`, surLaPage.join("|") === libelle && duServeur.choisi === mode && duServeur.libelle === libelle, { surLaPage, duServeur: duServeur.choisi });
      verifier(`« ${libelle} » : la phrase du serveur est affichée telle quelle`, (await page.locator("#mode-ouvriers-etat").innerText()) === reponse.changement_mode.phrase, await page.locator("#mode-ouvriers-etat").innerText());
      verifier(`« ${libelle} » : l'explication affichée est celle du serveur`, (await explicationVisible(page)).join("").includes(duServeur.choix.find((c) => c.mode === mode).explication));
      if (mode === "dontAsk" && !capturee) { capturee = true; await page.mouse.move(5, 5); await captureHaut(page, "changement"); }
    }
    await page.mouse.move(5, 5);
    await bouton(page, "Accepter les modifications").click();
    await jusqua(async () => (await pressé(page, "Accepter les modifications")), 8000);

    // Un double clic n'envoie qu'une requête, le choix en cours d'envoi est visible comme tel
    const nAvant = requetes.filter((r) => r.url === "/api/mode").length;
    await bouton(page, "Répétition").dblclick();
    await jusqua(async () => (await pressé(page, "Répétition")), 8000);
    await PAUSE(300);
    const doubles = requetes.filter((r) => r.url === "/api/mode").slice(nAvant);
    verifier("un double clic n'envoie qu'une seule requête", doubles.length === 1 && doubles[0].corps.mode === "plan", doubles);

    // Cliquer sur le choix déjà en vigueur n'envoie rien
    const n2 = requetes.filter((r) => r.url === "/api/mode").length;
    await bouton(page, "Répétition").click();
    await PAUSE(300);
    verifier("cliquer sur le choix en vigueur n'envoie rien", requetes.filter((r) => r.url === "/api/mode").length === n2);
    verifier("aucune erreur dans la page", erreurs.length === 0, erreurs);
    await contexte.close();
    await fetch(`${s.url}/api/mode`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ mode: "acceptEdits" }) });
  }

  /* ---------- 2. Vues et réponses fabriquées ---------- */
  console.log("\n== Partie 2 : réponses refusées, envoi en échec, envoi lent");
  {
    const vue = avecMode(base, "acceptEdits");
    const { page, contexte, erreurs, etatFaux } = await ouvrirFausse(browser, s.url, vue);
    await aller(page, "chantier");
    await page.waitForSelector("#mode-ouvriers button.mode-btn");

    // fait: false : l'ancien choix reste, la phrase dit pourquoi
    const refus = "Ce mode n'existe pas : choisis parmi les cinq. Rien n'a changé.";
    etatFaux.reponseMode = (route) => route.fulfill({ json: { ...vue, changement_mode: { fait: false, phrase: refus } } });
    await bouton(page, "Refuser sans demander").click();
    await jusqua(async () => (await page.locator("#mode-ouvriers-etat").innerText()) === refus, 8000);
    verifier("la requête partie porte le mode cliqué", etatFaux.mode && etatFaux.mode.mode === "dontAsk", etatFaux.mode);
    verifier("fait: false : la phrase du serveur s'affiche", (await page.locator("#mode-ouvriers-etat").innerText()) === refus);
    verifier("fait: false : le choix en vigueur reste l'ancien", (await enVigueur(page)).join("|") === "Accepter les modifications");
    verifier("fait: false : la phrase est dans la couleur de l'attention", await page.locator("#mode-ouvriers-etat p").evaluate((e) => getComputedStyle(e).color === "rgb(255, 167, 110)"));

    // fait: true mais la vue ne confirme pas : le choix affiché suit la vue, pas la réponse
    etatFaux.reponseMode = (route) => route.fulfill({ json: { ...vue, changement_mode: { fait: true, phrase: "Mode des ouvriers : « Laisser un arbitre décider »." } } });
    await bouton(page, "Laisser un arbitre décider").click();
    await jusqua(async () => /Laisser un arbitre décider »\.$/.test(await page.locator("#mode-ouvriers-etat").innerText()), 8000);
    verifier("fait: true sans confirmation de la vue : le choix en vigueur affiché reste celui de la vue", (await enVigueur(page)).join("|") === "Accepter les modifications", await enVigueur(page));

    // L'envoi échoue : réseau coupé, puis réponse 500
    etatFaux.reponseMode = (route) => route.abort();
    await bouton(page, "Me demander").click();
    await jusqua(async () => /n'est pas parti/.test(await page.locator("#mode-ouvriers-etat").innerText()), 8000);
    verifier("envoi en échec : la phrase dit que le choix n'est pas parti", /Le choix n'est pas parti : le mode en vigueur n'a pas changé/.test(await page.locator("#mode-ouvriers-etat").innerText()), await page.locator("#mode-ouvriers-etat").innerText());
    verifier("envoi en échec : le choix en vigueur reste l'ancien", (await enVigueur(page)).join("|") === "Accepter les modifications");
    verifier("envoi en échec : le bouton n'est plus en cours d'envoi", (await page.locator("#mode-ouvriers button.envoi").count()) === 0);
    etatFaux.reponseMode = (route) => route.fulfill({ status: 500, json: { erreur: "panne" } });
    await bouton(page, "Me demander").click();
    await jusqua(async () => /n'est pas parti/.test(await page.locator("#mode-ouvriers-etat").innerText()), 8000);
    verifier("réponse 500 : même traitement, ancien choix conservé", (await enVigueur(page)).join("|") === "Accepter les modifications");

    // Un envoi lent : le choix en cours est visible, l'ancien reste en vigueur, un second clic est ignoré
    let liberer, attente = new Promise((r) => { liberer = r; });
    let demandes = 0;
    const apres = avecMode(base, "plan");
    etatFaux.reponseMode = async (route) => { demandes += 1; await attente; etatFaux.vue = apres; await route.fulfill({ json: { ...apres, changement_mode: { fait: true, phrase: "Mode des ouvriers : « Répétition »." } } }); };
    await bouton(page, "Répétition").click();
    await page.waitForSelector("#mode-ouvriers button.envoi");
    verifier("pendant l'envoi, le choix en cours est marqué (occupé) et dit en toutes lettres", (await bouton(page, "Répétition").getAttribute("aria-busy")) === "true" && /Envoi du mode « Répétition » en cours/.test(await page.locator("#mode-ouvriers-etat").innerText()), await page.locator("#mode-ouvriers-etat").innerText());
    verifier("pendant l'envoi, l'ancien choix reste en vigueur (rien n'est acquis avant la vue)", (await enVigueur(page)).join("|") === "Accepter les modifications" && !(await pressé(page, "Répétition")));
    await bouton(page, "Refuser sans demander").click();
    await bouton(page, "Répétition").click();
    await PAUSE(300);
    verifier("pendant l'envoi, un autre clic n'envoie rien", demandes === 1, demandes);
    liberer();
    await jusqua(async () => (await pressé(page, "Répétition")), 8000);
    verifier("la réponse reçue et la vue confirmée, le choix passe en vigueur", (await enVigueur(page)).join("|") === "Répétition" && (await page.locator("#mode-ouvriers button.envoi").count()) === 0);
    verifier("aucune erreur dans la page", erreurs.length === 0, erreurs);
    await contexte.close();
  }

  /* ---------- 3. Le mode réellement appliqué, et le texte hostile ---------- */
  console.log("\n== Partie 3 : le mode réel, affichage sûr");
  {
    const propre = avecMode(base, "auto", [{ agent: "B-ouvrier-1", mode: "default", libelle: "Me demander" }]);
    const o = await ouvrirFausse(browser, s.url, propre);
    await aller(o.page, "chantier");
    await o.page.waitForSelector("#mode-ouvriers-etat .mode-reel");
    verifier("une seule ligne quand un seul ouvrier diverge", (await o.page.locator("#mode-ouvriers-etat .mode-reel").count()) === 1);
    await o.page.mouse.move(5, 5);
    await captureHaut(o.page, "mode-reel");
    await o.contexte.close();
  }
  {
    const mal = '<img src=x onerror="window.__xss=1">';
    const vue = avecMode(base, "auto", [
      { agent: "B-ouvrier-1", mode: "default", libelle: "Me demander" },
      { agent: mal, mode: "inconnu", libelle: `<b>${mal}</b>` },
    ]);
    vue.mode_ouvriers.choix[3].libelle = `Refuser <i>${mal}`;
    vue.mode_ouvriers.choix[3].explication = `<script>window.__xss=2</script>${mal}`;
    const { page, contexte, erreurs } = await ouvrirFausse(browser, s.url, vue);
    await aller(page, "chantier");
    await page.waitForSelector("#mode-ouvriers-etat .mode-reel");
    const lignes = await page.locator("#mode-ouvriers-etat .mode-reel").allInnerTexts();
    verifier("une ligne par agent dont le mode diffère", lignes.length === 2, lignes);
    verifier("la ligne dit le nom de l'agent et le mode réellement appliqué", lignes[0] === "B-ouvrier-1 travaille en mode « Me demander », pas dans le mode choisi.", lignes[0]);
    verifier("un agent et un mode hostiles restent du texte", lignes[1] === `${mal} travaille en mode « <b>${mal}</b> », pas dans le mode choisi.`, lignes[1]);
    verifier("les lignes de mode réel sont dans l'orange de l'attention", await page.locator("#mode-ouvriers-etat .mode-reel").first().evaluate((e) => getComputedStyle(e).color === "rgb(255, 167, 110)"));
    const dom = await page.evaluate(() => ({ xss: window.__xss, images: document.querySelectorAll('img[src="x"]').length, scripts: document.querySelectorAll("#carte-mode script, #carte-mode img, #mode-ouvriers button i, #mode-ouvriers-etat b, #mode-ouvriers-etat i").length }));
    verifier("rien n'est exécuté ni interprété dans le menu (libellé, explication, agent)", dom.xss === undefined && dom.images === 0 && dom.scripts === 0, dom);
    const hostile = await bouton(page, "Refuser <i>" + mal.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).count();
    verifier("le libellé hostile d'un choix s'affiche comme du texte", hostile === 1);
    verifier("aucune erreur dans la page", erreurs.length === 0, erreurs);
    await contexte.close();
  }

  /* ---------- 4. Vues sans menu ---------- */
  console.log("\n== Partie 4 : sans menu ni projet");
  {
    const cas = {
      "sans la clé mode_ouvriers": (() => { const v = JSON.parse(JSON.stringify(base)); delete v.mode_ouvriers; return v; })(),
      "avec mode_ouvriers nul": { ...JSON.parse(JSON.stringify(base)), mode_ouvriers: null },
      "avec mode_ouvriers qui n'est pas un objet": { ...JSON.parse(JSON.stringify(base)), mode_ouvriers: "oups" },
      "avec des choix absents": { ...JSON.parse(JSON.stringify(base)), mode_ouvriers: { choisi: "auto" } },
      "avec des choix vides": { ...JSON.parse(JSON.stringify(base)), mode_ouvriers: { choisi: "auto", choix: [], appliques: [] } },
    };
    for (const [nom, vue] of Object.entries(cas)) {
      const { page, contexte, erreurs } = await ouvrirFausse(browser, s.url, vue);
      await aller(page, "chantier");
      await jusqua(async () => (await page.locator("#point").textContent()).length > 0, 8000);
      verifier(`vue ${nom} : pas de menu`, !(await page.locator("#carte-mode").isVisible()) && (await page.locator("#mode-ouvriers button").count()) === 0);
      verifier(`vue ${nom} : le reste du chantier s'affiche, sans erreur`, (await page.locator("#vue-chantier h2", { hasText: "La salle" }).isVisible()) && erreurs.length === 0, erreurs);
      await contexte.close();
    }
    // Un menu qui a existé puis disparaît (changement de projet) se retire
    const vue = avecMode(base, "plan");
    const { page, contexte, erreurs, etatFaux } = await ouvrirFausse(browser, s.url, vue);
    await aller(page, "chantier");
    await page.waitForSelector("#mode-ouvriers button.mode-btn");
    etatFaux.vue = { aucun_projet: true, racine: "/tmp/projets", projets: [] };
    await jusqua(async () => !(await page.locator("#carte-mode").isVisible()), 8000);
    verifier("sans projet ouvert, le menu disparaît", !(await page.locator("#carte-mode").isVisible()));
    verifier("sans projet ouvert, aucune erreur", erreurs.length === 0, erreurs);
    await contexte.close();
  }

  /* ---------- 5. Fenêtre étroite ---------- */
  console.log("\n== Partie 5 : fenêtre de 400 pixels");
  {
    const vue = avecMode(base, "auto", [{ agent: "B-ouvrier-1", mode: "default", libelle: "Me demander" }]);
    const { page, contexte, erreurs } = await ouvrirFausse(browser, s.url, vue, { viewport: { width: 400, height: 800 } });
    await aller(page, "chantier");
    await page.waitForSelector("#mode-ouvriers button.mode-btn");
    const mesure = await page.evaluate(() => {
      const carte = document.getElementById("carte-mode"), c = carte.getBoundingClientRect();
      const boites = [...document.querySelectorAll("#mode-ouvriers button.mode-btn, #mode .expl.vigueur, #mode-ouvriers-etat p")].map((e) => { const r = e.getBoundingClientRect(); return { l: r.left, h: r.top, r: r.right, b: r.bottom, nom: e.textContent.slice(0, 20) }; });
      const recoupe = [];
      for (let i = 0; i < boites.length; i++) for (let j = i + 1; j < boites.length; j++) {
        const a = boites[i], b = boites[j];
        if (a.l < b.r - 0.5 && b.l < a.r - 0.5 && a.h < b.b - 0.5 && b.h < a.b - 0.5) recoupe.push([a.nom, b.nom]);
      }
      return { debord: carte.scrollWidth - carte.clientWidth, dehors: boites.filter((b) => b.l < c.left - 0.5 || b.r > c.right + 0.5).map((b) => b.nom), recoupe, defilementHorizontal: document.documentElement.scrollWidth - window.innerWidth };
    });
    verifier("à 400 px, la carte ne déborde pas et rien ne sort de la carte", mesure.debord <= 1 && mesure.dehors.length === 0 && mesure.defilementHorizontal <= 0, mesure);
    verifier("à 400 px, aucune boîte du menu n'en recoupe une autre", mesure.recoupe.length === 0, mesure.recoupe);
    await page.locator("#carte-mode").scrollIntoViewIfNeeded();
    await page.mouse.move(2, 2);
    await capture(page.locator("#carte-mode"), "etroit");
    verifier("aucune erreur dans la page", erreurs.length === 0, erreurs);
    await contexte.close();
  }

  /* ---------- 6. La page autonome des instantanés ---------- */
  console.log("\n== Partie 6 : la page des instantanés");
  {
    const fichier = path.join(fs.mkdtempSync(path.join(os.tmpdir(), "atelier-d3-")), "instantanes.html");
    const r = spawnSync("python3", ["-m", "atelier", "instantanes", fichier], { cwd: RACINE, encoding: "utf8" });
    verifier("la commande instantanes réussit", r.status === 0, r.stderr);
    const contexte = await browser.newContext({ viewport: { width: 1280, height: 800 } });
    const page = await contexte.newPage();
    const erreurs = [], requetes = [];
    page.on("pageerror", (e) => erreurs.push(String(e)));
    page.on("request", (q) => { if (q.method() === "POST") requetes.push(q.url()); });
    await page.goto(`file://${fichier}`);
    const nombre = await page.evaluate(() => INSTANTANES.length);
    verifier("la page rejoue ses 42 vues enregistrées", nombre === 42, nombre);
    verifier("les vues enregistrées portent le menu", await page.evaluate(() => INSTANTANES.every((v) => v.mode_ouvriers && v.mode_ouvriers.choix.length === 5)));
    await aller(page, "chantier");
    await page.waitForSelector("#mode-ouvriers button.mode-btn");
    verifier("le menu est visible dans la page autonome, avec ses cinq choix", (await page.locator("#carte-mode").isVisible()) && (await page.locator("#mode-ouvriers button.mode-btn").count()) === 5);
    const avant = await enVigueur(page);
    await bouton(page, "Me demander").click();
    await page.waitForSelector("#mode-ouvriers-etat p");
    verifier("un clic dit que la démonstration rejouée n'envoie rien", /Démonstration rejouée/.test(await page.locator("#mode-ouvriers-etat").innerText()), await page.locator("#mode-ouvriers-etat").innerText());
    verifier("le choix en vigueur ne change pas, aucune requête ne part", (await enVigueur(page)).join("|") === avant.join("|") && requetes.length === 0, { avant, requetes });
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
