#!/usr/bin/env python3
"""Toglie il glossario (le definizioni) dai documenti Markdown e lo salva in JSON.

Uso:
    python estrai_glossario.py documenti_senza_indice --uscita documenti_senza_glossario
    python estrai_glossario.py file1.md file2.md --uscita prova

Per ogni file .md (anche nelle sottocartelle) che ha una o più sezioni di definizioni:
1. trova la sezione: un titolo come "B. Definizioni", "SEZIONE 1 > DEFINIZIONI",
   "Definizioni", "DEFINIZIONI" o "Glossario dei termini tecnici". Se il titolo è un titolo
   Markdown (#), la sezione finisce al primo titolo successivo che non è una voce
   (es. "# NORME COMUNI", "## Art. 1 - Oggetto del contratto"); se è una riga di testo,
   finisce alla prima riga che non è una voce né il suo seguito;
2. legge le voci, in tutti i formati presenti nei documenti:
     - > **'Assicurato':** il soggetto ...        > "Polizza": il documento ...
     **Servizio:** l'insieme dei servizi ...      "Cliente": persona fisica ...
     ## › Appendice  (definizione nelle righe sotto)
     - › **Aderente**  (definizione nella riga rientrata sotto)
     | Termine | Definizione |
   con le righe che le continuano (sotto-elenchi, righe andate a capo);
3. scrive il documento senza la sezione, tenendo i marcatori <!-- pagina N --> e, se due
   marcatori restano attaccati, solo l'ultimo;
4. scrive un JSON con documento di origine, nome della sezione, pagine (da, a),
   introduzione e le voci (termine, definizione). Se il glossario compare più volte nello
   stesso documento, le altre sezioni sono in "altre_sezioni" e le voci ripetute sono scritte
   una volta sola.

Nella cartella --uscita scrive i documenti puliti (stesse sottocartelle) e, accanto a ogni
documento che ha un glossario, il suo JSON (nome_documento.glossario.json).
Non modifica gli originali.
"""
import argparse
import json
import re
import sys
from pathlib import Path

MARCATORE = re.compile(r"^\s*<!--\s*pagina\s+(\d+)\s*-->\s*$")
TITOLO_MD = re.compile(r"^(#{1,6})\s+(.*)$")
NOME_SEZIONE = re.compile(r"^\s*(\*\*)?\s*((sezione\s+\w+\s*>\s*)|([A-Z]\.\s*))?"
                          r"(definizioni|glossario)\b[^.:;]{0,60}?(\*\*)?\s*$", re.IGNORECASE)
VIRGOLETTE = "\"'“”‘’«»"
SEGNI = r"[-*•›»>]"
# - > **'Termine':** definizione   |   **Termine:** definizione   |   - › **Termine**
VOCE_GRASSETTO = re.compile(
    rf"^(?:{SEGNI}\s*){{0,3}}\*\*\s*(?P<t>[^*]{{1,120}}?)\s*\*\*\s*:?\s*(?P<d>.*)$")
# > "Polizza": definizione   |   "Cliente": definizione
VOCE_VIRGOLETTE = re.compile(
    rf"^(?:{SEGNI}\s*){{0,3}}[\"“'‘](?P<t>[^\"”'’\n]{{1,90}})[\"”'’]\s*\**\s*:\s*\**\s*(?P<d>.+)$")
# ## › Appendice   |   # > **Appendice**   (la definizione è nelle righe sotto)
VOCE_TITOLO = re.compile(r"^#{1,6}\s*[›»>]\s*(?:\*\*)?\s*(?P<t>[^*]{1,100}?)\s*(?:\*\*)?\s*:?\s*$")
RIGA_TABELLA = re.compile(r"^\s*\|(.+)\|\s*$")
SEPARATORE_TABELLA = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$")
SEGUITO = re.compile(r"^(\s+|[-*•›»>]|[a-z0-9]{1,2}\)\s)")   # sotto-elenco o riga rientrata


