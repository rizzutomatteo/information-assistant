# Preparazione dei dati

Gli script che hanno prodotto i documenti in `assistente/documenti/`, le FAQ in
`assistente/documenti/faq.json` e i glossari in `assistente/glossario/`. Usano solo la libreria
standard di Python. I documenti sono dati sintetici: società, prodotti e siti hanno nomi inventati,
e nomi, indirizzi e contatti sono segnaposto tra parentesi quadre.

## La catena

| Passo | Script | Cosa fa | Produce |
|---|---|---|---|
| 1 | `anonimizza.py` | sostituisce i riferimenti alle società reali con nomi inventati e i dati personali con segnaposto, nei documenti e nelle FAQ | documenti anonimi, `faq_anonime.json` |
| 2 | `deduplica.py` | toglie i documenti pubblicati in più aree con lo stesso contenuto, byte per byte | `duplicati.tsv` |
| 3 | `togli_indice.py` | toglie l'indice dei documenti e, dove due marcatori di pagina restano attaccati, tiene solo l'ultimo | documenti senza indice |
| 4 | `estrai_glossario.py` | toglie la sezione delle definizioni e la salva in un JSON per documento | documenti senza glossario, `*.glossario.json` |

```bash
python3 togli_indice.py documenti_anonimi --uscita documenti_senza_indice
python3 estrai_glossario.py documenti_senza_indice --uscita documenti_senza_glossario
```

I passi 3 e 4 si possono rifare partendo dai documenti di una versione precedente del repo.
I passi 1 e 2 partono dai documenti originali, che non sono nel repo.

## File che non sono nel repo

Restano solo sul Drive del gruppo, perché contengono i nomi reali:

- `sostituzioni.tsv`, il dizionario delle sostituzioni che `anonimizza.py` legge
- `anonimizzazione.tsv` e `anonimizzazione_faq.tsv`, l'elenco di ogni modifica fatta
- i documenti originali e il file originale delle FAQ

Il `.gitignore` di questa cartella li esclude, così non si possono aggiungere per errore.

## `duplicati.tsv`

Per ogni documento tenuto elenca le copie tolte (`copie_tolte`) e tutte le aree in cui era
pubblicato (`aree`). Un documento tolto da un'area resta trovabile anche per quell'area se il
chunking usa la colonna `aree`. Il file lo scrive `deduplica.py`: non va modificato a mano.

## Correzioni fatte a mano

Due correzioni non le fa nessuno script. Chi rilancia la catena deve rifarle:

1. **`auto_e_altri_veicoli/contratto_di_comodato_velaria_drive.md`**: il file conteneva lo stesso
   contratto due volte (pagine 1–5 e 6–10). È rimasta solo la prima copia, con tre correzioni prese
   dalla seconda: "attiverà" al posto di "attività", "Installatore convenzionato" con la maiuscola,
   "2.3" come titolo `##`.
2. **`faq.json`**: la FAQ `cosa-copre-la-garanzia-eventi-atmosferici-auto` era un doppione di
   `cosa-copre-la-garanzia-agenti-atmosferici-auto` (stessa domanda, stesso contenuto, senza
   categoria). È stata tolta: le FAQ passano da 171 a 170.
