"""Le credenziali del TURN di Cloudflare, per le chiamate dal sito pubblico.

Da internet l'audio non può arrivare diretto alla VPS: il firewall di Oracle non lascia entrare
UDP. Con un TURN browser e server mandano l'audio a turn.cloudflare.com, che lo passa all'altro:
dalla VPS partono solo connessioni in uscita, e il browser arriva anche dalle reti che bloccano
UDP (TURN su TLS, porta 443).

Le credenziali scadono. Si chiedono a Cloudflare con la chiave TURN (VOCE_TURN_CHIAVE e
VOCE_TURN_TOKEN) e si riusano finché resta abbastanza tempo per una chiamata. Le vede chiunque
apra la pagina, perché servono al browser: per questo durano poco.
"""

import asyncio
import time

import httpx
from loguru import logger

URL = "https://rtc.live.cloudflare.com/v1/turn/keys/{chiave}/credentials/generate-ice-servers"
# Secondi di validità delle credenziali, e il minimo che deve restare a quelle che si danno: una
# chiamata dura molto meno, e se scadessero a metà Cloudflare la chiuderebbe
DURATA = 2 * 3600
MARGINE = 3600


def _senza_porta_53(server: dict) -> dict | None:
    """Toglie gli indirizzi sulla porta 53: i browser la bloccano e la chiamata li aspetterebbe."""
    urls = server.get("urls")
    urls = [urls] if isinstance(urls, str) else list(urls or [])
    urls = [u for u in urls if ":53?" not in u and not u.endswith(":53")]
    return {**server, "urls": urls} if urls else None


class TurnCloudflare:
    """Dà server STUN e TURN con credenziali valide, nel formato RTCIceServer del browser."""

    def __init__(self, chiave: str, token: str, client: httpx.AsyncClient | None = None):
        self._url = URL.format(chiave=chiave)
        self._token = token
        self._client = client or httpx.AsyncClient(timeout=5.0)
        self._server: list[dict] = []
        self._scadenza = 0.0
        self._lucchetto = asyncio.Lock()

    async def server(self) -> list[dict]:
        """Le credenziali in uso, o nuove se stanno per scadere. Se Cloudflare non risponde,
        quelle vecchie finché valgono, poi nessuna (la chiamata prova senza TURN)."""
        async with self._lucchetto:
            adesso = time.monotonic()
            if adesso < self._scadenza - MARGINE:
                return self._server
            try:
                risposta = await self._client.post(
                    self._url,
                    headers={"Authorization": f"Bearer {self._token}"},
                    json={"ttl": DURATA},
                )
                risposta.raise_for_status()
                server = [_senza_porta_53(s) for s in risposta.json()["iceServers"]]
            except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError) as e:
                logger.warning(f"TURN di Cloudflare: niente credenziali nuove ({type(e).__name__})")
                return self._server if adesso < self._scadenza else []
            self._server = [s for s in server if s]
            self._scadenza = adesso + DURATA
            return self._server

    async def chiudi(self):
        await self._client.aclose()
