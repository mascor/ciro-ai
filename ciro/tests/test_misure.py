"""Usability measures (strumenti/misure.py): counts and times only, never what was said.

Run from ciro/: python3 -m unittest tests.test_misure
"""

import contextlib
import io
import json
import shutil
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "strumenti"))
import misure  # noqa: E402

ADESSO = datetime(2026, 11, 26, 12, 0, 0)


def evento(ora, tipo, **campi):
    return json.dumps(dict(ora=ora, tipo=tipo, **campi), ensure_ascii=False)


class TestMisure(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ciro-misure-"))
        self.registro = self.tmp / "conversazioni.log"
        self.domande = self.tmp / "domande"
        self.domande.mkdir()
        righe = [
            evento("2026-11-10 10:00:00", "ascolto", testo="vecchia", secondi_trascrizione=9.0),  # too old
            evento("2026-11-25 09:00:00", "ascolto", testo="segreto uno", secondi_trascrizione=0.3, audio_kb=10),
            evento("2026-11-25 09:00:05", "ascolto", testo="segreto due", secondi_trascrizione=0.5, audio_kb=10),
            evento("2026-11-25 09:00:09", "ascolto", testo="segreto tre", secondi_trascrizione=1.1, audio_kb=10),
            evento("2026-11-25 09:01:00", "ascolto-scartato", testo="Grazie a tutti.", motivo="frase inventata da whisper"),
            evento("2026-11-25 09:02:00", "pagina-rumore-ignorato", dettaglio="0.5 s"),
            evento("2026-11-25 09:03:00", "cervello", tu="segreto uno", ciro="Mandato: uno, procedi.",
                   mandato=True, secondi=0.1),
            evento("2026-11-25 09:04:00", "cervello", tu="A", ciro="Quale domanda? la uno, alpha.",
                   mandato=False, secondi=0.1),
            evento("2026-11-25 09:05:00", "cervello", tu="annulla", ciro="Correzione mandata a alpha.",
                   mandato=True, secondi=0.2),
            evento("2026-11-26 08:00:00", "cervello", tu="che succede", ciro="Il cervello non risponde: x",
                   mandato=False, secondi=8.0),
            evento("2026-11-26 08:01:00", "cervello", tu="uno, sì", ciro="La uno, di alpha, è già chiusa. Quale domanda?",
                   mandato=False, secondi=0.1),
            evento("2026-11-26 08:02:00", "parla", testo="segreto detto", secondi_voce=0.4),
            "riga rotta",
        ]
        self.registro.write_text("\n".join(righe) + "\n", encoding="utf-8")
        inizio = datetime(2026, 11, 25, 9, 0, 0).timestamp()
        for nome, stati, motivo in (("a", ["ricevuta", "in-attesa", "risposta-consegnata"], "utente"),
                                    ("b", ["ricevuta", "risposta-consegnata"], "regola:r1"),
                                    ("c", ["ricevuta", "in-attesa"], None)):
            storia = [{"stato": s, "t": inizio + 60 * i} for i, s in enumerate(stati)]
            (self.domande / (nome + ".json")).write_text(json.dumps(
                {"id": nome, "storia": storia, "risposta": {"motivo": motivo} if motivo else None}), encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def esegui(self, *altro):
        uscita = io.StringIO()
        with contextlib.redirect_stdout(uscita):
            rapporto = misure.principale(["--registro", str(self.registro), "--domande", str(self.domande)]
                                         + list(altro), adesso=ADESSO)
        return rapporto, uscita.getvalue()

    def test_conteggi(self):
        rapporto, _ = self.esegui()
        a, r, d = rapporto["ascolto"], rapporto["risposte"], rapporto["domande"]
        self.assertEqual(rapporto["giorni_con_uso"], 2)
        self.assertEqual((a["frasi_trascritte"], a["frasi_scartate"], a["scartate_percento"]), (3, 1, 25.0))
        self.assertEqual(a["secondi_trascrizione"]["mediana"], 0.5)
        self.assertEqual(a["rumori_ignorati"], 1)
        self.assertEqual((r["scambi"], r["mandate"], r["correzioni"], r["errori_modello"]), (5, 2, 1, 1))
        self.assertEqual(r["chiarimenti"]["quale_domanda"], 1)
        self.assertEqual(r["chiarimenti"]["gia_chiusa"], 1)
        self.assertEqual(r["chiarimenti_percento"], 40.0)
        self.assertEqual((d["risposte_tue"], d["risposte_con_le_tue_regole"], d["ancora_aperte"]), (1, 1, 1))
        self.assertEqual(d["secondi_per_rispondere"]["mediana"], 60)

    def test_periodo(self):
        rapporto, _ = self.esegui("--giorni", "0.5")        # only the morning of the 26th
        self.assertEqual(rapporto["risposte"]["scambi"], 2)
        self.assertEqual(rapporto["ascolto"]["frasi_trascritte"], 0)
        rapporto, _ = self.esegui("--dal", "2026-11-01")
        self.assertEqual(rapporto["ascolto"]["frasi_trascritte"], 4)

    def test_nessun_testo_nel_rapporto(self):
        _, uscita = self.esegui()
        _, uscita_json = self.esegui("--json")
        for parola in ("segreto", "Grazie a tutti", "alpha", "procedi"):
            self.assertNotIn(parola, uscita)
            self.assertNotIn(parola, uscita_json)
        self.assertIn("Misure di Ciro", uscita)
        self.assertIn("richieste di chiarimento", uscita)

    def test_registro_mancante(self):
        uscita = io.StringIO()
        with contextlib.redirect_stdout(uscita):
            rapporto = misure.principale(["--registro", str(self.tmp / "nessuno.log"),
                                          "--domande", str(self.tmp / "niente")], adesso=ADESSO)
        self.assertEqual(rapporto["risposte"]["scambi"], 0)
        self.assertIsNone(rapporto["risposte"]["secondi_risposta"])


if __name__ == "__main__":
    unittest.main()
