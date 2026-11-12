// Essai de l'onglet Code (explorateur, plan, vue d'un fichier, fiche, clignotement), dans un navigateur sans écran, sur la démonstration.
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
    ok('aucune vue avant l\'analyse', (await page.locator('#explorateur').isHidden()) && (await page.locator('#plan').isHidden()) && (await page.locator('#voisinage').isHidden()));

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

    // Le plan en étages, à la racine du projet.
    await page.click('button[data-action="code-vue"][data-vue="plan"]');
    await page.locator('#plan .bloc').first().waitFor();
    const blocTests = page.locator('#plan .bloc[data-chemin="tests"]'), blocAtelier = page.locator('#plan .bloc[data-chemin="atelier"]');
    ok('la racine montre un bloc par dossier relié', (await blocTests.count()) === 1 && (await blocAtelier.count()) === 1);
    ok('ce qui se sert des autres est au-dessus', (await blocTests.boundingBox()).y < (await blocAtelier.boundingBox()).y);
    ok('une flèche relie les deux', (await page.locator('#plan path.fleche').count()) >= 1);
    const avantTout = await page.locator('#plan .bloc').count();
    await page.click('[data-action="plan-tout"]');
    ok('« Montrer les éléments sans lien » les ajoute', (await page.locator('#plan .bloc').count()) > avantTout);
    await page.click('[data-action="plan-tout"]');
    ok('et « Cacher » les retire', (await page.locator('#plan .bloc').count()) === avantTout);
    // Un clic sur un dossier l'ouvre.
    await blocAtelier.click();
    await page.locator('#plan .bloc[data-chemin="atelier/serveur.py"]').waitFor();
    ok('un clic ouvre le dossier, et le fil d\'Ariane le dit', (await page.locator('#plan .ariane').textContent()).includes('atelier'));
    ok('ses fichiers sont rangés en étages', (await page.locator('#plan .etage').count()) > 2);
    ok('les dépendances sont tracées', (await page.locator('#plan path.fleche').count()) > 10);
    ok('une dépendance mutuelle est signalée en orange', (await page.locator('#plan path.fleche.mutuel').count()) > 0
      && (await page.locator('#plan .plan-aide .souci').count()) > 0);
    ok('le plan dit ce qui vient d\'ailleurs', (await page.locator('#plan .plan-aide').textContent()).includes('Hors de ce dossier'));
    await page.click('#plan .bloc[data-chemin="atelier/serveur.py"]');
    ok('un clic sur un fichier ouvre sa fiche', (await fiche.locator('h2').textContent()) === 'serveur.py');
    ok('ses flèches sont mises en avant, le reste s\'estompe', (await page.locator('#plan path.fleche.actif').count()) > 0
      && (await page.locator('#plan .bloc.pale').count()) > 0);
    await page.locator('#vue-code').screenshot({ path: path.join(CAPTURES, 'CODE-plan.png') });
    // La vue d'un fichier.
    await fiche.locator('[data-action="vue-fichier"]').click();
    const centre = page.locator('#voisinage .voisin-carte.centre');
    await centre.waitFor();
    ok('« Voir ses dépendances » le met au milieu', (await centre.getAttribute('data-chemin')) === 'atelier/serveur.py');
    const colonnes = page.locator('#voisinage .colonne-voisins');
    const gauche = await colonnes.filter({ hasText: 'Ils se servent de lui' }).textContent();
    const droite = await colonnes.filter({ hasText: 'Il se sert de' }).first().textContent();
    ok('à gauche ceux qui se servent de lui', gauche.includes('__main__.py'));
    ok('à droite ceux dont il se sert', droite.includes('moteur.py'));
    ok('la vue dit ce que toucherait une modification', /Si tu modifies serveur\.py, \d+ fichiers? s'en ser/.test(await page.locator('#voisinage .plan-tete').textContent()));
    ok('les flèches relient les colonnes', (await page.locator('#voisinage path.fleche').count()) > 3);
    await page.locator('#vue-code').screenshot({ path: path.join(CAPTURES, 'CODE-fichier.png') });
    await page.click('#voisinage .voisin-carte[data-chemin="atelier/moteur.py"]');
    ok('un clic sur un voisin le met au milieu', (await centre.getAttribute('data-chemin')) === 'atelier/moteur.py');
    await page.click('[data-action="precedent"]');
    ok('« Précédent » revient au fichier d\'avant', (await centre.getAttribute('data-chemin')) === 'atelier/serveur.py');
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
    await page.click('button[data-action="code-vue"][data-vue="plan"]');
    await page.click('#plan .ariane button[data-chemin=""]');
    await page.locator('#plan .bloc.dossier.en-cours[data-chemin="atelier"]').waitFor({ timeout: 10000 });
    ok('dans le plan, le dossier où un agent travaille clignote', true);
    ok('la ligne d\'état le dit', (await page.locator('#code-etat').textContent()).includes('en cours de modification par un agent'));
    await page.click('#plan .bloc[data-chemin="atelier"]');
    const blocEnCours = page.locator('#plan .bloc.fichier.en-cours').first();
    await blocEnCours.waitFor();
    ok('et dedans, le fichier lui-même', (await blocEnCours.textContent()).includes('En cours'));
    // Ce que l'agent écrit, pas encore vérifié : un fichier fantôme et des flèches en pointillés.
    const fantome = page.locator('#plan .bloc.fantome').first();
    await fantome.waitFor({ timeout: 10000 });
    ok('le fichier que l\'agent écrit apparaît en brouillon dans le plan', (await fantome.textContent()).includes('Brouillon'));
    ok('ses liens sont tracés en pointillés', (await page.locator('#plan path.fleche.provisoire').count()) > 0);
    await fantome.click();
    ok('sa fiche dit qu\'il n\'est pas encore vérifié', (await fiche.textContent()).includes('n\'existe encore que dans la copie de travail'));
    await page.locator('#vue-code').screenshot({ path: path.join(CAPTURES, 'CODE-brouillon.png') });
    // Les tâches de démonstration avancent vite : on prend un fichier encore en cours au moment du clic.
    let dit = false;
    for (let i = 0; i < 20 && !dit; i++) {
      const bloc = page.locator('#plan .bloc.fichier.en-cours:not(.fantome)').first();
      if (await bloc.count()) { await bloc.click(); dit = /En cours de modification par /.test(await fiche.textContent()); }
      if (!dit) await pause(150);
    }
    ok('la fiche dit quel agent le modifie', dit);
    await page.locator('#vue-code').screenshot({ path: path.join(CAPTURES, 'CODE-en-cours.png') });
    // L'explorateur reste à gauche quelle que soit la vue du milieu.
    ok('l\'explorateur reste visible à côté du plan', await page.locator('#explorateur').isVisible());
    const ligne = page.locator('#explorateur .ligne-arbre.fichier.en-cours:not(.fantome)').first();
    await ligne.waitFor({ timeout: 10000 });
    ok('la ligne du fichier clignote dans l\'explorateur', true);
    ok('elle porte le badge « En cours »', (await ligne.textContent()).includes('En cours'));
    ok('le brouillon est aussi dans l\'explorateur', (await page.locator('#explorateur .ligne-arbre.fichier.fantome').count()) > 0);

    // Un texte hostile reste du texte (carte fabriquée).
    const hostile = '<img src=x onerror="window.pirate=1">';
    await page.evaluate((h) => {
      carteComplete = { version: 999, liens: [[h, 'a.py']], supprimes: [h], nouveaux_absents: [h], fichiers: [
        { chemin: h, genre: 'code', lignes: 10, statut: 'nouveau', resume: h, detail: h, explique: true, attente: false, pieces: [{ nom: h, ligne: 1, sorte: 'fonction', role: h }] },
        { chemin: 'a.py', genre: 'code', lignes: 5, statut: '', resume: h, detail: '', explique: true, attente: false, pieces: [] }] };
      planChemin = ''; fichiersOuverts.add(h); fichierChoisi = h;
      afficherCode(derniere);
    }, hostile);
    for (const v of ['plan', 'voisinage']) { await page.click(`button[data-action="code-vue"][data-vue="${v}"]`); await pause(150); }
    ok('un texte hostile reste du texte', (await page.evaluate(() => window.pirate)) === undefined
      && (await page.locator('#vue-code img').count()) === 0 && (await fiche.locator('h2').textContent()) === hostile);
    await page.evaluate(() => { carteVersion = -1; fichierChoisi = ''; chargerCarte(true); });
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