def pulisci_termine(t):
    t = re.sub(r"\*+", "", t).strip().rstrip(":").strip()
    t = t.strip(VIRGOLETTE).strip().rstrip(":").strip().strip(VIRGOLETTE).strip()
    return re.sub(r"\s+", " ", t)


def pulisci_testo(s):
    s = re.sub(r"\*{1,3}([^*]+)\*{1,3}", r"\1", s)       # toglie grassetto e corsivo
    s = re.sub(r"^\s*(?:[-*•›»>]\s*)+", "", s)            # toglie i simboli di elenco
    return re.sub(r"\s+", " ", s).strip()


def voce(riga):
    """Se la riga apre una voce restituisce (termine, definizione), altrimenti None.
    Le righe rientrate sono il seguito della voce precedente, non voci nuove."""
    if riga.startswith((" ", "\t")):
        return None
    m = VOCE_TITOLO.match(riga)
    if m:
        return m.group("t"), ""
    if TITOLO_MD.match(riga):
        return None
    m = VOCE_GRASSETTO.match(riga)
    if m and (m.group("d").strip() or len(m.group("t")) <= 80):
        return m.group("t"), m.group("d")
    m = VOCE_VIRGOLETTE.match(riga)
    if m:
        return m.group("t"), m.group("d")
    return None


def livello(riga):
    m = TITOLO_MD.match(riga)
    return len(m.group(1)) if m else None


def fine_sezione(righe, i, liv):
    """Dove finisce la sezione che ha il titolo alla riga i."""
    if liv is not None:
        # finisce al primo titolo che non è una voce: dentro un glossario non ce ne sono
        for j in range(i + 1, len(righe)):
            if livello(righe[j]) is not None and not VOCE_TITOLO.match(righe[j]):
                return j
        return len(righe)
    # titolo in testo semplice: la sezione è fatta solo di voci e del loro seguito
    viste, ultima = 0, i
    for j in range(i + 1, len(righe)):
        r = righe[j]
        if not r.strip() or MARCATORE.match(r):
            continue
        if voce(r) or (viste and SEGUITO.match(r)):
            viste += 1 if voce(r) else 0
            ultima = j
        elif viste == 0 and j - i <= 4:
            continue            # qualche riga di introduzione prima delle voci
        else:
            break
    return ultima + 1


def trova_sezione(righe):
    """Restituisce (inizio, fine) della prima sezione di definizioni, o None."""
    for i, riga in enumerate(righe):
        m = TITOLO_MD.match(riga)
        testo = m.group(2) if m else riga
        if not NOME_SEZIONE.match(testo):
            continue
        fine = fine_sezione(righe, i, len(m.group(1)) if m else None)
        if conta_voci(righe[i + 1:fine]) >= 3:
            return i, fine
    return None


def conta_voci(righe):
    n = 0
    for r in righe:
        if voce(r):
            n += 1
        elif RIGA_TABELLA.match(r) and not SEPARATORE_TABELLA.match(r):
            celle = [c.strip() for c in RIGA_TABELLA.match(r).group(1).split("|")]
            if len(celle) >= 2 and celle[0] and celle[-1]:
                n += 1
    return n


def leggi_voci(righe, pagina):
    """Legge le voci della sezione. Restituisce (introduzione, voci, ultima pagina con testo)."""
    voci, intro, corrente, ultima = [], [], None, pagina
    for r in righe:
        mm = MARCATORE.match(r)
        if mm:
            pagina = int(mm.group(1))
            continue
        if not r.strip() or SEPARATORE_TABELLA.match(r):
            continue
        ultima = pagina
        v = voce(r)
        tab = RIGA_TABELLA.match(r)
        if v:
            corrente = {"pagina": pagina, "termine": pulisci_termine(v[0]),
                        "definizione": pulisci_testo(v[1])}
            voci.append(corrente)
        elif tab:
            celle = [c.strip() for c in tab.group(1).split("|") if c.strip()]
            if len(celle) >= 2:
                corrente = {"pagina": pagina, "termine": pulisci_termine(pulisci_testo(celle[0])),
                            "definizione": pulisci_testo(" ".join(celle[1:]))}
                voci.append(corrente)
            elif celle and corrente:
                corrente["definizione"] += " " + pulisci_testo(celle[0])
        elif corrente is not None:
            # riga che continua la voce (sotto-elenco, testo andato a capo, definizione sotto il titolo)
            corrente["definizione"] = (corrente["definizione"] + "\n" + pulisci_testo(r)).strip()
        elif not TITOLO_MD.match(r):
            intro.append(pulisci_testo(r))
    return " ".join(intro).strip(), voci, ultima


