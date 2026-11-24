"""whisper with the model kept loaded (#77): one local `whisper-server` per model.

whisper-cli loads the model on every phrase; with the model already loaded a short answer takes
0.09 s instead of 0.24 s and a phrase for the large model 1.13 s instead of 1.51 s (Mac mini M4,
measured 24/11/2026). Each server listens only on 127.0.0.1, with the VAD options Ciro uses.
Anything that goes wrong (not started, busy, error, timeout) returns None: the caller uses
whisper-cli as before, and the server is started again in the background.
"""

import json
import os
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

PROGRAMMA = os.environ.get("CIRO_WHISPER_SERVER", "/opt/homebrew/bin/whisper-server")
SEGNO = "/ciro-inference"            # inference path: marks the servers started by Ciro
ATTESA_AVVIO = 60                    # seconds to load a model
ATTESA_RISPOSTA = {"rapido": 5, "preciso": 20}


def porta_libera():
    with socket.socket() as prova:
        prova.bind(("127.0.0.1", 0))
        return prova.getsockname()[1]


def corpo_multiparte(campi, nome_file, dati):
    confine = uuid.uuid4().hex
    parti = []
    for nome, valore in campi.items():
        parti.append(('--%s\r\nContent-Disposition: form-data; name="%s"\r\n\r\n%s\r\n'
                      % (confine, nome, valore)).encode())
    parti.append(('--%s\r\nContent-Disposition: form-data; name="file"; filename="%s"\r\n'
                  "Content-Type: audio/wav\r\n\r\n" % (confine, nome_file)).encode() + dati + b"\r\n")
    parti.append(("--%s--\r\n" % confine).encode())
    return b"".join(parti), "multipart/form-data; boundary=" + confine


class ServerWhisper:
    """One model kept loaded. `trascrivi` -> text, or None (use whisper-cli)."""

    def __init__(self, tipo, modello, lingua, vad, registra=lambda *a, **k: None, programma=None):
        self.tipo, self.modello, self.lingua, self.vad = tipo, Path(modello), lingua, list(vad)
        self.registra, self.programma = registra, programma or PROGRAMMA
        self.processo, self.porta, self.pronto = None, None, False
        self._lock = threading.Lock()
        self._in_avvio = False

    def comando(self, porta):
        return [self.programma, "-m", str(self.modello), "-l", self.lingua(), "-nt",
                "--host", "127.0.0.1", "--port", str(porta), "--inference-path", SEGNO, *self.vad]

    def avvia(self):
        """Starts the server and waits until it answers (call it from a background thread)."""
        with self._lock:
            if self._in_avvio or (self.processo and self.processo.poll() is None and self.pronto):
                return self.pronto
            self._in_avvio = True
        try:
            if not (Path(self.programma).is_file() and self.modello.is_file()):
                return False
            self.ferma()
            porta = porta_libera()
            processo = subprocess.Popen(self.comando(porta), stdout=subprocess.DEVNULL,
                                        stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
            scadenza = time.time() + ATTESA_AVVIO
            while time.time() < scadenza and processo.poll() is None:
                try:
                    urllib.request.urlopen("http://127.0.0.1:%d/" % porta, timeout=1).close()
                    break
                except urllib.error.HTTPError:
                    break                      # it answers: the model is loaded
                except OSError:
                    time.sleep(0.3)
            if processo.poll() is not None or time.time() >= scadenza:
                processo.kill()
                self.registra("whisper-server-fallito", modello=self.tipo)
                return False
            self.processo, self.porta, self.pronto = processo, porta, True
            self.registra("whisper-server-pronto", modello=self.tipo, porta=porta)
            return True
        finally:
            self._in_avvio = False

    def riavvia_dopo(self):
        self.pronto = False
        threading.Thread(target=self.avvia, daemon=True).start()

    def ferma(self):
        processo, self.processo, self.pronto = self.processo, None, False
        if processo and processo.poll() is None:
            processo.terminate()
            try:
                processo.wait(timeout=5)
            except subprocess.TimeoutExpired:
                processo.kill()

    def trascrivi(self, percorso_audio):
        if not self.pronto or not self.processo or self.processo.poll() is not None:
            if self.processo is not None:     # it was running and stopped: start it again
                self.riavvia_dopo()
            return None
        try:
            dati = Path(percorso_audio).read_bytes()
            corpo, tipo = corpo_multiparte({"response_format": "json", "language": self.lingua()},
                                           Path(percorso_audio).name, dati)
            richiesta = urllib.request.Request("http://127.0.0.1:%d%s" % (self.porta, SEGNO), data=corpo,
                                               method="POST", headers={"Content-Type": tipo})
            with urllib.request.urlopen(richiesta, timeout=ATTESA_RISPOSTA.get(self.tipo, 20)) as risposta:
                testo = json.loads(risposta.read() or b"{}").get("text")
            return testo if isinstance(testo, str) else None
        except (OSError, ValueError) as errore:
            self.registra("whisper-server-errore", modello=self.tipo, errore=repr(errore)[:160])
            self.ferma()
            self.riavvia_dopo()
            return None


def ferma_vecchi():
    """Servers left by a previous Ciro (killed without cleaning up): recognised by SEGNO."""
    subprocess.run(["pkill", "-f", "whisper-server.*" + SEGNO], capture_output=True)
