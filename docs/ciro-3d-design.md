# Ciro 3D: half-bust character connected to real events

Date: 18/11/2026. Request from the user (text pasted in chat), choices made in conversation: avatar from an online generator (Avaturn, fallback MetaPerson) and animation computed in real time (no recorded clips).

## Why

Ciro stays open all day while the user works. Today it is a big SVG smiley that stares at the user. A pleasant character is needed, smaller, that makes clear at a glance what is happening and what its role is: it acts as the link between the user and the Claude Code sessions. The key gesture: when an agent's question arrives, Ciro first looks at that session's monitor, then turns towards him.

## Objectives

1. 3D character, half bust: adult man, alert and friendly, slightly messy hair, short beard, glasses, casual shirt with rolled-up sleeves. Skin, fabrics and light fairly realistic, proportions and expressions slightly stylised.
2. Scene: small desk, coffee cup, side monitors, dark environment, soft light on the face, light-blue details (`--ciano` #6ee7f9).
3. The character takes up less space than now: three-quarter view, at the distance of a desk, with no huge head staring. Usage panel, «Ti aspettano» ("They are waiting for you") and subtitles stay readable.
4. Every animation comes from a real event of the page or of the server (table below).
5. Sessions as monitors or cards around the desk, with the real project names. The one asking for something is highlighted.
6. Clickable A/B/C buttons when Ciro proposes options, on the same path as voice answers and with the same confirmation rules.
7. Confirmation card next to Ciro with recipient and text, plus the Conferma and Annulla buttons.
8. Occasional gestures (glasses, sip of coffee, stretching): rare and interrupted instantly when the user speaks.
9. Option «Movimenti ridotti» ("Reduced motion"), rendering reduced when the tab is hidden, static version if 3D is not available.

## What stays as it is

Local voice (Kokoro), transcription (whisper), voice interruption, messages to the sessions, confirmations, memory of the rules, persistent context, subtitles, usage panel, «Ti aspettano» ("They are waiting for you"), spontaneous notices, `conversazioni.log` log, automatic page refresh. Ciro's verbal style does not change.

## Non-objectives

- No new call to the model, no new spoken line, no delay due to the animations.
- No recorded animation clips (Mixamo or similar).
- No Unity or Babylon: we stay in the current page, in JavaScript without build steps.

## To avoid even if it works

- Showing successful sends, completed activities or progress without an event that confirms them.
- A button that sends the same message twice.
- Mouth or gestures that continue after an interruption, even for a few frames.
- Fake lip sync when the voice is muted.
- A page that heats up the Mac: 3D must not slow down listening.

## Constraints

- Everything local: three.js copied into the repository (`faccia/vendor/three/`, version 0.18x pinned), no CDN at runtime. The Python server (`server.py`) serves the files.
- Avatar in `faccia/modelli/ciro.glb`. Private repository: it is committed if under 25 MB, otherwise it goes in `~/.config/faccia/` and the server serves it from there *(my choice)*.
- Tests always with Playwright and a visible browser; screenshots in a local folder.
- Tests and mechanical work delegated to DeepSeek with `oc-task.sh`, as per global rules.
- Blender 5.2 (`/Applications/Blender.app`) to inspect, optimise and touch up the model (from the command line, Python script).

## Approaches considered

| Question | Options | Choice |
|---|---|---|
| Where the character comes from | A) online generator of realistic avatars (Avaturn, fallback MetaPerson) · B) modelled in code with simple shapes · C) 2D illustrations in layers | **A** (the user). B looked like plasticine; C had fake rotations. |
| How it moves | A) everything computed in real time (bones, face shapes, hand-written gestures) · B) recorded clips for the body and computation only for the face | **A** (the user). Interruptible within one frame, no extra files and accounts. B was more natural but heavy and slow to interrupt. |

## The character

