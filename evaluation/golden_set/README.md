# Golden set

Domande di prova con la risposta attesa e le fonti attese. Serve a misurare il retrieval
(Recall@8), le risposte (Ragas), il riconoscimento degli intenti e a tarare le soglie del reranker.

## File

| File | Contenuto |
|---|---|
| `golden_set.json` | le domande (versione 0.3) |
| `clienti_fittizi.json` | 6 clienti finti con polizze, rate e sinistri, per le domande da cliente loggato |
| `golden_set.py` | lo script che controlla tutto e stampa le statistiche |

## Stato (versione 0.3)

163 domande, tutte in `bozza`:

| Gruppo | Domande |
|---|---|
| Prodotti con risposta nei documenti o nelle FAQ (auto e altri veicoli 39, casa e famiglia 22, previdenza 20, vita e risparmio 16) | 97 |
| Domande del dominio a cui i documenti non rispondono | 15 |
| Ospite che chiede dei propri dati (deve chiedere il login) | 9 |
| Cliente loggato con i propri dati (clienti di `clienti_fittizi.json`) | 22 |
| Operatore e reclami | 10 + 1 da cliente loggato |
| Fuori ambito e saluti | 10 |

Le domande con `note` contengono le trappole da controllare: edizioni diverse dello stesso
prodotto (gs-143 contro gs-003), FAQ che semplificano troppo o valgono per un altro prodotto
(gs-079, gs-091), regole che cambiano tra prodotti (rate, disdetta, recesso), dati da mascherare.

## Campi di ogni domanda

| Campo | Valori | Significato |
|---|---|---|
| `id` | `gs-001`, … | unico, non si riusa mai |
| `domanda` | testo | come la scriverebbe un cliente vero, anche colloquiale |
| `utente` | `ospite`, `cliente` | chi fa la domanda (con o senza login) |
| `cliente` | `cli-01` … `cli-06`, o `null` | il cliente fittizio loggato, se la risposta dipende dai suoi dati |
| `intento` | `prodotto`, `polizza`, `sinistro`, `pagamenti`, `operatore`, `reclamo`, `fuori_ambito`, `saluto` | l'intento che `classify` deve riconoscere |
| `area` | cartella dei documenti, o `null` | |
| `prodotto`, `edizione` | es. `Velaria Auto`, `07/2026`, o `null` | se la domanda riguarda un prodotto e un'edizione precisi |
| `tipo` | `copertura`, `esclusione`, `importo`, `requisiti`, `procedura`, `modulo`, `definizione`, `fuori_documenti`, `dati_cliente`, `richiesta_persona`, `fuori_ambito` | che genere di domanda è |
| `esito_atteso` | `risposta`, `nessuna_fonte`, `richiesta_login`, `operatore`, `risposta_fissa`, `chiarimento`, `non_trovata` | cosa deve fare l'assistente |
| `risposta_attesa` | testo | i fatti che la risposta deve contenere |
| `fonti_attese` | lista | `{"file", "citazione", "pagina"}` per i documenti, `{"faq": id}` per le FAQ, `{"dati": numero polizza, "campo"}` per i dati del cliente |
| `split` | `sviluppo`, `test` | le domande di test non si guardano mentre si sistema il sistema |
| `stato` | `bozza`, `verificata` | `verificata` solo dopo aver controllato risposta e fonti |
| `note` | testo | |

`chiarimento` = il cliente ha più polizze e non dice quale: l'assistente chiede, non sceglie.
`non_trovata` = il cliente chiede una polizza non sua: risulta "non trovata", senza confermare che esista.

La **citazione** è una frase copiata dal documento, di almeno 20 caratteri. Così la fonte attesa
non dipende da come vengono fatti i chunk: un passaggio recuperato è giusto se contiene la citazione.
La pagina la ricava lo script.

## I clienti fittizi

| Cliente | Chi è | Cosa mette alla prova |
|---|---|---|
| cli-01 | Pendolare con l'auto sulla vecchia edizione (07/2025) | edizione giusta, sinistro in perizia, polizza di un altro cliente |
| cli-02 | Famiglia con auto, moto e casa | scelta tra più polizze, garanzia non acquistata, sinistro liquidato, rate mensili |
| cli-03 | Rata non pagata | polizza sospesa, carta mascherata |
| cli-04 | Nuovo cliente casa con un sinistro respinto | spiegare un rifiuto senza giudicarlo, carenza di 30 giorni |
| cli-05 | Polizza vita temporanea caso morte | capitale decrescente, recesso scaduto, IBAN mascherato |
| cli-06 | Polizza viaggi scaduta e polizza mutuo | polizza scaduta, vincolo della banca, "polizza della casa" che è la polizza mutuo |

Il file contiene i dati completi, come li avrebbe il gestionale: il policy server deve mascherare
targhe e dati di pagamento prima di passarli all'assistente. Nomi, indirizzi e contatti sono
segnaposto; targhe, carte e IBAN sono inventati e non validi. I dati sono fotografati al 24/11/2026.

## Controllo

```bash
cd evaluation/golden_set
python golden_set.py golden_set.json --documenti ../../assistente/documenti --faq ../../assistente/documenti/faq.json --clienti clienti_fittizi.json --aggiorna
```

Controlla campi e id, verifica che ogni citazione sia davvero nel file, scrive la pagina e
avvisa se la stessa frase compare in altri file (spesso un'altra edizione dello stesso prodotto).
Controlla anche i clienti: polizze uniche, rate che tornano con il premio annuo, e che ogni
fonte `dati` sia una polizza del cliente della domanda.
