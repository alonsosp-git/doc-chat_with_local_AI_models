# Docs Chat — v2.0

Ask questions about your PDF and DOCX files using a local AI.
**100% free. No API key. No internet after setup. Runs entirely on your machine.**

---

## What This App Does

Docs Chat is a local web application that lets you have a conversation with your documents.

- Drop any PDF or DOCX files into a folder on your computer
- Open a browser and ask questions in plain English
- The app finds the most relevant parts of your documents and uses a local AI model to generate an answer
- Everything runs inside Docker on your own machine — your documents never leave your PC

**Use cases:**
- Summarize long PDF reports
- Ask questions about contracts, manuals, or research papers
- Extract key dates, names, or figures from documents
- Analyze technical documents without sending them to a cloud service

---

## Supported Machines

| Machine | CPU | RAM | Notes |
|---|---|---|---|
| (Windows 11) | Intel i7· 4 cores / 8 threads | 24 GB | CPU-only inference |
| (macOS) | Apple · 8-core CPU + 10-core GPU | 16 GB | Metal GPU acceleration |

---

## Requirements

Only one thing needed: **Docker Desktop** (free)
- Windows: https://www.docker.com/products/docker-desktop/
- Mac: https://www.docker.com/products/docker-desktop/

---

## Setup — Windows PC

### File structure
Extract the Windows zip to `C:\doc-chat\` so it looks like this:

```
C:\doc-chat\
├── start-windows.bat       ← double-click to run everything
├── Dockerfile
├── app.py
├── requirements.txt
├── README.md
├── templates\
│   └── index.html
└── scripts\
    └── start.sh
```

### Steps

**1. Install Docker Desktop**
Download and install from https://www.docker.com/products/docker-desktop/

**2. Double-click `start-windows.bat`** (right-click → Run as Administrator)

The script will automatically:
- Check Docker is running (and start it if needed)
- Create `C:\pdfs\` folder for your documents
- Build the Docker image (3-5 minutes, first time only)
- Start the container
- Open your browser at http://localhost:5000

**3. Add your documents**
Copy your PDF and DOCX files to `C:\pdfs\`

**4. Click "Reload Documents" in the app sidebar**

**5. Start asking questions!**

### Starting/stopping after first setup
```cmd
docker start docs-chat     # Start (instant)
docker stop docs-chat      # Stop
docker logs -f docs-chat   # View logs
```

---

## Setup — Mac Mini Mx

### File structure
Extract the Mac zip to your home folder `~/doc-chat/` so it looks like this:

```
~/doc-chat/
├── start-mac.sh            ← run this once to set up everything
├── Dockerfile
├── app.py
├── requirements.txt
├── README.md
├── templates/
│   └── index.html
└── scripts/
    └── start.sh
