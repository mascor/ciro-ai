"""Le frasi lunghe le trascrive Hex, l'audio breve resta a whisper.

Misurato il 20/11/2026 sull'audio vero del banco di prova: parakeet_v3 di Hex
capisce come whisper (20/27 frasi esatte tutti e due) ma su una frase di cinque
secondi impiega 0,15 s invece di 1,9 s. Su lettere e «sì/no» invece Hex sbaglia,
quindi sotto i 3,5 s resta whisper.

Run from ciro/: python3 -m unittest tests.test_hex
"""

import io
import json
import subprocess
import unittest
import wave
from unittest import mock

from tests.test_coordinamento_ciro import server


def wav_di(secondi):
    dati = io.BytesIO()
    with wave.open(dati, "wb") as file_wav:
        file_wav.setnchannels(1)
        file_wav.setsampwidth(2)
        file_wav.setframerate(16000)
        file_wav.writeframes(b"\x00\x00" * int(16000 * secondi))
    return dati.getvalue()


def esito(uscita="", codice=0, errore=""):
    return subprocess.CompletedProcess([], codice, uscita, errore)


class TestHex(unittest.TestCase):
    def test_legge_il_testo(self):
        risposta = json.dumps({"version": 4, "status": "transcript", "text": "Come stanno le sessioni?"})
        with mock.patch.object(server, "HEX", "/finto/hex"), \
                mock.patch.object(server.subprocess, "run", return_value=esito(risposta)):
            self.assertEqual(server.trascrivi_hex("voce.wav"), "Come stanno le sessioni?")

    def test_laboratorio_spento_ricade_su_whisper(self):
        risposta = json.dumps({"version": 4, "status": "error", "code": "disabled",
                               "message": "Labs › Transcribe files is off"})
        with mock.patch.object(server, "HEX", "/finto/hex"), \
                mock.patch.object(server.subprocess, "run", return_value=esito(risposta, 1, risposta)):
            self.assertIsNone(server.trascrivi_hex("voce.wav"))

    def test_hex_che_non_parte_non_rompe(self):
        with mock.patch.object(server, "HEX", "/finto/hex"), \
                mock.patch.object(server.subprocess, "run", side_effect=FileNotFoundError("hex")):
            self.assertIsNone(server.trascrivi_hex("voce.wav"))

    def test_senza_hex_resta_whisper(self):
        with mock.patch.object(server, "HEX", ""):
            self.assertIsNone(server.trascrivi_hex("voce.wav"))

    def test_frase_lunga_a_hex_breve_a_whisper(self):
        chiamate = []

        def finto_hex(percorso):
            chiamate.append(("hex", percorso))
            return "la sessione ha finito il lavoro sul gantt"

        def finto_whisper(percorso, durata, grande=False):
            chiamate.append(("whisper", durata))
            return "bi"

        with mock.patch.object(server, "trascrivi_hex", finto_hex), \
                mock.patch.object(server, "trascrivi_whisper", finto_whisper), \
                mock.patch.object(server, "MODELLO_WHISPER", server.MODELLO_WHISPER):
            self.assertEqual(server.trascrivi(wav_di(5)),
                             "la sessione ha finito il lavoro sul gantt")
            self.assertEqual(server.trascrivi(wav_di(1.5)), "bi")
        self.assertEqual([c[0] for c in chiamate], ["hex", "whisper"])

    def test_hex_vuoto_ricade_su_whisper(self):
        with mock.patch.object(server, "trascrivi_hex", lambda percorso: None), \
                mock.patch.object(server, "trascrivi_whisper", lambda p, d, grande=False: "testo"):
            self.assertEqual(server.trascrivi(wav_di(5)), "testo")


if __name__ == "__main__":
    unittest.main()
