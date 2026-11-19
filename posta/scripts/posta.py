#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Posta su file tra OpenCode (gestore) e le sessioni Claude Code (sviluppatori).

Una casella per destinatario sotto la radice (predefinita ~/.posta-agenti):
    <radice>/<casella>/nuovi/   messaggi da leggere
    <radice>/<casella>/letti/   messaggi archiviati

Solo libreria standard, compatibile con /usr/bin/python3 (Python 3.9).
Nessuna rete, nessun modello di linguaggio.

La radice si puo' cambiare con la variabile d'ambiente POSTA_RADICE.
"""

import argparse
import errno
import fcntl
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
from datetime import datetime
from pathlib import Path

RADICE_PREDEFINITA = Path.home() / ".posta-agenti"

TIPI = ("richiesta", "risposta", "decisione", "avviso")
AZIONI = ("decisione", "conferma-server", "accesso", "risposta", "nessuna",
          "non-letto")
AZIONI_URGENTI = ("decisione", "conferma-server", "accesso", "non-letto")
AZIONI_LEGGIBILI = {
    "decisione": "decisione",
    "conferma-server": "conferma sul server",
    "accesso": "accesso",
    "risposta": "risposta",
    "nessuna": "nessuna",
    "non-letto": "messaggio non letto",
}
FRASI = {
    "decisione": "Progetto {p}. Serve una tua decisione.",
    "conferma-server": "Progetto {p}. Serve una tua conferma sul server.",
    "accesso": "Progetto {p}. Serve il tuo accesso con le credenziali.",
    "risposta": "Progetto {p}. \u00c8 arrivata una risposta.",
    "nessuna": "Progetto {p}.",
    "non-letto": "Progetto {p}. Un messaggio non \u00e8 stato letto: "
                 "la sessione forse non ascolta.",
}
NOME_CASELLA_RE = re.compile(r"^[A-Za-z0-9_-]{1,120}$")
OGGETTO_MAX = 200
SLUG_MAX = 40
INTERVALLO_PREDEFINITO = 5.0
SOGLIA_FERMI_PREDEFINITA = 300.0
STATO_AVVISATI = ".avvisati.json"
VOCI_STATO_MAX = 2000
SUONO_PREDEFINITO = "/System/Library/Sounds/Sosumi.aiff"
VOCE_PREDEFINITA = "Alice"

# Lock che mette le voci in fila: un solo processo suona e parla per volta.
LOCK_VOCE_NOME = ".voce.lock"
ATTESA_LOCK_PREDEFINITA = 120.0
PASSO_LOCK = 0.05

# Voce lanciata dal comando "parla": il PID del processo say sta qui, cosi' una
# voce nuova puo' interrompere quella di prima.
PID_PARLA_NOME = ".parla.pid"
ATTESA_SAY_PARLA = 300.0
TESTO_PARLA_MAX = 2000

# Ordine delle azioni urgenti, dalla piu' importante alla meno importante.
ORDINE_AZIONI_URGENTI = ("conferma-server", "accesso", "decisione", "non-letto")
FRASI_URGENTI = {
    "conferma-server": "Serve una tua conferma sul server.",
    "accesso": "Serve il tuo accesso con le credenziali.",
    "decisione": "Serve una tua decisione.",
    "non-letto": "Un messaggio non \u00e8 stato letto: la sessione forse non ascolta.",
}

# Registro unico degli eventi della posta: una riga per evento, in append.
REGISTRO_NOME = "registro.log"
REGISTRO_LIMITE = 5 * 1024 * 1024
DETTAGLIO_MAX = 120

CODICE_ERRORE = 2
CODICE_TIMEOUT = 3
# "parla --se-libero" con la voce gia' occupata: esce senza parlare.
CODICE_VOCE_OCCUPATA = 3
CODICE_INTERRUZIONE = 130
# Structured questions: state transition not allowed (nothing written).
CODICE_STATO = 4

OPERAZIONI = ("scelta", "deploy-prova", "deploy-produzione", "cancellazione",
              "database", "configurazione", "credenziali", "servizio-esterno",
              "abbonamento", "altro", "permesso")
AMBIENTI = ("locale", "prova", "produzione")
LETTERA_RE = re.compile(r"^[A-Z]$")
# "utente": the user answered; "regola:<id>": a saved rule answered
MOTIVO_RE = re.compile(r"^(utente|regola:[A-Za-z0-9_-]{1,80})$")
# Placeholder in `extra`: replaced by the ID of the message being written.
ID_MESSAGGIO = object()


class ErrorePosta(Exception):
    """Errore previsto: messaggio per l'utente, codice 2."""


class ErroreStato(ErrorePosta):
    """Passaggio di stato non ammesso per una domanda strutturata: codice 4."""


# ---------------------------------------------------------------- utilita' base


def _radice():
    """Cartella radice della posta (POSTA_RADICE vince sul valore predefinito)."""
    valore = os.environ.get("POSTA_RADICE")
    if valore:
        return Path(valore).expanduser()
    return RADICE_PREDEFINITA


def valida_casella(nome):
    """Accetta solo lettere, numeri, _ e -: niente / ne' .."""
    if not isinstance(nome, str):
        raise ErrorePosta("nome di casella non valido")
    nome = nome.strip()
    if not nome or not NOME_CASELLA_RE.match(nome):
        raise ErrorePosta(
            "nome di casella non valido: %r (ammessi solo lettere, numeri, _ e -)" % (nome,)
        )
    return nome


def _percorso_sicuro(*parti):
    """Compone un percorso sotto la radice e verifica che ci resti davvero."""
    radice = _radice()
    percorso = radice.joinpath(*parti)
    try:
        radice_reale = radice.resolve()
        percorso_reale = percorso.resolve()
    except OSError:
        raise ErrorePosta("percorso non risolvibile: %s" % percorso)
    if percorso_reale != radice_reale and radice_reale not in percorso_reale.parents:
        raise ErrorePosta("percorso fuori dalla radice della posta: %s" % percorso)
    return percorso


def _crea_cartella(percorso):
    percorso.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(percorso, 0o700)
    except OSError:
        pass


def cartella_casella(casella):
    """Crea (se serve) la radice e la casella con nuovi/ e letti/, permessi 700."""
    nome = valida_casella(casella)
    _crea_cartella(_radice())
    base = _percorso_sicuro(nome)
    _crea_cartella(base)
    for sotto in ("nuovi", "letti"):
        _crea_cartella(base / sotto)
    return base


def _adesso():
    return datetime.now().astimezone()


def _marca_tempo(quando):
    return quando.strftime("%Y%m%d-%H%M%S")


def _data_iso(quando):
    return quando.isoformat(timespec="seconds")


def slug(oggetto, massimo=SLUG_MAX):
    """Minuscolo, solo a-z0-9 e trattini, massimo 40 caratteri."""
    testo = oggetto or ""
    testo = unicodedata.normalize("NFKD", testo)
    testo = "".join(c for c in testo if not unicodedata.combining(c))
    testo = testo.lower()
    testo = re.sub(r"[^a-z0-9]+", "-", testo).strip("-")
    testo = testo[:massimo].strip("-")
    return testo or "messaggio"


def _una_riga(testo):
    return " ".join(str(testo).replace("\r", "\n").split("\n")).strip()


def _escape_osascript(testo):
    """Escape per stringhe tra virgolette negli script osascript."""
    testo = _una_riga(testo)
    return testo.replace("\\", "\\\\").replace('"', '\\"')


def scrivi_atomico(destinazione, contenuto, modo=0o600):
    """Scrive su un temporaneo nascosto nella stessa cartella e poi os.replace."""
    destinazione = Path(destinazione)
    cartella = destinazione.parent
    fd, temporaneo = tempfile.mkstemp(prefix=".tmp-posta-", dir=str(cartella))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as scrittura:
            scrittura.write(contenuto)
            scrittura.flush()
            os.fsync(scrittura.fileno())
        os.chmod(temporaneo, modo)
        os.replace(temporaneo, destinazione)
    except BaseException:
        try:
            os.unlink(temporaneo)
        except OSError:
            pass
        raise


# ------------------------------------------------------------------ registro


def _percorso_registro():
    """File del registro (POSTA_REGISTRO per i test)."""
    valore = os.environ.get("POSTA_REGISTRO")
    if valore:
        return Path(valore).expanduser()
    return _radice() / REGISTRO_NOME


def _dettaglio(valore):
    """Valore breve e senza spazi per la quinta colonna del registro."""
    testo = _una_riga("-" if valore is None else valore)
    testo = re.sub(r"\s+", "_", testo)
    if len(testo) > DETTAGLIO_MAX:
        testo = testo[:DETTAGLIO_MAX]
    return testo or "-"


