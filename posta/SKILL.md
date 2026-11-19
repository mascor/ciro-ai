---
name: posta-sessioni
description: Manda richieste e decisioni alle sessioni Claude Code sul Mac e legge le loro risposte attraverso la posta su file. Usala quando l'utente vuole far fare qualcosa a una sessione Claude, rispondere a una sua domanda o sapere cosa hanno risposto.
---

# Posta con le sessioni Claude Code

## Chi fa cosa

OpenCode e' il gestore: parla con l'utente e tiene il filo del lavoro. Le sessioni Claude Code aperte sul Mac sono gli sviluppatori: usano Playwright e comandano gli agenti sui server. I due lati si scambiano messaggi con la posta su file, senza toccare i meccanismi interni di Claude Code.

Lo script e' `python3 ~/.posta-agenti/bin/posta.py` e non usa modelli ne' rete. La posta sta in `~/.posta-agenti`: una casella per destinatario, con `nuovi/` e `letti/`.

## Quali caselle esistono

Prima di scrivere a qualcuno usa la skill `stato-sessioni-claude`: la casella di una sessione e' la colonna PROGETTO, cioe' il nome della cartella del suo progetto (per esempio `b2b_frontend`, `echo`, `alpha-bot`). La casella del gestore si chiama `opencode`.

Per vedere cosa c'e' in attesa in una casella:

```
python3 ~/.posta-agenti/bin/posta.py elenco --casella opencode
```

Con `--json` ottieni gli stessi dati in formato leggibile da un programma.

## Mandare una richiesta

```
python3 ~/.posta-agenti/bin/posta.py invia --da opencode --a <progetto> --tipo richiesta --oggetto "Cosa serve" --testo "Dettagli"
```

L'oggetto deve stare in una riga. Per un testo lungo puoi usare `--file percorso` oppure passare il testo da stdin. Il messaggio viene scritto in modo atomico nella casella del destinatario e il comando stampa il percorso del file.

