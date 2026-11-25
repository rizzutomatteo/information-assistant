# L'assistente in un container: il sito con la chat, l'accesso e il canale voce. Va avviato con
# la rete dell'host (vedi docker-compose.yml): WebRTC usa porte UDP scelte al momento, che con la
# rete «bridge» di Docker non arrivano.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/modelli/hf \
    VOCE_PIPER_CARTELLA=/modelli/piper \
    VOCE_IMPRONTE_CARTELLA=/modelli/impronte \
    ASSISTENTE_HOST=0.0.0.0

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-deps .

# I modelli della voce (Whisper, le voci di Piper, le impronte della voce) entrano nell'immagine:
# il container parte senza rete
RUN python -c "from assistente.config import Impostazioni; \
from assistente.voce.servizi import carica_modelli; carica_modelli(Impostazioni.da_ambiente())"

# I documenti da leggere nel sito (/documenti)
COPY documenti ./documenti
ENV ASSISTENTE_DOCUMENTI=/app/documenti

# Utenti e polizze in /dati: con un volume di Docker la cartella ne prende proprietario e permessi,
# quindi l'archivio si crea da solo su qualsiasi macchina
ENV ASSISTENTE_UTENTI=/dati/utenti.sqlite

# Mai come root
RUN useradd --system --home /app assistente && mkdir /dati && chown -R assistente /modelli /dati
USER assistente

EXPOSE 8002
CMD ["assistente"]
