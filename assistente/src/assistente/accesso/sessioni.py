"""Le sessioni di chi è entrato, l'accesso con il PIN al telefono e i limiti ai tentativi.

Le sessioni stanno in memoria: si perdono quando il server riparte. Il token della sessione è
anche quello che chat e voce passano all'API dell'assistente, così l'API sa che l'utente ha fatto
l'accesso. Nel sistema vero l'accesso passa da Keycloak e le polizze arrivano dal server delle
polizze.
"""

import secrets
import time

from fastapi import Request, Response

from assistente.accesso.utenti import Anagrafe, Utente

COOKIE = "accesso"
DURATA = 8 * 3600  # secondi


def metti_cookie(risposta: Response, nome: str, valore: str):
    """Il cookie di una sessione: solo per il server (HttpOnly), solo su HTTPS, solo da qui."""
    risposta.set_cookie(nome, valore, max_age=DURATA, httponly=True, secure=True, samesite="strict")


def togli_cookie(risposta: Response, nome: str):
    risposta.delete_cookie(nome, httponly=True, secure=True, samesite="strict")


class Limite:
    """Quante volte è successa una cosa di recente, per chiave (una password sbagliata per
    quell'utente, una registrazione): oltre il massimo, quella chiave deve aspettare."""

    def __init__(self, massimo: int, finestra: float):
        self._massimo = massimo
        self._finestra = finestra  # secondi
        self._volte: dict[str, list[float]] = {}

    def superato(self, chiave: str) -> bool:
        adesso = time.monotonic()
        recenti = [t for t in self._volte.get(chiave, []) if adesso - t < self._finestra]
        self._volte[chiave] = recenti
        return len(recenti) >= self._massimo

    def conta(self, chiave: str):
        self._volte.setdefault(chiave, []).append(time.monotonic())

    def azzera(self, chiave: str):
        self._volte.pop(chiave, None)


class Sessioni:
    """Le sessioni aperte: token casuale → id dell'utente nell'anagrafe."""

    def __init__(self, anagrafe: Anagrafe):
        self.anagrafe = anagrafe
        self._aperte: dict[str, int] = {}

    def apri(self, utente: Utente) -> str:
        token = secrets.token_urlsafe(32)
        self._aperte[token] = utente.id
        return token

    def utente(self, token: str | None) -> Utente | None:
        """L'utente com'è adesso nell'anagrafe (con le polizze aggiunte nel frattempo)."""
        id_utente = self._aperte.get(token) if token else None
        return self.anagrafe.utente(id_utente) if id_utente is not None else None

    def chiudi(self, token: str | None):
        if token:
            self._aperte.pop(token, None)

    def token(self, richiesta: Request) -> str | None:
        """Il token della richiesta, se corrisponde a una sessione aperta."""
        token = richiesta.cookies.get(COOKIE)
        return token if token in self._aperte else None


class AccessoConPin:
    """L'accesso di chi telefona: il PIN giusto apre una sessione, che si chiude con la chiamata.
    Ogni utente ha il suo PIN, quindi il PIN da solo dice chi è."""

    def __init__(self, sessioni: Sessioni):
        self._sessioni = sessioni
        self.token: str | None = None

    def entra(self, pin: str) -> Utente | None:
        utente = self._sessioni.anagrafe.da_pin(pin)
        if utente:
            self.chiudi()
            self.token = self._sessioni.apri(utente)
        return utente

    def chiudi(self):
        self._sessioni.chiudi(self.token)
        self.token = None
