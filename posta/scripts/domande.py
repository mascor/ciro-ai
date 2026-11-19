#!/usr/bin/env python3
"""Records of the structured questions asked by the sessions.

One JSON file per question in <root>/domande/<ID>.json, where <root> is
POSTA_RADICE or ~/.posta-agenti. Every change happens under a per-record
lock (fcntl) and is written atomically. Standard library only, Python 3.9.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

STATI = (
    "ricevuta",
    "in-valutazione",
    "in-attesa",
    "risposta-consegnata",
    "recepita",
    "risolta",
    "annullata",
)

# Allowed transitions (design §2). in-valutazione -> ricevuta is used only to
# release a record stuck after a restart (sblocca_ferme).
PASSAGGI = {
    "ricevuta": {"in-valutazione", "risposta-consegnata", "annullata"},
    "in-valutazione": {"in-attesa", "risposta-consegnata", "ricevuta", "annullata"},
    "in-attesa": {"risposta-consegnata", "annullata"},
    "risposta-consegnata": {"recepita", "annullata"},
    "recepita": {"risolta"},
    "risolta": set(),
    "annullata": set(),
}

ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,200}$")

# Replaceable clock (seconds since the epoch), for the tests.
orologio = time.time


class PassaggioNonAmmesso(Exception):
    """Transition not allowed from the current state: nothing was written."""


class SchedaEsistente(Exception):
    """A record with this ID already exists."""


class SchedaNonTrovata(Exception):
    """No record with this ID."""


def _radice() -> Path:
    valore = os.environ.get("POSTA_RADICE")
    if valore:
        return Path(valore).expanduser()
    return Path.home() / ".posta-agenti"


def cartella() -> Path:
    percorso = _radice() / "domande"
    percorso.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(percorso, 0o700)
    except OSError:
        pass
    return percorso


def _valida_id(identificativo) -> str:
    if not isinstance(identificativo, str) or not ID_RE.match(identificativo):
        raise ValueError("ID di domanda non valido: %r" % (identificativo,))
    return identificativo


def _percorso(identificativo: str) -> Path:
    return cartella() / (_valida_id(identificativo) + ".json")


def _ora(istante: float) -> str:
    return datetime.fromtimestamp(istante).astimezone().isoformat(timespec="seconds")


@contextmanager
def _bloccata(identificativo: str):
    serratura = cartella() / (_valida_id(identificativo) + ".lock")
    fd = os.open(str(serratura), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def _scrivi(percorso: Path, scheda: dict) -> None:
    fd, temporaneo = tempfile.mkstemp(prefix=".tmp-domanda-", dir=str(percorso.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as uscita:
            json.dump(scheda, uscita, ensure_ascii=False, indent=1)
            uscita.write("\n")
            uscita.flush()
            os.fsync(uscita.fileno())
        os.chmod(temporaneo, 0o600)
        os.replace(temporaneo, percorso)
    except BaseException:
        try:
            os.unlink(temporaneo)
        except OSError:
            pass
        raise


def _carica(percorso: Path, identificativo: str) -> dict:
    try:
        with open(percorso, encoding="utf-8") as ingresso:
            return json.load(ingresso)
    except FileNotFoundError:
        raise SchedaNonTrovata(identificativo)


def _voce(stato: str, chi: str, nota: str) -> dict:
    istante = orologio()
    return {"stato": stato, "ora": _ora(istante), "t": istante, "chi": chi, "nota": nota}


def crea(scheda: dict) -> dict:
    """Saves a new record in state 'ricevuta'. SchedaEsistente if the ID is taken."""
    identificativo = _valida_id(scheda.get("id"))
    percorso = _percorso(identificativo)
    with _bloccata(identificativo):
        if percorso.exists():
            raise SchedaEsistente(identificativo)
        nuova = dict(scheda)
        nuova["stato"] = "ricevuta"
        nuova.setdefault("risposta", None)
        nuova["storia"] = [_voce("ricevuta", str(scheda.get("progetto") or "-"), "")]
        _scrivi(percorso, nuova)
    return nuova


def leggi(identificativo: str) -> dict:
    return _carica(_percorso(identificativo), identificativo)


def elenca(stato: str | None = None) -> list:
    """All records (optionally only those in one state), oldest first."""
    schede = []
    for percorso in cartella().glob("*.json"):
        try:
            with open(percorso, encoding="utf-8") as ingresso:
                scheda = json.load(ingresso)
        except (OSError, ValueError):
            continue
        if stato is None or scheda.get("stato") == stato:
            schede.append(scheda)
    schede.sort(key=lambda s: ((s.get("storia") or [{}])[0].get("t", 0), s.get("id", "")))
    return schede


def passa(identificativo: str, nuovo: str, chi: str, nota: str = "",
          solo_da=None, prima=None, **campi) -> dict:
    """Moves the record to `nuovo`; PassaggioNonAmmesso (and no write) if not allowed.

    - solo_da: optional tuple of states the record must be in (stricter than PASSAGGI);
    - prima: optional callable(scheda) -> dict|None run under the lock after the
      checks and before the write (for example to send the answer message); its
      result is stored in the record. If it raises, the record is not changed.
    Extra keyword fields (for example risposta=...) are stored in the record.
    """
    percorso = _percorso(identificativo)
    with _bloccata(identificativo):
        scheda = _carica(percorso, identificativo)
        attuale = scheda.get("stato")
        if nuovo not in PASSAGGI.get(attuale, set()) or (solo_da and attuale not in solo_da):
            raise PassaggioNonAmmesso("%s: %s -> %s" % (identificativo, attuale, nuovo))
        if prima is not None:
            campi.update(prima(dict(scheda)) or {})
        scheda.update(campi)
        scheda["stato"] = nuovo
        scheda.setdefault("storia", []).append(_voce(nuovo, chi, nota))
        _scrivi(percorso, scheda)
    return scheda


def annota(identificativo: str, chi: str, nota: str, **campi) -> dict:
    """Adds a history entry (and fields) without changing the state."""
    percorso = _percorso(identificativo)
    with _bloccata(identificativo):
        scheda = _carica(percorso, identificativo)
        scheda.update(campi)
        scheda.setdefault("storia", []).append(_voce(scheda.get("stato", "-"), chi, nota))
        _scrivi(percorso, scheda)
    return scheda


def sblocca_ferme(secondi: int = 120) -> list:
    """Records in 'in-valutazione' for more than `secondi` go back to 'ricevuta'."""
    adesso = orologio()
    sbloccate = []
    for scheda in elenca("in-valutazione"):
        ultima = (scheda.get("storia") or [{}])[-1]
        if adesso - float(ultima.get("t", 0)) <= secondi:
            continue
        try:
            passa(scheda["id"], "ricevuta", "sblocca", nota="ferma da oltre %d s" % secondi)
        except (PassaggioNonAmmesso, SchedaNonTrovata):
            continue
        sbloccate.append(scheda["id"])
    return sbloccate
