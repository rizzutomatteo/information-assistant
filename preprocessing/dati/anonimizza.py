"""Toglie dai testi in Markdown i riferimenti alle società reali, con un dizionario di sostituzioni.

I testi che produce sono dati sintetici, generati con strumenti di AI a partire da documentazione
assicurativa pubblica: le società hanno nomi inventati, mentre nomi e cognomi, date e luoghi di
nascita, vie, numeri di telefono e fax ed email diventano segnaposto tra parentesi quadre
([NOME] [COGNOME], [INDIRIZZO], [TELEFONO], [EMAIL]...). Ogni file prodotto lo dichiara in testa.

    <testi>/<area>/<nome>.md  ->  <uscita>/<area>/<nome anonimo>.md

Le regole stanno in sostituzioni.tsv (tipo, reale, fittizio, nota), una per riga:

    testo     parola o frase, senza distinguere maiuscole e minuscole; il sostituto ne copia la forma
              (ACME -> VELARIA, acme -> velaria, Acme -> Velaria); gli spazi valgono anche
              come a capo
    esatto    parola o frase, maiuscole e minuscole comprese
    dominio   come testo, ma solo dentro indirizzi web ed email (www.x.it, nome@x.it, x.it/pagina)
    regex     espressione regolare di Python; nel sostituto si possono usare \\1, \\g<nome>;
              {B} è un confine di parola che, a differenza di \\b, vale anche prima di una nota in
              apice (Acme¹¹)
    telefono  le sole cifre del numero: si riconosce con qualunque separatore (spazi, punti,
              trattini, barre) e con o senza +39 / 0039 davanti, che resta com'è
    file      un pezzo di nome di file da cambiare (i nomi dei file passano anche per le regole
              testo ed esatto, con _ al posto degli spazi)
    consenti  non sostituisce nulla: un dominio o un telefono che il controllo finale deve accettare
              (enti pubblici come IVASS e CONSAP, domini fittizi)

Tutte le regole si cercano sul testo originale e le sostituzioni si fanno in un solo passaggio: dove
due regole si sovrappongono vince quella che comincia prima e, a parità, la più lunga. Così un nome
fittizio non viene mai sostituito di nuovo e le forme lunghe ("Acme Italia") vincono su quelle
corte ("Acme"). Il testo fuori dalle sostituzioni non cambia di un carattere.

    python3 anonimizza.py                 documenti_corretti/ -> documenti_anonimi/
    python3 anonimizza.py --controlla     cerca nei testi anonimi quello che è rimasto
    python3 anonimizza.py --faq faq.json  faq.json -> faq_anonime.json (e il suo controllo)

Nel file delle FAQ si anonimizzano tutti i testi (id, domanda, risposta, categorie, url, fonte),
non i nomi dei campi. Dove c'è un campo sha256 lo si ricalcola su domanda + "\n\n" + risposta
anonime, e la versione del file sui primi 12 caratteri dello sha256 dell'elenco faq in JSON
compatto con le chiavi ordinate: sono le stesse formule del file originale, così l'impronta
resta coerente con il contenuto e non rimanda più al testo reale.

Ogni modifica finisce in anonimizzazione.tsv (file, pagina, nota, prima, dopo). Il controllo elenca i
nomi del dizionario ancora presenti, le email, i siti e i telefoni che non sono tra quelli consentiti,
i numeri di 11 cifre (codici fiscali, partite IVA) e le date di nascita, ed esce con 1 se trova qualcosa.
Non scrive mai nella cartella da cui legge. Usa solo la libreria standard di Python.

ATTENZIONE: sostituzioni.tsv e anonimizzazione.tsv contengono i nomi reali, quindi come i testi
originali non vanno messi nel repository pubblico. Questo script e documenti_anonimi/ invece sì.
"""

import argparse
import csv
import hashlib
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

QUI = Path(__file__).resolve().parent
PAGINA = re.compile(r"<!-- pagina (\d+) -->")

NOTA = ("Dati sintetici generati con strumenti di AI a partire da documentazione assicurativa "
        "pubblica. Società, prodotti e siti hanno nomi inventati; nomi e cognomi, date e luoghi di "
        "nascita, indirizzi, numeri di telefono e fax ed email sono segnaposto tra parentesi quadre.")
NOTA_MD = f"<!-- {NOTA} -->\n\n"
TIPI = {"testo", "esatto", "dominio", "regex", "telefono", "file", "consenti"}

