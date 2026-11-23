"""Calendar alerts (M6, design: docs/calendar-alerts-design.md): the reader.

Every minute, for each linked account, the next red events (colour Tomato, colorId "11")
starting in the next 35 minutes. Read-only Google Calendar API. The download is a function
passed in, so tests run on fake answers with no network.

Accounts and calendars: ~/.config/ciro/calendario.json, for example
    {"lavoro": {"calendari": ["primary"]}, "personale": {"calendari": ["primary"]}}
The refresh token of each account is in the macOS Keychain (service ciro-calendario-<account>),
the OAuth client in ~/.config/ciro/calendario-client.json: never in the repository.
"""

import json
import re
import os
import subprocess
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROSSO = "11"                 # Tomato: the full red; Flamingo ("4") and calendar colours do not count
ANTICIPO = 35 * 60           # read window: alerts start at T-30, 5 minutes of margin
VECCHIO_DOPO = 10 * 60       # last good list kept this long when Google does not answer
CONFIGURAZIONE = Path(os.path.expanduser("~/.config/ciro/calendario.json"))
CLIENT = Path(os.path.expanduser("~/.config/ciro/calendario-client.json"))
API = "https://www.googleapis.com/calendar/v3/calendars/%s/events?%s"


def _istante(testo):
    """RFC 3339 -> epoch seconds; None if missing or not readable."""
    if not testo:
        return None
    try:
        return datetime.fromisoformat(str(testo).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def rfc3339(secondi):
    return datetime.fromtimestamp(secondi, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def filtra(risposta, account, calendario, adesso):
    """Red events of one events.list answer that start between now and now + ANTICIPO.
    All-day events (no time), cancelled ones and other colours are left out."""
    eventi = []
    for voce in (risposta or {}).get("items") or []:
        if not isinstance(voce, dict) or voce.get("colorId") != ROSSO or voce.get("status") == "cancelled":
            continue
        inizio = _istante((voce.get("start") or {}).get("dateTime"))
        if inizio is None or not adesso <= inizio <= adesso + ANTICIPO:
            continue
        eventi.append({
            "chiave": "%s|%s|%d" % (account, voce.get("id") or "", int(inizio)),   # moved event = new alert
            "id": voce.get("id") or "", "account": account, "calendario": calendario,
            "titolo": (voce.get("summary") or "").strip()[:120], "inizio": int(inizio),
            "link": voce.get("htmlLink") or "",
        })
    return eventi


def leggi_configurazione(percorso=None):
    try:
        dati = json.loads(Path(percorso or CONFIGURAZIONE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {str(a): {"calendari": [str(c) for c in (v or {}).get("calendari") or ["primary"]]}
            for a, v in dati.items()} if isinstance(dati, dict) else {}


class Lettore:
    """scarica(account, calendario, time_min, time_max) -> events.list answer (dict);
    it raises on network or Google errors."""

    def __init__(self, scarica, configurazione=None):
        self._scarica = scarica
        self._configurazione = configurazione or leggi_configurazione
        self._ultimi = {}          # account -> (time of the last good read, events)
        self.errori = {}           # account -> short error text of the last failed read

    def leggi(self, adesso=None):
        """Red events of all accounts, sorted by start. An account whose read fails keeps its
        last good list for VECCHIO_DOPO, then it gives nothing (never alert on stale data)."""
        adesso = time.time() if adesso is None else adesso
        tutti = []
        for account, impostazioni in self._configurazione().items():
            try:
                eventi = []
                for calendario in impostazioni["calendari"]:
                    risposta = self._scarica(account, calendario, rfc3339(adesso), rfc3339(adesso + ANTICIPO))
                    eventi += filtra(risposta, account, calendario, adesso)
                self._ultimi[account] = (adesso, eventi)
                self.errori.pop(account, None)
            except Exception as errore:  # noqa: BLE001 - any failure: keep the last good list
                self.errori[account] = type(errore).__name__
            quando, eventi = self._ultimi.get(account, (None, []))
            if quando is None or adesso - quando > VECCHIO_DOPO:
                continue
            tutti += [e for e in eventi if e["inizio"] >= adesso]
        visti = set()
        unici = [e for e in sorted(tutti, key=lambda e: e["inizio"])
                 if not (e["chiave"] in visti or visti.add(e["chiave"]))]
        return unici

    def non_aggiornati(self, adesso=None):
        """Accounts with no good read in the last VECCHIO_DOPO: the panel says «calendario non aggiornato»."""
        adesso = time.time() if adesso is None else adesso
        return sorted(a for a in self._configurazione()
                      if adesso - self._ultimi.get(a, (-1e12, None))[0] > VECCHIO_DOPO)


# --- Google (real network; not used by the tests) -----------------------------------------

def _token_portachiavi(account):
    esito = subprocess.run(["/usr/bin/security", "find-generic-password", "-s",
                            "ciro-calendario-" + account, "-w"], capture_output=True, text=True, timeout=10)
    if esito.returncode != 0 or not esito.stdout.strip():
        raise RuntimeError("calendario non collegato: " + account)
    return esito.stdout.strip()


def _accesso(account, _cache={}):
    """Short-lived access token from the refresh token (cached until one minute before expiry)."""
    salvato = _cache.get(account)
    if salvato and salvato[1] > time.time() + 60:
        return salvato[0]
    client = json.loads(CLIENT.read_text(encoding="utf-8"))
    client = client.get("installed") or client
    corpo = urllib.parse.urlencode({
        "client_id": client["client_id"], "client_secret": client["client_secret"],
        "refresh_token": _token_portachiavi(account), "grant_type": "refresh_token"}).encode()
    with urllib.request.urlopen("https://oauth2.googleapis.com/token", corpo, timeout=15) as risposta:
        dati = json.load(risposta)
    _cache[account] = (dati["access_token"], time.time() + int(dati.get("expires_in", 3600)))
    return dati["access_token"]


def scarica_google(account, calendario, time_min, time_max):
    domanda = urllib.parse.urlencode({"timeMin": time_min, "timeMax": time_max, "singleEvents": "true",
                                      "orderBy": "startTime", "maxResults": "50"})
    richiesta = urllib.request.Request(API % (urllib.parse.quote(calendario, safe=""), domanda),
                                       headers={"Authorization": "Bearer " + _accesso(account)})
    with urllib.request.urlopen(richiesta, timeout=15) as risposta:
        return json.load(risposta)


# --- Chrome extension (#70): the open Google Calendar tab, no Google Cloud setup ------------

MESI = {m: i + 1 for i, m in enumerate(
    "gennaio febbraio marzo aprile maggio giugno luglio agosto settembre ottobre novembre dicembre".split())}
MESI.update({m: i + 1 for i, m in enumerate(
    "january february march april may june july august september october november december".split())})
_MESE = "|".join(sorted(MESI, key=len, reverse=True))
DATA_GM_RE = re.compile(r"\b(\d{1,2})\s+(%s)\s+(\d{4})\b" % _MESE, re.I)          # 23 novembre 2026
DATA_MG_RE = re.compile(r"\b(%s)\s+(\d{1,2}),?\s+(\d{4})\b" % _MESE, re.I)         # November 23, 2026
ORA_RE = re.compile(r"\b(\d{1,2})(?:[:.](\d{2}))?\s*(am|pm)?\b", re.I)
# Google's «Pomodoro» / Tomato: (213, 0, 0) in the light theme; (218, 82, 52) in the dark theme,
# measured on the maintainer's test event on 23/11/2026. Orange (227, 104, 62) must stay out.
TOMATO = ((213, 0, 0), (218, 82, 52))
MARGINE_ROSSO = 12
PAGINA = "pagina"             # calendar name for events read from the tab
SILENZIO_PAGINA = 120         # a tab silent for 2 minutes is a failed read (stale after VECCHIO_DOPO)


def e_rosso(css):
    """True for Tomato in any notation the page uses (rgb, rgba, #d50000), with a small margin."""
    testo = (css or "").strip().lower()
    if testo.startswith("#") and len(testo) == 7:
        valori = tuple(int(testo[i:i + 2], 16) for i in (1, 3, 5))
    else:
        numeri = re.findall(r"\d+", testo)[:3]
        if len(numeri) < 3:
            return False
        valori = tuple(int(n) for n in numeri)
    return any(all(abs(a - b) <= MARGINE_ROSSO for a, b in zip(valori, rosso)) for rosso in TOMATO)


def inizio_da_etichetta(testo):
    """Start of the event (epoch, local time) from the chip label, or None (all-day, no date)."""
    testo = testo or ""
    data = DATA_GM_RE.search(testo)
    if data:
        giorno, mese, anno = int(data.group(1)), MESI[data.group(2).lower()], int(data.group(3))
    else:
        data = DATA_MG_RE.search(testo)
        if not data:
            return None
        mese, giorno, anno = MESI[data.group(1).lower()], int(data.group(2)), int(data.group(3))
    # the time comes before the date: «15:30 - 16:00, ...» or «3:30pm to 4pm, ...»
    prima = testo[:data.start()]
    for ora in ORA_RE.finditer(prima):
        dopo_parola = re.search(r"(?:dalle|from|ore|at)\s*$", prima[:ora.start()], re.I)
        if ora.group(2) is None and not ora.group(3) and not dopo_parola:
            continue   # a bare number is not a time, unless «dalle 9», «from 9»
        ore, minuti = int(ora.group(1)), int(ora.group(2) or 0)
        suffisso = (ora.group(3) or "").lower()
        if suffisso == "pm" and ore < 12:
            ore += 12
        if suffisso == "am" and ore == 12:
            ore = 0
        if ore > 23 or minuti > 59:
            continue
        try:
            return int(time.mktime((anno, mese, giorno, ore, minuti, 0, 0, 0, -1)))
        except (OverflowError, ValueError):
            return None
    return None


class FonteEstensione:
    """The last list each calendar tab sent; serves the Lettore like the Google API would."""

    def __init__(self):
        self._pagine = {}          # account -> (time received, list from the page)

    def ricevi(self, account, eventi, adesso=None):
        """Keeps the list and returns counts for the log (never titles)."""
        adesso = time.time() if adesso is None else adesso
        account = str(account or "?")[:120]
        pulite = [e for e in (eventi or []) if isinstance(e, dict) and e.get("id")][:200]
        self._pagine[account] = (adesso, pulite)
        rossi = [e for e in pulite if e_rosso(e.get("colore"))]
        colori = {}
        # calibration (#70): the colour of the maintainer's test event «Prova Ciro» (title chosen by him)
        prova = [[str(e.get("colore") or "nessuno")[:30], inizio_da_etichetta(e.get("testo")),
                  re.sub(r"[A-Za-zÀ-ÿ]", "x", str(e.get("testo") or ""))[:120]] for e in pulite
                 if "prova ciro" in str(e.get("testo") or "").lower()]
        for evento in pulite:
            colore = str(evento.get("colore") or "nessuno")[:30]
            colori[colore] = colori.get(colore, 0) + 1
        return {"eventi": len(pulite), "rossi": len(rossi),
                "rossi_con_ora": sum(1 for e in rossi if inizio_da_etichetta(e.get("testo"))),
                "con_ora": sum(1 for e in pulite if inizio_da_etichetta(e.get("testo"))),
                "colori": dict(sorted(colori.items(), key=lambda kv: -kv[1])[:8]),
                **({"colore_prova_ciro": prova} if prova else {})}

    def account(self, adesso=None):
        adesso = time.time() if adesso is None else adesso
        return {a: {"calendari": [PAGINA]} for a, (quando, _) in self._pagine.items() if adesso - quando < 86400}

    def scarica(self, account, calendario, time_min, time_max):
        quando, eventi = self._pagine.get(account, (0, []))
        if time.time() - quando > SILENZIO_PAGINA:
            raise TimeoutError("scheda del calendario chiusa o ferma")
        voci = []
        for evento in eventi:
            inizio = inizio_da_etichetta(evento.get("testo"))
            if inizio is None:
                continue
            voci.append({"id": str(evento["id"])[:200], "status": "confirmed",
                         "colorId": ROSSO if e_rosso(evento.get("colore")) else "",
                         "summary": titolo_da_etichetta(evento.get("testo")),
                         "start": {"dateTime": rfc3339(inizio)}})
        return {"items": voci}


def titolo_da_etichetta(testo):
    """The title is the first part of the label that is not a time: «15:30 - 16:00, Call, ...»."""
    for parte in (testo or "").split(","):
        parte = parte.strip()
        if parte and not ORARIO_RE.fullmatch(parte):
            return parte[:120]
    return ""


# «15:30 - 16:00», «dalle 15:30 alle 16», «3:30pm to 4pm»: a time or a time range, not a title
_ORA = r"\d{1,2}(?:[:.]\d{2})?\s*(?:am|pm)?"
ORARIO_RE = re.compile(r"(?:dalle\s+|from\s+)?%s(?:\s*(?:-|–|—|to|alle|a)\s*%s)?" % (_ORA, _ORA), re.I)
