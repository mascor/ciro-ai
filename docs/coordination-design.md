# Coordination with Ciro: structured questions, rules and complete cycle

Date: 18/11/2026. Proposal pasted by the user; choices made in conversation:
- rules on work choices and test deploys (B);
- for work choices the model evaluates, for test deploys an exact match is needed (B);
- the current mail is extended (A).

## Why

The group is: **User ↔ Ciro ↔ developer of each project (Claude Code session on the Mac) ↔ agent on the server**.

Today the sessions ask questions by mail in free text and Ciro reports them. Three things are missing:
- knowing which precise question a «sì» ("yes") answers;
- avoiding double executions;
- knowing whether the work has restarted.

The user wants Ciro to follow the whole picture, to settle by itself the questions already covered by its rules, to involve him only for the rest and to interrupt him only when needed. Only afterwards, the 3D avatar (plan in `faccia/docs/superpowers/plans/2026-11-18-ciro-3d.md`) will show these real states.

## the user's priority: responsiveness

«A me basta che Ciro sia reattivo e veloce: non mi deve far perdere tempo.» ("I only need Ciro to be responsive and fast: it must not make me waste time.") This applies above any other objective:
- **New questions:** Ciro says the question within 5 s from the `chiedi` command (check of the log every 2 s, only one file read, no model).
- **Answers:** the user's answer («A», «sì») leaves at once, without another confirmation, and Ciro says «Mandato» ("Sent") within 1 s. No call to the model on this path.
- **Evaluation of preferences:** the model works in the background and never blocks the conversation.
- **Silence:** Ciro speaks only when a decision from the user is needed or there is a serious problem, always in one sentence. No service questions, no voice summaries if there is nothing new.
- **Code:** for the same result, the simplest and fastest solution wins.

## Objectives (first version)

1. A complete and reliable cycle on the Mac: question from the session → evaluation of the rules → possible question to the user → delivery of the answer → confirmation that the session has restarted → risolta.
2. Structured questions with a unique identifier and a tracked state.
3. Rules learned by talking with Ciro:
   - a «sì» ("yes") is worth one operation only;
   - a permanent rule is born only when the user states it explicitly.
4. Automatic answers:
   - **work choices:** when a saved preference covers the question (the model evaluates), Ciro answers and warns at once;
   - **test deploys:** only with a rule that matches exactly.
5. No double execution, not even with duplicated messages or restarts.
6. Credentials entered in a protected field, saved in the Keychain, never pronounced, written in the logs or put in the mail.
7. Selective updates: at once for decisions and serious problems; a summary every 30 minutes only if there is news, changeable by voice.

## Non-objectives (first version)

- SSH connection with the agent on the server: it comes later, when the cycle on the Mac works.
- Permission on the server for test deploys without confirmation: it must be changed separately, in the server phase. Until then Ciro's automatic authorisation unlocks the session on the Mac, but the server can still ask for confirmation.
- 3D avatar: a later project.

## To avoid even if it works

- An automatic authorisation for production, deletions, databases, system configurations, credentials, new external services or subscriptions. Never, for any rule.
- A «sì» ("yes") linked to the wrong question.
- Two deliveries of the same answer, or a session that executes twice.
- A password in the log, in the conversation, in Ciro's context, in the mail or in the arguments of a command.
- Ciro speaking for news that do not matter.

## Constraints

- The global rule stays: production deploys, deletions, databases and configurations are confirmed in the server session, and no message replaces consent.
- `posta.py` stays the only way to read and write the mail, and stays standard library only, Python 3.9. This project is authorised to modify it. The copy in `~/.posta-agenti/bin/posta.py` is updated together.
- `posta-sessioni` today is not under git: before the changes a local git repository is created, without a remote server *(my choice)*.
- The existing tests (`scripts/test_posta.py`, `test_avvisi_opencode.py`, `test_rapporto_gestore.py`) must keep passing. Tests and mechanical work are delegated with `oc-task.sh`.

## Approaches considered

| Question | Options | Choice |
|---|---|---|
| How far the rules reach | A) work choices only · B) also test deploys after tests · C) any operation | **B** (the user) |
| How to know whether a rule covers a question | A) exact match only · B) for choices the model evaluates and Ciro warns at once, for test deploys exact match · C) the model evaluates everything | **B** (the user) |
| How to build it | A) the mail is extended: structured questions, state log, coordinator module · B) separate service with a database | **A** (the user). B was one more service to keep running and risked that mail and database would not match. Also rejected «lasciare tutto al modello» ("leave everything to the model"), because states and double executions are not entrusted to a model. |

## Project

### 1. Structured question: `posta.py chiedi`

New command for the sessions:

```
posta.py chiedi --da <progetto> --oggetto "<una riga>" --domanda "<la domanda in una frase>"
  --opzione "A=<testo breve>" --opzione "B=..." [--opzione "C=..."]
  [--raccomanda A] --operazione <operazione> [--ambiente <locale|prova|produzione>]
  --bloccato "<cosa è fermo finché non arriva la risposta>"
  [--condizioni test-ok,...] [--testo|--file <contesto essenziale>]
```

