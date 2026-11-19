// Faccia parlante: ascolta dal microfono (whisper sul Mac), parla con la voce
// Kokoro e muove la bocca seguendo il suono vero. Nessun servizio esterno.
"use strict";

const scena = document.getElementById("scena");
const bocca = document.getElementById("bocca");
const sorriso = document.getElementById("sorriso");
const cranio = document.getElementById("cranio");
const testa = document.getElementById("testa");
const occhioSx = document.getElementById("occhio-sx");
const occhioDx = document.getElementById("occhio-dx");
const pupillaSx = document.getElementById("pupilla-sx");
const pupillaDx = document.getElementById("pupilla-dx");
const sopracciglia = document.getElementById("sopracciglia");
const stato = document.getElementById("stato");
const avvio = document.getElementById("avvio");
const bottoneAvvio = document.getElementById("bottone-avvio");
const chat = document.getElementById("chat");
const chatLista = document.getElementById("chat-lista");
const chatForm = document.getElementById("chat-form");
const chatTesto = document.getElementById("chat-testo");
const apriChat = document.getElementById("apri-chat");
const chiudiChat = document.getElementById("chiudi-chat");
const interruttore = document.getElementById("interruttore");
const interruttoreTesto = document.getElementById("interruttore-testo");
const pannelloConsumi = document.getElementById("pannello-consumi");

// ---------------------------------------------------------------- animazione
let fase = "pronto";        // pronto | ascolto | penso | parlo
let livelloVoce = 0;        // 0..1 ampiezza della voce in uscita
let livelloMicrofono = 0;   // 0..1 ampiezza di chi parla
let apertura = 0;           // apertura bocca morbida
let blink = 1;              // 1 occhi aperti, 0 chiusi
let prossimoBlink = performance.now() + 2200;
let sguardo = { x: 0, y: 0 };
let sguardoBersaglio = { x: 0, y: 0 };

// ---------------------------------------------------------- accesa / dorme
let sveglia = false;                     // false: dorme
let ultimaAttivita = performance.now();
let richiami = 0;                        // promemoria fatti da quando si e' svegliato
const ATTESA_RICHIAMO = 5 * 60 * 1000;   // cinque minuti senza essere usata
const FRASI_RICHIAMO = [
  "Sono qui, mi hai lasciato acceso.",
  "Ehi, ci sei? Sono ancora sveglio.",
  "Ti ricordo che sono acceso: se non ti servo, spegnimi.",
];
// «Ehi Ciro»: di base Ciro risponde solo se lo chiami per nome; dopo che ha
// parlato (o dopo il suo nome) la conversazione resta aperta 15 secondi.
// Il pulsante «Ascolto» passa a «sempre in ascolto», come prima.
const FINESTRA_CONVERSAZIONE = 15000;
let modoAscolto = "nome";   // "nome" | "sempre"
try { if (localStorage.getItem("ciro-ascolto") === "sempre") modoAscolto = "sempre"; } catch (errore) { /* resta "nome" */ }
let finestraFino = 0;
function serveNome() {
  return modoAscolto === "nome" && !calibrando && performance.now() > finestraFino;
}
function apriFinestra() {
  finestraFino = performance.now() + FINESTRA_CONVERSAZIONE;
  aggiornaStatoAscolto();
}
function aggiornaStatoAscolto() {
  if (sveglia && fase === "ascolto") stato.textContent = T(serveNome() ? "Di' «Ciro»" : "Ti ascolto");
}
setInterval(aggiornaStatoAscolto, 1000);
let inclinazione = 0;
let inclinazioneBersaglio = 0;
let spostamentoX = 0;
let spostamentoXBersaglio = 0;
let prossimoMovimento = 0;
scena.classList.add("dorme"); // si parte spenta, sotto la scheda "Inizia"

function disegnaBocca(ap, larghezza) {
  const cx = 210, cy = 208, hw = 30 * larghezza;
  const altezza = 2 + ap * 22;
  const sotto = cy + altezza * 1.45;
  const sopra = cy - altezza * 0.5;
  bocca.setAttribute(
    "d",
    `M ${cx - hw} ${cy} Q ${cx} ${sotto} ${cx + hw} ${cy} Q ${cx} ${sopra} ${cx - hw} ${cy} Z`
  );
  // la linea del sorriso si vede solo a bocca chiusa
  sorriso.style.opacity = Math.max(0, 1 - ap * 7).toFixed(2);
}

function impostaFase(nuova) {
  if (!sveglia) {
    scena.classList.remove("ascolta", "parla");
    stato.textContent = T("Dormo…");
    return;
  }
  if (fase === nuova) return;
  fase = nuova;
  scena.classList.toggle("ascolta", nuova === "ascolto");
  scena.classList.toggle("parla", nuova === "parlo");
  sopracciglia.classList.toggle("su", nuova === "ascolto" || nuova === "penso");
  stato.textContent = T(nuova === "ascolto" && serveNome() ? "Di' «Ciro»" : {
    pronto: "Pronto",
    ascolto: "Ti ascolto",
    penso: "Un attimo",
    parlo: "Parlo io",
  }[nuova]);
}

function anima(adesso) {
  // respiro: quando dorme e' piu' lento e piu' profondo
  const respiro = 1 + Math.sin(adesso / (sveglia ? 2200 : 4600)) * (sveglia ? 0.006 : 0.009);
  const oscillazione = Math.sin(adesso / (sveglia ? 3400 : 5200)) * (sveglia ? 1.6 : 2.4);

  // testa: piccoli movimenti per attirare l'attenzione, o appoggiata quando dorme
  if (!sveglia) {
    inclinazioneBersaglio = -5;
    spostamentoXBersaglio = 0;
  } else if (adesso > prossimoMovimento) {
    inclinazioneBersaglio = (Math.random() * 2 - 1) * 2.6;
    spostamentoXBersaglio = (Math.random() * 2 - 1) * 3.5;
    prossimoMovimento = adesso + 2600 + Math.random() * 4200;
  }
  const morbidezza = sveglia ? 0.035 : 0.02;
  inclinazione += (inclinazioneBersaglio - inclinazione) * morbidezza;
  spostamentoX += (spostamentoXBersaglio - spostamentoX) * morbidezza;

  // bocca: segue la voce, oppure il microfono, oppure resta chiusa
  let bersaglio = 0;
  if (!sveglia) bersaglio = 0;
  else if (fase === "parlo") bersaglio = Math.min(1, livelloVoce * 1.25);
  // mentre ascolta la bocca resta ferma: si muove solo quando parla Ciro
  else if (fase === "penso") bersaglio = 0.12 + Math.sin(adesso / 260) * 0.05;

  // attacco rapido, rilascio morbido: si vede la bocca muoversi sulle sillabe
  const velocita = bersaglio > apertura ? 0.55 : 0.28;
  apertura += (bersaglio - apertura) * velocita;

  const larghezza = fase === "pronto" || !sveglia ? 1 : 1 + apertura * 0.12;
  disegnaBocca(apertura, larghezza);

  // occhi: sguardo che insegue il mouse, ammicco ogni tanto
  sguardo.x += (sguardoBersaglio.x - sguardo.x) * 0.12;
  sguardo.y += (sguardoBersaglio.y - sguardo.y) * 0.12;
  const s = `translate(${sguardo.x}px, ${sguardo.y}px)`;
  pupillaSx.style.transform = s;
  pupillaDx.style.transform = s;

  if (sveglia && adesso > prossimoBlink && fase !== "parlo") {
    blink = 0;
    if (adesso > prossimoBlink + 110) {
      blink = 1;
      prossimoBlink = adesso + 2400 + Math.random() * 3800;
    }
  }
  const aperturaOcchi = sveglia
    ? Math.max(0.05, blink) * (fase === "ascolto" ? 1.06 : 1)
    : 0.05;
  occhioSx.style.transform = `scale(1, ${aperturaOcchi})`;
  occhioDx.style.transform = `scale(1, ${aperturaOcchi})`;

  const abbassamento = sveglia ? 0 : 5;
  testa.setAttribute(
    "transform",
    `translate(${spostamentoX.toFixed(2)} ${(oscillazione + abbassamento).toFixed(2)}) ` +
      `rotate(${inclinazione.toFixed(2)} 210 250) scale(${respiro.toFixed(4)})`
  );
  requestAnimationFrame(anima);
}

