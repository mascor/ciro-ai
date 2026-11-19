#!/usr/bin/env python3
# Faccia parlante - server locale.
# Gira solo su 127.0.0.1: serve la pagina della faccia, sintetizza la voce con
# Kokoro (voce italiana maschile Nicola, tutto in locale) e trascrive il
# microfono con whisper-cli. Nessun dato esce dal Mac.
#
# Avvio: ./avvia.command   oppure   ./server.py [porta]

import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cervello as modulo_cervello
from testi import lingua, t  # noqa: E402
import chat as modulo_chat
import nome as modulo_nome
import numeri as numeri_parlati
import testi as modulo_testi  # noqa: E402

# domande strutturate: registro, coordinatore e posta (stessa cartella di posta.py)
sys.path.insert(0, str(modulo_cervello.POSTA_SCRIPT.parent))
import coordinatore  # noqa: E402
import domande  # noqa: E402
import posta as modulo_posta  # noqa: E402

CARTELLA = Path(__file__).resolve().parent
KOKORO_DIR = Path.home() / ".local/share/kokoro"
MODELLO_KOKORO = KOKORO_DIR / "kokoro-v1.0.onnx"
VOCI_KOKORO = KOKORO_DIR / "voices-v1.0.bin"
CACHE = KOKORO_DIR / "cache-faccia"
MODELLO_WHISPER = Path.home() / ".local/share/whisper-cpp/ggml-large-v3-turbo-q5_0.bin"
# riconoscitore di voce (Silero) dentro whisper: il rumore e il silenzio non vengono
# trascritti, quindi niente "Grazie a tutti" inventati (misurato il 19/11/2026)
MODELLO_VAD = Path(os.environ.get("CIRO_MODELLO_VAD") or
                   Path.home() / ".local/share/whisper-cpp/ggml-silero-v5.1.2.bin")
WHISPER = "/opt/homebrew/bin/whisper-cli"
FFMPEG = "/opt/homebrew/bin/ffmpeg"

CONFIG_FACCIA = Path.home() / ".config/faccia"
FILE_CLAUDE_CODE = CONFIG_FACCIA / "claude-code.json"   # scritto da barra-stato.py
FILE_CONSUMI = CONFIG_FACCIA / "consumi.json"           # mandato dall'estensione Chrome

VOCE = os.environ.get("FACCIA_VOCE") or "im_nicola"
VELOCITA = float(os.environ.get("FACCIA_VELOCITA") or 1.1)   # 1.25 era troppo veloce (19/11)
LINGUA = os.environ.get("FACCIA_LINGUA") or "it"

# names that mean "the user" in the sessions' waiting lines (CIRO_NOMI_UTENTE=Mario,Mario Rossi)
NOMI_UTENTE = [n.strip() for n in (os.environ.get("CIRO_NOMI_UTENTE") or os.environ.get("CIRO_UTENTE")
                                   or "").split(",") if n.strip()] + ["l'utente", "utente"]
NOMI_UTENTE_RE = "|".join(re.escape(n) for n in NOMI_UTENTE)

_coda = []            # messaggi da far dire alla faccia
_coda_lock = threading.Lock()
_cervello = modulo_cervello.Cervello()
_cervello.chiudi_chat = lambda chiave: _chat.chiudi(chiave)
_cervello.riassunto_perso = lambda dal: frase_perso(dal)
_cervello_lock = threading.Lock()
_kokoro = None
_kokoro_lock = threading.Lock()
_credito = {"quando": 0.0, "valore": None}
_credito_lock = threading.Lock()
_consumi_lock = threading.Lock()
FONTI_CONSUMI = ("claude.ai", "opencode-go", "deepseek")

# frasi che whisper "sente" nel silenzio o nel rumore: non sono parole tue
ALLUCINAZIONI = ("sottotitoli", "amara.org", "grazie per la visione", "iscriviti al canale",
                 "grazie per l'attenzione", "a tutti per la visione",
                 "grazie a tutti", "buona visione", "alla prossima",
                 "thanks for watching", "thank you for watching", "please subscribe", "subtitles by")


def log(riga):
    print(time.strftime("%H:%M:%S ") + riga, flush=True)


def registra(tipo, **campi):
    """Registro completo per capire i bug: ~/.config/faccia/conversazioni.log"""
    modulo_cervello.registra({"ora": time.strftime("%Y-%m-%d %H:%M:%S"), "tipo": tipo, **campi})


def kokoro():
    global _kokoro
    if _kokoro is None:
        from kokoro_onnx import Kokoro
        log("carico la voce Kokoro...")
        _kokoro = Kokoro(str(MODELLO_KOKORO), str(VOCI_KOKORO))
        log("voce Kokoro pronta")
    return _kokoro


FILE_MUTO = CONFIG_FACCIA / "muto"   # contiene l'ora (epoch) fino a cui Ciro sta zitto


AVVIO_SERVER = int(time.time())
FILE_PAGINA = ("index.html", "testi.js", "faccia.js", "stile.css")


def versione():
    """Cambia quando si riavvia il server o cambia un file della pagina:
    la pagina la controlla e si ricarica da sola."""
    cartella = Path(__file__).resolve().parent
    ultimi = 0
    for nome in FILE_PAGINA:
        try:
            ultimi = max(ultimi, int((cartella / nome).stat().st_mtime))
        except OSError:
            pass
    return "%d-%d" % (AVVIO_SERVER, ultimi)


def muto():
    try:
        return time.time() < float(FILE_MUTO.read_text().strip() or 0)
    except (OSError, ValueError):
        return False


LETTERE_DETTE = {"A": "a", "B": "bi", "C": "ci", "D": "di", "E": "e"}


def voce_attuale():
    """(voce Kokoro, lingua Kokoro) per la lingua di Ciro; FACCIA_VOCE vale per l'italiano."""
    if lingua() == "it":
        return VOCE, LINGUA
    return modulo_testi.VOCI[lingua()], modulo_testi.KOKORO[lingua()]


def lingua_whisper():
    return modulo_testi.WHISPER[lingua()]


def cartella_audio():
    """Gli audio delle calibrazioni (banco di prova), separati per lingua."""
    return CONFIG_FACCIA / "collaudi" / ("audio" if lingua() == "it" else "audio-" + lingua())


def per_voce(testo):
    """Le lettere delle opzioni dette come nomi («B» -> «bi»): una lettera isolata
    letta da Kokoro non si capisce. Parole e sigle restano come sono."""
    if lingua() != "it":
        return testo or ""
    return re.sub(r"(?<![\w'])([A-E])(?![\w'])", lambda m: LETTERE_DETTE[m.group(1)], testo or "")


def parla_wav(testo, velocita=None):
    """Restituisce i byte del WAV con la voce che legge il testo."""
    testo = " ".join(testo.split())[:4000]
    if not testo:
        raise ValueError("testo vuoto")
    velocita = float(velocita or VELOCITA)
    testo = per_voce(testo)
    voce, lingua_kokoro = voce_attuale()
    chiave = hashlib.sha256((voce + "|%.2f|" % velocita + testo).encode("utf-8")).hexdigest()[:32]
    CACHE.mkdir(parents=True, exist_ok=True)
    percorso = CACHE / (chiave + ".wav")
    if percorso.exists():
        return percorso.read_bytes()
    import soundfile as sf
    with _kokoro_lock:
        campioni, frequenza = kokoro().create(testo, voice=voce, speed=velocita, lang=lingua_kokoro)
    dati = io.BytesIO()
    sf.write(dati, campioni, frequenza, format="WAV", subtype="PCM_16")
    byte_wav = dati.getvalue()
    try:
        percorso.write_bytes(byte_wav)
    except OSError:
        pass
    return byte_wav


# Due modelli (misurati sulla voce vera il 19/11): per l'audio breve (risposte,
# lettere, sì/no) il modello base capisce come il turbo ed e' 7 volte piu' veloce
# (0,2 s invece di 1,5 s); per le frasi lunghe e libere resta il turbo.
MODELLO_RAPIDO = Path(os.environ.get("CIRO_MODELLO_RAPIDO") or
                      Path.home() / ".local/share/whisper-cpp/ggml-base-q5_1.bin")
AUDIO_BREVE = float(os.environ.get("CIRO_AUDIO_BREVE") or 3.5)   # secondi (un «sì» registrato dura ~3,1 s)


CARTELLA_MODELLI = Path.home() / ".local/share/whisper-cpp"
MODELLI_CANDIDATI = {"base": "ggml-base-q5_1.bin", "small": "ggml-small-q5_1.bin",
                     "large-v3-turbo": "ggml-large-v3-turbo-q5_0.bin"}


def modello_rapido():
    """Il modello per l'audio breve: quello scelto dal banco di prova dopo la
    calibrazione (profilo voce), altrimenti MODELLO_RAPIDO."""
    scelto = modulo_cervello.profilo_voce().get("modello_breve")
    if scelto and (CARTELLA_MODELLI / MODELLI_CANDIDATI.get(scelto, "")).is_file():
        return CARTELLA_MODELLI / MODELLI_CANDIDATI[scelto]
    return MODELLO_RAPIDO


def scegli_modello(risultati):
    """{nome: (capite, secondi)} -> il piu' veloce che capisce quanto il grande, o None."""
    riferimento = risultati.get("large-v3-turbo", (0, 0))[0]
    buoni = [(secondi, nome) for nome, (capite, secondi) in risultati.items()
             if nome != "large-v3-turbo" and capite >= riferimento]
    return min(buoni)[1] if buoni else None


