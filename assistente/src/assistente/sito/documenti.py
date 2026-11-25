"""I documenti di Velaria (condizioni, DIP, moduli…), da leggere nel sito.

    GET /documenti                 l'elenco, diviso nelle quattro aree dei prodotti
    GET /documenti/<area>/<nome>   un documento, dal suo Markdown

Sono i file anonimizzati del gruppo (documenti_anonimi.zip), gli stessi da cui il RAG prende i
pezzi, nella cartella ASSISTENTE_DOCUMENTI: <area>/<nome>.md. L'indirizzo di un documento è il
percorso del file senza «.md», così il RAG lo ricava da dove ha preso il pezzo, e si può andare
dritti al punto: ogni pagina del PDF originale (il commento «<!-- pagina N -->» dei file) ha
l'ancora #pagina-N, ogni titolo la sua, fatta dal testo (#che-cosa-e-assicurato).

    /documenti/casa_e_famiglia/dip_documento_informativo_precontrattuale_casa#pagina-2
"""

import re
from dataclasses import dataclass
from pathlib import Path

import markdown
from loguru import logger
from markdown.extensions.toc import TocExtension
from markupsafe import Markup

# Le cartelle delle aree, nell'ordine della home page, con il nome breve che sceglie icona e testi
AREE = {
    "auto_e_altri_veicoli": "auto",
    "casa_e_famiglia": "casa",
    "vita_e_risparmio": "vita",
    "previdenza": "previdenza",
}

# Il titolo viene dal nome del file: «dip_documento_informativo_precontrattuale_casa» diventa
# «DIP casa». Queste parole si scrivono diversamente: sigle, accenti e apostrofi persi nel nome
PAROLE = {
    "anas": "ANAS",
    "cid": "CID",
    "covip": "COVIP",
    "dip": "DIP",
    "dpi": "DPI",
    "fgvs": "FGVS",
    "ibip": "IBIP",
    "ii": "II",
    "kid": "KID",
    "mup": "MUP",
    "rita": "RITA",
    "sdd": "SDD",
    "sepa": "SEPA",
    "uci": "UCI",
    "invalidita": "invalidità",
    "piu": "più",
    "sostenibilita": "sostenibilità",
    "n": "n.",
    "all": "all'",
    "dell": "dell'",
    "sull": "sull'",
    "velaria": "Velaria",
}
RITOCCHI = (
    # «DIP» vuol già dire «documento informativo precontrattuale»
    (r"documento informativo precontrattuale (aggiuntivo )?", ""),
    (r"' ", "'"),
    (r"\bparte i\b", "parte I"),
    (r"\bfac simile\b", "fac-simile"),
    (r"\b(\d{1,2}) (\d{1,2}) (\d{4})\b", r"\1/\2/\3"),
    (r"\b(casa|pensione integrativa) Velaria\b", lambda m: f"{m[1].title()} Velaria"),
    (r"\bdrive\b", "Drive"),
)
# «Prodotto: Velaria Auto - ed. 07/2026», in testa ai DIP: distingue le edizioni di uno stesso
# documento (dip_…_auto, dip_…_auto_2)
PRODOTTO = re.compile(r"^Prodotto:\s*(.+?)\s*$", re.MULTILINE)
RIGHE_DI_TESTA = 40

PAGINA = re.compile(r"&lt;!--\s*pagina\s+(\d+)\s*-->")
COMMENTO = re.compile(r"<!--(?!\s*pagina\s+\d+\s*-->).*?-->", re.DOTALL)


@dataclass(frozen=True)
class Documento:
    area: str
    nome: str
    titolo: str
    prodotto: str  # vuoto se il file non lo scrive
    file: Path

    @property
    def indirizzo(self) -> str:
        """Relativo alla radice del sito."""
        return f"documenti/{self.area}/{self.nome}"

    @property
    def titolo_completo(self) -> str:
        return f"{self.titolo} · {self.prodotto}" if self.prodotto else self.titolo


def titolo(nome: str) -> str:
    """Il titolo da mostrare, dal nome del file."""
    t = " ".join(PAROLE.get(parola, parola) for parola in nome.split("_"))
    for modello, sostituto in RITOCCHI:
        t = re.sub(modello, sostituto, t)
    return t[:1].upper() + t[1:]


def prodotto(testo: str) -> str:
    """Il prodotto con l'edizione, se il documento lo scrive in testa."""
    trovato = PRODOTTO.search("\n".join(testo.splitlines()[:RIGHE_DI_TESTA]))
    return trovato[1] if trovato else ""


def in_html(testo: str) -> Markup:
    """Il Markdown di un documento in HTML, con le ancore delle pagine e dei titoli.

    Nei file non c'è HTML, a parte i commenti: «<» si scrive come testo, così anche un file
    sbagliato non può mettere nel sito qualcosa di suo.
    """
    testo = COMMENTO.sub("", testo).replace("<", "&lt;")
    testo = PAGINA.sub(r'\n\n<p class="pagina" id="pagina-\1">p. \1</p>\n\n', testo)
    html = markdown.markdown(
        testo,
        extensions=["tables", "sane_lists", TocExtension(baselevel=2)],
        output_format="html",
    )
    return Markup(html)


class Archivio:
    """I documenti della cartella, letti all'avvio; l'HTML si fa la prima volta che serve."""

    def __init__(self, cartella: Path):
        self._documenti: dict[tuple[str, str], Documento] = {}
        self._html: dict[Documento, Markup] = {}
        if not cartella.is_dir():
            logger.warning(f"Documenti: la cartella {cartella} non c'è")
            return
        for sotto in sorted(p for p in cartella.iterdir() if p.is_dir()):
            if sotto.name not in AREE:
                logger.warning(f"Documenti: area sconosciuta, saltata: {sotto.name}")
        for area in AREE:
            for file in sorted((cartella / area).glob("*.md")):
                testo = file.read_text(encoding="utf-8")
                documento = Documento(area, file.stem, titolo(file.stem), prodotto(testo), file)
                self._documenti[area, file.stem] = documento
        logger.info(f"Documenti: {len(self._documenti)} da {cartella}")

    def __len__(self) -> int:
        return len(self._documenti)

    def per_area(self) -> list[tuple[str, list[Documento]]]:
        """Le aree che hanno documenti, ognuna con i suoi in ordine di nome del file: è quasi
        l'ordine dei titoli, ma «auto» viene prima di «auto 2»."""
        aree = []
        for area in AREE:
            documenti = [d for (a, _), d in self._documenti.items() if a == area]
            if documenti:
                aree.append((area, sorted(documenti, key=lambda d: d.nome)))
        return aree

    def trova(self, area: str, nome: str) -> Documento | None:
        # Solo i documenti letti all'avvio: l'indirizzo non diventa mai un percorso da aprire
        return self._documenti.get((area, nome))

    def html(self, documento: Documento) -> Markup:
        if documento not in self._html:
            self._html[documento] = in_html(documento.file.read_text(encoding="utf-8"))
        return self._html[documento]
