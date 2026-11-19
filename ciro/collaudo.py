"""Calibration and acceptance test led by Ciro ("Ciro, calibrati").

Phases (see docs/calibration-design.md):
  silenzio  10 s of silence measured by the page -> microphone threshold
  frasi     8 phrases to repeat -> what whisper hears, aliases for misheard letters
  compiti   3 tasks with test sessions (prova-ciro, prova-due), answered normally
  spento    not running

The server drives it with tick() every 2 s; the brain hands it the user's words
with gestisci() while phases silenzio and frasi run (they are not commands then).
"""

import re
import statistics
import time
import unicodedata
from datetime import datetime
from pathlib import Path

import cervello as modulo_cervello

FRASI = ["A", "B", "sì", "no", "rispondi B", "B per prova due", "pausa progetti",
         "come stanno le sessioni"]
PROGETTI_PROVA = ["prova-ciro", "prova-due"]
ATTESA_FRASE = 20.0
ATTESA_COMPITO = 90.0
OPZIONI = {"A": "procedi", "B": "fermati"}
NUMERI = {"0": "zero", "1": "uno", "2": "due", "3": "tre"}
STOP_RE = re.compile(r"^(?:basta|ferma|stop|interrompi)(?: la)? (?:calibrazione|collaudo|prova)$")
PROMPT_COMPITI = [
    "Compito uno: rispondi A alla domanda che arriva.",
    "Compito due: ora correggi, di' rispondi B.",
    "Compito tre: arrivano due domande. Rispondi A a prova due e B a prova ciro.",
]


def detta(frase):
    """The phrase as Ciro says it in a prompt: capital letter and full stop."""
    return frase[:1].upper() + frase[1:] + "."


def normalizza(testo):
    testo = unicodedata.normalize("NFKD", (testo or "").lower())
    testo = "".join(c for c in testo if not unicodedata.combining(c))
    testo = re.sub(r"[^a-z0-9 ]+", " ", testo.replace("-", " "))
    parole = [NUMERI.get(p, p) for p in testo.split()]
    return " ".join(parole)


