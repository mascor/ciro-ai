#!/usr/bin/env python3
"""Usability measures from Ciro's log: where the voice really goes wrong.

Reads ~/.config/faccia/conversazioni.log (one JSON line per event) and the question
records (~/.posta-agenti/domande) and prints only counts and times, never what was
said: the report can be shared.

    python3 strumenti/misure.py               # last 7 days
    python3 strumenti/misure.py --giorni 1    # last 24 hours
    python3 strumenti/misure.py --dal 2026-11-20 --json

Standard library only, Python 3.9.
"""

import argparse
import json
import os
import statistics
import sys
from datetime import datetime, timedelta
from pathlib import Path

REGISTRO = Path(os.environ.get("CIRO_REGISTRO") or Path.home() / ".config/faccia/conversazioni.log")
DOMANDE = Path(os.environ.get("POSTA_RADICE") or Path.home() / ".posta-agenti") / "domande"

# What Ciro says when he has to ask again or refuse (Italian and English beginnings).
CHIARIMENTI = {
    "quale_domanda": ("Quale domanda?", "Which question?", "Per quale progetto?", "For which project?"),
    "conferma_lettera": ("Hai detto ", "Did you say "),
    "chiede_il_numero": ("Rispondi con il numero", "Answer with the number", "Per mandarla mi serve il numero",
                         "To send it I need the number", "Le opzioni sono", "The options are",
                         "Va bene. Dimmi il numero", "OK. Tell me the number"),
    "letta_prima": ("Prima te la dico", "Let me read it first"),
}
GIA_CHIUSA = ("è già chiusa", "is already closed", "Quella domanda è già chiusa", "That question is already closed")
ERRORI_MODELLO = ("Il cervello non risponde", "The brain is not answering", "Ci sto mettendo troppo",
                  "I'm taking too long")
CORREZIONI = ("Correzione mandata", "Correction sent")


