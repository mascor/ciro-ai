"""Calibration («Ciro, calibrati») and acceptance test («Ciro, collaudo»). Run from ciro/:
python3 -m unittest tests.test_collaudo"""

import unittest

from tests.test_coordinamento_ciro import BaseCiro, domande, modulo_cervello, posta, server

import collaudo as modulo_collaudo


class BaseCollaudo(BaseCiro):
    def setUp(self):
        super().setUp()
        self.adesso = [1_900_000_000.0]
        self.detti = []
        self.pausa = {"attiva": False, "solo": []}

        def imposta_pausa(attiva, solo=None):
            self.pausa = {"attiva": bool(attiva), "solo": list(solo or [])}
            return self.pausa
        self.c = modulo_collaudo.Collaudo(
            dire=lambda frase, **extra: self.detti.append(frase),
            stato_pausa=lambda: dict(self.pausa), imposta_pausa=imposta_pausa,
            cartella=self.tmp / "collaudi", orologio=lambda: self.adesso[0],
            righe_registro=lambda dal: [])

    def avanti(self, secondi):
        self.adesso[0] += secondi
        self.c.tick()

    def rapporti(self):
        return list((self.tmp / "collaudi").glob("*.txt"))


class TestCalibrazione(BaseCollaudo):
    def test_avvio_pausa_e_silenzio(self):
        frase = self.c.avvia("calibrazione")
        self.assertIn("silenzio", frase.lower())
        self.assertEqual(self.c.fase, "silenzio")
        self.assertEqual(modulo_collaudo.SILENZIO_SECONDI, 5)
        self.assertEqual(self.pausa, {"attiva": True, "solo": ["prova-ciro", "prova-due"]})
        self.assertEqual(self.c.stato_guida()["fase"], "silenzio")
        # words said during the silence measurement are not commands
        self.assertEqual(self.c.gestisci("pausa progetti", 0.05)["risposta"], "Aspetta, sto misurando il silenzio.")
        self.assertEqual(self.c.silenzio(0.002, 0.004, 0.01), "Ora ripeti dopo di me: uno.")
        guida = self.c.stato_guida()
        self.assertEqual((guida["fase"], guida["passo"], guida["totale"], guida["dire"]), ("frasi", 1, 5, "uno"))

    def test_frasi_giuste_e_sbagliate(self):
        self.c.avvia("calibrazione")
        self.c.silenzio(0.002, 0.003, 0.01)
        self.assertEqual(self.c.gestisci("Uno.", 0.05)["risposta"], "Di': due.")
        self.assertEqual(self.c.stato_guida()["ultima"], {"attesa": "uno", "sentito": "Uno.", "ok": True})
        self.assertEqual(self.c.gestisci("dove", 0.05)["risposta"], "Non ho capito bene. Ripeti: due.")
        self.assertEqual(self.c.stato_guida()["ultima"], {"attesa": "due", "sentito": "dove", "ok": False})
        self.assertEqual(self.c.gestisci("2", 0.05)["risposta"], "Di': sì.")
        self.assertEqual(self.c.frasi_sentite[1]["tentativi"], ["dove", "2"])

    def test_due_errori_si_va_avanti(self):
        self.c.avvia("calibrazione")
        self.c.silenzio(0.002, 0.003, 0.01)
        self.c.gestisci("casa", 0.05)
        self.assertEqual(self.c.gestisci("cosa", 0.05)["risposta"], "Di': due.")
        self.assertFalse(self.c.frasi_sentite[0]["ok"])

    def test_silenzio_dell_utente_ripete_poi_salta(self):
        self.c.avvia("calibrazione")
        self.c.silenzio(0.002, 0.003, 0.01)
        self.avanti(21)
        self.assertEqual(self.detti[-1], "Non ti ho sentito. Ripeti: uno.")
        self.avanti(21)
        self.assertEqual(self.detti[-1], "Di': due.")

    def test_fine_soglia_da_rumore_e_voce(self):
        self.c.avvia("calibrazione")
        self.c.silenzio(0.002, 0.004, 0.01)
        for detta in ("uno", "Due", "si", "No.", "uno per prova 2"):
            self.c.gestisci(detta, 0.08)
        self.assertEqual(self.c.fase, "fine")
        self.assertTrue(self.detti[-1].startswith("Calibrazione finita"), self.detti)
        self.assertIn("5 frasi su 5", self.detti[-1])
        # threshold between the room noise (2.5 x p95) and the voice (0.35 x median)
        # threshold between the mean room noise and the voice: sqrt(0.002 x 0.08)
        self.assertAlmostEqual(modulo_cervello.leggi_impostazioni()["soglia_microfono"], 0.0126)
        self.assertEqual(self.pausa, {"attiva": False, "solo": []})
        self.assertEqual(len(self.rapporti()), 1)
        self.assertIn("Rumore", self.rapporti()[0].read_text(encoding="utf-8"))
        guida = self.c.stato_guida()
        self.assertEqual(guida["fase"], "fine")
        self.assertIn("5 frasi su 5", guida["riepilogo"])
        self.c.chiudi()
        self.assertIsNone(self.c.stato_guida())
        self.assertEqual(self.c.fase, "spento")

    def test_voce_debole_avvisa_e_soglia_sotto_la_voce(self):
        self.c.avvia("calibrazione")
        self.c.silenzio(0.008, 0.02, 0.03)           # noisy room
        for detta in ("uno", "due", "sì", "no", "uno per prova due"):
            self.c.gestisci(detta, 0.03)              # quiet voice: 0.35 x 0.03 = 0.0105
        self.assertAlmostEqual(modulo_cervello.leggi_impostazioni()["soglia_microfono"], 0.015)  # half the voice
        self.assertIn("avvicinati al microfono", self.detti[-1])

    def test_picco_nel_silenzio_non_da_falso_avviso(self):
        self.c.avvia("calibrazione")
        self.c.silenzio(0.0048, 0.0227, 0.0277)      # quiet room with one peak (19/11, real data)
        for detta in ("uno", "due", "sì", "no", "uno per prova due"):
            self.c.gestisci(detta, 0.0832)
        self.assertNotIn("avvicinati", self.detti[-1])
        self.assertAlmostEqual(modulo_cervello.leggi_impostazioni()["soglia_microfono"], 0.02)

    def test_ripeti_e_ferma(self):
        self.c.avvia("calibrazione")
        self.c.silenzio(0.002, 0.003, 0.01)
        self.assertEqual(self.c.ripeti(), "Di': uno.")
        self.assertEqual(self.c.gestisci("basta calibrazione", 0.05)["risposta"], "Calibrazione fermata.")
        self.assertEqual(self.c.fase, "spento")
        self.assertEqual(self.pausa, {"attiva": False, "solo": []})


