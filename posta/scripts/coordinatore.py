#!/usr/bin/env python3
"""Decides whether a structured question can be answered without the user.

- Forbidden operations (VIETATE) are never answered automatically, whatever
  the rules or the model say.
- deploy-prova: automatic only with an authorisation that matches exactly
  (project, environment "prova", conditions declared by the session).
- scelta: the model compares the saved preferences with the question; only a
  valid JSON answer naming one of the options makes it automatic.
Standard library only, Python 3.9.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import time
from pathlib import Path

VIETATE = frozenset({"deploy-produzione", "cancellazione", "database", "configurazione",
                     "credenziali", "servizio-esterno", "abbonamento", "altro",
                     "permesso"})   # a tool permission asked by a session hook: only the user
SUL_SERVER = frozenset({"deploy-produzione", "cancellazione", "database", "configurazione"})
UNICA_AUTORIZZABILE = "deploy-prova"
NOME_RE = re.compile(r"^[A-Za-z0-9_-]{1,120}$")

PROMPT_PREFERENZE = """Sei il coordinatore dell'utente. Devi solo dire se una delle sue
preferenze salvate risponde gia' alla domanda di una sessione di lavoro.

Preferenze dell'utente (una per riga):
{preferenze}

Domanda della sessione {progetto}: {domanda}
Opzioni:
{opzioni}

Rispondi SOLO con un oggetto JSON su una riga, senza altro testo:
{{"copre": true|false, "scelta": "<lettera tra le opzioni o null>", "regola": "<la preferenza usata, parola per parola, o null>", "motivo": "<una frase breve>"}}
"copre" e' true solo se una preferenza indica chiaramente una delle opzioni. Nel dubbio, false."""


def _esito(esito="chiedi", scelta=None, regola=None, motivo=""):
    return {"esito": esito, "scelta": scelta, "regola": regola, "motivo": motivo}


def _json_in(testo):
    """First JSON object in the model's answer, or None."""
    if not isinstance(testo, str):
        return None
    inizio = testo.find("{")
    fine = testo.rfind("}")
    if inizio < 0 or fine <= inizio:
        return None
    try:
        valore = json.loads(testo[inizio:fine + 1])
    except ValueError:
        return None
    return valore if isinstance(valore, dict) else None


def _regola_che_copre(scheda, autorizzazioni):
    condizioni = set(scheda.get("condizioni") or [])
    for regola in autorizzazioni or []:
        richieste = set(regola.get("condizioni") or [])
        if (regola.get("operazione") == UNICA_AUTORIZZABILE
                and regola.get("progetto") == scheda.get("progetto")
                and regola.get("ambiente") == "prova"
                and scheda.get("ambiente") == "prova"
                and richieste and richieste <= condizioni):
            return regola
    return None


def valuta(scheda, preferenze, autorizzazioni, chiedi_al_modello=None):
    """{"esito": "automatica"|"chiedi", "scelta", "regola", "motivo"}.

    With chiedi_al_modello=None work choices give "chiedi" (fast evaluation)."""
    operazione = scheda.get("operazione")
    opzioni = scheda.get("opzioni") or {}
    if operazione in VIETATE:
        motivo = "operazione %s: decide sempre l'utente" % operazione
        if operazione in SUL_SERVER:
            motivo += "; la conferma vera si da' nella sessione del server"
        return _esito(motivo=motivo)
    if operazione == UNICA_AUTORIZZABILE:
        regola = _regola_che_copre(scheda, autorizzazioni)
        raccomanda = (scheda.get("raccomanda") or "").upper()
        if regola is None:
            return _esito(motivo="nessuna autorizzazione che corrisponde esattamente")
        if raccomanda not in opzioni:
            return _esito(motivo="la sessione non indica quale opzione procede")
        return _esito("automatica", raccomanda, regola.get("id"),
                      regola.get("frase") or "deploy di prova autorizzato dopo i test")
    if operazione != "scelta":
        return _esito(motivo="operazione sconosciuta: %r" % (operazione,))
    preferenze = [p.strip() for p in preferenze or [] if p and p.strip()]
    if chiedi_al_modello is None or not preferenze:
        return _esito(motivo="nessuna preferenza da valutare")
    prompt = PROMPT_PREFERENZE.format(
        preferenze="\n".join("- " + p for p in preferenze),
        progetto=scheda.get("progetto") or "?",
        domanda=scheda.get("domanda") or "",
        opzioni="\n".join("%s) %s" % voce for voce in opzioni.items()),
    )
    try:
        risposta = _json_in(chiedi_al_modello(prompt))
    except Exception as errore:  # model down, timeout: the user decides
        return _esito(motivo="modello non disponibile: %s" % type(errore).__name__)
    if not risposta or risposta.get("copre") is not True:
        return _esito(motivo="nessuna preferenza copre la domanda")
    scelta = str(risposta.get("scelta") or "").strip().upper()
    if scelta not in opzioni:
        return _esito(motivo="il modello ha indicato una scelta non valida")
    regola = str(risposta.get("regola") or risposta.get("motivo") or "preferenza salvata")
    return _esito("automatica", scelta, "preferenza", regola[:200])


