// Essai du bouton « Nouveau chantier » dans un navigateur sans écran, sur la démonstration.
// Usage : node chantier/essais/NC-nouveau-chantier.js
const { chromium } = require('playwright');
const { spawn } = require('child_process');
const net = require('net');
const path = require('path');
const DEPOT = process.argv[2] || path.resolve(__dirname, '..', '..');
const CAPTURES = process.argv[3] || path.join(DEPOT, 'chantier', 'captures');
const sorties = [];
const ok = (nom, vrai) => { sorties.push(vrai); console.log(`${vrai ? 'ok    ' : 'ECHEC '} - ${nom}`); };
const portLibre = () => new Promise((r) => { const s = net.createServer(); s.listen(0, '127.0.0.1', () => { const p = s.address().port; s.close(() => r(p)); }); });
(async () => {
  const port = await portLibre();
  const serveur = spawn('python3', ['-m', 'atelier', 'demo', '--port', String(port), '--delai', '0.2'], { cwd: DEPOT, stdio: 'ignore' });
  let nav;
  try {
    const base = `http://127.0.0.1:${port}`;
    for (let i = 0; i < 100; i++) { try { if ((await fetch(base + '/api/etat')).ok) break; } catch (e) {} await new Promise((r) => setTimeout(r, 100)); }
    nav = await chromium.launch();
    const page = await nav.newPage({ viewport: { width: 1280, height: 900 }, deviceScaleFactor: 2 });
    const erreurs = []; page.on('pageerror', (e) => erreurs.push(String(e)));
    const requetes = []; page.on('request', (q) => { if (q.url().endsWith('/api/chantier/nouveau')) requetes.push(q.method()); });
    await page.goto(base + '/#chantier');
    const bouton = page.locator('#nouveau-chantier');
    await bouton.waitFor();
    ok('le bouton « Nouveau chantier » est dans l\'onglet Chantier', (await bouton.textContent()) === 'Nouveau chantier');
    // Chantier vide : le serveur refuse et la phrase s'affiche.
    await bouton.click(); await page.waitForTimeout(500); await bouton.click();
    await page.waitForFunction(() => document.getElementById('nouveau-chantier-phrase').textContent.includes('encore vide'));
    ok('un chantier vide n\'est pas archivé, et la page le dit', true);
    // Un objectif, puis le plan : il y a maintenant quelque chose à archiver.
    await page.goto(base + '/#conversation');
    await page.fill('textarea, input[type=text]:not([id^=adresse])', 'Un objectif d\'essai');
    await page.keyboard.press('Enter');
    for (let i = 0; i < 150; i++) { const v = await (await fetch(base + '/api/etat')).json(); if (v.taches.length > 0 && !v.occupe) break; await new Promise((r) => setTimeout(r, 100)); }
    await page.goto(base + '/#chantier');
    await page.waitForFunction(() => document.querySelectorAll('#salle [data-action], #salle .poste, #salle svg').length > 0);
    // Un double-clic ne confirme pas.
    const avant = requetes.length;
    await bouton.dblclick(); await page.waitForTimeout(300);
    ok('un double-clic n\'envoie rien', requetes.length === avant);
    ok('le premier clic arme le bouton', (await bouton.textContent()) === 'Confirmer le nouveau chantier');
    await page.screenshot({ path: CAPTURES + '/NC-confirmation.png', clip: { x: 0, y: 0, width: 1280, height: 330 } });
    await page.waitForTimeout(500);
    await bouton.click();
    await page.waitForFunction(() => document.getElementById('nouveau-chantier-phrase').textContent.startsWith('Nouveau chantier ouvert.'), null, { timeout: 5000 });
    ok('le second clic envoie la demande', requetes.length === avant + 1);
    const vue = await (await fetch(base + '/api/etat')).json();
    ok('le projet repart sans tâche', vue.taches.length === 0);
    ok('l\'ancienne conversation n\'est plus dans la vue', !JSON.stringify(vue).includes('Un objectif d\'essai'));
    ok('le bouton revient à son libellé', (await bouton.textContent()) === 'Nouveau chantier');
    await page.screenshot({ path: CAPTURES + '/NC-apres.png', clip: { x: 0, y: 0, width: 1280, height: 330 } });
    await page.setViewportSize({ width: 400, height: 800 });
    await page.waitForTimeout(200);
    const debord = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1);
    ok('pas de débordement en fenêtre étroite', !debord);
    ok('aucune erreur dans la page', erreurs.length === 0);
    if (erreurs.length) console.log(erreurs);
  } finally { if (nav) await nav.close(); serveur.kill(); }
  const echecs = sorties.filter((v) => !v).length;
  console.log(echecs ? `${echecs} échec(s)` : `Toutes les vérifications passent : ${sorties.length} sur ${sorties.length}.`);
  process.exit(echecs ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(1); });