def _ora(valore):
    try:
        return datetime.strptime(str(valore), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _centili(valori):
    valori = sorted(v for v in valori if isinstance(v, (int, float)))
    if not valori:
        return None
    p90 = valori[min(len(valori) - 1, int(round(0.9 * (len(valori) - 1))))]
    return {"n": len(valori), "mediana": round(statistics.median(valori), 2), "p90": round(p90, 2)}


def _percentuale(parte, totale):
    return round(100.0 * parte / totale, 1) if totale else None


def leggi_eventi(percorso, dal, al):
    eventi = []
    try:
        righe = percorso.read_text(encoding="utf-8").splitlines()
    except OSError:
        return eventi
    for riga in righe:
        try:
            evento = json.loads(riga)
        except ValueError:
            continue
        quando = _ora(evento.get("ora")) if isinstance(evento, dict) else None
        if quando is not None and dal <= quando < al:
            evento["_quando"] = quando
            eventi.append(evento)
    return eventi


def misura(eventi):
    tipi = {}
    for evento in eventi:
        tipi[evento.get("tipo")] = tipi.get(evento.get("tipo"), 0) + 1

    ascoltate = tipi.get("ascolto", 0)
    scartate = [e for e in eventi if e.get("tipo") == "ascolto-scartato"]
    motivi = {}
    for evento in scartate:
        motivi[evento.get("motivo") or "?"] = motivi.get(evento.get("motivo") or "?", 0) + 1

    scambi = [e for e in eventi if e.get("tipo") == "cervello"]
    risposte = [str(e.get("ciro") or "") for e in scambi]
    chiarimenti = {nome: sum(1 for r in risposte if r.startswith(inizi)) for nome, inizi in CHIARIMENTI.items()}
    chiarimenti["gia_chiusa"] = sum(1 for r in risposte if any(g in r for g in GIA_CHIUSA))
    totale_chiarimenti = sum(chiarimenti.values())

    giorni = sorted({e["_quando"].strftime("%Y-%m-%d") for e in eventi})
    return {
        "giorni_con_uso": len(giorni),
        "ascolto": {
            "frasi_trascritte": ascoltate,
            "frasi_scartate": len(scartate),
            "scartate_percento": _percentuale(len(scartate), ascoltate + len(scartate)),
            "scartate_per_motivo": motivi,
            "secondi_trascrizione": _centili([e.get("secondi_trascrizione") for e in eventi
                                              if e.get("tipo") == "ascolto"]),
            "rumori_ignorati": tipi.get("pagina-rumore-ignorato", 0),
            "soglia_alzata": tipi.get("pagina-soglia-alzata", 0),
            "microfono_mentre_parla": tipi.get("pagina-mic-mentre-parla", 0),
            "interruzioni": tipi.get("pagina-interruzione", 0),
            "ignorate_senza_nome": tipi.get("pagina-ignorato-senza-nome", 0),
            "errori_ascolto": tipi.get("pagina-errore-ascolto", 0),
        },
        "risposte": {
            "scambi": len(scambi),
            "secondi_risposta": _centili([e.get("secondi") for e in scambi]),
            "mandate": sum(1 for e in scambi if e.get("mandato")),
            "correzioni": sum(1 for r in risposte if r.startswith(CORREZIONI)),
            "chiarimenti": chiarimenti,
            "chiarimenti_percento": _percentuale(totale_chiarimenti, len(scambi)),
            "errori_modello": sum(1 for r in risposte if r.startswith(ERRORI_MODELLO)),
        },
        "voce": {
            "frasi_dette": tipi.get("parla", 0),
            "secondi_sintesi": _centili([e.get("secondi_voce") for e in eventi if e.get("tipo") == "parla"]),
            "domande_annunciate": tipi.get("domanda", 0),
            "avvisi": tipi.get("avviso", 0),
        },
    }


def misura_domande(cartella, dal, al):
    """Questions asked by the sessions in the period: how fast and how they were answered."""
    attese_utente, per_regola, da_utente, annullate, ancora_aperte = [], 0, 0, 0, 0
    for file in sorted(cartella.glob("*.json")) if cartella.is_dir() else []:
        try:
            scheda = json.loads(file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        storia = scheda.get("storia") or []
        if not storia:
            continue
        inizio = datetime.fromtimestamp(float(storia[0].get("t") or 0))
        if not dal <= inizio < al:
            continue
        stati = {p.get("stato"): float(p.get("t") or 0) for p in storia}
        motivo = str((scheda.get("risposta") or {}).get("motivo") or "")
        if "risposta-consegnata" in stati:
            if motivo.startswith("regola:"):
                per_regola += 1
            else:
                da_utente += 1
                if "in-attesa" in stati:
                    attese_utente.append(stati["risposta-consegnata"] - stati["in-attesa"])
        elif "annullata" in stati:
            annullate += 1
        else:
            ancora_aperte += 1
    return {
        "risposte_tue": da_utente,
        "risposte_con_le_tue_regole": per_regola,
        "annullate_dalla_sessione": annullate,
        "ancora_aperte": ancora_aperte,
        "secondi_per_rispondere": _centili(attese_utente),
    }


def _riga(etichetta, valore):
    if isinstance(valore, dict) and "mediana" in valore:
        valore = "mediana %s s, 90%% entro %s s (%d)" % (valore["mediana"], valore["p90"], valore["n"])
    elif isinstance(valore, dict):
        valore = ", ".join("%s %s" % (k, v) for k, v in sorted(valore.items())) or "-"
    elif valore is None:
        valore = "-"
    return "  %-28s %s" % (etichetta, valore)


def testo(rapporto):
    a, r, v, d = rapporto["ascolto"], rapporto["risposte"], rapporto["voce"], rapporto["domande"]
    righe = ["Misure di Ciro dal %s al %s (%d giorni con uso)" % (
        rapporto["dal"], rapporto["al"], rapporto["giorni_con_uso"]), "", "Ascolto"]
    righe += [_riga("frasi trascritte", a["frasi_trascritte"]),
              _riga("frasi scartate", "%d (%s%%)" % (a["frasi_scartate"], a["scartate_percento"])),
              _riga("  per motivo", a["scartate_per_motivo"]),
              _riga("trascrizione", a["secondi_trascrizione"]),
              _riga("rumori ignorati", a["rumori_ignorati"]),
              _riga("microfono mentre parla", a["microfono_mentre_parla"]),
              _riga("interruzioni", a["interruzioni"]),
              _riga("senza «Ehi Ciro»", a["ignorate_senza_nome"]),
              "", "Risposte"]
    righe += [_riga("scambi", r["scambi"]),
              _riga("tempo di risposta", r["secondi_risposta"]),
              _riga("mandate alle sessioni", r["mandate"]),
              _riga("correzioni («annulla»...)", r["correzioni"]),
              _riga("richieste di chiarimento", "%d (%s%% degli scambi)" % (
                  sum(r["chiarimenti"].values()), r["chiarimenti_percento"])),
              _riga("  per tipo", r["chiarimenti"]),
              _riga("errori del modello", r["errori_modello"]),
              "", "Domande delle sessioni"]
    righe += [_riga("risposte tue", d["risposte_tue"]),
              _riga("con le tue regole", d["risposte_con_le_tue_regole"]),
              _riga("annullate dalla sessione", d["annullate_dalla_sessione"]),
              _riga("ancora aperte", d["ancora_aperte"]),
              _riga("tempo per rispondere", d["secondi_per_rispondere"]),
              "", "Voce"]
    righe += [_riga("frasi dette", v["frasi_dette"]),
              _riga("sintesi della voce", v["secondi_sintesi"]),
              _riga("domande annunciate", v["domande_annunciate"]),
              _riga("avvisi", v["avvisi"])]
    return "\n".join(righe)


def principale(argomenti=None, adesso=None):
    parser = argparse.ArgumentParser(description="Misure d'uso di Ciro (solo numeri, nessun testo).")
    parser.add_argument("--giorni", type=float, default=7, help="ultimi N giorni (predefinito 7)")
    parser.add_argument("--dal", help="dal giorno AAAA-MM-GG (al posto di --giorni)")
    parser.add_argument("--json", action="store_true", help="uscita JSON")
    parser.add_argument("--registro", default=str(REGISTRO))
    parser.add_argument("--domande", default=str(DOMANDE))
    opzioni = parser.parse_args(argomenti)
    adesso = adesso or datetime.now()
    dal = datetime.strptime(opzioni.dal, "%Y-%m-%d") if opzioni.dal else adesso - timedelta(days=opzioni.giorni)
    eventi = leggi_eventi(Path(opzioni.registro).expanduser(), dal, adesso)
    rapporto = dict(misura(eventi), dal=dal.strftime("%Y-%m-%d %H:%M"), al=adesso.strftime("%Y-%m-%d %H:%M"),
                    domande=misura_domande(Path(opzioni.domande).expanduser(), dal, adesso))
    print(json.dumps(rapporto, ensure_ascii=False, indent=1) if opzioni.json else testo(rapporto))
    return rapporto


if __name__ == "__main__":
    principale()
    sys.exit(0)
