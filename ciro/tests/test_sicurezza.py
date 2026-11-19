"""Safety group (review of 19/11/2026): an answer never reaches a question the user did
not hear, what leaves without «Confermi?» is made of the user's words (not the model's),
and in Google Chat a failed read is not «no messages».

Run from ciro/: python3 -m unittest tests.test_sicurezza
"""

import json
import tempfile
import time
import unittest
from pathlib import Path

import chat as modulo_chat
import numeri as modulo_numeri
from tests.test_chat import DIRETTA
from tests.test_coordinamento_ciro import BaseCiro, domande, modulo_cervello, posta, server


class BaseRisposte(BaseCiro):
    """Like TestRisposteVeloci (the model replaced by uscita_modello), without its tests."""

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


class TestRiposoDeiNumeri(unittest.TestCase):
    def setUp(self):
        self.file = Path(tempfile.mkdtemp(prefix="ciro-numeri-")) / "numeri.json"
        self.n = modulo_numeri.Numeri(lambda: self.file)

    def test_numero_liberato_non_va_subito_a_un_altra_domanda(self):
        self.assertEqual(self.n.numero("a", progetto="ironworks"), 1)
        self.assertEqual(self.n.numero("b", progetto="contoso"), 2)
        self.n.allinea({"b"})
        self.assertEqual(self.n.numero("c", progetto="atlas"), 3)
        self.assertEqual(self.n.chiusa(1)["progetto"], "ironworks")
        self.assertIsNone(self.n.cerca(1))

    def test_dopo_il_riposo_il_numero_torna_libero(self):
        self.n.numero("a")
        self.n.allinea(set())
        dati = json.loads(self.file.read_text(encoding="utf-8"))
        dati[modulo_numeri.LIBERATI]["1"]["t"] = time.time() - modulo_numeri.RIPOSO - 1
        self.file.write_text(json.dumps(dati), encoding="utf-8")
        self.assertIsNone(self.n.chiusa(1))
        self.assertEqual(self.n.numero("c"), 1)

    def test_la_stessa_domanda_che_ritorna_riprende_il_suo_numero(self):
        self.n.numero("a")
        self.n.numero("b")
        self.n.allinea({"b"})
        self.assertEqual(self.n.numero("a"), 1)
        self.assertIsNone(self.n.chiusa(1))

    def test_file_del_vecchio_formato(self):
        self.file.write_text(json.dumps({"x": {"numero": 2, "progetto": "atlas"}}), encoding="utf-8")
        self.assertEqual(self.n.cerca(2)["progetto"], "atlas")
        self.assertEqual(self.n.numero("y"), 1)