- `operazione` is one of: `scelta`, `deploy-prova`, `deploy-produzione`, `cancellazione`, `database`, `configurazione`, `credenziali`, `servizio-esterno`, `abbonamento`, `altro`.
- It writes into the `opencode` mailbox a message `TIPO: decisione`, `AZIONE: decisione` (or `accesso` for `credenziali`) with the new headers `DOMANDA-ID` (equal to the ID of the message), `OPERAZIONE`, `AMBIENTE`, `OPZIONI` (JSON on one line), `RACCOMANDA`, `BLOCCATO`, `CONDIZIONI`.
- It creates the record in the log (§2) with state `ricevuta`. It prints the ID.
- A message with the same headers but without `chiedi` stays valid as today: free-text questions keep working.

### 2. State log

- One JSON file per question: `~/.posta-agenti/domande/<ID>.json`, written atomically (temporary file and rename) with a lock per record.
- Fields: `id, progetto, oggetto, domanda, opzioni, raccomanda, operazione, ambiente, condizioni, bloccato, stato, risposta {scelta, testo, motivo: "utente"|"regola:<id>", ora}, storia [{stato, ora, chi, nota}]`.
- States and allowed transitions; every other transition is refused with exit code 4:

```
ricevuta → in-valutazione → in-attesa (di the user) → risposta-consegnata → recepita → risolta
ricevuta/in-valutazione → risposta-consegnata (risposta automatica)
qualsiasi stato prima di recepita → annullata (la sessione ritira la domanda)
```

- Commands:
  - `posta.py domande [--stato X] [--json]`: list;
  - `posta.py stato --id ID`: prints the state.

### 3. Delivery of the answer: `posta.py rispondi-domanda`

```
posta.py rispondi-domanda --id ID --scelta A [--testo "..."] --motivo utente|regola:<id> --da opencode
```

- Allowed only from `in-attesa` or `in-valutazione`: a second send exits with code 4 and writes nothing. This is what blocks double clicks, duplicated messages and restarts.
- It writes to the session a message `TIPO: decisione`, `RIF: ID`, `DOMANDA-ID: ID`, with the choice and the text of the option. It brings the record to `risposta-consegnata`.

### 4. Session side: `recepita` and `risolta`

- `posta.py recepita --id ID --casella <progetto>`: the session runs it when it reads the answer, **before** acting. If the record is already `recepita` or beyond, the command exits with code 4 and the session does not execute again.
- `posta.py risolta --id ID [--nota "..."]`: when the unlocked operation is done.
- For Ciro, «il lavoro è ripartito» ("the work has restarted") when there is `recepita` and the session state moves to «al lavoro» ("at work").
- The global rules (`~/.claude/CLAUDE.md`, mail section) and `REGOLA-CLAUDE.txt` change: questions to the user are asked with `posta.py chiedi`; when the answer arrives `recepita` is run and only if it succeeds do we act; when the work is done `risolta` is run.

### 5. The user's rules

Two types:
- **Work preferences:** free text, in the file that already exists, `~/.config/opencode/memoria-ciro.md`. Example: «per gli spazi Chat usa lo schema A» ("for the Chat spaces use scheme A"). The model evaluates them.
- **Authorisations:** structured, in `~/.config/opencode/autorizzazioni.json`. Each item is `{id, progetto, operazione, ambiente, condizioni[], creata, frase}`. **The code accepts only `operazione: "deploy-prova"`.** Any other operation is refused at saving time, even if the model proposes it.

How they are born:
- **Once only:** for a test deploy without a rule, Ciro asks «A: autorizza questa volta; B: autorizza sempre su questo progetto dopo i test; C: rimanda» ("A: authorise this time; B: always authorise on this project after the tests; C: postpone").
  - A answers that question only.
  - B saves the authorisation, after reading it out loud («Salvo: Ironworks, deploy di prova, dopo test riusciti. Confermi?» — "I save: Ironworks, test deploy, after successful tests. Do you confirm?"), and answers.
  - C leaves the question waiting.
- **By voice:**
  - «Da ora chiedimi sempre prima di pubblicare Ironworks» ("From now on always ask me before publishing Ironworks") removes the Ironworks authorisations and confirms it;
  - «Quali operazioni hai il permesso di fare su Contoso?» ("Which operations are you allowed to do on Contoso?") lists them in one sentence.

### 6. Coordinator: `scripts/coordinatore.py`

