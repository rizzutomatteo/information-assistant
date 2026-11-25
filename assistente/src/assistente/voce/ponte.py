"""Il ponte tra la voce e l'API dell'assistente, dentro la pipeline di Pipecat.

    microfono → VAD → Whisper → [Assistente] → Piper → altoparlante

Riceve il testo trascritto, lo manda all'API (la stessa della web chat), e intanto:

- se la risposta tarda, dice una frase di attesa adatta al nodo in corso («Un attimo, cerco
  nei documenti»), così qualche secondo di silenzio non sembra una linea caduta;
- quando arriva la risposta la trasforma in frasi da dire (parlato.py) e le passa a Piper;
- manda alla pagina, sul canale dati di WebRTC, la trascrizione, gli stati e la risposta
  completa con le citazioni, che la chat mostra per esteso (con i messaggi già pronti,
  sito/pagina.py);
- se l'utente parla mentre l'assistente sta parlando, lo interrompe;
- al telefono, quando l'API dice che serve l'accesso, chiede il PIN da digitare sul tastierino:
  se è giusto rifà la domanda, con il token di chi ha chiamato.

Se arriva una domanda nuova mentre la precedente è ancora in corso, vince l'ultima: l'utente
l'ha riformulata o ha cambiato idea.

Dal browser la chiamata è nella lingua scelta nella pagina (italiano o inglese); al telefono è
sempre in italiano, e il PIN si chiede solo lì.
"""

import asyncio
import re
import time
from dataclasses import dataclass

from loguru import logger
from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    Frame,
    InputDTMFFrame,
    OutputTransportMessageUrgentFrame,
    TranscriptionFrame,
    TTSSpeakFrame,
    VADUserStartedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from assistente.accesso.sessioni import AccessoConPin
from assistente.config import Lingua
from assistente.rag.client import ClientAssistente, ErroreAPI, Evento
from assistente.sito.pagina import per_la_pagina
from assistente.voce.parlato import risposta_parlata


@dataclass(frozen=True)
class Frasi:
    """Quello che l'assistente dice di suo, in una lingua."""

    # Chi chiama deve sapere subito che parla con un sistema automatico, non con una persona
    # (AI Act, art. 50). Che la voce non viene registrata lo dice la pagina, accanto al pulsante.
    saluto: str
    # La frase di attesa dipende dal nodo del grafo in corso
    attese: dict[str, str]
    attesa_generica: str
    attesa_lunga: str
    errore: str


FRASI = {
    "it": Frasi(
        saluto="Ciao, sono l'assistente automatico della compagnia, dimmi pure la tua domanda.",
        attese={
            "resolve_policy": "Un attimo, cerco la tua polizza.",
            "fetch_policy_data": "Un attimo, leggo i dati della tua polizza.",
            "retrieve": "Un attimo, cerco nei documenti.",
            "grade": "Un attimo, cerco nei documenti.",
            "rewrite_query": "Un attimo, cerco ancora nei documenti.",
            "generate": "Un attimo, preparo la risposta.",
            "output_guard": "Un attimo, controllo la risposta.",
            "finalize": "Un attimo, preparo la risposta.",
        },
        attesa_generica="Un attimo, ci penso.",
        attesa_lunga="Ci vuole ancora qualche secondo.",
        errore="Scusa, c'è un problema tecnico. Riprova tra poco, oppure scrivi nella chat.",
    ),
    "en": Frasi(
        saluto="Hi, I'm the company's automated assistant: go ahead and ask your question.",
        attese={
            "resolve_policy": "One moment, I'm looking for your policy.",
            "fetch_policy_data": "One moment, I'm reading your policy details.",
            "retrieve": "One moment, I'm searching the documents.",
            "grade": "One moment, I'm searching the documents.",
            "rewrite_query": "One moment, I'm searching the documents again.",
            "generate": "One moment, I'm preparing the answer.",
            "output_guard": "One moment, I'm checking the answer.",
            "finalize": "One moment, I'm preparing the answer.",
        },
        attesa_generica="One moment, let me think.",
        attesa_lunga="It'll take a few more seconds.",
        errore=(
            "Sorry, there's a technical problem. Please try again shortly, or write in the chat."
        ),
    ),
}
MAX_ATTESE = 3

