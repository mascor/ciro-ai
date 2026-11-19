"""Numbers of the open questions: «domanda tre» instead of a project name.

Whisper understands numbers far better than project names ("alpha" -> "alfa").
Every open question (structured question, mail asking for a decision, session
waiting for the user) gets the lowest free number from 1; the number stays the
same until the question is closed, then it is free again. Stored next to Ciro's
context file, so it survives a restart.
"""

import json
import threading
from pathlib import Path

PAROLE_IT = ["zero", "uno", "due", "tre", "quattro", "cinque", "sei", "sette", "otto", "nove", "dieci"]
PAROLE_EN = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"]
# how the user says a question number (Italian and English, words or digits)
DETTI = {parola: n for n, parola in enumerate(PAROLE_IT) if n}
DETTI.update({parola: n for n, parola in enumerate(PAROLE_EN) if n})
DETTI.update({"una": 1, "un": 1, "to": 2, "too": 2, "for": 4})
DETTI.update({str(n): n for n in range(1, 100)})


class Numeri:
    def __init__(self, percorso):
        self._percorso = percorso      # a function: the path can change (tests)
        self._lock = threading.Lock()

    def _file(self):
        return Path(self._percorso())

    def _leggi(self):
        try:
            dati = json.loads(self._file().read_text(encoding="utf-8"))
            return dati if isinstance(dati, dict) else {}
        except (OSError, ValueError):
            return {}

    def _scrivi(self, dati):
        try:
            self._file().write_text(json.dumps(dati, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass

    def numero(self, chiave, predefinite=None, **info):
        """The number of this question, assigning the lowest free one if it has none.
        `info` replaces the stored fields; `predefinite` fills only the missing ones."""
        with self._lock:
            dati = self._leggi()
            voce = dict(dati[chiave]) if chiave in dati else None   # copy: compared below
            if voce is None:
                usati = {v.get("numero") for v in dati.values()}
                libero = next(n for n in range(1, len(usati) + 2) if n not in usati)
                voce = {"numero": libero}
            voce.update({k: v for k, v in info.items() if v is not None})
            for k, v in (predefinite or {}).items():
                if v and not voce.get(k):
                    voce[k] = v
            if dati.get(chiave) != voce:
                dati[chiave] = voce
                self._scrivi(dati)
            return voce["numero"]

    def allinea(self, aperte):
        """Frees the numbers of the questions no longer open."""
        with self._lock:
            dati = self._leggi()
            tenuti = {k: v for k, v in dati.items() if k in aperte}
            if tenuti != dati:
                self._scrivi(tenuti)

    def cerca(self, numero):
        for chiave, voce in self._leggi().items():
            if voce.get("numero") == numero:
                return dict(voce, chiave=chiave)
        return None

    def elenco(self):
        return sorted((dict(v, chiave=k) for k, v in self._leggi().items()), key=lambda v: v["numero"])


def parola(numero, lingua="it"):
    parole = PAROLE_EN if lingua == "en" else PAROLE_IT
    return parole[numero] if 0 < numero < len(parole) else str(numero)
