"""Le pagine del sito dimostrativo e la chat scritta.

GET  /            la home page della compagnia (fittizia) con l'assistente, scritto e a voce,
                  nella lingua scelta (pagina.py); ?lingua=en la cambia
GET  /documenti   l'elenco dei documenti, per area; /documenti/<area>/<nome> un documento
                  (documenti.py)
GET  /faq         le domande frequenti, per categoria; /faq/<id> una domanda (faq.py)
GET  /a           la pagina degli utenti di prova: caricarli, modificarli, eliminarli
                  (accesso/amministrazione.py)
GET  /statico/…   CSS, JavaScript e caratteri della pagina
POST /api/chat    una domanda scritta → la domanda e gli eventi dell'API dell'assistente
                  (Server-Sent Events), con i messaggi già pronti per la pagina
"""

import asyncio
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger
from pydantic import BaseModel, Field

from assistente.accesso.amministrazione import ESEMPIO, Amministrazione
from assistente.accesso.sessioni import Sessioni
from assistente.config import LINGUE, Lingua
from assistente.rag.client import ClientAssistente, ErroreAPI, evento_sse
from assistente.sito.documenti import Archivio
from assistente.sito.faq import RaccoltaFaq
from assistente.sito.pagina import (
    pagina,
    pagina_amministrazione,
    pagina_documenti,
    pagina_documento,
    pagina_domanda,
    pagina_faq,
    per_la_pagina,
    testo,
)

STATICO = Path(__file__).parent / "statico"
# I file della pagina cambiano a ogni aggiornamento: il browser li ricontrolla sempre (con l'ETag:
# se non sono cambiati la risposta è un 304 vuoto): niente versioni vecchie e nuove insieme
RICONTROLLA = {"Cache-Control": "no-cache"}
# La pagina cambia con la lingua e con l'accesso, e può avere i dati di chi l'ha aperta: la tiene
# solo il suo browser, e la richiede ogni volta
SOLO_PER_TE = {"Cache-Control": "private, no-cache"}
COOKIE_LINGUA = "lingua"


class FileStatici(StaticFiles):
    """I file della pagina (CSS, JavaScript, caratteri), da ricontrollare a ogni visita."""

    async def get_response(self, path: str, scope):
        risposta = await super().get_response(path, scope)
        risposta.headers.update(RICONTROLLA)
        return risposta


class Domanda(BaseModel):
    """Un messaggio scritto nella chat della pagina."""

    messaggio: str = Field(min_length=1, max_length=1000)
    sessione: str = Field(default="", max_length=100)
    # La lingua scelta nella pagina: l'API risponde in questa
    lingua: Lingua = "it"


def lingua_scelta(richiesta: Request) -> Lingua:
    scelta = richiesta.cookies.get(COOKIE_LINGUA)
    return scelta if scelta in LINGUE else "it"


def cambia_lingua(lingua: str, indietro: str) -> RedirectResponse:
    """Una bandiera: la lingua si ricorda nel cookie, e si torna all'indirizzo senza ?lingua."""
    risposta = RedirectResponse(indietro, status_code=303)
    if lingua in LINGUE:
        risposta.set_cookie(COOKIE_LINGUA, lingua, max_age=365 * 86400, httponly=True, secure=True)
    return risposta


def router_sito(
    sessioni: Sessioni,
    archivio: Archivio,
    raccolta: RaccoltaFaq,
    amministrazione: Amministrazione,
    client: ClientAssistente,
    google: str,
    registra: bool,
) -> APIRouter:
    """google: il client ID per «Accedi con Google» (vuoto: niente Google); registra: se la voce
    delle chiamate si registra per le prove (la pagina lo dice)."""
    router = APIRouter()
    anagrafe = sessioni.anagrafe

    @router.get("/", include_in_schema=False)
    async def home(richiesta: Request, lingua: str | None = None):
        if lingua is not None:
            return cambia_lingua(lingua, "./")
        html = pagina(
            lingua_scelta(richiesta),
            await sessioni.utente(sessioni.token(richiesta)),
            google,
            registra=registra,
        )
        return HTMLResponse(html, headers=SOLO_PER_TE)

    @router.get("/a", include_in_schema=False)
    async def pagina_a(richiesta: Request, lingua: str | None = None):
        if not amministrazione.attiva:
            raise HTTPException(404)
        if lingua is not None:
            return cambia_lingua(lingua, "a")
        entrato = amministrazione.entrato(richiesta)
        html = pagina_amministrazione(
            lingua_scelta(richiesta),
            entrato,
            await anagrafe.elenco() if entrato else [],
            ESEMPIO.read_text(encoding="utf-8"),
        )
        return HTMLResponse(html, headers=SOLO_PER_TE)

    @router.get("/documenti", include_in_schema=False)
    async def documenti(richiesta: Request, lingua: str | None = None):
        if lingua is not None:
            return cambia_lingua(lingua, "documenti")
        html = pagina_documenti(lingua_scelta(richiesta), archivio)
        return HTMLResponse(html, headers=SOLO_PER_TE)

    @router.get("/documenti/{area}/{nome}", include_in_schema=False)
    async def documento(richiesta: Request, area: str, nome: str, lingua: str | None = None):
        trovato = archivio.trova(area, nome)
        if trovato is None:
            raise HTTPException(404, "Documento non trovato")
        if lingua is not None:
            # Relativo: dalla pagina del documento torna a sé stessa
            return cambia_lingua(lingua, nome)
        # Il primo HTML di un documento lungo richiede qualche decimo di secondo: fuori dal ciclo
        # degli eventi, che intanto porta avanti l'audio delle chiamate
        contenuto = await asyncio.to_thread(archivio.html, trovato)
        html = pagina_documento(lingua_scelta(richiesta), trovato, contenuto)
        return HTMLResponse(html, headers=SOLO_PER_TE)

    @router.get("/faq", include_in_schema=False)
    async def faq(richiesta: Request, lingua: str | None = None):
        if lingua is not None:
            return cambia_lingua(lingua, "faq")
        html = pagina_faq(lingua_scelta(richiesta), raccolta)
        return HTMLResponse(html, headers=SOLO_PER_TE)

    @router.get("/faq/{id}", include_in_schema=False)
    async def domanda(richiesta: Request, id: str, lingua: str | None = None):
        trovata = raccolta.trova(id)
        if trovata is None:
            raise HTTPException(404, "Domanda non trovata")
        if lingua is not None:
            return cambia_lingua(lingua, id)
        html = pagina_domanda(lingua_scelta(richiesta), trovata, raccolta.html(trovata))
        return HTMLResponse(html, headers=SOLO_PER_TE)

    @router.post("/api/chat")
    async def chat(domanda: Domanda, richiesta: Request):
        sessione = domanda.sessione or str(uuid.uuid4())
        token = sessioni.token(richiesta)
        lingua = domanda.lingua

        def alla_pagina(tipo: str, dati: dict) -> str:
            return evento_sse(tipo, dati | per_la_pagina(tipo, dati, lingua))

        async def eventi():
            yield alla_pagina("utente", {"testo": domanda.messaggio})
            try:
                async for evento in client.turno(
                    domanda.messaggio, sessione, token, "chat", lingua
                ):
                    yield alla_pagina(evento.tipo, evento.dati)
            except ErroreAPI as e:
                # Nel log il motivo, mai il testo dell'utente (può contenere dati personali)
                logger.warning(f"Chat: {e}")
                yield alla_pagina("errore", {"testo": testo("non_risponde", lingua)})

        return StreamingResponse(
            eventi(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"}
        )

    return router
