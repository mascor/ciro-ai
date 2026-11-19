"""Google Chat in Ciro: the unread conversations sent by the "Ciro Agente" extension.

The extension, in every Chrome profile, reads the unread conversations from the Chat
page (one entry per conversation: id, direct or space, the visible lines) and sends
the full list every 20 seconds. A conversation that is no longer in the list was read
in Chat and leaves Ciro too. Only direct messages go to the model, to judge whether
they are urgent and need an answer (the user's choice, 19/11/2026); spaces stay on the
panel. Stored next to Ciro's settings, never in the repository.
"""

import json
import re
import threading
import time
from pathlib import Path

DURATA = 2 * 3600          # a conversation leaves the panel after 2 hours
ASSENTE = 5 * 60           # a profile silent for 5 minutes: its Chat tab is closed
PROMEMORIA = 15 * 60       # urgent and unanswered: reminded every 15 minutes
FALLITA_DOPO = 2 * 60      # a profile whose Chat list is not found for 2 minutes: shown as a failed read

_TECNICHE = re.compile(
    r"^(?:\d{1,2}[:.]\d{2}|\d+|unread|non lett\w*|oggi|ieri|today|yesterday|"
    r"lun|mar|mer|gio|ven|sab|dom|mon|tue|wed|thu|fri|sat|sun|"
    r"\d{1,2}\s+\w{3,9}(?:\s+\d{4})?|\w{3,9}\s+\d{1,2}(?:,\s*\d{4})?|"
    r"(?:attivato da|activated by|anche|also)\b.*)$", re.I)


def estrai(righe):
    """(name, text) from the visible lines of a conversation in the Chat list."""
    pulite = [r.strip() for r in righe or [] if r and r.strip()]
    if not pulite:
        return "", ""
    nome = pulite[0]
    resto = [r for r in pulite[1:] if not _TECNICHE.match(r)]
    return nome, (resto[0] if resto else "")


PROMPT_URGENZA = """Sei il filtro dei messaggi di Google Chat di un imprenditore molto impegnato.
Decidi se questo messaggio diretto e' urgente (va gestito oggi, blocca qualcuno, scadenza vicina,
problema con un cliente) e se il mittente aspetta una sua risposta.
Rispondi SOLO con un oggetto JSON: {"urgente": true|false, "risposta": true|false, "motivo": "<al massimo 10 parole>"}

Mittente: %s
Messaggio: %s"""

PROMPT_URGENZA_EN = """You filter the Google Chat messages of a very busy business owner.
Decide whether this direct message is urgent (to handle today, it blocks someone, a close deadline,
a problem with a customer) and whether the sender is waiting for his answer.
Answer ONLY with a JSON object: {"urgente": true|false, "risposta": true|false, "motivo": "<at most 10 words>"}

Sender: %s
Message: %s"""


def valuta_urgenza(voce, chiedi, inglese=False):
    """{"urgente", "risposta", "motivo"} from the model, or None (no answer, bad JSON).
    Only the sender's name and the text go to the model, never the account."""
    prompt = (PROMPT_URGENZA_EN if inglese else PROMPT_URGENZA) % (voce.get("nome") or "?", voce.get("testo") or "")
    try:
        uscita = chiedi(prompt) or ""
        trovato = re.search(r"\{.*\}", uscita, re.S)
        dati = json.loads(trovato.group(0)) if trovato else None
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(dati, dict) or not isinstance(dati.get("urgente"), bool):
        return None
    return {"urgente": dati["urgente"], "risposta": bool(dati.get("risposta")),
            "motivo": str(dati.get("motivo") or "")[:120]}


