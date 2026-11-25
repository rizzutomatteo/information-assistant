"""Una chiamata di prova, senza browser né microfono.

Fa quello che farebbe una persona: chiama il server della voce in WebRTC, aspetta il saluto,
dice le domande (sintetizzate con Piper), ascolta le risposte. Alla fine trascrive con Whisper
tutto quello che ha detto l'assistente e misura i tempi:

- «prima voce»: dalla fine della domanda al primo suono dell'assistente (attesa o risposta);
- «risposta»: dalla fine della domanda al messaggio con la risposta sul canale dati.

    prova-chiamata                                   # la domanda predefinita
    prova-chiamata "Cos'è la franchigia?" "Posso pagare a rate?"
    prova-chiamata --lingua en "What is the excess?"     # la chiamata in inglese
    prova-chiamata --server http://127.0.0.1:8002 --salva voce/prove/chiamata.wav

Esce con 1 se una domanda resta senza risposta.
"""

import argparse
import asyncio
import fractions
import functools
import json
import sys
import time
import wave
from pathlib import Path

import av
import httpx
import numpy as np
from aiortc import MediaStreamTrack, RTCPeerConnection, RTCSessionDescription
from aiortc.mediastreams import MediaStreamError

from assistente.config import LINGUE, Impostazioni, Lingua
from assistente.voce.servizi import modello_whisper, voce_piper

FREQ = 48000
PEZZO = 960  # 20 ms
SOGLIA_VOCE = 400  # RMS (int16) sopra cui c'è voce
SILENZIO_FINE = 2.5  # secondi di silenzio dopo cui l'assistente ha finito di parlare

# Stampa subito, anche quando l'uscita va in un file o in una pipe
print = functools.partial(print, flush=True)  # noqa: A001

DOMANDE_PREDEFINITE = {
    "it": "Buongiorno, alla scadenza dell'assicurazione auto ci sono i quindici giorni di "
    "copertura?",
    "en": "Good morning, when my car insurance expires, am I still covered for fifteen days?",
}


class Microfono(MediaStreamTrack):
    """Un microfono finto: manda silenzio, o l'audio che gli si dà da «dire», in tempo reale."""

    kind = "audio"

    def __init__(self):
        super().__init__()
        self._coda = np.zeros(0, dtype=np.int16)
        self._inizio: float | None = None
        self._campioni = 0

    def di(self, campioni: np.ndarray) -> float:
        """Accoda l'audio (48 kHz, mono) e restituisce quando finirà di essere detto."""
        gia_in_coda = len(self._coda) / FREQ
        self._coda = np.concatenate([self._coda, campioni.astype(np.int16)])
        return time.monotonic() + gia_in_coda + len(campioni) / FREQ

    async def recv(self) -> av.AudioFrame:
        if self._inizio is None:
            self._inizio = time.monotonic()
        attesa = self._inizio + self._campioni / FREQ - time.monotonic()
        if attesa > 0:
            await asyncio.sleep(attesa)
        pezzo, self._coda = self._coda[:PEZZO], self._coda[PEZZO:]
        if len(pezzo) < PEZZO:
            pezzo = np.pad(pezzo, (0, PEZZO - len(pezzo)))
        frame = av.AudioFrame.from_ndarray(pezzo.reshape(1, -1), format="s16", layout="mono")
        frame.sample_rate = FREQ
        frame.pts = self._campioni
        frame.time_base = fractions.Fraction(1, FREQ)
        self._campioni += PEZZO
        return frame


