# Google Chat in Ciro

Date: 19/11/2026. Status: approved in principle (approach B, urgency by the model); waiting for the final approval.

## Why

The user works in many Google Chat spaces and direct messages across several Google
accounts (work Workspace accounts and a personal Gmail account). Today he must keep
looking at Chat. Ciro already tells him when a Claude Code session needs him; it should
do the same for Chat, and let him answer by voice.

## Goals

- Ciro tells the user about new Google Chat messages, from every account and Chrome
  profile, including the personal one.
- The user answers by voice: Ciro reads the answer back and writes it in Chat only after
  the user's "sì".
- Chat messages use the same numbers as the questions ("Messaggio quattro, da Luca in
  Sviluppo: …"; "quattro: rispondi che va bene").

## Non-goals

- No full Chat client: no history, no search, no attachments.
- No automatic replies, ever. Rules ("for X always answer Y") are not in scope.

## Anti-goals (a failure even if it works)

- Ciro talking all the time: busy spaces must not interrupt the user.
- Chat text leaving the Mac beyond what the user chose: only direct messages and mentions
  go to the model, to judge urgency (see below); nothing else leaves the Mac unless the user
  asks ("riassumi", "scrivi tu la risposta").
- A message written in the wrong conversation or account.
- Personal data (accounts, space IDs, names) in the public repository.

## Approaches

| | How | Trade-offs |
|---|---|---|
| A. Google Chat API | OAuth login per account, a Google Cloud project with the Chat API | Stable and official. It needs a Workspace account (as far as we know it does not work with a personal Gmail account), a Cloud project, and possibly admin approval |
| **B. Chrome extension (chosen by the user)** | The existing Ciro extension, installed in every Chrome profile, reads Chat in the browser where the user is already logged in | Works with every account, including Gmail. No Google setup. It depends on the Chat web page, which Google can change: the reading part must be small and easy to fix |
| C. Extension reading every conversation | Like B, but it opens each space and reads the page | It sees everything, but it is heavy and the most fragile |

The user chose B.

## Design

**Reading: the notifications of Chat.** On `chat.google.com` (and Chat inside Gmail), a
small script in the page catches the desktop notifications that Chat shows: each one
has the sender, the space and the text, and they cover direct messages, mentions and the
spaces the user follows. This avoids reading the page layout, which changes often.
*To verify first (1-hour spike):* that Chat raises these notifications from the page
while its tab is open. Fallback: read the unread list in the sidebar (sender, space, first
line).

- Chat must be open in a tab in each profile (a pinned tab). The extension shows a warning
  on Ciro's panel when a profile has no Chat tab.
- Each message goes to Ciro on the Mac (`127.0.0.1:8765/api/chat`) with: account, space or
  person, sender, text, time, and a link to the conversation. Only the extension's origin can
  call this endpoint, like `/api/consumi` today.

**What Ciro says: only urgent messages that need an answer.** The user does not want every
message read; he wants to be warned when something urgent needs his reply. The user chose
the model to decide (option B, 19/11/2026):

- Each direct message and @mention goes to the model (DeepSeek, like Ciro's brain) with the
  sender, the space and the text. The model answers in JSON: urgent yes/no, needs an answer
  from the user yes/no, a one-line reason.
- Urgent and needs an answer: Ciro says it at once, verbatim, with a number from the same
  pool as the questions ("Messaggio quattro, da Luca: …").
- Not urgent: only on the panel. Other space messages: only on the panel, counted
  ("tre messaggi nuovi in Sviluppo"); "leggi il quattro" reads one.
- If the model does not answer in a few seconds, the message stays on the panel and Ciro
  says nothing (no guessing).
- "Pausa progetti" also pauses Chat.

**Answering.**

1. The user says: "quattro: rispondi che va bene, ci sentiamo domani".
2. Ciro reads it back: "Scrivo a Luca: va bene, ci sentiamo domani. Confermi?"
3. Only after "sì", the extension in the right profile opens that conversation, writes the
   text and sends it. It reports back. Ciro says "Mandato" only when the message is in the
   conversation; otherwise it says it failed.

**On the panel.** The Chat messages appear in "Ti aspettano" with their number and the
account. They leave the panel when answered, when the user says "letto" or "ok il
quattro", or after 2 hours.

**Privacy and safety.**

- Direct messages and mentions are sent to the model to judge urgency (the user's choice);
  other messages stay on the Mac. Texts are in Ciro's local log (`conversazioni.log`), like
  everything Ciro says.
- The model sees other Chat texts only when the user asks for a summary or a drafted reply.
- Nothing is written without the user's "sì". The target conversation is the one the
  message came from, in the same account.
- The repository holds only code: no accounts, IDs or names.

## Pieces (in order)

1. Spike: catch Chat notifications in a real profile; decide notifications or sidebar.
2. Reading: extension → `/api/chat` → urgency by the model → panel and voice, with numbers;
   tests with fake messages and a fake model.
3. Answering: the confirmation flow, the extension writing in the conversation, the report
   back; tests on a test space.
4. Installation in every profile (README steps, including the personal profile) and the
   "no Chat tab" warning.

## Left to the builder

- The exact page selectors and the notification hook.
- How the extension identifies its account (the logged-in address shown in the page).
