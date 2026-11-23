// Google Chat, in every Chrome profile: every 20 seconds sends Ciro the unread
// conversations of this profile (the full list: a conversation that is no
// longer there was read in Chat). Only on chat.google.com, only when the
// conversation list is on the page. It only reads.
"use strict";

// the signed-in address: the account button carries it in its label. The page does
// not always show it (19/11/2026: the list arrived as "profilo-0" and the old list of
// the real address stayed in Ciro), so the last address seen for this /u/N is kept
// in the extension storage and used when the page does not show it.
async function accountDellaPagina() {
  const utente = location.pathname.match(/\/u\/(\d+)/);
  const chiave = "chat-account-u" + (utente ? utente[1] : "0");
  for (const el of document.querySelectorAll('[aria-label*="@"]')) {
    const trovato = (el.getAttribute("aria-label") || "").match(/[\w.+-]+@[\w-]+(?:\.[\w-]+)+/);
    if (trovato) {
      const indirizzo = trovato[0].toLowerCase();
      try { await chrome.storage.local.set({ [chiave]: indirizzo }); } catch {}
      return indirizzo;
    }
  }
  try {
    const salvato = (await chrome.storage.local.get(chiave))[chiave];
    if (salvato) return salvato;
  } catch {}
  return "profilo-" + (utente ? utente[1] : "0");
}

function nonLetti() {
  const elenco = document.querySelectorAll('span[role="listitem"][data-group-id]');
  if (!elenco.length) return null;   // not the Chat app (or not loaded yet): send nothing
  const conversazioni = [];
  for (const el of elenco) {
    if (el.getAttribute("data-is-unread") !== "true") continue;
    conversazioni.push({
      conversazione: el.getAttribute("data-group-id"),
      righe: (el.innerText || "").split("\n").map((r) => r.trim()).filter(Boolean).slice(0, 12),
    });
  }
  return conversazioni;
}

// when the list is not found: only counts of page elements, never any text,
// so Ciro can tell where the conversations are (sent once a minute, top page only)
let ultimaDiagnosi = 0;
function diagnosi() {
  const conta = (selettore) => document.querySelectorAll(selettore).length;
  return {
    pagina: location.hostname + location.pathname.replace(/\/[^/]{12,}/g, "/…"),
    cornice: window.top === window ? "principale" : "interna",
    gruppi: conta("[data-group-id]"),
    gruppi_span: conta("span[data-group-id]"),
    gruppi_div: conta("div[data-group-id]"),
    non_letti_attr: conta('[data-is-unread="true"]'),
    aria_non_letto: conta('[aria-label*="non lett" i],[aria-label*="unread" i]'),
    listitem: conta('[role="listitem"]'),
    treeitem: conta('[role="treeitem"]'),
    iframe: conta("iframe"),
  };
}

async function manda() {
  const conversazioni = nonLetti();
  if (conversazioni === null) {
    if (Date.now() - ultimaDiagnosi < 60000) return;
    ultimaDiagnosi = Date.now();
    chrome.runtime.sendMessage({ tipo: "chat-non-letti",
      dato: { account: await accountDellaPagina(), conversazioni: null, diagnosi: diagnosi() } }).catch(() => {});
    return;
  }
  chrome.runtime.sendMessage({ tipo: "chat-non-letti", dato: { account: await accountDellaPagina(), conversazioni } })
    .catch(() => {});
}

// every Chat page and frame, also Chat inside Gmail
setTimeout(manda, 5000);
setInterval(manda, 20000);