- The user creates it on Avaturn, following step-by-step instructions: short beard, glasses, messy hair, shirt. Then he exports it in GLB with the ARKit shapes and the visemes.
- If Avaturn does not have the right beard or shirt: touch-up in Blender, or fallback MetaPerson.
- Preparation in Blender (script in the repository, `strumenti/prepara_avatar.py`):
  - cut of the part below the bust;
  - textures reduced to 1024–2048 px;
  - compression of the shapes;
  - check of the bone and shape names;
  - static fallback image (`modelli/ciro-statico.png`) in three poses: idle, listening, off.
- The avatar comes out standing: the seated pose is obtained by rotating shoulders, arms and forearms in the code (hands resting on the desk) and the desk covers the legs *(my choice)*.
- Map names → movements in `corpo.js`. Bones: head, neck, torso, right arm, right forearm and right hand. Shapes: `jawOpen`, `mouthClose`, `mouthFunnel`, `mouthSmile`, `eyeBlink_L/R`, `browInnerUp`, `browDown_L/R`, `eyeLookIn/Out/Up/Down`. If they are missing, that movement is skipped without errors.

## The scene

- Three-quarter shot, slightly from above, Ciro sitting at the desk. It takes about 55% of the height of the area to the right of the panel. Below, the subtitles stay.
- Desk, cup and monitors built in the code with simple geometries and soft materials (dark wood, ceramic, black frames with a light-blue edge).
- Each monitor shows the project name and its status (at work, stopped, waiting for you), drawn on a canvas texture. At most 6 fit in a crown around the desk; beyond 6, a «+N» card.
- Lights: a warm and soft key light on the face, a light-blue rim light from behind, a low ambient light. Soft shadows only on the desk.
- When off: lights at 30%, Ciro relaxed leaning back, «Acceso» ("On") button clearly visible.

## States and animations

In the page there is only one main state at a time. The decorative gestures overlap only while idle and stop at any change of state.

| Real event (where it is born) | State | Animation |
|---|---|---|
| `accendi()`, no activity | idle | breathes, blinks every 2–6 s, small posture changes every 20–40 s |
| `esaminaMicrofono` detects voice (`parlando=true`) | listening | mouth closed, gaze towards the camera, torso forward by about 4° |
| `impostaFase("penso")` (transcription or model) | processing | gaze to a side monitor, eyebrows slightly frowned |
| `riproduci()` (real audio going out) | speaking | `jawOpen` and `mouthFunnel` from the audio level (`livelloVoce`), small head and hand gestures |
| `interrompiCiro()` | listening | in the same frame: mouth at zero, speaking gestures cancelled, then listening |
| notice from the server (`/api/messaggi`, type notice, project X) | attention | looks at X's monitor (0.6 s), turns towards the camera, raises the right hand a little; it lasts until the next change of state, at most 8 s; X's monitor stays highlighted as long as the question is open *(my choice)* |
| brain answer with a pending action (`azione_in_attesa`) | confirmation | waiting posture, hands together; card with recipient and text and Conferma/Annulla buttons |
| answer with `mandato: true` | sent | brief nod; light-blue tick on the recipient's monitor for 2 s |
| real error (voice, listening, brain, microphone, failed send) | error | puzzled expression (raised eyebrow), clear message below Ciro for 6 s |
| `spegni()` | off | relaxes, scene at 30% light, no gesture |

Distinct indicators, always visible next to the On/Off button:
- on/off;
- microphone active/disabled (key M);
- voice muted (file `muto`, already known to the page from `/api/messaggi`).

With the voice muted the answer appears only in the subtitles and the mouth does not move.

Occasional gestures: glasses, sip of coffee, stretching.
- Only while idle, at most one every 2–4 minutes.
- They last 2–4 s.
- They are cancelled in the frame in which the microphone detects voice or the state changes.

## Visible coordination

