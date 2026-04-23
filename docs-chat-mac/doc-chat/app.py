import os
import gc
import json
import requests
import threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import Flask, render_template, request, jsonify, stream_with_context, Response

# ── Config ────────────────────────────────────────────────────────────────────
DOCS_FOLDER  = os.environ.get("DOCS_FOLDER",  "/docs")
OLLAMA_URL   = os.environ.get("OLLAMA_URL",   "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.2:1b")
DOCS_LABEL   = os.environ.get("DOCS_LABEL",   "C:\\pdfs")
PLATFORM     = os.environ.get("PLATFORM",     "windows")  # "windows" or "mac"

# Download progress tracking
download_progress = {}

# ── Document readers ──────────────────────────────────────────────────────────
def read_pdf(path: str) -> str:
    import pdfplumber
    pages = []
    try:
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                t = page.extract_text()
                if t and t.strip():
                    pages.append(t.strip())
    except Exception as e:
        print(f"  [PDF error] {path}: {e}")
    return "\n\n".join(pages)

def read_docx(path: str) -> str:
    from docx import Document
    try:
        doc = Document(path)
        return "\n\n".join(p.text.strip() for p in doc.paragraphs if p.text.strip())
    except Exception as e:
        print(f"  [DOCX error] {path}: {e}")
        return ""

def read_file(f: Path):
    if f.suffix.lower() == ".pdf":
        return f.name, read_pdf(str(f))
    return f.name, read_docx(str(f))

# ── Chunking ──────────────────────────────────────────────────────────────────
def chunk_text(text: str, chunk_size: int = 400, overlap: int = 50):
    words = text.split()
    if not words:
        return []
    chunks, i = [], 0
    while i < len(words):
        chunk = " ".join(words[i : i + chunk_size])
        if chunk.strip():
            chunks.append(chunk)
        i += chunk_size - overlap
    return chunks

# ── Index ─────────────────────────────────────────────────────────────────────
def build_index(folder_path: str):
    folder = Path(folder_path)
    if not folder.exists():
        print(f"  [WARN] Folder not found: {folder_path}")
        return []
    eligible = sorted([f for f in folder.iterdir()
                       if f.suffix.lower() in (".pdf", ".docx", ".doc")])
    print(f"  Found {len(eligible)} file(s) — reading in parallel...")
    docs = []
    with ThreadPoolExecutor(max_workers=min(8, len(eligible) or 1)) as ex:
        futures = {ex.submit(read_file, f): f for f in eligible}
        for future in as_completed(futures):
            fname, text = future.result()
            if not text.strip():
                print(f"  [WARN] No text from {fname}")
                continue
            chunks = chunk_text(text)
            print(f"  -> {fname}: {len(chunks)} chunks")
            for chunk in chunks:
                docs.append({"file": fname, "content": chunk})
    print(f"  Total: {len(docs)} chunks")
    return docs

# ── TF-IDF search ─────────────────────────────────────────────────────────────
def search_chunks(query: str, chunks: list, top_k: int = 4):
    if not chunks:
        return []
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity
    import numpy as np
    texts  = [c["content"] for c in chunks]
    vec    = TfidfVectorizer(stop_words="english", max_features=8000)
    mat    = vec.fit_transform(texts + [query])
    scores = cosine_similarity(mat[-1], mat[:-1]).flatten()
    top    = scores.argsort()[::-1][:top_k]
    return [chunks[i] for i in top if scores[i] > 0]

# ── Ollama helpers ────────────────────────────────────────────────────────────
def ollama_is_running():
    try:
        return requests.get(f"{OLLAMA_URL}/api/tags", timeout=5).status_code == 200
    except Exception:
        return False

def ollama_list_models():
    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=3)
        return r.json().get("models", [])
    except Exception:
        return []

def ollama_model_names():
    return [m["name"] for m in ollama_list_models()]

def prewarm_model(model_name: str):
    """Load model weights into RAM with a 1-token request."""
    try:
        print(f"  Pre-warming model: {model_name} ...")
        requests.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": model_name,
                "messages": [{"role": "user", "content": "hi"}],
                "stream": False,
                "keep_alive": -1,
                "options": {"num_predict": 1, "num_ctx": 256}
            },
            timeout=180,
        )
        print(f"  Model warm and ready.")
    except Exception as e:
        print(f"  Pre-warm failed (non-fatal): {e}")

