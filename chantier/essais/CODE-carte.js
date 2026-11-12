// Essai de l'onglet Code (explorateur, constellation, fiche, clignotement), dans un navigateur sans écran, sur la démonstration.
// Usage : node chantier/essais/CODE-carte.js
const { chromium } = require('playwright');
const { spawn } = require('child_process');
const fs = require('fs');
const net = require('net');
const path = require('path');
const DEPOT = process.argv[2] || path.resolve(__dirname, '..', '..');
const CAPTURES = process.argv[3] || path.join(DEPOT, 'chantier', 'captures');
const sorties = [];
const ok = (nom, vrai) => { sorties.push(vrai); console.log(`${vrai ? 'ok    ' : 'ECHEC '} - ${nom}`); };
const portLibre = () => new Promise((r) => { const s = net.createServer(); s.listen(0, '127.0.0.1', () => { const p = s.address().port; s.close(() => r(p)); }); });
const pause = (ms) => new Promise((r) => setTimeout(r, ms));

(async () => {
  // La démonstration montre le code de l'Atelier lui-même : on repart d'une carte absente.
  fs.rmSync(path.join(DEPOT, '.atelier', 'carte.json'), { force: true });
  const port = await portLibre();
  const serveur = spawn('python3', ['-m', 'atelier', 'demo', '--port', String(port), '--delai', '0.2'], { cwd: DEPOT, stdio: 'ignore' });
  let nav;
  try {
    const base = `http://127.0.0.1:${port}`;
    for (let i = 0; i < 100; i++) { try { if ((await fetch(base + '/api/etat')).ok) break; } catch (e) {} await pause(100); }
    nav = await chromium.launch();
    const page = await nav.newPage({ viewport: { width: 1280, height: 860 }, deviceScaleFactor: 2 });
    const erreurs = []; page.on('pageerror', (e) => erreurs.push(String(e.stack)));
    const appels = []; page.on('request', (q) => { if (q.url().includes('/api/carte/')) appels.push(new URL(q.url()).pathname); });

    // Avant l'analyse : une explication et un bouton, rien d'autre.
    await page.goto(base + '/#code');
    const bouton = page.locator('#code-actions button[data-action="analyser-code"]');
    await bouton.waitFor();
    ok('l\'onglet Code propose « Analyser le code »', (await bouton.textContent()) === 'Analyser le code');
    ok('la page explique ce que fait la carte', (await page.locator('#code-vide').textContent()).includes('seuls les fichiers changés sont relus'));
    ok('ni explorateur ni constellation avant l\'analyse', (await page.locator('#explorateur').isHidden()) && (await page.locator('#constellation').isHidden()));

    // L'estimation, puis l'analyse.
    await bouton.click();
    const lancer = page.locator('#code-actions button[data-action="lancer-analyse"]');
    await lancer.waitFor();
    ok('l\'estimation s\'affiche avant de lancer', (await page.locator('#code-actions').textContent()).includes('sans appel à Claude'));
    await page.click('#code-actions button[data-action="annuler-analyse"]');
    ok('« Annuler » revient au bouton', await bouton.isVisible());
    ok('annuler ne lance rien', !appels.includes('/api/carte/analyser'));
    await bouton.click();
    await lancer.click();
    await page.locator('#explorateur .ligne-arbre').first().waitFor({ timeout: 30000 });
    ok('l\'analyse remplit l\'explorateur', true);
    const etat = await page.locator('#code-etat').textContent();
    ok('la ligne d\'état compte les fichiers', /^\d+ fichiers · analysé le/.test(etat)); if (!/^\d+ fichiers · analysé le/.test(etat)) console.log(etat);

    // L'explorateur : un dossier se déroule, un fichier montre à quoi il sert.
    const dossier = page.locator('#explorateur .ligne-arbre.dossier[data-chemin="atelier"]');
    ok('le dossier atelier est ouvert d\'emblée (petit projet)', (await dossier.getAttribute('aria-expanded')) === 'true');
    const carte = page.locator('#explorateur .ligne-arbre.fichier[data-chemin="atelier/modele.py"]');
    await carte.click();
    await page.locator('#explorateur .fichier-ouvert').first().waitFor();
    const ouvert = await page.locator('#explorateur .fichier-ouvert').first().textContent();
    ok('le fichier déroulé dit à quoi il sert', ouvert.length > 40);
    ok('le fichier déroulé liste ses parties', (await page.locator('#explorateur .fichier-ouvert ul.pieces li').count()) > 3);
    const fiche = page.locator('#fiche-code');
    ok('la fiche porte le nom du fichier', (await fiche.locator('h2').textContent()) === 'modele.py');
    ok('la fiche dit qui se sert de lui', (await fiche.textContent()).includes('Ils se servent de lui'));
    await page.locator('#vue-code').screenshot({ path: path.join(CAPTURES, 'CODE-explorateur.png') });
    await dossier.click();
    ok('un clic replie le dossier', (await dossier.getAttribute('aria-expanded')) === 'false' && (await carte.count()) === 0);
    await dossier.click();

    // Un lien de la fiche mène à l'autre fichier.
    const lien = fiche.locator('button.lien-fichier').first();
    const cible = await lien.getAttribute('data-chemin');
    await lien.click();
    ok('un lien de la fiche choisit l\'autre fichier', (await fiche.locator('p.petit').first().textContent()) === cible);

    // La constellation.
    await page.click('button[data-action="code-vue"][data-vue="constellation"]');
    await page.locator('#constellation svg').waitFor();
    const etoiles = await page.locator('#constellation .etoile').count();
    ok('une étoile par fichier', etoiles > 20);
    ok('les dépendances sont tracées', (await page.locator('#constellation line.lien').count()) > 10);
    ok('les amas portent le nom de leur dossier', (await page.locator('#constellation text.amas').allTextContents()).includes('atelier'));
    const etoile = page.locator('#constellation .etoile[data-chemin="atelier/serveur.py"]');
    await etoile.click();
    ok('un clic sur une étoile ouvre sa fiche', (await fiche.locator('h2').textContent()) === 'serveur.py');
    ok('ses voisines sont mises en avant', (await page.locator('#constellation .etoile.voisin').count()) > 0
      && (await page.locator('#constellation line.lien.actif').count()) > 0);
    // Le zoom ne casse rien et « Recentrer » revient.
    const boite = await page.locator('#constellation').boundingBox();
    await page.mouse.move(boite.x + boite.width / 2, boite.y + boite.height / 2);
    await page.mouse.wheel(0, -400);
    await pause(100);
    const zoome = await page.locator('#ciel').getAttribute('transform');
    ok('la molette zoome', !zoome.includes('scale(1)'));
    await page.click('[data-action="recentrer"]');
    ok('« Recentrer » revient au départ', (await page.locator('#ciel').getAttribute('transform')) === 'translate(0 0) scale(1)');
    await page.locator('#vue-code').screenshot({ path: path.join(CAPTURES, 'CODE-constellation.png') });
    const lectures = appels.filter((a) => a === '/api/carte/lire').length;
    await pause(2500);
    ok('la carte n\'est pas relue tant que sa version ne change pas', appels.filter((a) => a === '/api/carte/lire').length === lectures);

    // Un agent au travail : ses fichiers clignotent, et le point de l'onglet s'allume.
    await page.goto(base + '/#conversation');
    await page.fill('#message', 'Moteur de calcul : formules de la norme, validées sur les cas de référence.');
    await page.click('#envoi');
    await page.waitForSelector('#colonne button[data-action="valider"]', { timeout: 30000 });
    await page.click('#colonne button[data-action="valider"]');
    await page.waitForFunction(() => document.getElementById('pt-code').classList.contains('allume'), null, { timeout: 30000 });
    ok('le point de l\'onglet Code s\'allume quand un agent travaille', true);
    await page.click('a[data-onglet="code"]');
    await page.locator('#constellation .etoile.en-cours').first().waitFor({ timeout: 10000 });
    ok('les étoiles des fichiers en cours clignotent', true);
    ok('la ligne d\'état le dit', (await page.locator('#code-etat').textContent()).includes('en cours de modification par un agent'));
    const enCours = await page.locator('#constellation .etoile.en-cours').first().getAttribute('data-chemin');
    await page.locator('#constellation .etoile.en-cours').first().click();
    ok('la fiche dit quel agent le modifie', /En cours de modification par /.test(await fiche.textContent()));
    await page.locator('#vue-code').screenshot({ path: path.join(CAPTURES, 'CODE-en-cours.png') });
    await page.click('button[data-action="code-vue"][data-vue="explorateur"]');
    const ligne = page.locator(`#explorateur .ligne-arbre.fichier[data-chemin="${enCours}"]`);
    await ligne.waitFor();
    ok('la ligne du fichier clignote dans l\'explorateur', (await ligne.getAttribute('class')).includes('en-cours'));
    ok('elle porte le badge « En cours »', (await ligne.textContent()).includes('En cours'));

    // Un texte hostile reste du texte (carte fabriquée).
    const hostile = '<img src=x onerror="window.pirate=1">';
    await page.evaluate((h) => {
      carteComplete = { version: 999, liens: [[h, 'a.py']], supprimes: [h], nouveaux_absents: [h], fichiers: [
        { chemin: h, genre: 'code', lignes: 10, statut: 'nouveau', resume: h, detail: h, explique: true, attente: false, pieces: [{ nom: h, ligne: 1, sorte: 'fonction', role: h }] },
        { chemin: 'a.py', genre: 'code', lignes: 5, statut: '', resume: h, detail: '', explique: true, attente: false, pieces: [] }] };
      disposition = null; fichiersOuverts.add(h); fichierChoisi = h;
      afficherCode(derniere);
    }, hostile);
    await page.click('button[data-action="code-vue"][data-vue="constellation"]');
    await page.click('button[data-action="code-vue"][data-vue="explorateur"]');
    await pause(200);
    ok('un texte hostile reste du texte', (await page.evaluate(() => window.pirate)) === undefined
      && (await page.locator('#vue-code img').count()) === 0 && (await fiche.locator('h2').textContent()) === hostile);
    await page.evaluate(() => { carteVersion = -1; fichierChoisi = ''; disposition = null; chargerCarte(true); });
    await page.locator('#explorateur .ligne-arbre.fichier[data-chemin="atelier/modele.py"]').waitFor();

    // Fenêtre étroite.
    await page.setViewportSize({ width: 400, height: 800 });
    await pause(400);
    ok('pas de débordement en fenêtre étroite', !(await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1)));
    await page.screenshot({ path: path.join(CAPTURES, 'CODE-etroit.png') });
    ok('aucune erreur dans la page', erreurs.length === 0);
    if (erreurs.length) console.log(erreurs);
  } finally { if (nav) await nav.close(); serveur.kill(); }
  const echecs = sorties.filter((v) => !v).length;
  console.log(echecs ? `${echecs} échec(s)` : `Toutes les vérifications passent : ${sorties.length} sur ${sorties.length}.`);
  process.exit(echecs ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(1); });