# Lettere e cifre di una parola. Non si usa \w perché per Python anche le note in apice (¹ ² ³) sono
# lettere, e allora "Acme¹¹" non avrebbe un confine di parola dopo "Acme".
LETTERA = r"[0-9A-Za-z_À-ÖØ-öø-ÿ]"
CONFINE = rf"(?:(?<!{LETTERA})(?={LETTERA})|(?<={LETTERA})(?!{LETTERA}))"

# per il controllo finale
EMAIL = re.compile(r"[\w.%+-]+@([a-z0-9-]+(?:\.[a-z0-9-]+)+)")
SITO = re.compile(r"(?:https?://|www\.)([\w-]+(?:\.[\w-]+)+)|\b([\w-]+\.(?:it|com|eu|net|org|ch|example))\b", re.I)
TELEFONO = re.compile(r"(?<!\d)(?<!\d,)(?<!\d\.)(?:(?:\+|00)\s?39[\s.\-]*|\(\+39\)\s*)?\b(?:0\d{1,3}|80\d|199|3\d{2})(?:[\s.\-]?\d{2,4}){2,4}\b(?!\d|,\d|/\d)")
UNDICI_CIFRE = re.compile(r"(?<![\d.,])\d{11}(?![\d.,])")
CODICE = re.compile(r"\b[A-Z]{2}\s?\d{2}\s?[A-Z0-9](?:\s?[A-Z0-9]){10,29}\b")  # IBAN, codice creditore SEPA
NASCITA = re.compile(r"\bnat[oa] a [A-Z][^\n]{0,40}?\b(?:il|l')\s*\d{1,2}\b")


@dataclass
class Regola:
    tipo: str
    reale: str
    fittizio: str
    nota: str
    cerca: re.Pattern


def adatta(trovato, fittizio):
    """Copia sul sostituto la forma del testo trovato (tutto maiuscolo, tutto minuscolo)."""
    lettere = [c for c in trovato if c.isalpha()]
    if lettere and all(c.isupper() for c in lettere) and len(lettere) > 1:
        return fittizio.upper()
    if lettere and all(c.islower() for c in lettere):
        return fittizio.lower()
    return fittizio


def frase(reale):
    """Una frase letterale in cui ogni spazio vale anche come a capo, spazi multipli o trattino
    (quality-driver negli indirizzi delle pagine)."""
    return r"(?:\s+|-)".join(re.escape(parte) for parte in reale.split())


def compila(tipo, reale):
    if tipo == "testo":
        return re.compile(rf"(?<!{LETTERA})" + frase(reale) + rf"(?!{LETTERA})", re.I)
    if tipo == "esatto":
        return re.compile(rf"(?<!{LETTERA})" + frase(reale) + rf"(?!{LETTERA})")
    if tipo == "dominio":
        # x.it dentro www.x.it, a.b@x.it, https://x.it/..., non dentro parole più lunghe (abcx.it)
        return re.compile(r"(?<![\w-])" + re.escape(reale) + r"(?![\w-])", re.I)
    if tipo == "regex":
        return re.compile(reale.replace("{B}", CONFINE))
    if tipo == "telefono":
        if not reale.isdigit():
            raise ValueError(f"telefono con caratteri che non sono cifre: {reale!r}")
        cifre = r"[\s./\-]{0,2}".join(reale)
        return re.compile(r"(?<!\d)(?<!\d,)(?P<prefisso>(?:(?:\+|00)\s?39|\(\+39\))[\s.\-]*)?" + cifre + r"(?!\d|,\d)")
    return None


def leggi_regole(percorso):
    regole = []
    with open(percorso, encoding="utf-8", newline="") as f:
        for numero, riga in enumerate(csv.DictReader(f, delimiter="\t", quoting=csv.QUOTE_NONE), start=2):
            tipo = (riga["tipo"] or "").strip()
            if not tipo or tipo.startswith("#"):
                continue
            if tipo not in TIPI:
                raise SystemExit(f"{percorso}:{numero}: tipo sconosciuto {tipo!r}")
            try:
                cerca = compila(tipo, riga["reale"])
            except (re.error, ValueError) as errore:
                raise SystemExit(f"{percorso}:{numero}: {errore}")
            regole.append(Regola(tipo, riga["reale"], riga["fittizio"] or "", riga["nota"] or "", cerca))
    return regole


