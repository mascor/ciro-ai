"""Calibration («Ciro, calibrati») and acceptance test («Ciro, collaudo»), led by Ciro.

Calibration (about 40 s): 5 s of silence measured by the page, then 5 phrases to
repeat. The microphone threshold comes from the room noise AND the voice; misheard
single letters are learned as aliases. Acceptance test: 3 tasks with the test
sessions prova-ciro and prova-due, answered through the normal paths.

Phases: spento, silenzio, frasi, compiti, fine (result shown until closed).
The server calls tick() every 2 s; the brain hands the user's words to gestisci()
(during silenzio and frasi they are not commands). See docs/calibration-design.md.
"""

import re
import statistics
import time
import unicodedata
from datetime import datetime
from pathlib import Path

import cervello as modulo_cervello

FRASI = ["uno", "due", "sì", "no", "uno per prova due", "come stanno le sessioni oggi"]
FRASE_LIBERA = FRASI[-1]   # misura le pause e il riconoscimento delle frasi libere
SILENZIO_SECONDI = 5
PROGETTI_PROVA = ["prova-ciro", "prova-due"]
ATTESA_FRASE = 20.0
ATTESA_COMPITO = 90.0
ESITO_VISIBILE = 120.0
OPZIONI = {"A": "procedi", "B": "fermati"}
NUMERI = {"0": "zero", "1": "uno", "2": "due", "3": "tre"}
STOP_RE = re.compile(r"^(?:basta|ferma|stop|interrompi)(?: la| il)? (?:calibrazione|collaudo|prova)$")
PROMPT_COMPITI = [
    "Primo compito: rispondi uno alla domanda che arriva.",
    "Secondo compito: ora correggi, di' rispondi due.",
    "Terzo compito: arrivano due domande. Di' uno per prova due, poi due per prova ciro.",
]
SPIEGAZIONE_COMPITI = [
    "Rispondi «uno» alla domanda di prova-ciro",
    "Di' «rispondi due» per correggere",
    "Di' «uno per prova due», poi «due per prova ciro»",
]


def detta(frase, inizio="Di': "):
    """How Ciro asks for a phrase: one sentence, a single letter as «la A»
    (a letter alone is hard to understand with a synthetic voice)."""
    return inizio + ("la " + frase if len(frase) == 1 else frase) + "."


def normalizza(testo):
    testo = unicodedata.normalize("NFKD", (testo or "").lower())
    testo = "".join(c for c in testo if not unicodedata.combining(c))
    testo = re.sub(r"[^a-z0-9 ]+", " ", testo.replace("-", " "))
    return " ".join(NUMERI.get(p, p) for p in testo.split())


