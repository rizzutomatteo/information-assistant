"""Gli utenti della pagina dimostrativa e le loro polizze, in un file SQLite.

Le due copie del sito usano lo stesso file (ASSISTENTE_UTENTI), così chi aggiunge una polizza su
una la ritrova sull'altra. Senza file gli utenti stanno in memoria e si perdono quando il server
riparte.

Si entra in tre modi (rotte.py): con utente e password, di chi si è registrato o degli utenti di
prova; con Google, come l'utente che ha la stessa email (se non c'è, si crea con i dati di prova);
al telefono con il PIN, che per questo è diverso per ognuno. Gli utenti di prova si caricano da
/a incollando un JSON nel formato di FileUtenti, come esempio_utenti.json (amministrazione.py).
Al primo avvio c'è solo Mario Rossi, con il PIN 123456 e senza password: serve alle prove al
telefono.

Le password non si salvano: si salva la loro impronta scrypt, con un sale diverso per ognuna.
"""

import hashlib
import hmac
import json
import secrets
import sqlite3
from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

from loguru import logger
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# I prodotti che si possono avere in polizza, con l'area a cui appartengono (icona e colore)
PRODOTTI = {
    "Velaria Auto": "auto",
    "Velaria Moto": "auto",
    "Velaria Furgoni&Van": "auto",
    "Velaria Altri Veicoli": "auto",
    "Velaria Natanti": "auto",
    "Velaria Monopattini Elettrici": "auto",
    "Casa Velaria": "casa",
    "Mutuo Velaria": "casa",
    "Velaria Viaggi": "casa",
    "Assicurazione Vita Velaria": "vita",
    "Previdente formula su misura": "vita",
    "Piano Risparmio Velaria": "vita",
    "Pensione Integrativa Velaria": "previdenza",
}

# scrypt: circa 16 MB e qualche decina di millisecondi per password, abbastanza per rendere lenti
# i tentativi a caso
SCRYPT = {"n": 2**14, "r": 8, "p": 1, "dklen": 32}
PIN_DEMO = "123456"


@dataclass(frozen=True)
class Polizza:
    prodotto: str
    numero: str
    oggetto: str  # cosa assicura: il veicolo, la casa
    scadenza: date
    premio: Decimal  # all'anno, in euro
    garanzie: tuple[str, ...]
    id: int = 0

    @property
    def tipo(self) -> str:
        return PRODOTTI.get(self.prodotto, "auto")

    @property
    def scadenza_testo(self) -> str:
        return self.scadenza.strftime("%d/%m/%Y")

    @property
    def premio_testo(self) -> str:
        # All'italiana, come i documenti: «€ 1.480,00»
        cifre = f"{self.premio:,.2f}".replace(",", " ").replace(".", ",").replace(" ", ".")
        return f"€ {cifre}"


@dataclass(frozen=True)
class Utente:
    id: int
    utente: str  # il nome per entrare con la password; vuoto per chi entra solo con Google
    email: str
    pin_telefono: str  # le cifre da digitare al telefono, poi cancelletto
    nome: str
    cognome: str
    codice_fiscale: str
    telefono: str
    indirizzo: str
    polizze: tuple[Polizza, ...]

    def profilo(self) -> dict:
        """I dati da dare alla pagina dopo l'accesso."""
        return {k: v for k, v in asdict(self).items() if k not in ("id", "polizze")}

    @property
    def nome_completo(self) -> str:
        # Google può non dare il cognome
        return f"{self.nome} {self.cognome}".strip()

    @property
    def iniziali(self) -> str:
        return (self.nome[:1] + self.cognome[:1]).upper()


# I dati di prova: li ha Mario Rossi, e li riceve chi entra con Google la prima volta (con il suo
# nome e la sua email). Prodotti e garanzie sono quelli dei DIP (documenti/, «Che cosa è
# assicurato?»: Velaria Auto ed. 07/2026, Casa Velaria ed. 10/2026); numeri, targa, scadenze e
# premi sono inventati
DATI_DI_PROVA = {
    "codice_fiscale": "RSSMRA00A00A000A",
    "telefono": "+39 000 000 0003",
    "indirizzo": "Via Esempio, 1 – 00000 Città",
}
POLIZZE_DI_PROVA = (
    Polizza(
        prodotto="Velaria Auto",
        numero="0000000001",
        oggetto="Autovettura targata AA000AA",
        scadenza=date(2027, 6, 30),
        premio=Decimal("480.00"),
        garanzie=(
            "Responsabilità civile",
            "Furto e Incendio",
            "Eventi atmosferici",
            "Cristalli",
            "Assistenza Stradale Estesa",
        ),
    ),
    Polizza(
        prodotto="Casa Velaria",
        numero="0000000002",
        oggetto="Abitazione in Via Esempio, 1 – 00000 Città",
        scadenza=date(2027, 3, 15),
        premio=Decimal("210.00"),
        garanzie=(
            "Incendio e scoppio",
            "Ricerca e riparazione danni da acqua",
            "Fenomeni elettrici e altri danni alla casa",
            "Responsabilità civile casa",
            "Assistenza pronto intervento base",
        ),
    ),
)


