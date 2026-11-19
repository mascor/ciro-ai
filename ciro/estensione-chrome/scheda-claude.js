// Dentro una scheda di claude.ai: rilegge i limiti ogni 5 minuti e li passa
// allo sfondo dell'estensione. Serve se la lettura dallo sfondo non riesce.
"use strict";

function mandaDallaScheda(dato) {
  chrome.runtime.sendMessage({ tipo: "consumo", dato }).catch(() => {});
}

function giroScheda() {
  leggiClaude(mandaDallaScheda).catch((errore) => console.warn("faccia: claude.ai non leggibile", errore));
}

setTimeout(giroScheda, 3000);
setInterval(giroScheda, 5 * 60 * 1000);
