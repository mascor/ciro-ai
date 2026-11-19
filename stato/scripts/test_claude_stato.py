#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test di claude_stato.py: usano solo cartelle temporanee, mai i file veri dell'utente."""

import ast
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from unittest import mock

# I test stanno accanto allo script: cosi' funzionano anche lanciati da fuori.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import claude_stato as cs

# Un pid quasi certamente inesistente su macOS (il massimo e' intorno a 99998).
PID_MORTO = 4000001
ADESSO_MS = 1794907200000


def evento_assistente(testo):
    return {
        "type": "assistant",
        "timestamp": "2026-11-17T09:19:02.191Z",
        "message": {"role": "assistant", "content": [{"type": "text", "text": testo}]},
    }


class BaseTemporanea(unittest.TestCase):
    def setUp(self):
        self.cartella = tempfile.mkdtemp(prefix="claude-stato-test-")
        self.sessioni = os.path.join(self.cartella, "sessions")
        self.projects = os.path.join(self.cartella, "projects")
        os.makedirs(self.sessioni)
        os.makedirs(os.path.join(self.projects, "-Users-finto-progetto"))

    def tearDown(self):
        shutil.rmtree(self.cartella, ignore_errors=True)

    def scrivi_sessione(self, pid, **campi):
        dati = {"pid": pid}
        dati.update(campi)
        percorso = os.path.join(self.sessioni, "%s.json" % pid)
        with open(percorso, "w", encoding="utf-8") as f:
            json.dump(dati, f)
        return percorso

    def scrivi_jsonl(self, session_id, righe, sottocartella=None):
        cartella = os.path.join(self.projects, sottocartella or "-Users-finto-progetto")
        os.makedirs(cartella, exist_ok=True)
        percorso = os.path.join(cartella, "%s.jsonl" % session_id)
        with open(percorso, "w", encoding="utf-8") as f:
            for riga in righe:
                if isinstance(riga, str):
                    f.write(riga + "\n")
                else:
                    f.write(json.dumps(riga, ensure_ascii=False) + "\n")
        return percorso


class TestProcesso(unittest.TestCase):
    def test_processo_vivo(self):
        self.assertTrue(cs.processo_vivo(os.getpid()))

    def test_processo_morto(self):
        self.assertFalse(cs.processo_vivo(PID_MORTO))

    def test_pid_assente_o_zero(self):
        self.assertFalse(cs.processo_vivo(None))
        self.assertFalse(cs.processo_vivo(0))


class TestSessioni(BaseTemporanea):
    def test_sessione_viva_e_morta(self):
        self.scrivi_sessione(os.getpid(), sessionId="viva-1", cwd="/Users/x/prog",
                             status="idle", startedAt=ADESSO_MS - 7200000,
                             statusUpdatedAt=ADESSO_MS - 300000, name="viva")
        self.scrivi_sessione(PID_MORTO, sessionId="morta-1", cwd="/Users/x/vecchio",
                             status="idle", name="morta")
        vive = cs.carica_sessioni(self.sessioni)
        self.assertEqual([s["nome"] for s in vive], ["viva"])
        tutte = cs.carica_sessioni(self.sessioni, includi_morte=True)
        self.assertEqual(len(tutte), 2)
        vive_flag = {s["nome"]: s["viva"] for s in tutte}
        self.assertTrue(vive_flag["viva"])
        self.assertFalse(vive_flag["morta"])

    def test_campi_mancanti(self):
        # Solo il pid: nessun nome, cwd, sessionId, stato o tempi.
        self.scrivi_sessione(os.getpid())
        grezze = cs.carica_sessioni(self.sessioni)
        self.assertEqual(len(grezze), 1)
        s = grezze[0]
        self.assertEqual(s["progetto"], "?")
        self.assertEqual(s["stato_grezzo"], "")
        self.assertTrue(s["nome"].startswith("pid "))
        pronta = cs.costruisci_sessione(s, self.projects, ADESSO_MS)
        self.assertEqual(pronta["stato"], "sconosciuto")
        self.assertEqual(pronta["attesa"], "")
        self.assertFalse(pronta["domanda_per_utente"])
        self.assertEqual(pronta["da"], "meno di 1 min")

    def test_file_key_e_json_rotto_ignorati(self):
        with open(os.path.join(self.sessioni, "999.key"), "w", encoding="utf-8") as f:
            f.write("chiave segreta")
        with open(os.path.join(self.sessioni, "rotto.json"), "w", encoding="utf-8") as f:
            f.write("{non json")
        self.scrivi_sessione(os.getpid(), sessionId="buona", status="idle", name="buona")
        grezze = cs.carica_sessioni(self.sessioni)
        self.assertEqual([s["nome"] for s in grezze], ["buona"])

    def test_tutte_mostra_chiusa(self):
        self.scrivi_sessione(PID_MORTO, sessionId="morta", status="idle", name="morta")
        tutte = cs.raccogli(self.sessioni, self.projects, includi_morte=True)
        self.assertEqual(tutte[0]["stato"], "chiusa")


class TestJsonl(BaseTemporanea):
    def test_ultimo_testo_con_righe_malformate(self):
        self.scrivi_jsonl("s1", [
            evento_assistente("primo testo"),
            "questa riga non e' json",
            '{"type":"assistant","message":',       # JSON troncato
            evento_assistente("secondo testo"),
            {"type": "user", "message": {"content": [{"type": "text", "text": "utente"}]}},
            "   ",
        ])
        self.assertEqual(cs.ultimo_testo_assistente(self.projects, "s1"), "secondo testo")

    def test_solo_coda_e_riga_parziale(self):
        # Oltre 2 MB di riempimento: la prima riga letta sara' tagliata e va scartata.
        riempimento = json.dumps({"type": "user", "message": {"content": "x" * (3 * 1024 * 1024)}})
        self.scrivi_jsonl("grosso", [riempimento, evento_assistente("in fondo alla coda")])
        self.assertEqual(cs.ultimo_testo_assistente(self.projects, "grosso"), "in fondo alla coda")

    def test_session_id_sconosciuto(self):
        self.assertEqual(cs.ultimo_testo_assistente(self.projects, "non-esiste"), "")


