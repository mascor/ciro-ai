#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Cervello della faccia: OpenCode (deepseek/deepseek-flash, diretto) con il
quadro delle sessioni Claude Code e della posta. Solo testo: la voce la fa
server.py con Kokoro.

Nessuna azione parte da sola: se il modello propone di mandare un messaggio,
la proposta resta in attesa e parte solo dopo un "si" dell'utente.
"""

import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

from testi import lingua, per_lingua, t  # noqa: E402

# root of the repository (ciro/, posta/, stato/); the scripts can be moved with env variables
RADICE_PROGETTO = Path(__file__).resolve().parent.parent
# the user's name, used only to address them (CIRO_UTENTE=Mario); generic by default
NOME_UTENTE = (os.environ.get("CIRO_UTENTE") or "").strip() or "Utente"
STATO_SCRIPT = Path(os.environ.get("CIRO_STATO_SCRIPT") or RADICE_PROGETTO / "stato/scripts/claude_stato.py")
POSTA_SCRIPT = Path(os.environ.get("CIRO_POSTA_SCRIPT") or RADICE_PROGETTO / "posta/scripts/posta.py")
# DeepSeek diretto: risponde in meno di 2 s (Go ne impiegava 7-8); scelta dell'utente del 18/11/2026
MODELLO = os.environ.get("FACCIA_MODELLO") or "deepseek/deepseek-flash"
CASSELLA = "opencode"
RISPOSTA_MASSIMA = 520

RADICE_POSTA = Path.home() / ".posta-agenti"
PREFISSO_OGGETTO = "[faccia] "

# memoria delle regole generali, condivisa con OpenCode (opencode.json -> instructions)
MEMORIA = Path.home() / ".config/opencode/memoria-ciro.md"

AZIONE_RE = re.compile(r"^\s*AZIONE\s*:\s*(.+)$", re.IGNORECASE)
MEMORIA_RE = re.compile(r"^\s*MEMORIA\s*:\s*(aggiungi|togli)\s*\|\s*(.+)$", re.IGNORECASE)
# conferma: solo un si' secco, senza "ma", "pero'" o altro dopo
# Una conferma e' una frase breve fatta solo di parole di assenso: "si'",
# "si', confermo", "si' conferma", "ok vai", e anche "confirm" (whisper a volte
# trascrive in inglese). Senza "no", "non", "ma", "pero'".
PAROLE_SI = {"si", "sì", "ok", "okay", "va", "bene", "vai", "confermo", "conferma",
             "confermato", "confirm", "confirmed", "yes", "mandalo", "manda", "mandala",
             "procedi", "certo", "esatto", "perfetto", "grazie", "d'accordo", "daccordo",
             "accordo", "giusto", "ciro", "pure", "e", "allora", "sì,"}
PAROLE_FORTI = PAROLE_SI - {"grazie", "ciro", "pure", "e", "allora", "bene", "va"}


def e_conferma(detto):
    parole = re.sub(r"[^\w'àèéìòù]+", " ", detto.lower()).split()
    return (0 < len(parole) <= 6 and all(p in PAROLE_SI for p in parole)
            and any(p in PAROLE_FORTI for p in parole))


NO_RE = re.compile(r"^(no|annulla|lascia stare|non mandarlo|ferma|aspetta|cancel|don't|do not|stop|wait)\b")


# ----------------------------------------------------------- modello
# DeepSeek chiamato direttamente (circa 1 s in meno di "opencode run"); se manca
# la chiave o la chiamata fallisce, si torna a OpenCode. La chiave viene dal
# Portachiavi (servizio ciro-deepseek) o da DEEPSEEK_API_KEY e non va mai
# negli argomenti, nei log o nella conversazione.
DEEPSEEK_URL = os.environ.get("CIRO_DEEPSEEK_URL") or "https://api.deepseek.com/chat/completions"
MODELLO_DIRETTO = os.environ.get("CIRO_MODELLO_DIRETTO") or "deepseek-flash"   # alias of the latest Flash
_chiave_cache = {"valore": None, "letta": 0.0}


def _chiave_deepseek():
    if os.environ.get("CIRO_DEEPSEEK_DIRETTO") == "0":
        return None
    if os.environ.get("DEEPSEEK_API_KEY"):
        return os.environ["DEEPSEEK_API_KEY"].strip()
    if time.time() - _chiave_cache["letta"] < 300:
        return _chiave_cache["valore"]
    valore = None
    try:
        esito = subprocess.run(["security", "find-generic-password", "-s", "ciro-deepseek", "-w"],
                               capture_output=True, text=True, timeout=5)
        if esito.returncode == 0:
            valore = esito.stdout.strip() or None
    except (OSError, subprocess.TimeoutExpired):
        valore = None
    _chiave_cache.update({"valore": valore, "letta": time.time()})
    return valore


def _deepseek_diretto(prompt, timeout):
    chiave = _chiave_deepseek()
    if not chiave:
        return None
    import urllib.request
    corpo = json.dumps({"model": MODELLO_DIRETTO, "temperature": 0.3, "max_tokens": 800,
                        "messages": [{"role": "user", "content": prompt}]}).encode("utf-8")
    richiesta = urllib.request.Request(DEEPSEEK_URL, data=corpo, method="POST", headers={
        "Authorization": "Bearer " + chiave, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(richiesta, timeout=timeout) as risposta:
            dati = json.load(risposta)
        return (dati["choices"][0]["message"]["content"] or "").strip() or None
    except Exception as errore:  # noqa: BLE001
        # solo il tipo e il codice HTTP: il messaggio potrebbe contenere dati della richiesta
        registra({"ora": time.strftime("%Y-%m-%d %H:%M:%S"), "tipo": "errore-deepseek",
                  "errore": type(errore).__name__, "codice": getattr(errore, "code", None)})
        return None


def chiedi_modello(prompt, timeout):
    """(uscita, errore, codice) come _esegui: prima DeepSeek diretto, poi OpenCode."""
    testo = _deepseek_diretto(prompt, min(timeout, 30))
    if testo:
        return testo, "", 0
    return _esegui(["opencode", "run", "-m", MODELLO, "--archived", "--title", "faccia", prompt], timeout)


def _esegui(comando, timeout):
    esito = subprocess.run(
        comando,
        capture_output=True,
        text=True,
        timeout=timeout,
        env={**os.environ, "NO_COLOR": "1"},
    )
    return esito.stdout.strip(), esito.stderr.strip(), esito.returncode


def leggi_sessioni():
    """Elenco delle sessioni Claude Code aperte (vuoto se non si legge)."""
    try:
        uscita, _, codice = _esegui([sys.executable, str(STATO_SCRIPT), "--json"], 20)
        if codice != 0:
            return None
        return json.loads(uscita)
    except Exception:  # noqa: BLE001
        return None


def caselle_note():
    """Caselle a cui si puo' scrivere: progetti delle sessioni aperte e caselle
    gia' esistenti nella posta (tranne quella del gestore)."""
    nomi = {s.get("progetto") for s in (leggi_sessioni() or []) if s.get("progetto")}
    try:
        nomi |= {c.name for c in RADICE_POSTA.iterdir() if c.is_dir() and not c.name.startswith(".")}
    except OSError:
        pass
    nomi.discard(CASSELLA)
    return nomi - {"bin", "domande", "rapporti"}


def trova_casella(nome):
    """Il nome esatto della casella, tollerando maiuscole, spazi e trattini."""
    def norma(testo):
        return re.sub(r"[\s_-]+", "", (testo or "").lower())
    cercato = norma(nome)
    for casella in caselle_note():
        if norma(casella) == cercato:
            return casella
    return None


def quadro_sessioni():
    """Righe brevi sullo stato delle sessioni Claude Code."""
    sessioni = leggi_sessioni()
    if sessioni is None:
        return "(stato delle sessioni non disponibile)"

    righe = []
    for sessione in sessioni[:8]:
        pezzi = [
            "%s (progetto %s)" % (sessione.get("nome"), sessione.get("progetto")),
            "stato %s" % sessione.get("stato"),
        ]
        domanda = (sessione.get("domanda") or "").strip()
        if domanda:
            pezzi.append("domanda: " + domanda[:180])
        attese = sessione.get("attese_per_utente") or []
        if attese:
            pezzi.append("aspetta: " + "; ".join(a[:140] for a in attese[:2]))
        righe.append("- " + " · ".join(pezzi))
    return "\n".join(righe) or "(nessuna sessione aperta)"


