"""Calibration and acceptance test led by Ciro. Run from ciro/: python3 -m unittest tests.test_collaudo"""

import time
import unittest

from tests.test_coordinamento_ciro import BaseCiro, domande, modulo_cervello, posta, server

import collaudo as modulo_collaudo


class TestCollaudo(BaseCiro):
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

    def fino_ai_compiti(self):
        self.c.avvia()
        self.c.silenzio(0.002, 0.003, 0.01)
        for frase in modulo_collaudo.FRASI:
            self.c.gestisci(frase, 0.05)
        self.assertEqual(self.c.fase, "compiti")

    def rispondi(self, progetto, scelta):
        aperte = [s for s in domande.elenca("in-attesa") + domande.elenca("ricevuta")
                  + domande.elenca("in-valutazione") if s["progetto"] == progetto]
        self.assertTrue(aperte, progetto)
        posta.rispondi_domanda(aperte[-1]["id"], scelta, None, "utente", "opencode")

    def test_avvio_pausa_e_silenzio(self):
        frase = self.c.avvia()
        self.assertIn("silenzio", frase.lower())
        self.assertEqual(self.c.fase, "silenzio")
        self.assertEqual(self.pausa, {"attiva": True, "solo": ["prova-ciro", "prova-due"]})
        # words said during the silence measurement are not commands
        self.assertEqual(self.c.gestisci("pausa progetti", 0.05)["risposta"], "Aspetta, sto misurando il silenzio.")
        prossima = self.c.silenzio(0.002, 0.004, 0.01)
        self.assertEqual(prossima, "Ora ripeti dopo di me. A.")
        self.assertAlmostEqual(modulo_cervello.leggi_impostazioni()["soglia_microfono"], 0.01)

    def test_soglia_minima(self):
        self.c.avvia()
        self.c.silenzio(0.0005, 0.001, 0.002)
        self.assertAlmostEqual(modulo_cervello.leggi_impostazioni()["soglia_microfono"], 0.008)

    def test_frasi_giuste_e_sbagliate(self):
        self.c.avvia()
        self.c.silenzio(0.002, 0.003, 0.01)
        self.assertEqual(self.c.gestisci("A.", 0.05)["risposta"], "B.")
        # a mismatch is repeated once
        self.assertEqual(self.c.gestisci("allora", 0.05)["risposta"], "Non ho capito bene. Ripeti: B.")
        self.assertEqual(self.c.gestisci("Bi", 0.05)["risposta"], "Sì.")
        self.assertEqual(modulo_cervello.leggi_impostazioni()["alias_lettere"], {"bi": "b"})
        risultati = self.c.frasi_sentite
        self.assertEqual([(r["attesa"], r["ok"]) for r in risultati], [("A", True), ("B", True)])
        self.assertEqual(risultati[1]["tentativi"], ["allora", "Bi"])

    def test_frase_sbagliata_due_volte_si_va_avanti(self):
        self.c.avvia()
        self.c.silenzio(0.002, 0.003, 0.01)
        self.c.gestisci("casa", 0.05)
        self.assertEqual(self.c.gestisci("cosa", 0.05)["risposta"], "B.")
        self.assertFalse(self.c.frasi_sentite[0]["ok"])

    def test_equivalenze(self):
        self.c.avvia()
        self.c.silenzio(0.002, 0.003, 0.01)
        for detta in ("A", "b", "si", "No.", "Rispondi B.", "B per prova 2", "Pausa, progetti.",
                      "Come stanno le sessioni?"):
            self.c.gestisci(detta, 0.05)
        self.assertTrue(all(r["ok"] for r in self.c.frasi_sentite), self.c.frasi_sentite)

    def test_silenzio_dell_utente_ripete_poi_salta(self):
        self.c.avvia()
        self.c.silenzio(0.002, 0.003, 0.01)
        self.avanti(21)
        self.assertEqual(self.detti[-1], "Non ti ho sentito. Ripeti: A.")
        self.avanti(21)
        self.assertEqual(self.detti[-1], "B.")
        self.assertFalse(self.c.frasi_sentite[0]["ok"])

    def test_compiti_riusciti_e_rapporto(self):
        self.fino_ai_compiti()
        self.assertIn("Compito uno", self.detti[-1] if self.detti else "")
        # task 1: answer A
        self.c.gestisci("A", 0.05)
        self.rispondi("prova-ciro", "A")
        self.avanti(3)
        self.assertIn("Compito due", self.detti[-1])
        # task 2: correction B (Ciro writes it on the record)
        primo = self.c.compiti[0]["domanda"]
        domande.annota(primo, "utente", "correzione: B", correzione="B")
        self.avanti(3)
        self.assertIn("Compito tre", self.detti[-1])
        # task 3: two questions
        self.avanti(1)
        self.rispondi("prova-due", "A")
        self.rispondi("prova-ciro", "B")
        self.avanti(3)
        self.assertEqual(self.c.fase, "spento")
        self.assertTrue(self.detti[-1].startswith("Calibrazione finita"), self.detti[-1])
        self.assertIn("8 frasi su 8", self.detti[-1])
        self.assertIn("3 compiti su 3", self.detti[-1])
        self.assertEqual(self.pausa, {"attiva": False, "solo": []})  # previous state back
        rapporti = list((self.tmp / "collaudi").glob("collaudo-*.txt"))
        self.assertEqual(len(rapporti), 1)
        testo = rapporti[0].read_text(encoding="utf-8")
        self.assertIn("Rumore", testo)
        self.assertIn("compito 1", testo)
        # the test sessions closed their questions like real ones
        self.assertEqual(domande.leggi(primo)["stato"], "risolta")

    def test_compito_scaduto(self):
        self.fino_ai_compiti()
        self.avanti(91)
        self.assertIn("Compito due", self.detti[-1])
        self.assertFalse(self.c.compiti[0]["ok"])

    def test_ferma(self):
        self.c.avvia()
        esito = self.c.gestisci("basta calibrazione", 0.05)
        self.assertEqual(esito["risposta"], "Calibrazione fermata.")
        self.assertEqual(self.c.fase, "spento")
        self.assertEqual(self.pausa, {"attiva": False, "solo": []})


class TestCollaudoNelCervello(BaseCiro):
    def test_avvio_a_voce_e_frasi_non_sono_comandi(self):
        detti = []
        server._cervello.collaudo = modulo_collaudo.Collaudo(
            dire=lambda frase, **extra: detti.append(frase), stato_pausa=server.stato_pausa,
            imposta_pausa=server.imposta_pausa, cartella=self.tmp / "collaudi",
            righe_registro=lambda dal: [])
        esito = server._cervello.chiedi("Ciro, calibrati")
        self.assertIn("silenzio", esito["risposta"].lower())
        self.assertEqual(esito["comando"], "misura-silenzio")
        self.assertEqual(esito["secondi"], 10)
        server._cervello.collaudo.silenzio(0.002, 0.003, 0.01)
        esito = server._cervello.chiedi("pausa progetti")   # phrase 7 would be a command: not now
        self.assertNotIn("Progetti in pausa", esito["risposta"])
        self.assertEqual(self.chiamate_modello, [])

    def test_alias_imparato_usato_nelle_risposte(self):
        modulo_cervello.imposta("alias_lettere", {"vi": "b"})
        identificativo = self.chiedi()
        self.giro()
        self.assertEqual(server._cervello.chiedi("vi")["risposta"], "Mandato.")
        self.assertEqual(domande.leggi(identificativo)["risposta"]["scelta"], "B")


if __name__ == "__main__":
    unittest.main()