# Il PIN al telefono (sempre in italiano): si digita, poi cancelletto; l'asterisco ricomincia
CHIEDI_PIN = "Digita sul tastierino il tuo PIN telefonico, poi premi cancelletto."
PIN_SBAGLIATO = "Il PIN non è corretto. Riprova, e alla fine premi cancelletto."
PIN_ESAURITO = (
    "Non riesco a riconoscerti. Il PIN lo trovi nella tua area riservata sul nostro sito; "
    "per il resto, chiedimi pure."
)
MAX_TENTATIVI = 3
MAX_CIFRE = 12

# Frasi che Whisper «sente» nel rumore o nel silenzio: le ha imparate dai sottotitoli dei video
_ALLUCINAZIONI = re.compile(
    r"amara\.org|qtss|sottotitol|iscriviti al canale|per la visione|grazie per l'ascolto"
    r"|thanks? (?:you )?for watching|subtitles by|subscribe to",
    re.IGNORECASE,
)


def frase_di_attesa(nodo: str | None, gia_dette: int, lingua: Lingua = "it") -> str:
    """La prima attesa dice cosa si sta facendo; le successive solo che ci vuole ancora poco."""
    frasi = FRASI[lingua]
    if gia_dette == 0:
        return frasi.attese.get(nodo or "", frasi.attesa_generica)
    return frasi.attesa_lunga


def e_rumore(testo: str) -> bool:
    """Vero per le trascrizioni da scartare: vuote, di una lettera, o allucinazioni note."""
    lettere = re.sub(r"[^a-zà-ù]", "", testo.lower())
    return len(lettere) < 2 or bool(_ALLUCINAZIONI.search(testo))


