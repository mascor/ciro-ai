#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stato delle sessioni Claude Code aperte sul Mac.

Legge SOLO i file locali di Claude Code (~/.claude/sessions e ~/.claude/projects)
e mostra quali sessioni lavorano, quali sono ferme e quali aspettano una risposta.
Non usa nessun modello di linguaggio e non fa chiamate di rete.
L'unica scrittura consentita e' ~/.claude-stato/stato.json (modalita' --notify).
Gli avvisi usano posta.py della skill posta-sessioni: notifica macOS, suono e voce.
"""

import argparse
import glob
import importlib.util
import json
import os
import re
import subprocess
import sys
import time

SESSIONI_DIR = os.path.expanduser("~/.claude/sessions")
PROJECTS_DIR = os.path.expanduser("~/.claude/projects")
STATO_FILE = os.path.expanduser("~/.claude-stato/stato.json")

# Quanti byte leggere dalla coda di ogni conversazione (file molto grandi).
CODA_BYTE = 2 * 1024 * 1024
ANTEPRIMA_MAX = 120
VOCE_MAX = 160               # lunghezza massima di una voce di attesa in tabella
SEPARATORE_VOCI = "\u00b7"  # il "·" che divide le voci di una riga IN ATTESA DI

# Nomi che indicano una cosa che deve fare l'utente (confronto senza maiuscole).
# names that mean "the user" in a waiting line; add yours with CIRO_NOMI_UTENTE=Mario,Mario Rossi
NOMI_UTENTE_PREDEFINITI = tuple(
    n.strip() for n in (os.environ.get("CIRO_NOMI_UTENTE") or os.environ.get("CIRO_UTENTE") or "").split(",")
    if n.strip()) + ("l'utente", "utente")

# Stati grezzi in cui la sessione sta lavorando (non aspetta l'utente).
STATI_LAVORO = ("busy", "shell")

# Riga di comando che tiene in ascolto una casella della posta.
COMANDO_PS = ("/bin/ps", "-axo", "command")
ASCOLTO_RE = re.compile(r"posta\.py\s+attendi\b[^\n]*?--casella(?:=|\s+)(\S+)")
NOME_CASELLA_RE = re.compile(r"^[A-Za-z0-9_-]{1,120}$")
_SENZA_PS = object()

COLORI = {
    "attesa": "\033[1;31m",   # rosso vivo: aspetta te
    "busy": "\033[1;33m",     # giallo: al lavoro
    "idle": "\033[0;36m",     # ciano: ferma
    "chiusa": "\033[2m",      # grigio: sessione chiusa
    "testa": "\033[1m",
    "reset": "\033[0m",
}


# --------------------------------------------------------------------------
# Tempi e formattazione
# --------------------------------------------------------------------------

def _testo(valore):
    """Campo di testo normalizzato: '' se manca o non e' un valore semplice.

    I file di Claude Code possono contenere campi con tipi inattesi (numeri,
    oggetti): senza questa normalizzazione un .lower() o un .rstrip() fa
    cadere lo script.
    """
    if valore is None:
        return ""
    if isinstance(valore, str):
        return valore
    if isinstance(valore, bool):
        return "true" if valore else "false"
    if isinstance(valore, (int, float)):
        return str(valore)
    return ""


def _timestamp_ms(valore):
    """Millisecondi epoch da int/float/stringa numerica; None se non valido."""
    if valore is None or isinstance(valore, bool):
        return None
    if isinstance(valore, (int, float)):
        try:
            numero = int(valore)
        except (ValueError, OverflowError):
            return None
    elif isinstance(valore, str):
        testo = valore.strip()
        if not testo:
            return None
        try:
            numero = int(float(testo))
        except (ValueError, OverflowError):
            return None
    else:
        return None
    return numero if numero > 0 else None


def formatta_durata(secondi):
    """Trasforma una durata in secondi in una stringa breve: '5 min', '2 h 10 min', '3 g'."""
    try:
        secondi = int(secondi)
    except (TypeError, ValueError):
        return "?"
    if secondi < 0:
        secondi = 0
    if secondi < 60:
        return "meno di 1 min"
    minuti = secondi // 60
    if minuti < 60:
        return "%d min" % minuti
    ore = minuti // 60
    minuti_resto = minuti % 60
    if ore < 24:
        if minuti_resto:
            return "%d h %d min" % (ore, minuti_resto)
        return "%d h" % ore
    giorni = ore // 24
    return "%d g" % giorni


def ms_a_iso(ms):
    """Millisecondi epoch -> stringa locale leggibile ('' se non valido)."""
    if not ms:
        return ""
    try:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(int(ms) / 1000.0))
    except (TypeError, ValueError, OSError, OverflowError):
        return ""


# --------------------------------------------------------------------------
# Processi e sessioni
# --------------------------------------------------------------------------

def processo_vivo(pid):
    """True se il processo esiste. PermissionError = esiste ma non e' nostro.

    Un pid assente, booleano o <= 0 non e' un processo nostro: os.kill(-1, 0)
    farebbe il controllo su tutti i processi e la sessione sembrerebbe viva.
    """
    if not pid or isinstance(pid, bool):
        return False
    try:
        numero = int(pid)
    except (TypeError, ValueError, OverflowError):
        return False
    if numero <= 0:
        return False
    try:
        os.kill(numero, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except (OSError, ValueError, OverflowError):
        return False
    return True


def leggi_file_sessione(percorso):
    """Legge un file <pid>.json. Restituisce un dict o None se non e' valido."""
    try:
        with open(percorso, "r", encoding="utf-8") as f:
            dati = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(dati, dict):
        return None
    return dati


def leggi_ps(comando=None):
    """Righe di "ps -axo command"; None se il comando non risponde."""
    comando = list(comando or COMANDO_PS)
    try:
        risultato = subprocess.run(
            comando,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=5,
            universal_newlines=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if risultato.returncode != 0:
        return None
    return (risultato.stdout or "").splitlines()


def caselle_in_ascolto(righe):
    """Caselle con un processo "posta.py attendi --casella NOME"; None se ps e' fallito."""
    if righe is None:
        return None
    caselle = set()
    for riga in righe:
        if not isinstance(riga, str):
            continue
        for trovato in ASCOLTO_RE.findall(riga):
            nome = trovato.strip().strip("'\"")
            # Solo nomi di casella veri: un prompt che cita "casella <casella>" non conta.
            if nome and NOME_CASELLA_RE.match(nome):
                caselle.add(nome)
    return caselle


def ascolta_posta(righe, casella):
    """True/False se qualcuno ascolta quella casella; None se non si puo' sapere."""
    if righe is None or not casella:
        return None
    caselle = caselle_in_ascolto(righe)
    if caselle is None:
        return None
    return casella in caselle


def carica_sessioni(sessioni_dir, includi_morte=False):
    """Legge tutti i file .json della cartella sessioni (ignora i .key).

    Restituisce una lista di dict con i campi normalizzati e 'viva'.
    """
    sessioni = []
    if not os.path.isdir(sessioni_dir):
        return sessioni
    for percorso in sorted(glob.glob(os.path.join(sessioni_dir, "*.json"))):
        dati = leggi_file_sessione(percorso)
        if dati is None:
            continue
        pid = dati.get("pid")
        if not pid:
            # Senza pid non possiamo sapere se e' viva: la teniamo solo con --tutte.
            if not includi_morte:
                continue
            pid = None
        viva = processo_vivo(pid) if pid else False
        if not viva and not includi_morte:
            continue
        cwd = _testo(dati.get("cwd"))
        nome = (_testo(dati.get("name")) or _testo(dati.get("sessionId"))
                or ("pid %s" % pid))
        started_at = _timestamp_ms(dati.get("startedAt"))
        sessioni.append({
            "pid": pid,
            "session_id": _testo(dati.get("sessionId")),
            "cwd": cwd,
            "progetto": os.path.basename(cwd.rstrip("/")) if cwd else "?",
            "nome": nome,
            "stato_grezzo": _testo(dati.get("status")),
            "started_at": started_at,
            "status_updated_at": (_timestamp_ms(dati.get("statusUpdatedAt"))
                                  or started_at),
            "viva": viva,
        })
    return sessioni


# --------------------------------------------------------------------------
# Conversazione: solo la coda del file .jsonl
# --------------------------------------------------------------------------

def trova_jsonl(projects_dir, session_id):
    """Trova <sessionId>.jsonl in una qualsiasi sottocartella di projects."""
    if not session_id:
        return None
    pattern = os.path.join(projects_dir, "*", "%s.jsonl" % session_id)
    trovati = glob.glob(pattern)
    return trovati[0] if trovati else None


def leggi_coda(percorso, quantita=CODA_BYTE):
    """Legge gli ultimi 'quantita' byte e scarta la prima riga se e' parziale."""
    try:
        with open(percorso, "rb") as f:
            f.seek(0, os.SEEK_END)
            dimensione = f.tell()
            inizio = max(0, dimensione - quantita)
            f.seek(inizio)
            dati = f.read()
    except OSError:
        return []
    righe = dati.split(b"\n")
    if inizio > 0 and righe:
        righe = righe[1:]  # la prima riga e' quasi certamente tagliata
    return [r for r in righe if r.strip()]


def _testo_evento_assistente(evento):
    """Ultimo blocco di testo non vuoto dell'evento assistant; '' se non ce n'e'."""
    messaggio = evento.get("message")
    if not isinstance(messaggio, dict):
        return ""
    contenuto = messaggio.get("content")
    if not isinstance(contenuto, list):
        return ""
    ultimo = ""
    for blocco in contenuto:
        if not isinstance(blocco, dict) or blocco.get("type") != "text":
            continue
        testo = blocco.get("text")
        if isinstance(testo, str) and testo.strip():
            ultimo = testo
    return ultimo


def leggi_coda_conversazione(projects_dir, session_id):
    """(ultimo testo assistant, turno_finito) leggendo la coda una sola volta.

    Il campo "status" di Claude Code resta "shell" anche quando il turno e'
    finito (per esempio mentre in background gira "posta.py attendi").
    Nella conversazione la fine del turno si riconosce dal fatto che, fra gli
    eventi "user"/"assistant" e i system "turn_duration", l'ultimo e' proprio
    un "turn_duration". Gli altri eventi (attachment, api-request, ...) non
    contano. Senza nessun "turn_duration" nella coda il turno non e' finito.
    """
    percorso = trova_jsonl(projects_dir, session_id)
    if not percorso:
        return "", False
    ultimo_testo = ""
    ultimo_segno = None
    for riga in leggi_coda(percorso):
        try:
            evento = json.loads(riga.decode("utf-8", "replace"))
        except (ValueError, UnicodeDecodeError):
            continue
        if not isinstance(evento, dict):
            continue
        tipo = evento.get("type")
        if tipo == "assistant":
            ultimo_segno = tipo
            testo = _testo_evento_assistente(evento)
            if testo:
                ultimo_testo = testo
        elif tipo == "user":
            ultimo_segno = tipo
        elif tipo == "system" and evento.get("subtype") == "turn_duration":
            ultimo_segno = "turn_duration"
    return ultimo_testo, ultimo_segno == "turn_duration"


def ultimo_testo_assistente(projects_dir, session_id):
    """Ultimo blocco di testo non vuoto dell'ultimo evento assistant."""
    return leggi_coda_conversazione(projects_dir, session_id)[0]


# --------------------------------------------------------------------------
# Estrazione delle informazioni dal testo
# --------------------------------------------------------------------------

def senza_markdown_semplice(testo):
    """Toglie **, ` e gli asterischi, lasciando il testo leggibile."""
    return testo.replace("**", "").replace("`", "").replace("*", "")


def estrai_attesa(testo):
    """Riga 'IN ATTESA DI' senza simbolo e asterischi; '' se non c'e'."""
    if not testo:
        return ""
    for riga in testo.splitlines():
        if "IN ATTESA DI" not in riga:
            continue
        riga = riga.replace("\u23f3", "").replace("*", "").replace("`", "").strip()
        posizione = riga.find("IN ATTESA DI")
        resto = riga[posizione + len("IN ATTESA DI"):].lstrip()
        if resto.startswith(":"):
            resto = resto[1:].lstrip()
        return resto.strip()
    return ""


def estrai_domanda(testo):
    """Riga della domanda se il testo chiede (S/N) o finisce con '?'; altrimenti ''."""
    if not testo:
        return ""
    if "(S/N)" in testo:
        for riga in reversed(testo.splitlines()):
            if "(S/N)" in riga:
                return senza_markdown_semplice(riga).strip()
        return ""
    righe = [r.strip() for r in testo.splitlines() if r.strip()]
    righe = [r for r in righe if "IN ATTESA DI" not in r]
    # Le opzioni (A/B/C, S/N, 1/2/3) vengono dopo la domanda: si saltano.
    fine = len(righe)
    while fine > 0 and OPZIONE_RE.match(righe[fine - 1]):
        fine -= 1
    if fine > 0 and righe[fine - 1].rstrip().rstrip("*_ ").endswith("?"):
        return senza_markdown_semplice(righe[fine - 1]).strip()
    return ""


# Riga di un'opzione di scelta: "- **A** — testo", "A) testo", "**S** = si", "1. testo".
OPZIONE_RE = re.compile(
    r"^(?:[-*•]\s+)?(?:\*\*|__)?\(?(?:[A-F]|S|N|[1-9])(?:\)|\.|:)?(?:\*\*|__)?"
    r"\s*(?:—|–|-|:|=|\)|\.)\s*\S")


def _mappa_chiusure(testo):
    """Posizione della parentesi chiusa corrispondente a ogni parentesi aperta.

    Gestisce tonde, quadre e graffe; le aperture senza chiusura restano fuori
    dalla mappa (cosi' un errore di battitura non nasconde i separatori).
    """
    coppie = {")": "(", "]": "[", "}": "{"}
    pila = []
    mappa = {}
    for indice, carattere in enumerate(testo):
        if carattere in "([{":
            pila.append((carattere, indice))
        elif carattere in ")]}":
            for posizione in range(len(pila) - 1, -1, -1):
                if pila[posizione][0] == coppie[carattere]:
                    mappa[pila[posizione][1]] = indice
                    del pila[posizione:]
                    break
    return mappa


def dividi_voci(attesa):
    """Divide la riga di attesa nelle sue voci (separatore " · ").

    Non divide dentro le parentesi (tonde, quadre, graffe): li' il separatore
    fa parte della voce, per esempio "(messaggio: /a.txt · stato: fatto)".
    Restituisce una lista di stringhe non vuote.
    """
    if not attesa:
        return []
    if not isinstance(attesa, str):
        attesa = str(attesa)
    mappa = _mappa_chiusure(attesa)
    pezzi = []
    inizio = 0
    indice = 0
    while indice < len(attesa):
        if indice in mappa:               # salta tutto il blocco tra parentesi
            indice = mappa[indice] + 1
            continue
        if attesa[indice] == SEPARATORE_VOCI:
            pezzi.append(attesa[inizio:indice])
            inizio = indice + 1
        indice += 1
    pezzi.append(attesa[inizio:])
    voci = []
    for pezzo in pezzi:
        pezzo = pezzo.strip().strip(SEPARATORE_VOCI).strip()
        if pezzo:
            voci.append(pezzo)
    return voci


def voce_per_utente(voce, nomi_utente=None):
    """True se la voce inizia con uno dei nomi dell'utente (spazi/maiuscole ignorati)."""
    if not voce:
        return False
    pulita = senza_markdown_semplice(str(voce)).strip().lower()
    if not pulita:
        return False
    nomi = NOMI_UTENTE_PREDEFINITI if nomi_utente is None else nomi_utente
    for nome in nomi:
        nome = senza_markdown_semplice(str(nome)).strip().lower()
        if nome and pulita.startswith(nome):
            return True
    return False


def voci_per_utente(voci, nomi_utente=None):
    """Solo le voci che spettano all'utente, nello stesso ordine."""
    return [v for v in (voci or []) if voce_per_utente(v, nomi_utente)]


def taglia(testo, massimo=VOCE_MAX):
    """Taglia una stringa a 'massimo' caratteri, con "…" se e' stata tagliata."""
    testo = "" if testo is None else str(testo).strip()
    if len(testo) <= massimo:
        return testo
    return testo[:massimo - 1].rstrip() + "\u2026"


def anteprima(testo):
    """Prima riga non vuota, senza markdown semplice, massimo 120 caratteri."""
    if not testo:
        return ""
    for riga in testo.splitlines():
        riga = senza_markdown_semplice(riga).strip()
        if not riga:
            continue
        if len(riga) > ANTEPRIMA_MAX:
            return riga[:ANTEPRIMA_MAX - 1].rstrip() + "\u2026"
        return riga
    return ""


# --------------------------------------------------------------------------
# Costruzione del record mostrato all'utente
# --------------------------------------------------------------------------

def stato_leggibile(stato_grezzo):
    """Traduce lo stato dei file di Claude Code in italiano.

    I valori nuovi o sconosciuti vengono mostrati cosi' come sono.
    """
    if not isinstance(stato_grezzo, str):
        stato_grezzo = _testo(stato_grezzo)
    if stato_grezzo == "busy":
        return "al lavoro"
    if stato_grezzo == "shell":
        return "comando in corso"
    if stato_grezzo == "idle":
        return "ferma"
    return stato_grezzo or "sconosciuto"


def stato_effettivo(stato_grezzo, turno_finito):
    """Stato vero della sessione, tenendo conto della fine del turno.

    Claude Code lascia "shell" anche quando ha finito e aspetta l'utente
    (per esempio perche' in background gira "posta.py attendi"): in quel caso
    la sessione e' "idle", cioe' ferma, per la tabella e per le notifiche.
    """
    if stato_grezzo == "shell" and turno_finito:
        return "idle"
    return stato_grezzo


def costruisci_sessione(sessione, projects_dir, adesso_ms=None, nomi_utente=None,
                        righe_ps=_SENZA_PS):
    """Aggiunge stato leggibile, durate, ultimo testo, attese, domanda, anteprima."""
    if adesso_ms is None:
        adesso_ms = int(time.time() * 1000)

    stato_grezzo = sessione.get("stato_grezzo") or ""
    viva = bool(sessione.get("viva"))

    # La coda si legge una volta sola: serve sia per l'ultimo testo sia per
    # capire se il turno e' finito (il campo status puo' restare "shell").
    testo = ""
    turno_finito = False
    if viva:
        testo, turno_finito = leggi_coda_conversazione(
            projects_dir, sessione.get("session_id") or "")

    stato_vero = stato_effettivo(stato_grezzo, turno_finito) if viva else stato_grezzo
    if not viva:
        stato = "chiusa"
    else:
        stato = stato_leggibile(stato_vero)

    iniziato = _timestamp_ms(sessione.get("status_updated_at"))
    da_secondi = max(0, (adesso_ms - iniziato) // 1000) if iniziato else 0
    aperta_secondi = 0
    aperto = _timestamp_ms(sessione.get("started_at"))
    if aperto:
        aperta_secondi = max(0, (adesso_ms - aperto) // 1000)

    attesa = estrai_attesa(testo)
    attese = dividi_voci(attesa)
    per_utente = voci_per_utente(attese, nomi_utente)
    domanda = ""
    if viva and stato_vero == "idle":
        domanda = estrai_domanda(testo)

    # Aspetta te solo se la sessione e' ferma e c'e' qualcosa per te.
    aspetta_utente = bool(viva and stato_vero == "idle" and (domanda or per_utente))

    if not viva:
        ascolta = None
    else:
        righe = leggi_ps() if righe_ps is _SENZA_PS else righe_ps
        casella = os.path.basename(_testo(sessione.get("cwd")).rstrip("/"))
        ascolta = ascolta_posta(righe, casella or _testo(sessione.get("progetto")))

    return {
        "nome": sessione.get("nome") or "?",
        "progetto": sessione.get("progetto") or "?",
        "cwd": sessione.get("cwd") or "",
        "pid": sessione.get("pid"),
        "session_id": sessione.get("session_id") or "",
        "stato": stato,
        "stato_grezzo": stato_grezzo,
        "stato_effettivo": stato_vero,
        "turno_finito": turno_finito,
        "da": formatta_durata(da_secondi),
        "da_secondi": da_secondi,
        "aperta_da": ms_a_iso(sessione.get("started_at")),
        "aperta_da_secondi": aperta_secondi,
        "attesa": attesa,
        "attese": attese,
        "attese_per_utente": per_utente,
        "aspetta_utente": aspetta_utente,
        "domanda_per_utente": aspetta_utente,   # vecchio nome, stesso valore
        "domanda": domanda,
        "anteprima": anteprima(testo),
        "ascolta_posta": ascolta,
    }


def ordina_sessioni(sessioni):
    """Prima chi aspetta una risposta, poi chi ha un'attesa, poi le altre."""
    def chiave(s):
        if s.get("aspetta_utente", s.get("domanda_per_utente")):
            gruppo = 0
        elif s.get("attesa"):
            gruppo = 1
        else:
            gruppo = 2
        return (gruppo, _testo(s.get("nome")).lower())
    return sorted(sessioni, key=chiave)


def raccogli(sessioni_dir, projects_dir, includi_morte=False, nomi_utente=None):
    """Legge i file e restituisce i record pronti, gia' ordinati.

    La lista dei processi si legge una sola volta per ogni raccolta.
    """
    adesso_ms = int(time.time() * 1000)
    grezze = carica_sessioni(sessioni_dir, includi_morte=includi_morte)
    righe_ps = leggi_ps()
    pronte = [costruisci_sessione(s, projects_dir, adesso_ms, nomi_utente=nomi_utente,
                                 righe_ps=righe_ps)
              for s in grezze]
    return ordina_sessioni(pronte)


# --------------------------------------------------------------------------
# Tabella
# --------------------------------------------------------------------------

def _colora(testo, colore, attivo):
    if not attivo:
        return testo
    return "%s%s%s" % (COLORI[colore], testo, COLORI["reset"])


def voci_della_sessione(sessione):
    """Voci dell'attesa; se il record non le ha (record vecchio), le ricalcola."""
    voci = sessione.get("attese")
    if not isinstance(voci, list):
        voci = dividi_voci(sessione.get("attesa") or "")
    return [str(v) for v in voci if str(v).strip()]


def voci_utente_della_sessione(sessione, voci=None):
    """Voci per l'utente; se il record non le ha, le ricalcola dalle voci."""
    if voci is None:
        voci = voci_della_sessione(sessione)
    per_utente = sessione.get("attese_per_utente")
    if not isinstance(per_utente, list):
        per_utente = voci_per_utente(voci)
    return [str(v) for v in per_utente]


def attende_utente(sessione):
    """Legge aspetta_utente, con domanda_per_utente come ripiego (record vecchi)."""
    if "aspetta_utente" in sessione:
        return bool(sessione.get("aspetta_utente"))
    return bool(sessione.get("domanda_per_utente"))


def stato_posta(valore):
    """Cella della colonna POSTA: si, NO o ? (ps non disponibile)."""
    if valore is True:
        return "si"
    if valore is False:
        return "NO"
    return "?"


def render_tabella(sessioni, colore=False):
    """Tabella leggibile; sotto ogni riga la domanda e le singole voci di attesa."""
    intestazioni = ("SESSIONE", "PROGETTO", "STATO", "DA", "ASPETTA TE", "POSTA")
    righe = []
    for s in sessioni:
        if attende_utente(s):
            aspetta = "si"
        elif voci_della_sessione(s):
            aspetta = "attesa"
        else:
            aspetta = ""
        righe.append((s, (s["nome"], s["progetto"], s["stato"], s["da"], aspetta,
                          stato_posta(s.get("ascolta_posta")))))

    larghezze = [len(h) for h in intestazioni]
    for _, celle in righe:
        for i, cella in enumerate(celle):
            larghezze[i] = max(larghezze[i], len(str(cella)))

    def formatta(celle):
        parti = []
        for i, cella in enumerate(celle):
            if i == len(celle) - 1:
                parti.append(str(cella))
            else:
                parti.append(str(cella).ljust(larghezze[i]))
        return "  ".join(parti).rstrip()

    linee = ["  ".join(h.ljust(larghezze[i]) for i, h in enumerate(intestazioni)).rstrip()]
    linee.append("  ".join("-" * larghezza for larghezza in larghezze))
    for s, celle in righe:
        if s["stato"] == "chiusa":
            colore_riga = "chiusa"
        elif attende_utente(s):
            colore_riga = "attesa"
        elif (s.get("stato_effettivo") or s.get("stato_grezzo")) in STATI_LAVORO \
                or s["stato"] == "comando in corso":
            colore_riga = "busy"     # "shell"/"busy": sta lavorando
        else:
            colore_riga = "idle"
        linee.append(_colora(formatta(celle), colore_riga, colore))
        if s.get("domanda"):
            linee.append(_colora("    domanda: " + taglia(s["domanda"]), "attesa", colore))
        voci = voci_della_sessione(s)
        per_utente = voci_utente_della_sessione(s, voci)
        for voce in per_utente:
            linee.append(_colora("    per te: " + taglia(voce), "attesa", colore))
        for voce in voci:
            if voce in per_utente:
                continue
            linee.append(_colora("    attesa: " + taglia(voce), "idle", colore))
    if not righe:
        linee.append("(nessuna sessione viva)")
    return "\n".join(linee)


# --------------------------------------------------------------------------
# Notifiche macOS
# --------------------------------------------------------------------------

POSTA_INSTALLATA = os.path.expanduser("~/.posta-agenti/bin/posta.py")
POSTA_ACCANTO = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "..", "posta-sessioni", "scripts", "posta.py"))

_posta_caricato = None


def percorso_posta():
    """Il posta.py installato per launchd, altrimenti quello accanto alla skill."""
    for candidato in (POSTA_INSTALLATA, POSTA_ACCANTO):
        if os.path.isfile(candidato):
            return candidato
    return None


def carica_posta(percorso=None):
    """Importa posta.py una sola volta; errore chiaro se non c'e'."""
    global _posta_caricato
    if _posta_caricato is not None:
        return _posta_caricato
    percorso = percorso or percorso_posta()
    if not percorso:
        raise RuntimeError("posta.py non trovato: cercato %s e %s"
                           % (POSTA_INSTALLATA, POSTA_ACCANTO))
    specifica = importlib.util.spec_from_file_location("posta_avvisi", percorso)
    if specifica is None or specifica.loader is None:
        raise RuntimeError("posta.py non caricabile: %s" % percorso)
    modulo = importlib.util.module_from_spec(specifica)
    specifica.loader.exec_module(modulo)
    _posta_caricato = modulo
    return modulo


def avvisa_sessione(progetto, testo, avvisatore=None, modulo=None):
    """Avviso della posta: progetto (colonna PROGETTO) e azione decisione."""
    if avvisatore is not None:
        return avvisatore(progetto, testo)
    modulo = modulo or carica_posta()
    return modulo.avvisa(progetto, azione="decisione", testo=testo)


def testo_notifica(sessione):
    """Testo breve della notifica: la voce nuova, poi la domanda, poi la prima per te."""
    if sessione.get("voce_nuova"):
        return sessione["voce_nuova"]
    if sessione.get("domanda"):
        return sessione["domanda"]
    per_utente = sessione.get("attese_per_utente") or []
    if per_utente:
        return per_utente[0]
    if sessione.get("attesa"):
        return sessione["attesa"]
    return sessione.get("anteprima") or "Sessione ferma"


def chiave_sessione(sessione):
    return sessione.get("session_id") or ("pid:%s" % sessione.get("pid"))


def carica_stato(percorso):
    """Legge lo stato precedente; {} se il file manca o e' malformato."""
    try:
        with open(percorso, "r", encoding="utf-8") as f:
            dati = json.load(f)
    except (OSError, ValueError):
        return {}
    if not isinstance(dati, dict):
        return {}
    sessioni = dati.get("sessioni")
    return sessioni if isinstance(sessioni, dict) else {}


def salva_stato(percorso, sessioni):
    """Scrive lo stato corrente (unico file scritto dallo script)."""
    cartella = os.path.dirname(percorso)
    if cartella and not os.path.isdir(cartella):
        os.makedirs(cartella, exist_ok=True)
    stato = {
        "aggiornato": int(time.time()),
        "sessioni": {chiave_sessione(s): {
            "nome": s.get("nome"),
            "aspetta": attende_utente(s),
            "attese_per_utente": list(s.get("attese_per_utente") or []),
        } for s in sessioni},
    }
    with open(percorso, "w", encoding="utf-8") as f:
        json.dump(stato, f, ensure_ascii=False, indent=2)
        f.write("\n")


def _voci_salvate(prima):
    """Voci per l'utente ricordate nello stato precedente; None se non c'erano.

    I file scritti dalla versione vecchia non hanno l'elenco: in quel caso
    None significa "non lo sappiamo" e non si notifica di nuovo.
    """
    if "attese_per_utente" not in prima:
        return None
    voci = prima.get("attese_per_utente")
    if not isinstance(voci, list):
        return None
    return [v for v in voci if isinstance(v, str)]


def titolo_gruppo(quante):
    """Titolo dell'avviso unico quando ti aspettano piu' sessioni."""
    return "Sessioni: %d ti aspettano" % quante


def frase_gruppo(progetti):
    """Frase pronunciata: "<N> sessioni ti aspettano: <progetto1>, <progetto2>."."""
    return "%d sessioni ti aspettano: %s." % (len(progetti), ", ".join(progetti))


def _avviso_generico(modulo, titolo, testo, frase):
    """Notifica con titolo e frase scelti qui, anche con un posta.py piu' vecchio."""
    funzione = getattr(modulo, "avvisa_generico", None)
    if callable(funzione):
        funzione(titolo, testo, frase, urgente=True)
        return
    # posta.py installato prima degli avvisi raggruppati: stesse funzioni interne
    notifica = getattr(modulo, "_notifica", None)
    suona = getattr(modulo, "_suona_staccato", None)
    if callable(notifica) and callable(suona):
        notifica(titolo, testo)
        suona(frase, True)
        return
    modulo.avvisa(titolo, azione="decisione", testo=frase)


def avvisa_sessioni(sessioni, avvisatore=None, modulo=None):
    """Un solo avviso per giro: con una sessione si comporta come prima."""
    voci = list(sessioni or [])
    if not voci:
        return
    if len(voci) == 1:
        sessione = voci[0]
        avvisa_sessione(sessione.get("progetto") or "?", testo_notifica(sessione),
                        avvisatore=avvisatore, modulo=modulo)
        return
    progetti = [s.get("progetto") or "?" for s in voci]
    titolo = titolo_gruppo(len(progetti))
    frase = frase_gruppo(progetti)
    if avvisatore is not None:
        avvisatore(titolo, frase)
        return
    _avviso_generico(modulo or carica_posta(), titolo, frase, frase)


def sessioni_da_notificare(sessioni, precedente):
    """Sessioni che passano a "aspetta te" o che hanno una voce per te NUOVA."""
    da_notificare = []
    for s in sessioni:
        if not attende_utente(s):
            continue
        prima = precedente.get(chiave_sessione(s)) or {}
        if not isinstance(prima, dict):
            prima = {}
        attuali = s.get("attese_per_utente") or []
        if prima.get("aspetta"):
            vecchie = _voci_salvate(prima)
            if vecchie is None:      # stato vecchio senza elenco: niente doppioni
                continue
            nuove = [v for v in attuali if v not in vecchie]
            if not nuove:
                continue
            copia = dict(s)
            copia["voce_nuova"] = nuove[0]
            da_notificare.append(copia)
            continue
        da_notificare.append(s)
    return da_notificare


def esegui_notify(sessioni_dir, projects_dir, percorso_stato=STATO_FILE,
                  nomi_utente=None, avvisatore=None):
    """Confronta con lo stato salvato, notifica solo le nuove attese, salva lo stato."""
    sessioni = raccogli(sessioni_dir, projects_dir, includi_morte=False,
                        nomi_utente=nomi_utente)
    precedente = carica_stato(percorso_stato)
    avvisa_sessioni(sessioni_da_notificare(sessioni, precedente),
                    avvisatore=avvisatore)
    salva_stato(percorso_stato, sessioni)


# --------------------------------------------------------------------------
# Interfaccia a riga di comando
# --------------------------------------------------------------------------

def stampa_tabella(sessioni):
    colore = sys.stdout.isatty()
    print(render_tabella(sessioni, colore=colore))


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Mostra lo stato delle sessioni Claude Code aperte sul Mac.")
    parser.add_argument("--json", action="store_true", help="stampa la lista JSON")
    parser.add_argument("--watch", type=int, metavar="N",
                        help="aggiorna ogni N secondi (Ctrl+C per uscire)")
    parser.add_argument("--notify", action="store_true",
                        help="uso con launchd: notifica solo le nuove attese")
    parser.add_argument("--tutte", action="store_true", help="include le sessioni chiuse")
    parser.add_argument("--nome-utente", action="append", metavar="NOME", dest="nomi_utente",
                        help="nome che identifica te nelle righe IN ATTESA DI "
                             "(ripetibile; sostituisce l'elenco predefinito)")
    parser.add_argument("--sessioni-dir", default=SESSIONI_DIR,
                        help="cartella dei file <pid>.json (default ~/.claude/sessions)")
    parser.add_argument("--projects-dir", default=PROJECTS_DIR,
                        help="cartella delle conversazioni (default ~/.claude/projects)")
    args = parser.parse_args(argv)

    nomi_utente = None
    if args.nomi_utente:
        nomi_utente = [n.strip() for n in args.nomi_utente if n.strip()]
        if not nomi_utente:
            parser.error("--nome-utente vuole un nome non vuoto")

    if args.notify:
        try:
            esegui_notify(args.sessioni_dir, args.projects_dir, nomi_utente=nomi_utente)
        except Exception as errore:  # nessuna stampa: solo errori su stderr
            print("claude_stato: errore notifica: %s" % errore, file=sys.stderr)
            return 1
        return 0

    if args.watch is not None:
        intervallo = max(1, args.watch)
        try:
            while True:
                try:
                    sessioni = raccogli(args.sessioni_dir, args.projects_dir,
                                        includi_morte=args.tutte,
                                        nomi_utente=nomi_utente)
                except Exception as errore:   # riprova al giro successivo
                    print("claude_stato: errore nella lettura: %s" % errore,
                          file=sys.stderr)
                    time.sleep(max(1, args.watch))
                    continue
                sys.stdout.write("\033[H\033[2J")
                sys.stdout.write("Claude Code - aggiornato alle %s (Ctrl+C per uscire)\n\n"
                                 % time.strftime("%H:%M:%S"))
                if args.json:
                    print(json.dumps(sessioni, ensure_ascii=False, indent=2))
                else:
                    stampa_tabella(sessioni)
                sys.stdout.flush()
                time.sleep(intervallo)
        except KeyboardInterrupt:
            print("\nUscita.")
            return 0

    try:
        sessioni = raccogli(args.sessioni_dir, args.projects_dir,
                            includi_morte=args.tutte, nomi_utente=nomi_utente)
    except Exception as errore:   # un file che cambia durante la lettura
        print("claude_stato: errore nella lettura: %s" % errore, file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(sessioni, ensure_ascii=False, indent=2))
    else:
        stampa_tabella(sessioni)
    return 0


if __name__ == "__main__":
    sys.exit(main())
