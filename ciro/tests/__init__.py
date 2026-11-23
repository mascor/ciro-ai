"""Tests never touch the user's real files (issue #41).

This package runs before any test module imports server.py or cervello.py, so every
path built from Path.home() at import time points to a temporary home: settings,
context, conversation log, mailbox, mute file, usage readings... The read-only models
(Kokoro voice, whisper, hex) are linked into the temporary home so the tests that use
them keep working.
"""

import atexit
import os
import shutil
import tempfile
from pathlib import Path

_REALE = Path.home()
_FINTA = Path(tempfile.mkdtemp(prefix="ciro-test-home-"))
atexit.register(shutil.rmtree, _FINTA, True)

# models and tools only read by the code: linked, never copied or written
for relativo in (".local/share/kokoro", ".local/share/whisper-cpp", ".local/bin/hex"):
    sorgente = _REALE / relativo
    if sorgente.exists():
        destinazione = _FINTA / relativo
        destinazione.parent.mkdir(parents=True, exist_ok=True)
        destinazione.symlink_to(sorgente)

(_FINTA / ".config/faccia").mkdir(parents=True, exist_ok=True)
os.environ["HOME"] = str(_FINTA)
# the paths that can also come from the environment: inside the temporary home too
os.environ["FACCIA_IMPOSTAZIONI"] = str(_FINTA / ".config/faccia/impostazioni.json")
os.environ["FACCIA_CONTESTO"] = str(_FINTA / ".config/faccia/contesto.json")
os.environ["POSTA_RADICE"] = str(_FINTA / ".posta-agenti")
os.environ["CIRO_REGISTRO"] = str(_FINTA / ".config/faccia/conversazioni.log")
os.environ.pop("CIRO_LINGUA", None)   # Italian unless a test sets the language itself

assert Path.home() == _FINTA, "tests must not run with the real home"
