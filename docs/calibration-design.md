# Calibration and acceptance test led by Ciro ("Ciro, calibrati")

Date: 19/11/2026. Approved by the user in conversation.

## Why

A first voice test driven by an external script was confusing: the user did not know what to
say, the script waited silently, and the user's words were mixed with other sessions' notices.
The user asked for a procedure where **Ciro guides**, tells the user what to say, and checks
that he understands the user's voice and can interact properly — like the voice enrolment of
Siri or Google Assistant.

## What others do

- Siri: five enrolment phrases at set-up, then implicit enrolment up to 40 samples.
- Google Voice Match: "Hey Google, learn my voice", guided phrases, retrain at any time.
- Microphone calibration (patents, SpeechRecognition's `adjust_for_ambient_noise`): measure the
  silence first to set the noise threshold, then the voice; too low a threshold means false alarms.
- PARADISE (Walker et al., 1997): judge a spoken dialogue system by task success and dialogue
  costs (turns, response time, recognition errors).

## The procedure

Started by voice ("Ciro, calibrati", "calibrazione", "collaudo") or `POST /api/collaudo`.
Stopped by "basta calibrazione" / "ferma la calibrazione". While it runs the projects are paused
(only `prova-ciro` and `prova-due` may speak) and the previous pause state is restored at the end.

1. **Silence (10 s).** Ciro says "Resta in silenzio per dieci secondi". The page measures the
   microphone level (mean, 95th percentile) and sends it to the server.
2. **Voice (8 phrases).** "Ripeti dopo di me: …" for: A, B, sì, no, "rispondi B",
   "B per prova due", "pausa progetti", "come stanno le sessioni". For each: what whisper
   heard, whether it matches, the voice level, the transcription time. One retry on a mismatch
   or on 20 s of silence. Short mis-hearings of a single letter (for example "ah" for A) are
   learned as aliases. During phases 1–2 the user's words are not commands.
3. **Three tasks** with test sessions, answered through the normal paths (voice or buttons):
   answer a question (A); correct it ("rispondi B"); two questions at once (A to prova-due,
   B to prova-ciro). For each: success, number of user turns, time. 90 s per task.
4. **Result.** One spoken sentence and a report in `~/.config/faccia/collaudi/`.
   Saved in `impostazioni.json`: `soglia_microfono` (max(0.008, 2.5 × noise p95)) and
   `alias_lettere`. The page uses the calibrated threshold instead of the fixed 0.011.

## Non-goals

Speaker identification (Ciro does not tell your voice from others), wake word, model retraining.

## Builder's calls

State machine in `ciro/collaudo.py`, driven by the server loop (`tick`, every 2 s) and by the
brain (`gestisci(testo)` before any other handling while phases 1–2 run). The page sends the
level of each capture with `/api/cervello` and runs the silence measurement on a queued command.
