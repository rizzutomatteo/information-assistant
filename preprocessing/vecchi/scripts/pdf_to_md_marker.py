#!/usr/bin/env python3
"""Converte un PDF in Markdown tramite la CLI di Marker 2.1.

Dalla cartella preprocessing/vecchi:
    python -m pip install -r requirements-marker.txt
    python scripts/pdf_to_md_marker.py documento.pdf -o documento.md
"""

import argparse
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

from _pdf_to_md_cli import (
    add_common_arguments,
    executable,
    find_markdown,
    marker_pages,
    publish_markdown,
    run_engine,
    validate_paths,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Converte un PDF locale in Markdown con Marker.")
    add_common_arguments(parser)
    parser.add_argument(
        "--mode", choices=("fast", "balanced"), default="fast",
        help="Modalità Marker (predefinito: fast, adatta a CPU/Mac).",
    )
    parser.add_argument(
        "--marker-bin", default="marker_single", metavar="COMANDO",
        help="Eseguibile Marker, anche in un altro virtualenv (predefinito: marker_single).",
    )
    args = parser.parse_args()
    pdf_path, output_path = validate_paths(parser, args)

    try:
        command_path = executable(args.marker_bin, "requirements-marker.txt")
        with TemporaryDirectory(prefix="pdf-to-md-marker-") as directory:
            work = Path(directory)
            command = [
                command_path, str(pdf_path),
                "--output_dir", str(work),
                "--output_format", "markdown",
                "--mode", args.mode,
            ]
            if args.ocr == "always":
                command.append("--force_ocr")
            elif args.ocr == "never":
                command.append("--disable_ocr")
            if args.pages is not None:
                command.extend(["--page_range", marker_pages(args.pages)])
            run_engine(command)
            publish_markdown(find_markdown(work), output_path)
    except KeyboardInterrupt:
        print("Conversione interrotta.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"Errore durante la conversione con Marker: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