def get_inference_options():
    """
    Return Ollama inference options tuned per platform.
    Windows (i7 CPU-only): smaller context, use all CPU threads.
    Mac (M2 Metal GPU):    larger context allowed, GPU handles it.
    """
    if PLATFORM == "mac":
        return {
            "num_predict": 800,    # M2 is fast enough for longer answers
            "temperature": 0.1,
            "num_ctx": 3072,       # M2 can handle larger context
            "top_k": 20,
            "top_p": 0.9,
            "repeat_penalty": 1.1,
        }
    else:
        # Windows / Linux CPU
        return {
            "num_predict": 600,    # increased from 300 — fixes truncation
            "temperature": 0.1,
            "num_ctx": 2048,       # increased from 1024 — room for full answers
            "num_thread": 8,       # all i7 logical threads
            "top_k": 10,
            "top_p": 0.9,
            "repeat_penalty": 1.1,
        }

# ── Background model pull ─────────────────────────────────────────────────────
def _pull_model_bg(model_name: str):
    global download_progress
    download_progress[model_name] = {"status": "downloading", "pct": 0, "msg": "Starting download..."}
    try:
        resp = requests.post(
            f"{OLLAMA_URL}/api/pull",
            json={"name": model_name, "stream": True},
            stream=True, timeout=7200,
        )
        last_pct = 0
        for line in resp.iter_lines():
            if not line:
                continue
            try:
                payload   = json.loads(line)
                status    = payload.get("status", "")
                total     = payload.get("total", 0)
                completed = payload.get("completed", 0)
                if total > 0:
                    last_pct = int((completed / total) * 100)
                if status == "success":
                    download_progress[model_name] = {"status": "done", "pct": 100, "msg": "Download complete!"}
                    return
                download_progress[model_name] = {
                    "status": "downloading", "pct": last_pct,
                    "msg": status if status else f"Downloading... {last_pct}%",
                }
            except Exception:
                continue
        download_progress[model_name] = {"status": "done", "pct": 100, "msg": "Download complete!"}
    except Exception as e:
        download_progress[model_name] = {"status": "error", "pct": 0, "msg": str(e)}

# ── Flask ─────────────────────────────────────────────────────────────────────
app   = Flask(__name__)
INDEX = []

@app.route("/")
def index():
    return render_template("index.html",
                           docs_folder=DOCS_FOLDER,
                           docs_label=DOCS_LABEL,
                           ollama_model=OLLAMA_MODEL,
                           platform=PLATFORM)

@app.route("/api/status")
def status():
    running = ollama_is_running()
    models  = ollama_list_models() if running else []
    files   = sorted({c["file"] for c in INDEX})
    return jsonify({
        "ollama_running": running,
        "models": [m["name"] for m in models],
        "current_model": OLLAMA_MODEL,
        "indexed_files": files,
        "chunks": len(INDEX),
        "docs_label": DOCS_LABEL,
        "docs_folder": DOCS_FOLDER,
        "platform": PLATFORM,
    })

@app.route("/api/reload", methods=["POST"])
def reload_index():
    global INDEX
    data   = request.json or {}
    folder = data.get("folder", DOCS_FOLDER)
    INDEX  = build_index(folder)
    gc.collect()
    files  = sorted({c["file"] for c in INDEX})
    return jsonify({"status": "ok", "files": files, "chunks": len(INDEX), "folder": folder})

@app.route("/api/models")
def list_models():
    models = ollama_list_models()
    result = []
    for m in models:
        size_gb = round(m.get("size", 0) / 1e9, 1)
        result.append({"name": m["name"], "size_gb": size_gb, "modified": m.get("modified_at", "")})
    return jsonify({"models": result})

@app.route("/api/models/pull", methods=["POST"])
def pull_model():
    model_name = (request.json or {}).get("model", "")
    if not model_name:
        return jsonify({"error": "No model name provided"}), 400
    if model_name in download_progress and download_progress[model_name]["status"] == "downloading":
        return jsonify({"status": "already_downloading"})
    t = threading.Thread(target=_pull_model_bg, args=(model_name,), daemon=True)
    t.start()
    return jsonify({"status": "started", "model": model_name})

@app.route("/api/models/progress")
def model_progress():
    model_name = request.args.get("model", "")
    prog = download_progress.get(model_name, {"status": "idle", "pct": 0, "msg": ""})
    return jsonify(prog)

