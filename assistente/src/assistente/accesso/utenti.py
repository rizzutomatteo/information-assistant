"""Gli utenti della pagina dimostrativa e le loro polizze, in PostgreSQL.

Le due copie del sito usano lo stesso database (ASSISTENTE_DATABASE), così chi aggiunge una
polizza su una la ritrova sull'altra.

Si entra in tre modi (rotte.py): con utente e password, di chi si è registrato o degli utenti di
prova; con Google, come l'utente che ha la stessa email (se non c'è, si crea con i dati di prova);
al telefono con il PIN, che per questo è diverso per ognuno. Gli utenti di prova si caricano da
/a incollando un JSON nel formato di FileUtenti, come esempio_utenti.json, e lì si modificano o si
eliminano (amministrazione.py). Al primo avvio c'è solo Mario Rossi, con il PIN 123456 e senza
password: serve alle prove al telefono.

Le password non si salvano: si salva la loro impronta scrypt, con un sale diverso per ognuna.
"""

import hashlib
import hmac
import secrets
from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal

from loguru import logger
from psycopg import AsyncConnection
from psycopg.errors import UniqueViolation
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
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

    def nel_json(self) -> dict:
        """L'utente nel formato del JSON di /a, senza password: per modificarlo a mano."""
        polizze = [
            {
                "prodotto": p.prodotto,
                "numero": p.numero,
                "oggetto": p.oggetto,
                "scadenza": p.scadenza.isoformat(),
                "premio": str(p.premio),
                "garanzie": list(p.garanzie),
            }
            for p in self.polizze
        ]
        return self.profilo() | {"polizze": polizze}

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


