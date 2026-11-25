"""Azure Speech di Microsoft: con l'audio del telefono capisce meglio di Whisper.

Sulle frasi registrate dal numero vero (G.711, 8 kHz) ha capito tutti i dieci «Ciao» brevi
(Whisper large-v3 su Groq sette) e «voglio effettuare l'accesso» anche senza aiuti, in circa
0,7 s per frase, rete compresa. Per questo al telefono è il primo; dal sito Groq va bene uguale,
e lì resta il primo (canale.py).

Si usa l'API per l'audio breve (fino a 60 s): una richiesta per frase, con il WAV nel corpo e la
lingua nell'indirizzo. Piano gratuito (F0): 5 ore di audio al mese e circa 20 richieste al minuto;
oltre risponde con un errore e la frase passa a Groq. La risorsa sta in un'area europea (per
esempio North Europe): l'audio resta nell'UE.
"""

import httpx

from assistente.voce.remoti import ErroreRemoto, ServizioRemoto, wav

LINGUE = {"it": "it-IT", "en": "en-GB"}
# Nessuna parola riconosciuta: la frase è vuota, non è un errore
SENZA_PAROLE = {"NoMatch", "InitialSilenceTimeout", "BabbleTimeout"}


class Azure(ServizioRemoto):
    """Azure Speech nell'area della risorsa (per esempio «northeurope»)."""

    def __init__(
        self, chiave: str, area: str, attesa: float, client: httpx.AsyncClient | None = None
    ):
        super().__init__(
            client
            or httpx.AsyncClient(
                base_url=f"https://{area}.stt.speech.microsoft.com",
                headers={"Ocp-Apim-Subscription-Key": chiave},
                timeout=attesa,
            )
        )
        self.nome = f"azure:{area}"

    async def trascrivi(self, audio: bytes, lingua: str, prompt: str) -> list[tuple[str, float]]:
        """Il testo della frase. Azure non dice quanto è probabile che sia silenzio: sul silenzio
        risponde senza parole. Il prompt non si usa: con l'elenco di frasi da aspettarsi, nelle
        prove, una volta ha capito «Le menfo» invece di «Le mie info»."""
        risposta = await self._invia(
            "/speech/recognition/conversation/cognitiveservices/v1",
            params={"language": LINGUE.get(lingua, lingua), "format": "simple"},
            content=wav(audio),
            headers={"Content-Type": "audio/wav; codecs=audio/pcm; samplerate=16000"},
        )
        dati = risposta.json()
        stato = dati.get("RecognitionStatus")
        if stato in SENZA_PAROLE:
            return []
        if stato != "Success":
            raise ErroreRemoto(f"esito {stato}")
        return [(dati.get("DisplayText", ""), 0.0)]