def sostituto(regola, m):
    if regola.tipo == "regex":
        return m.expand(regola.fittizio)
    if regola.fittizio.startswith("["):
        return regola.fittizio  # un segnaposto ([TELEFONO], [EMAIL]...) resta sempre com'è
    if regola.tipo == "telefono":
        return (m.group("prefisso") or "") + regola.fittizio
    nuovo = regola.fittizio if regola.tipo == "esatto" else adatta(m.group(0), regola.fittizio)
    prima = m.string[m.start() - 1:m.start()]
    dopo = m.string[m.end():m.end() + 1]
    dentro_un_indirizzo = ("-" in m.group(0) and not re.search(r"\s", m.group(0))) or prima in {"-", "/"} or dopo in {"-", "/"}
    if regola.tipo in {"testo", "esatto"} and dentro_un_indirizzo:
        nuovo = "-".join(nuovo.split())  # dentro un indirizzo web (…/scatola-nera-acme) niente spazi
    return nuovo


def anonimizza(testo, regole):
    """Restituisce il testo anonimo e l'elenco delle modifiche (posizione, regola, prima, dopo)."""
    trovati = []
    for indice, regola in enumerate(regole):
        if regola.cerca is None:
            continue
        for m in regola.cerca.finditer(testo):
            if m.end() > m.start():
                trovati.append((m.start(), -(m.end() - m.start()), indice, m))
    trovati.sort()

    pezzi, modifiche, fine = [], [], 0
    for inizio, _, indice, m in trovati:
        if inizio < fine:
            continue  # si sovrappone a una sostituzione già scelta
        nuovo = sostituto(regole[indice], m)
        pezzi.append(testo[fine:inizio])
        pezzi.append(nuovo)
        modifiche.append((inizio, regole[indice], m.group(0), nuovo))
        fine = m.end()
    pezzi.append(testo[fine:])
    return "".join(pezzi), modifiche


def nome_anonimo(relativo, regole):
    """Toglie i nomi reali anche dai nomi dei file (rinnovi_acme.md -> rinnovi_velaria.md)."""
    nome = relativo.stem
    for regola in regole:
        if regola.tipo not in {"testo", "esatto"}:
            continue
        parole = [re.escape(p) for p in regola.reale.lower().split()]
        cerca = re.compile(r"(?<![a-z0-9])" + "[_\\s-]+".join(parole) + r"(?![a-z0-9])", re.I)
        nuovo = "_".join(regola.fittizio.lower().replace(".", "").split())
        nome = cerca.sub(nuovo, nome)
    for regola in regole:
        if regola.tipo == "file":
            nome = nome.replace(regola.reale, regola.fittizio)
    return relativo.with_name(nome + relativo.suffix)


def pagina_di(testo, posizione):
    pagine = PAGINA.findall(testo, 0, posizione)
    return pagine[-1] if pagine else ""


def converti(testi, uscita, regole, resoconto):
    if uscita.resolve() == testi.resolve() or testi.resolve() in uscita.resolve().parents:
        raise SystemExit("La cartella di uscita non può essere quella dei testi o stare dentro di essa")
    file_md = sorted(testi.rglob("*.md"))
    if not file_md:
        raise SystemExit(f"Nessun .md in {testi}")

    righe, nomi_usati, per_nota = [], {}, Counter()
    for sorgente in file_md:
        relativo = sorgente.relative_to(testi)
        nuovo_relativo = nome_anonimo(relativo, regole)
        if nuovo_relativo in nomi_usati:
            raise SystemExit(f"{relativo} e {nomi_usati[nuovo_relativo]} avrebbero lo stesso nome anonimo")
        nomi_usati[nuovo_relativo] = relativo

        testo = sorgente.read_text(encoding="utf-8")
        anonimo, modifiche = anonimizza(testo, regole)
        destinazione = uscita / nuovo_relativo
        destinazione.parent.mkdir(parents=True, exist_ok=True)
        destinazione.write_text(NOTA_MD + anonimo, encoding="utf-8")

        for posizione, regola, prima, dopo in modifiche:
            righe.append((str(nuovo_relativo), pagina_di(testo, posizione), regola.nota or regola.tipo,
                          " ".join(prima.split()), dopo))
            per_nota[regola.nota or regola.tipo] += 1

    with open(resoconto, "w", encoding="utf-8", newline="") as f:
        scrivi = csv.writer(f, delimiter="\t", lineterminator="\n")
        scrivi.writerow(["file", "pagina", "nota", "prima", "dopo"])
        scrivi.writerows(righe)

    rinominati = sum(1 for nuovo, vecchio in nomi_usati.items() if nuovo != vecchio)
    print(f"{len(file_md)} file in {uscita} ({rinominati} rinominati), {len(righe)} sostituzioni in {resoconto}")
    for nota, quante in per_nota.most_common(12):
        print(f"  {quante:6}  {nota}")


