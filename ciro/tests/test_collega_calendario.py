"""Linking a Google account to the calendar alerts (#30): consent URL and local config, no network.

Run from ciro/: python3 -m unittest tests.test_collega_calendario
"""

import json
import tempfile
import unittest
import urllib.parse
from pathlib import Path

from strumenti import collega_calendario as collega


class TestCollega(unittest.TestCase):
    def test_nome_breve(self):
        self.assertTrue(collega.nome_valido("lavoro"))
        self.assertTrue(collega.nome_valido("casa-2"))
        for nome in ("", "Lavoro", "a b", "x@y.it", "a" * 31, "../x"):
            self.assertFalse(collega.nome_valido(nome), nome)

    def test_indirizzo_solo_lettura_con_pkce(self):
        indirizzo = collega.indirizzo_consenso("id-finto", 54321, "v" * 64, "st", "work@example.com")
        domanda = urllib.parse.parse_qs(urllib.parse.urlparse(indirizzo).query)
        self.assertEqual(domanda["scope"], ["https://www.googleapis.com/auth/calendar.readonly"])
        self.assertEqual(domanda["redirect_uri"], ["http://127.0.0.1:54321/"])
        self.assertEqual(domanda["code_challenge_method"], ["S256"])
        self.assertEqual(domanda["access_type"], ["offline"])
        self.assertEqual(domanda["login_hint"], ["work@example.com"])
        self.assertEqual(domanda["state"], ["st"])

    def test_aggiungi_account_tiene_gli_altri(self):
        with tempfile.TemporaryDirectory() as cartella:
            percorso = Path(cartella) / "ciro" / "calendario.json"
            collega.aggiungi_account("lavoro", percorso)
            dati = collega.aggiungi_account("personale", percorso)
            self.assertEqual(dati, {"lavoro": {"calendari": ["primary"]}, "personale": {"calendari": ["primary"]}})
            percorso.write_text(json.dumps({"lavoro": {"calendari": ["primary", "team@group"]}}))
            dati = collega.aggiungi_account("lavoro", percorso)       # linked again: choices kept
            self.assertEqual(dati["lavoro"]["calendari"], ["primary", "team@group"])

    def test_senza_client_spiega(self):
        vecchio = collega.calendario.CLIENT
        collega.calendario.CLIENT = Path("/inesistente/calendario-client.json")
        try:
            self.assertEqual(collega.main(["lavoro"]), 1)
            self.assertEqual(collega.main(["Non Valido"]), 2)
        finally:
            collega.calendario.CLIENT = vecchio


if __name__ == "__main__":
    unittest.main()
