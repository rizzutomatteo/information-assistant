import asyncio

from pipecat.audio.dtmf.types import KeypadEntry
from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    InputDTMFFrame,
    InterruptionFrame,
    OutputTransportMessageUrgentFrame,
    TranscriptionFrame,
    TTSSpeakFrame,
    VADUserStartedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection
from pipecat.tests.utils import SleepFrame, run_test

from assistente.accesso.sessioni import AccessoConPin, Sessioni
from assistente.accesso.utenti import PIN_DEMO, Anagrafe
from assistente.rag.client import ErroreAPI, Evento
from assistente.voce.ponte import (
    CHIEDI_PIN,
    FRASI,
    PIN_ESAURITO,
    PIN_SBAGLIATO,
    Assistente,
    e_rumore,
    frase_di_attesa,
)


class ClientFinto:
    """Restituisce gli eventi dati, con una pausa prima della risposta."""

    def __init__(self, eventi, pausa=0.0, errore=None):
        self.eventi, self.pausa, self.errore = eventi, pausa, errore
        self.domande = []
        self.lingue = []

    async def turno(self, messaggio, sessione, token=None, canale="voce", lingua="it"):
        self.domande.append((messaggio, sessione, token))
        self.lingue.append(lingua)
        for e in self.eventi:
            if e.tipo == "risposta":
                await asyncio.sleep(self.pausa)
            yield e
        if self.errore:
            raise self.errore


RISPOSTA = Evento(
    "risposta",
    {"testo": "Sì, sei coperto.", "citazioni": ["FAQ «x»"], "intento": "prodotto"},
)


def _trascrizione(testo):
    return TranscriptionFrame(testo, "", "2026-11-13T00:00:00")


def _detto(frames):
    return [f.text for f in frames if isinstance(f, TTSSpeakFrame)]


def _alla_pagina(frames):
    return [f.message for f in frames if isinstance(f, OutputTransportMessageUrgentFrame)]


async def test_risposta_detta_e_mandata_alla_pagina():
    client = ClientFinto([Evento("stato", {"nodo": "retrieve", "testo": "Cerco"}), RISPOSTA])
    assistente = Assistente(client, "s1", token="t", attesa=5)
    giu, _ = await run_test(
        assistente, frames_to_send=[_trascrizione("Sono coperto?"), SleepFrame(0.3)]
    )
    assert client.domande == [("Sono coperto?", "s1", "t")]
    assert _detto(giu) == ["Sì, sei coperto.", "Lo trovi tra le domande frequenti."]
    utente, stato, risposta = _alla_pagina(giu)
    assert [m["tipo"] for m in (utente, stato, risposta)] == ["utente", "stato", "risposta"]
    # Con i messaggi pronti per la chat, come quelli della chat scritta (pagina.py)
    assert utente["html"] == '<div class="messaggio da-utente"><p>Sono coperto?</p></div>'
    assert stato["attesa"] == "Cerco" and risposta["attesa"] == ""
    assert risposta["html"].startswith('<div class="messaggio da-assistente">')
    # La trascrizione non arriva a Piper
    assert not any(isinstance(f, TranscriptionFrame) for f in giu)


async def test_frase_di_attesa_se_la_risposta_tarda():
    client = ClientFinto([Evento("stato", {"nodo": "retrieve"}), RISPOSTA], pausa=0.4)
    assistente = Assistente(client, "s1", attesa=0.1)
    giu, _ = await run_test(assistente, frames_to_send=[_trascrizione("Domanda"), SleepFrame(0.8)])
    assert _detto(giu)[0] == FRASI["it"].attese["retrieve"]
    assert "Sì, sei coperto." in _detto(giu)


async def test_errore_dell_api_detto_con_gentilezza():
    client = ClientFinto([], errore=ErroreAPI("API non raggiungibile"))
    giu, _ = await run_test(
        Assistente(client, "s1", attesa=5),
        frames_to_send=[_trascrizione("Domanda"), SleepFrame(0.3)],
    )
    assert _detto(giu) == [FRASI["it"].errore]


async def test_rumore_scartato():
    client = ClientFinto([RISPOSTA])
    allucinazione = _trascrizione("Sottotitoli creati dalla comunità Amara.org")
    giu, _ = await run_test(
        Assistente(client, "s1"), frames_to_send=[allucinazione, SleepFrame(0.2)]
    )
    assert client.domande == []
    assert _detto(giu) == []


async def test_bot_che_parla_si_ricorda():
    assistente = Assistente(ClientFinto([RISPOSTA]), "s1")
    await run_test(
        assistente,
        frames_to_send=[BotStartedSpeakingFrame()],
        frames_to_send_direction=FrameDirection.UPSTREAM,
    )
    assert assistente._bot_parla


async def test_interruzione_quando_l_utente_parla_sopra():
    assistente = Assistente(ClientFinto([RISPOSTA]), "s1")
    assistente._bot_parla = True
    giu, _ = await run_test(assistente, frames_to_send=[VADUserStartedSpeakingFrame()])
    assert any(isinstance(f, InterruptionFrame) for f in giu)


async def test_nessuna_interruzione_se_il_bot_tace():
    giu, _ = await run_test(
        Assistente(ClientFinto([RISPOSTA]), "s1"), frames_to_send=[VADUserStartedSpeakingFrame()]
    )
    assert not any(isinstance(f, InterruptionFrame) for f in giu)


