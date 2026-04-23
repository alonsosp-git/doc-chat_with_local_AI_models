#!/bin/bash
MODEL="${OLLAMA_MODEL:-llama3.2:1b}"
echo ""
echo "  Docs Chat starting..."
echo "  Model: $MODEL"
echo ""

# Start Ollama in background - do NOT wait for it
echo "  [1/2] Starting Ollama server in background..."
ollama serve &>/var/log/ollama.log &

# Pull model in background if needed (non-blocking)
(
  # Wait for Ollama to be ready, then pull model if missing
  for i in $(seq 1 60); do
    if curl -sf http://localhost:11434/api/tags >/dev/null 2>&1; then
      EXISTING=$(ollama list 2>/dev/null | grep -c "$MODEL" || true)
      if [ "$EXISTING" -gt 0 ]; then
        echo "  [BG] Model $MODEL already downloaded."
      else
        echo "  [BG] Downloading model $MODEL (first run only)..."
        ollama pull "$MODEL" >>/var/log/ollama-pull.log 2>&1
        echo "  [BG] Model download complete."
      fi
      exit 0
    fi
    sleep 1
  done
  echo "  [BG] Ollama did not start in time."
) &

# Start Flask immediately - no waiting
echo "  [2/2] Starting web app on port 5000 (Ollama loading in background)..."
echo ""
echo "  Open: http://localhost:5000"
echo "  The green dot will appear once Ollama is ready."
echo ""
cd /app
exec python3 app.py