class Chat:
    def __init__(self, percorso):
        self._percorso = percorso      # a function: the path can change (tests)
        self._lock = threading.Lock()

    def _leggi(self):
        try:
            dati = json.loads(Path(self._percorso()).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            dati = {}
        dati.setdefault("conversazioni", {})
        dati.setdefault("account", {})
        dati.setdefault("chiuse", {})
        dati.setdefault("letture", {})     # account -> {"ok": bool, "dal": first failure}
        return dati

    def _scrivi(self, dati):
        try:
            Path(self._percorso()).write_text(json.dumps(dati, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass

    def aggiorna(self, account, conversazioni, adesso=None):
        """The unread list of one profile replaces the previous one. Returns the
        conversations that are new or have a new text (to judge)."""
        adesso = time.time() if adesso is None else adesso
        account = str(account or "?")
        nuove = []
        with self._lock:
            dati = self._leggi()
            dati["account"][account] = adesso
            dati["letture"][account] = {"ok": True, "dal": None}
            presenti = set()
            for conv in conversazioni or []:
                ident = str(conv.get("conversazione") or "")
                if not ident:
                    continue
                chiave = account + "|" + ident
                presenti.add(chiave)
                nome, testo = estrai(conv.get("righe"))
                if dati["chiuse"].get(chiave) == testo:
                    continue   # the user said «letto»: back only with a new text
                vecchia = dati["conversazioni"].get(chiave)
                if vecchia and vecchia.get("testo") == testo:
                    continue
                voce = {"chiave": chiave, "account": account, "conversazione": ident,
                        "diretto": ident.startswith("dm/"), "nome": nome, "testo": testo,
                        "visto": adesso, "urgente": None, "risposta": None, "motivo": ""}
                dati["conversazioni"][chiave] = voce
                nuove.append(dict(voce))
            for chiave in [k for k, v in dati["conversazioni"].items()
                           if v.get("account") == account and k not in presenti]:
                del dati["conversazioni"][chiave]      # read in Chat
            for chiave in [k for k in dati["chiuse"] if k.startswith(account + "|") and k not in presenti]:
                del dati["chiuse"][chiave]
            self._scrivi(dati)
        return nuove

    def lettura_fallita(self, account, adesso=None):
        """The extension did not find the unread list: this is not «no messages».
        The conversations already known stay; the profile is marked as failing."""
        adesso = time.time() if adesso is None else adesso
        account = str(account or "?")
        with self._lock:
            dati = self._leggi()
            dati["account"][account] = adesso
            lettura = dati["letture"].get(account) or {}
            if lettura.get("ok", True) or not lettura.get("dal"):
                dati["letture"][account] = {"ok": False, "dal": adesso}
                self._scrivi(dati)

    def letture_fallite(self, adesso=None):
        """{account: seconds since the reads started failing}, only past FALLITA_DOPO."""
        adesso = time.time() if adesso is None else adesso
        fallite = {}
        for account, lettura in self._leggi()["letture"].items():
            if not lettura.get("ok", True) and lettura.get("dal") and adesso - lettura["dal"] >= FALLITA_DOPO:
                fallite[account] = int(adesso - lettura["dal"])
        return fallite

    def imposta_urgenza(self, chiave, esito):
        with self._lock:
            dati = self._leggi()
            voce = dati["conversazioni"].get(chiave)
            if voce is None:
                return
            if esito:
                voce.update(urgente=esito["urgente"], risposta=esito["risposta"], motivo=esito["motivo"])
            self._scrivi(dati)

    def aperte(self, adesso=None):
        adesso = time.time() if adesso is None else adesso
        voci = [v for v in self._leggi()["conversazioni"].values() if adesso - v.get("visto", adesso) <= DURATA]
        return sorted(voci, key=lambda v: v.get("visto", 0))

    def chiudi(self, chiave):
        """«letto il tre»: leaves the panel until a new message arrives in that conversation."""
        with self._lock:
            dati = self._leggi()
            voce = dati["conversazioni"].pop(chiave, None)
            if voce is None:
                return False
            dati["chiuse"][chiave] = voce.get("testo")
            self._scrivi(dati)
            return True

    def account_assenti(self, adesso=None):
        adesso = time.time() if adesso is None else adesso
        return sorted(a for a, quando in self._leggi()["account"].items() if adesso - quando > ASSENTE)
