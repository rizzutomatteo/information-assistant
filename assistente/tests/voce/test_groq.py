import io
import wave
from types import SimpleNamespace

import httpx
import pytest
from pipecat.frames.frames import TranscriptionFrame

from assistente.config import Impostazioni
from assistente.voce import servizi
from assistente.voce.groq import Groq
from assistente.voce.remoti import ErroreRemoto, wav
from assistente.voce.servizi import WhisperVeloce

UN_SECONDO = b"\x01\x00" * 16000


def _groq(risponde) -> tuple[Groq, list[httpx.Request]]:
    richieste = []

    def gestore(richiesta: httpx.Request) -> httpx.Response:
        richieste.append(richiesta)
        return risponde(richiesta)

    client = httpx.AsyncClient(base_url="https://groq", transport=httpx.MockTransport(gestore))
    return Groq("chiave", "whisper-large-v3", 2.0, client=client), richieste


def _segmenti(*pezzi):
    corpo = {"segments": [{"text": t, "no_speech_prob": p} for t, p in pezzi]}
    return lambda _richiesta: httpx.Response(200, json=corpo)


def test_wav_della_frase():
    with wave.open(io.BytesIO(wav(UN_SECONDO))) as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (1, 2, 16000)
        assert w.getnframes() == 16000


async def test_trascrive_con_lingua_e_prompt():
    groq, richieste = _groq(_segmenti((" Le mie informazioni.", 0.01)))
    assert await groq.trascrivi(UN_SECONDO, "it", "polizza") == [(" Le mie informazioni.", 0.01)]
    corpo = richieste[0].content
    for campo in (b"whisper-large-v3", b'name="language"', b"polizza", b"verbose_json"):
        assert campo in corpo
    assert richieste[0].url.path.endswith("/audio/transcriptions")


async def test_troppe_richieste_mette_in_pausa():
    groq, richieste = _groq(lambda _r: httpx.Response(429, headers={"retry-after": "60"}))
    with pytest.raises(ErroreRemoto):
        await groq.trascrivi(UN_SECONDO, "it", "")
    # Finché dura la pausa non si chiede nemmeno: si va subito in locale
    with pytest.raises(ErroreRemoto):
        await groq.trascrivi(UN_SECONDO, "it", "")
    assert len(richieste) == 1


@pytest.mark.parametrize(
    "risponde",
    [
        lambda _r: httpx.Response(500),
        lambda r: (_ for _ in ()).throw(httpx.ReadTimeout("lento", request=r)),
    ],
)
async def test_errori_di_groq(risponde):
    groq, _ = _groq(risponde)
    with pytest.raises(ErroreRemoto):
        await groq.trascrivi(UN_SECONDO, "it", "")


class ModelloFinto:
    """Whisper locale senza modello: conta le volte che lo si usa."""

    def __init__(self, testo):
        self.testo, self.usato = testo, 0

    def transcribe(self, *_args, **_kwargs):
        self.usato += 1
        return iter([SimpleNamespace(text=self.testo, no_speech_prob=0.0)]), None


async def _frasi(monkeypatch, groq):
    locale = ModelloFinto("Le mie polizie.")
    monkeypatch.setattr(servizi, "modello_whisper", lambda *_: locale)
    stt = WhisperVeloce(Impostazioni(), "it", remoti=[groq] if groq else [])
    frame = [f async for f in stt.run_stt(UN_SECONDO)]
    return [f.text for f in frame if isinstance(f, TranscriptionFrame)], locale.usato


async def test_con_groq_il_modello_locale_non_lavora(monkeypatch):
    groq, _ = _groq(_segmenti((" Le mie informazioni.", 0.01), (" Grazie.", 0.9)))
    assert await _frasi(monkeypatch, groq) == (["Le mie informazioni."], 0)


async def test_se_groq_non_risponde_trascrive_in_locale(monkeypatch):
    groq, _ = _groq(lambda _r: httpx.Response(503))
    assert await _frasi(monkeypatch, groq) == (["Le mie polizie."], 1)


async def test_senza_groq_solo_in_locale(monkeypatch):
    assert await _frasi(monkeypatch, None) == (["Le mie polizie."], 1)