requestAnimationFrame(anima);

// ------------------------------------------------------------- audio in uscita
const ctxUscita = new (window.AudioContext || window.webkitAudioContext)();
const analizzatore = ctxUscita.createAnalyser();
analizzatore.fftSize = 1024;
analizzatore.smoothingTimeConstant = 0.55;
analizzatore.connect(ctxUscita.destination);
let campioniUscita = new Uint8Array(analizzatore.fftSize);
let sorgente = null;

function leggiUscita() {
  if (fase !== "parlo") {
    livelloVoce *= 0.9;
    return;
  }
  analizzatore.getByteTimeDomainData(campioniUscita);
  let somma = 0;
  for (let i = 0; i < campioniUscita.length; i++) {
    const v = (campioniUscita[i] - 128) / 128;
    somma += v * v;
  }
  const rms = Math.sqrt(somma / campioniUscita.length);
  livelloVoce += (Math.min(1, rms * 4.2) - livelloVoce) * 0.5;
}

const orologioUscita = setInterval(leggiUscita, 33);

// --------------------------------------------- registro degli eventi (bug)
// Tutto finisce in ~/.config/faccia/conversazioni.log insieme a quello che
// Ciro sente e dice: con l'ora del problema si ricostruisce cosa e' successo.
function evento(tipo, dettaglio) {
  try {
    fetch("/api/evento", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tipo, dettaglio: String(dettaglio || "") }),
      keepalive: true,
    }).catch(() => {});
  } catch (errore) { /* il registro non deve mai fermare Ciro */ }
}

// ------------------------------------------------------------- coda della voce
const coda = [];
let inCorso = false;

// sottotitoli sotto il personaggio: l'ultima frase tua e l'ultima di Ciro
function sottotitolo(chi, testo) {
  const riga = document.getElementById(chi === "io" ? "sotto-tu" : "sotto-ciro");
  if (!riga) return;
  const pulito = (testo || "").trim();
  riga.querySelector("span").textContent = pulito;
  riga.classList.toggle("vuoto", !pulito);
}

// Divide in frasi: la prima parte subito, le altre si preparano mentre parla.
// I pezzi molto corti si uniscono al seguente (la voce resta naturale).
function dividiFrasi(testo) {
  if (testo.length <= 160) return [testo]; // le risposte brevi restano intere: suonano meglio
  const pezzi = testo.split(/(?<=[.!?…])\s+/).map((p) => p.trim()).filter(Boolean);
  const frasi = [];
  for (const pezzo of pezzi) {
    if (frasi.length > 1 && frasi[frasi.length - 1].length < 25) frasi[frasi.length - 1] += " " + pezzo;
    else frasi.push(pezzo);
  }
  return frasi.length ? frasi : [testo];
}

function caricaVoce(testo) {
  const promessa = fetch("/api/parla", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ testo }),
  }).then((risposta) => {
    if (!risposta.ok) throw new Error("voce non disponibile");
    return risposta.arrayBuffer();
  }).then((byte) => ctxUscita.decodeAudioData(byte));
  promessa.catch(() => {}); // se viene scartata (interruzione) non e' un errore
  return promessa;
}

function di(testo) {
  const pulito = (testo || "").trim();
  if (pulito && (sveglia || muto)) sottotitolo("ciro", pulito); // anche se zitto: la leggi
  if (!pulito || !sveglia || muto) return; // spento o zitto: resta solo nella chat
  for (const frase of dividiFrasi(pulito)) coda.push({ testo: frase, audio: null });
  if (!inCorso) prossimo();
}

async function prossimo() {
  if (!coda.length) {
    inCorso = false;
    if (sveglia) apriFinestra();   // ha appena parlato: puoi rispondere senza «Ciro»
    if (fase === "parlo") impostaFase(micAttivo ? "ascolto" : "pronto");
    return;
  }
  inCorso = true;
  const voce = coda.shift();
  if (!voce.audio) voce.audio = caricaVoce(voce.testo);
  if (coda.length && !coda[0].audio) coda[0].audio = caricaVoce(coda[0].testo); // la prossima, intanto
  try {
    const audio = await voce.audio;
    await riproduci(audio);
  } catch (errore) {
    console.warn(errore);
    evento("errore-voce", errore && errore.message);
    stato.textContent = T("Voce non disponibile");
  }
  prossimo();
}

function riproduci(audio) {
  return new Promise((risolvi) => {
    impostaFase("parlo");
    sospeso = true; // mentre parla il microfono ascolta solo per le interruzioni
    inizioVoceCiro = performance.now();
    eco = ecoCalibrata || 0;
    fotogrammiSopra = 0;
    misuraSospeso = { massimo: 0, soglia: 0, sopra: 0 };
    sorgente = ctxUscita.createBufferSource();
    sorgente.buffer = audio;
    sorgente.connect(analizzatore);
    sorgente.onended = () => {
      if (misuraSospeso.massimo > 0) {
        evento("mic-mentre-parla", `max ${misuraSospeso.massimo.toFixed(4)} soglia ${misuraSospeso.soglia.toFixed(4)} ` +
          `fotogrammi sopra ${misuraSospeso.sopra} eco ${eco.toFixed(3)} rumore ${rumore.toFixed(4)}`);
      }
      sorgente = null;
      sospeso = false;
      livelloVoce = 0;
      risolvi();
    };
    sorgente.start();
  });
}

// ------------------------------------------------------ fischi e richiami
let muto = false; // voce spenta dal Mac (~/.config/faccia/muto)

function fischia() {
  if (!sveglia || muto) return;
  const adesso = ctxUscita.currentTime;
  const oscillatore = ctxUscita.createOscillator();
  const volume = ctxUscita.createGain();
  oscillatore.type = "sine";
  oscillatore.frequency.setValueAtTime(1150, adesso);
  oscillatore.frequency.exponentialRampToValueAtTime(1680, adesso + 0.14);
  oscillatore.frequency.exponentialRampToValueAtTime(1380, adesso + 0.3);
  volume.gain.setValueAtTime(0.0001, adesso);
  volume.gain.linearRampToValueAtTime(0.07, adesso + 0.05);
  volume.gain.exponentialRampToValueAtTime(0.0001, adesso + 0.36);
  oscillatore.connect(volume).connect(ctxUscita.destination);
  oscillatore.start(adesso);
  oscillatore.stop(adesso + 0.38);
  // piccolo scatto della testa, così si nota anche senza audio
  inclinazioneBersaglio = (Math.random() * 2 - 1) * 5;
  spostamentoXBersaglio = (Math.random() * 2 - 1) * 4;
}

function segnalaAttivita() {
  ultimaAttivita = performance.now();
  richiami = 0;
}

function controllaInattivita() {
  if (!sveglia) return;
  if (performance.now() - ultimaAttivita < ATTESA_RICHIAMO) return;
  ultimaAttivita = performance.now();
  if (richiami % 2 === 0) {
    fischia(); // primo richiamo: fischio breve
  } else {
    const frase = FRASI_RICHIAMO[Math.floor(richiami / 2) % FRASI_RICHIAMO.length];
    di(T(frase)); // poi anche a voce, se continua a non essere usata
  }
  richiami++;
}

setInterval(controllaInattivita, 3000);

