# Google Chat in Ciro — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ciro warns the user about urgent Google Chat messages that need his answer, from every Chrome profile, and writes his spoken answer in Chat after his "sì".

**Architecture:** The existing Chrome extension (`ciro/estensione-chrome`) catches Chat's notifications in the page and forwards them to Ciro's server; a new module `ciro/chat.py` keeps the open conversations and asks the model whether each direct message or mention is urgent; the server shows them in "Ti aspettano" with the shared question numbers, and the brain turns "quattro: rispondi che …" into a confirmed write order that the extension carries out in the same profile.

**Tech Stack:** Python 3 standard library (server, tests with unittest), Chrome extension Manifest V3 (content scripts in the MAIN and isolated worlds, service worker), DeepSeek via `cervello.chiedi_modello`.

**Spec:** `docs/google-chat-design.md`

## Global Constraints

- Only direct messages and @mentions go to the model, to judge urgency; other Chat text stays on the Mac unless the user asks ("riassumi", "scrivi tu la risposta").
- Nothing is written in Chat without the user's "sì"; the target is the conversation the message came from, in the same account. "Mandato" only after the extension reports the message is in the conversation.
- No automatic replies, no rules that answer for the user.
- The repository holds no personal data: no accounts, space names, people, IDs; examples use fake names (Luca, Sviluppo, alpha). The pre-push guard must pass.
- Documents in English; spoken and UI texts in Italian through `t()` / `T()` with English entries in `testi.py` / `testi.js`.
- The model has 8 s to judge urgency; on no answer the message stays on the panel, silent.
- "Pausa progetti" also pauses Chat (Chat items use the project name `chat`).
- Chat items leave the panel when answered, when the user says "letto il N" / "ok il N", or after 2 hours.
- Tests run delegated (`opencode run -m deepseek/deepseek-flash`); browser checks with Playwright headed on a test Ciro (port 8766, temporary mail root), never on 8765; layout screenshots at 1496 and 1024 wide.

## Review Focus

- The same message notified twice (Chat re-notifies on focus, two tabs in one profile): one item, one announcement.
- Many messages in one conversation: one panel item and one number per conversation (latest text, count), not one per message.
- The user says "sì" after the item expired or after the extension went away: Ciro says it could not write, never "Mandato".
- A profile without a Chat tab: the panel warns within 5 minutes; a write order for that account fails fast (60 s) with a spoken message.
- Very long messages: spoken text cut at 300 characters, full text on the panel tooltip.

---

### Task 1: Spike — catch Chat notifications in a real profile

**Files:**
- Create: `ciro/estensione-chrome/chat-pagina.js` (MAIN world: hook), `ciro/estensione-chrome/chat.js` (isolated world: forwards)
- Modify: `ciro/estensione-chrome/manifest.json` (content scripts for `https://chat.google.com/*` and `https://mail.google.com/chat/*`, host permission `http://127.0.0.1:8765/*` already there; version 1.3), `ciro/estensione-chrome/sfondo.js` (forward to the server), `ciro/server.py` (`POST /api/chat/grezzo`, extension origin only)

**Interfaces:**
- Produces: page message `window.postMessage({ciro: "chat", titolo, corpo, tag, icona, quando, url})`; server file `~/.config/faccia/chat-grezzo.jsonl` (local only, never in the repo).

- [ ] **Step 1:** `chat-pagina.js` wraps `window.Notification` (constructor) and `ServiceWorkerRegistration.prototype.showNotification`, calls the original, and posts the fields above; `chat.js` relays to the service worker with `chrome.runtime.sendMessage`; `sfondo.js` POSTs to `/api/chat/grezzo`.
- [ ] **Step 2:** server appends each payload to `chat-grezzo.jsonl`; `_provenienza_ok` allows the extension origin for `/api/chat*` exactly as for `/api/consumi`.
- [ ] **Step 3 (with the user, one step at a time):** reload the extension in one profile, open Chat, enable Chat notifications, ask a colleague (or a second account) for a direct message, a mention and a space message.
  Expected: three lines in `chat-grezzo.jsonl`. Record the field formats (sender/space/text positions, `tag` uniqueness, `url` present or not) in `docs/google-chat-design.md` with fake values only.
- [ ] **Step 4:** decide: notifications work → continue; they do not → replace Task 1 Step 1 with the sidebar unread reader and record the ruling.
- [ ] **Step 5:** commit (`chat-pagina.js`, `chat.js`, `manifest.json`, `sfondo.js`, `server.py`, design note).

