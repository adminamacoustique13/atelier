/* Essai M13 : ce que la page montre du moteur d'après la fiche M13, dans un navigateur sans écran.
 *   le coût « X $ sur Y $ », « travail gardé » sur une tâche revenue, le vérificateur selon le niveau,
 *   la demande de budget, et « Arrêter la reprise » pendant le délai d'une reprise annoncée.
 *
 * Lancer depuis la racine du dépôt :  node chantier/essais/M13-page.js
 * Le script démarre lui-même `python3 -m atelier demo` (agents simulés, aucun appel réel) sur un port libre.
 * La démonstration ne joue ni budget ni travail gardé : l'essai réécrit donc la réponse de /api/etat en chemin,
 * avec les champs que le serveur donne (prouvés par tests/test_serveur_page.py), et constate ce que la page en fait.
 * Captures dans chantier/captures/M13-*.png ; code de sortie non nul si une vérification échoue.
 */
const { chromium } = require("playwright");
const { spawn } = require("node:child_process");
const net = require("node:net");
const fs = require("node:fs");
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
const aller = (page, onglet) => page.evaluate((o) => { location.hash = `#${o}`; }, onglet);
const capture = (cible, nom) => cible.screenshot({ path: path.join(CAPTURES, `M13-${nom}.png`) });
const texteDe = async (cible) => (await cible.innerText()).replace(/[  ]/g, " ").replace(/\s+/g, " ").trim();

/* Ce que le serveur dirait d'un chantier au budget atteint : la première tâche revenue avec son travail gardé,
   vérifiée de façon bornée ; la deuxième jugée par les contrôles seuls ; une demande de budget ouverte. */
const QUESTION = "le budget du chantier est atteint (41.20 $ dépensés pour 40.00 $). La relancer accorde une rallonge d'un cinquième.";
function avecBudget(etat, reprise) {
  const [a, b] = etat.taches;
  a.historique = [{ tentative: 1, modele: "sonnet", effort: "medium", issue: "local", detail: "La liste vide plante.", origine: "verdict", reprise: false },
    { tentative: 1, modele: "sonnet", effort: "high", issue: "bacle", detail: "Le test du cas vide manque.", origine: "verdict", reprise: false, sous_tache: `${a.id}-a` }];
  Object.assign(a, { etat: "revenu", etat_fr: "Revenue", travail_garde: true, copie: "/projet/.atelier/arbres/" + a.id,
    verification: "bornee", verification_fr: "Vérification bornée", verificateur_fr: "Sonnet, effort moyen", phase: undefined });
  Object.assign(b, { verification: "mecanique", verification_fr: "Vérification mécanique seule",
    verificateur_fr: "les contrôles automatiques, sans vérificateur" });
  etat.cout_usd = 41.2;
  etat.budget = { depense_usd: 41.2, budget_usd: 40, atteint: true, fr: "41,20 $ sur 40,00 $" };
  etat.demandes = [{ id: `${a.id}-1`, tache: a.id, question: `Tâche ${a.id}, « ${a.titre} » : ${QUESTION}`,
    options: ["Relancer telle quelle", "Relancer un cran plus haut", "Abandonner"], reponse: null, nature: "budget" }];
  etat.autorisations = [];
  etat.reprise_en_attente = reprise;
  return etat;
}