// ------------------------------------------------------ accesa / dorme
function accendi(saluta) {
  if (sveglia) return;
  sveglia = true;
  evento("acceso", saluta === false ? "senza saluto" : "");
  interruttore.classList.add("acceso");
  interruttore.setAttribute("aria-pressed", "true");
  interruttoreTesto.textContent = T("Acceso");
  scena.classList.remove("dorme");
  segnalaAttivita();
  impostaFase("ascolto");
  ctxUscita.resume().catch(() => {});
  accendiMicrofono().catch((errore) => {
    evento("errore-microfono", errore && errore.message);
    stato.textContent = T("Microfono non disponibile");
  });
  if (saluta !== false) di(T("Eccomi, sono sveglio."));
}

function spegni() {
  if (!sveglia) return;
  sveglia = false;
  evento("spento", "");
  interruttore.classList.remove("acceso");
  interruttore.setAttribute("aria-pressed", "false");
  interruttoreTesto.textContent = T("Spento");
  scena.classList.add("dorme");
  coda.length = 0; // niente frasi in sospeso mentre dorme
  if (sorgente) {
    try { sorgente.stop(); } catch (errore) { /* gia' finita */ }
  }
  spegniMicrofono();
  sospeso = false;
  attesaInvio = false;
  parlando = false;
  fase = "pronto";
  stato.textContent = T("Dormo…");
}

interruttore.addEventListener("click", () => {
  if (sveglia) spegni();
  else accendi();
});

// ----------------------------------------------------------------- microfono
const FREQUENZA = 16000;
let micAttivo = false;
let ctxRec = null;
let flusso = null;
let nodoRec = null;
let sospeso = false;      // true mentre la faccia parla
let bufferIngresso = [];  // pezzi Float32 del discorso in corso
let parlando = false;
let ultimoSuono = 0;
let inizioDiscorso = 0;
let rumore = 0.004;
let rumoreAppreso = 0;    // livello dei falsi allarmi: riscende piano (~3 minuti)
let sogliaCalibrata = null; // dalla calibrazione guidata («Ciro, calibrati»)
let calibrando = false;     // durante la calibrazione: niente ricariche e niente soglie apprese
let fineFrase = 900;        // ms di silenzio per dire che hai finito (profilo voce)
let ecoCalibrata = 0;       // eco della voce di Ciro nel microfono (profilo voce)
let pauseDiscorso = [];     // pause dentro la frase in corso, in ms (per il profilo voce)
let misurando = null;       // campioni del silenzio mentre la calibrazione lo misura
let attesaInvio = false;
let filaForte = 0;        // fotogrammi di fila sopra la soglia (128 ms l'uno)
let voceVera = false;     // nel discorso c'e' un suono continuo, non solo clic
const PRE_ROLL = [];      // 350 ms prima che si capisca che stai parlando

async function accendiMicrofono() {
  if (micAttivo) return;
  flusso = await navigator.mediaDevices.getUserMedia({
    audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 },
  });
  ctxRec = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: FREQUENZA });
  await ctxRec.resume();
  const sorgenteMic = ctxRec.createMediaStreamSource(flusso);
  nodoRec = ctxRec.createScriptProcessor(2048, 1, 1);
  nodoRec.onaudioprocess = (evento) => {
    const dati = evento.inputBuffer.getChannelData(0);
    esaminaMicrofono(dati);
  };
  sorgenteMic.connect(nodoRec);
  nodoRec.connect(ctxRec.destination); // serve al browser per far girare il nodo
  micAttivo = true;
  impostaFase("ascolto");
}

function esaminaMicrofono(dati) {
  let somma = 0;
  for (let i = 0; i < dati.length; i++) somma += dati[i] * dati[i];
  const rms = Math.sqrt(somma / dati.length);
  const adesso = performance.now();

  if (sospeso) {
    // Ciro sta parlando: il microfono resta acceso per sentire se lo interrompi.
    // La sua voce rientra un po' dagli altoparlanti (eco): la soglia sale con
    // il volume di Ciro e con l'eco misurata all'inizio di ogni sua frase.
    PRE_ROLL.push(new Float32Array(dati));
    if (PRE_ROLL.length > 12) PRE_ROLL.shift();
    livelloMicrofono *= 0.85;
    const daQuando = adesso - inizioVoceCiro;
    if (daQuando < 600) {
      if (livelloVoce > 0.05) eco = Math.max(eco, rms / livelloVoce);
      return;
    }
    const sogliaInterruzione = Math.max(0.03, rumore * 8, eco * livelloVoce * 1.8);
    // diagnosi: quanto forte arriva il microfono mentre Ciro parla
    if (rms > misuraSospeso.massimo) {
      misuraSospeso.massimo = rms;
      misuraSospeso.soglia = sogliaInterruzione;
    }
    misuraSospeso.sopra = Math.max(misuraSospeso.sopra, rms > sogliaInterruzione ? fotogrammiSopra + 1 : 0);
    fotogrammiSopra = rms > sogliaInterruzione ? fotogrammiSopra + 1 : 0;
    if (fotogrammiSopra >= 3) interrompiCiro(adesso); // circa 0,4 s di voce tua
    return;
  }
  if (attesaInvio) {
    livelloMicrofono *= 0.85;
    return;
  }

  livelloMicrofono += (Math.min(1, rms * 6) - livelloMicrofono) * 0.35;
  rumoreAppreso *= 0.9995; // circa 8 fotogrammi al secondo
  if (misurando) { // calibrazione: misuro il silenzio, non ascolto frasi
    misurando.push(rms);
    return;
  }
  const soglia = Math.max(sogliaCalibrata || 0.011, rumore * 3, rumoreAppreso * 3);

  if (!parlando && rms < soglia) {
    rumore = rumore * 0.98 + rms * 0.02; // impara il rumore di fondo
  }

  if (!parlando && rms > soglia) {
    parlando = true;
    inizioDiscorso = adesso;
    bufferIngresso = PRE_ROLL.slice();
    ultimoSuono = adesso;
    filaForte = 0;
    voceVera = false;
    pauseDiscorso = [];
    segnalaAttivita();
  }

  if (parlando) {
    bufferIngresso.push(new Float32Array(dati));
    // la voce dura almeno 2 fotogrammi di fila (~0,25 s); un clic della
    // tastiera no: i clic non tengono aperto l'ascolto
    filaForte = rms > soglia ? filaForte + 1 : 0;
    if (filaForte >= 2) {
      const pausa = adesso - ultimoSuono - 128; // un fotogramma e' ancora voce
      if (voceVera && pausa > 120) pauseDiscorso.push(Math.round(pausa));
      ultimoSuono = adesso;
      voceVera = true;
    }
    const troppoLungo = adesso - inizioDiscorso > 30000;
    if (adesso - ultimoSuono > fineFrase || troppoLungo) {
      parlando = false;
      const pezzi = bufferIngresso;
      bufferIngresso = [];
      PRE_ROLL.length = 0;
      if (!voceVera) {
        evento("rumore-ignorato", "solo clic o colpi brevi");
        return;
      }
      attesaInvio = true;
      inviaDiscorso(pezzi, pauseDiscorso.slice()).finally(() => {
        attesaInvio = false;
      });
    }
  } else {
    PRE_ROLL.push(new Float32Array(dati));
    if (PRE_ROLL.length > 12) PRE_ROLL.shift();
  }
}

// Lo interrompi: smette subito di parlare, butta le frasi in coda e ascolta.
let eco = 0;
let fotogrammiSopra = 0;
let misuraSospeso = { massimo: 0, soglia: 0, sopra: 0 };
let interrottoAlle = 0;   // la prossima frase arriva subito dopo un'interruzione
let inizioVoceCiro = 0;

