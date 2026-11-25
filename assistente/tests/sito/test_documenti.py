import httpx
import pytest

from assistente.config import Impostazioni
from assistente.rag.client import ClientAssistente
from assistente.server import crea_app
from assistente.sito.documenti import Archivio, in_html, prodotto, titolo
from assistente.sito.pagina import markdown, per_la_pagina

AVVISO = "<!-- Dati sintetici generati con strumenti di AI. -->\n\n"
DIP_CASA = (
    AVVISO
    + "<!-- pagina 1 -->\n\n# Assicurazione Multirischi Abitazione\n\n"
    + "Prodotto: Casa Velaria - ed. 10/2026\n\n"
    + "<!-- pagina 2 -->\n\n# Che cosa è assicurato?\n\n✔ Incendio <script>alert(1)</script>\n"
)


@pytest.fixture
def cartella(tmp_path):
    """Una cartella di documenti come quella vera, piccola."""
    file = {
        "casa_e_famiglia/dip_documento_informativo_precontrattuale_casa.md": DIP_CASA,
        "casa_e_famiglia/modulo_di_disdetta.md": AVVISO + "Spett.le Velaria",
        "auto_e_altri_veicoli/condizioni_di_assicurazione_auto_2.md": AVVISO + "# AUTO",
        "auto_e_altri_veicoli/condizioni_di_assicurazione_auto.md": AVVISO + "# AUTO",
        "sconosciuta/nota.md": "# Nota",
    }
    for percorso, testo in file.items():
        (tmp_path / percorso).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / percorso).write_text(testo, encoding="utf-8")
    return tmp_path


def _server(cartella) -> httpx.AsyncClient:
    app = crea_app(
        Impostazioni(documenti=cartella),
        precarica=False,
        client=ClientAssistente("http://127.0.0.1:9"),
    )
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://voce")


@pytest.mark.parametrize(
    "nome, atteso",
    [
        (
            "dip_aggiuntivo_documento_informativo_precontrattuale_aggiuntivo_moto_3",
            "DIP aggiuntivo moto 3",
        ),
        (
            "dichiarazioni_dell_assicurato_in_caso_di_infortuni_del_conducente",
            "Dichiarazioni dell'assicurato in caso di infortuni del conducente",
        ),
        (
            "informativa_periodica_sulla_sostenibilita_al_31_12_2025",
            "Informativa periodica sulla sostenibilità al 31/12/2025",
        ),
        ("nota_informativa_parte_ii_opzioni", "Nota informativa parte II opzioni"),
        ("mandato_per_addebito_diretto_sepa_sdd", "Mandato per addebito diretto SEPA SDD"),
    ],
)
def test_titolo_dal_nome_del_file(nome, atteso):
    assert titolo(nome) == atteso


def test_prodotto_scritto_in_testa():
    assert prodotto(DIP_CASA) == "Casa Velaria - ed. 10/2026"
    assert prodotto(AVVISO + "Spett.le Velaria") == ""


def test_html_con_le_ancore_di_pagine_e_titoli():
    html = in_html(DIP_CASA)
    assert '<p class="pagina" id="pagina-1">p. 1</p>' in html
    assert '<p class="pagina" id="pagina-2">p. 2</p>' in html
    # I titoli del file scendono di un livello: il titolo della pagina è l'h1
    assert '<h2 id="che-cosa-e-assicurato">Che cosa è assicurato?</h2>' in html
    # L'HTML del file resta testo, e i commenti spariscono
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert "Dati sintetici" not in html


def test_archivio_per_area_e_solo_i_documenti_letti(cartella):
    archivio = Archivio(cartella)
    assert len(archivio) == 4
    aree = archivio.per_area()
    # L'ordine delle aree è quello della home page; «auto» viene prima di «auto 2»
    assert [area for area, _ in aree] == ["auto_e_altri_veicoli", "casa_e_famiglia"]
    assert [d.nome for d in aree[0][1]] == [
        "condizioni_di_assicurazione_auto",
        "condizioni_di_assicurazione_auto_2",
    ]
    assert archivio.trova("sconosciuta", "nota") is None
    assert archivio.trova("casa_e_famiglia", "../casa_e_famiglia/modulo_di_disdetta") is None
    disdetta = archivio.trova("casa_e_famiglia", "modulo_di_disdetta")
    assert disdetta.indirizzo == "documenti/casa_e_famiglia/modulo_di_disdetta"


