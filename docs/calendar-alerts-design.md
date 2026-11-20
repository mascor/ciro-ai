# Calendar alerts: design

Milestone M6. Decisions taken with the maintainer on 20/11/2026 are recorded in #25.

## Goal

Fixed appointments (meetings, calls, visits) that the maintainer marks **red** in Google Calendar
cannot be moved and need attention. Ciro announces them and keeps announcing them until the
maintainer says they will handle them.

## Rules agreed

| Topic | Decision |
|---|---|
| Which events | only events coloured **Tomato** (the full red, `colorId` `"11"`); Flamingo and calendar colours do not count |
| Which calendars | the maintainer's two Google accounts (work and personal); in each account the calendars chosen at setup (default: the primary one) |
| When the alert starts | **30 minutes** before the start |
| Repetition | **every 5 minutes** until confirmed |
| After confirmation | **complete silence** for that event |
| Access | Google Calendar API, **read-only** (`calendar.readonly`); the only way to read the per-event colour (iCal links and the macOS Calendar do not expose it) |

## How it works

1. **Reader** (`ciro/calendario.py`): every 60 s, for each account, `events.list` on the chosen
   calendars with `timeMin = now`, `timeMax = now + 35 min`, `singleEvents = true`. Keeps events with
   `colorId == "11"` and `status != "cancelled"`; all-day events are ignored (no start time).
   Each event becomes `{id, account, calendar, title, start, link}`; the key is `account|event id|start`,
   so a moved event is a new alert.
2. **Panel**: red events within 30 minutes appear in «Ti aspettano» with a number, like the questions,
   time and calendar name, and a button «Lo gestisco».
3. **Voice**: at T-30 and then every 5 minutes, one short phrase: «Alle 15:00 hai la telefonata con
   Rossi, tra 20 minuti. Dimmi "lo gestisco".» The phrase goes through the normal speech queue
   (pause, mute and «Ciro off» are respected).
4. **Confirmation**: «lo gestisco», «ci penso io», «ok lo so», or «cinque, lo gestisco» with the
   number; in English «I'll handle it», «got it». The button does the same. Confirmations are stored in
   `~/.config/faccia/calendario-confermati.json` (key → time), so they survive a restart; entries older
   than a day are dropped.

## Access and secrets

- One OAuth client of type *Desktop app* in a Google Cloud project owned by the maintainer, Calendar
  API enabled, scope `https://www.googleapis.com/auth/calendar.readonly` only.
- First run per account: `python3 ciro/strumenti/collega_calendario.py <short name>` opens the Google
  consent page in the browser; the refresh token goes to the macOS Keychain (service
  `ciro-calendario-<short name>`). The client id/secret file stays in `~/.config/ciro/`, never in the
  repository; nothing about the accounts is logged.
- If a token is revoked or expired, Ciro says once that the calendar of that account is not readable
  and shows it in the panel.

## Failure modes

- No network or Google error: keep the last good list for up to 10 minutes, then show «calendario non
  aggiornato» in the panel; never alert on stale data older than that.
- Clock: all times compared in UTC; the phrase uses the local time.

## Issues

| Issue | Content |
|---|---|
| #25 | this note |
| #26 | reader + tests on fake API answers (no network) |
| #27 | panel |
| #28 | voice alert and repetition, with tests |
| #29 | confirmation by voice and button, saved |
| #30 | end-to-end test with a red test event in each calendar |

Open point to settle at setup (#26): which calendars of each account to read besides the primary one.
