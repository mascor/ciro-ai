"""A lone filler sound ("e", "eh", "ehm") is not a sentence: Ciro must not answer it.

Run from ciro/: python3 -m unittest tests.test_versi
"""

import unittest

from tests.test_coordinamento_ciro import server


class TestVersi(unittest.TestCase):
    def test_versi_da_soli_scartati(self):
        for testo in ("e", "E.", "eh", "Ehm...", "mm", "Mmh.", "uhm", "hmm", " e ", "uh", "um",
                      "Pfff", "pff", "uff", "Ufff.", "oh", "shh", "psst"):
            self.assertTrue(server.solo_verso(testo), testo)

    def test_risposte_vere_restano(self):
        for testo in ("sì", "no", "uno", "due", "A", "ah", "e poi?", "Sì, approvo il piano", "ok"):
            self.assertFalse(server.solo_verso(testo), testo)


if __name__ == "__main__":
    unittest.main()