def test_archivio_senza_cartella(tmp_path):
    archivio = Archivio(tmp_path / "manca")
    assert len(archivio) == 0 and archivio.per_area() == []


async def test_elenco_dei_documenti(cartella):
    async with _server(cartella) as server:
        risposta = await server.get("/documenti")
    assert risposta.status_code == 200
    pagina = risposta.text
    assert '<section id="casa_e_famiglia"' in pagina and 'href="#casa_e_famiglia"' in pagina
    assert '<span class="conta">2</span>' in pagina  # i documenti di un'area
    assert 'href="./documenti/casa_e_famiglia/dip_documento_informativo_precontrattuale_casa"' in (
        pagina
    )
    assert 'DIP casa <span class="documento-prodotto">· Casa Velaria - ed. 10/2026</span>' in pagina
    assert 'id="vita_e_risparmio"' not in pagina  # un'area senza documenti non c'è


async def test_un_documento(cartella):
    indirizzo = "/documenti/casa_e_famiglia/dip_documento_informativo_precontrattuale_casa"
    async with _server(cartella) as server:
        risposta = await server.get(indirizzo)
    assert risposta.status_code == 200
    pagina = risposta.text
    assert 'id="pagina-2"' in pagina and 'id="che-cosa-e-assicurato"' in pagina
    # Due cartelle sotto la radice: gli indirizzi relativi risalgono
    assert 'href="../../statico/stile.css"' in pagina
    assert '<a href="../../documenti#casa_e_famiglia">' in pagina


@pytest.mark.parametrize(
    "indirizzo",
    [
        "/documenti/casa_e_famiglia/manca",
        "/documenti/sconosciuta/nota",
        "/documenti/casa_e_famiglia/modulo_di_disdetta.md",
        "/documenti/casa_e_famiglia/..%2F..%2Fsconosciuta%2Fnota",
    ],
)
async def test_documento_che_non_c_e(cartella, indirizzo):
    async with _server(cartella) as server:
        assert (await server.get(indirizzo)).status_code == 404


async def test_la_lingua_dalla_pagina_di_un_documento(cartella):
    async with _server(cartella) as server:
        bandiera = await server.get("/documenti/casa_e_famiglia/modulo_di_disdetta?lingua=en")
        # Relativo: il browser torna allo stesso documento
        assert bandiera.status_code == 303 and bandiera.headers["location"] == "modulo_di_disdetta"
        pagina = (await server.get("/documenti/casa_e_famiglia/modulo_di_disdetta")).text
        assert '<html lang="en">' in pagina and '<article class="documento" lang="it">' in pagina
        bandiera = await server.get("/documenti?lingua=it")
        assert bandiera.headers["location"] == "documenti"


async def test_la_home_porta_ai_documenti(cartella):
    async with _server(cartella) as server:
        pagina = (await server.get("/")).text
    assert '<a href="./documenti">' in pagina  # nel menu
    assert '<a class="tutti-documenti" href="documenti">' in pagina  # nella sezione dei prodotti
    assert 'href="documenti#previdenza"' in pagina  # in ogni area dei prodotti


def test_link_ai_documenti_nelle_risposte():
    html = markdown("Vedi [DIP casa, p. 2](/documenti/casa_e_famiglia/dip#pagina-2).")
    assert '<a href="/documenti/casa_e_famiglia/dip#pagina-2" target="_blank"' in html
    # Solo i documenti di questo sito e gli indirizzi web
    assert "<a" not in markdown("[clic](javascript:alert(1))")
    assert "<a" not in markdown("[clic](/api/uscita)")


def test_le_citazioni_possono_essere_link():
    citazioni = [
        "[DIP casa, p. 2](/documenti/casa_e_famiglia/dip#pagina-2)",
        "CGA Auto <b>ed.</b> 03/2024",
    ]
    html = per_la_pagina("risposta", {"testo": "Sì.", "citazioni": citazioni}, "it")["html"]
    assert '<li><a href="/documenti/casa_e_famiglia/dip#pagina-2"' in html
    assert "<li>CGA Auto &lt;b&gt;ed.&lt;/b&gt; 03/2024</li>" in html