class TestEstrazione(unittest.TestCase):
    def test_estrai_attesa(self):
        testo = ("Ho fatto il lavoro.\n\n"
                 "\u23f3 **IN ATTESA DI:** Utente, che deve confermare (messaggio: /tmp/x.txt)\n")
        self.assertEqual(cs.estrai_attesa(testo),
                         "Utente, che deve confermare (messaggio: /tmp/x.txt)")

    def test_attesa_assente(self):
        self.assertEqual(cs.estrai_attesa("Solo testo normale."), "")
        self.assertEqual(cs.estrai_attesa(""), "")

    def test_domanda_sn(self):
        testo = "Prima parte.\n**Procedo con il caricamento? (S/N)**"
        self.assertEqual(cs.estrai_domanda(testo), "Procedo con il caricamento? (S/N)")

    def test_domanda_punto_interrogativo(self):
        testo = "Riepilogo.\n- fatto A\n- fatto B\n\nVuoi che continui domani?\n"
        self.assertEqual(cs.estrai_domanda(testo), "Vuoi che continui domani?")

    def test_attesa_non_e_domanda(self):
        testo = "Fatto.\n\n\u23f3 **IN ATTESA DI:** Utente, che deve decidere"
        self.assertEqual(cs.estrai_domanda(testo), "")

    def test_busy_non_ha_domanda(self):
        sessione = {"session_id": "s", "viva": True, "stato_grezzo": "busy",
                    "nome": "x", "progetto": "p", "status_updated_at": ADESSO_MS,
                    "started_at": ADESSO_MS}
        domanda = cs.estrai_domanda("Procedo? (S/N)")
        self.assertTrue(domanda)
        # costruisci_sessione non legge il jsonl se non esiste, ma la regola e' nello stato.
        pronta = cs.costruisci_sessione(sessione, "/cartella/inesistente", ADESSO_MS)
        self.assertFalse(pronta["domanda_per_utente"])

    def test_anteprima(self):
        lungo = "**Titolo** con `codice` " + ("parola " * 40)
        risultato = cs.anteprima("\n\n" + lungo + "\nseconda riga")
        self.assertLessEqual(len(risultato), 120)
        self.assertTrue(risultato.endswith("\u2026"))
        self.assertNotIn("**", risultato)
        self.assertNotIn("`", risultato)
        self.assertEqual(cs.anteprima("\n\nriga vera\n"), "riga vera")

    def test_formatta_durata(self):
        self.assertEqual(cs.formatta_durata(30), "meno di 1 min")
        self.assertEqual(cs.formatta_durata(300), "5 min")
        self.assertEqual(cs.formatta_durata(7800), "2 h 10 min")
        self.assertEqual(cs.formatta_durata(3 * 86400), "3 g")


class TestOrdinamento(unittest.TestCase):
    def test_chi_aspetta_in_cima(self):
        sessioni = [
            {"nome": "zeta", "domanda_per_utente": False, "attesa": ""},
            {"nome": "beta", "domanda_per_utente": False, "attesa": "qualcosa"},
            {"nome": "alfa", "domanda_per_utente": True, "attesa": ""},
        ]
        ordinate = cs.ordina_sessioni(sessioni)
        self.assertEqual([s["nome"] for s in ordinate], ["alfa", "beta", "zeta"])

    def test_tabella_mostra_domanda_rientrata(self):
        sessioni = [{
            "nome": "sess", "progetto": "prog", "stato": "ferma", "stato_grezzo": "idle",
            "da": "5 min", "domanda_per_utente": True, "domanda": "Procedo? (S/N)",
            "attesa": "",
        }]
        tabella = cs.render_tabella(sessioni)
        self.assertIn("SESSIONE", tabella)
        self.assertIn("Procedo? (S/N)", tabella)
        self.assertIn("    domanda:", tabella)


class TestNotifiche(unittest.TestCase):
    def test_percorso_posta(self):
        percorso = cs.percorso_posta()
        self.assertIsNotNone(percorso)
        self.assertTrue(os.path.isfile(percorso))
        self.assertIn(percorso, (cs.POSTA_INSTALLATA, cs.POSTA_ACCANTO))

    def test_carica_posta_espone_avvisa(self):
        modulo = cs.carica_posta()
        self.assertTrue(callable(getattr(modulo, "avvisa", None)))

    def test_avvisa_sessione_progetto_e_azione(self):
        chiamate = []

        class ModuloFinto(object):
            def avvisa(self, progetto, azione=None, testo=""):
                chiamate.append((progetto, azione, testo))

        cs.avvisa_sessione("b2b_frontend", "Testo per la notifica",
                           modulo=ModuloFinto())
        self.assertEqual(chiamate,
                         [("b2b_frontend", "decisione", "Testo per la notifica")])

    def test_avvisatore_iniettabile(self):
        chiamate = []
        cs.avvisa_sessione("echo", "Ciao",
                           avvisatore=lambda p, t: chiamate.append((p, t)))
        self.assertEqual(chiamate, [("echo", "Ciao")])

    def test_avvisa_sessioni_raggruppa_con_una_sola_voce(self):
        chiamate = []

        class ModuloFinto(object):
            def avvisa(self, progetto, azione=None, testo=""):
                chiamate.append(("avvisa", progetto, azione, testo))

            def avvisa_generico(self, titolo, testo, frase, urgente=None):
                chiamate.append(("generico", titolo, testo, frase, urgente))

        cs.avvisa_sessioni([{"progetto": "alfa"}, {"progetto": "beta"}],
                           modulo=ModuloFinto())
        frase = "2 sessioni ti aspettano: alfa, beta."
        self.assertEqual(chiamate,
                         [("generico", "Sessioni: 2 ti aspettano", frase, frase, True)])

    def test_avvisa_sessioni_una_sola_resta_come_prima(self):
        chiamate = []

        class ModuloFinto(object):
            def avvisa(self, progetto, azione=None, testo=""):
                chiamate.append((progetto, azione, testo))

            def avvisa_generico(self, *args, **kwargs):   # non deve essere usata
                raise AssertionError("con una sessione non si raggruppa")

        cs.avvisa_sessioni([{"progetto": "alfa", "domanda": "Procedo? (S/N)"}],
                           modulo=ModuloFinto())
        self.assertEqual(len(chiamate), 1)
        self.assertEqual(chiamate[0][0], "alfa")
        self.assertEqual(chiamate[0][1], "decisione")

    def test_avvisa_sessioni_nessuna_non_avvisa(self):
        chiamate = []
        cs.avvisa_sessioni([], avvisatore=lambda p, t: chiamate.append((p, t)))
        self.assertEqual(chiamate, [])

    def test_avvisa_sessioni_con_posta_vecchio(self):
        chiamate = []

        class ModuloVecchio(object):
            def _notifica(self, titolo, testo):
                chiamate.append(("notifica", titolo, testo))

            def _suona_staccato(self, frase, urgente):
                chiamate.append(("suona", frase, urgente))

            def avvisa(self, progetto, azione=None, testo=""):
                chiamate.append(("avvisa", progetto, azione, testo))

        cs.avvisa_sessioni([{"progetto": "alfa"}, {"progetto": "beta"}],
                           modulo=ModuloVecchio())
        frase = "2 sessioni ti aspettano: alfa, beta."
        self.assertEqual(chiamate,
                         [("notifica", "Sessioni: 2 ti aspettano", frase),
                          ("suona", frase, True)])

    def test_posta_mancante_errore_chiaro(self):
        with mock.patch.object(cs, "POSTA_INSTALLATA", "/non/esiste/posta.py"), \
             mock.patch.object(cs, "POSTA_ACCANTO", "/non/esiste/altro.py"), \
             mock.patch.object(cs, "_posta_caricato", None):
            with self.assertRaises(RuntimeError):
                cs.carica_posta()


