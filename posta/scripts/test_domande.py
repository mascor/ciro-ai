"""Tests for domande.py (question records). Run from scripts/: python3 -m unittest test_domande"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

QUI = Path(__file__).resolve().parent
sys.path.insert(0, str(QUI))

import domande  # noqa: E402


def scheda_base(identificativo="20261119-100000-ironworks-deploy"):
    return {
        "id": identificativo,
        "progetto": "ironworks",
        "oggetto": "Deploy di prova",
        "domanda": "Pubblico sul server di prova?",
        "opzioni": {"A": "procedi", "B": "aspetta"},
        "raccomanda": "A",
        "operazione": "deploy-prova",
        "ambiente": "prova",
        "condizioni": ["test-ok"],
        "bloccato": "il rilascio",
    }


class BaseDomande(unittest.TestCase):
    def setUp(self):
        self.cartella = tempfile.TemporaryDirectory()
        self.vecchia = os.environ.get("POSTA_RADICE")
        os.environ["POSTA_RADICE"] = self.cartella.name
        self.vecchio_orologio = domande.orologio

    def tearDown(self):
        domande.orologio = self.vecchio_orologio
        if self.vecchia is None:
            os.environ.pop("POSTA_RADICE", None)
        else:
            os.environ["POSTA_RADICE"] = self.vecchia
        self.cartella.cleanup()

    def file_scheda(self, identificativo):
        return Path(self.cartella.name) / "domande" / (identificativo + ".json")


class TestDomande(BaseDomande):
    def test_crea_e_leggi(self):
        creata = domande.crea(scheda_base())
        self.assertEqual(creata["stato"], "ricevuta")
        letta = domande.leggi(creata["id"])
        self.assertEqual(letta["domanda"], "Pubblico sul server di prova?")
        self.assertEqual(letta["opzioni"], {"A": "procedi", "B": "aspetta"})
        self.assertEqual([p["stato"] for p in letta["storia"]], ["ricevuta"])
        self.assertTrue(self.file_scheda(creata["id"]).exists())
        with self.assertRaises(domande.SchedaEsistente):
            domande.crea(scheda_base())
        self.assertEqual([s["id"] for s in domande.elenca()], [creata["id"]])
        self.assertEqual(domande.elenca("in-attesa"), [])

    def test_id_non_valido(self):
        with self.assertRaises(ValueError):
            domande.crea(scheda_base("../fuori"))
        with self.assertRaises(ValueError):
            domande.leggi("../fuori")

    def test_passaggio_ammesso_aggiorna_storia(self):
        domande.crea(scheda_base())
        identificativo = scheda_base()["id"]
        domande.passa(identificativo, "in-valutazione", "ciro")
        dopo = domande.passa(identificativo, "in-attesa", "ciro", nota="detta a voce")
        self.assertEqual(dopo["stato"], "in-attesa")
        self.assertEqual(
            [(p["stato"], p["chi"]) for p in dopo["storia"]],
            [("ricevuta", "ironworks"), ("in-valutazione", "ciro"), ("in-attesa", "ciro")],
        )
        self.assertEqual(dopo["storia"][-1]["nota"], "detta a voce")
        risposta = {"scelta": "A", "testo": "procedi", "motivo": "utente"}
        dopo = domande.passa(identificativo, "risposta-consegnata", "opencode", risposta=risposta)
        self.assertEqual(domande.leggi(identificativo)["risposta"], risposta)

    def test_passaggio_non_ammesso_solleva_e_non_scrive(self):
        domande.crea(scheda_base())
        identificativo = scheda_base()["id"]
        prima = self.file_scheda(identificativo).read_bytes()
        with self.assertRaises(domande.PassaggioNonAmmesso):
            domande.passa(identificativo, "recepita", "ironworks")
        with self.assertRaises(domande.PassaggioNonAmmesso):
            domande.passa(identificativo, "stato-inventato", "ironworks")
        self.assertEqual(self.file_scheda(identificativo).read_bytes(), prima)

    def test_stati_finali_bloccati(self):
        identificativo = scheda_base()["id"]
        domande.crea(scheda_base())
        domande.passa(identificativo, "annullata", "ironworks")
        for nuovo in domande.STATI:
            with self.assertRaises(domande.PassaggioNonAmmesso):
                domande.passa(identificativo, nuovo, "ciro")

    def test_annota_non_cambia_stato(self):
        identificativo = scheda_base()["id"]
        domande.crea(scheda_base())
        dopo = domande.annota(identificativo, "ciro", "correzione: B", correzione="B")
        self.assertEqual(dopo["stato"], "ricevuta")
        self.assertEqual(dopo["correzione"], "B")
        self.assertEqual(dopo["storia"][-1]["nota"], "correzione: B")

    def test_doppio_passaggio_concorrente(self):
        identificativo = scheda_base()["id"]
        domande.crea(scheda_base())
        codice = (
            "import sys; sys.path.insert(0, %r)\n"
            "import domande\n"
            "try:\n"
            "    domande.passa(%r, 'in-valutazione', 'ciro')\n"
            "except domande.PassaggioNonAmmesso:\n"
            "    sys.exit(4)\n"
        ) % (str(QUI), identificativo)
        processi = [
            subprocess.Popen([sys.executable, "-c", codice], env=dict(os.environ))
            for _ in range(2)
        ]
        codici = sorted(p.wait(timeout=30) for p in processi)
        self.assertEqual(codici, [0, 4])
        storia = domande.leggi(identificativo)["storia"]
        self.assertEqual([p["stato"] for p in storia], ["ricevuta", "in-valutazione"])

    def test_solo_da_e_prima(self):
        identificativo = scheda_base()["id"]
        domande.crea(scheda_base())
        chiamate = []
        with self.assertRaises(domande.PassaggioNonAmmesso):
            domande.passa(identificativo, "risposta-consegnata", "opencode",
                          solo_da=("in-attesa",), prima=lambda s: chiamate.append(s))
        self.assertEqual(chiamate, [])

        def guasto(_scheda):
            raise OSError("disco pieno")
        with self.assertRaises(OSError):
            domande.passa(identificativo, "in-valutazione", "ciro", prima=guasto)
        self.assertEqual(domande.leggi(identificativo)["stato"], "ricevuta")
        dopo = domande.passa(identificativo, "in-valutazione", "ciro",
                             prima=lambda s: {"messaggio": "m-" + s["stato"]})
        self.assertEqual(dopo["messaggio"], "m-ricevuta")

    def test_sblocca_ferme(self):
        adesso = [1000.0]
        domande.orologio = lambda: adesso[0]
        uno = scheda_base("uno")
        due = scheda_base("due")
        domande.crea(uno)
        domande.crea(due)
        domande.passa("uno", "in-valutazione", "ciro")
        adesso[0] = 1100.0
        domande.passa("due", "in-valutazione", "ciro")
        adesso[0] = 1121.0
        self.assertEqual(domande.sblocca_ferme(120), ["uno"])
        self.assertEqual(domande.leggi("uno")["stato"], "ricevuta")
        self.assertEqual(domande.leggi("due")["stato"], "in-valutazione")
        self.assertEqual(domande.sblocca_ferme(120), [])

    def test_file_json_valido_e_privato(self):
        creata = domande.crea(scheda_base())
        percorso = self.file_scheda(creata["id"])
        self.assertEqual(json.loads(percorso.read_text(encoding="utf-8"))["id"], creata["id"])
        self.assertEqual(percorso.stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
