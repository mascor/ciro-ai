#!/usr/bin/env python3
"""Guided voice test of Ciro: fake sessions ask, the user answers by voice.

    python3 prova_guidata.py --rapporto /path/to/report.txt [--porta 8765]

Steps (the user follows a printed sequence, without looking at the chat):
  1. prova-ciro asks a question            -> user answers «A»
  2. right after                           -> user says «rispondi B» (correction)
  3. prova-ciro and prova-due ask together -> «A», then «prova-due», then «B per prova-ciro»
  4. free question                         -> user asks «come stanno le sessioni?»
  5. end of the pause                      -> user says «riprendi i progetti»
Projects other than the two test ones are paused for the whole test.
Results and timings (from ~/.config/faccia/conversazioni.log) go to the report.
"""

import argparse
import json
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import domande  # noqa: E402
import posta  # noqa: E402

REGISTRO_CIRO = Path.home() / ".config/faccia/conversazioni.log"
OPZIONI = {"A": "procedi", "B": "fermati"}


def chiedi(casella, oggetto, domanda):
    return posta.chiedi(casella, oggetto, domanda, dict(OPZIONI), "scelta", "la prova guidata di Ciro",
                        raccomanda="A", testo="Prova: nessun lavoro vero dipende da questa risposta.")


def messaggi(casella, identificativo, correzione=False):
    trovati = []
    for cartella in ("nuovi", "letti"):
        for percorso in sorted((posta.cartella_casella(casella) / cartella).glob("*.md")):
            testa = posta.leggi_intestazioni(percorso)
            if testa.get("DOMANDA-ID") == identificativo and bool(testa.get("CORREZIONE")) == correzione:
                trovati.append(testa)
    return trovati


def aspetta(condizione, secondi):
    fine = time.time() + secondi
    while time.time() < fine:
        valore = condizione()
        if valore:
            return valore
        time.sleep(0.3)
    return None


def righe_registro(dal):
    righe = []
    try:
        for riga in REGISTRO_CIRO.read_text(encoding="utf-8").splitlines():
            try:
                voce = json.loads(riga)
            except ValueError:
                continue
            if voce.get("ora", "") >= dal:
                righe.append(voce)
    except OSError:
        pass
    return righe


def risposta_ciro(dal, filtro):
    for voce in righe_registro(dal):
        if voce.get("tipo") == "cervello" and filtro(voce):
            return voce
    return None


