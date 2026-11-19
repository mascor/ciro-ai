#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test di posta.py. Usano POSTA_RADICE su una cartella temporanea e finti
esecutori (osascript, afplay, say): nessuna notifica, voce o suono veri."""

import ast
import contextlib
import fcntl
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import posta  # noqa: E402

FINTO_OSASCRIPT = '''#!/usr/bin/python3
import os, sys
percorso = os.environ["POSTA_FINTO_LOG"]
with open(percorso, "a", encoding="utf-8") as scrittura:
    scrittura.write(repr(sys.argv[1:]) + "\\n")
    scrittura.flush()
'''

FINTO_AFPLAY = '''#!/usr/bin/python3
import os, sys
percorso = os.environ["POSTA_AUDIO_LOG"]
with open(percorso, "a", encoding="utf-8") as scrittura:
    scrittura.write(repr(["afplay"] + sys.argv[1:]) + "\\n")
    scrittura.flush()
'''

FINTO_SAY = '''#!/usr/bin/python3
import os, sys
if sys.argv[1:3] == ["-v", "?"]:
    print("Alice              en_US    # Hello, my name is Alice.")
    print("Flo                en_US    # Hello, my name is Flo.")
    sys.exit(0)
percorso = os.environ["POSTA_AUDIO_LOG"]
with open(percorso, "a", encoding="utf-8") as scrittura:
    scrittura.write(repr(["say"] + sys.argv[1:]) + "\\n")
    scrittura.flush()
'''

FINTO_SAY_LENTO = """#!/usr/bin/python3
import os, sys, time
if sys.argv[1:3] == ["-v", "?"]:
    print("Alice              en_US    # Hello, my name is Alice.")
    sys.exit(0)
percorso = os.environ["POSTA_AUDIO_LOG"]

def scrivi(evento):
    with open(percorso, "a", encoding="utf-8") as scrittura:
        scrittura.write("%s %.6f\\n" % (evento, time.time()))
        scrittura.flush()

scrivi("inizio")
time.sleep(0.6)
scrivi("fine")
"""

FINTO_SAY_MOLTO_LENTO = """#!/usr/bin/python3
import os, sys, time
if sys.argv[1:3] == ["-v", "?"]:
    print("Alice              en_US    # Hello, my name is Alice.")
    sys.exit(0)
percorso = os.environ["POSTA_AUDIO_LOG"]

def scrivi(evento):
    with open(percorso, "a", encoding="utf-8") as scrittura:
        scrittura.write("%s %s\\n" % (evento, sys.argv[-1]))
        scrittura.flush()