### Task 2: Server — open conversations, urgency, panel and voice

**Files:**
- Create: `ciro/chat.py`, `ciro/tests/test_chat.py`
- Modify: `ciro/server.py` (`POST /api/chat`, `POST /api/chat/vivo`, Chat items in `attese()`, voice in `giro_avvisi`), `ciro/testi.py`, `ciro/testi.js`, `ciro/faccia.js` (account and count on Chat items), `ciro/stile.css`

**Interfaces:**
- Consumes: payload from Task 1, normalised by the extension to `{account, conversazione, url, spazio, mittente, testo, quando, diretto, menzione, tag}`.
- Produces in `chat.py`:
  - `class Chat(percorso)`: `aggiungi(messaggio: dict) -> dict | None` (None for a duplicate `tag`), `aperte(adesso=None) -> list[dict]` (one per `conversazione`, with `conteggio`, latest `testo`, `urgente`, `risposta_serve`, `motivo`; drops those older than 2 h), `chiudi(conversazione: str) -> bool`, `vivo(account: str)`, `account_assenti(adesso=None) -> list[str]` (seen before, silent for 5 min).
  - `valuta_urgenza(messaggio: dict, chiedi_modello) -> dict | None` returning `{"urgente": bool, "risposta": bool, "motivo": str}`; None on timeout (8 s), bad JSON or model error; called only when `diretto or menzione`.
- Produces in `server.py`: Chat items in `attese()` with `tipo: "chat"`, `progetto: "chat"`, `chat_id: conversazione`, `account`, `mittente`, `spazio`, `conteggio`, `a_voce: urgente and risposta_serve`; numbered by `numera()` with key `"chat|" + conversazione`.

- [ ] **Step 1: failing tests in `tests/test_chat.py`** (fake model; temporary file):
  - `test_doppione_ignorato`: same `tag` twice → second `aggiungi` returns None, `len(aperte()) == 1`.
  - `test_una_voce_per_conversazione`: three messages, same `conversazione` → one item, `conteggio == 3`, `testo` == the last.
  - `test_scade_dopo_due_ore`: item absent from `aperte(adesso=quando + 7201)`.
  - `test_urgenza_solo_diretti_e_menzioni`: space message → the fake model is never called.
  - `test_urgenza_json`: model returns `{"urgente": true, "risposta": true, "motivo": "chiede una conferma oggi"}` → item `urgente` True.
  - `test_modello_muto_resta_silenzioso`: model times out → `urgente` None, item `a_voce` False in `server.attese()`.
  - `test_urgente_detto_con_numero`: urgent item → `giro_avvisi` queues a phrase starting `"Messaggio uno, da Luca"`.
  - `test_non_urgente_solo_pannello`: not urgent → listed in `attese()`, nothing queued.
  - `test_pausa_ferma_la_chat`: `pausa_progetti` true → urgent item not queued.
  - `test_testo_lungo_tagliato`: 1000-char text → spoken phrase ≤ 300 chars of message text.
  - `test_account_assente`: `vivo("work")` then 301 s of silence → `account_assenti() == ["work"]`, panel warning item present.
- [ ] **Step 2:** run `python3 -m unittest tests.test_chat` (delegated). Expected: FAIL, `ModuleNotFoundError: chat`.
- [ ] **Step 3:** implement `chat.py`; storage `CONFIG_FACCIA / "chat.json"` (tests use a temporary path); urgency prompt in Italian and English (`per_lingua`), answer is one JSON object; urgency runs in a thread so `/api/chat` answers at once.
- [ ] **Step 4:** wire `server.py`: `/api/chat` → `aggiungi` + urgency thread; `/api/chat/vivo`; Chat items in `attese()`; spoken phrase `t("Messaggio %s, da %s: %s. Come rispondo?")` (`"Message %s, from %s: %s. How do I answer?"`) with the space added when not a direct message (`t(" in %s")`).
- [ ] **Step 5:** run all suites (delegated). Expected: all OK.
- [ ] **Step 6:** panel: Chat items show `#N`, sender, space and account, count when > 1; warning line for absent accounts. Layout check on 8766 with fake data at 1496 and 1024; screenshots in `.playwright-mcp/`.
- [ ] **Step 7:** commit.

### Task 3: Answering by voice — confirmation and write orders

