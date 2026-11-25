import json

import httpx
import pytest

from assistente.config import CARTELLA_PROGETTO, Impostazioni
from assistente.rag.client import ClientAssistente
from assistente.server import crea_app
from assistente.sito.faq import FILE, RaccoltaFaq
from assistente.sito.pagina import markdown

FAQ = [
    {
        "id": "15-giorni-copertura",
        "domanda": "Alla scadenza ci sono i 15 giorni di copertura?",
        "risposta": "Sì, fino alle ore 24 del 15° giorno.",
        "categorie": ["Assicurazione Veicoli", "Gestione polizza"],
    },
    {
        "id": "assicurare-casa-da-terremoti",
        "domanda": "Posso assicurare la Casa per i terremoti?",
        "risposta": "Sì.\n\n## Cosa coprono le garanzie\n\n- Terremoto <script>alert(1)</script>",
        "categorie": ["FAQ Casa, Famiglia, Cane e Gatto, Mutuo, Viaggi"],
    },
    {"id": "sinistro-fgvs", "domanda": "Cos'è il FGVS?", "risposta": "Un fondo.", "categorie": []},
    {"id": "nuova", "domanda": "Una domanda nuova?", "risposta": "Sì.", "categorie": ["Novità"]},
]


@pytest.fixture
def cartella(tmp_path):
    """Una cartella di documenti con un faq.json come quello vero, piccolo."""
    (tmp_path / FILE).write_text(json.dumps({"versione": "prova", "faq": FAQ}), encoding="utf-8")
    return tmp_path


def _server(cartella) -> httpx.AsyncClient:
    app = crea_app(
        Impostazioni(documenti=cartella),
        precarica=False,
        client=ClientAssistente("http://127.0.0.1:9"),
    )
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://voce")


def test_per_categoria(cartella):
    raccolta = RaccoltaFaq(cartella)
    assert len(raccolta) == 4
    categorie = [
        (c.titolo, c.ancora, c.icona, [f.id for f in domande])
        for c, domande in raccolta.per_categoria()
    ]
    # L'ordine è quello di CATEGORIE, poi le categorie nuove, poi le domande senza categoria; una
    # domanda con due categorie sta in tutte e due, e il «FAQ» del nome sparisce
    assert categorie == [
        ("Assicurazione Veicoli", "assicurazione-veicoli", "auto", ["15-giorni-copertura"]),
        (
            "Casa, Famiglia, Cane e Gatto, Mutuo, Viaggi",
            "casa-famiglia-cane-e-gatto-mutuo-viaggi",
            "casa",
            ["assicurare-casa-da-terremoti"],
        ),
        ("Gestione polizza", "gestione-polizza", "documento", ["15-giorni-copertura"]),
        ("Novità", "novita", "domanda", ["nuova"]),
        ("", "altre", "domanda", ["sinistro-fgvs"]),
    ]


def test_risposta_in_html(cartella):
    raccolta = RaccoltaFaq(cartella)
    html = raccolta.html(raccolta.trova("assicurare-casa-da-terremoti"))
    # «##» diventa h2, sotto la domanda che è l'h1 della pagina
    assert '<h2 id="cosa-coprono-le-garanzie">Cosa coprono le garanzie</h2>' in html
    assert "<script>" not in html and "&lt;script&gt;" in html


def test_senza_file(tmp_path):
    raccolta = RaccoltaFaq(tmp_path)
    assert len(raccolta) == 0 and raccolta.per_categoria() == []


def test_il_file_vero():
    raccolta = RaccoltaFaq(CARTELLA_PROGETTO / "documenti")
    assert len(raccolta) == 171
    # Ogni categoria del file ha la sua icona: nessuna è finita in fondo come «nuova»
    icone = [c.icona for c, _ in raccolta.per_categoria() if c.nome]
    assert "domanda" not in icone


async def test_elenco_delle_faq(cartella):
    async with _server(cartella) as server:
        risposta = await server.get("/faq")
    assert risposta.status_code == 200
    pagina = risposta.text
    assert '<section id="gestione-polizza"' in pagina and 'href="#gestione-polizza"' in pagina
    assert 'href="./faq/15-giorni-copertura"' in pagina
    assert pagina.count('href="./faq/15-giorni-copertura"') == 2  # in due categorie
    assert '<span lang="it">Casa, Famiglia, Cane e Gatto, Mutuo, Viaggi</span>' in pagina
    assert '<section id="altre"' in pagina and "Altre domande" in pagina
    assert 'id="sinistri"' not in pagina  # una categoria senza domande non c'è


async def test_una_domanda(cartella):
    async with _server(cartella) as server:
        risposta = await server.get("/faq/assicurare-casa-da-terremoti")
    assert risposta.status_code == 200
    pagina = risposta.text
    assert '<h1 lang="it">Posso assicurare la Casa per i terremoti?</h1>' in pagina
    assert 'id="cosa-coprono-le-garanzie"' in pagina
    # Una cartella sotto la radice: gli indirizzi relativi risalgono di uno
    assert 'href="../statico/stile.css"' in pagina
    assert '<a href="../faq#casa-famiglia-cane-e-gatto-mutuo-viaggi" lang="it">' in pagina


async def test_domanda_senza_categoria(cartella):
    async with _server(cartella) as server:
        pagina = (await server.get("/faq/sinistro-fgvs")).text
    assert '<a href="../faq#altre">Altre domande</a>' in pagina


@pytest.mark.parametrize("indirizzo", ["/faq/manca", "/faq/..%2Ffaq.json", "/faq/nuova/altro"])
async def test_domanda_che_non_c_e(cartella, indirizzo):
    async with _server(cartella) as server:
        assert (await server.get(indirizzo)).status_code == 404


async def test_la_lingua_dalle_faq(cartella):
    async with _server(cartella) as server:
        bandiera = await server.get("/faq/nuova?lingua=en")
        # Relativo: il browser torna alla stessa domanda
        assert bandiera.status_code == 303 and bandiera.headers["location"] == "nuova"
        pagina = (await server.get("/faq/nuova")).text
        assert '<html lang="en">' in pagina and '<article class="documento" lang="it">' in pagina
        assert (await server.get("/faq?lingua=it")).headers["location"] == "faq"


async def test_la_home_porta_alle_faq(cartella):
    async with _server(cartella) as server:
        pagina = (await server.get("/")).text
    assert '<a href="./faq">' in pagina  # nel menu
    assert '<a class="tutte-faq" href="faq">' in pagina  # nella sezione dei contatti


def test_link_alle_faq_nelle_risposte():
    html = markdown("Vedi [la FAQ](/faq/15-giorni-copertura).")
    assert '<a href="/faq/15-giorni-copertura" target="_blank"' in html
