"""Doubles de test du guichet : ils servent aux tests, jamais au produit."""

from atelier.guichet import CHOIX, Guichet, Reponse, _Demande

SCENARIO_EPUISE = "Le scénario de démonstration ne prévoit pas cette demande."


class GuichetSimule(Guichet):
    """Double de test du guichet : répond tout de suite, selon un scénario écrit d'avance.

    Le scénario est une liste de choix (« une_fois », « toujours », « chantier », « non ») ou de
    Reponse,
    consommée dans l'ordre. Une fois épuisé, le guichet répond « non ». La règle d'un
    « toujours » est toujours celle que le vrai guichet proposerait, jamais celle du scénario.
    Quand cette règle manque, le vrai guichet refuserait « toujours » et laisserait la demande
    ouverte ; le guichet simulé, qui doit répondre tout de suite, répond alors « une_fois ». De
    même pour « chantier », dont les règles sont toujours celles du vrai guichet.
    """

    def __init__(self, scenario=()):
        super().__init__()
        self._scenario = [r if isinstance(r, Reponse) else Reponse(r) for r in scenario]
        if any(r.choix not in CHOIX for r in self._scenario):
            raise ValueError("Le scénario contient un choix inconnu.")
        self.demandes: list[dict] = []

    def demander(self, agent: str, outil: str, entree: dict) -> Reponse:
        with self._verrou:
            demande = _Demande(self._nouvel_identifiant(), agent, outil, entree)
            self.demandes.append(demande.fiche())
            prevue = self._scenario.pop(0) if self._scenario else Reponse("non", SCENARIO_EPUISE)
        if prevue.choix == "chantier":
            if not demande.regles_chantier:
                return Reponse("une_fois", prevue.message, "")
            return Reponse("chantier", prevue.message, "", tuple(demande.regles_chantier))
        if prevue.choix != "toujours":
            return Reponse(prevue.choix, prevue.message, "")
        if not demande.regle:
            return Reponse("une_fois", prevue.message, "")
        return Reponse("toujours", prevue.message, demande.regle)
