"""Whisper e Piper, caricati una volta sola e condivisi da tutte le chiamate.

I servizi di Pipecat caricano il modello a ogni istanza, cioè a ogni chiamata: per Whisper
`small` sono secondi di attesa e circa 1 GB di memoria in più per chiamata. Qui i modelli si
caricano all'avvio del server e ogni chiamata usa gli stessi.

Sulla CPU il tempo di Whisper dipende poco dalla lunghezza della frase: l'encoder lavora sempre
su una finestra di 30 secondi, e per una domanda di pochi secondi è quasi tutto il costo. Per
questo si può tenere beam_size=5 (cinque ipotesi in parallelo, più preciso): su una frase breve
costa quanto beam_size=1. Misure sul server del progetto (4 core Arm, a riposo): `small` circa
3,5 s per frase, `base` circa 1,4 s.

Con le chiavi dei servizi remoti (remoti.py) la frase va prima a loro: dal sito a Whisper
large-v3 su Groq, al telefono ad Azure Speech e poi a Groq. Il modello locale resta caricato e
trascrive le frasi a cui nessuno risponde.
"""

import asyncio
import time
from collections.abc import AsyncGenerator, Sequence
from functools import cache
from pathlib import Path

import numpy as np
from faster_whisper import WhisperModel
from loguru import logger
from pipecat.frames.frames import ErrorFrame, Frame, TranscriptionFrame
from pipecat.services.piper.tts import PiperTTSService
from pipecat.services.tts_service import TTSService
from pipecat.services.whisper.stt import WhisperSTTService
from pipecat.transcriptions.language import Language
from pipecat.utils.time import time_now_iso8601
from piper import PiperVoice
from piper.download_voices import download_voice

from assistente.config import LINGUE, Impostazioni, Lingua
from assistente.voce.chi_parla import estrattore
from assistente.voce.ponte import e_rumore
from assistente.voce.registro import RegistroChiamata
from assistente.voce.remoti import ErroreRemoto, ServizioRemoto

# Sotto questa durata (in secondi) non c'è una domanda: è un colpo di tosse o un «ehm»
DURATA_MINIMA = 0.3


@cache
def modello_whisper(nome: str, thread: int) -> WhisperModel:
    logger.info(f"Carico Whisper «{nome}» ({thread} thread)")
    return WhisperModel(nome, device="cpu", compute_type="int8", cpu_threads=thread)


@cache
def voce_piper(nome: str, cartella: Path) -> PiperVoice:
    percorso = cartella / f"{nome}.onnx"
    if not percorso.exists():
        logger.info(f"Scarico la voce di Piper «{nome}» in {cartella}")
        cartella.mkdir(parents=True, exist_ok=True)
        download_voice(nome, cartella)
    logger.info(f"Carico la voce di Piper «{nome}»")
    return PiperVoice.load(percorso)


def carica_modelli(imp: Impostazioni):
    """All'avvio del server, così la prima chiamata non aspetta: Whisper, una voce per lingua e
    il modello delle impronte della voce."""
    modello_whisper(imp.whisper_modello, imp.whisper_thread)
    for lingua in LINGUE:
        voce_piper(imp.voce(lingua), imp.piper_cartella)
    if imp.solo_chi_chiama:
        estrattore(imp.impronte_cartella)


