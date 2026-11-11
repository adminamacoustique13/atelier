/* Essai D2 : le tableau de bord (cartes d'autorisation, activité, boutons d'arrêt) dans un navigateur sans écran.
 *
 * Lancer depuis la racine du dépôt :  node chantier/essais/D2-tableau.js
 * Le script démarre lui-même `python3 -m atelier demo` (agents simulés, aucun appel réel), joue le scénario,
 * écrit les captures dans chantier/captures/D2-*.png, arrête les serveurs quoi qu'il arrive,
 * et sort avec un code non nul si une vérification échoue.
 */
const { chromium } = require("playwright");
const { spawn, spawnSync } = require("node:child_process");
const net = require("node:net");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const RACINE = path.resolve(__dirname, "..", "..");
const CAPTURES = path.resolve(__dirname, "..", "captures");
const PAUSE = (ms) => new Promise((r) => setTimeout(r, ms));
const serveurs = [];
let echecs = 0;

function verifier(nom, condition, detail) {
  if (condition) console.log(`ok     - ${nom}`);
  else { echecs += 1; console.log(`ECHEC  - ${nom}${detail !== undefined ? ` (${typeof detail === "string" ? detail : JSON.stringify(detail)})` : ""}`); }
}

function portLibre() {
  return new Promise((resolve, reject) => {
    const s = net.createServer();
    s.listen(0, "127.0.0.1", () => { const { port } = s.address(); s.close(() => resolve(port)); });
    s.on("error", reject);
  });
}

async function demarrer(delai) {
  const port = await portLibre();
  const processus = spawn("python3", ["-m", "atelier", "demo", "--port", String(port), "--delai", String(delai)], { cwd: RACINE, stdio: "ignore" });
  const serveur = { port, url: `http://127.0.0.1:${port}`, processus };
  serveurs.push(serveur);
  const limite = Date.now() + 20000;
  for (;;) {
    try { const r = await fetch(`${serveur.url}/api/etat`); if (r.ok) return serveur; } catch (e) { /* pas encore prêt */ }
    if (Date.now() > limite) throw new Error("La démonstration ne répond pas.");
    await PAUSE(150);
  }
}
const etat = async (serveur) => (await fetch(`${serveur.url}/api/etat`)).json();
async function jusqua(fonction, ms = 20000, pas = 120) {
  const limite = Date.now() + ms;
  for (;;) {
    const v = await fonction();
    if (v) return v;
    if (Date.now() > limite) return null;
    await PAUSE(pas);
  }
}
const aller = (page, onglet) => page.evaluate((o) => { location.hash = `#${o}`; }, onglet);
const capture = (cible, nom) => cible.screenshot({ path: path.join(CAPTURES, `D2-${nom}.png`) });

async function ouvrir(browser, serveur, options = {}) {
  const contexte = await browser.newContext({ viewport: { width: 1280, height: 800 }, deviceScaleFactor: 2, ...options });
  const page = await contexte.newPage();
  const erreurs = [], requetes = [];
  page.on("pageerror", (e) => erreurs.push(String(e)));
  page.on("console", (m) => { if (m.type() === "error" && !/Failed to load resource/.test(m.text())) erreurs.push(m.text()); });
  page.on("request", (r) => { if (r.method() === "POST") requetes.push({ url: new URL(r.url()).pathname, corps: r.postData() ? JSON.parse(r.postData()) : null }); });
  await page.goto(serveur.url);
  return { page, contexte, erreurs, requetes };
}

/* Envoie l'objectif, attend la proposition, valide le contrat, attend la carte d'autorisation. */
async function lancerChantier(page, serveur) {
  await page.fill("#message", "Moteur de calcul : formules de la norme, validées sur les cas de référence.");
  await page.click("#envoi");
  await page.waitForSelector('#colonne button[data-action="valider"]', { timeout: 30000 });
  await page.click('#colonne button[data-action="valider"]');
  await page.waitForSelector("#colonne .autorisation", { timeout: 30000 });
}

