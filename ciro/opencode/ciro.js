// Ciro connect for OpenCode (docs/hooks-design.md, phase 2).
// When a session asks for a permission ("permission.asked"), Ciro asks the user
// by voice; the user's answer goes back with the permission reply. The prompt
// stays in the OpenCode terminal too: whoever answers first wins, and an answer
// given in the terminal closes Ciro's question ("permission.replied").
// Loaded by OpenCode 2.x as { id, setup }. ES module, no dependencies.
// Installed by: python3 ciro/strumenti/collega.py connect-opencode

import { appendFileSync } from "node:fs"
import { homedir } from "node:os"
import { join } from "node:path"

const CIRO = "http://127.0.0.1:8765"
const ATTESA_MS = 75000 // Ciro waits for the user 60 s (at most 70)
const LOG = join(homedir(), ".config", "opencode", "ciro.log")

function scriviLog(testo) {
  try {
    appendFileSync(LOG, `${new Date().toISOString()} ${testo}\n`)
  } catch {}
}

async function chiama(percorso, dati, ms) {
  const controllo = new AbortController()
  const timer = setTimeout(() => controllo.abort(), ms)
  try {
    const risposta = await fetch(CIRO + percorso, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(dati),
      signal: controllo.signal,
    })
    const testo = await risposta.text()
    return testo ? JSON.parse(testo) : null
  } finally {
    clearTimeout(timer)
  }
}

export const CiroPlugin = {
  id: "ciro",
  async setup(ctx) {
    // in "opencode run" (delegated tasks) nothing: no voice questions, and the
    // subscription would keep the process from exiting
    if (process.argv.slice(1, 4).includes("run")) return () => {}
    let attivo = true
    const chieste = new Set() // requestIDs Ciro is asking about

    async function chiesto(richiesta) {
      if (!richiesta?.id || chieste.has(richiesta.id)) return
      chieste.add(richiesta.id)
      try {
        let titolo = ""
        let cartella = ""
        try {
          const sessione = await ctx.session.get({ sessionID: richiesta.sessionID })
          const dati = sessione?.data ?? sessione
          titolo = typeof dati?.title === "string" ? dati.title : ""
          cartella = typeof dati?.directory === "string" ? dati.directory : ""
        } catch {}
        const esito = await chiama("/hooks/opencode", {
          requestID: richiesta.id,
          sessionID: richiesta.sessionID,
          permission: richiesta.permission,
          patterns: richiesta.patterns,
          title: titolo,
          directory: cartella || process.cwd(),
        }, ATTESA_MS)
        const risposta = esito?.reply
        if (risposta !== "once" && risposta !== "reject") return // nothing: the terminal prompt stays
        const permessi = ctx.permission ?? ctx.client?.permission
        if (!permessi?.reply) throw new Error("permission.reply non disponibile in questa versione di OpenCode")
        await permessi.reply({ requestID: richiesta.id, reply: risposta,
          ...(risposta === "reject" ? { message: "Negato dall'utente tramite Ciro." } : {}) })
        scriviLog(`risposta ${risposta} a ${richiesta.id}`)
      } catch (errore) {
        scriviLog(`errore: ${errore?.message ?? errore}`)
      } finally {
        chieste.delete(richiesta.id)
      }
    }

    async function risposto(dati) {
      if (!dati?.requestID || !chieste.has(dati.requestID)) return
      try {
        await chiama("/hooks/opencode/risposto", { requestID: dati.requestID }, 5000)
      } catch {}
    }

    // one subscription per event type (OpenCode 2.x events carry their fields in .data)
    function ascolta(tipo, gestisci) {
      try {
        const flusso = ctx.event.subscribe({ types: [tipo] })
        ;(async () => {
          try {
            for await (const evento of flusso) {
              if (!attivo) break
              gestisci(evento?.data ?? evento?.properties)
            }
          } catch (errore) {
            scriviLog(`flusso ${tipo} interrotto: ${errore?.message ?? errore}`)
          }
        })()
      } catch (errore) {
        scriviLog(`errore sottoscrizione ${tipo}: ${errore?.message ?? errore}`)
      }
    }
    ascolta("permission.asked", chiesto)
    ascolta("permission.replied", risposto)
    scriviLog("plugin ciro caricato")
    return () => {
      attivo = false
    }
  },
}

export default CiroPlugin
