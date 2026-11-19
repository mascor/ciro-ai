"""Ciro's language: Italian (the source texts) or English.

t("Italian text") returns the English text when the language is English. The language
is the setting "lingua" in ~/.config/faccia/impostazioni.json ("it" or "en"), or the
environment variable CIRO_LINGUA; Italian by default. Templates keep their %s/%d.
"""

import os

LINGUE = ("it", "en")
# models and voice per language: Kokoro voice and language, whisper language
VOCI = {"it": "im_nicola", "en": "am_michael"}
KOKORO = {"it": "it", "en": "en-us"}
WHISPER = {"it": "it", "en": "en"}


def lingua():
    try:
        import cervello
        valore = cervello.leggi_impostazioni().get("lingua")
    except Exception:  # noqa: BLE001
        valore = None
    valore = valore or os.environ.get("CIRO_LINGUA") or "it"
    return valore if valore in LINGUE else "it"


def t(testo):
    if lingua() == "en":
        return EN.get(testo, testo)
    return testo


def per_lingua(italiano, inglese):
    return inglese if lingua() == "en" else italiano


EN = {
    # --- answers to structured questions (cervello.py)
    "Già mandata.": "Already sent.",
    "Non riesco a mandarla: %s": "I can't send it: %s",
    "Mandato: %s.": "Sent: %s.",
    "Mandato": "Sent",
    "Le opzioni erano %s.": "The options were %s.",
    "Non riesco a mandare la correzione: %s": "I can't send the correction: %s",
    "Correzione mandata a %s.": "Correction sent to %s.",
    " Attenzione: potrebbe aver già agito.": " Careful: it may have already acted.",
    "Fatto: da ora su %s chiedo sempre.": "Done: from now on I always ask on %s.",
    "Su %s chiedevo gia' sempre.": "On %s I was already asking every time.",
    "Non riesco a leggere le autorizzazioni: %s": "I can't read the authorisations: %s",
    "Su %s non ho autorizzazioni: chiedo sempre.": "On %s I have no authorisations: I always ask.",
    "Su %s posso fare da solo: %s.": "On %s I can do by myself: %s.",
    "deploy di prova dopo %s": "test deploy after %s",
    "Non posso salvarla: %s.": "I can't save it: %s.",
    "Salvata. ": "Saved. ",
    "Va bene, non la salvo. La domanda resta in attesa.": "OK, I won't save it. The question stays open.",
    "Va bene. Dimmi il numero: %s.": "OK. Tell me the number: %s.",
    "Per quale progetto?": "For which project?",
    "Progetti in pausa": "Projects paused",
    ", tranne %s.": ", except %s.",
    "Progetti ripresi.": "Projects resumed.",
    "Hai detto %s, %s? Di' sì, oppure il numero.": "Did you say %s, %s? Say yes, or the number.",
    "Rispondi con il numero: %s.": "Answer with the number: %s.",
    "Le opzioni sono: %s.": "The options are: %s.",
    "Va bene, resta in attesa.": "OK, it stays open.",
    "Salvo: %s, deploy di prova, dopo %s. Confermi?": "Saving: %s, test deploy, after %s. Do you confirm?",
    "nessuna condizione": "no condition",
    "Per il deploy di prova rispondi con uno, due o tre.": "For the test deploy answer one, two or three.",
    "Per mandarla mi serve il numero: %s.": "To send it I need the number: %s.",
    "Non sono riuscito a mandarlo: %s": "I couldn't send it: %s",
    "Mandato a %s: %s, %s.": "Sent to %s: %s, %s.",
    "Mandato a %s.": "Sent to %s.",
    "Ci sto mettendo troppo. Riprova tra un momento.": "I'm taking too long. Try again in a moment.",
    "Il cervello non risponde: %s": "The brain is not answering: %s",
    "Non ho una risposta.": "I have no answer.",
    "Lo mando a %s: %s. Confermi?": "Shall I send it to %s: %s? Do you confirm?",
    "Va bene, non lo mando.": "OK, I won't send it.",
    "Non trovo nessuna sessione che si chiama %s. A chi lo mando?":
        "I can't find a session called %s. Who should I send it to?",
    " L'ho segnato: %s.": " Noted: %s.",
    " Non sono riuscito a segnarlo.": " I couldn't note it.",
    " Non trovo quella regola da togliere.": " I can't find that rule to remove.",
    " Ho tolto la regola: %s": " I removed the rule: %s",
    "Riepiloghi spenti.": "Summaries off.",
    "Riepilogo ogni %d minuti.": "Summary every %d minutes.",
    "Va bene, da ora parlo italiano.": "Va bene, da ora parlo italiano.",
    "OK, from now on I speak English.": "OK, from now on I speak English.",
    # --- calibration and acceptance test (collaudo.py)
    "Inizio il collaudo: tre compiti, ti dico io cosa fare.":
        "Starting the acceptance test: three tasks, I'll tell you what to do.",
    "Inizio la calibrazione: ti guido io. Prima resta in silenzio per cinque secondi.":
        "Starting the calibration: I'll guide you. First, stay silent for five seconds.",
    "Collaudo fermato.": "Acceptance test stopped.",
    "Calibrazione fermata.": "Calibration stopped.",
    "Resta in silenzio per cinque secondi.": "Stay silent for five seconds.",
    "Calibrazione finita: ti ho capito %d frasi su %d.": "Calibration done: I understood %d phrases out of %d.",
    " Parli piano rispetto al rumore: avvicinati al microfono.":
        " You speak softly compared to the noise: move closer to the microphone.",
    "Aspetta, sto misurando il silenzio.": "Wait, I'm measuring the silence.",
    "Non ho capito bene. %s": "I didn't quite get that. %s",
    "Non ti ho sentito. %s": "I didn't hear you. %s",
    "Di': ": "Say: ",
    "Ora ripeti dopo di me: ": "Now repeat after me: ",
    "Ripeti: ": "Repeat: ",
    "Collaudo finito: %d compiti su %d": "Acceptance test done: %d tasks out of %d",
    ", rispondo in circa %d secondi": ", I answer in about %d seconds",
    " Il rapporto e' nella cartella collaudi.": " The report is in the collaudi folder.",
    "Calibrazione · silenzio": "Calibration · silence",
    "Calibrazione · frasi": "Calibration · phrases",
    "Collaudo · compito %d di %d": "Acceptance test · task %d of %d",
    "Collaudo finito": "Acceptance test done",
    "Calibrazione finita": "Calibration done",
    "Resta in silenzio": "Stay silent",
    "È la prima volta che ci sentiamo: ti guido in una calibrazione di cinquanta secondi.":
        "This is the first time we talk: I'll guide you through a fifty-second calibration.",
    # --- notices and summaries (server.py)
    "Da %s: %s": "From %s: %s",
    "una sessione": "a session",
    " Scrivila nel campo protetto della pagina.": " Type it in the protected field on the page.",
    " Consiglia %s.": " I recommend %s.",
    " Come rispondo?": " How do I answer?",
    "Da %s: %s. Come rispondo?": "From %s: %s. How do I answer?",
    "Da %s, serve una %s: %s. Come rispondo?": "From %s, a %s is needed: %s. How do I answer?",
    "decisione": "decision",
    "conferma sul server": "confirmation on the server",
    "accesso": "access",
    "Ci sono %d domande per te: da %s. Le trovi a sinistra; dimmi da quale parto.":
        "There are %d questions for you: from %s. They are on the left; tell me where to start.",
    "Non riesco a consegnare la risposta a %s.": "I can't deliver the answer to %s.",
    "Ho risposto %s a %s, per la tua regola: %s.": "I answered %s to %s, following your rule: %s.",
    "Riepilogo: %s.": "Summary: %s.",
    "ripartito %s": "%s restarted",
    "risolto %s": "%s solved",
    "%d %s con le tue regole": "%d %s with your rules",
    "risposta data": "answer given",
    "risposte date": "answers given",
    "Aspettano te da oltre mezz'ora: %s.": "Waiting for you for over half an hour: %s.",
    "Durante la pausa sono arrivate %d domande: da %s. Le trovi a sinistra.":
        "During the pause %d questions arrived: from %s. They are on the left.",
    "Salvata nel Portachiavi come %s. Mandato.": "Saved in the Keychain as %s. Sent.",
    " e ": " and ",
    # Google Chat
    "Messaggio %s, ": "Message %s, ",
    "Ti ricordo il messaggio %s, da %s: %s.": "Reminder: message %s, from %s: %s.",
    "Va bene.": "OK.",
    # numbered questions
    "Domanda %s, ": "Question %s, ",
    "Quale domanda? %s.": "Which question? %s.",
    "la": "number",
    "Non c'è una domanda %s. %s": "There is no question %s. %s",
    "Quella domanda è già chiusa.": "That question is already closed.",
    "Eccomi, sono sveglio.": "Here I am, I'm awake.",
    # safety: closed numbers, unheard questions, model actions
    "La %s, di %s, è già chiusa. %s": "Number %s, from %s, is already closed. %s",
    "Prima te la dico. La %s: %s. Ripeti la risposta.": "Let me read it first. Number %s: %s. Say your answer again.",
    "Il messaggio è troppo lungo per leggertelo. Dimmelo più corto.":
        "The message is too long to read back to you. Tell me a shorter one.",
    "Lettura non riuscita": "Read failed",
    "Messaggi non letti": "Unread messages",
    "La %s è un messaggio di Chat: per toglierlo di' «letto il %s».":
        "Number %s is a Chat message: to remove it say «read %s».",
    "Scheda di Chat chiusa": "Chat tab closed",
    "Da %d min non arriva niente da questo profilo: riapri la scheda di Google Chat.":
        "Nothing from this profile for %d min: reopen the Google Chat tab.",
    # session hooks («ciro connect»)
    "vuole eseguire: %s": "wants to run: %s",
    "vuole modificare il file %s": "wants to edit the file %s",
    "vuole consultare il web: %s": "wants to look on the web: %s",
    "vuole usare %s di %s": "wants to use %s from %s",
    "vuole usare %s": "wants to use %s",
    "vuole il permesso %s: %s": "asks for the %s permission: %s",
    "Permesso: %s": "Permission: %s",
    "Consento?": "Shall I allow it?",
    "consenti": "allow",
    "nega": "deny",
    # «cosa mi sono perso?»
    "Non riesco a fare il punto: %s": "I can't catch you up: %s",
    "una domanda nuova da %s": "one new question from %s",
    "%d domande nuove da %s": "%d new questions from %s",
    "Dalle %s: %s.": "Since %s: %s.",
    "Ti aspettano: %s.": "Waiting for you: %s.",
    "; e altre %d": "; and %d more",
    "In Chat, un messaggio urgente.": "In Chat, one urgent message.",
    "In Chat, %d messaggi urgenti.": "In Chat, %d urgent messages.",
    "Niente di nuovo dalle %s, e nessuno ti aspetta.": "Nothing new since %s, and nobody is waiting for you.",
    "Niente di nuovo dalle %s.": "Nothing new since %s.",
    "Non riesco a leggere i messaggi non letti: ricarica la scheda di Google Chat.":
        "I can't read the unread messages: reload the Google Chat tab.",
}