function interrompiCiro(adesso) {
  evento("interruzione", "eco " + eco.toFixed(3) + ", frasi scartate " + coda.length);
  interrottoAlle = adesso;
  apriFinestra();   // chi interrompe sta gia' parlando con Ciro
  fotogrammiSopra = 0;
  coda.length = 0;
  if (sorgente) {
    try { sorgente.stop(); } catch (errore) { /* gia' finita */ }
  }
  sospeso = false;
  livelloVoce = 0;
  impostaFase("ascolto");
  parlando = true;               // il tuo discorso e' gia' cominciato
  inizioDiscorso = adesso;
  ultimoSuono = adesso;
  bufferIngresso = PRE_ROLL.slice();
  segnalaAttivita();
}

function codificaWav(pezzi, frequenza) {
  let totale = 0;
  for (const p of pezzi) totale += p.length;
  const dati = new Float32Array(totale);
  let posizione = 0;
  for (const p of pezzi) {
    dati.set(p, posizione);
    posizione += p.length;
  }
  const buffer = new ArrayBuffer(44 + totale * 2);
  const vista = new DataView(buffer);
  const scrivi = (offset, testo) => {
    for (let i = 0; i < testo.length; i++) vista.setUint8(offset + i, testo.charCodeAt(i));
  };
  scrivi(0, "RIFF");
  vista.setUint32(4, 36 + totale * 2, true);
  scrivi(8, "WAVE");
  scrivi(12, "fmt ");
  vista.setUint32(16, 16, true);
  vista.setUint16(20, 1, true);
  vista.setUint16(22, 1, true);
  vista.setUint32(24, frequenza, true);
  vista.setUint32(28, frequenza * 2, true);
  vista.setUint16(32, 2, true);
  vista.setUint16(34, 16, true);
  scrivi(36, "data");
  vista.setUint32(40, totale * 2, true);
  let offset = 44;
  for (let i = 0; i < totale; i++, offset += 2) {
    const v = Math.max(-1, Math.min(1, dati[i]));
    vista.setInt16(offset, v < 0 ? v * 0x8000 : v * 0x7fff, true);
  }
  return buffer;
}

async function inviaDiscorso(pezzi, pause) {
  if (!pezzi.length || !ctxRec) return;
  const campioni = pezzi.reduce((totale, p) => totale + p.length, 0);
  if (campioni < ctxRec.sampleRate * 0.6) { // meno di 0,6 s: un rumore, non una frase
    evento("rumore-ignorato", (campioni / ctxRec.sampleRate).toFixed(2) + " s");
    return;
  }
  const wav = codificaWav(pezzi, ctxRec.sampleRate);
  impostaFase("penso");
  try {
    // aspetta il nome: il server usa il modello grande, che sbaglia meno «Ciro»
    const risposta = await fetch(serveNome() ? "/api/ascolta?nome=1" : "/api/ascolta", {
      method: "POST",
      headers: { "Content-Type": "audio/wav" },
      body: wav,
    });
    if (!risposta.ok) throw new Error("trascrizione fallita");
    const dato = await risposta.json();
    let testo = dato.testo;
    let somma = 0;
    for (const pezzo of pezzi) for (let i = 0; i < pezzo.length; i++) somma += pezzo[i] * pezzo[i];
    const livello = Math.sqrt(somma / campioni);
    if (!testo || !testo.trim()) { // anche una lettera sola («a») e' una risposta
      // falso allarme: era rumore. La soglia sale al livello di quel rumore
      // (e riscende da sola quando la stanza torna silenziosa)
      const prima = rumoreAppreso;
      if (!calibrando) rumoreAppreso = Math.min(0.006, Math.max(rumoreAppreso, livello * 0.6));
      else azioneGuida("ripeti"); // in calibrazione una frase vuota si ripete subito
      if (rumoreAppreso > prima) evento("soglia-alzata", prima.toFixed(4) + " -> " + rumoreAppreso.toFixed(4));
      impostaFase("ascolto");
      return;
    }
    if (dato.chiamato) {           // «Ciro, …»: il nome apre la conversazione
      apriFinestra();
      if (!dato.resto) {           // solo «Ciro»: un fischio e ti ascolta
        evento("chiamato", "");
        fischia();
        sottotitolo("ciro", T("Dimmi."));
        impostaFase("ascolto");
        return;
      }
      testo = dato.resto;
    } else if (serveNome()) {      // non l'hai chiamato: rumore, tastiera, altre persone
      evento("ignorato-senza-nome", testo.slice(0, 60));
      impostaFase("ascolto");
      return;
    }
    aggiungiMessaggio("io", testo);
    impostaFase("ascolto");
    segnalaAttivita();
    await chiediAlCervello(testo, livello, pause);
  } catch (errore) {
    console.warn(errore);
    evento("errore-ascolto", errore && errore.message);
    stato.textContent = T("Non ho capito");
    setTimeout(() => impostaFase(micAttivo ? "ascolto" : "pronto"), 1500);
  }
}

// Il cervello: OpenCode con il quadro delle sessioni e della posta.
async function chiediAlCervello(testo, livello, pause) {
  impostaFase("penso");
  try {
    const risposta = await fetch("/api/cervello", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ testo, livello: livello || null, pause: pause || [],
                             interrotto: performance.now() - interrottoAlle < 15000 }),
    });
    if (!risposta.ok) throw new Error("cervello non disponibile");
    const dato = await risposta.json();
    const frase = (dato.risposta || "").trim();
    if (!frase) { // solo un grazie o un saluto: Ciro non risponde
      sottotitolo("ciro", "");
      impostaFase(micAttivo ? "ascolto" : "pronto");
      return;
    }
    aggiungiMessaggio("lui", frase);
    di(frase);
    eseguiComando(dato);
    aggiornaQuadro();
  } catch (errore) {
    console.warn(errore);
    evento("errore-cervello", errore && errore.message);
    di(rispostaProvvisoria(testo));
  }
}

// Risposta di riserva, se il cervello non risponde.
function rispostaProvvisoria(testo) {
  const pulito = testo.trim().replace(/\s+/g, " ");
  if (/\?\s*$/.test(pulito)) {
    return T("In questo momento non riesco a pensare. Riprova tra un attimo.");
  }
  return T("Ho sentito: ") + pulito;
}

// ------------------------------------------------------------------- la chat
function aggiungiMessaggio(chi, testo) {
  if (chi === "io") {
    sottotitolo("io", testo);
    sottotitolo("ciro", "…");
  }
  const riga = document.createElement("div");
  riga.className = "riga " + chi;
  const fumetto = document.createElement("div");
  fumetto.className = "fumetto";
  fumetto.textContent = testo;
  riga.appendChild(fumetto);
  chatLista.appendChild(riga);
  chatLista.scrollTop = chatLista.scrollHeight;
}

chatForm.addEventListener("submit", (evento) => {
  evento.preventDefault();
  const testo = chatTesto.value.trim();
  if (!testo) return;
  chatTesto.value = "";
  if (!sveglia) accendi(false); // scriverle la sveglia
  aggiungiMessaggio("io", testo);
  segnalaAttivita();
  chiediAlCervello(testo);
});

apriChat.addEventListener("click", () => {
  chat.classList.toggle("aperta");
  if (chat.classList.contains("aperta")) chatTesto.focus();
});

chiudiChat.addEventListener("click", () => chat.classList.remove("aperta"));

document.addEventListener("keydown", (evento) => {
  if (evento.key === "Escape") chat.classList.remove("aperta");
  if (document.activeElement === chatTesto) return;
  segnalaAttivita();
  const tasto = evento.key.toLowerCase();
  if (evento.metaKey || evento.ctrlKey) return;
  if (tasto === "s") {
    sveglia ? spegni() : accendi();
  } else if (tasto === "m") {
    if (!sveglia) accendi();
    else if (micAttivo) spegniMicrofono();
    else accendiMicrofono();
  }
});

