"""Dalla risposta scritta alle frasi da dire al telefono.

La risposta dell'assistente è pensata per essere letta: Markdown, elenchi, sigle, importi come
«€ 1.500,00», date come «03/2024», citazioni come «CGA Auto ed. 03/2024, art. 12, p. 18».
Letta così com'è, la voce sintetica direbbe «euro uno punto cinquecento» o salterebbe i simboli.
Qui il testo diventa frasi semplici, con numeri, date, importi e codici scritti per esteso.

I passi sono gli stessi in ogni lingua; come si dicono numeri, importi, date, ore, sigle e codici,
e le frasi che il canale aggiunge, sono di ciascuna lingua (Italiano, Inglese).

Le funzioni sono pure (nessun modello, nessuna rete), così si provano con pytest.
"""

import re
import string
from abc import ABC, abstractmethod

from num2words import num2words

from assistente.config import Lingua

# Indirizzi email e link, che non si dettano
_EMAIL = r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"
_LINK = r"(?:https?://|www\.)\S+?(?=[.,;:!?)]*(?:\s|$))"


class Pronuncia(ABC):
    """Le regole di una lingua. Le sottoclassi danno le tabelle e le frasi; qui ciò che è comune."""

    codice: str  # la lingua, per num2words
    mesi: tuple[str, ...]
    cifre: tuple[str, ...]
    lettere: dict[str, str]  # come si pronunciano, per targhe e codici
    sigle: dict[str, str]  # dette per esteso o come si pronunciano
    abbreviazioni: tuple[tuple[str, str], ...]  # nell'ordine in cui vanno sostituite
    migliaia: str  # il separatore delle migliaia
    virgola: str  # il separatore dei decimali
    numero: str  # un numero scritto in questa lingua (espressione regolare)
    parola_euro: str  # «euro» dopo un numero (espressione regolare)
    ordinale: str  # un ordinale scritto con le cifre (espressione regolare, le cifre nel gruppo 1)
    per_cento: str
    piu: str
    oppure: str
    e: str
    resto_nella_chat: str
    resto_sul_sito: str
    fonte: str
    faq: str

    def parole(self, n: int) -> str:
        return num2words(n, lang=self.codice)

    def una_per_una(self, cifre: str) -> str:
        return " ".join(self.cifre[int(c)] for c in cifre)

    def compita(self, codice: str) -> str:
        """Targhe e codici lettera per lettera: «AB12» → «a, bi, uno, due»."""
        return ", ".join(self.cifre[int(c)] if c.isdigit() else self.lettere[c] for c in codice)

    def _parti(self, numero: str) -> tuple[int, str]:
        intera, _, decimali = numero.partition(self.virgola)
        return int(intera.replace(self.migliaia, "")), decimali

    def numero_in_parole(self, numero: str) -> str:
        """«1.500,25» → «millecinquecento virgola venticinque»."""
        intera, decimali = self._parti(numero)
        parole = self.parole(intera)
        return f"{parole} {self.decimali(decimali)}" if decimali else parole

    def importo_in_parole(self, numero: str) -> str:
        """«1.500,50» → «millecinquecento euro e cinquanta centesimi»."""
        euro, decimali = self._parti(numero)
        centesimi = int((decimali + "00")[:2]) if decimali else 0
        parti = []
        if euro or not centesimi:
            parti.append(self.euro(euro))
        if centesimi:
            parti.append(self.centesimi(centesimi))
        return f" {self.e} ".join(parti)

    def leggi_data(self, m: re.Match) -> str:
        giorno, mese, anno = int(m[1]), int(m[2]), int(m[3])
        if not (1 <= giorno <= 31 and 1 <= mese <= 12):
            return m[0]
        return self.data(giorno, self.mesi[mese - 1], anno)

    def leggi_mese_anno(self, m: re.Match) -> str:
        mese, anno = int(m[1]), int(m[2])
        if not 1 <= mese <= 12:
            return m[0]
        return f"{self.mesi[mese - 1]} {self.anno(anno)}"

    def leggi_ore(self, testo: str) -> str:
        """Le ore come 9:30."""
        return re.sub(
            r"\b(?P<ore>[01]?\d|2[0-4]):(?P<minuti>[0-5]\d)\b",
            lambda m: self.ora(int(m["ore"]), int(m["minuti"])),
            testo,
        )

    def anno(self, anno: int) -> str:
        return self.parole(anno)

    @abstractmethod
    def decimali(self, cifre: str) -> str: ...

    @abstractmethod
    def euro(self, n: int) -> str: ...

    @abstractmethod
    def centesimi(self, n: int) -> str: ...

    @abstractmethod
    def data(self, giorno: int, mese: str, anno: int) -> str: ...

    @abstractmethod
    def ora(self, ore: int, minuti: int) -> str: ...

    @abstractmethod
    def senza_link(self, testo: str, chat: bool) -> str:
        """Link ed email non si dettano: si rimanda alla chat (chat=True) o al sito."""


