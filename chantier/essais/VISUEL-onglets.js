// Essai du nouvel habillage (polices livrées, courbes d'activité, Salle isométrique, câblage du Plan),
// dans un navigateur sans écran, sur la démonstration.
//
// Lancer depuis la racine du dépôt :  node chantier/essais/VISUEL-onglets.js
// Le script démarre lui-même `python3 -m atelier demo` (agents simulés, aucun appel réel), écrit les captures
// dans chantier/captures/VISUEL-*.png, arrête le serveur quoi qu'il arrive et sort en erreur si une
// vérification échoue.
const { chromium } = require('playwright');
const { spawn } = require('child_process');
const net = require('net');
const path = require('path');

const DEPOT = path.resolve(__dirname, '..', '..');
const CAPTURES = path.join(DEPOT, 'chantier', 'captures');
const pause = (ms) => new Promise((r) => setTimeout(r, ms));
let echecs = 0;
const ok = (nom, vrai, detail) => { console.log(`${vrai ? 'ok    ' : 'ECHEC '} - ${nom}${vrai || detail === undefined ? '' : ` (${JSON.stringify(detail)})`}`); if (!vrai) echecs++; };
const portLibre = () => new Promise((r) => { const s = net.createServer(); s.listen(0, '127.0.0.1', () => { const { port } = s.address(); s.close(() => r(port)); }); });

