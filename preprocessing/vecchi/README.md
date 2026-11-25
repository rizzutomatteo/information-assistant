# Conversione PDF in Markdown

Quattro script da riga di comando per confrontare Docling, PyMuPDF, Marker e MinerU
sugli stessi PDF. Eseguire i comandi di questa guida da `preprocessing/vecchi/`.

| Script | Motore | Comportamento iniziale |
| --- | --- | --- |
| [`scripts/pdf_to_md.py`](scripts/pdf_to_md.py) | Docling | Lettura PDF con PDFium, analisi del layout e OCR secondo la pipeline Docling |
| [`scripts/pdf_to_md_pymupdf.py`](scripts/pdf_to_md_pymupdf.py) | PyMuPDF 2.x | OCR forzato, lingue `ita+eng`, 300 DPI; per i PDF digitali usare `--ocr auto` |
| [`scripts/pdf_to_md_marker.py`](scripts/pdf_to_md_marker.py) | Marker 2.1+ | Modalità `fast`, OCR automatico |
| [`scripts/pdf_to_md_mineru.py`](scripts/pdf_to_md_mineru.py) | MinerU 4.2+ | Parser locale `mineru-kit`, livello `basic`, OCR automatico, tutte le pagine |

## Requisiti e installazione

Python **3.11 o 3.12** è una scelta comune ai quattro ambienti. Sostituire
`python3.11` con il proprio interprete compatibile, se necessario. Il pacchetto
MinerU 4.2 richiede Python da 3.11 a 3.14.

Usare ambienti separati: i motori hanno dipendenze e versioni di PyTorch,
Transformers e delle librerie PDF che possono entrare in conflitto. Gli esempi
usano direttamente il Python del virtualenv; non serve attivarlo.

### Docling

```bash
python3.11 -m venv .venv-docling
.venv-docling/bin/python -m pip install docling
```

### PyMuPDF e Tesseract

```bash
python3.11 -m venv .venv-pymupdf
.venv-pymupdf/bin/python -m pip install 'pymupdf>=2.0,<3'
```

Per l'OCR installare anche Tesseract e le lingue necessarie. Su macOS:

```bash
brew install tesseract tesseract-lang
tesseract --list-langs
```

Su Debian/Ubuntu:

```bash
sudo apt install tesseract-ocr tesseract-ocr-ita tesseract-ocr-eng
```

Per l'impostazione `ita+eng` devono essere disponibili entrambe le lingue.

### Marker

```bash
python3.11 -m venv .venv-marker
.venv-marker/bin/python -m pip install -r requirements-marker.txt
```

Marker 2.1 usa un modello VLM per l'OCR e per alcune riparazioni del testo.
Su macOS/CPU serve anche il comando `llama-server` di llama.cpp:

```bash
brew install llama.cpp
```

Con `--ocr never` Marker disabilita le chiamate al VLM: è una modalità per PDF
con testo incorporato utilizzabile, senza riconoscimento delle scansioni.
Lo script non abilita l'opzione aggiuntiva `--use_llm` di Marker.

### MinerU

```bash
python3.11 -m venv .venv-mineru
.venv-mineru/bin/python -m pip install -r requirements-mineru.txt
.venv-mineru/bin/mineru-kit models download --tier basic
.venv-mineru/bin/mineru-kit models verify --tier basic
```

Lo script usa il parser locale stateless `mineru-kit`, senza richiedere il server
Doclib o l'indicizzazione dei documenti. Non aggiunge opzioni di elaborazione remota.
Il formato ZIP intermedio conserva anche le immagini, che il solo export Markdown
di MinerU Kit non salva come file associati.

Per usare `--tier standard` o `--tier advanced` preparare il set di modelli
`standard` con gli stessi comandi `models download` e `models verify`.
I livelli superiori richiedono più risorse: per le prime prove su un M2 con 8 GB
partire da `basic` e da poche pagine.

