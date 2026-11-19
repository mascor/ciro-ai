"""Tests for the "Quanto ti resta" panel data. Run from faccia/: python3 -m unittest tests.test_consumi"""

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

QUI = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(QUI))
_TEMP = tempfile.mkdtemp()
os.environ["FACCIA_CONTESTO"] = os.path.join(_TEMP, "contesto.json")

import server  # noqa: E402


def voci(cinque, settimana, reset_cinque="", reset_settimana=""):
    return [{"nome": "5 ore", "percentuale": cinque, "reset": reset_cinque},
            {"nome": "Settimana", "percentuale": settimana, "reset": reset_settimana}]


class TestConsumi(unittest.TestCase):
    def setUp(self):
        self.originali = (server.leggi_consumi, server.consumo_claude_code,
                          server.consumo_deepseek_api, server.NOMI_ACCOUNT)
        server.NOMI_ACCOUNT = {"me@example.com": "Ironworks"}
        server.consumo_deepseek_api = lambda: None
        self.adesso = int(time.time())

    def tearDown(self):
        (server.leggi_consumi, server.consumo_claude_code,
         server.consumo_deepseek_api, server.NOMI_ACCOUNT) = self.originali

    def test_organizzazione_personale_un_solo_blocco(self):
        # same account: the Chrome extension calls it by the email, Claude Code
        # by "<email>'s Organization"
        vecchio = {"fonte": "claude.ai", "account": "me@example.com",
                   "voci": voci(0, 23), "saldo": None, "nota": None,
                   "aggiornato": self.adesso - 16 * 3600}
        nuovo = {"fonte": "claude-code", "account": "me@example.com's Organization",
                 "voci": voci(13, 35), "saldo": None, "nota": None,
                 "aggiornato": self.adesso}
        server.leggi_consumi = lambda: {"claude.ai|me@example.com": vecchio}
        server.consumo_claude_code = lambda: nuovo
        elenco = server.consumi()
        self.assertEqual(len(elenco), 1)
        self.assertEqual(elenco[0]["account"], "Ironworks")
        self.assertEqual([v["percentuale"] for v in elenco[0]["voci"]], [13, 35])

    def test_reset_passato_azzera(self):
        passato = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(self.adesso - 3600))
        futuro = str(self.adesso + 3600)
        vecchio = {"fonte": "claude.ai", "account": "Meridian",
                   "voci": voci(92, 60, passato, futuro), "saldo": None, "nota": None,
                   "aggiornato": self.adesso - 16 * 3600}
        server.leggi_consumi = lambda: {"claude.ai|Meridian": vecchio}
        server.consumo_claude_code = lambda: None
        elenco = server.consumi()
        self.assertEqual([v["percentuale"] for v in elenco[0]["voci"]], [0.0, 60])
        self.assertEqual(elenco[0]["voci"][0]["reset"], "")
        # the stored data is not changed
        self.assertEqual(vecchio["voci"][0]["percentuale"], 92)

    def test_account_diversi_restano_separati(self):
        server.leggi_consumi = lambda: {
            "claude.ai|Meridian": {"fonte": "claude.ai", "account": "Meridian", "voci": [],
                                   "aggiornato": self.adesso},
            "claude.ai|team@example.org": {"fonte": "claude.ai", "account": "team@example.org",
                                              "voci": [], "aggiornato": self.adesso},
        }
        server.consumo_claude_code = lambda: None
        self.assertEqual(len(server.consumi()), 2)


if __name__ == "__main__":
    unittest.main()