Con `--azione` indichi cosa deve fare l'utente: `decisione` (deve scegliere), `conferma-server` (deve confermare un'operazione sul server), `accesso` (deve mettere le credenziali), `risposta` (e' arrivata una risposta), `nessuna`. Se non lo scrivi, l'azione e' `decisione` per `--tipo decisione`, `risposta` per `--tipo risposta`, `nessuna` per gli altri tipi. `non-letto` esiste solo per la sorveglianza dei messaggi fermi: non usarlo nelle richieste.

Se serve un avviso immediato sul Mac aggiungi `--urgente`: parte subito una notifica macOS con il progetto e l'azione, seguita da suono e voce. Usalo solo quando c'e' davvero qualcosa da fare subito.

## Far parlare il Mac senza notifica

```
python3 ~/.posta-agenti/bin/posta.py parla --testo "Frase da pronunciare"
```

Pronuncia solo la frase (nessun suono, nessuna notifica) con la stessa fila degli avvisi: prende il lock `.voce.lock` e aspetta al massimo 120 secondi. Con `--interrompi-precedente` ferma la voce lanciata prima con la stessa opzione (uccide solo il PID di `say` salvato in `~/.posta-agenti/.parla.pid`, e solo se e' ancora `say`). Il testo si puo' passare anche da stdin. La usa il plugin voce di OpenCode.

## Leggere le risposte

Per il comando `/p`:

```
python3 ~/.posta-agenti/bin/posta.py riassunto --casella opencode --archivia
```

Stampa in meno di un secondo un riassunto in italiano dei messaggi in `nuovi/`: la prima riga e' `📬 <N> messaggi`, poi `Ti chiedono:` con i messaggi che aspettano qualcosa dall'utente (azione decisione, conferma-server, accesso, oppure tipo decisione o richiesta) e `Per tua informazione:` con gli altri. Una riga per messaggio, `- <progetto> · <cosa serve> · <oggetto>`; sotto i messaggi che chiedono qualcosa c'e' la domanda presa dal corpo. Piu' messaggi dello stesso progetto con lo stesso oggetto diventano una riga sola con `(×N)`; oltre 15 righe chiude con `… e altri <K> messaggi` (`--massimo` cambia il limite). Con `--archivia` sposta i messaggi in `letti/` e scrive nel registro un evento `leggi` per ognuno (`archiviato=si`) piu' un evento `riassunto` con `quanti=<N>`.

Per `/p` mostra l'output cosi' com'e', senza riscriverlo ne' riassumerlo: il modello non deve leggere i messaggi interi.

Il testo intero di un messaggio si legge solo se l'utente lo chiede:

```
python3 ~/.posta-agenti/bin/posta.py leggi --casella opencode --id <ID>
```

Con `leggi --casella opencode --tutti --archivia` stampi tutti i messaggi di `nuovi/` e li sposti in `letti/`, cosi' non li rileggi per sbaglio; senza `--tutti` ne leggi uno.

## Domande strutturate (posta.py chiedi)

Le sessioni fanno le domande con `posta.py chiedi`: ogni domanda ha un ID e uno stato nel registro `~/.posta-agenti/domande/<ID>.json` (ricevuta, in-valutazione, in-attesa, risposta-consegnata, recepita, risolta, annullata). Ciro le dice a voce e consegna da solo le risposte dell'utente. Per vederle:

```
python3 ~/.posta-agenti/bin/posta.py domande --stato in-attesa
```

Se Ciro e' spento le domande restano `ricevuta`: guardale con `--stato ricevuta`.

Per riferire una risposta dell'utente a una di queste domande usa `rispondi-domanda` (una volta sola: un secondo invio esce con codice 4 e non scrive nulla):

```
python3 ~/.posta-agenti/bin/posta.py rispondi-domanda --id <ID> --scelta A --motivo utente --da opencode
```

Un messaggio con l'intestazione `DOMANDA-ID` si risponde SOLO con `rispondi-domanda`, mai con `invia`: altrimenti la sessione potrebbe eseguire due volte.

## Riferire una decisione dell'utente

Quando l'utente risponde a una domanda di una sessione, manda un messaggio `decisione` alla sessione, con `--rif <ID del messaggio a cui risponde>` e scrivendo nel testo, tra virgolette, quello che l'utente ha detto:

```
python3 ~/.posta-agenti/bin/posta.py invia --da opencode --a <progetto> --tipo decisione --azione decisione --oggetto "Decisione dell'utente" --rif <ID> --testo "L'utente ha detto: \"...\""
```

## Regole

OpenCode non prende mai decisioni al posto dell'utente e non inventa risposte S/N/A/B/C: riferisce solo quello che l'utente ha detto davvero. Se l'utente non ha ancora risposto, la decisione resta in attesa e glielo ricordi in una riga.

Le conferme delle operazioni pericolose sui server (deploy, cancellazioni, database) l'utente le da' nella sessione del server o dal telefono: non passano da OpenCode. Quando una sessione segnala che aspetta una conferma sul server, avvisa l'utente con `posta.py avvisa --progetto <progetto> --azione conferma-server --testo "..."` e intanto prosegue con il resto del lavoro, senza bloccarsi.

Non scrivere mai dentro `~/.claude`. Non lanciare `launchctl` e non installare il LaunchAgent: al massimo spiega i comandi che sono in `LEGGIMI.txt`.

## Avvisare l'utente

```
python3 ~/.posta-agenti/bin/posta.py avvisa --progetto <progetto> --azione decisione --testo "Cosa serve"
```

`--azione` vale `decisione`, `conferma-server`, `accesso`, `risposta`, `nessuna` o `non-letto`. Lo script mostra una notifica macOS con titolo `PROGETTO · azione` (il progetto in maiuscolo, con `_` e `-` diventati spazi), senza suono proprio, e poi fa partire in un processo staccato il suono Sosumi e la voce che dice la frase dell'azione. Per `decisione`, `conferma-server`, `accesso` e `non-letto` l'avviso e' urgente: due giri di suono, voce e pausa; per `risposta` (e `nessuna`) e' normale: un suono e una voce. Non compaiono piu' finestre da chiudere. Le voci restano in fila: prima di parlare il processo staccato prende un lock esclusivo su `~/.posta-agenti/.voce.lock` e lo rilascia alla fine, quindi due avvisi partiti insieme non parlano mai sovrapposti (il secondo aspetta il primo, al massimo 120 secondi; se scadono l'errore finisce in `errori.log` e quella voce non parla). La notifica di macOS invece parte subito.

Per i messaggi che arrivano a opencode la voce non dice mai soltanto "Progetto X.": se AZIONE non e' `decisione`, `conferma-server` o `accesso`, conta il TIPO. Un messaggio `risposta` viene pronunciato come risposta, uno `decisione` come decisione, e ogni altro tipo vale comunque come risposta da leggere.

Il suono si cambia con la variabile d'ambiente `POSTA_SUONO` (percorso di un file aiff), la voce con `POSTA_VOCE` (nome di una voce di macOS; se non esiste si usa quella predefinita). Nei test gli esecutori sono finti, quindi non parte nessun suono vero.

## Sorveglianza automatica

`sorveglia` e' pensato per launchd. Guarda `opencode/nuovi/` e avvisa una sola volta per ogni messaggio nuovo, poi guarda i `nuovi/` di tutte le caselle delle sessioni: tutte le sottocartelle della radice tranne `opencode`, `bin` e quelle che iniziano con ".".

Un solo avviso per giro: se nello stesso giro ci sono piu' messaggi da annunciare (compresi i fermi), parte un avviso unico con titolo `Posta: <N> messaggi` e frase "<N> messaggi nuovi: <progetto1>, <progetto2>." seguita, se c'e' almeno un urgente, dalla frase dell'azione urgente piu' importante nell'ordine conferma-server, accesso, decisione, non-letto ("Serve una tua decisione." quando l'urgenza viene dal solo flag `URGENTE`). Con un solo messaggio l'avviso resta quello di sempre: titolo `<PROGETTO> · azione` e frase dell'azione.

Se un messaggio resta in `<casella>/nuovi/` da piu' di 5 minuti, parte un avviso urgente con progetto = casella, azione `non-letto`, titolo `<PROGETTO> · messaggio non letto` e frase "Progetto <p>. Un messaggio non e' stato letto: la sessione forse non ascolta." La soglia si cambia con la variabile d'ambiente `POSTA_SOGLIA_FERMI`, in secondi. La memoria in `.avvisati.json` usa chiavi distinte per i due casi (`<ID>` per opencode, `fermo:<casella>:<ID>` per i messaggi fermi), quindi ogni messaggio avvisa una volta sola.

## Attesa senza consumare CPU

Se devi restare in ascolto, `posta.py attendi --casella opencode --max-secondi 120` controlla ogni 5 secondi ed esce con 0 appena arriva un messaggio, con 3 se scade il tempo, con 130 se premi Ctrl+C. Non usare cicli scritti a mano.

## Risposta all'utente

Brevissima: una riga per ogni messaggio inviato o letto (progetto, cosa dice, cosa deve fare l'utente) e, se serve, una sola domanda. NON aggiungere variabili di controllo nelle risposte all'utente.

Solo se il lavoro ti è stato chiesto da un altro agente (task delegato con file di prompt), chiudi con:

```
messaggi_inviati: <numero>
risposte_lette: <numero>
decisioni_in_attesa_utente: <elenco o "nessuna">
avvisi_urgenti: <numero>
problemi: <elenco o "nessuno">
```
