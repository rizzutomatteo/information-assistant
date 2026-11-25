"""Il registro delle frasi: per ognuna, l'audio che Whisper ha sentito e il testo che ne ha capito.

Serve a trovare gli errori di riconoscimento prima di una dimostrazione: si riascolta la frase, si
legge cosa ha capito Whisper e si prova a correggere (prompt, modello, fine della frase). È acceso
solo se VOCE_REGISTRAZIONI indica una cartella; quando è acceso, la pagina e il saluto al telefono
dicono che la voce viene registrata.

    registrazioni/
      frasi.jsonl                          una riga per frase, la più recente in fondo
      2026-11-16/183501-voce-3fa2c1/       una cartella per chiamata: ora, canale, codice
        01.wav, 02.wav, …                  l'audio di ogni frase: PCM 16 bit, 16 kHz, mono
        chiamata.wav                       tutto quello che è arrivato dal microfono, scritto a
                                           fine chiamata: c'è anche quello che il VAD non ha
                                           preso per voce, e che quindi Whisper non ha mai sentito
"""

import asyncio
import json
import threading
import uuid
import wave
from datetime import datetime
from pathlib import Path

from loguru import logger
from pipecat.frames.frames import Frame, InputAudioRawFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

FREQUENZA = 16000
INDICE = "frasi.jsonl"


class Registro:
    """La cartella delle registrazioni, condivisa da tutte le chiamate."""

    def __init__(self, cartella: Path):
        self.cartella = cartella
        cartella.mkdir(parents=True, exist_ok=True)
        # Due chiamate insieme aggiungono righe allo stesso indice
        self._lucchetto = threading.Lock()

    def chiamata(self, canale: str, lingua: str) -> "RegistroChiamata":
        adesso = datetime.now()
        nome = f"{adesso:%H%M%S}-{canale}-{uuid.uuid4().hex[:6]}"
        return RegistroChiamata(self, self.cartella / f"{adesso:%Y-%m-%d}" / nome, canale, lingua)

    def aggiungi(self, riga: dict):
        with self._lucchetto, open(self.cartella / INDICE, "a", encoding="utf-8") as f:
            f.write(json.dumps(riga, ensure_ascii=False) + "\n")


class RegistroChiamata:
    """Le frasi di una chiamata, numerate nell'ordine in cui sono state dette."""

    def __init__(self, registro: Registro, cartella: Path, canale: str, lingua: str):
        self._registro = registro
        self.cartella = cartella
        self.canale = canale
        self.lingua = lingua
        self._frasi = 0

    def prossima(self) -> int:
        """Il numero della frase appena detta: si prende subito, prima di scrivere nel thread."""
        self._frasi += 1
        return self._frasi

    def salva(self, numero: int, audio: bytes, esito: str, capito: str = "", **dettagli) -> Path:
        """Scrive l'audio della frase e la sua riga nell'indice. Usa il disco: va in un thread."""
        file = self._scrivi(f"{numero:02d}.wav", audio, FREQUENZA)
        self._registro.aggiungi(
            {
                "quando": datetime.now().isoformat(timespec="seconds"),
                "chiamata": self.cartella.name,
                "frase": numero,
                "canale": self.canale,
                "lingua": self.lingua,
                "audio": file.relative_to(self._registro.cartella).as_posix(),
                "durata": round(len(audio) / 2 / FREQUENZA, 2),
                "esito": esito,
                "capito": capito,
                **dettagli,
            }
        )
        return file

    def salva_chiamata(self, audio: bytes, frequenza: int) -> Path:
        """Scrive tutto l'audio arrivato dal microfono. Usa il disco: va in un thread."""
        return self._scrivi("chiamata.wav", audio, frequenza)

    def _scrivi(self, nome: str, audio: bytes, frequenza: int) -> Path:
        self.cartella.mkdir(parents=True, exist_ok=True)
        file = self.cartella / nome
        with wave.open(str(file), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(frequenza)
            wav.writeframes(audio)
        return file


class AscoltoChiamata(FrameProcessor):
    """Tiene tutto l'audio che arriva dal microfono e a fine chiamata lo scrive nel registro.

    Va subito dopo l'ingresso del trasporto, prima del VAD: così c'è anche una frase che il VAD
    non ha preso per voce (per esempio un «Ciao» breve), che nel registro delle frasi non compare.
    """

    def __init__(self, registro: RegistroChiamata, **kwargs):
        super().__init__(**kwargs)
        self._registro = registro
        self._audio = bytearray()
        self._frequenza = FREQUENZA

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, InputAudioRawFrame) and frame.num_channels == 1:
            self._frequenza = frame.sample_rate
            self._audio.extend(frame.audio)
        await self.push_frame(frame, direction)

    async def cleanup(self):
        await super().cleanup()
        if not self._audio:
            return
        try:
            audio = bytes(self._audio)
            await asyncio.to_thread(self._registro.salva_chiamata, audio, self._frequenza)
        except OSError as e:
            logger.warning(f"{self}: audio della chiamata non registrato: {e}")