class Orecchio:
    """Registra l'audio dell'assistente (16 kHz, mono) e sa quando sta parlando."""

    def __init__(self):
        self.pezzi: list[tuple[float, np.ndarray]] = []

    async def ascolta(self, traccia):
        ricampiona = av.AudioResampler(format="s16", layout="mono", rate=16000)
        while True:
            try:
                frame = await traccia.recv()
            except MediaStreamError:
                return
            for f in ricampiona.resample(frame):
                self.pezzi.append((time.monotonic(), f.to_ndarray().reshape(-1)))

    def voce_dopo(self, istante: float) -> float | None:
        """Il primo istante, dopo `istante`, in cui l'assistente parla."""
        for t, p in self.pezzi:
            if t > istante and _rms(p) > SOGLIA_VOCE:
                return t
        return None

    def ultima_voce(self) -> float | None:
        for t, p in reversed(self.pezzi):
            if _rms(p) > SOGLIA_VOCE:
                return t
        return None

    def audio(self) -> np.ndarray:
        return np.concatenate([p for _, p in self.pezzi]) if self.pezzi else np.zeros(0, np.int16)

    def segmenti(self, pausa: float = 0.8) -> list[tuple[float, np.ndarray]]:
        """Le frasi dell'assistente: pezzi con voce, separati da almeno `pausa` di silenzio."""
        frasi, attuale, inizio, ultimo = [], [], None, None
        for t, p in self.pezzi:
            parla = _rms(p) > SOGLIA_VOCE
            if parla:
                if ultimo is not None and t - ultimo > pausa and attuale:
                    frasi.append((inizio, np.concatenate(attuale)))
                    attuale, inizio = [], None
                inizio = inizio or t
                ultimo = t
            if inizio is not None:
                attuale.append(p)
        if attuale:
            frasi.append((inizio, np.concatenate(attuale)))
        return frasi


def _rms(p: np.ndarray) -> float:
    return float(np.sqrt(np.mean(p.astype(np.float32) ** 2))) if len(p) else 0.0


def sintetizza(testo: str, imp: Impostazioni, lingua: Lingua) -> np.ndarray:
    """La domanda detta da Piper, portata a 48 kHz."""
    voce = voce_piper(imp.voce(lingua), imp.piper_cartella)
    campioni = np.concatenate([c.audio_int16_array for c in voce.synthesize(testo)])
    da = voce.config.sample_rate
    x = np.arange(0, len(campioni) * FREQ / da) * da / FREQ
    return np.interp(x, np.arange(len(campioni)), campioni).astype(np.int16)


async def aspetta(condizione, massimo: float, passo: float = 0.1) -> bool:
    fine = time.monotonic() + massimo
    while time.monotonic() < fine:
        if condizione():
            return True
        await asyncio.sleep(passo)
    return False


