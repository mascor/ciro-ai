"""Tests for coordinatore.py. Run from scripts/: python3 -m unittest test_coordinatore"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import coordinatore  # noqa: E402


def scheda(operazione="scelta", progetto="ironworks", ambiente=None, condizioni=None,
           raccomanda="A"):
    return {
        "id": "d1", "progetto": progetto, "oggetto": "x",
        "domanda": "Quale schema uso per gli spazi Chat?",
        "opzioni": {"A": "uno spazio per progetto", "B": "uno spazio per cliente"},
        "raccomanda": raccomanda, "operazione": operazione, "ambiente": ambiente,
        "condizioni": condizioni or [],
    }


REGOLA = {"id": "r1", "progetto": "ironworks", "operazione": "deploy-prova",
          "ambiente": "prova", "condizioni": ["test-ok"]}


def modello(risposta):
    chiamate = []

    def chiedi(prompt):
        chiamate.append(prompt)
        return risposta
    chiedi.chiamate = chiamate
    return chiedi


class TestValuta(unittest.TestCase):
    def test_vietata_mai_automatica_anche_se_modello_dice_si(self):
        finto = modello('{"copre": true, "scelta": "A", "regola": "sempre", "motivo": "x"}')
        tutto_permesso = [dict(REGOLA, operazione=op) for op in coordinatore.VIETATE]
        for operazione in sorted(coordinatore.VIETATE):
            esito = coordinatore.valuta(
                scheda(operazione, ambiente="produzione", condizioni=["test-ok"]),
                ["fai sempre A"], tutto_permesso, finto)
            self.assertEqual(esito["esito"], "chiedi", operazione)
            self.assertIsNone(esito["scelta"], operazione)
        self.assertEqual(finto.chiamate, [])

    def test_operazione_sconosciuta_chiede(self):
        esito = coordinatore.valuta(scheda("inventata"), ["fai A"], [REGOLA],
                                    modello('{"copre": true, "scelta": "A"}'))
        self.assertEqual(esito["esito"], "chiedi")

    def test_deploy_prova_regola_esatta(self):
        esito = coordinatore.valuta(
            scheda("deploy-prova", ambiente="prova", condizioni=["test-ok", "build-ok"]),
            [], [REGOLA], None)
        self.assertEqual((esito["esito"], esito["scelta"], esito["regola"]), ("automatica", "A", "r1"))

    def test_deploy_prova_senza_condizione(self):
        esito = coordinatore.valuta(scheda("deploy-prova", ambiente="prova", condizioni=[]),
                                    [], [REGOLA], None)
        self.assertEqual(esito["esito"], "chiedi")

    def test_deploy_prova_altro_progetto(self):
        esito = coordinatore.valuta(
            scheda("deploy-prova", progetto="contoso", ambiente="prova", condizioni=["test-ok"]),
            [], [REGOLA], None)
        self.assertEqual(esito["esito"], "chiedi")

    def test_deploy_prova_ambiente_produzione(self):
        esito = coordinatore.valuta(
            scheda("deploy-prova", ambiente="produzione", condizioni=["test-ok"]), [], [REGOLA], None)
        self.assertEqual(esito["esito"], "chiedi")

    def test_deploy_prova_senza_raccomanda(self):
        esito = coordinatore.valuta(
            scheda("deploy-prova", ambiente="prova", condizioni=["test-ok"], raccomanda=None),
            [], [REGOLA], None)
        self.assertEqual(esito["esito"], "chiedi")

    def test_scelta_coperta(self):
        finto = modello('Ecco: {"copre": true, "scelta": "b", "regola": "spazi Chat per cliente", '
                        '"motivo": "preferenza salvata"}')
        esito = coordinatore.valuta(scheda(), ["per gli spazi Chat usa uno spazio per cliente"],
                                    [], finto)
        self.assertEqual((esito["esito"], esito["scelta"]), ("automatica", "B"))
        self.assertIn("spazi Chat", esito["motivo"])
        self.assertEqual(len(finto.chiamate), 1)
        self.assertIn("per gli spazi Chat usa uno spazio per cliente", finto.chiamate[0])
        self.assertIn("Quale schema uso per gli spazi Chat?", finto.chiamate[0])

    def test_scelta_veloce_senza_modello(self):
        esito = coordinatore.valuta(scheda(), ["qualcosa"], [], None)
        self.assertEqual(esito["esito"], "chiedi")

    def test_scelta_senza_preferenze_non_chiama_modello(self):
        finto = modello('{"copre": true, "scelta": "A"}')
        esito = coordinatore.valuta(scheda(), [], [], finto)
        self.assertEqual(esito["esito"], "chiedi")
        self.assertEqual(finto.chiamate, [])

    def test_scelta_non_coperta(self):
        esito = coordinatore.valuta(scheda(), ["x"], [], modello('{"copre": false, "scelta": null}'))
        self.assertEqual(esito["esito"], "chiedi")

    def test_scelta_non_tra_opzioni(self):
        esito = coordinatore.valuta(scheda(), ["x"], [], modello('{"copre": true, "scelta": "D"}'))
        self.assertEqual(esito["esito"], "chiedi")

    def test_modello_json_rotto(self):
        for risposta in ("non so", '{"copre": true, "scelta": ', "", None):
            esito = coordinatore.valuta(scheda(), ["x"], [], modello(risposta))
            self.assertEqual(esito["esito"], "chiedi", repr(risposta))

    def test_modello_che_solleva(self):
        def guasto(_prompt):
            raise TimeoutError("lento")
        esito = coordinatore.valuta(scheda(), ["x"], [], guasto)
        self.assertEqual(esito["esito"], "chiedi")


class TestAutorizzazioni(unittest.TestCase):
    def setUp(self):
        self.cartella = tempfile.TemporaryDirectory()
        self.file = Path(self.cartella.name) / "autorizzazioni.json"
        self.prima = os.environ.get("CIRO_AUTORIZZAZIONI")
        os.environ["CIRO_AUTORIZZAZIONI"] = str(self.file)

    def tearDown(self):
        if self.prima is None:
            os.environ.pop("CIRO_AUTORIZZAZIONI", None)
        else:
            os.environ["CIRO_AUTORIZZAZIONI"] = self.prima
        self.cartella.cleanup()

    def test_salva_elenca_togli(self):
        self.assertEqual(coordinatore.carica_autorizzazioni(), [])
        regola = coordinatore.salva_autorizzazione("ironworks", "deploy-prova", "prova",
                                                   ["test-ok"], "deploy di prova dopo i test")
        self.assertEqual(regola["operazione"], "deploy-prova")
        self.assertRegex(regola["id"], r"^[A-Za-z0-9_-]+$")
        coordinatore.salva_autorizzazione("contoso", "deploy-prova", "prova", ["test-ok"], "x")
        # same rule again: not duplicated
        coordinatore.salva_autorizzazione("ironworks", "deploy-prova", "prova", ["test-ok"], "x")
        self.assertEqual(len(coordinatore.elenca_autorizzazioni("ironworks")), 1)
        self.assertEqual(len(coordinatore.carica_autorizzazioni()), 2)
        self.assertEqual(self.file.stat().st_mode & 0o777, 0o600)
        self.assertEqual(coordinatore.togli_autorizzazioni("ironworks"), 1)
        self.assertEqual(coordinatore.elenca_autorizzazioni("ironworks"), [])
        self.assertEqual(len(coordinatore.carica_autorizzazioni()), 1)

    def test_salva_autorizzazione_vietata(self):
        coordinatore.salva_autorizzazione("ironworks", "deploy-prova", "prova", ["test-ok"], "x")
        prima = self.file.read_bytes()
        for operazione in sorted(coordinatore.VIETATE) + ["scelta"]:
            with self.assertRaises(ValueError, msg=operazione):
                coordinatore.salva_autorizzazione("ironworks", operazione, "prova", ["test-ok"], "x")
        with self.assertRaises(ValueError):
            coordinatore.salva_autorizzazione("ironworks", "deploy-prova", "produzione", ["test-ok"], "x")
        with self.assertRaises(ValueError):
            coordinatore.salva_autorizzazione("ironworks", "deploy-prova", "prova", [], "x")
        self.assertEqual(self.file.read_bytes(), prima)

    def test_file_modificato_a_mano_non_apre_vietate(self):
        self.file.write_text(json.dumps([dict(REGOLA, operazione="deploy-produzione"), REGOLA]))
        self.assertEqual([r["operazione"] for r in coordinatore.carica_autorizzazioni()],
                         ["deploy-prova"])

    def test_file_rotto(self):
        self.file.write_text("{non json")
        self.assertEqual(coordinatore.carica_autorizzazioni(), [])


if __name__ == "__main__":
    unittest.main()