@app.route("/api/models/delete", methods=["POST"])
def delete_model():
    global OLLAMA_MODEL
    model_name = (request.json or {}).get("model", "")
    if not model_name:
        return jsonify({"error": "No model name provided"}), 400
    try:
        r = requests.delete(f"{OLLAMA_URL}/api/delete", json={"name": model_name}, timeout=30)
        if r.status_code in (200, 204):
            remaining = ollama_model_names()
            if OLLAMA_MODEL == model_name and remaining:
                OLLAMA_MODEL = remaining[0]
            return jsonify({"status": "deleted", "remaining": remaining})
        return jsonify({"error": f"Ollama returned {r.status_code}"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def _parse_param_size(s):
    """Parse '8B', '7b', '13B' etc into a float number of billions."""
    if not s:
        return 0.0
    import re
    m = re.search(r"([\d.]+)\s*[Bb]", str(s))
    if m:
        return float(m.group(1))
    return 0.0

def _classify_model(name: str, param_size_str: str, size_bytes: int):
    """
    Return a full classification dict from model name + param size + byte size.
    Uses param count as the primary signal; falls back to name heuristics.
    """
    import re
    n = name.lower()

    # ── param count ──────────────────────────────────────────────────────────
    params = _parse_param_size(param_size_str)

    # If param_size_str is empty, try to guess from the model name tag
    # e.g. "llama3.1:8b" → 8, "phi3:mini" → 3.8 (known), "mistral:7b" → 7
    if params == 0:
        m2 = re.search(r":(\d+\.?\d*)b", n)
        if m2:
            params = float(m2.group(1))

    # ── size string ───────────────────────────────────────────────────────────
    if size_bytes and size_bytes > 0:
        size_str = f"{round(size_bytes / 1e9, 1)} GB"
    elif params > 0:
        # Estimate: ~0.6 GB per B at 4-bit quantisation
        est = round(params * 0.6, 1)
        size_str = f"~{est} GB (estimated)"
    else:
        size_str = "See ollama.com"

    # ── speed / tier / accuracy ──────────────────────────────────────────────
    if params <= 0:
        speed = "Unknown"; tier = "balanced"; tier_label = "Unknown"
        accuracy = "Unknown"; ram = "Unknown"
    elif params <= 2:
        speed = "⚡ Fast";   tier = "fast";     tier_label = "Speed Priority"
        accuracy = "Good";           ram = f"~{max(4, int(params*1.5))} GB"
    elif params <= 4:
        speed = "⚡ Fast";   tier = "fast";     tier_label = "Speed Priority"
        accuracy = "Good–Very Good"; ram = f"~{max(6, int(params*1.5))} GB"
    elif params <= 8:
        speed = "◑ Medium"; tier = "balanced"; tier_label = "Balanced"
        accuracy = "Excellent";      ram = f"~{max(8, int(params*1.5))} GB"
    elif params <= 14:
        speed = "◔ Slow";   tier = "accurate"; tier_label = "Accuracy Priority"
        accuracy = "Near GPT-3.5";   ram = f"~{max(12, int(params*1.2))} GB"
    elif params <= 34:
        speed = "◔ Slow";   tier = "accurate"; tier_label = "Accuracy Priority"
        accuracy = "Near GPT-4";     ram = f"~{max(20, int(params*1.0))} GB"
    else:
        speed = "🐢 Very Slow"; tier = "accurate"; tier_label = "Accuracy Priority"
        accuracy = "GPT-4 class";    ram = f"~{max(40, int(params*0.8))} GB"

    # ── machine compatibility ─────────────────────────────────────────────────
    if params <= 0 or params <= 8:
        machine = "both"; machine_label = "Windows & Mac"
    elif params <= 14:
        machine = "mac";  machine_label = "Mac Mini M2 only (needs 12+ GB RAM)"
    else:
        machine = "none"; machine_label = "Needs workstation GPU (>20 GB VRAM)"

    # ── purpose detection ─────────────────────────────────────────────────────
    if re.search(r"code|coder|starcoder|wizard-coder|deepseek-coder|commit|programming", n):
        purpose = "Coding"
    elif re.search(r"llava|vision|bakllava|moondream|cogvlm|minicpm-v|qwen-vl|internvl", n):
        purpose = "Images & Vision"
    elif re.search(r"aya|multilingual|qwen|bloom|xglm|mamba|falcon", n):
        purpose = "Multilingual"
    elif re.search(r"embed|nomic|all-mini|e5-|bge-", n):
        purpose = "Embeddings"
    elif re.search(r"math|numeric|wizard-math", n):
        purpose = "Math & Reasoning"
    else:
        purpose = "Chat & Q&A"

    return {
        "size":        size_str,
        "param_size":  param_size_str or (f"{params}B" if params else ""),
        "params":      params,
        "speed":       speed,
        "tier":        tier,
        "tier_label":  tier_label,
        "accuracy":    accuracy,
        "ram":         ram,
        "machine":     machine,
        "machine_label": machine_label,
        "purpose":     purpose,
    }

@app.route("/api/models/search")
def search_models():
    """
    Search the Ollama registry using their JSON API.
    Returns structured results with full classification.
    """
    query = request.args.get("q", "").strip()
    if not query:
        return jsonify({"error": "No query provided", "results": []}), 400

    results = []
    installed_names = set(ollama_model_names())

    try:
        # ── 1. Use Ollama's JSON search API ───────────────────────────────────
        api_url = f"https://ollama.com/api/search?q={requests.utils.quote(query)}&limit=16"
        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; DocsChatApp/2.0)",
            "Accept": "application/json",
        }
        r = requests.get(api_url, headers=headers, timeout=12)
        models_raw = []

        if r.status_code == 200:
            try:
                data = r.json()
                # API may return {"models": [...]} or a direct list
                if isinstance(data, list):
                    models_raw = data
                elif isinstance(data, dict):
                    models_raw = data.get("models", data.get("results", []))
            except Exception:
                pass

        # ── 2. Fallback: try the tags/library endpoint ────────────────────────
        if not models_raw:
            lib_url = f"https://ollama.com/api/tags?q={requests.utils.quote(query)}&limit=16"
            r2 = requests.get(lib_url, headers=headers, timeout=12)
            if r2.status_code == 200:
                try:
                    d2 = r2.json()
                    if isinstance(d2, list):
                        models_raw = d2
                    elif isinstance(d2, dict):
                        models_raw = d2.get("models", d2.get("tags", []))
                except Exception:
                    pass

        # ── 3. Fallback: scrape the search page for model names ───────────────
        if not models_raw:
            import re as _re
            search_url = f"https://ollama.com/search?q={requests.utils.quote(query)}"
            r3 = requests.get(search_url, headers={
                "User-Agent": "Mozilla/5.0",
                "Accept": "text/html",
            }, timeout=12)
            # Extract model slugs from href="/modelname" patterns
            names_found = _re.findall(r'href="/([a-zA-Z0-9_-]+)"', r3.text)
            # Deduplicate and filter noise
            seen = set()
            for nm in names_found:
                if nm in seen or nm in {"search","library","blog","download","models","docs","pricing"}:
                    continue
                seen.add(nm)
                if query.lower() in nm.lower():
                    models_raw.append({"name": nm})

        print(f"  [Search] '{query}' → {len(models_raw)} raw results")

        # ── 4. Build structured results ───────────────────────────────────────
        for raw in models_raw[:14]:
            # Normalise field names across different API response shapes
            name        = (raw.get("name") or raw.get("model") or raw.get("namespace","") + "/" + raw.get("repo","")).strip("/")
            description = raw.get("description") or raw.get("desc") or ""
            pulls       = raw.get("pulls") or raw.get("pull_count") or ""
            tags_list   = raw.get("tags") or []

            # Size / param info from API response
            size_bytes  = int(raw.get("size") or 0)
            param_size  = raw.get("parameter_size") or raw.get("params") or ""

            # Some APIs nest details
            details = raw.get("details") or {}
            if not param_size:
                param_size = details.get("parameter_size","")
            if not size_bytes:
                size_bytes = int(details.get("size") or 0)

            if not name or len(name) < 2:
                continue

            cls = _classify_model(name, param_size, size_bytes)

            # Format pulls nicely
            pulls_str = ""
            if pulls:
                try:
                    p = int(str(pulls).replace(",",""))
                    if p >= 1_000_000:
                        pulls_str = f"{p//1_000_000}M pulls"
                    elif p >= 1_000:
                        pulls_str = f"{p//1_000}K pulls"
                    else:
                        pulls_str = f"{p} pulls"
                except Exception:
                    pulls_str = str(pulls)

            is_installed = (name in installed_names or
                            f"{name}:latest" in installed_names)

            results.append({
                "name":        name,
                "desc":        description or f"Ollama model — see ollama.com/{name}",
                "pulls":       pulls_str,
                "tags":        tags_list[:6] if isinstance(tags_list, list) else [],
                "installed":   is_installed,
                "url":         f"https://ollama.com/{name}",
                **cls,
            })

    except Exception as e:
        print(f"  [Search error] {e}")
        import traceback; traceback.print_exc()
        return jsonify({"error": str(e), "results": []}), 500

    return jsonify({"results": results, "query": query})