# Preposizione + articolo: «a» + «l'» → «all'», «su» + «il» → «sul»
_ARTICOLATE = {
    ("a", "il"): "al", ("da", "il"): "dal", ("di", "il"): "del", ("in", "il"): "nel",
    ("su", "il"): "sul", ("a", "l'"): "all'", ("da", "l'"): "dall'", ("di", "l'"): "dell'",
    ("in", "l'"): "nell'", ("su", "l'"): "sull'", ("ad", "l'"): "all'",
}  # fmt: skip


def _al_posto_di(modello: str, articolo: str, resto: str):
    """Sostituisce link ed email con una frase («il link che trovi nella chat»), unendo
    l'articolo alla preposizione che li precede: «vai su www…» → «vai sul link …»."""

    def sostituisci(m: re.Match) -> str:
        prep = (m["prep"] or "").lower()
        spazio = "" if articolo.endswith("'") else " "
        unita = _ARTICOLATE.get((prep, articolo))
        if unita:
            # Si tiene la maiuscola della preposizione: «Su www…» → «Sul link…»
            return f"{m['prep'][0]}{unita[1:]}{spazio}{resto}"
        return f"{m['prep'] + ' ' if m['prep'] else ''}{articolo}{spazio}{resto}"

    return re.compile(rf"(?:\b(?P<prep>[Aa]d?|[Dd]a|[Dd]i|[Ii]n|[Ss]u)\s+)?{modello}"), sostituisci


