import json

import httpx
import pytest

from assistente.rag.client import ClientAssistente, ErroreAPI, Evento, leggi_sse
from assistente.rag.finta import TESTI, crea_app, decidi

IT, EN = TESTI["it"], TESTI["en"]


async def _tutti(righe):
    return [e async for e in leggi_sse(righe)]


async def test_sse_eventi_e_commenti():
    righe = [
        ": tieni viva la connessione",
        "event: stato",
        'data: {"nodo": "retrieve", "testo": "Cerco nei documenti"}',
        "",
        "event: risposta",
        'data: {"testo": "Sì.",',
        'data: "citazioni": []}',
        "",
    ]
    assert await _tutti(righe) == [
        Evento("stato", {"nodo": "retrieve", "testo": "Cerco nei documenti"}),
        Evento("risposta", {"testo": "Sì.", "citazioni": []}),
    ]


async def test_sse_ultimo_blocco_senza_riga_vuota_e_testo_semplice():
    assert await _tutti(["data: ciao"]) == [Evento("message", {"testo": "ciao"})]


def _client(app) -> ClientAssistente:
    trasporto = httpx.ASGITransport(app=app)
    return ClientAssistente("http://finta", client=httpx.AsyncClient(transport=trasporto))


async def test_finta_api_risponde_che_non_sa():
    client = _client(crea_app(ritardo=0))
    eventi = [e async for e in client.turno("Che cos'è la franchigia?", "s1")]
    stati = [e.dati["nodo"] for e in eventi if e.tipo == "stato"]
    assert stati == ["input_guard", "classify", "retrieve", "grade"]
    assert eventi[-1].tipo == "risposta"
    assert eventi[-1].dati["testo"] == IT["non_so"]


@pytest.mark.parametrize("messaggio", ["ciao", "Ciao!", "  buongiorno."])
def test_saluto(messaggio):
    _, risposta = decidi(messaggio, "chat", con_accesso=False)
    assert risposta["testo"] == IT["ciao"]


@pytest.mark.parametrize("canale", ["chat", "voce", "telefono"])
@pytest.mark.parametrize(
    "messaggio", ["Le mie info.", "Le mie informazioni.", "La mia polizza", "Voglio fare l'accesso"]
)
def test_ospite_che_vuole_accedere(canale, messaggio):
    nodi, risposta = decidi(messaggio, canale, con_accesso=False)
    assert nodi == ["input_guard", "classify"]
    assert risposta["accesso"] is True
    assert risposta["testo"] == IT["serve_accesso"][canale]


def test_chi_ha_gia_fatto_l_accesso():
    _, risposta = decidi("Voglio fare l'accesso", "chat", con_accesso=True)
    assert risposta["accesso"] is False
    assert risposta["testo"] == IT["gia_dentro"]


async def test_la_finta_api_vede_il_token():
    client = _client(crea_app(ritardo=0))
    eventi = [e async for e in client.turno("voglio accedere", "s1", token="abc")]
    assert eventi[-1].dati["testo"] == IT["gia_dentro"]


async def test_finta_api_in_inglese():
    client = _client(crea_app(ritardo=0))
    eventi = [e async for e in client.turno("What is the excess?", "s1", lingua="en")]
    assert [e.dati["testo"] for e in eventi if e.tipo == "stato"] == list(EN["stati"].values())
    assert eventi[-1].dati["testo"] == EN["non_so"]


@pytest.mark.parametrize("messaggio", ["hello", "Good morning!"])
def test_saluto_in_inglese(messaggio):
    _, risposta = decidi(messaggio, "chat", con_accesso=False, lingua="en")
    assert risposta["testo"] == EN["ciao"]


@pytest.mark.parametrize("messaggio", ["My information", "I want to sign in"])
def test_ospite_che_vuole_accedere_in_inglese(messaggio):
    _, risposta = decidi(messaggio, "voce", con_accesso=False, lingua="en")
    assert risposta["accesso"] is True
    assert risposta["testo"] == EN["serve_accesso"]["voce"]


def test_le_due_lingue_hanno_gli_stessi_testi():
    assert IT.keys() == EN.keys()
    assert IT["stati"].keys() == EN["stati"].keys()
    assert IT["serve_accesso"].keys() == EN["serve_accesso"].keys()


async def test_corpo_della_richiesta():
    ricevuto = {}

    async def app(scope, receive, send):
        ricevuto.update(json.loads((await receive())["body"]))
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"event: risposta\ndata: {}\n\n"})

    [e async for e in _client(app).turno("hello", "s1", canale="chat", lingua="en")]
    assert ricevuto == {"sessione": "s1", "messaggio": "hello", "canale": "chat", "lingua": "en"}


async def test_token_inoltrato_come_bearer():
    ricevute = {}

    async def app(scope, receive, send):
        ricevute.update({k.decode(): v.decode() for k, v in scope["headers"]})
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"event: risposta\ndata: {}\n\n"})

    client = _client(app)
    [e async for e in client.turno("ciao", "s1", token="abc")]
    assert ricevute["authorization"] == "Bearer abc"


async def test_errore_http_diventa_errore_api():
    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 500, "headers": []})
        await send({"type": "http.response.body", "body": b"rotto"})

    with pytest.raises(ErroreAPI, match="500"):
        [e async for e in _client(app).turno("ciao", "s1")]
