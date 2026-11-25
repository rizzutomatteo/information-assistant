import copy
import json
from datetime import date
from decimal import Decimal

import httpx
import pytest

from assistente.accesso.amministrazione import ESEMPIO
from assistente.accesso.sessioni import Limite
from assistente.accesso.utenti import (
    PIN_DEMO,
    Anagrafe,
    Conflitto,
    FileUtenti,
    Polizza,
    Registrazione,
    impronta_password,
    password_giusta,
)
from assistente.config import Impostazioni
from assistente.rag.client import ClientAssistente
from assistente.server import crea_app

PASSWORD_A = "password-di-amministrazione"
# Lo stampino del JSON di /a, letto dal suo file
STAMPINO = json.loads(ESEMPIO.read_text(encoding="utf-8"))


def _file(**cambi) -> dict:
    """Il JSON di esempio, con i campi del primo utente cambiati."""
    dati = copy.deepcopy(STAMPINO)
    dati["utenti"][0].update(cambi)
    return dati


def _carica(anagrafe: Anagrafe, dati: dict) -> tuple[int, int]:
    utenti = FileUtenti.model_validate(dati).utenti
    return anagrafe.carica(utenti, {u.utente: impronta_password(u.password) for u in utenti})


def test_lo_stampino_della_pagina_a_e_valido():
    assert FileUtenti.model_validate(STAMPINO).utenti[0].utente == "giulia.verdi"


def test_al_primo_avvio_c_e_solo_mario_rossi(tmp_path):
    anagrafe = Anagrafe(tmp_path / "utenti.sqlite")
    (mario,) = anagrafe.elenco()
    assert (mario.nome_completo, mario.pin_telefono, len(mario.polizze)) == (
        "Mario Rossi",
        PIN_DEMO,
        2,
    )
    # Senza password: con utente e password non si entra
    assert anagrafe.impronta("mario.rossi") is None


def test_le_due_copie_del_sito_vedono_gli_stessi_utenti(tmp_path):
    privata, pubblica = Anagrafe(tmp_path / "u.sqlite"), Anagrafe(tmp_path / "u.sqlite")
    _carica(privata, STAMPINO)
    giulia = pubblica.da_pin("246810")
    assert giulia.nome_completo == "Giulia Verdi" and len(pubblica.elenco()) == 2
    pubblica.aggiungi_polizza(giulia.id, giulia.polizze[0])
    assert len(privata.da_pin("246810").polizze) == 2


def test_caricare_crea_e_poi_sostituisce():
    anagrafe = Anagrafe(None)
    assert _carica(anagrafe, STAMPINO) == (1, 0)
    assert _carica(anagrafe, _file(nome="Giulia Maria", polizze=[])) == (0, 1)
    giulia = anagrafe.da_pin("246810")
    assert giulia.nome == "Giulia Maria" and giulia.polizze == ()


def test_il_pin_si_sceglie_se_manca_e_resta_quando_si_sostituisce():
    anagrafe = Anagrafe(None)
    _carica(anagrafe, _file(pin_telefono=None))
    (pin,) = [u.pin_telefono for u in anagrafe.elenco() if u.utente == "giulia.verdi"]
    assert len(pin) == 6 and pin != PIN_DEMO
    _carica(anagrafe, _file(pin_telefono=None, nome="Giulia Maria"))
    assert anagrafe.da_pin(pin).nome == "Giulia Maria"


def test_pin_ed_email_di_un_altro_utente_non_si_possono_usare():
    anagrafe = Anagrafe(None)
    with pytest.raises(Conflitto, match="mario.rossi"):
        _carica(anagrafe, _file(pin_telefono=PIN_DEMO))
    anagrafe.da_google("anna@example.com", "Anna", "Bianchi")
    with pytest.raises(Conflitto):
        _carica(anagrafe, _file(email="anna@example.com"))
    # Tutto o niente: nessun utente nuovo
    assert len(anagrafe.elenco()) == 2


@pytest.mark.parametrize(
    "cambi",
    [
        {"utente": "Giulia Verdi"},  # spazi e maiuscole
        {"password": "corta"},
        {"pin_telefono": "12345"},
        {"email": "non-una-email"},
        {"polizze": [{**STAMPINO["utenti"][0]["polizze"][0], "prodotto": "Velaria Razzi"}]},
        {"polizze": [{**STAMPINO["utenti"][0]["polizze"][0], "scadenza": "30/09/2027"}]},
        {"campo_in_piu": 1},
    ],
)
def test_json_sbagliato(cambi):
    with pytest.raises(ValueError):
        FileUtenti.model_validate(_file(**cambi))


