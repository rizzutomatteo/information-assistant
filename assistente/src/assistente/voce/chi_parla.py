"""Quando parla chi chiama, e solo lui: le altre voci della stanza non arrivano a Whisper.

In un'aula, mentre chi chiama parla, altre persone commentano, ridono, tossiscono, e in fondo
c'è brusio. Il VAD (Silero) sente tutto come voce: senza le difese di questo modulo l'assistente
risponderebbe anche agli altri, smetterebbe di parlare ogni volta che qualcuno apre bocca, e con
il brusio la frase non finirebbe mai. Le difese sono due.

1. Il volume. Chi chiama è il più vicino al microfono, quindi il più forte. Quando si conosce il
   suo volume, il VAD conta come voce solo ciò che gli sta al massimo MARGINE_VOLUME sotto: il
   brusio e le voci lontane non tengono aperta la frase, che finisce quando chi chiama tace.

2. L'impronta della voce. Ogni voce ne ha una: 512 numeri che un modello piccolo (CAM++ di
   WeSpeaker, 29 MB; sulla CPU del server circa 0,1 s per 3 secondi di voce) calcola
   dall'audio. Due frasi della stessa persona danno impronte vicine (somiglianza coseno verso
   1), due persone diverse impronte lontane (verso 0). La prima frase forte detta mentre
   l'assistente tace è di chi chiama: la sua impronta fa da riferimento. Dopo passano solo le
   frasi che gli somigliano almeno quanto la soglia, e quelle sicure affinano riferimento e
   volume.

Una frase che inizia resta qui (l'inizio e il suo audio) finché non si sa di chi è: dopo
DECIDI_DOPO secondi, o alla fine se è più corta. Solo allora va avanti, a Whisper e
all'Assistente, che se stava parlando si interrompe; se è di un altro si butta.
"""

import asyncio
import hashlib
import urllib.request
from functools import cache
from pathlib import Path

import numpy as np
import sherpa_onnx
from loguru import logger
from pipecat.audio.utils import calculate_audio_volume
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    Frame,
    InputAudioRawFrame,
    VADParamsUpdateFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from assistente.voce.registro import RegistroChiamata

MODELLO = "wespeaker_en_voxceleb_CAM++.onnx"
# Lo specchio su Hugging Face, fermo a una versione: il 19/11/2026 sherpa-onnx ha sostituito il
# file con un altro dello stesso nome, su cui la soglia della voce (soglia_voce) non è misurata
URL_MODELLO = (
    "https://huggingface.co/csukuangfj/speaker-embedding-models/resolve/"
    "0743f301363dec56491a490f6d6cbc9d67f9a3bf/wespeaker_en_voxceleb_CAM%2B%2B.onnx"
)
# Dal checksum.txt della release originale: un file diverso non si carica
SHA256_MODELLO = "c46fad10b5f81e1aa4a60c162714208577093655076c5450f8c469e522ec54ef"

FREQUENZA = 16000
PEZZO = 320  # 20 ms: la frase si guarda a pezzi, per tenere solo quelli con la voce
# Della frase si tengono solo i pezzi al massimo tanti dB sotto il più forte (e sopra il
# fruscio): chi chiama è il più vicino, quindi una voce più debole sotto la sua, se c'è, non entra
# nell'impronta e non abbassa il volume
SOTTO_IL_PICCO = 15.0
FRUSCIO = -55.0
# Il VAD si accorge della voce con qualche decimo di secondo di ritardo: l'inizio della frase è
# nell'audio di poco prima
PRIMA_DELLA_FRASE = 0.5
# Secondi di voce sotto cui l'impronta non è affidabile (un «Ciao» ne ha circa 0,3)
VOCE_MINIMA = 0.25
# Secondi di frase dopo cui si prova a decidere senza aspettarne la fine, così chi chiama può
# interrompere l'assistente quasi subito. Con poca voce l'impronta è meno sicura: per decidere
# presto ne serve almeno VOCE_PRESTO, e una somiglianza di MARGINE_SICURO sopra la soglia
DECIDI_DOPO = 0.8
VOCE_PRESTO = 0.5
# Anche il riferimento impara solo dalle frasi sicure: una frase passata per poco può avere
# dentro anche un'altra voce, che a poco a poco lo sposterebbe
MARGINE_SICURO = 0.1

# Il volume come lo misura Pipecat: loudness da 0 (-110 LUFS) a 1 (-10 LUFS), quindi 0,1 = 10 dB.
# Il primo riferimento deve essere forte almeno quanto VOLUME_RIFERIMENTO (-40 LUFS): chi chiama
# al telefono o al computer sta intorno a 0,85, il brusio di una stanza sotto 0,65
VOLUME_RIFERIMENTO = 0.7
MARGINE_VOLUME = 0.15
# Quanto pesa il volume del blocco nuovo (32 ms) nella media mobile del VAD. Con lo 0,2 di Pipecat
# il volume di un «Ciao» breve arriva alla soglia quando la parola è già finita
LIVELLAMENTO = 0.5


