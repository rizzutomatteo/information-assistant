#!/usr/bin/env python3
"""Toglie l'indice dai documenti Markdown e riordina i marcatori di pagina.

Uso:
    python togli_indice.py documenti_anonimi --uscita documenti_senza_indice
    python togli_indice.py file1.md file2.md --uscita prova
    python togli_indice.py documenti_anonimi --uscita prova --mostra   # stampa le righe tolte

Cosa fa, per ogni file .md (anche nelle sottocartelle):
1. trova il titolo dell'indice (una riga che contiene solo "Indice", "INDICE" o "Sommario",
   anche come titolo Markdown o in grassetto) e toglie l'indice che lo segue: le voci con il
   numero di pagina in fondo ("... 12", "... Pag. 3 di 48", "... IV"), le righe di tabella,
   i sottotitoli, le righe che continuano una voce, i separatori. Se l'indice non ha numeri
   di pagina (solo titoli), lo toglie fino al marcatore di pagina successivo.
   I marcatori <!-- pagina N --> che stanno dentro l'indice restano;
2. dove due o più marcatori di pagina sono attaccati, cioè separati solo da righe vuote,
   tiene solo l'ultimo (quello più in basso).

Non sovrascrive gli originali: scrive i file nuovi nella cartella --uscita, con la stessa
struttura di sottocartelle. Alla fine stampa un riepilogo per file.
"""
import argparse
import re
import sys
from pathlib import Path

MARCATORE = re.compile(r"^\s*<!--\s*pagina\s+\d+\s*-->\s*$")
TITOLO_INDICE = re.compile(r"^\s*(#{1,6}\s*)?(\*\*|__)?\s*(indice|sommario)\s*(\*\*|__)?\s*:?\s*$",
                           re.IGNORECASE)
# Voce con il numero di pagina in fondo: "Art. 2 - Decorrenza 15", "SEZIONE 1 > DEFINIZIONI ... 1",
# "Definizioni ... Pag. 1 di 48", "Contatti Utili ... IV", anche dentro una tabella "| ... | 14 |".
VOCE = re.compile(r"(\s|\.|…|\||-)\s*(pag\.?\s*)?(\d{1,3}|(?-i:[IVXLC]{1,6}))(\s+di\s+\d{1,3})?\s*\|?\s*$",
                  re.IGNORECASE)
SEPARATORE_TABELLA = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$")
RIGA_TABELLA = re.compile(r"^\s*\|.*\|\s*$")
MAX_CONTINUAZIONE = 200   # una riga di continuazione non è un paragrafo intero
MAX_RIGHE_SENZA_VOCE = 3  # oltre queste righe di fila senza una voce, l'indice è finito


def e_voce(riga):
    s = riga.strip()
    if not s or s.startswith("#"):
        return False
    if len(s) > 200:
        return False
    return bool(VOCE.search(s))


def e_continuazione(riga):
    """Riga corta che può stare dentro un indice senza essere una voce: un sottotitolo
    ("## B. Definizioni") o il seguito di una voce andata a capo."""
    s = riga.strip()
    if not 0 < len(s) <= MAX_CONTINUAZIONE or s.startswith("- >"):
        return False
    return s.startswith("#") or not s.endswith((".", ";", ":"))


def trova_indice(righe):
    """Restituisce (inizio, fine) dell'indice (fine esclusa), o None se non c'è."""
    for i, riga in enumerate(righe):
        if not TITOLO_INDICE.match(riga):
            continue
        ultima_voce, senza_voce = None, 0
        for j in range(i + 1, len(righe)):
            r = righe[j]
            if not r.strip() or MARCATORE.match(r) or SEPARATORE_TABELLA.match(r):
                continue
            if e_voce(r) or (RIGA_TABELLA.match(r) and ultima_voce is not None):
                ultima_voce, senza_voce = j, 0
            elif e_continuazione(r):
                senza_voce += 1
                if senza_voce > MAX_RIGHE_SENZA_VOCE:
                    break
            else:
                break
        if ultima_voce is not None:
            return i, ultima_voce + 1
        fine = indice_senza_numeri(righe, i)
        if fine:
            return i, fine
    return None


def indice_senza_numeri(righe, i):
    """Indice senza numeri di pagina (solo titoli): finisce al primo marcatore di pagina.
    Vale solo se in mezzo ci sono almeno 5 righe e sono tutte titoli corti."""
    titoli = 0
    for j in range(i + 1, min(len(righe), i + 400)):
        s = righe[j].strip()
        if MARCATORE.match(righe[j]):
            return j if titoli >= 5 else None
        if not s:
            continue
        if len(s) > 160 or (not s.startswith("#") and s.endswith((".", ";", ":"))):
            return None
        titoli += 1
    return None


def unisci_marcatori(righe):
    """Tra marcatori separati solo da righe vuote tiene l'ultimo. Restituisce (righe, tolti)."""
    out, tolti = [], 0
    for riga in righe:
        if MARCATORE.match(riga):
            # risale oltre le righe vuote: se prima c'è un marcatore, lo toglie
            k = len(out) - 1
            while k >= 0 and not out[k].strip():
                k -= 1
            if k >= 0 and MARCATORE.match(out[k]):
                del out[k:]
                tolti += 1
        out.append(riga)
    return out, tolti


def pulisci(testo):
    righe = testo.split("\n")
    info = {"indice": None, "righe_tolte": [], "marcatori_uniti": 0}
    pos = trova_indice(righe)
    if pos:
        inizio, fine = pos
        info["indice"] = (inizio + 1, fine)
        tenute = []
        for k in range(inizio, fine):
            if MARCATORE.match(righe[k]):
                tenute += [righe[k], ""]
            elif righe[k].strip():
                info["righe_tolte"].append(righe[k])
        righe = righe[:inizio] + tenute + righe[fine:]
    righe, info["marcatori_uniti"] = unisci_marcatori(righe)
    testo = re.sub(r"\n{3,}", "\n\n", "\n".join(righe))
    return testo, info


def file_da(percorsi):
    for p in map(Path, percorsi):
        if p.is_dir():
            for f in sorted(p.rglob("*.md")):
                yield f, f.relative_to(p)
        elif p.suffix == ".md":
            yield p, Path(p.name)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("percorsi", nargs="+", help="file .md o cartelle")
    ap.add_argument("--uscita", required=True, help="cartella dove scrivere i file puliti")
    ap.add_argument("--mostra", action="store_true", help="stampa le righe tolte da ogni indice")
    a = ap.parse_args()

    uscita = Path(a.uscita)
    n_file = n_indici = n_marcatori = 0
    for f, rel in file_da(a.percorsi):
        testo = f.read_text(encoding="utf-8")
        nuovo, info = pulisci(testo)
        dest = uscita / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(nuovo, encoding="utf-8")
        n_file += 1
        n_marcatori += info["marcatori_uniti"]
        if info["indice"]:
            n_indici += 1
            da, a_ = info["indice"]
            print(f"{rel}: indice alle righe {da}-{a_}, {len(info['righe_tolte'])} righe tolte, "
                  f"{info['marcatori_uniti']} marcatori uniti")
            if a.mostra:
                for r in info["righe_tolte"]:
                    print("    - " + r.strip()[:110])
        elif info["marcatori_uniti"]:
            print(f"{rel}: nessun indice, {info['marcatori_uniti']} marcatori uniti")
    print(f"\n{n_file} file, {n_indici} indici tolti, {n_marcatori} marcatori uniti. "
          f"File scritti in {uscita}")


if __name__ == "__main__":
    sys.exit(main())
