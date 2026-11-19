"""«Ciro, cosa mi sono perso?»: what happened since the user last spoke, and who waits now.

Run from ciro/: python3 -m unittest tests.test_perso
"""

import time

import cervello as modulo_cervello_diretto
from tests.test_coordinamento_ciro import BaseCiro, domande, modulo_cervello, server


class TestCosaMiSonoPerso(BaseCiro):
    def setUp(self):
        super().setUp()
        self.c = server._cervello
        self.c.riassunto_perso = server.frase_perso

    def apri(self, progetto, **altro):
        identificativo = self.chiedi(progetto=progetto, **altro)
        self.giro()
        return identificativo

    def test_riconosce_le_frasi(self):
        for frase in ("Ciro, cosa mi sono perso?", "che mi sono perso", "Cosa è successo mentre ero via?",
                      "novità?", "aggiornami", "What did I miss?", "catch me up"):
            detto = modulo_cervello_diretto.re.sub(r"[^\w\s']+", " ", frase.lower())
            detto = modulo_cervello_diretto.re.sub(r"\s+", " ", detto).strip()
            self.assertTrue(modulo_cervello.PERSO_RE.match(detto), frase)
        for frase in ("cosa mi sono perso nel deploy di ieri con contoso", "perso", "che succede"):
            detto = modulo_cervello_diretto.re.sub(r"[^\w\s']+", " ", frase.lower()).strip()
            self.assertFalse(modulo_cervello.PERSO_RE.match(detto), frase)

    def test_niente_di_nuovo(self):
        esito = self.c.chiedi("cosa mi sono perso?")
        self.assertIn("Niente di nuovo dalle", esito["risposta"])
        self.assertIn("nessuno ti aspetta", esito["risposta"])
        self.assertFalse(esito["mandato"])

    def test_domande_nuove_e_chi_aspetta_per_numero(self):
        self.apri("ironworks")
        self.apri("contoso")
        esito = self.c.chiedi("Ciro, cosa mi sono perso?")
        risposta = esito["risposta"]
        self.assertIn("2 domande nuove da contoso e ironworks", risposta)
        self.assertIn("Ti aspettano: la uno, ironworks; la due, contoso.", risposta)

    def test_da_quando(self):
        visti = []
        self.c.riassunto_perso = lambda dal: visti.append(dal) or "ok"
        adesso = time.time()
        self.c.chiedi("cosa mi sono perso")                     # first time, user was here: last hour
        self.assertAlmostEqual(visti[-1], adesso - modulo_cervello.PERSO_PREDEFINITO, delta=2)
        self.c.ultimo_utente_t = adesso - 20 * 60                # then silent for 20 minutes
        self.c.chiedi("cosa mi sono perso")
        self.assertAlmostEqual(visti[-1], adesso - 20 * 60, delta=2)
        self.c.chiedi("novità")                                  # right after: since the last ask
        self.assertAlmostEqual(visti[-1], adesso, delta=2)
        self.c.ultimo_utente_t = adesso - 48 * 3600              # away two days: at most 12 hours
        self.c.chiedi("aggiornami")
        self.assertAlmostEqual(visti[-1], adesso - modulo_cervello.PERSO_MASSIMO, delta=2)

    def test_risposta_breve_dopo_il_punto_non_va_indovinata(self):
        self.apri("ironworks")
        seconda = self.apri("contoso")
        self.c.chiedi("cosa mi sono perso")
        esito = self.c.chiedi("A")
        self.assertFalse(esito["mandato"])
        self.assertIn("Quale domanda?", esito["risposta"])
        self.assertEqual(domande.leggi(seconda)["stato"], "in-attesa")

    def test_in_inglese(self):
        modulo_cervello.imposta("lingua", "en")
        esito = self.c.chiedi("what did I miss?")
        self.assertIn("Nothing new since", esito["risposta"])

    def test_senza_modello(self):
        chiamate = []
        prima = modulo_cervello._esegui
        modulo_cervello._esegui = lambda comando, timeout: chiamate.append(comando) or ("", "", 1)
        try:
            self.c.chiedi("cosa mi sono perso")
        finally:
            modulo_cervello._esegui = prima
        self.assertFalse([c for c in chiamate if c and c[0] == "opencode"])