**Files:**
- Modify: `ciro/cervello.py` (routing for Chat items), `ciro/chat.py` (write orders), `ciro/server.py` (`GET /api/chat/da-scrivere`, `POST /api/chat/esito`), `ciro/testi.py`
- Test: `ciro/tests/test_chat_risposte.py`

**Interfaces:**
- Consumes: Task 2 items (`chat_id`, `account`, `mittente`), `Numeri.cerca(n)` returning `{"progetto": "chat", "chiave": "chat|<conversazione>", …}`.
- Produces in `chat.py`: `ordina(conversazione: str, testo: str) -> str` (order id), `da_scrivere(account: str) -> list[dict]` (`{id, conversazione, url, testo}`; marks them taken), `esito(ordine: str, ok: bool, errore: str | None) -> dict | None`, `scaduti(adesso=None) -> list[dict]` (taken or waiting for more than 60 s without an outcome).
- Produces in `cervello.py`: `self.chat_in_attesa = {"conversazione", "mittente", "testo"} | None`.

- [ ] **Step 1: failing tests:**
  - `test_rispondi_chiede_conferma`: open Chat item #1 from "Luca"; `chiedi("uno: rispondi che va bene, ci sentiamo domani")` → `risposta == "Scrivo a Luca: va bene, ci sentiamo domani. Confermi?"`, `mandato` False, no order.
  - `test_si_crea_ordine`: then `chiedi("sì")` → one order in `da_scrivere(account)`; Ciro says `"Lo scrivo."`, not "Mandato".
  - `test_no_annulla`: `chiedi("no")` after the read-back → no order, `"Va bene, non lo scrivo."`.
  - `test_esito_ok_dice_mandato`: `esito(ordine, True, None)` → queued phrase `"Mandato a Luca."`; the Chat item is closed.
  - `test_esito_ko`: `esito(ordine, False, "casella non trovata")` → queued `"Non sono riuscito a scrivere a Luca: casella non trovata."`; item stays.
  - `test_nessuna_estensione`: no `da_scrivere` call for 61 s → queued failure phrase; order dropped.
  - `test_letto_chiude`: `chiedi("letto il uno")` and `chiedi("ok il uno")` → item closed, no model call.
  - `test_si_dopo_scadenza`: item expired before "sì" → `"Quel messaggio non è più aperto."`, no order.
- [ ] **Step 2:** run (delegated). Expected: FAIL.
- [ ] **Step 3:** in `_risposta_per_numero`, when `voce["chiave"]` starts with `"chat|"`: free text after the number matching `^(?:rispondi|scrivi|digli|dille)\s+(?:che\s+)?(.+)$` → read-back; "letto"/"ok" before the number → `chiudi`. In `risposta_veloce`, `chat_in_attesa` takes "sì"/"no" before every other state. Order expiry checked in the server's 8-second loop.
- [ ] **Step 4:** run all suites (delegated). Expected: all OK.
- [ ] **Step 5:** commit.

### Task 4: Extension — forward, write, report; installation

**Files:**
- Modify: `ciro/estensione-chrome/chat.js`, `chat-pagina.js`, `sfondo.js`, `manifest.json` (version 1.4), `README.md` (install in every profile, Chat tab pinned, Chat notifications on)

**Interfaces:**
- Consumes: `/api/chat`, `/api/chat/vivo` (Task 2), `/api/chat/da-scrivere?account=…`, `/api/chat/esito` (Task 3).

- [ ] **Step 1:** `chat.js` normalises the notification into the Task 2 payload; `account` is the signed-in address read from the page; `diretto`/`menzione` from the notification format recorded in Task 1.
- [ ] **Step 2:** `sfondo.js`: every 60 s `vivo` for each profile with a Chat tab; every 3 s `da-scrivere`; an order goes to the Chat tab of that account, which opens `url`, writes the text in the composer, sends it, checks that the last message of the conversation equals the text, and posts `esito`.
- [ ] **Step 3 (with the user, one step at a time):** install 1.4 in the profiles, including the personal one; a test conversation with a second account: urgent DM → Ciro speaks; "uno: rispondi che ok" → read-back → "sì" → the message appears in Chat → "Mandato a …". Then close the Chat tab → "sì" on a new order → failure spoken within 60 s.
- [ ] **Step 4:** README section "Google Chat" (English, fake names), pre-push guard passes, commit and push.
