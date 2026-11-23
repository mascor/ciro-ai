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
