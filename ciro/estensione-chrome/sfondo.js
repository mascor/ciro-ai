// Ciro Agente: ogni 5 minuti legge i limiti d'uso degli account claude.ai
// del profilo e li manda a Ciro sul Mac. Riceve anche i dati letti dalle
// schede aperte (claude.ai, OpenCode Go, DeepSeek).
// Usa solo l'accesso gia' attivo nel browser: non salva password ne' cookie.
"use strict";
importScripts("claude.js", "pagine.js");

const FACCIA = "http://127.0.0.1:8765/api/consumi";

// via (issue #6): "sfondo" se l'ha letto questo service worker, "scheda" se viene da una scheda aperta
async function mandaAllaFaccia(dato, via = "sfondo") {
  dato = { ...dato, via };
  try {
    await fetch(FACCIA, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(dato),
    });
  } catch (errore) {
    console.warn("faccia non raggiungibile", errore);
  }
}

function testoDaHtml(html) {
  return html
    .replace(/<style[\s\S]*?<\/style>/gi, " ")
    .replace(/<[^>]+>/g, "\n")
    .replace(/&nbsp;/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/\n\s*\n+/g, "\n");
}

// OpenCode Go: riscarica da solo la pagina Go (l'indirizzo lo ha dato la
// scheda l'ultima volta). Se la pagina non porta i numeri, ricarico le schede
// aperte di OpenCode e DeepSeek, cosi' i numeri restano freschi.
async function leggiPagineDaSolo() {
  let riuscito = false;
  const { indirizzoGo } = await chrome.storage.local.get("indirizzoGo");
  if (indirizzoGo) {
    try {
      const risposta = await fetch(indirizzoGo, { credentials: "include" });
      const dato = risposta.ok ? leggiOpenCodeGo(testoDaHtml(await risposta.text())) : null;
      if (dato) {
        await mandaAllaFaccia(dato);
        riuscito = true;
      }
    } catch (errore) {
      console.warn("OpenCode Go non leggibile dallo sfondo", errore);
    }
  }
  const schede = await chrome.tabs.query({
    url: riuscito
      ? ["https://platform.deepseek.com/usage*"]
      : ["https://opencode.ai/console/*", "https://platform.deepseek.com/usage*"],
  });
  for (const scheda of schede) chrome.tabs.reload(scheda.id).catch(() => {});
}

function giro() {
  leggiClaude((dato) => mandaAllaFaccia(dato, "sfondo")).catch((errore) =>
    console.warn("claude.ai dallo sfondo non leggibile (ci pensano le schede aperte)", errore)
  );
  leggiPagineDaSolo().catch((errore) => console.warn("pagine dei consumi", errore));
}

// Google Chat: i non letti di ogni scheda di Chat vanno a Ciro
const CIRO_CHAT = { "chat-non-letti": "http://127.0.0.1:8765/api/chat/non-letti",
                    "calendario-eventi": "http://127.0.0.1:8765/api/calendario/eventi" };
chrome.runtime.onMessage.addListener((messaggio) => {
  const indirizzo = messaggio && CIRO_CHAT[messaggio.tipo];
  if (!indirizzo || !messaggio.dato) return;
  fetch(indirizzo, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(messaggio.dato),
  }).catch((errore) => console.warn("Ciro non raggiungibile (chat)", errore));
});

chrome.runtime.onMessage.addListener((messaggio) => {
  if (!messaggio || messaggio.tipo !== "consumo" || !messaggio.dato) return;
  mandaAllaFaccia(messaggio.dato, "scheda");
  if (messaggio.dato.fonte === "opencode-go" && /\/go\b/.test(messaggio.indirizzo || "")) {
    chrome.storage.local.set({ indirizzoGo: messaggio.indirizzo });
  }
});

// issue #56: se nella cartella c'e' una versione nuova dell'estensione, mi ricarico da solo
const CIRO_ESTENSIONE = "http://127.0.0.1:8765/api/estensione";
async function aggiornaSeServe() {
  try {
    const risposta = await fetch(CIRO_ESTENSIONE);
    if (!risposta.ok) return;
    const { versione } = await risposta.json();
    if (!versione || versione === chrome.runtime.getManifest().version) return;
    // un solo tentativo per versione: se l'estensione e' caricata da un'altra
    // cartella, ricaricarla non cambia niente e non deve ricaricarsi all'infinito
    const { ricaricataPer } = await chrome.storage.local.get("ricaricataPer");
    if (ricaricataPer === versione) return;
    await chrome.storage.local.set({ ricaricataPer: versione });
    console.info("Ciro Agente: nuova versione", versione, "- mi ricarico");
    chrome.runtime.reload();
  } catch (errore) {
    console.warn("Ciro non raggiungibile (versione)", errore);
  }
}

// issue #55: il service worker riparte a ogni messaggio delle schede; ricreare
// l'allarme ogni volta ne faceva ripartire il conto e la lettura non arrivava mai
chrome.alarms.get("claude", (allarme) => {
  if (!allarme) chrome.alarms.create("claude", { periodInMinutes: 5 });
});
chrome.alarms.onAlarm.addListener((allarme) => {
  if (allarme.name !== "claude") return;
  giro();
  aggiornaSeServe();
});
chrome.runtime.onStartup.addListener(() => { giro(); aggiornaSeServe(); });
// issue #56: dopo un aggiornamento le schede gia' aperte non parlano piu' con
// l'estensione nuova: ricarico quelle di Google Chat (i consumi li legge lo sfondo)
async function ricaricaSchedeChat() {
  const schede = await chrome.tabs.query({
    url: ["https://chat.google.com/*", "https://mail.google.com/chat/*", "https://calendar.google.com/*"],
  });
  for (const scheda of schede) chrome.tabs.reload(scheda.id).catch(() => {});
}

chrome.runtime.onInstalled.addListener((dettagli) => {
  giro();
  if (dettagli.reason === "update") ricaricaSchedeChat().catch((errore) => console.warn("schede di Chat", errore));
});
