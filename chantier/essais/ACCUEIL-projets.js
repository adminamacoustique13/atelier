// Essai de la page d'accueil (projets, reprise, nouveau chantier), dans un navigateur sans écran, sur la démonstration.
// Usage : node chantier/essais/ACCUEIL-projets.js
const { chromium } = require('playwright');
const { spawn } = require('child_process');
const net = require('net');
const path = require('path');
const DEPOT = process.argv[2] || path.resolve(__dirname, '..', '..');
const CAPTURES = process.argv[3] || path.join(DEPOT, 'chantier', 'captures');
const sorties = [];
const ok = (nom, vrai) => { sorties.push(vrai); console.log(`${vrai ? 'ok    ' : 'ECHEC '} - ${nom}`); };
const portLibre = () => new Promise((r) => { const s = net.createServer(); s.listen(0, '127.0.0.1', () => { const p = s.address().port; s.close(() => r(p)); }); });
const pause = (ms) => new Promise((r) => setTimeout(r, ms));

(async () => {
  const port = await portLibre();
  const serveur = spawn('python3', ['-m', 'atelier', 'demo', '--port', String(port), '--delai', '0.2'], { cwd: DEPOT, stdio: 'ignore' });
  let nav;
  try {
    const base = `http://127.0.0.1:${port}`;
    const etat = async () => (await fetch(base + '/api/etat')).json();
    for (let i = 0; i < 100; i++) { try { if ((await fetch(base + '/api/etat')).ok) break; } catch (e) {} await pause(100); }
    nav = await chromium.launch();
    const page = await nav.newPage({ viewport: { width: 1280, height: 900 }, deviceScaleFactor: 2 });
    const erreurs = []; page.on('pageerror', (e) => erreurs.push(String(e.stack)));
    const carte = (id) => page.locator(`.projet-carte[data-id="${id}"]`);
    const accueil = async () => { await page.click('a.vers-accueil'); await page.locator('.projet-carte').first().waitFor(); await pause(300); };

    // L'arrivée : l'accueil, avec le projet de démonstration.
    await page.goto(base + '/');
    await carte('demonstration').waitFor();
    ok('sans onglet demandé, la page s\'ouvre sur l\'accueil', (await page.locator('#vue-accueil').isVisible()) && page.url().endsWith('/'));
    ok('l\'onglet Accueil est marqué', (await page.locator('.onglets a[data-onglet="accueil"]').getAttribute('aria-current')) === 'page');
    ok('une salutation et la date', /^(Bonjour|Bonsoir)\.$/.test(await page.locator('#accueil-salut').textContent())
      && (await page.locator('#accueil-date').textContent()).length > 5);
    ok('la démonstration ne propose pas de récupérer un vrai dépôt', await page.locator('#tuile-cloner').isHidden());
    ok('un projet sans chantier se dit « Pas commencé »', (await carte('demonstration').locator('.etat-projet').textContent()) === 'Pas commencé');
    ok('et propose seulement « Commencer »', (await carte('demonstration').locator('[data-action="reprendre"]').textContent()) === 'Commencer'
      && (await carte('demonstration').locator('[data-action="session-neuve"]').count()) === 0);
    await carte('demonstration').locator('[data-action="reprendre"]').click();
    await page.locator('#vue-conversation').waitFor();
    ok('« Commencer » mène à la conversation', page.url().endsWith('#conversation'));

    // Un chantier lancé : ses tâches se lisent depuis l'accueil.
    await page.fill('#message', 'Moteur de calcul : formules de la norme, validées sur les cas de référence.');
    await page.click('#envoi');
    await page.waitForSelector('#colonne button[data-action="valider"]', { timeout: 30000 });
    await page.click('#colonne button[data-action="valider"]');
    await page.waitForSelector('#colonne .autorisation', { timeout: 30000 });
    await accueil();
    const demo = carte('demonstration');
    ok('la carte porte le nom du chantier', (await demo.locator('.chantier-nom').textContent()).startsWith('« Moteur de calcul'));
    ok('une barre montre ses tâches', (await demo.locator('.barre-taches i').count()) === (await etat()).taches.length);
    ok('l\'état dit qu\'une question attend ou que des agents travaillent', /Une question t'attend|Agents au travail/.test(await demo.locator('.etat-projet').textContent()));
    ok('le projet affiché est marqué', (await demo.getAttribute('class')).includes('courant') && (await demo.textContent()).includes('affiché'));
    // Un nouveau chantier est refusé tant qu'un agent travaille, et la carte le dit.
    await demo.locator('[data-action="session-neuve"]').click();
    const form = demo.locator('form.session-neuve');
    await form.waitFor();
    ok('« Nouveau chantier » ouvre une confirmation dans la carte', (await form.textContent()).includes('sera archivé avec son journal'));
    ok('le nom proposé est celui du chantier', (await page.locator('#nom-session').inputValue()).startsWith('Moteur de calcul'));
    await form.locator('button[type="submit"]').click();
    let refus = '';
    for (let i = 0; i < 50 && !refus.includes('Un agent travaille'); i++) { await pause(100); refus = (await form.locator('.alerte').textContent()) || ''; }
    ok('tant qu\'un agent travaille, le refus est dit dans la carte', refus.includes('Un agent travaille'));
    await page.locator('#vue-accueil').screenshot({ path: path.join(CAPTURES, 'ACCUEIL-confirmation.png') });
    await form.locator('[data-action="session-annuler"]').click();
    ok('« Annuler » referme la confirmation', (await demo.locator('form.session-neuve').count()) === 0);

    // Un deuxième projet, créé depuis la tuile.
    await page.click('[data-action="accueil-creer"]');
    await page.fill('#nom-nouveau', 'Site de la boutique');
    await page.click('#creer');
    await page.waitForFunction(() => location.hash === '#conversation', null, { polling: 100 });
    ok('la tuile « Nouveau projet » crée un projet et ouvre sa conversation', (await etat()).projet === 'Site de la boutique');
    await page.fill('#message', 'Une page d\'accueil pour la boutique');
    await page.click('#envoi');
    await page.waitForSelector('#colonne button[data-action="valider"]', { timeout: 30000 });
    await accueil();
    const ids = await page.locator('.projet-carte').evaluateAll((cs) => cs.map((c) => c.dataset.id));
    ok('le projet touché le plus récemment vient en premier', ids[0] === 'site-de-la-boutique' && ids.length === 2);
    const site = carte('site-de-la-boutique');
    ok('un plan proposé se dit « Plan à valider »', (await site.locator('.etat-projet').textContent()) === 'Plan à valider');
    await page.screenshot({ path: path.join(CAPTURES, 'ACCUEIL.png') });

    // Reprendre l'autre projet : il s'ouvre là où il en était.
    await demo.locator('[data-action="reprendre"]').click();
    await page.waitForFunction(() => location.hash === '#chantier', null, { polling: 100 });
    ok('« Reprendre le chantier » rouvre le projet sur son tableau de bord', (await etat()).projet === 'Projet de démonstration');

    // Une nouvelle session dans le projet sans agent au travail : l'ancien chantier est archivé.
    await accueil();
    await site.locator('[data-action="session-neuve"]').click();
    await page.fill('#nom-session', 'Page d\'accueil, premier jet');
    await site.locator('form.session-neuve button[type="submit"]').click();
    await page.waitForFunction(() => location.hash === '#conversation', null, { polling: 100 });
    const apres = await etat();
    ok('« Archiver et commencer » ouvre le projet sur un chantier vide', apres.projet === 'Site de la boutique' && apres.taches.length === 0);
    ok('l\'ancien chantier est archivé sous le nom choisi', apres.archives.some((a) => a.nom === 'Page d\'accueil, premier jet'));
    await accueil();
    ok('la carte compte le chantier passé', (await site.locator('.projet-meta').textContent()).includes('1 chantier passé'));
    ok('et repart à « Pas commencé »', (await site.locator('.etat-projet').textContent()) === 'Pas commencé');

    // Un nom hostile reste du texte.
    const hostile = '<img src=x onerror="window.pirate=1">';
    await page.evaluate((h) => {
      accueil = [{ id: h, nom: h, courant: false, ouvert: false, archives: 1, fichiers: 0, en_ligne: h, activite: h, activite_fr: h,
        chantier: { nom: h, etat: h, phrase: h, taches: [h] } }];
      afficherAccueil();
    }, hostile);
    await pause(200);
    ok('un texte hostile reste du texte', (await page.evaluate(() => window.pirate)) === undefined
      && (await page.locator('#vue-accueil img').count()) === 0 && (await page.locator('.projet-carte h3').first().textContent()) === hostile);
    await page.evaluate(() => chargerAccueil());
    await carte('demonstration').waitFor();

    // Fenêtre étroite.
    await page.setViewportSize({ width: 400, height: 860 });
    await pause(400);
    ok('pas de débordement en fenêtre étroite', !(await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1)));
    await page.screenshot({ path: path.join(CAPTURES, 'ACCUEIL-etroit.png') });
    ok('aucune erreur dans la page', erreurs.length === 0);
    if (erreurs.length) console.log(erreurs);
  } finally { if (nav) await nav.close(); serveur.kill(); }
  const echecs = sorties.filter((v) => !v).length;
  console.log(echecs ? `${echecs} échec(s)` : `Toutes les vérifications passent : ${sorties.length} sur ${sorties.length}.`);
  process.exit(echecs ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(1); });
