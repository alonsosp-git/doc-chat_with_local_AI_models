FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV OLLAMA_HOST=0.0.0.0
ENV OLLAMA_MODELS=/root/.ollama/models
ENV DOCS_FOLDER=/docs
ENV OLLAMA_MODEL=llama3.2:1b
ENV PLATFORM=windows

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip python3-dev curl wget ca-certificates gcc zstd \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL https://ollama.com/install.sh | sh

COPY requirements.txt /app/requirements.txt
RUN pip3 install --no-cache-dir -r /app/requirements.txt

COPY app.py /app/app.py
COPY templates/ /app/templates/
COPY scripts/start.sh /start.sh
RUN chmod +x /start.sh
RUN mkdir -p /docs

WORKDIR /app
EXPOSE 5000
ENTRYPOINT ["/start.sh"]
