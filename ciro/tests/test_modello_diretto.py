"""Direct DeepSeek call with fallback to OpenCode. Run from ciro/: python3 -m unittest tests.test_modello_diretto

No network: urllib and the Keychain are replaced by fakes.
"""

import io
import json
import os
import unittest
from unittest import mock

from tests.test_consumi import server  # noqa: F401  (sets FACCIA_CONTESTO before import)
import cervello


class Risposta(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *argomenti):
        return False


class TestModelloDiretto(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": "chiave-finta-123",
                                                "CIRO_DEEPSEEK_DIRETTO": "1"})
        self.env.start()
        cervello._chiave_cache.update({"valore": None, "letta": 0})
        self.chiamate_opencode = []
        self.esegui_prima = cervello._esegui

        def finto_esegui(comando, timeout):
            self.chiamate_opencode.append(comando)
            return "da opencode", "", 0
        cervello._esegui = finto_esegui

    def tearDown(self):
        cervello._esegui = self.esegui_prima
        self.env.stop()

    def test_usa_deepseek_diretto(self):
        richieste = []

        def finto_urlopen(richiesta, timeout):
            richieste.append(richiesta)
            corpo = {"choices": [{"message": {"content": "Ciao dal diretto"}}]}
            return Risposta(json.dumps(corpo).encode())
        with mock.patch("urllib.request.urlopen", finto_urlopen):
            uscita, errore, codice = cervello.chiedi_modello("domanda", 30)
        self.assertEqual((uscita, codice), ("Ciao dal diretto", 0))
        self.assertEqual(self.chiamate_opencode, [])
        self.assertEqual(richieste[0].get_header("Authorization"), "Bearer chiave-finta-123")
        self.assertEqual(json.loads(richieste[0].data)["messages"][0]["content"], "domanda")

    def test_errore_torna_a_opencode_senza_chiave_nel_registro(self):
        registrate = []
        with mock.patch("urllib.request.urlopen", side_effect=OSError("rete giu chiave-finta-123")), \
                mock.patch.object(cervello, "registra", registrate.append):
            uscita, _, codice = cervello.chiedi_modello("domanda", 30)
        self.assertEqual((uscita, codice), ("da opencode", 0))
        self.assertEqual(len(self.chiamate_opencode), 1)
        self.assertNotIn("chiave-finta-123", json.dumps(registrate))

    def test_senza_chiave_usa_opencode(self):
        os.environ.pop("DEEPSEEK_API_KEY")
        with mock.patch("subprocess.run") as finto_run, mock.patch("urllib.request.urlopen") as rete:
            finto_run.return_value = mock.Mock(returncode=44, stdout="")
            uscita, _, _ = cervello.chiedi_modello("domanda", 30)
        self.assertEqual(uscita, "da opencode")
        rete.assert_not_called()

    def test_spento_con_variabile(self):
        os.environ["CIRO_DEEPSEEK_DIRETTO"] = "0"
        with mock.patch("urllib.request.urlopen") as rete:
            cervello.chiedi_modello("domanda", 30)
        rete.assert_not_called()
        self.assertEqual(len(self.chiamate_opencode), 1)


if __name__ == "__main__":
    unittest.main()