def posta_recente():
    """Ultimi messaggi arrivati nella casella del gestore."""
    try:
        uscita, _, codice = _esegui(
            [sys.executable, str(POSTA_SCRIPT), "elenco", "--casella", CASSELLA, "--json"], 20
        )
        if codice != 0:
            return "(posta non disponibile)"
        dati = json.loads(uscita)
    except Exception as errore:  # noqa: BLE001
        return "(posta non disponibile: %s)" % errore

    if isinstance(dati, dict):
        dati = dati.get("messaggi") or []
    righe = []
    dati = [m for m in dati if not m.get("domanda_id")]  # le segue il registro delle domande
    for messaggio in dati[-6:]:
        righe.append(
            "- da %s · %s · %s · %s"
            % (
                messaggio.get("da") or messaggio.get("mittente") or "?",
                messaggio.get("tipo") or "messaggio",
                (messaggio.get("oggetto") or "")[:90],
                _inizio_testo(messaggio)[:200],
            )
        )
    return "\n".join(righe) or "(nessun messaggio nuovo)"


def leggi_regole():
    """Le regole salvate, una per riga (righe del file che iniziano con "- ")."""
    try:
        righe = MEMORIA.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    return [r[2:].strip() for r in righe if r.startswith("- ")]


def aggiungi_regola(regola):
    regola = " ".join((regola or "").split()).strip(" .")
    if not regola:
        return None
    if any(regola.lower() in r.lower() for r in leggi_regole()):
        return regola  # gia' presente
    from datetime import date
    if not MEMORIA.exists():
        MEMORIA.write_text("# Memoria di Ciro: regole generali date dall'utente\n\n", encoding="utf-8")
    testo = MEMORIA.read_text(encoding="utf-8")
    if testo and not testo.endswith("\n"):
        testo += "\n"
    testo += "- %s: %s.\n" % (date.today().strftime("%d/%m/%Y"), regola)
    MEMORIA.write_text(testo, encoding="utf-8")
    return regola


def togli_regola(numero):
    """Toglie la regola numero N (come elencata nel prompt, da 1)."""
    try:
        numero = int(re.sub(r"\D", "", numero))
        righe = MEMORIA.read_text(encoding="utf-8").splitlines()
    except (ValueError, OSError):
        return None
    posizioni = [i for i, r in enumerate(righe) if r.startswith("- ")]
    if not 1 <= numero <= len(posizioni):
        return None
    tolta = righe.pop(posizioni[numero - 1])[2:].strip()
    MEMORIA.write_text("\n".join(righe) + "\n", encoding="utf-8")
    return tolta


def quadro_regole():
    regole = leggi_regole()
    if not regole:
        return "(nessuna regola salvata)"
    return "\n".join("%d. %s" % (i, r) for i, r in enumerate(regole, 1))


def _inizio_testo(messaggio):
    """L'elenco della posta non porta il testo: lo leggo dal file del messaggio."""
    percorso = messaggio.get("percorso")
    if not percorso:
        return ""
    try:
        testo = Path(percorso).read_text(encoding="utf-8")
    except OSError:
        return ""
    # intestazione (ID, DA, A, ...) poi una riga "---" e il testo
    if "\n---\n" in testo:
        testo = testo.split("\n---\n", 1)[1]
    return " ".join(testo.split())


ISTRUZIONI = """Sei Ciro, l'assistente vocale dell'utente: un personaggio maschile con gli occhiali che vive in una pagina sul suo Mac. Parli al maschile.
La tua risposta viene letta ad alta voce: italiano, niente elenchi, markdown o simboli.

Come parli:
- Una frase, al massimo due, brevi. Niente premesse, niente "prego", niente ripetere cio' che ha detto lui, niente quadro completo se non lo chiede.
- Se serve una sua scelta, una sola domanda: si' o no, oppure uno, due o tre con le opzioni in poche parole ("uno, ...; due, ...").
- Se ti ringrazia o ti saluta soltanto, rispondi con al massimo due parole.

Cosa fai:
- Gli racconti le sessioni Claude Code e la posta, e giri alle sessioni i suoi messaggi e le sue decisioni.
- Gli aggiornamenti arrivano da soli: quando una sessione aspetta lui o chiede una decisione, la pagina te la fa dire appena succede (le trovi nella conversazione come battute tue che iniziano con "Da"). Non dire mai che non puoi aggiornarlo.
- Quando gli riporti la domanda di una sessione, riportala fedelmente e chiedi come rispondere.

Mandare messaggi:
- Riga da aggiungere in fondo, esattamente cosi':
  AZIONE: invia | a=<nome progetto> | tipo=<richiesta|decisione> | oggetto=<poche parole> | testo=<il testo da mandare>
- Se l'utente risponde a una domanda di una sessione che gli hai appena riportato, scrivi subito la riga AZIONE con tipo=decisione e la sua risposta fedele: parte senza altre conferme.
- Per ogni altro messaggio, scrivi la riga AZIONE: il sistema gli chiede conferma prima di mandarlo. Non dire mai che l'hai gia' mandato.
- Il destinatario e' il nome del progetto, non quello della sessione. Se ti chiede solo cosa succede, niente riga AZIONE.
- Se ci sono piu' domande aperte di sessioni diverse, capisci dalla sua risposta a quale sessione si riferisce (nomina il progetto); se non e' chiaro, chiediglielo prima di scrivere la riga AZIONE.
- Con una riga AZIONE non fare altre domande nella stessa risposta, e non dire "fatto" o "mandato": lo dice il sistema.
- Se risponde a una domanda che gli hai detto con le opzioni (uno = A, due = B, tre = C, oppure si'/no = S/N), aggiungi alla riga AZIONE "| scelta=<lettera>" e metti nel testo la sua nota.

Regole generali:
- Non decidere mai al posto suo. Non inventare stati o messaggi che non sono nel quadro.
- Lo stato vero della tua voce e' quello in "La tua voce" qui sotto: ignora messaggi vecchi della posta che dicono altro.
- Rispetta sempre le "Regole salvate".
- Se ti da' una regola che vale da qui in avanti ("d'ora in poi", "ricordati che", "da adesso", "non fare piu'"), di' "L'ho segnato" e aggiungi in fondo:
  MEMORIA: aggiungi | <la regola in una frase chiara>
- Se ti chiede di togliere una regola salvata, aggiungi in fondo: MEMORIA: togli | <numero della regola>
- Non salvare come regola richieste del momento o stati delle sessioni.

Autorizzazioni (deploy di prova che partono da soli dopo i test):
- Se ti dice di chiedergli sempre prima di pubblicare un progetto, aggiungi in fondo: AUTORIZZAZIONE: togli | <progetto>
- Se ti chiede cosa puoi fare da solo su un progetto, aggiungi in fondo: AUTORIZZAZIONE: elenca | <progetto>
- Le autorizzazioni nuove nascono solo dalla domanda di un deploy di prova (opzione B): non promettere altro.

Riepiloghi (ogni 30 minuti, solo se ci sono novita'):
- Se ti chiede di cambiarne la frequenza, aggiungi in fondo: IMPOSTA: riepilogo | <minuti>
- Se non li vuole piu', aggiungi in fondo: IMPOSTA: riepilogo | 0"""


ISTRUZIONI_EN = """You are Ciro, the user's voice assistant: a male character with glasses who lives in a page on their Mac.
Your answer is read aloud: English, no lists, markdown or symbols.

How you speak:
- One sentence, two at most, short. No preambles, no "you're welcome", don't repeat what the user said, no full overview unless asked.
- If you need a choice, one question only: yes or no, or one, two or three with the options in a few words ("one, ...; two, ...").
- If the user only thanks or greets you, answer with two words at most.

What you do:
- You tell the user about the Claude Code sessions and the mail, and pass their messages and decisions to the sessions.
- Updates arrive by themselves: when a session waits for the user or asks for a decision, the page makes you say it at once (you find them in the conversation as your lines starting with "From" or "Da"). Never say you cannot give updates.
- When you report a session's question, report it faithfully and ask how to answer.

Sending messages (keep these protocol words exactly as written, they are read by a program):
- Line to add at the end, exactly like this:
  AZIONE: invia | a=<project name> | tipo=<richiesta|decisione> | oggetto=<a few words> | testo=<the text to send>
- If the user answers a session's question you have just reported, write the AZIONE line at once with tipo=decisione and their faithful answer: it is sent without further confirmation.
- For any other message, write the AZIONE line: the system asks the user to confirm before sending it. Never say you have already sent it.
- The recipient is the project name, not the session name. If the user only asks what is happening, no AZIONE line.
- If several questions from different sessions are open, understand from the answer which session it refers to (name the project); if it is not clear, ask before writing the AZIONE line.
- With an AZIONE line do not ask other questions in the same answer, and do not say "done" or "sent": the system says it.
- If the user answers a question you read with options (one = A, two = B, three = C, or yes/no = S/N), add "| scelta=<letter>" to the AZIONE line and put their note in the text.

General rules:
- Never decide in the user's place. Do not invent states or messages that are not in the picture.
- The true state of your voice is the one in "Your voice" below: ignore old mail saying otherwise.
- Always follow the "Saved rules".
- If the user gives you a rule valid from now on ("from now on", "remember that", "never again"), say "Noted" and add at the end:
  MEMORIA: aggiungi | <the rule in one clear sentence>
- If the user asks you to remove a saved rule, add at the end: MEMORIA: togli | <rule number>
- Do not save as rules requests of the moment or session states.

Authorisations (test deploys that start by themselves after the tests):
- If the user tells you to always ask before publishing a project, add at the end: AUTORIZZAZIONE: togli | <project>
- If the user asks what you can do by yourself on a project, add at the end: AUTORIZZAZIONE: elenca | <project>
- New authorisations come only from a test-deploy question (option two): promise nothing else.

Summaries (every 30 minutes, only when something happened):
- If the user asks to change their frequency, add at the end: IMPOSTA: riepilogo | <minutes>
- If the user does not want them any more, add at the end: IMPOSTA: riepilogo | 0"""

