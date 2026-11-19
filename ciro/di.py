#!/usr/bin/python3
# Fa dire una frase alla faccia che sta girando (server locale sulla 8765).
# Uso: ./di.py "Testo da pronunciare"     ./di.py --stato
import json
import sys
import urllib.request

PORTA = 8765


def chiama(percorso, dati=None):
    url = "http://127.0.0.1:%d%s" % (PORTA, percorso)
    corpo = json.dumps(dati).encode("utf-8") if dati is not None else None
    richiesta = urllib.request.Request(
        url, data=corpo, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(richiesta, timeout=10) as risposta:
        return json.loads(risposta.read() or b"{}")


if __name__ == "__main__":
    argomenti = sys.argv[1:]
    if not argomenti or argomenti[0] in ("--stato", "-s"):
        print(json.dumps(chiama("/api/stato"), ensure_ascii=False))
        sys.exit(0)
    testo = " ".join(argomenti)
    print(json.dumps(chiama("/api/messaggio", {"testo": testo}), ensure_ascii=False))
