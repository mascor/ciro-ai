"""«Ehi Ciro»: Ciro answers only when called by name (or in the 15 s after he spoke).

Run from ciro/: python3 -m unittest tests.test_nome
"""

import unittest

from tests.test_coordinamento_ciro import server


class TestNome(unittest.TestCase):
    def test_chiamato_con_resto(self):
        for detto, resto in (("Ciro, come stanno le sessioni?", "come stanno le sessioni?"),
                             ("Ehi Ciro come stanno le sessioni", "come stanno le sessioni"),
                             ("Hey Ciro, status", "status"),
                             ("Ciro. Tre, sì.", "Tre, sì."),
                             ("Kiro, pausa progetti", "pausa progetti"),
                             ("ciro' calibrati", "calibrati"),
                             ("Ok Ciro: speak English", "speak English")):
            self.assertEqual(server.togli_nome(detto), (True, resto), detto)

    def test_solo_il_nome(self):
        for detto in ("Ciro.", "Ehi Ciro!", "ciro", " Hey, Ciro? ", "Chiro"):
            self.assertEqual(server.togli_nome(detto), (True, ""), detto)

    def test_storpiature_vere(self):
        # come whisper ha scritto «Ehi Ciro» detto dall'utente il 19/11
        for detto in ("e il giro.", "ehi, tiro!", "Ehi Giro", "hey tiro"):
            self.assertEqual(server.togli_nome(detto), (True, ""), detto)
        self.assertEqual(server.togli_nome("Ehi tiro, come stanno le sessioni"),
                         (True, "come stanno le sessioni"))

    def test_non_chiamato(self):
        for detto in ("PIP PIP PIP PIP", "come stanno le sessioni", "tre, sì", "giro di prova", "zero",
                      "e poi", "il giro del mondo in ottanta giorni",
                      "Ho detto a Ciro di aspettare", "Cirocalibrati e poi", ""):
            self.assertEqual(server.togli_nome(detto)[0], False, detto)


if __name__ == "__main__":
    unittest.main()