Il primo utilizzo dei motori può richiedere download di modelli. L'installazione
dei pacchetti Python da sola non equivale a una conversione pronta per l'uso offline.

`requirements.txt` rimane il file delle due varianti iniziali, Docling e PyMuPDF.
Le nuove varianti hanno requisiti separati in `requirements-marker.txt` e
`requirements-mineru.txt`; evitare di installare tutti i motori nello stesso ambiente.

## Uso dei quattro script

Copiare i PDF campione in `input/`, una cartella locale ignorata da Git.
I file Markdown in `risultati/` raccolgono le prove precedenti.
`mistral_documento2.md` è un risultato di confronto ottenuto tramite la console Mistral.

### 1. Docling

```bash
.venv-docling/bin/python scripts/pdf_to_md.py \
  "input/condizioni_di_assicurazione_viaggi.pdf" \
  -o risultati/condizioni_docling.md
```

Il backend PDFium è esplicito perché il backend `docling-parse v4` di Docling 2.51
non leggeva il testo del PDF di viaggio nelle prove effettuate. Un risultato vuoto
o costituito solo da commenti/segnaposto causa un errore.

Lo script imposta `HF_HUB_DISABLE_IMPLICIT_TOKEN=1`, se la variabile non è già
definita, prima di importare Docling. Questo evita che un token Hugging Face
salvato ma scaduto blocchi i download pubblici. Per usare l'autenticazione implicita
impostare esplicitamente la variabile a `0` e disporre di un token valido.

### 2. PyMuPDF

Per questi PDF, che contengono già testo estraibile, usare OCR automatico:

```bash
.venv-pymupdf/bin/python scripts/pdf_to_md_pymupdf.py \
  "input/condizioni_di_assicurazione_viaggi.pdf" \
  -o risultati/condizioni_pymupdf.md --ocr auto
```

Per forzare l'OCR su tutte le pagine:

```bash
.venv-pymupdf/bin/python scripts/pdf_to_md_pymupdf.py \
  "input/condizioni_di_assicurazione_viaggi.pdf" \
  -o risultati/condizioni_pymupdf_ocr.md \
  --ocr always --ocr-language ita+eng --ocr-dpi 300
```

| Opzione | Valori | Predefinito |
| --- | --- | --- |
| `--ocr` | `always`, `auto` | `always` |
| `--ocr-language` | Codici Tesseract separati da `+` | `ita+eng` |
| `--ocr-dpi` | Intero positivo | `300` |

L'OCR forzato può aggiungere testo spurio da loghi e illustrazioni. Non garantisce
che i sottoelenchi siano ricostruiti correttamente.

### 3. Marker

```bash
.venv-marker/bin/python scripts/pdf_to_md_marker.py \
  "input/condizioni_di_assicurazione_viaggi.pdf" \
  -o risultati/condizioni_marker.md
```

Prova limitata alle pagine 2, 4, 5 e 6, utili per controllare riquadri, tabelle ed elenchi:

```bash
.venv-marker/bin/python scripts/pdf_to_md_marker.py \
  "input/condizioni_di_assicurazione_viaggi.pdf" \
  -o risultati/campione_marker.md --pages 2,4-6 --mode fast --ocr auto
```

| Opzione | Valori | Predefinito |
| --- | --- | --- |
| `--mode` | `fast`, `balanced` | `fast` |
| `--ocr` | `auto`, `always`, `never` | `auto` |
| `--pages` | Pagine da 1, per esempio `1,4-6` | Tutte |
| `--marker-bin` | Comando o percorso di `marker_single` | `marker_single` |

`balanced` dedica più elaborazione al riconoscimento tramite VLM. La numerazione
delle pagine dello script parte da **1**: l'adattatore la converte nella numerazione
da zero richiesta dalla CLI di Marker.

### 4. MinerU

```bash
.venv-mineru/bin/python scripts/pdf_to_md_mineru.py \
  "input/condizioni_di_assicurazione_viaggi.pdf" \
  -o risultati/condizioni_mineru.md
```

