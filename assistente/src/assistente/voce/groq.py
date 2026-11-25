"""Whisper large-v3 su Groq, gratuito entro i limiti del piano (20 richieste al minuto).

Rispetto a Whisper `small` sulla CPU del server è molto più veloce (0,3-0,5 s per frase, rete
compresa, contro circa 3,5 s) e un po' più preciso. È il primo per le chiamate dal sito; al
telefono viene dopo Azure (azure.py).
"""

import httpx

from assistente.voce.remoti import ServizioRemoto, wav

URL = "https://api.groq.com/openai/v1"


class Groq(ServizioRemoto):
    """Whisper su Groq, con il prompt delle parole da riconoscere bene."""

    def __init__(
        self, chiave: str, modello: str, attesa: float, client: httpx.AsyncClient | None = None
    ):
        super().__init__(
            client
            or httpx.AsyncClient(
                base_url=URL, headers={"Authorization": f"Bearer {chiave}"}, timeout=attesa
            )
        )
        self.modello = modello
        self.nome = f"groq:{modello}"

    async def trascrivi(self, audio: bytes, lingua: str, prompt: str) -> list[tuple[str, float]]:
        """I pezzi della frase, ciascuno con la probabilità che sia silenzio, come in locale."""
        campi = {"model": self.modello, "language": lingua, "temperature": "0"}
        campi["response_format"] = "verbose_json"
        if prompt:
            campi["prompt"] = prompt
        risposta = await self._invia(
            "/audio/transcriptions",
            data=campi,
            files={"file": ("frase.wav", wav(audio), "audio/wav")},
        )
        dati = risposta.json()
        segmenti = dati.get("segments") or [{"text": dati.get("text", "")}]
        return [(s.get("text", ""), float(s.get("no_speech_prob", 0.0))) for s in segmenti]