def test_doppioni_nel_file():
    dati = _file()
    dati["utenti"].append(copy.deepcopy(dati["utenti"][0]))
    with pytest.raises(ValueError, match="utente"):
        FileUtenti.model_validate(dati)


def test_password():
    impronta = impronta_password("una-password-lunga")
    assert impronta.startswith("scrypt$") and "una-password" not in impronta
    assert password_giusta("una-password-lunga", impronta)
    assert not password_giusta("un'altra-password", impronta)
    assert not password_giusta("una-password-lunga", None)


def test_google_la_prima_volta_crea_l_utente_con_i_dati_di_prova():
    anagrafe = Anagrafe(None)
    anna = anagrafe.da_google("anna@example.com", "Anna", "Bianchi")
    assert len(anna.polizze) == 2 and anna.pin_telefono != PIN_DEMO
    assert anagrafe.da_google("anna@example.com", "Anna", "Bianchi").id == anna.id


def test_polizze_aggiunte_e_tolte_solo_dal_loro_utente():
    anagrafe = Anagrafe(None)
    mario = anagrafe.da_pin(PIN_DEMO)
    anna = anagrafe.da_google("anna@example.com", "Anna", "Bianchi")
    nuova = Polizza(
        "Velaria Moto", "77", "Moto targata AA00000", date(2028, 1, 31), Decimal("99.5"), ()
    )
    id_polizza = anagrafe.aggiungi_polizza(mario.id, nuova)
    assert anagrafe.utente(mario.id).polizze[-1].premio_testo == "€ 99,50"
    assert not anagrafe.togli_polizza(anna.id, id_polizza)
    assert anagrafe.togli_polizza(mario.id, id_polizza)
    assert len(anagrafe.utente(mario.id).polizze) == 2


def test_importi_e_date_all_italiana():
    p = Polizza("Casa Velaria", "1", "Casa", date(2027, 3, 5), Decimal("1480.5"), ())
    assert (p.premio_testo, p.scadenza_testo, p.tipo) == ("€ 1.480,50", "05/03/2027", "casa")


def _nuova(**cambi) -> Registrazione:
    dati = {"nome": "Luca", "utente": "Luca.Neri", "password": "una-password-lunga"} | cambi
    return Registrazione.model_validate(dati)


def test_registrazione_crea_un_account_senza_polizze():
    anagrafe = Anagrafe(None)
    luca = anagrafe.registra(_nuova(), impronta_password("una-password-lunga"))
    # Il nome utente si salva in minuscolo; niente dati di prova né polizze: le aggiunge lui
    assert (luca.utente, luca.polizze, luca.codice_fiscale) == ("luca.neri", (), "")
    assert luca.pin_telefono != PIN_DEMO and anagrafe.impronta("LUCA.NERI")[0] == luca.id


def test_registrazione_con_nome_o_email_gia_usati():
    anagrafe = Anagrafe(None)
    with pytest.raises(Conflitto) as conflitto:
        anagrafe.registra(_nuova(utente="mario.rossi"), "impronta")
    assert conflitto.value.campo == "utente"
    anagrafe.registra(_nuova(email="luca@example.com"), "impronta")
    with pytest.raises(Conflitto) as conflitto:
        anagrafe.registra(_nuova(utente="luca2", email="luca@example.com"), "impronta")
    assert conflitto.value.campo == "email"


@pytest.mark.parametrize("cambi", [{"password": "corta"}, {"utente": "lu"}, {"nome": ""}])
def test_registrazione_sbagliata(cambi):
    with pytest.raises(ValueError):
        _nuova(**cambi)


def test_limite():
    limite = Limite(2, 60)
    limite.conta("x")
    assert not limite.superato("x")
    limite.conta("x")
    assert limite.superato("x") and not limite.superato("y")
    limite.azzera("x")
    assert not limite.superato("x")


# --- Dal sito: registrazione, accesso con password, polizze, pagina /a ---------------------


def _server(password_a: str = PASSWORD_A) -> httpx.AsyncClient:
    app = crea_app(
        Impostazioni(amministrazione_password=password_a),
        precarica=False,
        client=ClientAssistente("http://127.0.0.1:9"),
    )
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://voce")


async def _carica_dal_sito(server: httpx.AsyncClient, dati: dict) -> httpx.Response:
    assert (await server.post("/api/a/accesso", json={"password": PASSWORD_A})).status_code == 200
    return await server.post("/api/a/utenti", json=dati)


async def test_senza_password_di_amministrazione_la_pagina_a_non_c_e():
    async with _server(password_a="") as server:
        assert (await server.get("/a")).status_code == 404
        risposta = await server.post("/api/a/accesso", json={"password": "x"})
        assert risposta.status_code == 404


