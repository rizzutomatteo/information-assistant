"""Una chiamata: la pipeline di Pipecat su un trasporto, dall'inizio alla fine.

Il trasporto cambia con l'entrata, la pipeline no:

- dal browser, SmallWebRTCTransport (WebRTC), con la chat accanto;
- dal numero vero, FastAPIWebsocketTransport con l'audio di Asterisk (telefono.py), senza chat.

Anche la lingua cambia con l'entrata: dal browser quella scelta nella pagina, al telefono
l'italiano.
"""

from collections.abc import Sequence

from loguru import logger
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.audio.vad_processor import VADProcessor
from pipecat.transports.base_transport import BaseTransport
from pipecat.workers.runner import WorkerRunner

from assistente.accesso.sessioni import AccessoConPin
from assistente.config import Impostazioni, Lingua
from assistente.rag.client import ClientAssistente
from assistente.voce.chi_parla import SoloChiChiama, VADPronto
from assistente.voce.ponte import Assistente
from assistente.voce.registro import AscoltoChiamata, Registro
from assistente.voce.remoti import ServizioRemoto
from assistente.voce.servizi import VocePiper, WhisperVeloce


async def esegui_chiamata(
    trasporto: BaseTransport,
    imp: Impostazioni,
    client: ClientAssistente,
    sessione: str,
    token: str | None = None,
    *,
    canale: str = "voce",
    lingua: Lingua = "it",
    nome: str = "",
    frequenza_uscita: int = 24000,
    accesso_pin: AccessoConPin | None = None,
    registro: Registro | None = None,
    remoti: Sequence[ServizioRemoto] = (),
):
    """Monta la pipeline e la fa girare finché la chiamata non finisce.

        microfono → VAD (Silero) → solo chi chiama → Whisper → Assistente → Piper → altoparlante

    Il VAD decide quando l'utente ha finito di parlare (fine_frase secondi di silenzio): solo
    allora Whisper trascrive il pezzo di audio, e l'Assistente manda il testo all'API. In mezzo,
    se imp.solo_chi_chiama, le frasi di altre persone nella stanza si scartano (chi_parla.py).

    canale è quello che l'API riceve: «voce» dal browser (c'è la chat), «telefono» dal numero
    vero (niente chat). lingua è quella in cui Whisper ascolta, l'API risponde e Piper parla.
    frequenza_uscita è quella dell'audio verso il trasporto: 24 kHz per il browser, 16 kHz per
    Asterisk. accesso_pin, se c'è, permette di riconoscersi con il PIN digitato sul tastierino
    (al telefono). registro, se c'è, riceve l'audio e il testo capito di ogni frase. remoti sono
    i servizi che trascrivono le frasi, in ordine, prima del modello locale (remoti.py).
    """
    parametri_vad = VADParams(stop_secs=imp.fine_frase)
    vad = VADProcessor(vad_analyzer=VADPronto(params=parametri_vad))
    assistente = Assistente(
        client,
        sessione,
        token,
        canale=canale,
        lingua=lingua,
        attesa=imp.attesa,
        max_frasi=imp.max_frasi,
        interruzioni=imp.interruzioni,
        chat=canale == "voce",
        accesso_pin=accesso_pin,
    )
    registro_chiamata = registro.chiamata(canale, lingua) if registro else None
    ascolto = [AscoltoChiamata(registro_chiamata)] if registro_chiamata else []
    filtro = (
        [SoloChiChiama(imp.impronte_cartella, imp.soglia_voce, parametri_vad, registro_chiamata)]
        if imp.solo_chi_chiama
        else []
    )
    pipeline = Pipeline(
        [
            trasporto.input(),
            *ascolto,
            vad,
            *filtro,
            WhisperVeloce(imp, lingua, registro_chiamata, remoti),
            assistente,
            VocePiper(imp, lingua),
            trasporto.output(),
        ]
    )
    worker = PipelineWorker(
        pipeline,
        params=PipelineParams(audio_in_sample_rate=16000, audio_out_sample_rate=frequenza_uscita),
        # Il protocollo RTVI serve al client JavaScript di Pipecat: la pagina usa messaggi suoi
        enable_rtvi=False,
        idle_timeout_secs=imp.silenzio_max,
    )

    @trasporto.event_handler("on_client_connected")
    async def collegato(_trasporto, _client):
        logger.info(f"Chiamata {nome}: in linea ({lingua})")
        await assistente.saluta()

    @trasporto.event_handler("on_client_disconnected")
    async def scollegato(_trasporto, _client):
        logger.info(f"Chiamata {nome}: riattaccato")
        await worker.cancel()

    runner = WorkerRunner(handle_sigint=False)
    await runner.add_workers(worker)
    await runner.run()
