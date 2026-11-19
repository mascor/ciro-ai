"""Credentials go to the Keychain and nowhere else. Run from faccia/: python3 -m unittest tests.test_credenziali

The Keychain is never touched: subprocess.run is replaced by a recorder.
"""

import subprocess
import time
import unittest
from pathlib import Path

from tests.test_coordinamento_ciro import BaseCiro, domande, posta, server

SEGRETO = 'sk-Prova"123\\abc' + "x" * 200


class TestCredenziali(BaseCiro):
    def setUp(self):
        super().setUp()
        self.chiamate = []
        self.run_prima = server.subprocess.run

        def registratore(comando, *argomenti, **opzioni):
            self.chiamate.append((list(comando), opzioni.get("input")))
            return subprocess.CompletedProcess(comando, 0, "", "")
        server.subprocess.run = registratore

    def tearDown(self):
        server.subprocess.run = self.run_prima
        super().tearDown()

    def domanda_credenziale(self, progetto="ironworks"):
        identificativo = self.chiedi(progetto, "credenziali", oggetto="Chiave Shopify",
                                     domanda="Mi serve la chiave API di Shopify",
                                     opzioni={"A": "la inserisco ora", "B": "rimanda"},
                                     raccomanda="A")
        self.giro()
        return identificativo

    def test_valore_mai_negli_argomenti(self):
        identificativo = self.domanda_credenziale()
        servizio = server.salva_credenziale(identificativo, "shopify", SEGRETO)
        self.assertEqual(servizio, "ciro-ironworks-shopify")
        self.assertEqual(len(self.chiamate), 1)
        comando, ingresso = self.chiamate[0]
        self.assertEqual(comando, ["security", "-i"])
        self.assertFalse(any(SEGRETO in parte for parte in comando))
        self.assertIn("add-generic-password -U -s \"ciro-ironworks-shopify\" -a \"ironworks\" -w ", ingresso)
        # quotes and backslashes escaped for security -i
        self.assertIn('sk-Prova\\"123\\\\abc', ingresso)

    def test_valore_mai_nei_file(self):
        identificativo = self.domanda_credenziale()
        server.salva_credenziale(identificativo, "shopify", SEGRETO)
        trovati = []
        for percorso in [p for p in self.tmp.rglob("*") if p.is_file()]:
            if SEGRETO.encode() in percorso.read_bytes() or b"sk-Prova" in percorso.read_bytes():
                trovati.append(str(percorso))
        self.assertEqual(trovati, [])
        self.assertNotIn("sk-Prova", repr(server._cervello.storico))

    def test_risposta_con_nome_servizio(self):
        identificativo = self.domanda_credenziale()
        server.salva_credenziale(identificativo, "shopify", SEGRETO)
        scheda = domande.leggi(identificativo)
        self.assertEqual(scheda["stato"], "risposta-consegnata")
        messaggi = self.messaggi_a("ironworks")
        self.assertEqual(len(messaggi), 1)
        corpo = posta.leggi_intestazioni(messaggi[0])["_CORPO"]
        self.assertIn("Credenziale salvata nel Portachiavi: servizio ciro-ironworks-shopify", corpo)
        self.assertNotIn(identificativo, server._cervello.domande_in_attesa)

    def test_rifiuti(self):
        normale = self.chiedi("contoso")
        identificativo = self.domanda_credenziale()
        for domanda_id, nome, valore in ((normale, "shopify", "x"),          # not a credentials question
                                         (identificativo, "../x", "x"),       # bad name
                                         (identificativo, "Shopify Key", "x"),
                                         (identificativo, "shopify", ""),     # empty value
                                         (identificativo, "shopify", "a\nb"),  # newline
                                         ("non-esiste", "shopify", "x")):
            with self.assertRaises(ValueError, msg=(nome, valore)):
                server.salva_credenziale(domanda_id, nome, valore)
        self.assertEqual(self.chiamate, [])
        self.assertEqual(domande.leggi(identificativo)["stato"], "in-attesa")

    def test_errore_portachiavi_non_consegna(self):
        identificativo = self.domanda_credenziale()

        def guasto(comando, *argomenti, **opzioni):
            return subprocess.CompletedProcess(comando, 0, "", "SecKeychainItemCreateFromContent: error")
        server.subprocess.run = guasto
        with self.assertRaises(RuntimeError) as contesto:
            server.salva_credenziale(identificativo, "shopify", SEGRETO)
        self.assertNotIn("sk-Prova", str(contesto.exception))
        self.assertEqual(domande.leggi(identificativo)["stato"], "in-attesa")
        self.assertEqual(self.messaggi_a("ironworks"), [])

    def test_voce_dice_di_usare_il_campo(self):
        self.domanda_credenziale()
        frase = self.coda()[-1]["testo"]
        self.assertIn("campo protetto", frase)
        self.assertEqual(self.coda()[-1]["operazione"], "credenziali")


if __name__ == "__main__":
    unittest.main()
