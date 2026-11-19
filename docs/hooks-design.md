# Ciro connect: sessions reach Ciro through hooks

Date: 19/11/2026. Requested by the user after the external review ("connect to sessions
without instructing them"). Status: design, phase 1 (Claude Code) being implemented.

## Goal

Today a session reaches Ciro only if its CLAUDE.md tells it to run `posta.py chiedi`.
With hooks, every Claude Code session (and later every OpenCode session) sends Ciro its
permission requests and multiple-choice questions on its own. Ciro reads them aloud with
a number, the user answers by voice or on the panel, and the session receives the answer.
Nothing to install in the projects; nothing to teach the sessions.

## What the tools offer (verified 19/11/2026)

Claude Code 2.1.328 (docs: code.claude.com/docs/en/hooks.md):
- `PermissionRequest`: fires when a tool needs a permission decision. Input: `tool_name`,
  `tool_input`, `session_id`, `cwd`, `transcript_path`. Output:
  `{"hookSpecificOutput": {"hookEventName": "PermissionRequest", "decision": {"behavior": "allow"|"deny", "message": ...}}}`.
  A hook cannot allow what a deny rule refuses.
- `PreToolUse` with matcher `AskUserQuestion`: sees `tool_input.questions` (question,
  header, options, multiSelect). It answers with `permissionDecision: "allow"` plus
  `updatedInput` (the questions echoed back with `answers`: question text -> chosen label).
- Hook type `http`: Claude Code POSTs the input JSON to a URL; a 2xx JSON body is read as
  the hook output; an empty 2xx, a non-2xx or a connection error is a non-blocking error,
  so the normal prompt appears in the terminal. Default timeout 600 s; we set our own.
- User settings `~/.claude/settings.json` apply to every session.

OpenCode 2.3.2: plugin event `permission.asked`, reply through `POST /permission/:id/reply`
(`permission.reply` in the SDK). Phase 2.

## Design

### Flow (Claude Code)

1. Claude Code POSTs the hook input to `http://127.0.0.1:8765/hooks/claude` (timeout 75 s).
2. Ciro answers at once with an empty 200 (= "ask in the terminal as usual") when:
   Ciro is off or muted, the projects are paused for that project, the hook is not one we
   handle, or the question is not a single single-select question.
3. Otherwise Ciro creates a structured question in the existing registry
   (`domande`), with `canale: "hook"`:
   - permission: `operazione: "permesso"`, options `S` = allow, `N` = deny; the text says
     the tool and a short, speakable summary of what it wants to do
     ("vuole eseguire: npm test", "vuole modificare: src/app.py");
   - AskUserQuestion: `operazione: "scelta"`, options A, B, C... from the labels.
   The project is the basename of `cwd`. No mail is sent: neither to the manager nor,
   on answer, to the session (the hook is the channel).
4. The question follows the normal path: number, voice announcement, panel buttons,
   answer by voice («quattro, sì»), with every safety rule of 19/11 (numbers resting,
   answers only to questions said aloud, the letter from the user's words).
   Permissions are never answered by saved preferences or authorisations: only the user.
5. The HTTP handler waits for the record to reach `risposta-consegnata` (polling the
   registry, up to 60 s, setting attesa_hook) and returns allow/deny (or the chosen labels). On
   time-out it closes the record as `annullata` («passata al terminale») and returns an
   empty 200: the terminal prompt appears, nothing is lost.
6. The record is then marked `recepita` and `risolta` by Ciro itself.

### Safety

- The server listens only on 127.0.0.1. Allow is returned only for a record answered by
  the user (`motivo: utente`), never by a rule or the model.
- Deny rules of Claude Code always win (documented behaviour).
- A late answer (after the time-out) finds the record `annullata`: «Già passata al terminale».
- If Ciro crashes, Claude Code gets a connection error and shows the normal prompt.

### Install: `ciro connect` / `ciro disconnect`

`ciro/strumenti/collega.py connect|disconnect|stato`:
- backs up `~/.claude/settings.json` (`settings.json.bak-ciro-<date>`), then adds two hook
  entries whose URL contains `/hooks/claude` (PermissionRequest; PreToolUse matcher
  AskUserQuestion), keeping every other setting and hook;
- `disconnect` removes only those entries; `stato` says whether they are there.
- Idempotent: connecting twice changes nothing.

### Not in phase 1

- Stop / Notification (session finished, idle): the session panel already shows it.
- OpenCode plugin (phase 2), multi-question or multi-select AskUserQuestion, answers
  with free text.

## Tests

- registry: hook questions are created without mail, answered without mail, never
  answered by rules;
- server: `/hooks/claude` returns empty when Ciro is off; allow/deny after a voice answer;
  empty after the time-out with the record `annullata`; AskUserQuestion answers carry
  `updatedInput.answers`;
- collega.py: connect/disconnect keep the other settings, are idempotent, make a backup.