class VADPronto(SileroVADAnalyzer):
    """Silero con il volume che segue la voce più in fretta: prende anche i «Ciao» brevi."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._smoothing_factor = LIVELLAMENTO


@cache
def estrattore(cartella: Path) -> sherpa_onnx.SpeakerEmbeddingExtractor:
    """Il modello delle impronte, uno per tutte le chiamate; la prima volta si scarica."""
    percorso = cartella / MODELLO
    if not percorso.exists():
        logger.info(f"Scarico il modello delle impronte della voce in {cartella}")
        cartella.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(URL_MODELLO, timeout=120) as risposta:
            dati = risposta.read()
        if hashlib.sha256(dati).hexdigest() != SHA256_MODELLO:
            raise RuntimeError(f"{MODELLO}: il file scaricato non è quello atteso")
        percorso.write_bytes(dati)
    logger.info("Carico il modello delle impronte della voce")
    config = sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(percorso), num_threads=1)
    return sherpa_onnx.SpeakerEmbeddingExtractor(config)


def solo_voce(audio: bytes) -> bytes:
    """I pezzi della frase con la voce: il silenzio e il fruscio falsano impronta e volume."""
    campioni = np.frombuffer(audio, dtype=np.int16)
    pezzi = campioni[: len(campioni) // PEZZO * PEZZO].reshape(-1, PEZZO)
    if not len(pezzi):
        return b""
    energia = (pezzi.astype(np.float32) / 32768) ** 2
    livello = 10 * np.log10(energia.mean(axis=1) + 1e-12)
    soglia = max(FRUSCIO, livello.max() - SOTTO_IL_PICCO)
    return pezzi[livello > soglia].tobytes()


class Frase:
    """L'impronta e il volume di una frase. Il calcolo usa la CPU: va fatto in un thread."""

    def __init__(self, modello: sherpa_onnx.SpeakerEmbeddingExtractor, audio: bytes):
        voce = solo_voce(audio)
        self.secondi = len(voce) / 2 / FREQUENZA
        self.impronta: np.ndarray | None = None
        self.volume: float | None = None
        if self.secondi < VOCE_MINIMA:
            return
        flusso = modello.create_stream()
        flusso.accept_waveform(FREQUENZA, np.frombuffer(voce, dtype=np.int16) / 32768)
        flusso.input_finished()
        vettore = np.array(modello.compute(flusso), dtype=np.float32)
        self.impronta = vettore / np.linalg.norm(vettore)
        # La loudness si misura su blocchi da 400 ms: con meno voce non c'è
        if self.secondi >= 0.4:
            self.volume = calculate_audio_volume(voce, FREQUENZA)


class VoceDiChiChiama:
    """Ciò che si sa della voce di chi chiama: impronta di riferimento e volume."""

    def __init__(self, soglia: float):
        self.soglia = soglia
        self._somma: np.ndarray | None = None
        self._volumi: list[float] = []

    @property
    def nota(self) -> bool:
        return self._somma is not None

    @property
    def volume(self) -> float | None:
        return float(np.mean(self._volumi)) if self._volumi else None

    def somiglianza(self, frase: Frase) -> float | None:
        if self._somma is None or frase.impronta is None:
            return None
        return float(frase.impronta @ (self._somma / np.linalg.norm(self._somma)))

    def e_sua(self, frase: Frase) -> bool:
        """Senza riferimento, o con troppo poca voce per dirlo (un «sì» brevissimo), passa: se è
        solo rumore la scarta Whisper."""
        valore = self.somiglianza(frase)
        return valore is None or valore >= self.soglia

    def e_sicuramente_sua(self, frase: Frase) -> bool:
        """Per decidere prima della fine della frase, e per imparare: serve più somiglianza."""
        valore = self.somiglianza(frase)
        return valore is not None and valore >= self.soglia + MARGINE_SICURO

    def impara(self, frase: Frase, assistente_parlava: bool):
        """Aggiunge una frase di chi chiama. Fa da primo riferimento solo se è forte e detta
        mentre l'assistente taceva: chi chiama di solito aspetta la fine del saluto ed è il più
        vicino al microfono, mentre un commento o il brusio possono arrivare in ogni momento."""
        if frase.impronta is None:
            return
        if self._somma is None:
            if assistente_parlava or (frase.volume or 0) < VOLUME_RIFERIMENTO:
                return
            self._somma = frase.impronta.copy()
        elif self.e_sicuramente_sua(frase):
            self._somma = self._somma + frase.impronta
        else:
            return
        if frase.volume is not None:
            self._volumi.append(frase.volume)


