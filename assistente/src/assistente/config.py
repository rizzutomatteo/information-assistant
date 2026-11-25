"""Le impostazioni dell'assistente, lette dalle variabili d'ambiente (o dal file .env).

Quelle di tutto l'assistente cominciano con ASSISTENTE_, quelle del canale voce con VOCE_. Ogni
variabile ha un valore predefinito pensato per il server del progetto: 4 core Arm, nessuna GPU,
un paio di chiamate alla volta. L'elenco completo è in .env.example.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, get_args

from dotenv import load_dotenv

# La cartella del progetto, per trovare documenti e modelli quando non si usa Docker
CARTELLA_PROGETTO = Path(__file__).resolve().parents[2]

# Le lingue dell'assistente: la pagina manda quella scelta con le bandiere; al telefono si parla
# sempre italiano
Lingua = Literal["it", "en"]
LINGUE: tuple[Lingua, ...] = get_args(Lingua)

# Parole che Whisper deve riconoscere bene: gli si danno come «testo precedente».
# Va tenuto corto: un prompt lungo, sul silenzio, può essere ripetuto come se fosse stato detto.
# Le frasi per l'accesso vanno intere: con l'audio del telefono (8 kHz) «l'accesso» suona come
# «la cessa», e solo la frase intera nel prompt fa scegliere a Whisper quella giusta
PROMPT_WHISPER = (
    "Voglio fare l'accesso. Le mie info. Assicurazione auto, polizza, copertura, franchigia, "
    "massimale, sinistro, carta verde, RC auto, disdetta, rata."
)
PROMPT_WHISPER_EN = (
    "Car insurance, policy, cover, excess, limit, claim, green card, third-party liability, "
    "cancellation, instalment."
)


def _intero(nome: str, predefinito: int) -> int:
    return int(os.environ.get(nome, predefinito))


def _decimale(nome: str, predefinito: float) -> float:
    return float(os.environ.get(nome, predefinito))


def _vero(nome: str, predefinito: bool) -> bool:
    valore = os.environ.get(nome)
    if valore is None:
        return predefinito
    return valore.strip().lower() in ("1", "si", "sì", "true", "yes", "on")


def _elenco(nome: str) -> list[str]:
    return [v.strip() for v in os.environ.get(nome, "").split(",") if v.strip()]


@dataclass(frozen=True)
class Impostazioni:
    """Tutto ciò che si può regolare senza toccare il codice."""

    # --- L'assistente (ASSISTENTE_…) ---
    # L'API dell'assistente, il RAG (la stessa per chat e voce), e dove ascolta questo server
    url_api: str = "http://127.0.0.1:8001"
    host: str = "127.0.0.1"
    porta: int = 8002
    # Il client OAuth di Google per «Accedi con Google» (accesso/google.py); vuoti: niente Google
    google_client_id: str = ""
    google_client_secret: str = ""
    # I documenti da leggere nel sito, <area>/<nome>.md (sito/documenti.py), e le FAQ, faq.json
    # (sito/faq.py)
    documenti: Path = CARTELLA_PROGETTO / "documenti"
    # Il database PostgreSQL degli utenti e delle polizze (accesso/utenti.py), lo stesso per le
    # due copie del sito: postgresql://utente:password@host:porta/database
    database: str = ""
    # La password della pagina /a (accesso/amministrazione.py); vuota: la pagina non c'è
    amministrazione_password: str = ""
    log: str = "INFO"

    # --- Il canale voce (VOCE_…) ---
    chiamate_max: int = 2
    # Server STUN per WebRTC (es. «stun:stun.cloudflare.com:3478»); vuoto: solo rete locale o
    # Tailscale
    ice: list[str] = field(default_factory=list)
    # La chiave del TURN di Cloudflare (turn.py), per le chiamate da internet; vuote: niente TURN
    turn_chiave: str = ""
    turn_token: str = ""
    # Indirizzi e porte UDP per l'audio (vedi rete.py); vuoti: tutte le interfacce, porte casuali
    indirizzi: list[str] = field(default_factory=list)
    porte_udp: str = ""
    # Il segreto con cui Asterisk si presenta a /telefono (telefono.py); vuoto: niente telefonate
    telefono_segreto: str = ""

    # Voce → testo
    whisper_modello: str = "small"
    whisper_thread: int = 4
    whisper_beam: int = 5
    whisper_prompt: str = PROMPT_WHISPER
    whisper_prompt_en: str = PROMPT_WHISPER_EN
    # Secondi di silenzio dopo cui la frase è finita
    fine_frase: float = 0.8
    # Solo la voce di chi chiama (chi_parla.py): le frasi di altre persone nella stanza si
    # scartano se la loro impronta somiglia meno di soglia_voce a quella di chi chiama
    solo_chi_chiama: bool = True
    soglia_voce: float = 0.55
    impronte_cartella: Path = CARTELLA_PROGETTO / "voce" / "modelli" / "impronte"
    # Whisper su Groq (groq.py) e Azure Speech (azure.py): con la chiave le frasi vanno prima lì,
    # e il modello locale fa da riserva se nessuno risponde entro *_attesa secondi
    groq_chiave: str = ""
    groq_modello: str = "whisper-large-v3"
    groq_attesa: float = 2.0
    azure_chiave: str = ""
    azure_area: str = ""
    azure_attesa: float = 2.0
    # Chi trascrive, in ordine, per ogni entrata (i servizi senza chiave si saltano; il modello
    # locale è sempre l'ultimo). Con l'audio del telefono Azure capisce meglio di Whisper
    trascrizione_sito: list[str] = field(default_factory=lambda: ["groq"])
    trascrizione_telefono: list[str] = field(default_factory=lambda: ["azure", "groq"])
    # Dove salvare l'audio di ogni frase e il testo capito (registro.py); None: non si registra
    registrazioni: Path | None = None

    # Testo → voce
    piper_voce: str = "it_IT-paola-medium"
    piper_voce_en: str = "en_GB-cori-medium"
    piper_cartella: Path = CARTELLA_PROGETTO / "voce" / "modelli" / "piper"
    # Lentezza della voce: 1 normale, 1.1 un po' più lenta
    ritmo: float = 1.0

    # Conversazione
    interruzioni: bool = True
    max_frasi: int = 3
    attesa: float = 1.5
    silenzio_max: float = 180.0

    @classmethod
    def da_ambiente(cls) -> "Impostazioni":
        load_dotenv()
        base = cls()
        return cls(
            url_api=os.environ.get("ASSISTENTE_API_URL", base.url_api).rstrip("/"),
            host=os.environ.get("ASSISTENTE_HOST", base.host),
            porta=_intero("ASSISTENTE_PORTA", base.porta),
            chiamate_max=_intero("VOCE_CHIAMATE_MAX", base.chiamate_max),
            ice=_elenco("VOCE_ICE"),
            turn_chiave=os.environ.get("VOCE_TURN_CHIAVE", base.turn_chiave),
            turn_token=os.environ.get("VOCE_TURN_TOKEN", base.turn_token),
            indirizzi=_elenco("VOCE_INDIRIZZI"),
            porte_udp=os.environ.get("VOCE_PORTE_UDP", base.porte_udp),
            telefono_segreto=os.environ.get("VOCE_TELEFONO_SEGRETO", base.telefono_segreto),
            google_client_id=os.environ.get("ASSISTENTE_GOOGLE_CLIENT_ID", base.google_client_id),
            google_client_secret=os.environ.get(
                "ASSISTENTE_GOOGLE_CLIENT_SECRET", base.google_client_secret
            ),
            documenti=Path(os.environ.get("ASSISTENTE_DOCUMENTI", base.documenti)),
            database=os.environ.get("ASSISTENTE_DATABASE", base.database),
            amministrazione_password=os.environ.get(
                "ASSISTENTE_AMMINISTRAZIONE_PASSWORD", base.amministrazione_password
            ),
            whisper_modello=os.environ.get("VOCE_WHISPER_MODELLO", base.whisper_modello),
            whisper_thread=_intero("VOCE_WHISPER_THREAD", base.whisper_thread),
            whisper_beam=_intero("VOCE_WHISPER_BEAM", base.whisper_beam),
            whisper_prompt=os.environ.get("VOCE_WHISPER_PROMPT", base.whisper_prompt),
            whisper_prompt_en=os.environ.get("VOCE_WHISPER_PROMPT_EN", base.whisper_prompt_en),
            fine_frase=_decimale("VOCE_FINE_FRASE", base.fine_frase),
            solo_chi_chiama=_vero("VOCE_SOLO_CHI_CHIAMA", base.solo_chi_chiama),
            soglia_voce=_decimale("VOCE_SOGLIA_VOCE", base.soglia_voce),
            impronte_cartella=Path(
                os.environ.get("VOCE_IMPRONTE_CARTELLA", base.impronte_cartella)
            ),
            groq_chiave=os.environ.get("VOCE_GROQ_CHIAVE", base.groq_chiave),
            groq_modello=os.environ.get("VOCE_GROQ_MODELLO", base.groq_modello),
            groq_attesa=_decimale("VOCE_GROQ_ATTESA", base.groq_attesa),
            azure_chiave=os.environ.get("VOCE_AZURE_CHIAVE", base.azure_chiave),
            azure_area=os.environ.get("VOCE_AZURE_AREA", base.azure_area),
            azure_attesa=_decimale("VOCE_AZURE_ATTESA", base.azure_attesa),
            trascrizione_sito=_elenco("VOCE_TRASCRIZIONE_SITO") or base.trascrizione_sito,
            trascrizione_telefono=(
                _elenco("VOCE_TRASCRIZIONE_TELEFONO") or base.trascrizione_telefono
            ),
            registrazioni=Path(v) if (v := os.environ.get("VOCE_REGISTRAZIONI")) else None,
            piper_voce=os.environ.get("VOCE_PIPER_VOCE", base.piper_voce),
            piper_voce_en=os.environ.get("VOCE_PIPER_VOCE_EN", base.piper_voce_en),
            piper_cartella=Path(os.environ.get("VOCE_PIPER_CARTELLA", base.piper_cartella)),
            ritmo=_decimale("VOCE_RITMO", base.ritmo),
            interruzioni=_vero("VOCE_INTERRUZIONI", base.interruzioni),
            max_frasi=_intero("VOCE_MAX_FRASI", base.max_frasi),
            attesa=_decimale("VOCE_ATTESA", base.attesa),
            silenzio_max=_decimale("VOCE_SILENZIO_MAX", base.silenzio_max),
            log=os.environ.get("ASSISTENTE_LOG", base.log).upper(),
        )

    def voce(self, lingua: Lingua) -> str:
        """La voce di Piper per la lingua della chiamata."""
        return self.piper_voce_en if lingua == "en" else self.piper_voce

    def prompt(self, lingua: Lingua) -> str:
        """Le parole da suggerire a Whisper, nella lingua della chiamata."""
        return self.whisper_prompt_en if lingua == "en" else self.whisper_prompt