document.addEventListener("pointerdown", segnalaAttivita);

function spegniMicrofono() {
  if (nodoRec) nodoRec.disconnect();
  if (flusso) flusso.getTracks().forEach((traccia) => traccia.stop());
  if (ctxRec) ctxRec.close().catch(() => {}); // Chrome regge pochi contesti audio
  nodoRec = null;
  flusso = null;
  ctxRec = null;
  parlando = false;
  bufferIngresso = [];
  PRE_ROLL.length = 0;
  micAttivo = false;
  impostaFase("pronto");
}

// ------------------------------------------------- fine dell'ascolto, avvio
bottoneAvvio.addEventListener("click", async () => {
  avvio.classList.remove("visibile");
  await ctxUscita.resume();
  // la prima volta che un utente usa Ciro parte la calibrazione (come la
  // configurazione di Siri); se la interrompe, riparte alla prossima sessione
  let primaVolta = false;
  try {
    const quadro = await (await fetch("/api/quadro", { cache: "no-store" })).json();
    primaVolta = !quadro.calibrato && !sessionStorage.getItem("ciro-prima-calibrazione");
  } catch (errore) { /* senza quadro si parte normalmente */ }
  if (!primaVolta) {
    accendi();
    return;
  }
  try { sessionStorage.setItem("ciro-prima-calibrazione", "1"); } catch (errore) { /* pazienza */ }
  accendi(false);
  di(T("È la prima volta che ci sentiamo: ti guido in una calibrazione di cinquanta secondi."));
  avviaCalibrazione();
});

// ------------------------------------------- aggiornamento automatico
// Quando arriva una versione nuova (file della pagina cambiati o server
// riavviato) la pagina si ricarica da sola, ma non mentre Ciro parla o pensa
// o mentre stai scrivendo; dopo il ricaricamento torna com'era.
const CHIAVE_RIAVVIO = "ciro-riavvio";
let versioneCaricata = null;

async function controllaVersione() {
  try {
    const risposta = await fetch("/api/versione", { cache: "no-store" });
    if (!risposta.ok) return;
    const { versione } = await risposta.json();
    if (versioneCaricata === null) {
      versioneCaricata = versione;
      return;
    }
    if (versione === versioneCaricata) return;
    const occupato = fase === "parlo" || fase === "penso" || inCorso || parlando ||
      (document.activeElement === chatTesto && chatTesto.value.trim());
    if (occupato || calibrando) return; // riprovo al giro dopo
    try {
      sessionStorage.setItem(CHIAVE_RIAVVIO, JSON.stringify({
        sveglia, microfono: micAttivo, chat: chat.classList.contains("aperta"),
      }));
    } catch (errore) { /* senza memoria del browser riparte dalla schermata iniziale */ }
    evento("ricarica", "versione " + versione);
    location.reload();
  } catch (errore) {
    /* server fermo o in riavvio: riprovo al giro dopo */
  }
}
setInterval(controllaVersione, 3000);
controllaVersione();

(function riprendiDopoAggiornamento() {
  let stato = null;
  try {
    stato = JSON.parse(sessionStorage.getItem(CHIAVE_RIAVVIO) || "null");
    sessionStorage.removeItem(CHIAVE_RIAVVIO);
  } catch (errore) { return; }
  if (!stato) return;
  avvio.classList.remove("visibile");
  if (stato.chat) chat.classList.add("aperta");
  if (!stato.sveglia) return;
  accendi(false);
  if (!stato.microfono) spegniMicrofono();
  // se il browser blocca l'audio senza un clic, riparte al primo clic o tasto
  ctxUscita.resume().catch(() => {});
  const sblocca = () => ctxUscita.resume().catch(() => {});
  window.addEventListener("pointerdown", sblocca, { once: true });
  window.addEventListener("keydown", sblocca, { once: true });
})();

// Il mouse sposta lo sguardo: la faccia sembra viva.
window.addEventListener("mousemove", (evento) => {
  const x = (evento.clientX / window.innerWidth - 0.5) * 8;
  const y = (evento.clientY / window.innerHeight - 0.5) * 6;
  sguardoBersaglio = { x: Math.max(-4, Math.min(4, x)), y: Math.max(-3, Math.min(3, y)) };
});

// ------------------------------------------------------------ pannello laterale
const pannelloAttese = document.getElementById("pannello-attese");
const contaAttese = document.getElementById("conta-attese");

function testoAttesa(secondi) {
  const minuti = Math.round((secondi || 0) / 60);
  if (minuti < 1) return T("adesso");
  if (minuti < 60) return T("da %d min", minuti);
  const ore = Math.floor(minuti / 60);
  return ore < 24 ? T("da %d h %d min", ore, minuti % 60) : T("da %d g", Math.floor(ore / 24));
}

function disegnaAttese(elenco) {
  pannelloAttese.innerHTML = "";
  contaAttese.textContent = elenco.length ? `(${elenco.length})` : "";
  if (!elenco.length) {
    const vuoto = document.createElement("li");
    vuoto.className = "vuoto";
    vuoto.textContent = T("nessuno: tutto in ordine");
    pannelloAttese.appendChild(vuoto);
    return;
  }
  for (const attesa of elenco) {
    const riga = document.createElement("li");
    const diChat = attesa.tipo === "chat";
    riga.className = "attesa " + (attesa.tipo === "domanda" ? "" : diChat ? "chat" : "posta") +
      (diChat && attesa.urgente ? " urgente" : "");
    riga.title = diChat ? (attesa.motivo || attesa.testo || "") : T("Clicca per rispondere a %s", attesa.progetto);
    const testa = document.createElement("div");
    testa.className = "attesa-testa";
    const progetto = document.createElement("b");
    // un messaggio di Google Chat: chi scrive al posto del progetto
    progetto.textContent = diChat ? (attesa.mittente || "?") : (attesa.progetto || "?");
    if (attesa.numero) {
      // il numero della domanda: a voce «tre, sì» invece del nome del progetto
      const numero = document.createElement("span");
      numero.className = "numero-domanda";
      numero.textContent = "#" + attesa.numero;
      progetto.prepend(numero);
    }
    const quando = document.createElement("span");
    const dove = diChat ? "Chat " + String(attesa.account || "").split("@").pop() : T(attesa.tipo);
    quando.textContent = `${dove} · ${testoAttesa(attesa.secondi)}`;
    testa.append(progetto, quando);
    const testo = document.createElement("p");
    testo.textContent = attesa.testo;
    riga.append(testa, testo);
    // domanda strutturata: un pulsante per opzione, la risposta parte subito
    const opzioni = Object.entries(attesa.opzioni || {});
    if (attesa.domanda_id && opzioni.length) {
      const pulsanti = document.createElement("div");
      pulsanti.className = "opzioni";
      for (const [lettera, spiegazione] of opzioni) {
        const pulsante = document.createElement("button");
        pulsante.type = "button";
        // come le dice la voce: numeri (le lettere si confondono), sì/no
        pulsante.textContent = { A: "1", B: "2", C: "3", D: "4", E: "5", S: T("Sì"), N: "No" }[lettera] || lettera;
        pulsante.title = spiegazione;
        pulsante.addEventListener("click", (evento) => {
          evento.stopPropagation();
          pulsanti.querySelectorAll("button").forEach((b) => { b.disabled = true; });
          chiediAlCervello(`${lettera} per ${attesa.progetto}`);
        });
        pulsanti.appendChild(pulsante);
      }
      riga.appendChild(pulsanti);
    }
    // clic: apre la chat pronta per rispondere a quella sessione tramite Ciro
    if (!diChat) riga.addEventListener("click", () => {
      chat.classList.add("aperta");
      chatTesto.value = T("Di' a %s: ", attesa.progetto);
      chatTesto.focus();
    });
    pannelloAttese.appendChild(riga);
  }
}

