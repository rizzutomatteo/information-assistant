import socket

import aioice
import pipecat.transports.smallwebrtc.connection as connessione_pipecat
import pytest
from aiortc import RTCBundlePolicy

from assistente.voce.rete import configura_rete, intervallo, ripristina_rete


def test_intervallo():
    assert intervallo("8098-8101") == range(8098, 8102)
    assert intervallo(" 8098 ") == range(8098, 8099)
    assert intervallo("") is None
    with pytest.raises(ValueError):
        intervallo("9000-8000")


def _porte_libere(quante: int) -> range:
    """Un intervallo di porte UDP libere su 127.0.0.1."""
    for inizio in range(47100, 48000, 10):
        prese = []
        try:
            for p in range(inizio, inizio + quante):
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.bind(("127.0.0.1", p))
                prese.append(s)
            return range(inizio, inizio + quante)
        except OSError:
            continue
        finally:
            for s in prese:
                s.close()
    raise RuntimeError("nessun intervallo libero")


@pytest.fixture
def rete():
    yield
    ripristina_rete()


async def test_candidati_solo_sull_indirizzo_e_nelle_porte(rete):
    porte = _porte_libere(2)
    configura_rete(["127.0.0.1"], porte)
    prima = aioice.Connection(ice_controlling=True)
    seconda = aioice.Connection(ice_controlling=True)
    await prima.gather_candidates()
    await seconda.gather_candidates()
    usate = [c.port for conn in (prima, seconda) for c in conn.local_candidates]
    assert [c.host for c in prima.local_candidates] == ["127.0.0.1"]
    assert sorted(usate) == list(porte)

    # Le porte sono finite: la terza connessione non ha candidati (aioice lo scrive nel log)
    terza = aioice.Connection(ice_controlling=True)
    await terza.gather_candidates()
    assert terza.local_candidates == []
    for conn in (prima, seconda, terza):
        await conn.close()


async def test_senza_configurazione_aioice_resta_com_e(rete):
    configura_rete([], None)
    conn = aioice.Connection(ice_controlling=True, use_ipv6=False)
    await conn.gather_candidates()
    assert all(c.host != "127.0.0.1" for c in conn.local_candidates)
    await conn.close()


def test_le_chiamate_usano_il_bundle_bilanciato(rete):
    # pipecat chiede MAX_BUNDLE: con quello un browser che passa solo dal TURN non si collega
    configura_rete([], None)
    chiesta = connessione_pipecat.RTCConfiguration(
        iceServers=[], bundlePolicy=RTCBundlePolicy.MAX_BUNDLE
    )
    assert chiesta.bundlePolicy == RTCBundlePolicy.BALANCED
    ripristina_rete()
    chiesta = connessione_pipecat.RTCConfiguration(bundlePolicy=RTCBundlePolicy.MAX_BUNDLE)
    assert chiesta.bundlePolicy == RTCBundlePolicy.MAX_BUNDLE