def testi_da_controllare(percorso):
    """(nome, testo) da controllare: i .md di una cartella, oppure ogni testo di un file JSON."""
    if percorso.is_dir():
        for file_md in sorted(percorso.rglob("*.md")):
            yield str(file_md.relative_to(percorso)), file_md.read_text(encoding="utf-8")
        return
    dati = json.loads(percorso.read_text(encoding="utf-8"))
    for dove, testo in stringhe(dati):
        if not dove.endswith(("sha256", "versione")):  # impronte esadecimali, non testo
            yield f"{percorso.name}:{dove}", testo


def stringhe(dati, dove=""):
    """Tutti i testi di un oggetto JSON, con il percorso per ritrovarli (faq/15-giorni/risposta)."""
    if isinstance(dati, dict):
        for chiave, valore in dati.items():
            yield from stringhe(valore, f"{dove}/{chiave}" if dove else chiave)
    elif isinstance(dati, list):
        for posizione, valore in enumerate(dati):
            nome = valore.get("id", posizione) if isinstance(valore, dict) else posizione
            yield from stringhe(valore, f"{dove}/{nome}")
    elif isinstance(dati, str):
        yield dove, dati


def impronta(testo):
    return hashlib.sha256(testo.encode("utf-8")).hexdigest()


def anonimizza_json(dati, regole, righe, nome_file, dove=""):
    """Anonimizza ogni testo di un oggetto JSON (le chiavi restano), ricalcolando gli sha256."""
    if isinstance(dati, dict):
        nuovo = {chiave: anonimizza_json(valore, regole, righe, nome_file, f"{dove}/{chiave}" if dove else chiave)
                 for chiave, valore in dati.items()}
        if {"domanda", "risposta", "sha256"} <= nuovo.keys():
            nuovo["sha256"] = impronta(nuovo["domanda"] + "\n\n" + nuovo["risposta"])
        if {"versione", "faq"} <= nuovo.keys():
            compatto = json.dumps(nuovo["faq"], ensure_ascii=False, separators=(",", ":"), sort_keys=True)
            nuovo["versione"] = impronta(compatto)[:12]
        return nuovo
    if isinstance(dati, list):
        return [anonimizza_json(valore, regole, righe, nome_file,
                                f"{dove}/{valore.get('id', i) if isinstance(valore, dict) else i}")
                for i, valore in enumerate(dati)]
    if isinstance(dati, str) and not dove.endswith(("sha256", "versione")):
        anonimo, modifiche = anonimizza(dati, regole)
        for _, regola, prima, dopo in modifiche:
            righe.append((nome_file, dove, regola.nota or regola.tipo, " ".join(prima.split()), dopo))
        return anonimo
    return dati


