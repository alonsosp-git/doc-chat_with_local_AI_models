#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
#  Docs Chat — Mac Mini M2 Launcher
#  Run this once to build and start everything.
# ─────────────────────────────────────────────────────────────────────────────

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOCS_DIR="$HOME/pdfs"
MODEL="llama3.2:1b"
PORT=5000

clear
echo ""
echo "  Docs Chat -- Mac Mini M2 Setup and Launch"
echo "  Free - Local - Private - No API Key Needed"
echo ""

# Check Docker
if ! command -v docker &>/dev/null; then
    echo "  [ERROR] Docker is not installed."
    echo "  Install from: https://www.docker.com/products/docker-desktop/"
    exit 1
fi

if ! docker info &>/dev/null; then
    echo "  [WAIT] Docker not running. Trying to start Docker Desktop..."
    open -a Docker 2>/dev/null || true
    echo "  Waiting for Docker to start..."
    for i in $(seq 1 30); do
        sleep 2
        if docker info &>/dev/null; then
            echo "  [OK] Docker started!"
            break
        fi
        echo "  Still waiting... $i/30"
    done
    if ! docker info &>/dev/null; then
        echo "  [ERROR] Docker did not start. Open Docker Desktop manually and try again."
        exit 1
    fi
fi
echo "  [OK] Docker is running."
echo ""

# Create docs folder
if [ ! -d "$DOCS_DIR" ]; then
    echo "  [INFO] Creating ~/pdfs folder for your documents..."
    mkdir -p "$DOCS_DIR"
    echo "  [OK] Created. Put your PDF and DOCX files in ~/pdfs"
else
    echo "  [OK] Documents folder ~/pdfs exists."
fi
echo ""

# Build image
echo "  [BUILD] Building Docker image (first time: 3-5 min, then instant)..."
echo ""
docker build -t docs-chat:latest "$SCRIPT_DIR"
echo ""
echo "  [OK] Image ready."
echo ""

# Remove old container
docker rm -f docs-chat 2>/dev/null || true

# Start container
echo "  [START] Starting container..."
echo ""
docker run -d \
  --name docs-chat \
  --restart unless-stopped \
  -p ${PORT}:5000 \
  -v "${DOCS_DIR}:/docs" \
  -v ollama_models:/root/.ollama \
  -e DOCS_FOLDER=/docs \
  -e DOCS_LABEL="${DOCS_DIR}" \
  -e OLLAMA_MODEL=${MODEL} \
  -e PLATFORM=mac \
  docs-chat:latest

echo "  [OK] Container is running."
echo ""
echo "  [INFO] AI model downloading in background (~700MB, first run only)."
echo "         Wait for the green dot in the app before asking questions."
echo ""
echo "  Opening browser at http://localhost:${PORT} ..."
echo ""

sleep 5
open "http://localhost:${PORT}"

echo "  Commands:"
echo "    docker stop docs-chat      - Stop"
echo "    docker start docs-chat     - Start again (instant)"
echo "    docker logs -f docs-chat   - View logs"
echo ""
echo "  Documents folder: ~/pdfs"
echo ""
