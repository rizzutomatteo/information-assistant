#!/usr/bin/env python3
"""Controlla il golden set e ne stampa le statistiche.

Uso:
    python golden_set.py golden_set.json --documenti ../../assistente/documenti --faq ../../assistente/documenti/faq.json --clienti clienti_fittizi.json
    python golden_set.py golden_set.json ... --aggiorna   # scrive anche le pagine mancanti

Per ogni domanda controlla che i campi abbiano valori ammessi e che gli id siano unici.
Per ogni fonte attesa controlla che la citazione si trovi davvero nel file indicato (ignorando
grassetti, corsivi, a capo e spazi doppi), ricava la pagina dai marcatori <!-- pagina N --> e
segnala gli altri file che contengono la stessa frase (di solito un'altra edizione).
Le fonti FAQ sono controllate per id.
"""
import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

INTENTI = {"polizza", "sinistro", "pagamenti", "prodotto", "operatore", "reclamo",
           "fuori_ambito", "saluto"}
UTENTI = {"ospite", "cliente"}
AREE = {"auto_e_altri_veicoli", "casa_e_famiglia", "vita_e_risparmio", "previdenza", None}
TIPI = {"copertura", "esclusione", "importo", "requisiti", "procedura", "modulo",
        "definizione", "fuori_documenti", "dati_cliente", "richiesta_persona", "fuori_ambito"}
ESITI = {"risposta", "nessuna_fonte", "richiesta_login", "operatore", "risposta_fissa",
         "chiarimento", "non_trovata"}
RATE_ANNUE = {"annuale": 1, "unico": 1, "semestrale": 2, "trimestrale": 4, "mensile": 12}


def controlla_clienti(clienti):
    """Controlla clienti_fittizi.json e restituisce ({id cliente: {numero: polizza}}, errori)."""
    errori, per_cliente, numeri = [], {}, Counter()
    for c in clienti["clienti"]:
        if c["id"] in per_cliente:
            errori.append(f"clienti: id {c['id']} ripetuto")
        per_cliente[c["id"]] = {}
        for p in c["polizze"]:
            numeri[p["numero"]] += 1
            per_cliente[c["id"]][p["numero"]] = p
            n = RATE_ANNUE.get(p.get("frazionamento"))
            if n is None:
                errori.append(f"clienti: {p['numero']} frazionamento {p.get('frazionamento')!r} non ammesso")
            elif abs(p["rate"][0]["importo_euro"] * n - p["premio_annuo_euro"]) > 0.01:
                errori.append(f"clienti: {p['numero']} rate ({n} x {p['rate'][0]['importo_euro']}) "
                              f"diverse dal premio annuo {p['premio_annuo_euro']}")
    errori += [f"clienti: polizza {k} ripetuta" for k, v in numeri.items() if v > 1]
    return per_cliente, errori
SPLIT = {"sviluppo", "test"}
STATI = {"bozza", "verificata"}
OBBLIGATORI = ["id", "domanda", "utente", "intento", "area", "tipo", "esito_atteso",
               "risposta_attesa", "fonti_attese", "split", "stato"]
PAGINA = re.compile(r"<!--\s*pagina\s+(\d+)\s*-->")


def normalizza(testo):
    """Toglie la formattazione Markdown che non cambia il senso e uniforma spazi e apostrofi."""
    testo = testo.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    testo = re.sub(r"[*_]{1,3}", "", testo)
    testo = re.sub(r"\s+", " ", testo)
    return testo.strip().lower()


def carica_documenti(cartella):
    """Restituisce {percorso relativo: (testo normalizzato, [(posizione, pagina)])}."""
    documenti = {}
    for f in sorted(Path(cartella).rglob("*.md")):
        grezzo = f.read_text(encoding="utf-8")
        # Normalizza pezzo per pezzo, così le posizioni delle pagine restano allineate.
        pezzi, pagine, pos = [], [], 0
        ultimo = 0
        for m in PAGINA.finditer(grezzo):
            parte = normalizza(grezzo[ultimo:m.start()]) + " "
            pezzi.append(parte)
            pos += len(parte)
            pagine.append((pos, int(m.group(1))))
            ultimo = m.end()
        pezzi.append(normalizza(grezzo[ultimo:]))
        documenti[f.relative_to(cartella).as_posix()] = ("".join(pezzi), pagine)
    return documenti