def scegli_modello_in_sottofondo():
    """Dopo una calibrazione: prova i modelli sulle frasi brevi registrate (banco di
    prova) e salva nel profilo il piu' veloce che non perde precisione."""
    def lavora():
        try:
            cartella = cartella_audio()
            etichette = json.loads((cartella / "etichette.json").read_text(encoding="utf-8"))
            alias = dict(modulo_cervello.LETTERE_SENTITE)
            alias.update(modulo_cervello.leggi_impostazioni().get("alias_lettere") or {})
            brevi = {f: e for f, e in etichette.items() if (cartella / f).is_file()
                     and ((cartella / f).stat().st_size - 44) / 32000.0 <= AUDIO_BREVE * 1.5}
            risultati = {}
            for nome, file_modello in MODELLI_CANDIDATI.items():
                percorso = CARTELLA_MODELLI / file_modello
                if not percorso.is_file():
                    continue
                capite, tempi = 0, []
                for file, attesa in brevi.items():
                    inizio = time.time()
                    esito = subprocess.run([WHISPER, "-m", str(percorso), "-l", lingua_whisper(), "-nt", "-np",
                                            "--vad", "-vm", str(MODELLO_VAD), "-vspd", "80", "-vp", "200",
                                            "-f", str(cartella / file)], capture_output=True, text=True,
                                           timeout=120)
                    tempi.append(time.time() - inizio)
                    sentita = pulisci_trascrizione(esito.stdout)
                    a, s = modulo_collaudo.normalizza(attesa), modulo_collaudo.normalizza(sentita)
                    capite += a == s or (len(a) == 1 and alias.get(s) == a)
                risultati[nome] = (capite, sorted(tempi)[len(tempi) // 2] if tempi else 0)
            scelto = scegli_modello(risultati)
            if scelto:
                modulo_cervello.aggiorna_profilo(modello_breve=scelto)
            registra("modello-scelto", scelto=scelto, risultati=risultati, frasi=len(brevi))
        except Exception as errore:  # noqa: BLE001
            registra("errore-modello", errore=repr(errore)[:300])
    threading.Thread(target=lavora, daemon=True).start()


# ultime frasi trascritte con il loro audio: se l'utente corregge una risposta
# capita male, quell'audio va nel banco di prova con l'etichetta giusta
import collections  # noqa: E402
_ultimi_audio = collections.deque(maxlen=6)


def _normale(testo):
    return re.sub(r"[^\w'àèéìòù]+", " ", (testo or "").lower()).strip()


def impara_audio(da_imparare, cartella=None):
    cartella = Path(cartella or cartella_audio())
    for testo, audio in reversed(_ultimi_audio):
        if _normale(testo) == da_imparare.get("sentito"):
            cartella.mkdir(parents=True, exist_ok=True)
            nome = "correzione-%s.wav" % time.strftime("%Y%m%d-%H%M%S")
            (cartella / nome).write_bytes(audio)
            file_etichette = cartella / "etichette.json"
            try:
                etichette = json.loads(file_etichette.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                etichette = {}
            etichette[nome] = da_imparare.get("giusta")
            file_etichette.write_text(json.dumps(etichette, ensure_ascii=False, indent=1), encoding="utf-8")
            registra("impara-audio", sentito=da_imparare.get("sentito"), giusta=da_imparare.get("giusta"))
            return nome
    return None


def passate_whisper(durata, rapido_esiste=None, grande=False):
    """Le passate da provare in ordine: (modello, con VAD). Per l'audio breve,
    se il VAD scarta tutto (una «A» cortissima), una seconda passata senza VAD."""
    if rapido_esiste is None:
        rapido_esiste = modello_rapido().is_file()
    if durata <= AUDIO_BREVE and grande:   # aspetta il nome: il modello grande sbaglia meno i nomi
        return [("preciso", True), ("preciso", False)]
    if durata <= AUDIO_BREVE and rapido_esiste:
        return [("rapido", True), ("rapido", False)]
    return [("preciso", True)]


def pulisci_trascrizione(testo):
    testo = re.sub(r"\[[^\]]*\]|\([^)]*\)", " ", testo or "")   # [Musica], (risate)
    testo = testo.replace("*", " ")                                 # *Ahh*
    return " ".join(testo.split())


# un verso da solo (respiro, esitazione, rumore) non e' una frase: whisper lo scrive
# come «e» e il modello rifaceva l'ultima domanda a ogni respiro (19/11)
# anche i sospiri e gli sbuffi («Pfff», «uff»: 19/11); «ah» resta: e' la lettera A
VERSO_RE = re.compile(r"^(?:e+h*|e+h*m+|u+h+|u+h*m+|m+h*|h+m+|p+f+|u+f+|f+|o+h+|s+h+|p+s+t*)$")


# dopo un'interruzione «Ciro, fermati» vuol dire solo: stai zitto (whisper a volte
# scrive «Spero fermati»: fino a due parole prima della parola di stop)
STOP_RE = re.compile(r"^\W*(?:[\w']+\W+){0,2}?(?:fermati|fermo|basta|zitto|stai zitto|taci|silenzio|"
                     r"aspetta|stop|wait|quiet|be quiet|enough|shut up)\W*$", re.I)


def solo_stop(testo):
    return bool(STOP_RE.match(testo or ""))


# «Ehi Ciro»: il riconoscimento del nome sta in nome.py (anche la calibrazione lo usa)
togli_nome = modulo_nome.togli_nome
_tentativi_nome = collections.deque(maxlen=5)   # frasi non riconosciute mentre aspettava il nome


def nota_ascolto_nome(testo, chiamato, adesso=None):
    """Mentre aspetta il nome: un tentativo non riconosciuto seguito entro 10 s da una
    chiamata riconosciuta era il nome detto male -> diventa una variante di questa voce."""
    adesso = time.time() if adesso is None else adesso
    if not chiamato:
        if testo:
            _tentativi_nome.append((adesso, testo))
        return []
    imparate = [t_ for quando, t_ in _tentativi_nome
                if adesso - quando <= 10 and modulo_nome.impara_variante(t_)]
    _tentativi_nome.clear()
    if imparate:
        registra("nome-imparato", varianti=imparate)
    return imparate


def solo_verso(testo):
    return bool(VERSO_RE.match(re.sub(r"[^a-z]", "", (testo or "").lower())))


def trascrivi(byte_audio, grande=False):
    """Trascrive un WAV (qualsiasi frequenza) in italiano con whisper.cpp."""
    if not MODELLO_WHISPER.exists():
        raise RuntimeError("manca il modello whisper in " + str(MODELLO_WHISPER))
    with tempfile.TemporaryDirectory() as tmp:
        grezzo = Path(tmp) / "voce.bin"
        grezzo.write_bytes(byte_audio)
        pronto = Path(tmp) / "voce16.wav"
        subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-i", str(grezzo),
                        "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(pronto)],
                       check=True, timeout=60)
        durata = max(0, pronto.stat().st_size - 44) / 32000.0
        testo = ""
        for modello, con_vad in passate_whisper(durata, grande=grande):
            # VAD tarato sulla voce vera: con i valori predefiniti una «A» detta da sola
            # (sotto 250 ms) veniva scartata; 80 ms e 200 ms di margine la tengono
            vad = (["--vad", "-vm", str(MODELLO_VAD), "-vspd", "80", "-vp", "200"]
                   if con_vad and MODELLO_VAD.is_file() else [])
            percorso = modello_rapido() if modello == "rapido" else MODELLO_WHISPER
            esito = subprocess.run([WHISPER, "-m", str(percorso), "-l", lingua_whisper(),
                                    "-nt", "-np", *vad, "-f", str(pronto)],
                                   capture_output=True, text=True, timeout=180)
            if esito.returncode != 0:
                raise RuntimeError("whisper: " + " ".join(esito.stderr.split())[-400:])
            testo = pulisci_trascrizione(esito.stdout)
            if testo:
                break
        # whisper "sente" queste frasi nel rumore; un "grazie" da solo non chiede
        # comunque nulla a Ciro, quindi si scarta anche quello
        if any(frase in testo.lower() for frase in ALLUCINAZIONI) or \
                re.sub(r"[^a-z]", "", testo.lower()) in ("grazie", "grazieatutti", "grazieate", "thankyou",
                                                         "thanks", "you", "thankyouforwatching", "bye"):
            log("scartata frase inventata da whisper: " + testo[:80])
            registra("ascolto-scartato", testo=testo, motivo="frase inventata da whisper")
            return ""
        if solo_verso(testo):
            registra("ascolto-scartato", testo=testo, motivo="solo un verso")
            return ""
        return testo


def chiave_deepseek():
    """Chiave delle API DeepSeek, se c'e' sul Mac."""
    if os.environ.get("DEEPSEEK_API_KEY"):
        return os.environ["DEEPSEEK_API_KEY"].strip()
    dal_portachiavi = modulo_cervello._chiave_deepseek()   # servizio ciro-deepseek
    if dal_portachiavi:
        return dal_portachiavi
    for percorso in (Path.home() / ".deepseek-key",
                     Path.home() / ".config/deepseek/key",
                     Path.home() / ".config/deepseek/api-key"):
        try:
            if percorso.is_file():
                testo = percorso.read_text(encoding="utf-8").strip()
                if testo:
                    return testo
        except OSError:
            continue
    return None


def credito_deepseek():
    """Saldo DeepSeek, letto al massimo ogni 5 minuti."""
    with _credito_lock:
        if _credito["valore"] is not None and time.time() - _credito["quando"] < 300:
            return _credito["valore"]
        valore = _leggi_credito_deepseek()
        _credito.update(quando=time.time(), valore=valore)
        return valore


def _leggi_credito_deepseek():
    chiave = chiave_deepseek()
    if not chiave:
        return {"disponibile": False, "nota": "chiave non trovata"}
    try:
        import urllib.request
        richiesta = urllib.request.Request(
            "https://api.deepseek.com/user/balance",
            headers={"Authorization": "Bearer " + chiave, "Accept": "application/json"},
        )
        with urllib.request.urlopen(richiesta, timeout=8) as risposta:
            dato = json.loads(risposta.read() or b"{}")
    except Exception as errore:  # noqa: BLE001
        return {"disponibile": False, "nota": str(errore)[:120]}
    saldo = (dato.get("balance_infos") or [{}])[0]
    return {
        "disponibile": bool(dato.get("is_available")),
        "valuta": saldo.get("currency") or "USD",
        "saldo": saldo.get("total_balance") or "0",
        "ricaricato": saldo.get("topped_up_balance") or "0",
        "regalato": saldo.get("granted_balance") or "0",
    }


def _testo(valore, massimo=80):
    return str(valore)[:massimo] if valore is not None else None


def _numero(valore):
    try:
        numero = float(valore)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(100.0, numero))


def pulisci_consumo(dato):
    """Tiene solo i campi attesi, con lunghezze limitate."""
    if not isinstance(dato, dict) or dato.get("fonte") not in FONTI_CONSUMI:
        raise ValueError("fonte non valida")
    voci = []
    for voce in (dato.get("voci") or [])[:6]:
        if isinstance(voce, dict):
            voci.append({"nome": _testo(voce.get("nome"), 30),
                         "percentuale": _numero(voce.get("percentuale")),
                         "reset": _testo(voce.get("reset"), 40)})
    return {
        "fonte": dato["fonte"],
        "account": _testo(dato.get("account"), 60) or "?",
        "voci": voci,
        "saldo": _testo(dato.get("saldo"), 40),
        "nota": _testo(dato.get("nota"), 120),
        "aggiornato": int(time.time()),
    }


def leggi_consumi():
    try:
        dati = json.loads(FILE_CONSUMI.read_text(encoding="utf-8"))
        return dati if isinstance(dati, dict) else {}
    except (OSError, ValueError):
        return {}


def salva_consumo(dato):
    pulito = pulisci_consumo(dato)
    with _consumi_lock:
        dati = leggi_consumi()
        dati[pulito["fonte"] + "|" + pulito["account"]] = pulito
        CONFIG_FACCIA.mkdir(parents=True, exist_ok=True)
        temporaneo = FILE_CONSUMI.with_suffix(".tmp")
        temporaneo.write_text(json.dumps(dati, ensure_ascii=False), encoding="utf-8")
        os.replace(temporaneo, FILE_CONSUMI)


def consumo_claude_code():
    """Limiti ufficiali di Claude Code, salvati dalla barra di stato."""
    try:
        dato = json.loads(FILE_CLAUDE_CODE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    limiti = dato.get("limiti") or {}
    voci = []
    for chiave, nome in (("five_hour", "5 ore"), ("seven_day", "Settimana")):
        limite = limiti.get(chiave) or {}
        if limite.get("used_percentage") is not None:
            voci.append({"nome": nome, "percentuale": _numero(limite.get("used_percentage")),
                         "reset": _testo(limite.get("resets_at"), 40)})
    return {"fonte": "claude-code", "account": _testo(dato.get("account"), 60),
            "voci": voci, "saldo": None, "nota": None,
            "aggiornato": dato.get("aggiornato")}


def consumo_deepseek_api():
    credito = credito_deepseek()
    if not credito.get("saldo"):
        return None
    return {"fonte": "deepseek", "account": "API", "voci": [],
            "saldo": "%s %s" % (credito["saldo"], credito.get("valuta") or "USD"),
            "nota": None, "aggiornato": int(_credito["quando"])}


ORDINE_FONTI = {"claude-code": 0, "claude.ai": 0, "opencode-go": 1, "deepseek": 2}
ORGANIZZAZIONE_RE = re.compile(r"['’]s organi[sz]ation$", re.IGNORECASE)


def _chiave_account(nome):
    """Same key for the same account: Claude Code names the personal
    organisation "<email>'s Organization", the Chrome extension just "<email>"."""
    return ORGANIZZAZIONE_RE.sub("", (nome or "").strip()).strip().lower()


def _nome_account(nome):
    chiave = _chiave_account(nome)
    for originale, breve in NOMI_ACCOUNT.items():
        if _chiave_account(originale) == chiave:
            return breve
    return nome


def _istante_reset(reset):
    """Reset time in seconds since the epoch (number or ISO date), or None."""
    testo = str(reset or "").strip()
    if not testo:
        return None
    if testo.isdigit():
        return float(testo)
    try:
        from datetime import datetime
        return datetime.fromisoformat(testo.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _voce_attuale(voce, adesso):
    """A limit whose reset time has passed is back to 0% used, even if the
    last reading (maybe hours old) said otherwise."""
    istante = _istante_reset(voce.get("reset"))
    if istante is not None and istante <= adesso:
        return dict(voce, percentuale=0.0, reset="")
    return voce


def consumi():
    """Un blocco per account. Se lo stesso account arriva da due strade
    (barra di stato ed estensione, oppure API ed estensione) tengo il piu' recente."""
    candidati = list(leggi_consumi().values())
    for extra in (consumo_claude_code(), consumo_deepseek_api()):
        if extra:
            candidati.append(extra)
    scelti = {}
    for consumo in candidati:
        famiglia = "claude" if consumo.get("fonte") in ("claude-code", "claude.ai") else consumo.get("fonte")
        chiave = famiglia if famiglia == "deepseek" else famiglia + "|" + _chiave_account(consumo.get("account"))
        if chiave not in scelti or (consumo.get("aggiornato") or 0) > (scelti[chiave].get("aggiornato") or 0):
            scelti[chiave] = consumo
    adesso = time.time()
    elenco = []
    for consumo in scelti.values():
        consumo = dict(consumo)
        consumo["account"] = _nome_account(consumo.get("account"))
        consumo["voci"] = [_voce_attuale(voce, adesso) for voce in consumo.get("voci") or []]
        elenco.append(consumo)
    return sorted(elenco, key=lambda v: (ORDINE_FONTI.get(v.get("fonte"), 9), (v.get("account") or "").lower()))


# nomi brevi per gli account (le organizzazioni personali hanno come nome l'email)
# tenuti fuori dal repository: ~/.config/faccia/nomi-account.json {"email": "nome breve"}
try:
    NOMI_ACCOUNT = json.loads((CONFIG_FACCIA / "nomi-account.json").read_text(encoding="utf-8"))
except (OSError, ValueError):
    NOMI_ACCOUNT = {}
AZIONI_PER_TE = {"decisione": "decisione", "conferma-server": "conferma sul server",
                 "accesso": "accesso"}
# un messaggio di un progetto senza sessione aperta resta in "Ti aspettano" al massimo
# 2 ore (un agente su un server non ha sessione sul Mac): dopo, chi l'ha mandato non c'e' piu'
SENZA_SESSIONE_MAX = 2 * 3600


def attese(sessioni=None):
    """Cosa aspetta l'utente: sessioni ferme su una sua risposta e
    messaggi della posta che chiedono una decisione, una conferma o un accesso."""
    elenco = []
    if sessioni is None:
        sessioni = modulo_cervello.leggi_sessioni() or []
    adesso_s = time.time()
    # quando ogni progetto si e' mosso l'ultima volta (cambio di stato della sessione)
    mossa = {}
    for sessione in sessioni:
        quando = adesso_s - int(sessione.get("da_secondi") or 0)
        progetto = sessione.get("progetto")
        mossa[progetto] = max(mossa.get(progetto, 0), quando)
    for sessione in sessioni:
        if not sessione.get("aspetta_utente"):
            continue
        # Ciro ha gia' mandato la tua risposta dopo che la sessione si e' fermata:
        # non la ripropone mentre la sessione la legge (torna se chiede di nuovo)
        ferma_dal = adesso_s - int(sessione.get("da_secondi") or 0)
        if _cervello.decisioni_mandate.get(sessione.get("progetto"), 0) > ferma_dal:
            continue
        testo = (sessione.get("domanda") or "").strip()
        a_voce = bool(testo)   # a voce solo le domande vere, non le righe di attesa
        if not testo:
            testo = "; ".join((sessione.get("attese_per_utente") or [])[:1]).strip()
        elenco.append({"progetto": sessione.get("progetto"), "tipo": "domanda", "a_voce": a_voce,
                       "testo": (testo or "aspetta una tua risposta")[:280],
                       "secondi": int(sessione.get("da_secondi") or 0)})
    try:
        schede = domande.elenca()
    except Exception:  # noqa: BLE001
        schede = []
    con_scheda = {s.get("id") for s in schede}
    for scheda in schede:
        if scheda.get("stato") != "in-attesa":
            continue
        dal = float((scheda.get("storia") or [{}])[0].get("t") or adesso_s)
        elenco.append({"progetto": scheda.get("progetto"), "sessione": scheda.get("sessione"), "tipo": "decisione",
                       "testo": (scheda.get("domanda") or "")[:280],
                       "secondi": int(adesso_s - dal), "domanda_id": scheda.get("id"),
                       "opzioni": modulo_cervello.opzioni_per_voce(scheda),
                       "operazione": scheda.get("operazione"),
                       "nome_credenziale": nome_credenziale(scheda),
                       "dettaglio": frase_domanda(scheda)})
    try:
        uscita = subprocess.run([sys.executable, str(modulo_cervello.POSTA_SCRIPT), "elenco",
                                 "--casella", modulo_cervello.CASSELLA, "--json"],
                                capture_output=True, text=True, timeout=20)
        posta = json.loads(uscita.stdout or "[]")
    except Exception:  # noqa: BLE001
        posta = []
    adesso = time.time()
    for messaggio in posta if isinstance(posta, list) else []:
        tipo = AZIONI_PER_TE.get(messaggio.get("azione"))
        if not tipo or messaggio.get("id") in con_scheda or messaggio.get("domanda_id"):
            continue  # le domande strutturate le segue il loro registro
        try:
            from datetime import datetime
            inviato = datetime.fromisoformat(messaggio.get("data")).timestamp()
        except Exception:  # noqa: BLE001
            inviato = adesso
        secondi = int(adesso - inviato)
        progetto = messaggio.get("da")
        # gia' gestita: Ciro ha mandato la tua risposta a quel progetto dopo il
        # messaggio, oppure la sessione e' andata avanti (stato cambiato oltre
        # 45 s dopo il messaggio: le hai risposto direttamente)
        if _cervello.decisioni_mandate.get(progetto, 0) > inviato:
            continue
        if mossa.get(progetto, 0) > inviato + 45:
            continue
        if progetto not in mossa and secondi > SENZA_SESSIONE_MAX:
            continue  # vecchio e la sessione non e' aperta: non lo dico e non lo mostro
        elenco.append({"progetto": messaggio.get("da"), "tipo": tipo,
                       "testo": (messaggio.get("oggetto") or "")[:280], "secondi": secondi,
                       # il corpo porta la domanda completa con le opzioni A/B/C
                       "dettaglio": modulo_cervello._inizio_testo(messaggio)[:3000]})
    for voce in _chat.aperte(adesso_s):
        elenco.append({"progetto": "chat", "tipo": "chat", "chat_id": voce["chiave"],
                       "account": voce.get("account"), "mittente": voce.get("nome"),
                       "diretto": voce.get("diretto"), "urgente": voce.get("urgente"),
                       "risposta": voce.get("risposta"), "motivo": voce.get("motivo"),
                       "testo": (voce.get("testo") or t("Messaggi non letti"))[:280], "a_voce": False,
                       "secondi": int(adesso_s - voce.get("visto", adesso_s))})
    for account, secondi in _chat.letture_fallite(adesso_s).items():
        # zero messaggi e lettura fallita sono diversi: questa si vede nel pannello
        elenco.append({"progetto": "chat", "tipo": "chat", "chat_id": "lettura|" + account,
                       "account": account, "mittente": t("Lettura non riuscita"),
                       "testo": t("Non riesco a leggere i messaggi non letti: ricarica la scheda di Google Chat."),
                       "urgente": False, "a_voce": False, "secondi": secondi})
    # prima chi aspetta da piu' tempo; i messaggi di Chat non urgenti in fondo
    elenco.sort(key=lambda v: (v.get("tipo") == "chat" and not v.get("urgente"), -v["secondi"]))
    numera(elenco)
    return elenco[:40]   # il pannello scorre (19/11/2026): prima 10, e i messaggi di Chat sparivano


def chiave_numero(voce):
    if voce.get("chat_id"):
        return "chat|" + voce["chat_id"]   # stesso numero finche' la conversazione resta aperta
    return voce.get("domanda_id") or _chiave(voce)


def numera(elenco):
    """Ogni domanda aperta ha il suo numero («domanda tre»): lo stesso finche' resta aperta."""
    numeri = _cervello.numeri
    for voce in elenco:
        # la frase completa la salva chi la dice (avvisi, domande); qui solo una di riserva
        riserva = t("Da %s: %s") % (voce.get("progetto") or t("una sessione"), _testo_parlabile(voce.get("testo")))
        voce["numero"] = numeri.numero(chiave_numero(voce), predefinite={"frase": riserva},
                                       progetto=voce.get("progetto"), domanda_id=voce.get("domanda_id"))
    numeri.allinea({chiave_numero(v) for v in elenco})


def con_numero(frase, numero, parola="Domanda %s, "):
    """«Da alpha: ...» -> «Domanda tre, da alpha: ...» (o «Messaggio tre, ...»)."""
    if not numero:
        return frase
    return t(parola) % numeri_parlati.parola(numero, lingua()) + frase[:1].lower() + frase[1:]


# ----------------------------------------------- avvisi spontanei di Ciro
# Ogni 8 secondi guarda "Ti aspettano": quando compare una domanda nuova di una
# sessione o un messaggio che chiede una decisione, la fa dire a Ciro subito.
_visti = None


def _chiave(voce):
    return "%s|%s|%s" % (voce.get("progetto"), voce.get("tipo"), voce.get("testo"))


def _testo_parlabile(testo):
    """Toglie percorsi di file, link e riferimenti ai messaggi: non si leggono a voce."""
    testo = re.sub(r"\(\s*messaggio:[^)]*\)?", " ", testo or "", flags=re.I)
    testo = re.sub(r"(https?://|/Users/|~/)\S+", " ", testo)
    testo = re.sub(r"^\s*(?:%s),?\s*(che\s+)?(deve|devi)\s+" % NOMI_UTENTE_RE, "", testo, flags=re.I)
    testo = re.sub(r"\s+", " ", testo).strip(" .,;:")
    return testo[:1].upper() + testo[1:]


_ultimo_avviso = {}   # progetto -> ora dell'ultimo avviso detto


def _frase_avviso(voce):
    progetto = voce.get("progetto") or t("una sessione")
    testo = _testo_parlabile(voce.get("testo"))
    if voce.get("tipo") == "domanda":
        return t("Da %s: %s. Come rispondo?") % (progetto, testo)
    dettaglio = voce.get("dettaglio") or ""
    if len(dettaglio) > 250:  # domanda lunga: la riduco per la voce (domanda + opzioni)
        breve = _testo_parlabile(modulo_cervello.domanda_per_voce(dettaglio))
        if breve:
            return t("Da %s: %s. Come rispondo?") % (progetto, breve)
    elif dettaglio:
        return t("Da %s, serve una %s: %s. Come rispondo?") % (progetto, t(voce.get("tipo") or ""),
                                                           _testo_parlabile(dettaglio))
    return t("Da %s, serve una %s: %s. Come rispondo?") % (progetto, t(voce.get("tipo") or ""), testo)


# -------------------------------------------------------------- Google Chat
# L'estensione «Ciro Agente» manda i non letti di ogni profilo; solo i messaggi
# diretti vanno al modello per l'urgenza. Ciro dice quelli urgenti che aspettano
# una risposta e li ricorda ogni 15 minuti finche' restano non letti.
# accanto al contesto di Ciro (~/.config/faccia): un Ciro di prova ha il suo
_chat = modulo_chat.Chat(lambda: Path(modulo_cervello.CONTESTO).with_name("chat.json"))
_promemoria_chat = {}   # chiave -> ultima volta che Ciro l'ha detto
_frasi_chat = []        # le ultime frasi di Chat dette: il loro testo non va nel registro (impostazione)


def _chiedi_urgenza(prompt):
    uscita, _, codice = modulo_cervello.chiedi_modello(prompt, 8)
    return uscita if codice == 0 else ""


def _giudica(voci):
    for voce in voci:
        if voce.get("diretto"):
            _chat.imposta_urgenza(voce["chiave"], modulo_chat.valuta_urgenza(
                voce, _chiedi_urgenza, inglese=lingua() == "en"))


def ricevi_chat(dato, in_sottofondo=True):
    if dato.get("conversazioni") is None:   # l'elenco non e' nella pagina: solo conteggi, per capire dove sta
        if (dato.get("diagnosi") or {}).get("cornice") != "interna":
            # lettura fallita, non «zero messaggi» (le cornici di Chat dentro Gmail non hanno l'elenco: normale)
            _chat.lettura_fallita(dato.get("account"))
        try:
            file_diagnosi = Path(modulo_cervello.CONTESTO).with_name("chat-diagnosi.json")
            vecchie = json.loads(file_diagnosi.read_text(encoding="utf-8")) if file_diagnosi.exists() else []
            vecchie = (vecchie + [dict(dato.get("diagnosi") or {}, ora=time.strftime("%H:%M:%S"))])[-30:]
            file_diagnosi.write_text(json.dumps(vecchie, ensure_ascii=False, indent=1), encoding="utf-8")
        except (OSError, ValueError):
            pass
        return
    nuove = _chat.aggiorna(dato.get("account"), dato.get("conversazioni") or [])
    if not nuove or not modulo_cervello.leggi_impostazioni().get("chat_al_modello", True):
        return   # impostazione spenta: nessun messaggio al modello, restano nel pannello
    if in_sottofondo:
        threading.Thread(target=_giudica, args=(nuove,), daemon=True).start()
    else:
        _giudica(nuove)


def testo_per_registro(testo):
    """Una frase di Chat detta da Ciro: nel registro solo se l'impostazione lo permette."""
    pulito = (testo or "").strip()
    if len(pulito) >= 8 and any(pulito in frase or frase in pulito for frase in _frasi_chat):
        return "[messaggio di Google Chat: testo non registrato]"
    return testo


def giro_chat(adesso=None):
    """Dice i messaggi urgenti che aspettano una risposta; li ricorda ogni 15 minuti."""
    adesso = time.time() if adesso is None else adesso
    voci = [v for v in attese() if v.get("tipo") == "chat"]
    aperte = {v["chat_id"] for v in voci}
    for chiave in [k for k in _promemoria_chat if k not in aperte]:
        del _promemoria_chat[chiave]
    if in_pausa("chat"):
        return
    for voce in voci:
        if not (voce.get("urgente") and voce.get("risposta")):
            continue
        ultima = _promemoria_chat.get(voce["chat_id"])
        if ultima is not None and adesso - ultima < modulo_chat.PROMEMORIA:
            continue
        testo = _testo_parlabile(voce.get("testo"))[:300]
        numero = numeri_parlati.parola(voce.get("numero") or 0, lingua())
        if ultima is None:
            frase = con_numero(t("Da %s: %s. Come rispondo?") % (voce.get("mittente") or "?", testo),
                               voce.get("numero"), "Messaggio %s, ")
        else:
            frase = t("Ti ricordo il messaggio %s, da %s: %s.") % (numero, voce.get("mittente") or "?", testo)
        _promemoria_chat[voce["chat_id"]] = adesso
        _in_coda({"testo": frase, "da": "chat", "progetto": "chat", "quando": adesso})
        _cervello.annota_avviso("chat", frase, domanda=False)
        if modulo_cervello.leggi_impostazioni().get("chat_nel_registro"):
            registra("chat-avviso", testo=frase)
        else:
            _frasi_chat.append(frase)
            del _frasi_chat[:-20]
            registra("chat-avviso", chat_id=voce["chat_id"].split("|")[0] + "|…", promemoria=ultima is not None)


def giro_avvisi():
    """Un giro: dice le domande nuove delle sessioni e della posta."""
    global _visti
    voci = attese()
    chiavi = {_chiave(v): v for v in voci}
    if _visti is None:
        _visti = set(chiavi)  # all'avvio: quelle gia' presenti le dice se glielo chiedi
    for chiave, voce in chiavi.items():
        if chiave in _visti or voce.get("domanda_id"):
            continue  # le domande strutturate le annuncia sorveglia_domande
        if voce.get("a_voce") is False:
            continue  # una riga di attesa, non una domanda: resta solo nel pannello
        progetto = voce.get("progetto")
        if in_pausa(progetto):
            _in_pausa.append(progetto)
            continue
        if time.time() - _ultimo_avviso.get(progetto, 0) < 90:
            continue  # stessa sessione appena annunciata (sessione e posta insieme)
        _ultimo_avviso[progetto] = time.time()
        frase = _frase_avviso(voce)
        _cervello.numeri.numero(chiave_numero(voce), frase=frase, detta=True)
        frase = con_numero(frase, voce.get("numero"))
        with _coda_lock:
            if len(_coda) < 10:
                _coda.append({"testo": frase, "da": "avvisi", "chiave": chiave,
                              "progetto": progetto, "quando": time.time()})
        _cervello.annota_avviso(voce.get("progetto"), frase,
                                domanda=voce.get("tipo") in ("domanda", "decisione"))
        registra("avviso", testo=frase)
    _visti = set(chiavi)
    giro_chat()


def sorveglia_attese():
    while True:
        try:
            giro_avvisi()
        except Exception as errore:  # noqa: BLE001
            registra("errore-avvisi", errore=repr(errore)[:300])
        time.sleep(8)


# --------------------------------------------- coda al risveglio
# Mentre Ciro dorme gli avvisi si accumulano: quando la pagina li prende, Ciro
# dice solo quelli ancora aperti, e se le domande sono piu' di 3 una frase sola.
ETA_MASSIMA_CODA = 15 * 60
DOMANDE_DA_LEGGERE = 3


def filtra_coda(voci, attuali=None, adesso=None):
    adesso = time.time() if adesso is None else adesso
    tenute = []
    for voce in voci:
        if voce.get("domanda_id") and voce.get("tipo") == "domanda":
            try:
                aperta = domande.leggi(voce["domanda_id"]).get("stato") == "in-attesa"
            except Exception:  # noqa: BLE001
                aperta = False
        elif voce.get("da") == "avvisi" and voce.get("chiave"):
            if attuali is None:
                try:
                    attuali = {_chiave(v) for v in attese()}
                except Exception:  # noqa: BLE001
                    attuali = set()
            aperta = voce["chiave"] in attuali
        else:
            aperta = adesso - float(voce.get("quando") or adesso) <= ETA_MASSIMA_CODA
        if aperta:
            tenute.append(voce)
    da_decidere = [v for v in tenute if v.get("tipo") == "domanda" or v.get("da") == "avvisi"]
    if len(da_decidere) > DOMANDE_DA_LEGGERE:
        progetti = [v.get("progetto") or t("una sessione") for v in da_decidere]
        frase = (t("Ci sono %d domande per te: da %s. Le trovi a sinistra; dimmi da quale parto.")
                 % (len(da_decidere), _elenco(progetti)))
        tenute = [v for v in tenute if v not in da_decidere] + [
            {"testo": frase, "da": "riassunto", "quando": adesso}]
        # una risposta breve adesso non deve andare a una domanda mai letta
        _cervello.ultimo_detto = {"tipo": "avviso", "id": None, "ora": adesso}
        registra("coda-riassunta", testo=frase)
    return tenute


# ------------------------------------------------- domande strutturate
# Ogni 2 secondi: le domande nuove (posta.py chiedi) passano dal coordinatore.
# Se una regola risponde, la risposta parte subito; altrimenti Ciro dice la
# domanda. Il modello serve solo per le preferenze ed e' in sottofondo.
INTERVALLO_DOMANDE = 2.0
ATTESA_MODELLO = 2.0   # oltre, la domanda si dice comunque
# parole troppo comuni per dire che una preferenza riguarda una domanda
PAROLE_VUOTE = {"sempre", "quando", "prima", "dopo", "della", "delle", "degli", "dello", "questo",
                "questa", "quello", "quella", "sessione", "sessioni", "utente", "domanda",
                "domande", "risposta", "risposte", "rispondi", "chiedi", "chiedimi", "agente",
                "agenti", "parola", "parole", "breve", "chiaro", "chiara", "opzioni", "ancora"}


def _parole(testo):
    import unicodedata
    testo = unicodedata.normalize("NFKD", (testo or "").lower())
    testo = "".join(c for c in testo if not unicodedata.combining(c))
    return {p for p in re.findall(r"[a-z0-9]{5,}", testo) if p not in PAROLE_VUOTE}


def preferenze_pertinenti(preferenze, scheda):
    """Solo le preferenze che hanno parole in comune con la domanda: le altre
    non possono coprirla, e il modello si risparmia (e Ciro non aspetta)."""
    domanda = _parole(" ".join([scheda.get("domanda") or "", scheda.get("oggetto") or "",
                                scheda.get("progetto") or ""] + list((scheda.get("opzioni") or {}).values())))
    return [p for p in preferenze if _parole(p) & domanda]


def _come_scritto(testo):
    """Parlabile, ma con l'iniziale come l'ha scritta la sessione."""
    pulito = _testo_parlabile(testo)
    originale = (testo or "").strip()
    if pulito and originale[:1].islower():
        pulito = pulito[:1].lower() + pulito[1:]
    return pulito


def nome_da_dire(scheda):
    """«test, OPENCODE-SKILLS» se la sessione ha un nome dato con /rename, se no il progetto."""
    progetto = scheda.get("progetto") or t("una sessione")
    sessione = (scheda.get("sessione") or "").strip()
    return "%s, %s" % (sessione, progetto) if sessione and sessione.lower() != progetto.lower() else progetto


def frase_domanda(scheda):
    domanda = _testo_parlabile(scheda.get("domanda") or scheda.get("oggetto") or "")
    if domanda and domanda[-1] not in "?.!":
        domanda += "."
    dette = modulo_cervello.opzioni_per_voce(scheda)
    # a voce le opzioni sono numeri («uno, procedi; due, fermati»): le lettere si confondono
    opzioni = "; ".join("%s, %s" % (modulo_cervello.nome_opzione(lettera), _come_scritto(testo))
                        for lettera, testo in dette.items())
    frase = t("Da %s: %s") % (nome_da_dire(scheda), domanda)
    if scheda.get("operazione") == "credenziali":
        return frase + t(" Scrivila nel campo protetto della pagina.")
    if opzioni:
        frase += " %s." % opzioni
    if scheda.get("raccomanda") and dette == scheda.get("opzioni"):
        frase += t(" Consiglia %s.") % modulo_cervello.nome_opzione(scheda["raccomanda"])
    return frase + t(" Come rispondo?")


# -------------------------------------------------------- pausa progetti
# Durante i test (o quando vuoi concentrarti) Ciro non annuncia le sessioni,
# tranne i progetti permessi; le domande restano nel pannello e alla ripresa
# Ciro dice in una frase cosa e' arrivato.
_in_pausa = []   # progetti di cui non ha detto le domande durante la pausa


def stato_pausa():
    impostazioni = modulo_cervello.leggi_impostazioni()
    return {"attiva": bool(impostazioni.get("pausa_progetti")),
            "solo": list(impostazioni.get("solo_progetti") or [])}


def in_pausa(progetto):
    stato = stato_pausa()
    return stato["attiva"] and progetto not in stato["solo"]


def imposta_pausa(attiva, solo=None):
    modulo_cervello.imposta("pausa_progetti", bool(attiva))
    modulo_cervello.imposta("solo_progetti", [str(p) for p in (solo or []) if str(p).strip()][:10])
    registra("pausa-progetti", attiva=bool(attiva), solo=solo or [])
    return stato_pausa()


def frase_ripresa():
    if stato_pausa()["attiva"] or not _in_pausa:
        return ""
    progetti = list(_in_pausa)
    _in_pausa.clear()
    return (t("Durante la pausa sono arrivate %d domande: da %s. Le trovi a sinistra.")
            % (len(progetti), _elenco(progetti)))


def _in_coda(voce):
    voce.setdefault("quando", time.time())
    with _coda_lock:
        if len(_coda) < 20:
            _coda.append(voce)


def _metti_in_attesa(scheda):
    try:
        scheda = domande.passa(scheda["id"], "in-attesa", "ciro", "detta a voce")
    except (domande.PassaggioNonAmmesso, domande.SchedaNonTrovata):
        return  # nel frattempo e' cambiata (annullata dalla sessione)
    if in_pausa(scheda.get("progetto")):
        _in_pausa.append(scheda.get("progetto"))
        registra("domanda-in-pausa", domanda_id=scheda["id"])
        return  # resta nel pannello, la dira' il riassunto alla ripresa
    numero = _cervello.numeri.numero(scheda["id"], progetto=scheda.get("progetto"), domanda_id=scheda["id"],
                                     frase=frase_domanda(scheda), detta=True)
    frase = con_numero(frase_domanda(scheda), numero)
    _in_coda({"testo": frase, "da": "domande", "tipo": "domanda", "progetto": scheda.get("progetto"),
              "domanda_id": scheda["id"], "opzioni": modulo_cervello.opzioni_per_voce(scheda),
              "operazione": scheda.get("operazione"), "nome_credenziale": nome_credenziale(scheda)})
    _cervello.annota_domanda(scheda, frase)
    registra("domanda", domanda_id=scheda["id"], testo=frase)


def _consegna_automatica(scheda, esito):
    motivo = "regola:%s" % re.sub(r"[^A-Za-z0-9_-]", "-", str(esito.get("regola") or "preferenza"))
    try:
        modulo_posta.rispondi_domanda(scheda["id"], esito["scelta"], None, motivo[:88], "opencode")
    except modulo_posta.ErroreStato:
        return
    except Exception as errore:  # noqa: BLE001
        registra("errore-domande", domanda_id=scheda["id"], errore=repr(errore)[:300])
        _in_coda({"testo": t("Non riesco a consegnare la risposta a %s.") % scheda.get("progetto"),
                  "da": "domande"})
        return
    if in_pausa(scheda.get("progetto")):
        registra("risposta-automatica", domanda_id=scheda["id"], scelta=esito["scelta"],
                 regola=esito.get("regola"), in_pausa=True)
        return
    frase = t("Ho risposto %s a %s, per la tua regola: %s.") % (
        esito["scelta"], scheda.get("progetto"), _testo_parlabile(esito.get("motivo") or ""))
    _in_coda({"testo": frase, "da": "domande", "tipo": "automatica",
              "progetto": scheda.get("progetto"), "domanda_id": scheda["id"]})
    _cervello.annota_automatica(scheda, frase)
    registra("risposta-automatica", domanda_id=scheda["id"], scelta=esito["scelta"],
             regola=esito.get("regola"))


def _valuta_con_modello(scheda, preferenze, autorizzazioni):
    """Il modello confronta le preferenze; se ci mette troppo decide l'utente."""
    risultato = {}

    def lavora():
        risultato["esito"] = coordinatore.valuta(scheda, preferenze, autorizzazioni,
                                                 _cervello.chiedi_preferenze)
    filo = threading.Thread(target=lavora, daemon=True)
    filo.start()
    filo.join(ATTESA_MODELLO)
    esito = risultato.get("esito") if not filo.is_alive() else None
    if esito and esito["esito"] == "automatica":
        _consegna_automatica(scheda, esito)
    else:
        _metti_in_attesa(scheda)


def giro_domande():
    """Un giro sul registro. Ritorna i fili avviati per il modello (per i test)."""
    fili = []
    domande.sblocca_ferme(120)
    for scheda in domande.elenca("ricevuta"):
        try:
            scheda = domande.passa(scheda["id"], "in-valutazione", "ciro")
        except (domande.PassaggioNonAmmesso, domande.SchedaNonTrovata):
            continue  # la sta valutando un altro giro
        if scheda.get("canale") == "hook":
            _metti_in_attesa(scheda)   # dagli hook delle sessioni: risponde solo l'utente
            continue
        autorizzazioni = coordinatore.carica_autorizzazioni()
        esito = coordinatore.valuta(scheda, [], autorizzazioni, None)
        preferenze = preferenze_pertinenti(modulo_cervello.leggi_regole(), scheda)
        if esito["esito"] == "automatica":
            _consegna_automatica(scheda, esito)
        elif scheda.get("operazione") == "scelta" and preferenze:
            filo = threading.Thread(target=_valuta_con_modello,
                                    args=(scheda, preferenze, autorizzazioni), daemon=True)
            filo.start()
            fili.append(filo)
        else:
            _metti_in_attesa(scheda)
    return fili


# ------------------------------------------------- hook delle sessioni
# «Ciro connect» (docs/hooks-design.md): Claude Code manda a /hooks/claude le
# richieste di permesso e le domande a scelta. Ciro le fa diventare domande
# numerate (solo registro, niente posta), aspetta la risposta dell'utente e la
# restituisce alla sessione. Se Ciro e' spento, zitto o in pausa, o se l'utente
# non risponde in tempo, risposta vuota: la sessione chiede nel terminale.
ATTESA_HOOK = 60          # secondi; il timeout dell'hook in settings.json e' 75
PAGINA_SVEGLIA = 15       # la pagina sveglia chiede i messaggi ogni pochi secondi
_pagina = {"sveglia": 0.0}


def segna_pagina_sveglia():
    _pagina["sveglia"] = time.time()


def pagina_sveglia():
    return time.time() - _pagina["sveglia"] <= PAGINA_SVEGLIA


def _corto(testo, massimo=120):
    testo = re.sub(r"\s+", " ", str(testo or "")).strip()
    return testo if len(testo) <= massimo else testo[:massimo - 1].rstrip() + "…"


def riassunto_permesso(strumento, ingresso):
    """Cosa vuole fare la sessione, in una frase breve da dire a voce."""
    ingresso = ingresso if isinstance(ingresso, dict) else {}
    if strumento == "Bash":
        return t("vuole eseguire: %s") % _corto(ingresso.get("command"), 100)
    if strumento in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        return t("vuole modificare il file %s") % os.path.basename(
            str(ingresso.get("file_path") or ingresso.get("notebook_path") or "?"))
    if strumento in ("WebFetch", "WebSearch"):
        dove = urlparse(str(ingresso.get("url") or "")).hostname or _corto(ingresso.get("query"), 60)
        return t("vuole consultare il web: %s") % dove
    if strumento.startswith("mcp__"):
        parti = strumento.split("__")
        return t("vuole usare %s di %s") % (parti[-1], parti[1] if len(parti) > 2 else "?")
    return t("vuole usare %s") % strumento


def titolo_sessione(percorso, massimo=20_000_000):
    """Il nome dato alla sessione con /rename (riga «custom-title» del transcript), o ""."""
    titolo = ""
    try:
        if not percorso or Path(percorso).stat().st_size > massimo:
            return ""
        with open(percorso, encoding="utf-8", errors="ignore") as ingresso:
            for riga in ingresso:
                if '"custom-title"' not in riga:
                    continue
                try:
                    voce = json.loads(riga)
                except ValueError:
                    continue
                if voce.get("type") == "custom-title":
                    titolo = str(voce.get("customTitle") or "").strip()
    except OSError:
        return ""
    return _corto(titolo, 60)


def _domanda_da_hook(dato):
    """(progetto, oggetto, domanda, opzioni, operazione, risposta) o None se non la gestiamo.
    `risposta(scelta)` costruisce l'uscita dell'hook per la lettera scelta."""
    evento = dato.get("hook_event_name")
    progetto = os.path.basename(str(dato.get("cwd") or "").rstrip("/")) or "sessione"
    strumento = str(dato.get("tool_name") or "")
    ingresso = dato.get("tool_input") if isinstance(dato.get("tool_input"), dict) else {}
    if evento == "PermissionRequest" and strumento:
        frase = riassunto_permesso(strumento, ingresso)

        def risposta(scelta):
            decisione = {"behavior": "allow"} if scelta == "S" else {
                "behavior": "deny", "message": "Negato da %s tramite Ciro." % modulo_cervello.NOME_UTENTE}
            return {"hookSpecificOutput": {"hookEventName": "PermissionRequest", "decision": decisione}}
        return (progetto, t("Permesso: %s") % strumento, frase[:1].upper() + frase[1:] + ". " + t("Consento?"),
                {"S": t("consenti"), "N": t("nega")}, "permesso", risposta)
    if evento == "PreToolUse" and strumento == "AskUserQuestion":
        domande_hook = ingresso.get("questions") or []
        if len(domande_hook) != 1 or domande_hook[0].get("multiSelect"):
            return None   # piu' domande o scelta multipla: nel terminale
        domanda = domande_hook[0]
        etichette = [str(o.get("label") or "") for o in (domanda.get("options") or []) if o.get("label")]
        if not 2 <= len(etichette) <= 5:
            return None
        opzioni = {chr(65 + i): etichetta for i, etichetta in enumerate(etichette)}

        def risposta(scelta):
            nuovo = dict(ingresso, answers={str(domanda.get("question") or ""): opzioni[scelta]})
            return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow",
                                           "updatedInput": nuovo}}
        return (progetto, str(domanda.get("header") or "domanda"), _corto(domanda.get("question"), 280),
                opzioni, "scelta", risposta)
    return None


def gestisci_hook(dato, attesa=None, adesso=time.time):
    """Claude Code: l'uscita per l'hook (dict) o None: «chiedi nel terminale come sempre»."""
    if not isinstance(dato, dict) or muto() or not pagina_sveglia():
        return None
    pronta = _domanda_da_hook(dato)
    if pronta is None:
        return None
    return _chiedi_e_aspetta(pronta, titolo_sessione(dato.get("transcript_path")),
                             dato.get("hook_event_name"), attesa, adesso)


# OpenCode: il plugin ciro.js manda «permission.asked»; la domanda compare anche
# nel terminale, e se l'utente risponde li' il plugin lo dice (/hooks/opencode/risposto).
_richieste_opencode = {}   # requestID di OpenCode -> ID della domanda


def riassunto_opencode(permesso, schemi):
    schemi = [str(s) for s in (schemi or []) if s]
    primo = schemi[0] if schemi else ""
    if permesso == "bash":
        return t("vuole eseguire: %s") % _corto(primo or "?", 100)
    if permesso in ("edit", "write", "patch"):
        return t("vuole modificare il file %s") % os.path.basename(primo.rstrip("/") or "?")
    if permesso == "webfetch":
        return t("vuole consultare il web: %s") % (urlparse(primo).hostname or _corto(primo, 60))
    return t("vuole il permesso %s: %s") % (permesso or "?", _corto(", ".join(schemi), 80) or "?")


def gestisci_opencode(dato, attesa=None, adesso=time.time):
    """{"reply": "once"|"reject"} o None (l'utente risponde nel terminale di OpenCode)."""
    if not isinstance(dato, dict) or muto() or not pagina_sveglia() or not dato.get("requestID"):
        return None
    progetto = os.path.basename(str(dato.get("directory") or "").rstrip("/")) or "opencode"
    permesso = str(dato.get("permission") or "")
    frase = riassunto_opencode(permesso, dato.get("patterns"))

    def risposta(scelta):
        return {"reply": "once" if scelta == "S" else "reject"}
    pronta = (progetto, t("Permesso: %s") % (permesso or "?"), frase[:1].upper() + frase[1:] + ". " + t("Consento?"),
              {"S": t("consenti"), "N": t("nega")}, "permesso", risposta)
    return _chiedi_e_aspetta(pronta, _corto(dato.get("title"), 60), "opencode " + permesso, attesa, adesso,
                             richiesta=str(dato["requestID"]))


def opencode_risposto(dato):
    """L'utente ha risposto nel terminale di OpenCode: la domanda di Ciro si chiude."""
    identificativo = _richieste_opencode.pop(str((dato or {}).get("requestID") or ""), None)
    if not identificativo:
        return False
    try:
        domande.passa(identificativo, "annullata", "ciro", "risposto nel terminale",
                      solo_da=("ricevuta", "in-valutazione", "in-attesa"))
        return True
    except (domande.PassaggioNonAmmesso, domande.SchedaNonTrovata):
        return False


def _chiedi_e_aspetta(pronta, sessione, evento, attesa, adesso, richiesta=None):
    progetto, oggetto, testo, opzioni, operazione, risposta = pronta
    if in_pausa(progetto):
        return None
    try:
        identificativo = modulo_posta.chiedi_da_hook(progetto, oggetto, testo, opzioni, operazione,
                                                     sessione=sessione)
    except Exception as errore:  # noqa: BLE001
        registra("errore-hook", errore=repr(errore)[:300])
        return None
    if richiesta:
        _richieste_opencode[richiesta] = identificativo
    registra("hook", evento=evento, domanda_id=identificativo)
    if attesa is None:   # impostabile: «attesa_hook» in impostazioni.json (secondi, al massimo 70)
        attesa = min(70, max(5, int(modulo_cervello.leggi_impostazioni().get("attesa_hook") or ATTESA_HOOK)))
    fine = adesso() + attesa
    try:
        while True:
            scheda = domande.leggi(identificativo)
            if scheda.get("stato") == "risposta-consegnata":
                break
            if scheda.get("stato") == "annullata":
                return None   # risposto nel terminale
            if adesso() >= fine:
                try:
                    domande.passa(identificativo, "annullata", "ciro", "passata al terminale",
                                  solo_da=("ricevuta", "in-valutazione", "in-attesa"))
                    registra("hook-scaduto", domanda_id=identificativo)
                    return None
                except domande.PassaggioNonAmmesso:
                    continue   # la risposta e' arrivata proprio adesso: rileggo
            time.sleep(0.2)
    finally:
        if richiesta:
            _richieste_opencode.pop(richiesta, None)
    esito = scheda.get("risposta") or {}
    scelta = str(esito.get("scelta") or "")
    if esito.get("motivo") != "utente" or scelta not in opzioni:
        return None   # solo una risposta dell'utente consente qualcosa
    for stato in ("recepita", "risolta"):
        try:
            domande.passa(identificativo, stato, "ciro", "restituita alla sessione dall'hook")
        except (domande.PassaggioNonAmmesso, domande.SchedaNonTrovata):
            pass
    registra("hook-risposto", domanda_id=identificativo, scelta=scelta)
    return risposta(scelta)


# ------------------------------------------------------------ credenziali
# Il valore arriva dal campo protetto della pagina e va solo nel Portachiavi:
# mai negli argomenti di un comando (visibili a tutti i processi), nei log,
# nella posta, nel contesto di Ciro. `security -i` legge il comando da stdin.
NOME_CREDENZIALE_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")


def nome_credenziale(scheda):
    """Nome proposto per la voce del Portachiavi: dall'oggetto della domanda."""
    if scheda.get("operazione") != "credenziali":
        return None
    return modulo_posta.slug(scheda.get("oggetto") or "credenziale")


def _tra_virgolette(testo):
    return '"%s"' % testo.replace("\\", "\\\\").replace('"', '\\"')


def salva_credenziale(domanda_id, nome, valore):
    """Salva nel Portachiavi come ciro-<progetto>-<nome> e risponde alla sessione.
    ValueError per richieste non valide; RuntimeError se il Portachiavi rifiuta."""
    try:
        scheda = domande.leggi(str(domanda_id or ""))
    except (domande.SchedaNonTrovata, ValueError):
        raise ValueError("domanda non trovata")
    if scheda.get("operazione") != "credenziali" or scheda.get("stato") not in ("in-attesa", "in-valutazione"):
        raise ValueError("questa domanda non aspetta una credenziale")
    nome = str(nome or "").strip()
    if not NOME_CREDENZIALE_RE.match(nome):
        raise ValueError("nome non valido: solo minuscole, numeri e trattini")
    if not isinstance(valore, str) or not valore or len(valore) > 4096 or any(c in valore for c in "\r\n\0"):
        raise ValueError("valore non valido (vuoto, troppo lungo o su piu' righe)")
    progetto = str(scheda.get("progetto") or "").lower()
    servizio = "ciro-%s-%s" % (progetto, nome)
    comando = "add-generic-password -U -s %s -a %s -w %s\n" % (
        _tra_virgolette(servizio), _tra_virgolette(progetto), _tra_virgolette(valore))
    esito = subprocess.run(["security", "-i"], input=comando, capture_output=True, text=True, timeout=20)
    del comando
    if esito.returncode != 0 or "error" in ((esito.stdout or "") + (esito.stderr or "")).lower():
        registra("errore-credenziale", domanda_id=scheda["id"], nome=nome)
        raise RuntimeError("il Portachiavi non ha accettato la credenziale")
    opzioni = scheda.get("opzioni") or {}
    scelta = scheda.get("raccomanda") if scheda.get("raccomanda") in opzioni else next(iter(opzioni))
    modulo_posta.rispondi_domanda(scheda["id"], scelta,
                                  "Credenziale salvata nel Portachiavi: servizio %s" % servizio,
                                  "utente", "opencode")
    _cervello.domande_in_attesa.pop(scheda["id"], None)
    _cervello.risposte_recenti[scheda["id"]] = (time.time(), scheda, scelta)
    registra("credenziale", domanda_id=scheda["id"], nome=nome)
    return servizio


# ------------------------------------------------------ calibrazione guidata
import collaudo as modulo_collaudo  # noqa: E402

_collaudo = modulo_collaudo.Collaudo(
    dire=lambda frase, **extra: _in_coda({"testo": frase, "da": "collaudo", **extra}),
    stato_pausa=stato_pausa, imposta_pausa=imposta_pausa,
    cartella=CONFIG_FACCIA / "collaudi",
    righe_registro=lambda dal: _righe_registro(dal),
    dopo_calibrazione=lambda: scegli_modello_in_sottofondo())
_cervello.collaudo = _collaudo


def _righe_registro(dal):
    righe = []
    try:
        for riga in modulo_cervello.REGISTRO.read_text(encoding="utf-8").splitlines()[-3000:]:
            try:
                voce = json.loads(riga)
            except ValueError:
                continue
            if voce.get("ora", "") >= dal:
                righe.append(voce)
    except OSError:
        pass
    return righe


# ---------------------------------------------------------------- riepilogo
# Ogni 30 minuti (impostabile a voce), solo se ci sono novita': sessioni
# ripartite o domande risolte, risposte date dalle sue regole, domande che
# aspettano lui da oltre 30 minuti (una volta sola). Al massimo due frasi.
SOLLECITO_SECONDI = 30 * 60
_riepilogo = {}


def azzera_riepilogo(adesso=None):
    adesso = time.time() if adesso is None else adesso
    _riepilogo.clear()
    _riepilogo.update({"ultimo": adesso, "avvio": adesso, "riportate": set(), "sollecitate": set()})


azzera_riepilogo()


def _elenco(nomi):
    nomi = sorted(set(n for n in nomi if n))
    return ", ".join(nomi[:-1]) + t(" e ") + nomi[-1] if len(nomi) > 1 else (nomi[0] if nomi else "")


def riepilogo_se_serve(adesso=None):
    """La frase del riepilogo, se e' ora e ci sono novita' (e la mette in coda)."""
    adesso = time.time() if adesso is None else adesso
    minuti = int(modulo_cervello.leggi_impostazioni().get("riepilogo") or 0)
    if minuti <= 0 or stato_pausa()["attiva"] or adesso - _riepilogo["ultimo"] < minuti * 60:
        return None
    _riepilogo["ultimo"] = adesso
    ripartiti, risolti, automatiche, ferme = [], [], 0, []
    for scheda in domande.elenca():
        for passo in scheda.get("storia") or []:
            chiave = (scheda.get("id"), passo.get("stato"), passo.get("t"))
            if (passo.get("t") or 0) < _riepilogo["avvio"] or chiave in _riepilogo["riportate"]:
                continue
            if passo.get("stato") == "recepita":
                ripartiti.append(scheda.get("progetto"))
            elif passo.get("stato") == "risolta":
                risolti.append(scheda.get("progetto"))
            elif passo.get("stato") == "risposta-consegnata" and \
                    str((scheda.get("risposta") or {}).get("motivo") or "").startswith("regola:"):
                automatiche += 1
            else:
                continue
            _riepilogo["riportate"].add(chiave)
        if scheda.get("stato") == "in-attesa" and scheda.get("id") not in _riepilogo["sollecitate"]:
            dal = float((scheda.get("storia") or [{}])[-1].get("t") or adesso)
            if adesso - dal > SOLLECITO_SECONDI:
                ferme.append(scheda.get("progetto"))
                _riepilogo["sollecitate"].add(scheda.get("id"))
    parti = []
    if ripartiti:
        parti.append(t("ripartito %s") % _elenco(ripartiti))
    if risolti:
        parti.append(t("risolto %s") % _elenco(risolti))
    if automatiche:
        parti.append(t("%d %s con le tue regole") % (automatiche, t("risposta data") if automatiche == 1 else t("risposte date")))
    frasi = []
    if parti:
        frasi.append(t("Riepilogo: %s.") % "; ".join(parti))
    if ferme:
        frasi.append(t("Aspettano te da oltre mezz'ora: %s.") % _elenco(ferme))
    if not frasi:
        return None
    frase = " ".join(frasi)
    _in_coda({"testo": frase, "da": "riepilogo"})
    registra("riepilogo", testo=frase)
    return frase


def frase_perso(dal, adesso=None):
    """«Ciro, cosa mi sono perso?»: cosa e' successo da `dal` e chi ti aspetta adesso."""
    adesso = time.time() if adesso is None else adesso
    arrivate, da_chi, ripartiti, risolti, automatiche = 0, [], [], [], 0
    for scheda in domande.elenca():
        for passo in scheda.get("storia") or []:
            if float(passo.get("t") or 0) < dal:
                continue
            stato = passo.get("stato")
            if stato == "ricevuta":
                arrivate += 1
                da_chi.append(scheda.get("progetto"))
            elif stato == "recepita":
                ripartiti.append(scheda.get("progetto"))
            elif stato == "risolta":
                risolti.append(scheda.get("progetto"))
            elif stato == "risposta-consegnata" and \
                    str((scheda.get("risposta") or {}).get("motivo") or "").startswith("regola:"):
                automatiche += 1
    elenco = attese()
    aspettano = [v for v in elenco if v.get("tipo") != "chat" and v.get("numero")]
    urgenti = [v for v in elenco if v.get("tipo") == "chat" and v.get("urgente") and v.get("risposta")]

    ora = time.strftime("%H:%M", time.localtime(dal))
    parti = []
    if arrivate:
        parti.append((t("una domanda nuova da %s") if arrivate == 1 else t("%d domande nuove da %s") % (
            arrivate, "%s")) % _elenco(da_chi))
    if ripartiti:
        parti.append(t("ripartito %s") % _elenco(ripartiti))
    if risolti:
        parti.append(t("risolto %s") % _elenco(risolti))
    if automatiche:
        parti.append(t("%d %s con le tue regole") % (
            automatiche, t("risposta data") if automatiche == 1 else t("risposte date")))
    frasi = [t("Dalle %s: %s.") % (ora, "; ".join(parti))] if parti else []
    if aspettano:
        voci = "; ".join("%s %s, %s" % (t("la"), numeri_parlati.parola(v["numero"], lingua()),
                                        v.get("progetto") or "?") for v in aspettano[:5])
        if len(aspettano) > 5:
            voci += t("; e altre %d") % (len(aspettano) - 5)
        frasi.append(t("Ti aspettano: %s.") % voci)
    if urgenti:
        frasi.append(t("In Chat, un messaggio urgente.") if len(urgenti) == 1
                     else t("In Chat, %d messaggi urgenti.") % len(urgenti))
    if not frasi:
        return t("Niente di nuovo dalle %s, e nessuno ti aspetta.") % ora
    if not parti:
        frasi.insert(0, t("Niente di nuovo dalle %s.") % ora)
    frase = " ".join(frasi)
    registra("perso", dal=ora, arrivate=arrivate, aspettano=len(aspettano), urgenti=len(urgenti))
    return frase


def sorveglia_domande(ferma=None):
    ferma = ferma or threading.Event()
    while not ferma.is_set():
        try:
            giro_domande()
            _collaudo.tick()
            riepilogo_se_serve()
            ripresa = frase_ripresa()
            if ripresa:
                _in_coda({"testo": ripresa, "da": "ripresa"})
        except Exception as errore:  # noqa: BLE001
            registra("errore-domande", errore=repr(errore)[:300])
        ferma.wait(INTERVALLO_DOMANDE)


# -------------------------------------------- colonna destra: le sessioni
# Una scheda per sessione Claude Code aperta, con una riga di sintesi presa
# dai dati dello stato (niente modello: istantanea e gratis).
SINTESI_MASSIMA = 140
ORDINE_STATI = {"aspetta te": 0, "al lavoro": 1}


def _una_riga_pulita(testo):
    testo = re.sub(r"^\s*(\[[^\]]{1,40}\]\s*)+", "", testo or "")   # [Claude · Opus 5.5]
    testo = re.sub(r"[*_#`]+", "", testo)
    testo = re.sub(r"\s*\((?:messaggio|log|file)\s*:[^)]*\)?", "", testo, flags=re.I)
    return re.sub(r"\s+", " ", testo).strip()


def _accorcia(testo, massimo=SINTESI_MASSIMA):
    if len(testo) <= massimo:
        return testo
    return testo[:massimo - 1].rsplit(" ", 1)[0].rstrip(" ,;:.") + "…"


def _sintesi(sessione):
    if sessione.get("aspetta_utente") and (sessione.get("domanda") or "").strip():
        return _accorcia(_una_riga_pulita(sessione["domanda"]))
    anteprima = _una_riga_pulita(sessione.get("anteprima"))
    if anteprima:
        return _accorcia(anteprima)
    prima = _una_riga_pulita((sessione.get("attesa") or "").split(" · ")[0])
    if prima:
        prima = re.sub(r"^(?:%s),?\s*(che\s+)?deve\s+" % NOMI_UTENTE_RE, "te: deve ", prima, flags=re.I)
        return _accorcia("Aspetta " + prima)
    return ""


REPO_RE = re.compile(r"[:/]([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?$")
_repo_cache = {}   # cartella -> (ora, (proprietario, repo) | None)
_repo_lock = threading.Lock()


def proprietario_repo(url):
    """("proprietario", "repo") da un indirizzo git (https o ssh), altrimenti None."""
    trovato = REPO_RE.search((url or "").strip())
    if not trovato or "/" not in (url or "") and ":" not in (url or ""):
        return None
    return trovato.group(1), trovato.group(2)


def repo_di(cartella):
    """Proprietario e nome del repository della cartella (origin), con 5 minuti di cache."""
    if not cartella:
        return None
    with _repo_lock:
        dato = _repo_cache.get(cartella)
        if dato and time.time() - dato[0] < 300:
            return dato[1]
    try:
        esito = subprocess.run(["git", "-C", str(cartella), "remote", "get-url", "origin"],
                               capture_output=True, text=True, timeout=2)
        valore = proprietario_repo(esito.stdout) if esito.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        valore = None
    with _repo_lock:
        _repo_cache[cartella] = (time.time(), valore)
    return valore


def schede_sessioni(sessioni, repo_di=repo_di):
    """Una scheda per sessione, titolo proprietario/repo; prima chi aspetta te,
    poi chi lavora, e nello stesso stato insieme le sessioni dello stesso proprietario."""
    schede = []
    for sessione in sessioni or []:
        stato = "aspetta te" if sessione.get("aspetta_utente") else (sessione.get("stato") or "?")
        progetto = sessione.get("progetto") or "?"
        proprietario, repo = repo_di(sessione.get("cwd")) or ("", "")
        schede.append({"progetto": progetto, "nome": sessione.get("nome") or "",
                       "proprietario": proprietario, "repo": repo,
                       "titolo": "%s/%s" % (proprietario, repo) if proprietario else progetto,
                       "stato": stato, "secondi": int(sessione.get("da_secondi") or 0),
                       "sintesi": _sintesi(sessione)})
    schede.sort(key=lambda s: (ORDINE_STATI.get(s["stato"], 2), s["proprietario"].lower() or "~",
                               s["titolo"].lower()))
    return schede


def quadro():
    """Dati per i pannelli: consumi, chi ti aspetta e le sessioni aperte."""
    sessioni = modulo_cervello.leggi_sessioni() or []
    return {"consumi": consumi(), "attese": attese(sessioni), "sessioni": schede_sessioni(sessioni),
            "pausa": stato_pausa(), "collaudo": _collaudo.fase, "guida": _collaudo.stato_guida(),
            "calibrato": bool(modulo_cervello.leggi_impostazioni().get(modulo_cervello.chiave_lingua("calibrato"))),
            "lingua": lingua(),
            "microfono": {"soglia": modulo_cervello.leggi_impostazioni().get("soglia_microfono"),
                          "fine_frase_ms": modulo_cervello.profilo_voce().get("fine_frase_ms"),
                          "eco": modulo_cervello.profilo_voce().get("eco")}}



class Gestore(BaseHTTPRequestHandler):
    server_version = "Faccia/1.0"

    def log_message(self, formato, *argomenti):
        pass  # niente righe di log per ogni richiesta

    def _invia(self, codice, corpo, tipo="application/json; charset=utf-8"):
        if isinstance(corpo, str):
            corpo = corpo.encode("utf-8")
        self.send_response(codice)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(corpo)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _errore(self, codice, messaggio):
        self._invia(codice, json.dumps({"errore": messaggio}))

    def _provenienza_ok(self, percorso):
        """Accetta solo la pagina della faccia, i programmi locali e, per i
        consumi, l'estensione Chrome. Blocca gli altri siti aperti nel browser
        e i trucchi sul nome del server (DNS rebinding)."""
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0]
        if host not in ("127.0.0.1", "localhost"):
            return False
        origine = self.headers.get("Origin")
        if origine and origine.startswith("chrome-extension://"):
            return percorso == "/api/consumi" or percorso.startswith("/api/chat/")
        if origine and urlparse(origine).hostname not in ("127.0.0.1", "localhost"):
            return False
        sito = self.headers.get("Sec-Fetch-Site")
        return not sito or sito in ("same-origin", "none")

    def _corpo(self, massimo=8_000_000):
        lunghezza = int(self.headers.get("Content-Length") or 0)
        if lunghezza <= 0 or lunghezza > massimo:
            return b""
        return self.rfile.read(lunghezza)

    def do_GET(self):
        percorso = urlparse(self.path).path
        if not self._provenienza_ok(percorso):
            self._errore(403, "provenienza non ammessa")
            return
        if percorso in ("/", "/index.html"):
            self._file("index.html", "text/html; charset=utf-8")
        elif percorso == "/api/messaggi":
            segna_pagina_sveglia()
            if muto():  # zitto: i messaggi restano in coda per dopo
                self._invia(200, json.dumps({"messaggi": [], "muto": True}))
                return
            with _coda_lock:
                messaggi, _coda[:] = list(_coda), []
            messaggi = filtra_coda(messaggi)
            self._invia(200, json.dumps({"messaggi": messaggi, "muto": False}))
        elif percorso == "/api/versione":
            self._invia(200, json.dumps({"versione": versione()}))
        elif percorso == "/api/stato":
            self._invia(200, json.dumps({"ok": True, "voce": VOCE,
                                         "whisper": MODELLO_WHISPER.exists()}))
        elif percorso == "/api/quadro":
            try:
                self._invia(200, json.dumps(quadro(), ensure_ascii=False))
            except Exception as errore:  # noqa: BLE001
                self._errore(500, str(errore))
        else:
            self._file(percorso.lstrip("/"), None)

    def _file(self, nome, tipo):
        percorso = (CARTELLA / nome).resolve()
        if (not percorso.is_relative_to(CARTELLA) or not percorso.is_file()
                or any(parte.startswith(".") for parte in percorso.relative_to(CARTELLA).parts)):
            self._errore(404, "non trovato")
            return
        if tipo is None:
            tipo = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
                    ".js": "application/javascript; charset=utf-8",
                    ".svg": "image/svg+xml", ".png": "image/png",
                    ".wav": "audio/wav", ".json": "application/json"}.get(percorso.suffix, "application/octet-stream")
        self._invia(200, percorso.read_bytes(), tipo)

    def do_POST(self):
        percorso = urlparse(self.path).path
        if not self._provenienza_ok(percorso):
            self._errore(403, "provenienza non ammessa")
            return
        corpo = self._corpo()
        try:
            if percorso == "/api/parla":
                dato = json.loads(corpo or b"{}")
                if muto():
                    registra("parla-zitto", testo=testo_per_registro(dato.get("testo", "")))
                    self._errore(423, "voce spenta")
                    return
                inizio = time.time()
                byte_wav = parla_wav(dato.get("testo", ""), dato.get("velocita"))
                registra("parla", testo=testo_per_registro(dato.get("testo", "")),
                         secondi_voce=round(time.time() - inizio, 1))
                self._invia(200, byte_wav, "audio/wav")
            elif percorso == "/api/ascolta":
                if _collaudo.fase == "frasi":   # le frasi della calibrazione restano sul Mac, per misure
                    cartella = cartella_audio()
                    cartella.mkdir(parents=True, exist_ok=True)
                    nome = "frase-%s.wav" % time.strftime("%Y%m%d-%H%M%S")
                    (cartella / nome).write_bytes(corpo)
                    try:   # l'etichetta (la frase che doveva dire) per il banco di prova
                        etichette_file = cartella / "etichette.json"
                        etichette = json.loads(etichette_file.read_text(encoding="utf-8")) \
                            if etichette_file.is_file() else {}
                        etichette[nome] = _collaudo.frasi[_collaudo.indice]
                        etichette_file.write_text(json.dumps(etichette, ensure_ascii=False, indent=1),
                                                  encoding="utf-8")
                    except (OSError, ValueError, IndexError):
                        pass
                inizio = time.time()
                aspetta_nome = parse_qs(urlparse(self.path).query).get("nome") == ["1"]
                testo = trascrivi(corpo, grande=aspetta_nome)
                if testo:
                    _ultimi_audio.append((testo, corpo))
                registra("ascolto", testo=testo, audio_kb=len(corpo) // 1024,
                         secondi_trascrizione=round(time.time() - inizio, 1))
                chiamato, resto = togli_nome(testo)
                if aspetta_nome:
                    nota_ascolto_nome(testo, chiamato)
                self._invia(200, json.dumps({"testo": testo, "chiamato": chiamato, "resto": resto}))
            elif percorso == "/api/messaggio":
                dato = json.loads(corpo or b"{}")
                testo = (dato.get("testo") or "").strip()
                if not testo:
                    self._errore(400, "testo vuoto")
                    return
                registra("messaggio-da-fuori", testo=testo, da=dato.get("da") or "opencode")
                with _coda_lock:
                    _coda.append({"testo": testo, "da": dato.get("da") or "opencode"})
                self._invia(200, json.dumps({"ok": True}))
            elif percorso == "/hooks/opencode":
                uscita = gestisci_opencode(json.loads(corpo or b"{}"))
                self._invia(200, json.dumps(uscita) if uscita else b"")
            elif percorso == "/hooks/opencode/risposto":
                self._invia(200, json.dumps({"chiusa": opencode_risposto(json.loads(corpo or b"{}"))}))
            elif percorso == "/hooks/claude":
                # hook http di Claude Code: risposta vuota = chiedi nel terminale
                uscita = gestisci_hook(json.loads(corpo or b"{}"))
                self._invia(200, json.dumps(uscita) if uscita else b"")
            elif percorso == "/api/evento":
                # eventi della pagina: interruzioni, errori, ricaricamenti, accensioni
                dato = json.loads(corpo or b"{}")
                registra("pagina-" + re.sub(r"[^a-z-]", "", str(dato.get("tipo") or "evento"))[:30],
                         dettaglio=str(dato.get("dettaglio") or "")[:500])
                self._invia(200, json.dumps({"ok": True}))
            elif percorso == "/api/consumi":
                salva_consumo(json.loads(corpo or b"{}"))
                self._invia(200, json.dumps({"ok": True}))
            elif percorso == "/api/collaudo":
                dato = json.loads(corpo or b"{}")
                with _cervello_lock:
                    if dato.get("azione") == "avvia":
                        esito = {"risposta": _collaudo.avvia("calibrazione"), "comando": "misura-silenzio",
                                 "secondi": modulo_collaudo.SILENZIO_SECONDI}
                    elif dato.get("azione") == "collaudo":
                        esito = {"risposta": _collaudo.avvia("collaudo")}
                    elif dato.get("azione") == "ripeti":
                        esito = {"risposta": _collaudo.ripeti()}
                    elif dato.get("azione") == "chiudi":
                        _collaudo.chiudi()
                        esito = {"risposta": ""}
                    elif dato.get("tipo") == "silenzio":
                        esito = {"risposta": _collaudo.silenzio(dato.get("medio") or 0, dato.get("p95") or 0,
                                                                dato.get("massimo") or 0, dato.get("eco"))}
                        registra("collaudo-silenzio", **{k: dato.get(k) for k in ("medio", "p95", "massimo")})
                    elif dato.get("azione") == "ferma":
                        esito = {"risposta": _collaudo.ferma()}
                    else:
                        esito = {"risposta": "", "fase": _collaudo.fase}
                self._invia(200, json.dumps(esito, ensure_ascii=False))
            elif percorso == "/api/chat/non-letti":
                ricevi_chat(json.loads(corpo or b"{}"))
                self._invia(200, json.dumps({"ok": True}))
            elif percorso == "/api/lingua":
                dato = json.loads(corpo or b"{}")
                if dato.get("lingua") in modulo_testi.LINGUE:
                    modulo_cervello.imposta("lingua", dato["lingua"])
                    registra("lingua", lingua=dato["lingua"])
                self._invia(200, json.dumps({"lingua": lingua()}))
            elif percorso == "/api/pausa":
                dato = json.loads(corpo or b"{}")
                self._invia(200, json.dumps(imposta_pausa(dato.get("attiva"), dato.get("solo"))))
            elif percorso == "/api/credenziale":
                dato = json.loads(corpo or b"{}")
                try:
                    servizio = salva_credenziale(dato.get("domanda_id"), dato.get("nome"), dato.get("valore"))
                except RuntimeError as errore:
                    self._errore(502, str(errore))
                    return
                finally:
                    dato = corpo = None
                frase = t("Salvata nel Portachiavi come %s. Mandato.") % servizio
                _in_coda({"testo": frase, "da": "domande"})
                self._invia(200, json.dumps({"ok": True, "servizio": servizio}))
            elif percorso == "/api/cervello":
                dato = json.loads(corpo or b"{}")
                testo = (dato.get("testo") or "").strip()
                if not testo:
                    self._errore(400, "testo vuoto")
                    return
                if dato.get("interrotto") and solo_stop(testo):
                    registra("stop-dopo-interruzione", testo=testo)
                    self._invia(200, json.dumps({"risposta": ""}))
                    return
                with _cervello_lock:
                    _cervello.ultimo_livello = dato.get("livello")
                    _cervello.ultime_pause = dato.get("pause")
                    esito = _cervello.chiedi(testo)
                    if _cervello.da_imparare:   # una correzione: l'audio capito male va nel banco
                        impara_audio(_cervello.da_imparare)
                        _cervello.da_imparare = None
                self._invia(200, json.dumps(esito, ensure_ascii=False))
            else:
                self._errore(404, "non trovato")
        except ValueError as errore:
            self._errore(400, str(errore))
        except subprocess.TimeoutExpired:
            self._errore(504, "trascrizione troppo lenta")
        except Exception as errore:  # noqa: BLE001
            log("errore: %r" % (errore,))
            registra("errore-server", percorso=percorso, errore=repr(errore)[:300])
            self._errore(500, str(errore))


def avvia(porta):
    indirizzo = "http://127.0.0.1:%d/" % porta
    log("faccia su " + indirizzo)
    print(indirizzo, flush=True)
    try:
        server = ThreadingHTTPServer(("127.0.0.1", porta), Gestore)
    except OSError as errore:
        log("porta %d occupata (%s): chiudi l'altra faccia o usa FACCIA_PORTA" % (porta, errore))
        sys.exit(1)
    threading.Thread(target=sorveglia_attese, daemon=True).start()
    threading.Thread(target=sorveglia_domande, daemon=True).start()
    server.serve_forever()


if __name__ == "__main__":
    preferita = int(sys.argv[1]) if len(sys.argv) > 1 else int(os.environ.get("FACCIA_PORTA") or 8765)
    avvia(preferita)
