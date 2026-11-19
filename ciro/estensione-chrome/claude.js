// Lettura dei limiti d'uso degli account claude.ai collegati nel profilo.
// Usata dallo sfondo dell'estensione e, come riserva, dentro le schede di
// claude.ai aperte (li' l'accesso e' sicuramente attivo).
"use strict";

const NOMI_LIMITI_CLAUDE = { five_hour: "5 ore", seven_day: "Settimana" };

function nomeAccountClaude(org) {
  return (org.name || org.uuid || "?").replace(/'s Organization$/i, "");
}

async function leggiClaude(manda) {
  const base = "https://claude.ai";
  const risposta = await fetch(base + "/api/organizations", { credentials: "include" });
  if (!risposta.ok) throw new Error("organizzazioni: HTTP " + risposta.status);
  const organizzazioni = await risposta.json();
  for (const org of organizzazioni || []) {
    const capacita = org.capabilities || [];
    if (capacita.length && !capacita.includes("chat")) continue; // org solo API
    try {
      const r = await fetch(`${base}/api/organizations/${org.uuid}/usage`, { credentials: "include" });
      if (!r.ok) throw new Error("HTTP " + r.status);
      const uso = await r.json();
      const voci = [];
      for (const [chiave, nome] of Object.entries(NOMI_LIMITI_CLAUDE)) {
        const valore = uso && uso[chiave];
        if (valore && valore.utilization != null) {
          voci.push({ nome, percentuale: valore.utilization, reset: valore.resets_at || "" });
        }
      }
      let nota = null;
      const extra = uso && uso.extra_usage;
      if (extra && extra.is_enabled) {
        const euro = (c) => (c == null ? "?" : "€" + (c / 100).toFixed(2).replace(".", ","));
        nota = `Extra del mese: ${euro(extra.used_credits)} su ${euro(extra.monthly_limit)}`;
      }
      if (voci.length || nota) manda({ fonte: "claude.ai", account: nomeAccountClaude(org), voci, nota });
    } catch (errore) {
      console.warn("faccia: consumi non leggibili per", org.name, errore);
    }
  }
}