// ------------------------------------------- colonna destra: le sessioni
const pannelloSessioni = document.getElementById("pannello-sessioni");
const contaSessioni = document.getElementById("conta-sessioni");

function disegnaSessioni(elenco) {
  pannelloSessioni.innerHTML = "";
  contaSessioni.textContent = elenco.length ? `(${elenco.length})` : "";
  if (!elenco.length) {
    const vuoto = document.createElement("li");
    vuoto.className = "vuoto";
    vuoto.textContent = T("nessuna sessione aperta");
    pannelloSessioni.appendChild(vuoto);
    return;
  }
  for (const sessione of elenco) {
    const riga = document.createElement("li");
    riga.className = sessione.stato === "aspetta te" ? "attende" : sessione.stato === "al lavoro" ? "lavora" : "";
    const pallino = document.createElement("span");
    pallino.className = "pallino-sessione";
    const dati = document.createElement("div");
    dati.className = "dati";
    const nome = document.createElement("span");
    nome.className = "nome";
    if (sessione.proprietario) {
      // stesso proprietario, stessa tinta (chiara: il testo resta leggibile)
      riga.style.setProperty("--tinta", tintaDi(sessione.proprietario));
      riga.classList.add("con-proprietario");
      const proprietario = document.createElement("span");
      proprietario.className = "proprietario";
      proprietario.textContent = sessione.proprietario + "/";
      nome.append(proprietario, document.createTextNode(sessione.repo));
    } else {
      nome.textContent = sessione.titolo || sessione.progetto;
    }
    riga.title = (sessione.titolo || sessione.progetto) + " · " + T("cartella") + " " + sessione.progetto;
    const mini = document.createElement("span");
    mini.className = "mini";
    mini.textContent = `${T(sessione.stato)} · ${testoAttesa(sessione.secondi)}`;
    dati.append(nome, mini);
    if (sessione.sintesi) {
      const sintesi = document.createElement("span");
      sintesi.className = "domanda";
      sintesi.textContent = sessione.sintesi;
      dati.append(sintesi);
    }
    riga.append(pallino, dati);
    pannelloSessioni.appendChild(riga);
  }
  adattaSessioni();
}

function tintaDi(testo) {
  let h = 0;
  for (const c of testo.toLowerCase()) h = (h * 31 + c.charCodeAt(0)) % 360;
  return String(h);
}

// Tutte le sessioni sempre visibili, senza scorrere: prima riduco le righe di
// sintesi da 3 a 1, poi la grandezza del testo (da 15 px fino a 8 px).
const pannelloDestra = document.getElementById("pannello-destra");
function adattaSessioni() {
  const entra = () => pannelloSessioni.scrollHeight <= pannelloSessioni.clientHeight + 1;
  const prove = [];
  for (const righe of [3, 2]) prove.push([15, righe]);
  for (let px = 15; px >= 8; px -= 0.5) prove.push([px, 1]);
  for (const [px, righe] of prove) {
    pannelloSessioni.style.fontSize = px + "px";
    pannelloSessioni.style.setProperty("--righe", righe);
    if (entra()) return;
  }
}
window.addEventListener("resize", adattaSessioni);

// la colonna destra parte sotto i pulsanti in alto, anche se vanno a capo
const comandiAlto = document.getElementById("comandi-alto");
function adattaComandi() {
  const altezza = comandiAlto ? comandiAlto.getBoundingClientRect().bottom : 56;
  document.documentElement.style.setProperty("--sotto-comandi", Math.ceil(altezza + 20) + "px");
}
window.addEventListener("resize", adattaComandi);
if (window.ResizeObserver && comandiAlto) new ResizeObserver(adattaComandi).observe(comandiAlto);

// pausa progetti: Ciro non annuncia le sessioni (tranne i progetti permessi)
const pulsantePausa = document.getElementById("pausa-progetti");
function disegnaPausa(pausa) {
  const attiva = Boolean(pausa && pausa.attiva);
  pulsantePausa.classList.toggle("attiva", attiva);
  pulsantePausa.setAttribute("aria-pressed", String(attiva));
  const tranne = attiva && pausa.solo && pausa.solo.length ? " tranne " + pausa.solo.join(", ") : "";
  pulsantePausa.textContent = T(attiva ? "▶ Riprendi progetti" : "⏸ Pausa progetti");
  pulsantePausa.title = attiva
    ? T("Progetti in pausa") + (tranne ? T(" (parlano solo: %s)", pausa.solo.join(", ")) : "") + T(". Premi per riprendere.")
    : T("Ciro smette di annunciare le domande delle sessioni (restano nel pannello)");
  adattaComandi();
}
pulsantePausa.addEventListener("click", async () => {
  const attiva = !pulsantePausa.classList.contains("attiva");
  try {
    const risposta = await fetch("/api/pausa", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ attiva, solo: [] }),
    });
    if (risposta.ok) disegnaPausa(await risposta.json());
  } catch (errore) { /* riprovo al prossimo clic */ }
});

// modo di ascolto: «Ciro» (risponde solo se chiamato) o sempre in ascolto
const pulsanteAscolto = document.getElementById("modo-ascolto");
function disegnaModoAscolto() {
  pulsanteAscolto.textContent = T(modoAscolto === "nome" ? "Ascolto: «Ciro»" : "Ascolto: sempre");
  pulsanteAscolto.title = T(modoAscolto === "nome"
    ? "Ciro risponde solo se lo chiami per nome (e per 15 secondi dopo che ha parlato). Premi per tenerlo sempre in ascolto."
    : "Ciro ascolta tutto. Premi per farlo rispondere solo quando lo chiami «Ciro».");
  pulsanteAscolto.setAttribute("aria-pressed", String(modoAscolto === "sempre"));
  aggiornaStatoAscolto();
}
pulsanteAscolto.addEventListener("click", () => {
  modoAscolto = modoAscolto === "nome" ? "sempre" : "nome";
  try { localStorage.setItem("ciro-ascolto", modoAscolto); } catch (errore) { /* solo per questa pagina */ }
  evento("modo-ascolto", modoAscolto);
  disegnaModoAscolto();
});
disegnaModoAscolto();

// lingua: dal server (impostazione "lingua"); il pulsante IT/EN la cambia
const pulsanteLingua = document.getElementById("lingua");
function disegnaLingua(lingua) {
  if (lingua && lingua !== LINGUA) {
    applicaLingua(lingua);
    interruttoreTesto.textContent = T(sveglia ? "Acceso" : "Spento");
    const attuale = fase;
    fase = null; // ridisegna lo stato nella nuova lingua
    impostaFase(attuale);
  }
  pulsanteLingua.textContent = LINGUA === "en" ? "IT" : "EN";
  disegnaModoAscolto();
  pulsanteLingua.title = T("Passa all'inglese");
}
pulsanteLingua.addEventListener("click", async () => {
  try {
    await fetch("/api/lingua", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ lingua: LINGUA === "en" ? "it" : "en" }),
    });
  } catch (errore) { /* riprovo al prossimo clic */ }
  aggiornaQuadro();
});

// Pannello sinistro in una schermata, senza scorrere: prima rimpicciolisco i
// consumi (fino al 55%), poi anche «Ti aspettano» (fino al 70%).
const pannelloSinistro = document.getElementById("pannello");
function adattaPannello() {
  const consumi = document.getElementById("pannello-consumi");
  const attese = document.getElementById("pannello-attese");
  consumi.style.zoom = "";
  attese.style.zoom = "";
  // «Ti aspettano» prende lo spazio che resta e taglia cio' che non ci sta
  const entra = () => pannelloSinistro.scrollHeight <= pannelloSinistro.clientHeight + 1 &&
    attese.scrollHeight <= attese.clientHeight + 1;
  for (let z = 1; z >= 0.55 && !entra(); z -= 0.05) consumi.style.zoom = z.toFixed(2);
  for (let z = 1; z >= 0.7 && !entra(); z -= 0.05) attese.style.zoom = z.toFixed(2);
}
window.addEventListener("resize", adattaPannello);