class TestNotifyEndToEnd(BaseTemporanea):
    def test_solo_alla_transizione(self):
        self.scrivi_sessione(os.getpid(), sessionId="sess-1", cwd="/Users/x/prog",
                             status="idle", name="prog-1",
                             startedAt=ADESSO_MS - 600000, statusUpdatedAt=ADESSO_MS - 60000)
        self.scrivi_jsonl("sess-1", [evento_assistente("Fatto.\nProcedo con il deploy? (S/N)")])
        percorso_stato = os.path.join(self.cartella, "stato", "stato.json")

        chiamate = []
        def avvisatore_finto(progetto, testo):
            chiamate.append((progetto, testo))

        cs.esegui_notify(self.sessioni, self.projects, percorso_stato,
                         avvisatore=avvisatore_finto)
        self.assertEqual(len(chiamate), 1)
        self.assertEqual(chiamate[0][0], "prog")
        self.assertIn("deploy? (S/N)", chiamate[0][1])
        self.assertTrue(os.path.isfile(percorso_stato))

        # Secondo giro: la sessione aspetta ancora, ma non e' una transizione.
        cs.esegui_notify(self.sessioni, self.projects, percorso_stato,
                         avvisatore=avvisatore_finto)
        self.assertEqual(len(chiamate), 1)

    def test_stato_malformato_non_blocca(self):
        percorso_stato = os.path.join(self.cartella, "stato.json")
        with open(percorso_stato, "w", encoding="utf-8") as f:
            f.write("non json")
        self.assertEqual(cs.carica_stato(percorso_stato), {})
        cs.salva_stato(percorso_stato, [{"session_id": "x", "nome": "X",
                                         "domanda_per_utente": True}])
        self.assertTrue(cs.carica_stato(percorso_stato)["x"]["aspetta"])


class TestNotifyGruppo(BaseTemporanea):
    """Due sessioni che passano ad "aspetta te" nello stesso giro: un avviso solo."""

    def setUp(self):
        super().setUp()
        self.percorso_stato = os.path.join(self.cartella, "stato", "stato.json")

    def _attesa(self, pid, session_id, cwd, nome):
        self.scrivi_sessione(pid, sessionId=session_id, cwd=cwd, status="idle",
                             name=nome, startedAt=ADESSO_MS - 600000,
                             statusUpdatedAt=ADESSO_MS - 60000)
        self.scrivi_jsonl(session_id, [evento_assistente(
            "Fatto.\n\n\u23f3 **IN ATTESA DI:** Utente, che deve decidere")])

    def _giro(self, chiamate):
        cs.esegui_notify(self.sessioni, self.projects, self.percorso_stato,
                         avvisatore=lambda p, t: chiamate.append((p, t)))

    def test_due_sessioni_un_solo_avviso(self):
        self._attesa(os.getpid(), "sess-a", "/Users/x/alfa", "alfa")
        self._attesa(os.getppid(), "sess-b", "/Users/x/beta", "beta")
        chiamate = []
        self._giro(chiamate)
        self.assertEqual(len(chiamate), 1)
        self.assertEqual(chiamate[0][0], "Sessioni: 2 ti aspettano")
        self.assertIn("2 sessioni ti aspettano: alfa, beta.", chiamate[0][1])

        # secondo giro: nessuna nuova attesa, nessun avviso
        self._giro(chiamate)
        self.assertEqual(len(chiamate), 1)

    def test_una_sola_sessione_avvisa_come_prima(self):
        self._attesa(os.getpid(), "sess-a", "/Users/x/alfa", "alfa")
        chiamate = []
        self._giro(chiamate)
        self.assertEqual(len(chiamate), 1)
        self.assertEqual(chiamate[0][0], "alfa")
        self.assertIn("Utente", chiamate[0][1])


class TestJson(BaseTemporanea):
    def test_json_valido_con_chiavi_italiane(self):
        self.scrivi_sessione(os.getpid(), sessionId="sess-2", cwd="/Users/x/prog",
                             status="idle", name="prog-2",
                             startedAt=ADESSO_MS - 600000, statusUpdatedAt=ADESSO_MS - 60000)
        self.scrivi_jsonl("sess-2", [evento_assistente("Riepilogo.\nServe un ok? (S/N)")])
        sessioni = cs.raccogli(self.sessioni, self.projects)
        dati = json.loads(json.dumps(sessioni, ensure_ascii=False))
        self.assertEqual(len(dati), 1)
        for chiave in ("nome", "progetto", "stato", "da", "aperta_da", "attesa",
                       "domanda_per_utente", "domanda", "anteprima"):
            self.assertIn(chiave, dati[0])
        self.assertTrue(dati[0]["domanda_per_utente"])


# ==========================================================================
# Correzioni del 17/11/2026: voci di attesa, nome utente, stato "shell"
# ==========================================================================

ATTESA_DUE_VOCI = ("Fatto.\n\n\u23f3 **IN ATTESA DI:** Utente, che deve approvare S/N il design "
                   "(messaggio: /a.md) \u00b7 Bruno, che deve aggiungere il service account "
                   "(messaggio: /b.txt)")


class TestVoci(unittest.TestCase):
    def test_divisione_semplice(self):
        voci = cs.dividi_voci(ATTESA_DUE_VOCI.split("IN ATTESA DI:**", 1)[1].strip())
        self.assertEqual(len(voci), 2)
        self.assertTrue(voci[0].startswith("Utente"))
        self.assertTrue(voci[1].startswith("Bruno"))

    def test_separatore_dentro_parentesi_non_divide(self):
        riga = ("Utente, che deve approvare (messaggio: /a.txt \u00b7 stato: /b.txt) \u00b7 "
                "Claude in Chrome, che deve controllare (cookie HttpOnly \u00b7 scadenza: no)")
        voci = cs.dividi_voci(riga)
        self.assertEqual(len(voci), 2)
        self.assertIn("/a.txt \u00b7 stato: /b.txt", voci[0])
        self.assertIn("cookie HttpOnly \u00b7 scadenza: no", voci[1])

    def test_parentesi_quadre_e_graffe(self):
        riga = "Utente, che deve [a \u00b7 b] \u00b7 Bruno, che deve {c \u00b7 d}"
        voci = cs.dividi_voci(riga)
        self.assertEqual(len(voci), 2)
        self.assertIn("[a \u00b7 b]", voci[0])

    def test_parentesi_non_chiusa_non_nasconde_le_voci(self):
        riga = "Utente, che deve (senza chiusura \u00b7 Bruno, che deve B"
        self.assertEqual(len(cs.dividi_voci(riga)), 2)

    def test_attesa_vuota_o_una_sola_voce(self):
        self.assertEqual(cs.dividi_voci(""), [])
        self.assertEqual(cs.dividi_voci(None), [])
        self.assertEqual(cs.dividi_voci("solo una voce"), ["solo una voce"])
        self.assertEqual(cs.dividi_voci("  \u00b7  "), [])

    def test_estrai_attesa_poi_divisione(self):
        attesa = cs.estrai_attesa(ATTESA_DUE_VOCI)
        self.assertEqual(len(cs.dividi_voci(attesa)), 2)


class TestNomeUtente(unittest.TestCase):
    def test_nomi_predefiniti(self):
        self.assertTrue(cs.voce_per_utente("Utente, che deve approvare"))
        self.assertTrue(cs.voce_per_utente("  UTENTE, che deve approvare"))
        self.assertFalse(cs.voce_per_utente("Mario, che deve firmare"))  # not a default name
        self.assertTrue(cs.voce_per_utente("L'utente deve scegliere"))
        self.assertTrue(cs.voce_per_utente("utente: serve un ok"))

    def test_voci_di_altri(self):
        self.assertFalse(cs.voce_per_utente("Bruno, che deve aggiungere il service account"))
        self.assertFalse(cs.voce_per_utente("Claude in Chrome, che deve controllare"))
        self.assertFalse(cs.voce_per_utente("agente Claude sul server, che deve lanciare il collaudo"))
        self.assertFalse(cs.voce_per_utente(""))
        self.assertFalse(cs.voce_per_utente(None))

    def test_nomi_personalizzati_sostituiscono_i_predefiniti(self):
        nomi = ["Bruno"]
        self.assertTrue(cs.voce_per_utente("bruno, che deve confermare", nomi))
        self.assertFalse(cs.voce_per_utente("Utente, che deve approvare", nomi))

    def test_voci_per_utente_filtra_e_mantiene_ordine(self):
        voci = ["Utente, che deve A", "Bruno, che deve B", "l'utente deve C"]
        self.assertEqual(cs.voci_per_utente(voci), [voci[0], voci[2]])
        self.assertEqual(cs.voci_per_utente(voci, ["Bruno"]), [voci[1]])


