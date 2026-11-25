"""I servizi di trascrizione fuori dal server: Whisper su Groq (groq.py) e Azure Speech (azure.py).

Hanno la stessa forma: trascrivi(audio, lingua, prompt) restituisce i pezzi della frase, ognuno con
la probabilità che sia silenzio. Se il servizio non risponde in tempo, risponde con un errore o ha
finito le richieste gratuite, solleva ErroreRemoto e la frase passa al servizio successivo, fino
al modello locale (servizi.py). L'audio esce dal server: si usano solo se c'è la chiave.
"""

import io
import time
import wave

import httpx

FREQUENZA = 16000
# Dopo un «troppe richieste» senza indicazioni, per quanto non si riprova
PAUSA_PREDEFINITA = 30.0


class ErroreRemoto(Exception):
    """Il servizio non ha trascritto la frase: la si passa al successivo."""


def wav(audio: bytes) -> bytes:
    """Il PCM della frase (16 bit, 16 kHz, mono) in un file WAV, in memoria."""
    file = io.BytesIO()
    with wave.open(file, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(FREQUENZA)
        w.writeframes(audio)
    return file.getvalue()


class ServizioRemoto:
    """Il client HTTP di un servizio, condiviso da tutte le chiamate.

    Dopo un «troppe richieste» per un po' non lo si chiama nemmeno: la frase va subito al
    successivo, invece di aspettare una risposta che sarebbe ancora un rifiuto.
    """

    nome = ""

    def __init__(self, client: httpx.AsyncClient):
        self._client = client
        self._ferma_fino = 0.0

    async def trascrivi(self, audio: bytes, lingua: str, prompt: str) -> list[tuple[str, float]]:
        raise NotImplementedError

    async def _invia(self, url: str, **richiesta) -> httpx.Response:
        if time.monotonic() < self._ferma_fino:
            raise ErroreRemoto("in pausa dopo troppe richieste")
        try:
            risposta = await self._client.post(url, **richiesta)
        except httpx.HTTPError as e:
            raise ErroreRemoto(type(e).__name__) from e
        if risposta.status_code == 429:
            self._ferma_fino = time.monotonic() + _secondi(risposta.headers.get("retry-after"))
            raise ErroreRemoto("troppe richieste")
        if risposta.is_error:
            raise ErroreRemoto(f"HTTP {risposta.status_code}")
        return risposta

    async def chiudi(self):
        await self._client.aclose()


def _secondi(valore: str | None) -> float:
    try:
        return max(1.0, float(valore))
    except (TypeError, ValueError):
        return PAUSA_PREDEFINITA
