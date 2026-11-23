"""Link a Google account to Ciro's calendar alerts (M6, #30): read-only, once per account.

    python3 ciro/strumenti/collega_calendario.py <short name> [email]

Before: an OAuth client of type «Desktop app» with the Calendar API enabled, its JSON saved as
~/.config/ciro/calendario-client.json (never in the repository).
The browser opens Google's consent page (scope calendar.readonly only); the refresh token goes to
the macOS Keychain as ciro-calendario-<short name>, and the account is added to
~/.config/ciro/calendario.json with its primary calendar. Nothing about the account is logged.
"""

import base64
import hashlib
import http.server
import json
import secrets
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import calendario  # noqa: E402

AMBITO = "https://www.googleapis.com/auth/calendar.readonly"
NOME_RE = "abcdefghijklmnopqrstuvwxyz0123456789-"


def nome_valido(nome):
    return bool(nome) and len(nome) <= 30 and all(c in NOME_RE for c in nome)


def indirizzo_consenso(client_id, porta, verifica, stato, email=None):
    sfida = base64.urlsafe_b64encode(hashlib.sha256(verifica.encode()).digest()).decode().rstrip("=")
    parametri = {"client_id": client_id, "redirect_uri": "http://127.0.0.1:%d/" % porta,
                 "response_type": "code", "scope": AMBITO, "access_type": "offline", "prompt": "consent",
                 "code_challenge": sfida, "code_challenge_method": "S256", "state": stato}
    if email:
        parametri["login_hint"] = email
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(parametri)


def aggiungi_account(nome, percorso=None):
    """Adds the account (primary calendar) to calendario.json, keeping the others."""
    percorso = Path(percorso or calendario.CONFIGURAZIONE)
    try:
        dati = json.loads(percorso.read_text(encoding="utf-8"))
        if not isinstance(dati, dict):
            dati = {}
    except (OSError, ValueError):
        dati = {}
    dati.setdefault(nome, {"calendari": ["primary"]})
    percorso.parent.mkdir(parents=True, exist_ok=True)
    percorso.write_text(json.dumps(dati, ensure_ascii=False, indent=1), encoding="utf-8")
    return dati


def _tra_virgolette(testo):
    return '"' + str(testo).replace("\\", "\\\\").replace('"', '\\"') + '"'


def salva_nel_portachiavi(nome, token):
    """Through `security -i` (stdin): the token never appears in the process list."""
    comando = "add-generic-password -U -s %s -a %s -w %s\n" % (
        _tra_virgolette("ciro-calendario-" + nome), _tra_virgolette(nome), _tra_virgolette(token))
    esito = subprocess.run(["security", "-i"], input=comando, capture_output=True, text=True, timeout=20)
    del comando
    if esito.returncode != 0 or "error" in ((esito.stdout or "") + (esito.stderr or "")).lower():
        raise RuntimeError("il Portachiavi non ha accettato il token")


def aspetta_codice(stato):
    """Local page on a free port: Google sends the browser back here with the code."""
    risultato = {}

    class Ritorno(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            domanda = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if domanda.get("state", [""])[0] == stato:
                risultato["codice"] = domanda.get("code", [""])[0]
                risultato["errore"] = domanda.get("error", [""])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write("<p>Fatto: puoi chiudere questa pagina e tornare al terminale.</p>".encode())

        def log_message(self, *argomenti):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Ritorno)
    return server, risultato


def main(argomenti):
    if not argomenti or not nome_valido(argomenti[0]):
        print("Uso: collega_calendario.py <nome breve: lettere minuscole, cifre, trattino> [email]")
        return 2
    nome, email = argomenti[0], (argomenti[1] if len(argomenti) > 1 else None)
    try:
        client = json.loads(calendario.CLIENT.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        print("Manca %s: scarica il client OAuth «Desktop app» da Google Cloud e salvalo li'." % calendario.CLIENT)
        return 1
    client = client.get("installed") or client
    verifica, stato = secrets.token_urlsafe(64), secrets.token_urlsafe(16)
    server, risultato = aspetta_codice(stato)
    porta = server.server_address[1]
    indirizzo = indirizzo_consenso(client["client_id"], porta, verifica, stato, email)
    print("Si apre il browser: scegli l'account e consenti la sola lettura del calendario.")
    webbrowser.open(indirizzo)
    server.timeout = 30
    scadenza = time.time() + 300          # five minutes to choose the account and consent
    while "codice" not in risultato and time.time() < scadenza:
        server.handle_request()           # other requests (favicon) are answered and ignored
    server.server_close()
    if "codice" not in risultato:
        print("Tempo scaduto: rilancia il comando.")
        return 1
    if not risultato["codice"]:
        print("Google non ha dato il consenso (%s)." % (risultato.get("errore") or "?"))
        return 1
    corpo = urllib.parse.urlencode({
        "client_id": client["client_id"], "client_secret": client.get("client_secret", ""),
        "code": risultato["codice"], "code_verifier": verifica, "grant_type": "authorization_code",
        "redirect_uri": "http://127.0.0.1:%d/" % porta}).encode()
    with urllib.request.urlopen("https://oauth2.googleapis.com/token", corpo, timeout=20) as risposta:
        token = json.load(risposta).get("refresh_token")
    if not token:
        print("Google non ha dato un token permanente: rilancia il comando.")
        return 1
    salva_nel_portachiavi(nome, token)
    del token
    aggiungi_account(nome)
    eventi = calendario.Lettore(calendario.scarica_google, lambda: {nome: {"calendari": ["primary"]}}).leggi()
    print("Collegato «%s». Eventi rossi nei prossimi 35 minuti: %d." % (nome, len(eventi)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
