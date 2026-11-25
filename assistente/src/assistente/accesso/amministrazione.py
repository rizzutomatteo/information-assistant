"""La pagina /a: si caricano gli utenti di prova incollando un JSON (utenti.FileUtenti), e si
modificano o si eliminano uno alla volta, o tutti insieme.

    GET    /a                  la pagina (sito/rotte.py): la password, poi il JSON e gli utenti
    POST   /api/a/accesso      la password di amministrazione → cookie
    POST   /api/a/utenti       il JSON → utenti creati, o sostituiti se il nome utente c'è già
    PUT    /api/a/utenti/<id>  dati e polizze di un utente, cambiati a mano (utenti.ModificaUtente)
    DELETE /api/a/utenti/<id>  elimina un utente, con le sue polizze
    DELETE /api/a/utenti       li elimina tutti
    POST   /api/a/uscita       chiude la sessione di amministrazione

Il formato del JSON è quello di esempio_utenti.json, che la pagina mostra e che si può copiare e
riempire. Si entra con la password ASSISTENTE_AMMINISTRAZIONE_PASSWORD; senza password la pagina
non c'è (404). Come per gli utenti, dopo troppe password sbagliate bisogna aspettare.
"""

import hmac
import secrets
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from assistente.accesso.sessioni import Limite, metti_cookie, togli_cookie
from assistente.accesso.utenti import (
    Anagrafe,
    Conflitto,
    FileUtenti,
    ModificaUtente,
    impronta_password,
)

COOKIE = "amministrazione"
TENTATIVI = 5
ATTESA = 15 * 60  # secondi
# Lo «stampino» del JSON: un utente completo, con una polizza
ESEMPIO = Path(__file__).with_name("esempio_utenti.json")


class Password(BaseModel):
    password: str = Field(min_length=1, max_length=200)


class Amministrazione:
    """La password di amministrazione e le sessioni aperte con essa (in memoria)."""

    def __init__(self, password: str):
        self._password = password
        self._aperte: set[str] = set()
        self.sbagliate = Limite(TENTATIVI, ATTESA)

    @property
    def attiva(self) -> bool:
        return bool(self._password)

    def password_giusta(self, password: str) -> bool:
        return self.attiva and hmac.compare_digest(password.encode(), self._password.encode())

    def apri(self) -> str:
        token = secrets.token_urlsafe(32)
        self._aperte.add(token)
        return token

    def entrato(self, richiesta: Request) -> bool:
        return self.attiva and richiesta.cookies.get(COOKIE) in self._aperte

    def chiudi(self, richiesta: Request):
        self._aperte.discard(richiesta.cookies.get(COOKIE))


def router_amministrazione(amministrazione: Amministrazione, anagrafe: Anagrafe) -> APIRouter:
    router = APIRouter(prefix="/api/a")

    def controlla(richiesta: Request):
        if not amministrazione.attiva:
            raise HTTPException(404)
        if not amministrazione.entrato(richiesta):
            raise HTTPException(401, "Serve la password di amministrazione.")

    @router.post("/accesso")
    async def accedi(corpo: Password, risposta: Response):
        if not amministrazione.attiva:
            raise HTTPException(404)
        if amministrazione.sbagliate.superato(COOKIE):
            raise HTTPException(429, "Troppi tentativi: riprova tra qualche minuto.")
        if not amministrazione.password_giusta(corpo.password):
            amministrazione.sbagliate.conta(COOKIE)
            raise HTTPException(401, "Password sbagliata.")
        amministrazione.sbagliate.azzera(COOKIE)
        metti_cookie(risposta, COOKIE, amministrazione.apri())

    @router.post("/utenti")
    async def carica(corpo: FileUtenti, richiesta: Request):
        controlla(richiesta)
        password = {u.utente: u.password for u in corpo.utenti}
        impronte = await run_in_threadpool(
            lambda: {nome: impronta_password(p) for nome, p in password.items()}
        )
        try:
            creati, sostituiti = await anagrafe.carica(corpo.utenti, impronte)
        except Conflitto as e:
            raise HTTPException(409, str(e)) from None
        return {"creati": creati, "sostituiti": sostituiti}

    @router.put("/utenti/{id_utente}", status_code=204)
    async def modifica(id_utente: int, corpo: ModificaUtente, richiesta: Request):
        controlla(richiesta)
        impronta = None
        if corpo.password:
            impronta = await run_in_threadpool(impronta_password, corpo.password)
        try:
            utente = await anagrafe.modifica(id_utente, corpo, impronta)
        except Conflitto as e:
            raise HTTPException(409, str(e)) from None
        if utente is None:
            raise HTTPException(404, "Utente non trovato.")

    @router.delete("/utenti/{id_utente}", status_code=204)
    async def elimina(id_utente: int, richiesta: Request):
        controlla(richiesta)
        if not await anagrafe.elimina(id_utente):
            raise HTTPException(404, "Utente non trovato.")

    @router.delete("/utenti")
    async def elimina_tutti(richiesta: Request):
        controlla(richiesta)
        return {"eliminati": await anagrafe.elimina_tutti()}

    @router.post("/uscita", status_code=204)
    async def esci(richiesta: Request, risposta: Response):
        amministrazione.chiudi(richiesta)
        togli_cookie(risposta, COOKIE)

    return router
