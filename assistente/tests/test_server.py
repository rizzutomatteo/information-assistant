import time
from types import SimpleNamespace
from urllib.parse import parse_qs

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from assistente.accesso.google import TOKEN_GOOGLE, AccessoGoogle
from assistente.accesso.sessioni import COOKIE
from assistente.config import Impostazioni
from assistente.rag.client import ClientAssistente, leggi_sse
from assistente.rag.finta import TESTI as TESTI_API
from assistente.rag.finta import crea_app as crea_finta_api
from assistente.server import crea_app
from assistente.sito.testi import TESTI

# Al posto di Google: una chiave RSA fatta qui, con cui si firmano ID token di prova
CLIENT_ID = "prova.apps.googleusercontent.com"
CLIENT_SECRET = "segreto-di-prova"
CODICE_SCADUTO = "codice-già-usato"
CHIAVE = rsa.generate_private_key(public_exponent=65537, key_size=2048)
ALTRA_CHIAVE = rsa.generate_private_key(public_exponent=65537, key_size=2048)


class ChiaviFinte:
    """Fa le veci di jwt.PyJWKClient: dà la chiave pubblica senza scaricarla da Google."""

    def get_signing_key_from_jwt(self, _token: str):
        return SimpleNamespace(key=CHIAVE.public_key())


def _token(chiave=CHIAVE, **campi) -> str:
    """Un ID token come quelli di Google; i campi passati sostituiscono quelli predefiniti."""
    adesso = int(time.time())
    dati = {
        "iss": "https://accounts.google.com",
        "aud": CLIENT_ID,
        "sub": "1234567890",
        "email": "anna.bianchi@example.com",
        "email_verified": True,
        "given_name": "Anna",
        "family_name": "Bianchi",
        "iat": adesso,
        "exp": adesso + 600,
        **campi,
    }
    return jwt.encode(dati, chiave, algorithm="RS256")


def _google_finto(richiesta: httpx.Request) -> httpx.Response:
    """L'endpoint di Google che scambia il codice: qui il codice è l'ID token stesso."""
    assert str(richiesta.url) == TOKEN_GOOGLE
    dati = {k: v[0] for k, v in parse_qs(richiesta.content.decode()).items()}
    assert (dati["client_id"], dati["client_secret"]) == (CLIENT_ID, CLIENT_SECRET)
    assert dati["redirect_uri"] == "postmessage"
    if dati["code"] == CODICE_SCADUTO:
        return httpx.Response(400, json={"error": "invalid_grant"})
    return httpx.Response(200, json={"id_token": dati["code"], "access_token": "a"})


def _accesso(token: str | None = None) -> dict:
    return {"codice": token or _token()}


def _server(client: ClientAssistente | None = None, google: bool = True) -> httpx.AsyncClient:
    """Il server della voce (senza modelli) davanti alla finta API, tutto in memoria.

    In HTTPS perché il cookie dell'accesso è «Secure»: su HTTP il client non lo rimanda.
    """
    if client is None:
        finta = httpx.ASGITransport(app=crea_finta_api(ritardo=0))
        client = ClientAssistente("http://finta", client=httpx.AsyncClient(transport=finta))
    accesso = None
    if google:
        http = httpx.AsyncClient(transport=httpx.MockTransport(_google_finto))
        accesso = AccessoGoogle(CLIENT_ID, CLIENT_SECRET, chiavi=ChiaviFinte(), http=http)
    app = crea_app(Impostazioni(), precarica=False, client=client, google=accesso)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://voce")


async def _chat(server: httpx.AsyncClient, messaggio: str, lingua: str = "it"):
    corpo = {"messaggio": messaggio, "sessione": "s1", "lingua": lingua}
    risposta = await server.post("/api/chat", json=corpo)
    assert risposta.headers["content-type"].startswith("text/event-stream")
    return [e async for e in leggi_sse(risposta.text.splitlines())]


async def test_chat_inoltra_gli_eventi_dell_api():
    async with _server() as server:
        eventi = await _chat(server, "Cosa copre la Kasko?")
    assert [e.tipo for e in eventi] == ["utente"] + ["stato"] * 4 + ["risposta"]
    assert eventi[-1].dati["testo"] == TESTI_API["it"]["non_so"]


async def test_chat_con_i_messaggi_pronti_per_la_pagina():
    async with _server() as server:
        domanda, *stati, risposta = await _chat(server, "<b>Kasko</b>?")
    # La domanda torna protetta: nella pagina è testo, non HTML
    protetta = "<p>&lt;b&gt;Kasko&lt;/b&gt;?</p>"
    assert domanda.dati["html"] == f'<div class="messaggio da-utente">{protetta}</div>'
    assert domanda.dati["attesa"] == TESTI["ci_penso"].it
    assert all(e.dati["attesa"] == e.dati["testo"] for e in stati)
    assert risposta.dati["html"].startswith('<div class="messaggio da-assistente"><p>')
    assert risposta.dati["attesa"] == ""


async def test_chat_nella_lingua_della_pagina():
    async with _server() as server:
        eventi = await _chat(server, "What does Kasko cover?", lingua="en")
        assert eventi[-1].dati["testo"] == TESTI_API["en"]["non_so"]
        sconosciuta = {"messaggio": "Bonjour", "lingua": "fr"}
        assert (await server.post("/api/chat", json=sconosciuta)).status_code == 422