class TestCollaudoCompiti(BaseCollaudo):
    def rispondi(self, progetto, scelta):
        aperte = [s for s in domande.elenca() if s["progetto"] == progetto
                  and s["stato"] in ("ricevuta", "in-valutazione", "in-attesa")]
        self.assertTrue(aperte, progetto)
        posta.rispondi_domanda(aperte[-1]["id"], scelta, None, "utente", "opencode")

    def test_tre_compiti_e_rapporto(self):
        frase = self.c.avvia("collaudo")
        self.assertIn("collaudo", frase.lower())
        self.assertEqual(self.c.fase, "compiti")
        self.assertIn("Primo compito", self.detti[-1])
        self.assertEqual(self.c.stato_guida()["passo"], 1)
        self.c.gestisci("A", 0.05)
        self.rispondi("prova-ciro", "A")
        self.avanti(3)
        self.assertIn("Secondo compito", self.detti[-1])
        primo = self.c.compiti[0]["domanda"]
        domande.annota(primo, "utente", "correzione: B", correzione="B")
        self.avanti(3)
        self.assertIn("Terzo compito", self.detti[-1])
        self.avanti(1)
        self.rispondi("prova-due", "A")
        self.rispondi("prova-ciro", "B")
        self.avanti(3)
        self.assertEqual(self.c.fase, "fine")
        self.assertTrue(self.detti[-1].startswith("Collaudo finito"), self.detti[-1])
        self.assertIn("3 compiti su 3", self.detti[-1])
        self.assertEqual(self.pausa, {"attiva": False, "solo": []})
        self.assertIn("compito 1", self.rapporti()[0].read_text(encoding="utf-8"))
        self.assertEqual(domande.leggi(primo)["stato"], "risolta")

    def test_compito_scaduto(self):
        self.c.avvia("collaudo")
        self.avanti(91)
        self.assertIn("Secondo compito", self.detti[-1])
        self.assertFalse(self.c.compiti[0]["ok"])