class TestAspettaUtente(BaseTemporanea):
    def _pronta(self, stato, testo, nomi_utente=None):
        self.scrivi_jsonl("sess-a", [evento_assistente(testo)])
        grezza = {"session_id": "sess-a", "viva": True, "stato_grezzo": stato,
                  "nome": "n", "progetto": "p", "status_updated_at": ADESSO_MS,
                  "started_at": ADESSO_MS}
        return cs.costruisci_sessione(grezza, self.projects, ADESSO_MS, nomi_utente=nomi_utente)

    def test_idle_con_attesa_per_utente_aspetta(self):
        pronta = self._pronta("idle", ATTESA_DUE_VOCI)
        self.assertTrue(pronta["aspetta_utente"])
        self.assertTrue(pronta["domanda_per_utente"])   # compatibilita'
        self.assertEqual(len(pronta["attese"]), 2)
        self.assertEqual(len(pronta["attese_per_utente"]), 1)
        self.assertIn("Utente", pronta["attese_per_utente"][0])

    def test_busy_con_la_stessa_attesa_non_aspetta(self):
        pronta = self._pronta("busy", ATTESA_DUE_VOCI)
        self.assertFalse(pronta["aspetta_utente"])
        self.assertFalse(pronta["domanda_per_utente"])
        self.assertEqual(pronta["stato"], "al lavoro")
        self.assertEqual(len(pronta["attese_per_utente"]), 1)   # le voci restano

    def test_shell_con_la_stessa_attesa_non_aspetta(self):
        pronta = self._pronta("shell", ATTESA_DUE_VOCI)
        self.assertFalse(pronta["aspetta_utente"])
        self.assertEqual(pronta["stato"], "comando in corso")

    def test_idle_senza_voci_per_utente_non_aspetta(self):
        testo = ("\u23f3 **IN ATTESA DI:** Bruno, che deve aggiungere il service account "
                 "\u00b7 Claude in Chrome, che deve controllare i cookie")
        pronta = self._pronta("idle", testo)
        self.assertFalse(pronta["aspetta_utente"])
        self.assertEqual(pronta["attese_per_utente"], [])
        self.assertEqual(len(pronta["attese"]), 2)

    def test_idle_con_domanda_aspetta(self):
        pronta = self._pronta("idle", "Riepilogo.\nProcedo con il deploy? (S/N)")
        self.assertTrue(pronta["aspetta_utente"])
        self.assertTrue(pronta["domanda"])

    def test_nome_utente_personalizzato(self):
        pronta = self._pronta("idle", ATTESA_DUE_VOCI, nomi_utente=["Bruno"])
        self.assertTrue(pronta["aspetta_utente"])
        self.assertEqual(len(pronta["attese_per_utente"]), 1)
        self.assertIn("Bruno", pronta["attese_per_utente"][0])


class TestStatoShell(unittest.TestCase):
    def test_mappatura(self):
        self.assertEqual(cs.stato_leggibile("busy"), "al lavoro")
        self.assertEqual(cs.stato_leggibile("shell"), "comando in corso")
        self.assertEqual(cs.stato_leggibile("idle"), "ferma")
        self.assertEqual(cs.stato_leggibile("nuovo-valore"), "nuovo-valore")
        self.assertEqual(cs.stato_leggibile(""), "sconosciuto")

    def test_shell_in_tabella_e_giallo(self):
        sessioni = [{"nome": "s", "progetto": "p", "stato": "comando in corso",
                     "stato_grezzo": "shell", "da": "1 min", "aspetta_utente": False,
                     "attese": [], "attese_per_utente": [], "domanda": "", "attesa": ""}]
        tabella = cs.render_tabella(sessioni, colore=True)
        self.assertIn("comando in corso", tabella)
        self.assertIn(cs.COLORI["busy"], tabella)
        self.assertNotIn(cs.COLORI["attesa"], tabella)

    def test_busy_in_tabella_e_giallo(self):
        sessioni = [{"nome": "s", "progetto": "p", "stato": "al lavoro",
                     "stato_grezzo": "busy", "da": "1 min", "aspetta_utente": False,
                     "attese": [], "attese_per_utente": [], "domanda": "", "attesa": ""}]
        tabella = cs.render_tabella(sessioni, colore=True)
        self.assertIn(cs.COLORI["busy"], tabella)


class TestTabellaVoci(unittest.TestCase):
    def _sessione(self, attese, per_utente, domanda=""):
        return {"nome": "s", "progetto": "p", "stato": "ferma", "stato_grezzo": "idle",
                "da": "2 min", "aspetta_utente": bool(per_utente or domanda),
                "domanda": domanda, "attesa": " \u00b7 ".join(attese),
                "attese": attese, "attese_per_utente": per_utente}

    def test_colonna_si_e_righe_per_te_prima_delle_altre(self):
        sessione = self._sessione(["Utente, che deve A", "Bruno, che deve B"],
                                  ["Utente, che deve A"])
        tabella = cs.render_tabella([sessione])
        righe = tabella.splitlines()
        self.assertIn("si", righe[2])
        pos_per_te = next(i for i, r in enumerate(righe) if r.strip().startswith("per te: Utente"))
        pos_attesa = next(i for i, r in enumerate(righe) if r.strip().startswith("attesa: Bruno"))
        self.assertLess(pos_per_te, pos_attesa)
        self.assertFalse(any("attesa: Utente" in r for r in righe))

    def test_domanda_prima_delle_voci(self):
        sessione = self._sessione(["Utente, che deve A"], ["Utente, che deve A"],
                                  domanda="Procedo? (S/N)")
        righe = cs.render_tabella([sessione]).splitlines()
        pos_domanda = next(i for i, r in enumerate(righe) if r.strip().startswith("domanda: "))
        pos_per_te = next(i for i, r in enumerate(righe) if r.strip().startswith("per te: "))
        self.assertLess(pos_domanda, pos_per_te)
        self.assertIn("Procedo? (S/N)", righe[pos_domanda])

    def test_voce_lunga_tagliata_a_160(self):
        lunga = "Utente, che deve " + ("parola " * 60)
        sessione = self._sessione([lunga], [lunga])
        righe = cs.render_tabella([sessione]).splitlines()
        riga = next(r for r in righe if r.strip().startswith("per te: "))
        self.assertTrue(riga.endswith("\u2026"))
        self.assertLessEqual(len(riga), len("    per te: ") + 160)

    def test_record_vecchio_senza_lista_voci(self):
        sessione = {"nome": "s", "progetto": "p", "stato": "ferma", "stato_grezzo": "idle",
                    "da": "2 min", "domanda_per_utente": False,
                    "attesa": "Utente, che deve A \u00b7 Bruno, che deve B"}
        tabella = cs.render_tabella([sessione])
        # Le liste mancano: la tabella le ricalcola dalla riga di attesa.
        self.assertIn("    per te: Utente, che deve A", tabella)
        self.assertIn("    attesa: Bruno, che deve B", tabella)


