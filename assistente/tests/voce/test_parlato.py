import pytest

from assistente.voce.parlato import PRONUNCE, citazione_parlata, normalizza, risposta_parlata

ITALIANO, INGLESE = PRONUNCE["it"], PRONUNCE["en"]


@pytest.mark.parametrize(
    ("scritto", "detto"),
    [
        ("1500", "millecinquecento"),
        ("1.500", "millecinquecento"),
        ("2,5", "due virgola cinque"),
        ("0,05", "zero virgola zero cinque"),
    ],
)
def test_numeri(scritto, detto):
    assert ITALIANO.numero_in_parole(scritto) == detto


@pytest.mark.parametrize(
    ("scritto", "detto"),
    [
        ("1.500,00", "millecinquecento euro"),
        ("1", "un euro"),
        ("250,50", "duecentocinquanta euro e cinquanta centesimi"),
        ("0,50", "cinquanta centesimi"),
        ("0,01", "un centesimo"),
        ("1.000.000", "un milione di euro"),
        ("6.070.000", "sei milioni e settantamila euro"),
    ],
)
def test_importi(scritto, detto):
    assert ITALIANO.importo_in_parole(scritto) == detto


@pytest.mark.parametrize(
    ("scritto", "detto"),
    [
        ("La franchigia è di € 1.500,00.", "La franchigia è di millecinquecento euro."),
        ("Costa 250 euro.", "Costa duecentocinquanta euro."),
        ("Costa 1.500 €.", "Costa millecinquecento euro."),
        ("Scoperto del 10%.", "Scoperto del dieci per cento."),
        ("Fino al 15° giorno.", "Fino al quindicesimo giorno."),
        ("Edizione 03/2024.", "Edizione marzo duemilaventiquattro."),
        ("Scade il 01/04/2025.", "Scade il primo aprile duemilaventicinque."),
        ("Dalle 9:00 alle 18.30.", "Dalle nove alle diciotto e trenta."),
        (
            "Vedi art. 12 delle CGA.",
            "Vedi articolo dodici delle condizioni generali di assicurazione.",
        ),
        ("Polizza n. 123456.", "Polizza numero uno due tre quattro cinque sei."),
        ("Targa AB123CD.", "Targa a, bi, uno, due, tre, ci, di."),
        ("RC Auto e/o furto/incendio.", "Erre ci Auto e o furto o incendio."),
        ("Scarica l'app Orvenia+.", "Scarica l'app Orvenia più."),
    ],
)
def test_normalizza(scritto, detto):
    assert normalizza(scritto) == detto


def test_markdown_diventa_frasi():
    scritto = "## Come fare\n\nPuoi:\n- scaricare l'**app**\n- accedere all'[Area Riservata](https://x.it/a)"
    assert normalizza(scritto) == ("Come fare. Puoi: scaricare l'app. Accedere all'Area Riservata.")


def test_tabella_senza_intestazione():
    scritto = "| Garanzia | Massimale |\n|---|---|\n| RCA | € 6.070.000 |"
    assert normalizza(scritto) == "Erre ci auto, sei milioni e settantamila euro."


def test_link_ed_email_non_si_dettano():
    assert normalizza("Scrivi a info@esempio.it oppure vai su www.esempio.it/faq.") == (
        "Scrivi all'indirizzo email che trovi nella chat oppure vai sul link che trovi nella chat."
    )
    assert normalizza("Visita https://esempio.it.", chat=False) == (
        "Visita il link che trovi sul nostro sito."
    )


def test_compita():
    assert ITALIANO.compita("AB12") == "a, bi, uno, due"
    assert INGLESE.compita("AB12") == "A, B, one, two"


def test_citazione_senza_pagina():
    assert citazione_parlata("CGA Auto ed. 03/2024, art. 12, p. 18") == (
        "Fonte: condizioni generali di assicurazione Auto edizione marzo duemilaventiquattro, "
        "articolo dodici."
    )
    detta = citazione_parlata("FAQ «Come si fa la disdetta?»")
    assert detta == "Lo trovi tra le domande frequenti."