async def test_pagina_a_prima_la_password_poi_il_json():
    async with _server() as server:
        pagina = (await server.get("/a")).text
        assert 'id="a-accesso"' in pagina and 'id="a-utenti"' not in pagina
        assert (await server.post("/api/a/utenti", json=STAMPINO)).status_code == 401
        sbagliata = await server.post("/api/a/accesso", json={"password": "no"})
        assert sbagliata.status_code == 401

        risposta = await _carica_dal_sito(server, STAMPINO)
        assert risposta.json() == {"creati": 1, "sostituiti": 0}
        pagina = (await server.get("/a")).text
        assert 'id="a-utenti"' in pagina and "<td>giulia.verdi</td>" in pagina
        assert "una-password-lunga" in pagina  # solo nell'esempio, mai quelle caricate
        assert pagina.count("una-password-lunga") == 1


async def test_pagina_a_json_sbagliato_o_in_conflitto():
    async with _server() as server:
        sbagliato = await _carica_dal_sito(server, _file(pin_telefono="12"))
        assert sbagliato.status_code == 422
        assert sbagliato.json()["detail"][0]["loc"][-1] == "pin_telefono"
        conflitto = await server.post("/api/a/utenti", json=_file(pin_telefono=PIN_DEMO))
        assert conflitto.status_code == 409 and "mario.rossi" in conflitto.json()["detail"]


async def test_troppe_password_sbagliate():
    async with _server() as server:
        for _ in range(5):
            await server.post("/api/a/accesso", json={"password": "no"})
        giusta = await server.post("/api/a/accesso", json={"password": PASSWORD_A})
        assert giusta.status_code == 429
        for _ in range(5):
            await server.post("/api/accesso/password", json={"utente": "x", "password": "no"})
        risposta = await server.post("/api/accesso/password", json={"utente": "x", "password": "y"})
        assert risposta.status_code == 429


async def test_utente_e_password_poi_polizze_aggiunte_e_tolte():
    async with _server() as server:
        await _carica_dal_sito(server, STAMPINO)
        sbagliata = {"utente": "giulia.verdi", "password": "sbagliata"}
        assert (await server.post("/api/accesso/password", json=sbagliata)).status_code == 401

        giusta = {"utente": "Giulia.Verdi", "password": "una-password-lunga"}
        risposta = await server.post("/api/accesso/password", json=giusta)
        assert risposta.status_code == 200 and risposta.json()["nome"] == "Giulia"
        pagina = (await server.get("/")).text
        assert pagina.count('<article class="scheda polizza ') == 1 and "€ 520,00" in pagina

        nuova = {
            "prodotto": "Casa Velaria",
            "numero": "555",
            "oggetto": "Appartamento",
            "scadenza": "2028-01-31",
            "premio": "199.9",
            "garanzie": ["Incendio e scoppio"],
        }
        risposta = await server.post("/api/polizze", json=nuova)
        assert risposta.status_code == 201
        pagina = (await server.get("/")).text
        assert 'polizza polizza-casa"' in pagina and "31/01/2028" in pagina and "€ 199,90" in pagina
        assert (await server.post("/api/polizze", json={**nuova, "premio": -1})).status_code == 422

        assert (await server.delete(f"/api/polizze/{risposta.json()['id']}")).status_code == 204
        assert (await server.delete("/api/polizze/1")).status_code == 404  # è di Mario Rossi
        assert (await server.get("/")).text.count('<article class="scheda polizza ') == 1

        await server.post("/api/uscita")
        assert (await server.post("/api/polizze", json=nuova)).status_code == 401


async def test_registrazione_dal_sito_poi_dentro():
    async with _server() as server:
        nuovo = {"nome": "Luca", "utente": "luca.neri", "password": "una-password-lunga"}
        risposta = await server.post("/api/registrazione", json=nuovo)
        assert risposta.status_code == 201 and risposta.json()["utente"] == "luca.neri"
        pagina = (await server.get("/")).text
        assert 'id="esci"' in pagina and 'class="polizze-vuote"' in pagina
        assert "<dd>—</dd>" in pagina  # codice fiscale, telefono e indirizzo non ci sono ancora

        doppio = await server.post("/api/registrazione", json=nuovo)
        assert doppio.status_code == 409 and doppio.json()["detail"]["campo"] == "utente"
        corta = await server.post("/api/registrazione", json={**nuovo, "password": "corta"})
        assert corta.status_code == 422

        await server.post("/api/uscita")
        credenziali = {"utente": "luca.neri", "password": "una-password-lunga"}
        assert (await server.post("/api/accesso/password", json=credenziali)).status_code == 200
