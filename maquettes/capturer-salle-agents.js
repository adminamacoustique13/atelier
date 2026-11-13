/* Prend les images des maquettes V1, sans réseau : `node maquettes/capturer-salle-agents.js`.
   Pour chaque vue : <nom>.png (fenêtre 1280 × 900) et <nom>-etroit.png (420 de large, page entière).
   Pour les deux pistes de la Salle, en plus : <nom>-gris.png, la même image large en niveaux de gris,
   pour vérifier que les rôles se lisent sans la couleur ; et <nom>-32.png, l'épreuve de charge
   (« ?charge=32 » : soixante tâches, 32 places).
   Un ou plusieurs noms en argument ne reprennent que ces vues : `... salle-agents-a-32 depot`. */
const path = require("path");
const { chromium } = require("playwright");

const VUES = [
  { nom: "salle-agents-a", page: "salle-agents-a.html", gris: true },
  { nom: "salle-agents-b", page: "salle-agents-b.html", gris: true },
  { nom: "salle-agents-a-32", page: "salle-agents-a.html?charge=32" },
  { nom: "salle-agents-b-32", page: "salle-agents-b.html?charge=32" },
  { nom: "depot", page: "depot.html" },
];

(async () => {
  const seules = process.argv.slice(2);
  const navigateur = await chromium.launch();
  for (const vue of VUES.filter((v) => !seules.length || seules.includes(v.nom))) {
    for (const [suffixe, largeur, hauteur] of [["", 1280, 900], ["-etroit", 420, 900]]) {
      const contexte = await navigateur.newContext({ viewport: { width: largeur, height: hauteur }, deviceScaleFactor: 2, offline: true });
      const page = await contexte.newPage();
      const soucis = [];
      page.on("pageerror", (e) => soucis.push(String(e)));
      page.on("requestfailed", (r) => soucis.push(`introuvable : ${r.url()}`));
      await page.goto("file://" + path.join(__dirname, vue.page));
      await page.evaluate(() => document.fonts.ready);
      const debord = await page.evaluate(() => ({ l: document.documentElement.scrollWidth, h: document.documentElement.scrollHeight }));
      await page.screenshot({ path: path.join(__dirname, `${vue.nom}${suffixe}.png`), fullPage: true });
      console.log(`${vue.nom}${suffixe}.png : page de ${debord.l} × ${debord.h} pour une fenêtre de ${largeur} × ${hauteur}${soucis.length ? " · " + soucis.join(" ; ") : ""}`);
      if (!suffixe && vue.gris) {
        await page.addStyleTag({ content: "html { filter: grayscale(1); }" });
        await page.screenshot({ path: path.join(__dirname, `${vue.nom}-gris.png`), fullPage: true });
        console.log(`${vue.nom}-gris.png : la même, en niveaux de gris`);
      }
      await contexte.close();
    }
  }
  await navigateur.close();
})();