class TestNotifyVoci(BaseTemporanea):
    def setUp(self):
        super().setUp()
        self.scrivi_sessione(os.getpid(), sessionId="sess-v", cwd="/Users/x/prog",
                             status="idle", name="prog-v",
                             startedAt=ADESSO_MS - 600000, statusUpdatedAt=ADESSO_MS - 60000)
        self.percorso_stato = os.path.join(self.cartella, "stato", "stato.json")
        self.chiamate = []

        def avvisatore_finto(progetto, testo):
            self.chiamate.append((progetto, testo))

        self.avvisatore = avvisatore_finto

    def _attesa(self, voci):
        testo = ("Fatto.\n\n\u23f3 **IN ATTESA DI:** " + " \u00b7 ".join(voci))
        self.scrivi_jsonl("sess-v", [evento_assistente(testo)])

    def _giro(self):
        cs.esegui_notify(self.sessioni, self.projects, self.percorso_stato,
                         avvisatore=self.avvisatore)

    def test_prima_attesa_poi_nessuna_poi_voce_nuova(self):
        self._attesa(["Utente, che deve A (messaggio: /a.md)",
                      "Bruno, che deve B"])
        self._giro()
        self.assertEqual(len(self.chiamate), 1)
        self.assertEqual(self.chiamate[0][0], "prog")
        self.assertIn("Utente, che deve A", self.chiamate[0][1])

        self._giro()   # giro uguale: nessuna notifica
        self.assertEqual(len(self.chiamate), 1)

        self._attesa(["Utente, che deve A (messaggio: /a.md)",
                      "Utente, che deve C (messaggio: /c.md)",
                      "Bruno, che deve B"])
        self._giro()   # voce per l'utente nuova: nuova notifica con quella voce
        self.assertEqual(len(self.chiamate), 2)
        self.assertIn("Utente, che deve C", self.chiamate[1][1])

        self._giro()   # le voci sono le stesse: niente
        self.assertEqual(len(self.chiamate), 2)

    def test_stato_salva_le_voci_per_utente(self):
        self._attesa(["Utente, che deve A", "Bruno, che deve B"])
        self._giro()
        with open(self.percorso_stato, "r", encoding="utf-8") as f:
            salvato = json.load(f)
        voce = salvato["sessioni"]["sess-v"]
        self.assertTrue(voce["aspetta"])
        self.assertEqual(voce["attese_per_utente"], ["Utente, che deve A"])

    def test_domanda_ha_la_precedenza_nel_testo(self):
        testo = ("Riepilogo.\nProcedo con il deploy? (S/N)\n\n\u23f3 **IN ATTESA DI:** "
                 "Utente, che deve approvare (messaggio: /a.md)")
        self.scrivi_jsonl("sess-v", [evento_assistente(testo)])
        self._giro()
        self.assertEqual(len(self.chiamate), 1)
        self.assertIn("deploy? (S/N)", self.chiamate[0][1])

    def test_sessione_busy_non_notifica(self):
        self.scrivi_sessione(os.getpid(), sessionId="sess-v", cwd="/Users/x/prog",
                             status="busy", name="prog-v",
                             startedAt=ADESSO_MS - 600000, statusUpdatedAt=ADESSO_MS - 60000)
        self._attesa(["Utente, che deve A"])
        self._giro()
        self.assertEqual(self.chiamate, [])


class TestStatoVecchio(BaseTemporanea):
    def test_stato_senza_elenco_voci_non_notifica_di_nuovo(self):
        sessioni = [{"session_id": "a", "nome": "A", "aspetta_utente": True,
                     "domanda_per_utente": True, "domanda": "A?",
                     "attese_per_utente": ["Utente, che deve A"]}]
        precedente = {"a": {"nome": "A", "aspetta": True}}   # formato vecchio
        self.assertEqual(cs.sessioni_da_notificare(sessioni, precedente), [])

    def test_stato_vecchio_che_non_aspettava_notifica(self):
        sessioni = [{"session_id": "a", "nome": "A", "aspetta_utente": True,
                     "attese_per_utente": ["Utente, che deve A"]}]
        precedente = {"a": {"nome": "A", "aspetta": False}}
        self.assertEqual(len(cs.sessioni_da_notificare(sessioni, precedente)), 1)

    def test_vecchio_stato_json_su_disco(self):
        percorso = os.path.join(self.cartella, "stato.json")
        with open(percorso, "w", encoding="utf-8") as f:
            json.dump({"aggiornato": 1, "sessioni": {"a": {"nome": "A", "aspetta": True}}}, f)
        caricato = cs.carica_stato(percorso)
        self.assertEqual(caricato, {"a": {"nome": "A", "aspetta": True}})
        sessioni = [{"session_id": "a", "nome": "A", "aspetta_utente": True,
                     "attese_per_utente": ["Utente, che deve A"]}]
        self.assertEqual(cs.sessioni_da_notificare(sessioni, caricato), [])
        cs.salva_stato(percorso, sessioni)   # riscrittura nel formato nuovo
        with open(percorso, "r", encoding="utf-8") as f:
            nuovo = json.load(f)
        self.assertEqual(nuovo["sessioni"]["a"]["attese_per_utente"],
                         ["Utente, che deve A"])


class TestRigaDiComando(BaseTemporanea):
    def _esegui(self, argv):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            codice = cs.main(argv)
        return codice, buffer.getvalue()

    def test_json_con_aspetta_utente_e_nome_utente(self):
        self.scrivi_sessione(os.getpid(), sessionId="cli-1", cwd="/Users/x/prog",
                             status="idle", name="cli")
        self.scrivi_jsonl("cli-1", [evento_assistente(
            "\u23f3 **IN ATTESA DI:** Bruno, che deve confermare \u00b7 "
            "Utente, che deve approvare")])
        base = ["--json", "--sessioni-dir", self.sessioni, "--projects-dir", self.projects]

        codice, uscita = self._esegui(base)
        self.assertEqual(codice, 0)
        dati = json.loads(uscita)
        self.assertTrue(dati[0]["aspetta_utente"])
        self.assertEqual(len(dati[0]["attese"]), 2)
        self.assertEqual(len(dati[0]["attese_per_utente"]), 1)

        codice, uscita = self._esegui(base + ["--nome-utente", "Bruno",
                                             "--nome-utente", "Carlo"])
        self.assertEqual(codice, 0)
        dati = json.loads(uscita)
        self.assertEqual(len(dati[0]["attese_per_utente"]), 1)
        self.assertIn("Bruno", dati[0]["attese_per_utente"][0])

    def test_tabella_senza_colori(self):
        self.scrivi_sessione(os.getpid(), sessionId="cli-2", cwd="/Users/x/prog",
                             status="shell", name="cli-shell")
        codice, uscita = self._esegui(["--sessioni-dir", self.sessioni,
                                      "--projects-dir", self.projects])
        self.assertEqual(codice, 0)
        self.assertIn("comando in corso", uscita)