@app.route("/api/sysinfo")
def sysinfo():
    """
    Return host machine specs. Uses ONLY /proc filesystem — no subprocess calls
    that could hang inside Docker.
    """
    import re

    info = {
        "platform": PLATFORM,
        "cpu_model": "Unknown",
        "cpu_cores_physical": 0,
        "cpu_cores_logical": 0,
        "cpu_freq_mhz": 0,
        "ram_total_gb": 0,
        "ram_available_gb": 0,
        "gpu_name": "None detected",
        "gpu_vram_gb": 0,
        "has_gpu": False,
        "recommendation": "",
    }

    # ── CPU — read /proc/cpuinfo only (never hangs) ───────────────────────────
    try:
        with open("/proc/cpuinfo") as f:
            cpuinfo = f.read()
        models = re.findall(r"model name\s*:\s*(.+)", cpuinfo)
        if models:
            info["cpu_model"] = models[0].strip()
        logical = cpuinfo.count("processor\t:")
        info["cpu_cores_logical"] = logical
        core_ids = set(re.findall(r"core id\s*:\s*(\d+)", cpuinfo))
        info["cpu_cores_physical"] = len(core_ids) if core_ids else max(1, logical // 2)
        # CPU MHz from /proc/cpuinfo directly
        freqs = re.findall(r"cpu MHz\s*:\s*([\d.]+)", cpuinfo)
        if freqs:
            info["cpu_freq_mhz"] = round(float(freqs[0]))
    except Exception:
        pass

    # ── RAM — read /proc/meminfo only (never hangs) ───────────────────────────
    try:
        with open("/proc/meminfo") as f:
            meminfo = f.read()
        total = re.search(r"MemTotal:\s+(\d+)", meminfo)
        avail = re.search(r"MemAvailable:\s+(\d+)", meminfo)
        if total:
            info["ram_total_gb"] = round(int(total.group(1)) / 1024 / 1024, 1)
        if avail:
            info["ram_available_gb"] = round(int(avail.group(1)) / 1024 / 1024, 1)
    except Exception:
        pass

    # ── GPU — read /proc only, NO nvidia-smi (can hang) ──────────────────────
    # Try reading NVIDIA info from /proc/driver/nvidia
    try:
        with open("/proc/driver/nvidia/version") as f:
            info["gpu_name"] = "NVIDIA GPU"
            info["has_gpu"]  = True
    except Exception:
        pass

    # Apple Silicon — always has Metal GPU with unified memory
    if PLATFORM == "mac":
        info["gpu_name"]    = f"Apple M2 GPU — Metal (unified {info['ram_total_gb']} GB)"
        info["gpu_vram_gb"] = info["ram_total_gb"]
        info["has_gpu"]     = True

    # ── Recommendation ───────────────────────────────────────────────────────
    ram     = info["ram_total_gb"]
    has_gpu = info["has_gpu"]

    if PLATFORM == "mac":
        if ram >= 16:
            rec = "Excellent — M2 Metal GPU + 16 GB unified memory. Runs mistral:7b and llama3.1:8b in 10-20 sec. Best models: mistral:7b, llama3.1:8b, phi3:mini."
        elif ram >= 8:
            rec = "Good — M2 Metal GPU + 8 GB. Best with 3B-7B models. Recommended: llama3.2:3b, phi3:mini."
        else:
            rec = "Limited RAM — stick to 1B-3B models: llama3.2:1b, llama3.2:3b."
    elif has_gpu:
        rec = f"GPU detected — can run 7B models faster. Recommended: mistral:7b or llama3.1:8b."
    elif ram >= 24:
        rec = f"CPU-only, {ram} GB RAM — can run 7B models (2-4 min). Best balance: mistral:7b. For speed: llama3.2:1b."
    elif ram >= 16:
        rec = f"CPU-only, {ram} GB RAM — recommended: llama3.2:3b or phi3:mini."
    elif ram >= 8:
        rec = f"CPU-only, {ram} GB RAM — stick to small models: llama3.2:1b."
    else:
        rec = f"Low RAM ({ram} GB) — use llama3.2:1b only."

    info["recommendation"] = rec
    return jsonify(info)


@app.route("/api/models/prewarm", methods=["POST"])
def api_prewarm():
    global OLLAMA_MODEL
    model_name  = (request.json or {}).get("model", OLLAMA_MODEL)
    OLLAMA_MODEL = model_name
    t = threading.Thread(target=prewarm_model, args=(model_name,), daemon=True)
    t.start()
    return jsonify({"status": "warming", "model": model_name})

@app.route("/api/chat", methods=["POST"])
def chat():
    global OLLAMA_MODEL
    data             = request.json
    messages_history = data.get("messages", [])
    model_override   = data.get("model")
    if model_override:
        OLLAMA_MODEL = model_override

    question = messages_history[-1]["content"] if messages_history else ""
    gc.collect()
    relevant = search_chunks(question, INDEX, top_k=4)

    if relevant:
        context_block = "\n\n---\n\n".join(
            f"[Source: {r['file']}]\n{r['content']}" for r in relevant)
        system_msg = (
            "You are a helpful document assistant. "
            "Answer the user's question using the document excerpts below. "
            "Write complete, full answers — do NOT cut off or stop mid-list. "
            "If listing points, always finish the complete list before stopping. "
            "State which file your answer comes from.\n\n"
            "DOCUMENT EXCERPTS:\n\n" + context_block
        )
    else:
        system_msg = (
            "You are a document assistant. No relevant content found. "
            "Tell the user to add documents and click Reload."
        )

    full_messages = [{"role": "system", "content": system_msg}] + [
        {"role": m["role"], "content": m["content"]} for m in messages_history
    ]

    options = get_inference_options()

    def generate():
        try:
            resp = requests.post(
                f"{OLLAMA_URL}/api/chat",
                json={
                    "model": OLLAMA_MODEL,
                    "messages": full_messages,
                    "stream": True,
                    "keep_alive": -1,
                    "options": options,
                },
                stream=True, timeout=300,
            )
            for line in resp.iter_lines():
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                    token   = payload.get("message", {}).get("content", "")
                    if token:
                        yield f"data: {json.dumps({'text': token})}\n\n"
                    if payload.get("done"):
                        break
                except Exception:
                    continue
        except requests.exceptions.ReadTimeout:
            yield f"data: {json.dumps({'text': 'The model timed out. Try llama3.2:1b for faster responses.'})}\n\n"
        except requests.exceptions.ConnectionError:
            yield f"data: {json.dumps({'text': 'Cannot reach Ollama. Please wait and try again.'})}\n\n"
        except GeneratorExit:
            return
        gc.collect()
        sources = list({r["file"] for r in relevant})
        yield f"data: {json.dumps({'done': True, 'sources': sources})}\n\n"

    return Response(stream_with_context(generate()), mimetype="text/event-stream")

if __name__ == "__main__":
    print(f"\n  Platform    : {PLATFORM.upper()}")
    print(f"  Docs folder : {DOCS_FOLDER} ({DOCS_LABEL})")
    print(f"  Model       : {OLLAMA_MODEL}")
    print(f"  Ollama URL  : {OLLAMA_URL}")
    print("\n  Building document index...")
    INDEX = build_index(DOCS_FOLDER)
    files = sorted({c["file"] for c in INDEX})
    print(f"  Indexed {len(files)} file(s) — {len(INDEX)} chunks")

    # Pre-warm in background — NEVER block Flask startup
    def _startup_prewarm():
        print("  Waiting for Ollama to be ready before pre-warming...")
        for _ in range(60):          # wait up to 60 seconds
            if ollama_is_running():
                prewarm_model(OLLAMA_MODEL)
                return
            import time; time.sleep(1)
        print("  Ollama did not become ready — skipping pre-warm.")

    t = threading.Thread(target=_startup_prewarm, daemon=True)
    t.start()

    print("\n  Open http://localhost:5000\n")
    app.run(host="0.0.0.0", debug=False, port=5000, threaded=True)