def pausa(porta, attiva, solo):
    corpo = json.dumps({"attiva": attiva, "solo": solo}).encode()
    richiesta = urllib.request.Request("http://127.0.0.1:%d/api/pausa" % porta, data=corpo, method="POST",
                                       headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(richiesta, timeout=5) as risposta:
        return json.load(risposta)


def guida(porta, frase):
    """Ciro tells the user what to do next (an external message: not paused)."""
    corpo = json.dumps({"testo": frase, "da": "prova"}).encode()
    richiesta = urllib.request.Request("http://127.0.0.1:%d/api/messaggio" % porta, data=corpo, method="POST",
                                       headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(richiesta, timeout=5).close()
    except OSError:
        pass


def aspetta_detto(dal, frase, secondi):
    """Waits until Ciro has spoken `frase` (so the next step does not talk over it)."""
    return aspetta(lambda: any(v.get("tipo") == "parla" and frase in (v.get("testo") or "")
                               for v in righe_registro(dal)), secondi)


def consegna(casella, identificativo):
    """The fake session reads the answer like a real one: recepita, then risolta."""
    risposte = messaggi(casella, identificativo)
    seconda = 0
    try:
        posta.recepita(identificativo, casella)
        try:
            posta.recepita(identificativo, casella)
        except posta.ErroreStato:
            seconda = posta.CODICE_STATO
        posta.risolta(identificativo, "prova guidata")
    except posta.ErroreStato:
        pass
    scheda = domande.leggi(identificativo)
    return {"scelta": (scheda.get("risposta") or {}).get("scelta"), "messaggi": len(risposte),
            "seconda_recepita": seconda, "stato": scheda.get("stato")}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--rapporto", required=True)
    parser.add_argument("--porta", type=int, default=8765)
    parser.add_argument("--attesa", type=float, default=180.0, help="seconds per step")
    args = parser.parse_args(argv)
    inizio = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    esiti = []

    def esito(passo, ok, dettaglio):
        esiti.append((passo, ok, dettaglio))
        print("%s passo %s: %s — %s" % (datetime.now().strftime("%H:%M:%S"), passo,
                                         "OK" if ok else "NO", dettaglio), flush=True)

    for scheda in domande.elenca("in-attesa"):  # old test questions would confuse the test
        if scheda.get("progetto") in ("prova-ciro", "prova-due"):
            posta.annulla(scheda["id"], scheda["progetto"])
    pausa(args.porta, True, ["prova-ciro", "prova-due"])
    print("pausa attiva tranne prova-ciro e prova-due; inizio %s" % inizio, flush=True)

    guida(args.porta, "Inizia la prova guidata. Passo uno: rispondi A alla domanda che arriva.")
    aspetta_detto(inizio, "Passo uno", 30)
    time.sleep(1)

    # 1. one question, answer «A»
    t0 = time.time()
    q1 = chiedi("prova-ciro", "Prova 1", "Prova uno: procedo?")
    arrivata = aspetta(lambda: messaggi("prova-ciro", q1), args.attesa)
    if arrivata:
        r = consegna("prova-ciro", q1)
        esito(1, r["scelta"] == "A" and r["messaggi"] == 1 and r["seconda_recepita"] == 4,
              "scelta %s, %d messaggio, seconda lettura %s, %.0f s dalla domanda"
              % (r["scelta"], r["messaggi"], r["seconda_recepita"], time.time() - t0))
    else:
        esito(1, False, "nessuna risposta in %.0f s" % args.attesa)

    # 2. correction «rispondi B»
    if arrivata:
        time.sleep(2)
        guida(args.porta, "Passo due: adesso di' rispondi B.")
    correzione = aspetta(lambda: messaggi("prova-ciro", q1, correzione=True), 120) if arrivata else None
    esito(2, bool(correzione) and correzione[0].get("CORREZIONE") == "B",
          "correzione %s" % (correzione[0].get("CORREZIONE") if correzione else "non arrivata in 120 s"))

    # 3. two questions together
    time.sleep(4)
    dal = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    guida(args.porta, "Passo tre: arrivano due domande. Rispondi A, poi di' prova due, poi B per prova ciro.")
    aspetta_detto(dal, "Passo tre", 30)
    time.sleep(1)
    q2 = chiedi("prova-ciro", "Prova 3a", "Prova tre, prima domanda: procedo?")
    q3 = chiedi("prova-due", "Prova 3b", "Prova tre, seconda domanda: procedo?")
    t3 = time.time()
    a3 = aspetta(lambda: messaggi("prova-due", q3), args.attesa)
    r3 = consegna("prova-due", q3) if a3 else None
    a2 = aspetta(lambda: messaggi("prova-ciro", q2), args.attesa)
    r2 = consegna("prova-ciro", q2) if a2 else None
    esito("3a", bool(r3) and r3["scelta"] == "A", "prova-due: %s" % (r3["scelta"] if r3 else "nessuna risposta"))
    esito("3b", bool(r2) and r2["scelta"] == "B", "prova-ciro: %s, %.0f s in tutto"
          % (r2["scelta"] if r2 else "nessuna risposta", time.time() - t3))
    chiese = any("Per quale progetto" in (v.get("ciro") or "") for v in righe_registro(inizio))
    esito("3c", chiese, "Ciro ha chiesto «Per quale progetto?»" if chiese else "non ha chiesto il progetto")

    # 4. free question
    time.sleep(3)
    dal = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    guida(args.porta, "Passo quattro: chiedimi come stanno le sessioni.")
    libera = aspetta(lambda: risposta_ciro(dal, lambda v: "session" in (v.get("tu") or "").lower()), 120)
    esito(4, bool(libera and libera.get("ciro")),
          ("«%s» in %.1f s" % ((libera.get("ciro") or "")[:90], libera.get("secondi") or 0)) if libera
          else "nessuna domanda sulle sessioni in 120 s")

    # 5. resume the projects
    time.sleep(3)
    dal = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    guida(args.porta, "Passo cinque: di' riprendi i progetti.")
    ripresa = aspetta(lambda: risposta_ciro(dal, lambda v: (v.get("ciro") or "").startswith("Progetti ripresi")), 120)
    if not ripresa:
        pausa(args.porta, False, [])
    esito(5, bool(ripresa), "pausa tolta a voce" if ripresa else "pausa tolta dallo script (comando non sentito)")

    time.sleep(6)
    riusciti = sum(1 for _, ok, _ in esiti if ok)
    guida(args.porta, "Prova finita: %d passi su %d riusciti." % (riusciti, len(esiti)))

    # report
    fine = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    righe = righe_registro(inizio)
    trascrizioni = [v.get("secondi_trascrizione") for v in righe if v.get("tipo") == "ascolto" and v.get("testo")]
    cervello = [v.get("secondi") for v in righe if v.get("tipo") == "cervello"]
    voce = [v.get("secondi_voce") for v in righe if v.get("tipo") == "parla" and v.get("secondi_voce")]
    scartate = sum(1 for v in righe if v.get("tipo") == "ascolto-scartato")
    testo = ["PROGETTO: CIRO AI", "DESTINATARIO: l'utente",
             "MITTENTE: prova_guidata.py (Claude Code, progetto ciro-ai), " + fine[:10],
             "DOVE INCOLLARLO: niente da incollare: e' il rapporto della prova a voce",
             "MOTIVO: esiti e tempi della prova guidata di Ciro", "",
             "Prova dalle %s alle %s" % (inizio[11:], fine[11:]), ""]
    for passo, ok, dettaglio in esiti:
        testo.append("passo %-3s %-3s %s" % (passo, "OK" if ok else "NO", dettaglio))
    media = lambda xs: (sum(xs) / len(xs)) if xs else 0  # noqa: E731
    testo += ["", "Tempi medi: trascrizione %.1f s (%d frasi), cervello %.1f s (%d risposte), "
              "voce %.1f s; registrazioni a vuoto scartate: %d"
              % (media(trascrizioni), len(trascrizioni), media(cervello), len(cervello), media(voce), scartate),
              "", "Cosa e' successo (dal registro di Ciro):"]
    for v in righe:
        if v.get("tipo") in ("domanda", "ascolto", "cervello", "ascolto-scartato"):
            testo.append("  %s %-16s %s%s" % (
                v["ora"][11:], v["tipo"], (v.get("testo") or v.get("tu") or "")[:80],
                (" -> " + (v.get("ciro") or "")[:80] + " (%.1f s)" % (v.get("secondi") or 0))
                if v.get("tipo") == "cervello" else ""))
    Path(args.rapporto).write_text("\n".join(testo) + "\n", encoding="utf-8")
    print("rapporto: %s" % args.rapporto, flush=True)
    return 0 if all(ok for _, ok, _ in esiti) else 1


if __name__ == "__main__":
    sys.exit(main())
