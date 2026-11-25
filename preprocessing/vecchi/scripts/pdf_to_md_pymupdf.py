#!/usr/bin/env python3
"""Converte un PDF locale in Markdown con PyMuPDF e OCR.

Installazione Python:
    python3 -m pip install 'pymupdf>=2.0,<3'

Per l'OCR installare Tesseract e i dati delle lingue richieste:
    macOS:         brew install tesseract tesseract-lang
    Debian/Ubuntu: sudo apt install tesseract-ocr tesseract-ocr-ita tesseract-ocr-eng

Esempi dalla cartella preprocessing/vecchi:
    python3 scripts/pdf_to_md_pymupdf.py documento.pdf
    python3 scripts/pdf_to_md_pymupdf.py documento.pdf -o documento.md
    python3 scripts/pdf_to_md_pymupdf.py documento.pdf --ocr auto --ocr-language eng
"""

import argparse
from contextlib import redirect_stdout
from pathlib import Path
import sys


def pdf_to_md(
    pdf_path: Path,
    *,
    ocr_language: str = "ita+eng",
    ocr_dpi: int = 300,
    force_ocr: bool = True,
) -> str:
    """Estrae Markdown usando l'analisi del layout e il riconoscimento OCR."""
    with redirect_stdout(sys.stderr):
        try:
            import pymupdf
        except ModuleNotFoundError as exc:
            if exc.name == "pymupdf":
                raise RuntimeError(
                    "PyMuPDF non è installato. Esegui: "
                    "python3 -m pip install 'pymupdf>=2.0,<3'"
                ) from exc
            raise

        with pymupdf.open(pdf_path) as document:
            if document.needs_pass:
                raise ValueError("Il PDF è protetto da password: fornire una copia sbloccata.")
            if not hasattr(document, "to_markdown"):
                raise RuntimeError(
                    "È richiesto PyMuPDF 2.0 o successivo. Esegui: "
                    "python3 -m pip install --upgrade 'pymupdf>=2.0,<3'"
                )
            return document.to_markdown(
                use_ocr=True,
                force_ocr=force_ocr,
                ocr_language=ocr_language,
                ocr_dpi=ocr_dpi,
                show_progress=False,
            )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Converte un PDF locale in Markdown con PyMuPDF e OCR."
    )
    parser.add_argument("pdf", type=Path, help="Percorso del PDF da convertire.")
    parser.add_argument(
        "-o", "--output", type=Path, metavar="FILE.md",
        help="Salva il Markdown in un file UTF-8 (predefinito: stdout).",
    )
    parser.add_argument(
        "--ocr", choices=("always", "auto"), default="always",
        help="Esegue OCR su tutte le pagine o solo se necessario (predefinito: always).",
    )
    parser.add_argument(
        "--ocr-language", default="ita+eng", metavar="LINGUE",
        help="Codici delle lingue Tesseract separati da + (predefinito: ita+eng).",
    )
    parser.add_argument(
        "--ocr-dpi", type=int, default=300, metavar="DPI",
        help="Risoluzione OCR in punti per pollice (predefinito: 300).",
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
    if args.ocr_dpi <= 0:
        parser.error("--ocr-dpi deve essere un intero positivo.")
    if not args.ocr_language.strip() or any(
        not language.strip() for language in args.ocr_language.split("+")
    ):
        parser.error("--ocr-language richiede codici lingua separati da +, per esempio ita+eng.")

    try:
        markdown = pdf_to_md(
            pdf_path,
            ocr_language=args.ocr_language,
            ocr_dpi=args.ocr_dpi,
            force_ocr=args.ocr == "always",
        )
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
