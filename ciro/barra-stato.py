#!/usr/bin/python3
# Barra di stato di Claude Code: salva i limiti d'uso ufficiali (rate_limits)
# in ~/.config/faccia/claude-code.json, cosi' la faccia li mostra nel pannello,
# e stampa una riga breve in fondo alla sessione.
# Collegata in ~/.claude/settings.json -> statusLine.
import json
import os
import sys
import time
from pathlib import Path

USCITA = Path.home() / ".config/faccia/claude-code.json"


def account():
    try:
        dati = json.loads((Path.home() / ".claude.json").read_text(encoding="utf-8"))
        info = dati.get("oauthAccount") or {}
        return info.get("organizationName") or info.get("emailAddress") or "Claude Code"
    except Exception:  # noqa: BLE001
        return "Claude Code"


def main():
    try:
        dato = json.load(sys.stdin)
    except Exception:  # noqa: BLE001
        dato = {}
    limiti = dato.get("rate_limits") or {}
    if limiti:
        try:
            USCITA.parent.mkdir(parents=True, exist_ok=True)
            temporaneo = USCITA.with_suffix(".tmp")
            temporaneo.write_text(json.dumps({
                "account": account(),
                "limiti": limiti,
                "aggiornato": int(time.time()),
            }, ensure_ascii=False), encoding="utf-8")
            os.replace(temporaneo, USCITA)
        except OSError:
            pass
    pezzi = []
    for chiave, etichetta in (("five_hour", "5h"), ("seven_day", "7g")):
        valore = (limiti.get(chiave) or {}).get("used_percentage")
        if valore is not None:
            pezzi.append("%s %.0f%%" % (etichetta, float(valore)))
    modello = ((dato.get("model") or {}).get("display_name")) or ""
    print(" · ".join([p for p in [modello] + pezzi if p]))


if __name__ == "__main__":
    main()