async def chiama(
    server: str,
    domande: list[str],
    imp: Impostazioni,
    salva: Path | None,
    trascrivi: bool = True,
    lingua: Lingua = "it",
) -> int:
    print("Preparo le domande con Piper…")
    audio_domande = [sintetizza(d, imp, lingua) for d in domande]

    pc = RTCPeerConnection()
    microfono, orecchio = Microfono(), Orecchio()
    pc.addTrack(microfono)
    messaggi: list[tuple[float, dict]] = []
    canale = pc.createDataChannel("messaggi")

    @canale.on("message")
    def ricevuto(m):
        try:
            messaggi.append((time.monotonic(), json.loads(m)))
        except (TypeError, json.JSONDecodeError):
            pass

    ascolto = []

    @pc.on("track")
    def traccia(t):
        if t.kind == "audio":
            ascolto.append(asyncio.ensure_future(orecchio.ascolta(t)))

    await pc.setLocalDescription(await pc.createOffer())
    async with httpx.AsyncClient(timeout=30) as http:
        r = await http.post(
            f"{server.rstrip('/')}/api/offer",
            json={
                "sdp": pc.localDescription.sdp,
                "type": pc.localDescription.type,
                "request_data": {"sessione": "prova", "lingua": lingua},
            },
        )
        if r.status_code != 200:
            print(f"Il server ha risposto {r.status_code}: {r.text}")
            return 1
        risposta = r.json()
    await pc.setRemoteDescription(RTCSessionDescription(risposta["sdp"], risposta["type"]))

    inizio = time.monotonic()
    esito = 0
    try:
        # Il saluto: si aspetta che l'assistente parli e poi taccia
        if not await aspetta(lambda: orecchio.voce_dopo(inizio), 30):
            print("Nessun saluto entro 30 s: la connessione audio non funziona.")
            return 1
        await aspetta(lambda: time.monotonic() - (orecchio.ultima_voce() or 0) > SILENZIO_FINE, 60)
        print(f"Saluto ricevuto ({orecchio.voce_dopo(inizio) - inizio:.1f} s dopo la connessione)")

        for domanda, audio in zip(domande, audio_domande, strict=True):
            print(f"\nDomanda: {domanda}")
            gia = len(messaggi)
            fine_domanda = microfono.di(audio)
            await aspetta(lambda f=fine_domanda: time.monotonic() > f, 60)

            def risposta(gia=gia):
                return next(
                    (t for t, m in messaggi[gia:] if m["tipo"] in ("risposta", "errore")), None
                )

            if not await aspetta(lambda: risposta() is not None, 90):
                print("  nessuna risposta entro 90 s")
                esito = 1
                continue
            # La risposta arriva prima sul canale dati, poi a voce: si aspetta che l'assistente
            # cominci a dirla e che poi taccia
            arrivata = risposta()
            await aspetta(lambda a=arrivata: orecchio.voce_dopo(a) is not None, 30)
            await aspetta(
                lambda: time.monotonic() - (orecchio.ultima_voce() or 0) > SILENZIO_FINE, 90
            )
            for t, m in messaggi[gia:]:
                if m["tipo"] == "utente":
                    print(f"  trascritto: «{m['testo']}» ({t - fine_domanda:.1f} s)")
                elif m["tipo"] == "risposta":
                    print(
                        f"  risposta dall'API dopo {t - fine_domanda:.1f} s: intento "
                        f"{m.get('intento')}, citazioni {m.get('citazioni')}"
                    )
                elif m["tipo"] == "errore":
                    print(f"  errore: {m['testo']}")
                    esito = 1
            voce = orecchio.voce_dopo(fine_domanda)
            if voce is None:
                print("  l'assistente non ha detto niente")
                esito = 1
            else:
                print(f"  prima voce dell'assistente dopo {voce - fine_domanda:.1f} s")
    finally:
        await pc.close()
        for a in ascolto:
            a.cancel()

    if trascrivi:
        # Con «base» basta per capire se l'audio si sente bene, e costa un quarto di «small»
        print("\nCosa ha detto l'assistente (ritrascritto con Whisper base):")
        whisper = modello_whisper("base", imp.whisper_thread)
    for t, pezzo in orecchio.segmenti() if trascrivi else []:
        segmenti, _ = whisper.transcribe(
            pezzo.astype(np.float32) / 32768, language=lingua, beam_size=1, without_timestamps=True
        )
        testo = " ".join(s.text.strip() for s in segmenti)
        print(f"  [{t - inizio:5.1f} s] {testo}")

    if salva:
        salva.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(salva), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(16000)
            w.writeframes(orecchio.audio().tobytes())
        print(f"\nAudio dell'assistente salvato in {salva}")
    return esito


def main():
    imp = Impostazioni.da_ambiente()
    p = argparse.ArgumentParser(description="Una chiamata di prova al server della voce")
    p.add_argument("domande", nargs="*")
    p.add_argument("--lingua", choices=LINGUE, default="it", help="la lingua della chiamata")
    p.add_argument("--server", default=f"http://{imp.host}:{imp.porta}")
    p.add_argument("--salva", type=Path, help="dove salvare l'audio dell'assistente (WAV)")
    p.add_argument(
        "--senza-trascrizione", action="store_true", help="non ritrascrivere l'audio alla fine"
    )
    a = p.parse_args()
    domande = a.domande or [DOMANDE_PREDEFINITE[a.lingua]]
    sys.exit(
        asyncio.run(chiama(a.server, domande, imp, a.salva, not a.senza_trascrizione, a.lingua))
    )


if __name__ == "__main__":
    main()
