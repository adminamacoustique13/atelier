// Essai des pannes de réseau : le serveur ne répond plus à un envoi, la page le dit et rend la main. Navigateur sans écran, sur la démonstration.
// Usage : node chantier/essais/PANNES-reseau.js
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
const PANNE = 'ne répond pas';

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
    // Coupure : tant que `coupe` est vrai, tout POST vers /api/ échoue comme si le serveur s'était arrêté (le fetch lève).
    // Les interrogations de /api/etat (GET) passent : la page reste vivante.
    let coupe = false, coupures = 0;
    await page.route('**/api/**', (route) => {
      if (coupe && route.request().method() === 'POST') { coupures += 1; return route.abort('connectionrefused'); }
      return route.continue();
    });
    // Attend qu'un élément contienne le texte de panne ; rend vrai ou faux, sans lever.
    const ditPanne = (selecteur) => page.waitForFunction(([s, t]) => (document.querySelector(s) || {}).textContent?.includes(t), [selecteur, PANNE], { timeout: 5000 })
      .then(() => true, () => false);
    // La phrase de panne s'écrit à un seul endroit, sous l'en-tête, quel que soit l'onglet.
    const textePanne = () => page.evaluate(() => { const p = document.getElementById('panne'); return p && !p.hidden ? p.textContent : ''; });
    const bandeauPanne = async () => (await textePanne()).includes(PANNE);
    const voitPanne = () => page.waitForFunction((t) => { const p = document.getElementById('panne'); return p && !p.hidden && p.textContent.includes(t); }, PANNE, { timeout: 5000 })
      .then(() => true, () => false);
    const oublier = () => page.evaluate(() => { dire(''); if (typeof avisPanne === 'function') avisPanne(''); });

    await page.goto(base + '/#conversation');
    await page.locator('#message').waitFor();

    // Un message : la page le dit, la saisie est gardée, le bouton d'envoi reste disponible.
    coupe = true;
    const objectif = 'Un objectif d\'essai, envoyé pendant la panne';
    await page.fill('#message', objectif);
    await page.keyboard.press('Enter');
    ok('message : la page dit que l\'Atelier ne répond pas', await voitPanne());
    ok('message : le texte de la phrase est complet', /vérifie qu'il tourne encore.*réessaie/.test(await textePanne()));
    ok('message : la saisie est conservée', (await page.inputValue('#message')) === objectif);
    ok('message : le bouton d\'envoi reste cliquable', await page.locator('#envoi').isEnabled());
    ok('message : la coupure a bien eu lieu', coupures >= 1);
    ok('message : rien n\'est arrivé au serveur', !JSON.stringify((await etat()).evenements).includes(objectif));

    // Le même message, la connexion revenue : il part, et l'orchestrateur simulé propose un plan.
    coupe = false; await oublier();
    await page.fill('#message', 'Un objectif d\'essai');
    await page.keyboard.press('Enter');
    for (let i = 0; i < 150; i++) { const v = await etat(); if (v.taches.length > 0 && !v.occupe) break; await pause(100); }

    // Valider le contrat pendant la panne : la page le dit, le bouton est toujours là, le contrat attend toujours.
    await page.goto(base + '/#chantier');
    const valider = page.locator('#attente [data-action="valider"]');
    await valider.waitFor();
    await oublier();
    coupe = true; coupures = 0;
    await valider.click();
    ok('validation : la page dit que l\'Atelier ne répond pas', await voitPanne());
    ok('validation : le bouton « Valider » est toujours là et cliquable', (await valider.isVisible()) && (await valider.isEnabled()));
    ok('validation : la coupure a bien eu lieu', coupures >= 1);
    ok('validation : le contrat attend toujours ta validation', (await etat()).contrat.valide === false);
    await page.locator('#carte-attente').screenshot({ path: path.join(CAPTURES, 'PANNES-validation.png') });

    // Créer un projet : la fenêtre le dit, le nom tapé reste.
    await oublier();
    await page.click('#nouveau');
    await page.fill('#nom-nouveau', 'Projet pendant la panne');
    await page.click('#creer');
    ok('création : la fenêtre dit que l\'Atelier ne répond pas', await ditPanne('#erreur-creation'));
    ok('création : le nom tapé est conservé', (await page.inputValue('#nom-nouveau')) === 'Projet pendant la panne');
    ok('création : le bouton « Créer » reste cliquable', await page.locator('#creer').isEnabled());

    // Cloner un dépôt (formulaire montré de force : la démonstration le cache) : le bouton retrouve son libellé.
    await page.evaluate(() => { document.getElementById('form-clonage').hidden = false; });
    const cloner = page.locator('#cloner');
    const libelleCloner = await cloner.textContent();
    await page.fill('#adresse-depot', 'https://exemple.org/depot.git');
    await cloner.click();
    ok('clonage : la fenêtre dit que l\'Atelier ne répond pas', await ditPanne('#erreur-clonage'));
    ok('clonage : le bouton retrouve son libellé', (await cloner.textContent()) === libelleCloner);
    ok('clonage : le bouton redevient cliquable', await cloner.isEnabled());
    ok('clonage : l\'adresse tapée est conservée', (await page.inputValue('#adresse-depot')) === 'https://exemple.org/depot.git');
    ok('la phrase de panne est aussi dite sous l\'en-tête', await bandeauPanne());
    await page.locator('#creation').screenshot({ path: path.join(CAPTURES, 'PANNES-clonage.png') });
    await page.click('#annuler-creation');

    // Relier à un dépôt en ligne (bouton caché en démonstration : on ouvre la fenêtre par lui quand même).
    await page.evaluate(() => document.getElementById('distant').click());
    const relier = page.locator('#relier');
    await relier.waitFor();
    const libelleRelier = await relier.textContent();
    await page.fill('#adresse-liaison', 'https://exemple.org/en-ligne.git');
    await relier.click();
    ok('liaison : la fenêtre dit que l\'Atelier ne répond pas', await ditPanne('#erreur-liaison'));
    ok('liaison : le bouton retrouve son libellé', (await relier.textContent()) === libelleRelier);
    ok('liaison : le bouton redevient cliquable', await relier.isEnabled());
    ok('liaison : l\'adresse tapée est conservée', (await page.inputValue('#adresse-liaison')) === 'https://exemple.org/en-ligne.git');
    await page.click('#annuler-liaison');

    // Valider depuis le bandeau du Plan, là où la page invite à valider : la phrase se voit dans le Plan.
    await page.goto(base + '/#plan');
    const validerPlan = page.locator('#vue-plan .bandeau [data-action="valider"]');
    await validerPlan.waitFor();
    await oublier(); coupures = 0;
    await validerPlan.click();
    ok('Plan : valider pendant la panne, la page le dit', await voitPanne());
    ok('Plan : le bouton « Valider » est toujours là et cliquable', (await validerPlan.isVisible()) && (await validerPlan.isEnabled()));
    ok('Plan : la coupure a bien eu lieu', coupures >= 1);

    // La connexion revient : la validation part et le chantier démarre, preuve que la page n'est pas restée coincée,
    // et la phrase de panne s'efface tout de suite, sans attendre la fin de son délai.
    coupe = false;
    await validerPlan.click();
    let lance = false;
    for (let i = 0; i < 50 && !lance; i++) { lance = (await etat()).contrat.valide === true; if (!lance) await pause(100); }
    ok('la connexion revenue, la validation part', lance);
    ok('un envoi réussi efface aussitôt la phrase de panne', await page.waitForFunction((t) => ['panne', 'sous-saisie', 'attente', 'salle-attente']
      .every((id) => { const e = document.getElementById(id); return !e || e.hidden || !e.textContent.includes(t); }), PANNE, { timeout: 1500 }).then(() => true, () => false));

    // Un deuxième projet, connexion ouverte : il devient le projet ouvert.
    await page.click('#nouveau');
    await page.fill('#nom-nouveau', 'Second projet');
    await page.click('#creer');
    await page.waitForFunction(() => (derniere?.projets || []).length >= 2 && derniere.projets.find((p) => p.courant)?.nom === 'Second projet', null, { timeout: 10000 });
    const projets = (await page.evaluate(() => derniere.projets));
    const ouvert = projets.find((p) => p.courant), autre = projets.find((p) => !p.courant);

    // Changer de projet depuis le Plan pendant la panne : la page le dit, le menu revient sur le projet ouvert.
    await page.goto(base + '/#plan');
    await page.locator('#projet').waitFor();
    await oublier();
    coupe = true; coupures = 0;
    await page.selectOption('#projet', autre.id);
    ok('changer de projet depuis le Plan : la page le dit', await voitPanne());
    ok('changer de projet : le menu revient sur le projet ouvert', (await page.inputValue('#projet')) === ouvert.id);
    ok('changer de projet : rien n\'a changé côté serveur', (await etat()).projet === ouvert.nom);

    // Reprendre un autre projet depuis l'Accueil pendant la panne : la page le dit, sur l'Accueil.
    // La liste des projets se charge connexion ouverte (elle est demandée en POST), puis la connexion est coupée.
    coupe = false;
    await page.goto(base + '/#accueil');
    const reprendre = page.locator(`#grille-projets [data-action="reprendre"][data-id="${autre.id}"]`);
    await reprendre.waitFor();
    await oublier();
    coupe = true; coupures = 0;
    await reprendre.click();
    ok('reprendre depuis l\'Accueil : la page le dit', await voitPanne());
    ok('reprendre : on reste sur l\'Accueil', (await page.evaluate(() => location.hash)) === '#accueil');
    ok('reprendre : la coupure a bien eu lieu', coupures >= 1);
    await page.screenshot({ path: path.join(CAPTURES, 'PANNES-accueil.png'), clip: { x: 0, y: 0, width: 1280, height: 200 } });
    coupe = false;

    ok('aucune erreur laissée sans traitement dans la page', erreurs.length === 0);
    if (erreurs.length) console.log(erreurs);
  } finally { if (nav) await nav.close(); serveur.kill(); }
  const echecs = sorties.filter((v) => !v).length;
  console.log(echecs ? `${echecs} échec(s)` : `Toutes les vérifications passent : ${sorties.length} sur ${sorties.length}.`);
  process.exit(echecs ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(1); });