class Italiano(Pronuncia):
    """L'italiano dei documenti: «1.500,25», «€ 250», «15°», «alle 18.30»."""

    codice = "it"
    mesi = (
        "gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
        "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre",
    )  # fmt: skip
    cifre = ("zero", "uno", "due", "tre", "quattro", "cinque", "sei", "sette", "otto", "nove")
    lettere = {
        "A": "a", "B": "bi", "C": "ci", "D": "di", "E": "e", "F": "effe", "G": "gi",
        "H": "acca", "I": "i", "J": "i lunga", "K": "cappa", "L": "elle", "M": "emme",
        "N": "enne", "O": "o", "P": "pi", "Q": "cu", "R": "erre", "S": "esse", "T": "ti",
        "U": "u", "V": "vu", "W": "doppia vu", "X": "ics", "Y": "ipsilon", "Z": "zeta",
    }  # fmt: skip
    # Sigle dei documenti assicurativi
    sigle = {
        "IVASS": "Ivass",
        "FGVS": "Fondo di garanzia per le vittime della strada",
        "IBAN": "Iban",
        "SPID": "spid",
        "CGA": "condizioni generali di assicurazione",
        "DIP": "documento informativo precontrattuale",
        "RCA": "erre ci auto",
        "FAQ": "domande frequenti",
        "UCI": "u ci i",
        "CID": "ci i di",
        "PDF": "pi di effe",
        "SMS": "esse emme esse",
        "PEC": "pec",
        "RC": "erre ci",
    }
    abbreviazioni = (
        (r"\bS\.p\.A\.?", "spa"),
        (r"\bR\.C\.", "erre ci"),
        (r"\bartt\.\s*", "articoli "),
        (r"\bart\.\s*", "articolo "),
        (r"\bed\.\s*(?=\d)", "edizione "),
        (r"\bpagg?\.\s*(?=\d)", "pagina "),
        (r"\bp\.\s*(?=\d)", "pagina "),
        (r"\bn[.°]\s*(?=\d)", "numero "),
        (r"\btel\.\s*", "telefono "),
        (r"\becc\.", "eccetera"),
        (r"\bes\.\s", "ad esempio "),
        (r"\bh24\b", "ventiquattro ore su ventiquattro"),
        (r"\be/o\b", "e o"),
    )
    # 15, 1.500, 1.500,25, 2,5
    migliaia, virgola = ".", ","
    numero = r"(?:\d{1,3}(?:\.\d{3})+|\d+)(?:,\d+)?"
    parola_euro = r"euro"
    ordinale = r"\b(\d{1,3})\s?[°º]"
    per_cento, piu, oppure, e = "per cento", "più", "o", "e"
    resto_nella_chat = "Il resto te l'ho scritto nella chat."
    resto_sul_sito = "Il resto lo trovi sul nostro sito."
    fonte = "Fonte"
    faq = "Lo trovi tra le domande frequenti."

    def decimali(self, cifre: str) -> str:
        # 0,05 → «zero virgola zero cinque»: con lo zero davanti si leggono le cifre
        if cifre.startswith("0"):
            return "virgola " + self.una_per_una(cifre)
        return "virgola " + self.parole(int(cifre))

    def euro(self, n: int) -> str:
        parole = "un" if n == 1 else self.parole(n)
        # «un milione di euro», non «un milione euro»
        if re.search(r"(milion[ei]|miliard[oi])$", parole):
            parole += " di"
        return f"{parole} euro"

    def centesimi(self, n: int) -> str:
        return "un centesimo" if n == 1 else f"{self.parole(n)} centesimi"

    def data(self, giorno: int, mese: str, anno: int) -> str:
        detto = "primo" if giorno == 1 else self.parole(giorno)
        return f"{detto} {mese} {self.anno(anno)}"

    def ora(self, ore: int, minuti: int) -> str:
        detto = self.parole(ore)
        return detto if minuti == 0 else f"{detto} e {self.parole(minuti)}"

    def leggi_ore(self, testo: str) -> str:
        """Le ore come 9:30, e anche come «alle 18.00»."""
        testo = super().leggi_ore(testo)
        return re.sub(
            r"\b(?P<prima>ore|alle|dalle|le) (?P<ore>[01]?\d|2[0-4])\.(?P<minuti>[0-5]\d)\b",
            lambda m: f"{m['prima']} {self.ora(int(m['ore']), int(m['minuti']))}",
            testo,
        )

    def senza_link(self, testo: str, chat: bool) -> str:
        dove = "nella chat" if chat else "sul nostro sito"
        for modello, articolo, resto in (
            (_EMAIL, "l'", f"indirizzo email che trovi {dove}"),
            (_LINK, "il", f"link che trovi {dove}"),
        ):
            regola, sostituisci = _al_posto_di(modello, articolo, resto)
            testo = regola.sub(sostituisci, testo)
        return testo


class Inglese(Pronuncia):
    """Inglese britannico, come la voce (en_GB): date giorno/mese/anno, «zed»."""

    codice = "en"
    mesi = (
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December",
    )  # fmt: skip
    cifre = ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine")
    # Una lettera maiuscola da sola la voce inglese la dice già con il suo nome (A «ei», Z «zed»)
    lettere = {c: c for c in string.ascii_uppercase}
    # Le sigle italiane dei documenti (le citazioni restano in italiano), dette in inglese
    sigle = {
        "CGA": "general terms and conditions",
        "DIP": "pre-contract information document",
        "FAQ": "frequently asked questions",
        "RCA": "motor third-party liability",
        "RC": "third-party liability",
        "IVASS": "Ivass",
    }
    abbreviazioni = (
        (r"\bS\.p\.A\.?", "S P A"),
        (r"\bartt\.\s*", "articles "),
        (r"\bart\.\s*", "article "),
        (r"\bed\.\s*(?=\d)", "edition "),
        (r"\b(?:pp?|pagg?)\.\s*(?=\d)", "page "),
        (r"\b(?:[Nn]o\.|n[.°])\s*(?=\d)", "number "),
        (r"\btel\.\s*", "phone "),
        (r"\betc\.", "et cetera"),
        (r"\be\.g\.,?\s*", "for example "),
        (r"\bi\.e\.,?\s*", "that is "),
        (r"\b(?:24/7|h24)\b", "twenty-four seven"),
        (r"\band/or\b", "and or"),
    )
    # 15, 1,500, 1,500.25, 2.5
    migliaia, virgola = ",", "."
    numero = r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
    parola_euro = r"euros?"
    ordinale = r"\b(\d{1,3})(?:st|nd|rd|th)\b"
    per_cento, piu, oppure, e = "percent", "plus", "or", "and"
    resto_nella_chat = "I've written the rest in the chat."
    resto_sul_sito = "You'll find the rest on our website."
    fonte = "Source"
    faq = "You'll find it in the frequently asked questions."

    def parole(self, n: int) -> str:
        # num2words scrive «one thousand, five hundred»: la virgola, detta, è una pausa di troppo
        return num2words(n, lang="en").replace(",", "")

    def anno(self, anno: int) -> str:
        return num2words(anno, lang="en", to="year").replace(",", "")

    def decimali(self, cifre: str) -> str:
        return "point " + self.una_per_una(cifre)

    def euro(self, n: int) -> str:
        return "one euro" if n == 1 else f"{self.parole(n)} euros"

    def centesimi(self, n: int) -> str:
        return "one cent" if n == 1 else f"{self.parole(n)} cents"

    def data(self, giorno: int, mese: str, anno: int) -> str:
        return f"the {num2words(giorno, lang='en', to='ordinal')} of {mese} {self.anno(anno)}"

    def ora(self, ore: int, minuti: int) -> str:
        detto = self.parole(ore)
        if minuti == 0:
            return f"{detto} o'clock" if ore <= 12 else f"{detto} hundred"
        if minuti < 10:
            return f"{detto} oh {self.parole(minuti)}"
        return f"{detto} {self.parole(minuti)}"

    def senza_link(self, testo: str, chat: bool) -> str:
        dove = "in the chat" if chat else "on our website"
        testo = re.sub(_EMAIL, f"the email address you'll find {dove}", testo)
        return re.sub(_LINK, f"the link you'll find {dove}", testo)