class TestFileMalformati(BaseTemporanea):
    """File JSON validi ma con tipi sbagliati: non devono far cadere lo script."""

    def _raccogli(self):
        return cs.raccogli(self.sessioni, self.projects)

    def test_timestamp_non_numerico(self):
        self.scrivi_sessione(os.getpid(), status="idle", name="rotto",
                             startedAt="abc", statusUpdatedAt="ieri")
        sessioni = self._raccogli()
        self.assertEqual(len(sessioni), 1)
        self.assertEqual(sessioni[0]["stato"], "ferma")
        self.assertEqual(sessioni[0]["da"], "meno di 1 min")
        self.assertEqual(sessioni[0]["aperta_da"], "")

    def test_timestamp_numerico_in_stringa_accettato(self):
        adesso = int(time.time() * 1000)
        self.scrivi_sessione(os.getpid(), status="busy", name="ok",
                             statusUpdatedAt=str(adesso - 125000))
        sessioni = self._raccogli()
        self.assertEqual(sessioni[0]["stato"], "al lavoro")
        self.assertEqual(sessioni[0]["da"], "2 min")

    def test_nome_numerico(self):
        self.scrivi_sessione(os.getpid(), status="idle", name=123)
        sessioni = self._raccogli()
        self.assertEqual(sessioni[0]["nome"], "123")

    def test_cwd_numerico(self):
        self.scrivi_sessione(os.getpid(), status="idle", name="x", cwd=5)
        sessioni = self._raccogli()          # non deve far cadere lo script
        self.assertEqual(sessioni[0]["progetto"], "5")
        self.scrivi_sessione(os.getpid(), status="idle", name="y", cwd={"a": 1})
        self.assertEqual(self._raccogli()[0]["progetto"], "?")

    def test_status_non_testo(self):
        self.scrivi_sessione(os.getpid(), status={"a": 1}, name="x")
        sessioni = self._raccogli()
        self.assertEqual(sessioni[0]["stato"], "sconosciuto")

    def test_pid_booleano_non_e_vivo(self):
        self.assertFalse(cs.processo_vivo(True))

    def test_pid_non_positivo_non_e_vivo(self):
        self.assertFalse(cs.processo_vivo(0))
        self.assertFalse(cs.processo_vivo(-1))

    def test_pid_booleano_nel_file_sessione(self):
        with open(os.path.join(self.sessioni, "1.json"), "w", encoding="utf-8") as f:
            f.write('{"pid": true, "status": "idle", "name": "finta"}')
        self.assertEqual(self._raccogli(), [])

    def test_ms_a_iso_tipo_sbagliato(self):
        self.assertEqual(cs.ms_a_iso({"a": 1}), "")
        self.assertEqual(cs.ms_a_iso("ieri"), "")

    def test_record_con_timestamp_rotto(self):
        record = cs.costruisci_sessione(
            {"nome": "x", "viva": True, "stato_grezzo": "idle",
             "status_updated_at": "ieri", "started_at": {"a": 1}},
            self.projects)
        self.assertEqual(record["da"], "meno di 1 min")
        self.assertEqual(record["aperta_da"], "")

    def test_main_errore_imprevisto_senza_traceback(self):
        with mock.patch.object(cs, "raccogli", side_effect=OSError("disco")):
            errore = io.StringIO()
            with contextlib.redirect_stderr(errore):
                codice = cs.main(["--sessioni-dir", self.sessioni,
                                  "--projects-dir", self.projects])
        self.assertEqual(codice, 1)
        self.assertIn("errore nella lettura", errore.getvalue())




FINTO_OSASCRIPT = """#!/usr/bin/python3
import os, sys
with open(os.environ["POSTA_FINTO_LOG"], "a", encoding="utf-8") as scrittura:
    scrittura.write(repr(sys.argv[1:]) + "\\n")
    scrittura.flush()
"""

FINTO_AFPLAY = """#!/usr/bin/python3
import os, sys
with open(os.environ["POSTA_AUDIO_LOG"], "a", encoding="utf-8") as scrittura:
    scrittura.write(repr(["afplay"] + sys.argv[1:]) + "\\n")
    scrittura.flush()
"""

FINTO_SAY = """#!/usr/bin/python3
import os, sys
if sys.argv[1:3] == ["-v", "?"]:
    print("Alice              en_US    # Hello, my name is Alice.")
    sys.exit(0)
with open(os.environ["POSTA_AUDIO_LOG"], "a", encoding="utf-8") as scrittura:
    scrittura.write(repr(["say"] + sys.argv[1:]) + "\\n")
    scrittura.flush()
"""


class TestAvvisoConPosta(unittest.TestCase):
    """Integrazione con il vero posta.py, ma con osascript/afplay/say finti."""

    VARIABILI = ("POSTA_OSASCRIPT", "POSTA_FINTO_LOG", "POSTA_AFPLAY",
                 "POSTA_SAY", "POSTA_AUDIO_LOG", "POSTA_SUONO",
                 "POSTA_LOCK_VOCE", "POSTA_LOCK_TIMEOUT", "POSTA_ERRORI_LOG")

    def setUp(self):
        self.cartella = tempfile.mkdtemp(prefix="claude-stato-avviso-")
        self.env_prima = {chiave: os.environ.get(chiave) for chiave in self.VARIABILI}
        self.log_osascript = os.path.join(self.cartella, "osascript.log")
        self.log_audio = os.path.join(self.cartella, "audio.log")
        os.environ["POSTA_FINTO_LOG"] = self.log_osascript
        os.environ["POSTA_AUDIO_LOG"] = self.log_audio
        os.environ["POSTA_SUONO"] = os.path.join(self.cartella, "sosumi.aiff")
        os.environ["POSTA_LOCK_VOCE"] = os.path.join(self.cartella, "voce.lock")
        os.environ["POSTA_ERRORI_LOG"] = os.path.join(self.cartella, "errori.log")
        for variabile, nome, testo, in (
                ("POSTA_OSASCRIPT", "finto-osascript", FINTO_OSASCRIPT),
                ("POSTA_AFPLAY", "finto-afplay", FINTO_AFPLAY),
                ("POSTA_SAY", "finto-say", FINTO_SAY)):
            percorso = os.path.join(self.cartella, nome)
            with open(percorso, "w", encoding="utf-8") as f:
                f.write(testo)
            os.chmod(percorso, 0o755)
            os.environ[variabile] = percorso

    def tearDown(self):
        for chiave, valore in self.env_prima.items():
            if valore is None:
                os.environ.pop(chiave, None)
            else:
                os.environ[chiave] = valore
        shutil.rmtree(self.cartella, ignore_errors=True)

    def _righe(self, percorso, minimo, secondi=12.0):
        fine = time.time() + secondi
        voci = []
        while time.time() < fine:
            voci = []
            try:
                with open(percorso, "r", encoding="utf-8") as f:
                    for riga in f:
                        riga = riga.strip()
                        if riga:
                            voci.append(ast.literal_eval(riga))
            except (OSError, ValueError, SyntaxError):
                voci = []
            if len(voci) >= minimo:
                return voci
            time.sleep(0.05)
        self.fail("attese almeno %d righe in %s, trovate %d"
                  % (minimo, percorso, len(voci)))

    def test_decisione_usa_notifica_suono_e_voce(self):
        cs.avvisa_sessione("b2b_frontend", "Testo della notifica")

        voci = self._righe(self.log_osascript, 1)
        self.assertEqual(len(voci), 1)
        script = voci[0][1]
        self.assertIn('display notification "Testo della notifica"', script)
        self.assertIn('with title "B2B FRONTEND \u00b7 decisione"', script)
        self.assertNotIn("display alert", script)
        self.assertNotIn("sound name", script)

        audio = self._righe(self.log_audio, 6)
        afplay = [a for a in audio if a[0] == "afplay"]
        parlate = [a for a in audio if a[0] == "say"]
        self.assertEqual(len(afplay), 4)
        self.assertEqual(len(parlate), 2)
        for voce in afplay:
            self.assertEqual(voce[1:], [os.environ["POSTA_SUONO"]])
        for voce in parlate:
            self.assertEqual(voce[1:], ["-v", "Alice",
                                        "Progetto b2b frontend. Serve una tua decisione."])


