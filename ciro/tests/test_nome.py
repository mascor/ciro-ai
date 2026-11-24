"""«Ehi Ciro»: Ciro answers only when called by name (or in the 15 s after he spoke).

Run from ciro/: python3 -m unittest tests.test_nome
"""

import unittest

import time

from tests.test_coordinamento_ciro import BaseCiro, server

import nome as modulo_nome


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

    def test_nome_storpiato_all_inizio_di_una_frase(self):
        # 19/11/2026: whisper wrote «Eishiro, uno, due.» and Ciro ignored the answer
        for detto, resto in (("Eishiro, uno, due.", "uno, due"), ("Ei shiro, tre sì", "tre sì"),
                             ("Eiciro cosa mi sono perso", "cosa mi sono perso")):
            self.assertEqual(server.togli_nome(detto), (True, resto), detto)
        for detto in ("Eccomi, uno due", "Hey, Siri, apri", "Esempio di frase lunga", "Hai, che bravo?"):
            self.assertFalse(server.togli_nome(detto)[0], detto)

    def test_non_chiamato(self):
        for detto in ("PIP PIP PIP PIP", "come stanno le sessioni", "tre, sì", "giro di prova", "zero",
                      "e poi", "il giro del mondo in ottanta giorni",
                      "Ho detto a Ciro di aspettare", "Cirocalibrati e poi", ""):
            self.assertEqual(server.togli_nome(detto)[0], False, detto)


class TestVarianti(BaseCiro):
    def setUp(self):
        super().setUp()
        server._tentativi_nome.clear()
        modulo_nome._sentite_una_volta.clear()

    def test_variante_imparata(self):
        self.assertFalse(server.togli_nome("quacca")[0])
        self.assertFalse(modulo_nome.impara_variante("quacca"))     # far from «Ciro»: once is not enough
        self.assertTrue(modulo_nome.impara_variante("quacca"))
        self.assertEqual(server.togli_nome("quacca"), (True, ""))
        self.assertEqual(server.togli_nome("Quacca, come stanno le sessioni?"), (True, "come stanno le sessioni?"))

    def test_mai_versi_o_risposte(self):
        for detto in ("e", "eh", "sì", "no", "tre", "una frase lunga di parole"):
            self.assertFalse(modulo_nome.impara_variante(detto), detto)

    def test_impara_dall_uso(self):
        t0 = time.time()
        server.nota_ascolto_nome("quacca", False, t0 + 20)
        self.assertEqual(server.nota_ascolto_nome("ehi, giro", True, t0 + 25), [])
        server.nota_ascolto_nome("quacca", False, t0 + 30)
        self.assertEqual(server.nota_ascolto_nome("ehi, giro", True, t0 + 35), ["quacca"])
        self.assertEqual(server.togli_nome("quacca"), (True, ""))

    def test_lontano_dal_nome_non_imparato_subito(self):
        # #39: in the calibration «A e Q» was saved as a way of saying the name
        self.assertTrue(modulo_nome.somiglia_al_nome(modulo_nome.compatta("Ehi Siro")))
        self.assertFalse(modulo_nome.somiglia_al_nome(modulo_nome.compatta("A e Q")))
        self.assertFalse(modulo_nome.impara_variante("A e Q"))
        self.assertFalse(server.togli_nome("A e Q")[0])
        self.assertTrue(modulo_nome.impara_variante("Ehi Siro"))

    def test_varianti_gia_imparate_restano(self):
        modulo_nome.cervello.aggiorna_profilo(nomi_sentiti=["quacca"])
        self.assertEqual(server.togli_nome("quacca"), (True, ""))
        self.assertTrue(modulo_nome.impara_variante("quacca"))

    def test_troppo_tardi_non_impara(self):
        t0 = time.time()
        server.nota_ascolto_nome("pippo", False, t0)
        self.assertEqual(server.nota_ascolto_nome("ehi ciro", True, t0 + 11), [])
        self.assertFalse(server.togli_nome("pippo")[0])

    def test_modello_grande_per_il_nome(self):
        self.assertEqual(server.passate_whisper(2.0, True, grande=True), [("preciso", True), ("preciso", False)])
        self.assertEqual(server.passate_whisper(2.0, True), [("rapido", True), ("rapido", False)])


if __name__ == "__main__":
    unittest.main()