def pagina_di(pagine, posizione):
    numero = None
    for inizio, n in pagine:
        if inizio <= posizione:
            numero = n
        else:
            break
    return numero


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("golden")
    ap.add_argument("--documenti", required=True)
    ap.add_argument("--faq", required=True)
    ap.add_argument("--clienti", required=True, help="clienti_fittizi.json")
    ap.add_argument("--aggiorna", action="store_true",
                    help="scrive nel file le pagine trovate quando mancano")
    a = ap.parse_args()

    dati = json.loads(Path(a.golden).read_text(encoding="utf-8"))
    domande = dati["domande"]
    documenti = carica_documenti(a.documenti)
    faq = {f["id"] for f in json.loads(Path(a.faq).read_text(encoding="utf-8"))["faq"]}
    polizze, errori = controlla_clienti(json.loads(Path(a.clienti).read_text(encoding="utf-8")))

    avvisi = []
    visti = Counter(d.get("id") for d in domande)
    for id_, n in visti.items():
        if n > 1:
            errori.append(f"{id_}: id ripetuto {n} volte")

    for d in domande:
        id_ = d.get("id", "?")
        for campo in OBBLIGATORI:
            if campo not in d:
                errori.append(f"{id_}: manca il campo '{campo}'")
        for campo, ammessi in [("intento", INTENTI), ("utente", UTENTI), ("area", AREE),
                               ("tipo", TIPI), ("esito_atteso", ESITI), ("split", SPLIT),
                               ("stato", STATI)]:
            if campo in d and d[campo] not in ammessi:
                errori.append(f"{id_}: {campo} = {d[campo]!r} non ammesso")

        fonti = d.get("fonti_attese", [])
        if d.get("esito_atteso") == "risposta" and not fonti and d.get("tipo") != "dati_cliente":
            avvisi.append(f"{id_}: esito 'risposta' ma nessuna fonte attesa")
        if d.get("esito_atteso") in {"nessuna_fonte", "richiesta_login", "risposta_fissa",
                                     "non_trovata"} and fonti:
            avvisi.append(f"{id_}: esito {d['esito_atteso']!r} ma con fonti attese")
        if d.get("utente") == "ospite" and d.get("intento") in {"polizza", "sinistro", "pagamenti"} \
                and d.get("esito_atteso") != "richiesta_login":
            errori.append(f"{id_}: un ospite che chiede della sua polizza deve ricevere 'richiesta_login'")
        cliente = d.get("cliente")
        if d.get("utente") == "ospite" and cliente:
            errori.append(f"{id_}: un ospite non ha un cliente")
        if d.get("utente") == "cliente" and d.get("tipo") == "dati_cliente" and cliente not in polizze:
            errori.append(f"{id_}: domanda sui propri dati senza un cliente valido ({cliente!r})")

        for fonte in fonti:
            if "dati" in fonte:
                polizza = polizze.get(cliente, {}).get(fonte["dati"])
                if polizza is None:
                    errori.append(f"{id_}: la polizza {fonte['dati']} non è del cliente {cliente}")
                elif fonte.get("campo") not in polizza:
                    errori.append(f"{id_}: la polizza {fonte['dati']} non ha il campo {fonte.get('campo')!r}")
                continue
            if "faq" in fonte:
                if fonte["faq"] not in faq:
                    errori.append(f"{id_}: FAQ {fonte['faq']!r} inesistente")
                continue
            file = fonte.get("file")
            if file not in documenti:
                errori.append(f"{id_}: file {file!r} inesistente")
                continue
            citazione = normalizza(fonte.get("citazione", ""))
            if len(citazione) < 20:
                errori.append(f"{id_}: citazione troppo corta in {file}")
                continue
            testo, pagine = documenti[file]
            pos = testo.find(citazione)
            if pos < 0:
                errori.append(f"{id_}: citazione non trovata in {file}: «{fonte['citazione'][:70]}…»")
                continue
            trovata = pagina_di(pagine, pos)
            if fonte.get("pagina") is None:
                fonte["pagina"] = trovata
            elif fonte["pagina"] != trovata:
                errori.append(f"{id_}: pagina {fonte['pagina']} indicata, la citazione è a pagina {trovata}")
            altri = [f for f, (t, _) in documenti.items() if f != file and citazione in t]
            if altri:
                avvisi.append(f"{id_}: la citazione compare anche in {', '.join(altri)}")

    print(f"Domande: {len(domande)}")
    for campo in ["intento", "area", "esito_atteso", "tipo", "utente", "split", "stato"]:
        conta = Counter(str(d.get(campo)) for d in domande)
        print(f"  {campo}: " + ", ".join(f"{k} {v}" for k, v in conta.most_common()))
    for titolo, righe in [("AVVISI", avvisi), ("ERRORI", errori)]:
        if righe:
            print(f"\n{titolo} ({len(righe)})")
            for r in righe:
                print("  - " + r)

    if a.aggiorna:
        Path(a.golden).write_text(json.dumps(dati, ensure_ascii=False, indent=2) + "\n",
                                  encoding="utf-8")
        print("\nFile aggiornato con le pagine trovate.")
    if errori:
        sys.exit(1)
    print("\nNessun errore.")


if __name__ == "__main__":
    main()