```

### Steps

**1. Install Docker Desktop for Mac**
Download from https://www.docker.com/products/docker-desktop/ (choose Apple Silicon)

**2. Open Terminal, navigate to the folder and run:**
```bash
cd ~/doc-chat
chmod +x start-mac.sh
./start-mac.sh
```

The script will automatically:
- Check Docker is running (and start it if needed)
- Create `~/pdfs/` folder for your documents
- Build the Docker image (3-5 minutes, first time only)
- Start the container
- Open your browser at http://localhost:5000

**3. Add your documents**
Copy your PDF and DOCX files to `~/pdfs/`

**4. Click "Reload Documents" in the app sidebar**

**5. Start asking questions!**

### Starting/stopping after first setup
```bash
docker start docs-chat     # Start (instant)
docker stop docs-chat      # Stop
docker logs -f docs-chat   # View logs
```

---

## AI Models

The app comes with a built-in **Model Manager** (click "Manage" in the sidebar).

### Default model
`llama3.2:1b` — fastest option, recommended for Windows PC

### Recommended models per machine

| Model | Size | Speed | Best for |
|---|---|---|---|
| `llama3.2:1b` | 0.7 GB | ⚡ Fastest | Windows PC — quick Q&A |
| `llama3.2:3b` | 1.9 GB | ⚡ Fast | Both — best balance |
| `phi3:mini` | 2.3 GB | ⚡ Fast | Both — structured extraction |
| `gemma2:2b` | 1.6 GB | ⚡ Fast | Both — summarization |
| `mistral:7b` | 4.1 GB | ◑ Medium | Mac only — long documents |
| `moondream:1.8b` | 1.1 GB | ⚡ Fast | Both — image understanding |
| `llava:7b` | 4.7 GB | ◑ Medium | Mac only — images in PDFs |

### Downloading a new model
1. Click **Manage** in the sidebar
2. Go to **Browse & Download**
3. Filter by machine (Windows PC or Mac Mini Mx) and purpose
4. Click **Download via Ollama**
5. Wait for the progress bar to complete
6. Click **Use Now**

---

## Performance Notes

### Windows PC
- Uses CPU-only inference (no GPU)
- `llama3.2:1b` responds in 20-40 seconds
- `llama3.2:3b` responds in 40-90 seconds
- Models larger than 4B parameters will be very slow
- The app pre-loads the model into RAM on startup for faster first queries

### Mac Mini Mx
- Uses Apple Metal GPU acceleration via Ollama
- `llama3.2:1b` responds in 2-5 seconds
- `llama3.2:3b` responds in 5-10 seconds
- `mistral:7b` responds in 10-20 seconds
- Significantly faster than Windows CPU mode

---

## How It Works (Technical)

1. **Document indexing** — when you click Reload, the app reads all PDF/DOCX files in parallel, splits them into overlapping text chunks, and builds a TF-IDF search index in memory
2. **Search** — when you ask a question, TF-IDF cosine similarity finds the 4 most relevant chunks
3. **Generation** — the relevant chunks are sent to the local Ollama AI model as context, and the answer streams back token by token
4. **Nothing leaves your machine** — the AI model runs inside Docker, documents stay in your local folder, no network calls are made after initial setup

---

## Folder Structure Explained

```
doc-chat/
├── Dockerfile          ← defines the Docker image (Ubuntu + Ollama + Python)
├── app.py              ← Flask web server + document indexing + AI chat logic
├── requirements.txt    ← Python packages installed inside Docker
├── README.md           ← this file
├── start-windows.bat   ← Windows automated launcher
├── start-mac.sh        ← Mac automated launcher
├── templates/
│   └── index.html      ← the entire web UI (chat + model manager)
└── scripts/
    └── start.sh        ← startup script that runs inside the container
```

---

## Troubleshooting

**Green dot not appearing / Ollama not ready**
Run `docker logs -f docs-chat` — if you see the model is still downloading, just wait.

**"No PDF or DOCX files found" after clicking Reload**
Make sure your files are in `C:\pdfs` (Windows) or `~/pdfs` (Mac) and click Reload again.

**Answers get cut off or truncated**
The model hit its token limit. Click the ■ Stop button and rephrase as a more specific question, or switch to a model with higher quality (e.g. `llama3.2:3b` instead of `1b`).

**Very slow responses on Windows**
Switch to `llama3.2:1b` in the Model Manager — it is the fastest model for CPU-only machines.

**Port 5000 already in use**
Change `5000:5000` to `5001:5000` in the docker run command, then open http://localhost:5001

**To completely reset and start fresh**
```cmd
docker rm -f docs-chat
docker rmi docs-chat:latest
docker volume rm ollama_models
```
Then run the launcher script again.

---

## Version History

| Version | Changes |
|---|---|
| v2.0 | Model Manager with purpose tabs (Chat, Docs, Code, Multilingual, Vision). Per-machine inference tuning (Windows CPU vs Mac M2 Metal). Pre-warm model on startup. Fix answer truncation. Filter bar high-contrast active states. Mac launcher script. |
| v1.x | Basic chat, Ollama integration, document indexing, stop button, progress bar |
| v1.0 | Initial release |


## Note:
Large language models range from lightweight versions under 1 GB to massive ones exceeding 400 GB, but bigger isn’t always better accuracy depends not only on size but also on training quality, architecture, and hardware capacity. Smaller models (around 7B–13B parameters, typically 7–14 GB) often strike the best balance between performance and usability, while ultra-large models (70B–400B parameters, 140–400+ GB) deliver stronger reasoning but require powerful infrastructure.

## Reference:
https://medium.com/@VenuThomas/ai-model-basics-understanding-size-hardware-and-setup-8ad12bfaed79
