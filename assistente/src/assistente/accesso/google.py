"""L'accesso con Google.

Il pulsante «Accedi con Google» è della pagina; l'accesso si fa in una finestra di Google (Google
Identity Services, modello «codice»), che alla fine dà alla pagina un codice monouso. Il server lo
scambia con Google, usando il client secret, per un ID token: un JWT firmato con il nome e l'email
dell'utente. Lo verifica con le chiavi pubbliche di Google (firma, destinatario uguale al nostro
client ID, emittente, scadenza, email verificata) e ne ricava chi è entrato.
"""

from typing import NamedTuple

import httpx
import jwt
from fastapi.concurrency import run_in_threadpool
from loguru import logger

# Dove si scambia il codice per l'ID token, le chiavi con cui Google lo firma, e chi lo emette
TOKEN_GOOGLE = "https://oauth2.googleapis.com/token"
CHIAVI_GOOGLE = "https://www.googleapis.com/oauth2/v3/certs"
EMITTENTI_GOOGLE = ("accounts.google.com", "https://accounts.google.com")


class IdentitaGoogle(NamedTuple):
    email: str
    nome: str
    cognome: str


class AccessoGoogle:
    """Scambia il codice di Google per l'ID token, lo verifica e ne ricava chi è entrato."""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        chiavi: jwt.PyJWKClient | None = None,
        http: httpx.AsyncClient | None = None,
    ):
        self.client_id = client_id
        self._client_secret = client_secret
        # Scarica le chiavi pubbliche di Google e le tiene in memoria per qualche minuto
        self._chiavi = chiavi or jwt.PyJWKClient(CHIAVI_GOOGLE)
        self._http = http or httpx.AsyncClient(timeout=10)

    async def identita_dal_codice(self, codice: str) -> IdentitaGoogle | None:
        """Chi ha fatto l'accesso nella finestra di Google, o None."""
        try:
            risposta = await self._http.post(
                TOKEN_GOOGLE,
                data={
                    "code": codice,
                    "client_id": self.client_id,
                    "client_secret": self._client_secret,
                    # Il codice è arrivato alla pagina dalla finestra di Google, senza reindirizzare
                    "redirect_uri": "postmessage",
                    "grant_type": "authorization_code",
                },
            )
        except httpx.HTTPError as e:
            logger.warning(f"Accesso con Google: Google non risponde ({e!r})")
            return None
        token = risposta.json().get("id_token") if risposta.status_code == 200 else None
        if not token:
            # Nel log il motivo di Google («invalid_grant»…), mai il codice
            logger.warning(f"Accesso con Google rifiutato: {risposta.text[:200]}")
            return None
        return await run_in_threadpool(self.identita, token)

    async def chiudi(self):
        await self._http.aclose()

    def identita(self, token: str) -> IdentitaGoogle | None:
        """Chi è nel token, o None se non è valido. Può scaricare le chiavi: va in un thread."""
        try:
            chiave = self._chiavi.get_signing_key_from_jwt(token).key
            dati = jwt.decode(
                token,
                chiave,
                algorithms=["RS256"],
                audience=self.client_id,
                issuer=EMITTENTI_GOOGLE,
                options={"require": ["exp", "iat", "sub", "email"]},
            )
        except jwt.PyJWTError as e:
            logger.warning(f"Accesso con Google rifiutato: {e}")
            return None
        if dati.get("email_verified") is not True:
            logger.warning("Accesso con Google rifiutato: email non verificata")
            return None
        email = dati["email"]
        return IdentitaGoogle(
            email,
            dati.get("given_name") or dati.get("name") or email.split("@")[0],
            dati.get("family_name", ""),
        )
