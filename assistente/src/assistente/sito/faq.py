"""Le domande frequenti di Velaria, da leggere nel sito.

    GET /faq        l'elenco delle domande, diviso per categoria
    GET /faq/<id>   una domanda con la sua risposta

Sono le FAQ anonimizzate del gruppo (faq_anonime.json, nella cartella del Drive), copiate accanto
ai documenti come faq.json. L'indirizzo di una domanda è il suo id, lo stesso che il file ha
nel campo «url» (https://www.velaria.example/faq/<id>): il RAG lo ricava da lì. Le risposte sono
in Markdown, come i documenti, e ogni titolo ha la sua ancora (#cosa-coprono-le-garanzie).

    /faq/assicurare-casa-da-terremoti-alluvioni#cosa-coprono-le-garanzie
"""

import json
from dataclasses import dataclass
from pathlib import Path

from loguru import logger
from markdown.extensions.toc import slugify
from markupsafe import Markup

from assistente.sito.documenti import in_html

FILE = "faq.json"

# Le categorie del file, nell'ordine dell'elenco, con la loro icona: le prime tre sono aree dei
# prodotti e ne prendono anche il colore. Una categoria che qui non c'è va in fondo
CATEGORIE = {
    "Assicurazione Veicoli": "auto",
    "FAQ Casa, Famiglia, Cane e Gatto, Mutuo, Viaggi": "casa",
    "Prodotti Vita, Investimento, Risparmio e Pensione": "vita",
    "Gestione polizza": "documento",
    "Sinistri": "avviso",
}
ICONA = "domanda"
# Le domande senza categoria, in fondo all'elenco
ALTRE = "altre"


@dataclass(frozen=True)
class Categoria:
    nome: str  # come nel file; vuoto per le domande senza categoria

    @property
    def titolo(self) -> str:
        # Nella pagina delle FAQ il «FAQ» di «FAQ Casa, Famiglia…» è di troppo
        return self.nome.removeprefix("FAQ ")

    @property
    def icona(self) -> str:
        return CATEGORIE.get(self.nome, ICONA)

    @property
    def ancora(self) -> str:
        """«Gestione polizza» → «gestione-polizza», come le ancore dei titoli."""
        return slugify(self.titolo, "-") if self.nome else ALTRE


@dataclass(frozen=True)
class Faq:
    id: str
    domanda: str
    risposta: str
    categorie: tuple[str, ...]

    @property
    def indirizzo(self) -> str:
        """Relativo alla radice del sito."""
        return f"faq/{self.id}"

    @property
    def categoria(self) -> Categoria:
        """La prima delle sue categorie: quella del percorso in testa alla pagina."""
        return Categoria(self.categorie[0] if self.categorie else "")


class RaccoltaFaq:
    """Le FAQ del file, lette all'avvio; l'HTML di una risposta si fa la prima volta che serve."""

    def __init__(self, cartella: Path):
        self._faq: dict[str, Faq] = {}
        self._html: dict[str, Markup] = {}
        file = cartella / FILE
        if not file.is_file():
            logger.warning(f"FAQ: il file {file} non c'è")
            return
        for voce in json.loads(file.read_text(encoding="utf-8"))["faq"]:
            faq = Faq(voce["id"], voce["domanda"], voce["risposta"], tuple(voce["categorie"]))
            self._faq[faq.id] = faq
        logger.info(f"FAQ: {len(self._faq)} da {file}")

    def __len__(self) -> int:
        return len(self._faq)

    def per_categoria(self) -> list[tuple[Categoria, list[Faq]]]:
        """Le categorie che hanno domande, ognuna con le sue nell'ordine del file. Una domanda
        con due categorie sta in tutte e due, una senza categoria in fondo."""
        gruppi: dict[str, list[Faq]] = {nome: [] for nome in CATEGORIE}
        senza: list[Faq] = []
        for faq in self._faq.values():
            for nome in faq.categorie:
                gruppi.setdefault(nome, []).append(faq)
            if not faq.categorie:
                senza.append(faq)
        gruppi[""] = senza
        return [(Categoria(nome), domande) for nome, domande in gruppi.items() if domande]

    def trova(self, id: str) -> Faq | None:
        return self._faq.get(id)

    def html(self, faq: Faq) -> Markup:
        if faq.id not in self._html:
            # I titoli delle risposte cominciano da «##»: diventano h2, sotto la domanda (h1)
            self._html[faq.id] = in_html(faq.risposta, livello=1)
        return self._html[faq.id]
