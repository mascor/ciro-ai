#!/usr/bin/env python3
"""«ciro connect»: Claude Code sessions send Ciro their permission requests and
multiple-choice questions through hooks (docs/hooks-design.md).

    python3 strumenti/collega.py stato        # are the hooks there?
    python3 strumenti/collega.py connect      # add them (backup first)
    python3 strumenti/collega.py disconnect   # remove only Ciro's hooks

Works on ~/.claude/settings.json (user settings: every session, every project), or on
the file given with --impostazioni. Every other setting and hook is kept. Idempotent.
Standard library only, Python 3.9.
"""

import argparse
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

IMPOSTAZIONI = Path.home() / ".claude" / "settings.json"
INDIRIZZO = "http://127.0.0.1:8765/hooks/claude"
SEGNO = "/hooks/claude"        # how Ciro's hooks are recognised
TIMEOUT = 75                   # seconds; Ciro waits for the user 60 (at most 70)
EVENTI = {"PermissionRequest": None, "PreToolUse": "AskUserQuestion"}   # event -> matcher


def _gancio():
    return {"type": "http", "url": INDIRIZZO, "timeout": TIMEOUT}


def _di_ciro(gancio):
    return isinstance(gancio, dict) and SEGNO in str(gancio.get("url") or "")


def leggi(percorso):
    try:
        dati = json.loads(Path(percorso).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    if not isinstance(dati, dict):
        raise ValueError("%s non contiene un oggetto JSON" % percorso)
    return dati


def scrivi(percorso, dati):
    percorso = Path(percorso)
    percorso.parent.mkdir(parents=True, exist_ok=True)
    fd, temporaneo = tempfile.mkstemp(prefix=".settings-", dir=str(percorso.parent))
    with os.fdopen(fd, "w", encoding="utf-8") as uscita:
        json.dump(dati, uscita, ensure_ascii=False, indent=2)
        uscita.write("\n")
    os.replace(temporaneo, percorso)


def togli(dati):
    """Settings without Ciro's hooks (empty groups and events removed)."""
    dati = json.loads(json.dumps(dati))
    ganci = dati.get("hooks")
    if not isinstance(ganci, dict):
        return dati
    for evento in list(ganci):
        gruppi = []
        for gruppo in ganci[evento] if isinstance(ganci[evento], list) else []:
            if not isinstance(gruppo, dict):
                gruppi.append(gruppo)
                continue
            rimasti = [g for g in gruppo.get("hooks") or [] if not _di_ciro(g)]
            if rimasti:
                gruppi.append(dict(gruppo, hooks=rimasti))
            elif not gruppo.get("hooks"):
                gruppi.append(gruppo)
        if gruppi:
            ganci[evento] = gruppi
        else:
            del ganci[evento]
    if not ganci:
        del dati["hooks"]
    return dati


def aggiungi(dati):
    dati = togli(dati)
    ganci = dati.setdefault("hooks", {})
    for evento, abbinamento in EVENTI.items():
        gruppo = {"hooks": [_gancio()]}
        if abbinamento:
            gruppo = {"matcher": abbinamento, "hooks": [_gancio()]}
        ganci.setdefault(evento, []).append(gruppo)
    return dati


def collegato(dati):
    ganci = dati.get("hooks") if isinstance(dati.get("hooks"), dict) else {}
    trovati = set()
    for evento, gruppi in ganci.items():
        for gruppo in gruppi if isinstance(gruppi, list) else []:
            if isinstance(gruppo, dict) and any(_di_ciro(g) for g in gruppo.get("hooks") or []):
                trovati.add(evento)
    return trovati >= set(EVENTI)


def principale(argomenti=None):
    parser = argparse.ArgumentParser(description="Collega Claude Code a Ciro con gli hook.")
    parser.add_argument("azione", choices=("stato", "connect", "disconnect"))
    parser.add_argument("--impostazioni", default=str(IMPOSTAZIONI))
    opzioni = parser.parse_args(argomenti)
    percorso = Path(opzioni.impostazioni).expanduser()
    dati = leggi(percorso)
    if opzioni.azione == "stato":
        print("collegato: %s" % ("si" if collegato(dati) else "no"))
        return 0
    nuovi = aggiungi(dati) if opzioni.azione == "connect" else togli(dati)
    if nuovi == dati:
        print("%s: niente da cambiare" % opzioni.azione)
        return 0
    if percorso.exists():
        copia = percorso.with_name(percorso.name + ".bak-ciro-" + time.strftime("%Y%m%d-%H%M%S"))
        shutil.copy2(percorso, copia)
        print("backup: %s" % copia)
    scrivi(percorso, nuovi)
    print("%s: fatto (%s). Le sessioni gia' aperte lo vedono dopo un riavvio." % (opzioni.azione, percorso))
    return 0


if __name__ == "__main__":
    sys.exit(principale())
