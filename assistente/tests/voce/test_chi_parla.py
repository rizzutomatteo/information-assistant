import numpy as np
import pytest
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    InputAudioRawFrame,
    VADParamsUpdateFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.tests.utils import run_test

from assistente.voce import chi_parla
from assistente.voce.chi_parla import Frase, SoloChiChiama, VoceDiChiChiama, solo_voce
from assistente.voce.registro import Registro

FREQUENZA = 16000


def _tono(hz: float, secondi: float, ampiezza: float = 0.3) -> bytes:
    t = np.arange(int(FREQUENZA * secondi)) / FREQUENZA
    return (ampiezza * 32767 * np.sin(2 * np.pi * hz * t)).astype(np.int16).tobytes()


# Due «persone»: un tono grave e uno acuto
IO, ALTRO = 200, 1500


class ModelloFinto:
    """Al posto di CAM++: l'impronta dice solo se il tono è grave o acuto."""

    class Flusso:
        def accept_waveform(self, _frequenza, campioni):
            self.campioni = np.asarray(campioni)

        def input_finished(self):
            pass

    def create_stream(self):
        return self.Flusso()

    def compute(self, flusso):
        passaggi_per_zero = np.mean(np.abs(np.diff(np.sign(flusso.campioni))) > 0)
        acuto = passaggi_per_zero > 2 * 800 / FREQUENZA
        return [0.0, 1.0] if acuto else [1.0, 0.0]


@pytest.fixture
def modello(monkeypatch):
    finto = ModelloFinto()
    monkeypatch.setattr(chi_parla, "estrattore", lambda _cartella: finto)
    return finto


def _frase(hz: float, secondi: float = 1.0) -> list:
    audio = _tono(hz, secondi)
    pezzi = [audio[i : i + 640] for i in range(0, len(audio), 640)]
    return [
        VADUserStartedSpeakingFrame(),
        *[InputAudioRawFrame(audio=p, sample_rate=FREQUENZA, num_channels=1) for p in pezzi],
        VADUserStoppedSpeakingFrame(),
    ]


def _passate(frames) -> int:
    return sum(isinstance(f, VADUserStoppedSpeakingFrame) for f in frames)


def test_solo_voce_toglie_il_silenzio():
    audio = _tono(IO, 0.5) + bytes(FREQUENZA)  # mezzo secondo di voce, uno di silenzio
    assert len(solo_voce(audio)) == len(_tono(IO, 0.5))


def test_niente_impronta_con_troppo_poca_voce(modello):
    assert Frase(modello, _tono(IO, 0.1)).impronta is None
    frase = Frase(modello, _tono(IO, 1.0))
    assert frase.impronta is not None and frase.volume > 0.8


def test_il_riferimento_viene_da_una_frase_forte_detta_ad_assistente_zitto(modello):
    voce = VoceDiChiChiama(0.55)
    voce.impara(Frase(modello, _tono(IO, 1.0)), assistente_parlava=True)
    assert not voce.nota
    voce.impara(Frase(modello, _tono(IO, 1.0, ampiezza=0.003)), assistente_parlava=False)
    assert not voce.nota
    voce.impara(Frase(modello, _tono(IO, 1.0)), assistente_parlava=False)
    assert voce.nota
    assert voce.e_sua(Frase(modello, _tono(IO, 1.0)))
    assert not voce.e_sua(Frase(modello, _tono(ALTRO, 1.0)))
    # Troppo poca voce per dirlo: passa, se è rumore lo scarta Whisper
    assert voce.e_sua(Frase(modello, _tono(ALTRO, 0.1)))


async def test_passano_solo_le_frasi_di_chi_chiama(modello, tmp_path):
    registro = Registro(tmp_path).chiamata("telefono", "it")
    filtro = SoloChiChiama(tmp_path, 0.55, VADParams(), registro)
    giu, su = await run_test(filtro, frames_to_send=_frase(IO) + _frase(ALTRO) + _frase(IO, 2.0))
    assert _passate(giu) == 2
    # Le frasi che passano arrivano intere e in ordine: inizio, audio, fine
    tipi = [type(f) for f in giu if not isinstance(f, InputAudioRawFrame)]
    assert tipi == [VADUserStartedSpeakingFrame, VADUserStoppedSpeakingFrame] * 2
    secondi = sum(len(f.audio) for f in giu if isinstance(f, InputAudioRawFrame)) / 2 / FREQUENZA
    assert secondi == pytest.approx(3.0, abs=0.05)
    # Conosciuto il volume di chi chiama, la soglia del VAD sale
    aggiornamenti = [f for f in su if isinstance(f, VADParamsUpdateFrame)]
    assert aggiornamenti and aggiornamenti[0].params.min_volume > VADParams().min_volume
    # L'altra voce resta nel registro, con quanto somigliava
    assert (registro.cartella / "01.wav").exists()


async def test_senza_riferimento_passa_tutto(modello, tmp_path):
    # La prima frase arriva mentre l'assistente parla: non fa da riferimento
    frames = [BotStartedSpeakingFrame(), *_frase(IO), *_frase(ALTRO)]
    giu, _ = await run_test(SoloChiChiama(tmp_path, 0.55, VADParams()), frames_to_send=frames)
    assert _passate(giu) == 2