class PolizzaDati(BaseModel):
    """Una polizza come la manda la pagina («Aggiungi una polizza») o il JSON degli utenti."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    prodotto: str
    numero: str = Field(min_length=1, max_length=30)
    oggetto: str = Field(min_length=1, max_length=120)
    scadenza: date
    premio: Decimal = Field(ge=0, le=1_000_000, decimal_places=2)
    garanzie: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("prodotto")
    @classmethod
    def _prodotto_conosciuto(cls, valore: str) -> str:
        if valore not in PRODOTTI:
            raise ValueError(f"prodotto sconosciuto; quelli possibili: {', '.join(PRODOTTI)}")
        return valore

    @field_validator("garanzie")
    @classmethod
    def _garanzie_brevi(cls, valore: list[str]) -> list[str]:
        garanzie = [g.strip() for g in valore if g.strip()]
        if any(len(g) > 80 for g in garanzie):
            raise ValueError("ogni garanzia al massimo 80 caratteri")
        return garanzie

    def polizza(self) -> Polizza:
        return Polizza(
            self.prodotto,
            self.numero,
            self.oggetto,
            self.scadenza,
            self.premio,
            tuple(self.garanzie),
        )


NOME_UTENTE = r"^[a-z0-9][a-z0-9._-]{2,39}$"
EMAIL = r"^$|^[^@\s]+@[^@\s]+\.[^@\s]+$"


class Registrazione(BaseModel):
    """Un account nuovo, dalla scheda «Registrati» della finestra di accesso."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    nome: str = Field(min_length=1, max_length=60)
    cognome: str = Field(default="", max_length=60)
    email: str = Field(default="", max_length=120, pattern=EMAIL)
    utente: str = Field(pattern=NOME_UTENTE)
    password: str = Field(min_length=8, max_length=200)

    @field_validator("utente", mode="before")
    @classmethod
    def _in_minuscolo(cls, valore):
        # «Giulia.Verdi» e «giulia.verdi» sono lo stesso utente
        return valore.strip().lower() if isinstance(valore, str) else valore


class UtenteDati(BaseModel):
    """Un utente di prova, nel JSON che si incolla in /a."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    utente: str = Field(pattern=NOME_UTENTE)
    password: str = Field(min_length=8, max_length=200)
    nome: str = Field(min_length=1, max_length=60)
    cognome: str = Field(default="", max_length=60)
    email: str = Field(default="", max_length=120, pattern=EMAIL)
    codice_fiscale: str = Field(default="", max_length=16)
    telefono: str = Field(default="", max_length=40)
    indirizzo: str = Field(default="", max_length=120)
    # Se manca, se ne sceglie uno libero
    pin_telefono: str | None = Field(default=None, pattern=r"^\d{6}$")
    polizze: list[PolizzaDati] = Field(default_factory=list, max_length=50)


class FileUtenti(BaseModel):
    """Il JSON da incollare in /a: {"utenti": [...]}."""

    model_config = ConfigDict(extra="forbid")

    utenti: list[UtenteDati] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def _senza_doppioni(self) -> "FileUtenti":
        for campo in ("utente", "email", "pin_telefono"):
            valori = [getattr(u, campo) for u in self.utenti if getattr(u, campo)]
            doppi = sorted({v for v in valori if valori.count(v) > 1})
            if doppi:
                raise ValueError(f"«{campo}» ripetuto nel file: {', '.join(doppi)}")
        return self


class Conflitto(Exception):
    """Un nome utente, un'email o un PIN appartengono già a un altro utente."""

    def __init__(self, campo: str, messaggio: str):
        super().__init__(messaggio)
        self.campo = campo


def impronta_password(password: str) -> str:
    """Lenta di proposito: va chiamata fuori dal ciclo degli eventi."""
    sale = secrets.token_bytes(16)
    impronta = hashlib.scrypt(password.encode(), salt=sale, **SCRYPT)
    return f"scrypt${sale.hex()}${impronta.hex()}"


