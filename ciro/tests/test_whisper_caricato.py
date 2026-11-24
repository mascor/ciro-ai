"""whisper with the model kept loaded (#77): answer, timeout, error -> whisper-cli as before.

Run from ciro/: python3 -m unittest tests.test_whisper_caricato
A fake whisper-server on 127.0.0.1; no real model is loaded.
"""

import json
import subprocess
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

import whisper_caricato
from tests.test_coordinamento_ciro import server


class Finto(BaseHTTPRequestHandler):
    modo = "ok"
    ricevute = []

    def do_POST(self):
        corpo = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        Finto.ricevute.append((self.path, corpo))
        if Finto.modo == "lento":
            time.sleep(2)
        if Finto.modo == "errore":
            self.send_response(500)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"text": " Sì!\n"}).encode())

    def log_message(self, *argomenti):
        pass


class ProcessoVivo:
    def poll(self):
        return None

    def terminate(self):
        pass

    def wait(self, timeout=None):
        return 0


def esito(uscita="", codice=0):
    return subprocess.CompletedProcess([], codice, uscita, "")


class TestWhisperCaricato(unittest.TestCase):
    def setUp(self):
        Finto.modo, Finto.ricevute = "ok", []
        self.http = ThreadingHTTPServer(("127.0.0.1", 0), Finto)
        threading.Thread(target=self.http.serve_forever, daemon=True).start()
        self.addCleanup(self.http.server_close)
        self.addCleanup(self.http.shutdown)
        self.audio = Path(tempfile.mkdtemp()) / "voce.wav"
        self.audio.write_bytes(b"RIFF....WAVE")
        self.riavvii = []
        self.caricato = whisper_caricato.ServerWhisper("rapido", "/finto/base.bin", lambda: "it", ["--vad"])
        self.caricato.processo, self.caricato.porta, self.caricato.pronto = \
            ProcessoVivo(), self.http.server_address[1], True
        self.caricato.riavvia_dopo = lambda: self.riavvii.append(1)
        # the server module: this model is the loaded one, VAD available
        self.addCleanup(server._whisper_caricati.clear)
        server._whisper_caricati[str(server.modello_rapido())] = self.caricato
        patch_vad = mock.patch.object(server, "opzioni_vad", return_value=["--vad", "-vm", "silero.bin"])
        patch_vad.start()
        self.addCleanup(patch_vad.stop)

    def test_risposta_dal_modello_caricato(self):
        self.assertEqual(self.caricato.trascrivi(self.audio), " Sì!\n")
        percorso, corpo = Finto.ricevute[0]
        self.assertEqual(percorso, whisper_caricato.SEGNO)
        self.assertIn(b'name="language"\r\n\r\nit', corpo)
        self.assertIn(b"RIFF....WAVE", corpo)
        with mock.patch.object(server.subprocess, "run", side_effect=AssertionError("whisper-cli called")):
            self.assertEqual(server.trascrivi_whisper(self.audio, 1.0), "Sì!")

    def test_errore_ricade_su_whisper_cli(self):
        Finto.modo = "errore"
        with mock.patch.object(server.subprocess, "run", return_value=esito(" no\n")) as cli:
            self.assertEqual(server.trascrivi_whisper(self.audio, 1.0), "no")
        self.assertEqual(cli.call_args[0][0][0], server.WHISPER)
        self.assertEqual(self.riavvii, [1])          # started again in the background
        self.assertFalse(self.caricato.pronto)

    def test_tempo_scaduto_ricade_su_whisper_cli(self):
        Finto.modo = "lento"
        with mock.patch.dict(whisper_caricato.ATTESA_RISPOSTA, {"rapido": 0.3}):
            self.assertIsNone(self.caricato.trascrivi(self.audio))
        self.assertEqual(self.riavvii, [1])

    def test_mai_avviato_non_riparte(self):
        mai = whisper_caricato.ServerWhisper("rapido", "/finto/base.bin", lambda: "it", [])
        mai.riavvia_dopo = lambda: self.riavvii.append(1)
        self.assertIsNone(mai.trascrivi(self.audio))
        self.assertEqual(self.riavvii, [])

    def test_passata_senza_vad_resta_a_whisper_cli(self):
        # a very short «A» dropped by the VAD: the second pass, without VAD, is whisper-cli
        with mock.patch.object(self.caricato, "trascrivi", return_value="") as dal_server, \
                mock.patch.object(server.subprocess, "run", return_value=esito(" A\n")) as cli:
            self.assertEqual(server.trascrivi_whisper(self.audio, 1.0), "A")
        self.assertEqual(dal_server.call_count, 1)
        self.assertNotIn("--vad", cli.call_args[0][0])

    def test_senza_programma_o_modello_non_parte(self):
        nuovo = whisper_caricato.ServerWhisper("rapido", "/finto/base.bin", lambda: "it", [],
                                               programma="/finto/whisper-server")
        self.assertFalse(nuovo.avvia())
        self.assertIsNone(nuovo.processo)


if __name__ == "__main__":
    unittest.main()
