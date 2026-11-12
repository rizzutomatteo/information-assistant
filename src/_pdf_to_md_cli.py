"""Funzioni comuni agli adattatori CLI di Marker e MinerU (solo libreria standard)."""

import argparse
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
from urllib.parse import quote, unquote, urlsplit
import zipfile


_MD_IMAGE = re.compile(r'!\[([^\]\n]*)\]\(\s*(<[^>\n]+>|[^\s)]+)(?:\s+"[^"\n]*")?\s*\)')
_HTML_IMAGE = re.compile(
    r'(?P<prefix><img\b[^>]*?\bsrc\s*=\s*)(?P<quote>[\'\"])(?P<url>.*?)(?P=quote)(?P<suffix>[^>]*>)',
    re.IGNORECASE | re.DOTALL,
)


def add_common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("pdf", type=Path, help="Percorso del PDF locale da convertire.")
    parser.add_argument(
        "-o", "--output", type=Path, metavar="FILE.md",
        help="Salva il Markdown UTF-8 e le immagini associate (predefinito: testo su stdout).",
    )
    parser.add_argument(
        "--ocr", choices=("auto", "always", "never"), default="auto",
        help="OCR automatico, forzato o disattivato (predefinito: auto).",
    )
    parser.add_argument(
        "--pages", type=page_selection, metavar="PAGINE",
        help="Pagine da 1, per esempio 1,4-6 (predefinito: tutte).",
    )


def page_selection(value: str) -> str:
    """Valida una selezione di pagine da 1 senza espandere intervalli grandi."""
    parts = []
    for part in value.split(","):
        match = re.fullmatch(r"\s*([1-9]\d*)(?:-([1-9]\d*))?\s*", part)
        if match is None:
            raise argparse.ArgumentTypeError("Usare pagine da 1, per esempio 1,4-6.")
        start = int(match[1])
        end = int(match[2]) if match[2] else start
        if end < start:
            raise argparse.ArgumentTypeError("Gli intervalli devono essere crescenti.")
        parts.append(str(start) if end == start else f"{start}-{end}")
    return ",".join(parts)


def marker_pages(value: str) -> str:
    return ",".join(
        "-".join(str(int(number) - 1) for number in part.split("-"))
        for part in value.split(",")
    )


def validate_paths(parser, args) -> tuple[Path, Path | None]:
    pdf_path = args.pdf.expanduser().resolve()
    output_path = args.output.expanduser().absolute() if args.output is not None else None
    if not pdf_path.is_file():
        parser.error(f"Il file non esiste o non è un file regolare: {pdf_path}")
    if pdf_path.suffix.lower() != ".pdf":
        parser.error(f"Il file di input deve avere estensione .pdf: {pdf_path}")
    if output_path is not None:
        same_file = output_path.resolve() == pdf_path
        if output_path.exists() and output_path.is_file():
            same_file = same_file or output_path.samefile(pdf_path)
        if same_file:
            parser.error("Il percorso di output deve essere diverso dal PDF di input.")
        if output_path.is_dir():
            parser.error(f"L'output deve essere un file: {output_path}")
        if not output_path.parent.is_dir():
            parser.error(f"La cartella di output non esiste: {output_path.parent}")
    return pdf_path, output_path


def executable(command: str, requirements: str) -> str:
    path = shutil.which(command, path=str(Path(sys.executable).parent)) or shutil.which(command)
    if path is None:
        raise RuntimeError(
            f"Comando non trovato: {command}. Attivare l'ambiente del motore ed eseguire: "
            f"python -m pip install -r {requirements}"
        )
    return path


def run_engine(command: list[str]) -> None:
    env = os.environ.copy()
    env.setdefault("HF_HUB_DISABLE_IMPLICIT_TOKEN", "1")
    result = subprocess.run(command, stdout=sys.stderr, stderr=sys.stderr, env=env)
    if result.returncode != 0:
        raise RuntimeError(
            f"{Path(command[0]).name} è terminato con codice {result.returncode}. "
            "Consultare i messaggi del motore su stderr."
        )


def find_markdown(directory: Path) -> Path:
    candidates = sorted(directory.rglob("*.md"))
    if len(candidates) != 1:
        raise RuntimeError(
            f"Il motore ha prodotto {len(candidates)} file Markdown; ne era atteso uno. "
            "Verificare la versione installata e i messaggi del motore."
        )
    return candidates[0]


def extract_result(archive_path: Path, destination: Path) -> None:
    """Estrae il risultato MinerU solo dentro la cartella temporanea prevista."""
    root = destination.resolve()
    with zipfile.ZipFile(archive_path) as archive:
        for member in archive.infolist():
            target = (root / member.filename).resolve()
            if not target.is_relative_to(root) or stat.S_ISLNK(member.external_attr >> 16):
                raise RuntimeError("Il risultato ZIP contiene un percorso non valido.")
        archive.extractall(root)


def publish_markdown(markdown_path: Path, output_path: Path | None) -> None:
    """Preserva il testo e rende persistenti le immagini locali con -o."""
    markdown = markdown_path.read_text(encoding="utf-8")
    root = markdown_path.parent.resolve()
    copied = {}

    def image_url(raw_url: str) -> str | None:
        url = raw_url.removeprefix("<").removesuffix(">")
        parsed = urlsplit(url)
        if parsed.scheme or parsed.netloc or url.startswith("#"):
            return url
        if output_path is None:
            return None
        source = (root / unquote(parsed.path)).resolve()
        if not source.is_relative_to(root) or not source.is_file():
            raise RuntimeError(f"Immagine del risultato non disponibile: {url}")
        relative = source.relative_to(root)
        if relative not in copied:
            assets = output_path.parent / f"{output_path.stem}_assets"
            target = assets / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            copied[relative] = quote(target.relative_to(output_path.parent).as_posix(), safe="/")
        return copied[relative]

    def markdown_image(match):
        url = image_url(match[2])
        return "<!-- image -->" if url is None else f"![{match[1]}]({url})"

    def html_image(match):
        url = image_url(match["url"])
        if url is None:
            return "<!-- image -->"
        return f'{match["prefix"]}{match["quote"]}{url}{match["quote"]}{match["suffix"]}'

    # Rifiuta i risultati vuoti prima di scrivere file di output.
    if not re.sub(r"<!--.*?-->", "", markdown, flags=re.DOTALL).strip():
        raise RuntimeError("Il motore ha prodotto un Markdown vuoto o solo segnaposto.")
    markdown = _MD_IMAGE.sub(markdown_image, markdown)
    markdown = _HTML_IMAGE.sub(html_image, markdown)
    if not re.sub(r"<!--.*?-->", "", markdown, flags=re.DOTALL).strip():
        raise RuntimeError("Il risultato non contiene testo. Usare -o per salvare le immagini o abilitare l'OCR.")
    if not markdown.endswith("\n"):
        markdown += "\n"
    if output_path is None:
        sys.stdout.write(markdown)
    else:
        output_path.write_text(markdown, encoding="utf-8")
