#!/usr/bin/env python3
"""Voice test bench: how well and how fast each whisper setting understands YOUR voice.

Uses the phrases recorded during «Ciro, calibrati» (~/.config/faccia/collaudi/audio,
labels in etichette.json) and compares whisper models and options.

    python3 strumenti/banco_voce.py                      # all models found
    python3 strumenti/banco_voce.py --modelli small      # only some

A phrase counts as understood when it matches the expected one, or when a single
letter is heard as one of its known aliases ("Ah" for A), like Ciro does.
"""

import argparse
import json
import statistics
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

AUDIO = Path.home() / ".config/faccia/collaudi/audio"
MODELLI = Path.home() / ".local/share/whisper-cpp"
VAD = MODELLI / "ggml-silero-v5.1.2.bin"
WHISPER = "/opt/homebrew/bin/whisper-cli"
CANDIDATI = {
    "large-v3-turbo": "ggml-large-v3-turbo-q5_0.bin",
    "medium": "ggml-medium-q5_0.bin",
    "small": "ggml-small-q5_1.bin",
    "base": "ggml-base-q5_1.bin",
}


def corrisponde(attesa, sentita, alias):
    from collaudo import normalizza
    a, s = normalizza(attesa), normalizza(sentita)
    if a == s:
        return True
    return len(a) == 1 and (alias.get(s) == a or (len(s) <= 3 and " " not in s and s.startswith(a)))


def trascrivi(modello, file):
    comando = [WHISPER, "-m", str(modello), "-l", "it", "-nt", "-np", "-f", str(file)]
    if VAD.is_file():
        comando[5:5] = ["--vad", "-vm", str(VAD), "-vspd", "80", "-vp", "200"]
    inizio = time.time()
    esito = subprocess.run(comando, capture_output=True, text=True, timeout=120)
    return time.time() - inizio, " ".join(esito.stdout.split())


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--modelli", nargs="*", default=list(CANDIDATI))
    args = parser.parse_args(argv)
    import cervello
    alias = dict(cervello.LETTERE_SENTITE)
    alias.update(cervello.leggi_impostazioni().get("alias_lettere") or {})
    etichette = json.loads((AUDIO / "etichette.json").read_text(encoding="utf-8"))
    righe = []
    for nome in args.modelli:
        modello = MODELLI / CANDIDATI[nome]
        if not modello.is_file():
            print("%-15s manca %s" % (nome, modello.name))
            continue
        tempi, giuste, dettagli = [], 0, []
        for file, attesa in sorted(etichette.items()):
            if not (AUDIO / file).is_file():
                continue
            secondi, sentita = trascrivi(modello, AUDIO / file)
            ok = corrisponde(attesa, sentita, alias)
            tempi.append(secondi)
            giuste += ok
            dettagli.append("    %-3s %-16s -> %r" % ("OK" if ok else "NO", attesa, sentita))
        righe.append((nome, giuste, len(tempi), statistics.median(tempi) if tempi else 0))
        print("%-15s %2d/%d capite, %.2f s a frase (mediana)" % righe[-1])
        print("\n".join(dettagli), flush=True)
    print("\nRIEPILOGO")
    for nome, giuste, totale, mediana in righe:
        print("  %-15s %2d/%d  %.2f s" % (nome, giuste, totale, mediana))
    return 0


if __name__ == "__main__":
    sys.exit(main())