def test_e_rumore():
    assert e_rumore("")
    assert e_rumore(" . ")
    assert e_rumore("Sottotitoli a cura di QTSS")
    assert e_rumore("Thank you for watching!")
    assert not e_rumore("Sì")
    assert not e_rumore("Cos'è la franchigia?")


def test_frase_di_attesa():
    assert frase_di_attesa("retrieve", 0) == "Un attimo, cerco nei documenti."
    assert frase_di_attesa("nodo_sconosciuto", 0) == "Un attimo, ci penso."
    assert frase_di_attesa("retrieve", 1) == "Ci vuole ancora qualche secondo."
    assert frase_di_attesa("retrieve", 0, "en") == "One moment, I'm searching the documents."


def test_ogni_lingua_ha_le_attese_di_ogni_nodo():
    assert FRASI["it"].attese.keys() == FRASI["en"].attese.keys()


async def test_in_inglese():
    risposta = Evento("risposta", {"testo": "Yes, you're covered.", "citazioni": ["FAQ «x»"]})
    client = ClientFinto([risposta])
    assistente = Assistente(client, "s1", lingua="en", attesa=5)
    giu, _ = await run_test(
        assistente, frames_to_send=[_trascrizione("Am I covered?"), SleepFrame(0.3)]
    )
    assert client.lingue == ["en"]
    assert _detto(giu) == [
        "Yes, you're covered.",
        "You'll find it in the frequently asked questions.",
    ]


# --- Il PIN al telefono -----------------------------------------------------------------


class ClientConAccesso:
    """Come l'API: senza token chiede l'accesso, con il token risponde."""

    def __init__(self):
        self.domande = []

    async def turno(self, messaggio, sessione, token=None, canale="voce", lingua="it"):
        self.domande.append((messaggio, token))
        if token:
            yield Evento("risposta", {"testo": "La tua polizza scade a giugno."})
        else:
            dati = {"testo": "Per continuare devo sapere chi sei.", "accesso": True}
            yield Evento("risposta", dati)


def _tasti(sequenza):
    return [InputDTMFFrame(button=KeypadEntry(t)) for t in sequenza]


def _al_telefono(client, anagrafe=None):
    """anagrafe: per i test in cui il PIN si controlla davvero."""
    accesso = AccessoConPin(Sessioni(anagrafe or Anagrafe("")))
    return Assistente(client, "s1", canale="telefono", chat=False, accesso_pin=accesso), accesso


async def test_pin_giusto_rifa_la_domanda_con_il_token(anagrafe):
    client = ClientConAccesso()
    assistente, accesso = _al_telefono(client, anagrafe)
    frames = [_trascrizione("Quando scade la mia polizza?"), SleepFrame(0.2)]
    frames += _tasti(PIN_DEMO + "#") + [SleepFrame(0.3)]
    giu, _ = await run_test(assistente, frames_to_send=frames)
    assert _detto(giu) == [
        "Per continuare devo sapere chi sei.",
        CHIEDI_PIN,
        "Grazie Mario, ti ho riconosciuto.",
        "La tua polizza scade a giugno.",
    ]
    assert client.domande == [
        ("Quando scade la mia polizza?", None),
        ("Quando scade la mia polizza?", accesso.token),
    ]
    assert accesso.token
    # I tasti non arrivano a Piper
    assert not any(isinstance(f, InputDTMFFrame) for f in giu)


async def test_pin_sbagliato_tre_volte(anagrafe):
    assistente, accesso = _al_telefono(ClientConAccesso(), anagrafe)
    frames = [_trascrizione("Voglio fare l'accesso"), SleepFrame(0.2)]
    frames += _tasti("1#2#3#4#") + [SleepFrame(0.2)]
    giu, _ = await run_test(assistente, frames_to_send=frames)
    # Dopo il terzo errore non aspetta più il PIN: il quarto cancelletto non conta
    assert _detto(giu)[2:] == [PIN_SBAGLIATO, PIN_SBAGLIATO, PIN_ESAURITO]
    assert accesso.token is None


async def test_asterisco_ricomincia_il_pin(anagrafe):
    assistente, accesso = _al_telefono(ClientConAccesso(), anagrafe)
    frames = [_trascrizione("Voglio fare l'accesso"), SleepFrame(0.2)]
    frames += _tasti("99*" + PIN_DEMO + "#") + [SleepFrame(0.3)]
    giu, _ = await run_test(assistente, frames_to_send=frames)
    assert "Grazie Mario, ti ho riconosciuto." in _detto(giu)


async def test_tasti_ignorati_se_non_si_aspetta_il_pin():
    assistente, accesso = _al_telefono(ClientConAccesso())
    giu, _ = await run_test(assistente, frames_to_send=_tasti(PIN_DEMO + "#") + [SleepFrame(0.1)])
    assert _detto(giu) == [] and accesso.token is None


async def test_dal_browser_niente_pin():
    # Senza accesso_pin (chiamata dal browser) si accede nella pagina: nessuna richiesta di PIN
    giu, _ = await run_test(
        Assistente(ClientConAccesso(), "s1", attesa=5),
        frames_to_send=[_trascrizione("Voglio fare l'accesso"), SleepFrame(0.2)],
    )
    assert CHIEDI_PIN not in _detto(giu)
