"""Il server dell'assistente assicurativo: il sito di Velaria con la chat, l'accesso e la voce.

Mette insieme le parti, ognuna con le sue rotte:

    sito/       le pagine, i documenti, le FAQ e la chat scritta
    accesso/    registrazione, accesso, polizze e la pagina /a degli utenti di prova
    voce/       le chiamate dal sito e le telefonate
    rag/        il client dell'API dell'assistente (il RAG), che chat e voce usano

    GET /salute   chiamate in corso e massimo
"""

import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from loguru import logger

from assistente.accesso.amministrazione import Amministrazione, router_amministrazione
from assistente.accesso.google import AccessoGoogle
from assistente.accesso.rotte import router_accesso
from assistente.accesso.sessioni import Sessioni
from assistente.accesso.utenti import Anagrafe
from assistente.config import Impostazioni
from assistente.rag.client import ClientAssistente
from assistente.sito.documenti import Archivio
from assistente.sito.faq import RaccoltaFaq
from assistente.sito.rotte import STATICO, FileStatici, router_sito
from assistente.voce.canale import CanaleVoce
from assistente.voce.turn import TurnCloudflare


def crea_app(
    imp: Impostazioni | None = None,
    precarica: bool = True,
    client: ClientAssistente | None = None,
    google: AccessoGoogle | None = None,
    turn: TurnCloudflare | None = None,
    anagrafe: Anagrafe | None = None,
) -> FastAPI:
    """precarica: se caricare i modelli della voce all'avvio (i test non li caricano).
    anagrafe: già aperta, per i test; altrimenti si apre all'avvio con ASSISTENTE_DATABASE."""
    imp = imp or Impostazioni.da_ambiente()
    client = client or ClientAssistente(imp.url_api)
    anagrafe = anagrafe or Anagrafe(imp.database)
    sessioni = Sessioni(anagrafe)
    if google is None and imp.google_client_id and imp.google_client_secret:
        google = AccessoGoogle(imp.google_client_id, imp.google_client_secret)
    amministrazione = Amministrazione(imp.amministrazione_password)
    voce = CanaleVoce(imp, client, sessioni, turn, precarica)

    @asynccontextmanager
    async def ciclo_di_vita(_app: FastAPI):
        # Senza database il server non parte: meglio subito che al primo accesso
        await anagrafe.apri()
        await voce.avvia()
        yield
        await voce.chiudi()
        await client.chiudi()
        if google:
            await google.chiudi()
        await anagrafe.chiudi()

    app = FastAPI(title="Assistente assicurativo", lifespan=ciclo_di_vita)
    app.mount("/statico", FileStatici(directory=STATICO), name="statico")
    app.include_router(
        router_sito(
            sessioni,
            Archivio(imp.documenti),
            RaccoltaFaq(imp.documenti),
            amministrazione,
            client,
            google.client_id if google else "",
            registra=voce.registro is not None,
        )
    )
    app.include_router(router_accesso(sessioni, google))
    app.include_router(router_amministrazione(amministrazione, anagrafe))
    app.include_router(voce.router)

    @app.get("/salute")
    async def salute():
        return {"ok": True, "chiamate": voce.linee.attive, "massimo": voce.linee.massimo}

    return app


def main():
    import uvicorn

    imp = Impostazioni.da_ambiente()
    logger.remove()
    logger.add(sys.stderr, level=imp.log)
    uvicorn.run(crea_app(imp), host=imp.host, port=imp.porta, log_level="warning")


if __name__ == "__main__":
    main()
