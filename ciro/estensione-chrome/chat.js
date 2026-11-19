// Google Chat, in every Chrome profile: every 20 seconds sends Ciro the unread
// conversations of this profile (the full list: a conversation that is no
// longer there was read in Chat). Only on chat.google.com, only when the
// conversation list is on the page. It only reads.
"use strict";

// the signed-in address: the account button carries it in its label
function accountDellaPagina() {
  for (const el of document.querySelectorAll('[aria-label*="@"]')) {
    const trovato = (el.getAttribute("aria-label") || "").match(/[\w.+-]+@[\w-]+(?:\.[\w-]+)+/);
    if (trovato) return trovato[0].toLowerCase();
  }
  const utente = location.pathname.match(/\/u\/(\d+)/);
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

function manda() {
  const conversazioni = nonLetti();
  if (conversazioni === null) return;
  chrome.runtime.sendMessage({ tipo: "chat-non-letti", dato: { account: accountDellaPagina(), conversazioni } })
    .catch(() => {});
}

if (window.top === window && location.hostname === "chat.google.com") {
  setTimeout(manda, 5000);
  setInterval(manda, 20000);
}