# ------------------------------------------------------------ autorizzazioni


def _file_autorizzazioni() -> Path:
    valore = os.environ.get("CIRO_AUTORIZZAZIONI")
    if valore:
        return Path(valore).expanduser()
    return Path.home() / ".config" / "opencode" / "autorizzazioni.json"


def carica_autorizzazioni() -> list:
    """Saved authorisations. Anything that is not a test deploy is ignored,
    even if someone wrote it into the file by hand."""
    try:
        dati = json.loads(_file_autorizzazioni().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(dati, list):
        return []
    return [r for r in dati if isinstance(r, dict) and r.get("operazione") == UNICA_AUTORIZZABILE]


def _salva(regole):
    percorso = _file_autorizzazioni()
    percorso.parent.mkdir(parents=True, exist_ok=True)
    fd, temporaneo = tempfile.mkstemp(prefix=".tmp-aut-", dir=str(percorso.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as uscita:
            json.dump(regole, uscita, ensure_ascii=False, indent=1)
            uscita.write("\n")
        os.chmod(temporaneo, 0o600)
        os.replace(temporaneo, percorso)
    except BaseException:
        try:
            os.unlink(temporaneo)
        except OSError:
            pass
        raise


def salva_autorizzazione(progetto, operazione, ambiente, condizioni, frase) -> dict:
    """Saves a standing authorisation. Only test deploys after declared conditions."""
    if operazione != UNICA_AUTORIZZABILE:
        raise ValueError("si possono autorizzare solo i deploy di prova, non %r" % (operazione,))
    if ambiente != "prova":
        raise ValueError("ambiente non autorizzabile: %r" % (ambiente,))
    if not isinstance(progetto, str) or not NOME_RE.match(progetto):
        raise ValueError("progetto non valido: %r" % (progetto,))
    condizioni = sorted({str(c).strip() for c in condizioni or [] if str(c).strip()})
    if not condizioni:
        raise ValueError("serve almeno una condizione, per esempio test-ok")
    regole = carica_autorizzazioni()
    for regola in regole:
        if (regola.get("progetto") == progetto and regola.get("ambiente") == ambiente
                and sorted(regola.get("condizioni") or []) == condizioni):
            return regola
    nuova = {
        "id": "aut-%s-%d" % (progetto, int(time.time() * 1000)),
        "progetto": progetto, "operazione": operazione, "ambiente": ambiente,
        "condizioni": condizioni, "creata": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "frase": " ".join(str(frase or "").split())[:200],
    }
    _salva(regole + [nuova])
    return nuova


def togli_autorizzazioni(progetto) -> int:
    regole = carica_autorizzazioni()
    restano = [r for r in regole if r.get("progetto") != progetto]
    if len(restano) != len(regole):
        _salva(restano)
    return len(regole) - len(restano)


def elenca_autorizzazioni(progetto) -> list:
    return [r for r in carica_autorizzazioni() if r.get("progetto") == progetto]