class SoloChiChiama(FrameProcessor):
    """Tra il VAD e Whisper: lascia andare avanti solo le frasi con la voce di chi chiama.

    Trattiene l'inizio della frase e il suo audio finché non sa di chi è; poi li manda avanti
    nello stesso ordine, oppure li butta. Quando conosce il volume di chi chiama alza la soglia
    del VAD (con un VADParamsUpdateFrame verso il VAD, a monte). Gli altri frame passano subito.
    """

    def __init__(
        self,
        cartella: Path,
        soglia: float,
        vad: VADParams,
        registro: RegistroChiamata | None = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._modello = estrattore(cartella)
        self._voce = VoceDiChiChiama(soglia)
        self._vad = vad
        self._volume_di_partenza = vad.min_volume
        self._registro = registro
        self._assistente_parla = False
        self._in_frase = False
        self._parlava_all_inizio = False
        self._prima = bytearray()  # l'ultimo mezzo secondo fuori dalle frasi
        self._audio = bytearray()
        # I frame trattenuti della frase in corso; None quando la frase va già avanti
        self._trattenuti: list[tuple[Frame, FrameDirection]] | None = None
        self._provato_presto = False

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, BotStartedSpeakingFrame):
            self._assistente_parla = True
        elif isinstance(frame, BotStoppedSpeakingFrame):
            self._assistente_parla = False

        if isinstance(frame, VADUserStartedSpeakingFrame):
            self._in_frase, self._audio, self._provato_presto = True, self._prima, False
            self._prima = bytearray()
            self._parlava_all_inizio = self._assistente_parla
            if self._voce.nota:
                self._trattenuti = [(frame, direction)]
            else:
                self._trattenuti = None
                await self.push_frame(frame, direction)
        elif isinstance(frame, InputAudioRawFrame) and not self._in_frase:
            self._prima.extend(frame.audio)
            del self._prima[: max(0, len(self._prima) - int(PRIMA_DELLA_FRASE * FREQUENZA) * 2)]
            await self.push_frame(frame, direction)
        elif isinstance(frame, InputAudioRawFrame):
            self._audio.extend(frame.audio)
            if self._trattenuti is None:
                await self.push_frame(frame, direction)
            else:
                self._trattenuti.append((frame, direction))
                await self._prova_presto()
        elif isinstance(frame, VADUserStoppedSpeakingFrame) and self._in_frase:
            await self._fine_frase(frame, direction)
        else:
            await self.push_frame(frame, direction)

    async def _prova_presto(self):
        """Con DECIDI_DOPO secondi di frase si prova a dire se è di chi chiama. Se non somiglia
        si aspetta la fine: con tutta la frase l'impronta è più sicura."""
        if (
            self._provato_presto
            or len(self._audio) < (PRIMA_DELLA_FRASE + DECIDI_DOPO) * FREQUENZA * 2
        ):
            return
        self._provato_presto = True
        frase = await asyncio.to_thread(Frase, self._modello, bytes(self._audio))
        if frase.secondi >= VOCE_PRESTO and self._voce.e_sicuramente_sua(frase):
            logger.debug(f"{self}: voce di chi chiama ({_num(self._voce.somiglianza(frase))})")
            await self._lascia_andare()

    async def _fine_frase(self, frame: Frame, direction: FrameDirection):
        self._in_frase = False
        audio = bytes(self._audio)
        frase = await asyncio.to_thread(Frase, self._modello, audio)
        if self._trattenuti is not None and not self._voce.e_sua(frase):
            valore = self._voce.somiglianza(frase)
            # Nel log solo quanto somiglia: mai l'audio o il testo
            logger.info(f"{self}: frase di un'altra voce scartata (somiglianza {_num(valore)})")
            self._trattenuti = None
            await self._registra(audio, valore)
            return
        await self._lascia_andare()
        await self.push_frame(frame, direction)
        self._voce.impara(frase, self._parlava_all_inizio)
        await self._segui_volume()

    async def _lascia_andare(self):
        trattenuti, self._trattenuti = self._trattenuti or [], None
        for frame, direction in trattenuti:
            await self.push_frame(frame, direction)

    async def _segui_volume(self):
        """La soglia del VAD MARGINE_VOLUME sotto la voce di chi chiama, mai sotto quella di
        partenza. Si cambia solo tra una frase e l'altra: il VAD, con i parametri nuovi, riparte
        dal silenzio."""
        if self._voce.volume is None:
            return
        soglia = round(max(self._volume_di_partenza, self._voce.volume - MARGINE_VOLUME), 2)
        if soglia == self._vad.min_volume:
            return
        self._vad = self._vad.model_copy(update={"min_volume": soglia})
        logger.debug(f"{self}: soglia di volume del VAD a {soglia}")
        await self.push_frame(VADParamsUpdateFrame(params=self._vad), FrameDirection.UPSTREAM)

    async def _registra(self, audio: bytes, valore: float | None):
        if self._registro is None:
            return
        numero = self._registro.prossima()
        try:
            await asyncio.to_thread(
                self._registro.salva, numero, audio, "altra voce", somiglianza=_num(valore)
            )
        except OSError as e:
            logger.warning(f"{self}: frase {numero} non registrata: {e}")


def _num(valore: float | None) -> float | None:
    return None if valore is None else round(valore, 2)
