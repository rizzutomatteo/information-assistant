"""Toglie da documenti_anonimi/ i documenti presenti in più aree della raccolta.

I documenti sono dati sintetici, generati con strumenti di AI a partire da documentazione
assicurativa pubblica (vedi anonimizza.py).

    python3 deduplica.py            elimina le copie e scrive duplicati.tsv
    python3 deduplica.py --prova    mostra solo cosa farebbe

Due file sono la stessa cosa quando hanno lo stesso contenuto, byte per byte: il nome non conta.
Per ogni gruppo di copie se ne tiene una sola, scelta così:

1. mai un file con il titolo sbagliato (SBAGLIATI, qui sotto);
2. prima un nome che dice cos'è il documento ("modulo_unico_precontrattuale_mup_..._allegato_3")
   rispetto a un nome generico ("allegato_3");
3. poi la cartella che viene prima in CARTELLE.

duplicati.tsv elenca per ogni file tenuto le copie tolte e tutte le aree in cui il documento era
pubblicato: un documento tolto da "previdenza" resta trovabile anche per quell'area, se chi
prepara i chunk usa la colonna "aree". Usa solo la libreria standard di Python.
"""

import argparse
import csv
import hashlib
import re
from collections import defaultdict
from pathlib import Path

QUI = Path(__file__).resolve().parent
CARTELLE = ["auto_e_altri_veicoli", "casa_e_famiglia", "vita_e_risparmio", "previdenza"]

# Pubblicati sul sito con il titolo sbagliato: "senza modulo blu" contiene in realtà il modulo
# "con modulo blu", identico all'altro file.
SBAGLIATI = {"auto_e_altri_veicoli/richiesta_danni_a_responsabile_civile_senza_modulo_blu_e_con_lesioni.md"}

NOME_GENERICO = re.compile(r"^allegato_\d+$")


def priorita(relativo):
    """Più è bassa, più il file merita di essere tenuto."""
    cartella = relativo.parts[0]
    return (
        relativo.as_posix() in SBAGLIATI,
        bool(NOME_GENERICO.match(relativo.stem)),
        CARTELLE.index(cartella) if cartella in CARTELLE else len(CARTELLE),
        relativo.as_posix(),
    )


def main():
    argomenti = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    argomenti.add_argument("--testi", type=Path, default=QUI / "documenti_anonimi")
    argomenti.add_argument("--elenco", type=Path, default=QUI / "duplicati.tsv")
    argomenti.add_argument("--prova", action="store_true", help="non elimina nulla")
    a = argomenti.parse_args()

    gruppi = defaultdict(list)
    for percorso in sorted(a.testi.rglob("*.md")):
        impronta = hashlib.sha256(percorso.read_bytes()).hexdigest()
        gruppi[impronta].append(percorso.relative_to(a.testi))

    righe, tolti = [], 0
    for copie in gruppi.values():
        if len(copie) < 2:
            continue
        tenuto, *doppi = sorted(copie, key=priorita)
        aree = sorted({c.parts[0] for c in copie}, key=lambda x: CARTELLE.index(x) if x in CARTELLE else 99)
        righe.append((tenuto.as_posix(), " ".join(d.as_posix() for d in doppi), " ".join(aree)))
        for doppio in doppi:
            print(f"tolgo {doppio}  (uguale a {tenuto})")
            if not a.prova:
                (a.testi / doppio).unlink()
            tolti += 1

    righe.sort()
    if not a.prova:
        with open(a.elenco, "w", encoding="utf-8", newline="") as f:
            scrivi = csv.writer(f, delimiter="\t", lineterminator="\n")
            scrivi.writerow(["tenuto", "copie_tolte", "aree"])
            scrivi.writerows(righe)
    rimasti = sum(len(c) for c in gruppi.values()) - tolti
    print(f"{len(righe)} gruppi di copie, {tolti} file tolti, {rimasti} documenti unici"
          + ("" if a.prova else f"; elenco in {a.elenco}"))


if __name__ == "__main__":
    main()
