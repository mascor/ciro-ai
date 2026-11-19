// Ciro's page in Italian (the source texts) or English. T("testo italiano")
// returns the English text when the language is English; the language comes
// from the server (/api/quadro "lingua"). Static elements carry data-t (text)
// and data-t-title / data-t-placeholder with their Italian text.
"use strict";

let LINGUA = "it";

const EN_UI = {
  // page states and buttons
  "Dormo…": "Sleeping…",
  "Pronto": "Ready",
  "Ti ascolto": "Listening",
  "Un attimo": "One moment",
  "Parlo io": "Speaking",
  "Voce non disponibile": "Voice not available",
  "Microfono non disponibile": "Microphone not available",
  "Non ho capito": "I didn't understand",
  "Misuro il silenzio…": "Measuring the silence…",
  "Acceso": "On",
  "Di' «Ciro»": "Say “Ciro”",
  "Dimmi.": "Yes?",
  "Ascolto: «Ciro»": "Listening: “Ciro”",
  "Ascolto: sempre": "Listening: always",
  "Ciro risponde solo se lo chiami per nome (e per 15 secondi dopo che ha parlato). Premi per tenerlo sempre in ascolto.":
    "Ciro answers only when you call him by name (and for 15 seconds after he spoke). Press to keep him always listening.",
  "Ciro ascolta tutto. Premi per farlo rispondere solo quando lo chiami «Ciro».":
    "Ciro listens to everything. Press to make him answer only when you call him “Ciro”.",
  "Spento": "Off",
  "Accendi / spegni Ciro (S)": "Turn Ciro on / off (S)",
  "🎚 Calibra": "🎚 Calibrate",
  "Calibrazione guidata del microfono e della voce (circa 50 secondi)":
    "Guided calibration of the microphone and the voice (about 50 seconds)",
  "⏸ Pausa progetti": "⏸ Pause projects",
  "▶ Riprendi progetti": "▶ Resume projects",
  "Ciro smette di annunciare le domande delle sessioni (restano nel pannello)":
    "Ciro stops announcing the sessions' questions (they stay in the panel)",
  "Progetti in pausa": "Projects paused",
  " (parlano solo: %s)": " (only %s speak)",
  ". Premi per riprendere.": ". Press to resume.",
  "Passa all'inglese": "Switch to Italian",
  // start card, chat, subtitles
  "Ciao, sono Ciro": "Hi, I'm Ciro",
  "Chiamami per nome: «Ciro, …». Ti rispondo a voce.": "Call me by name: “Ciro, …”. I answer out loud.",
  "Serve il permesso del microfono.": "I need permission to use the microphone.",
  "Inizia": "Start",
  "Puoi anche scrivermi: tocca la A in basso a destra.": "You can also write to me: tap the A at the bottom right.",
  "Chat scritta": "Written chat",
  "Chiudi": "Close",
  "Scrivi e premi Invio": "Type and press Enter",
  "Invia": "Send",
  "Tu": "You",
  "Di' a %s: ": "Tell %s: ",
  "Ho sentito: ": "I heard: ",
  "In questo momento non riesco a pensare. Riprova tra un attimo.": "I can't think right now. Try again in a moment.",
  // spoken by the page
  "Eccomi, sono sveglio.": "Here I am, I'm awake.",
  "Sono qui, mi hai lasciato acceso.": "I'm here, you left me on.",
  "Ehi, ci sei? Sono ancora sveglio.": "Hey, are you there? I'm still awake.",
  "Ti ricordo che sono acceso: se non ti servo, spegnimi.": "Just a reminder that I'm on: if you don't need me, turn me off.",
  "È la prima volta che ci sentiamo: ti guido in una calibrazione di cinquanta secondi.":
    "This is the first time we talk: I'll guide you through a fifty-second calibration.",
  // left panel
  "Quanto ti resta": "What you have left",
  "Ti aspettano": "Waiting for you",
  "nessuno": "nobody",
  "nessuno: tutto in ordine": "nobody: all in order",
  "Clicca per rispondere a %s": "Click to answer %s",
  "domanda": "question",
  "posta": "mail",
  "decisione": "decision",
  "Sì": "Yes",
  "adesso": "now",
  "da %d min": "for %d min",
  "da %d h %d min": "for %d h %d min",
  "da %d g": "for %d d",
  "%d min fa": "%d min ago",
  "%d h fa": "%d h ago",
  "reset ora": "resets now",
  "reset tra %d min": "resets in %d min",
  "reset tra %d h %d min": "resets in %d h %d min",
  "reset tra %d g %d h": "resets in %d d %d h",
  "5 ore": "5 hours",
  "Settimana": "Week",
  "Credito": "Credit",
  "nessun dato ancora: apri una sessione Claude Code o installa l'estensione Chrome":
    "no data yet: open a Claude Code session or install the Chrome extension",
  "gli altri account Claude": "the other Claude accounts",
  "Mancano %s: arrivano dall'estensione Chrome, da installare nei profili del browser.":
    "Missing %s: they come from the Chrome extension, to install in the browser profiles.",
  // right panel
  "Sessioni": "Sessions",
  "nessuna sessione aperta": "no open sessions",
  "aspetta te": "waiting for you",
  "al lavoro": "working",
  "ferma": "idle",
  "comando in corso": "running a command",
  "cartella": "folder",
  // guide card and credential form
  "Ripeti": "Repeat",
  "Ferma": "Stop",
  "Resta in silenzio": "Stay silent",
  "Resta in silenzio… %d": "Stay silent… %d",
  "Di':": "Say:",
  "Ho sentito: «%s» %s": "I heard: «%s» %s",
  "Nome": "Name",
  "Valore": "Value",
  "Salva nel Portachiavi": "Save in the Keychain",
  "Credenziale per %s: %s": "Credential for %s: %s",
  "una sessione": "a session",
  "Salvo…": "Saving…",
  "Non salvata: %s. Riscrivila.": "Not saved: %s. Type it again.",
  "Il server non risponde. Riscrivila.": "The server is not answering. Type it again.",
  // waiting list in groups (19/11/2026)
  "Domande delle sessioni": "Session questions",
  "Urgenti in Google Chat": "Urgent in Google Chat",
  "%d non letto": "%d unread",
  "%d non letti": "%d unread",
  "%d spazio": "%d space",
  "%d spazi": "%d spaces",
  "con messaggi non letti: %s": "with unread messages: %s",
  "Clicca per vederli": "Click to show them",
  "urgente": "urgent",
  "Lettura non riuscita": "Read failed",
  "Scheda di Chat chiusa": "Chat tab closed",
};

// T("da %d min", 5): translation, then %s/%d replaced in order
function T(testo, ...valori) {
  let risultato = LINGUA === "en" && Object.prototype.hasOwnProperty.call(EN_UI, testo) ? EN_UI[testo] : testo;
  for (const valore of valori) risultato = risultato.replace(/%[sd]/, String(valore));
  return risultato;
}

function applicaLingua(lingua) {
  LINGUA = lingua === "en" ? "en" : "it";
  document.documentElement.lang = LINGUA;
  document.querySelectorAll("[data-t]").forEach((el) => { el.textContent = T(el.dataset.t); });
  document.querySelectorAll("[data-t-title]").forEach((el) => { el.title = T(el.dataset.tTitle); });
  document.querySelectorAll("[data-t-placeholder]").forEach((el) => { el.placeholder = T(el.dataset.tPlaceholder); });
  try { localStorage.setItem("ciro-lingua", LINGUA); } catch (errore) { /* solo per la prima schermata */ }
}

// the last language seen, so the first screen is right before the server answers
try { if (localStorage.getItem("ciro-lingua") === "en") applicaLingua("en"); } catch (errore) { /* italiano */ }
