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

    def test_suono_ripetuto_scartato(self):
        # issue #61: whisper scrive bip e tasti come parole ripetute
        for testo in ("PIP PIP PIP PIP PIP", "bip bip bip", "Tic, tic, tic.", "pi pi pi"):
            self.assertTrue(server.solo_verso(testo), testo)

    def test_risposte_ripetute_restano(self):
        for testo in ("no no no", "Sì, sì, sì", "ok ok ok", "pip pip", "uno due tre",
                      "basta basta basta"):
            self.assertFalse(server.solo_verso(testo), testo)


if __name__ == "__main__":
    unittest.main()