class ModificaUtente(UtenteDati):
    """Un utente cambiato a mano in /a. Il nome utente può mancare (chi entra solo con Google);
    senza password nuova resta quella di prima, senza PIN quello di prima."""

    utente: str = Field(default="", pattern=f"^$|{NOME_UTENTE}")
    password: str | None = Field(default=None, min_length=8, max_length=200)


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
    -- IDENTITY: i numeri vanno solo avanti. L'id di un utente eliminato non passa a uno nuovo,
    -- che altrimenti erediterebbe le sessioni ancora aperte (in memoria, nelle due copie del sito)
    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
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
    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    utente_id INTEGER NOT NULL REFERENCES utenti(id) ON DELETE CASCADE,
    prodotto TEXT NOT NULL,
    numero TEXT NOT NULL,
    oggetto TEXT NOT NULL,
    scadenza DATE NOT NULL,
    premio NUMERIC(10, 2) NOT NULL,
    garanzie TEXT[] NOT NULL
);
CREATE INDEX IF NOT EXISTS polizze_utente ON polizze (utente_id);
"""
# Il numero del blocco che tiene una sola copia del sito alla volta a preparare le tabelle
BLOCCO_TABELLE = 20261125
SENZA_DATI = {"codice_fiscale": "", "telefono": "", "indirizzo": ""}


async def _tutte(c: AsyncConnection, sql: str, *valori) -> list[dict]:
    return await (await c.execute(sql, valori)).fetchall()


async def _una(c: AsyncConnection, sql: str, *valori) -> dict | None:
    return await (await c.execute(sql, valori)).fetchone()


class Anagrafe:
    """Gli utenti e le loro polizze, in PostgreSQL. Ogni metodo è una transazione: tutto o
    niente. Le impronte delle password si calcolano fuori dal ciclo degli eventi
    (impronta_password, password_giusta)."""

    def __init__(self, indirizzo: str):
        self._indirizzo = indirizzo  # postgresql://utente:password@host:porta/database
        self._pool: AsyncConnectionPool | None = None

    async def apri(self):
        """All'avvio del server: le connessioni, le tabelle e, la prima volta, Mario Rossi. Se è
        già aperta (i test la aprono prima di darla al server) non fa nulla."""
        if self._pool:
            return
        if not self._indirizzo:
            raise RuntimeError("manca ASSISTENTE_DATABASE, l'indirizzo di PostgreSQL")
        pool = AsyncConnectionPool(
            self._indirizzo,
            min_size=1,
            max_size=4,
            kwargs={"row_factory": dict_row},
            # Una connessione caduta (PostgreSQL riavviato) si scarta prima di usarla
            check=AsyncConnectionPool.check_connection,
            open=False,
        )
        await pool.open(wait=True)
        self._pool = pool
        async with pool.connection() as c:
            # Le due copie del sito partono insieme: una prepara le tabelle, l'altra aspetta
            await c.execute("SELECT pg_advisory_xact_lock(%s)", (BLOCCO_TABELLE,))
            await c.execute(TABELLE)
            # Solo se la tabella non ha mai avuto utenti: dopo «Elimina tutti» resta vuota
            mai = await _una(
                c,
                "SELECT pg_sequence_last_value(pg_get_serial_sequence('utenti', 'id')) IS NULL"
                " AS mai",
            )
            if mai["mai"]:
                await self._nuovo(
                    c, "mario.rossi", "", None, PIN_DEMO, "Mario", "Rossi", POLIZZE_DI_PROVA
                )
        logger.info("Utenti: PostgreSQL")

    async def chiudi(self):
        if self._pool:
            await self._pool.close()

    async def utente(self, id_utente: int) -> Utente | None:
        async with self._pool.connection() as c:
            return await self._uno(c, "id = %s", id_utente)

    async def da_pin(self, pin: str) -> Utente | None:
        async with self._pool.connection() as c:
            return await self._uno(c, "pin = %s", pin)

    async def impronta(self, nome_utente: str) -> tuple[int, str] | None:
        """L'id e l'impronta della password di chi entra con questo nome, se c'è."""
        async with self._pool.connection() as c:
            riga = await _una(
                c,
                "SELECT id, password FROM utenti WHERE utente = %s AND password IS NOT NULL",
                nome_utente.strip().lower(),
            )
        return (riga["id"], riga["password"]) if riga else None

    async def da_google(self, email: str, nome: str, cognome: str) -> Utente:
        """L'utente con questa email; la prima volta lo si crea, con dati e polizze di prova."""
        async with self._pool.connection() as c:
            if utente := await self._uno(c, "email = %s", email):
                return utente
            pin = await self._pin_libero(c)
            nuovo = await self._nuovo(c, None, email, None, pin, nome, cognome, POLIZZE_DI_PROVA)
            return await self._uno(c, "id = %s", nuovo)

    async def registra(self, dati: Registrazione, impronta: str) -> Utente:
        """Un account nuovo, senza polizze: se le aggiunge l'utente. Conflitto se il nome
        utente o l'email sono già usati."""
        try:
            async with self._pool.connection() as c:
                await self._libero(c, "utente", dati.utente, None)
                if dati.email:
                    await self._libero(c, "email", dati.email, None)
                nuovo = await self._nuovo(
                    c,
                    dati.utente,
                    dati.email,
                    impronta,
                    await self._pin_libero(c),
                    dati.nome,
                    dati.cognome,
                    [],
                    SENZA_DATI,
                )
                return await self._uno(c, "id = %s", nuovo)
        except UniqueViolation:
            # Lo stesso nome registrato nello stesso istante dall'altra copia del sito
            raise Conflitto("utente", f"«utente» {dati.utente} è già usato") from None

    async def aggiungi_polizza(self, id_utente: int, polizza: Polizza) -> int:
        async with self._pool.connection() as c:
            return await self._polizza(c, id_utente, polizza)

    async def togli_polizza(self, id_utente: int, id_polizza: int) -> bool:
        async with self._pool.connection() as c:
            cursore = await c.execute(
                "DELETE FROM polizze WHERE id = %s AND utente_id = %s", (id_polizza, id_utente)
            )
        return cursore.rowcount > 0

    async def carica(self, utenti: list[UtenteDati], impronte: dict[str, str]) -> tuple[int, int]:
        """Crea gli utenti del JSON, o li sostituisce se il nome c'è già (polizze comprese).
        impronte: nome utente → impronta della password. Tutto o niente: (creati, sostituiti)."""
        creati = sostituiti = 0
        async with self._pool.connection() as c:
            for u in utenti:
                vecchio = await _una(c, "SELECT id, pin FROM utenti WHERE utente = %s", u.utente)
                id_vecchio = vecchio["id"] if vecchio else None
                pin = u.pin_telefono or (vecchio["pin"] if vecchio else await self._pin_libero(c))
                await self._libero(c, "pin", pin, id_vecchio)
                if u.email:
                    await self._libero(c, "email", u.email, id_vecchio)
                if vecchio:
                    await c.execute("DELETE FROM utenti WHERE id = %s", (id_vecchio,))
                    sostituiti += 1
                else:
                    creati += 1
                await self._nuovo(
                    c,
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

    async def modifica(
        self, id_utente: int, dati: ModificaUtente, impronta: str | None
    ) -> Utente | None:
        """Cambia dati e polizze di un utente; id e sessioni restano. impronta: della password
        nuova, None per tenere quella di prima. None se l'utente non c'è; Conflitto se nome
        utente, email o PIN sono di un altro."""
        async with self._pool.connection() as c:
            vecchio = await _una(c, "SELECT pin FROM utenti WHERE id = %s", id_utente)
            if not vecchio:
                return None
            pin = dati.pin_telefono or vecchio["pin"]
            for campo, valore in (("utente", dati.utente), ("email", dati.email), ("pin", pin)):
                if valore:
                    await self._libero(c, campo, valore, id_utente)
            await c.execute(
                "UPDATE utenti SET utente = %s, email = %s, password = COALESCE(%s, password),"
                " pin = %s, nome = %s, cognome = %s, codice_fiscale = %s, telefono = %s,"
                " indirizzo = %s WHERE id = %s",
                (
                    dati.utente or None,
                    dati.email or None,
                    impronta,
                    pin,
                    dati.nome,
                    dati.cognome,
                    dati.codice_fiscale,
                    dati.telefono,
                    dati.indirizzo,
                    id_utente,
                ),
            )
            await c.execute("DELETE FROM polizze WHERE utente_id = %s", (id_utente,))
            for polizza in dati.polizze:
                await self._polizza(c, id_utente, polizza.polizza())
            return await self._uno(c, "id = %s", id_utente)

    async def elimina(self, id_utente: int) -> bool:
        """Con le sue polizze. Le sue sessioni aperte non trovano più nessuno."""
        async with self._pool.connection() as c:
            cursore = await c.execute("DELETE FROM utenti WHERE id = %s", (id_utente,))
        return cursore.rowcount > 0

    async def elimina_tutti(self) -> int:
        async with self._pool.connection() as c:
            cursore = await c.execute("DELETE FROM utenti")
        return cursore.rowcount

    async def elenco(self) -> list[Utente]:
        async with self._pool.connection() as c:
            return await self._utenti(c, "TRUE")

    async def _libero(self, c: AsyncConnection, campo: str, valore: str, tranne: int | None):
        # campo è uno dei nomi di colonna scritti qui, mai un dato che arriva da fuori
        riga = await _una(
            c,
            f"SELECT utente, email FROM utenti WHERE {campo} = %s AND id IS DISTINCT FROM %s",
            valore,
            tranne,
        )
        if riga:
            chi = riga["utente"] or riga["email"]
            raise Conflitto(campo, f"«{campo}» {valore} è già di un altro utente ({chi})")

    async def _pin_libero(self, c: AsyncConnection) -> str:
        while True:
            pin = f"{secrets.randbelow(10**6):06d}"
            if not await _una(c, "SELECT 1 FROM utenti WHERE pin = %s", pin):
                return pin

    async def _nuovo(
        self, c, nome_utente, email, impronta, pin, nome, cognome, polizze, dati=None
    ) -> int:
        dati = DATI_DI_PROVA if dati is None else dati
        riga = await _una(
            c,
            "INSERT INTO utenti (utente, email, password, pin, nome, cognome, codice_fiscale,"
            " telefono, indirizzo) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
            nome_utente,
            email or None,
            impronta,
            pin,
            nome,
            cognome,
            dati["codice_fiscale"],
            dati["telefono"],
            dati["indirizzo"],
        )
        for polizza in polizze:
            await self._polizza(c, riga["id"], polizza)
        return riga["id"]

    async def _polizza(self, c: AsyncConnection, id_utente: int, p: Polizza) -> int:
        riga = await _una(
            c,
            "INSERT INTO polizze (utente_id, prodotto, numero, oggetto, scadenza, premio,"
            " garanzie) VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
            id_utente,
            p.prodotto,
            p.numero,
            p.oggetto,
            p.scadenza,
            p.premio,
            list(p.garanzie),
        )
        return riga["id"]

    async def _uno(self, c: AsyncConnection, condizione: str, valore) -> Utente | None:
        utenti = await self._utenti(c, condizione, valore)
        return utenti[0] if utenti else None

    async def _utenti(self, c: AsyncConnection, condizione: str, *valori) -> list[Utente]:
        """Gli utenti che rispettano la condizione (scritta qui, con i valori a parte), con le
        loro polizze: due domande al database in tutto, quanti che siano gli utenti."""
        righe = await _tutte(
            c, f"SELECT * FROM utenti WHERE {condizione} ORDER BY cognome, nome, id", *valori
        )
        polizze: dict[int, list[Polizza]] = {r["id"]: [] for r in righe}
        for p in await _tutte(
            c, "SELECT * FROM polizze WHERE utente_id = ANY(%s) ORDER BY id", list(polizze)
        ):
            polizze[p["utente_id"]].append(
                Polizza(
                    prodotto=p["prodotto"],
                    numero=p["numero"],
                    oggetto=p["oggetto"],
                    scadenza=p["scadenza"],
                    premio=p["premio"],
                    garanzie=tuple(p["garanzie"]),
                    id=p["id"],
                )
            )
        return [
            Utente(
                id=r["id"],
                utente=r["utente"] or "",
                email=r["email"] or "",
                pin_telefono=r["pin"],
                nome=r["nome"],
                cognome=r["cognome"],
                codice_fiscale=r["codice_fiscale"],
                telefono=r["telefono"],
                indirizzo=r["indirizzo"],
                polizze=tuple(polizze[r["id"]]),
            )
            for r in righe
        ]