def password_giusta(password: str, impronta: str | None) -> bool:
    """Lenta di proposito, anche quando l'utente non c'è: il tempo non dice se esiste."""
    if not impronta:
        hashlib.scrypt(password.encode(), salt=b"\0" * 16, **SCRYPT)
        return False
    _, sale, attesa = impronta.split("$")
    calcolata = hashlib.scrypt(password.encode(), salt=bytes.fromhex(sale), **SCRYPT)
    return hmac.compare_digest(calcolata.hex(), attesa)


TABELLE = """
CREATE TABLE IF NOT EXISTS utenti (
    id INTEGER PRIMARY KEY,
    utente TEXT UNIQUE,
    email TEXT UNIQUE,
    password TEXT,
    pin TEXT NOT NULL UNIQUE,
    nome TEXT NOT NULL,
    cognome TEXT NOT NULL DEFAULT '',
    codice_fiscale TEXT NOT NULL DEFAULT '',
    telefono TEXT NOT NULL DEFAULT '',
    indirizzo TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS polizze (
    id INTEGER PRIMARY KEY,
    utente_id INTEGER NOT NULL REFERENCES utenti(id) ON DELETE CASCADE,
    prodotto TEXT NOT NULL,
    numero TEXT NOT NULL,
    oggetto TEXT NOT NULL,
    scadenza TEXT NOT NULL,
    premio TEXT NOT NULL,
    garanzie TEXT NOT NULL
);
"""