class Collaudo:
    def __init__(self, dire, stato_pausa, imposta_pausa, cartella, orologio=time.time,
                 righe_registro=None, dopo_calibrazione=None):
        self.dire = dire                   # dire(frase, **extra): Ciro says it (server queue)
        self.stato_pausa = stato_pausa
        self.imposta_pausa = imposta_pausa
        self.cartella = Path(cartella)
        self.orologio = orologio
        self.righe_registro = righe_registro or (lambda dal: [])
        self.dopo_calibrazione = dopo_calibrazione   # es. scelta automatica del modello
        self.fase = "spento"
        self._azzera()

    def _azzera(self):
        self.modo = None
        self.inizio_testo = ""
        self.pausa_prima = None
        self.rumore = {}
        self.livelli = []
        self.pause = []
        self.frasi_sentite = []
        self.indice = 0
        self.tentativi = []
        self.ultima = None
        self.chiesta = 0.0
        self.ripetuta = False
        self.compiti = []
        self.compito = 0
        self.domande = {}
        self.riepilogo = ""
        self.finito = 0.0

    @property
    def attivo(self):
        return self.fase in ("silenzio", "frasi", "compiti")

    # ------------------------------------------------------------ start / stop
    def avvia(self, modo="calibrazione"):
        self._azzera()
        self.modo = modo
        self.inizio_testo = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.pausa_prima = self.stato_pausa()
        self.imposta_pausa(True, PROGETTI_PROVA)
        if modo == "collaudo":
            self.fase = "compiti"
            self._avvia_compito(0)
            return "Inizio il collaudo: tre compiti, ti dico io cosa fare."
        self.fase = "silenzio"
        return "Inizio la calibrazione: ti guido io. Prima resta in silenzio per cinque secondi."

    def ferma(self):
        nome = "Collaudo" if self.modo == "collaudo" else "Calibrazione"
        self._chiudi_domande()
        self._ripristina_pausa()
        self.fase = "spento"
        return "%s fermato." % nome if nome == "Collaudo" else "Calibrazione fermata."

    def chiudi(self):
        """The user closed the result card."""
        if self.fase == "fine":
            self.fase = "spento"

    def ripeti(self):
        """What Ciro asked last, to say it again (button «Ripeti»)."""
        if self.fase == "frasi":
            self.chiesta = self.orologio()
            return detta(FRASI[self.indice])
        if self.fase == "compiti":
            return PROMPT_COMPITI[self.compito]
        if self.fase == "silenzio":
            return "Resta in silenzio per cinque secondi."
        return ""

    def _ripristina_pausa(self):
        prima = self.pausa_prima or {"attiva": False, "solo": []}
        self.imposta_pausa(prima.get("attiva"), prima.get("solo"))

    # ------------------------------------------------------------ guide card
    def stato_guida(self):
        if self.fase == "spento":
            return None
        if self.fase == "fine" and self.orologio() - self.finito > ESITO_VISIBILE:
            self.fase = "spento"
            return None
        if self.fase == "silenzio":
            return {"fase": "silenzio", "titolo": "Calibrazione · silenzio", "dire": "",
                    "spiegazione": "Resta in silenzio", "secondi": SILENZIO_SECONDI}
        if self.fase == "frasi":
            return {"fase": "frasi", "titolo": "Calibrazione · frasi", "passo": self.indice + 1,
                    "totale": len(FRASI), "dire": FRASI[self.indice], "ultima": self.ultima,
                    "esiti": [r["ok"] for r in self.frasi_sentite]}
        if self.fase == "compiti":
            return {"fase": "compiti", "titolo": "Collaudo · compito %d di %d" % (self.compito + 1, len(PROMPT_COMPITI)),
                    "passo": self.compito + 1, "totale": len(PROMPT_COMPITI),
                    "dire": "", "spiegazione": SPIEGAZIONE_COMPITI[self.compito],
                    "esiti": [c["ok"] for c in self.compiti if c["ok"] is not None]}
        return {"fase": "fine", "titolo": "Collaudo finito" if self.modo == "collaudo" else "Calibrazione finita",
                "riepilogo": self.riepilogo}

    # ------------------------------------------------------------ calibration
    def silenzio(self, medio, p95, massimo, eco=None):
        if self.fase != "silenzio":
            return ""
        self.rumore = {"medio": float(medio), "p95": float(p95), "massimo": float(massimo)}
        if eco:
            self.rumore["eco"] = float(eco)
        provvisoria = round(max(0.008, 3 * float(medio)), 4)
        modulo_cervello.imposta("soglia_microfono", provvisoria)
        self.rumore["soglia"] = provvisoria
        self.fase = "frasi"
        self._chiedi_frase()
        return detta(FRASI[0], "Ora ripeti dopo di me: ")

    def _chiedi_frase(self):
        self.chiesta = self.orologio()
        self.ripetuta = False
        self.tentativi = []

    def _uguale(self, attesa, sentita):
        a, s = normalizza(attesa), normalizza(sentita)
        if a == s:
            return True
        if attesa == FRASE_LIBERA:   # frase lunga: basta la maggior parte delle parole
            parole = a.split()
            return sum(1 for p in parole if p in s.split()) >= 0.6 * len(parole)
        if len(a) == 1 and s:
            appresi = dict(modulo_cervello.leggi_impostazioni().get("alias_lettere") or {})
            alias = dict(modulo_cervello.LETTERE_SENTITE)
            alias.update(appresi)
            if alias.get(s) == a or (len(s) <= 3 and " " not in s and s.startswith(a)):
                appresi[s] = a
                modulo_cervello.imposta("alias_lettere", appresi)
                return True
        return False

    def _registra_frase(self, ok):
        if ok:   # i tentativi sbagliati prima di quello giusto: errori tipici di questa voce
            for sbagliato in self.tentativi[:-1]:
                if len(normalizza(sbagliato)) <= 3:
                    modulo_cervello.impara_confusione(sbagliato, FRASI[self.indice])
        self.frasi_sentite.append({"attesa": FRASI[self.indice], "ok": ok, "tentativi": list(self.tentativi),
                                   "secondi": round(self.orologio() - self.chiesta, 1)})
        self.indice += 1

    def _prossima_frase(self):
        if self.indice < len(FRASI):
            self._chiedi_frase()
            return detta(FRASI[self.indice])
        self._fine_calibrazione()
        return ""

    def _fine_calibrazione(self):
        voce = statistics.median(self.livelli) if self.livelli else 0.0
        # tra il rumore medio e la voce (media geometrica): un picco nel silenzio
        # (eco, un colpo) non alza la soglia; mai oltre meta' della voce
        rumore = self.rumore.get("medio", 0.0)
        if voce:
            soglia = round(max(0.008, min((rumore * voce) ** 0.5, 0.5 * voce)), 4)
        else:
            soglia = round(max(0.008, 3 * rumore), 4)
        modulo_cervello.imposta("soglia_microfono", soglia)
        self.rumore["soglia"] = soglia
        self.rumore["voce"] = voce
        profilo = {}
        if len(self.pause) >= 3:   # fine frase su misura: le pause dentro le sue frasi
            ordinate = sorted(self.pause)
            p90 = ordinate[min(len(ordinate) - 1, int(len(ordinate) * 0.9))]
            profilo["fine_frase_ms"] = max(600, min(1200, p90 + 250))
        if self.rumore.get("eco"):
            profilo["eco"] = self.rumore["eco"]
        if profilo:
            modulo_cervello.aggiorna_profilo(**profilo)
        self.rumore.update(profilo)
        capite = sum(1 for r in self.frasi_sentite if r["ok"])
        frase = "Calibrazione finita: ti ho capito %d frasi su %d." % (capite, len(FRASI))
        if voce and voce < 5 * rumore:
            frase += " Parli piano rispetto al rumore: avvicinati al microfono."
        self._chiudi(frase)
        if self.dopo_calibrazione:
            self.dopo_calibrazione()

    def gestisci(self, testo, livello=None, pause=None):
        """The user's words: consumed during silenzio and frasi (dict), otherwise None."""
        if not self.attivo:
            return None
        if STOP_RE.match(normalizza(testo)):
            return {"risposta": self.ferma(), "azione": None, "mandato": False}
        if self.fase == "silenzio":
            return {"risposta": "Aspetta, sto misurando il silenzio.", "azione": None, "mandato": False}
        if self.fase == "compiti":
            if self.compito < len(self.compiti):
                self.compiti[self.compito]["turni"] += 1
            return None
        if livello:
            self.livelli.append(float(livello))
        self.pause.extend(int(p) for p in (pause or []) if 0 < int(p) < 3000)
        self.tentativi.append(testo)
        ok = self._uguale(FRASI[self.indice], testo)
        self.ultima = {"attesa": FRASI[self.indice], "sentito": testo, "ok": ok}
        if ok or self.ripetuta:
            self._registra_frase(ok)
            prossima = self._prossima_frase()
            return {"risposta": prossima, "azione": None, "mandato": False}
        self.ripetuta = True
        self.chiesta = self.orologio()
        return {"risposta": "Non ho capito bene. %s" % detta(FRASI[self.indice], "Ripeti: "),
                "azione": None, "mandato": False}

    # ------------------------------------------------------------ acceptance test
    def _moduli(self):
        return modulo_cervello._moduli_posta()

    def _chiedi(self, progetto, numero):
        posta, _, _ = self._moduli()
        return posta.chiedi(progetto, "Collaudo %s" % numero, "Collaudo, compito %s: procedo?" % numero,
                            dict(OPZIONI), "scelta", "il collaudo di Ciro", raccomanda="A",
                            testo="Collaudo di Ciro: nessun lavoro vero dipende da questa risposta.")

    def _avvia_compito(self, indice):
        self.compito = indice
        self.compiti.append({"numero": indice + 1, "inizio": self.orologio(), "turni": 0, "ok": None,
                             "dettaglio": ""})
        self.dire(PROMPT_COMPITI[indice])
        if indice == 0:
            self.domande["uno"] = self._chiedi("prova-ciro", "uno")
            self.compiti[0]["domanda"] = self.domande["uno"]
        elif indice == 2:
            self.domande["tre-ciro"] = self._chiedi("prova-ciro", "tre")
            self.domande["tre-due"] = self._chiedi("prova-due", "tre")

    def _scheda(self, chiave):
        _, domande, _ = self._moduli()
        try:
            return domande.leggi(self.domande[chiave])
        except Exception:  # noqa: BLE001
            return {}

    def _come_sessione(self, chiave):
        """The test session reads the answer like a real one."""
        posta, _, _ = self._moduli()
        scheda = self._scheda(chiave)
        try:
            posta.recepita(scheda["id"], scheda["progetto"])
            posta.risolta(scheda["id"], "collaudo")
        except Exception:  # noqa: BLE001
            pass

    def _esito_compito(self):
        fatte = ("risposta-consegnata", "recepita", "risolta")
        if self.compito == 0:
            scheda = self._scheda("uno")
            if scheda.get("stato") in fatte:
                scelta = (scheda.get("risposta") or {}).get("scelta")
                self._come_sessione("uno")
                return scelta == "A", "risposta %s" % scelta
        elif self.compito == 1:
            scheda = self._scheda("uno")
            if scheda.get("correzione"):
                return scheda["correzione"] == "B", "correzione %s" % scheda["correzione"]
        else:
            due, ciro = self._scheda("tre-due"), self._scheda("tre-ciro")
            if due.get("stato") in fatte and ciro.get("stato") in fatte:
                scelte = ((due.get("risposta") or {}).get("scelta"), (ciro.get("risposta") or {}).get("scelta"))
                self._come_sessione("tre-due")
                self._come_sessione("tre-ciro")
                return scelte == ("A", "B"), "prova-due %s, prova-ciro %s" % scelte
        return None

    def tick(self):
        if self.fase == "frasi":
            if self.orologio() - self.chiesta > ATTESA_FRASE:
                if not self.ripetuta:
                    self.ripetuta = True
                    self.chiesta = self.orologio()
                    self.dire("Non ti ho sentito. %s" % detta(FRASI[self.indice], "Ripeti: "))
                else:
                    self._registra_frase(False)
                    prossima = self._prossima_frase()
                    if prossima:
                        self.dire(prossima)
            return
        if self.fase != "compiti":
            return
        compito = self.compiti[self.compito]
        esito = self._esito_compito()
        if esito is None and self.orologio() - compito["inizio"] <= ATTESA_COMPITO:
            return
        compito["ok"], compito["dettaglio"] = esito if esito else (False, "tempo scaduto")
        compito["secondi"] = round(self.orologio() - compito["inizio"], 1)
        if self.compito + 1 < len(PROMPT_COMPITI):
            self._avvia_compito(self.compito + 1)
        else:
            self._fine_collaudo()

    def _fine_collaudo(self):
        righe = self.righe_registro(self.inizio_testo)
        trascrizioni = [v.get("secondi_trascrizione") or 0 for v in righe
                        if v.get("tipo") == "ascolto" and v.get("testo")]
        cervello = [v.get("secondi") or 0 for v in righe if v.get("tipo") == "cervello"]
        risposta = (statistics.mean(trascrizioni) if trascrizioni else 0) + \
                   (statistics.mean(cervello) if cervello else 0)
        riusciti = sum(1 for c in self.compiti if c["ok"])
        frase = "Collaudo finito: %d compiti su %d" % (riusciti, len(PROMPT_COMPITI))
        if risposta:
            frase += ", rispondo in circa %d secondi" % max(1, round(risposta))
        self._chiudi(frase + ".", trascrizioni, cervello)

    # ------------------------------------------------------------ end
    def _chiudi_domande(self):
        posta, domande, _ = self._moduli()
        for identificativo in self.domande.values():
            try:
                scheda = domande.leggi(identificativo)
                if scheda.get("stato") in ("ricevuta", "in-valutazione", "in-attesa", "risposta-consegnata"):
                    posta.annulla(identificativo, scheda["progetto"])
            except Exception:  # noqa: BLE001
                continue

    def _chiudi(self, frase, trascrizioni=(), cervello=()):
        self._chiudi_domande()
        self._ripristina_pausa()
        self.riepilogo = frase
        self.dire(frase + " Il rapporto e' nella cartella collaudi.")
        self._rapporto(trascrizioni, cervello)
        self.fase = "fine"
        self.finito = self.orologio()

    def _rapporto(self, trascrizioni, cervello):
        self.cartella.mkdir(parents=True, exist_ok=True)
        media = lambda xs: (sum(xs) / len(xs)) if xs else 0  # noqa: E731
        righe = ["%s DI CIRO" % ("COLLAUDO" if self.modo == "collaudo" else "CALIBRAZIONE"),
                 "Iniziato: %s" % self.inizio_testo, "", self.riepilogo, ""]
        if self.modo != "collaudo":
            righe += ["Rumore della stanza: medio %.4f, 95%% %.4f, massimo %.4f"
                      % (self.rumore.get("medio", 0), self.rumore.get("p95", 0), self.rumore.get("massimo", 0)),
                      "Voce (mediana delle frasi): %.4f" % self.rumore.get("voce", 0),
                      "Soglia del microfono: %.4f" % self.rumore.get("soglia", 0),
                      "Fine frase: %s ms (pause misurate: %s)" % (self.rumore.get("fine_frase_ms", "invariata"),
                                                                 self.pause or "-"),
                      "Eco della voce di Ciro: %s" % self.rumore.get("eco", "-"), ""]
            for r in self.frasi_sentite:
                righe.append("  %-3s %-18s sentito: %s" % ("OK" if r["ok"] else "NO", r["attesa"],
                                                         " | ".join(r["tentativi"]) or "(niente)"))
            righe += ["", "Alias imparati: %s" % (modulo_cervello.leggi_impostazioni().get("alias_lettere") or {}),
                      "Errori tipici della voce: %s" % (modulo_cervello.profilo_voce().get("confusioni") or {})]
        else:
            for c in self.compiti:
                righe.append("  compito %d: %s, %s, %d turni, %.0f s" % (
                    c["numero"], "OK" if c["ok"] else "NO", c["dettaglio"], c["turni"], c.get("secondi", 0)))
            righe += ["", "Tempi medi: trascrizione %.1f s, cervello %.1f s" % (media(trascrizioni), media(cervello))]
        nome = "%s-%s.txt" % (self.modo or "calibrazione", datetime.now().strftime("%Y%m%d-%H%M%S"))
        (self.cartella / nome).write_text("\n".join(righe) + "\n", encoding="utf-8")
