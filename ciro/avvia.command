#!/bin/zsh
# Apre la faccia parlante: avvia il server locale e il browser.
cd "$(dirname "$0")" || exit 1
PORTA="${FACCIA_PORTA:-8765}"

# se gira gia', apro solo la finestra
if curl -s -o /dev/null --max-time 1 "http://127.0.0.1:${PORTA}/api/stato"; then
  open "http://127.0.0.1:${PORTA}/"
  exit 0
fi

# apro il browser appena il server risponde
(
  for _ in {1..40}; do
    if curl -s -o /dev/null --max-time 1 "http://127.0.0.1:${PORTA}/api/stato"; then
      open "http://127.0.0.1:${PORTA}/"
      exit 0
    fi
    sleep 0.25
  done
) &

# Python with kokoro-onnx installed (see README): CIRO_PYTHON overrides it
PY="${CIRO_PYTHON:-$HOME/.local/share/kokoro/venv/bin/python}"
exec "$PY" -I ./server.py "$PORTA"