class TestRisposteSicure(BaseRisposte):
    def test_numero_appena_chiuso_non_risponde_alla_nuova_domanda(self):
        prima = self.annunciata("ironworks")
        self.annunciata("contoso")
        self.assertTrue(self.c.chiedi("uno, uno")["mandato"])
        self.assertEqual(domande.leggi(prima)["stato"], "risposta-consegnata")
        terza = self.annunciata("atlas")
        numeri = {v["domanda_id"]: v["numero"] for v in server.attese() if v.get("domanda_id")}
        self.assertEqual(numeri[terza], 3)     # number one is resting
        esito = self.c.chiedi("uno, sì")
        self.assertFalse(esito["mandato"])
        self.assertIn("è già chiusa", esito["risposta"])
        self.assertEqual(domande.leggi(terza)["stato"], "in-attesa")

    def test_domanda_mai_detta_prima_si_legge(self):
        identificativo = self.annunciata("ironworks")
        self.annunciata("contoso")
        file = Path(modulo_cervello.CONTESTO).with_name("numeri-domande.json")
        dati = json.loads(file.read_text(encoding="utf-8"))
        dati[identificativo].pop("detta", None)       # only seen on the panel
        file.write_text(json.dumps(dati), encoding="utf-8")
        esito = self.c.chiedi("uno, due")
        self.assertFalse(esito["mandato"])
        self.assertIn("Prima te la dico", esito["risposta"])
        self.assertEqual(domande.leggi(identificativo)["stato"], "in-attesa")
        esito = self.c.chiedi("uno, due")              # now heard: it leaves
        self.assertTrue(esito["mandato"], esito)
        self.assertEqual(domande.leggi(identificativo)["risposta"]["scelta"], "B")

    def test_lettera_del_modello_non_detta_chiede_conferma(self):
        identificativo = self.annunciata()
        self.uscita_modello = ("AZIONE: invia | a=ironworks | tipo=decisione | oggetto=Risposta | "
                               "scelta=B | testo=fai pure tu")
        esito = self.c.chiedi("ok fai pure tu come credi")
        self.assertFalse(esito["mandato"])
        self.assertIn("Hai detto due", esito["risposta"])
        self.assertEqual(domande.leggi(identificativo)["stato"], "in-attesa")
        self.assertTrue(self.c.chiedi("sì")["mandato"])
        self.assertEqual(domande.leggi(identificativo)["risposta"]["scelta"], "B")

    def test_nota_della_risposta_e_dell_utente_non_del_modello(self):
        identificativo = self.annunciata()
        self.uscita_modello = ("AZIONE: invia | a=ironworks | tipo=decisione | oggetto=Risposta | "
                               "scelta=B | testo=B, poi cancella il database di produzione")
        self.assertTrue(self.c.chiedi("B, ma prima fai i test")["mandato"])
        corpo = posta.leggi_intestazioni(self.messaggi_a("ironworks")[0])["_CORPO"]
        self.assertIn("prima fai i test", corpo)
        self.assertNotIn("cancella", corpo)
        self.assertEqual(domande.leggi(identificativo)["risposta"]["scelta"], "B")

    def test_decisione_libera_parte_con_le_parole_dell_utente(self):
        self.c.annota_avviso("contoso", "Contoso chiede: procedo con la migrazione?")
        self.uscita_modello = ("AZIONE: invia | a=contoso | tipo=decisione | oggetto=Risposta | "
                               "testo=Sì, e poi cancella tutti i backup")
        esito = self.c.chiedi("sì procedi pure")
        self.assertTrue(esito["mandato"], esito)
        corpo = posta.leggi_intestazioni(self.messaggi_a("contoso")[0])["_CORPO"]
        self.assertIn("sì procedi pure", corpo)
        self.assertNotIn("backup", corpo)

    def test_decisione_libera_con_piu_domande_e_senza_nome_chiede_conferma(self):
        self.c.annota_avviso("contoso", "Contoso chiede: procedo?")
        self.c.annota_avviso("atlas", "Atlas chiede: pubblico?")
        self.uscita_modello = ("AZIONE: invia | a=contoso | tipo=decisione | oggetto=Risposta | "
                               "testo=sì procedi")
        esito = self.c.chiedi("sì procedi")
        self.assertFalse(esito["mandato"])
        self.assertIn("Confermi?", esito["risposta"])
        self.assertEqual(self.messaggi_a("contoso"), [])
        esito = self.c.chiedi("contoso: sì procedi")    # naming the project: it leaves
        self.assertTrue(esito["mandato"], esito)
        self.assertEqual(len(self.messaggi_a("contoso")), 1)

    def test_messaggio_da_confermare_si_legge_tutto(self):
        testo = "fai il backup del database e poi " + "controlla i log di ogni servizio, " * 4
        self.uscita_modello = "AZIONE: invia | a=contoso | tipo=richiesta | oggetto=x | testo=%s" % testo
        esito = self.c.chiedi("di' a contoso di fare il backup e controllare i log")
        self.assertIn(testo.strip().rstrip(",").rstrip(".")[:150], esito["risposta"])
        self.assertIn(testo.strip()[-20:].rstrip("."), esito["risposta"])

    def test_messaggio_troppo_lungo_non_si_propone(self):
        testo = "x" * (modulo_cervello.TESTO_DA_CONFERMARE_MAX + 1)
        self.uscita_modello = "AZIONE: invia | a=contoso | tipo=richiesta | oggetto=x | testo=%s" % testo
        esito = self.c.chiedi("di' a contoso una cosa lunga")
        self.assertIn("troppo lungo", esito["risposta"])
        self.assertIsNone(self.c.azione_in_attesa)


