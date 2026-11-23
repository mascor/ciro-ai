"""Chrome extension version and origin checks (issue #56).
Run from ciro/: python3 -m unittest tests.test_estensione"""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

QUI = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(QUI))

import server  # noqa: E402


class TestVersioneEstensione(unittest.TestCase):
    def setUp(self):
        self.originale = server.CARTELLA
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "estensione-chrome").mkdir()
        server.CARTELLA = self.tmp

    def tearDown(self):
        server.CARTELLA = self.originale

    def scrivi(self, testo):
        (self.tmp / "estensione-chrome" / "manifest.json").write_text(testo, encoding="utf-8")

    def test_legge_la_versione_dal_disco(self):
        self.scrivi(json.dumps({"version": "2.3"}))
        self.assertEqual(server.versione_estensione(), "2.3")

    def test_manifest_assente_rotto_o_strano(self):
        self.assertIsNone(server.versione_estensione())
        self.scrivi("{ non json")
        self.assertIsNone(server.versione_estensione())
        self.scrivi(json.dumps({"version": "1.8; rm -rf"}))
        self.assertIsNone(server.versione_estensione())

    def test_versione_vera_del_repository(self):
        server.CARTELLA = self.originale
        manifest = json.loads((self.originale / "estensione-chrome" / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(server.versione_estensione(), manifest["version"])


class TestProvenienza(unittest.TestCase):
    def ok(self, percorso, origine):
        finto = SimpleNamespace(headers={"Host": "127.0.0.1:8765", "Origin": origine})
        return server.Gestore._provenienza_ok(finto, percorso)

    def test_estensione_puo_chiedere_la_versione(self):
        self.assertTrue(self.ok("/api/estensione", "chrome-extension://abcdef"))
        self.assertTrue(self.ok("/api/consumi", "chrome-extension://abcdef"))

    def test_estensione_non_puo_altro(self):
        self.assertFalse(self.ok("/api/quadro", "chrome-extension://abcdef"))

    def test_altri_siti_rifiutati(self):
        self.assertFalse(self.ok("/api/estensione", "https://example.com"))


if __name__ == "__main__":
    unittest.main()
