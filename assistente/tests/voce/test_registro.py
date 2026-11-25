import json
import wave
from types import SimpleNamespace

import httpx
import pytest
from pipecat.frames.frames import InputAudioRawFrame, TranscriptionFrame
from pipecat.tests.utils import run_test

from assistente.config import Impostazioni
from assistente.server import crea_app
from assistente.sito.testi import TESTI
from assistente.voce import servizi
from assistente.voce.registro import INDICE, AscoltoChiamata, Registro
from assistente.voce.servizi import WhisperVeloce

UN_SECONDO = b"\x01\x00" * 16000


def _righe(cartella):
    return [json.loads(r) for r in (cartella / INDICE).read_text(encoding="utf-8").splitlines()]


def test_salva_audio_e_riga(tmp_path):
    chiamata = Registro(tmp_path).chiamata("telefono", "it")
    domanda = "Cos'è la franchigia?"
    file = chiamata.salva(chiamata.prossima(), UN_SECONDO, "capita", domanda, tempo=3.2)

    with wave.open(str(file)) as wav:
        assert (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) == (1, 2, 16000)
        assert wav.getnframes() == 16000
    [riga] = _righe(tmp_path)
    assert riga["audio"] == file.relative_to(tmp_path).as_posix()
    assert riga["audio"].endswith("-telefono-" + riga["chiamata"].rsplit("-", 1)[1] + "/01.wav")
    assert (riga["canale"], riga["lingua"], riga["frase"]) == ("telefono", "it", 1)
    assert (riga["esito"], riga["capito"], riga["durata"], riga["tempo"]) == (
        "capita",
        "Cos'è la franchigia?",
        1.0,
        3.2,
    )


def test_frasi_numerate_per_chiamata(tmp_path):
    registro = Registro(tmp_path)
    prima, seconda = registro.chiamata("voce", "it"), registro.chiamata("voce", "en")
    for chiamata in (prima, seconda, prima):
        chiamata.salva(chiamata.prossima(), UN_SECONDO, "capita")
    assert [(r["chiamata"], r["frase"]) for r in _righe(tmp_path)] == [
        (prima.cartella.name, 1),
        (seconda.cartella.name, 1),
        (prima.cartella.name, 2),
    ]


class ModelloFinto:
    """Whisper senza modello: restituisce i segmenti dati."""

    def __init__(self, *segmenti):
        self.segmenti = [SimpleNamespace(text=t, no_speech_prob=p) for t, p in segmenti]

    def transcribe(self, *_args, **_kwargs):
        return iter(self.segmenti), None


async def _trascrivi(monkeypatch, tmp_path, audio, *segmenti):
    monkeypatch.setattr(servizi, "modello_whisper", lambda *_: ModelloFinto(*segmenti))
    imp = Impostazioni(whisper_modello="small", whisper_beam=5)
    stt = WhisperVeloce(imp, "it", Registro(tmp_path).chiamata("voce", "it"))
    frame = [f async for f in stt.run_stt(audio)]
    return frame, _righe(tmp_path)


async def test_whisper_registra_quello_che_ha_capito(monkeypatch, tmp_path):
    frame, [riga] = await _trascrivi(
        monkeypatch, tmp_path, UN_SECONDO, (" Cos'è la franchigia?", 0.1), (" grazie", 0.9)
    )
    assert [f.text for f in frame if isinstance(f, TranscriptionFrame)] == ["Cos'è la franchigia?"]
    assert (riga["esito"], riga["capito"], riga["modello"], riga["beam"]) == (
        "capita",
        "Cos'è la franchigia?",
        "small",
        5,
    )
    # Il pezzo che Whisper ha preso per silenzio resta nel registro
    assert riga["segmenti"][1] == {"testo": "grazie", "silenzio": 0.9}
    assert "franchigia" in riga["prompt"]


@pytest.mark.parametrize(
    ("audio", "segmenti", "esito"),
    [
        (UN_SECONDO, [("Sottotitoli a cura di QTSS", 0.1)], "scartata"),
        (UN_SECONDO, [("boh", 0.8)], "vuota"),
        (UN_SECONDO[:3200], [], "troppo corta"),
    ],
)
async def test_whisper_registra_le_frasi_scartate(monkeypatch, tmp_path, audio, segmenti, esito):
    _frame, [riga] = await _trascrivi(monkeypatch, tmp_path, audio, *segmenti)
    assert riga["esito"] == esito


async def test_la_pagina_dice_se_la_voce_si_registra(tmp_path):
    for imp, registra in ((Impostazioni(), False), (Impostazioni(registrazioni=tmp_path), True)):
        app = crea_app(imp, precarica=False)
        trasporto = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=trasporto, base_url="http://v") as server:
            pagina = (await server.get("/")).text
        assert (TESTI["nota_registra"].it in pagina) is registra
        assert (TESTI["assistente_nota"].it in pagina) is not registra


def test_cartella_non_scrivibile_spegne_il_registro(tmp_path):
    file = tmp_path / "file"
    file.write_text("")
    # Una cartella dentro un file non si può creare: il server parte lo stesso, senza registro
    crea_app(Impostazioni(registrazioni=file / "registrazioni"), precarica=False)


async def test_ascolto_scrive_tutto_l_audio_della_chiamata(tmp_path):
    chiamata = Registro(tmp_path).chiamata("voce", "it")
    pezzo = InputAudioRawFrame(UN_SECONDO[:640], sample_rate=16000, num_channels=1)
    await run_test(
        AscoltoChiamata(chiamata),
        frames_to_send=[pezzo, pezzo],
        expected_down_frames=[InputAudioRawFrame, InputAudioRawFrame],
    )
    with wave.open(str(chiamata.cartella / "chiamata.wav")) as wav:
        assert (wav.getframerate(), wav.getnframes()) == (16000, 640)