class Anagrafe:
    """Gli utenti e le loro polizze. Le operazioni sono brevi e si fanno nel ciclo degli eventi;
    le impronte delle password si calcolano fuori (impronta_password, password_giusta)."""

    def __init__(self, file: Path | None):
        if file:
            file.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(file or ":memory:", check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys = ON")
        # Le due copie del sito scrivono nello stesso file: chi trova il file occupato aspetta
        self._db.execute("PRAGMA busy_timeout = 5000")
        if file:
            self._db.execute("PRAGMA journal_mode = WAL")
        self._db.executescript(TABELLE)
        try:
            with self._db:
                if not self._db.execute("SELECT 1 FROM utenti LIMIT 1").fetchone():
                    self._nuovo(
                        "mario.rossi", "", None, PIN_DEMO, "Mario", "Rossi", POLIZZE_DI_PROVA
                    )
        except sqlite3.IntegrityError:
            # Al primo avvio le due copie del sito partono insieme: l'altra l'ha appena creato
            pass
        logger.info(f"Utenti: {file or 'in memoria (si perdono quando il server riparte)'}")

    def utente(self, id_utente: int) -> Utente | None:
        riga = self._db.execute("SELECT * FROM utenti WHERE id = ?", (id_utente,)).fetchone()
        return self._utente(riga) if riga else None

    def da_pin(self, pin: str) -> Utente | None:
        riga = self._db.execute("SELECT * FROM utenti WHERE pin = ?", (pin,)).fetchone()
        return self._utente(riga) if riga else None

    def impronta(self, nome_utente: str) -> tuple[int, str] | None:
        """L'id e l'impronta della password di chi entra con questo nome, se c'è."""
        riga = self._db.execute(
            "SELECT id, password FROM utenti WHERE utente = ? AND password IS NOT NULL",
            (nome_utente.strip().lower(),),
        ).fetchone()
        return (riga["id"], riga["password"]) if riga else None

    def da_google(self, email: str, nome: str, cognome: str) -> Utente:
        """L'utente con questa email; la prima volta lo si crea, con dati e polizze di prova."""
        riga = self._db.execute("SELECT id FROM utenti WHERE email = ?", (email,)).fetchone()
        if riga:
            return self.utente(riga["id"])
        with self._db:
            nuovo = self._nuovo(
                None, email, None, self._pin_libero(), nome, cognome, POLIZZE_DI_PROVA
            )
        return self.utente(nuovo)

    def registra(self, dati: Registrazione, impronta: str) -> Utente:
        """Un account nuovo, senza polizze: se le aggiunge l'utente. Conflitto se il nome
        utente o l'email sono già usati."""
        try:
            with self._db:
                self._libero("utente", dati.utente, None)
                if dati.email:
                    self._libero("email", dati.email, None)
                nuovo = self._nuovo(
                    dati.utente,
                    dati.email,
                    impronta,
                    self._pin_libero(),
                    dati.nome,
                    dati.cognome,
                    [],
                    {"codice_fiscale": "", "telefono": "", "indirizzo": ""},
                )
        except sqlite3.IntegrityError:
            # Lo stesso nome registrato nello stesso istante dall'altra copia del sito
            raise Conflitto("utente", f"«utente» {dati.utente} è già usato") from None
        return self.utente(nuovo)

    def aggiungi_polizza(self, id_utente: int, polizza: Polizza) -> int:
        with self._db:
            return self._polizza(id_utente, polizza)

    def togli_polizza(self, id_utente: int, id_polizza: int) -> bool:
        with self._db:
            cursore = self._db.execute(
                "DELETE FROM polizze WHERE id = ? AND utente_id = ?", (id_polizza, id_utente)
            )
        return cursore.rowcount > 0

    def carica(self, utenti: list[UtenteDati], impronte: dict[str, str]) -> tuple[int, int]:
        """Crea gli utenti del JSON, o li sostituisce se il nome c'è già (polizze comprese).
        impronte: nome utente → impronta della password. Tutto o niente: (creati, sostituiti)."""
        creati = sostituiti = 0
        with self._db:
            for u in utenti:
                vecchio = self._db.execute(
                    "SELECT id, pin FROM utenti WHERE utente = ?", (u.utente,)
                ).fetchone()
                id_vecchio = vecchio["id"] if vecchio else None
                pin = u.pin_telefono or (vecchio["pin"] if vecchio else self._pin_libero())
                self._libero("pin", pin, id_vecchio)
                if u.email:
                    self._libero("email", u.email, id_vecchio)
                if vecchio:
                    self._db.execute("DELETE FROM utenti WHERE id = ?", (id_vecchio,))
                    sostituiti += 1
                else:
                    creati += 1
                self._nuovo(
                    u.utente,
                    u.email,
                    impronte[u.utente],
                    pin,
                    u.nome,
                    u.cognome,
                    [p.polizza() for p in u.polizze],
                    {
                        "codice_fiscale": u.codice_fiscale,
                        "telefono": u.telefono,
                        "indirizzo": u.indirizzo,
                    },
                )
        return creati, sostituiti

    def elenco(self) -> list[Utente]:
        righe = self._db.execute("SELECT * FROM utenti ORDER BY cognome, nome, id").fetchall()
        return [self._utente(r) for r in righe]

    def chiudi(self):
        self._db.close()

    def _libero(self, campo: str, valore: str, tranne: int | None):
        riga = self._db.execute(
            f"SELECT utente, email FROM utenti WHERE {campo} = ? AND id IS NOT ?", (valore, tranne)
        ).fetchone()
        if riga:
            chi = riga["utente"] or riga["email"]
            raise Conflitto(campo, f"«{campo}» {valore} è già di un altro utente ({chi})")

    def _pin_libero(self) -> str:
        while True:
            pin = f"{secrets.randbelow(10**6):06d}"
            if not self._db.execute("SELECT 1 FROM utenti WHERE pin = ?", (pin,)).fetchone():
                return pin

    def _nuovo(self, nome_utente, email, impronta, pin, nome, cognome, polizze, dati=None) -> int:
        dati = DATI_DI_PROVA if dati is None else dati
        cursore = self._db.execute(
            "INSERT INTO utenti (utente, email, password, pin, nome, cognome, codice_fiscale,"
            " telefono, indirizzo) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                nome_utente,
                email or None,
                impronta,
                pin,
                nome,
                cognome,
                dati["codice_fiscale"],
                dati["telefono"],
                dati["indirizzo"],
            ),
        )
        for polizza in polizze:
            self._polizza(cursore.lastrowid, polizza)
        return cursore.lastrowid

    def _polizza(self, id_utente: int, p: Polizza) -> int:
        cursore = self._db.execute(
            "INSERT INTO polizze (utente_id, prodotto, numero, oggetto, scadenza, premio, garanzie)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                id_utente,
                p.prodotto,
                p.numero,
                p.oggetto,
                p.scadenza.isoformat(),
                str(p.premio),
                json.dumps(list(p.garanzie), ensure_ascii=False),
            ),
        )
        return cursore.lastrowid

    def _utente(self, riga: sqlite3.Row) -> Utente:
        polizze = self._db.execute(
            "SELECT * FROM polizze WHERE utente_id = ? ORDER BY id", (riga["id"],)
        ).fetchall()
        return Utente(
            id=riga["id"],
            utente=riga["utente"] or "",
            email=riga["email"] or "",
            pin_telefono=riga["pin"],
            nome=riga["nome"],
            cognome=riga["cognome"],
            codice_fiscale=riga["codice_fiscale"],
            telefono=riga["telefono"],
            indirizzo=riga["indirizzo"],
            polizze=tuple(
                Polizza(
                    prodotto=p["prodotto"],
                    numero=p["numero"],
                    oggetto=p["oggetto"],
                    scadenza=date.fromisoformat(p["scadenza"]),
                    premio=Decimal(p["premio"]),
                    garanzie=tuple(json.loads(p["garanzie"])),
                    id=p["id"],
                )
                for p in polizze
            ),
        )
