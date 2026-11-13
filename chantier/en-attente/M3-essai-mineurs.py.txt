"""Deux défauts dans le périmètre (atelier/agents.py), montrés par des comptes. À lancer depuis la copie :
   TMPDIR=<dossier à soi> python <ce fichier>
1. Après `arreter(tache)` (ouvrier ouvert en attente) ou un `liberer` rendu à sa borne, un nouvel ouvrier de la
   même tâche se connecte alors que l'ancien programme n'est pas encore déconnecté (point 5 du contrat).
2. Un `arreter(tache)` demandé pendant que le nouvel ouvrier attend la fermeture de l'ancien est perdu :
   il rend False et le nouvel ouvrier fait tout son tour.
3. Init à chaque tour (ce que fait peut-être le vrai) : rien ne casse."""
import os, sys, threading, time
sys.path.insert(0, os.path.dirname(__file__)); sys.path.insert(0, os.getcwd())
from faux import Fabrique, fils
from atelier.agents import AgentClaude

O = {"role": "ouvrier", "tache": "B", "tentative": 1}
def ex(a, garder=True, reprendre=None):
    return a.executer("C", "opus", "high", None, False, O, reprendre=reprendre, garder_ouvert=garder)
echecs = []
# 1a. arreter en attente, puis nouvel ouvrier
f = Fabrique(deconnexion=0.5); a = AgentClaude({}, delai_max_s=5, fabrique_client=f)
ex(a); a.arreter("B"); ex(a, garder=False); a.liberer_tous()
print("1a. arreter puis nouvel ouvrier : clients connectés en même temps (ancien, nouveau) =", f.chevauchements())
echecs += ["1a"] if f.chevauchements() else []
# 1b. liberer rendu à sa borne, puis reprise
f = Fabrique(deconnexion=0.5); a = AgentClaude({}, delai_max_s=5, fabrique_client=f); a.delai_liberer_s = 0.05
r = ex(a); a.liberer("B"); ex(a, garder=False, reprendre=r.session); a.liberer_tous()
print("1b. liberer (borne atteinte) puis reprise : connectés en même temps =", f.chevauchements())
echecs += ["1b"] if f.chevauchements() else []
# 2. arreter pendant que le nouvel ouvrier attend la fermeture de l'ancien
f = Fabrique(deconnexion=0.8); a = AgentClaude({}, delai_max_s=5, fabrique_client=f)
ex(a); res = []; th = threading.Thread(target=lambda: res.append(ex(a, garder=False))); th.start()
time.sleep(0.2); rendu = a.arreter("B"); th.join()
print(f"2. arreter pendant la fermeture de l'ancien : rend {rendu} ; le nouvel ouvrier : ok={res[0].ok} erreur={res[0].erreur!r}")
echecs += ["2"] if res[0].ok else []
# 3. init à chaque tour, mode plan
f = Fabrique(init_a_chaque_tour=True); a = AgentClaude({"mode_ouvriers": "plan"}, delai_max_s=5, fabrique_client=f); ev = []; a.sur_evenement = ev.append
r = ex(a); r2 = ex(a, reprendre=r.session); r3 = ex(a, garder=False, reprendre=r.session)
print("3. init à chaque tour :", [(x.ok, x.ouverte) for x in (r, r2, r3)], "connexions", f.connexions, "déconnexions", f.deconnexions, "types", sorted({e["type"] for e in ev}), "fils", fils())
print("DÉFAUTS MONTRÉS :", echecs)
