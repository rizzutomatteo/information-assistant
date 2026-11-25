"""Un PostgreSQL per i test che usano l'anagrafe degli utenti (accesso/utenti.py).

Con ASSISTENTE_DATABASE_PROVE (postgresql://…) si usa quel server; altrimenti se ne avvia uno usa
e getta con Docker, con i dati in memoria, che si toglie alla fine. Ogni test ha il suo schema,
cioè tabelle tutte sue: i test non si vedono tra loro.
"""

import os
import shutil
import subprocess
import time
import uuid

import psycopg
import pytest
from psycopg.conninfo import make_conninfo

from assistente.accesso.utenti import Anagrafe

IMMAGINE = "postgres:18.7-alpine"


def _aspetta(indirizzo: str, secondi: float = 30):
    fine = time.monotonic() + secondi
    while True:
        try:
            psycopg.connect(indirizzo).close()
            return
        except psycopg.OperationalError:
            if time.monotonic() > fine:
                raise
            time.sleep(0.2)


@pytest.fixture(scope="session")
def postgres():
    """L'indirizzo del server PostgreSQL dei test."""
    if indirizzo := os.environ.get("ASSISTENTE_DATABASE_PROVE"):
        yield indirizzo
        return
    if not shutil.which("docker"):
        pytest.skip("serve PostgreSQL: ASSISTENTE_DATABASE_PROVE, oppure Docker per avviarne uno")
    nome = f"assistente-prove-{uuid.uuid4().hex[:8]}"
    subprocess.run(
        [
            "docker", "run", "-d", "--rm", "--name", nome,
            "-e", "POSTGRES_USER=prove", "-e", "POSTGRES_PASSWORD=prove",
            # I dati in memoria: più veloce, e alla fine non resta nulla
            "--tmpfs", "/var/lib/postgresql",
            "-p", "127.0.0.1::5432",
            IMMAGINE,
        ],
        check=True,
        capture_output=True,
    )  # fmt: skip
    try:
        uscita = subprocess.run(
            ["docker", "port", nome, "5432"], check=True, capture_output=True, text=True
        )
        porta = uscita.stdout.split()[0].rsplit(":", 1)[1]  # «127.0.0.1:32768»
        indirizzo = f"postgresql://prove:prove@127.0.0.1:{porta}/prove"
        _aspetta(indirizzo)
        yield indirizzo
    finally:
        subprocess.run(["docker", "rm", "-f", nome], capture_output=True)


@pytest.fixture
def indirizzo_db(postgres):
    """Lo stesso server, con uno schema nuovo solo per questo test."""
    schema = f"prova_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(postgres, autocommit=True) as c:
        c.execute(f"CREATE SCHEMA {schema}")
    yield make_conninfo(postgres, options=f"-c search_path={schema}")
    with psycopg.connect(postgres, autocommit=True) as c:
        c.execute(f"DROP SCHEMA {schema} CASCADE")


@pytest.fixture
async def anagrafe(indirizzo_db):
    """Un'anagrafe aperta, come all'avvio del server: c'è solo Mario Rossi."""
    anagrafe = Anagrafe(indirizzo_db)
    await anagrafe.apri()
    yield anagrafe
    await anagrafe.chiudi()