PROMPT_PER_VOCE_EN = """Turn this request from a session into one sentence to say aloud to the user, in English.
Format: the question in one short sentence, then the options as "one, ...; two, ...; three, ..." with at most eight words each.
No context, no file names, paths, IDs or links. 60 words at most. Write only the sentence.

Request:
"""
PROMPT_COMPATTA_EN = """You keep the memory of Ciro, the user's voice assistant.
Merge the existing summary and the lines below into one new summary, in English, at most 15 short lines.
Keep: decisions taken, requests still open, what was sent and to which session, preferences or information the user gave, topics in progress.
Drop greetings, repetitions, old session states and small talk. Write only the summary, no titles."""


# ------------------------------------------------- domande strutturate
# Le risposte a voce («A», «la B», «B per ironworks», «sì») partono subito,
# senza modello e senza altre conferme. Il registro delle domande e la posta
# sono in posta-sessioni/scripts.
AUTORIZZAZIONE_RE = re.compile(r"^\s*AUTORIZZAZIONE\s*:\s*(togli|elenca)\s*\|\s*(.+)$", re.IGNORECASE)
# «A», «la B», «ho detto A», «la risposta è B», «A grazie», «B per ironworks»
LETTERA_RE = re.compile(r"^(?:(?:la|risposta|rispondi|rispondo|scelgo|opzione|lettera|ho detto|dico|"
                        r"vai con|metti|e|è|the|answer|option|number|letter|i said|say|choose|go with|"
                        r"it's|it is)\s+)*([a-z])"
                        r"(?:\s+(?:per|a|ad|al|alla|for)\s+(.+?))?(?:\s+(?:grazie|thanks|thank you|please))?$")
# A voce le opzioni si chiamano con numeri: in italiano le lettere si confondono
# (bi, ci, di, gi, pi, vi suonano quasi uguali; misurato sulla voce vera il 19/11)
NOMI_OPZIONE = {"A": "uno", "B": "due", "C": "tre", "D": "quattro", "E": "cinque", "S": "sì", "N": "no"}
NOMI_OPZIONE_EN = {"A": "one", "B": "two", "C": "three", "D": "four", "E": "five", "S": "yes", "N": "no"}
NUMERI_RISPOSTA = {"uno": "a", "1": "a", "prima": "a", "primo": "a",
                   "due": "b", "2": "b", "seconda": "b", "secondo": "b",
                   "tre": "c", "3": "c", "terza": "c", "terzo": "c",
                   "quattro": "d", "4": "d", "quarta": "d", "quarto": "d",
                   "cinque": "e", "5": "e", "quinta": "e", "quinto": "e",
                   # English
                   "one": "a", "first": "a", "two": "b", "to": "b", "too": "b", "second": "b",
                   "three": "c", "third": "c", "four": "d", "for": "d", "fourth": "d",
                   "five": "e", "fifth": "e"}
PAROLE_PRIMA = {"the", "answer", "option", "number", "letter", "i", "said", "say", "choose", "go", "with",
                "change", "it's", "its", "is",
                "la", "il", "risposta", "rispondi", "rispondo", "scelgo", "opzione", "numero", "lettera",
                "ho", "detto", "dico", "vai", "con", "metti", "e", "è", "cambia", "correggi", "in"}
LETTERE_AMBIGUE = set("BCDE")   # dette come lettere si scambiano tra loro


def nome_opzione(lettera):
    return per_lingua(NOMI_OPZIONE, NOMI_OPZIONE_EN).get(lettera, lettera)


def elenco_opzioni(opzioni):
    """«uno, procedi; due, fermati»: come Ciro dice le opzioni."""
    return "; ".join("%s, %s" % (nome_opzione(l), t) for l, t in opzioni.items())


def numeri_in_lettere(detto):
    """«uno per prova due» -> «a per prova due»: il primo numero (dopo «rispondi»,
    «ho detto»...) diventa la lettera dell'opzione. Ritorna (testo, era_numero)."""
    parole = detto.split()
    for indice, parola in enumerate(parole):
        if parola in PAROLE_PRIMA:
            continue
        if parola in NUMERI_RISPOSTA:
            parole[indice] = NUMERI_RISPOSTA[parola]
            return " ".join(parole), True
        break
    return detto, False


# come whisper scrive a volte una lettera detta da sola
LETTERE_SENTITE = {"ah": "a", "ahh": "a", "aah": "a", "ha": "a", "à": "a",
                   "bi": "b", "be": "b", "bè": "b", "ci": "c"}
CORREZIONE_RE = re.compile(r"^(?:rispondi|cambia(?:\s+in)?|correggi(?:\s+in)?|answer|change(?:\s+it)?\s+to|"
                           r"correct(?:\s+it)?\s+to)\s+(?:la\s+|the\s+)?([a-z])$")
CORREZIONE_SECONDI = 120
OPZIONI_DEPLOY_PROVA = {"A": "autorizza questa volta",
                        "B": "autorizza sempre su questo progetto dopo i test",
                        "C": "rimanda"}


def _moduli_posta():
    cartella = str(POSTA_SCRIPT.parent)
    if cartella not in sys.path:
        sys.path.insert(0, cartella)
    import coordinatore
    import domande
    import posta
    return posta, domande, coordinatore


def opzioni_per_voce(scheda):
    """Le opzioni che Ciro dice. Per un deploy di prova con l'opzione che
    procede indicata, sono quelle di Ciro: questa volta, sempre, rimanda."""
    if scheda.get("operazione") == "deploy-prova" and scheda.get("raccomanda") in (scheda.get("opzioni") or {}):
        return dict(OPZIONI_DEPLOY_PROVA)
    return dict(scheda.get("opzioni") or {})


def _norma(testo):
    return re.sub(r"[^a-z0-9]", "", (testo or "").lower())


# Impostazioni cambiate a voce («riepilogo ogni ora», «niente riepiloghi»)
IMPOSTAZIONI = Path(os.environ.get("FACCIA_IMPOSTAZIONI") or (Path.home() / ".config/faccia/impostazioni.json"))
IMPOSTAZIONI_PREDEFINITE = {"riepilogo": 30,          # minuti; 0 = spento
                            "pausa_progetti": False,  # niente annunci delle sessioni...
                            "solo_progetti": []}      # ...tranne questi
PAUSA_RE = re.compile(r"^(?:(?:metti in |metti |attiva la )?pausa (?:ai |i |sui |dei )?progetti(?: tranne (.+))?"
                      r"|(?:pause|mute) (?:the )?projects(?: except (.+))?)$")
RIPRESA_RE = re.compile(r"^(?:(?:riprendi|riattiva|togli la pausa)(?: (?:ai |i |dei )?progetti)?"
                        r"|(?:resume|unpause|restart) (?:the )?projects)$")
IMPOSTA_RE = re.compile(r"^\s*IMPOSTA\s*:\s*(riepilogo)\s*\|\s*(\d{1,4})", re.IGNORECASE)


def chiave_lingua(nome):
    """Le impostazioni che dipendono dalla lingua: profilo_voce, profilo_voce_en..."""
    return nome if lingua() == "it" else "%s_%s" % (nome, lingua())


def profilo_voce():
    """Il profilo della voce dell'utente nella lingua attuale (docs/voice-profile-design.md)."""
    return dict(leggi_impostazioni().get(chiave_lingua("profilo_voce")) or {})


def aggiorna_profilo(**campi):
    profilo = profilo_voce()
    profilo.update(campi)
    imposta(chiave_lingua("profilo_voce"), profilo)
    return profilo


def impara_confusione(sentito, giusta):
    """Whisper ha scritto `sentito` quando l'utente diceva `giusta`."""
    sentito = re.sub(r"[^\w'àèéìòù]+", " ", (sentito or "").lower()).strip()
    if not sentito or sentito == giusta:
        return
    profilo = profilo_voce()
    confusioni = dict(profilo.get("confusioni") or {})
    confusioni[sentito] = giusta
    aggiorna_profilo(confusioni=confusioni)