class TestAscoltoPosta(unittest.TestCase):
    """Riconoscimento dei processi "posta.py attendi --casella NOME"."""

    def test_riconosce_posta_attendi(self):
        righe = [
            "/usr/bin/python3 /Users/x/x/posta.py attendi --casella b2b_frontend "
            "--max-secondi 120",
            "python3 posta.py attendi --casella echo",
            "python3 posta.py elenco --casella echo",
            "python3 /x/posta.py attendi --max-secondi 60 --casella alpha-bot",
            "python3 /x/posta.py attendi --casella=b2b_frontend2",
            "opencode run 'un prompt che cita posta.py attendi --casella <casella>'",
        ]
        self.assertEqual(cs.caselle_in_ascolto(righe),
                         {"b2b_frontend", "echo", "alpha-bot", "b2b_frontend2"})
        self.assertTrue(cs.ascolta_posta(righe, "b2b_frontend"))
        self.assertTrue(cs.ascolta_posta(righe, "echo"))
        self.assertFalse(cs.ascolta_posta(righe, "erp_core"))

    def test_altri_comandi_e_nomi_simili_non_contano(self):
        righe = ["python3 posta.py invia --da opencode --a echo --tipo richiesta",
                 "python3 posta.py attendi --casella echo2"]
        self.assertEqual(cs.caselle_in_ascolto(righe), {"echo2"})
        self.assertFalse(cs.ascolta_posta(righe, "echo"))

    def test_ps_fallito_e_righe_strane(self):
        self.assertIsNone(cs.caselle_in_ascolto(None))
        self.assertIsNone(cs.ascolta_posta(None, "echo"))
        self.assertIsNone(cs.ascolta_posta([], ""))
        self.assertEqual(cs.caselle_in_ascolto([None, 3, "x"]), set())

    def test_leggi_ps_con_eseguibile_finto(self):
        cartella = tempfile.mkdtemp(prefix="finto-ps-")
        self.addCleanup(shutil.rmtree, cartella, True)
        finto = os.path.join(cartella, "finto-ps")
        with open(finto, "w", encoding="utf-8") as f:
            f.write("#!/usr/bin/python3\n"
                    "print('python3 /x/posta.py attendi --casella echo')\n")
        os.chmod(finto, 0o755)
        self.assertEqual(cs.leggi_ps([finto, "-axo", "command"]),
                         ["python3 /x/posta.py attendi --casella echo"])

        rotto = os.path.join(cartella, "finto-ps-rotto")
        with open(rotto, "w", encoding="utf-8") as f:
            f.write("#!/bin/sh\nexit 1\n")
        os.chmod(rotto, 0o755)
        self.assertIsNone(cs.leggi_ps([rotto]))
        self.assertIsNone(cs.leggi_ps([os.path.join(cartella, "non-esiste")]))


class TestColonnaPosta(BaseTemporanea):
    def _due_sessioni(self):
        # Due pid vivi e diversi: il nome del file sessione e' il pid.
        self.scrivi_sessione(os.getpid(), sessionId="posta-1",
                             cwd="/Users/x/b2b_frontend", status="idle", name="alfa")
        self.scrivi_sessione(os.getppid(), sessionId="posta-2",
                             cwd="/Users/x/echo", status="idle", name="beta")
        self.scrivi_jsonl("posta-1", [evento_assistente("Fatto.")])
        self.scrivi_jsonl("posta-2", [evento_assistente("Fatto.")])

    def test_colonna_e_json_con_finto_ps(self):
        self._due_sessioni()
        righe = ["python3 /x/posta.py attendi --casella b2b_frontend --max-secondi 120"]
        with mock.patch.object(cs, "leggi_ps", return_value=righe):
            sessioni = cs.raccogli(self.sessioni, self.projects)
        per_nome = {s["nome"]: s for s in sessioni}
        self.assertIs(per_nome["alfa"]["ascolta_posta"], True)
        self.assertIs(per_nome["beta"]["ascolta_posta"], False)

        tabella = cs.render_tabella(sessioni)
        righe_tabella = tabella.splitlines()
        self.assertIn("POSTA", righe_tabella[0])
        alfa = next(r for r in righe_tabella if r.startswith("alfa"))
        beta = next(r for r in righe_tabella if r.startswith("beta"))
        self.assertEqual(alfa.split()[-1], "si")
        self.assertEqual(beta.split()[-1], "NO")

    def test_ps_fallito_colonna_interrogativo(self):
        self._due_sessioni()
        with mock.patch.object(cs, "leggi_ps", return_value=None):
            sessioni = cs.raccogli(self.sessioni, self.projects)
        self.assertTrue(all(s["ascolta_posta"] is None for s in sessioni))
        righe_tabella = cs.render_tabella(sessioni).splitlines()
        self.assertIn("POSTA", righe_tabella[0])
        for riga in righe_tabella[2:]:
            self.assertTrue(riga.endswith("?"), riga)

    def test_una_sola_chiamata_a_ps_per_raccolta(self):
        self._due_sessioni()
        chiamate = []

        def finto(comando=None):
            chiamate.append(comando)
            return []

        with mock.patch.object(cs, "leggi_ps", side_effect=finto):
            cs.raccogli(self.sessioni, self.projects)
        self.assertEqual(len(chiamate), 1)

    def test_sessione_chiusa_non_ha_ascolto(self):
        self.scrivi_sessione(PID_MORTO, sessionId="morta-p", cwd="/Users/x/echo",
                             status="idle", name="morta")
        with mock.patch.object(cs, "leggi_ps",
                               return_value=["python3 posta.py attendi --casella echo"]):
            tutte = cs.raccogli(self.sessioni, self.projects, includi_morte=True)
        self.assertIsNone(tutte[0]["ascolta_posta"])
        self.assertTrue(cs.render_tabella(tutte).splitlines()[-1].endswith("?"))

    def test_json_della_riga_di_comando(self):
        self._due_sessioni()
        with mock.patch.object(cs, "leggi_ps",
                               return_value=["python3 posta.py attendi --casella b2b_frontend"]):
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                codice = cs.main(["--json", "--sessioni-dir", self.sessioni,
                                  "--projects-dir", self.projects])
        self.assertEqual(codice, 0)
        dati = json.loads(buffer.getvalue())
        per_nome = {s["nome"]: s for s in dati}
        self.assertTrue(per_nome["alfa"]["ascolta_posta"])
        self.assertFalse(per_nome["beta"]["ascolta_posta"])


