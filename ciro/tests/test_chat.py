"""Google Chat in Ciro: unread conversations from the extension, urgency by the model.

Run from ciro/: python3 -m unittest tests.test_chat
All names are fake.
"""

import json
import time
import unittest

import chat as modulo_chat
from tests.test_coordinamento_ciro import BaseCiro, modulo_cervello, server


def conversazione(id_, righe):
    return {"conversazione": id_, "righe": righe}


DIRETTA = conversazione("dm/AAA", ["Luca Bianchi", "16:05", "Unread", "Mi confermi il preventivo entro oggi?"])
SPAZIO = conversazione("space/BBB", ["Sviluppo", "15:40", "Unread", "Luca: build verde", "Attivato da Sara"])


class TestEstrazione(unittest.TestCase):
    def test_nome_e_testo(self):
        self.assertEqual(modulo_chat.estrai(DIRETTA["righe"]),
                         ("Luca Bianchi", "Mi confermi il preventivo entro oggi?"))

    def test_righe_tecniche_tolte(self):
        nome, testo = modulo_chat.estrai(SPAZIO["righe"])
        self.assertEqual(nome, "Sviluppo")
        self.assertEqual(testo, "Luca: build verde")

    def test_italiano(self):
        self.assertEqual(modulo_chat.estrai(["Sara", "ieri", "Non letto", "ok"]), ("Sara", "ok"))


class TestChat(BaseCiro):
    def setUp(self):
        super().setUp()
        self.risposte_modello = []
        self.chat = modulo_chat.Chat(lambda: self.tmp / "chat.json")
        server._chat = self.chat

        def modello(prompt):
            self.risposte_modello.append(prompt)
            return self.urgenza
        self.urgenza = '{"urgente": true, "risposta": true, "motivo": "chiede una conferma oggi"}'
        server._chiedi_urgenza = modello
        server._visti = set()
        server._ultimo_avviso.clear()
        server._promemoria_chat.clear()
        server._cervello.chiudi_chat = self.chat.chiudi

    def arriva(self, *conversazioni, account="work@example.com"):
        server.ricevi_chat({"account": account, "conversazioni": list(conversazioni)}, in_sottofondo=False)

    def chat_in_attesa(self):
        return [v for v in server.attese() if v.get("tipo") == "chat"]

    def test_diretta_urgente_detta_con_numero(self):
        self.arriva(DIRETTA)
        server.giro_avvisi()
        detti = [v["testo"] for v in self.coda()]
        self.assertEqual(len(detti), 1, detti)
        self.assertTrue(detti[0].startswith("Messaggio uno, da Luca Bianchi:"), detti[0])
        self.assertIn("preventivo", detti[0])

    def test_spazio_solo_pannello_senza_modello(self):
        self.arriva(SPAZIO)
        server.giro_avvisi()
        self.assertEqual(self.coda(), [])
        self.assertEqual(self.risposte_modello, [])      # spaces never go to the model
        self.assertEqual([v["progetto"] for v in self.chat_in_attesa()], ["chat"])

    def test_non_urgente_solo_pannello(self):
        self.urgenza = '{"urgente": false, "risposta": false, "motivo": "un saluto"}'
        self.arriva(DIRETTA)
        server.giro_avvisi()
        self.assertEqual(self.coda(), [])
        self.assertEqual(len(self.chat_in_attesa()), 1)

    def test_modello_muto_resta_silenzioso(self):
        self.urgenza = "non so"
        self.arriva(DIRETTA)
        server.giro_avvisi()
        self.assertEqual(self.coda(), [])
        self.assertEqual(len(self.chat_in_attesa()), 1)

    def test_stessa_conversazione_una_volta(self):
        self.arriva(DIRETTA)
        self.arriva(DIRETTA)
        server.giro_avvisi()
        self.assertEqual(len(self.chat_in_attesa()), 1)
        self.assertEqual(len(self.risposte_modello), 1)  # same text: judged once

    def test_letta_in_chat_sparisce(self):
        self.arriva(DIRETTA, SPAZIO)
        self.arriva(SPAZIO)                              # the direct one was read in Chat
        self.assertEqual([v["chat_id"] for v in self.chat_in_attesa()], ["work@example.com|space/BBB"])

    def test_scade_dopo_due_ore(self):
        self.arriva(DIRETTA)
        dopo = time.time() + 7201
        self.assertEqual(self.chat.aperte(adesso=dopo), [])

    def test_pausa_ferma_la_chat(self):
        modulo_cervello.imposta("pausa_progetti", True)
        self.arriva(DIRETTA)
        server.giro_avvisi()
        self.assertEqual(self.coda(), [])

    def test_testo_lungo_tagliato(self):
        lunga = conversazione("dm/CCC", ["Luca", "16:00", "Unread", "parola " * 200])
        self.arriva(lunga)
        server.giro_avvisi()
        detto = self.coda()[0]["testo"]
        self.assertLessEqual(len(detto), 400)

    def test_letto_il_numero_chiude(self):
        self.arriva(DIRETTA)
        server.attese()                                  # numbers assigned
        esito = server._cervello.chiedi("letto il uno")
        self.assertEqual(esito["risposta"], "Va bene.")
        self.assertEqual(self.chat_in_attesa(), [])

    def test_account_assente(self):
        self.arriva(SPAZIO)
        self.assertEqual(self.chat.account_assenti(adesso=time.time() + 301), ["work@example.com"])

    def test_solo_testo_minimo_al_modello(self):
        self.arriva(DIRETTA)
        prompt = self.risposte_modello[0]
        self.assertIn("Mi confermi il preventivo entro oggi?", prompt)
        self.assertNotIn("work@example.com", prompt)     # the account does not leave the Mac

    def test_promemoria_ogni_quindici_minuti(self):
        self.arriva(DIRETTA)
        adesso = time.time()
        server.giro_chat(adesso=adesso)                  # first time: said at once
        self.assertEqual(len(self.coda()), 1)
        server.giro_chat(adesso=adesso + 600)            # 10 minutes: nothing
        self.assertEqual(len(self.coda()), 1)
        server.giro_chat(adesso=adesso + 901)            # 15 minutes: reminder
        self.assertEqual(len(self.coda()), 2)
        self.assertTrue(self.coda()[-1]["testo"].startswith("Ti ricordo il messaggio uno, da Luca Bianchi"),
                        self.coda()[-1]["testo"])

    def test_tre_account_separati(self):
        for account in ("a@example.com", "b@example.com", "c@example.org"):
            self.arriva(conversazione("dm/X1", ["Luca", "16:00", "Unread", "ciao " + account]), account=account)
        voci = self.chat_in_attesa()
        self.assertEqual(sorted(v["account"] for v in voci), ["a@example.com", "b@example.com", "c@example.org"])
        self.assertEqual(len({v["numero"] for v in voci}), 3)
        self.arriva(account="b@example.com")             # read in profile b: only b leaves
        self.assertEqual(sorted(v["account"] for v in self.chat_in_attesa()), ["a@example.com", "c@example.org"])


if __name__ == "__main__":
    unittest.main()
