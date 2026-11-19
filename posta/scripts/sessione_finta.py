#!/usr/bin/env python3
"""Fake session for the full-cycle test: asks a structured question, waits
for the answer, runs recepita and risolta, and prints control variables.

    python3 sessione_finta.py --casella prova-ciro [--attesa 120]

Uses POSTA_RADICE like posta.py (set it to a temporary folder for tests).
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import domande  # noqa: E402
import posta  # noqa: E402


def aspetta_risposta(casella, identificativo, secondi):
    """Path of the answer message for this question, or None after `secondi`."""
    fine = time.time() + secondi
    cartella = posta.cartella_casella(casella) / "nuovi"
    while time.time() < fine:
        for percorso in sorted(cartella.glob("*.md")):
            testa = posta.leggi_intestazioni(percorso)
            if testa.get("DOMANDA-ID") == identificativo and not testa.get("CORREZIONE"):
                return percorso, testa
        time.sleep(0.2)
    return None, None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--casella", default="prova-ciro")
    parser.add_argument("--attesa", type=float, default=120.0)
    args = parser.parse_args(argv)

    inizio = time.time()
    identificativo = posta.chiedi(
        args.casella, "Prova del ciclo completo", "Procedo con la prova del ciclo completo?",
        {"A": "procedi", "B": "fermati"}, "scelta", "la prova del coordinamento",
        raccomanda="A", testo="Messaggio di prova: nessun lavoro vero dipende da questa risposta.")
    print("domanda_id: %s" % identificativo, flush=True)

    percorso, testa = aspetta_risposta(args.casella, identificativo, args.attesa)
    if percorso is None:
        print("risposta_ricevuta: no (dopo %.0f s)" % args.attesa)
        print("stato_finale: %s" % domande.leggi(identificativo)["stato"])
        return 1
    secondi_risposta = time.time() - inizio
    posta.archivia(percorso)

    codice_recepita = 0
    try:
        posta.recepita(identificativo, args.casella)
    except posta.ErroreStato:
        codice_recepita = posta.CODICE_STATO
    codice_seconda = 0
    try:
        posta.recepita(identificativo, args.casella)  # a duplicate must be refused
    except posta.ErroreStato:
        codice_seconda = posta.CODICE_STATO
    if codice_recepita == 0:
        posta.risolta(identificativo, "prova completata")

    scheda = domande.leggi(identificativo)
    messaggi = [p for p in (posta.cartella_casella(args.casella) / "nuovi").glob("*.md")] + \
               [p for p in (posta.cartella_casella(args.casella) / "letti").glob("*.md")]
    risposte = [p for p in messaggi
                if posta.leggi_intestazioni(p).get("DOMANDA-ID") == identificativo]
    print("risposta_ricevuta: si")
    print("scelta: %s" % (scheda.get("risposta") or {}).get("scelta"))
    print("motivo: %s" % (scheda.get("risposta") or {}).get("motivo"))
    print("secondi_da_chiedi_a_risposta: %.1f" % secondi_risposta)
    print("recepita_codice: %d" % codice_recepita)
    print("seconda_recepita_codice: %d" % codice_seconda)
    print("messaggi_di_risposta: %d" % len(risposte))
    print("storia: %s" % " -> ".join(p["stato"] for p in scheda["storia"]))
    print("stato_finale: %s" % scheda["stato"])
    return 0 if scheda["stato"] == "risolta" and len(risposte) == 1 else 1


if __name__ == "__main__":
    sys.exit(main())
