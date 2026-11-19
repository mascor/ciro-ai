---
name: stato-sessioni-claude
description: Mostra lo stato delle sessioni Claude Code aperte sul Mac (al lavoro, ferme, in attesa dell'utente) leggendo i file locali, senza usare modelli. Usala quando l'utente chiede lo stato, la situazione o cosa aspettano le sessioni Claude Code.
---

# Stato delle sessioni Claude Code

## Quando usarla

Quando l'utente chiede come stanno le sessioni Claude Code aperte sul Mac: quali lavorano, quali sono ferme, quali aspettano una sua risposta. Serve anche prima di rispondere a domande tipo "cosa devo fare adesso?" o "chi mi sta aspettando?". Non serve chiedere nulla a Claude: si leggono solo i file locali, senza consumare modelli.

## Comando da lanciare

```
python3 <ciro-ai>/stato/scripts/claude_stato.py
```

Con `--json` si ottengono gli stessi dati completi in formato JSON (utile per filtrare o contare). `--tutte` include anche le sessioni chiuse, `--watch 30` aggiorna ogni 30 secondi.

## Come leggere il risultato

Ogni riga è una sessione: SESSIONE (nome), PROGETTO, STATO, DA (da quanto è in quello stato), ASPETTA TE e POSTA. Lo stato può essere "al lavoro", "comando in corso" (sta eseguendo un comando), "ferma" o "chiusa". Claude Code però lascia lo status `shell` anche quando il turno è finito: se nella conversazione l'ultimo evento utile (user, assistant o system `turn_duration`) è un `turn_duration`, la sessione viene mostrata "ferma" come una idle, perché sta aspettando una risposta. In `--json` lo dice il campo `turno_finito`, mentre `stato_grezzo` resta il valore originale. ASPETTA TE vale "si" quando la sessione è ferma e ha qualcosa per l'utente, "attesa" quando ha attese ma nessuna sua, vuoto quando non ha attese. POSTA vale "si" se un processo `posta.py attendi --casella <progetto>` sta ascoltando la casella della sessione, "NO" se nessuno la ascolta e "?" se il controllo dei processi non è disponibile (per le sessioni chiuse è sempre "?"). In `--json` il campo corrispondente è `ascolta_posta` (vero, falso o null).

Sotto la riga compaiono le righe di dettaglio: `domanda:` è la domanda posta dalla sessione, `per te:` è una cosa che deve fare l'utente (spesso con il percorso del messaggio), `attesa:` è una cosa che aspetta qualcun altro (un collaboratore, un altro agente, un servizio).

## Cosa rispondere all'utente

Niente introduzioni né commenti. Usa SEMPRE questo formato markdown, con le righe vuote dove indicato (senza righe vuote l'app unisce tutto in un paragrafo):

### 🔴 Ti aspettano

| Sessione | Cosa devi fare |
|---|---|
| alpha-bot | autorizzare la prova email sul server Hermes (+2 altre) |
| echo | rispondere S/N sui limiti di Nginx |

### 🟡 Al lavoro
b2b-frontend, echo

### ⚪ Ferme
ironworks-jobs, tools

Regole: nella tabella metti SOLO le sessioni con aspetta_utente vero (ferme e con qualcosa per l'utente), una riga per sessione, nome senza il suffisso finale (alpha-bot-66 → alpha-bot), la cosa più importante in max 12 parole e "(+N altre)" se ce ne sono di più. Una sessione al lavoro non va nella tabella. Ometti le sezioni vuote; se nessuno aspetta, la prima riga è "✅ Nessuno ti aspetta". Se ci sono sessioni con POSTA = NO aggiungi in fondo "### ⚠ Non ascoltano la posta" con i nomi. Non riportare le attese che riguardano altre persone o agenti, salvo richiesta. Non inventare nulla che non sia nell'output; se l'output dice "(nessuna sessione viva)", rispondi solo "Nessuna sessione Claude aperta.". Per i dettagli l'utente chiede "dettagli di <sessione>".

## Limiti

Vede solo le sessioni Claude Code aperte su questo Mac. I server e gli agenti remoti compaiono solo se una sessione locale li segue via /remote-control. Riporta quello che le sessioni hanno scritto nei loro file: non verifica se è vero e non legge i messaggi citati.

## Regole

Non scrivere mai dentro `~/.claude` (lo script apre quei file in sola lettura). Non mandare messaggi alle sessioni e non toccare il loro stato. Non eseguire `launchctl` e non installare il LaunchAgent: al massimo spiega i comandi descritti nel README del progetto.

## Variabili di controllo

Non aggiungerle alla risposta all'utente. Usale solo se lo stato ti è stato chiesto da un altro agente:

```
sessioni_vive: <numero>
sessioni_che_aspettano_utente: <nomi, o "nessuna">
sessioni_al_lavoro: <nomi, o "nessuna">
problemi: <elenco o "nessuno">
```