# ==========================================================================
# Correzione del 17/11/2026: status "shell" con il turno gia' finito = ferma
# ==========================================================================

def evento_system(subtype):
    return {"type": "system", "subtype": subtype,
            "timestamp": "2026-11-17T09:19:20.000Z"}


def evento_tool_use():
    return {"type": "assistant",
            "message": {"role": "assistant",
                        "content": [{"type": "tool_use", "id": "t1",
                                     "name": "Bash", "input": {}}]}}


def evento_tool_result():
    return {"type": "user",
            "message": {"role": "user",
                        "content": [{"type": "tool_result", "tool_use_id": "t1",
                                     "content": "fatto"}]}}


ATTESA_PER_UTENTE = ("Fatto.\n\n\u23f3 **IN ATTESA DI:** Utente, che deve approvare "
                     "(messaggio: /a.md)")


class TestTurnoFinito(BaseTemporanea):
    def _pronta(self, stato, righe, session_id="turno-1"):
        self.scrivi_jsonl(session_id, righe)
        grezza = {"session_id": session_id, "viva": True, "stato_grezzo": stato,
                  "nome": "n", "progetto": "p", "status_updated_at": ADESSO_MS,
                  "started_at": ADESSO_MS}
        return cs.costruisci_sessione(grezza, self.projects, ADESSO_MS)

    def test_shell_con_turn_duration_finale_e_ferma(self):
        pronta = self._pronta("shell", [
            evento_assistente(ATTESA_PER_UTENTE),
            evento_system("turn_duration"),
            evento_system("away_summary"),
        ])
        self.assertTrue(pronta["turno_finito"])
        self.assertEqual(pronta["stato"], "ferma")
        self.assertEqual(pronta["stato_grezzo"], "shell")
        self.assertTrue(pronta["aspetta_utente"])
        self.assertTrue(pronta["domanda_per_utente"])
        self.assertEqual(len(pronta["attese_per_utente"]), 1)

    def test_shell_senza_voci_per_utente_e_ferma_ma_non_aspetta(self):
        pronta = self._pronta("shell", [
            evento_assistente("Fatto.\n\n\u23f3 **IN ATTESA DI:** Bruno, che deve B"),
            evento_system("turn_duration"),
        ])
        self.assertEqual(pronta["stato"], "ferma")
        self.assertFalse(pronta["aspetta_utente"])

    def test_shell_con_tool_use_dopo_il_turn_duration_lavora(self):
        pronta = self._pronta("shell", [
            evento_assistente(ATTESA_PER_UTENTE),
            evento_system("turn_duration"),
            evento_assistente("Altro giro."),
            evento_tool_use(),
            evento_tool_result(),
        ])
        self.assertFalse(pronta["turno_finito"])
        self.assertEqual(pronta["stato"], "comando in corso")
        self.assertFalse(pronta["aspetta_utente"])

    def test_shell_senza_turn_duration_lavora(self):
        pronta = self._pronta("shell", [evento_assistente(ATTESA_PER_UTENTE)])
        self.assertFalse(pronta["turno_finito"])
        self.assertEqual(pronta["stato"], "comando in corso")
        self.assertFalse(pronta["aspetta_utente"])

    def test_shell_senza_jsonl_lavora(self):
        grezza = {"session_id": "non-esiste", "viva": True, "stato_grezzo": "shell",
                  "nome": "n", "progetto": "p", "status_updated_at": ADESSO_MS,
                  "started_at": ADESSO_MS}
        pronta = cs.costruisci_sessione(grezza, self.projects, ADESSO_MS)
        self.assertFalse(pronta["turno_finito"])
        self.assertEqual(pronta["stato"], "comando in corso")

    def test_idle_invariato(self):
        pronta = self._pronta("idle", [
            evento_assistente(ATTESA_PER_UTENTE),
            evento_system("turn_duration"),
        ])
        self.assertTrue(pronta["turno_finito"])
        self.assertEqual(pronta["stato"], "ferma")
        self.assertTrue(pronta["aspetta_utente"])

    def test_busy_resta_al_lavoro(self):
        pronta = self._pronta("busy", [
            evento_assistente(ATTESA_PER_UTENTE),
            evento_system("turn_duration"),
        ])
        self.assertEqual(pronta["stato"], "al lavoro")
        self.assertFalse(pronta["aspetta_utente"])

    def test_eventi_non_utili_non_contano(self):
        pronta = self._pronta("shell", [
            evento_assistente("Fatto."),
            evento_system("turn_duration"),
            {"type": "attachment", "name": "x"},
            {"type": "api-request", "id": "r1"},
            evento_system("away_summary"),
        ])
        self.assertTrue(pronta["turno_finito"])
        self.assertEqual(pronta["stato"], "ferma")

    def test_leggi_coda_conversazione_una_sola_lettura(self):
        self.scrivi_jsonl("turno-2", [evento_assistente("Testo vero"),
                                      evento_system("turn_duration")])
        testo, finito = cs.leggi_coda_conversazione(self.projects, "turno-2")
        self.assertEqual(testo, "Testo vero")
        self.assertTrue(finito)
        self.assertEqual(cs.ultimo_testo_assistente(self.projects, "turno-2"), "Testo vero")

    def test_colore_ciano_come_idle(self):
        sessione = {"nome": "s", "progetto": "p", "stato": "ferma",
                    "stato_grezzo": "shell", "stato_effettivo": "idle",
                    "turno_finito": True, "da": "1 min", "aspetta_utente": False,
                    "attese": [], "attese_per_utente": [], "domanda": "", "attesa": ""}
        tabella = cs.render_tabella([sessione], colore=True)
        self.assertIn(cs.COLORI["idle"], tabella)
        self.assertNotIn(cs.COLORI["busy"], tabella)


class TestNotifyTurnoFinito(BaseTemporanea):
    def test_shell_ferma_notifica_e_busy_no(self):
        self.scrivi_sessione(os.getpid(), sessionId="sess-t", cwd="/Users/x/prog",
                             status="shell", name="prog-t",
                             startedAt=ADESSO_MS - 600000,
                             statusUpdatedAt=ADESSO_MS - 60000)
        self.scrivi_jsonl("sess-t", [evento_assistente(ATTESA_PER_UTENTE),
                                     evento_system("turn_duration")])
        percorso_stato = os.path.join(self.cartella, "stato", "stato.json")
        chiamate = []
        cs.esegui_notify(self.sessioni, self.projects, percorso_stato,
                         avvisatore=lambda p, t: chiamate.append((p, t)))
        self.assertEqual(len(chiamate), 1)
        self.assertIn("Utente", chiamate[0][1])

        # Stessa sessione ma tornata a lavorare: lo stato salvato non aspetta piu'.
        self.scrivi_jsonl("sess-t", [evento_assistente(ATTESA_PER_UTENTE),
                                     evento_system("turn_duration"),
                                     evento_tool_use()])
        cs.esegui_notify(self.sessioni, self.projects, percorso_stato,
                         avvisatore=lambda p, t: chiamate.append((p, t)))
        self.assertEqual(len(chiamate), 1)
        with open(percorso_stato, "r", encoding="utf-8") as f:
            salvato = json.load(f)
        self.assertFalse(salvato["sessioni"]["sess-t"]["aspetta"])


if __name__ == "__main__":
    unittest.main()