- Function `valuta(scheda, preferenze, autorizzazioni, chiedi_al_modello) -> {esito: "automatica"|"chiedi", scelta?, regola?, motivo}`:
  - `deploy-produzione`, `cancellazione`, `database`, `configurazione`, `credenziali`, `servizio-esterno`, `abbonamento`, `altro` → always `chiedi`. For the operations on the server the reason recalls that the real confirmation is given in the server session.
  - `deploy-prova` → `automatica` only if an authorisation has the same project, environment `prova` and conditions contained in those declared by the session. Choice: the option that the session indicates as «procedi» ("proceed") (`RACCOMANDA`); if it is missing, `chiedi`.
  - `scelta` → the model receives preferences and question and answers in JSON `{copre, scelta, regola, motivo}`. `automatica` only if `copre` is true and `scelta` is among the options. Error, timeout or invalid JSON → `chiedi`.
- Who runs it: Ciro's server, with a check of the log every 2 s on the records in `ricevuta`. It moves the record to `in-valutazione` with the lock, so that two runs do not evaluate twice. A record stuck in `in-valutazione` for more than 2 minutes (restart in the middle) goes back to `ricevuta`.
- If Ciro is off, the questions stay `ricevuta` and OpenCode sees them with `posta.py domande`. The evaluation restarts at the next power-on.

### 7. Ciro

- **Waiting question:** Ciro says it at once with the structured fields, without a model summary: «Da <progetto>: <domanda>. A, …; B, …. Consiglia A. Come rispondo?» ("From <project>: <question>. A, …; B, …. I recommend A. How do I answer?").
- **Linking the «sì» or the letter to the question:** Ciro remembers the ID of the last question it pronounced. The answer goes to that ID. If more than one question is waiting and the answer does not name the project (or is not clearly for the last one), it asks «Per quale progetto?» ("For which project?") before sending.
- **Automatic answer:** one sentence, «Ho risposto A ad alpha-bot, per la tua regola sugli spazi Chat» ("I answered A to alpha-bot, for your rule on the Chat spaces").
  - Within 2 minutes, «annulla» ("cancel") or «rispondi B» ("answer B") send a correction, a new message with `RIF` to the ID, marked in the history.
  - If the session has already run `recepita`, the correction says that it may have already acted.
- **Delivery:** after a successful `rispondi-domanda`, «Mandato» ("Sent"). The restart is announced only when `recepita` arrives and only in the summary, not by voice at once.
- The old free-text questions stay handled as today.

### 8. Updates

- **At once, by voice:**
  - new question in `in-attesa`;
  - message with `URGENTE: si`;
  - automatic answer (one sentence);
  - coordination errors (mail that does not write, inconsistent record).
- **Summary every 30 minutes**, only if there is news since the last one: records resolved or restarted, sessions stuck for more than 30 minutes on a question, authorisations used. One or two sentences. It is changed by voice («riepilogo ogni ora» — "summary every hour"; «niente riepiloghi» — "no summaries"); the setting is in `~/.config/faccia/impostazioni.json`.
- **Without an answer:** only the session that asked stops; no voice reminder before 30 minutes, then once in the summary.

### 9. Credentials

- For a question with `operazione: credenziali`, Ciro's page shows a password field with the name of the entry requested by the session, for example `ciro-ironworks-shopify`.
- The value goes with POST to `/api/credenziale` (only from the local page) and the server saves it in the Keychain with the service `ciro-<progetto>-<nome>`.
- The value must not pass through the arguments of a command (visible in the processes): method at the choice of whoever builds it, for example `security` with standard input.
- To the session goes `rispondi-domanda` with text «Credenziale salvata nel Portachiavi: servizio ciro-<progetto>-<nome>» ("Credential saved in the Keychain: service ...").
- Never in the log, in the conversation, in Ciro's context or in the mail.

## Checks

- **Complete cycle** with a fake session (test script):
  - `chiedi` → `in-attesa`;
  - simulated answer from the user (Ciro with fake model) → `risposta-consegnata` → `recepita` → `risolta`;
  - messages and history consistent.
- **Double executions:** two `rispondi-domanda` on the same record give a single message. A second `recepita` exits with 4. A restart of Ciro's server during `in-valutazione` does not lead to a second answer.
- **Linking:** two waiting questions from different projects, «A» without project → Ciro asks for which one. «A per P2» → only P2.
- **Authorisations:**
  - `deploy-prova` with the right rule and conditions → automatic;
  - without `test-ok` → chiedi;
  - the saving of a rule for `deploy-produzione`, `database` and similar is refused by the code;
  - no forbidden operation ever answers automatically, not even if the fake model says `copre: true`.
- **Credentials:** after an entry, a search of the value in `~/.posta-agenti`, `~/.config/faccia`, in the log and in the process list does not find it.
- **Compatibility:** existing tests green; a question in the old free-text style works as today.

## Left to whoever builds it

- The exact names of the internal functions, the format of the logs and the text of the prompt for evaluating preferences, as long as it asks for JSON and nothing else.
- The safe method of writing into the Keychain.

## What is needed from the user

- Approving this document.
- Later, in the server phase: deciding how to give the agent on the server the permission for test deploys.
