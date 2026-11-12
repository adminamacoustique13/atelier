// Essai de l'onglet Code (explorateur, page du projet, d'un dossier et d'un fichier, recherche, travail en cours),
// dans un navigateur sans écran, sur la démonstration.
// Usage : node chantier/essais/CODE-carte.js
const { chromium } = require('playwright');
const { spawn } = require('child_process');
const fs = require('fs');
const net = require('net');
const path = require('path');
const DEPOT = process.argv[2] || path.resolve(__dirname, '..', '..');
const CAPTURES = process.argv[3] || path.join(DEPOT, 'chantier', 'captures');
const sorties = [];
const ok = (nom, vrai, detail) => { sorties.push(vrai); console.log(`${vrai ? 'ok    ' : 'ECHEC '} - ${nom}${!vrai && detail !== undefined ? ` (${JSON.stringify(detail)})` : ''}`); };
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
    const contenu = page.locator('#code-page');

    // Avant l'analyse : une explication et un bouton, rien d'autre.
    await page.goto(base + '/#code');
    const bouton = page.locator('#code-actions button[data-action="analyser-code"]');
    await bouton.waitFor();
    ok('l\'onglet Code propose « Analyser le code »', (await bouton.textContent()) === 'Analyser le code');
    ok('la page explique ce que fait la carte', (await page.locator('#code-vide').textContent()).includes('seuls les fichiers changés sont relus'));
    ok('aucune page avant l\'analyse', (await page.locator('#explorateur').isHidden()) && (await contenu.isHidden()) && (await page.locator('#code-chercher').isHidden()));

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
    await page.locator('#code-page .cd-chaine').waitFor({ timeout: 30000 });
    const etat = await page.locator('#code-etat').textContent();
    ok('la ligne d\'état compte les fichiers', /^\d+ fichiers · analysé le/.test(etat), etat);

    // La page du projet : le portrait, la chaîne qui part de là où vit le code, ce qu'il y a dedans.
    ok('le titre est le nom du projet', (await contenu.locator('h1').textContent()) === 'Projet de démonstration');
    ok('le portrait vient du LISEZMOI, et le dit', /chef de chantier/.test(await contenu.locator('.cd-portrait').textContent())
      && /Tiré du LISEZMOI/i.test(await contenu.locator('.cd-source').first().textContent()));
    ok('la chaîne part de atelier/, là où vit le code', /On part de atelier\//.test(await contenu.locator('.cd-note').textContent()));
    const blocs = await contenu.locator('.cd-chaine .cd-bloc').evaluateAll((l) => l.map((b) => b.dataset.chemin));
    ok('la chaîne montre les fichiers du code, pas les presque vides', blocs.includes('atelier/serveur.py') && blocs.includes('atelier/moteur.py') && !blocs.includes('atelier/__init__.py'), blocs);
    const haut = await contenu.locator('.cd-bloc[data-chemin="atelier/__main__.py"]').boundingBox();
    const bas = await contenu.locator('.cd-bloc[data-chemin="atelier/serveur.py"]').boundingBox();
    ok('de haut en bas : __main__.py au-dessus de serveur.py', haut.y < bas.y);
    const etiquettes = await contenu.locator('.cd-chaine .cd-lab').allTextContents();
    ok('sur les fils, les noms pris lus dans le code', etiquettes.some((t) => /Moteur/.test(t)) && etiquettes.length > 4, etiquettes);
    ok('le socle regroupe ce dont tout le monde se sert', /modele\.py/.test(await contenu.locator('.cd-socle').textContent()));
    const dedans = await contenu.locator('.cd-dedans .cd-ligne .nm').allTextContents();
    ok('« Ce qu\'il y a dedans » liste la racine', dedans.includes('atelier/') && dedans.includes('tests/') && dedans.includes('LISEZMOI.md'), dedans);
    await page.locator('#vue-code').screenshot({ path: path.join(CAPTURES, 'CODE-projet.png') });

    // Un clic sur un bloc ouvre la page du fichier.
    await contenu.locator('.cd-bloc[data-chemin="atelier/serveur.py"]').click();
    await page.waitForFunction(() => document.querySelector('#code-page h1')?.textContent === 'serveur.py');
    ok('la page du fichier s\'ouvre, avec son étage', (await page.locator('.etage-pt.on').textContent()) === '2' && /serveur\.py/.test(await page.locator('#code-ariane .ariane').textContent()));
    ok('l\'explorateur suit : la ligne du fichier est choisie', await page.locator('#explorateur .ligne-arbre.choisi[data-chemin="atelier/serveur.py"]').count() === 1);
    ok('le fichier est au milieu de son schéma', await contenu.locator('.cd-bloc.centre[data-chemin="atelier/serveur.py"]').count() === 1);
    ok('au-dessus, ceux qui s\'en servent', await contenu.locator('.cd-bloc[data-chemin="atelier/__main__.py"]').count() === 1);
    ok('les chiffres de l\'impact', /s'en servent/i.test(await contenu.locator('.cd-impact').textContent()));
    const prudence = await contenu.locator('.cd-prudence').textContent();
    ok('« Avant de le modifier » dit qui s\'en sert et quels tests l\'importent', /s'en servent directement/.test(prudence) && /test_serveur\.py/.test(prudence), prudence);
    ok('ses parties, avec leur ligne', (await contenu.locator('.cd-piece').count()) > 5 && /ligne \d+/.test(await contenu.locator('.cd-piece .lg').first().textContent()));
    await page.locator('#vue-code').screenshot({ path: path.join(CAPTURES, 'CODE-fichier.png') });

    // Le fil d'Ariane remonte, l'explorateur ouvre la page d'un dossier.
    await page.click('#code-ariane .ariane button[data-chemin="atelier/"]');
    await page.waitForFunction(() => document.querySelector('#code-page h1')?.textContent === 'atelier/');
    ok('le fil d\'Ariane ouvre la page du dossier', (await page.locator('.etage-pt.on').textContent()) === '1');
    await page.click('#explorateur .ligne-arbre.dossier[data-chemin="tests"]');
    await page.waitForFunction(() => document.querySelector('#code-page h1')?.textContent === 'tests/');
    ok('un dossier de l\'explorateur ouvre sa page', /13 fichiers|\d+ fichiers/.test(await contenu.locator('.cd-puces').textContent()));

    // La recherche trouve un fichier, une partie, et y mène.
    await page.fill('#code-chercher', 'Rythmes');
    const resultat = page.locator('#code-resultats button.resultat').first();
    await resultat.waitFor();
    ok('la recherche trouve une partie et dit sa ligne', /rythme\.py, ligne \d+/.test(await resultat.textContent()));
    await page.keyboard.press('Enter');
    await page.waitForFunction(() => document.querySelector('#code-page h1')?.textContent === 'rythme.py');
    ok('Entrée ouvre le premier résultat', true);

    ok('la carte n\'est pas relue tant que sa version ne change pas', await (async () => {
      const lectures = appels.filter((a) => a === '/api/carte/lire').length; await pause(2500); return appels.filter((a) => a === '/api/carte/lire').length === lectures;
    })());

    // Un agent au travail : ses fichiers s'allument en bleu, son brouillon entre dans la chaîne.
    await page.goto(base + '/#conversation');
    await page.fill('#message', 'Moteur de calcul : formules de la norme, validées sur les cas de référence.');
    await page.click('#envoi');
    await page.waitForSelector('#colonne button[data-action="valider"]', { timeout: 30000 });
    await page.click('#colonne button[data-action="valider"]');
    await page.waitForFunction(() => document.getElementById('pt-code').classList.contains('allume'), null, { timeout: 30000 });
    ok('le point de l\'onglet Code s\'allume quand un agent travaille', true);
    await page.click('a[data-onglet="code"]');
    await page.click('#code-ariane .ariane button[data-chemin=""]');
    await page.locator('#code-page .cd-bloc.vif').first().waitFor({ timeout: 10000 });
    ok('dans la chaîne, le bloc où un agent travaille est en bleu, avec son nom', /●/.test(await contenu.locator('.cd-bloc.vif').first().textContent()));
    ok('la ligne d\'état le dit', (await page.locator('#code-etat').textContent()).includes('en cours de modification par un agent'));
    const fantome = contenu.locator('.cd-bloc.fantome').first();
    await fantome.waitFor({ timeout: 10000 });
    ok('le fichier que l\'agent écrit entre dans la chaîne en pointillés', true);
    await fantome.click();
    await page.waitForFunction(() => /brouillon/.test(document.querySelector('#code-page h1')?.textContent || ''));
    ok('sa page dit qu\'il n\'existe que dans la copie de l\'agent', /copie de travail de l'agent/.test(await contenu.textContent()));
    ok('l\'explorateur montre le brouillon', (await page.locator('#explorateur .ligne-arbre.fichier.fantome').count()) > 0);
    await page.locator('#vue-code').screenshot({ path: path.join(CAPTURES, 'CODE-brouillon.png') });

    // Un texte hostile reste du texte (carte fabriquée).
    const hostile = '<img src=x onerror="window.pirate=1">';
    await page.evaluate((h) => {
      carteComplete = { version: 999, liens: [[h, 'a.py']], noms: { [h + '\u0000a.py']: [h] }, supprimes: [], nouveaux_absents: [], portrait: h, dossiers: {}, lisezmoi: h,
        fichiers: [
          { chemin: h, genre: 'code', lignes: 10, statut: 'nouveau', resume: h, detail: h, explique: true, attente: false, prudence: [h], pieces: [{ nom: h, ligne: 1, sorte: 'fonction', role: h }] },
          { chemin: 'a.py', genre: 'code', lignes: 50, statut: '', resume: h, detail: '', explique: true, attente: false, prudence: [], pieces: [] }] };
      allerCode('');
    }, hostile);
    await page.evaluate((h) => allerCode(h), hostile);
    await page.fill('#code-chercher', 'img');
    await pause(200);
    ok('un texte hostile reste du texte', (await page.evaluate(() => window.pirate)) === undefined
      && (await page.locator('#vue-code img').count()) === 0 && (await contenu.locator('h1').textContent()) === hostile);
    await page.evaluate(() => { carteVersion = -1; codeChemin = ''; chargerCarte(true); });
    await page.locator('#explorateur .ligne-arbre.dossier[data-chemin="atelier"]').waitFor();

    // Fenêtre étroite.
    await page.setViewportSize({ width: 400, height: 800 });
    await page.fill('#code-chercher', '');
    await pause(400);
    ok('pas de débordement en fenêtre étroite', !(await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1)));
    await page.screenshot({ path: path.join(CAPTURES, 'CODE-etroit.png') });
    ok('aucune erreur dans la page', erreurs.length === 0, erreurs);
  } finally { if (nav) await nav.close(); serveur.kill(); }
  const echecs = sorties.filter((v) => !v).length;
  console.log(echecs ? `${echecs} échec(s)` : `Toutes les vérifications passent : ${sorties.length} sur ${sorties.length}.`);
  process.exit(echecs ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(1); });
