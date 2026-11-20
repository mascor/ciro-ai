#!/usr/bin/env python3
"""Automated calibration run, without a person at the microphone.

Each calibration phrase is spoken by Ciro's own voice (/api/parla), converted like the
page does (16 kHz mono), sent to /api/ascolta and then, as the page would, to
/api/cervello. Prints what was heard at each step and whether the calibration finished.

    python3 ciro/strumenti/prova_calibrazione.py [--url http://127.0.0.1:8765] [--tieni]

It changes the voice profile of the account it runs on (that is what a calibration does):
by default the settings file is restored at the end; --tieni keeps the new profile.
Use it on a test account, never on the real Ciro while you are using it.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

QUI = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(QUI))
import collaudo as modulo_collaudo  # noqa: E402
from testi import lingua  # noqa: E402

FFMPEG = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"
IMPOSTAZIONI = Path(os.environ.get("FACCIA_IMPOSTAZIONI") or Path.home() / ".config/faccia/impostazioni.json")
MAX_PASSI = 30


def chiama(url, percorso, corpo, tipo="application/json"):
    dati = corpo if isinstance(corpo, bytes) else json.dumps(corpo).encode("utf-8")
    richiesta = urllib.request.Request(url + percorso, data=dati, method="POST",
                                       headers={"Content-Type": tipo})
    with urllib.request.urlopen(richiesta, timeout=90) as risposta:
        contenuto = risposta.read()
    return contenuto if tipo != "application/json" or percorso == "/api/parla" else json.loads(contenuto)


def voce(url, frase, cartella):
    wav = chiama(url, "/api/parla", {"testo": frase})
    grezzo, pronto = cartella / "frase.wav", cartella / "frase-16k.wav"
    grezzo.write_bytes(wav)
    subprocess.run([FFMPEG, "-loglevel", "error", "-y", "-i", str(grezzo), "-ar", "16000", "-ac", "1",
                    str(pronto)], check=True)
    return pronto.read_bytes()


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    parser.add_argument("--tieni", action="store_true", help="keep the voice profile made by this run")
    a = parser.parse_args()
    frasi = modulo_collaudo.FRASI_EN if lingua() == "en" else modulo_collaudo.FRASI
    copia = IMPOSTAZIONI.read_bytes() if IMPOSTAZIONI.is_file() else None
    cartella = Path(tempfile.mkdtemp(prefix="prova-calibrazione-"))
    righe, finita, nome_ok = [], False, None
    try:
        print("avvia:", chiama(a.url, "/api/collaudo", {"azione": "avvia"}).get("risposta", "")[:80])
        risposta = chiama(a.url, "/api/collaudo", {"tipo": "silenzio", "medio": 0.0015, "p95": 0.003,
                                                    "massimo": 0.003}).get("risposta", "")
        indice = 0
        for passo in range(MAX_PASSI):
            if "finit" in risposta.lower() or "finished" in risposta.lower():
                finita = True
                break
            frase = frasi[min(indice, len(frasi) - 1)]
            sentito = chiama(a.url, "/api/ascolta", voce(a.url, frase, cartella), "audio/wav")
            sentito = json.loads(sentito) if isinstance(sentito, bytes) else sentito
            testo = sentito.get("resto") if sentito.get("chiamato") else sentito.get("testo")
            if frase in modulo_collaudo.NOME_DETTO and nome_ok is None:
                nome_ok = not sentito.get("chiamato")
            risposta = chiama(a.url, "/api/cervello", {"testo": testo or frase}).get("risposta", "") \
                if (testo or "").strip() else chiama(a.url, "/api/collaudo", {"azione": "ripeti"}).get("risposta", "")
            righe.append((passo + 1, frase, sentito.get("testo"), sentito.get("chiamato"), risposta))
            print("%2d  detto=%-30s sentito=%-32s chiamato=%-5s -> %s" % (
                passo + 1, frase, repr(sentito.get("testo")), sentito.get("chiamato"), risposta[:70]))
            if "ripeti" not in risposta.lower() and "repeat" not in risposta.lower():
                indice += 1
            time.sleep(0.3)
    finally:
        try:
            chiama(a.url, "/api/collaudo", {"azione": "chiudi"})
        except Exception:  # noqa: BLE001
            pass
        if not a.tieni and copia is not None:
            IMPOSTAZIONI.write_bytes(copia)
        shutil.rmtree(cartella, ignore_errors=True)
    print()
    print("calibrazione_finita: %s" % ("si" if finita else "no"))
    print("nome_in_calibrazione_non_chiamata: %s" % {True: "si", False: "no", None: "non provato"}[nome_ok])
    print("passi: %d" % len(righe))
    print("profilo: %s" % ("tenuto" if a.tieni else "ripristinato"))
    sys.exit(0 if finita and nome_ok else 1)


if __name__ == "__main__":
    main()
