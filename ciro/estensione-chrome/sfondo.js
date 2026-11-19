// Faccia - consumi: ogni 5 minuti legge i limiti d'uso degli account claude.ai
// del profilo e li manda a Ciro sul Mac. Riceve anche i dati letti dalle
// schede aperte (claude.ai, OpenCode Go, DeepSeek).
// Usa solo l'accesso gia' attivo nel browser: non salva password ne' cookie.
"use strict";
importScripts("claude.js", "pagine.js");

const FACCIA = "http://127.0.0.1:8765/api/consumi";

async function mandaAllaFaccia(dato) {
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
  leggiClaude(mandaAllaFaccia).catch((errore) =>
    console.warn("claude.ai dallo sfondo non leggibile (ci pensano le schede aperte)", errore)
  );
  leggiPagineDaSolo().catch((errore) => console.warn("pagine dei consumi", errore));
}

chrome.runtime.onMessage.addListener((messaggio) => {
  if (!messaggio || messaggio.tipo !== "consumo" || !messaggio.dato) return;
  mandaAllaFaccia(messaggio.dato);
  if (messaggio.dato.fonte === "opencode-go" && /\/go\b/.test(messaggio.indirizzo || "")) {
    chrome.storage.local.set({ indirizzoGo: messaggio.indirizzo });
  }
});

chrome.alarms.create("claude", { periodInMinutes: 5 });
chrome.alarms.onAlarm.addListener((allarme) => {
  if (allarme.name === "claude") giro();
});
chrome.runtime.onStartup.addListener(giro);
chrome.runtime.onInstalled.addListener(giro);
