// Dentro le schede di OpenCode Go e DeepSeek: legge i numeri della pagina e
// li passa allo sfondo dell'estensione, insieme all'indirizzo della pagina
// (cosi' lo sfondo puo' rileggerla da solo anche a scheda chiusa).
"use strict";

function leggi() {
  const testo = document.body ? document.body.innerText : "";
  const dato = location.hostname === "opencode.ai" ? leggiOpenCodeGo(testo) : leggiDeepSeek(testo);
  if (dato) chrome.runtime.sendMessage({ tipo: "consumo", dato, indirizzo: location.href }).catch(() => {});
}

setTimeout(leggi, 2500);
setInterval(leggi, 60000);
