/* Prend les images des maquettes V1, sans réseau : `node maquettes/capturer-salle-agents.js`.
   Pour chaque page : <nom>.png (fenêtre 1280 × 900) et <nom>-etroit.png (420 de large, page entière). */
const path = require("path");
const { chromium } = require("playwright");

const PAGES = ["salle-agents-a", "salle-agents-b", "depot"];

(async () => {
  const seules = process.argv.slice(2);
  const navigateur = await chromium.launch();
  for (const nom of PAGES.filter((p) => !seules.length || seules.includes(p))) {
    for (const [suffixe, largeur, hauteur] of [["", 1280, 900], ["-etroit", 420, 900]]) {
      const contexte = await navigateur.newContext({ viewport: { width: largeur, height: hauteur }, deviceScaleFactor: 2, offline: true });
      const page = await contexte.newPage();
      const soucis = [];
      page.on("pageerror", (e) => soucis.push(String(e)));
      page.on("requestfailed", (r) => soucis.push(`introuvable : ${r.url()}`));
      await page.goto("file://" + path.join(__dirname, `${nom}.html`));
      await page.evaluate(() => document.fonts.ready);
      const debord = await page.evaluate(() => ({ l: document.documentElement.scrollWidth, h: document.documentElement.scrollHeight }));
      await page.screenshot({ path: path.join(__dirname, `${nom}${suffixe}.png`), fullPage: true });
      console.log(`${nom}${suffixe}.png : page de ${debord.l} × ${debord.h} pour une fenêtre de ${largeur} × ${hauteur}${soucis.length ? " · " + soucis.join(" ; ") : ""}`);
      await contexte.close();
    }
  }
  await navigateur.close();
})();