function disegnaQuadro(dati) {
  disegnaLingua(dati.lingua);
  disegnaPausa(dati.pausa);
  disegnaGuida(dati.guida);
  const calibrata = dati.microfono && Number(dati.microfono.soglia);
  if (calibrata > 0) sogliaCalibrata = calibrata;
  const fine = dati.microfono && Number(dati.microfono.fine_frase_ms);
  if (fine >= 500 && fine <= 1500) fineFrase = fine;
  const ecoProfilo = dati.microfono && Number(dati.microfono.eco);
  if (ecoProfilo > 0) ecoCalibrata = ecoProfilo;
  disegnaConsumi(dati.consumi || []);
  disegnaAttese(dati.attese || []);
  disegnaSessioni(dati.sessioni || []);
  adattaPannello();
  // dopo un ricaricamento: una credenziale ancora chiesta riapre il campo
  const credenziale = (dati.attese || []).find((a) => a.operazione === "credenziali" && a.domanda_id);
  if (credenziale) mostraCredenziale(credenziale);
}

// ------------------------------------------------ campo per le credenziali
// Il valore va solo al server, che lo mette nel Portachiavi: non si dice,
// non si scrive nei sottotitoli e il campo si svuota subito dopo l'invio.
const moduloCredenziale = document.getElementById("credenziale");
const chiuseCredenziali = new Set();
let credenzialeAperta = null;

function mostraCredenziale(domanda) {
  if (credenzialeAperta === domanda.domanda_id || chiuseCredenziali.has(domanda.domanda_id)) return;
  credenzialeAperta = domanda.domanda_id;
  document.getElementById("credenziale-titolo").textContent =
    T("Credenziale per %s: %s", domanda.progetto || T("una sessione"), domanda.testo || "");
  document.getElementById("credenziale-prefisso").textContent = "ciro-" + (domanda.progetto || "") + "-";
  document.getElementById("credenziale-nome").value = domanda.nome_credenziale || "";
  document.getElementById("credenziale-valore").value = "";
  document.getElementById("credenziale-esito").textContent = "";
  moduloCredenziale.hidden = false;
  document.getElementById("credenziale-valore").focus();
}

function chiudiCredenziale() {
  document.getElementById("credenziale-valore").value = "";
  if (credenzialeAperta) chiuseCredenziali.add(credenzialeAperta);
  credenzialeAperta = null;
  moduloCredenziale.hidden = true;
}

document.getElementById("credenziale-chiudi").addEventListener("click", chiudiCredenziale);
moduloCredenziale.addEventListener("submit", async (evento) => {
  evento.preventDefault();
  const campo = document.getElementById("credenziale-valore");
  const esito = document.getElementById("credenziale-esito");
  const corpo = JSON.stringify({
    domanda_id: credenzialeAperta,
    nome: document.getElementById("credenziale-nome").value.trim(),
    valore: campo.value,
  });
  campo.value = "";
  esito.textContent = T("Salvo…");
  try {
    const risposta = await fetch("/api/credenziale", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: corpo,
    });
    const dati = await risposta.json().catch(() => ({}));
    if (risposta.ok) {
      chiudiCredenziale();
      aggiornaQuadro();
    } else {
      esito.textContent = T("Non salvata: %s. Riscrivila.", dati.errore || risposta.status);
    }
  } catch (errore) {
    esito.textContent = T("Il server non risponde. Riscrivila.");
  }
});

const NOMI_FONTI = {
  "claude-code": "Claude",
  "claude.ai": "Claude",
  "opencode-go": "OpenCode Go",
  deepseek: "DeepSeek",
};

function testoReset(reset) {
  if (!reset) return "";
  let data = null;
  if (/^\d+(\.\d+)?$/.test(reset)) {
    const numero = Number(reset);
    data = new Date(numero < 1e12 ? numero * 1000 : numero);
  } else if (/^\d{4}-\d{2}-\d{2}/.test(reset)) {
    data = new Date(reset);
  }
  if (!data || isNaN(data)) return reset; // gia' scritto a parole ("tra 3h 59m")
  const minuti = Math.round((data - Date.now()) / 60000);
  if (minuti <= 0) return T("reset ora");
  if (minuti < 60) return T("reset tra %d min", minuti);
  const ore = Math.floor(minuti / 60);
  if (ore < 48) return T("reset tra %d h %d min", ore, minuti % 60);
  return T("reset tra %d g %d h", Math.floor(ore / 24), ore % 24);
}

function testoEta(secondi) {
  if (!secondi) return "";
  const minuti = Math.round((Date.now() / 1000 - secondi) / 60);
  if (minuti < 2) return T("adesso");
  if (minuti < 60) return T("%d min fa", minuti);
  return T("%d h fa", Math.round(minuti / 60));
}

function disegnaConsumi(elenco) {
  pannelloConsumi.innerHTML = "";
  if (!elenco.length) {
    const vuoto = document.createElement("p");
    vuoto.className = "vuoto";
    vuoto.textContent = T("nessun dato ancora: apri una sessione Claude Code o installa l'estensione Chrome");
    pannelloConsumi.appendChild(vuoto);
    return;
  }
  for (const consumo of elenco) {
    const blocco = document.createElement("div");
    blocco.className = "consumo";
    const titolo = document.createElement("div");
    titolo.className = "consumo-titolo";
    const nome = document.createElement("span");
    nome.textContent = `${NOMI_FONTI[consumo.fonte] || consumo.fonte} · ${consumo.account || ""}`;
    const eta = document.createElement("span");
    eta.className = "eta";
    eta.textContent = testoEta(consumo.aggiornato);
    titolo.append(nome, eta);
    blocco.appendChild(titolo);

    for (const voce of consumo.voci || []) {
      const riga = document.createElement("div");
      riga.className = "barra-consumo";
      const etichetta = document.createElement("span");
      etichetta.textContent = T(voce.nome || "");
      const traccia = document.createElement("span");
      traccia.className = "traccia";
      // la barra mostra quanto resta: rossa dal 25% in giu', gialla dal 50%
      const pieno = document.createElement("span");
      const usato = Math.max(0, Math.min(100, Number(voce.percentuale) || 0));
      const resta = 100 - usato;
      pieno.style.width = resta + "%";
      if (resta <= 25) {
        pieno.className = "alto";
        riga.classList.add("in-esaurimento");
      } else if (resta <= 50) pieno.className = "medio";
      traccia.appendChild(pieno);
      const valore = document.createElement("b");
      valore.textContent = voce.percentuale == null ? "—" : Math.round(resta) + "%";
      const reset = document.createElement("small");
      reset.textContent = testoReset(voce.reset);
      riga.append(etichetta, traccia, valore, reset);
      blocco.appendChild(riga);
    }
    if (consumo.saldo) {
      const saldo = document.createElement("div");
      saldo.className = "voce";
      const etichetta = document.createElement("span");
      etichetta.textContent = T("Credito");
      const valore = document.createElement("b");
      valore.textContent = consumo.saldo;
      saldo.append(etichetta, valore);
      blocco.appendChild(saldo);
    }
    if (consumo.nota) {
      const nota = document.createElement("div");
      nota.className = "voce tenue";
      nota.textContent = consumo.nota;
      blocco.appendChild(nota);
    }
    pannelloConsumi.appendChild(blocco);
  }
  // gli account claude.ai arrivano solo dall'estensione Chrome
  const mancano = [];
  if (!elenco.some((c) => c.fonte === "claude.ai")) mancano.push(T("gli altri account Claude"));
  if (!elenco.some((c) => c.fonte === "opencode-go")) mancano.push("OpenCode Go");
  if (!elenco.some((c) => c.fonte === "deepseek")) mancano.push("DeepSeek");
  if (mancano.length) {
    const avviso = document.createElement("p");
    avviso.className = "mancano";
    avviso.textContent = T("Mancano %s: arrivano dall'estensione Chrome, da installare nei profili del browser.", mancano.join(", "));
    pannelloConsumi.appendChild(avviso);
  }
}

