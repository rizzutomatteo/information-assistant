import json

import httpx

from assistente.config import Impostazioni
from assistente.server import crea_app
from assistente.voce import turn as modulo_turn
from assistente.voce.turn import TurnCloudflare

RISPOSTA = {
    "iceServers": [
        {"urls": ["stun:stun.cloudflare.com:3478", "stun:stun.cloudflare.com:53"]},
        {
            "urls": [
                "turn:turn.cloudflare.com:3478?transport=udp",
                "turn:turn.cloudflare.com:53?transport=udp",
                "turns:turn.cloudflare.com:443?transport=tcp",
            ],
            "username": "utente",
            "credential": "parola",
        },
    ]
}


def _turn(risponde) -> tuple[TurnCloudflare, list[httpx.Request]]:
    richieste = []

    def gestore(richiesta: httpx.Request) -> httpx.Response:
        richieste.append(richiesta)
        return risponde(richiesta)

    client = httpx.AsyncClient(transport=httpx.MockTransport(gestore))
    return TurnCloudflare("chiave", "token", client=client), richieste


async def test_chiede_le_credenziali_e_toglie_la_porta_53():
    turn, richieste = _turn(lambda _r: httpx.Response(201, json=RISPOSTA))
    server = await turn.server()
    assert server == [
        {"urls": ["stun:stun.cloudflare.com:3478"]},
        {
            "urls": [
                "turn:turn.cloudflare.com:3478?transport=udp",
                "turns:turn.cloudflare.com:443?transport=tcp",
            ],
            "username": "utente",
            "credential": "parola",
        },
    ]
    assert richieste[0].url.path == "/v1/turn/keys/chiave/credentials/generate-ice-servers"
    assert richieste[0].headers["authorization"] == "Bearer token"
    assert json.loads(richieste[0].content) == {"ttl": modulo_turn.DURATA}


async def test_riusa_le_credenziali_finche_basta_il_tempo(monkeypatch):
    adesso = [1000.0]
    monkeypatch.setattr(modulo_turn.time, "monotonic", lambda: adesso[0])
    turn, richieste = _turn(lambda _r: httpx.Response(201, json=RISPOSTA))
    await turn.server()
    adesso[0] += modulo_turn.DURATA - modulo_turn.MARGINE - 1
    await turn.server()
    assert len(richieste) == 1
    adesso[0] += 2
    await turn.server()
    assert len(richieste) == 2


async def test_se_cloudflare_non_risponde_tiene_quelle_ancora_valide(monkeypatch):
    adesso = [1000.0]
    monkeypatch.setattr(modulo_turn.time, "monotonic", lambda: adesso[0])
    risposte = iter([httpx.Response(201, json=RISPOSTA), httpx.Response(500), httpx.Response(500)])
    turn, _ = _turn(lambda _r: next(risposte))
    prime = await turn.server()
    adesso[0] += modulo_turn.DURATA - 1  # nel margine, ma non ancora scadute
    assert await turn.server() == prime
    adesso[0] += 2  # scadute
    assert await turn.server() == []


async def test_config_da_turn_e_stun_al_browser():
    turn, _ = _turn(lambda _r: httpx.Response(201, json=RISPOSTA))
    imp = Impostazioni(ice=["stun:stun.example.com:3478"])
    app = httpx.ASGITransport(app=crea_app(imp, precarica=False, turn=turn))
    async with httpx.AsyncClient(transport=app, base_url="https://voce") as server:
        ice = (await server.get("/api/config")).json()["ice"]
    assert ice[-1] == {"urls": "stun:stun.example.com:3478"}
    assert ice[1]["username"] == "utente"
