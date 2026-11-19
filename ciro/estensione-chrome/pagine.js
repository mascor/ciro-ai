// Lettori del testo delle pagine dei consumi di OpenCode Go e DeepSeek.
// Usati sia dentro le schede aperte sia dallo sfondo dell'estensione.
"use strict";

function numero(testo) {
  return testo == null ? null : Number(String(testo).replace(",", "."));
}

function leggiOpenCodeGo(testo) {
  const voci = [];
  for (const [etichetta, nome] of [["5-hour window", "5 ore"], ["Weekly", "Settimana"], ["Monthly", "Mese"]]) {
    const trovato = new RegExp(etichetta + "\\s*(\\d+(?:[.,]\\d+)?)%\\s*used[\\s\\S]*?Resets in ([^\\n]+)").exec(testo);
    if (trovato) voci.push({ nome, percentuale: numero(trovato[1]), reset: "tra " + trovato[2].trim() });
  }
  if (!voci.length) return null;
  const credito = /\$\s?([\d.,]+)\s*available credit/i.exec(testo);
  return {
    fonte: "opencode-go",
    account: "abbonamento",
    voci,
    saldo: credito ? "$" + credito[1] : null,
  };
}

function leggiDeepSeek(testo) {
  const saldo = /Topped-up balance[\s\S]*?\$\s?([\d.,]+)/i.exec(testo);
  if (!saldo) return null;
  const totale = /Total cost[\s\S]*?\$\s?([\d.,]+)/i.exec(testo);
  return {
    fonte: "deepseek",
    account: "API",
    voci: [],
    saldo: "$" + saldo[1],
    nota: totale ? "Spesa totale: $" + totale[1] : null,
  };
}