- The session monitors come from `/api/quadro`, to which the field `sessioni` is added (project, status, waiting), updated every 3 s as today.
- **Notices with project:** today the message queue carries only the text. Each item becomes `{testo, da, tipo: "avviso", progetto, opzioni}`. `opzioni` is derived on the server from the short sentence of the notice (format «A, …; B, …; C, …»).
- **A/B/C buttons:**
  - they appear under the subtitles together with the notice;
  - on click they send «A per <progetto>» (or B, C) to `/api/cervello`, the same path as the voice: naming the project avoids ambiguity if more than one question is open *(my choice)*. The model has the notice in its context, so the answer leaves immediately towards that session, as today;
  - after the first click they are all disabled until the answer arrives;
  - on the server, `domande_aperte` is emptied at the first send, so a second «A» no longer finds the open question and asks for confirmation instead of sending;
  - every group of buttons has an identifier: a click with an identifier already used is ignored.
- **Confirmation card:**
  - `/api/cervello` also returns `in_attesa: {a, testo}` when there is an action to confirm;
  - Conferma sends «sì», Annulla sends «no», on the same path;
  - it disappears when the outcome arrives.
- **No invented success:** the tick and the nod start only from `mandato: true`, that is when `posta.py invia` exited without errors.

## Smoothness, accessibility, performance

- Drawing loop at 30 frames per second during listening, speaking and attention, at 15 while idle, stopped when the tab is hidden (`visibilitychange`). Pixel ratio at most 1.5.
- Audio and microphone stay on their own loop (`AudioContext`, `ScriptProcessor`): 3D reads the values and never conditions them.
- **Movimenti ridotti** ("Reduced motion"): switch in the panel, remembered in the browser (`localStorage`). Mouth, eyelids and gaze remain, at 50%; gestures, posture changes and camera oscillations disappear. It starts on by itself if the system asks for `prefers-reduced-motion`.
- **Static version:** if WebGL is missing or the model does not load within 10 s, the page shows `ciro-statico.png` in the pose of the current state, with the same indicators, subtitles, buttons and confirmation card. The error goes into the log.
- After the automatic refresh these come back: on/off, microphone, open chat (`sessionStorage`, as today) and Movimenti ridotti ("Reduced motion") (`localStorage`).

## Order of work

1. **Test scene** (`prova3d.html`, separate from the real page):
   - avatar loaded, shot and lights;
   - five states: idle, listening, processing, speaking (on a Kokoro test audio), attention;
   - test buttons to move from one state to another.

   The user looks at it and approves it before going on.
2. **Connection to real events** in the real page: states, interruption, errors, off, muted voice, microphone. The SVG panel stays as a fallback version until the 3D one is approved.
3. **Desk and monitors** with the real projects, notices with project, A/B/C buttons, confirmation card, send tick.
4. **Occasional gestures, Movimenti ridotti, static version**, performance finishing.

## Checks

- **Interruption:** with real audio and a test voice from the microphone, the mouth (`jawOpen`) returns to zero within 1 frame from `interrompiCiro()` and the audio is stopped in the same cycle. It is measured in the page and written into the log.
- **Buttons:**
  - a quick double click, a click after the answer and a click on an old group produce a single send;
  - the send is checked by replacing `_invia` in a test: no real messages to the sessions.
- **Confirmation:** Conferma and Annulla follow the same rules as the voice confirmations (test on the brain).
- **Reload:** after a new version the state, microphone, chat and Movimenti ridotti ("Reduced motion") remain.
- **Real successes:** no tick without `mandato: true` (test with `_invia` failing).
- **Performance:** while idle, consumption of the browser process measured with Activity Monitor, target under 15% of one core. With the tab hidden, no frame drawn.
- **Fallback:** with WebGL disabled or the model missing the static version appears and everything else works.

## Left to whoever builds it

- Exact values of angles, timings and shades, as long as they stay sober.
- Precise layout of the monitors and of the cup.
- How to write the performance log.
- Correspondence between the model names and the movements, once the real file is seen.

## What is needed from the user

1. Create the avatar on Avaturn and export it (step-by-step instructions at the right moment).
2. Look at and approve the test scene before the connection to the events.