class Assistente(FrameProcessor):
    """Riceve le trascrizioni, chiede all'API, dice la risposta."""

    def __init__(
        self,
        client: ClientAssistente,
        sessione: str,
        token: str | None = None,
        *,
        canale: str = "voce",
        lingua: Lingua = "it",
        attesa: float = 1.5,
        attesa_lunga: float = 8.0,
        max_frasi: int = 3,
        interruzioni: bool = True,
        chat: bool = True,
        accesso_pin: AccessoConPin | None = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._client = client
        self._sessione = sessione
        self._token = token
        self._canale = canale
        self._lingua = lingua
        self._frasi = FRASI[lingua]
        self._attesa = attesa
        self._attesa_lunga = attesa_lunga
        self._max_frasi = max_frasi
        self._interruzioni = interruzioni
        self._chat = chat
        self._turno: asyncio.Task | None = None
        self._bot_parla = False
        # Il PIN: None se non lo si aspetta, altrimenti le cifre digitate finora
        self._accesso_pin = accesso_pin
        self._pin: str | None = None
        self._tentativi = 0
        self._in_sospeso: str | None = None  # la domanda che ha chiesto l'accesso

    async def saluta(self):
        await self._di([self._frasi.saluto])

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, TranscriptionFrame):
            # La trascrizione non va avanti: a Piper arriva solo ciò che l'assistente dice
            await self._domanda(frame.text)
            return
        if isinstance(frame, InputDTMFFrame):
            await self._tasto(frame.button.value)
            return

        if isinstance(frame, BotStartedSpeakingFrame):
            self._bot_parla = True
        elif isinstance(frame, BotStoppedSpeakingFrame):
            self._bot_parla = False
        elif (
            isinstance(frame, VADUserStartedSpeakingFrame)
            and self._interruzioni
            and self._bot_parla
        ):
            # L'utente parla sopra l'assistente: si smette di parlare (l'audio in coda si scarta)
            logger.debug(f"{self}: interruzione")
            await self.broadcast_interruption()

        await self.push_frame(frame, direction)

    async def _domanda(self, testo: str):
        testo = testo.strip()
        if e_rumore(testo):
            logger.debug(f"{self}: trascrizione scartata (rumore)")
            return
        # Chi parla invece di digitare il PIN ha cambiato discorso
        self._pin = None
        if self._turno and not self._turno.done():
            logger.debug(f"{self}: domanda nuova, la precedente si abbandona")
            await self.cancel_task(self._turno)
        self._turno = self.create_task(self._esegui_turno(testo), "turno")

    async def _esegui_turno(self, domanda: str):
        await self._alla_pagina({"tipo": "utente", "testo": domanda})
        coda: asyncio.Queue[Evento | None] = asyncio.Queue()

        async def leggi():
            try:
                async for evento in self._client.turno(
                    domanda, self._sessione, self._token, self._canale, self._lingua
                ):
                    await coda.put(evento)
            except ErroreAPI as e:
                await coda.put(Evento("errore", {"testo": str(e)}))
            finally:
                await coda.put(None)

        lettore = self.create_task(leggi(), "leggi_api")
        inizio = time.monotonic()
        prossima_attesa = self._attesa
        attese_dette = 0
        nodo = None
        try:
            while True:
                resta = inizio + prossima_attesa - time.monotonic()
                try:
                    if attese_dette >= MAX_ATTESE:
                        evento = await coda.get()
                    else:
                        evento = await asyncio.wait_for(coda.get(), timeout=max(0.0, resta))
                except TimeoutError:
                    await self._di([frase_di_attesa(nodo, attese_dette, self._lingua)])
                    attese_dette += 1
                    prossima_attesa += self._attesa_lunga
                    continue

                if evento is None:
                    raise ErroreAPI("l'API ha chiuso il flusso senza una risposta")
                if evento.tipo == "stato":
                    nodo = evento.dati.get("nodo")
                    await self._alla_pagina({"tipo": "stato", **evento.dati})
                elif evento.tipo == "risposta":
                    logger.info(
                        f"{self}: risposta in {time.monotonic() - inizio:.1f} s "
                        f"(intento {evento.dati.get('intento')}, "
                        f"operatore {bool(evento.dati.get('operatore'))})"
                    )
                    await self._rispondi(domanda, evento.dati)
                    return
                elif evento.tipo == "errore":
                    raise ErroreAPI(evento.dati.get("testo", "errore dell'API"))
        except ErroreAPI as e:
            # Nel log il motivo, mai il testo dell'utente (può contenere dati personali)
            logger.warning(f"{self}: {e}")
            await self._alla_pagina({"tipo": "errore", "testo": self._frasi.errore})
            await self._di([self._frasi.errore])
        finally:
            if not lettore.done():
                await self.cancel_task(lettore)

    async def _rispondi(self, domanda: str, dati: dict):
        await self._alla_pagina({"tipo": "risposta", **dati})
        frasi = risposta_parlata(
            dati.get("testo", ""),
            dati.get("citazioni") or [],
            max_frasi=self._max_frasi,
            chat=self._chat,
            lingua=self._lingua,
        )
        if dati.get("accesso") and self._accesso_pin and not self._token:
            self._pin, self._tentativi, self._in_sospeso = "", 0, domanda
            frasi.append(CHIEDI_PIN)
        await self._di(frasi)

    async def _tasto(self, tasto: str):
        """Un tasto del tastierino: conta solo mentre si aspetta il PIN."""
        if self._pin is None or self._accesso_pin is None:
            return
        if tasto == "*":
            self._pin = ""
        elif tasto != "#":
            self._pin = (self._pin + tasto)[:MAX_CIFRE]
        else:
            await self._controlla_pin(self._pin)

    async def _controlla_pin(self, pin: str):
        # Nel log solo l'esito, mai le cifre
        utente = await self._accesso_pin.entra(pin)
        if utente:
            logger.info(f"{self}: riconosciuto con il PIN")
            self._pin, self._token = None, self._accesso_pin.token
            await self._di([f"Grazie {utente.nome}, ti ho riconosciuto."])
            domanda, self._in_sospeso = self._in_sospeso, None
            if domanda:
                await self._domanda(domanda)
            return
        self._tentativi += 1
        logger.info(f"{self}: PIN sbagliato ({self._tentativi} di {MAX_TENTATIVI})")
        if self._tentativi >= MAX_TENTATIVI:
            self._pin = None
            await self._di([PIN_ESAURITO])
        else:
            self._pin = ""
            await self._di([PIN_SBAGLIATO])

    async def _di(self, frasi: list[str]):
        # Una frase per volta: Piper comincia a parlare appena la prima è pronta
        for frase in frasi:
            await self.push_frame(TTSSpeakFrame(frase, append_to_context=False))

    async def _alla_pagina(self, messaggio: dict):
        if self._chat:
            messaggio |= per_la_pagina(messaggio["tipo"], messaggio, self._lingua)
        await self.push_frame(OutputTransportMessageUrgentFrame(message=messaggio))

    async def cleanup(self):
        if self._turno and not self._turno.done():
            await self.cancel_task(self._turno)
        await super().cleanup()
