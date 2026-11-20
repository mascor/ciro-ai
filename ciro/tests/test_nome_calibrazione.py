"""«Ehi Ciro» during calibration is a phrase to repeat, not a call (issue #38).

Run from ciro/: python3 -m unittest tests.test_nome_calibrazione
"""

from tests.test_coordinamento_ciro import BaseCiro, server


class TestNomeInCalibrazione(BaseCiro):
    def setUp(self):
        super().setUp()
        self.fase_prima = server._collaudo.fase

    def tearDown(self):
        server._collaudo.fase = self.fase_prima
        super().tearDown()

    def test_in_calibrazione_la_frase_va_alla_calibrazione(self):
        server._collaudo.fase = "frasi"
        for detto in ("Ehi, ciro!", "Ehi Ciro!", "Hey Ciro!"):
            self.assertEqual(server.nome_in_ascolto(detto), (False, detto))

    def test_fuori_calibrazione_il_nome_chiama_ciro(self):
        server._collaudo.fase = "spento"
        chiamato, resto = server.nome_in_ascolto("Ehi Ciro!")
        self.assertTrue(chiamato)
        self.assertEqual(resto, "")
        chiamato, resto = server.nome_in_ascolto("Ciro, leggi la posta")
        self.assertTrue(chiamato)
        self.assertIn("posta", resto.lower())
