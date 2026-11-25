# Information Assistant

- Sito Velaria con chat, accesso, FAQ e assistente vocale. [Guida dell’applicazione](assistente/README.md)
- Confronto tra Docling, PyMuPDF, Marker e MinerU, con script, requisiti e risultati. [Guida al preprocessing](preprocessing/vecchi/README.md)
- Relazione di progetto con capitoli, figure e bibliografia. [Sorgente LaTeX](docs/relazione/CSD_2026-27_InformationAssistant.tex)
- Valutazione comparativa dei chatbot assicurativi. [Stato dell’arte](docs/ricerca/state_of_art.md)

## Compilare la relazione

Con una distribuzione LaTeX e `latexmk` installati, eseguire il comando dalla radice del repository.

```bash
latexmk -cd -pdf docs/relazione/CSD_2026-27_InformationAssistant.tex
```