def converti_faq(sorgente, destinazione, regole, resoconto):
    if destinazione.resolve() == sorgente.resolve():
        raise SystemExit("Il file anonimo non può sostituire quello originale")
    righe = []
    dati = anonimizza_json(json.loads(sorgente.read_text(encoding="utf-8")), regole, righe, destinazione.name)
    if isinstance(dati, dict):
        dati = {"nota": NOTA, **dati}
    destinazione.write_text(json.dumps(dati, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with open(resoconto, "w", encoding="utf-8", newline="") as f:
        scrivi = csv.writer(f, delimiter="\t", lineterminator="\n")
        scrivi.writerow(["file", "dove", "nota", "prima", "dopo"])
        scrivi.writerows(righe)
    domande = len(dati.get("faq", [])) if isinstance(dati, dict) else 0
    print(f"{domande} FAQ in {destinazione}, {len(righe)} sostituzioni in {resoconto}")
    for nota, quante in Counter(r[2] for r in righe).most_common(12):
        print(f"  {quante:6}  {nota}")


def controlla(cartella, regole):
    """Cerca nei testi anonimi i riferimenti rimasti. Restituisce il numero di problemi."""
    domini_ok = [r.reale.lower() for r in regole if r.tipo == "consenti" and not r.reale.isdigit()]
    telefoni_ok = {r.reale for r in regole if r.tipo == "consenti" and r.reale.isdigit()}
    # numeri e codici inventati dal dizionario: il controllo non li segnala
    fittizi = {re.sub(r"\D", "", r.fittizio) for r in regole if r.tipo in {"telefono", "regex"}} - {""}
    codici_fittizi = {re.sub(r"\s", "", r.fittizio) for r in regole if r.tipo == "regex"}
    nascite_fittizie = [r.fittizio for r in regole if r.tipo == "esatto" and r.nota == "dati di nascita"]
    da_cercare = [r for r in regole if r.tipo in {"testo", "esatto", "dominio", "telefono"}]

    def dominio_ok(dominio):
        dominio = dominio.lower().rstrip(".")
        return any(dominio == ok or dominio.endswith("." + ok) for ok in domini_ok)

    problemi = Counter()
    for nome, testo in testi_da_controllare(cartella):
        for regola in da_cercare:
            for m in regola.cerca.finditer(testo):
                problemi[(nome, "nome reale rimasto", m.group(0))] += 1
        for m in EMAIL.finditer(testo):
            if not dominio_ok(m.group(1)):
                problemi[(nome, "email", m.group(0))] += 1
        for m in SITO.finditer(testo):
            dominio = m.group(1) or m.group(2)
            if not dominio_ok(dominio) and "@" not in testo[max(0, m.start() - 1):m.start()]:
                problemi[(nome, "sito", m.group(0))] += 1
        for m in TELEFONO.finditer(testo):
            cifre = re.sub(r"\D", "", m.group(0))
            cifre = re.sub(r"^(?:0039|39)(?=0|3|8|1)", "", cifre) if m.group(0).lstrip().startswith(("+", "00", "(")) else cifre
            valore = m.group(0).strip()
            if (cifre in telefoni_ok or len(cifre) < 8
                    or any(f in cifre or cifre in f for f in fittizi if len(f) >= 6)   # inventati da noi
                    or re.fullmatch(r"\d{2}[./]\d{2}[./]\d{4}", valore)              # date
                    or (re.fullmatch(r"\d{3}(?:\.\d{3})+", valore) and not valore.startswith(("80", "199")))):  # importi
                continue
            problemi[(nome, "telefono?", m.group(0))] += 1
        for m in UNDICI_CIFRE.finditer(testo):
            if m.group(0) not in fittizi:
                problemi[(nome, "11 cifre (C.F./P.IVA?)", m.group(0))] += 1
        for m in CODICE.finditer(testo):
            if re.sub(r"\s", "", m.group(0)) not in codici_fittizi and any(c.isdigit() for c in m.group(0)[4:]):
                problemi[(nome, "IBAN o codice?", m.group(0))] += 1
        for m in NASCITA.finditer(testo):
            if not any(m.group(0) in finta for finta in nascite_fittizie):
                problemi[(nome, "data di nascita", m.group(0))] += 1

    for (nome, tipo, valore), quante in sorted(problemi.items()):
        print(f"{tipo}\t{quante}\t{valore}\t{nome}")
    totale = sum(problemi.values())
    print(f"{totale} cose da ricontrollare" if totale else "Nessun riferimento reale trovato.", file=sys.stderr)
    return totale


def main():
    argomenti = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                        formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    argomenti.add_argument("--testi", type=Path, default=QUI / "documenti_corretti", help="cartella dei testi da anonimizzare")
    argomenti.add_argument("--uscita", type=Path, default=QUI / "documenti_anonimi", help="dove scrivere i testi anonimi")
    argomenti.add_argument("--dizionario", type=Path, default=QUI / "sostituzioni.tsv", help="le regole di sostituzione")
    argomenti.add_argument("--resoconto", type=Path, default=QUI / "anonimizzazione.tsv", help="elenco delle modifiche")
    argomenti.add_argument("--controlla", action="store_true", help="solo il controllo dei testi già anonimizzati")
    argomenti.add_argument("--faq", type=Path, help="file JSON delle FAQ da anonimizzare al posto dei testi")
    argomenti.add_argument("--faq-uscita", type=Path, help="dove scrivere le FAQ anonime (predefinito: faq_anonime.json)")
    a = argomenti.parse_args()

    regole = leggi_regole(a.dizionario)
    if a.faq:
        uscita = a.faq_uscita or QUI / f"{a.faq.stem}_anonime.json"
        resoconto = a.resoconto if "--resoconto" in sys.argv else QUI / f"anonimizzazione_{a.faq.stem}.tsv"
        if not a.controlla:
            converti_faq(a.faq, uscita, regole, resoconto)
        sys.exit(1 if controlla(uscita, regole) else 0)
    if not a.controlla:
        converti(a.testi, a.uscita, regole, a.resoconto)
    sys.exit(1 if controlla(a.uscita, regole) else 0)


if __name__ == "__main__":
    main()
