#!/bin/sh
# Pulls $OLLAMA_MODEL into the shared ollama_models volume, then exits.
# Runs in the model-init container, the only Ollama container with internet access.
set -eu

: "${OLLAMA_MODEL:?OLLAMA_MODEL is not set}"

ollama serve >/tmp/ollama-serve.log 2>&1 &
server=$!
trap 'kill "$server" 2>/dev/null || true' EXIT

i=0
until ollama list >/dev/null 2>&1; do
    i=$((i + 1))
    if [ "$i" -ge 60 ]; then
        echo "ollama serve did not start" >&2
        cat /tmp/ollama-serve.log >&2
        exit 1
    fi
    sleep 1
done

echo "Pulling $OLLAMA_MODEL"
ollama pull "$OLLAMA_MODEL"
ollama list
