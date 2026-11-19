# Using the calibration data: the voice profile

Date: 19/11/2026. Approved by the user in conversation.

## Why

The calibration measured the room and the voice but only two results were used (microphone
threshold, letter aliases). Real data showed that the errors are personal and repeatable
(this user's "B" is heard as "di", a "sì" once as "C"), and that whisper models differ little on
short answers but a lot in speed. Similar projects use enrolment and usage data to adapt:
per-user end-of-speech pauses (Google endpointing patents, Pipecat Smart Turn), confidence-based
confirmations (Bohus & Rudnicky, Pearl), implicit enrolment from use (Siri), biasing towards the
words expected in context (CB-Whisper), PARADISE-style measures over time.

## The voice profile (`impostazioni.json` → `profilo_voce`)

| Field | From | Used for |
|---|---|---|
| `confusioni` {heard → meant} | calibration mismatches, user corrections | explicit "Hai detto due?" only when the heard answer is a known confusion |
| `modello_breve` | automatic test bench after each calibration | fastest whisper model that understands the short answers as well as the big one |
| `fine_frase_ms` | pauses inside the user's phrases | end-of-speech silence (default 900 ms) |
| `eco` | microphone level while Ciro speaks the first prompt | barge-in threshold |

## Pieces (in this order)

1. **Calibration revised (~50 s)**: 5 s silence (Ciro's echo is measured while he speaks the
   prompt), 5 short answers, one long free sentence ("come stanno le sessioni oggi e chi mi
   aspetta"). The page sends the pauses inside each phrase.
2. **Confusion-aware confirmation (three tiers)**: clear answer → implicit confirmation
   ("Mandato: due, fermati"); heard answer is a known confusion or an ambiguous lone letter →
   "Hai detto due, fermati?"; heard answer not among the options but a known confusion of one →
   "Hai detto due?"; otherwise an escalating reprompt (first "Ripeti", then the numbered options).
3. **Implicit learning**: a correction within 2 minutes ("rispondi due") records the confusion
   and saves the audio of the misunderstood answer, labelled, into the test bench.
4. **Automatic model choice**: after a calibration the bench runs in the background on all
   labelled recordings and keeps the fastest short-answer model with no loss of accuracy.

Later: post-recognition matching against the words expected in context (options, project
names); Smart Turn for end of turn; usability measures over time.
