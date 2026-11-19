"""Ciro in English. Run from ciro/: python3 -m unittest tests.test_inglese"""

from tests.test_coordinamento_ciro import BaseCiro, domande, modulo_cervello, server
import collaudo as modulo_collaudo


class BaseInglese(BaseCiro):
    def setUp(self):
        super().setUp()
        modulo_cervello.imposta("lingua", "en")
        self.esegui_prima = modulo_cervello._esegui
        modulo_cervello._esegui = lambda comando, timeout: ("OK.", "", 0) if comando[0] == "opencode" \
            else self.esegui_prima(comando, timeout)
        self.c = server._cervello

    def tearDown(self):
        modulo_cervello._esegui = self.esegui_prima
        super().tearDown()

    def annunciata(self, progetto="ironworks", **altro):
        identificativo = self.chiedi(progetto, **altro)
        self.giro()
        return identificativo


class TestInglese(BaseInglese):
    def test_domanda_detta_in_inglese(self):
        self.annunciata(opzioni={"A": "proceed", "B": "stop"})
        frase = self.coda()[-1]["testo"]
        self.assertEqual(frase, "Question one, from ironworks: Quale schema uso per gli spazi Chat? "
                                "one, proceed; two, stop. I recommend one. How do I answer?")

    def test_risposte_in_inglese(self):
        for detto, lettera in (("two", "B"), ("One.", "A"), ("the second", "B"), ("I said two", "B"),
                               ("answer two", "B")):
            identificativo = self.annunciata(oggetto=detto, opzioni={"A": "proceed", "B": "stop"})
            esito = self.c.chiedi(detto)
            self.assertTrue(esito["mandato"], (detto, esito))
            self.assertEqual(domande.leggi(identificativo)["risposta"]["scelta"], lettera, detto)
        self.assertEqual(esito["risposta"], "Sent: two, stop.")

    def test_yes_accetta_il_consiglio(self):
        identificativo = self.annunciata(opzioni={"A": "proceed", "B": "stop"})
        self.assertEqual(self.c.chiedi("yes")["risposta"], "Sent: one, proceed.")
        self.assertEqual(domande.leggi(identificativo)["risposta"]["scelta"], "A")

    def test_progetto_e_correzione(self):
        primo = self.annunciata("ironworks", opzioni={"A": "proceed", "B": "stop"})
        self.annunciata("contoso", opzioni={"A": "proceed", "B": "stop"})
        self.assertTrue(self.c.chiedi("one")["risposta"].startswith("Which question?"))
        self.assertTrue(self.c.chiedi("two for ironworks")["mandato"])
        self.assertEqual(domande.leggi(primo)["risposta"]["scelta"], "B")
        self.assertIn("Correction sent to ironworks", self.c.chiedi("answer one")["risposta"])

    def test_pausa_in_inglese(self):
        self.assertEqual(self.c.chiedi("pause projects except prova-ciro")["risposta"],
                         "Projects paused, except prova-ciro.")
        self.assertTrue(modulo_cervello.leggi_impostazioni()["pausa_progetti"])
        self.assertEqual(self.c.chiedi("resume projects")["risposta"], "Projects resumed.")

    def test_cambio_lingua_a_voce(self):
        self.assertEqual(self.c.chiedi("parla italiano")["risposta"], "Va bene, da ora parlo italiano.")
        self.assertEqual(modulo_cervello.leggi_impostazioni()["lingua"], "it")
        self.assertEqual(self.c.chiedi("speak English")["risposta"], "OK, from now on I speak English.")
        self.assertEqual(modulo_cervello.leggi_impostazioni()["lingua"], "en")

    def test_modelli_e_voce(self):
        self.assertEqual(server.voce_attuale(), ("am_michael", "en-us"))
        self.assertEqual(server.lingua_whisper(), "en")
        self.assertEqual(server.per_voce("one, proceed; two, stop. A"), "one, proceed; two, stop. A")
        modulo_cervello.imposta("lingua", "it")
        self.assertEqual(server.voce_attuale(), ("im_nicola", "it"))

    def test_istruzioni_in_inglese(self):
        prompt = self.c._prompt("how are the sessions?")
        self.assertIn("You are Ciro", prompt)
        self.assertIn("User: how are the sessions?", prompt)

    def test_profilo_separato_per_lingua(self):
        modulo_cervello.aggiorna_profilo(fine_frase_ms=650)
        self.assertEqual(modulo_cervello.leggi_impostazioni()["profilo_voce_en"]["fine_frase_ms"], 650)
        modulo_cervello.imposta("lingua", "it")
        self.assertNotIn("fine_frase_ms", modulo_cervello.profilo_voce())


class TestCalibrazioneInglese(BaseInglese):
    def test_calibrazione_in_inglese(self):
        detti = []
        self.c.collaudo = modulo_collaudo.Collaudo(
            dire=lambda frase, **extra: detti.append(frase), stato_pausa=server.stato_pausa,
            imposta_pausa=server.imposta_pausa, cartella=self.tmp / "collaudi", righe_registro=lambda dal: [])
        esito = self.c.chiedi("calibrate")
        self.assertIn("stay silent", esito["risposta"].lower())
        self.assertEqual(self.c.collaudo.silenzio(0.002, 0.003, 0.01), "Now repeat after me: one.")
        for detta in ("one", "Two", "yes", "no", "Hey Ciro", "Hey Ciro", "Hey Ciro", "one for test 2", "how are the sessions today"):
            self.c.chiedi(detta)
        self.assertTrue(detti[-1].startswith("Calibration done: I understood 9 phrases out of 9"), detti)
        self.assertTrue(modulo_cervello.leggi_impostazioni()["calibrato_en"])
        self.assertNotIn("calibrato", modulo_cervello.leggi_impostazioni())
