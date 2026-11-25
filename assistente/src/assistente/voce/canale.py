"""Il canale voce dell'assistente: le chiamate dal sito (WebRTC) e le telefonate (Asterisk).

    GET  /api/config  i server STUN/TURN da usare nel browser (turn.py)
    POST /api/offer   l'offerta WebRTC del browser → la risposta del server, e parte la chiamata
    WS   /telefono    le telefonate dal numero vero, da Asterisk (telefono.py)

Ogni chiamata trascrive la voce e la manda all'API dell'assistente (il RAG), come fa la chat, poi
legge la risposta (chiamata.py, ponte.py). L'audio delle chiamate dal browser non passa dal server
web: va diretto tra browser e server, in UDP, cifrato (DTLS-SRTP), o attraverso il TURN di
Cloudflare quando il browser è su internet. Quello delle telefonate arriva da Asterisk, sulla
stessa macchina.
"""

import asyncio
import uuid

from fastapi import APIRouter, HTTPException, Request, WebSocket
from loguru import logger
from pipecat.transports.base_transport import TransportParams
from pipecat.transports.smallwebrtc.connection import IceServer, SmallWebRTCConnection
from pipecat.transports.smallwebrtc.request_handler import (
    SmallWebRTCRequest,
    SmallWebRTCRequestHandler,
)
from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport
from pipecat.transports.websocket.fastapi import FastAPIWebsocketParams, FastAPIWebsocketTransport

from assistente.accesso.sessioni import AccessoConPin, Sessioni
from assistente.config import LINGUE, Impostazioni
from assistente.rag.client import ClientAssistente
from assistente.voce.azure import Azure
from assistente.voce.chiamata import esegui_chiamata
from assistente.voce.groq import Groq
from assistente.voce.registro import Registro
from assistente.voce.remoti import ServizioRemoto
from assistente.voce.rete import configura_rete, intervallo
from assistente.voce.servizi import carica_modelli
from assistente.voce.telefono import FREQUENZA, PEZZO, SerializzatoreAsterisk, credenziali_valide
from assistente.voce.turn import TurnCloudflare

CAMPI_OFFERTA = ("sdp", "type", "pc_id", "restart_pc", "request_data", "requestData")
OCCUPATO = "Tutte le linee sono occupate: riprova tra poco, oppure scrivi nella chat."


class Linee:
    """Quante chiamate possono esserci insieme: la CPU è condivisa con il resto dell'assistente."""

    def __init__(self, massimo: int):
        self.massimo = massimo
        self.attive = 0

    def prendi(self) -> bool:
        if self.attive >= self.massimo:
            return False
        self.attive += 1
        return True

    def libera(self):
        self.attive = max(0, self.attive - 1)


def servizi_remoti(imp: Impostazioni) -> dict[str, ServizioRemoto]:
    """I servizi di trascrizione fuori dal server per cui c'è la chiave, per nome."""
    remoti: dict[str, ServizioRemoto] = {}
    if imp.groq_chiave:
        remoti["groq"] = Groq(imp.groq_chiave, imp.groq_modello, imp.groq_attesa)
    if imp.azure_chiave and imp.azure_area:
        remoti["azure"] = Azure(imp.azure_chiave, imp.azure_area, imp.azure_attesa)
    return remoti


def apri_registro(imp: Impostazioni) -> Registro | None:
    """Il registro delle frasi, se c'è la cartella. Se non ci si può scrivere, si parte senza."""
    if imp.registrazioni is None:
        return None
    try:
        registro = Registro(imp.registrazioni)
    except OSError as e:
        logger.error(f"Registro delle frasi spento: {e}")
        return None
    logger.info(f"Registro delle frasi acceso: {imp.registrazioni}")
    return registro


