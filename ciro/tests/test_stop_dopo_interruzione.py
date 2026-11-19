"""After you interrupt Ciro, "fermati" / "basta" / "stop" just means: be quiet.

Run from ciro/: python3 -m unittest tests.test_stop_dopo_interruzione
"""

import unittest

from tests.test_coordinamento_ciro import server


class TestStop(unittest.TestCase):
    def test_stop_riconosciuti(self):
        for testo in ("Ciro, fermati.", "Spero fermati.", "fermati", "Basta!", "zitto", "Ciro stop",
                      "aspetta", "Ok, basta.", "stai zitto", "taci", "Stop.", "wait", "be quiet"):
            self.assertTrue(server.solo_stop(testo), testo)

    def test_frasi_vere_restano(self):
        for testo in ("Come stanno le sessioni?", "due, fermati per alpha", "Ferma il deploy di alpha",
                      "Sì", "Basta con i riepiloghi ogni 30 minuti", "uno"):
            self.assertFalse(server.solo_stop(testo), testo)


if __name__ == "__main__":
    unittest.main()