async def test_chat_rifiuta_un_messaggio_vuoto():
    async with _server() as server:
        assert (await server.post("/api/chat", json={"messaggio": ""})).status_code == 422


async def test_chat_senza_api_manda_un_errore():
    async with _server(ClientAssistente("http://127.0.0.1:9")) as server:  # nessuno in ascolto
        eventi = await _chat(server, "Ciao")
    assert [e.tipo for e in eventi] == ["utente", "errore"]
    assert eventi[-1].dati["testo"] == TESTI["non_risponde"].it


async def test_pagina_e_file_statici():
    async with _server() as server:
        pagina = await server.get("/")
        assert pagina.status_code == 200 and "assistente.js" in pagina.text
        # Può avere i dati di chi l'ha aperta: niente copie fuori dal suo browser
        assert pagina.headers["cache-control"] == "private, no-cache"
        for file in ("stile.css", "assistente.js", "accesso.js", "logo.svg"):
            risposta = await server.get(f"/statico/{file}")
            assert risposta.status_code == 200, file
            # Dopo un aggiornamento il browser non deve tenere la versione vecchia
            assert risposta.headers["cache-control"] == "no-cache", file


async def test_pagina_nella_lingua_scelta():
    async with _server() as server:
        pagina = (await server.get("/")).text
        assert '<html lang="it">' in pagina and str(TESTI["benvenuto"].it) in pagina

        # Una bandiera: il server ricorda la lingua e torna all'indirizzo senza ?lingua
        bandiera = await server.get("/?lingua=en")
        assert bandiera.status_code == 303 and bandiera.headers["location"] == "./"
        pagina = (await server.get("/")).text
        assert '<html lang="en">' in pagina and TESTI["benvenuto"].en in pagina
        assert 'value="en" lang="en" aria-pressed="true"' in pagina

        # Una lingua che non c'è non cambia niente
        await server.get("/?lingua=fr")
        assert '<html lang="en">' in (await server.get("/")).text


def test_ogni_testo_ha_le_due_lingue():
    assert all(testo.it and testo.en for testo in TESTI.values())


async def test_pagina_con_il_client_id_di_google():
    async with _server() as server:
        assert f'data-client="{CLIENT_ID}"' in (await server.get("/")).text
    async with _server(google=False) as server:
        pagina = (await server.get("/")).text
    # Senza Google si entra solo con utente e password
    assert 'id="pulsante-google"' not in pagina and 'id="modulo-password"' in pagina


async def _dentro(server: httpx.AsyncClient) -> bool:
    """Se la pagina mostra l'area riservata."""
    return 'id="esci"' in (await server.get("/")).text


@pytest.mark.parametrize(
    "token",
    [
        _token(chiave=ALTRA_CHIAVE),  # firma non di Google
        _token(aud="altro.apps.googleusercontent.com"),  # fatto per un altro sito
        _token(iss="https://altro.example.com"),
        _token(exp=int(time.time()) - 60),  # scaduto
        _token(email_verified=False),
        "non-è-un-token",
        CODICE_SCADUTO,  # Google rifiuta il codice
    ],
    ids=[
        "firma",
        "destinatario",
        "emittente",
        "scaduto",
        "email-non-verificata",
        "spazzatura",
        "codice-rifiutato",
    ],
)
async def test_accesso_rifiutato(token):
    async with _server() as server:
        risposta = await server.post("/api/accesso", json=_accesso(token))
        assert risposta.status_code == 401
        assert COOKIE not in server.cookies
        assert not await _dentro(server)


async def test_accesso_senza_google_configurato():
    async with _server(google=False) as server:
        assert (await server.post("/api/accesso", json=_accesso())).status_code == 503


async def test_accesso_dati_polizze_e_uscita():
    async with _server() as server:
        risposta = await server.post("/api/accesso", json=_accesso())
        assert risposta.status_code == 200
        intestazione = risposta.headers["set-cookie"].lower()
        assert "httponly" in intestazione and "secure" in intestazione

        io = risposta.json()
        assert (io["nome"], io["cognome"]) == ("Anna", "Bianchi")

        pagina = (await server.get("/")).text
        assert "<dd>Anna Bianchi</dd>" in pagina and "<dd>anna.bianchi@example.com</dd>" in pagina
        assert '<span class="iniziali" aria-hidden="true">AB</span>' in pagina
        assert pagina.count('<article class="scheda polizza ') == 2
        assert "data-accedi hidden>" in pagina  # il pulsante «Accedi» in alto

        assert (await server.post("/api/uscita")).status_code == 204
        assert not await _dentro(server)


async def test_la_chat_passa_l_accesso_all_api():
    async with _server() as server:
        ospite = await _chat(server, "Voglio fare l'accesso")
        assert ospite[-1].dati["testo"] == TESTI_API["it"]["serve_accesso"]["chat"]
        assert ospite[-1].dati["accesso"] is True

        await server.post("/api/accesso", json=_accesso())
        dentro = await _chat(server, "Voglio fare l'accesso")
        assert dentro[-1].dati["testo"] == TESTI_API["it"]["gia_dentro"]
