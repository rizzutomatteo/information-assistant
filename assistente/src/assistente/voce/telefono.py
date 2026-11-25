"""Le telefonate dal numero vero: Asterisk passa l'audio al server della voce in WebSocket.

    telefono → operatore VoIP (SIP) → Asterisk → Dial(WebSocket/voce/c(slin16))
             → ws://127.0.0.1:8002/telefono → la stessa pipeline delle chiamate dal browser

Il protocollo è quello di chan_websocket (Asterisk 22.6 e successivi), con gli eventi in JSON:

- audio nei messaggi binari, in entrambe le direzioni: slin16, cioè PCM a 16 bit, 16 kHz, mono,
  senza intestazioni, a pezzi di 20 ms (640 byte);
- eventi di Asterisk nei messaggi di testo, per esempio {"event": "MEDIA_START", "format":
  "slin16", "optimal_frame_size": 640, …} o, per un tasto premuto, {"event": "DTMF_END",
  "digit": "5"};
- comandi verso Asterisk nei messaggi di testo, per esempio {"command": "FLUSH_MEDIA"}.

Asterisk si presenta con il segreto condiviso (VOCE_TELEFONO_SEGRETO) in HTTP Basic.
"""

import base64
import binascii
import hmac
import json

from loguru import logger
from pipecat.audio.dtmf.types import KeypadEntry
from pipecat.frames.frames import (
    AudioRawFrame,
    Frame,
    InputAudioRawFrame,
    InputDTMFFrame,
    InterruptionFrame,
)
from pipecat.serializers.base_serializer import FrameSerializer

FREQUENZA = 16000
PEZZO = 640  # byte: 20 ms di slin16, il pezzo che Asterisk si aspetta (optimal_frame_size)
UTENTE = "asterisk"


def credenziali_valide(intestazione: str | None, segreto: str) -> bool:
    """Vero se l'intestazione Authorization è «Basic» con utente asterisk e il segreto giusto."""
    if not segreto or not intestazione or not intestazione.startswith("Basic "):
        return False
    try:
        utente, _, password = base64.b64decode(intestazione[6:]).decode().partition(":")
    except (binascii.Error, UnicodeDecodeError):
        return False
    return utente == UTENTE and hmac.compare_digest(password.encode(), segreto.encode())


class SerializzatoreAsterisk(FrameSerializer):
    """Traduce tra i messaggi di chan_websocket e i frame di Pipecat."""

    def __init__(self):
        super().__init__(
            FrameSerializer.InputParams(
                audio_in_sample_rate=FREQUENZA, audio_out_sample_rate=FREQUENZA
            )
        )

    async def serialize(self, frame: Frame) -> str | bytes | None:
        if isinstance(frame, InterruptionFrame):
            # L'utente parla sopra l'assistente: Asterisk butta l'audio che ha ancora in coda
            await self._reset_audio_out()
            return json.dumps({"command": "FLUSH_MEDIA"})
        if isinstance(frame, AudioRawFrame):
            return await self._resample_audio_out(frame) or None
        # I messaggi per la chat (trascrizione, stati, fonti): al telefono non c'è una chat
        return None

    async def deserialize(self, data: str | bytes) -> Frame | None:
        if isinstance(data, bytes):
            audio = await self._resample_audio_in(data)
            if not audio:
                return None
            return InputAudioRawFrame(audio=audio, num_channels=1, sample_rate=self._sample_rate)
        try:
            evento = json.loads(data)
        except json.JSONDecodeError:
            logger.warning("Asterisk: messaggio di testo non JSON (manca control_message_format?)")
            return None
        if evento.get("event") == "DTMF_END":
            # Un tasto del tastierino (il PIN): l'Assistente lo usa solo se lo sta aspettando
            try:
                return InputDTMFFrame(button=KeypadEntry(evento.get("digit")))
            except ValueError:
                return None
        if evento.get("event") == "MEDIA_START" and evento.get("format") != "slin16":
            logger.warning(f"Asterisk manda audio {evento.get('format')}, non slin16")
        return None