def _ruota_registro(fd, percorso):
    """Oltre 5 MB il registro diventa registro.log.1 (una sola copia vecchia).

    Va chiamata con il lock preso: True se ha ruotato, False se non serviva.
    """
    try:
        if os.fstat(fd).st_size <= REGISTRO_LIMITE:
            return False
    except OSError:
        return False
    try:
        os.replace(str(percorso), str(percorso) + ".1")
        return True
    except OSError:
        return False


def scrivi_registro(evento, casella="-", identificativo="-", dettagli=None):
    """Aggiunge una riga al registro, in append e con flock sul file."""
    riga = "\t".join([
        _data_iso(_adesso()),
        _dettaglio(evento),
        _dettaglio(casella),
        _dettaglio(identificativo),
        " ".join("%s=%s" % (chiave, _dettaglio(valore))
                 for chiave, valore in (dettagli or {}).items()) or "-",
    ])
    percorso = _percorso_registro()
    percorso.parent.mkdir(parents=True, exist_ok=True)
    dati = (riga + "\n").encode("utf-8")
    # Due giri al massimo: il secondo scrive nel registro nuovo, dopo la rotazione.
    for _ in range(2):
        fd = os.open(str(percorso), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        ruotato = False
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            try:
                ruotato = _ruota_registro(fd, percorso)
                if not ruotato:
                    os.write(fd, dati)
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)
        if not ruotato:
            return


def registra(evento, casella="-", identificativo="-", dettagli=None):
    """Scrive un evento nel registro senza mai far fallire il comando."""
    try:
        scrivi_registro(evento, casella, identificativo, dettagli)
    except Exception:
        pass


# ------------------------------------------------------------------ messaggi


def _componi(identificativo, da, a, data_iso, tipo, rif, urgente, azione, oggetto, testo,
             extra=None):
    righe = [
        "ID: %s" % identificativo,
        "DA: %s" % da,
        "A: %s" % a,
        "DATA: %s" % data_iso,
        "TIPO: %s" % tipo,
        "RIF: %s" % (rif or ""),
        "URGENTE: %s" % ("si" if urgente else "no"),
        "AZIONE: %s" % azione,
        "OGGETTO: %s" % _una_riga(oggetto),
    ]
    for chiave, valore in (extra or {}).items():
        if valore is ID_MESSAGGIO:
            valore = identificativo
        righe.append("%s: %s" % (chiave, _una_riga(valore)))
    righe.append("---")
    corpo = testo.rstrip("\n")
    contenuto = "\n".join(righe) + "\n"
    if corpo:
        contenuto += corpo + "\n"
    return contenuto


def _nome_libero(cartella, base, estensione=".md"):
    """Nome file libero: se esiste gia', aggiunge -2, -3, ... prima dell'estensione."""
    candidato = "%s%s" % (base, estensione)
    numero = 2
    while (cartella / candidato).exists():
        candidato = "%s-%d%s" % (base, numero, estensione)
        numero += 1
    return candidato


def azione_predefinita(tipo):
    """Azione dell'avviso quando il mittente non la indica."""
    if tipo == "decisione":
        return "decisione"
    if tipo == "risposta":
        return "risposta"
    return "nessuna"


def valida_azione(azione):
    """Azione ammessa, in minuscolo; errore previsto se non lo e'."""
    valore = _una_riga(azione or "").lower()
    if valore not in AZIONI:
        raise ErrorePosta(
            "azione non valida: %r (ammesse: %s)" % (azione, ", ".join(AZIONI))
        )
    return valore


def invia(da, a, tipo, oggetto, testo, rif="", urgente=False, azione=None, extra=None):
    """Scrive il messaggio nella casella nuovi/ del destinatario. Ritorna il percorso."""
    mittente = valida_casella(da)
    destinatario = valida_casella(a)
    if tipo not in TIPI:
        raise ErrorePosta("tipo non valido: %r (ammessi: %s)" % (tipo, ", ".join(TIPI)))
    if azione is None:
        azione = azione_predefinita(tipo)
    azione = valida_azione(azione)
    if rif:
        rif = str(rif).strip()
        if "/" in rif or "\\" in rif:
            raise ErrorePosta("RIF non valido: %r" % (rif,))

    casella_destinatario = cartella_casella(destinatario)
    cartella_nuovi = casella_destinatario / "nuovi"

    quando = _adesso()
    base = "%s-%s-%s" % (_marca_tempo(quando), mittente, slug(oggetto))
    nome_file = _nome_libero(cartella_nuovi, base)
    identificativo = nome_file[:-3]

    contenuto = _componi(
        identificativo, mittente, destinatario, _data_iso(quando),
        tipo, rif, urgente, azione, oggetto, testo, extra,
    )
    destinazione = cartella_nuovi / nome_file
    scrivi_atomico(destinazione, contenuto)
    registra("invia", mittente, identificativo, {
        "da": mittente, "a": destinatario, "tipo": tipo, "azione": azione,
        "urgente": "si" if urgente else "no", "rif": rif or "-",
    })

    if urgente:
        avvisa(mittente, azione_avviso(azione, tipo), _una_riga(oggetto),
               urgente=True)

    return destinazione


def leggi_intestazioni(percorso):
    """Intestazioni di un messaggio (dict) piu' il corpo in _CORPO."""
    percorso = Path(percorso)
    try:
        contenuto = percorso.read_text(encoding="utf-8")
    except OSError as errore:
        raise ErrorePosta("impossibile leggere %s: %s" % (percorso, errore))
    intestazioni = {}
    corpo = ""
    righe = contenuto.splitlines()
    for indice, riga in enumerate(righe):
        if riga.strip() == "---":
            corpo = "\n".join(righe[indice + 1:])
            break
        if ":" in riga:
            chiave, valore = riga.split(":", 1)
            intestazioni[chiave.strip().upper()] = valore.strip()
    intestazioni["_ID"] = percorso.stem
    intestazioni["_PERCORSO"] = str(percorso)
    intestazioni["_CORPO"] = corpo
    intestazioni["_CONTENUTO"] = contenuto
    return intestazioni


def _vero(valore):
    return str(valore or "").strip().lower() in ("si", "sì", "yes", "true", "1")


def _messaggi(cartella):
    """File .md in una cartella, dal piu' vecchio, ignorando i temporanei nascosti."""
    cartella = Path(cartella)
    if not cartella.is_dir():
        return []
    risultato = []
    try:
        for voce in cartella.iterdir():
            if voce.name.startswith("."):
                continue
            if voce.is_file() and voce.suffix == ".md":
                risultato.append(voce)
    except OSError as errore:
        raise ErrorePosta("impossibile leggere %s: %s" % (cartella, errore))
    risultato.sort(key=lambda p: p.name)
    return risultato


def _trova_messaggio(casella, identificativo):
    if not identificativo:
        raise ErrorePosta("ID del messaggio mancante")
    identificativo = str(identificativo).strip()
    if "/" in identificativo or "\\" in identificativo or identificativo in (".", ".."):
        raise ErrorePosta("ID non valido: %r" % (identificativo,))
    if identificativo.endswith(".md"):
        identificativo = identificativo[:-3]
    casella_base = cartella_casella(casella)
    percorso = casella_base / "nuovi" / (identificativo + ".md")
    if not percorso.is_file():
        raise ErrorePosta("messaggio non trovato: %s" % identificativo)
    return percorso


def archivia(percorso_messaggio):
    """Sposta un messaggio da nuovi/ a letti/ senza sovrascrivere."""
    percorso_messaggio = Path(percorso_messaggio)
    casella_base = percorso_messaggio.parent.parent
    destinazione_cartella = casella_base / "letti"
    _crea_cartella(destinazione_cartella)
    destinazione = destinazione_cartella / percorso_messaggio.name
    if destinazione.exists():
        destinazione = destinazione_cartella / _nome_libero(
            destinazione_cartella, percorso_messaggio.stem
        )
    os.replace(str(percorso_messaggio), str(destinazione))
    return destinazione


# -------------------------------------------------------------------- avvisi


def _eseguibile_osascript():
    return os.environ.get("POSTA_OSASCRIPT") or "/usr/bin/osascript"


def _eseguibile_afplay():
    return os.environ.get("POSTA_AFPLAY") or "/usr/bin/afplay"


def _eseguibile_say():
    return os.environ.get("POSTA_SAY") or "/usr/bin/say"


def _file_suono():
    return os.environ.get("POSTA_SUONO") or SUONO_PREDEFINITO


def _nome_voce():
    return (os.environ.get("POSTA_VOCE") or VOCE_PREDEFINITA).strip() or VOCE_PREDEFINITA