class WhisperVeloce(WhisperSTTService):
    """Whisper nella lingua della chiamata, con il modello condiviso e le impostazioni per la CPU.

    Il modello è uno solo per tutte le lingue: cambia solo quella che gli si chiede di sentire.
    Con dei servizi remoti, la frase va a loro nell'ordine dato, e il modello locale fa da riserva.
    Con un registro, ogni frase ricevuta finisce nel registro con il testo capito (registro.py).
    """

    def __init__(
        self,
        imp: Impostazioni,
        lingua: Lingua = "it",
        registro: RegistroChiamata | None = None,
        remoti: Sequence[ServizioRemoto] = (),
        **kwargs,
    ):
        # Servono già a _load(), che il costruttore della classe madre chiama
        self._imp = imp
        self._lingua = lingua
        self._registro = registro
        self._remoti = list(remoti)
        super().__init__(
            device="cpu",
            compute_type="int8",
            settings=WhisperSTTService.Settings(
                model=imp.whisper_modello, language=Language(lingua), no_speech_prob=0.4
            ),
            **kwargs,
        )

    def _load(self):
        self._model = modello_whisper(self._imp.whisper_modello, self._imp.whisper_thread)

    async def run_stt(self, audio: bytes) -> AsyncGenerator[Frame, None]:
        campioni = np.frombuffer(audio, dtype=np.int16).astype(np.float32) / 32768.0
        if len(campioni) < 16000 * DURATA_MINIMA:
            await self._registra(audio, "troppo corta")
            return

        prompt = self._imp.prompt(self._lingua)

        def trascrivi():
            segmenti, _ = self._model.transcribe(
                campioni,
                language=self._lingua,
                beam_size=self._imp.whisper_beam,
                without_timestamps=True,
                condition_on_previous_text=False,
                initial_prompt=prompt or None,
            )
            # Il generatore decodifica man mano: va consumato qui, nel thread
            return [(s.text, s.no_speech_prob) for s in segmenti]

        await self.start_processing_metrics()
        inizio = time.monotonic()
        modello, ricadute = self._imp.whisper_modello, []
        try:
            segmenti = None
            for servizio in self._remoti:
                try:
                    segmenti = await servizio.trascrivi(audio, self._lingua, prompt)
                    modello = servizio.nome
                    break
                except ErroreRemoto as e:
                    ricadute.append(f"{servizio.nome}: {e}")
                    logger.warning(f"{self}: {servizio.nome} non ha risposto ({e})")
            if segmenti is None:
                segmenti = await asyncio.to_thread(trascrivi)
        except Exception as e:  # noqa: BLE001 - un errore di Whisper non deve chiudere la chiamata
            logger.error(f"{self}: trascrizione fallita: {type(e).__name__}")
            await self._registra(audio, "errore")
            yield ErrorFrame(f"trascrizione fallita: {type(e).__name__}")
            return
        finally:
            await self.stop_processing_metrics()

        testo = " ".join(t.strip() for t, silenzio in segmenti if silenzio < 0.4).strip()
        esito = "vuota" if not testo else "scartata" if e_rumore(testo) else "capita"
        await self._registra(
            audio,
            esito,
            testo,
            modello=modello,
            ricaduta="; ".join(ricadute) or None,
            tempo=round(time.monotonic() - inizio, 2),
            # Anche i pezzi tolti perché Whisper li crede silenzio: a volte erano parole vere
            segmenti=[{"testo": t.strip(), "silenzio": round(s, 2)} for t, s in segmenti],
        )
        if testo:
            # Nel log solo la lunghezza: la frase può contenere dati personali
            logger.debug(f"{self}: trascritti {len(testo)} caratteri")
            yield TranscriptionFrame(
                testo, self._user_id, time_now_iso8601(), Language(self._lingua)
            )

    async def _registra(self, audio: bytes, esito: str, capito: str = "", **dettagli):
        """Mette la frase nel registro, se c'è. Un disco pieno non deve fermare la chiamata."""
        if self._registro is None:
            return
        numero = self._registro.prossima()
        try:
            impostazioni = {
                "modello": self._imp.whisper_modello,
                "beam": self._imp.whisper_beam,
                "prompt": self._imp.prompt(self._lingua),
            }
            await asyncio.to_thread(
                self._registro.salva, numero, audio, esito, capito, **(impostazioni | dettagli)
            )
        except OSError as e:
            logger.warning(f"{self}: frase {numero} non registrata: {e}")


class VocePiper(PiperTTSService):
    """Piper con la voce condivisa della lingua della chiamata.

    Il costruttore di PiperTTSService carica la voce dal disco: qui si salta e si usa quella già
    in memoria. La sintesi (run_tts) resta quella di Pipecat.
    """

    def __init__(self, imp: Impostazioni, lingua: Lingua = "it", **kwargs):
        voce = imp.voce(lingua)
        TTSService.__init__(
            self,
            push_start_frame=True,
            push_stop_frames=True,
            settings=PiperTTSService.Settings(
                model=None,
                voice=voce,
                language=None,
                speaker_id=None,
                length_scale=imp.ritmo,
                noise_scale=None,
                noise_w_scale=None,
            ),
            **kwargs,
        )
        self._voice = voce_piper(voce, imp.piper_cartella)
