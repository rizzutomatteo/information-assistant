from types import SimpleNamespace

import httpx
import pytest
from pipecat.frames.frames import TranscriptionFrame

from assistente.config import Impostazioni
from assistente.voce import servizi
from assistente.voce.azure import Azure
from assistente.voce.groq import Groq
from assistente.voce.remoti import ErroreRemoto
from assistente.voce.servizi import WhisperVeloce

UN_SECONDO = b"\x01\x00" * 16000


def _servizio(classe, risponde):
    richieste = []

    def gestore(richiesta: httpx.Request) -> httpx.Response:
        richieste.append(richiesta)
        return risponde(richiesta)

    client = httpx.AsyncClient(base_url="https://remoto", transport=httpx.MockTransport(gestore))
    return classe(
        "chiave", "northeurope" if classe is Azure else "m", 2.0, client=client
    ), richieste


def _azure(corpo):
    return lambda _richiesta: httpx.Response(200, json=corpo)


async def test_azure_trascrive_in_italiano():
    azure, richieste = _servizio(
        Azure, _azure({"RecognitionStatus": "Success", "DisplayText": "Ciao."})
    )
    assert await azure.trascrivi(UN_SECONDO, "it", "polizza") == [("Ciao.", 0.0)]
    assert richieste[0].url.params["language"] == "it-IT"
    assert richieste[0].content.startswith(b"RIFF")


async def test_azure_sul_silenzio_non_dice_niente():
    azure, _ = _servizio(Azure, _azure({"RecognitionStatus": "InitialSilenceTimeout"}))
    assert await azure.trascrivi(UN_SECONDO, "it", "") == []


@pytest.mark.parametrize(
    "risponde",
    [
        _azure({"RecognitionStatus": "Error"}),
        lambda _r: httpx.Response(401),
        lambda _r: httpx.Response(429, headers={"retry-after": "60"}),
    ],
)
async def test_errori_di_azure(risponde):
    azure, _ = _servizio(Azure, risponde)
    with pytest.raises(ErroreRemoto):
        await azure.trascrivi(UN_SECONDO, "it", "")


class ModelloFinto:
    def __init__(self):
        self.usato = 0

    def transcribe(self, *_args, **_kwargs):
        self.usato += 1
        return iter([SimpleNamespace(text="Dal server.", no_speech_prob=0.0)]), None


async def _catena(monkeypatch, *remoti):
    locale = ModelloFinto()
    monkeypatch.setattr(servizi, "modello_whisper", lambda *_: locale)
    stt = WhisperVeloce(Impostazioni(), "it", remoti=remoti)
    frame = [f async for f in stt.run_stt(UN_SECONDO)]
    return [f.text for f in frame if isinstance(f, TranscriptionFrame)], locale.usato


async def test_al_telefono_prima_azure(monkeypatch):
    azure, _ = _servizio(Azure, _azure({"RecognitionStatus": "Success", "DisplayText": "Ciao."}))
    groq, chieste_a_groq = _servizio(Groq, lambda _r: httpx.Response(500))
    assert await _catena(monkeypatch, azure, groq) == (["Ciao."], 0)
    assert chieste_a_groq == []


async def test_se_azure_non_risponde_passa_a_groq(monkeypatch):
    azure, _ = _servizio(Azure, lambda _r: httpx.Response(503))
    corpo = {"segments": [{"text": " Ciao!", "no_speech_prob": 0.01}]}
    groq, _ = _servizio(Groq, lambda _r: httpx.Response(200, json=corpo))
    assert await _catena(monkeypatch, azure, groq) == (["Ciao!"], 0)


async def test_se_nessuno_risponde_trascrive_il_server(monkeypatch):
    azure, _ = _servizio(Azure, lambda _r: httpx.Response(503))
    groq, _ = _servizio(Groq, lambda _r: httpx.Response(503))
    assert await _catena(monkeypatch, azure, groq) == (["Dal server."], 1)


def test_ordine_per_entrata(monkeypatch):
    monkeypatch.setenv("VOCE_TRASCRIZIONE_TELEFONO", "groq")
    imp = Impostazioni.da_ambiente()
    assert imp.trascrizione_telefono == ["groq"]
    assert imp.trascrizione_sito == ["groq"]
    assert Impostazioni().trascrizione_telefono == ["azure", "groq"]
