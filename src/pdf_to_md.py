#!/usr/bin/env python3
"""Converte un PDF locale in Markdown usando Docling.

Installazione:
    python3 -m pip install -r requirements.txt

Esempi:
    python3 src/pdf_to_md.py documento.pdf
    python3 src/pdf_to_md.py documento.pdf -o documento.md

I modelli pubblici vengono scaricati senza inviare automaticamente il token
Hugging Face salvato. Per abilitarlo, impostare HF_HUB_DISABLE_IMPLICIT_TOKEN=0.

La lettura del PDF usa PDFium: alcuni PDF con testo incorporato restituiscono
celle vuote con il backend docling-parse v4.
"""

import argparse
from contextlib import redirect_stdout
import os
from pathlib import Path
import re
import sys


def pdf_to_md(pdf_path: Path) -> str:
    """Restituisce il Markdown, riservando stdout al risultato della CLI."""
    # Hugging Face legge questa opzione all'import: configurarla prima di Docling.
    # Un token salvato ma scaduto può bloccare anche i download dei modelli pubblici.
    os.environ.setdefault("HF_HUB_DISABLE_IMPLICIT_TOKEN", "1")

    with redirect_stdout(sys.stderr):
        try:
            from docling.backend.pypdfium2_backend import PyPdfiumDocumentBackend
            from docling.datamodel.base_models import InputFormat
            from docling.document_converter import DocumentConverter, PdfFormatOption
        except ModuleNotFoundError as exc:
            if exc.name == "docling":
                raise RuntimeError(
                    "Docling non è installato. Esegui: "
                    "python3 -m pip install -r requirements.txt"
                ) from exc
            raise

        converter = DocumentConverter(
            allowed_formats=[InputFormat.PDF],
            format_options={
                InputFormat.PDF: PdfFormatOption(backend=PyPdfiumDocumentBackend)
            },
        )
        result = converter.convert(pdf_path)
        markdown = result.document.export_to_markdown()
        if not re.sub(r"<!--.*?-->", "", markdown, flags=re.DOTALL).strip():
            raise RuntimeError(
                "Docling non ha estratto testo: il risultato contiene solo "
                "segnaposto immagine o è vuoto. Verificare l'OCR del documento."
            )
        return markdown


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Converte un PDF locale in Markdown con Docling."
    )
    parser.add_argument("pdf", type=Path, help="Percorso del PDF da convertire.")
    parser.add_argument(
        "-o", "--output", type=Path, metavar="FILE.md",
        help="Salva il Markdown in un file UTF-8 (predefinito: stdout).",
    )
    args = parser.parse_args()
    pdf_path = args.pdf.expanduser()
    output_path = args.output.expanduser() if args.output is not None else None

    if not pdf_path.is_file():
        parser.error(f"Il file non esiste o non è un file regolare: {pdf_path}")
    if pdf_path.suffix.lower() != ".pdf":
        parser.error(f"Il file di input deve avere estensione .pdf: {pdf_path}")
    if output_path is not None and output_path.resolve() == pdf_path.resolve():
        parser.error("Il percorso di output deve essere diverso dal PDF di input.")

    try:
        markdown = pdf_to_md(pdf_path)
    except Exception as exc:
        print(f"Errore durante la conversione: {exc}", file=sys.stderr)
        return 1

    if not markdown.endswith("\n"):
        markdown += "\n"

    try:
        if output_path is None:
            sys.stdout.write(markdown)
        else:
            output_path.write_text(markdown, encoding="utf-8")
    except OSError as exc:
        print(f"Errore durante la scrittura del Markdown: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
