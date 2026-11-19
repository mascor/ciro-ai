"""Ciro and the structured questions. Run from faccia/: python3 -m unittest tests.test_coordinamento_ciro

Everything runs on temporary folders: mail root (POSTA_RADICE), authorisations
(CIRO_AUTORIZZAZIONI), Ciro's context, rules and log. The model is a fake.
"""

import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

QUI = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(QUI))
_TEMP = tempfile.mkdtemp()
os.environ.setdefault("FACCIA_CONTESTO", os.path.join(_TEMP, "contesto.json"))

import server  # noqa: E402
import cervello as modulo_cervello  # noqa: E402

domande = server.domande
posta = server.modulo_posta
coordinatore = server.coordinatore


class BaseCiro(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ciro-test-"))
        self.env = {k: os.environ.get(k) for k in ("POSTA_RADICE", "CIRO_AUTORIZZAZIONI",
                                                   "POSTA_REGISTRO", "CIRO_DEEPSEEK_DIRETTO")}
        os.environ["POSTA_RADICE"] = str(self.tmp / "posta")
        os.environ["CIRO_AUTORIZZAZIONI"] = str(self.tmp / "autorizzazioni.json")
        os.environ["POSTA_REGISTRO"] = str(self.tmp / "registro.log")
        os.environ["CIRO_DEEPSEEK_DIRETTO"] = "0"   # the tests never call the real model
        self.originali = {
            "REGISTRO": modulo_cervello.REGISTRO, "MEMORIA": modulo_cervello.MEMORIA,
            "CONTESTO": modulo_cervello.CONTESTO, "leggi_sessioni": modulo_cervello.leggi_sessioni,
            "RADICE_POSTA": modulo_cervello.RADICE_POSTA,
            "IMPOSTAZIONI": modulo_cervello.IMPOSTAZIONI,
        }
        modulo_cervello.RADICE_POSTA = self.tmp / "posta"
        modulo_cervello.IMPOSTAZIONI = self.tmp / "impostazioni.json"   # never the real settings
        modulo_cervello.REGISTRO = self.tmp / "conversazioni.log"
        modulo_cervello.MEMORIA = self.tmp / "memoria-ciro.md"
        modulo_cervello.CONTESTO = self.tmp / "contesto.json"
        modulo_cervello.leggi_sessioni = lambda: [
            {"progetto": p, "stato": "al lavoro", "aspetta_utente": False, "da_secondi": 0}
            for p in ("ironworks", "contoso", "atlas")]
        self.cervello_prima = server._cervello
        server._cervello = modulo_cervello.Cervello()
        self.chiamate_modello = []
        self.risposta_modello = '{"copre": false, "scelta": null}'

        def finto(prompt):
            self.chiamate_modello.append(prompt)
            return self.risposta_modello
        server._cervello.chiedi_preferenze = finto
        with server._coda_lock:
            server._coda[:] = []

    def tearDown(self):
        for nome, valore in self.originali.items():
            setattr(modulo_cervello, nome, valore)
        server._cervello = self.cervello_prima
        for chiave, valore in self.env.items():
            if valore is None:
                os.environ.pop(chiave, None)
            else:
                os.environ[chiave] = valore
        with server._coda_lock:
            server._coda[:] = []
        shutil.rmtree(self.tmp, ignore_errors=True)

    def chiedi(self, progetto="ironworks", operazione="scelta", **altro):
        argomenti = dict(oggetto="Schema spazi Chat",
                         domanda="Quale schema uso per gli spazi Chat?",
                         opzioni={"A": "uno spazio per progetto", "B": "uno spazio per cliente"},
                         raccomanda="A", bloccato="la creazione degli spazi")
        argomenti.update(altro)
        return posta.chiedi(progetto, argomenti.pop("oggetto"), argomenti.pop("domanda"),
                            argomenti.pop("opzioni"), operazione, argomenti.pop("bloccato"),
                            **argomenti)

    def giro(self):
        for filo in server.giro_domande():
            filo.join(10)

    def coda(self):
        with server._coda_lock:
            return list(server._coda)

    def messaggi_a(self, casella):
        cartella = self.tmp / "posta" / casella / "nuovi"
        return sorted(cartella.glob("*.md")) if cartella.is_dir() else []


class TestSorveglianza(BaseCiro):
    def test_domanda_detta_entro_un_giro(self):
        modulo_cervello.MEMORIA.write_text("- per gli spazi Chat decido io\n", encoding="utf-8")
        identificativo = self.chiedi()
        self.giro()
        voci = self.coda()
        self.assertEqual(len(voci), 1)
        self.assertEqual(voci[0]["testo"],
                         "Da ironworks: Quale schema uso per gli spazi Chat? "
                         "A, uno spazio per progetto; B, uno spazio per cliente. "
                         "Consiglia A. Come rispondo?")
        self.assertEqual(voci[0]["tipo"], "domanda")
        self.assertEqual(voci[0]["domanda_id"], identificativo)
        self.assertEqual(voci[0]["progetto"], "ironworks")
        self.assertEqual(voci[0]["opzioni"], {"A": "uno spazio per progetto",
                                              "B": "uno spazio per cliente"})
        self.assertEqual(domande.leggi(identificativo)["stato"], "in-attesa")
        self.assertEqual(len(self.chiamate_modello), 1)
        self.assertEqual(server._cervello.domanda_corrente, identificativo)
        self.assertIn(identificativo, server._cervello.domande_in_attesa)
        # a second round says nothing new
        self.giro()
        self.assertEqual(len(self.coda()), 1)

    def test_preferenza_non_pertinente_nessun_modello(self):
        modulo_cervello.MEMORIA.write_text("- rispondi breve e chiaro\n", encoding="utf-8")
        self.chiedi()
        self.giro()
        self.assertEqual(len(self.coda()), 1)
        self.assertEqual(self.chiamate_modello, [])

    def test_senza_preferenze_nessun_modello(self):
        self.chiedi()
        self.giro()
        self.assertEqual(len(self.coda()), 1)
        self.assertEqual(self.chiamate_modello, [])

    def test_vietata_detta_senza_modello(self):
        modulo_cervello.MEMORIA.write_text("- fai sempre tutto\n", encoding="utf-8")
        identificativo = self.chiedi(operazione="database")
        self.giro()
        self.assertEqual(domande.leggi(identificativo)["stato"], "in-attesa")
        self.assertEqual(self.chiamate_modello, [])

    def test_automatica_consegna_e_annuncia(self):
        coordinatore.salva_autorizzazione("ironworks", "deploy-prova", "prova", ["test-ok"],
                                          "deploy di prova dopo i test")
        identificativo = self.chiedi(operazione="deploy-prova", ambiente="prova",
                                     condizioni=["test-ok"],
                                     opzioni={"A": "procedi", "B": "aspetta"})
        self.giro()
        scheda = domande.leggi(identificativo)
        self.assertEqual(scheda["stato"], "risposta-consegnata")
        self.assertEqual(scheda["risposta"]["scelta"], "A")
        self.assertTrue(scheda["risposta"]["motivo"].startswith("regola:aut-ironworks-"))
        self.assertEqual(len(self.messaggi_a("ironworks")), 1)
        voci = self.coda()
        self.assertEqual(len(voci), 1)
        self.assertTrue(voci[0]["testo"].startswith("Ho risposto A a ironworks, per la tua regola"),
                        voci[0]["testo"])
        self.assertIn(identificativo, server._cervello.risposte_automatiche)

    def test_preferenza_coperta_dal_modello(self):
        modulo_cervello.MEMORIA.write_text("- per gli spazi Chat usa uno spazio per cliente\n",
                                           encoding="utf-8")
        self.risposta_modello = ('{"copre": true, "scelta": "B", '
                                 '"regola": "per gli spazi Chat usa uno spazio per cliente"}')
        identificativo = self.chiedi()
        self.giro()
        self.assertEqual(domande.leggi(identificativo)["risposta"]["scelta"], "B")
        self.assertIn("per la tua regola", self.coda()[0]["testo"])

    def test_modello_lento_la_domanda_parte_lo_stesso(self):
        modulo_cervello.MEMORIA.write_text("- per gli spazi Chat qualcosa\n", encoding="utf-8")
        server.ATTESA_MODELLO = 0.3
        sblocca = threading.Event()

        def lento(prompt):
            sblocca.wait(5)
            return '{"copre": true, "scelta": "B"}'
        server._cervello.chiedi_preferenze = lento
        try:
            identificativo = self.chiedi()
            fili = server.giro_domande()
            fine = time.time() + 3
            while not self.coda() and time.time() < fine:
                time.sleep(0.05)
            self.assertEqual(domande.leggi(identificativo)["stato"], "in-attesa")
            sblocca.set()
            for filo in fili:
                filo.join(10)
            # the late "yes" of the model does not answer for Utente
            self.assertEqual(domande.leggi(identificativo)["stato"], "in-attesa")
            self.assertEqual(self.messaggi_a("ironworks"), [])
        finally:
            server.ATTESA_MODELLO = 2.0
            sblocca.set()

    def test_scheda_bloccata_torna_ricevuta_una_volta(self):
        adesso = [time.time()]
        prima = domande.orologio
        domande.orologio = lambda: adesso[0]
        try:
            identificativo = self.chiedi()
            domande.passa(identificativo, "in-valutazione", "ciro")  # Ciro died here
            self.giro()
            self.assertEqual(self.coda(), [])
            adesso[0] += 121
            self.giro()
            self.giro()
            self.assertEqual(len(self.coda()), 1)
            stati = [p["stato"] for p in domande.leggi(identificativo)["storia"]]
            self.assertEqual(stati, ["ricevuta", "in-valutazione", "ricevuta",
                                     "in-valutazione", "in-attesa"])
        finally:
            domande.orologio = prima

    def test_messaggio_senza_domanda_id_invariato(self):
        posta.invia("contoso", "opencode", "decisione", "Vecchio stile", "A o B?",
                    azione="decisione")
        identificativo = self.chiedi()
        self.giro()
        voci = server.attese()
        vecchie = [v for v in voci if v["progetto"] == "contoso"]
        self.assertEqual(len(vecchie), 1)
        self.assertEqual(vecchie[0]["tipo"], "decisione")
        self.assertNotIn("domanda_id", vecchie[0])
        nuove = [v for v in voci if v.get("domanda_id")]
        self.assertEqual([v["domanda_id"] for v in nuove], [identificativo])
        # the structured question is not also listed as a plain mail message
        self.assertEqual(len([v for v in voci if v["progetto"] == "ironworks"]), 1)

    def test_giro_reale_entro_tre_secondi(self):
        ferma = threading.Event()
        filo = threading.Thread(target=server.sorveglia_domande, args=(ferma,), daemon=True)
        filo.start()
        try:
            time.sleep(0.2)
            inizio = time.time()
            self.chiedi()
            while not self.coda() and time.time() - inizio < 5:
                time.sleep(0.05)
            self.assertTrue(self.coda())
            self.assertLess(time.time() - inizio, 3.0)
        finally:
            ferma.set()
            filo.join(5)


class TestRisposteVeloci(BaseCiro):
    def setUp(self):
        super().setUp()
        self.modello_chiamato = []
        self.uscita_modello = "Va bene."
        self.esegui_prima = modulo_cervello._esegui

        def finto_esegui(comando, timeout):
            if comando and comando[0] == "opencode":
                self.modello_chiamato.append(comando[-1])
                return self.uscita_modello, "", 0
            return self.esegui_prima(comando, timeout)
        modulo_cervello._esegui = finto_esegui
        self.c = server._cervello

    def tearDown(self):
        modulo_cervello._esegui = self.esegui_prima
        super().tearDown()

    def annunciata(self, progetto="ironworks", **altro):
        identificativo = self.chiedi(progetto, **altro)
        self.giro()
        return identificativo

    def test_A_va_alla_domanda_corrente(self):
        identificativo = self.annunciata()
        inizio = time.time()
        esito = self.c.chiedi("A")
        self.assertLess(time.time() - inizio, 1.0)
        self.assertEqual(esito["risposta"], "Mandato.")
        self.assertTrue(esito["mandato"])
        self.assertEqual(self.modello_chiamato, [])
        scheda = domande.leggi(identificativo)
        self.assertEqual(scheda["stato"], "risposta-consegnata")
        self.assertEqual(scheda["risposta"]["scelta"], "A")
        self.assertEqual(scheda["risposta"]["motivo"], "utente")
        self.assertEqual(len(self.messaggi_a("ironworks")), 1)

    def test_forme_della_lettera(self):
        for detto, lettera in (("la B", "B"), ("B.", "B"), ("rispondi a", "A"), ("Opzione b", "B")):
            identificativo = self.annunciata(oggetto=detto)
            esito = self.c.chiedi(detto)
            self.assertEqual(esito["risposta"], "Mandato.", detto)
            self.assertEqual(domande.leggi(identificativo)["risposta"]["scelta"], lettera, detto)
        self.assertEqual(self.modello_chiamato, [])

    def test_risposta_ambigua_chiede_progetto(self):
        primo = self.annunciata("ironworks")
        secondo = self.annunciata("contoso")
        esito = self.c.chiedi("A")
        self.assertEqual(esito["risposta"], "Per quale progetto?")
        self.assertFalse(esito["mandato"])
        self.assertEqual(domande.leggi(primo)["stato"], "in-attesa")
        self.assertEqual(domande.leggi(secondo)["stato"], "in-attesa")
        # he names the project: the letter he already said goes there
        esito = self.c.chiedi("ironworks")
        self.assertEqual(esito["risposta"], "Mandato.")
        self.assertEqual(domande.leggi(primo)["risposta"]["scelta"], "A")
        self.assertEqual(domande.leggi(secondo)["stato"], "in-attesa")
        # «B per contoso» goes only to contoso
        esito = self.c.chiedi("B per contoso")
        self.assertEqual(esito["risposta"], "Mandato.")
        self.assertEqual(domande.leggi(secondo)["risposta"]["scelta"], "B")
        self.assertEqual(self.modello_chiamato, [])

    def test_seconda_A_non_rimanda(self):
        self.annunciata()
        self.c.chiedi("A")
        esito = self.c.chiedi("A")
        self.assertEqual(esito["risposta"], "Già mandata.")
        self.assertFalse(esito["mandato"])
        self.assertEqual(len(self.messaggi_a("ironworks")), 1)

    def test_si_no_su_domanda_si_no(self):
        identificativo = self.annunciata(opzioni={"S": "procedi", "N": "fermati"}, raccomanda="S")
        self.assertEqual(self.c.chiedi("sì")["risposta"], "Mandato.")
        self.assertEqual(domande.leggi(identificativo)["risposta"]["scelta"], "S")
        identificativo = self.annunciata(opzioni={"S": "procedi", "N": "fermati"}, raccomanda="S")
        self.assertEqual(self.c.chiedi("no")["risposta"], "Mandato.")
        self.assertEqual(domande.leggi(identificativo)["risposta"]["scelta"], "N")

    def test_si_accetta_l_opzione_consigliata(self):
        identificativo = self.annunciata(raccomanda="B")
        esito = self.c.chiedi("sì")
        self.assertEqual(esito["risposta"], "Mandato: B.")
        self.assertEqual(domande.leggi(identificativo)["risposta"]["scelta"], "B")

    def test_si_senza_consiglio_chiede_la_lettera(self):
        identificativo = self.annunciata(raccomanda=None)
        self.assertIn("A, B", self.c.chiedi("sì")["risposta"])
        self.assertEqual(domande.leggi(identificativo)["stato"], "in-attesa")

    def test_lettera_non_tra_le_opzioni(self):
        identificativo = self.annunciata()
        esito = self.c.chiedi("C")
        self.assertIn("A", esito["risposta"])
        self.assertIn("B", esito["risposta"])
        self.assertEqual(domande.leggi(identificativo)["stato"], "in-attesa")

    def test_frase_normale_va_al_modello(self):
        self.annunciata()
        self.c.chiedi("come va il lavoro su atlas?")
        self.assertEqual(len(self.modello_chiamato), 1)

    def test_deploy_prova_B_salva_dopo_conferma(self):
        argomenti = dict(operazione="deploy-prova", ambiente="prova", condizioni=["test-ok"],
                         opzioni={"A": "procedi", "B": "aspetta"}, raccomanda="A")
        identificativo = self.annunciata(**argomenti)
        frase = self.coda()[-1]["testo"]
        self.assertIn("A, autorizza questa volta", frase)
        self.assertIn("B, autorizza sempre", frase)
        self.assertIn("C, rimanda", frase)
        esito = self.c.chiedi("B")
        self.assertIn("Salvo:", esito["risposta"])
        self.assertTrue(esito["risposta"].endswith("Confermi?"))
        self.assertEqual(coordinatore.carica_autorizzazioni(), [])
        esito = self.c.chiedi("no")
        self.assertEqual(coordinatore.carica_autorizzazioni(), [])
        self.assertEqual(domande.leggi(identificativo)["stato"], "in-attesa")
        esito = self.c.chiedi("B")
        esito = self.c.chiedi("sì")
        regole = coordinatore.carica_autorizzazioni()
        self.assertEqual([(r["progetto"], r["condizioni"]) for r in regole], [("ironworks", ["test-ok"])])
        scheda = domande.leggi(identificativo)
        self.assertEqual(scheda["stato"], "risposta-consegnata")
        self.assertEqual(scheda["risposta"]["scelta"], "A")  # the option that proceeds
        self.assertIn("Mandato", esito["risposta"])
        self.assertEqual(self.modello_chiamato, [])

    def test_deploy_prova_A_e_C(self):
        argomenti = dict(operazione="deploy-prova", ambiente="prova", condizioni=["test-ok"],
                         opzioni={"A": "aspetta", "B": "procedi"}, raccomanda="B")
        identificativo = self.annunciata(**argomenti)
        esito = self.c.chiedi("C")
        self.assertEqual(domande.leggi(identificativo)["stato"], "in-attesa")
        self.assertFalse(esito["mandato"])
        self.c.chiedi("A")
        scheda = domande.leggi(identificativo)
        self.assertEqual(scheda["risposta"]["scelta"], "B")  # "this time" = the option that proceeds
        self.assertEqual(coordinatore.carica_autorizzazioni(), [])

    def test_chiedimi_sempre_toglie(self):
        coordinatore.salva_autorizzazione("ironworks", "deploy-prova", "prova", ["test-ok"], "x")
        self.uscita_modello = "Va bene, da ora ti chiedo sempre. AUTORIZZAZIONE: togli | ironworks"
        esito = self.c.chiedi("da ora chiedimi sempre prima di pubblicare ironworks")
        self.assertEqual(coordinatore.carica_autorizzazioni(), [])
        self.assertNotIn("AUTORIZZAZIONE", esito["risposta"])
        self.uscita_modello = "AUTORIZZAZIONE: elenca | ironworks"
        esito = self.c.chiedi("cosa puoi fare su ironworks?")
        self.assertIn("chiedo sempre", esito["risposta"])

    def test_correzione_entro_due_minuti(self):
        identificativo = self.annunciata()
        self.c.chiedi("A")
        esito = self.c.chiedi("rispondi B")
        self.assertIn("Correzione mandata", esito["risposta"])
        messaggi = self.messaggi_a("ironworks")
        self.assertEqual(len(messaggi), 2)
        teste = [posta.leggi_intestazioni(m) for m in messaggi]
        testa = [t for t in teste if t.get("CORREZIONE")][0]
        self.assertEqual(testa["CORREZIONE"], "B")
        self.assertEqual(testa["RIF"], identificativo)
        self.assertIn("B", testa["_CORPO"])
        scheda = domande.leggi(identificativo)
        self.assertEqual(scheda["correzione"], "B")
        self.assertIn("correzione", scheda["storia"][-1]["nota"])
        # after two minutes it is not a correction any more
        self.c.risposte_recenti[identificativo] = (time.time() - 121,) + self.c.risposte_recenti[identificativo][1:]
        self.c.chiedi("annulla")
        self.assertEqual(len(self.messaggi_a("ironworks")), 2)

    def test_annulla_dopo_recepita_avvisa(self):
        identificativo = self.annunciata()
        self.c.chiedi("A")
        posta.recepita(identificativo, "ironworks")
        esito = self.c.chiedi("annulla")
        self.assertIn("potrebbe aver già agito", esito["risposta"])
        self.assertEqual(domande.leggi(identificativo)["correzione"], "annulla")

    # --- revisione finale: una risposta breve non va mai alla domanda sbagliata
    def test_si_dopo_proposta_libera_passa_dal_registro(self):
        identificativo = self.annunciata(opzioni={"S": "procedi", "N": "fermati"}, raccomanda="S")
        self.uscita_modello = ("Va bene. AZIONE: invia | a=ironworks | tipo=decisione | "
                               "oggetto=Risposta | testo=Sì, ma solo in locale")
        esito = self.c.chiedi("sì, ma solo in locale")
        self.assertTrue(esito["risposta"].endswith("Confermi?"), esito["risposta"])
        self.assertEqual(domande.leggi(identificativo)["stato"], "in-attesa")
        esito = self.c.chiedi("sì")
        self.assertTrue(esito["mandato"], esito)
        self.assertIsNone(self.c.azione_in_attesa)
        messaggi = self.messaggi_a("ironworks")
        self.assertEqual(len(messaggi), 1)
        self.assertIn("solo in locale", posta.leggi_intestazioni(messaggi[0])["_CORPO"])
        scheda = domande.leggi(identificativo)
        self.assertEqual((scheda["stato"], scheda["risposta"]["scelta"]), ("risposta-consegnata", "S"))

    def test_risposta_libera_con_lettera_passa_dal_registro(self):
        identificativo = self.annunciata()
        self.uscita_modello = ("AZIONE: invia | a=ironworks | tipo=decisione | oggetto=Risposta | "
                               "scelta=B | testo=B, ma prima fai i test")
        self.c.chiedi("B, ma prima fai i test")
        self.c.chiedi("sì")
        messaggi = self.messaggi_a("ironworks")
        self.assertEqual(len(messaggi), 1)
        testa = posta.leggi_intestazioni(messaggi[0])
        self.assertEqual(testa["DOMANDA-ID"], identificativo)
        self.assertIn("prima fai i test", testa["_CORPO"])
        self.assertEqual(domande.leggi(identificativo)["risposta"]["scelta"], "B")
        # a second answer is refused by the record: the session cannot act twice
        self.assertEqual(self.c.chiedi("A")["mandato"], False)
        self.assertEqual(len(self.messaggi_a("ironworks")), 1)

    def test_ok_non_e_una_risposta(self):
        identificativo = self.annunciata(opzioni={"S": "procedi", "N": "fermati"}, raccomanda="S")
        for detto in ("ok", "perfetto", "certo"):
            self.c.chiedi(detto)
        self.assertEqual(domande.leggi(identificativo)["stato"], "in-attesa")
        self.assertEqual(self.messaggi_a("ironworks"), [])

    def test_si_dopo_un_altro_annuncio_chiede_il_progetto(self):
        identificativo = self.annunciata(opzioni={"S": "procedi", "N": "fermati"}, raccomanda="S")
        server._cervello.annota_avviso("contoso", "Da contoso: serve una decisione.")
        esito = self.c.chiedi("sì")
        self.assertEqual(esito["risposta"], "Per quale progetto?")
        self.assertEqual(domande.leggi(identificativo)["stato"], "in-attesa")
        self.assertEqual(self.c.chiedi("ironworks")["risposta"], "Mandato.")
        self.assertEqual(domande.leggi(identificativo)["risposta"]["scelta"], "S")

    def test_rispondi_B_dopo_automatica_corregge_quella(self):
        altra = self.annunciata("contoso")
        coordinatore.salva_autorizzazione("ironworks", "deploy-prova", "prova", ["test-ok"], "x")
        automatica = self.annunciata("ironworks", operazione="deploy-prova", ambiente="prova",
                                     condizioni=["test-ok"], opzioni={"A": "procedi", "B": "aspetta"})
        self.assertEqual(domande.leggi(automatica)["stato"], "risposta-consegnata")
        esito = self.c.chiedi("rispondi B")
        self.assertIn("Correzione mandata a ironworks", esito["risposta"])
        self.assertEqual(domande.leggi(altra)["stato"], "in-attesa")
        self.assertEqual(self.messaggi_a("contoso"), [])

    def test_frase_che_inizia_con_e_va_al_modello(self):
        identificativo = self.annunciata()
        self.c.chiedi("e alla fine cosa ha detto ironworks?")
        self.assertEqual(len(self.modello_chiamato), 1)
        self.assertEqual(domande.leggi(identificativo)["stato"], "in-attesa")

    def test_nome_progetto_dentro_una_frase_non_manda(self):
        primo = self.annunciata("ironworks")
        self.annunciata("contoso")
        self.assertEqual(self.c.chiedi("A")["risposta"], "Per quale progetto?")
        self.c.chiedi("aspetta, cosa vuole ironworks?")
        self.assertEqual(domande.leggi(primo)["stato"], "in-attesa")
        self.assertEqual(len(self.modello_chiamato), 1)

    def test_annulla_con_proposta_libera_va_al_vecchio_flusso(self):
        self.annunciata()
        self.c.chiedi("A")
        self.uscita_modello = "AZIONE: invia | a=contoso | tipo=richiesta | oggetto=x | testo=fai il backup"
        self.c.chiedi("di' a contoso di fare il backup")
        self.assertIsNotNone(self.c.azione_in_attesa)
        esito = self.c.chiedi("annulla")
        self.assertEqual(esito["risposta"], "Va bene, non lo mando.")
        self.assertEqual(len(self.messaggi_a("ironworks")), 1)  # no correction sent

    def test_posta_recente_esclude_le_domande_strutturate(self):
        self.annunciata()
        posta.invia("contoso", "opencode", "decisione", "Vecchio stile", "A o B?", azione="decisione")
        prima = modulo_cervello._esegui
        modulo_cervello._esegui = self.esegui_prima
        try:
            recente = modulo_cervello.posta_recente()
        finally:
            modulo_cervello._esegui = prima
        self.assertIn("Vecchio stile", recente)
        self.assertNotIn("Schema spazi Chat", recente)

    def test_dopo_riavvio_ritrova_le_domande(self):
        identificativo = self.annunciata()
        server._cervello = modulo_cervello.Cervello()  # Ciro restarted
        self.c = server._cervello
        self.assertEqual(self.c.chiedi("A")["risposta"], "Mandato.")
        self.assertEqual(domande.leggi(identificativo)["stato"], "risposta-consegnata")


class TestRiepilogo(BaseCiro):
    def setUp(self):
        super().setUp()
        self.prima_impostazioni = modulo_cervello.IMPOSTAZIONI
        modulo_cervello.IMPOSTAZIONI = self.tmp / "impostazioni.json"
        self.prima_orologio = domande.orologio
        self.adesso = [1_800_000_000.0]
        domande.orologio = lambda: self.adesso[0]
        server.azzera_riepilogo(self.adesso[0])

    def tearDown(self):
        modulo_cervello.IMPOSTAZIONI = self.prima_impostazioni
        domande.orologio = self.prima_orologio
        super().tearDown()

    def avanti(self, minuti):
        self.adesso[0] += minuti * 60
        return server.riepilogo_se_serve(self.adesso[0])

    def test_riepilogo_solo_con_novita(self):
        identificativo = self.chiedi()
        self.giro()
        posta.rispondi_domanda(identificativo, "A", None, "utente", "opencode")
        with server._coda_lock:
            server._coda[:] = []
        self.assertIsNone(self.avanti(30))  # nothing new in 30 minutes
        self.adesso[0] += 60
        posta.recepita(identificativo, "ironworks")
        posta.risolta(identificativo)
        self.assertIsNone(self.avanti(10))  # not yet time
        frase = self.avanti(20)
        self.assertIsNotNone(frase)
        self.assertIn("ironworks", frase)
        self.assertLessEqual(frase.count(". ") + 1, 2)
        self.assertEqual([v["testo"] for v in self.coda()], [frase])
        self.assertIsNone(self.avanti(30))  # the same news is not repeated

    def test_riepilogo_spento(self):
        modulo_cervello.imposta("riepilogo", 0)
        identificativo = self.chiedi()
        self.giro()
        posta.rispondi_domanda(identificativo, "A", None, "utente", "opencode")
        posta.recepita(identificativo, "ironworks")
        for _ in range(6):
            self.assertIsNone(self.avanti(30))

    def test_riepilogo_ogni_ora(self):
        modulo_cervello.imposta("riepilogo", 60)
        identificativo = self.chiedi()
        self.giro()
        posta.rispondi_domanda(identificativo, "A", None, "utente", "opencode")
        posta.recepita(identificativo, "ironworks")
        self.assertIsNone(self.avanti(30))
        self.assertIsNotNone(self.avanti(30))

    def test_sollecito_dopo_30_min(self):
        self.chiedi("atlas")
        self.giro()
        with server._coda_lock:
            server._coda[:] = []
        self.assertIsNone(self.avanti(29))  # waiting less than 30 minutes: not news
        frase = self.avanti(31)
        self.assertIsNotNone(frase)
        self.assertIn("atlas", frase)
        self.assertIsNone(self.avanti(30))  # reminded once, not at every summary

    def test_imposta_dal_modello(self):
        uscite = iter(["Va bene. IMPOSTA: riepilogo | 60", "Fatto. IMPOSTA: riepilogo | 0"])
        prima = modulo_cervello._esegui
        modulo_cervello._esegui = lambda comando, timeout: (
            (next(uscite), "", 0) if comando[0] == "opencode" else ("[]", "", 0))
        try:
            esito = server._cervello.chiedi("riepilogo ogni ora")
            self.assertEqual(modulo_cervello.leggi_impostazioni()["riepilogo"], 60)
            self.assertNotIn("IMPOSTA", esito["risposta"])
            server._cervello.chiedi("niente riepiloghi")
            self.assertEqual(modulo_cervello.leggi_impostazioni()["riepilogo"], 0)
        finally:
            modulo_cervello._esegui = prima


class TestCodaAlRisveglio(BaseCiro):
    """While Ciro sleeps notices pile up: on waking he says only what is still open."""

    def test_domanda_gia_risposta_non_si_dice(self):
        identificativo = self.chiedi()
        self.giro()
        posta.rispondi_domanda(identificativo, "A", None, "utente", "opencode")
        with server._coda_lock:
            voci = list(server._coda)
        self.assertEqual(server.filtra_coda(voci), [])

    def test_avviso_superato_non_si_dice(self):
        vecchio = {"testo": "Da atlas: procedo?", "da": "avvisi", "chiave": "atlas|domanda|procedo?",
                   "quando": time.time()}
        self.assertEqual(server.filtra_coda([vecchio], attuali=set()), [])
        self.assertEqual(server.filtra_coda([vecchio], attuali={"atlas|domanda|procedo?"}), [vecchio])

    def test_messaggio_vecchio_scartato(self):
        vecchio = {"testo": "Riepilogo: ripartito atlas.", "da": "riepilogo", "quando": time.time() - 3600}
        nuovo = {"testo": "Ciao", "da": "opencode", "quando": time.time()}
        self.assertEqual(server.filtra_coda([vecchio, nuovo], attuali=set()), [nuovo])

    def test_tante_domande_una_frase_sola(self):
        chiavi = set()
        voci = []
        for progetto in ("alpha", "beta", "gamma", "delta"):
            chiave = "%s|domanda|x" % progetto
            chiavi.add(chiave)
            voci.append({"testo": "Da %s: x?" % progetto, "da": "avvisi", "chiave": chiave,
                         "progetto": progetto, "quando": time.time()})
        risultato = server.filtra_coda(voci, attuali=chiavi)
        self.assertEqual(len(risultato), 1)
        self.assertIn("4 domande", risultato[0]["testo"])
        self.assertIn("alpha", risultato[0]["testo"])
        # a short answer now must not go to a question Ciro never read aloud
        self.assertEqual(server._cervello.ultimo_detto.get("tipo"), "avviso")

    def test_tre_domande_si_dicono_tutte(self):
        chiavi = {"a|domanda|x", "b|domanda|x", "c|domanda|x"}
        voci = [{"testo": "Da %s: x?" % c[0], "da": "avvisi", "chiave": c, "progetto": c[0],
                 "quando": time.time()} for c in sorted(chiavi)]
        self.assertEqual(len(server.filtra_coda(voci, attuali=chiavi)), 3)


class TestAvvisiSoloDomande(BaseCiro):
    """Ciro speaks only real questions of a session, not its waiting lines."""

    def avvisi_con(self, sessione):
        modulo_cervello.leggi_sessioni = lambda: [sessione]
        server._visti = set()
        server._ultimo_avviso.clear()
        server.giro_avvisi()
        return [v["testo"] for v in self.coda()]

    def test_riga_di_attesa_non_si_dice(self):
        detti = self.avvisi_con({"progetto": "tools", "aspetta_utente": True, "da_secondi": 5, "domanda": "",
                                 "attese_per_utente": ["Utente, che deve rispondere A a Ciro"]})
        self.assertEqual(detti, [])
        # still listed on the left panel
        self.assertEqual([v["progetto"] for v in server.attese()], ["tools"])

    def test_domanda_vera_si_dice(self):
        detti = self.avvisi_con({"progetto": "tools", "aspetta_utente": True, "da_secondi": 5,
                                 "domanda": "Procedo con il deploy di prova? (S/N)", "attese_per_utente": []})
        self.assertEqual(len(detti), 1)
        self.assertIn("Procedo con il deploy di prova", detti[0])


class TestPausaProgetti(BaseCiro):
    """While projects are paused Ciro does not announce them (except the allowed ones)."""

    def setUp(self):
        super().setUp()
        self.prima_impostazioni = modulo_cervello.IMPOSTAZIONI
        modulo_cervello.IMPOSTAZIONI = self.tmp / "impostazioni.json"
        server._in_pausa.clear()

    def tearDown(self):
        modulo_cervello.IMPOSTAZIONI = self.prima_impostazioni
        super().tearDown()

    def test_domanda_strutturata_in_pausa_non_si_dice(self):
        server.imposta_pausa(True)
        identificativo = self.chiedi("ironworks")
        self.giro()
        self.assertEqual(self.coda(), [])
        self.assertEqual(domande.leggi(identificativo)["stato"], "in-attesa")  # still on the panel
        self.assertNotEqual((server._cervello.ultimo_detto or {}).get("id"), identificativo)

    def test_progetto_permesso_si_dice(self):
        server.imposta_pausa(True, ["prova-ciro"])
        self.chiedi("ironworks")
        self.chiedi("prova-ciro")
        self.giro()
        self.assertEqual([v["progetto"] for v in self.coda()], ["prova-ciro"])

    def test_avviso_sessione_in_pausa_non_si_dice(self):
        server.imposta_pausa(True)
        modulo_cervello.leggi_sessioni = lambda: [{"progetto": "atlas", "aspetta_utente": True, "da_secondi": 3,
                                                   "domanda": "Procedo? (S/N)", "attese_per_utente": []}]
        server._visti = set()
        server._ultimo_avviso.clear()
        server.giro_avvisi()
        self.assertEqual(self.coda(), [])

    def test_alla_ripresa_una_frase(self):
        server.imposta_pausa(True)
        self.chiedi("ironworks")
        self.chiedi("contoso")
        self.giro()
        server.imposta_pausa(False)
        frase = server.frase_ripresa()
        self.assertIn("2 domande", frase)
        self.assertIn("ironworks", frase)
        self.assertEqual(server.frase_ripresa(), "")

    def test_comandi_a_voce(self):
        esito = server._cervello.chiedi("pausa progetti tranne prova-ciro")
        self.assertIn("pausa", esito["risposta"].lower())
        impostazioni = modulo_cervello.leggi_impostazioni()
        self.assertEqual((impostazioni["pausa_progetti"], impostazioni["solo_progetti"]), (True, ["prova-ciro"]))
        esito = server._cervello.chiedi("riprendi i progetti")
        self.assertFalse(modulo_cervello.leggi_impostazioni()["pausa_progetti"])
        self.assertEqual(self.chiamate_modello, [])


if __name__ == "__main__":
    unittest.main()
