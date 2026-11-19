"""«Ehi Ciro»: is Ciro being called? (docs: README, "Using it").

By default Ciro answers only when called by name. Whisper's fast model often
mangles the name («e il giro», «ehi, tiro!», «quacca»), so a call is recognised:
- by the name (and its usual misspellings) at the start of the sentence;
- by the variants learned for THIS voice: in the calibration («Ehi Ciro» three
  times) and in use (a failed try followed within 10 s by a recognised call);
- for a short sentence alone, by sounding like «Ehi Ciro» (edit distance).
"""

import re

import cervello

NOME_RE = re.compile(r"^\W*(?:(?:ehi|ehy|hey|ei|ok|okay|oh)\W+)?(?:ciro|kiro|chiro|cyro|ciroo|cirò)\b'?[\s,.:;!?]*", re.I)
NOME_DOPO_EHI_RE = re.compile(r"^\W*(?:ehi|ehy|hey|hei|ei|eh|e)\W+(?:il\W+)?(?:tiro|giro|siro|piro|ciro|kiro|chiro)\b'?[\s,.:;!?]*", re.I)
CHIAMATE = ("ehiciro", "heyciro", "eiciro", "okciro", "ciro")
# never learned as a name: answers and short words said to Ciro anyway
MAI_NOME = {"si", "sì", "no", "uno", "due", "tre", "ok", "okay", "grazie", "yes", "one", "two", "three",
            "basta", "stop", "fermati", "annulla"}
MAX_VARIANTI = 20


def compatta(testo):
    return re.sub(r"[^a-zàèéìòù]", "", (testo or "").lower())


def _distanza(a, b):
    riga = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        prima, riga[0] = riga[0], i
        for j, cb in enumerate(b, 1):
            prima, riga[j] = riga[j], min(riga[j] + 1, riga[j - 1] + 1, prima + (ca != cb))
    return riga[-1]


def varianti():
    return list(cervello.profilo_voce().get("nomi_sentiti") or [])


def impara_variante(testo):
    """How whisper wrote «Ehi Ciro» for this voice: from now on it is a call. False if unusable."""
    parole = (testo or "").split()
    forma = compatta(testo)
    if not parole or len(parole) > 3 or len(forma) < 3 or forma in MAI_NOME:
        return False
    if togli_nome(testo) == (True, ""):
        return True           # already recognised
    tutte = [v for v in varianti() if v != forma] + [forma]
    cervello.aggiorna_profilo(nomi_sentiti=tutte[-MAX_VARIANTI:])
    return True


def togli_nome(testo):
    """(chiamato, resto): «Ciro, come va?» -> (True, «come va?»)."""
    testo = (testo or "").strip()
    trovato = NOME_RE.match(testo) or NOME_DOPO_EHI_RE.match(testo)
    if trovato:
        return True, testo[trovato.end():].strip()
    parole = testo.split()
    apprese = set(varianti())
    for quante in (3, 2, 1):   # a learned variant at the start
        if len(parole) >= quante and compatta(" ".join(parole[:quante])) in apprese:
            return True, " ".join(parole[quante:]).strip()
    # only the name, said badly: up to 3 words that sound like «Ehi Ciro»
    if 0 < len(parole) <= 3:
        forma = compatta(testo)
        soglia = 1 if len(forma) <= 5 else 2
        if forma and min(_distanza(forma, c) for c in CHIAMATE) <= soglia:
            return True, ""
    return False, testo
