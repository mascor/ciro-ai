"""Red events from the open Google Calendar tab (#70): colour, start from the label, the source.

Run from ciro/: python3 -m unittest tests.test_calendario_estensione
All names are fake; no network.
"""

import time
import unittest
from pathlib import Path

import calendario
from tests.test_coordinamento_ciro import BaseCiro, modulo_cervello, server


def etichetta(inizio, titolo="Call with Rossi"):
    mesi = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto",
            "settembre", "ottobre", "novembre", "dicembre"]
    t = time.localtime(inizio)
    return "%02d:%02d - %02d:%02d, %s, Mario Rossi, Accettato, Nessuna posizione, %d %s %d" % (
        t.tm_hour, t.tm_min, (t.tm_hour + 1) % 24, t.tm_min, titolo, t.tm_mday, mesi[t.tm_mon - 1], t.tm_year)


class TestEtichette(unittest.TestCase):
    def test_rosso(self):
        for css in ("rgb(213, 0, 0)", "rgba(213, 0, 0, 1)", "#d50000", "rgb(205, 5, 5)", "rgb(218, 82, 52)"):
            self.assertTrue(calendario.e_rosso(css), css)
        for css in ("", "rgb(3, 155, 229)", "rgb(230, 124, 115)", "transparent", "#7986cb",
                    "rgb(227, 104, 62)", "rgb(125, 58, 44)", "rgb(110, 114, 195)"):   # orange, faded, blue
            self.assertFalse(calendario.e_rosso(css), css)

    def test_inizio_italiano(self):
        inizio = calendario.inizio_da_etichetta("15:30 - 16:00, Call, 23 novembre 2026")
        self.assertEqual(time.localtime(inizio)[:5], (2026, 11, 23, 15, 30))

    def test_inizio_inglese(self):
        inizio = calendario.inizio_da_etichetta("3:30pm to 4pm, Call, Mario, November 23, 2026")
        self.assertEqual(time.localtime(inizio)[:5], (2026, 11, 23, 15, 30))
        inizio = calendario.inizio_da_etichetta("12am to 1am, Night, 5 December 2026")
        self.assertEqual(time.localtime(inizio)[:5], (2026, 12, 5, 0, 0))

    def test_dalle(self):
        inizio = calendario.inizio_da_etichetta("dalle 9 alle 10, Meet, 24 novembre 2026")
        self.assertEqual(time.localtime(inizio)[3:5], (9, 0))

    def test_senza_ora_o_data(self):
        self.assertIsNone(calendario.inizio_da_etichetta("Tutto il giorno, Ferie, 23 novembre 2026"))
        self.assertIsNone(calendario.inizio_da_etichetta("15:30 - 16:00, Call senza data"))
        self.assertIsNone(calendario.inizio_da_etichetta(""))

    def test_titolo(self):
        self.assertEqual(calendario.titolo_da_etichetta("15:30 - 16:00, Meet team, x"), "Meet team")
        self.assertEqual(calendario.titolo_da_etichetta("dalle 9 alle 10, Ottica, x"), "Ottica")
        self.assertEqual(calendario.titolo_da_etichetta("3pm to 4pm, Atlas, x"), "Atlas")


class TestFonte(unittest.TestCase):
    def test_solo_rossi_nella_finestra(self):
        adesso = time.time()
        fonte = calendario.FonteEstensione()
        conteggi = fonte.ricevi("work@example.com", [
            {"id": "a", "testo": etichetta(adesso + 600), "colore": "rgb(213, 0, 0)"},
            {"id": "b", "testo": etichetta(adesso + 900, "Blue"), "colore": "rgb(3, 155, 229)"},
            {"id": "c", "testo": "Tutto il giorno, Ferie, 1 gennaio 2027", "colore": "rgb(213, 0, 0)"},
            {"testo": "senza id"}], adesso)
        self.assertEqual({k: conteggi[k] for k in ("eventi", "rossi", "rossi_con_ora", "con_ora")},
                         {"eventi": 3, "rossi": 2, "rossi_con_ora": 1, "con_ora": 2})
        self.assertEqual(conteggi["colori"], {"rgb(213, 0, 0)": 2, "rgb(3, 155, 229)": 1})
        lettore = calendario.Lettore(fonte.scarica, fonte.account)
        eventi = lettore.leggi(adesso)
        self.assertEqual([(e["id"], e["titolo"]) for e in eventi], [("a", "Call with Rossi")])

    def test_scheda_ferma_e_lettura_fallita(self):
        fonte = calendario.FonteEstensione()
        fonte.ricevi("work@example.com", [], time.time() - 300)
        with self.assertRaises(TimeoutError):
            fonte.scarica("work@example.com", calendario.PAGINA, "", "")

    def test_account_dimenticato_dopo_un_giorno(self):
        fonte = calendario.FonteEstensione()
        fonte.ricevi("old@example.com", [], time.time() - 90000)
        fonte.ricevi("new@example.com", [])
        self.assertEqual(list(fonte.account()), ["new@example.com"])


class TestServer(BaseCiro):
    def setUp(self):
        super().setUp()
        vecchia = calendario.CONFIGURAZIONE
        calendario.CONFIGURAZIONE = Path(self.tmp) / "calendario.json"      # no OAuth accounts
        self.addCleanup(setattr, calendario, "CONFIGURAZIONE", vecchia)
        server._fonte_pagina = calendario.FonteEstensione()
        server._diagnosi_calendario.clear()
        server._calendario = calendario.Lettore(server._scarica_calendario, server._account_calendario)
        self.addCleanup(setattr, server, "_eventi_calendario", [])
        self.addCleanup(setattr, server, "_calendario_non_aggiornati", [])

    def test_dalla_scheda_al_pannello(self):
        adesso = time.time()
        server.ricevi_calendario({"account": "work@example.com", "eventi": [
            {"id": "a", "testo": etichetta(adesso + 1200), "colore": "rgb(213, 0, 0)"}]})
        server.giro_calendario()
        voci = [v for v in server.attese() if v.get("tipo") == "calendario"]
        self.assertEqual([(v["testo"], v["account"]) for v in voci], [("Call with Rossi", "work@example.com")])

    def test_registro_senza_titoli(self):
        server.ricevi_calendario({"account": "work@example.com", "eventi": [
            {"id": "a", "testo": etichetta(time.time() + 600, "Segreto"), "colore": "#d50000"}]})
        registro = modulo_cervello.REGISTRO.read_text(encoding="utf-8")
        self.assertIn("calendario-pagina", registro)                     # the counts are there
        self.assertNotIn("Segreto", registro)
        self.assertNotIn("work@example.com", registro)


if __name__ == "__main__":
    unittest.main()