```bash
.venv-mineru/bin/python scripts/pdf_to_md_mineru.py \
  "input/condizioni_di_assicurazione_viaggi.pdf" \
  -o risultati/campione_mineru.md --pages 2,4-6 --tier basic --ocr auto
```

| Opzione | Valori | Predefinito |
| --- | --- | --- |
| `--tier` | `basic`, `standard`, `advanced` | `basic` |
| `--ocr` | `auto`, `always`, `never` | `auto` |
| `--pages` | Pagine da 1, per esempio `1,4-6` | Tutte |
| `--no-image-analysis` | Disabilita l'analisi delle immagini | Analisi abilitata |
| `--mineru-bin` | Comando o percorso di `mineru-kit` | `mineru-kit` |

Le modalità OCR vengono tradotte nei valori MinerU `auto`, `ocr` e `txt`.
Il comando specifica `--pages all` se non si selezionano pagine: il risultato
deve comprendere l'intero PDF, senza una finestra iniziale di lettura.

## Output, immagini ed errori

- Tutti gli script ricevono un singolo PDF locale e accettano `-o` / `--output`.
- Senza `-o`, il Markdown viene scritto su stdout; i log rimangono su stderr.
- Il file di destinazione è UTF-8 e la sua directory deve già esistere.
- Marker e MinerU salvano le immagini locali referenziate in `<nome_output>_assets/`
  accanto al Markdown e aggiornano i collegamenti. Spostare insieme file e cartella.
- Senza `-o`, i due nuovi script sostituiscono le immagini locali con
  `<!-- image -->`, così stdout non contiene riferimenti a cartelle temporanee eliminate.
- Le directory temporanee dei due adattatori vengono rimosse a fine esecuzione.
  Un errore del motore lascia il precedente file Markdown di destinazione intatto.
- I codici di uscita sono `0` per successo, `1` per errore di conversione/dipendenze/
  scrittura e `2` per argomenti non validi.

I nuovi script cercano l'eseguibile prima accanto al Python in uso, poi nel `PATH`.
Si può anche usare un motore installato in un altro ambiente:

```bash
python3 scripts/pdf_to_md_marker.py "input/condizioni_di_assicurazione_viaggi.pdf" \
  --marker-bin .venv-marker/bin/marker_single -o risultati/condizioni_marker.md
```

I nuovi adattatori sono verificati rispetto alle interfacce di Marker 2.1 e MinerU
4.2. Le vecchie CLI MinerU 2.x/3.x hanno comandi diversi e non sono supportate.

## Verifica della qualità

Confrontare il Markdown con le pagine originali, controllando almeno:

- presenza di tutto il testo nei riquadri;
- contenuto delle tabelle, comprese spunte e celle vuote;
- rientri e appartenenza delle voci negli elenchi annidati;
- ordine di lettura delle colonne e continuità tra pagine;
- ripetizioni, ligature spezzate e testo introdotto da loghi o sfondi.

Un risultato non vuoto o molto lungo non certifica completezza e fedeltà.
I nuovi adattatori non riscrivono o correggono il testo estratto dai motori.

I test degli adattatori e della gestione dei file usano CLI simulate e non scaricano
modelli. Non costituiscono un benchmark OCR dei due motori:

```bash
python3 -m unittest discover -s tests -v
```

## Documentazione dei motori

- [Docling: backend e pipeline](https://docling-project.github.io/docling/concepts/architecture/)
- [PyMuPDF: conversione Markdown](https://pymupdf.readthedocs.io/en/latest/document.html#Document.to_markdown)
- [Marker: installazione, modalità e CLI](https://github.com/datalab-to/marker)
- [MinerU: installazione e parser locale](https://github.com/opendatalab/MinerU)
- [MinerU Kit: interfaccia della conversione](https://github.com/opendatalab/MinerU/blob/master/mineru/kit/commands/parse.py)