def leggi_impostazioni():
    dati = dict(IMPOSTAZIONI_PREDEFINITE)
    try:
        letti = json.loads(IMPOSTAZIONI.read_text(encoding="utf-8"))
        if isinstance(letti, dict):
            dati.update(letti)
    except (OSError, ValueError):
        pass
    return dati


def imposta(chiave, valore):
    dati = leggi_impostazioni()
    dati[chiave] = valore
    IMPOSTAZIONI.parent.mkdir(parents=True, exist_ok=True)
    temporaneo = IMPOSTAZIONI.with_suffix(".tmp")
    temporaneo.write_text(json.dumps(dati, ensure_ascii=False), encoding="utf-8")
    os.replace(temporaneo, IMPOSTAZIONI)
    return dati


FILE_MUTO = Path.home() / ".config/faccia/muto"

# ringraziamenti e saluti senza richiesta: niente modello, niente risposta
CHIACCHIERA = {"grazie", "grazie mille", "grazie ciro", "ok grazie", "perfetto grazie",
               "grazie a tutti", "ok", "va bene", "bene", "ciao", "a dopo"}


def stato_voce():
    try:
        fino = float(FILE_MUTO.read_text().strip() or 0)
    except (OSError, ValueError):
        fino = 0
    if fino > time.time():
        return "spenta fino alle %s" % time.strftime("%H:%M", time.localtime(fino))
    return "accesa"


PROMPT_PER_VOCE = """Trasforma questa richiesta di una sessione in una frase da dire a voce all'utente.
Formato: la domanda in una frase breve, poi le opzioni come "uno, ...; due, ...; tre, ..." con al massimo otto parole ciascuna.
Niente contesto, niente nomi di file, percorsi, ID o link. Massimo 60 parole. Scrivi solo la frase.

Richiesta:
"""


def domanda_per_voce(testo):
    """Versione parlabile e breve di una domanda lunga (vuota se il modello non risponde)."""
    try:
        uscita, _, codice = chiedi_modello(per_lingua(PROMPT_PER_VOCE, PROMPT_PER_VOCE_EN) + testo[:3000], 60)
    except Exception:  # noqa: BLE001
        return ""
    if codice != 0:
        return ""
    return Cervello._pulisci(uscita)[:500]


REGISTRO = Path.home() / ".config/faccia/conversazioni.log"