scrivi("inizio")
time.sleep(4)
scrivi("fine")
"""


VARIABILI = ("POSTA_RADICE", "POSTA_OSASCRIPT", "POSTA_FINTO_LOG", "POSTA_INTERVALLO",
             "POSTA_AFPLAY", "POSTA_SAY", "POSTA_AUDIO_LOG", "POSTA_SUONO", "POSTA_VOCE",
             "POSTA_SOGLIA_FERMI", "POSTA_LOCK_VOCE", "POSTA_LOCK_TIMEOUT",
             "POSTA_ERRORI_LOG", "POSTA_PID_PARLA", "POSTA_REGISTRO")


class BasePosta(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="posta-test-"))
        self.radice = self.tmp / "posta"
        self.radice.mkdir()
        self.env_prima = {chiave: os.environ.get(chiave) for chiave in VARIABILI}
        os.environ["POSTA_RADICE"] = str(self.radice)
        os.environ.pop("POSTA_VOCE", None)
        os.environ.pop("POSTA_REGISTRO", None)
        # Il lock delle voci resta nella cartella temporanea del test.
        os.environ["POSTA_LOCK_VOCE"] = str(self.tmp / "voce.lock")

        self.log_osascript = self.tmp / "osascript.log"
        os.environ["POSTA_FINTO_LOG"] = str(self.log_osascript)
        finto = self.tmp / "finto-osascript"
        finto.write_text(FINTO_OSASCRIPT, encoding="utf-8")
        finto.chmod(0o755)
        os.environ["POSTA_OSASCRIPT"] = str(finto)

        self.log_audio = self.tmp / "audio.log"
        os.environ["POSTA_AUDIO_LOG"] = str(self.log_audio)
        for variabile, nome, testo in (("POSTA_AFPLAY", "finto-afplay", FINTO_AFPLAY),
                                       ("POSTA_SAY", "finto-say", FINTO_SAY)):
            percorso = self.tmp / nome
            percorso.write_text(testo, encoding="utf-8")
            percorso.chmod(0o755)
            os.environ[variabile] = str(percorso)
        os.environ["POSTA_SUONO"] = str(self.tmp / "sosumi.aiff")
        os.environ["POSTA_INTERVALLO"] = "0.2"

    def tearDown(self):
        for chiave, valore in self.env_prima.items():
            if valore is None:
                os.environ.pop(chiave, None)
            else:
                os.environ[chiave] = valore
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ------------------------------------------------------------- attrezzi

    def esegui(self, *argomenti):
        uscita, errori = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(uscita), contextlib.redirect_stderr(errori):
            codice = posta.main([str(a) for a in argomenti])
        return codice, uscita.getvalue(), errori.getvalue()

    def invia(self, oggetto="Prova", testo="corpo del messaggio", da="opencode",
              a="sessione", tipo="richiesta", rif="", urgente=False, azione=None):
        argomenti = ["invia", "--da", da, "--a", a, "--tipo", tipo,
                     "--oggetto", oggetto, "--testo", testo]
        if rif:
            argomenti += ["--rif", rif]
        if azione:
            argomenti += ["--azione", azione]
        if urgente:
            argomenti += ["--urgente"]
        codice, uscita, errori = self.esegui(*argomenti)
        self.assertEqual(codice, 0, errori)
        return Path(uscita.strip())

    def _righe_log(self, percorso):
        if not percorso.exists():
            return []
        voci = []
        for riga in percorso.read_text(encoding="utf-8").splitlines():
            riga = riga.strip()
            if not riga:
                continue
            try:
                voci.append(ast.literal_eval(riga))
            except (ValueError, SyntaxError):
                continue  # riga scritta a meta' da un processo parallelo
        return voci

    def avvisi(self):
        return self._righe_log(self.log_osascript)

    def audio(self):
        return self._righe_log(self.log_audio)

    def attendi_avvisi(self, minimo, secondi=6.0):
        self._attendi(self.avvisi, minimo, secondi, "avvisi")

    def attendi_audio(self, minimo, secondi=12.0):
        self._attendi(self.audio, minimo, secondi, "voci audio")

    def _attendi(self, lettore, minimo, secondi, nome):
        fine = time.monotonic() + secondi
        while time.monotonic() < fine:
            if len(lettore()) >= minimo:
                return
            time.sleep(0.05)
        self.fail("attesi almeno %d %s, trovati %d" % (minimo, nome, len(lettore())))

    def registro(self):
        """Righe del registro degli eventi, divise in colonne."""
        percorso = self.radice / "registro.log"
        if not percorso.exists():
            return []
        righe = []
        for riga in percorso.read_text(encoding="utf-8").splitlines():
            if riga.strip():
                righe.append(riga.split("\t"))
        return righe

    def eventi(self, nome=None):
        return [riga for riga in self.registro()
                if nome is None or riga[1] == nome]

    def messaggi_in(self, casella, cartella="nuovi"):
        percorso = self.radice / casella / cartella
        if not percorso.is_dir():
            return []
        return sorted(p.name for p in percorso.iterdir() if p.suffix == ".md")


class TestInvioELettura(BasePosta):
    def test_invio_e_lettura(self):
        percorso = self.invia(oggetto="Ciao sessione", testo="Fai la cosa")
        self.assertTrue(percorso.is_file())
        self.assertEqual(percorso.parent.name, "nuovi")
        self.assertEqual(percorso.parent.parent.name, "sessione")

        contenuto = percorso.read_text(encoding="utf-8")
        self.assertIn("ID: %s" % percorso.stem, contenuto)
        self.assertIn("DA: opencode", contenuto)
        self.assertIn("A: sessione", contenuto)
        self.assertIn("TIPO: richiesta", contenuto)
        self.assertIn("RIF: ", contenuto)
        self.assertIn("URGENTE: no", contenuto)
        self.assertIn("AZIONE: nessuna", contenuto)
        self.assertIn("OGGETTO: Ciao sessione", contenuto)
        self.assertIn("Fai la cosa", contenuto)

        codice, uscita, errori = self.esegui("leggi", "--casella", "sessione",
                                            "--id", percorso.stem)
        self.assertEqual(codice, 0, errori)
        self.assertIn("Fai la cosa", uscita)
        self.assertIn(percorso.stem, uscita)

    def test_lettura_senza_messaggi(self):
        codice, uscita, _ = self.esegui("leggi", "--casella", "vuota", "--tutti")
        self.assertEqual(codice, 0)
        self.assertIn("nessun messaggio", uscita)

    def test_id_inesistente_errore(self):
        codice, _, errori = self.esegui("leggi", "--casella", "sessione",
                                        "--id", "20200101-000000-opencode-mai")
        self.assertEqual(codice, 2)
        self.assertIn("non trovato", errori)

    def test_id_non_valido(self):
        with self.assertRaises(posta.ErrorePosta):
            posta._trova_messaggio("sessione", "../../etc/passwd")

    def test_tipo_non_valido(self):
        # argparse rifiuta il tipo sconosciuto uscendo con 2
        with self.assertRaises(SystemExit) as contesto:
            self.esegui("invia", "--da", "opencode", "--a", "x",
                        "--tipo", "inventato", "--oggetto", "x", "--testo", "y")
        self.assertEqual(contesto.exception.code, 2)
        with self.assertRaises(posta.ErrorePosta):
            posta.invia("opencode", "x", "inventato", "oggetto", "testo")


class TestFormato(BasePosta):
    def test_scrittura_atomica(self):
        percorso = self.invia()
        nomi = [p.name for p in (self.radice / "sessione" / "nuovi").iterdir()]
        self.assertEqual(nomi, [percorso.name])
        self.assertFalse([n for n in nomi if n.startswith(".tmp")])
        self.assertEqual(percorso.stat().st_mode & 0o777, 0o600)
        # nessun temporaneo lasciato dietro anche quando si sovrascrive
        destinazione = self.tmp / "prova.txt"
        posta.scrivi_atomico(destinazione, "prima\n")
        posta.scrivi_atomico(destinazione, "seconda\n")
        self.assertEqual(destinazione.read_text(encoding="utf-8"), "seconda\n")
        self.assertEqual(sorted(p.name for p in self.tmp.iterdir() if p.name.startswith(".tmp")), [])

    def test_formato_e_slug(self):
        percorso = self.invia(oggetto="Risposta S/N: perché NO? (subito)")
        nome = percorso.name
        trovato = re.match(r"^(\d{8}-\d{6})-(opencode)-([a-z0-9-]+)\.md$", nome)
        self.assertIsNotNone(trovato, nome)
        parte_slug = trovato.group(3)
        self.assertLessEqual(len(parte_slug), 40)
        self.assertRegex(parte_slug, r"^[a-z0-9-]+$")
        self.assertFalse(parte_slug.startswith("-") or parte_slug.endswith("-"))
        self.assertIn("perche", parte_slug)

        righe = percorso.read_text(encoding="utf-8").splitlines()
        chiavi = [riga.split(":", 1)[0] for riga in righe[:9]]
        self.assertEqual(chiavi, ["ID", "DA", "A", "DATA", "TIPO", "RIF",
                                  "URGENTE", "AZIONE", "OGGETTO"])
        self.assertEqual(righe[9], "---")

        data = [r for r in righe if r.startswith("DATA: ")][0][6:]
        self.assertIsNotNone(datetime.fromisoformat(data))

    def test_slug_massimo_quaranta(self):
        percorso = self.invia(oggetto="x" * 200)
        trovato = re.match(r"^\d{8}-\d{6}-opencode-([a-z0-9-]+)\.md$", percorso.name)
        self.assertIsNotNone(trovato, percorso.name)
        self.assertEqual(len(trovato.group(1)), 40)

    def test_slug_oggetto_vuoto(self):
        self.assertEqual(posta.slug(""), "messaggio")
        self.assertEqual(posta.slug("***"), "messaggio")

    def test_permessi_cartelle(self):
        self.invia()
        for percorso in (self.radice, self.radice / "sessione",
                         self.radice / "sessione" / "nuovi",
                         self.radice / "sessione" / "letti"):
            self.assertEqual(percorso.stat().st_mode & 0o777, 0o700)

    def test_nomi_casella_non_validi(self):
        for nome in ("../fuori", "a/b", "..", "", "con spazio", ".nascosto",
                     "a\\b", "a" * 200):
            with self.assertRaises(posta.ErrorePosta, msg=nome):
                posta.valida_casella(nome)

    def test_scrittura_fuori_radice_rifiutata(self):
        codice, _, errori = self.esegui("invia", "--da", "opencode", "--a", "../fuori",
                                        "--tipo", "richiesta", "--oggetto", "x",
                                        "--testo", "y")
        self.assertEqual(codice, 2)
        self.assertIn("non valido", errori)
        self.assertFalse((self.tmp / "fuori").exists())


class TestElencoEArchivio(BasePosta):
    def test_elenco_ordinato(self):
        originale = posta._adesso
        istanti = [datetime(2026, 11, 17, 10, 0, 0).astimezone() + timedelta(seconds=i)
                   for i in range(3)]
        self.addCleanup(setattr, posta, "_adesso", originale)
        for indice, quando in enumerate(istanti):
            posta._adesso = lambda q=quando: q
            self.invia(oggetto="Messaggio %d" % (indice + 1), testo="corpo %d" % (indice + 1))

        codice, uscita, errori = self.esegui("elenco", "--casella", "sessione", "--json")
        self.assertEqual(codice, 0, errori)
        voci = json.loads(uscita)
        self.assertEqual([v["oggetto"] for v in voci],
                         ["Messaggio 1", "Messaggio 2", "Messaggio 3"])
        self.assertEqual([v["urgente"] for v in voci], ["no", "no", "no"])
        self.assertEqual([v["azione"] for v in voci], ["nessuna", "nessuna", "nessuna"])

        codice, uscita, _ = self.esegui("elenco", "--casella", "sessione")
        righe = uscita.strip().splitlines()
        self.assertEqual(righe[0].split("\t"), ["ID", "DA", "TIPO", "URGENTE", "OGGETTO"])
        self.assertEqual(len(righe), 4)
        self.assertIn("Messaggio 1", righe[1])
        self.assertIn("Messaggio 3", righe[3])

    def test_elenco_vuoto(self):
        codice, uscita, _ = self.esegui("elenco", "--casella", "nessuno")
        self.assertEqual(codice, 0)
        self.assertIn("nessun messaggio", uscita)

    def test_archiviazione(self):
        percorso = self.invia(oggetto="Da archiviare")
        originale = percorso.read_text(encoding="utf-8")
        codice, uscita, errori = self.esegui("leggi", "--casella", "sessione",
                                            "--tutti", "--archivia")
        self.assertEqual(codice, 0, errori)
        self.assertIn("Da archiviare", uscita)
        self.assertEqual(self.messaggi_in("sessione", "nuovi"), [])
        self.assertEqual(self.messaggi_in("sessione", "letti"), [percorso.name])
        archiviato = self.radice / "sessione" / "letti" / percorso.name
        self.assertFalse(percorso.exists())
        self.assertEqual(archiviato.read_text(encoding="utf-8"), originale)

    def test_leggi_un_solo_messaggio_per_volta(self):
        primo = self.invia(oggetto="Primo")
        self.invia(oggetto="Secondo")
        codice, uscita, _ = self.esegui("leggi", "--casella", "sessione")
        self.assertEqual(codice, 0)
        self.assertIn("Primo", uscita)
        self.assertNotIn("Secondo", uscita)
        self.assertTrue(primo.exists())

    def test_archivia_senza_sovrascrivere(self):
        percorso = self.invia(oggetto="Doppione")
        letti = self.radice / "sessione" / "letti"
        letti.mkdir(parents=True, exist_ok=True)
        (letti / percorso.name).write_text("vecchio\n", encoding="utf-8")
        codice, _, errori = self.esegui("leggi", "--casella", "sessione",
                                        "--tutti", "--archivia")
        self.assertEqual(codice, 0, errori)
        self.assertEqual(len([p for p in letti.iterdir() if p.suffix == ".md"]), 2)
        self.assertEqual((letti / percorso.name).read_text(encoding="utf-8"), "vecchio\n")


class TestAttendi(BasePosta):
    def test_attendi_esce_quando_arriva_un_file(self):
        def scrivi():
            time.sleep(1.0)
            posta.invia("opencode", "sessione", "richiesta", "Arrivato", "testo")

        filo = threading.Thread(target=scrivi)
        filo.start()
        inizio = time.monotonic()
        codice, uscita, errori = self.esegui("attendi", "--casella", "sessione",
                                            "--max-secondi", "20")
        durata = time.monotonic() - inizio
        filo.join()
        self.assertEqual(codice, 0, errori)
        self.assertLess(durata, 10)
        self.assertTrue(uscita.strip())
        self.assertTrue(Path(uscita.strip().splitlines()[0]).is_file())

    def test_attendi_esce_con_3_al_limite(self):
        inizio = time.monotonic()
        codice, uscita, _ = self.esegui("attendi", "--casella", "sessione",
                                       "--max-secondi", "0.5")
        durata = time.monotonic() - inizio
        self.assertEqual(codice, 3)
        self.assertEqual(uscita, "")
        self.assertLess(durata, 3)

    def test_attendi_esce_subito_se_ce_gia_un_messaggio(self):
        percorso = self.invia()
        codice, uscita, _ = self.esegui("attendi", "--casella", "sessione",
                                       "--max-secondi", "5")
        self.assertEqual(codice, 0)
        self.assertEqual(uscita.strip(), str(percorso))


class TestAvvisi(BasePosta):
    def test_avviso_decisione_urgente(self):
        codice, uscita, errori = self.esegui(
            "avvisa", "--progetto", "b2b_frontend", "--azione", "decisione",
            "--testo", "Scegli fra A e B")
        self.assertEqual(codice, 0, errori)
        self.assertEqual(uscita, "")

        voci = self.avvisi()
        self.assertEqual(len(voci), 1)
        self.assertEqual(voci[0][0], "-e")
        script = voci[0][1]
        self.assertIn("display notification", script)
        self.assertIn('with title "B2B FRONTEND \u00b7 decisione"', script)
        self.assertIn('"Scegli fra A e B"', script)
        self.assertNotIn("sound name", script)
        self.assertNotIn("display alert", script)

        self.attendi_audio(6)
        audio = self.audio()
        afplay = [a for a in audio if a[0] == "afplay"]
        voci_voce = [a for a in audio if a[0] == "say"]
        self.assertEqual(len(afplay), 4)
        self.assertEqual(len(voci_voce), 2)
        for voce in afplay:
            self.assertEqual(voce[1:], [str(self.tmp / "sosumi.aiff")])
        for voce in voci_voce:
            self.assertEqual(voce[1:], ["-v", "Alice",
                                        "Progetto b2b frontend. Serve una tua decisione."])

    def test_avviso_conferma_server(self):
        posta.avvisa("alpha-bot", "conferma-server")
        script = self.avvisi()[0][1]
        self.assertIn('with title "ALPHA BOT \u00b7 conferma sul server"', script)
        self.assertIn("Progetto alpha bot. Serve una tua conferma sul server.", script)
        self.attendi_audio(6)
        voci_voce = [a for a in self.audio() if a[0] == "say"]
        self.assertEqual(voci_voce[0][1:], ["-v", "Alice",
                                           "Progetto alpha bot. Serve una tua conferma sul server."])

    def test_avviso_accesso(self):
        posta.avvisa("echo", "accesso")
        script = self.avvisi()[0][1]
        self.assertIn('with title "ECHO \u00b7 accesso"', script)
        self.attendi_audio(6)
        voci_voce = [a for a in self.audio() if a[0] == "say"]
        self.assertEqual(
            voci_voce[0][1:],
            ["-v", "Alice", "Progetto echo. Serve il tuo accesso con le credenziali."])

    def test_avviso_risposta_normale(self):
        codice, _, errori = self.esegui("avvisa", "--progetto", "b2b-frontend",
                                       "--azione", "risposta")
        self.assertEqual(codice, 0, errori)
        script = self.avvisi()[0][1]
        self.assertIn('with title "B2B FRONTEND \u00b7 risposta"', script)
        self.assertIn('"Progetto b2b frontend. \u00c8 arrivata una risposta."', script)
        self.assertNotIn("sound name", script)

        self.attendi_audio(2)
        audio = self.audio()
        self.assertEqual([a[0] for a in audio], ["afplay", "say"])
        self.assertEqual(audio[1][1:], ["-v", "Alice",
                                        "Progetto b2b frontend. \u00c8 arrivata una risposta."])

    def test_nessuna_azione_e_normale(self):
        posta.avvisa("progetto", "nessuna")
        self.assertIn('with title "PROGETTO \u00b7 nessuna"', self.avvisi()[0][1])
        self.attendi_audio(2)
        self.assertEqual([a[0] for a in self.audio()], ["afplay", "say"])

    def test_escape_del_testo(self):
        posta.avvisa('progetto "strano"', "risposta",
                     'Percorso C:\\tmp e "virgolette"')
        script = self.avvisi()[0][1]
        self.assertIn("display notification", script)
        self.assertIn('C:\\\\tmp', script)
        self.assertIn('\\"virgolette\\"', script)
        self.assertIn('PROGETTO \\"STRANO\\" \u00b7 risposta', script)
        self.attendi_audio(2)

    def test_voce_inesistente_usa_la_predefinita(self):
        os.environ["POSTA_VOCE"] = "VoceCheNonEsiste"
        posta.avvisa("progetto", "risposta")
        self.attendi_audio(2)
        voci_voce = [a for a in self.audio() if a[0] == "say"]
        self.assertEqual(voci_voce[0][1:],
                         ["Progetto progetto. \u00c8 arrivata una risposta."])

    def test_voce_configurabile(self):
        os.environ["POSTA_VOCE"] = "Flo"
        posta.avvisa("progetto", "risposta")
        self.attendi_audio(2)
        voci_voce = [a for a in self.audio() if a[0] == "say"]
        self.assertEqual(voci_voce[0][1:],
                         ["-v", "Flo", "Progetto progetto. \u00c8 arrivata una risposta."])

    def test_suono_configurabile(self):
        os.environ["POSTA_SUONO"] = "/tmp/mio-suono.aiff"
        posta.avvisa("progetto", "risposta")
        self.attendi_audio(2)
        afplay = [a for a in self.audio() if a[0] == "afplay"]
        self.assertEqual(afplay[0][1:], ["/tmp/mio-suono.aiff"])

    def test_mai_display_alert(self):
        for azione in posta.AZIONI:
            posta.avvisa("progetto", azione)
        for voce in self.avvisi():
            self.assertNotIn("display alert", voce[1])
            self.assertNotIn("sound name", voce[1])

    def test_azione_non_valida(self):
        with self.assertRaises(posta.ErrorePosta):
            posta.avvisa("progetto", "inventata")
        with self.assertRaises(SystemExit) as contesto:
            self.esegui("avvisa", "--progetto", "x", "--azione", "inventata")
        self.assertEqual(contesto.exception.code, 2)

    def test_progetto_mancante(self):
        with self.assertRaises(posta.ErrorePosta):
            posta.avvisa("   ", "decisione")
        codice, _, errori = self.esegui("avvisa", "--progetto", "  ",
                                        "--azione", "decisione")
        self.assertEqual(codice, 2)
        self.assertIn("progetto", errori)

    def test_invia_urgente_manda_avviso(self):
        percorso = self.invia(oggetto="Subito", urgente=True)
        self.assertTrue(percorso.exists())
        self.attendi_avvisi(1)
        script = self.avvisi()[0][1]
        # TIPO richiesta senza azione: per l'avviso vale almeno "risposta".
        self.assertIn('with title "OPENCODE \u00b7 risposta"', script)
        self.assertIn('"Subito"', script)
        self.assertNotIn("display alert", script)
        self.attendi_audio(6)
        self.assertEqual(sum(1 for a in self.audio() if a[0] == "afplay"), 4)
        parlate = [a for a in self.audio() if a[0] == "say"]
        self.assertEqual(parlate[0][1:], ["-v", "Alice",
                                         "Progetto opencode. \u00c8 arrivata una risposta."])


class TestAzione(BasePosta):
    def _azione_scritta(self, percorso):
        for riga in percorso.read_text(encoding="utf-8").splitlines():
            if riga.startswith("AZIONE:"):
                return riga.split(":", 1)[1].strip()
        return None

    def test_predefinita_secondo_il_tipo(self):
        attesi = (("decisione", "decisione"), ("risposta", "risposta"),
                  ("richiesta", "nessuna"), ("avviso", "nessuna"))
        for tipo, atteso in attesi:
            with self.subTest(tipo=tipo):
                percorso = self.invia(oggetto="Azione %s" % tipo, tipo=tipo)
                self.assertEqual(self._azione_scritta(percorso), atteso)

    def test_azione_esplicita(self):
        percorso = self.invia(oggetto="Accesso", tipo="richiesta", azione="accesso")
        self.assertEqual(self._azione_scritta(percorso), "accesso")

    def test_azione_esplicita_prevale_sul_tipo(self):
        percorso = self.invia(oggetto="Conferma", tipo="richiesta",
                              azione="conferma-server")
        self.assertEqual(self._azione_scritta(percorso), "conferma-server")

    def test_azione_maiuscola_accettata(self):
        self.assertEqual(posta.valida_azione("  DECISIONE  "), "decisione")

    def test_messaggio_vecchio_senza_azione(self):
        vecchio = {"OGGETTO": "Deploy", "_CORPO": "serve una conferma sul server prima"}
        self.assertEqual(posta.azione_messaggio(vecchio), "conferma-server")
        vecchio = {"OGGETTO": "Notizia", "_CORPO": "tutto tranquillo"}
        self.assertEqual(posta.azione_messaggio(vecchio), "nessuna")
        self.assertEqual(posta.azione_messaggio({}), "nessuna")

    def test_messaggio_con_azione_la_rispetta(self):
        self.assertEqual(
            posta.azione_messaggio({"AZIONE": "accesso", "_CORPO": "x"}), "accesso")
        self.assertEqual(
            posta.azione_messaggio({"AZIONE": "nessuna",
                                    "_CORPO": "conferma sul server"}), "nessuna")


class TestAzioneAvviso(unittest.TestCase):
    """L'azione pronunciata non e' mai il solo "Progetto X."."""

    def test_azioni_esplicite_urgenti_vincono_sul_tipo(self):
        for azione in ("decisione", "conferma-server", "accesso"):
            for tipo in ("risposta", "decisione", "richiesta", "avviso", ""):
                with self.subTest(azione=azione, tipo=tipo):
                    self.assertEqual(posta.azione_avviso(azione, tipo), azione)

    def test_risposta_con_azione_nessuna_diventa_risposta(self):
        self.assertEqual(posta.azione_avviso("nessuna", "risposta"), "risposta")
        self.assertEqual(posta.azione_avviso("", "risposta"), "risposta")
        self.assertEqual(posta.azione_avviso("risposta", "risposta"), "risposta")

    def test_decisione_senza_azione_diventa_decisione(self):
        self.assertEqual(posta.azione_avviso("nessuna", "decisione"), "decisione")
        self.assertEqual(posta.azione_avviso("", "decisione"), "decisione")

    def test_ogni_altro_tipo_diventa_risposta(self):
        for tipo in ("richiesta", "avviso", "", "sconosciuto"):
            with self.subTest(tipo=tipo):
                self.assertEqual(posta.azione_avviso("nessuna", tipo), "risposta")

    def test_messaggio_vecchio_con_conferma_resta_urgente(self):
        intestazioni = {"TIPO": "richiesta", "OGGETTO": "Deploy",
                        "_CORPO": "serve una conferma sul server"}
        self.assertEqual(posta.azione_avviso_messaggio(intestazioni),
                         "conferma-server")

    def test_intestazioni_risposta_con_azione_nessuna(self):
        intestazioni = {"TIPO": "risposta", "AZIONE": "nessuna",
                        "OGGETTO": "Fatto", "_CORPO": "tutto ok"}
        self.assertEqual(posta.azione_avviso_messaggio(intestazioni), "risposta")


class TestSorveglia(BasePosta):
    def prepara(self, oggetto, testo="testo", tipo="richiesta", urgente=False,
                vecchio=False, azione=None, da="sessione"):
        percorso = posta.invia(da, "opencode", tipo, oggetto, testo,
                               azione=azione)
        contenuto = percorso.read_text(encoding="utf-8")
        if urgente:
            # segna il messaggio come urgente senza far partire l'avviso:
            # l'avviso lo deve mandare sorveglia, non l'invio
            contenuto = contenuto.replace("URGENTE: no", "URGENTE: si", 1)
        if vecchio:
            contenuto = "\n".join(riga for riga in contenuto.splitlines()
                                  if not riga.startswith("AZIONE:")) + "\n"
        percorso.write_text(contenuto, encoding="utf-8")
        return percorso

    def test_avvisa_una_sola_volta_e_raggruppa(self):
        self.prepara("Notizia normale", "tutto tranquillo", da="echo")
        self.prepara("Bloccato", "serve una mano", urgente=True, da="sessione")
        self.prepara("Scegli fra A e B", "dimmi tu", tipo="decisione",
                     da="alpha-bot")
        self.prepara("Deploy pronto", "serve conferma sul server prima di andare",
                     vecchio=True, da="b2b_frontend")

        codice, uscita, errori = self.esegui("sorveglia")
        self.assertEqual(codice, 0, errori)
        self.assertEqual(uscita, "", "sorveglia non deve stampare nulla")
        self.attendi_avvisi(1)
        time.sleep(0.6)
        voci = self.avvisi()
        self.assertEqual(len(voci), 1, "un solo avviso per giro")
        script = voci[0][1]
        self.assertIn('with title "Posta: 4 messaggi"', script)
        self.assertNotIn("display alert", script)
        self.assertNotIn("sound name", script)
        self.assertIn("4 messaggi nuovi: alpha bot, b2b frontend, echo, sessione.",
                      script)
        self.assertIn("Serve una tua conferma sul server.", script)

        self.attendi_audio(6)   # avviso urgente: 4 afplay e 2 say
        audio = self.audio()
        self.assertEqual(sum(1 for a in audio if a[0] == "afplay"), 4)
        parlate = [a for a in audio if a[0] == "say"]
        self.assertEqual(len(parlate), 2)
        for voce in parlate:
            self.assertEqual(voce[1:], ["-v", "Alice",
                "4 messaggi nuovi: alpha bot, b2b frontend, echo, sessione. "
                "Serve una tua conferma sul server."])

        stato = json.loads((self.radice / ".avvisati.json").read_text(encoding="utf-8"))
        self.assertEqual(len(stato), 4)

        # secondo giro: nessun nuovo avviso, nessun nuovo suono
        codice, uscita, errori = self.esegui("sorveglia")
        self.assertEqual(codice, 0, errori)
        time.sleep(0.6)
        self.assertEqual(len(self.avvisi()), 1)
        self.assertEqual(len(self.audio()), 6)

    def test_due_messaggi_normali_un_solo_avviso(self):
        self.prepara("Prima notizia", "niente di che", da="echo")
        self.prepara("Seconda notizia", "tutto ok", da="sessione")
        codice, _, errori = self.esegui("sorveglia")
        self.assertEqual(codice, 0, errori)
        self.attendi_avvisi(1)
        time.sleep(0.5)
        voci = self.avvisi()
        self.assertEqual(len(voci), 1)
        self.assertIn('with title "Posta: 2 messaggi"', voci[0][1])
        self.assertIn("2 messaggi nuovi: echo, sessione.", voci[0][1])

        self.attendi_audio(2)
        audio = self.audio()
        # nessun urgente: un solo suono e una sola frase
        self.assertEqual([a[0] for a in audio], ["afplay", "say"])
        self.assertEqual(audio[1][1:], ["-v", "Alice",
                                        "2 messaggi nuovi: echo, sessione."])
        stato = json.loads((self.radice / ".avvisati.json").read_text(encoding="utf-8"))
        self.assertEqual(len(stato), 2)

    def test_tre_messaggi_con_urgente_usa_la_frase_piu_importante(self):
        self.prepara("Chiede una decisione", tipo="decisione", da="echo")
        self.prepara("Serve l'accesso", azione="accesso", da="sessione")
        self.prepara("Solo una notizia", da="alpha-bot")
        codice, _, errori = self.esegui("sorveglia")
        self.assertEqual(codice, 0, errori)
        self.attendi_avvisi(1)
        time.sleep(0.5)
        voci = self.avvisi()
        self.assertEqual(len(voci), 1)
        self.assertIn('with title "Posta: 3 messaggi"', voci[0][1])
        self.assertIn("3 messaggi nuovi: alpha bot, echo, sessione.", voci[0][1])
        # Fra accesso e decisione vince l'accesso (ordine delle azioni urgenti).
        self.assertIn("Serve il tuo accesso con le credenziali.", voci[0][1])

        self.attendi_audio(6)   # urgente: 4 afplay e 2 say
        self.assertEqual(sum(1 for a in self.audio() if a[0] == "afplay"), 4)

    def test_messaggio_fermo_raggruppato_con_uno_nuovo(self):
        self.prepara("Da leggere", da="echo")
        fermo = posta.invia("opencode", "b2b_frontend", "richiesta",
                            "Fermo da leggere", "corpo")
        quando = time.time() - 400
        os.utime(str(fermo), (quando, quando))
        codice, _, errori = self.esegui("sorveglia")
        self.assertEqual(codice, 0, errori)
        self.attendi_avvisi(1)
        time.sleep(0.5)
        voci = self.avvisi()
        self.assertEqual(len(voci), 1)
        self.assertIn('with title "Posta: 2 messaggi"', voci[0][1])
        self.assertIn("2 messaggi nuovi: echo, b2b frontend.", voci[0][1])
        self.assertIn("Un messaggio non \u00e8 stato letto", voci[0][1])

        stato = json.loads((self.radice / ".avvisati.json").read_text(encoding="utf-8"))
        self.assertIn("fermo:b2b_frontend:%s" % fermo.stem, stato)
        self.assertEqual(len(stato), 2)

    def test_sorveglia_stato_malformato(self):
        (self.radice / ".avvisati.json").write_text("{non e' json", encoding="utf-8")
        self.prepara("Dopo guasto")
        codice, _, errori = self.esegui("sorveglia")
        self.assertEqual(codice, 0, errori)
        self.attendi_avvisi(1)
        self.assertIn("Dopo guasto", self.avvisi()[0][1])
        stato = json.loads((self.radice / ".avvisati.json").read_text(encoding="utf-8"))
        self.assertEqual(len(stato), 1)

    def test_sorveglia_stato_non_oggetto(self):
        (self.radice / ".avvisati.json").write_text("[]", encoding="utf-8")
        self.prepara("Ancora")
        codice, _, _ = self.esegui("sorveglia")
        self.assertEqual(codice, 0)
        self.attendi_avvisi(1)

    def test_sorveglia_senza_messaggi_non_crea_stato(self):
        codice, uscita, errori = self.esegui("sorveglia")
        self.assertEqual(codice, 0, errori)
        self.assertEqual(uscita, "")
        self.assertEqual(self.avvisi(), [])
        self.assertEqual(self.audio(), [])
        self.assertFalse((self.radice / ".avvisati.json").exists())

    def test_sorveglia_ignora_messaggi_gia_archiviati(self):
        percorso = self.prepara("Archiviato prima")
        posta.archivia(percorso)
        codice, _, errori = self.esegui("sorveglia")
        self.assertEqual(codice, 0, errori)
        time.sleep(0.3)
        self.assertEqual(self.avvisi(), [])
        self.assertEqual(self.audio(), [])

    def test_risposta_senza_azione_viene_pronunciata_come_risposta(self):
        self.prepara("Risposta pronta", "ecco il risultato", tipo="risposta",
                     azione="nessuna")
        codice, uscita, errori = self.esegui("sorveglia")
        self.assertEqual(codice, 0, errori)
        self.attendi_avvisi(1)
        voci = self.avvisi()
        self.assertEqual(len(voci), 1)
        self.assertIn('with title "SESSIONE \u00b7 risposta"', voci[0][1])
        # La notifica resta quella normale: niente urgenza per una risposta.
        self.attendi_audio(2)
        audio = self.audio()
        self.assertEqual([a[0] for a in audio], ["afplay", "say"])
        self.assertEqual(audio[1][1:], ["-v", "Alice",
                                        "Progetto sessione. \u00c8 arrivata una risposta."])
        state = json.loads((self.radice / ".avvisati.json").read_text(encoding="utf-8"))
        self.assertEqual(len(state), 1)


class TestMessaggiFermi(BasePosta):
    """Messaggi rimasti in <casella>/nuovi/ oltre POSTA_SOGLIA_FERMI."""

    def invecchia(self, percorso, secondi):
        quando = time.time() - secondi
        os.utime(str(percorso), (quando, quando))

    def invia_in(self, casella, oggetto="Fermo", tipo="richiesta", azione=None):
        return posta.invia("opencode", casella, tipo, oggetto, "corpo",
                           azione=azione)

    def test_messaggio_fermo_avvisa_una_volta_e_scrive_la_chiave(self):
        percorso = self.invia_in("b2b_frontend", oggetto="Fermo da leggere")
        self.invecchia(percorso, 400)
        codice, uscita, errori = self.esegui("sorveglia")
        self.assertEqual(codice, 0, errori)
        self.assertEqual(uscita, "")
        self.attendi_avvisi(1)
        voci = self.avvisi()
        self.assertEqual(len(voci), 1)
        script = voci[0][1]
        self.assertIn('with title "B2B FRONTEND \u00b7 messaggio non letto"', script)
        self.assertIn("Fermo da leggere", script)
        self.assertNotIn("display alert", script)

        self.attendi_audio(6)   # avviso urgente: 4 afplay e 2 say
        audio = self.audio()
        self.assertEqual(sum(1 for a in audio if a[0] == "afplay"), 4)
        parlate = [a for a in audio if a[0] == "say"]
        self.assertEqual(len(parlate), 2)
        for voce in parlate:
            self.assertEqual(voce[1:], ["-v", "Alice",
                "Progetto b2b frontend. Un messaggio non \u00e8 stato letto: "
                "la sessione forse non ascolta."])

        state = json.loads((self.radice / ".avvisati.json").read_text(encoding="utf-8"))
        self.assertIn("fermo:b2b_frontend:%s" % percorso.stem, state)
        self.assertNotIn(percorso.stem, state)

        # Secondo giro: lo stesso messaggio non avvisa piu'.
        codice, _, errori = self.esegui("sorveglia")
        self.assertEqual(codice, 0, errori)
        time.sleep(0.6)
        self.assertEqual(len(self.avvisi()), 1)
        self.assertEqual(len(self.audio()), 6)

    def test_messaggio_recente_non_avvisa(self):
        self.invia_in("echo", oggetto="Appena arrivato")
        codice, _, errori = self.esegui("sorveglia")
        self.assertEqual(codice, 0, errori)
        time.sleep(0.4)
        self.assertEqual(self.avvisi(), [])
        self.assertEqual(self.audio(), [])
        self.assertFalse((self.radice / ".avvisati.json").exists())

    def test_soglia_configurabile(self):
        os.environ["POSTA_SOGLIA_FERMI"] = "10"
        fermo = self.invia_in("alpha-bot", oggetto="Oltre la soglia")
        self.invecchia(fermo, 30)
        fresco = self.invia_in("echo", oggetto="Sotto la soglia")
        self.invecchia(fresco, 5)
        codice, _, errori = self.esegui("sorveglia")
        self.assertEqual(codice, 0, errori)
        self.attendi_avvisi(1)
        time.sleep(0.4)
        voci = self.avvisi()
        self.assertEqual(len(voci), 1)
        self.assertIn('with title "ALPHA BOT \u00b7 messaggio non letto"', voci[0][1])
        self.assertFalse(any("ECHO" in v[1] for v in voci))

    def test_soglia_non_valida_o_negativa(self):
        os.environ["POSTA_SOGLIA_FERMI"] = "boh"
        self.assertEqual(posta._soglia_fermi(), posta.SOGLIA_FERMI_PREDEFINITA)
        os.environ["POSTA_SOGLIA_FERMI"] = "-5"
        self.assertEqual(posta._soglia_fermi(), 0.0)
        os.environ["POSTA_SOGLIA_FERMI"] = ""
        self.assertEqual(posta._soglia_fermi(), posta.SOGLIA_FERMI_PREDEFINITA)
        self.assertEqual(posta.SOGLIA_FERMI_PREDEFINITA, 300.0)

    def test_opencode_bin_e_cartelle_nascoste_non_sono_fermi(self):
        vecchio_opencode = posta.invia("sessione", "opencode", "richiesta",
                                       "Per opencode", "da leggere")
        self.invecchia(vecchio_opencode, 400)
        for cartella in ("bin", ".nascosta"):
            nuovi = self.radice / cartella / "nuovi"
            nuovi.mkdir(parents=True)
            finto = nuovi / "20260101-000000-x-vecchio.md"
            finto.write_text("ID: 20260101-000000-x-vecchio\nOGGETTO: vecchio\n---\n",
                             encoding="utf-8")
            self.invecchia(finto, 400)

        codice, _, errori = self.esegui("sorveglia")
        self.assertEqual(codice, 0, errori)
        self.attendi_avvisi(1)
        time.sleep(0.4)
        voci = self.avvisi()
        self.assertEqual(len(voci), 1)
        self.assertIn('with title "SESSIONE \u00b7 risposta"', voci[0][1])
        self.assertFalse(any("messaggio non letto" in v[1] for v in voci))

        state = json.loads((self.radice / ".avvisati.json").read_text(encoding="utf-8"))
        self.assertIn(vecchio_opencode.stem, state)
        self.assertFalse([k for k in state if k.startswith("fermo:")])

    def test_caselle_sessioni_elenco(self):
        for nome in ("b2b_frontend", "echo", "alpha-bot"):
            posta.cartella_casella(nome)
        (self.radice / "bin").mkdir(exist_ok=True)
        (self.radice / ".nascosta").mkdir(exist_ok=True)
        (self.radice / "un-file").write_text("x", encoding="utf-8")
        self.assertEqual(posta.caselle_sessioni(),
                         ["alpha-bot", "b2b_frontend", "echo"])


class TestFraseGruppo(unittest.TestCase):
    """Frase vocale degli avvisi raggruppati (nessun processo, nessun suono)."""

    def test_senza_urgenti(self):
        self.assertEqual(
            posta.frase_gruppo(["echo", "b2b_frontend"], ["risposta", "risposta"]),
            "2 messaggi nuovi: echo, b2b frontend.")

    def test_progetti_ripetuti_pronunciati_una_volta(self):
        self.assertEqual(
            posta.frase_gruppo(["sessione", "sessione"], ["risposta", "risposta"]),
            "2 messaggi nuovi: sessione.")

    def test_ordine_delle_azioni_urgenti(self):
        casi = (
            (["decisione", "conferma-server"], "Serve una tua conferma sul server."),
            (["conferma-server", "accesso"], "Serve una tua conferma sul server."),
            (["decisione", "accesso"], "Serve il tuo accesso con le credenziali."),
            (["non-letto", "decisione"], "Serve una tua decisione."),
            (["non-letto"], "Un messaggio non \u00e8 stato letto: "
                            "la sessione forse non ascolta."),
        )
        for azioni, attesa in casi:
            frase = posta.frase_gruppo(["a", "b"], azioni, [True] * len(azioni))
            self.assertTrue(frase.endswith(attesa), (azioni, frase))

    def test_urgente_senza_azione_urgente_usa_la_decisione(self):
        frase = posta.frase_gruppo(["a", "b"], ["risposta", "risposta"],
                                   [True, False])
        self.assertTrue(frase.endswith("Serve una tua decisione."), frase)

    def test_nessun_messaggio(self):
        self.assertEqual(posta.avvisa_messaggi([]), None)


class TestLockVoce(BasePosta):
    """Le voci non si sovrappongono: il lock mette in fila i figli _suona."""

    def setUp(self):
        super().setUp()
        lento = self.tmp / "finto-say-lento"
        lento.write_text(FINTO_SAY_LENTO, encoding="utf-8")
        lento.chmod(0o755)
        os.environ["POSTA_SAY"] = str(lento)
        os.environ["POSTA_LOCK_TIMEOUT"] = "10"

    def _script(self):
        return Path(__file__).resolve().parent / "posta.py"

    def _lancia(self):
        return subprocess.Popen(
            [sys.executable, str(self._script()), "_suona", "--frase", "uno"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, env=dict(os.environ))

    def _eventi(self):
        eventi = []
        if not self.log_audio.exists():
            return eventi
        for riga in self.log_audio.read_text(encoding="utf-8").splitlines():
            parti = riga.split()
            if len(parti) == 2 and parti[0] in ("inizio", "fine"):
                eventi.append((parti[0], float(parti[1])))
        return eventi

    def test_due_avvisi_insieme_non_si_sovrappongono(self):
        primo = self._lancia()
        secondo = self._lancia()
        self.assertEqual(primo.wait(timeout=60), 0)
        self.assertEqual(secondo.wait(timeout=60), 0)
        eventi = self._eventi()
        self.assertEqual([e[0] for e in eventi],
                         ["inizio", "fine", "inizio", "fine"], eventi)
        # il secondo inizia solo dopo che il primo ha finito
        self.assertGreaterEqual(eventi[2][1], eventi[1][1] - 0.02, eventi)
        # e ogni voce e' durata davvero (il finto say dorme 0.6 s)
        self.assertGreaterEqual(eventi[1][1] - eventi[0][1], 0.4, eventi)

    def test_lock_occupato_rinuncia_e_scrive_su_errori_log(self):
        lock = Path(os.environ["POSTA_LOCK_VOCE"])
        fd = os.open(str(lock), os.O_RDWR | os.O_CREAT, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX)
        os.environ["POSTA_LOCK_TIMEOUT"] = "0.3"
        inizio = time.monotonic()
        try:
            risultato = subprocess.run(
                [sys.executable, str(self._script()), "_suona", "--frase", "tardi"],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, env=dict(os.environ), timeout=60)
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
        durata = time.monotonic() - inizio
        self.assertEqual(risultato.returncode, 2)
        self.assertGreaterEqual(durata, 0.25)
        self.assertLess(durata, 10)
        self.assertFalse(self.log_audio.exists(), "senza lock non si parla")
        errori = (self.radice / "errori.log").read_text(encoding="utf-8")
        self.assertIn("voce non pronunciata", errori)
        self.assertIn("lock", errori)

    def test_lock_rilasciato_dopo_un_avviso(self):
        codice, _, errori = self.esegui("avvisa", "--progetto", "echo",
                                       "--azione", "risposta",
                                       "--testo", "prova")
        self.assertEqual(codice, 0, errori)
        self._attendi(self._eventi, 2, 15.0, "eventi della voce")
        lock = Path(os.environ["POSTA_LOCK_VOCE"])
        self.assertTrue(lock.is_file())
        # il lock torna libero appena il figlio ha finito di parlare
        fd = os.open(str(lock), os.O_RDWR | os.O_CREAT, 0o600)
        preso = False
        try:
            fine = time.monotonic() + 10
            while time.monotonic() < fine:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    preso = True
                    break
                except OSError:
                    time.sleep(0.05)
        finally:
            if preso:
                fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
        self.assertTrue(preso, "il lock e' rimasto occupato dopo l'avviso")
        self.assertEqual([e[0] for e in self._eventi()], ["inizio", "fine"])
        self.assertEqual(sum(1 for a in self.audio() if a[0] == "afplay"), 1)


class TestParla(BasePosta):
    """Il comando 'parla': solo voce, in fila con il lock, interrompibile."""

    def _script(self):
        return Path(__file__).resolve().parent / "posta.py"

    def _comando(self):
        return [sys.executable, str(self._script()), "parla"]

    def _eventi(self):
        eventi = []
        if not self.log_audio.exists():
            return eventi
        for riga in self.log_audio.read_text(encoding="utf-8").splitlines():
            parti = riga.split(" ", 1)
            if len(parti) == 2 and parti[0] in ("inizio", "fine"):
                eventi.append((parti[0], parti[1]))
        return eventi

    def _attendi_eventi(self, minimo, secondi=20.0):
        fine = time.monotonic() + secondi
        while time.monotonic() < fine:
            if len(self._eventi()) >= minimo:
                return
            time.sleep(0.05)
        self.fail("attesi %d eventi della voce, trovati %d"
                  % (minimo, len(self._eventi())))

    def _attendi_pid(self, secondi=10.0):
        percorso = self.radice / ".parla.pid"
        fine = time.monotonic() + secondi
        while time.monotonic() < fine:
            if percorso.is_file():
                return percorso
            time.sleep(0.05)
        self.fail("il file .parla.pid non e' comparso")

    def test_parla_pronuncia_solo_la_voce(self):
        codice, _, errori = self.esegui("parla", "--testo", "Ciao dalla fila")
        self.assertEqual(codice, 0, errori)
        self.attendi_audio(1, 15.0)
        voci = self.audio()
        self.assertEqual([voce[0] for voce in voci], ["say"])
        self.assertEqual(voci[0][1:], ["-v", "Alice", "Ciao dalla fila"])
        # niente suono: afplay non viene mai chiamato
        self.assertFalse(any(voce[0] == "afplay" for voce in voci))
        # e il PID sparisce quando la voce ha finito
        fine = time.monotonic() + 10
        while time.monotonic() < fine and (self.radice / ".parla.pid").exists():
            time.sleep(0.05)
        self.assertFalse((self.radice / ".parla.pid").exists())

    def test_parla_legge_il_testo_da_stdin(self):
        risultato = subprocess.run(
            self._comando(), input="testo arrivato da stdin\n",
            capture_output=True, text=True, env=dict(os.environ), timeout=60)
        self.assertEqual(risultato.returncode, 0, risultato.stderr)
        self.attendi_audio(1, 15.0)
        self.assertEqual(self.audio()[0][1:], ["-v", "Alice", "testo arrivato da stdin"])

    def test_parla_senza_testo_e_un_errore(self):
        risultato = subprocess.run(
            self._comando(), input="", capture_output=True, text=True,
            env=dict(os.environ), timeout=60)
        self.assertEqual(risultato.returncode, 2)
        self.assertIn("testo da pronunciare mancante", risultato.stderr)
        self.assertFalse(self.log_audio.exists())

    def test_parla_rispetta_il_lock(self):
        lock = Path(os.environ["POSTA_LOCK_VOCE"])
        fd = os.open(str(lock), os.O_RDWR | os.O_CREAT, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX)
        os.environ["POSTA_LOCK_TIMEOUT"] = "0.3"
        errori_log = self.radice / "errori.log"
        try:
            codice, _, _ = self.esegui("parla", "--testo", "tardi")
            self.assertEqual(codice, 0)
            fine = time.monotonic() + 10
            while time.monotonic() < fine:
                if errori_log.exists() and "voce non pronunciata" in errori_log.read_text(
                        encoding="utf-8"):
                    break
                time.sleep(0.05)
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
        self.assertFalse(self.log_audio.exists(), "senza lock non si parla")
        self.assertIn("voce non pronunciata", errori_log.read_text(encoding="utf-8"))

    def test_interrompe_la_voce_precedente(self):
        lento = self.tmp / "finto-say-molto-lento"
        lento.write_text(FINTO_SAY_MOLTO_LENTO, encoding="utf-8")
        lento.chmod(0o755)
        os.environ["POSTA_SAY"] = str(lento)
        os.environ["POSTA_LOCK_TIMEOUT"] = "15"

        codice, _, errori = self.esegui(
            "parla", "--interrompi-precedente", "--testo", "prima voce")
        self.assertEqual(codice, 0, errori)
        self._attendi_pid()
        self._attendi_eventi(1)

        codice, _, errori = self.esegui(
            "parla", "--interrompi-precedente", "--testo", "seconda voce")
        self.assertEqual(codice, 0, errori)
        # due inizi e un solo finale: la prima voce e' stata interrotta
        self._attendi_eventi(3)
        eventi = self._eventi()
        self.assertEqual([evento[0] for evento in eventi], ["inizio", "inizio", "fine"])
        self.assertEqual(eventi[0][1], "prima voce")
        self.assertEqual(eventi[1][1], "seconda voce")
        self.assertEqual(eventi[2][1], "seconda voce")

    def test_non_uccide_un_processo_che_non_e_say(self):
        altro = subprocess.Popen(
            ["/bin/sleep", "3"], stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        pid_file = self.radice / ".parla.pid"
        try:
            pid_file.write_text("%d\n" % altro.pid, encoding="utf-8")
            codice, _, errori = self.esegui(
                "parla", "--interrompi-precedente", "--testo", "ciao")
            self.assertEqual(codice, 0, errori)
            self.attendi_audio(1, 15.0)
            self.assertIsNone(altro.poll(), "un PID che non e' say non va ucciso")
        finally:
            if altro.poll() is None:
                altro.kill()
            altro.wait(timeout=10)
        self.assertEqual(self.audio()[0][1:], ["-v", "Alice", "ciao"])



class TestParlaSeLibero(BasePosta):
    """'parla --se-libero': nessuna coda, suono e voce nello stesso processo."""

    def _script(self):
        return Path(__file__).resolve().parent / "posta.py"

    def _comando(self, *argomenti):
        return [sys.executable, str(self._script()), "parla"] + list(argomenti)

    def test_se_libero_parla_subito_quando_il_lock_e_libero(self):
        risultato = subprocess.run(
            self._comando("--se-libero", "--testo", "Ciao dalla fila"),
            stdin=subprocess.DEVNULL, capture_output=True, text=True,
            env=dict(os.environ), timeout=60)
        self.assertEqual(risultato.returncode, 0, risultato.stderr)
        # parla in primo piano: quando il comando torna la voce ha gia' parlato
        voci = self.audio()
        self.assertEqual([voce[0] for voce in voci], ["say"])
        self.assertEqual(voci[0][1:], ["-v", "Alice", "Ciao dalla fila"])

    def test_se_libero_con_lock_occupato_esce_con_3_senza_parlare(self):
        lock = Path(os.environ["POSTA_LOCK_VOCE"])
        fd = os.open(str(lock), os.O_RDWR | os.O_CREAT, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX)
        inizio = time.monotonic()
        try:
            risultato = subprocess.run(
                self._comando("--se-libero", "--testo", "tardi"),
                stdin=subprocess.DEVNULL, capture_output=True, text=True,
                env=dict(os.environ), timeout=60)
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
        durata = time.monotonic() - inizio
        self.assertEqual(risultato.returncode, 3)
        self.assertLess(durata, 10, "deve uscire subito, senza aspettare il lock")
        self.assertFalse(self.log_audio.exists(), "senza lock non si parla")
        # nessuna coda e nessun errore: la voce occupata e' normale
        self.assertFalse((self.radice / "errori.log").exists())

    def test_se_libero_suona_prima_della_voce(self):
        suono = self.tmp / "sosumi.aiff"
        suono.write_bytes(b"aiff finto")
        risultato = subprocess.run(
            self._comando("--se-libero", "--testo", "Ciao",
                          "--suono", str(suono)),
            stdin=subprocess.DEVNULL, capture_output=True, text=True,
            env=dict(os.environ), timeout=60)
        self.assertEqual(risultato.returncode, 0, risultato.stderr)
        voci = self.audio()
        self.assertEqual([voce[0] for voce in voci], ["afplay", "say"])
        self.assertEqual(voci[0][1:], [str(suono)])
        self.assertEqual(voci[1][1:], ["-v", "Alice", "Ciao"])

    def test_se_libero_non_parla_se_il_suono_tiene_il_lock(self):
        lock = Path(os.environ["POSTA_LOCK_VOCE"])
        fd = os.open(str(lock), os.O_RDWR | os.O_CREAT, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            risultato = subprocess.run(
                self._comando("--se-libero", "--testo", "Ciao",
                              "--suono", str(self.tmp / "sosumi.aiff")),
                stdin=subprocess.DEVNULL, capture_output=True, text=True,
                env=dict(os.environ), timeout=60)
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
        self.assertEqual(risultato.returncode, 3)
        self.assertFalse(self.log_audio.exists())

    def test_parla_normale_passa_il_suono_al_figlio(self):
        suono = self.tmp / "sosumi.aiff"
        suono.write_bytes(b"aiff finto")
        codice, _, errori = self.esegui("parla", "--testo", "Ciao",
                                        "--suono", str(suono))
        self.assertEqual(codice, 0, errori)
        self.attendi_audio(2, 15.0)
        voci = self.audio()
        self.assertEqual([voce[0] for voce in voci], ["afplay", "say"])

    def test_help_mostra_se_libero_e_suono(self):
        risultato = subprocess.run(
            self._comando("--help"), stdin=subprocess.DEVNULL,
            capture_output=True, text=True, env=dict(os.environ), timeout=60)
        self.assertEqual(risultato.returncode, 0, risultato.stderr)
        self.assertIn("--se-libero", risultato.stdout)
        self.assertIn("--suono", risultato.stdout)


class TestRiassunto(BasePosta):
    def riassunto(self, *extra, casella="opencode"):
        return self.esegui("riassunto", "--casella", casella, *extra)

    def righe_messaggi(self, uscita):
        return [riga for riga in uscita.splitlines() if riga.startswith("- ")]

    def test_zero_messaggi(self):
        codice, uscita, errori = self.riassunto(casella="vuota")
        self.assertEqual(codice, 0, errori)
        self.assertEqual(uscita.strip(), "\U0001f4ec Nessun messaggio nuovo.")
        self.assertEqual(self.eventi(), [])

    def test_chiedono_prima_e_info_dopo(self):
        self.invia(da="beta", a="opencode", tipo="risposta", oggetto="Deploy fatto",
                   testo="Tutto verde.")
        self.invia(da="alfa", a="opencode", tipo="decisione", oggetto="Scelta server",
                   testo="Quale server usiamo?")
        codice, uscita, errori = self.riassunto()
        self.assertEqual(codice, 0, errori)
        righe = uscita.splitlines()
        self.assertEqual(righe, [
            "\U0001f4ec 2 messaggi",
            "Ti chiedono:",
            "- alfa \u00b7 decisione \u00b7 Scelta server",
            "  Quale server usiamo?",
            "Per tua informazione:",
            "- beta \u00b7 risposta \u00b7 Deploy fatto",
        ])

    def test_solo_info_senza_titolo_chiedono(self):
        self.invia(da="beta", a="opencode", tipo="risposta", oggetto="Deploy fatto",
                   testo="Tutto verde.")
        _, uscita, _ = self.riassunto()
        self.assertNotIn("Ti chiedono:", uscita)
        self.assertIn("Per tua informazione:", uscita)

    def test_cosa_serve(self):
        self.invia(da="alfa", a="opencode", tipo="richiesta", azione="accesso",
                   oggetto="Credenziali", testo="Mi passi la password?")
        self.invia(da="beta", a="opencode", tipo="richiesta", azione="conferma-server",
                   oggetto="Deploy", testo="Confermi il deploy?")
        self.invia(da="gamma", a="opencode", tipo="risposta", azione="risposta",
                   oggetto="Ok", testo="Fatto.")
        self.invia(da="delta", a="opencode", tipo="avviso", oggetto="Nota",
                   testo="Solo informazione.")
        _, uscita, _ = self.riassunto()
        self.assertIn("- alfa \u00b7 accesso \u00b7 Credenziali", uscita)
        self.assertIn("- beta \u00b7 conferma sul server \u00b7 Deploy", uscita)
        self.assertIn("- gamma \u00b7 risposta \u00b7 Ok", uscita)
        self.assertIn("- delta \u00b7 info \u00b7 Nota", uscita)

    def test_domanda_dalla_prima_riga_utile(self):
        self.assertEqual(posta.domanda_dal_corpo(""), "")
        self.assertEqual(posta.domanda_dal_corpo("nessuna domanda qui"), "")
        self.assertEqual(posta.domanda_dal_corpo("riga piana\nQuale scegli?"),
                         "Quale scegli?")
        self.assertEqual(posta.domanda_dal_corpo("A) primo\nB) secondo"),
                         "A) primo")
        self.assertEqual(posta.domanda_dal_corpo("A: primo"), "A: primo")
        self.assertEqual(posta.domanda_dal_corpo("S/N"), "S/N")
        self.assertEqual(posta.domanda_dal_corpo("Scelta: si o no"), "Scelta: si o no")
        self.assertEqual(posta.domanda_dal_corpo("Opzioni\n- a"), "Opzioni")

    def test_domanda_solo_per_chi_chiede(self):
        # una risposta con un punto di domanda nel corpo non porta la domanda
        self.invia(da="beta", a="opencode", tipo="risposta", oggetto="Ok",
                   testo="Va bene? si")
        _, uscita, _ = self.riassunto()
        self.assertNotIn("Va bene? si", uscita)

    def test_domanda_troncata(self):
        self.invia(da="alfa", a="opencode", tipo="decisione", oggetto="Scelta",
                   testo="Domanda " + "x" * 300 + "?")
        _, uscita, _ = self.riassunto()
        seconda = [r for r in uscita.splitlines() if r.startswith("  ")][0]
        self.assertEqual(len(seconda), 2 + posta.RIASSUNTO_DOMANDA_MAX)
        self.assertTrue(seconda.endswith("\u2026"))

    def test_oggetto_troncato(self):
        self.invia(da="alfa", a="opencode", tipo="risposta",
                   oggetto="Oggetto " + "y" * 300, testo="Fatto.")
        _, uscita, _ = self.riassunto()
        riga = self.righe_messaggi(uscita)[0]
        oggetto = riga.split(" \u00b7 ")[2]
        self.assertEqual(len(oggetto), posta.RIASSUNTO_OGGETTO_MAX)
        self.assertTrue(oggetto.endswith("\u2026"))

    def test_doppioni_una_riga_con_il_numero(self):
        for testo in ("primo", "secondo", "terzo"):
            self.invia(da="beta", a="opencode", tipo="risposta",
                       oggetto="Deploy fatto", testo=testo)
        self.invia(da="beta", a="opencode", tipo="risposta", oggetto="Altra cosa",
                   testo="Fatto.")
        _, uscita, _ = self.riassunto()
        righe = self.righe_messaggi(uscita)
        self.assertEqual(len(righe), 2)
        self.assertEqual([r for r in righe if "Deploy fatto" in r],
                         ["- beta \u00b7 risposta \u00b7 Deploy fatto (\u00d73)"])
        self.assertEqual([r for r in righe if "Altra cosa" in r],
                         ["- beta \u00b7 risposta \u00b7 Altra cosa"])
        self.assertIn("\U0001f4ec 4 messaggi", uscita)

    def test_doppioni_solo_stesso_progetto_e_oggetto(self):
        self.invia(da="alfa", a="opencode", tipo="risposta", oggetto="Deploy",
                   testo="uno")
        self.invia(da="beta", a="opencode", tipo="risposta", oggetto="Deploy",
                   testo="due")
        _, uscita, _ = self.riassunto()
        righe = self.righe_messaggi(uscita)
        self.assertEqual(len(righe), 2)
        self.assertNotIn("\u00d7", uscita)

    def test_massimo_limita_le_righe(self):
        for numero in range(4):
            self.invia(da="beta", a="opencode", tipo="risposta",
                       oggetto="Messaggio %d" % numero, testo="Fatto.")
        _, uscita, _ = self.riassunto()
        self.assertEqual(len(self.righe_messaggi(uscita)), 4)

        _, uscita, _ = self.riassunto("--massimo", "2")
        self.assertEqual(len(self.righe_messaggi(uscita)), 2)
        self.assertIn("\u2026 e altri 2 messaggi (posta.py leggi per il testo intero).",
                      uscita)

    def test_massimo_zero(self):
        self.invia(da="beta", a="opencode", tipo="risposta", oggetto="Uno",
                   testo="Fatto.")
        _, uscita, _ = self.riassunto("--massimo", "0")
        self.assertEqual(self.righe_messaggi(uscita), [])
        self.assertIn("e altri 1 messaggi", uscita)

    def test_massimo_negativo_e_errore(self):
        self.invia(da="beta", a="opencode", tipo="risposta", oggetto="Uno",
                   testo="Fatto.")
        codice, _, errori = self.riassunto("--massimo", "-1")
        self.assertEqual(codice, 2)
        self.assertIn("negativo", errori)

    def test_archivia_sposta_e_registra(self):
        primo = self.invia(da="alfa", a="opencode", tipo="decisione",
                           oggetto="Scelta", testo="Quale?")
        secondo = self.invia(da="beta", a="opencode", tipo="risposta",
                             oggetto="Deploy fatto", testo="Fatto.")
        codice, uscita, errori = self.riassunto("--archivia")
        self.assertEqual(codice, 0, errori)
        self.assertIn("\U0001f4ec 2 messaggi", uscita)

        self.assertEqual(self.messaggi_in("opencode", "nuovi"), [])
        letti = self.messaggi_in("opencode", "letti")
        self.assertEqual(letti, sorted([primo.name, secondo.name]))

        leggi = self.eventi("leggi")
        self.assertEqual(sorted(riga[3] for riga in leggi),
                         sorted([primo.stem, secondo.stem]))
        for riga in leggi:
            self.assertEqual(riga[2], "opencode")
            self.assertIn("archiviato=si", riga[4])

        riassunto = self.eventi("riassunto")
        self.assertEqual(len(riassunto), 1)
        self.assertEqual(riassunto[0][2], "opencode")
        self.assertIn("quanti=2", riassunto[0][4])

    def test_senza_archivia_i_messaggi_restano(self):
        self.invia(da="beta", a="opencode", tipo="risposta", oggetto="Uno",
                   testo="Fatto.")
        self.riassunto()
        self.assertEqual(len(self.messaggi_in("opencode", "nuovi")), 1)
        self.assertEqual(self.messaggi_in("opencode", "letti"), [])
        self.assertEqual(self.eventi("leggi"), [])
        self.assertEqual(self.eventi("riassunto"), [])

    def test_usa_la_radice_temporanea(self):
        casella = "prova-radice-temporanea"
        self.invia(da="beta", a=casella, tipo="risposta", oggetto="Uno",
                   testo="Fatto.")
        codice, uscita, errori = self.riassunto("--archivia", casella=casella)
        self.assertEqual(codice, 0, errori)
        self.assertIn("1 messaggi", uscita)
        self.assertTrue((self.radice / casella / "letti").is_dir())
        self.assertEqual(self.messaggi_in(casella, "nuovi"), [])
        # niente e' finito nella posta vera
        self.assertFalse((posta.RADICE_PREDEFINITA / casella).exists())

    def test_help_mostra_riassunto(self):
        uscita = io.StringIO()
        with contextlib.redirect_stdout(uscita):
            with self.assertRaises(SystemExit) as contesto:
                posta.main(["riassunto", "--help"])
        self.assertEqual(contesto.exception.code, 0)
        self.assertIn("--archivia", uscita.getvalue())
        self.assertIn("--massimo", uscita.getvalue())


class TestRegistro(BasePosta):
    """Il registro unico degli eventi: una riga per evento, senza mai fermare la posta."""

    def test_invio_registra_la_riga(self):
        percorso = self.invia(oggetto="Registro", da="opencode", a="sessione",
                              tipo="richiesta", urgente=True, azione="decisione")
        righe = self.eventi("invia")
        self.assertEqual(len(righe), 1)
        riga = righe[0]
        self.assertEqual(len(riga), 5)
        self.assertTrue(riga[0].startswith("20"), riga[0])
        self.assertEqual(riga[2], "opencode")
        self.assertEqual(riga[3], percorso.stem)
        for pezzo in ("da=opencode", "a=sessione", "tipo=richiesta",
                      "azione=decisione", "urgente=si", "rif=-"):
            self.assertIn(pezzo, riga[4])

    def test_rif_vuoto_diventa_trattino(self):
        self.invia(rif="")
        self.assertIn("rif=-", self.eventi("invia")[0][4])

    def test_leggi_registra_archiviazione(self):
        percorso = self.invia()
        self.esegui("leggi", "--casella", "sessione", "--id", percorso.stem)
        righe = self.eventi("leggi")
        self.assertEqual(len(righe), 1)
        self.assertEqual(righe[0][2], "sessione")
        self.assertEqual(righe[0][3], percorso.stem)
        self.assertIn("archiviato=no", righe[0][4])

        self.esegui("leggi", "--casella", "sessione", "--id", percorso.stem,
                    "--archivia")
        righe = self.eventi("leggi")
        self.assertEqual(len(righe), 2)
        self.assertIn("archiviato=si", righe[1][4])

    def test_attendi_registra_inizio_e_sveglia(self):
        def scrivi():
            time.sleep(0.7)
            posta.invia("opencode", "sessione", "richiesta", "Sveglia", "testo")

        filo = threading.Thread(target=scrivi)
        filo.start()
        codice, _, errori = self.esegui("attendi", "--casella", "sessione",
                                       "--max-secondi", "20")
        filo.join()
        self.assertEqual(codice, 0, errori)
        self.assertEqual(len(self.eventi("attendi-inizio")), 1)
        sveglie = self.eventi("attendi-sveglia")
        self.assertEqual(len(sveglie), 1)
        self.assertIn("messaggi=1", sveglie[0][4])
        self.assertEqual(self.eventi("attendi-scaduto"), [])

    def test_attendi_registra_scadenza(self):
        codice, _, _ = self.esegui("attendi", "--casella", "sessione",
                                   "--max-secondi", "0.4")
        self.assertEqual(codice, 3)
        scaduti = self.eventi("attendi-scaduto")
        self.assertEqual(len(scaduti), 1)
        self.assertEqual(scaduti[0][2], "sessione")
        self.assertIn("max_secondi=0.4", scaduti[0][4])

    def test_avvisa_registra_progetto_e_azione(self):
        codice, _, errori = self.esegui("avvisa", "--progetto", "b2b_frontend",
                                       "--azione", "decisione")
        self.assertEqual(codice, 0, errori)
        righe = self.eventi("avvisa")
        self.assertEqual(len(righe), 1)
        self.assertEqual(righe[0][2], "b2b_frontend")
        self.assertIn("progetto=b2b_frontend", righe[0][4])
        self.assertIn("azione=decisione", righe[0][4])
        self.assertIn("urgente=si", righe[0][4])
        self.assertIn("raggruppati=1", righe[0][4])
        self.attendi_avvisi(1)

    def test_parla_registra_lunghezza_e_attesa(self):
        self.assertTrue(posta.parla_solo_in_fila("ciao", attesa=1))
        righe = self.eventi("parla")
        self.assertEqual(len(righe), 1)
        self.assertIn("lunghezza=4", righe[0][4])
        self.assertRegex(righe[0][4], r"attesa=\d+\.\d+")

    def test_errore_registra_il_messaggio(self):
        posta.scrivi_errore("prova di errore")
        righe = self.eventi("errore")
        self.assertEqual(len(righe), 1)
        self.assertIn("messaggio=prova_di_errore", righe[0][4])

    def test_registro_illeggibile_non_ferma_il_comando(self):
        blocco = self.tmp / "blocco"
        blocco.write_text("non sono una cartella", encoding="utf-8")
        os.environ["POSTA_REGISTRO"] = str(blocco / "registro.log")
        percorso = self.invia()
        self.assertTrue(percorso.is_file())
        self.assertFalse((blocco / "registro.log").exists())

    def test_rotazione_oltre_cinque_megabyte(self):
        registro = self.radice / "registro.log"
        registro.write_text("x" * (5 * 1024 * 1024 + 10), encoding="utf-8")
        self.invia()
        vecchio = self.radice / "registro.log.1"
        self.assertTrue(vecchio.is_file())
        self.assertLess(registro.stat().st_size, 5 * 1024 * 1024)
        self.assertEqual(len(self.eventi("invia")), 1)

    def test_righe_separate_da_tab_e_valori_senza_spazi(self):
        posta.registra("avvisa", "b2b frontend", "-",
                       {"progetto": "b2b  frontend", "nota": "due\nrighe"})
        riga = self.eventi("avvisa")[0]
        self.assertEqual(len(riga), 5)
        self.assertEqual(riga[2], "b2b_frontend")
        self.assertIn("progetto=b2b_frontend", riga[4])
        self.assertIn("nota=due_righe", riga[4])


class TestRigaDiComando(BasePosta):
    def test_invio_da_stdin(self):
        script = Path(__file__).resolve().parent / "posta.py"
        ambiente = dict(os.environ)
        risultato = subprocess.run(
            [sys.executable, str(script), "invia", "--da", "opencode",
             "--a", "sessione", "--tipo", "richiesta", "--oggetto", "Da stdin",
             "--azione", "risposta"],
            input="testo arrivato da stdin\n",
            capture_output=True, text=True, env=ambiente, timeout=30,
        )
        self.assertEqual(risultato.returncode, 0, risultato.stderr)
        percorso = Path(risultato.stdout.strip())
        contenuto = percorso.read_text(encoding="utf-8")
        self.assertIn("testo arrivato da stdin", contenuto)
        self.assertIn("AZIONE: risposta", contenuto)

    def test_help(self):
        script = Path(__file__).resolve().parent / "posta.py"
        risultato = subprocess.run([sys.executable, str(script), "--help"],
                                   capture_output=True, text=True, timeout=30)
        self.assertEqual(risultato.returncode, 0)
        for comando in ("invia", "elenco", "leggi", "riassunto", "attendi",
                        "avvisa", "sorveglia"):
            self.assertIn(comando, risultato.stdout)
        self.assertNotIn("_suona", risultato.stdout)


class TestDomande(BasePosta):
    """Structured questions: chiedi, rispondi-domanda, recepita, risolta, annulla."""

    def chiedi(self, da="ironworks", operazione="scelta", *extra):
        argomenti = ["chiedi", "--da", da, "--oggetto", "Schema spazi Chat",
                     "--domanda", "Quale schema uso per gli spazi Chat?",
                     "--opzione", "A=uno spazio per progetto",
                     "--opzione", "B=uno spazio per cliente",
                     "--raccomanda", "A", "--operazione", operazione,
                     "--bloccato", "la creazione degli spazi"] + list(extra)
        codice, uscita, errori = self.esegui(*argomenti)
        self.assertEqual(codice, 0, errori)
        return uscita.strip()

    def portare_in_attesa(self, identificativo):
        import domande
        domande.passa(identificativo, "in-valutazione", "ciro")
        domande.passa(identificativo, "in-attesa", "ciro")

    def test_chiedi_crea_scheda_e_messaggio(self):
        identificativo = self.chiedi("ironworks", "deploy-prova", "--ambiente", "prova",
                                     "--condizioni", "test-ok,build-ok")
        nomi = self.messaggi_in("opencode")
        self.assertEqual(nomi, [identificativo + ".md"])
        testa = posta.leggi_intestazioni(self.radice / "opencode" / "nuovi" / nomi[0])
        self.assertEqual(testa["DOMANDA-ID"], identificativo)
        self.assertEqual(testa["TIPO"], "decisione")
        self.assertEqual(testa["AZIONE"], "decisione")
        self.assertEqual(testa["OPERAZIONE"], "deploy-prova")
        self.assertEqual(testa["AMBIENTE"], "prova")
        self.assertEqual(testa["RACCOMANDA"], "A")
        self.assertEqual(testa["BLOCCATO"], "la creazione degli spazi")
        self.assertEqual(testa["CONDIZIONI"], "test-ok,build-ok")
        self.assertEqual(json.loads(testa["OPZIONI"]),
                         {"A": "uno spazio per progetto", "B": "uno spazio per cliente"})
        self.assertIn("Quale schema uso per gli spazi Chat?", testa["_CORPO"])
        codice, uscita, _ = self.esegui("stato", "--id", identificativo)
        self.assertEqual((codice, uscita.strip()), (0, "ricevuta"))
        scheda = json.loads((self.radice / "domande" / (identificativo + ".json")).read_text())
        self.assertEqual(scheda["progetto"], "ironworks")
        self.assertEqual(scheda["condizioni"], ["test-ok", "build-ok"])
        self.assertEqual(scheda["opzioni"]["B"], "uno spazio per cliente")

    def test_chiedi_credenziali_azione_accesso(self):
        identificativo = self.chiedi("ironworks", "credenziali")
        testa = posta.leggi_intestazioni(self.radice / "opencode" / "nuovi" / (identificativo + ".md"))
        self.assertEqual(testa["AZIONE"], "accesso")

    def test_chiedi_opzione_mal_formata(self):
        codice, _, errori = self.esegui(
            "chiedi", "--da", "ironworks", "--oggetto", "x", "--domanda", "x?",
            "--opzione", "A", "--opzione", "B=due", "--operazione", "scelta",
            "--bloccato", "niente")
        self.assertEqual(codice, posta.CODICE_ERRORE, errori)
        self.assertEqual(self.messaggi_in("opencode"), [])
        self.assertFalse((self.radice / "domande").exists() and any((self.radice / "domande").glob("*.json")))

    def test_chiedi_raccomanda_non_tra_opzioni(self):
        codice, _, _ = self.esegui(
            "chiedi", "--da", "ironworks", "--oggetto", "x", "--domanda", "x?",
            "--opzione", "A=uno", "--opzione", "B=due", "--raccomanda", "C",
            "--operazione", "scelta", "--bloccato", "niente")
        self.assertEqual(codice, posta.CODICE_ERRORE)

    def test_rispondi_due_volte(self):
        identificativo = self.chiedi()
        self.portare_in_attesa(identificativo)
        codice, uscita, errori = self.esegui(
            "rispondi-domanda", "--id", identificativo, "--scelta", "A",
            "--motivo", "utente", "--da", "opencode")
        self.assertEqual(codice, 0, errori)
        messaggi = self.messaggi_in("ironworks")
        self.assertEqual(len(messaggi), 1)
        testa = posta.leggi_intestazioni(self.radice / "ironworks" / "nuovi" / messaggi[0])
        self.assertEqual(testa["TIPO"], "decisione")
        self.assertEqual(testa["RIF"], identificativo)
        self.assertEqual(testa["DOMANDA-ID"], identificativo)
        self.assertIn("A", testa["_CORPO"])
        self.assertIn("uno spazio per progetto", testa["_CORPO"])
        codice, _, _ = self.esegui(
            "rispondi-domanda", "--id", identificativo, "--scelta", "B",
            "--motivo", "utente", "--da", "opencode")
        self.assertEqual(codice, posta.CODICE_STATO)
        self.assertEqual(len(self.messaggi_in("ironworks")), 1)
        codice, uscita, _ = self.esegui("stato", "--id", identificativo)
        self.assertEqual(uscita.strip(), "risposta-consegnata")

    def test_rispondi_da_ricevuta_solo_per_utente(self):
        # Ciro spento: la domanda resta ricevuta e OpenCode puo' consegnare la risposta
        identificativo = self.chiedi()
        codice, _, _ = self.esegui(
            "rispondi-domanda", "--id", identificativo, "--scelta", "A",
            "--motivo", "regola:r1", "--da", "opencode")
        self.assertEqual(codice, posta.CODICE_STATO)
        self.assertEqual(self.messaggi_in("ironworks"), [])
        codice, _, errori = self.esegui(
            "rispondi-domanda", "--id", identificativo, "--scelta", "A",
            "--motivo", "utente", "--da", "opencode")
        self.assertEqual(codice, 0, errori)
        self.assertEqual(len(self.messaggi_in("ironworks")), 1)

    def test_elenco_json_porta_domanda_id(self):
        identificativo = self.chiedi()
        self.invia(oggetto="Vecchio stile", a="opencode", tipo="decisione")
        codice, uscita, _ = self.esegui("elenco", "--casella", "opencode", "--json")
        self.assertEqual(codice, 0)
        self.assertEqual(sorted(m["domanda_id"] for m in json.loads(uscita)), ["", identificativo])

    def test_rispondi_scelta_non_tra_opzioni(self):
        identificativo = self.chiedi()
        self.portare_in_attesa(identificativo)
        codice, _, _ = self.esegui(
            "rispondi-domanda", "--id", identificativo, "--scelta", "D",
            "--motivo", "utente", "--da", "opencode")
        self.assertEqual(codice, posta.CODICE_ERRORE)
        self.assertEqual(self.messaggi_in("ironworks"), [])

    def test_rispondi_funzione_python(self):
        identificativo = self.chiedi()
        self.portare_in_attesa(identificativo)
        percorso = posta.rispondi_domanda(identificativo, "b", None, "regola:r1", "opencode")
        self.assertTrue(Path(percorso).is_file())
        import domande
        scheda = domande.leggi(identificativo)
        self.assertEqual(scheda["risposta"]["scelta"], "B")
        self.assertEqual(scheda["risposta"]["motivo"], "regola:r1")
        self.assertEqual(scheda["risposta"]["testo"], "uno spazio per cliente")

    def test_recepita_due_volte(self):
        identificativo = self.chiedi()
        self.portare_in_attesa(identificativo)
        posta.rispondi_domanda(identificativo, "A", None, "utente", "opencode")
        codice, _, errori = self.esegui("recepita", "--id", identificativo, "--casella", "ironworks")
        self.assertEqual(codice, 0, errori)
        codice, _, _ = self.esegui("recepita", "--id", identificativo, "--casella", "ironworks")
        self.assertEqual(codice, posta.CODICE_STATO)
        codice, _, errori = self.esegui("risolta", "--id", identificativo, "--nota", "fatto")
        self.assertEqual(codice, 0, errori)
        codice, _, _ = self.esegui("risolta", "--id", identificativo)
        self.assertEqual(codice, posta.CODICE_STATO)
        codice, uscita, _ = self.esegui("stato", "--id", identificativo)
        self.assertEqual(uscita.strip(), "risolta")

    def test_recepita_da_altro_progetto_rifiutata(self):
        identificativo = self.chiedi()
        self.portare_in_attesa(identificativo)
        posta.rispondi_domanda(identificativo, "A", None, "utente", "opencode")
        codice, _, _ = self.esegui("recepita", "--id", identificativo, "--casella", "contoso")
        self.assertEqual(codice, posta.CODICE_ERRORE)
        codice, uscita, _ = self.esegui("stato", "--id", identificativo)
        self.assertEqual(uscita.strip(), "risposta-consegnata")

    def test_annulla_da_altro_progetto_rifiutato(self):
        identificativo = self.chiedi()
        codice, _, _ = self.esegui("annulla", "--id", identificativo, "--casella", "contoso")
        self.assertEqual(codice, posta.CODICE_ERRORE)
        codice, uscita, _ = self.esegui("stato", "--id", identificativo)
        self.assertEqual(uscita.strip(), "ricevuta")
        codice, _, errori = self.esegui("annulla", "--id", identificativo, "--casella", "ironworks")
        self.assertEqual(codice, 0, errori)
        codice, _, _ = self.esegui("annulla", "--id", identificativo, "--casella", "ironworks")
        self.assertEqual(codice, posta.CODICE_STATO)

    def test_domande_elenco_e_json(self):
        primo = self.chiedi("ironworks")
        secondo = self.chiedi("contoso")
        self.portare_in_attesa(secondo)
        codice, uscita, _ = self.esegui("domande")
        self.assertEqual(codice, 0)
        self.assertIn(primo, uscita)
        self.assertIn(secondo, uscita)
        codice, uscita, _ = self.esegui("domande", "--stato", "in-attesa", "--json")
        self.assertEqual(codice, 0)
        self.assertEqual([s["id"] for s in json.loads(uscita)], [secondo])

    def test_cartella_domande_non_e_una_casella(self):
        self.chiedi()
        (self.radice / "ironworks").mkdir(exist_ok=True)
        self.assertIn("ironworks", posta.caselle_sessioni())
        self.assertNotIn("domande", posta.caselle_sessioni())

    def test_stato_id_inesistente(self):
        codice, _, _ = self.esegui("stato", "--id", "non-esiste")
        self.assertEqual(codice, posta.CODICE_ERRORE)

    def test_vecchio_invia_invariato(self):
        percorso = self.invia(oggetto="Vecchio stile", testo="testo libero", a="opencode",
                              tipo="decisione")
        righe = percorso.read_text(encoding="utf-8").splitlines()
        self.assertEqual([r.split(":", 1)[0] for r in righe[:9]],
                         ["ID", "DA", "A", "DATA", "TIPO", "RIF", "URGENTE", "AZIONE", "OGGETTO"])
        self.assertEqual(righe[9], "---")
        self.assertEqual(righe[10:], ["testo libero"])
        self.assertFalse((self.radice / "domande").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
