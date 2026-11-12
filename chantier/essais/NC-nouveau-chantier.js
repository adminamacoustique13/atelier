// Essai de « Nouveau chantier » et des chantiers archivés, dans un navigateur sans écran, sur la démonstration.
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
    const erreurs = []; page.on('pageerror', (e) => erreurs.push(String(e)));
    const envois = []; page.on('request', (q) => { if (q.url().endsWith('/api/chantier/nouveau')) envois.push(JSON.parse(q.postData() || '{}')); });
    const bouton = page.locator('#nouveau-chantier'), form = page.locator('#form-nouveau-chantier');
    const champ = page.locator('#nom-chantier'), archiver = page.locator('#archiver-chantier');
    const phrase = page.locator('#nouveau-chantier-phrase');

    await page.goto(base + '/#chantier');
    await bouton.waitFor();
    ok('le bouton « Nouveau chantier » est dans l\'onglet Chantier', (await bouton.textContent()) === 'Nouveau chantier');
    ok('aucun chantier archivé au départ : la carte est cachée', await page.locator('#carte-archives').isHidden());

    // Un chantier vide : le serveur refuse, la page le dit.
    await bouton.click();
    ok('un clic ouvre le formulaire et cache le bouton', (await form.isVisible()) && (await bouton.isHidden()));
    await archiver.click();
    await page.waitForFunction(() => document.getElementById('nouveau-chantier-phrase').textContent.includes('encore vide'));
    ok('un chantier vide n\'est pas archivé, et la page le dit', true);
    await page.click('[data-action="nouveau-chantier-annuler"]');
    ok('« Annuler » referme le formulaire', (await form.isHidden()) && (await bouton.isVisible()));

    // Un objectif : l'orchestrateur simulé propose un plan, il y a maintenant de quoi archiver.
    await page.goto(base + '/#conversation');
    await page.fill('#message', 'Un objectif d\'essai');
    await page.keyboard.press('Enter');
    for (let i = 0; i < 150; i++) { const v = await etat(); if (v.taches.length > 0 && !v.occupe) break; await pause(100); }
    await page.goto(base + '/#chantier');
    await bouton.waitFor();
    const propose = (await etat()).nom_propose;
    await bouton.click();
    for (let i = 0; i < 30 && (await champ.inputValue()) !== propose; i++) await pause(100);
    ok('le champ propose le nom à jour venu du serveur', propose.length > 0 && (await champ.inputValue()) === propose);
    // Un rafraîchissement ne réécrit pas ce qu'on tape.
    await champ.fill('Moteur de calcul, première version');
    await pause(2500);
    ok('ce qu\'on tape survit aux rafraîchissements', (await champ.inputValue()) === 'Moteur de calcul, première version');
    await page.screenshot({ path: path.join(CAPTURES, 'NC-formulaire.png'), clip: { x: 0, y: 0, width: 1280, height: 420 } });
    // Deux clics rapprochés n'envoient qu'une demande.
    const avant = envois.length;
    await archiver.dblclick();
    await page.waitForFunction(() => document.getElementById('nouveau-chantier-phrase').textContent.startsWith('Nouveau chantier ouvert.'));
    ok('un double-clic n\'envoie qu\'une demande', envois.length === avant + 1);
    ok('le nom tapé part avec la demande', envois[envois.length - 1].nom === 'Moteur de calcul, première version');
    ok('le formulaire se referme après l\'archivage', await form.isHidden());
    const vue = await etat();
    ok('le projet repart sans tâche', vue.taches.length === 0);
    ok('l\'ancienne conversation n\'est plus dans la vue courante', !JSON.stringify(vue.evenements).includes('Un objectif d\'essai'));

    // La liste des archives.
    const ligne = page.locator('.archive-ligne').first();
    await ligne.waitFor();
    ok('la carte « Chantiers archivés » apparaît', await page.locator('#carte-archives').isVisible());
    ok('la ligne porte le nom choisi', (await ligne.locator('b').textContent()) === 'Moteur de calcul, première version');
    const dates = await ligne.locator('.petit').textContent();
    ok('la ligne porte les dates', /^Du \d+ \S+ \d{4} à \d+ h \d{2} au \d+ \S+ \d{4} à \d+ h \d{2}$/.test(dates));
    ok('la ligne porte le bilan', /tâche/.test(await ligne.locator('.bilan').textContent()));
    await page.locator('#carte-archives').scrollIntoViewIfNeeded();
    await page.locator('#carte-archives').screenshot({ path: path.join(CAPTURES, 'NC-liste.png') });

    // Le journal.
    await ligne.click();
    const fenetre = page.locator('#archive');
    await fenetre.waitFor({ state: 'visible' });
    const texte = await fenetre.textContent();
    ok('le journal s\'ouvre avec le nom du chantier', (await page.locator('#titre-archive').textContent()) === 'Moteur de calcul, première version');
    for (const section of ['Livré', 'Pas terminé', 'Tes décisions', 'Les chiffres']) ok(`le journal a sa section « ${section} »`, texte.includes(section));
    ok('le journal dit que la démonstration n\'a rien livré pour de vrai', texte.includes('Démonstration : rien n\'a été livré pour de vrai.'));
    ok('le fil complet est replié', !(await page.locator('#archive details').evaluate((d) => d.open)));
    ok('le fil complet contient l\'ancien objectif', texte.includes('Un objectif d\'essai'));
    await page.screenshot({ path: path.join(CAPTURES, 'NC-journal.png') });
    await page.click('#fermer-archive');
    ok('« Fermer » referme le journal', await fenetre.isHidden());

    // Un nom ou un texte hostile reste du texte, dans la liste comme dans le journal (vues fabriquées).
    const hostile = '<img src=x onerror="window.pirate=1">';
    await page.evaluate((h) => {
      afficherArchives({ archives: [{ id: 'x', nom: h, ouvert_le: '', archive_le: h, bilan: h }] });
      document.getElementById('contenu-archive').innerHTML = journalHtml({ nom: h, objectif: h, ouvert_le: '', archive_le: h, bilan: h,
        en_ligne: h, livre: [{ id: h, titre: h, detail: h }], inacheve: [{ id: h, titre: h, etat: h, raison: h }],
        decisions: [{ question: h, reponse: h }], chiffres: [[h, h]], fil: [{ heure: h, auteur: h, texte: h }] });
    }, hostile);
    await pause(200);
    ok('un texte hostile reste du texte', (await page.evaluate(() => window.pirate)) === undefined
      && (await page.locator('#archives img, #contenu-archive img').count()) === 0
      && (await page.locator('.archive-ligne b').first().textContent()) === hostile);
    await page.evaluate(() => afficherArchives(derniere));

    // Fenêtre étroite.
    await page.setViewportSize({ width: 400, height: 800 });
    await pause(300);
    const deborde = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1);
    ok('pas de débordement en fenêtre étroite', !deborde);
    await ligne.click();
    await fenetre.waitFor({ state: 'visible' });
    const largeur = await fenetre.evaluate((d) => d.getBoundingClientRect().width);
    ok('le journal tient dans une fenêtre étroite', largeur <= 400);
    await page.screenshot({ path: path.join(CAPTURES, 'NC-journal-etroit.png') });
    await page.click('#fermer-archive');
    ok('aucune erreur dans la page', erreurs.length === 0);
    if (erreurs.length) console.log(erreurs);
  } finally { if (nav) await nav.close(); serveur.kill(); }
  const echecs = sorties.filter((v) => !v).length;
  console.log(echecs ? `${echecs} échec(s)` : `Toutes les vérifications passent : ${sorties.length} sur ${sorties.length}.`);
  process.exit(echecs ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(1); });
