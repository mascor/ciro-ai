"""«Chiudi cinque» and the × of the panel: an item disappears until something new arrives.

Run from ciro/: python3 -m unittest tests.test_chiudi
"""

from tests.test_chat import DIRETTA
from tests.test_coordinamento_ciro import BaseCiro, domande, posta, server
import chat as modulo_chat


class TestChiudi(BaseCiro):
    def setUp(self):
        super().setUp()
        self.c = server._cervello
        self.chat_prima = server._chat
        server._chat = modulo_chat.Chat(lambda: self.tmp / "chat.json")
        self.c.chiudi_chat = server._chat.chiudi
        self.c.nascondi = server.nascondi

    def tearDown(self):
        server._chat = self.chat_prima
        super().tearDown()

    def apri(self, progetto):
        identificativo = self.chiedi(progetto=progetto)
        self.giro()
        return identificativo

    def test_chiudi_una_domanda_della_sessione(self):
        identificativo = self.apri("ironworks")
        voce = [v for v in server.attese() if v.get("domanda_id") == identificativo][0]
        esito = self.c.chiedi("chiudi la %s" % ["", "uno", "due", "tre"][voce["numero"]])
        self.assertFalse(esito["mandato"])
        self.assertIn("Chiusa", esito["risposta"])
        self.assertIn("ironworks aspetta ancora", esito["risposta"])
        self.assertEqual([v for v in server.attese() if v.get("domanda_id") == identificativo], [])
        self.assertEqual(domande.leggi(identificativo)["stato"], "in-attesa")   # not answered

    def test_messaggio_di_posta_torna_se_cambia(self):
        posta.invia("contoso", "opencode", "decisione", "Unisco la PR?", "S/N", azione="decisione")
        voce = [v for v in server.attese() if v["progetto"] == "contoso"][0]
        self.assertTrue(server.nascondi(voce["chiave"]))
        self.assertEqual([v for v in server.attese() if v["progetto"] == "contoso"], [])
        posta.invia("contoso", "opencode", "decisione", "Rilascio adesso?", "S/N", azione="decisione")
        self.assertTrue([v for v in server.attese() if v["progetto"] == "contoso"])

    def test_chiudi_un_messaggio_di_chat(self):
        server.ricevi_chat({"account": "work@example.com", "conversazioni": [DIRETTA]}, in_sottofondo=False)
        voce = [v for v in server.attese() if v.get("tipo") == "chat"][0]
        esito = self.c.chiedi("chiudi l'undici")
        self.assertEqual(esito["risposta"], "Chiusa la undici.")
        self.assertEqual([v for v in server.attese() if v.get("tipo") == "chat"], [])
        self.assertEqual(voce["numero"], 11)

    def test_numero_che_non_esiste(self):
        esito = self.c.chiedi("chiudi sette")
        self.assertIn("Non c'è una domanda sette", esito["risposta"])

    def test_chiudi_seguito_da_parole_non_e_un_comando(self):
        self.assertIsNone(self.c._risposta_per_numero("chiudi la porta", "chiudi la porta"))
