"""No model at all (no DeepSeek key, opencode missing): Ciro says what is missing (issue #43).

Run from ciro/: python3 -m unittest tests.test_senza_modello
"""

import unittest
from unittest import mock

from tests.test_consumi import server  # noqa: F401  (sets FACCIA_CONTESTO before import)
import cervello


class TestSenzaModello(unittest.TestCase):
    def test_opencode_mancante_non_e_un_errore_del_server(self):
        with mock.patch.object(cervello, "_deepseek_diretto", return_value=None), \
             mock.patch.object(cervello.subprocess, "run", side_effect=FileNotFoundError("opencode")):
            uscita, errore, codice = cervello.chiedi_modello("ciao", 5)
        self.assertEqual((uscita, errore, codice), ("", cervello.SENZA_MODELLO, cervello.CODICE_SENZA_MODELLO))

    def test_opencode_senza_modello_collegato(self):
        errore = "\x1b[91m\x1b[1mError: \x1b[0mModel unavailable: deepseek/deepseek-flash"
        finto = mock.Mock(stdout="", stderr=errore, returncode=1)
        with mock.patch.object(cervello, "_deepseek_diretto", return_value=None), \
             mock.patch.object(cervello.subprocess, "run", return_value=finto):
            self.assertEqual(cervello.chiedi_modello("ciao", 5),
                             ("", cervello.SENZA_MODELLO, cervello.CODICE_SENZA_MODELLO))

    def test_altri_errori_senza_colori(self):
        finto = mock.Mock(stdout="", stderr="\x1b[91mError: \x1b[0mrate limit", returncode=1)
        with mock.patch.object(cervello, "_deepseek_diretto", return_value=None), \
             mock.patch.object(cervello.subprocess, "run", return_value=finto):
            self.assertEqual(cervello.chiedi_modello("ciao", 5), ("", "Error: rate limit", 1))

    def test_ciro_spiega_cosa_manca(self):
        c = cervello.Cervello()
        storico_prima = len(c.storico)
        with mock.patch.object(cervello, "chiedi_modello",
                               return_value=("", cervello.SENZA_MODELLO, cervello.CODICE_SENZA_MODELLO)):
            esito = c._rispondi("raccontami una barzelletta sui gatti")
        self.assertIn("ciro-deepseek", esito["risposta"])   # same in Italian and English
        self.assertIn("/connect", esito["risposta"])
        self.assertFalse(esito["mandato"])
        self.assertEqual(len(c.storico), storico_prima)   # the failed turn is not kept


if __name__ == "__main__":
    unittest.main()
