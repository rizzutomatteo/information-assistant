"""Client dell'API dell'assistente: la stessa che usa la web chat.

Il canale voce non ha un'intelligenza sua: manda il testo trascritto all'API, con il token
dell'utente se ha fatto il login, e riceve gli stati del grafo e la risposta come Server-Sent
Events. Il contratto (lo stesso della chat, più i campi «canale» e «lingua») è descritto nel
README:

    POST {url_api}/turno
    Authorization: Bearer <token>            (solo se l'utente ha fatto il login)
    {"sessione": "...", "messaggio": "...", "canale": "voce", "lingua": "it"}

    event: stato
    data: {"nodo": "retrieve", "testo": "Cerco nei documenti"}

    event: risposta
    data: {"testo": "...", "citazioni": ["..."], "intento": "prodotto",
           "confidenza": "alta", "operatore": false}
"""

import json
from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass, field

import httpx

from assistente.config import Lingua


@dataclass
class Evento:
    """Un evento dell'API: «stato», «risposta» oppure «errore»."""

    tipo: str
    dati: dict = field(default_factory=dict)


class ErroreAPI(Exception):
    """L'API non ha risposto o ha risposto con un errore."""


async def leggi_sse(righe: AsyncIterator[str] | Iterable[str]) -> AsyncIterator[Evento]:
    """Legge un flusso Server-Sent Events e restituisce un Evento per blocco.

    Un blocco è fatto di righe «event: …» e «data: …» (anche più di una) e finisce con una riga
    vuota. Le righe che iniziano con «:» sono commenti (spesso usati per tenere viva la
    connessione) e si saltano.
    """
    tipo, dati = "message", []

    async def tutte():
        if hasattr(righe, "__aiter__"):
            async for r in righe:
                yield r
        else:
            for r in righe:
                yield r

    async for riga in tutte():
        riga = riga.rstrip("\r\n")
        if not riga:
            if dati:
                yield _evento(tipo, dati)
            tipo, dati = "message", []
            continue
        if riga.startswith(":"):
            continue
        nome, _, valore = riga.partition(":")
        valore = valore.removeprefix(" ")
        if nome == "event":
            tipo = valore
        elif nome == "data":
            dati.append(valore)
    if dati:
        yield _evento(tipo, dati)


def evento_sse(tipo: str, dati: dict) -> str:
    """Un evento nel formato Server-Sent Events, il contrario di leggi_sse."""
    return f"event: {tipo}\ndata: {json.dumps(dati, ensure_ascii=False)}\n\n"


def _evento(tipo: str, dati: list[str]) -> Evento:
    testo = "\n".join(dati)
    try:
        contenuto = json.loads(testo)
    except json.JSONDecodeError:
        contenuto = {"testo": testo}
    if not isinstance(contenuto, dict):
        contenuto = {"valore": contenuto}
    return Evento(tipo, contenuto)


class ClientAssistente:
    """Manda un turno all'API e ne restituisce gli eventi, man mano che arrivano."""

    def __init__(
        self, url_api: str, timeout: float = 60.0, client: httpx.AsyncClient | None = None
    ):
        self._url = url_api.rstrip("/")
        # Connessione rapida, ma un turno può durare decine di secondi (generazione, verifica)
        self._client = client or httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=5.0))

    async def turno(
        self,
        messaggio: str,
        sessione: str,
        token: str | None = None,
        canale: str = "voce",
        lingua: Lingua = "it",
    ) -> AsyncIterator[Evento]:
        intestazioni = {"Accept": "text/event-stream"}
        if token:
            intestazioni["Authorization"] = f"Bearer {token}"
        corpo = {"sessione": sessione, "messaggio": messaggio, "canale": canale, "lingua": lingua}
        try:
            async with self._client.stream(
                "POST", f"{self._url}/turno", json=corpo, headers=intestazioni
            ) as risposta:
                if risposta.status_code >= 400:
                    await risposta.aread()
                    raise ErroreAPI(f"l'API ha risposto {risposta.status_code}")
                async for evento in leggi_sse(risposta.aiter_lines()):
                    yield evento
        except httpx.HTTPError as e:
            raise ErroreAPI(f"API non raggiungibile: {type(e).__name__}") from e

    async def chiudi(self):
        await self._client.aclose()
