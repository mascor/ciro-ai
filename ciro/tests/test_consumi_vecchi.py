"""Old usage readings (issue #23): marked after 15 minutes, one voice reminder only.

Run from ciro/: python3 -m unittest tests.test_consumi_vecchi
"""

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

QUI = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(QUI))
_TEMP = tempfile.mkdtemp()
os.environ.setdefault("FACCIA_CONTESTO", os.path.join(_TEMP, "contesto.json"))

import server  # noqa: E402


def lettura(fonte, account, eta):
    return {"fonte": fonte, "account": account, "saldo": None, "nota": None,
            "voci": [{"nome": "5 ore", "percentuale": 40, "reset": ""}],
            "aggiornato": int(time.time()) - eta}


class TestConsumiVecchi(unittest.TestCase):
    def setUp(self):
        self.originali = (server.leggi_consumi, server.consumo_claude_code,
                          server.consumo_deepseek_api, server.NOMI_ACCOUNT, server._in_coda, server.registra)
        server.registra = lambda *a, **k: None   # never write to the real log
        server.NOMI_ACCOUNT = {}
        server.consumo_claude_code = lambda: None
        server.consumo_deepseek_api = lambda: None
        self.detti = []
        server._in_coda = self.detti.append
        server._consumi_ricordati.clear()

    def tearDown(self):
        (server.leggi_consumi, server.consumo_claude_code,
         server.consumo_deepseek_api, server.NOMI_ACCOUNT, server._in_coda, server.registra) = self.originali
        server._consumi_ricordati.clear()

    def metti(self, *letture):
        server.leggi_consumi = lambda: {l["fonte"] + "|" + l["account"]: l for l in letture}

    def test_vecchio_dopo_quindici_minuti(self):
        self.metti(lettura("claude.ai", "Ironworks", 14 * 60), lettura("opencode-go", "Contoso", 16 * 60))
        vecchi = {c["account"]: c["vecchio"] for c in server.consumi()}
        self.assertEqual(vecchi, {"Ironworks": False, "Contoso": True})

    def test_un_solo_promemoria_finche_non_torna_fresco(self):
        self.metti(lettura("claude.ai", "Ironworks", 20 * 60))
        server.giro_consumi()
        server.giro_consumi()
        self.assertEqual(len(self.detti), 1)
        self.assertIn("Claude Ironworks", self.detti[0]["testo"])
        self.assertIn("20 minuti", self.detti[0]["testo"])
        # fresh again, then old again: one new reminder
        self.metti(lettura("claude.ai", "Ironworks", 60))
        server.giro_consumi()
        self.metti(lettura("claude.ai", "Ironworks", 2 * 3600))
        server.giro_consumi()
        self.assertEqual(len(self.detti), 2)
        self.assertIn("2 ore", self.detti[1]["testo"])

    def test_niente_promemoria_per_claude_code_e_deepseek(self):
        self.metti()
        server.consumo_claude_code = lambda: lettura("claude-code", "Alice", 3600)
        server.consumo_deepseek_api = lambda: dict(lettura("deepseek", "API", 3600), voci=[], saldo="9 USD")
        elenco = server.consumi()
        self.assertTrue(all(c["vecchio"] for c in elenco))
        server.giro_consumi()
        self.assertEqual(self.detti, [])


if __name__ == "__main__":
    unittest.main()
