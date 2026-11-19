"""Right-hand column: one card per open Claude Code session. Run from faccia/: python3 -m unittest tests.test_pannello_sessioni"""

import unittest

from tests.test_consumi import server


def sessione(**campi):
    base = {"progetto": "atlas", "nome": "atlas-1e", "stato": "ferma", "aspetta_utente": False,
            "da_secondi": 60, "domanda": "", "anteprima": "", "attesa": ""}
    base.update(campi)
    return base


class TestPannelloSessioni(unittest.TestCase):
    def test_ordine_e_stati(self):
        schede = server.schede_sessioni([
            sessione(progetto="zeta", stato="ferma"),
            sessione(progetto="beta", stato="al lavoro"),
            sessione(progetto="alfa", aspetta_utente=True, domanda="Procedo? (S/N)"),
        ])
        self.assertEqual([(s["progetto"], s["stato"]) for s in schede],
                         [("alfa", "aspetta te"), ("beta", "al lavoro"), ("zeta", "ferma")])

    def test_sintesi_domanda_se_aspetta_te(self):
        scheda = server.schede_sessioni([sessione(aspetta_utente=True, domanda="Procedo col deploy? (S/N)",
                                                  anteprima="[Claude · Opus 5.5] Ho finito i test.")])[0]
        self.assertEqual(scheda["sintesi"], "Procedo col deploy? (S/N)")

    def test_sintesi_ultima_frase_senza_modello_in_testa(self):
        scheda = server.schede_sessioni([sessione(
            anteprima="[Claude · Opus 5.5] La scena è caricata sul pod (968 MB). Ora parte il render.")])[0]
        self.assertEqual(scheda["sintesi"], "La scena è caricata sul pod (968 MB). Ora parte il render.")

    def test_sintesi_da_chi_aspetta_quando_manca_la_frase(self):
        scheda = server.schede_sessioni([sessione(
            anteprima="[Claude · Opus 5.5]",
            attesa="Alice, che deve rispondere alle domande sulle luci "
                   "(messaggio: /Users/x/ATLAS-PER-Alice.txt) · sessione hardware, che deve leggere")])[0]
        self.assertEqual(scheda["sintesi"], "Aspetta Alice, che deve rispondere alle domande sulle luci")

    def test_sintesi_accorciata_su_una_riga(self):
        scheda = server.schede_sessioni([sessione(anteprima="**Fatto**\n" + "parola " * 60)])[0]
        self.assertNotIn("\n", scheda["sintesi"])
        self.assertNotIn("*", scheda["sintesi"])
        self.assertLessEqual(len(scheda["sintesi"]), 141)
        self.assertTrue(scheda["sintesi"].endswith("…"))

    def test_proprietario_e_repo_dall_indirizzo(self):
        casi = {
            "https://github.com/ironworks-corp/agent-platform.git": ("ironworks-corp", "agent-platform"),
            "git@github.com:example/atlas-docs.git": ("example", "atlas-docs"),
            "https://github.com/contoso-org/atlas-hardware": ("contoso-org", "atlas-hardware"),
            "ssh://git@github.com/Example/Repo.git/": ("Example", "Repo"),
            "": None, "non un indirizzo": None,
        }
        for url, atteso in casi.items():
            self.assertEqual(server.proprietario_repo(url), atteso, url)

    def test_titolo_proprietario_repo_e_ordine(self):
        repo = {"/a": ("ironworks-corp", "ironworks-mcp"), "/b": ("nordic", "atlas-docs"),
                "/c": ("ironworks-corp", "agent-platform"), "/d": None}
        schede = server.schede_sessioni([
            sessione(progetto="atlas", cwd="/b"),
            sessione(progetto="mcp", cwd="/a"),
            sessione(progetto="tools", cwd="/d"),
            sessione(progetto="hermes", cwd="/c"),
        ], repo_di=repo.get)
        self.assertEqual([s["titolo"] for s in schede],
                         ["ironworks-corp/agent-platform", "ironworks-corp/ironworks-mcp",
                          "nordic/atlas-docs", "tools"])
        self.assertEqual([s["proprietario"] for s in schede], ["ironworks-corp", "ironworks-corp", "nordic", ""])
        self.assertEqual(schede[0]["repo"], "agent-platform")

    def test_campi_per_la_pagina(self):
        scheda = server.schede_sessioni([sessione(da_secondi=125)])[0]
        self.assertEqual(scheda["secondi"], 125)
        self.assertEqual(scheda["nome"], "atlas-1e")
        self.assertEqual(server.schede_sessioni(None), [])


if __name__ == "__main__":
    unittest.main()