class CanaleVoce:
    """Le chiamate in corso e ciò che serve loro; le rotte sono in «router»."""

    def __init__(
        self,
        imp: Impostazioni,
        client: ClientAssistente,
        sessioni: Sessioni,
        turn: TurnCloudflare | None = None,
        precarica: bool = True,
    ):
        porte = intervallo(imp.porte_udp)
        configura_rete(imp.indirizzi, porte)
        if porte and len(porte) < imp.chiamate_max:
            logger.warning(
                f"{len(porte)} porte UDP per {imp.chiamate_max} chiamate: alcune resterebbero mute"
            )
        if turn is None and imp.turn_chiave and imp.turn_token:
            turn = TurnCloudflare(imp.turn_chiave, imp.turn_token)
        self._imp = imp
        self._client = client
        self._sessioni = sessioni
        self._turn = turn
        self._precarica = precarica
        self._gestore = SmallWebRTCRequestHandler()
        self._chiamate: set[asyncio.Task] = set()
        self._remoti = servizi_remoti(imp)
        self._dal_sito = [self._remoti[n] for n in imp.trascrizione_sito if n in self._remoti]
        self._al_telefono = [
            self._remoti[n] for n in imp.trascrizione_telefono if n in self._remoti
        ]
        self.linee = Linee(imp.chiamate_max)
        self.registro = apri_registro(imp)
        self.router = self._rotte()

    async def avvia(self):
        imp = self._imp
        if self._precarica:
            await asyncio.to_thread(carica_modelli, imp)
        logger.info(f"Canale voce pronto: API {imp.url_api}, massimo {imp.chiamate_max} chiamate")
        locale = f"Whisper {imp.whisper_modello} sul server"
        for entrata, servizi in (("dal sito", self._dal_sito), ("al telefono", self._al_telefono)):
            catena = " → ".join([s.nome for s in servizi] + [locale])
            logger.info(f"Voce → testo {entrata}: {catena}")
        if imp.solo_chi_chiama:
            logger.info(f"Solo la voce di chi chiama: somiglianza minima {imp.soglia_voce}")

    async def chiudi(self):
        for t in list(self._chiamate):
            t.cancel()
        await self._gestore.close()
        for servizio in self._remoti.values():
            await servizio.chiudi()
        if self._turn:
            await self._turn.chiudi()

    async def _server_ice(self) -> list[dict]:
        """STUN e TURN per una chiamata, nel formato RTCIceServer del browser."""
        turn = await self._turn.server() if self._turn else []
        return turn + [{"urls": u} for u in self._imp.ice]

    def _rotte(self) -> APIRouter:
        router = APIRouter()
        imp, client, sessioni, linee = self._imp, self._client, self._sessioni, self.linee

        @router.get("/api/config")
        async def configurazione():
            return {"ice": await self._server_ice()}

        @router.post("/api/offer")
        async def offerta(corpo: dict, richiesta_http: Request):
            if not isinstance(corpo.get("sdp"), str) or corpo.get("type") != "offer":
                raise HTTPException(400, "Serve un'offerta WebRTC (sdp e type «offer»)")
            richiesta = SmallWebRTCRequest.from_dict(
                {k: corpo[k] for k in CAMPI_OFFERTA if k in corpo}
            )
            dati = richiesta.request_data if isinstance(richiesta.request_data, dict) else {}
            # La lingua della pagina quando la chiamata parte: resta quella fino alla fine
            lingua = dati.get("lingua") if dati.get("lingua") in LINGUE else "it"
            # Se l'utente ha fatto l'accesso, la chiamata è sua: il token resta per tutta la
            # chiamata
            token = sessioni.token(richiesta_http)
            nuova = not richiesta.pc_id
            if nuova and not linee.prendi():
                raise HTTPException(503, OCCUPATO)

            avviata = False

            async def avvia(connessione: SmallWebRTCConnection):
                nonlocal avviata
                avviata = True
                sessione = str(dati.get("sessione") or uuid.uuid4())
                trasporto = SmallWebRTCTransport(
                    webrtc_connection=connessione,
                    params=TransportParams(audio_in_enabled=True, audio_out_enabled=True),
                )

                async def gira():
                    try:
                        await esegui_chiamata(
                            trasporto,
                            imp,
                            client,
                            sessione,
                            token,
                            lingua=lingua,
                            nome=connessione.pc_id[-8:],
                            registro=self.registro,
                            remoti=self._dal_sito,
                        )
                    except Exception:  # noqa: BLE001 - una chiamata rotta non ferma il server
                        logger.exception("Chiamata finita con un errore")
                    finally:
                        linee.libera()

                compito = asyncio.create_task(gira())
                self._chiamate.add(compito)
                compito.add_done_callback(self._chiamate.discard)

            try:
                if nuova:
                    # Le credenziali TURN scadono: ogni chiamata parte con quelle in uso adesso
                    server = [
                        IceServer(i["urls"], i.get("username"), i.get("credential"))
                        for i in await self._server_ice()
                    ]
                    self._gestore.update_ice_servers(server or None)
                return await self._gestore.handle_web_request(richiesta, avvia)
            finally:
                if nuova and not avviata:
                    linee.libera()

        @router.websocket("/telefono")
        async def telefonata(websocket: WebSocket):
            # Solo Asterisk, con il segreto condiviso. Chi chiama parte da ospite e si fa
            # riconoscere con il PIN quando serve; la sessione si chiude quando riattacca
            autorizzazione = websocket.headers.get("authorization")
            if not credenziali_valide(autorizzazione, imp.telefono_segreto):
                await websocket.close(code=1008)
                return
            if not linee.prendi():
                # Asterisk vede la connessione rifiutata e fa sentire il segnale di occupato
                await websocket.close(code=1013)
                return
            accesso_pin = AccessoConPin(sessioni)
            try:
                await websocket.accept(subprotocol="media")
                trasporto = FastAPIWebsocketTransport(
                    websocket,
                    FastAPIWebsocketParams(
                        audio_in_enabled=True,
                        audio_out_enabled=True,
                        add_wav_header=False,
                        serializer=SerializzatoreAsterisk(),
                        fixed_audio_packet_size=PEZZO,
                    ),
                )
                await esegui_chiamata(
                    trasporto,
                    imp,
                    client,
                    str(uuid.uuid4()),
                    canale="telefono",
                    nome="dal telefono",
                    frequenza_uscita=FREQUENZA,
                    accesso_pin=accesso_pin,
                    registro=self.registro,
                    remoti=self._al_telefono,
                )
            except Exception:  # noqa: BLE001 - una telefonata rotta non ferma il server
                logger.exception("Telefonata finita con un errore")
            finally:
                accesso_pin.chiudi()
                linee.libera()

        return router