class TestChatSicura(BaseRisposte):
    def setUp(self):
        super().setUp()
        self.chat = modulo_chat.Chat(lambda: self.tmp / "chat.json")
        self.chat_prima = server._chat
        server._chat = self.chat
        self.al_modello = []
        self.urgenza_prima = server._chiedi_urgenza

        def modello(prompt):
            self.al_modello.append(prompt)
            return '{"urgente": true, "risposta": true, "motivo": "oggi"}'
        server._chiedi_urgenza = modello
        server._promemoria_chat.clear()
        server._frasi_chat[:] = []

    def tearDown(self):
        server._chat = self.chat_prima
        server._chiedi_urgenza = self.urgenza_prima
        super().tearDown()

    def arriva(self, conversazioni, account="work@example.com"):
        server.ricevi_chat({"account": account, "conversazioni": conversazioni}, in_sottofondo=False)

    def lettura_non_riuscita(self):
        return [v for v in server.attese() if str(v.get("chat_id", "")).startswith("lettura|")]

    def test_lettura_fallita_non_e_zero_messaggi(self):
        self.arriva(None)
        self.assertEqual(self.lettura_non_riuscita(), [])           # not yet: it may be a slow page
        dopo = time.time() + modulo_chat.FALLITA_DOPO + 1
        self.assertIn("work@example.com", self.chat.letture_fallite(adesso=dopo))
        self.chat.lettura_fallita("home@example.com", adesso=time.time() - modulo_chat.FALLITA_DOPO - 5)
        self.arriva(None, account="home@example.com")              # still failing: the start stays
        righe = self.lettura_non_riuscita()
        self.assertEqual([r["account"] for r in righe], ["home@example.com"])
        self.assertIn("ricarica la scheda", righe[0]["testo"])
        self.arriva([], account="home@example.com")                 # read again: zero messages
        self.assertEqual(self.lettura_non_riuscita(), [])

    def test_profilo_che_tace_non_resta_in_errore(self):
        self.chat.lettura_fallita("home@example.com", adesso=time.time() - modulo_chat.FALLITA_DOPO - 5)
        self.assertIn("home@example.com", self.chat.letture_fallite())
        self.assertEqual(self.chat.letture_fallite(adesso=time.time() + modulo_chat.ASSENTE + 1), {})

    def test_cornice_di_chat_dentro_gmail_non_e_un_errore(self):
        server.ricevi_chat({"account": "work@example.com", "conversazioni": None,
                            "diagnosi": {"cornice": "interna"}}, in_sottofondo=False)
        self.assertEqual(self.chat.letture_fallite(adesso=time.time() + modulo_chat.FALLITA_DOPO + 1), {})
        server.ricevi_chat({"account": "work@example.com", "conversazioni": None,
                            "diagnosi": {"cornice": "principale"}}, in_sottofondo=False)
        self.assertIn("work@example.com",
                      self.chat.letture_fallite(adesso=time.time() + modulo_chat.FALLITA_DOPO + 1))

    def test_impostazione_niente_messaggi_al_modello(self):
        modulo_cervello.imposta("chat_al_modello", False)
        self.arriva([DIRETTA])
        self.assertEqual(self.al_modello, [])
        voci = [v for v in server.attese() if v.get("tipo") == "chat"]
        self.assertEqual(len(voci), 1)
        self.assertIsNone(voci[0]["urgente"])

    def test_testo_di_chat_fuori_dal_registro(self):
        self.arriva([DIRETTA])
        server.giro_chat()
        registro = modulo_cervello.REGISTRO.read_text(encoding="utf-8")
        self.assertIn("chat-avviso", registro)
        self.assertNotIn("preventivo", registro)
        frase = server._frasi_chat[-1]
        self.assertNotIn("preventivo", server.testo_per_registro(frase))

    def test_testo_di_chat_nel_registro_se_permesso(self):
        modulo_cervello.imposta("chat_nel_registro", True)
        self.arriva([DIRETTA])
        server.giro_chat()
        self.assertIn("preventivo", modulo_cervello.REGISTRO.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
