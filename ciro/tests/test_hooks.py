"""«Ciro connect»: Claude Code hooks reach Ciro (docs/hooks-design.md).

Run from ciro/: python3 -m unittest tests.test_hooks
"""

import json
import shutil
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

from tests.test_coordinamento_ciro import BaseCiro, domande, modulo_cervello, posta, server

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "strumenti"))
import collega  # noqa: E402

PERMESSO = {"hook_event_name": "PermissionRequest", "session_id": "s1", "cwd": "/tmp/progetti/ironworks",
            "tool_name": "Bash", "tool_input": {"command": "npm test"}}
DOMANDA = {"hook_event_name": "PreToolUse", "session_id": "s2", "cwd": "/tmp/progetti/contoso",
           "tool_name": "AskUserQuestion",
           "tool_input": {"questions": [{"question": "Quale database uso?", "header": "Database",
                                         "multiSelect": False,
                                         "options": [{"label": "Postgres", "description": "x"},
                                                     {"label": "SQLite", "description": "y"},
                                                     {"label": "MySQL", "description": "z"}]}]}}


class BaseHook(BaseCiro):
    def setUp(self):
        super().setUp()
        self.muto_prima = server.muto
        server.muto = lambda: False
        server.segna_pagina_sveglia()
        self.c = server._cervello

    def tearDown(self):
        server.muto = self.muto_prima
        server._pagina["sveglia"] = 0.0
        super().tearDown()

    def in_corso(self, dato, attesa=5):
        esito = {}
        filo = threading.Thread(target=lambda: esito.update(uscita=server.gestisci_hook(dato, attesa=attesa)))
        filo.start()
        for _ in range(100):           # the record appears
            if domande.elenca():
                break
            time.sleep(0.05)
        self.giro()                    # Ciro announces it (in-attesa, number said aloud)
        return filo, esito


