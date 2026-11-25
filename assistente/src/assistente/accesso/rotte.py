"""Gli endpoint dell'accesso e delle polizze di chi è entrato.

    POST   /api/registrazione     un account nuovo (nome, utente, password…) → già dentro
    POST   /api/accesso/password  utente e password → cookie di sessione, e i dati dell'utente
    POST   /api/accesso           il codice di Google → cookie di sessione, e i dati dell'utente
    POST   /api/uscita            chiude la sessione
    POST   /api/polizze           aggiunge una polizza a chi è entrato
    DELETE /api/polizze/<id>      la toglie

Dopo TENTATIVI password sbagliate per lo stesso utente, quell'utente aspetta ATTESA secondi; dopo
REGISTRAZIONI account nuovi in un'ora, il prossimo aspetta (il sito pubblico è aperto a tutti).
Con Google si entra come l'utente dell'anagrafe con la stessa email: la prima volta lo si crea,
con i dati e le polizze di prova.
"""

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from assistente.accesso.google import AccessoGoogle
from assistente.accesso.sessioni import COOKIE, Limite, Sessioni, metti_cookie, togli_cookie
from assistente.accesso.utenti import (
    Conflitto,
    PolizzaDati,
    Registrazione,
    Utente,
    impronta_password,
    password_giusta,
)

TENTATIVI = 5
ATTESA = 15 * 60  # secondi
REGISTRAZIONI = 30


class CodiceGoogle(BaseModel):
    """Quello che la pagina riceve da Google dopo «Accedi con Google»."""

    codice: str = Field(min_length=1, max_length=2048)


class Credenziali(BaseModel):
    utente: str = Field(min_length=1, max_length=60)
    password: str = Field(min_length=1, max_length=200)


def router_accesso(sessioni: Sessioni, google: AccessoGoogle | None) -> APIRouter:
    """Senza «google» (client non configurato) si entra solo con utente e password."""
    router = APIRouter(prefix="/api")
    sbagliate = Limite(TENTATIVI, ATTESA)
    nuovi = Limite(REGISTRAZIONI, 3600)
    anagrafe = sessioni.anagrafe

    def entrato(utente: Utente, risposta: Response) -> dict:
        metti_cookie(risposta, COOKIE, sessioni.apri(utente))
        return utente.profilo()

    def chi_e_entrato(richiesta: Request) -> Utente:
        utente = sessioni.utente(sessioni.token(richiesta))
        if utente is None:
            raise HTTPException(401, "Serve l'accesso.")
        return utente

    @router.post("/registrazione", status_code=201)
    async def registrati(corpo: Registrazione, risposta: Response):
        if nuovi.superato("tutti"):
            raise HTTPException(429, "Troppe registrazioni: riprova più tardi.")
        impronta = await run_in_threadpool(impronta_password, corpo.password)
        try:
            utente = anagrafe.registra(corpo, impronta)
        except Conflitto as e:
            # Il campo già usato, perché la pagina dica quale
            raise HTTPException(409, {"campo": e.campo, "messaggio": str(e)}) from None
        nuovi.conta("tutti")
        return entrato(utente, risposta)

    @router.post("/accesso/password")
    async def accedi_con_password(corpo: Credenziali, risposta: Response):
        chi = corpo.utente.strip().lower()
        if sbagliate.superato(chi):
            raise HTTPException(429, "Troppi tentativi: riprova tra qualche minuto.")
        trovato = anagrafe.impronta(chi)
        giusta = await run_in_threadpool(
            password_giusta, corpo.password, trovato[1] if trovato else None
        )
        utente = anagrafe.utente(trovato[0]) if trovato and giusta else None
        if utente is None:
            sbagliate.conta(chi)
            raise HTTPException(401, "Utente o password sbagliati.")
        sbagliate.azzera(chi)
        return entrato(utente, risposta)

    @router.post("/accesso")
    async def accedi_con_google(corpo: CodiceGoogle, risposta: Response):
        if google is None:
            raise HTTPException(503, "L'accesso con Google non è configurato.")
        identita = await google.identita_dal_codice(corpo.codice)
        if identita is None:
            raise HTTPException(401, "Accesso con Google non riuscito: riprova.")
        return entrato(anagrafe.da_google(*identita), risposta)

    @router.post("/uscita", status_code=204)
    async def esci(richiesta: Request, risposta: Response):
        sessioni.chiudi(richiesta.cookies.get(COOKIE))
        togli_cookie(risposta, COOKIE)

    @router.post("/polizze", status_code=201)
    async def aggiungi_polizza(corpo: PolizzaDati, richiesta: Request):
        utente = chi_e_entrato(richiesta)
        return {"id": anagrafe.aggiungi_polizza(utente.id, corpo.polizza())}

    @router.delete("/polizze/{id_polizza}", status_code=204)
    async def togli_polizza(id_polizza: int, richiesta: Request):
        utente = chi_e_entrato(richiesta)
        if not anagrafe.togli_polizza(utente.id, id_polizza):
            raise HTTPException(404, "Polizza non trovata.")

    return router
