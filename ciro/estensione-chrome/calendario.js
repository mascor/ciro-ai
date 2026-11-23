// Google Calendar, in every Chrome profile: every 30 seconds sends Ciro the event chips of the
// open view (id, label, colour). Ciro keeps only the red ones (Tomato) and says them from
// 30 minutes before the start (#70). It only reads.
"use strict";

function accountDellaPagina() {
  for (const el of document.querySelectorAll('[aria-label*="@"]')) {
    const trovato = (el.getAttribute("aria-label") || "").match(/[\w.+-]+@[\w-]+(?:\.[\w-]+)+/);
    if (trovato) return trovato[0].toLowerCase();
  }
  const utente = location.pathname.match(/\/u\/(\d+)/);
  return "calendario-" + (utente ? utente[1] : "0");
}

// the chip colour: the first background that is not transparent, on the chip or inside it
function colore(el) {
  for (const nodo of [el, ...el.querySelectorAll("*")].slice(0, 12)) {
    const sfondo = getComputedStyle(nodo).backgroundColor;
    if (sfondo && sfondo !== "transparent" && !/rgba\(\s*0,\s*0,\s*0,\s*0\s*\)/.test(sfondo)) return sfondo;
    const bordo = getComputedStyle(nodo).borderLeftColor;   // some views mark the colour with a border
    if (nodo !== el && bordo && /rgb\(/.test(bordo) && getComputedStyle(nodo).borderLeftWidth !== "0px") return bordo;
  }
  return "";
}

function eventi() {
  const visti = new Set();
  const elenco = [];
  for (const el of document.querySelectorAll("[data-eventid]")) {
    const id = el.getAttribute("data-eventid");
    if (!id || visti.has(id)) continue;
    visti.add(id);
    // the label carries time, title and date; the visible text is the fallback
    const etichetta = (el.getAttribute("aria-label") || el.querySelector("[aria-label]")?.getAttribute("aria-label")
                       || el.innerText || "").replace(/\s+/g, " ").trim().slice(0, 400);
    if (etichetta) elenco.push({ id, testo: etichetta, colore: colore(el) });
    if (elenco.length >= 200) break;
  }
  return elenco;
}

function manda() {
  if (window.top !== window) return;
  const elenco = eventi();
  if (!elenco.length && !document.querySelector('[role="main"]')) return;   // page not loaded yet
  chrome.runtime.sendMessage({ tipo: "calendario-eventi",
    dato: { account: accountDellaPagina(), eventi: elenco, ora_pagina: Date.now() } }).catch(() => {});
}

setTimeout(manda, 5000);
setInterval(manda, 30000);
