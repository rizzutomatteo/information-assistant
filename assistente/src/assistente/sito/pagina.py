"""Le pagine del sito dimostrativo, fatte sul server con Jinja2, nella lingua scelta.

    pagine/base.html       ciò che hanno tutte: testata, icone, piede
    pagine/pagina.html     la home page: prodotti, assistente, area riservata
    pagine/documenti.html  l'elenco dei documenti, per area (documenti.py)
    pagine/documento.html  un documento
    pagine/faq.html        le domande frequenti, per categoria (faq.py)
    pagine/domanda.html    una domanda frequente con la sua risposta
    pagine/amministrazione.html  la pagina /a, per caricare, modificare ed eliminare gli utenti
    pagine/messaggio.html  un messaggio della conversazione (chat e chiamata)

I testi, nelle due lingue, stanno in testi.py. Ciò che dipende da chi apre la pagina lo mette il
server: l'area riservata di chi ha fatto l'accesso e l'avviso sulla registrazione della voce.

Anche i messaggi della conversazione si fanno qui. Ogni evento dell'API, che arrivi dalla chat o
dalla chiamata, va alla pagina con due campi in più: «html», il messaggio da aggiungere alla
conversazione, e «attesa», la riga sotto («Ci penso…»), vuota quando l'assistente ha finito. Il
browser li mette nella pagina così come sono: ciò che viene da fuori (la domanda, la risposta
dell'API, le citazioni) è già protetto qui, perché il modello trasforma i caratteri dell'HTML.
"""

import re
from pathlib import Path
from types import SimpleNamespace

from jinja2 import Environment, FileSystemLoader, StrictUndefined
from markupsafe import Markup, escape

from assistente.accesso.utenti import PRODOTTI, Utente
from assistente.config import LINGUE, Lingua
from assistente.sito.documenti import AREE, Archivio, Documento
from assistente.sito.faq import Faq, RaccoltaFaq
from assistente.sito.testi import DEGLI_SCRIPT, TESTI

PAGINE = Path(__file__).parent / "pagine"
VOCE_ELENCO = re.compile(r"^\s*([-*•]|\d+[.)])\s+")
GRASSETTO = re.compile(r"\*\*(.+?)\*\*")
# I link delle risposte e delle citazioni: verso altri siti o verso i documenti e le FAQ di
# questo (/documenti/<area>/<nome>#pagina-N, documenti.py; /faq/<id>, faq.py)
LINK = re.compile(r"\[([^\]]+)\]\(((?:https?://|/documenti/|/faq/)[^)\s]+)\)")
MESSAGGI = ("utente", "risposta", "errore")


def riga(testo: str) -> Markup:
    """Una riga di Markdown, sicura: prima si toglie l'HTML, poi grassetto e link."""
    r = GRASSETTO.sub(r"<strong>\1</strong>", str(escape(testo)))
    return Markup(LINK.sub(r'<a href="\2" target="_blank" rel="noopener noreferrer">\1</a>', r))


def markdown(testo: str) -> Markup:
    """Il Markdown delle risposte, minimo e sicuro: righe come in riga(), più gli elenchi (un
    blocco in cui ogni riga comincia con «-», «*», «•» o «1.»)."""
    blocchi = []
    for blocco in re.split(r"\n{2,}", testo.strip()):
        righe = blocco.split("\n")
        if all(VOCE_ELENCO.match(r) for r in righe):
            voci = "".join(f"<li>{riga(VOCE_ELENCO.sub('', r))}</li>" for r in righe)
            blocchi.append(f"<ul>{voci}</ul>")
        else:
            blocchi.append(f"<p>{'<br>'.join(riga(r) for r in righe)}</p>")
    return Markup("".join(blocchi))


_ambiente = Environment(
    loader=FileSystemLoader(PAGINE),
    autoescape=True,
    # Un testo che manca è un errore, non un buco nella pagina
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
)
_ambiente.filters["markdown"] = markdown
_ambiente.filters["riga"] = riga
_ambiente.globals["AREE"] = AREE
_ambiente.globals["PRODOTTI"] = PRODOTTI

# I testi nostri entrano nella pagina così come sono, con il loro HTML
_TESTI = {
    lingua: SimpleNamespace(**{nome: Markup(getattr(t, lingua)) for nome, t in TESTI.items()})
    for lingua in LINGUE
}


def testo(nome: str, lingua: Lingua) -> str:
    return getattr(_TESTI[lingua], nome)


def _fai(modello: str, lingua: Lingua, radice: str = "./", **valori) -> str:
    return _ambiente.get_template(modello).render(
        lingua=lingua, t=_TESTI[lingua], radice=radice, **valori
    )


def pagina(lingua: Lingua, utente: Utente | None, google: str, registra: bool) -> str:
    """La home page per chi la apre: google è il client ID per l'accesso (vuoto: niente accesso),
    registra dice se la voce delle chiamate si registra."""
    t = _TESTI[lingua]
    return _fai(
        "pagina.html",
        lingua,
        utente=utente,
        google=google,
        registra=registra,
        testi_script={nome: getattr(t, nome) for nome in DEGLI_SCRIPT},
    )


def pagina_documenti(lingua: Lingua, archivio: Archivio) -> str:
    """L'elenco dei documenti, su /documenti."""
    return _fai("documenti.html", lingua, aree=archivio.per_area())


def pagina_documento(lingua: Lingua, documento: Documento, html: Markup) -> str:
    """Un documento, su /documenti/<area>/<nome>: due cartelle sotto la radice."""
    return _fai("documento.html", lingua, radice="../../", documento=documento, html=html)


def pagina_faq(lingua: Lingua, raccolta: RaccoltaFaq) -> str:
    """Le domande frequenti, su /faq."""
    return _fai("faq.html", lingua, categorie=raccolta.per_categoria())


def pagina_domanda(lingua: Lingua, faq: Faq, html: Markup) -> str:
    """Una domanda frequente, su /faq/<id>: una cartella sotto la radice."""
    return _fai("domanda.html", lingua, radice="../", faq=faq, html=html)


def pagina_amministrazione(
    lingua: Lingua, entrato: bool, utenti: list[Utente], esempio: str
) -> str:
    """La pagina /a: senza la password di amministrazione, solo il campo per scriverla."""
    t = _TESTI[lingua]
    return _fai(
        "amministrazione.html",
        lingua,
        entrato=entrato,
        utenti=utenti,
        # Per la finestra «Modifica»: i dati di ogni utente, per id
        da_modificare={u.id: u.nel_json() for u in utenti},
        esempio=esempio,
        testi_script={nome: getattr(t, nome) for nome in DEGLI_SCRIPT},
    )


def per_la_pagina(tipo: str, dati: dict, lingua: Lingua) -> dict:
    """Ciò che la pagina fa con un evento: il messaggio da aggiungere e la riga di attesa."""
    if tipo == "stato":
        return {"attesa": dati["testo"]} if dati.get("testo") else {}
    if tipo not in MESSAGGI:
        return {}
    t = _TESTI[lingua]
    html = _ambiente.get_template("messaggio.html").render(tipo=tipo, dati=dati, t=t)
    return {"html": html.strip(), "attesa": str(t.ci_penso) if tipo == "utente" else ""}