async function main() {
  fs.mkdirSync(CAPTURES, { recursive: true });
  const browser = await chromium.launch();

  /* ---------- 1. Une demande : carte, règle, détail, activité, « Autoriser une fois » ---------- */
  console.log("\n== Partie 1 : la carte, l'activité, « Autoriser une fois »");
  let s1 = await demarrer(3);
  {
    const { page, contexte, erreurs, requetes } = await ouvrir(browser, s1);
    await lancerChantier(page, s1);
    const carte = page.locator("#colonne .autorisation");
    const texte = await carte.innerText();
    verifier("la carte dit qui demande quoi, en une phrase", /veut lancer la commande « npm install left-pad »/.test(texte), texte);
    verifier("la carte affiche la règle exacte retenue par « Toujours »", (await carte.locator(".regle").innerText()) === "Bash(npm install:*)");
    verifier("la carte explique la portée de la règle", /toute commande qui commence par « npm install » sera permise sans redemander/.test(texte), texte);
    verifier("trois choix sont proposés", (await carte.locator("button").allInnerTexts()).join("|") === "Autoriser une fois|Toujours pour ce projet|Refuser", await carte.locator("button").allInnerTexts());
    verifier("le détail complet est caché avant le clic", (await carte.locator("pre.detail").count()) === 0);
    await carte.locator(".autor-corps").click();
    verifier("un clic sur la carte montre le texte complet", (await carte.locator("pre.detail").innerText()) === "npm install left-pad");
    await capture(page.locator("#vue-conversation"), "carte-conversation");
    await capture(page.locator("#colonne .carte-fil.decision"), "carte-detail");
    await carte.locator("pre.detail").click({ clickCount: 3 });
    verifier("cliquer dans le détail pour le sélectionner ne replie pas la carte", (await carte.locator("pre.detail").count()) === 1);
    await carte.locator(".autor-corps > p").click();
    verifier("un clic sur la carte, hors du détail, replie le détail", (await carte.locator("pre.detail").count()) === 0);

    await aller(page, "chantier");
    const carteChantier = page.locator("#attente .autorisation");
    verifier("la même carte est dans l'onglet Chantier", (await carteChantier.count()) === 1 && /npm install left-pad/.test(await carteChantier.innerText()));
    await capture(page.locator("#vue-chantier"), "carte-chantier");
    verifier("le point d'étape signale l'autorisation", /1 autorisation/.test(await page.locator("#point").innerText()), await page.locator("#point").innerText());

    // L'activité : dernière ligne dans le poste, 30 lignes au plus au clic
    const ligne = page.locator("#agents .agent").filter({ hasText: "En attente de ton autorisation" }).first();
    verifier("la ligne d'un agent montre sa dernière activité", (await ligne.count()) === 1 && /En attente de ton autorisation : Lance npm install left-pad/.test(await ligne.innerText()), await page.locator("#agents").innerText());
    const poste = await page.locator("svg.salle .s-activite").evaluateAll((l) => l.map((e) => e.textContent));
    verifier("le poste de la salle montre la dernière ligne d'activité", poste.some((t) => t.startsWith("En attente de ton autorisat")), poste);
    verifier("le journal est replié au départ", (await page.locator("#agents .journal").count()) === 0);
    await ligne.locator("button.agent-ligne").click();
    const lignes = await page.locator("#agents .journal li").allInnerTexts();
    verifier("un clic déroule les dernières lignes (de 2 à 30)", lignes.length >= 2 && lignes.length <= 30 && lignes[0] === "Lit la consigne", lignes);
    await capture(page.locator("#vue-chantier .carte").nth(2), "activite-deroulee");
    const nomAgent = await ligne.locator("button.agent-ligne").getAttribute("data-nom");
    await page.locator(`svg.salle .poste-actif[data-nom="${nomAgent}"]`).click();
    verifier("un clic sur le poste de la salle replie le journal correspondant", (await page.locator("#agents .journal").count()) === 0);

    // Avant de répondre : une seule réponse part, même si l'on clique partout
    const avant = requetes.filter((r) => r.url === "/api/autorisation").length;
    const identifiant = (await etat(s1)).autorisations[0].id;
    await aller(page, "conversation");
    await page.evaluate(() => document.querySelectorAll('[data-action="autoriser"][data-choix="une_fois"]').forEach((b) => { b.click(); b.click(); }));
    await jusqua(async () => (await page.locator(".autorisation").count()) === 0, 8000);
    const envoyees = requetes.filter((r) => r.url === "/api/autorisation").slice(avant);
    verifier("un seul envoi malgré les clics répétés", envoyees.length === 1 && envoyees[0].corps.choix === "une_fois" && envoyees[0].corps.id === identifiant && envoyees[0].corps.message === "", envoyees);
    verifier("la carte disparaît des deux onglets", (await page.locator(".autorisation").count()) === 0);
    const apres = await jusqua(async () => {
      const v = await etat(s1);
      return v.agents.some((a) => a.lignes.some((l) => /Réponse de la personne responsable : /.test(l))) ? v : null;
    }, 8000);
    verifier("l'agent reprend après l'autorisation", Boolean(apres), apres && apres.agents.map((a) => a.lignes.slice(-2)));
    verifier("aucune erreur dans la page", erreurs.length === 0, erreurs);
    await contexte.close();
  }

  /* ---------- 1 bis. « Toujours pour ce projet » ---------- */
  console.log("\n== Partie 1 bis : « Toujours pour ce projet »");
  {
    const s = await demarrer(3);
    const { page, contexte, erreurs, requetes } = await ouvrir(browser, s);
    await lancerChantier(page, s);
    const identifiant = (await etat(s)).autorisations[0].id;
    const reponses = [];
    page.on("response", async (r) => { if (new URL(r.url()).pathname === "/api/autorisation") reponses.push(await r.json()); });
    await page.locator("#colonne .autorisation").getByRole("button", { name: "Toujours pour ce projet" }).click();
    await jusqua(async () => reponses.length > 0, 8000);
    const envoi = requetes.filter((r) => r.url === "/api/autorisation");
    verifier("« Toujours » envoie le choix « toujours » et l'identifiant de la demande", envoi.length === 1 && envoi[0].corps.choix === "toujours" && envoi[0].corps.id === identifiant && envoi[0].corps.message === "", envoi);
    verifier("le serveur a bien réglé la demande par une règle", reponses.length === 1 && reponses[0].autorisation.reglee === true && /Bash\(npm install:\*\)/.test(reponses[0].autorisation.phrase), reponses);
    await jusqua(async () => (await page.locator(".autorisation").count()) === 0, 8000);
    verifier("la phrase du serveur est affichée telle quelle", reponses.length === 1 && (await page.locator("#sous-saisie").innerText()) === reponses[0].autorisation.phrase, await page.locator("#sous-saisie").innerText());
    verifier("aucune erreur dans la page", erreurs.length === 0, erreurs);
    await contexte.close();
  }

  /* ---------- 2. Refuser avec un texte ---------- */
  console.log("\n== Partie 2 : « Refuser » et « Dis-lui plutôt quoi faire »");
  {
    const s = await demarrer(3);
    const { page, contexte, erreurs, requetes } = await ouvrir(browser, s);
    await lancerChantier(page, s);
    const identifiantRefus = (await etat(s)).autorisations[0].id;
    const carte = page.locator("#colonne .autorisation");
    verifier("le champ de refus est caché au départ", (await carte.locator("textarea").count()) === 0);
    await carte.getByRole("button", { name: "Refuser" }).click();
    const champ = carte.getByLabel("Dis-lui plutôt quoi faire");
    verifier("« Refuser » ouvre le champ « Dis-lui plutôt quoi faire »", (await champ.count()) === 1 && /facultatif/i.test(await carte.innerText()));
    await champ.fill("Utilise plutôt pnpm.");
    // une nouvelle interrogation du serveur ne doit ni vider le champ ni lui retirer le focus
    await PAUSE(2200);
    verifier("la saisie survit aux rafraîchissements", (await champ.inputValue()) === "Utilise plutôt pnpm.");
    await capture(page.locator("#vue-conversation"), "refus-champ");
    await carte.getByRole("button", { name: "Confirmer le refus" }).click();
    await jusqua(async () => (await page.locator(".autorisation").count()) === 0, 8000);
    const envoi = requetes.filter((r) => r.url === "/api/autorisation");
    verifier("le texte part dans « message », avec le choix « non »", envoi.length === 1 && envoi[0].corps.choix === "non" && envoi[0].corps.id === identifiantRefus && envoi[0].corps.message === "Utilise plutôt pnpm.", envoi);
    const v = await jusqua(async () => {
      const e = await etat(s);
      return e.agents.some((a) => a.lignes.some((l) => /refusé\. Utilise plutôt pnpm\./.test(l))) ? e : null;
    }, 8000);
    verifier("l'agent a bien reçu le refus et le message", Boolean(v));
    verifier("la carte a disparu et un avis le confirme", (await page.locator("#sous-saisie").innerText()).startsWith("Refusé"), await page.locator("#sous-saisie").innerText());
    verifier("aucune erreur dans la page", erreurs.length === 0, erreurs);
    await contexte.close();
  }

  /* ---------- 3. Arrêter un agent (puis la tâche revient « arrêtée par toi ») ---------- */
  console.log("\n== Partie 3 : arrêter un agent en marche");
  {
    const s = await demarrer(25);
    const { page, contexte, erreurs, requetes } = await ouvrir(browser, s, { viewport: { width: 1280, height: 1500 } });
    await lancerChantier(page, s);
    await aller(page, "chantier");
    const cible = await jusqua(async () => {
      const v = await etat(s);
      const attente = new Set(v.autorisations.map((a) => a.agent));
      return v.agents.find((a) => a.role === "ouvrier" && a.tache && !attente.has(a.nom) && a.tache !== "B.1");
    }, 15000);
    verifier("un autre agent simulé est en marche", Boolean(cible), cible);
    const rang = page.locator("#agents .agent").filter({ has: page.locator(`button.agent-ligne .id`, { hasText: new RegExp(`^${cible.tache}$`) }) });
    const bouton = rang.locator('button[data-action="arreter"]');
    verifier("le bouton « Arrêter » est présent et discret", (await bouton.innerText()) === "Arrêter" && (await bouton.evaluate((b) => b.classList.contains("discret") && b.getBoundingClientRect().height <= 28)));
    await capture(page.locator("#vue-chantier .carte").nth(2), "arret-bouton");
    await bouton.click();
    verifier("un premier clic demande confirmation, au même endroit", (await bouton.innerText()) === "Confirmer l'arrêt");
    verifier("rien n'est parti au premier clic", requetes.filter((r) => r.url === "/api/arreter").length === 0);
    await capture(page.locator("#vue-chantier .carte").nth(2), "arret-confirmation");
    await PAUSE(5600);
    verifier("la confirmation s'efface d'elle-même", (await bouton.innerText()) === "Arrêter");
    await bouton.dblclick();
    await PAUSE(300);
    verifier("un double-clic n'arrête rien : aucune requête, le bouton attend sa confirmation", requetes.filter((r) => r.url === "/api/arreter").length === 0 && (await bouton.innerText()) === "Confirmer l'arrêt");
    await PAUSE(600);
    await bouton.click();
    await jusqua(async () => requetes.some((r) => r.url === "/api/arreter"), 5000);
    const arrets = requetes.filter((r) => r.url === "/api/arreter");
    verifier("le clic de confirmation envoie l'arrêt, pour cette tâche seulement", arrets.length === 1 && arrets[0].corps.tache === cible.tache, arrets);
    const revenue = await jusqua(async () => {
      const v = await etat(s);
      const t = v.taches.find((x) => x.id === cible.tache);
      return t.etat === "revenu" ? t : null;
    }, 15000);
    verifier("la tâche revient dans la vue du serveur", Boolean(revenue));
    verifier("l'historique porte l'issue « arretee »", revenue && revenue.historique.slice(-1)[0].issue === "arretee");
    await page.waitForFunction((tache) => [...document.querySelectorAll("#lignes tr")].some((tr) => tr.innerText.includes(tache) && /Arrêtée par toi/.test(tr.innerText)), cible.tache, { timeout: 8000 });
    verifier("le tableau affiche « Arrêtée par toi »", /Arrêtée par toi/.test(await page.locator("#lignes").innerText()));
    verifier("l'avis du serveur est affiché tel quel", /Arrêt demandé pour la tâche/.test(await page.locator("#attente").innerText()) || /Arrêt demandé pour la tâche/.test(await page.locator("#sous-saisie").innerText()));
    verifier("le poste ne montre plus de bouton d'arrêt pour cet agent", (await page.locator(`#agents .agent .id`, { hasText: new RegExp(`^${cible.tache}$`) }).count()) === 0);
    const postes = await page.locator("svg.salle").evaluate((e) => e.textContent);
    verifier("le poste de la salle dit « Arrêtée par toi »", /Arrêtée par toi/.test(postes), postes);
    await capture(page.locator("#vue-chantier"), "tache-arretee");
    await aller(page, "plan");
    await page.locator(`.noeud[data-id="${cible.tache}"]`).click();
    const fiche = await page.locator("#fiche").innerText();
    verifier("la fiche de tâche montre l'arrêt sans l'appeler un échec", /Arrêtée par toi/.test(fiche) && !/✕/.test(fiche), fiche);
    await capture(page.locator("#vue-plan"), "tache-arretee-plan");
    await aller(page, "conversation");
    const decision = await page.locator("#colonne").innerText();
    verifier("la décision dit « arrêtée par toi »", /arrêtée par toi\./.test(decision));
    verifier("aucune erreur dans la page", erreurs.length === 0, erreurs);
    await contexte.close();
  }

  /* ---------- 4. Arrêter l'orchestrateur pendant qu'il répond ---------- */
  console.log("\n== Partie 4 : arrêter l'orchestrateur");
  {
    /* La réponse de la démonstration dure quelques secondes : sur une machine chargée, elle peut finir avant le geste.
       On attend des états de la page (bouton visible, texte du bouton), et on reprend sur une démonstration neuve
       si la réponse s'est achevée trop tôt. Les vérifications ne sont écrites que pour la dernière tentative. */
    let resultats = [];
    for (let tentative = 1; tentative <= 4; tentative += 1) {
      const s = await demarrer(25);
      const { page, contexte, erreurs, requetes } = await ouvrir(browser, s);
      const bouton = page.locator("#arret-orch");
      const res = [];
      const note = (nom, condition, detail) => res.push([nom, condition, detail]);
      let complet = false;
      try {
        note("pas de bouton d'arrêt quand l'orchestrateur ne répond pas", await bouton.isHidden());
        await page.fill("#message", "Un objectif pour tester l'arrêt.");
        await page.click("#envoi");
        await page.waitForSelector("#arret-orch:not([hidden])", { timeout: 8000 });
        note("le bouton « Arrêter » apparaît à côté de la saisie pendant la réponse", (await bouton.innerText({ timeout: 2000 })) === "Arrêter");
        await capture(page.locator(".saisie"), "arret-orchestrateur");
        await bouton.dblclick({ timeout: 2000 });
        await PAUSE(200);
        note("un double-clic n'arrête pas l'orchestrateur", requetes.filter((r) => r.url === "/api/arreter").length === 0 && (await bouton.innerText({ timeout: 2000 })) === "Confirmer l'arrêt", requetes);
        await capture(page.locator(".saisie"), "arret-orchestrateur-confirmation");
        await PAUSE(600);
        const reponse = page.waitForResponse((r) => new URL(r.url()).pathname === "/api/arreter", { timeout: 4000 });
        await bouton.click({ timeout: 2000 });
        const arret = (await (await reponse).json()).arret;
        const arrets = requetes.filter((r) => r.url === "/api/arreter");
        note("l'arrêt part avec un corps vide", arrets.length === 1 && Object.keys(arrets[0].corps).length === 0, arrets);
        complet = arret.fait === true;
        if (complet) {
          note("l'orchestrateur s'arrête", Boolean(await jusqua(async () => !(await etat(s)).occupe, 15000)));
          await page.waitForSelector("#arret-orch", { state: "hidden", timeout: 8000 });
          note("le bouton disparaît une fois l'orchestrateur revenu", await bouton.isHidden());
          note("la phrase du serveur est affichée", /Arrêt demandé : la réponse en cours s'arrête/.test(await page.locator("#sous-saisie").innerText()), await page.locator("#sous-saisie").innerText());
        }
        note("aucune erreur dans la page", erreurs.length === 0, erreurs);
      } catch (e) {
        note(`la partie s'est interrompue (tentative ${tentative})`, false, String(e).split("\n")[0]);
      }
      await contexte.close();
      resultats = res;
      if (complet) break;
      console.log(`(tentative ${tentative} : la réponse s'est achevée avant le geste, reprise)`);
    }
    resultats.forEach(([nom, condition, detail]) => verifier(nom, condition, detail));
  }

  /* ---------- 5. Vues fabriquées : demande sans règle, texte hostile, fenêtre étroite ---------- */
  console.log("\n== Partie 5 : demande sans règle, affichage sûr, fenêtre étroite");
  {
    const base = await etat(s1);
    const mal = '<img src=x onerror="window.__xss=1">';
    const faux = JSON.parse(JSON.stringify(base));
    faux.agents = [
      { nom: "B-ouvrier-1", tache: "B", role: "ouvrier", lignes: ["Lit la consigne", "En attente de ton autorisation : Lance une commande"] },
      { nom: "orchestrateur", tache: "", role: "orchestrateur", lignes: ["Réponse en cours"] },
    ];
    const nom = faux.agents[0].nom;
    faux.autorisations = [
      { id: "x1", agent: nom, outil: "Bash", phrase: `${nom} veut lancer la commande « ${mal} ».`, regle: `Bash(${mal}:*)`, detail: `${mal}\n<script>window.__xss=2</script>` },
      { id: "x2", agent: nom, outil: "WebFetch", phrase: "L'agent veut lire une page sur internet.", regle: "", detail: "https://exemple.invalid/page" },
    ];
    faux.agents.forEach((a) => { a.lignes = [...a.lignes, mal, "<script>window.__xss=3</script>"]; });
    const contexte = await browser.newContext({ viewport: { width: 1280, height: 800 }, deviceScaleFactor: 2 });
    const page = await contexte.newPage();
    const erreurs = [];
    page.on("pageerror", (e) => erreurs.push(String(e)));
    await page.route("**/api/etat", (route) => route.fulfill({ json: faux }));
    await page.goto(s1.url);
    await page.waitForSelector("#colonne .autorisation");
    const cartes = page.locator("#colonne .autorisation");
    verifier("deux cartes s'affichent", (await cartes.count()) === 2);
    const sans = cartes.nth(1);
    const boutons = await sans.locator("button").allInnerTexts();
    verifier("sans règle, « Toujours pour ce projet » n'apparaît pas", boutons.join("|") === "Autoriser une fois|Refuser", boutons);
    verifier("sans règle, la carte le dit", /Aucune règle n'est possible/.test(await sans.innerText()));
    const avecRegle = cartes.nth(0);
    verifier("avec règle, « Toujours pour ce projet » apparaît", (await avecRegle.locator("button").allInnerTexts()).includes("Toujours pour ce projet"));
    await avecRegle.locator(".autor-corps").click();
    await aller(page, "chantier");
    await page.locator("#agents button.agent-ligne").first().click();
    const resultat = await page.evaluate(() => ({
      xss: window.__xss,
      images: document.querySelectorAll('img[src="x"]').length,
      scripts: document.querySelectorAll("#colonne script, #attente script, #agents script").length,
      regle: document.querySelector("#attente .autorisation .regle").textContent,
      detail: document.querySelector("#attente .autorisation pre.detail")?.textContent ?? "",
      journal: [...document.querySelectorAll("#agents .journal li")].map((li) => li.textContent),
    }));
    verifier("rien n'est exécuté (aucun gestionnaire onerror ni script)", resultat.xss === undefined && resultat.images === 0 && resultat.scripts === 0, resultat);
    verifier("la règle hostile s'affiche comme du texte", resultat.regle === `Bash(${mal}:*)`, resultat.regle);
    verifier("le détail hostile s'affiche comme du texte", resultat.detail.includes(mal) && resultat.detail.includes("<script>"), resultat.detail);
    verifier("la ligne d'activité hostile s'affiche comme du texte", resultat.journal.includes(mal), resultat.journal);
    verifier("la page n'a rien cassé", erreurs.length === 0, erreurs);
    await capture(page.locator("#vue-chantier"), "affichage-sur");
    await contexte.close();

    // Fenêtre étroite
    const etroit = await browser.newContext({ viewport: { width: 390, height: 800 }, deviceScaleFactor: 2 });
    const p2 = await etroit.newPage();
    await p2.route("**/api/etat", (route) => route.fulfill({ json: faux }));
    await p2.goto(s1.url);
    await p2.waitForSelector("#colonne .autorisation");
    await p2.locator("#colonne .autor-corps").first().click();
    const debord = await p2.evaluate(() => [...document.querySelectorAll(".carte-fil, .autorisation")].map((e) => e.scrollWidth - e.clientWidth).filter((d) => d > 1));
    verifier("sur une fenêtre étroite, la carte ne déborde pas", debord.length === 0, debord);
    await capture(p2.locator("#vue-conversation"), "carte-etroite");
    await etroit.close();

    // Anneau de progression et objectif long : les boîtes ne se recoupent pas
    const longue = JSON.parse(JSON.stringify(base));
    longue.contrat.objectif = "Reprendre entièrement le tableau de bord afin que chaque carte reste lisible, même lorsque la personne responsable décrit son objectif en plusieurs phrases détaillées, avec des précisions sur les cas limites, les fenêtres étroites, les textes très longs et les vérifications attendues avant la clôture du chantier. ".repeat(2);
    longue.taches = longue.taches.length ? longue.taches : [{ id: "A", etat: "verifie", etat_fr: "Vérifiée" }];
    for (const largeur of [1280, 400]) {
      const ctx = await browser.newContext({ viewport: { width: largeur, height: 900 }, deviceScaleFactor: 2 });
      const p = await ctx.newPage();
      await p.route("**/api/etat", (route) => route.fulfill({ json: longue }));
      await p.goto(s1.url);
      await aller(p, "chantier");
      await p.waitForSelector("#anneau svg.anneau");
      const m = await p.evaluate(() => {
        const r = (e) => { const b = e.getBoundingClientRect(); return { x: b.x, y: b.y, w: b.width, h: b.height, d: b.right, bas: b.bottom }; };
        const texte = document.getElementById("objectif");
        return { anneau: r(document.querySelector("#anneau svg.anneau")), texte: r(texte.parentElement), lignes: Math.round(texte.getBoundingClientRect().height / parseFloat(getComputedStyle(texte).lineHeight)) };
      });
      const chevauche = m.anneau.x < m.texte.d && m.texte.x < m.anneau.d && m.anneau.y < m.texte.bas && m.texte.y < m.anneau.bas;
      verifier(`objectif long à ${largeur} px : au moins 4 lignes`, m.lignes >= 4, m.lignes);
      verifier(`objectif long à ${largeur} px : l'anneau garde 78 px`, Math.round(m.anneau.w) === 78 && Math.round(m.anneau.h) === 78, m.anneau);
      verifier(`objectif long à ${largeur} px : l'anneau et le texte ne se chevauchent pas`, !chevauche, m);
      if (largeur === 1280) await capture(p.locator("#vue-chantier .carte").first(), "anneau");
      await ctx.close();
    }
  }

  /* ---------- 5 bis. Ce que la carte dit de la règle, journal long, noms d'agent, armement ---------- */
  console.log("\n== Partie 5 bis : phrases de règle, journal long, nom d'agent hostile, désarmement");
  {
    const base = await etat(s1);
    const pageFabriquee = async (courante, options = {}) => {
      const contexte = await browser.newContext({ viewport: { width: 1280, height: 800 }, deviceScaleFactor: 2, ...options });
      const page = await contexte.newPage();
      const erreurs = [], requetes = [];
      page.on("pageerror", (e) => erreurs.push(String(e)));
      page.on("request", (r) => { if (r.method() === "POST") requetes.push(new URL(r.url()).pathname); });
      await page.route("**/api/etat", (route) => route.fulfill({ json: courante() }));
      await page.goto(s1.url);
      return { page, contexte, erreurs, requetes };
    };
    const copie = () => JSON.parse(JSON.stringify(base));

    // Les trois formes de règle du guichet, et une forme inconnue
    {
      const vue = copie();
      const demande = (id, outil, regle, detail) => ({ id, agent: "B-ouvrier-1", outil, phrase: `B-ouvrier-1 demande l'outil ${outil}.`, regle, detail });
      vue.autorisations = [
        demande("r1", "Bash", "Bash(npm install:*)", "npm install left-pad"),
        demande("r2", "WebFetch", "WebFetch(domain:example.com)", "https://example.com/page"),
        demande("r3", "Write", "Write", "/tmp/fichier.txt"),
        demande("r4", "Read", "Read", "/tmp/fichier.txt"),
        demande("r5", "mcp__outil", "mcp__outil(valeur rare)", "{}"),
      ];
      const attendu = [
        "toute commande qui commence par « npm install » sera permise sans redemander.",
        "toute page du site example.com pourra être consultée sans redemander.",
        "tout usage de l'outil Write sera permis sans redemander : cela veut dire toute modification de fichier.",
        "tout usage de l'outil Read sera permis sans redemander.",
        "cette règle sera retenue telle quelle pour ce projet",
      ];
      const { page, contexte, erreurs } = await pageFabriquee(() => vue, { viewport: { width: 1280, height: 1500 } });
      await page.waitForSelector("#colonne .autorisation");
      const cartes = page.locator("#colonne .autorisation");
      for (let i = 0; i < attendu.length; i += 1) {
        const texte = (await cartes.nth(i).innerText()).replace(/\s+/g, " ");
        const regle = await cartes.nth(i).locator(".regle").innerText();
        verifier(`la carte ${vue.autorisations[i].regle} dit ce qu'elle permet`, texte.includes(attendu[i]) && regle === vue.autorisations[i].regle, texte);
      }
      verifier("une règle d'écriture dit « toute modification de fichier »", /toute modification de fichier/.test(await cartes.nth(2).innerText()));
      await capture(page.locator("#vue-conversation"), "regles");
      verifier("aucune erreur dans la page", erreurs.length === 0, erreurs);
      await contexte.close();
    }

    // Le journal long : ouverture sur les plus récentes, position gardée
    {
      const texteLong = " : texte d'activité assez long pour occuper de la place dans le journal déroulé, comme le ferait un vrai agent.";
      const lignesDe = (a, b) => Array.from({ length: b - a + 1 }, (_, k) => `Ligne ${a + k}${texteLong}`);
      const vue = copie();
      vue.taches[0].etat = "en_cours"; vue.taches[0].etat_fr = "En cours";
      vue.autorisations = [];
      vue.agents = [{ nom: "A-ouvrier-1", tache: vue.taches[0].id, role: "ouvrier", lignes: lignesDe(1, 30) }];
      const { page, contexte, erreurs } = await pageFabriquee(() => vue, { viewport: { width: 1280, height: 1500 } });
      await aller(page, "chantier");
      await page.waitForSelector("#agents .agent-ligne");
      await page.locator("#agents button.agent-ligne").click();
      const mesure = () => page.evaluate(() => { const j = document.querySelector("#agents .journal"); return { n: j.children.length, haut: j.scrollTop, reste: j.scrollHeight - j.scrollTop - j.clientHeight, deborde: j.scrollHeight > j.clientHeight, derniere: j.lastElementChild.textContent.slice(0, 9) }; });
      let m = await mesure();
      verifier("le journal de 30 lignes déborde et s'ouvre sur les plus récentes", m.n === 30 && m.deborde && m.reste <= 2 && m.derniere === "Ligne 30 ", m);
      await capture(page.locator("#vue-chantier .carte").nth(2), "journal");
      await page.evaluate(() => { document.querySelector("#agents .journal").scrollTop = 120; });
      vue.agents[0].lignes = lignesDe(2, 31);
      await page.evaluate(() => charger());
      m = await mesure();
      verifier("remonté pour lire, le journal garde sa position quand une ligne arrive", m.derniere === "Ligne 31 " && Math.abs(m.haut - 120) <= 1, m);
      await page.evaluate(() => { const j = document.querySelector("#agents .journal"); j.scrollTop = j.scrollHeight; });
      vue.agents[0].lignes = lignesDe(3, 32);
      await page.evaluate(() => charger());
      m = await mesure();
      verifier("en bas, le journal y reste quand une ligne arrive", m.derniere === "Ligne 32 " && m.reste <= 2, m);
      verifier("aucune erreur dans la page", erreurs.length === 0, erreurs);
      await contexte.close();
    }

    // Un nom d'agent hostile sert d'attribut ; un agent qui part puis revient retrouve un bouton désarmé
    {
      const nomMauvais = 'x" onmouseover="window.__xss=9" data-y="<b>';
      const vue = copie();
      vue.taches[0].etat = "en_cours"; vue.taches[0].etat_fr = "En cours";
      vue.autorisations = [];
      const agent = { nom: nomMauvais, tache: vue.taches[0].id, role: "ouvrier", lignes: ["Lit la consigne"] };
      vue.agents = [agent];
      const { page, contexte, erreurs, requetes } = await pageFabriquee(() => vue);
      await aller(page, "chantier");
      await page.waitForSelector("#agents .agent-ligne");
      const mesure = await page.evaluate(() => ({
        ligne: document.querySelector("#agents button.agent-ligne").dataset.nom,
        poste: document.querySelector("svg.salle .poste-actif").dataset.nom,
        intrus: document.querySelectorAll("[onmouseover], [data-y]").length,
        xss: window.__xss,
      }));
      verifier("le nom d'agent reste une valeur d'attribut, sans attribut en plus", mesure.ligne === nomMauvais && mesure.poste === nomMauvais && mesure.intrus === 0 && mesure.xss === undefined, mesure);
      await page.locator("#agents button.agent-ligne").click();
      verifier("le journal de cet agent se déroule", (await page.locator("#agents .journal li").count()) === 1);
      const bouton = page.locator('#agents button[data-action="arreter"]');
      await bouton.click();
      verifier("le bouton est armé", (await bouton.innerText()) === "Confirmer l'arrêt");
      vue.agents = [];
      await page.evaluate(() => charger());
      verifier("l'agent parti, sa ligne disparaît", (await page.locator("#agents .agent").count()) === 0);
      vue.agents = [agent];
      await page.evaluate(() => charger());
      verifier("revenu en moins de cinq secondes, l'agent retrouve un bouton désarmé", (await page.locator('#agents button[data-action="arreter"]').innerText()) === "Arrêter");
      verifier("aucune requête d'arrêt n'est partie", !requetes.includes("/api/arreter"), requetes);
      verifier("aucune erreur dans la page", erreurs.length === 0, erreurs);
      await contexte.close();
    }
  }

  /* ---------- 6. La page des instantanés (sans serveur) ---------- */
  console.log("\n== Partie 6 : la page des instantanés");
  {
    const fichier = path.join(fs.mkdtempSync(path.join(os.tmpdir(), "atelier-d2-")), "instantanes.html");
    const r = spawnSync("python3", ["-m", "atelier", "instantanes", fichier], { cwd: RACINE, encoding: "utf8" });
    verifier("la commande instantanes réussit", r.status === 0, r.stderr);
    const contexte = await browser.newContext({ viewport: { width: 1280, height: 800 } });
    const page = await contexte.newPage();
    const erreurs = [];
    page.on("pageerror", (e) => erreurs.push(String(e)));
    await page.goto(`file://${fichier}`);
    const nombre = await page.evaluate(() => INSTANTANES.length);
    verifier("la page rejoue ses 42 vues enregistrées", nombre === 42, nombre);
    verifier("une vue enregistrée porte une autorisation ouverte", await page.evaluate(() => INSTANTANES.some((v) => (v.autorisations || []).length > 0)));
    await page.fill("#message", "Un objectif.");
    await page.click("#envoi");
    await page.waitForSelector('#colonne button[data-action="valider"]', { timeout: 15000 });
    await page.click('#colonne button[data-action="valider"]');
    await page.waitForSelector("#colonne .autorisation", { timeout: 15000 });
    verifier("la carte d'autorisation s'ouvre dans la page autonome", /npm install left-pad/.test(await page.locator("#colonne .autorisation").innerText()));
    await page.locator("#colonne .autorisation").getByRole("button", { name: "Autoriser une fois" }).click();
    await jusqua(async () => (await page.locator(".autorisation").count()) === 0, 8000);
    verifier("le clic fait avancer la rejouée, sans serveur", (await page.locator(".autorisation").count()) === 0);
    await page.waitForSelector("#colonne .carte-fil.decision", { timeout: 90000 });
    verifier("la rejouée continue jusqu'à la décision suivante", (await page.locator("#colonne .carte-fil.decision").count()) >= 1);
    verifier("aucune erreur dans la page autonome", erreurs.length === 0, erreurs);
    await contexte.close();
  }

  await browser.close();
}

function arreterServeurs() {
  for (const s of serveurs) { try { s.processus.kill("SIGKILL"); } catch (e) { /* déjà arrêté */ } }
}
process.on("exit", arreterServeurs);

main().then(() => {
  console.log(echecs ? `\n${echecs} vérification(s) en échec.` : "\nToutes les vérifications passent.");
  arreterServeurs();
  process.exit(echecs ? 1 : 0);
}).catch((erreur) => {
  console.error("\nECHEC  - l'essai s'est interrompu :", erreur);
  arreterServeurs();
  process.exit(1);
});