async function aggiornaQuadro() {
  try {
    const risposta = await fetch("/api/quadro", { cache: "no-store" });
    if (!risposta.ok) return;
    disegnaQuadro(await risposta.json());
  } catch (errore) {
    /* server non raggiungibile: riprovo al giro dopo */
  }
}

// "Ti aspettano" deve sparire appena una richiesta e' gestita: giro ogni 3 s
// (il server risponde in 0,1 s) e subito quando la finestra torna davanti,
// perche' Chrome rallenta i timer delle finestre in secondo piano.
setInterval(aggiornaQuadro, 3000);
document.addEventListener("visibilitychange", () => {
  if (!document.hidden) aggiornaQuadro();
});
window.addEventListener("focus", aggiornaQuadro);
aggiornaQuadro();

// ------------------------------------------- scheda guida (calibrazione e collaudo)
const schedaGuida = document.getElementById("guida");
let contoSilenzio = 0; // secondi rimasti mentre misura il silenzio

function disegnaGuida(g) {
  calibrando = Boolean(g && g.fase !== "fine");
  schedaGuida.hidden = !g;
  if (!g) return;
  document.getElementById("guida-titolo").textContent = g.titolo || "";
  const esiti = g.esiti || [];
  let passi = "";
  for (let i = 0; i < (g.totale || 0); i++) {
    passi += i < esiti.length ? (esiti[i] ? "✓" : "✗") : i === esiti.length ? "●" : "○";
  }
  document.getElementById("guida-passi").textContent = passi;
  const spiegazione = document.getElementById("guida-spiegazione");
  const dire = document.getElementById("guida-dire");
  const sentito = document.getElementById("guida-sentito");
  sentito.className = "";
  sentito.textContent = "";
  dire.textContent = "";
  if (g.fase === "silenzio") {
    spiegazione.textContent = contoSilenzio > 0 ? T("Resta in silenzio… %d", contoSilenzio) : T("Resta in silenzio");
  } else if (g.fase === "frasi") {
    spiegazione.textContent = T("Di':");
    dire.textContent = `«${g.dire}»`;
    if (g.ultima) {
      sentito.textContent = T("Ho sentito: «%s» %s", g.ultima.sentito, g.ultima.ok ? "✓" : "✗");
      sentito.className = g.ultima.ok ? "ok" : "no";
    }
  } else if (g.fase === "compiti") {
    spiegazione.textContent = g.spiegazione || "";
  } else {
    spiegazione.textContent = g.riepilogo || "";
  }
  const finita = g.fase === "fine";
  document.getElementById("guida-ripeti").hidden = finita;
  document.getElementById("guida-ferma").hidden = finita;
  document.getElementById("guida-chiudi").hidden = !finita;
}

async function azioneGuida(azione) {
  try {
    const risposta = await fetch("/api/collaudo", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ azione }),
    });
    const dato = await risposta.json();
    if (dato.risposta) di(dato.risposta);
  } catch (errore) { /* riprovo al prossimo clic */ }
  aggiornaQuadro();
}
document.getElementById("guida-ripeti").addEventListener("click", () => azioneGuida("ripeti"));
document.getElementById("guida-ferma").addEventListener("click", () => azioneGuida("ferma"));
document.getElementById("guida-chiudi").addEventListener("click", () => azioneGuida("chiudi"));
document.getElementById("calibra").addEventListener("click", () => avviaCalibrazione());

async function avviaCalibrazione() {
  if (!sveglia) accendi(false); // per misurare serve il microfono acceso
  try {
    const risposta = await fetch("/api/collaudo", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ azione: "avvia" }),
    });
    const dato = await risposta.json();
    if (dato.risposta) {
      aggiungiMessaggio("lui", dato.risposta);
      di(dato.risposta);
    }
    eseguiComando(dato);
  } catch (errore) { /* riprovo al prossimo clic */ }
  aggiornaQuadro();
}

// ------------------------------------------- calibrazione guidata
// «Ciro, calibrati»: il server chiede di misurare il silenzio dopo aver parlato.
function eseguiComando(dato) {
  if (dato && dato.comando === "misura-silenzio") misuraSilenzio(Number(dato.secondi) || 10);
}

async function misuraSilenzio(secondi) {
  // aspetto che Ciro finisca di parlare (e la sua eco si spenga)
  while (inCorso || coda.length) await new Promise((r) => setTimeout(r, 200));
  await new Promise((r) => setTimeout(r, 600));
  misurando = [];
  stato.textContent = T("Misuro il silenzio…");
  for (contoSilenzio = secondi; contoSilenzio > 0; contoSilenzio--) {
    const testo = document.getElementById("guida-spiegazione");
    if (testo) testo.textContent = T("Resta in silenzio… %d", contoSilenzio);
    await new Promise((r) => setTimeout(r, 1000));
  }
  const campioni = misurando.slice().sort((a, b) => a - b);
  misurando = null;
  impostaFase(micAttivo ? "ascolto" : "pronto");
  if (!campioni.length) return;
  const medio = campioni.reduce((a, b) => a + b, 0) / campioni.length;
  const p95 = campioni[Math.min(campioni.length - 1, Math.floor(campioni.length * 0.95))];
  const massimo = campioni[campioni.length - 1];
  try {
    const risposta = await fetch("/api/collaudo", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tipo: "silenzio", medio, p95, massimo, eco: eco || null }),
    });
    const dato = await risposta.json();
    sogliaCalibrata = null; // la nuova arriva con il quadro
    aggiornaQuadro();
    if (dato.risposta) {
      aggiungiMessaggio("lui", dato.risposta);
      di(dato.risposta);
    }
  } catch (errore) {
    evento("errore-collaudo", errore && errore.message);
  }
}

// ------------------------------------------------- messaggi spinti da fuori
async function controllaMessaggi() {
  if (!sveglia) return; // se dorme restano in coda e li dice quando si sveglia
  try {
    const risposta = await fetch("/api/messaggi", { cache: "no-store" });
    if (!risposta.ok) return;
    const { messaggi, muto: zitto } = await risposta.json();
    muto = Boolean(zitto);
    for (const messaggio of messaggi) {
      segnalaAttivita();
      if (messaggio.operazione === "credenziali" && messaggio.domanda_id) {
        mostraCredenziale({ domanda_id: messaggio.domanda_id, progetto: messaggio.progetto,
                            testo: messaggio.testo, nome_credenziale: messaggio.nome_credenziale });
      }
      aggiungiMessaggio("lui", messaggio.testo);
      di(messaggio.testo);
      eseguiComando(messaggio);
    }
  } catch (errore) {
    /* server non raggiungibile: riprovo al giro dopo */
  }
}

setInterval(controllaMessaggi, 1200);

// API per chi vuole comandare la faccia da fuori (pagina o console)
window.faccia = {
  di,
  parla: di,
  ascolta: accendiMicrofono,
  ferma: spegniMicrofono,
  accendi,
  spegni,
  fischia,
  quadro: aggiornaQuadro,
  richiamo: () => {
    ultimaAttivita = performance.now() - ATTESA_RICHIAMO - 1; // prova immediata
    controllaInattivita();
  },
  accesa: () => sveglia,
  stato: () => fase,
};