(async () => {
  const port = await portLibre(), base = `http://127.0.0.1:${port}`;
  // Des agents lents (20 s) : le chantier reste en marche pendant tout l'essai.
  const serveur = spawn('python3', ['-m', 'atelier', 'demo', '--port', String(port), '--delai', '20'], { cwd: DEPOT, stdio: 'ignore' });
  const navigateur = await chromium.launch();
  try {
    for (let i = 0; i < 50; i++) { try { await fetch(base + '/api/etat'); break; } catch { await pause(200); } }
    // Les polices sont livrées avec l'Atelier, et seules celles-ci sont servies.
    const police = await fetch(base + '/polices/geist.woff2');
    ok('Geist est servie en woff2', police.status === 200 && police.headers.get('content-type') === 'font/woff2');
    ok('Doto est servie', (await fetch(base + '/polices/doto.woff')).status === 200);
    ok('une police inconnue ne l\'est pas', (await fetch(base + '/polices/../serveur.py')).status === 404);

    const page = await navigateur.newPage({ viewport: { width: 1440, height: 900 } });
    const erreurs = [];
    page.on('pageerror', (e) => erreurs.push(String(e)));
    page.on('console', (m) => { if (m.type() === 'error') erreurs.push(m.text()); });
    const etat = () => page.evaluate(() => fetch('/api/etat').then((r) => r.json()));
    const post = (a, c) => page.evaluate(([a, c]) => fetch(a, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(c || {}) }).then((r) => r.json()), [a, c]);
    await page.goto(base + '/#accueil');
    await page.waitForSelector('.projet-carte');
    ok('les polices du tableau sont chargées', await page.evaluate(async () => { await document.fonts.ready; return document.fonts.check('900 20px Doto') && document.fonts.check('12px "Geist Mono"'); }));
    await page.screenshot({ path: path.join(CAPTURES, 'VISUEL-accueil.png') });

    await post('/api/message', { texte: 'Moteur de calcul : formules de la norme, validées sur les cas de référence.' });
    let vue = null;
    for (let i = 0; i < 80; i++) { vue = await etat(); if (vue.taches.length && !vue.occupe) break; await pause(250); }
    ok('le plan est proposé', vue.taches.length > 0);
    await page.goto(base + '/#plan');
    await page.waitForSelector('.cablage .noeud[data-id]');
    ok('le Plan est un câblage : un nœud par tâche', (await page.locator('.cablage .noeud[data-id]').count()) === vue.taches.length);
    ok('contrat à valider : un fil ambre va de l\'orchestrateur à « Toi »', (await page.locator('.cablage path.fil-lien.attend').count()) >= 1 && (await page.locator('.cablage .noeud.fixe.attend').count()) === 1);
    await post('/api/contrat/valider');
    for (let i = 0; i < 80; i++) { vue = await etat(); if ((vue.autorisations || []).length) break; await pause(250); }
    const attendue = (vue.autorisations[0].agent || '').split('-').slice(0, -2).join('-');
    ok('une autorisation attend', Boolean(attendue), vue.autorisations);
    await pause(1500); // quelques tranches d'activité

    // Chantier : l'anneau de points, et la courbe de chaque poste.
    await page.goto(base + '/#chantier');
    await page.waitForSelector('#anneau svg.anneau-points');
    ok('le module 01 porte l\'anneau de points', (await page.locator('#anneau svg.anneau-points circle').count()) === 120);
    const couleurs = await page.locator('svg.salle circle').evaluateAll((l) => l.map((c) => c.getAttribute('fill')));
    ok('les postes en marche ont une courbe bleu acier', couleurs.includes('#8297c4'));
    ok('le poste qui t\'attend a sa queue ambre', couleurs.includes('#e8953a'));
    ok('le module 02 est teinté quand quelque chose t\'attend', await page.locator('#carte-attente').evaluate((e) => e.classList.contains('attend')));
    ok('le serveur envoie les rythmes en direct', Object.keys((await etat()).rythmes.en_direct).length > 0);
    await page.screenshot({ path: path.join(CAPTURES, 'VISUEL-chantier.png') });

    // Salle : une colonne et une étiquette par poste, plus l'orchestrateur et la livraison.
    await page.goto(base + '/#salle');
    await page.waitForSelector('#salle-etiquettes .s-tag');
    ok('une étiquette par tâche, plus l\'orchestrateur et la livraison', (await page.locator('#salle-etiquettes .s-tag').count()) === vue.taches.length + 2);
    ok('la tâche qui t\'attend est en ambre', (await page.locator(`#salle-etiquettes .s-tag.attend[data-id="${attendue}"]`).count()) === 1);
    ok('le sol porte les colonnes', (await page.locator('#salle-sol polygon').count()) >= 3 * vue.taches.length);
    ok('le panneau « Ce qui t\'attend » porte l\'autorisation', (await page.locator('#salle-attente .autorisation button').count()) >= 2 && await page.locator('#salle-attente').isVisible());
    await page.screenshot({ path: path.join(CAPTURES, 'VISUEL-salle.png') });
    await page.click(`#salle-etiquettes .s-tag[data-id="${attendue}"]`);
    await page.waitForFunction(() => location.hash === '#plan');
    ok('un clic sur une étiquette ouvre la tâche dans le Plan', (await page.locator(`.noeud.choisie[data-id="${attendue}"]`).count()) === 1);
    ok('la fiche porte l\'autorisation de la tâche', (await page.locator('#fiche .autorisation').count()) === 1);
    ok('le fil de la tâche qui attend mène à « Toi »', (await page.locator('.cablage path.fil-lien.attend').count()) >= 1);
    await page.screenshot({ path: path.join(CAPTURES, 'VISUEL-plan.png') });
    await page.goto(base + '/#conversation');
    await page.waitForSelector('#rail-anneau svg.anneau-points');
    ok('le rail de la conversation porte l\'anneau', true);
    await page.screenshot({ path: path.join(CAPTURES, 'VISUEL-conversation.png') });

    // Code : l'explorateur reste à gauche.
    await post('/api/carte/analyser');
    await page.goto(base + '/#code');
    await page.locator('#explorateur .ligne-arbre').first().waitFor({ timeout: 30000 });
    await page.locator('#code-page .cd-chaine').waitFor({ timeout: 30000 });
    ok('l\'explorateur et la chaîne du code se voient ensemble', await page.locator('#explorateur').isVisible() && await page.locator('#code-page .cd-chaine').isVisible());
    await page.screenshot({ path: path.join(CAPTURES, 'VISUEL-code.png') });

    // Fenêtre étroite : rien ne déborde sur le côté.
    await page.setViewportSize({ width: 400, height: 860 });
    for (const onglet of ['chantier', 'salle', 'plan', 'conversation']) {
      await page.goto(base + '/#' + onglet);
      await pause(500);
      const largeur = await page.evaluate(() => document.documentElement.scrollWidth);
      ok(`à 400 px, l'onglet ${onglet} ne déborde pas`, largeur <= 400, largeur);
    }
    await page.goto(base + '/#salle'); await pause(400);
    await page.screenshot({ path: path.join(CAPTURES, 'VISUEL-salle-etroit.png'), fullPage: true });
    ok('aucune erreur dans la page', erreurs.length === 0, erreurs);
  } catch (e) {
    ok('l\'essai s\'est interrompu : ' + e.message.split('\n')[0], false);
  } finally {
    await navigateur.close();
    serveur.kill('SIGKILL');
  }
  console.log(echecs ? `\n${echecs} échec(s)` : '\nTout est vérifié.');
  process.exit(echecs ? 1 : 0);
})();