class TestHook(BaseHook):
    def test_ciro_spento_chiede_nel_terminale(self):
        server._pagina["sveglia"] = 0.0
        self.assertIsNone(server.gestisci_hook(PERMESSO, attesa=1))
        self.assertEqual(domande.elenca(), [])

    def test_permesso_consentito_a_voce(self):
        filo, esito = self.in_corso(PERMESSO)
        detti = [v["testo"] for v in self.coda()]
        self.assertTrue(any("vuole eseguire: npm test" in d.lower() for d in detti), detti)
        self.assertTrue(self.c.chiedi("sì")["mandato"])
        filo.join(5)
        self.assertEqual(esito["uscita"]["hookSpecificOutput"]["decision"], {"behavior": "allow"})
        scheda = domande.elenca()[0]
        self.assertEqual(scheda["stato"], "risolta")
        self.assertEqual(scheda["canale"], "hook")
        self.assertEqual(self.messaggi_a("ironworks"), [])      # no mail to the session
        self.assertEqual(self.messaggi_a("opencode"), [])       # nor to the manager

    def test_permesso_negato(self):
        filo, esito = self.in_corso(PERMESSO)
        self.c.chiedi("no")
        filo.join(5)
        decisione = esito["uscita"]["hookSpecificOutput"]["decision"]
        self.assertEqual(decisione["behavior"], "deny")
        self.assertIn("Ciro", decisione["message"])

    def test_senza_risposta_torna_al_terminale(self):
        filo, esito = self.in_corso(PERMESSO, attesa=0.6)
        filo.join(5)
        self.assertIsNone(esito["uscita"])
        self.assertEqual(domande.elenca()[0]["stato"], "annullata")
        tardi = self.c.risposta_veloce("sì")                     # too late: nothing allowed
        self.assertFalse(tardi and tardi["mandato"])

    def test_mai_risposta_da_una_regola(self):
        modulo_cervello.aggiungi_regola("Consenti sempre npm test")
        filo, esito = self.in_corso(PERMESSO, attesa=0.6)
        filo.join(5)
        self.assertIsNone(esito["uscita"])
        self.assertEqual(self.chiamate_modello, [])             # preferences never asked

    def test_domanda_a_scelta(self):
        filo, esito = self.in_corso(DOMANDA)
        self.assertTrue(self.c.chiedi("due")["mandato"])
        filo.join(5)
        uscita = esito["uscita"]["hookSpecificOutput"]
        self.assertEqual(uscita["permissionDecision"], "allow")
        self.assertEqual(uscita["updatedInput"]["answers"], {"Quale database uso?": "SQLite"})
        self.assertEqual(uscita["updatedInput"]["questions"], DOMANDA["tool_input"]["questions"])

    def test_scelta_multipla_resta_nel_terminale(self):
        dato = json.loads(json.dumps(DOMANDA))
        dato["tool_input"]["questions"][0]["multiSelect"] = True
        self.assertIsNone(server.gestisci_hook(dato, attesa=1))
        self.assertEqual(domande.elenca(), [])

    def test_progetto_in_pausa(self):
        server.imposta_pausa(True)
        try:
            self.assertIsNone(server.gestisci_hook(PERMESSO, attesa=1))
        finally:
            server.imposta_pausa(False)
        self.assertEqual(domande.elenca(), [])

    def test_risposta_del_modello_con_il_nome_della_casella(self):
        # 19/11/2026: «Ho detto sì, consenti» passato dal modello, con a=OPENCODE-SKILLS
        dato = dict(PERMESSO, cwd="/Users/x/Documents/OPENCODE-SKILLS")
        filo, esito = self.in_corso(dato)
        self.assertEqual(domande.elenca()[0]["progetto"], "OPENCODE-SKILLS")   # case kept
        prima = modulo_cervello._esegui
        modulo_cervello._esegui = lambda comando, timeout: (
            "AZIONE: invia | a=OPENCODE-SKILLS | tipo=decisione | oggetto=x | testo=Sì, consenti", "", 0) \
            if comando and comando[0] == "opencode" else prima(comando, timeout)
        modulo_cervello.leggi_sessioni = lambda: [{"progetto": "OPENCODE-SKILLS", "stato": "al lavoro",
                                                    "aspetta_utente": False, "da_secondi": 0}]
        try:
            self.c.ultimo_detto = {"tipo": "avviso", "id": "altro", "ora": 0}   # not right after the question
            esito_voce = self.c.chiedi("Ho detto sì, consenti.")
        finally:
            modulo_cervello._esegui = prima
        self.assertTrue(esito_voce["mandato"], esito_voce)
        filo.join(5)
        self.assertEqual(esito["uscita"]["hookSpecificOutput"]["decision"], {"behavior": "allow"})
        self.assertEqual(self.messaggi_a("OPENCODE-SKILLS"), [])

    def test_nome_della_sessione_da_rename(self):
        transcript = self.tmp / "sessione.jsonl"
        transcript.write_text("\n".join([
            json.dumps({"type": "user", "message": {"content": "ciao"}}),
            json.dumps({"type": "custom-title", "customTitle": "vecchio", "sessionId": "s1"}),
            json.dumps({"type": "custom-title", "customTitle": "test", "sessionId": "s1"})]) + "\n", encoding="utf-8")
        self.assertEqual(server.titolo_sessione(str(transcript)), "test")
        self.assertEqual(server.titolo_sessione(str(self.tmp / "manca.jsonl")), "")
        filo, esito = self.in_corso(dict(PERMESSO, transcript_path=str(transcript)), attesa=0.6)
        filo.join(5)
        self.assertEqual(domande.elenca()[0]["sessione"], "test")
        detti = [v["testo"] for v in self.coda()]
        self.assertTrue(any("da test, ironworks:" in d.lower() for d in detti), detti)

    def test_riassunti(self):
        self.assertEqual(server.riassunto_permesso("Edit", {"file_path": "/a/b/app.py"}),
                         "vuole modificare il file app.py")
        self.assertEqual(server.riassunto_permesso("mcp__github__create_pr", {}), "vuole usare create_pr di github")
        self.assertEqual(server.riassunto_permesso("WebFetch", {"url": "https://example.com/x"}),
                         "vuole consultare il web: example.com")


