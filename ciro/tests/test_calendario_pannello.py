"""Red calendar events in «Ti aspettano» (#27) and spoken from T-30, every 5 minutes (#28).

Run from ciro/: python3 -m unittest tests.test_calendario_pannello
All names are fake; no network (the reader gets fake answers).
"""

import time
import unittest

import calendario
from tests.test_coordinamento_ciro import BaseCiro, server


def evento(ident, tra_minuti, adesso, colore="11", titolo="Call with Rossi"):
    return {"id": ident, "status": "confirmed", "summary": titolo, "colorId": colore,
            "start": {"dateTime": calendario.rfc3339(adesso + tra_minuti * 60)}}


class TestCalendarioPannello(BaseCiro):
    def setUp(self):
        super().setUp()
        self.adesso = time.time()
        self.risposte = {}
        self.guasto = False

        def scarica(account, calendario_, time_min, time_max):
            if self.guasto:
                raise OSError("down")
            return {"items": self.risposte.get(account, [])}

        server._calendario = calendario.Lettore(scarica, lambda: {"work": {"calendari": ["primary"]}})
        server._eventi_calendario = []
        server._calendario_non_aggiornati = []
        self.addCleanup(setattr, server, "_eventi_calendario", [])
        self.addCleanup(setattr, server, "_calendario_non_aggiornati", [])

    def calendario_in_attesa(self):
        return [v for v in server.attese() if v.get("tipo") == "calendario"]

    def test_evento_rosso_in_cima_con_numero(self):
        self.risposte["work"] = [evento("b", 25, self.adesso, titolo="Visit"),
                                 evento("a", 10, self.adesso), evento("blu", 5, self.adesso, colore="9")]
        server.giro_calendario(self.adesso)
        voci = server.attese()
        self.assertEqual([v["tipo"] for v in voci[:2]], ["calendario", "calendario"])
        primo = voci[0]
        self.assertEqual(primo["testo"], "Call with Rossi")       # the closest first
        self.assertEqual(primo["ora"], time.strftime("%H:%M", time.localtime(int(self.adesso) + 600)))
        self.assertEqual((primo["account"], primo["calendario"]), ("work", "primary"))
        self.assertIn(primo["minuti"], (9, 10))
        self.assertTrue(primo["numero"])
        self.assertTrue(primo["chiave"].startswith("calendario|work|a|"))
        self.assertEqual(len(self.calendario_in_attesa()), 2)

    def detti(self):
        return [v["testo"] for v in self.coda() if v.get("da") == "calendario"]

    def test_detto_a_trenta_minuti(self):
        server._promemoria_calendario.clear()
        server._calendario_confermati.clear()
        self.risposte["work"] = [evento("a", 20, self.adesso)]
        server.giro_calendario(self.adesso)
        server.giro_calendario_voce(server.attese(), self.adesso)
        detti = self.detti()
        self.assertEqual(len(detti), 1, detti)
        self.assertTrue(detti[0].startswith("Appuntamento "), detti[0])
        self.assertIn("Call with Rossi", detti[0])
        self.assertIn("lo gestisco", detti[0])

    def test_non_prima_di_trenta_minuti(self):
        server._promemoria_calendario.clear()
        self.risposte["work"] = [evento("a", 33, self.adesso)]
        server.giro_calendario(self.adesso)
        server.giro_calendario_voce(server.attese(), self.adesso)
        self.assertEqual(self.detti(), [])
        self.assertEqual(len(self.calendario_in_attesa()), 1)      # in the panel already

    def test_ripetuto_ogni_cinque_minuti(self):
        server._promemoria_calendario.clear()
        self.risposte["work"] = [evento("a", 25, self.adesso)]
        server.giro_calendario(self.adesso)
        voci = server.attese()
        server.giro_calendario_voce(voci, self.adesso)
        server.giro_calendario_voce(voci, self.adesso + 120)       # 2 min: not yet
        self.assertEqual(len(self.detti()), 1)
        server.giro_calendario_voce(voci, self.adesso + 301)       # 5 min: again
        self.assertEqual(len(self.detti()), 2)

    def test_confermato_silenzio(self):
        server._promemoria_calendario.clear()
        self.risposte["work"] = [evento("a", 10, self.adesso)]
        server.giro_calendario(self.adesso)
        voci = server.attese()
        server._calendario_confermati.add(server._eventi_calendario[0]["chiave"])
        self.addCleanup(server._calendario_confermati.clear)
        server.giro_calendario_voce(voci, self.adesso)
        self.assertEqual(self.detti(), [])

    def test_pausa_rispettata(self):
        server._promemoria_calendario.clear()
        self.risposte["work"] = [evento("a", 10, self.adesso)]
        server.giro_calendario(self.adesso)
        voci = server.attese()
        server.imposta_pausa(True)
        self.addCleanup(server.imposta_pausa, False)
        server.giro_calendario_voce(voci, self.adesso)
        self.assertEqual(self.detti(), [])

    def test_non_aggiornato_non_detto(self):
        self.guasto = True
        server.giro_calendario(self.adesso)
        server.giro_calendario_voce(server.attese(), self.adesso)
        self.assertEqual(self.detti(), [])

    def test_iniziato_sparisce(self):
        self.risposte["work"] = [evento("a", 1, self.adesso)]
        server.giro_calendario(self.adesso)
        self.assertEqual(len(self.calendario_in_attesa()), 1)
        server._eventi_calendario[0]["inizio"] = int(time.time()) - 1
        self.assertEqual(self.calendario_in_attesa(), [])

    def test_calendario_non_aggiornato(self):
        self.guasto = True
        server.giro_calendario(self.adesso)
        voci = self.calendario_in_attesa()
        self.assertEqual(len(voci), 1)
        self.assertTrue(voci[0]["non_aggiornato"])
        self.assertEqual(voci[0]["account"], "work")

    def test_senza_account_niente(self):
        server._calendario = calendario.Lettore(lambda *a: {"items": []}, lambda: {})
        server.giro_calendario(self.adesso)
        self.assertEqual(self.calendario_in_attesa(), [])


if __name__ == "__main__":
    unittest.main()
