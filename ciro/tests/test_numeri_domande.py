"""Questions by number: «Domanda tre, da ...», answered with «tre, sì» or «la tre: due».

Run from ciro/: python3 -m unittest tests.test_numeri_domande
"""

import unittest

from tests.test_coordinamento_ciro import BaseCiro, domande, modulo_cervello, posta, server


class TestNumeriDomande(BaseCiro):
    def apri(self, progetto, **altro):
        identificativo = self.chiedi(progetto=progetto, **altro)
        self.giro()
        return identificativo

    def test_numeri_bassi_e_stabili(self):
        prima = self.apri("ironworks")
        seconda = self.apri("contoso")
        numeri = {v["domanda_id"]: v["numero"] for v in server.attese() if v.get("domanda_id")}
        self.assertEqual(numeri, {prima: 1, seconda: 2})
        # the number is said first
        testi = [v["testo"] for v in self.coda()]
        self.assertTrue(testi[0].startswith("Domanda uno, da ironworks:"), testi[0])
        self.assertTrue(testi[1].startswith("Domanda due, da contoso:"), testi[1])
        # closing the first frees number 1; the second keeps 2
        server._cervello.chiedi("uno, uno")
        self.assertEqual(domande.leggi(prima)["stato"], "risposta-consegnata")
        numeri = {v["domanda_id"]: v["numero"] for v in server.attese() if v.get("domanda_id")}
        self.assertEqual(numeri, {seconda: 2})
        terza = self.apri("atlas")
        numeri = {v["domanda_id"]: v["numero"] for v in server.attese() if v.get("domanda_id")}
        self.assertEqual(numeri, {seconda: 2, terza: 1})

    def test_risposta_per_numero_va_alla_domanda_giusta(self):
        prima = self.apri("ironworks")
        seconda = self.apri("contoso")
        esito = server._cervello.chiedi("la uno: due")   # question 1, option 2, not the last one said
        self.assertTrue(esito["mandato"], esito)
        self.assertEqual(domande.leggi(prima)["risposta"]["scelta"], "B")
        self.assertEqual(domande.leggi(seconda)["stato"], "in-attesa")

    def test_due_cifre_attaccate(self):
        self.apri("ironworks")
        seconda = self.apri("contoso")
        esito = server._cervello.chiedi("21")   # whisper writes «due uno» as 21
        self.assertTrue(esito["mandato"], esito)
        self.assertEqual(domande.leggi(seconda)["risposta"]["scelta"], "A")

    def test_si_no_per_numero(self):
        self.apri("ironworks", opzioni={"S": "procedi", "N": "fermati"}, raccomanda="S")
        seconda = self.apri("contoso", opzioni={"S": "procedi", "N": "fermati"}, raccomanda="S")
        esito = server._cervello.chiedi("Due, sì.")
        self.assertTrue(esito["mandato"], esito)
        self.assertEqual(domande.leggi(seconda)["risposta"]["scelta"], "S")

    def test_numero_che_non_esiste(self):
        self.apri("ironworks")
        esito = server._cervello.chiedi("domanda sette, sì")
        self.assertFalse(esito["mandato"])
        self.assertIn("Non c'è una domanda sette", esito["risposta"])
        self.assertIn("la uno, ironworks", esito["risposta"])

    def test_quale_domanda_al_posto_del_progetto(self):
        self.apri("ironworks")
        seconda = self.apri("contoso")
        server._cervello.ultimo_detto = {"tipo": "avviso", "id": "altro", "ora": 0}
        esito = server._cervello.chiedi("due")
        self.assertIn("Quale domanda?", esito["risposta"])
        self.assertIn("la due, contoso", esito["risposta"])
        esito = server._cervello.chiedi("la due")   # after «Quale domanda?»: the number
        self.assertTrue(esito["mandato"], esito)
        self.assertEqual(domande.leggi(seconda)["risposta"]["scelta"], "B")

    def test_domanda_tre_la_ridice(self):
        self.apri("ironworks")
        self.apri("contoso")
        esito = server._cervello.chiedi("domanda uno")
        self.assertFalse(esito["mandato"])
        self.assertIn("ironworks", esito["risposta"])
        esito = server._cervello.chiedi("uno")   # now a short answer goes to question 1
        self.assertTrue(esito["mandato"], esito)

    def test_frase_con_un_numero_non_e_una_risposta(self):
        self.apri("ironworks")
        self.assertIsNone(server._cervello.risposta_veloce("uno per prova due e poi vediamo"))

    def test_messaggio_di_posta_numerato(self):
        posta.invia("contoso", "opencode", "decisione", "Unisco la PR?", "S/N",
                    azione="decisione")
        voci = server.attese()
        numero = [v["numero"] for v in voci if v["progetto"] == "contoso"][0]
        esito = server._cervello.chiedi("%s sì" % ["", "uno", "due", "tre"][numero])
        self.assertTrue(esito["mandato"], esito)
        self.assertEqual(len(self.messaggi_a("contoso")), 1)

    def test_numeri_sopravvivono_al_riavvio(self):
        prima = self.apri("ironworks")
        server.attese()
        server._cervello = modulo_cervello.Cervello()   # Ciro restarted
        numeri = {v["domanda_id"]: v["numero"] for v in server.attese() if v.get("domanda_id")}
        self.assertEqual(numeri, {prima: 1})


if __name__ == "__main__":
    unittest.main()