class Collaudo:
    def __init__(self, dire, stato_pausa, imposta_pausa, cartella, orologio=time.time,
                 righe_registro=None):
        self.dire = dire                   # dire(frase, **extra): Ciro says it (server queue)
        self.stato_pausa = stato_pausa
        self.imposta_pausa = imposta_pausa
        self.cartella = Path(cartella)
        self.orologio = orologio
        self.righe_registro = righe_registro or (lambda dal: [])
        self.fase = "spento"
        self._azzera()

    def _azzera(self):
        self.inizio = None
        self.inizio_testo = ""
        self.pausa_prima = None
        self.rumore = {}
        self.livelli = []
        self.frasi_sentite = []
        self.indice = 0
        self.tentativi = []
        self.chiesta = 0.0
        self.ripetuta = False
        self.compiti = []
        self.compito = 0
        self.domande = {}

    @property
    def attivo(self):
        return self.fase != "spento"

    # ------------------------------------------------------------ start / stop
    def avvia(self):
        self._azzera()
        self.inizio = self.orologio()
        self.inizio_testo = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.pausa_prima = self.stato_pausa()
        self.imposta_pausa(True, PROGETTI_PROVA)
        self.fase = "silenzio"
        return ("Inizio la calibrazione: ti guido io, passo per passo. "
                "Prima resta in silenzio per dieci secondi.")

    def ferma(self):
        self._chiudi_domande()
        self._ripristina_pausa()
        self.fase = "spento"
        return "Calibrazione fermata."

    def _ripristina_pausa(self):
        prima = self.pausa_prima or {"attiva": False, "solo": []}
        self.imposta_pausa(prima.get("attiva"), prima.get("solo"))

    # ------------------------------------------------------------ phase 1
    def silenzio(self, medio, p95, massimo):
        if self.fase != "silenzio":
            return ""
        self.rumore = {"medio": float(medio), "p95": float(p95), "massimo": float(massimo)}
        soglia = round(max(0.008, 2.5 * float(p95)), 4)
        modulo_cervello.imposta("soglia_microfono", soglia)
        self.rumore["soglia"] = soglia
        self.fase = "frasi"
        self._chiedi_frase()
        return "Ora ripeti dopo di me. %s" % detta(FRASI[0])

    # ------------------------------------------------------------ phase 2
    def _chiedi_frase(self):
        self.chiesta = self.orologio()
        self.ripetuta = False
        self.tentativi = []

    def _uguale(self, attesa, sentita):
        a, s = normalizza(attesa), normalizza(sentita)
        if a == s:
            return True
        if len(a) == 1 and s:
            alias = dict(modulo_cervello.LETTERE_SENTITE)
            alias.update(modulo_cervello.leggi_impostazioni().get("alias_lettere") or {})
            if alias.get(s) == a or (len(s) <= 3 and " " not in s and s.startswith(a)):
                appresi = dict(modulo_cervello.leggi_impostazioni().get("alias_lettere") or {})
                appresi[s] = a
                modulo_cervello.imposta("alias_lettere", appresi)
                return True
        return False

    def _registra_frase(self, ok):
        self.frasi_sentite.append({"attesa": FRASI[self.indice], "ok": ok, "tentativi": list(self.tentativi),
                                   "secondi": round(self.orologio() - self.chiesta, 1)})
        self.indice += 1

    def _prossima_frase(self):
        """The next phrase, or the start of the tasks after the last one."""
        if self.indice < len(FRASI):
            self._chiedi_frase()
            return detta(FRASI[self.indice])
        self.fase = "compiti"
        self._avvia_compito(0)
        return ""

    def gestisci(self, testo, livello=None):
        """The user's words: consumed during phases 1-2 (dict), otherwise None."""
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
        if self.fase != "frasi":
            return None
        if livello:
            self.livelli.append(float(livello))
        self.tentativi.append(testo)
        if self._uguale(FRASI[self.indice], testo):
            self._registra_frase(True)
            prossima = self._prossima_frase()
            return {"risposta": prossima or "Fatto con le frasi.", "azione": None, "mandato": False}
        if not self.ripetuta:
            self.ripetuta = True
            self.chiesta = self.orologio()
            return {"risposta": "Non ho capito bene. Ripeti: %s" % detta(FRASI[self.indice]),
                    "azione": None, "mandato": False}
        self._registra_frase(False)
        prossima = self._prossima_frase()
        return {"risposta": prossima or "Fatto con le frasi.", "azione": None, "mandato": False}

    # ------------------------------------------------------------ phase 3
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
        indice = self.compito
        if indice == 0:
            scheda = self._scheda("uno")
            if scheda.get("stato") in ("risposta-consegnata", "recepita", "risolta"):
                scelta = (scheda.get("risposta") or {}).get("scelta")
                self._come_sessione("uno")
                return scelta == "A", "risposta %s" % scelta
        elif indice == 1:
            scheda = self._scheda("uno")
            if scheda.get("correzione"):
                return scheda["correzione"] == "B", "correzione %s" % scheda["correzione"]
        else:
            due, ciro = self._scheda("tre-due"), self._scheda("tre-ciro")
            fatte = ("risposta-consegnata", "recepita", "risolta")
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
                    self.dire("Non ti ho sentito. Ripeti: %s" % detta(FRASI[self.indice]))
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
            self._fine()

    # ------------------------------------------------------------ phase 4
    def _chiudi_domande(self):
        posta, domande, _ = self._moduli()
        for identificativo in self.domande.values():
            try:
                scheda = domande.leggi(identificativo)
                if scheda.get("stato") in ("ricevuta", "in-valutazione", "in-attesa", "risposta-consegnata"):
                    posta.annulla(identificativo, scheda["progetto"])
            except Exception:  # noqa: BLE001
                continue

    def _fine(self):
        self._chiudi_domande()
        self._ripristina_pausa()
        capite = sum(1 for r in self.frasi_sentite if r["ok"])
        riusciti = sum(1 for c in self.compiti if c["ok"])
        righe = self.righe_registro(self.inizio_testo)
        trascrizioni = [v.get("secondi_trascrizione") or 0 for v in righe
                        if v.get("tipo") == "ascolto" and v.get("testo")]
        cervello = [v.get("secondi") or 0 for v in righe if v.get("tipo") == "cervello"]
        risposta = (statistics.mean(trascrizioni) if trascrizioni else 0) + (statistics.mean(cervello) if cervello else 0)
        voce = statistics.median(self.livelli) if self.livelli else 0
        frase = "Calibrazione finita. Ti ho capito %d frasi su %d, %d compiti su %d" % (
            capite, len(FRASI), riusciti, len(PROMPT_COMPITI))
        if risposta:
            frase += ", rispondo in circa %d secondi" % max(1, round(risposta))
        frase += "."
        if voce and self.rumore.get("p95") and voce < 2 * self.rumore.get("soglia", 0):
            frase += " Parli piano rispetto al rumore: avvicinati al microfono."
        self.dire(frase + " Il rapporto e' nella cartella collaudi.")
        self._rapporto(capite, riusciti, voce, trascrizioni, cervello)
        self.fase = "spento"

    def _rapporto(self, capite, riusciti, voce, trascrizioni, cervello):
        self.cartella.mkdir(parents=True, exist_ok=True)
        media = lambda xs: (sum(xs) / len(xs)) if xs else 0  # noqa: E731
        righe = ["CALIBRAZIONE E COLLAUDO DI CIRO", "Iniziato: %s" % self.inizio_testo, "",
                 "Rumore della stanza: medio %.4f, 95%% %.4f, massimo %.4f -> soglia del microfono %.4f"
                 % (self.rumore.get("medio", 0), self.rumore.get("p95", 0), self.rumore.get("massimo", 0),
                    self.rumore.get("soglia", 0)),
                 "Voce (mediana delle frasi): %.4f" % voce, "",
                 "Frasi capite: %d su %d" % (capite, len(FRASI))]
        for r in self.frasi_sentite:
            righe.append("  %-3s %-25s sentito: %s" % ("OK" if r["ok"] else "NO", r["attesa"],
                                                     " | ".join(r["tentativi"]) or "(niente)"))
        righe += ["", "Compiti riusciti: %d su %d" % (riusciti, len(PROMPT_COMPITI))]
        for c in self.compiti:
            righe.append("  compito %d: %s, %s, %d turni, %.0f s" % (
                c["numero"], "OK" if c["ok"] else "NO", c["dettaglio"], c["turni"], c.get("secondi", 0)))
        righe += ["", "Tempi medi: trascrizione %.1f s, cervello %.1f s" % (media(trascrizioni), media(cervello)),
                  "Alias imparati: %s" % (modulo_cervello.leggi_impostazioni().get("alias_lettere") or {})]
        nome = "collaudo-%s.txt" % datetime.now().strftime("%Y%m%d-%H%M%S")
        (self.cartella / nome).write_text("\n".join(righe) + "\n", encoding="utf-8")