def _notifica(titolo, testo):
    """Notifica macOS senza suono proprio: il suono lo fa afplay."""
    script = 'display notification "%s" with title "%s"' % (
        _escape_osascript(testo), _escape_osascript(titolo),
    )
    subprocess.run(
        [_eseguibile_osascript(), "-e", script],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
        timeout=30,
    )


def _nome_pronunciato(progetto):
    """b2b_frontend e b2b-frontend diventano 'b2b frontend'."""
    nome = re.sub(r"[_-]+", " ", str(progetto)).strip()
    return re.sub(r"\s+", " ", nome)


def _senza_markdown(testo):
    """Toglie i segni di markdown dal testo che deve essere pronunciato."""
    testo = str(testo or "")
    testo = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", testo)   # [testo](link)
    testo = testo.replace("**", "").replace("*", "").replace("`", "")
    testo = testo.replace("#", "").replace("_", " ")
    return " ".join(testo.split())


def frase_avviso(progetto, azione):
    """Frase pronunciata dalla voce per il progetto e l'azione."""
    return FRASI[azione].format(p=_nome_pronunciato(progetto))


def _voce_esiste(voce):
    """True se 'say' conosce la voce (elenco di 'say -v ?')."""
    try:
        risultato = subprocess.run(
            [_eseguibile_say(), "-v", "?"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=10,
            universal_newlines=True,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    for riga in (risultato.stdout or "").splitlines():
        trovato = re.match(r"^(.+?)\s{2,}", riga)
        if trovato and trovato.group(1).strip().lower() == voce.strip().lower():
            return True
    return False


def _comando_voce(frase):
    voce = _nome_voce()
    if _voce_esiste(voce):
        return [_eseguibile_say(), "-v", voce, frase]
    return [_eseguibile_say(), frase]


def _esegui_audio(comando):
    """afplay/say: errori ignorati, nessuna stampa (siamo in un figlio staccato)."""
    try:
        subprocess.run(
            comando,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        pass


def _suona_file(percorso):
    """Suona un file aiff prima della voce, nello stesso processo (lock tenuto)."""
    if not percorso:
        return
    _esegui_audio([_eseguibile_afplay(), str(percorso)])


def _percorso_lock_voce():
    """File del lock delle voci (POSTA_LOCK_VOCE per i test)."""
    valore = os.environ.get("POSTA_LOCK_VOCE")
    if valore:
        return Path(valore).expanduser()
    return _radice() / LOCK_VOCE_NOME


def _percorso_errori():
    """errori.log accanto alla posta (POSTA_ERRORI_LOG per i test)."""
    valore = os.environ.get("POSTA_ERRORI_LOG")
    if valore:
        return Path(valore).expanduser()
    return _radice() / "errori.log"


def _attesa_lock():
    """Secondi di attesa massima per il lock (POSTA_LOCK_TIMEOUT per i test)."""
    valore = os.environ.get("POSTA_LOCK_TIMEOUT")
    if valore is None or not str(valore).strip():
        return ATTESA_LOCK_PREDEFINITA
    try:
        secondi = float(str(valore).strip())
    except (TypeError, ValueError):
        return ATTESA_LOCK_PREDEFINITA
    return max(0.0, secondi)


def scrivi_errore(messaggio):
    """Aggiunge una riga a errori.log senza mai far cadere l'avviso."""
    try:
        percorso = _percorso_errori()
        percorso.parent.mkdir(parents=True, exist_ok=True)
        with percorso.open("a", encoding="utf-8") as scrittura:
            scrittura.write("%s %s\n" % (_data_iso(_adesso()), _una_riga(messaggio)))
    except OSError:
        return
    registra("errore", "-", "-", {"messaggio": messaggio})


def _prendi_lock_voce(attesa=None):
    """Lock esclusivo sul file della voce: (fd, None) oppure (None, motivo).

    L'attesa e' bloccante ma rinuncia dopo 'attesa' secondi (120 di default).
    """
    if attesa is None:
        attesa = _attesa_lock()
    percorso = _percorso_lock_voce()
    try:
        percorso.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(percorso), os.O_RDWR | os.O_CREAT, 0o600)
    except OSError as errore:
        return None, "lock non apribile (%s)" % errore
    scadenza = time.monotonic() + attesa
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return fd, None
        except OSError as errore:
            if errore.errno not in (errno.EACCES, errno.EAGAIN):
                os.close(fd)
                return None, "lock non ottenibile (%s)" % errore
        if time.monotonic() >= scadenza:
            os.close(fd)
            return None, "lock occupato da oltre %d secondi" % int(attesa)
        time.sleep(PASSO_LOCK)


def _rilascia_lock_voce(fd):
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
    except OSError:
        pass
    try:
        os.close(fd)
    except OSError:
        pass


def parla_in_fila(frase, urgente=False, attesa=None):
    """Suona e parla tenendo il lock: due voci non si sovrappongono mai.

    Lo usa il figlio staccato _suona. False se il lock non e' arrivato in tempo
    (in quel caso l'errore finisce su errori.log e non si parla).
    """
    fd, motivo = _prendi_lock_voce(attesa)
    if fd is None:
        scrivi_errore("voce non pronunciata (%s): %s" % (motivo, frase))
        return False
    try:
        suona(frase, urgente=urgente)
        return True
    finally:
        _rilascia_lock_voce(fd)


def suona(frase, urgente=False):
    """Esegue suono e voce nel processo corrente (lo usa il figlio staccato)."""
    frase = _senza_markdown(frase)
    suono = _file_suono()
    if urgente:
        for _ in range(2):
            _esegui_audio([_eseguibile_afplay(), suono])
            _esegui_audio([_eseguibile_afplay(), suono])
            _esegui_audio(_comando_voce(frase))
            time.sleep(1.0)
    else:
        _esegui_audio([_eseguibile_afplay(), suono])
        _esegui_audio(_comando_voce(frase))


def _suona_staccato(frase, urgente):
    """Lancia un figlio staccato che suona e parla: lo script principale esce subito."""
    python = sys.executable or "/usr/bin/python3"
    comando = [python, os.path.abspath(__file__), "_suona", "--frase", frase]
    if urgente:
        comando.append("--urgente")
    figlio = subprocess.Popen(
        comando,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        close_fds=True,
    )
    # Raccolglie il figlio quando ha finito, senza aspettarlo: se il processo
    # principale esce prima, il figlio staccato continua da solo.
    try:
        threading.Thread(target=figlio.wait, daemon=True).start()
    except RuntimeError:
        pass


def _percorso_pid_parla():
    """File del PID della voce lanciata con 'parla' (POSTA_PID_PARLA per i test)."""
    valore = os.environ.get("POSTA_PID_PARLA")
    if valore:
        return Path(valore).expanduser()
    return _radice() / PID_PARLA_NOME


def scrivi_pid_parla(pid):
    """Scrive il PID del processo say in corso (errori ignorati)."""
    try:
        percorso = _percorso_pid_parla()
        percorso.parent.mkdir(parents=True, exist_ok=True)
        percorso.write_text("%d\n" % int(pid), encoding="utf-8")
    except (OSError, TypeError, ValueError):
        pass


def leggi_pid_parla():
    """PID scritto da 'parla', oppure None."""
    try:
        testo = _percorso_pid_parla().read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not testo.isdigit():
        return None
    return int(testo)


def rimuovi_pid_parla(pid):
    """Toglie il file del PID solo se contiene ancora il PID indicato."""
    if leggi_pid_parla() != int(pid):
        return
    try:
        _percorso_pid_parla().unlink()
    except OSError:
        pass


def _comando_di(pid):
    """Riga di comando del processo (ps command=), o stringa vuota."""
    try:
        risultato = subprocess.run(
            ["/bin/ps", "-p", str(int(pid)), "-o", "command="],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=10,
            universal_newlines=True,
        )
    except (OSError, subprocess.SubprocessError, TypeError, ValueError):
        return ""
    righe = [riga.strip() for riga in (risultato.stdout or "").splitlines()
             if riga.strip()]
    return righe[0] if righe else ""


def _e_la_voce(pid):
    """True se il PID e' ancora il processo che pronuncia (say o il finto say)."""
    comando = _comando_di(pid)
    if not comando:
        return False
    attesi = {"say", os.path.basename(_eseguibile_say())}
    for pezzo in comando.split():
        if os.path.basename(pezzo) in attesi:
            return True
    return False


def interrompi_parla_precedente():
    """Ferma la voce lanciata prima con --interrompi-precedente, se parla ancora.

    Uccide solo il PID salvato in .parla.pid e solo se il suo comando e' ancora
    say: un PID riciclato da un altro programma non viene toccato.
    """
    pid = leggi_pid_parla()
    if pid is None or not _e_la_voce(pid):
        return False
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return False
    return True


def _pronuncia_con_pid(frase):
    """Esegue solo 'say' (niente suono) e tiene il PID in .parla.pid."""
    try:
        processo = subprocess.Popen(
            _comando_voce(frase),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )
    except (OSError, subprocess.SubprocessError) as errore:
        scrivi_errore("voce non pronunciata (%s): %s" % (errore, frase))
        return
    scrivi_pid_parla(processo.pid)
    try:
        processo.wait(timeout=ATTESA_SAY_PARLA)
    except subprocess.TimeoutExpired:
        try:
            processo.kill()
            processo.wait(timeout=10)
        except (OSError, subprocess.SubprocessError):
            pass
    finally:
        rimuovi_pid_parla(processo.pid)


def parla_solo_in_fila(frase, suono=None, attesa=None):
    """Pronuncia solo la frase tenendo il lock delle voci (nessun suono).

    Lo usa il figlio staccato _parla: la voce nuova aspetta che quella in corso
    abbia finito (o sia stata interrotta).
    """
    inizio = time.monotonic()
    fd, motivo = _prendi_lock_voce(attesa)
    attesa_lock = time.monotonic() - inizio
    registra("parla", "-", "-", {"lunghezza": len(frase),
                                "attesa": "%.2f" % attesa_lock})
    if fd is None:
        scrivi_errore("voce non pronunciata (%s): %s" % (motivo, frase))
        return False
    try:
        _suona_file(suono)
        _pronuncia_con_pid(frase)
        return True
    finally:
        _rilascia_lock_voce(fd)


def parla_se_libero(frase, suono=None):
    """Parla solo se il lock delle voci e' libero: mai in coda.

    Prova il lock in modo non bloccante (LOCK_EX|LOCK_NB): se un'altra voce lo
    tiene esce subito con CODICE_VOCE_OCCUPATA senza suonare e senza parlare.
    Suono e voce restano nello stesso processo, sotto lo stesso lock.
    """
    fd, motivo = _prendi_lock_voce(0.0)
    if fd is None:
        registra("parla-occupata", "-", "-", {"motivo": motivo})
        return CODICE_VOCE_OCCUPATA
    try:
        registra("parla", "-", "-", {
            "lunghezza": len(frase), "attesa": "0.00",
            "suono": "si" if suono else "no",
        })
        _suona_file(suono)
        _pronuncia_con_pid(frase)
        return 0
    finally:
        _rilascia_lock_voce(fd)


def _parla_staccato(frase, suono=None):
    """Lancia un figlio staccato che pronuncia la frase: lo script esce subito."""
    python = sys.executable or "/usr/bin/python3"
    comando = [python, os.path.abspath(__file__), "_parla", "--frase", frase]
    if suono:
        comando += ["--suono", str(suono)]
    figlio = subprocess.Popen(
        comando,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        close_fds=True,
    )
    try:
        threading.Thread(target=figlio.wait, daemon=True).start()
    except RuntimeError:
        pass


def _main_parla(argomenti):
    """Riga di comando interna del figlio staccato (non compare in --help)."""
    parser = argparse.ArgumentParser(prog="posta.py _parla")
    parser.add_argument("--frase", required=True)
    parser.add_argument("--suono", default=None)
    args = parser.parse_args(argomenti)
    if parla_solo_in_fila(args.frase, suono=args.suono):
        return 0
    return CODICE_ERRORE


def cmd_parla(args):
    """Pronuncia solo il testo (niente notifica).

    Con --se-libero non mette la voce in coda: se il lock e' occupato esce
    subito con codice 3. Con --suono fa sentire un aiff prima della voce,
    sempre sotto lo stesso lock.
    """
    testo = args.testo
    if testo is None or not str(testo).strip():
        testo = sys.stdin.read()
    frase = _senza_markdown(testo)
    if not frase:
        raise ErrorePosta("testo da pronunciare mancante")
    if len(frase) > TESTO_PARLA_MAX:
        frase = frase[:TESTO_PARLA_MAX]
    if args.interrompi_precedente:
        interrompi_parla_precedente()
    if args.se_libero:
        return parla_se_libero(frase, suono=args.suono)
    _parla_staccato(frase, suono=args.suono)
    return 0


def _valida_progetto(progetto):
    nome = _una_riga(progetto)
    if not nome:
        raise ErrorePosta("nome di progetto mancante")
    if len(nome) > 120:
        raise ErrorePosta("nome di progetto troppo lungo: %r" % (nome[:40],))
    return nome


def avvisa_generico(titolo, testo, frase, urgente=None):
    """Notifica con titolo e frase scelti da chi chiama (avvisi raggruppati)."""
    titolo = _una_riga(titolo) or "Posta"
    frase = _senza_markdown(frase) or titolo
    messaggio = _una_riga(testo) or frase
    _notifica(titolo, messaggio)
    _suona_staccato(frase, bool(urgente))


def avvisa(progetto, azione="nessuna", testo="", urgente=None):
    """Notifica macOS con titolo PROGETTO - azione, poi suono e voce staccati."""
    nome = _valida_progetto(progetto)
    azione = valida_azione(azione)
    frase = frase_avviso(nome, azione)
    messaggio = _una_riga(testo) or frase
    titolo = "%s \u00b7 %s" % (_nome_pronunciato(nome).upper(),
                               AZIONI_LEGGIBILI[azione])
    if urgente is None:
        urgente = azione in AZIONI_URGENTI
    avvisa_generico(titolo, messaggio, frase, urgente=bool(urgente))
    registra("avvisa", nome, "-", {
        "progetto": nome, "azione": azione,
        "urgente": "si" if urgente else "no", "raggruppati": 1,
    })


def frase_gruppo(progetti, azioni, urgenti=None):
    """Frase vocale di un giro con piu' messaggi.

    "<N> messaggi nuovi: <progetto1>, <progetto2>." e, se c'e' almeno un
    urgente, la frase dell'azione urgente piu' importante (conferma-server,
    accesso, decisione, non-letto).
    """
    nomi = []
    for progetto in progetti or []:
        pronunciato = _nome_pronunciato(progetto)
        if pronunciato and pronunciato not in nomi:
            nomi.append(pronunciato)
    totale = len(list(progetti or []))
    frase = "%d messaggi nuovi: %s." % (totale, ", ".join(nomi))
    azioni = list(azioni or [])
    if urgenti is None:
        urgenti = [azione in AZIONI_URGENTI for azione in azioni]
    urgenti = list(urgenti)
    if not any(urgenti):
        return frase
    scelta = "decisione"
    for candidata in ORDINE_AZIONI_URGENTI:
        if any(u and a == candidata for u, a in zip(urgenti, azioni)):
            scelta = candidata
            break
    return frase + " " + FRASI_URGENTI[scelta]


def avvisa_messaggi(messaggi):
    """Un solo avviso per giro: con un messaggio si comporta come avvisa()."""
    voci = [m for m in (messaggi or []) if m]
    if not voci:
        return
    if len(voci) == 1:
        voce = voci[0]
        avvisa(voce.get("progetto") or "?", voce.get("azione") or "nessuna",
               voce.get("testo") or "", urgente=bool(voce.get("urgente")))
        return
    progetti = [v.get("progetto") or "?" for v in voci]
    azioni = [v.get("azione") or "nessuna" for v in voci]
    urgenti = [bool(v.get("urgente")) for v in voci]
    frase = frase_gruppo(progetti, azioni, urgenti)
    avvisa_generico("Posta: %d messaggi" % len(voci), frase, frase,
                    urgente=any(urgenti))
    registra("avvisa", "gruppo", "-", {
        "progetto": ",".join(progetti), "azione": "gruppo",
        "urgente": "si" if any(urgenti) else "no", "raggruppati": len(voci),
    })


def _main_suona(argomenti):
    """Riga di comando interna del figlio staccato (non compare in --help)."""
    parser = argparse.ArgumentParser(prog="posta.py _suona")
    parser.add_argument("--frase", required=True)
    parser.add_argument("--urgente", action="store_true")
    args = parser.parse_args(argomenti)
    if parla_in_fila(args.frase, urgente=bool(args.urgente)):
        return 0
    return CODICE_ERRORE


# ------------------------------------------------------------------ sorveglia


def _percorso_stato():
    return _percorso_sicuro(STATO_AVVISATI)


def carica_avvisati(percorso):
    """Memoria degli avvisi gia' mandati; un file malformato vale come vuoto."""
    percorso = Path(percorso)
    if not percorso.is_file():
        return {}
    try:
        with percorso.open("r", encoding="utf-8") as lettura:
            dati = json.load(lettura)
    except (OSError, ValueError):
        return {}
    if not isinstance(dati, dict):
        return {}
    return {str(chiave): valore for chiave, valore in dati.items()}


def salva_avvisati(percorso, visti):
    percorso = Path(percorso)
    voci = list(visti.items())
    if len(voci) > VOCI_STATO_MAX:
        voci = voci[-VOCI_STATO_MAX:]
        visti = dict(voci)
    _crea_cartella(percorso.parent)
    scrivi_atomico(
        percorso, json.dumps(visti, ensure_ascii=False, indent=0, sort_keys=True) + "\n"
    )


def azione_messaggio(intestazioni):
    """Azione dichiarata nell'intestazione AZIONE, con compatibilita' per i vecchi messaggi."""
    dichiarata = _una_riga(intestazioni.get("AZIONE", "")).lower()
    if dichiarata in AZIONI:
        return dichiarata
    testo = "%s\n%s" % (intestazioni.get("OGGETTO", ""), intestazioni.get("_CORPO", ""))
    if "conferma sul server" in testo.lower():
        return "conferma-server"
    return "nessuna"


def azione_avviso(azione, tipo):
    """Azione effettiva dell'avviso per un messaggio destinato a opencode.

    Le richieste esplicite (decisione, conferma-server, accesso) vincono sempre.
    Altrimenti conta il TIPO: un messaggio arrivato al gestore e' almeno una
    risposta da leggere, mai un semplice "Progetto X." senza seguito.
    """
    if azione in ("decisione", "conferma-server", "accesso"):
        return azione
    tipo = _una_riga(tipo).lower()
    if tipo == "risposta":
        return "risposta"
    if tipo == "decisione":
        return "decisione"
    return "risposta"


def azione_avviso_messaggio(intestazioni):
    """Azione dell'avviso calcolata dalle intestazioni di un messaggio."""
    return azione_avviso(azione_messaggio(intestazioni),
                         intestazioni.get("TIPO", ""))


def _soglia_fermi():
    """Secondi oltre i quali un messaggio in nuovi/ e' considerato fermo."""
    valore = os.environ.get("POSTA_SOGLIA_FERMI")
    if valore is None or not str(valore).strip():
        return SOGLIA_FERMI_PREDEFINITA
    try:
        secondi = float(str(valore).strip())
    except (TypeError, ValueError):
        return SOGLIA_FERMI_PREDEFINITA
    if secondi < 0:
        return 0.0
    return secondi


def caselle_sessioni():
    """Caselle delle sessioni: sottocartelle della radice tranne opencode, bin, domande e nascoste."""
    radice = _radice()
    try:
        voci = sorted(radice.iterdir(), key=lambda p: p.name)
    except OSError:
        return []
    nomi = []
    for voce in voci:
        nome = voce.name
        if nome in ("opencode", "bin", "domande") or nome.startswith("."):
            continue
        if not NOME_CASELLA_RE.match(nome):
            continue
        try:
            if voce.is_symlink() or not voce.is_dir():
                continue
        except OSError:
            continue
        nomi.append(nome)
    return nomi


def _avvisi_fermi(visti, soglia=None, adesso=None):
    """Avvisi (non ancora mandati) per i messaggi rimasti in nuovi/ oltre la soglia.

    La chiave nello stato e' "fermo:<casella>:<ID>", distinta da quella dei
    messaggi di opencode (che e' il solo ID). Aggiorna 'visti'.
    """
    if soglia is None:
        soglia = _soglia_fermi()
    if adesso is None:
        adesso = time.time()
    avvisi = []
    for casella in caselle_sessioni():
        try:
            cartella = _percorso_sicuro(casella, "nuovi")
            percorsi = _messaggi(cartella)
        except ErrorePosta as errore:
            print("errore: %s" % errore, file=sys.stderr)
            continue
        for percorso in percorsi:
            chiave = "fermo:%s:%s" % (casella, percorso.stem)
            if chiave in visti:
                continue
            try:
                eta = adesso - percorso.stat().st_mtime
            except OSError:
                continue
            if eta <= soglia:
                continue
            testo = "Un messaggio non letto nella casella %s" % casella
            try:
                intestazioni = leggi_intestazioni(percorso)
                mittente = intestazioni.get("DA") or "sconosciuto"
                oggetto = intestazioni.get("OGGETTO") or percorso.stem
                testo = "Messaggio di %s non letto da %d minuti: %s" % (
                    mittente, max(1, int(eta // 60)), oggetto)
            except ErrorePosta:
                pass
            avvisi.append({"progetto": casella, "azione": "non-letto",
                           "testo": testo, "urgente": True})
            visti[chiave] = _data_iso(_adesso())
            registra("avviso-fermo", casella, percorso.stem, {
                "casella": casella, "minuti": max(1, int(eta // 60)),
            })
    return avvisi


def sorveglia():
    """Avvisa una volta per i nuovi messaggi di opencode e per quelli fermi.

    Un solo avviso per giro: se i messaggi da annunciare sono piu' di uno
    partono come un unico avviso raggruppato (le voci restano comunque in fila).
    """
    percorso_stato = _percorso_stato()
    visti = carica_avvisati(percorso_stato)
    cambiato = False
    avvisi = []

    cartella = _percorso_sicuro("opencode", "nuovi")
    nuovi = [p for p in _messaggi(cartella) if p.stem not in visti]
    for percorso in nuovi:
        try:
            intestazioni = leggi_intestazioni(percorso)
        except ErrorePosta as errore:
            print("errore: %s" % errore, file=sys.stderr)
            visti[percorso.stem] = _data_iso(_adesso())
            cambiato = True
            continue
        azione = azione_avviso_messaggio(intestazioni)
        urgente = _vero(intestazioni.get("URGENTE")) or azione in AZIONI_URGENTI
        progetto = intestazioni.get("DA") or "sconosciuto"
        testo = intestazioni.get("OGGETTO") or percorso.stem
        avvisi.append({"progetto": progetto, "azione": azione,
                       "testo": testo, "urgente": urgente})
        visti[percorso.stem] = _data_iso(_adesso())
        cambiato = True

    fermi = _avvisi_fermi(visti)
    if fermi:
        avvisi.extend(fermi)
        cambiato = True

    if avvisi:
        try:
            avvisa_messaggi(avvisi)
        except Exception as errore:  # osascript assente o in errore: non ferma il giro
            print("errore avviso: %s" % errore, file=sys.stderr)

    # Se non c'e' niente da fare non si crea nemmeno lo stato (come prima).
    if cambiato:
        salva_avvisati(percorso_stato, visti)
    return 0


# ------------------------------------------------------------------- riassunto

RIASSUNTO_OGGETTO_MAX = 110
RIASSUNTO_DOMANDA_MAX = 160
RIASSUNTO_MASSIMO_PREDEFINITO = 15
RIASSUNTO_AZIONI_CHIESTE = ("decisione", "conferma-server", "accesso")
RIASSUNTO_TIPI_CHIESTI = ("decisione", "richiesta")
RIASSUNTO_COSA_SERVE = {
    "decisione": "decisione",
    "conferma-server": "conferma sul server",
    "accesso": "accesso",
    "risposta": "risposta",
}
RIASSUNTO_INIZI_DOMANDA = ("a)", "a:", "s/n", "scelta", "opzioni")
RIASSUNTO_TITOLO_CHIEDONO = "Ti chiedono:"
RIASSUNTO_TITOLO_INFO = "Per tua informazione:"
RIASSUNTO_NESSUNO = "\U0001f4ec Nessun messaggio nuovo."


def _accorcia(testo, massimo):
    """Testo su una riga, lungo al massimo "massimo" caratteri."""
    testo = _una_riga(testo)
    if massimo is None or len(testo) <= massimo:
        return testo
    if massimo <= 1:
        return testo[:massimo]
    return testo[:massimo - 1].rstrip() + "\u2026"


def cosa_serve(azione):
    """Cosa deve fare l'utente, in due parole."""
    return RIASSUNTO_COSA_SERVE.get(_una_riga(azione).lower(), "info")


def chiede_all_utente(azione, tipo):
    """True se il messaggio aspetta qualcosa dall'utente."""
    return (_una_riga(azione).lower() in RIASSUNTO_AZIONI_CHIESTE
            or _una_riga(tipo).lower() in RIASSUNTO_TIPI_CHIESTI)


def domanda_dal_corpo(corpo, massimo=RIASSUNTO_DOMANDA_MAX):
    """Prima riga del corpo che sembra una domanda, o stringa vuota."""
    for riga in str(corpo or "").splitlines():
        riga = _una_riga(riga)
        if not riga:
            continue
        minuscola = riga.lower()
        if "?" in riga or minuscola.startswith(RIASSUNTO_INIZI_DOMANDA):
            return _accorcia(riga, massimo)
    return ""


def voce_riassunto(intestazioni):
    """I campi che servono al riassunto, ricavati dalle intestazioni."""
    azione = azione_messaggio(intestazioni)
    tipo = intestazioni.get("TIPO", "")
    chiede = chiede_all_utente(azione, tipo)
    return {
        "id": intestazioni.get("_ID", ""),
        "progetto": _una_riga(intestazioni.get("DA", "")) or "sconosciuto",
        "tipo": tipo,
        "azione": azione,
        "serve": cosa_serve(azione),
        "oggetto": (_una_riga(intestazioni.get("OGGETTO", ""))
                    or intestazioni.get("_ID", "")),
        "chiede": chiede,
        "domanda": domanda_dal_corpo(intestazioni.get("_CORPO", "")) if chiede else "",
    }


def _raggruppa(messaggi):
    """Una voce per (progetto, oggetto), nell'ordine in cui compare la prima."""
    ordine = []
    conteggio = {}
    for voce in messaggi:
        chiave = (voce["progetto"], voce["oggetto"])
        if chiave not in conteggio:
            conteggio[chiave] = 0
            ordine.append((chiave, voce))
        conteggio[chiave] += 1
    return [(voce, conteggio[chiave]) for chiave, voce in ordine]


def riassumi(messaggi, massimo=None):
    """Testo del riassunto: prima chi chiede qualcosa, poi il resto."""
    messaggi = [voce for voce in (messaggi or []) if voce]
    if not messaggi:
        return RIASSUNTO_NESSUNO + "\n"
    if massimo is None:
        massimo = RIASSUNTO_MASSIMO_PREDEFINITO

    chiedono = [voce for voce in messaggi if voce.get("chiede")]
    altri = [voce for voce in messaggi if not voce.get("chiede")]

    righe = ["\U0001f4ec %d messaggi" % len(messaggi)]
    mostrate = 0
    restanti = 0

    for titolo, gruppo in ((RIASSUNTO_TITOLO_CHIEDONO, chiedono),
                           (RIASSUNTO_TITOLO_INFO, altri)):
        if not gruppo:
            continue
        righe.append(titolo)
        for voce, quante in _raggruppa(gruppo):
            if mostrate >= massimo:
                restanti += quante
                continue
            riga = "- %s \u00b7 %s \u00b7 %s" % (
                voce["progetto"],
                voce["serve"],
                _accorcia(voce["oggetto"], RIASSUNTO_OGGETTO_MAX),
            )
            if quante > 1:
                riga += " (\u00d7%d)" % quante
            righe.append(riga)
            if voce.get("chiede") and voce.get("domanda"):
                righe.append("  %s" % _accorcia(voce["domanda"], RIASSUNTO_DOMANDA_MAX))
            mostrate += 1

    if restanti:
        righe.append("\u2026 e altri %d messaggi (posta.py leggi per il testo intero)."
                     % restanti)
    return "\n".join(righe) + "\n"


# -------------------------------------------------------------------- comandi


# ------------------------------------------------------- domande strutturate


def _domande():
    """Module of the question records, next to this script."""
    import domande
    return domande


def leggi_opzioni(voci):
    """["A=testo", ...] -> {"A": "testo"}; letters A-Z, at least two, no repeats."""
    opzioni = {}
    for voce in voci or []:
        if "=" not in str(voce):
            raise ErrorePosta("opzione senza '=': %r (forma: A=testo breve)" % (voce,))
        lettera, testo = str(voce).split("=", 1)
        lettera = lettera.strip().upper()
        testo = _una_riga(testo)
        if not LETTERA_RE.match(lettera) or not testo:
            raise ErrorePosta("opzione non valida: %r (forma: A=testo breve)" % (voce,))
        if lettera in opzioni:
            raise ErrorePosta("opzione ripetuta: %s" % lettera)
        opzioni[lettera] = testo
    if len(opzioni) < 2:
        raise ErrorePosta("servono almeno due opzioni (--opzione A=... --opzione B=...)")
    return opzioni


def _testo_domanda(domanda, opzioni, raccomanda, bloccato, contesto):
    righe = [_una_riga(domanda), ""]
    righe += ["%s) %s" % (lettera, testo) for lettera, testo in opzioni.items()]
    if raccomanda:
        righe.append("Consiglia: %s" % raccomanda)
    righe.append("Fermo finche' non arriva la risposta: %s" % _una_riga(bloccato))
    if contesto and contesto.strip():
        righe += ["", contesto.strip()]
    return "\n".join(righe)


def chiedi(da, oggetto, domanda, opzioni, operazione, bloccato, raccomanda=None,
           ambiente=None, condizioni=None, testo=""):
    """Structured question to the manager: message to opencode + record. Returns the ID."""
    domande = _domande()
    progetto = valida_casella(da)
    if operazione not in OPERAZIONI:
        raise ErrorePosta("operazione non valida: %r (ammesse: %s)"
                          % (operazione, ", ".join(OPERAZIONI)))
    if ambiente and ambiente not in AMBIENTI:
        raise ErrorePosta("ambiente non valido: %r (ammessi: %s)" % (ambiente, ", ".join(AMBIENTI)))
    if not _una_riga(domanda) or not _una_riga(bloccato):
        raise ErrorePosta("--domanda e --bloccato non possono essere vuoti")
    if raccomanda:
        raccomanda = raccomanda.strip().upper()
        if raccomanda not in opzioni:
            raise ErrorePosta("--raccomanda %s non e' tra le opzioni" % raccomanda)
    condizioni = [c.strip() for c in (condizioni or []) if c and c.strip()]
    extra = {
        "DOMANDA-ID": ID_MESSAGGIO,
        "OPERAZIONE": operazione,
        "AMBIENTE": ambiente or "",
        "OPZIONI": json.dumps(opzioni, ensure_ascii=False),
        "RACCOMANDA": raccomanda or "",
        "BLOCCATO": _una_riga(bloccato),
        "CONDIZIONI": ",".join(condizioni),
    }
    percorso = invia(
        da=progetto, a="opencode", tipo="decisione", oggetto=oggetto,
        testo=_testo_domanda(domanda, opzioni, raccomanda, bloccato, testo),
        azione="accesso" if operazione == "credenziali" else "decisione", extra=extra,
    )
    identificativo = Path(percorso).stem
    try:
        domande.crea({
            "id": identificativo, "progetto": progetto, "oggetto": _una_riga(oggetto),
            "domanda": _una_riga(domanda), "opzioni": opzioni, "raccomanda": raccomanda,
            "operazione": operazione, "ambiente": ambiente, "condizioni": condizioni,
            "bloccato": _una_riga(bloccato), "contesto": (testo or "").strip(),
            "messaggio": str(percorso),
        })
    except BaseException:
        try:
            os.unlink(percorso)
        except OSError:
            pass
        raise
    registra("chiedi", progetto, identificativo, {"operazione": operazione})
    return identificativo


def chiedi_da_hook(progetto, oggetto, domanda, opzioni, operazione="permesso", testo="", sessione=""):
    """Question from a session hook (Claude Code, OpenCode): only the record, no mail.

    The hook waits for the answer in the registry and gives it back to the session
    itself, so nothing goes to the manager or to the session's mailbox. Returns the ID.
    """
    # the mailbox name as the sessions use it (case kept: OPENCODE-SKILLS, not opencode-skills)
    progetto = valida_casella(re.sub(r"[^A-Za-z0-9_-]+", "-", str(progetto or "")).strip("-")[:60] or "sessione")
    if operazione not in OPERAZIONI:
        raise ErrorePosta("operazione non valida: %r" % (operazione,))
    if not _una_riga(domanda) or not opzioni:
        raise ErrorePosta("domanda e opzioni non possono essere vuote")
    identificativo = "%s-%s-%s-%s" % (time.strftime("%Y%m%d-%H%M%S"), progetto,
                                      slug(oggetto or "hook", 30), os.urandom(3).hex())
    _domande().crea({
        "id": identificativo, "progetto": progetto, "oggetto": _una_riga(oggetto),
        "domanda": _una_riga(domanda), "opzioni": dict(opzioni), "raccomanda": None,
        "operazione": operazione, "ambiente": None, "condizioni": [],
        "bloccato": _una_riga(oggetto) or "la sessione", "contesto": (testo or "").strip(),
        "canale": "hook", "sessione": _una_riga(sessione)[:60],
    })
    registra("chiedi-hook", progetto, identificativo, {"operazione": operazione})
    return identificativo


def _scheda(identificativo):
    domande = _domande()
    try:
        return domande.leggi(identificativo)
    except domande.SchedaNonTrovata:
        raise ErrorePosta("domanda non trovata: %s" % identificativo)
    except ValueError as errore:
        raise ErrorePosta(str(errore))


def _passa(identificativo, nuovo, chi, nota="", **argomenti):
    domande = _domande()
    try:
        return domande.passa(identificativo, nuovo, chi, nota, **argomenti)
    except domande.PassaggioNonAmmesso as errore:
        raise ErroreStato("passaggio non ammesso: %s" % errore)
    except domande.SchedaNonTrovata:
        raise ErrorePosta("domanda non trovata: %s" % identificativo)
    except ValueError as errore:
        raise ErrorePosta(str(errore))


def rispondi_domanda(identificativo, scelta, testo, motivo, da="opencode"):
    """Delivers the answer to the session that asked. Only once: a second call
    raises ErroreStato and writes nothing. Returns the path of the message."""
    scheda = _scheda(identificativo)
    scelta = str(scelta or "").strip().upper()
    opzioni = scheda.get("opzioni") or {}
    if scelta not in opzioni:
        raise ErrorePosta("scelta %r non tra le opzioni (%s)" % (scelta, ", ".join(opzioni)))
    motivo = str(motivo or "").strip()
    if not MOTIVO_RE.match(motivo):
        raise ErrorePosta("motivo non valido: %r (utente oppure regola:<id>)" % (motivo,))
    mittente = valida_casella(da)
    testo = _una_riga(testo) if testo else opzioni[scelta]
    risposta = {"scelta": scelta, "testo": testo, "motivo": motivo, "ora": _data_iso(_adesso())}
    scritto = {}

    def manda(attuale):
        if attuale.get("canale") == "hook":
            scritto["percorso"] = None   # the hook reads the answer from the record: no mail
            return {}
        corpo = ("Risposta alla domanda %s: %s) %s\nMotivo: %s\n\n"
                 "Prima di agire esegui: posta.py recepita --id %s --casella %s "
                 "(se esce con 4 non rifare nulla). A lavoro finito: posta.py risolta --id %s"
                 % (identificativo, scelta, testo, motivo, identificativo,
                    attuale["progetto"], identificativo))
        percorso = invia(da=mittente, a=attuale["progetto"], tipo="decisione",
                         oggetto="Risposta: %s" % (attuale.get("oggetto") or identificativo),
                         testo=corpo, rif=identificativo, azione="nessuna",
                         extra={"DOMANDA-ID": identificativo})
        scritto["percorso"] = str(percorso)
        return {"messaggio_risposta": str(percorso)}

    # Una regola risponde solo mentre Ciro valuta; l'utente anche a Ciro spento
    # (domanda ancora ricevuta, la consegna OpenCode).
    stati = ("in-attesa", "in-valutazione") + (("ricevuta",) if motivo == "utente" else ())
    _passa(identificativo, "risposta-consegnata", mittente, "scelta %s (%s)" % (scelta, motivo),
           solo_da=stati, prima=manda, risposta=risposta)
    registra("rispondi-domanda", mittente, identificativo, {"scelta": scelta, "motivo": motivo})
    return scritto["percorso"]


def _solo_proprietario(scheda, casella):
    casella = valida_casella(casella)
    if scheda.get("progetto") != casella:
        raise ErrorePosta("la domanda %s e' di %s, non di %s"
                          % (scheda.get("id"), scheda.get("progetto"), casella))
    return casella


def recepita(identificativo, casella):
    casella = _solo_proprietario(_scheda(identificativo), casella)
    return _passa(identificativo, "recepita", casella)


def risolta(identificativo, nota=""):
    scheda = _scheda(identificativo)
    return _passa(identificativo, "risolta", scheda.get("progetto") or "-", nota or "")


def annulla(identificativo, casella):
    casella = _solo_proprietario(_scheda(identificativo), casella)
    return _passa(identificativo, "annullata", casella, "ritirata dalla sessione")


def cmd_chiedi(args):
    if args.testo is not None and args.file:
        raise ErrorePosta("usa --testo oppure --file, non entrambi")
    testo = args.testo or ""
    if args.file:
        try:
            testo = Path(args.file).expanduser().read_text(encoding="utf-8")
        except OSError as errore:
            raise ErrorePosta("impossibile leggere %s: %s" % (args.file, errore))
    condizioni = (args.condizioni or "").split(",") if args.condizioni else []
    print(chiedi(args.da, args.oggetto, args.domanda, leggi_opzioni(args.opzione),
                 args.operazione, args.bloccato, args.raccomanda, args.ambiente,
                 condizioni, testo))
    return 0


def cmd_domande(args):
    schede = _domande().elenca(args.stato)
    if args.json:
        print(json.dumps(schede, ensure_ascii=False, indent=1))
        return 0
    for scheda in schede:
        print("%s\t%s\t%s\t%s" % (scheda.get("id"), scheda.get("stato"),
                                  scheda.get("progetto"), scheda.get("domanda")))
    return 0


def cmd_stato(args):
    print(_scheda(args.id).get("stato"))
    return 0


def cmd_rispondi_domanda(args):
    print(rispondi_domanda(args.id, args.scelta, args.testo, args.motivo, args.da))
    return 0


def cmd_recepita(args):
    recepita(args.id, args.casella)
    return 0


def cmd_risolta(args):
    risolta(args.id, args.nota)
    return 0


def cmd_annulla(args):
    annulla(args.id, args.casella)
    return 0


def cmd_invia(args):
    if args.testo is not None and args.file:
        raise ErrorePosta("usa --testo oppure --file, non entrambi")
    if args.file:
        percorso_file = Path(args.file).expanduser()
        try:
            testo = percorso_file.read_text(encoding="utf-8")
        except OSError as errore:
            raise ErrorePosta("impossibile leggere %s: %s" % (percorso_file, errore))
    elif args.testo is not None:
        testo = args.testo
    else:
        if sys.stdin is not None and not sys.stdin.isatty():
            testo = sys.stdin.read()
        else:
            testo = ""

    percorso = invia(
        da=args.da,
        a=args.a,
        tipo=args.tipo,
        oggetto=args.oggetto,
        testo=testo,
        rif=args.rif or "",
        urgente=bool(args.urgente),
        azione=args.azione,
    )
    print(percorso)
    return 0


def cmd_elenco(args):
    casella_base = cartella_casella(args.casella)
    messaggi = []
    for percorso in _messaggi(casella_base / "nuovi"):
        intestazioni = leggi_intestazioni(percorso)
        messaggi.append({
            "id": intestazioni["_ID"],
            "da": intestazioni.get("DA", ""),
            "a": intestazioni.get("A", ""),
            "data": intestazioni.get("DATA", ""),
            "tipo": intestazioni.get("TIPO", ""),
            "urgente": "si" if _vero(intestazioni.get("URGENTE")) else "no",
            "azione": azione_messaggio(intestazioni),
            "oggetto": intestazioni.get("OGGETTO", ""),
            "rif": intestazioni.get("RIF", ""),
            "domanda_id": intestazioni.get("DOMANDA-ID", ""),
            "percorso": str(percorso),
        })

    if args.json:
        print(json.dumps(messaggi, ensure_ascii=False, indent=2))
        return 0

    if not messaggi:
        print("(nessun messaggio)")
        return 0

    print("ID\tDA\tTIPO\tURGENTE\tOGGETTO")
    for voce in messaggi:
        print("%s\t%s\t%s\t%s\t%s" % (
            voce["id"], voce["da"], voce["tipo"], voce["urgente"], voce["oggetto"],
        ))
    return 0


def cmd_leggi(args):
    casella_base = cartella_casella(args.casella)
    if args.id:
        percorsi = [_trova_messaggio(args.casella, args.id)]
    else:
        percorsi = _messaggi(casella_base / "nuovi")
        if not args.tutti and percorsi:
            percorsi = percorsi[:1]

    if not percorsi:
        print("(nessun messaggio)")
        return 0

    primo = True
    for percorso in percorsi:
        intestazioni = leggi_intestazioni(percorso)
        contenuto = intestazioni["_CONTENUTO"]
        if not primo:
            print()
        primo = False
        sys.stdout.write(contenuto)
        if not contenuto.endswith("\n"):
            sys.stdout.write("\n")
        sys.stdout.flush()
        if args.archivia:
            archivia(percorso)
        registra("leggi", args.casella, intestazioni["_ID"], {
            "casella": args.casella,
            "archiviato": "si" if args.archivia else "no",
        })
    return 0


def cmd_riassunto(args):
    casella_base = cartella_casella(args.casella)
    massimo = args.massimo
    if massimo is None:
        massimo = RIASSUNTO_MASSIMO_PREDEFINITO
    if massimo < 0:
        raise ErrorePosta("--massimo non puo' essere negativo")

    voci = []
    for percorso in _messaggi(casella_base / "nuovi"):
        intestazioni = leggi_intestazioni(percorso)
        voce = voce_riassunto(intestazioni)
        voce["percorso"] = percorso
        voci.append(voce)

    sys.stdout.write(riassumi(voci, massimo))
    sys.stdout.flush()

    if not voci:
        return 0

    if args.archivia:
        for voce in voci:
            try:
                archivia(voce["percorso"])
            except OSError as errore:
                raise ErrorePosta("impossibile archiviare %s: %s"
                                  % (voce["percorso"], errore))
            registra("leggi", args.casella, voce["id"], {
                "casella": args.casella,
                "archiviato": "si",
            })
        registra("riassunto", args.casella, "-", {
            "quanti": len(voci),
            "archiviato": "si",
        })
    return 0


def cmd_attendi(args):
    casella_base = cartella_casella(args.casella)
    cartella = casella_base / "nuovi"
    intervallo = float(os.environ.get("POSTA_INTERVALLO") or INTERVALLO_PREDEFINITO)
    if intervallo <= 0:
        intervallo = INTERVALLO_PREDEFINITO

    registra("attendi-inizio", args.casella, "-", {
        "max_secondi": args.max_secondi if args.max_secondi is not None else "-",
    })
    inizio = time.monotonic()
    while True:
        trovati = _messaggi(cartella)
        if trovati:
            for percorso in trovati:
                print(percorso)
            sys.stdout.flush()
            registra("attendi-sveglia", args.casella, "-",
                     {"messaggi": len(trovati)})
            return 0

        if args.max_secondi is not None:
            trascorso = time.monotonic() - inizio
            if trascorso >= args.max_secondi:
                registra("attendi-scaduto", args.casella, "-",
                         {"max_secondi": args.max_secondi})
                return CODICE_TIMEOUT
            attesa = min(intervallo, args.max_secondi - trascorso)
        else:
            attesa = intervallo
        time.sleep(max(0.05, attesa))


def cmd_avvisa(args):
    avvisa(args.progetto, args.azione, args.testo or "")
    return 0


def cmd_sorveglia(_args):
    return sorveglia()


# --------------------------------------------------------------------- parser


def costruisci_parser():
    parser = argparse.ArgumentParser(
        prog="posta.py",
        description="Posta su file tra OpenCode e le sessioni Claude Code.",
    )
    comandi = parser.add_subparsers(dest="comando", required=True)

    p = comandi.add_parser("invia", help="scrive un messaggio in una casella")
    p.add_argument("--da", required=True, help="casella mittente")
    p.add_argument("--a", required=True, help="casella destinatario")
    p.add_argument("--tipo", required=True, choices=TIPI)
    p.add_argument("--oggetto", required=True)
    p.add_argument("--testo", default=None, help="testo del messaggio")
    p.add_argument("--file", default=None, help="testo letto da questo file UTF-8")
    p.add_argument("--rif", default="", help="ID del messaggio a cui si risponde")
    p.add_argument("--azione", choices=AZIONI, default=None,
                   help="azione richiesta all'utente (predefinita secondo --tipo)")
    p.add_argument("--urgente", action="store_true")
    p.set_defaults(func=cmd_invia)

    p = comandi.add_parser("chiedi", help="domanda strutturata al gestore (stampa l'ID)")
    p.add_argument("--da", required=True, help="casella del progetto che chiede")
    p.add_argument("--oggetto", required=True)
    p.add_argument("--domanda", required=True, help="la domanda in una frase")
    p.add_argument("--opzione", action="append", required=True, help="A=testo breve (ripetibile)")
    p.add_argument("--raccomanda", default=None, help="lettera consigliata")
    p.add_argument("--operazione", required=True, choices=OPERAZIONI)
    p.add_argument("--ambiente", default=None, choices=AMBIENTI)
    p.add_argument("--bloccato", required=True, help="cosa e' fermo finche' non arriva la risposta")
    p.add_argument("--condizioni", default=None, help="es. test-ok,build-ok")
    p.add_argument("--testo", default=None, help="contesto essenziale")
    p.add_argument("--file", default=None, help="contesto letto da questo file UTF-8")
    p.set_defaults(func=cmd_chiedi)

    p = comandi.add_parser("domande", help="elenca le domande strutturate")
    p.add_argument("--stato", default=None)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_domande)

    p = comandi.add_parser("stato", help="stato di una domanda strutturata")
    p.add_argument("--id", required=True)
    p.set_defaults(func=cmd_stato)

    p = comandi.add_parser("rispondi-domanda", help="consegna la risposta alla sessione (una volta)")
    p.add_argument("--id", required=True)
    p.add_argument("--scelta", required=True)
    p.add_argument("--testo", default=None)
    p.add_argument("--motivo", required=True, help="utente oppure regola:<id>")
    p.add_argument("--da", default="opencode")
    p.set_defaults(func=cmd_rispondi_domanda)

    p = comandi.add_parser("recepita", help="la sessione ha letto la risposta (prima di agire)")
    p.add_argument("--id", required=True)
    p.add_argument("--casella", required=True)
    p.set_defaults(func=cmd_recepita)

    p = comandi.add_parser("risolta", help="il lavoro sbloccato dalla risposta e' fatto")
    p.add_argument("--id", required=True)
    p.add_argument("--nota", default="")
    p.set_defaults(func=cmd_risolta)

    p = comandi.add_parser("annulla", help="la sessione ritira la sua domanda")
    p.add_argument("--id", required=True)
    p.add_argument("--casella", required=True)
    p.set_defaults(func=cmd_annulla)

    p = comandi.add_parser("elenco", help="elenca i messaggi in nuovi/")
    p.add_argument("--casella", required=True)
    p.add_argument("--json", dest="json", action="store_true")
    p.set_defaults(func=cmd_elenco)

    p = comandi.add_parser("leggi", help="stampa i messaggi e, se richiesto, li archivia")
    p.add_argument("--casella", required=True)
    p.add_argument("--id", default=None)
    p.add_argument("--tutti", action="store_true")
    p.add_argument("--archivia", action="store_true")
    p.set_defaults(func=cmd_leggi)

    p = comandi.add_parser("riassunto",
                           help="stampa un riassunto breve dei messaggi nuovi")
    p.add_argument("--casella", required=True)
    p.add_argument("--archivia", action="store_true")
    p.add_argument("--massimo", type=int, default=None,
                   help="righe massime nel riassunto (predefinito 15)")
    p.set_defaults(func=cmd_riassunto)

    p = comandi.add_parser("attendi", help="aspetta che arrivi un messaggio")
    p.add_argument("--casella", required=True)
    p.add_argument("--max-secondi", dest="max_secondi", type=float, default=None)
    p.set_defaults(func=cmd_attendi)

    p = comandi.add_parser("avvisa", help="notifica, suono e voce sul Mac")
    p.add_argument("--progetto", required=True,
                   help="nome del progetto da pronunciare e mostrare")
    p.add_argument("--azione", required=True, choices=AZIONI)
    p.add_argument("--testo", default="",
                   help="testo della notifica (predefinito: la frase dell'azione)")
    p.set_defaults(func=cmd_avvisa)

    p = comandi.add_parser("parla",
                           help="pronuncia solo il testo (niente suono, niente notifica)")
    p.add_argument("--testo", default=None,
                   help="testo da pronunciare (predefinito: letto da stdin)")
    p.add_argument("--interrompi-precedente", dest="interrompi_precedente",
                   action="store_true",
                   help="interrompe la voce lanciata prima con questa opzione")
    p.add_argument("--se-libero", dest="se_libero", action="store_true",
                   help="parla solo se nessun'altra voce e' in corso: se il lock "
                        "e' occupato esce con codice 3 senza parlare")
    p.add_argument("--suono", default=None,
                   help="file aiff da suonare prima della voce, sotto lo stesso lock")
    p.set_defaults(func=cmd_parla)

    p = comandi.add_parser("sorveglia",
                           help="avvisa sui messaggi nuovi e su quelli rimasti fermi")
    p.set_defaults(func=cmd_sorveglia)

    return parser


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]
    if argv and argv[0] == "_suona":
        return _main_suona(list(argv[1:]))
    if argv and argv[0] == "_parla":
        return _main_parla(list(argv[1:]))
    parser = costruisci_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args) or 0
    except ErroreStato as errore:
        print("errore: %s" % errore, file=sys.stderr)
        return CODICE_STATO
    except ErrorePosta as errore:
        print("errore: %s" % errore, file=sys.stderr)
        return CODICE_ERRORE
    except KeyboardInterrupt:
        return CODICE_INTERRUZIONE
    except BrokenPipeError:
        return 0


if __name__ == "__main__":
    sys.exit(main())