def unisci_marcatori(righe):
    out = []
    for riga in righe:
        if MARCATORE.match(riga):
            k = len(out) - 1
            while k >= 0 and not out[k].strip():
                k -= 1
            if k >= 0 and MARCATORE.match(out[k]):
                del out[k:]
        out.append(riga)
    return out


def elabora(testo):
    """Toglie tutte le sezioni di definizioni. Restituisce (testo nuovo, sezioni)."""
    righe = testo.split("\n")
    sezioni = []
    while True:
        pos = trova_sezione(righe)
        if not pos:
            break
        inizio, fine = pos
        pagina = None
        for r in righe[:inizio]:
            mm = MARCATORE.match(r)
            if mm:
                pagina = int(mm.group(1))
        titolo = pulisci_testo(TITOLO_MD.sub(r"\2", righe[inizio]))
        intro, voci, ultima = leggi_voci(righe[inizio + 1:fine], pagina)
        sezioni.append({"sezione": titolo, "pagine": {"da": pagina, "a": ultima},
                        "righe_tolte": fine - inizio,
                        "introduzione": intro, "voci": voci})
        tenuti = []
        for r in righe[inizio:fine]:
            if MARCATORE.match(r):
                tenuti += [r, ""]
        righe = righe[:inizio] + tenuti + righe[fine:]
    righe = unisci_marcatori(righe)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(righe)), sezioni


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
    ap.add_argument("--uscita", required=True, help="cartella dove scrivere documenti e JSON")
    a = ap.parse_args()

    uscita = Path(a.uscita)
    tutte, n_file, n_doc = [], 0, 0
    for f, rel in file_da(a.percorsi):
        nuovo, sezioni = elabora(f.read_text(encoding="utf-8"))
        dest = uscita / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(nuovo, encoding="utf-8")
        n_file += 1
        if not sezioni:
            continue
        n_doc += 1
        doc = rel.as_posix()
        voci, viste = [], set()
        for s in sezioni:
            for v in s["voci"]:
                chiave = (v["termine"].lower(), v["definizione"])
                if chiave in viste:          # stessa voce ripetuta nello stesso documento
                    continue
                viste.add(chiave)
                voci.append({"termine": v["termine"], "definizione": v["definizione"]})
        tutte += voci
        prima = sezioni[0]
        dati = {"documento": doc, "sezione": prima["sezione"], "pagine": prima["pagine"],
                "introduzione": prima["introduzione"]}
        if len(sezioni) > 1:                 # raro: il glossario compare più volte nel documento
            dati["altre_sezioni"] = [{"sezione": s["sezione"], "pagine": s["pagine"]}
                                     for s in sezioni[1:]]
        dati["voci"] = voci
        (dest.parent / (dest.stem + ".glossario.json")).write_text(
            json.dumps(dati, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        nomi = ", ".join(f"«{s['sezione']}» (pag. {s['pagine']['da']}-{s['pagine']['a']}, "
                         f"{len(s['voci'])} voci)" for s in sezioni)
        print(f"{doc}: {nomi} → {len(voci)} voci nel JSON")
    print(f"\n{n_file} file, {n_doc} con glossario, {len(tutte)} voci. File scritti in {uscita}")


if __name__ == "__main__":
    sys.exit(main())