async function main() {
  fs.mkdirSync(CAPTURES, { recursive: true });
  const browser = await chromium.launch();
  const serveur = await demarrer(3);
  const contexte = await browser.newContext({ viewport: { width: 1280, height: 800 }, deviceScaleFactor: 2 });
  const page = await contexte.newPage();
  const erreurs = [], arrets = [];
  page.on("pageerror", (e) => erreurs.push(String(e)));
  page.on("console", (m) => { if (m.type() === "error" && !/Failed to load resource/.test(m.text())) erreurs.push(m.text()); });
  page.on("request", (r) => { if (r.method() === "POST" && new URL(r.url()).pathname === "/api/arreter") arrets.push(r.postData()); });
  await page.goto(serveur.url + "#conversation");
  await page.fill("#message", "Moteur de calcul : formules de la norme, validées sur les cas de référence.");
  await page.click("#envoi");
  await page.waitForSelector('#colonne button[data-action="valider"]', { timeout: 30000 });
  await page.click('#colonne button[data-action="valider"]');
  await page.waitForSelector("#colonne .autorisation", { timeout: 30000 });
  const vrai = await (await fetch(`${serveur.url}/api/etat`)).json();
  const [a, b] = vrai.taches;

  /* ---------- 1. Sans budget : la page d'avant, plus le niveau de vérification ---------- */
  console.log("\n== Partie 1 : sans budget, rien ne change, et la fiche dit qui vérifie");
  verifier("le serveur dit qu'il n'y a pas de budget", vrai.budget === null, vrai.budget);
  verifier("chaque tâche porte son niveau et son vérificateur", vrai.taches.every((t) => t.verification && t.verification_fr && t.verificateur_fr && t.travail_garde === false),
    vrai.taches.map((t) => [t.id, t.verification, t.travail_garde]));
  verifier("le serveur dit qu'aucune reprise n'attend", vrai.reprise_en_attente === false, vrai.reprise_en_attente);
  await aller(page, "chantier");
  await page.waitForSelector("#lignes tr");
  verifier("le coût s'affiche seul, sans budget", (await page.locator("#jauges [data-budget]").count()) === 0 && /coût équivalent/i.test(await texteDe(page.locator("#jauges"))));
  verifier("aucune tâche ne dit « travail gardé »", (await page.locator("[data-garde]").count()) === 0);
  await aller(page, "plan");
  await page.click(`[data-action="choisir"][data-id="${a.id}"]`);
  const section = await texteDe(page.locator("#fiche [data-verification]"));
  verifier("la fiche d'une tâche dit son niveau et son vérificateur", section.includes(a.verification_fr) && section.includes(a.verificateur_fr), section);

  /* ---------- 2. Budget atteint : coût sur budget, travail gardé, demande de budget ---------- */
  console.log("\n== Partie 2 : budget atteint, travail gardé, demande de budget");
  let reprise = false;
  await page.route("**/api/etat", async (route) => {
    const reponse = await route.fetch();
    await route.fulfill({ response: reponse, json: avecBudget(await reponse.json(), reprise) });
  });
  await aller(page, "chantier");
  await page.waitForSelector("#jauges [data-budget]", { timeout: 15000 });
  const cout = await texteDe(page.locator("#jauges [data-budget]"));
  verifier("l'onglet Chantier écrit « X $ sur Y $ »", /^41,20 ?\$ sur 40,00 \$$/.test(cout), cout);
  verifier("un budget atteint se voit (ambre)", await page.locator("#jauges [data-budget].budget-atteint").count() === 1);
  const ligne = page.locator("#lignes tr", { has: page.locator(`.puce:text-is("${a.id}")`) });
  verifier("la tâche revenue porte « Travail gardé » dans le tableau", (await ligne.locator("[data-garde]").count()) === 1 && /Travail gardé/.test(await texteDe(ligne)), await texteDe(ligne));
  verifier("les autres tâches ne le portent pas", (await page.locator("#lignes [data-garde]").count()) === 1);
  const demande = page.locator("#attente .demande");
  const dit = await texteDe(demande);
  verifier("la demande de budget s'annonce avec la dépense et le budget", /Budget du chantier atteint : 41,20 \$ sur 40,00 \$/.test(dit), dit);
  verifier("elle garde la question du moteur et ses trois boutons", dit.includes("La relancer accorde une rallonge d'un cinquième.") && (await demande.locator("button").count()) === 3, dit);
  await capture(page.locator("#vue-chantier"), "chantier-budget");

  await aller(page, "conversation");
  const carte = await texteDe(page.locator("#colonne .carte-fil.decision"));
  verifier("la même demande est dans la conversation", /Budget du chantier atteint : 41,20 \$ sur 40,00 \$/.test(carte), carte);

  await aller(page, "salle");
  await page.waitForSelector("#salle-compteurs [data-budget]", { timeout: 15000 });
  const compteur = await texteDe(page.locator("#salle-compteurs [data-budget]"));
  verifier("la Salle écrit aussi « X $ sur Y $ »", compteur === "41,20 $ sur 40,00 $", compteur);
  await capture(page.locator("#vue-salle"), "salle-budget");

  /* ---------- 3. La fiche : travail gardé, vérification bornée, contrôles seuls ---------- */
  console.log("\n== Partie 3 : la fiche d'une tâche");
  await aller(page, "plan");
  await page.click(`[data-action="choisir"][data-id="${a.id}"]`);
  await page.waitForSelector("#fiche [data-garde]", { timeout: 15000 });
  const fiche = await texteDe(page.locator("#fiche"));
  verifier("la fiche de la tâche revenue dit que son travail est gardé", fiche.includes("Travail gardé dans sa copie : la relancer le reprend, sans tout refaire."), fiche);
  verifier("elle dit sa vérification bornée et son vérificateur", fiche.includes("Vérification bornée · vérificateur Sonnet, effort moyen"), fiche);
  verifier("son historique nomme la sous-tâche, sans la compter comme une tentative", /Tentative 1 · Sonnet, effort moyen/.test(fiche) && fiche.includes(`Sous-tâche ${a.id}-a · Sonnet, effort élevé`) && !/Tentative 2/.test(fiche), fiche);
  await capture(page.locator("#fiche"), "fiche-travail-garde");
  await page.click(`[data-action="choisir"][data-id="${b.id}"]`);
  await page.waitForFunction(() => /mécanique seule/.test(document.querySelector("#fiche [data-verification]")?.innerText || ""), null, { timeout: 15000 });
  const mecanique = await texteDe(page.locator("#fiche [data-verification]"));
  verifier("une tâche mécanique ne nomme aucun vérificateur", mecanique.includes("Vérification mécanique seule · les contrôles automatiques, sans vérificateur") && !/vérificateur (Sonnet|Opus|Haiku|Fable)/.test(mecanique), mecanique);
  verifier("sa fiche ne dit pas « travail gardé »", (await page.locator("#fiche [data-garde]").count()) === 0);

  /* ---------- 4. « Arrêter la reprise » pendant le délai d'une reprise annoncée ---------- */
  console.log("\n== Partie 4 : arrêter une reprise annoncée");
  await aller(page, "conversation");
  const bouton = page.locator("#arret-orch");
  verifier("sans reprise annoncée ni réponse en cours, le bouton d'arrêt est caché", await bouton.isHidden());
  reprise = true;
  await page.waitForFunction(() => !document.getElementById("arret-orch").hidden, null, { timeout: 15000 });
  verifier("pendant le délai, le bouton dit « Arrêter la reprise »", (await bouton.innerText()) === "Arrêter la reprise", await bouton.innerText());
  await capture(page.locator("#vue-conversation"), "arreter-la-reprise");
  await bouton.click();
  const parti = await (async () => { const fin = Date.now() + 5000; while (Date.now() < fin && !arrets.length) await PAUSE(50); return arrets.length; })();
  verifier("un seul clic envoie l'arrêt, sans confirmation", parti === 1 && arrets[0] === "{}", arrets);

  verifier("aucune erreur dans la page", erreurs.length === 0, erreurs);
  await contexte.close();
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
