"""Su quali indirizzi e porte UDP passa l'audio WebRTC.

aiortc (attraverso aioice) offre al browser un indirizzo per ogni interfaccia del server, ognuno
con una porta UDP casuale. Dietro un firewall o una VPN con regole sulle porte (come la tailnet
del progetto, che per il telefono apre solo poche porte) l'audio non passerebbe. Qui si può
scegliere:

- VOCE_INDIRIZZI: gli unici indirizzi da offrire (es. 100.64.0.10, l'indirizzo Tailscale), così
  nell'SDP non finiscono gli indirizzi privati del server;
- VOCE_PORTE_UDP: l'intervallo di porte da usare (es. 8098-8101), una porta per chiamata.

aioice non ha un'opzione per le porte: si intercettano solo le sue aperture di socket UDP su
porta 0 («una qualsiasi») e si prova una porta libera dell'intervallo. Il resto di aioice, e ogni
altro socket del processo, resta com'è.

Inoltre le chiamate usano la politica di bundle predefinita di aiortc (BALANCED) e non quella che
sceglie pipecat (MAX_BUNDLE, che gli serve per la condivisione dello schermo). Con MAX_BUNDLE aiortc
non si collega a un browser che può usare solo il TURN, come un telefono su rete mobile: le sue
verifiche ICE non vengono mai accettate (provato con Chrome costretto al TURN contro il sito
pubblico: 0 chiamate su 7 con MAX_BUNDLE, 6 su 6 con BALANCED). Con solo audio e canale dati la
risposta SDP è la stessa: un trasporto solo per tutti e due.
"""

import asyncio
import types

import aioice.ice
import pipecat.transports.smallwebrtc.connection as connessione_pipecat
from aiortc import RTCBundlePolicy, RTCConfiguration
from loguru import logger

_ORIGINALI = {
    "get_host_addresses": aioice.ice.get_host_addresses,
    "asyncio": aioice.ice.asyncio,
    "RTCConfiguration": connessione_pipecat.RTCConfiguration,
}


def _configurazione_bilanciata(*args, **kwargs) -> RTCConfiguration:
    """Quella che pipecat chiede ad aiortc, ma con la politica di bundle predefinita."""
    kwargs["bundlePolicy"] = RTCBundlePolicy.BALANCED
    return RTCConfiguration(*args, **kwargs)


def intervallo(testo: str) -> range | None:
    """«8098-8101» → range(8098, 8102); «8098» → una porta sola; vuoto → nessun limite."""
    testo = testo.strip()
    if not testo:
        return None
    primo, _, ultimo = testo.partition("-")
    primo, ultimo = int(primo), int(ultimo or primo)
    if not 1 <= primo <= ultimo <= 65535:
        raise ValueError(f"intervallo di porte non valido: {testo!r}")
    return range(primo, ultimo + 1)


class _CicloConPorte:
    """L'event loop di sempre, tranne che per i socket UDP di aioice su porta 0."""

    def __init__(self, ciclo, indirizzi: list[str], porte: range):
        self._ciclo = ciclo
        self._indirizzi = indirizzi
        self._porte = porte

    def __getattr__(self, nome):
        return getattr(self._ciclo, nome)

    async def create_datagram_endpoint(self, fabbrica, local_addr=None, **altri):
        if (
            local_addr
            and local_addr[1] == 0
            and (not self._indirizzi or local_addr[0] in self._indirizzi)
        ):
            for porta in self._porte:
                try:
                    return await self._ciclo.create_datagram_endpoint(
                        fabbrica, local_addr=(local_addr[0], porta), **altri
                    )
                except OSError:
                    continue
            raise OSError(
                f"nessuna porta UDP libera tra {self._porte.start} e {self._porte.stop - 1}"
            )
        return await self._ciclo.create_datagram_endpoint(fabbrica, local_addr=local_addr, **altri)


class _AsyncioConPorte(types.ModuleType):
    """Il modulo asyncio visto da aioice: uguale, ma con l'event loop che sceglie le porte."""

    def __init__(self, indirizzi: list[str], porte: range):
        super().__init__("asyncio")
        self._indirizzi = indirizzi
        self._porte = porte

    def __getattr__(self, nome):
        return getattr(asyncio, nome)

    def get_running_loop(self):
        return _CicloConPorte(asyncio.get_running_loop(), self._indirizzi, self._porte)


def configura_rete(indirizzi: list[str], porte: range | None):
    """Da chiamare una volta, all'avvio del server, prima di qualsiasi chiamata."""
    ripristina_rete()
    connessione_pipecat.RTCConfiguration = _configurazione_bilanciata
    if indirizzi:

        def solo_questi(use_ipv4: bool, use_ipv6: bool) -> list[str]:
            return [a for a in indirizzi if (use_ipv6 if ":" in a else use_ipv4)]

        aioice.ice.get_host_addresses = solo_questi
        logger.info(f"WebRTC: offro solo {', '.join(indirizzi)}")
    if porte:
        aioice.ice.asyncio = _AsyncioConPorte(indirizzi, porte)
        logger.info(f"WebRTC: porte UDP {porte.start}-{porte.stop - 1}")


def ripristina_rete():
    """Toglie le scelte fatte con configura_rete (serve ai test)."""
    aioice.ice.get_host_addresses = _ORIGINALI["get_host_addresses"]
    aioice.ice.asyncio = _ORIGINALI["asyncio"]
    connessione_pipecat.RTCConfiguration = _ORIGINALI["RTCConfiguration"]
