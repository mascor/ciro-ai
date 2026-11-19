"""Old mail from projects without an open session, and decisions remembered after a restart.

Run from ciro/: python3 -m unittest tests.test_attese_vecchie
"""

import time
import unittest
from unittest import mock

from tests.test_coordinamento_ciro import BaseCiro, modulo_cervello, posta, server

ORA = 22 * 3600   # the real case: a message from yesterday


class TestAtteseVecchie(BaseCiro):
    def manda(self, progetto):
        posta.invia(progetto, "opencode", "decisione", "Chi vede lo spazio?", "A, B o C?",
                    azione="decisione")

    def progetti_tra(self, secondi):
        adesso = time.time() + secondi
        with mock.patch.object(server.time, "time", return_value=adesso):
            return [v["progetto"] for v in server.attese()]

    def test_vecchia_senza_sessione_aperta_sparisce(self):
        self.manda("server-agent")   # no session called server-agent is open
        self.assertNotIn("server-agent", self.progetti_tra(ORA))

    def test_recente_senza_sessione_resta(self):
        self.manda("server-agent")   # e.g. an agent on a server: shown for a while
        self.assertIn("server-agent", self.progetti_tra(5 * 60))

    def test_vecchia_con_sessione_aperta_resta(self):
        modulo_cervello.leggi_sessioni = lambda: [
            {"progetto": "contoso", "stato": "ferma", "aspetta_utente": False, "da_secondi": ORA + 3600}]
        self.manda("contoso")
        self.assertIn("contoso", self.progetti_tra(ORA))

    def test_decisione_mandata_ricordata_dopo_riavvio(self):
        self.manda("server-agent")
        server._cervello.segna_decisione("server-agent")
        server._cervello = modulo_cervello.Cervello()   # Ciro restarted
        self.assertIn("server-agent", server._cervello.decisioni_mandate)
        self.assertNotIn("server-agent", self.progetti_tra(5 * 60))


class TestDomandaSessioneRisposta(BaseCiro):
    """A session question leaves the list once Ciro has sent the answer (the real case:
    answered twice by voice, still listed because the session had not moved yet)."""

    def sessione_che_aspetta(self, da_secondi):
        modulo_cervello.leggi_sessioni = lambda: [
            {"progetto": "tools", "stato": "aspetta te", "aspetta_utente": True, "da_secondi": da_secondi,
             "domanda": "Riscrivo la storia? (S/N)", "attese_per_utente": []}]

    def test_risposta_mandata_toglie_la_domanda(self):
        self.sessione_che_aspetta(60)
        self.assertIn("tools", [v["progetto"] for v in server.attese()])
        server._cervello.segna_decisione("tools")
        self.assertNotIn("tools", [v["progetto"] for v in server.attese()])

    def test_domanda_nuova_dopo_la_risposta_ricompare(self):
        server._cervello.segna_decisione("tools")
        server._cervello.decisioni_mandate["tools"] -= 120   # answered 2 minutes ago
        self.sessione_che_aspetta(30)                         # the session asked again since
        self.assertIn("tools", [v["progetto"] for v in server.attese()])


if __name__ == "__main__":
    unittest.main()
