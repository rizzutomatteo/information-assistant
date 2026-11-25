import base64
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pipecat.frames.frames import (
    InputAudioRawFrame,
    InputDTMFFrame,
    InterruptionFrame,
    OutputAudioRawFrame,
    OutputTransportMessageUrgentFrame,
)
from starlette.websockets import WebSocketDisconnect

from assistente.accesso.sessioni import AccessoConPin, Sessioni
from assistente.accesso.utenti import PIN_DEMO
from assistente.config import Impostazioni
from assistente.server import crea_app
from assistente.voce.telefono import PEZZO, SerializzatoreAsterisk, credenziali_valide


def _basic(utente: str, password: str) -> str:
    return "Basic " + base64.b64encode(f"{utente}:{password}".encode()).decode()


@pytest.mark.parametrize(
    ("intestazione", "segreto", "valide"),
    [
        (_basic("asterisk", "s3greto"), "s3greto", True),
        (_basic("asterisk", "sbagliato"), "s3greto", False),
        (_basic("altro", "s3greto"), "s3greto", False),
        (_basic("asterisk", ""), "", False),  # senza segreto il telefono è spento
        ("Basic ???", "s3greto", False),
        ("Bearer s3greto", "s3greto", False),
        (None, "s3greto", False),
    ],
)
def test_credenziali_di_asterisk(intestazione, segreto, valide):
    assert credenziali_valide(intestazione, segreto) is valide


@pytest.fixture
async def serializzatore():
    s = SerializzatoreAsterisk()
    await s.setup(SimpleNamespace(audio_in_sample_rate=16000))
    return s


async def test_audio_da_asterisk(serializzatore):
    frame = await serializzatore.deserialize(b"\x01\x00" * (PEZZO // 2))
    assert isinstance(frame, InputAudioRawFrame)
    assert frame.sample_rate == 16000 and len(frame.audio) == PEZZO


async def test_audio_verso_asterisk_a_16_khz(serializzatore):
    audio = b"\x00\x01" * 320
    frame = OutputAudioRawFrame(audio=audio, sample_rate=16000, num_channels=1)
    assert await serializzatore.serialize(frame) == audio


async def test_interruzione_svuota_la_coda_di_asterisk(serializzatore):
    comando = await serializzatore.serialize(InterruptionFrame())
    assert json.loads(comando) == {"command": "FLUSH_MEDIA"}


async def test_tasto_del_tastierino(serializzatore):
    frame = await serializzatore.deserialize(json.dumps({"event": "DTMF_END", "digit": "#"}))
    assert isinstance(frame, InputDTMFFrame) and frame.button.value == "#"
    assert await serializzatore.deserialize('{"event": "DTMF_END", "digit": "X"}') is None


async def test_eventi_e_messaggi_per_la_chat_si_ignorano(serializzatore):
    evento = {"event": "MEDIA_START", "format": "slin16", "optimal_frame_size": 640}
    assert await serializzatore.deserialize(json.dumps(evento)) is None
    assert await serializzatore.deserialize("MEDIA_START format:slin16") is None
    messaggio = OutputTransportMessageUrgentFrame(message={"tipo": "stato"})
    assert await serializzatore.serialize(messaggio) is None


@pytest.mark.parametrize("intestazione", [None, _basic("asterisk", "sbagliato")])
def test_telefono_rifiuta_chi_non_e_asterisk(intestazione, indirizzo_db):
    # TestClient avvia il server come in produzione: anche il database
    app = crea_app(Impostazioni(telefono_segreto="s3greto", database=indirizzo_db), precarica=False)
    intestazioni = {"Authorization": intestazione} if intestazione else {}
    with TestClient(app) as client, pytest.raises(WebSocketDisconnect) as errore:
        with client.websocket_connect("/telefono", headers=intestazioni):
            pass
    assert errore.value.code == 1008


def test_telefono_occupato_quando_le_linee_sono_piene(indirizzo_db):
    imp = Impostazioni(telefono_segreto="s3greto", chiamate_max=0, database=indirizzo_db)
    app = crea_app(imp, precarica=False)
    with TestClient(app) as client, pytest.raises(WebSocketDisconnect) as errore:
        with client.websocket_connect(
            "/telefono", headers={"Authorization": _basic("asterisk", "s3greto")}
        ):
            pass
    assert errore.value.code == 1013


async def test_accesso_con_pin_apre_e_chiude_la_sessione(anagrafe):
    sessioni = Sessioni(anagrafe)
    accesso = AccessoConPin(sessioni)
    assert await accesso.entra("000000") is None and accesso.token is None
    # Al primo avvio c'è Mario Rossi, con il PIN delle prove al telefono
    assert (await accesso.entra(PIN_DEMO)).nome_completo == "Mario Rossi"
    token = accesso.token
    assert (await sessioni.utente(token)).pin_telefono == PIN_DEMO
    accesso.chiudi()
    assert await sessioni.utente(token) is None