class TestOpenCode(BaseHook):
    def in_corso_oc(self, dato, attesa=5):
        esito = {}
        filo = threading.Thread(target=lambda: esito.update(uscita=server.gestisci_opencode(dato, attesa=attesa)))
        filo.start()
        for _ in range(100):
            if domande.elenca():
                break
            time.sleep(0.05)
        self.giro()
        return filo, esito

    RICHIESTA = {"requestID": "per_1", "sessionID": "ses_1", "permission": "bash", "patterns": ["git push"],
                 "title": "rilascio", "directory": "/Users/x/progetti/atlas"}

    def test_permesso_opencode_consentito(self):
        filo, esito = self.in_corso_oc(self.RICHIESTA)
        detti = [v["testo"] for v in self.coda()]
        self.assertTrue(any("da rilascio, atlas: vuole eseguire: git push" in d.lower() for d in detti), detti)
        self.assertTrue(self.c.chiedi("sì")["mandato"])
        filo.join(5)
        self.assertEqual(esito["uscita"], {"reply": "once"})

    def test_permesso_opencode_negato(self):
        filo, esito = self.in_corso_oc(self.RICHIESTA)
        self.c.chiedi("no")
        filo.join(5)
        self.assertEqual(esito["uscita"], {"reply": "reject"})

    def test_risposto_nel_terminale_chiude_la_domanda(self):
        filo, esito = self.in_corso_oc(self.RICHIESTA)
        self.assertTrue(server.opencode_risposto({"requestID": "per_1"}))
        filo.join(5)
        self.assertIsNone(esito["uscita"])
        self.assertEqual(domande.elenca()[0]["stato"], "annullata")
        self.assertFalse(server.opencode_risposto({"requestID": "per_1"}))   # already closed

    def test_stessa_richiesta_da_piu_processi_una_domanda(self):
        esiti = []
        fili = [threading.Thread(target=lambda: esiti.append(server.gestisci_opencode(self.RICHIESTA, attesa=5)))
                for _ in range(3)]
        fili[0].start()
        for _ in range(100):
            if domande.elenca():
                break
            time.sleep(0.05)
        for filo in fili[1:]:
            filo.start()
        time.sleep(0.3)
        self.giro()
        self.assertEqual(len(domande.elenca()), 1)
        self.assertTrue(self.c.chiedi("sì")["mandato"])
        for filo in fili:
            filo.join(5)
        self.assertEqual(esiti, [{"reply": "once"}] * 3)

    def test_task_delegati_e_richieste_vuote_non_chiedono(self):
        self.assertIsNone(server.gestisci_opencode(dict(self.RICHIESTA, title="oc-p4-green3-20261119-224727"), attesa=1))
        self.assertIsNone(server.gestisci_opencode(dict(self.RICHIESTA, permission=None, patterns=[]), attesa=1))
        self.assertEqual(domande.elenca(), [])

    def test_campi_di_opencode_1(self):
        dato = {k: v for k, v in self.RICHIESTA.items() if k not in ("permission", "patterns")}
        filo, esito = self.in_corso_oc(dict(dato, type="bash", pattern="git push"))
        detti = [v["testo"] for v in self.coda()]
        self.assertTrue(any("vuole eseguire: git push" in d.lower() for d in detti), detti)
        self.c.chiedi("no")
        filo.join(5)
        self.assertEqual(esito["uscita"], {"reply": "reject"})

    def test_riassunti_opencode(self):
        self.assertEqual(server.riassunto_opencode("edit", ["/a/b/app.py"]), "vuole modificare il file app.py")
        self.assertEqual(server.riassunto_opencode("external_directory", ["/tmp/*"]),
                         "vuole il permesso external_directory: /tmp/*")


class TestCollega(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ciro-collega-"))
        self.file = self.tmp / "settings.json"
        self.altro = {"type": "command", "command": "echo ciao"}
        self.file.write_text(json.dumps({"model": "opus", "hooks": {
            "PreToolUse": [{"matcher": "Bash", "hooks": [self.altro]}]}}), encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def esegui(self, azione):
        import contextlib
        import io
        with contextlib.redirect_stdout(io.StringIO()):
            return collega.principale([azione, "--impostazioni", str(self.file)])

    def test_connect_e_disconnect(self):
        self.esegui("connect")
        dati = json.loads(self.file.read_text(encoding="utf-8"))
        self.assertTrue(collega.collegato(dati))
        self.assertEqual(dati["model"], "opus")
        self.assertIn({"matcher": "Bash", "hooks": [self.altro]}, dati["hooks"]["PreToolUse"])
        self.assertIn({"matcher": "AskUserQuestion", "hooks": [collega._gancio()]}, dati["hooks"]["PreToolUse"])
        self.assertEqual(len(list(self.tmp.glob("settings.json.bak-ciro-*"))), 1)
        self.esegui("connect")                                   # idempotent
        self.assertEqual(json.loads(self.file.read_text(encoding="utf-8")), dati)
        self.esegui("disconnect")
        dati = json.loads(self.file.read_text(encoding="utf-8"))
        self.assertFalse(collega.collegato(dati))
        self.assertEqual(dati, {"model": "opus", "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [self.altro]}]}})

    def test_plugin_opencode(self):
        destinazione = self.tmp / "plugins" / "ciro.js"
        argomenti = ["--impostazioni", str(self.file), "--plugin-opencode", str(destinazione)]
        import contextlib
        import io
        with contextlib.redirect_stdout(io.StringIO()):
            collega.principale(["connect-opencode"] + argomenti)
            self.assertEqual(destinazione.read_bytes(), collega.PLUGIN_SORGENTE.read_bytes())
            collega.principale(["connect-opencode"] + argomenti)            # idempotent, no backup
            self.assertEqual(list(destinazione.parent.glob("*.bak-ciro-*")), [])
            collega.principale(["disconnect-opencode"] + argomenti)
        self.assertFalse(destinazione.exists())

    def test_file_che_non_esiste(self):
        self.file.unlink()
        self.esegui("connect")
        self.assertTrue(collega.collegato(json.loads(self.file.read_text(encoding="utf-8"))))


if __name__ == "__main__":
    unittest.main()
