"""Calendar reader (#26): only red events in the next 35 minutes, on fake Google answers.

Run from ciro/: python3 -m unittest tests.test_calendario
"""

import unittest

import calendario

ADESSO = 1_800_000_000          # fixed clock: 2027-01-15T08:00:00Z


def iso(secondi):
    return calendario.rfc3339(secondi)


def evento(ident, tra_minuti, colore="11", stato="confirmed", tutto_il_giorno=False, titolo="Call with Rossi"):
    voce = {"id": ident, "status": stato, "summary": titolo, "htmlLink": "https://calendar.example/" + ident}
    if colore is not None:
        voce["colorId"] = colore
    voce["start"] = {"date": "2027-01-15"} if tutto_il_giorno else {"dateTime": iso(ADESSO + tra_minuti * 60)}
    return voce


class TestFiltra(unittest.TestCase):
    def filtra(self, *voci):
        return calendario.filtra({"items": list(voci)}, "work", "primary", ADESSO)

    def test_rosso_tenuto(self):
        eventi = self.filtra(evento("a", 20))
        self.assertEqual(len(eventi), 1)
        self.assertEqual(eventi[0]["titolo"], "Call with Rossi")
        self.assertEqual(eventi[0]["inizio"], ADESSO + 1200)
        self.assertEqual(eventi[0]["chiave"], "work|a|%d" % (ADESSO + 1200))

    def test_altri_colori_ignorati(self):
        self.assertEqual(self.filtra(evento("f", 20, colore="4"), evento("n", 20, colore=None),
                                     evento("b", 20, colore="9")), [])

    def test_annullato_ignorato(self):
        self.assertEqual(self.filtra(evento("c", 20, stato="cancelled")), [])

    def test_tutto_il_giorno_ignorato(self):
        self.assertEqual(self.filtra(evento("g", 0, tutto_il_giorno=True)), [])

    def test_finestra(self):
        eventi = self.filtra(evento("presto", 35), evento("tardi", 36), evento("iniziato", -1))
        self.assertEqual([e["id"] for e in eventi], ["presto"])

    def test_spostato_e_un_altro_avviso(self):
        prima = self.filtra(evento("m", 10))[0]["chiave"]
        dopo = self.filtra(evento("m", 25))[0]["chiave"]
        self.assertNotEqual(prima, dopo)

    def test_risposta_strana(self):
        self.assertEqual(calendario.filtra(None, "w", "p", ADESSO), [])
        self.assertEqual(calendario.filtra({"items": ["x", {"colorId": "11"}]}, "w", "p", ADESSO), [])


class TestLettore(unittest.TestCase):
    def setUp(self):
        self.risposte = {}
        self.chiamate = []
        self.guasti = set()

        def scarica(account, calendario_, time_min, time_max):
            self.chiamate.append((account, calendario_, time_min, time_max))
            if account in self.guasti:
                raise OSError("network down")
            return {"items": self.risposte.get((account, calendario_), [])}

        config = {"work": {"calendari": ["primary", "team"]}, "home": {"calendari": ["primary"]}}
        self.lettore = calendario.Lettore(scarica, lambda: config)

    def test_due_account_ordinati(self):
        self.risposte[("work", "team")] = [evento("t", 25)]
        self.risposte[("home", "primary")] = [evento("h", 5), evento("blu", 6, colore="9")]
        eventi = self.lettore.leggi(ADESSO)
        self.assertEqual([(e["account"], e["id"]) for e in eventi], [("home", "h"), ("work", "t")])
        self.assertIn(("work", "primary", iso(ADESSO), iso(ADESSO + 35 * 60)), self.chiamate)

    def test_stesso_evento_in_due_calendari_una_volta(self):
        self.risposte[("work", "primary")] = [evento("x", 10)]
        self.risposte[("work", "team")] = [evento("x", 10)]
        self.assertEqual(len(self.lettore.leggi(ADESSO)), 1)

    def test_guasto_tiene_l_ultima_lista_dieci_minuti(self):
        self.risposte[("home", "primary")] = [evento("h", 30)]
        self.assertEqual(len(self.lettore.leggi(ADESSO)), 1)
        self.guasti.add("home")
        self.assertEqual(len(self.lettore.leggi(ADESSO + 300)), 1)        # 5 min later: still there
        self.assertEqual(self.lettore.errori, {"home": "OSError"})
        self.assertEqual(self.lettore.non_aggiornati(ADESSO + 300), [])
        self.assertEqual(self.lettore.leggi(ADESSO + 660), [])            # 11 min: stale, no alert
        self.assertEqual(self.lettore.non_aggiornati(ADESSO + 660), ["home"])

    def test_evento_passato_non_resta(self):
        self.risposte[("home", "primary")] = [evento("h", 2)]
        self.lettore.leggi(ADESSO)
        self.guasti.add("home")
        self.assertEqual(self.lettore.leggi(ADESSO + 180), [])            # started: no more alerts

    def test_mai_letto_e_non_aggiornato(self):
        self.guasti.update({"work", "home"})
        self.assertEqual(self.lettore.leggi(ADESSO), [])
        self.assertEqual(self.lettore.non_aggiornati(ADESSO), ["home", "work"])


class TestConfigurazione(unittest.TestCase):
    def test_file_assente_o_rotto(self):
        import tempfile, pathlib
        with tempfile.TemporaryDirectory() as cartella:
            percorso = pathlib.Path(cartella) / "calendario.json"
            self.assertEqual(calendario.leggi_configurazione(percorso), {})
            percorso.write_text("{rotto")
            self.assertEqual(calendario.leggi_configurazione(percorso), {})
            percorso.write_text('{"work": {}, "home": {"calendari": ["primary", "x@group"]}}')
            self.assertEqual(calendario.leggi_configurazione(percorso),
                             {"work": {"calendari": ["primary"]}, "home": {"calendari": ["primary", "x@group"]}})


if __name__ == "__main__":
    unittest.main()