def registra(voce):
    """Una riga JSON per scambio in ~/.config/faccia/conversazioni.log
    (si accorcia da solo oltre 2 MB, tenendo la meta' piu' recente)."""
    try:
        REGISTRO.parent.mkdir(parents=True, exist_ok=True)
        with REGISTRO.open("a", encoding="utf-8") as file:
            file.write(json.dumps(voce, ensure_ascii=False) + "\n")
        if REGISTRO.stat().st_size > 2_000_000:
            righe = REGISTRO.read_text(encoding="utf-8").splitlines()
            REGISTRO.write_text("\n".join(righe[len(righe) // 2:]) + "\n", encoding="utf-8")
    except OSError:
        pass


# Contesto della conversazione: resta anche se spegni Ciro o si riavvia il
# server. Le battute vecchie vengono riassunte (compattazione) in background,
# cosi' il prompt resta piccolo ma Ciro ricorda di cosa si parlava.
CONTESTO = Path(os.environ.get("FACCIA_CONTESTO") or (Path.home() / ".config/faccia/contesto.json"))
BATTUTE_NEL_PROMPT = 16      # ultime battute passate per intero al modello
COMPATTA_OLTRE = 30          # oltre questo numero di battute si riassume
BATTUTE_DA_TENERE = 14       # dopo il riassunto restano le piu' recenti
RIASSUNTO_MASSIMO = 2500     # caratteri

PROMPT_COMPATTA = """Tieni la memoria di Ciro, l'assistente vocale dell'utente.
Unisci il riassunto che esiste gia' e le battute qui sotto in un unico riassunto nuovo, in italiano, al massimo 15 righe brevi.
Tieni: decisioni prese, richieste ancora aperte, cosa e' stato mandato e a quale sessione, preferenze o informazioni che l'utente ha dato, argomenti in corso.
Togli saluti, ripetizioni, stati delle sessioni ormai vecchi e chiacchiere. Scrivi solo il riassunto, senza titoli."""


class Cervello:
    def __init__(self):
        self.storico = []          # (chi, testo)
        self.riassunto = ""
        self.ultima = ""           # ora dell'ultima battuta, "GG/MM HH:MM"
        self.azione_in_attesa = None
        self._lock = threading.Lock()
        self._compattando = False
        self.domande_aperte = {}   # progetto -> domanda riportata da Ciro
        # progetto -> ora dell'ultimo invio (per "Ti aspettano"); su file, per i riavvii
        self.decisioni_mandate = self._leggi_decisioni()
        # domande strutturate (posta.py chiedi)
        self.domanda_corrente = None   # ID dell'ultima domanda detta a voce
        self.domande_in_attesa = {}    # ID -> scheda, in ordine di annuncio
        self.risposte_automatiche = {}  # ID -> (ora, scheda) delle risposte date da una regola
        self.risposte_recenti = {}     # ID -> (ora, scheda, scelta): correggibili per 2 minuti
        self.annunciate = {}           # ID -> ora in cui Ciro l'ha detta
        self.lettera_sospesa = None    # lettera detta senza progetto, con piu' domande aperte
        self.autorizzazione_in_attesa = None  # scheda di un deploy di prova: «B» da confermare
        self.conferma_lettera = None   # (scheda, lettera, sentito): «Hai detto tre?» su una risposta incerta
        self.sentito_per_risposta = {}  # ID -> cosa aveva capito whisper (per imparare dalle correzioni)
        self.da_imparare = None        # {sentito, giusta}: il server salva quell'audio nel banco di prova
        # cosa ha detto Ciro per ultimo: le risposte brevi («sì», «A», «rispondi B»)
        # vanno solo li'. tipo: domanda, automatica, avviso, proposta, mandato
        self.ultimo_detto = None
        self.collaudo = None          # calibrazione guidata (collaudo.Collaudo), se c'e'
        self.ultimo_livello = None    # livello del microfono dell'ultima frase (dalla pagina)
        self.ultime_pause = None      # pause dentro l'ultima frase, in ms (dalla pagina)
        self._carica()

    @staticmethod
    def _file_decisioni():
        return Path(CONTESTO).with_name("decisioni-mandate.json")

    def _leggi_decisioni(self):
        try:
            dati = json.loads(self._file_decisioni().read_text(encoding="utf-8"))
            return {str(k): float(v) for k, v in dati.items()} if isinstance(dati, dict) else {}
        except (OSError, ValueError, TypeError):
            return {}

    def segna_decisione(self, progetto):
        """Ricorda che la risposta e' partita: "Ti aspettano" non la ripropone, anche dopo un riavvio."""
        self.decisioni_mandate[progetto] = time.time()
        try:
            self._file_decisioni().write_text(json.dumps(self.decisioni_mandate), encoding="utf-8")
        except OSError:
            pass

    def annota_avviso(self, progetto, frase, domanda=True):
        """Il server ha fatto dire a Ciro un avviso: entra nella conversazione
        e, se e' una domanda di una sessione, la risposta partira' subito."""
        with self._lock:
            self.storico.append(("faccia", frase))
            if domanda and progetto:
                self.domande_aperte[progetto] = frase
            self.ultimo_detto = {"tipo": "avviso", "id": progetto, "ora": time.time()}
        self._salva()

    def annota_domanda(self, scheda, frase):
        """Ciro ha appena detto una domanda strutturata: le risposte brevi
        («A», «sì») vanno a lei."""
        with self._lock:
            self.storico.append(("faccia", frase))
            self.domande_in_attesa.pop(scheda["id"], None)
            self.domande_in_attesa[scheda["id"]] = scheda
            self.domanda_corrente = scheda["id"]
            self.annunciate[scheda["id"]] = time.time()
            self.ultimo_detto = {"tipo": "domanda", "id": scheda["id"], "ora": time.time()}
        self._salva()

    def annota_automatica(self, scheda, frase):
        """Una regola ha risposto al posto dell'utente: entro 2 minuti
        puo' ancora dire «annulla» o «rispondi B»."""
        with self._lock:
            self.storico.append(("faccia", frase))
            self.risposte_automatiche[scheda["id"]] = (time.time(), scheda)
            esito = scheda.get("risposta") or {}
            self.risposte_recenti[scheda["id"]] = (time.time(), scheda, esito.get("scelta"))
            self.ultimo_detto = {"tipo": "automatica", "id": scheda["id"], "ora": time.time()}
        self._salva()

    def chiedi_preferenze(self, prompt):
        """Il modello valuta se una preferenza salvata copre una domanda
        (lo usa solo il coordinatore, in sottofondo)."""
        uscita, errore, codice = chiedi_modello(prompt, 30)
        if codice != 0:
            raise RuntimeError((errore or "errore del modello")[-200:])
        return uscita

    # ------------------------------------------------- risposte veloci
    def _aggiorna_domande(self, domande):
        """Le domande davvero in attesa (anche dopo un riavvio di Ciro), in ordine di annuncio."""
        attese = {s["id"]: s for s in domande.elenca("in-attesa")}
        for identificativo in list(self.domande_in_attesa):
            if identificativo not in attese:
                self.domande_in_attesa.pop(identificativo, None)
        for identificativo, scheda in attese.items():
            if identificativo in self.domande_in_attesa:
                self.domande_in_attesa[identificativo] = scheda
            else:
                self.domande_in_attesa = {identificativo: scheda, **self.domande_in_attesa}
        if self.domanda_corrente not in self.domande_in_attesa:
            self.domanda_corrente = next(reversed(self.domande_in_attesa), None) if self.domande_in_attesa else None

    def _progetto_esatto(self, testo):
        """La domanda in attesa del progetto, se il testo e' esattamente il suo
        nome (tollerando «per», «a», maiuscole e trattini)."""
        detto = _norma(re.sub(r"^(?:per|a|ad|al|alla|di)\s+", "", (testo or "").strip().lower()))
        trovate = [s for s in self.domande_in_attesa.values() if detto and _norma(s.get("progetto")) == detto]
        return trovate[-1] if trovate else None

    def _manda(self, scheda, scelta, testo_detto, motivo="utente", sentito=None):
        posta, _, _ = _moduli_posta()
        try:
            posta.rispondi_domanda(scheda["id"], scelta, None, motivo, "opencode")
        except posta.ErroreStato:
            self.domande_in_attesa.pop(scheda["id"], None)
            return self._detto(testo_detto, t("Già mandata."), False)
        except posta.ErrorePosta as errore:
            return self._detto(testo_detto, t("Non riesco a mandarla: %s") % errore, False)
        self.domande_in_attesa.pop(scheda["id"], None)
        self.lettera_sospesa = None
        self.risposte_recenti[scheda["id"]] = (time.time(), scheda, scelta)
        self.sentito_per_risposta[scheda["id"]] = sentito or re.sub(
            r"[^\w'àèéìòù]+", " ", (testo_detto or "").lower()).strip()
        self.segna_decisione(scheda.get("progetto"))
        self.ultimo_detto = {"tipo": "mandato", "id": scheda["id"], "ora": time.time()}
        # dice cosa ha capito: se e' sbagliato lo senti subito («annulla» entro 2 minuti)
        testo_opzione = (scheda.get("opzioni") or {}).get(scelta, "")
        return self._detto(testo_detto, t("Mandato: %s.") % ", ".join(
            x for x in (nome_opzione(scelta), testo_opzione) if x), True)

    def _detto(self, testo, risposta, mandato):
        self.storico += [("io", testo), ("faccia", risposta)]
        self.storico = self.storico[-80:]
        return {"risposta": risposta, "azione": None, "mandato": mandato}

    def _correggi(self, testo, detto):
        annulla = detto in ("annulla", "cancel", "cancel it") or detto.startswith("annulla ")
        cambio = CORREZIONE_RE.match(detto)
        if not annulla and not cambio:
            return None
        adesso = time.time()
        ultimo = self.ultimo_detto or {}
        if ultimo.get("tipo") not in ("automatica", "mandato") or ultimo.get("id") not in self.risposte_recenti:
            return None  # si corregge solo la risposta appena data
        ora, scheda, _ = self.risposte_recenti[ultimo["id"]]
        if adesso - ora > CORREZIONE_SECONDI:
            return None
        posta, domande, _ = _moduli_posta()
        opzioni = scheda.get("opzioni") or {}
        if annulla:
            correzione = "annulla"
            corpo = ("Correzione dell'utente: annulla la risposta alla domanda %s. "
                     "Non procedere e aspetta una nuova risposta." % scheda["id"])
        else:
            correzione = cambio.group(1).upper()
            if correzione not in opzioni:
                return self._detto(testo, t("Le opzioni erano %s.") % ", ".join(opzioni), False)
            corpo = ("Correzione dell'utente alla domanda %s: la risposta giusta e' %s) %s."
                     % (scheda["id"], correzione, opzioni[correzione]))
            # whisper aveva capito male una risposta brevissima: lo ricordo (profilo voce)
            sentito = self.sentito_per_risposta.get(scheda["id"]) or ""
            if sentito and len(sentito) <= 3 and " " not in sentito:
                impara_confusione(sentito, nome_opzione(correzione))
                self.da_imparare = {"sentito": sentito, "giusta": nome_opzione(correzione)}
        try:
            posta.invia("opencode", scheda["progetto"], "decisione",
                        "Correzione: %s" % (scheda.get("oggetto") or scheda["id"]), corpo,
                        rif=scheda["id"], azione="nessuna",
                        extra={"DOMANDA-ID": scheda["id"], "CORREZIONE": correzione})
            attuale = domande.annota(scheda["id"], "utente", "correzione: %s" % correzione,
                                     correzione=correzione)
        except Exception as errore:  # noqa: BLE001
            return self._detto(testo, t("Non riesco a mandare la correzione: %s") % errore, False)
        if correzione != "annulla":
            self.risposte_recenti[scheda["id"]] = (adesso, scheda, correzione)
        else:
            self.risposte_recenti.pop(scheda["id"], None)
        risposta = t("Correzione mandata a %s.") % scheda["progetto"]
        if attuale.get("stato") in ("recepita", "risolta"):
            risposta += t(" Attenzione: potrebbe aver già agito.")
        return self._detto(testo, risposta, True)

    @staticmethod
    def _autorizzazioni(verbo, progetto):
        try:
            _, _, coordinatore = _moduli_posta()
            casella = trova_casella(progetto) or progetto.strip().lower()
            if verbo == "togli":
                tolte = coordinatore.togli_autorizzazioni(casella)
                return (t("Fatto: da ora su %s chiedo sempre.") % casella if tolte
                        else t("Su %s chiedevo gia' sempre.") % casella)
            regole = coordinatore.elenca_autorizzazioni(casella)
        except Exception as errore:  # noqa: BLE001
            return t("Non riesco a leggere le autorizzazioni: %s") % errore
        if not regole:
            return t("Su %s non ho autorizzazioni: chiedo sempre.") % casella
        return t("Su %s posso fare da solo: %s.") % (
            casella, "; ".join(t("deploy di prova dopo %s") % ", ".join(r.get("condizioni") or [])
                               for r in regole))

    def risposta_veloce(self, testo):
        """Risposta a una domanda strutturata, senza modello. None se il testo non lo e'.

        Una risposta breve va solo a cio' che Ciro ha detto per ultimo: se e'
        stato altro (un avviso, una proposta da confermare, un'altra domanda),
        Ciro chiede «Per quale progetto?» invece di indovinare."""
        detto = re.sub(r"[^\w'àèéìòù]+", " ", (testo or "").lower()).strip()
        appresi = leggi_impostazioni().get("alias_lettere") or {}   # dalla calibrazione
        detto = appresi.get(detto) or LETTERE_SENTITE.get(detto, detto)
        if not detto:
            return None
        detto_parole = detto
        detto, era_numero = numeri_in_lettere(detto)
        try:
            posta, domande, coordinatore = _moduli_posta()
            with self._lock:
                self._aggiorna_domande(domande)
        except Exception:  # noqa: BLE001
            return None

        # «B» su un deploy di prova: la regola si salva solo dopo il suo «sì»
        if self.autorizzazione_in_attesa:
            scheda = self.autorizzazione_in_attesa
            if detto in ("si", "sì", "yes") or e_conferma(detto):
                self.autorizzazione_in_attesa = None
                try:
                    regola = coordinatore.salva_autorizzazione(
                        scheda["progetto"], "deploy-prova", "prova", scheda.get("condizioni") or [],
                        "deploy di prova di %s dopo %s" % (scheda["progetto"],
                                                           ", ".join(scheda.get("condizioni") or [])))
                except ValueError as errore:
                    return self._detto(testo, t("Non posso salvarla: %s.") % errore, False)
                esito = self._manda(scheda, scheda["raccomanda"], testo, "regola:%s" % regola["id"])
                if esito["mandato"]:
                    esito["risposta"] = t("Salvata. ") + esito["risposta"]
                return esito
            if NO_RE.match(detto):
                self.autorizzazione_in_attesa = None
                return self._detto(testo, t("Va bene, non la salvo. La domanda resta in attesa."), False)
            self.autorizzazione_in_attesa = None

        # «Hai detto tre?» dopo una lettera ambigua: «sì» la manda, il numero la corregge
        if self.conferma_lettera:
            scheda, lettera_ambigua, sentito_prima = self.conferma_lettera
            self.conferma_lettera = None
            if detto in ("si", "sì", "yes") or e_conferma(detto):
                return self._manda(scheda, lettera_ambigua, testo, sentito=sentito_prima)
            if NO_RE.match(detto):
                return self._detto(testo, t("Va bene. Dimmi il numero: %s.") % elenco_opzioni(
                    opzioni_per_voce(scheda)), False)

        # un messaggio libero aspetta conferma: «sì», «no», «annulla» sono per lui
        if self.azione_in_attesa and (detto in ("si", "sì", "no", "yes") or e_conferma(detto) or NO_RE.match(detto)):
            return None

        # «annulla» o «rispondi B» subito dopo una risposta: e' una correzione
        corretto = self._correggi(testo, detto)
        if corretto is not None:
            return corretto

        # solo il nome del progetto, dopo «Per quale progetto?»
        if self.lettera_sospesa:
            lettera_sospesa, self.lettera_sospesa = self.lettera_sospesa, None
            scheda = self._progetto_esatto(detto)
            if scheda:
                return self._rispondi_lettera(scheda, lettera_sospesa, testo)

        lettera = progetto = None
        trovata = LETTERA_RE.match(detto)
        if trovata:
            lettera, progetto = trovata.group(1).upper(), trovata.group(2)
        elif detto in ("si", "sì", "no", "yes"):
            lettera = "no" if detto == "no" else "si"
        if lettera is None:
            lettera = self._lettera_da_parole(detto_parole)   # «procedi» al posto di «A»
        # errori tipici di questa voce (profilo): si chiede conferma invece di indovinare
        confusioni = profilo_voce().get("confusioni") or {}
        da_confermare = detto_parole in confusioni
        alternativa = None
        if da_confermare:
            probabile, _ = numeri_in_lettere(confusioni[detto_parole])
            alternativa = probabile.upper() if len(probabile) == 1 else (
                "si" if probabile in ("si", "sì") else "no" if probabile == "no" else None)
            if lettera is None:
                lettera = alternativa
        if lettera is None:
            return None

        if not self.domande_in_attesa:
            ultimo = self.ultimo_detto or {}
            if (trovata and not progetto and ultimo.get("tipo") == "mandato"
                    and time.time() - ultimo.get("ora", 0) <= CORREZIONE_SECONDI and not self.domande_aperte):
                return self._detto(testo, t("Già mandata."), False)
            return None

        if progetto:
            scheda = self._progetto_esatto(progetto)
            if scheda is None:
                return None  # «e alla fine ...»: una frase, non una risposta
            return self._rispondi_lettera(scheda, lettera, testo, ambigua=bool(trovata) and not era_numero,
                                          conferma=da_confermare, alternativa=alternativa, sentito=detto_parole)

        if lettera not in ("si", "no") and not any(lettera in opzioni_per_voce(s)
                                                   for s in self.domande_in_attesa.values()):
            if len(detto) > 12:
                return None  # una frase che inizia con una lettera
        ultimo = self.ultimo_detto or {}
        if len(self.domande_in_attesa) == 1:
            scheda = next(iter(self.domande_in_attesa.values()))
            # dopo un riavvio Ciro non ha ancora detto nulla: c'e' una sola domanda
            if ultimo == {} or (ultimo.get("tipo") == "domanda" and ultimo.get("id") == scheda["id"]):
                return self._rispondi_lettera(scheda, lettera, testo, ambigua=bool(trovata) and not era_numero,
                                          conferma=da_confermare, alternativa=alternativa, sentito=detto_parole)
        self.lettera_sospesa = lettera
        return self._detto(testo, t("Per quale progetto?"), False)

    def _comando_pausa(self, testo):
        detto = re.sub(r"[^\w\s'-]+", " ", (testo or "").lower())
        detto = re.sub(r"\s+", " ", detto).strip()
        pausa = PAUSA_RE.match(detto)
        if pausa:
            permessi = []
            for nome in re.split(r",| e | and ", pausa.group(1) or pausa.group(2) or ""):
                nome = nome.strip()
                if nome:
                    permessi.append(trova_casella(nome) or nome)
            imposta("pausa_progetti", True)
            imposta("solo_progetti", permessi)
            risposta = t("Progetti in pausa") + (t(", tranne %s.") % t(" e ").join(permessi) if permessi else ".")
            return self._detto(testo, risposta, False)
        if RIPRESA_RE.match(detto):
            imposta("pausa_progetti", False)
            imposta("solo_progetti", [])
            return self._detto(testo, t("Progetti ripresi."), False)
        return None

    def _lettera_da_parole(self, detto):
        """La lettera dell'opzione detta per intero («procedi» = A), solo se la
        domanda aperta e' una e coincide con quello che Ciro ha detto per ultimo."""
        if len(self.domande_in_attesa) != 1:
            return None
        scheda = next(iter(self.domande_in_attesa.values()))
        ultimo = self.ultimo_detto or {}
        if ultimo and not (ultimo.get("tipo") == "domanda" and ultimo.get("id") == scheda["id"]):
            return None
        for lettera, testo in opzioni_per_voce(scheda).items():
            if _norma(testo) and _norma(testo) == _norma(detto):
                return lettera
        return None

    def _valida(self, scheda, lettera):
        """La lettera dell'opzione corrispondente (sì/no -> S/N), o None."""
        opzioni = opzioni_per_voce(scheda)
        if lettera in ("si", "no"):
            return ("S" if lettera == "si" else "N") if set(opzioni) >= {"S", "N"} else None
        return lettera if lettera in opzioni else None

    def _chiedi_conferma(self, scheda, lettera, testo, sentito):
        self.conferma_lettera = (scheda, lettera, sentito)
        return self._detto(testo, t("Hai detto %s, %s? Di' sì, oppure il numero.") % (
            nome_opzione(lettera), opzioni_per_voce(scheda)[lettera]), False)

    def _rispondi_lettera(self, scheda, lettera, testo, ambigua=False, conferma=False,
                          alternativa=None, sentito=None):
        self.lettera_sospesa = None
        opzioni = opzioni_per_voce(scheda)
        if conferma:   # un errore tipico di questa voce: conferma con l'ipotesi valida
            for candidata in (lettera, alternativa):
                valida = self._valida(scheda, candidata) if candidata else None
                if valida:
                    return self._chiedi_conferma(scheda, valida, testo, sentito)
        if ambigua and lettera in LETTERE_AMBIGUE and len(opzioni) >= 3 and lettera in opzioni:
            # una lettera detta da sola con tre o piu' opzioni: B, C, D si scambiano
            return self._chiedi_conferma(scheda, lettera, testo, sentito)
        if lettera in ("si", "no"):
            if set(opzioni) >= {"S", "N"}:
                lettera = "S" if lettera == "si" else "N"
            elif lettera == "si" and opzioni == OPZIONI_DEPLOY_PROVA:
                lettera = "A"  # «sì» a un deploy di prova: autorizza questa volta
            elif lettera == "si" and scheda.get("raccomanda") in opzioni:
                # Ciro ha detto «Consiglia X»: «sì» accetta il consiglio, e lo dice
                return self._manda(scheda, scheda["raccomanda"], testo)
            else:
                return self._detto(testo, t("Rispondi con il numero: %s.") % elenco_opzioni(opzioni), False)
        if lettera not in opzioni:
            return self._detto(testo, t("Le opzioni sono: %s.") % elenco_opzioni(opzioni), False)
        if opzioni == OPZIONI_DEPLOY_PROVA and scheda.get("operazione") == "deploy-prova":
            if lettera == "A":
                return self._manda(scheda, scheda["raccomanda"], testo)
            if lettera == "C":
                return self._detto(testo, t("Va bene, resta in attesa."), False)
            self.autorizzazione_in_attesa = scheda
            condizioni = ", ".join(scheda.get("condizioni") or []) or t("nessuna condizione")
            return self._detto(testo, t("Salvo: %s, deploy di prova, dopo %s. Confermi?")
                               % (scheda["progetto"], condizioni), False)
        return self._manda(scheda, lettera, testo, sentito=sentito)

    def _domanda_aperta_di(self, progetto):
        """La domanda strutturata ancora senza risposta di un progetto, se c'e'."""
        try:
            _, domande, _ = _moduli_posta()
            aperte = [s for s in domande.elenca()
                      if s.get("progetto") == progetto
                      and s.get("stato") in ("ricevuta", "in-valutazione", "in-attesa")]
        except Exception:  # noqa: BLE001
            return None
        return aperte[-1] if aperte else None

    def _invia_strutturata(self, scheda, azione):
        """Una risposta libera a una domanda strutturata passa dal registro:
        una sola consegna, con la nota dell'utente nel testo."""
        posta, _, _ = _moduli_posta()
        opzioni = scheda.get("opzioni") or {}
        dette = opzioni_per_voce(scheda)
        testo = azione.get("testo") or ""
        scelta = (azione.get("scelta") or "").strip().upper()[:1]
        if not scelta:
            numero, era_numero = numeri_in_lettere(re.sub(r"[^\w'àèéìòù]+", " ", testo.lower()).strip())
            inizio = re.match(r"^\s*(?:la\s+|opzione\s+)?([A-Za-z])(?![A-Za-zàèéìòù])", numero if era_numero else testo)
            if inizio:
                scelta = inizio.group(1).upper()
            elif re.match(r"(?i)^\s*s[iì]\b", testo) and "S" in opzioni:
                scelta = "S"
            elif re.match(r"(?i)^\s*no\b", testo) and "N" in opzioni:
                scelta = "N"
        if dette == OPZIONI_DEPLOY_PROVA:
            if scelta != "A":
                return t("Per il deploy di prova rispondi con uno, due o tre.")
            scelta = scheda["raccomanda"]
        if scelta not in opzioni:
            return t("Per mandarla mi serve il numero: %s.") % elenco_opzioni(dette)
        try:
            posta.rispondi_domanda(scheda["id"], scelta, testo, "utente", "opencode")
        except posta.ErroreStato:
            return t("Già mandata.")
        except posta.ErrorePosta as errore:
            return t("Non sono riuscito a mandarlo: %s") % errore
        with self._lock:
            self.domande_in_attesa.pop(scheda["id"], None)
        self.risposte_recenti[scheda["id"]] = (time.time(), scheda, scelta)
        self.segna_decisione(scheda.get("progetto"))
        self.ultimo_detto = {"tipo": "mandato", "id": scheda["id"], "ora": time.time()}
        return t("Mandato a %s: %s, %s.") % (scheda.get("progetto"), nome_opzione(scelta), opzioni.get(scelta, ""))

    # ------------------------------------------------------------- contesto
    def _carica(self):
        try:
            dati = json.loads(CONTESTO.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        self.riassunto = str(dati.get("riassunto") or "")
        self.ultima = str(dati.get("ultima") or "")
        self.storico = [(str(c), str(t)) for c, t in (dati.get("storico") or []) if t]

    def _salva(self):
        with self._lock:
            dati = {"riassunto": self.riassunto, "ultima": self.ultima,
                    "storico": [list(b) for b in self.storico]}
        try:
            CONTESTO.parent.mkdir(parents=True, exist_ok=True)
            provvisorio = CONTESTO.with_suffix(".tmp")
            provvisorio.write_text(json.dumps(dati, ensure_ascii=False, indent=1), encoding="utf-8")
            provvisorio.replace(CONTESTO)
        except OSError:
            pass

    def _compatta_se_serve(self):
        with self._lock:
            if self._compattando or len(self.storico) <= COMPATTA_OLTRE:
                return
            self._compattando = True
            vecchie = self.storico[:-BATTUTE_DA_TENERE]
            riassunto = self.riassunto
        threading.Thread(target=self._compatta, args=(vecchie, riassunto), daemon=True).start()

    def _compatta(self, vecchie, riassunto):
        testo = [per_lingua(PROMPT_COMPATTA, PROMPT_COMPATTA_EN), "", "Riassunto esistente:", riassunto or "(vuoto)", "",
                 "Battute:"]
        testo += ["%s: %s" % (NOME_UTENTE if c == "io" else "Ciro", t) for c, t in vecchie]
        nuovo = ""
        try:
            uscita, _, codice = chiedi_modello("\n".join(testo), 120)
            if codice == 0:
                nuovo = self._pulisci(uscita)[:RIASSUNTO_MASSIMO]
        except Exception:  # noqa: BLE001
            nuovo = ""
        with self._lock:
            if nuovo:
                self.riassunto = nuovo
                self.storico = self.storico[len(vecchie):]
            self._compattando = False
        registra({"ora": time.strftime("%Y-%m-%d %H:%M:%S"), "tipo": "compattazione",
                  "riuscita": bool(nuovo), "battute_riassunte": len(vecchie), "riassunto": nuovo})
        if nuovo:
            self._salva()

    # ---------------------------------------------------------------- interno
    def _prompt(self, testo):
        en = lingua() == "en"
        parti = [ISTRUZIONI_EN if en else ISTRUZIONI, ""]
        if NOME_UTENTE != "Utente":
            parti += [("The user's name is %s." if en else "L'utente si chiama %s.") % NOME_UTENTE, ""]
        parti += [("Your voice: %s" if en else "La tua voce: %s") % stato_voce(), ""]
        parti += ["Saved rules:" if en else "Regole salvate:", quadro_regole(), ""]
        parti += ["Open Claude Code sessions:" if en else "Sessioni Claude Code aperte:", quadro_sessioni(), ""]
        parti += ["Incoming mail (opencode mailbox):" if en else "Posta in arrivo (casella opencode):",
                  posta_recente(), ""]
        if self.azione_in_attesa:
            parti += [
                ("Action proposed and not yet confirmed: %s" if en else
                 "Azione proposta e non ancora confermata: %s") % self.azione_in_attesa["descrizione"],
                "If the user says yes, answer that you send it and repeat the AZIONE line." if en else
                "Se l'utente dice si, rispondi che la mandi e ripeti la riga AZIONE.",
                "",
            ]
        if self.riassunto:
            parti += ["Summary of earlier conversations with the user:" if en else
                      "Riassunto delle conversazioni precedenti con l'utente:", self.riassunto, ""]
        utente = "User" if en else "Utente"
        if self.storico:
            intestazione = "Conversation so far" if en else "Conversazione fin qui"
            if self.ultima:
                intestazione += (" (last line: %s; now: %s)" if en else " (ultima battuta: %s; adesso: %s)") % (
                    self.ultima, time.strftime("%d/%m %H:%M"))
            parti.append(intestazione + ":")
            for chi, frase in self.storico[-BATTUTE_NEL_PROMPT:]:
                parti.append("%s: %s" % (utente if chi == "io" else "Ciro", frase))
            parti.append("")
        parti.append("%s: %s" % (utente, testo))
        return "\n".join(parti)

    @staticmethod
    def _pulisci(uscita):
        righe = []
        for riga in uscita.splitlines():
            riga = riga.strip()
            if not riga or riga.startswith(">"):
                continue
            righe.append(riga)
        testo = " ".join(righe)
        testo = re.sub(r"```.*?```", " ", testo, flags=re.S)
        testo = re.sub(r"[*_#`]+", "", testo)
        return re.sub(r"\s+", " ", testo).strip()

    @staticmethod
    def _leggi_azione(riga):
        campi = {}
        for pezzo in riga.split("|"):
            pezzo = pezzo.strip()
            if "=" not in pezzo:
                continue
            chiave, valore = pezzo.split("=", 1)
            campi[chiave.strip().lower()] = valore.strip()
        if not campi.get("a") or not campi.get("testo"):
            return None
        if campi.get("tipo") not in ("richiesta", "decisione"):
            campi["tipo"] = "richiesta"
        campi.setdefault("oggetto", "Messaggio dalla faccia")
        return campi

    def _invia(self, azione):
        if azione.get("tipo") == "decisione":
            scheda = self._domanda_aperta_di(azione["a"])
            if scheda:
                return self._invia_strutturata(scheda, azione)
        comando = [
            sys.executable, str(POSTA_SCRIPT), "invia",
            "--da", CASSELLA,
            "--a", azione["a"],
            "--tipo", azione["tipo"],
            "--oggetto", PREFISSO_OGGETTO + azione["oggetto"],
            "--testo", azione["testo"],
        ]
        if azione["tipo"] == "decisione":
            comando += ["--azione", "decisione"]
        _, errore, codice = _esegui(comando, 20)
        if codice != 0:
            return t("Non sono riuscito a mandarlo: %s") % (errore or "errore della posta")
        self.segna_decisione(azione["a"])
        return t("Mandato a %s.") % azione["a"]

    # ------------------------------------------------------------------ fuori
    def chiedi(self, testo):
        """Risponde e scrive lo scambio nel registro (per capire i bug)."""
        inizio = time.time()
        attesa_prima = bool(self.azione_in_attesa)
        esito = self._rispondi(testo)
        self.ultima = time.strftime("%d/%m %H:%M")
        self._salva()
        self._compatta_se_serve()
        registra({
            "ora": time.strftime("%Y-%m-%d %H:%M:%S"),
            "tipo": "cervello",
            "secondi": round(time.time() - inizio, 1),
            "modello": MODELLO,
            "tu": (testo or "").strip(),
            "ciro": esito.get("risposta"),
            "azione_in_attesa_prima": attesa_prima,
            "azione": {k: v for k, v in (esito.get("azione") or {}).items() if k != "descrizione"} or None,
            "mandato": esito.get("mandato"),
        })
        return esito

    def _rispondi(self, testo):
        testo = (testo or "").strip()
        if not testo:
            return {"risposta": "", "azione": None, "mandato": False}

        # «parla inglese» / «speak Italian»: cambia lingua (voce, ascolto, modello)
        compatto = re.sub(r"[^a-zàèéìòù]", "", testo.lower())
        compatto = re.sub(r"^(ciro|please)", "", compatto)
        if compatto in ("parlainglese", "parlaininglese", "ininglese", "speakenglish", "english", "inenglish"):
            imposta("lingua", "en")
            return self._detto(testo, "OK, from now on I speak English.", False)
        if compatto in ("parlaitaliano", "parlainitaliano", "initaliano", "speakitalian", "italian", "initalian",
                        "italiano"):
            imposta("lingua", "it")
            return self._detto(testo, "Va bene, da ora parlo italiano.", False)

        # calibrazione guidata: «Ciro, calibrati»; mentre misura, le frasi non sono comandi
        if self.collaudo is not None:
            detto = re.sub(r"[^\w\s]+", " ", testo.lower()).split()
            # whisper a volte attacca le parole («cirocalibrati»): confronto senza spazi
            comando = re.sub(r"^ciro", "", "".join(w for w in detto if w != "ciro"))
            if comando in ("calibrati", "calibrazione", "falacalibrazione", "avvialacalibrazione",
                           "calibrazioneguidata", "calibrare", "calibrate", "calibration", "calibrateyourself",
                           "startthecalibration", "startcalibration"):
                risposta = self.collaudo.avvia("calibrazione")
                self.storico += [("io", testo), ("faccia", risposta)]
                return {"risposta": risposta, "azione": None, "mandato": False,
                        "comando": "misura-silenzio", "secondi": 5}
            if comando in ("collaudo", "failcollaudo", "avviailcollaudo", "collaudati", "acceptancetest",
                           "runtheacceptancetest", "selftest"):
                risposta = self.collaudo.avvia("collaudo")
                self.storico += [("io", testo), ("faccia", risposta)]
                return {"risposta": risposta, "azione": None, "mandato": False}
            consumato = self.collaudo.gestisci(testo, self.ultimo_livello, self.ultime_pause)
            if consumato is not None:
                self.storico += [("io", testo), ("faccia", consumato["risposta"])]
                return consumato

        # «pausa progetti [tranne X]» / «riprendi i progetti»: subito, senza modello
        comando = self._comando_pausa(testo)
        if comando is not None:
            return comando

        # risposta a una domanda strutturata: parte subito, senza modello
        veloce = self.risposta_veloce(testo)
        if veloce is not None:
            return veloce

        # conferma di un'azione gia' proposta: la eseguo io, senza modello
        detto = re.sub(r"[^\w'àèéìòù]+", " ", testo.lower()).strip()
        if self.azione_in_attesa and e_conferma(detto):
            azione = self.azione_in_attesa
            self.azione_in_attesa = None
            esito = self._invia(azione)
            self.storico += [("io", testo), ("faccia", esito)]
            self.storico = self.storico[-80:]
            return {"risposta": esito, "azione": azione, "mandato": True}
        if self.azione_in_attesa and NO_RE.match(detto):
            self.azione_in_attesa = None
            esito = t("Va bene, non lo mando.")
            self.storico += [("io", testo), ("faccia", esito)]
            return {"risposta": esito, "azione": None, "mandato": False}

        if detto in CHIACCHIERA and not self.azione_in_attesa:
            return {"risposta": "", "azione": None, "mandato": False}

        self.storico.append(("io", testo))
        try:
            uscita, errore, codice = chiedi_modello(
                self._prompt(testo),
                120,
            )
        except subprocess.TimeoutExpired:
            return {"risposta": t("Ci sto mettendo troppo. Riprova tra un momento."), "azione": None, "mandato": False}
        if codice != 0 or not uscita:
            dettaglio = (errore or "").strip().splitlines()
            return {
                "risposta": t("Il cervello non risponde: %s") % (dettaglio[-1][:120] if dettaglio else "errore"),
                "azione": None,
                "mandato": False,
            }

        pulita = self._pulisci(uscita)
        azione = None
        righe_dette = []
        memoria = []
        autorizzazioni = []
        impostazioni_dette = []
        for riga in re.split(r"(?=\b(?:AZIONE|MEMORIA|AUTORIZZAZIONE|IMPOSTA)\s*:)", pulita,
                             flags=re.IGNORECASE):
            impostazione = IMPOSTA_RE.match(riga.strip())
            if impostazione:
                minuti = max(0, min(1440, int(impostazione.group(2))))
                imposta("riepilogo", minuti)
                aggiunta = t("Riepiloghi spenti.") if minuti == 0 else t("Riepilogo ogni %d minuti.") % minuti
                impostazioni_dette.append(aggiunta)
                continue
            permesso = AUTORIZZAZIONE_RE.match(riga.strip())
            if permesso:
                autorizzazioni.append((permesso.group(1).lower(), permesso.group(2).strip()))
                continue
            ricordo = MEMORIA_RE.match(riga.strip())
            if ricordo:
                memoria.append((ricordo.group(1).lower(), ricordo.group(2).strip()))
                continue
            trovata = AZIONE_RE.match(riga.strip())
            if trovata:
                azione = self._leggi_azione(trovata.group(1)) or azione
            else:
                righe_dette.append(riga.strip())
        risposta = " ".join(r for r in righe_dette if r).strip()
        if len(risposta) > RISPOSTA_MASSIMA:
            risposta = risposta[:RISPOSTA_MASSIMA].rsplit(" ", 1)[0] + "."

        for aggiunta in impostazioni_dette:
            if aggiunta.lower() not in risposta.lower():
                risposta = (risposta + " " + aggiunta).strip()
        for verbo, progetto in autorizzazioni:
            risposta = (risposta + " " + self._autorizzazioni(verbo, progetto)).strip()

        for verbo, valore in memoria:
            if verbo == "aggiungi":
                salvata = aggiungi_regola(valore)
                if salvata and "segnat" not in risposta.lower():
                    risposta = (risposta + t(" L'ho segnato: %s.") % salvata).strip()
                elif not salvata:
                    risposta = (risposta + t(" Non sono riuscito a segnarlo.")).strip()
            else:
                tolta = togli_regola(valore)
                if not tolta:
                    risposta = (risposta + t(" Non trovo quella regola da togliere.")).strip()
                elif "tolt" not in risposta.lower():
                    tolta = re.sub(r"^\d{2}/\d{2}/\d{4}:\s*", "", tolta)
                    risposta = (risposta + t(" Ho tolto la regola: %s") % tolta).strip()

        if azione:
            casella = trova_casella(azione["a"])
            strutturata = casella and azione["tipo"] == "decisione" and self._domanda_aperta_di(casella)
            if strutturata:
                # risposta a una domanda strutturata aperta: parte subito, senza «Confermi?»,
                # solo se la lettera e' chiara (altrimenti Ciro la chiede)
                self.domande_aperte.pop(casella, None)
                self.azione_in_attesa = None
                esito = self._invia(azione)
                self.storico.append(("faccia", esito))
                return {"risposta": esito, "azione": azione, "mandato": esito.startswith(t("Mandato"))}
            if casella and azione["tipo"] == "decisione" and casella in self.domande_aperte:
                # risposta a una domanda che Ciro gli ha appena riportato: parte subito
                self.domande_aperte.pop(casella, None)
                self.azione_in_attesa = None
                esito = self._invia(azione)
                if esito.startswith("Non sono riuscito") or "mand" not in risposta.lower():
                    risposta = esito  # errore o risposta muta: dico l'esito vero
                self.storico.append(("faccia", risposta))
                return {"risposta": risposta, "azione": azione, "mandato": True}
            if casella:
                azione["a"] = casella
                azione["descrizione"] = "mandare a %s: %s" % (casella, azione["testo"])
                self.azione_in_attesa = azione
                self.ultimo_detto = {"tipo": "proposta", "id": casella, "ora": time.time()}
                # una domanda alla volta: tolgo le altre domande e i "fatto" anticipati
                frasi = [f for f in re.split(r"(?<=[.!?])\s+", risposta) if f and not f.endswith("?")]
                frasi = [f for f in frasi if not re.match(r"(?i)^(fatto|mandato|inviato)\b", f)]
                risposta = (" ".join(frasi) + " " + t("Lo mando a %s: %s. Confermi?") % (
                    casella, azione["testo"][:160].rstrip("."))).strip()
            else:
                risposta = t("Non trovo nessuna sessione che si chiama %s. A chi lo mando?") % azione["a"]
                azione = None
                self.azione_in_attesa = None
        else:
            self.azione_in_attesa = None

        self.storico.append(("faccia", risposta))
        self.storico = self.storico[-80:]
        return {"risposta": risposta or t("Non ho una risposta."), "azione": azione, "mandato": False}


if __name__ == "__main__":
    domanda = " ".join(sys.argv[1:]) or "Che succede con le sessioni?"
    print(json.dumps(Cervello().chiedi(domanda), ensure_ascii=False, indent=2))
