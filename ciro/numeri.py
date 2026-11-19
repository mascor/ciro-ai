"""Numbers of the open questions: «domanda tre» instead of a project name.

Whisper understands numbers far better than project names ("alpha" -> "alfa").
Every open question (structured question, mail asking for a decision, session
waiting for the user) gets the lowest free number from 1; the number stays the
same until the question is closed. A freed number rests for RIPOSO seconds before
another question can take it: «tre, sì» said just after question three closed must
not reach the next question (it would answer a question the user never heard).
Stored next to Ciro's context file, so it survives a restart.
"""

import json
import threading
import time
from pathlib import Path

RIPOSO = 5 * 60            # seconds a freed number is not given to another question
LIBERATI = "~liberati"     # key, in the file, of the recently freed numbers

PAROLE_IT = ["zero", "uno", "due", "tre", "quattro", "cinque", "sei", "sette", "otto", "nove", "dieci",
             "undici", "dodici", "tredici", "quattordici", "quindici", "sedici", "diciassette", "diciotto",
             "diciannove", "venti"]
PAROLE_EN = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
             "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen",
             "nineteen", "twenty"]
# how the user says a question number (Italian and English, words or digits)
DETTI = {parola: n for n, parola in enumerate(PAROLE_IT) if n}
DETTI.update({parola: n for n, parola in enumerate(PAROLE_EN) if n})
DETTI.update({"una": 1, "un": 1, "to": 2, "too": 2, "for": 4})
PRIMO_CHAT = 11   # numbers 1-10 stay for the sessions' questions
DETTI.update({str(n): n for n in range(1, 100)})


class Numeri:
    def __init__(self, percorso):
        self._percorso = percorso      # a function: the path can change (tests)
        self._lock = threading.Lock()

    def _file(self):
        return Path(self._percorso())

    def _leggi_tutto(self):
        """(open questions, recently freed numbers: str(number) -> entry with "t")."""
        try:
            dati = json.loads(self._file().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            dati = {}
        if not isinstance(dati, dict):
            dati = {}
        liberati = dati.pop(LIBERATI, None)
        adesso = time.time()
        liberati = {k: v for k, v in (liberati or {}).items()
                    if isinstance(v, dict) and adesso - float(v.get("t", 0)) < RIPOSO}
        return dati, liberati

    def _leggi(self):
        return self._leggi_tutto()[0]

    def _scrivi(self, dati, liberati=None):
        if liberati:
            dati = dict(dati, **{LIBERATI: liberati})
        try:
            self._file().write_text(json.dumps(dati, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass

    def numero(self, chiave, predefinite=None, **info):
        """The number of this question, assigning the lowest free one if it has none.
        `info` replaces the stored fields; `predefinite` fills only the missing ones."""
        with self._lock:
            dati, liberati = self._leggi_tutto()
            voce = dict(dati[chiave]) if chiave in dati else None   # copy: compared below
            if voce is None:
                # the same question back within the rest (a flicker of the list): same number
                tornata = next((k for k, v in liberati.items() if v.get("chiave") == chiave), None)
                if tornata is not None:
                    voce = {k: v for k, v in liberati.pop(tornata).items() if k not in ("t", "chiave")}
                else:
                    usati = {v.get("numero") for v in dati.values()} | {int(k) for k in liberati}
                    primo = PRIMO_CHAT if str(chiave).startswith("chat|") else 1
                    libero = next(n for n in range(primo, primo + len(usati) + 2) if n not in usati)
                    voce = {"numero": libero}
            voce.update({k: v for k, v in info.items() if v is not None})
            for k, v in (predefinite or {}).items():
                if v and not voce.get(k):
                    voce[k] = v
            if dati.get(chiave) != voce:
                dati[chiave] = voce
                self._scrivi(dati, liberati)
            return voce["numero"]

    def segna_detta(self, chiave):
        """Ciro has said this question aloud: an answer by its number can go to it."""
        with self._lock:
            dati, liberati = self._leggi_tutto()
            if chiave in dati and not dati[chiave].get("detta"):
                dati[chiave] = dict(dati[chiave], detta=True)
                self._scrivi(dati, liberati)

    def allinea(self, aperte):
        """Frees the numbers of the questions no longer open: they rest for RIPOSO seconds."""
        with self._lock:
            dati, liberati = self._leggi_tutto()
            tenuti = {k: v for k, v in dati.items() if k in aperte}
            if tenuti != dati:
                adesso = time.time()
                for chiave, voce in dati.items():
                    if chiave not in aperte:
                        liberati[str(voce.get("numero"))] = dict(voce, chiave=chiave, t=adesso)
                self._scrivi(tenuti, liberati)

    def chiusa(self, numero):
        """The question that had this number and closed less than RIPOSO seconds ago, or None."""
        voce = self._leggi_tutto()[1].get(str(numero))
        return dict(voce) if voce else None

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