PRONUNCE: dict[str, Pronuncia] = {"it": Italiano(), "en": Inglese()}

_SEPARATORE = re.compile(r"[-*_=|:\s]{3,}")


def _da_markdown(testo: str) -> str:
    """Toglie il Markdown: ogni riga (titolo, voce di elenco, riga di tabella) diventa una frase."""
    frasi = []
    righe = [r.strip() for r in testo.splitlines()]
    for i, r in enumerate(righe):
        # Righe vuote e separatori (---, ***, |---|---|)
        if not r or _SEPARATORE.fullmatch(r):
            continue
        if r.startswith("|"):
            # L'intestazione di una tabella (la riga sopra |---|) non si legge
            if i + 1 < len(righe) and _SEPARATORE.fullmatch(righe[i + 1]):
                continue
            r = ", ".join(c.strip() for c in r.strip("|").split("|") if c.strip())
        r = re.sub(r"^#{1,6}\s*", "", r)
        r = re.sub(r"^>\s*", "", r)
        r = re.sub(r"^(?:[-*+•]|\d{1,2}[.)])\s+", "", r)
        r = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", r)
        r = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", r)
        r = re.sub(r"\*\*(.+?)\*\*|__(.+?)__", lambda m: m[1] or m[2], r)
        r = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"\1", r)
        r = re.sub(r"(?<![\w_])_(?!\s)(.+?)(?<!\s)_(?![\w_])", r"\1", r)
        r = r.replace("`", "").strip()
        if not r:
            continue
        if not re.search(r"[.!?:;,]$", r):
            r += "."
        frasi.append(r)
    return " ".join(frasi)


