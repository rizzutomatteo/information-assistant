"""Una finta API dell'assistente, per provare la chat e il canale voce prima che esista quella vera.

Ha lo stesso contratto dell'API vera (POST /turno, risposta in Server-Sent Events, vedi client.py) e
manda gli stati del grafo con qualche attesa per simulare i tempi. Non ha ancora una base di
conoscenza: risponde solo al saluto e alla richiesta di accedere, e a ogni altra domanda dice che
l'informazione non c'è. Risponde nella lingua chiesta (italiano o inglese).

Quando l'API vera esiste, basta puntare ASSISTENTE_API_URL su di lei.
"""

import asyncio
import os
import re
from collections.abc import AsyncIterator

from fastapi import FastAPI, Header
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from assistente.config import Lingua
from assistente.rag.client import evento_sse

# I nodi del grafo e quanto durano, in secondi, con FINTA_API_RITARDO=1
DURATE = {"input_guard": 0.15, "classify": 0.4, "retrieve": 0.5, "grade": 0.2}

SALUTO = re.compile(
    r"^\W*(ciao|salve|buongiorno|buonasera|hi|hello|hey|good (?:morning|afternoon|evening))\W*$",
    re.IGNORECASE,
)
# La frase consigliata è «le mie info»: con l'audio del telefono (8 kHz, G.711) Whisper la capisce
# perché è nel suo prompt (config.py). «Le mie polizze» e «i miei dati» invece diventano «le mie
# polizie» e «immedati»
ACCESSO = re.compile(
    r"\b(mie info|mie informazioni|mia polizza|accesso|accedere|accedo|login|log in|sign in"
    r"|my information|my policy|my details)\b",
    re.IGNORECASE,
)

# I testi, nelle due lingue: gli stati dei nodi per la chat e le risposte.
# Nella chiamata dal browser il pulsante non c'è: si accede nella pagina, poi si richiama.
# Al telefono basta dire che serve l'accesso: il PIN lo chiede il canale voce (voce/ponte.py).
TESTI = {
    "it": {
        "stati": {
            "input_guard": "Controllo il messaggio",
            "classify": "Capisco la domanda",
            "retrieve": "Cerco nei documenti",
            "grade": "Valuto i documenti trovati",
        },
        "ciao": "Ciao, come posso esserti utile?",
        "gia_dentro": "Hai già fatto l'accesso: come posso esserti utile?",
        "serve_accesso": {
            "chat": "Per continuare serve l'accesso alla tua area riservata: usa il pulsante "
            "qui sotto.",
            "voce": "Per continuare serve l'accesso alla tua area riservata: accedi dalla "
            "pagina, poi richiamami.",
            "telefono": "Per continuare devo sapere chi sei.",
        },
        "non_so": "Mi dispiace, questa informazione non è nella mia base di conoscenza.",
    },
    "en": {
        "stati": {
            "input_guard": "Checking the message",
            "classify": "Understanding the question",
            "retrieve": "Searching the documents",
            "grade": "Assessing the documents found",
        },
        "ciao": "Hi, how can I help you?",
        "gia_dentro": "You're already signed in: how can I help you?",
        "serve_accesso": {
            "chat": "To continue, you need to sign in to your personal area: use the button below.",
            "voce": "To continue, you need to sign in to your personal area: sign in on the "
            "page, then call me again.",
            "telefono": "To continue, I need to know who you are.",
        },
        "non_so": "I'm sorry, this information is not in my knowledge base.",
    },
}


class Turno(BaseModel):
    messaggio: str
    sessione: str = ""
    canale: str = "chat"
    lingua: Lingua = "it"


def risposta(testo: str, intento: str, confidenza: str = "alta", accesso: bool = False) -> dict:
    """Una risposta con tutti i campi del contratto; «accesso» chiede alla pagina di proporlo."""
    return {
        "testo": testo,
        "citazioni": [],
        "intento": intento,
        "confidenza": confidenza,
        "operatore": False,
        "accesso": accesso,
    }


def decidi(
    messaggio: str, canale: str, con_accesso: bool, lingua: Lingua = "it"
) -> tuple[list[str], dict]:
    """I nodi che il grafo attraverserebbe e la risposta, con due regole al posto dei modelli."""
    testi = TESTI[lingua]
    if SALUTO.match(messaggio):
        return ["input_guard", "classify"], risposta(testi["ciao"], "saluto")
    if ACCESSO.search(messaggio):
        if con_accesso:
            return ["input_guard", "classify"], risposta(testi["gia_dentro"], "accesso")
        serve = testi["serve_accesso"]
        testo = serve.get(canale, serve["chat"])
        return ["input_guard", "classify"], risposta(testo, "accesso", accesso=True)
    nodi = ["input_guard", "classify", "retrieve", "grade"]
    return nodi, risposta(testi["non_so"], "prodotto", confidenza="bassa")


def crea_app(ritardo: float | None = None) -> FastAPI:
    """ritardo moltiplica le durate dei nodi: 1 i tempi simulati, 0 subito (per i test)."""
    if ritardo is None:
        ritardo = float(os.environ.get("FINTA_API_RITARDO", 1.0))
    app = FastAPI(title="Finta API dell'assistente")

    @app.get("/salute")
    async def salute():
        return {"ok": True}

    @app.post("/turno")
    async def turno(corpo: Turno, authorization: str | None = Header(default=None)):
        # La finta API non controlla il token: le basta sapere se c'è
        con_accesso = (authorization or "").startswith("Bearer ")
        nodi, finale = decidi(corpo.messaggio, corpo.canale, con_accesso, corpo.lingua)
        stati = TESTI[corpo.lingua]["stati"]

        async def eventi() -> AsyncIterator[str]:
            for nodo in nodi:
                yield evento_sse("stato", {"nodo": nodo, "testo": stati[nodo]})
                await asyncio.sleep(DURATE[nodo] * ritardo)
            yield evento_sse("risposta", finale)

        return StreamingResponse(eventi(), media_type="text/event-stream")

    return app


def main():
    import uvicorn

    host = os.environ.get("FINTA_API_HOST", "127.0.0.1")
    porta = int(os.environ.get("FINTA_API_PORTA", 8001))
    uvicorn.run(crea_app(), host=host, port=porta)


if __name__ == "__main__":
    main()