class TestVoce(unittest.TestCase):
    def test_lettere_pronunciate(self):
        self.assertEqual(server.per_voce("A, procedi; B, fermati. Consiglia A."),
                         "a, procedi; bi, fermati. Consiglia a.")
        self.assertEqual(server.per_voce("Di': la B."), "Di': la bi.")
        self.assertEqual(server.per_voce("Mandato: A."), "Mandato: a.")
        # words and acronyms are not touched
        self.assertEqual(server.per_voce("API e CPU, Alice"), "API e CPU, Alice")


class TestTrascrizione(unittest.TestCase):
    def test_modello_per_durata(self):
        self.assertEqual(server.passate_whisper(1.5, rapido_esiste=True),
                         [("rapido", True), ("rapido", False)])
        self.assertEqual(server.passate_whisper(4.0, rapido_esiste=True), [("preciso", True)])
        self.assertEqual(server.passate_whisper(1.5, rapido_esiste=False), [("preciso", True)])

    def test_pulizia(self):
        self.assertEqual(server.pulisci_trascrizione("*Ahh*"), "Ahh")
        self.assertEqual(server.pulisci_trascrizione("[Musica]"), "")
        self.assertEqual(server.pulisci_trascrizione("B per prova (2)."), "B per prova .")

    def test_ahh_vale_a(self):
        self.assertEqual(modulo_cervello.LETTERE_SENTITE.get("ahh"), "a")


class TestCollaudoNelCervello(BaseCiro):
    def collega(self):
        server._cervello.collaudo = modulo_collaudo.Collaudo(
            dire=lambda frase, **extra: None, stato_pausa=server.stato_pausa,
            imposta_pausa=server.imposta_pausa, cartella=self.tmp / "collaudi",
            righe_registro=lambda dal: [])

    def test_calibrati_a_voce(self):
        self.collega()
        esito = server._cervello.chiedi("Ciro, calibrati")
        self.assertIn("silenzio", esito["risposta"].lower())
        self.assertEqual((esito["comando"], esito["secondi"]), ("misura-silenzio", 5))
        server._cervello.collaudo.silenzio(0.002, 0.003, 0.01)
        esito = server._cervello.chiedi("pausa progetti")   # not a command now
        self.assertNotIn("Progetti in pausa", esito["risposta"])
        self.assertEqual(self.chiamate_modello, [])

    def test_calibrati_scritto_attaccato(self):
        for detto in ("cirocalibrati.", "Ciro calibrati!", "calibrazione"):
            self.collega()
            esito = server._cervello.chiedi(detto)
            self.assertEqual(esito.get("comando"), "misura-silenzio", detto)
            server._cervello.collaudo.ferma()

    def test_collaudo_a_voce(self):
        self.collega()
        esito = server._cervello.chiedi("Ciro, collaudo")
        self.assertIn("collaudo", esito["risposta"].lower())
        self.assertNotIn("comando", esito)
        self.assertEqual(server._cervello.collaudo.fase, "compiti")

    def test_alias_imparato_usato_nelle_risposte(self):
        modulo_cervello.imposta("alias_lettere", {"vi": "b"})
        identificativo = self.chiedi()
        self.giro()
        self.assertTrue(server._cervello.chiedi("vi")["risposta"].startswith("Mandato"), server._cervello.chiedi("vi")["risposta"])
        self.assertEqual(domande.leggi(identificativo)["risposta"]["scelta"], "B")


if __name__ == "__main__":
    unittest.main()