def normalizza(testo: str, chat: bool = True, lingua: Lingua = "it") -> str:
    """Il testo scritto diventa testo da pronunciare, nella lingua della chiamata.

    chat dice se chi ascolta ha anche la chat davanti (chiamata dal browser): i link e gli
    indirizzi email non si leggono, si rimanda alla chat o al sito.
    """
    p = PRONUNCE[lingua]
    t = p.senza_link(_da_markdown(testo), chat)

    for modello, sostituto in p.abbreviazioni:
        t = re.sub(modello, sostituto, t)
    for sigla in sorted(p.sigle, key=len, reverse=True):
        t = re.sub(rf"\b{sigla}\b", p.sigle[sigla], t)

    # Targhe e codici (lettere maiuscole e cifre insieme)
    t = re.sub(r"\b(?=[A-Z0-9]*\d)(?=[A-Z0-9]*[A-Z])[A-Z0-9]{4,}\b", lambda m: p.compita(m[0]), t)

    # Date: 15/03/2024 e 03/2024
    t = re.sub(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", p.leggi_data, t)
    t = re.sub(r"\b(\d{1,2})/(\d{4})\b", p.leggi_mese_anno, t)
    t = p.leggi_ore(t)

    # Importi: € 1.500,00 / 1.500 € / 250 euro / EUR 250
    n = p.numero
    t = re.sub(rf"(?:€|\bEUR)\s?({n})", lambda m: p.importo_in_parole(m[1]), t)
    t = re.sub(rf"\b({n})\s?(?:€|EUR\b|{p.parola_euro}\b)", lambda m: p.importo_in_parole(m[1]), t)

    # Percentuali e ordinali
    t = re.sub(rf"\b({n})\s?%", lambda m: f"{p.numero_in_parole(m[1])} {p.per_cento}", t)
    t = re.sub(p.ordinale, lambda m: num2words(int(m[1]), lang=p.codice, to="ordinal"), t)

    # Numeri lunghi senza separatori (numeri di polizza, di pratica): cifra per cifra
    t = re.sub(r"\b\d{5,}\b", lambda m: p.una_per_una(m[0]), t)
    # Tutti gli altri numeri
    t = re.sub(rf"\b{n}\b", lambda m: p.numero_in_parole(m[0]), t)

    # Simboli rimasti
    t = re.sub(r"(?<=\w)\+", f" {p.piu}", t)
    t = re.sub(r"(?<=[a-zà-ù])/(?=[a-zà-ù])", f" {p.oppure} ", t)
    t = t.replace("&", f" {p.e} ").replace("€", " euro").replace("%", f" {p.per_cento}")
    t = re.sub(r"[«»\"“”]", "", t)
    t = re.sub(r"\s*[()\[\]]\s*", ", ", t)

    # Spazi e punteggiatura
    t = re.sub(r"\s+", " ", t)
    t = re.sub(r"\s+([.,;:!?])", r"\1", t)
    t = re.sub(r",(\s*,)+", ",", t)
    t = re.sub(r",\s*([.;:!?])", r"\1", t)
    t = re.sub(r"\.{2,}", ".", t)
    t = re.sub(r"^[,\s]+", "", t)
    # Maiuscola a inizio frase
    t = re.sub(r"(^|[.!?]\s+)([a-zà-ù])", lambda m: m[1] + m[2].upper(), t)
    return t.strip()


def frasi(testo: str) -> list[str]:
    """Divide un testo già normalizzato in frasi (le abbreviazioni non ci sono più)."""
    return [f.strip() for f in re.split(r"(?<=[.!?])\s+", testo) if f.strip()]


def citazione_parlata(citazione: str, lingua: Lingua = "it") -> str:
    """«CGA Auto ed. 03/2024, art. 12, p. 18» → «Fonte: condizioni generali … articolo dodici.»

    Il numero di pagina non si dice: al telefono non serve, e nella chat c'è la citazione intera.
    """
    p = PRONUNCE[lingua]
    # Anche quando la citazione è un link a un documento: «[FAQ …](/documenti/…)»
    if re.match(r"\s*\[?FAQ\b", citazione, re.IGNORECASE):
        return p.faq
    senza_pagina = re.sub(r",?\s*\b(?:pagg?|p)\.\s*\d+(?:\s*-\s*\d+)?", "", citazione)
    detta = normalizza(senza_pagina, lingua=lingua).rstrip(".")
    return f"{p.fonte}: {detta[:1].lower()}{detta[1:]}."


def risposta_parlata(
    testo: str,
    citazioni: list[str] | tuple[str, ...] = (),
    max_frasi: int = 3,
    chat: bool = True,
    lingua: Lingua = "it",
) -> list[str]:
    """Le frasi da dire per una risposta: al massimo max_frasi, poi la fonte principale.

    L'API, per il canale voce, dovrebbe già rispondere in poche frasi. Se la risposta è più
    lunga, si dicono le prime e si rimanda alla chat (o al sito) per il resto.
    """
    p = PRONUNCE[lingua]
    tutte = frasi(normalizza(testo, chat=chat, lingua=lingua))
    dette = tutte[:max_frasi]
    if len(tutte) > max_frasi:
        dette.append(p.resto_nella_chat if chat else p.resto_sul_sito)
    if citazioni:
        dette.append(citazione_parlata(citazioni[0], lingua))
    return dette
