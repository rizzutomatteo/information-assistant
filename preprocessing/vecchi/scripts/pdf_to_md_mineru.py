#!/usr/bin/env python3
"""Converte un PDF in Markdown con il parser locale stateless di MinerU 4.2.

Dalla cartella preprocessing/vecchi:
    python -m pip install -r requirements-mineru.txt
    python scripts/pdf_to_md_mineru.py documento.pdf -o documento.md
"""

import argparse
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

from _pdf_to_md_cli import (
    add_common_arguments,
    executable,
    extract_result,
    find_markdown,
    publish_markdown,
    run_engine,
    validate_paths,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Converte un PDF locale in Markdown con MinerU.")
    add_common_arguments(parser)
    parser.add_argument(
        "--tier", choices=("basic", "standard", "advanced"), default="basic",
        help="Livello MinerU (predefinito: basic, per macchine con meno memoria).",
    )
    parser.add_argument(
        "--no-image-analysis", action="store_true",
        help="Disabilita l'analisi delle immagini di MinerU.",
    )
    parser.add_argument(
        "--mineru-bin", default="mineru-kit", metavar="COMANDO",
        help="Eseguibile MinerU Kit, anche in un altro virtualenv (predefinito: mineru-kit).",
    )
    args = parser.parse_args()
    pdf_path, output_path = validate_paths(parser, args)

    try:
        command_path = executable(args.mineru_bin, "requirements-mineru.txt")
        with TemporaryDirectory(prefix="pdf-to-md-mineru-") as directory:
            work = Path(directory)
            archive = work / "result.zip"
            command = [
                command_path, "parse", str(pdf_path),
                "--output", str(archive),
                "--format", "zip",
                "--tier", args.tier,
                "--ocr-mode", {"auto": "auto", "always": "ocr", "never": "txt"}[args.ocr],
                "--pages", args.pages or "all",
            ]
            if args.no_image_analysis:
                command.append("--disable-image-analysis")
            run_engine(command)
            result_directory = work / "result"
            extract_result(archive, result_directory)
            publish_markdown(find_markdown(result_directory), output_path)
    except KeyboardInterrupt:
        print("Conversione interrotta.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"Errore durante la conversione con MinerU: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