def test_citazione_con_il_link_al_documento():
    # Il link è per la chat: si dice solo il testo
    documento = "/documenti/auto_e_altri_veicoli/condizioni_di_assicurazione_auto#pagina-18"
    con_link = citazione_parlata(f"[CGA Auto ed. 03/2024, art. 12, p. 18]({documento})")
    assert con_link == citazione_parlata("CGA Auto ed. 03/2024, art. 12, p. 18")
    faq = citazione_parlata("[FAQ «Come si fa la disdetta?»](/documenti/x/y)")
    assert faq == "Lo trovi tra le domande frequenti."


def test_risposta_lunga_rimanda_alla_chat():
    detto = risposta_parlata("Uno. Due. Tre. Quattro.", ["FAQ «x»"], max_frasi=2)
    assert detto == [
        "Uno.",
        "Due.",
        "Il resto te l'ho scritto nella chat.",
        "Lo trovi tra le domande frequenti.",
    ]


def test_risposta_corta_intera():
    assert risposta_parlata("Sì, è coperto.") == ["Sì, è coperto."]


# --- In inglese: la lingua scelta nella pagina --------------------------------------------


@pytest.mark.parametrize(
    ("scritto", "detto"),
    [
        ("1500", "one thousand five hundred"),
        ("1,500", "one thousand five hundred"),
        ("2.5", "two point five"),
        ("0.05", "zero point zero five"),
    ],
)
def test_numeri_in_inglese(scritto, detto):
    assert INGLESE.numero_in_parole(scritto) == detto


@pytest.mark.parametrize(
    ("scritto", "detto"),
    [
        ("1,500.00", "one thousand five hundred euros"),
        ("1", "one euro"),
        ("250.50", "two hundred and fifty euros and fifty cents"),
        ("0.01", "one cent"),
    ],
)
def test_importi_in_inglese(scritto, detto):
    assert INGLESE.importo_in_parole(scritto) == detto


@pytest.mark.parametrize(
    ("scritto", "detto"),
    [
        ("The excess is €1,500.00.", "The excess is one thousand five hundred euros."),
        ("It costs 250 euros.", "It costs two hundred and fifty euros."),
        ("A 10% deductible.", "A ten percent deductible."),
        ("Up to the 15th day.", "Up to the fifteenth day."),
        ("Edition 03/2024.", "Edition March twenty twenty-four."),
        ("It expires on 01/04/2025.", "It expires on the first of April twenty twenty-five."),
        ("From 9:00 to 18:30.", "From nine o'clock to eighteen thirty."),
        ("See art. 12 of the CGA.", "See article twelve of the general terms and conditions."),
        ("Policy no. 123456.", "Policy number one two three four five six."),
        ("Plate AB123CD.", "Plate A, B, one, two, three, C, D."),
        (
            "Roadside assistance 24/7 and/or towing.",
            "Roadside assistance twenty-four seven and or towing.",
        ),
    ],
)
def test_normalizza_in_inglese(scritto, detto):
    assert normalizza(scritto, lingua="en") == detto


def test_link_ed_email_in_inglese():
    assert normalizza("Write to info@example.com or visit www.example.com/faq.", lingua="en") == (
        "Write to the email address you'll find in the chat or visit the link you'll find in the "
        "chat."
    )


def test_citazione_e_resto_in_inglese():
    assert citazione_parlata("CGA Auto ed. 03/2024, art. 12, p. 18", "en") == (
        "Source: general terms and conditions Auto edition March twenty twenty-four, article "
        "twelve."
    )
    detto = risposta_parlata("One. Two. Three.", ["FAQ «x»"], max_frasi=2, lingua="en")
    assert detto == [
        "One.",
        "Two.",
        "I've written the rest in the chat.",
        "You'll find it in the frequently asked questions.",
    ]
