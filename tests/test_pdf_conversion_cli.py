"""Test del contratto CLI e dei file, senza dipendenze o modelli OCR."""

import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
import venv


ROOT = Path(__file__).resolve().parents[1]
ENGINES = {
    "marker": ("pdf_to_md_marker.py", "--marker-bin", "marker_single"),
    "mineru": ("pdf_to_md_mineru.py", "--mineru-bin", "mineru-kit"),
}

# CLI simulate: validano gli argomenti pubblici e producono output realistici
# (Markdown + immagini per Marker, archivio ZIP per MinerU).
FAKE_ENGINE = r'''
import argparse
import json
import os
from pathlib import Path
import sys
import zipfile

parser = argparse.ArgumentParser()
is_marker = Path(sys.argv[0]).name == "marker_single"
if is_marker:
    parser.add_argument("pdf")
    parser.add_argument("--output_dir", required=True)
    parser.add_argument("--output_format", required=True, choices=["markdown"])
    parser.add_argument("--mode", required=True, choices=["fast", "balanced"])
    parser.add_argument("--page_range")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--force_ocr", action="store_true")
    group.add_argument("--disable_ocr", action="store_true")
else:
    parser.add_argument("command", choices=["parse"])
    parser.add_argument("pdf")
    parser.add_argument("--output", required=True)
    parser.add_argument("--format", required=True, choices=["zip"])
    parser.add_argument("--tier", required=True, choices=["basic", "standard", "advanced"])
    parser.add_argument("--ocr-mode", required=True, choices=["auto", "ocr", "txt"])
    parser.add_argument("--pages", required=True)
    parser.add_argument("--disable-image-analysis", action="store_true")
args = parser.parse_args()
assert Path(args.pdf).is_absolute() and Path(args.pdf).is_file()
Path(os.environ["ADAPTER_TEST_RECORD"]).write_text(json.dumps(vars(args)), encoding="utf-8")
print("LOG DEL MOTORE SU STDOUT")
mode = os.environ.get("ADAPTER_TEST_MODE", "normal")
if mode == "fail":
    sys.exit(7)
markdown = "# Titolo\n\n- Padre\n    - Figlio\n\n![Figura](images/figura.png)\n<img src=\"images/figura.png\" alt=\"Figura\">\n"
if mode == "empty":
    markdown = "<!-- image -->\n\n<!-- image -->\n"
elif mode == "external-image":
    markdown = "# Titolo\n\n![Figura](../segreto.png)\n"
if is_marker:
    target = Path(args.output_dir) / "documento"
    (target / "images").mkdir(parents=True)
    (target / "documento.md").write_text(markdown, encoding="utf-8")
    (target / "images" / "figura.png").write_bytes(b"contenuto immagine di test")
else:
    with zipfile.ZipFile(args.output, "w") as archive:
        archive.writestr("documento/documento.md", markdown)
        archive.writestr("documento/images/figura.png", b"contenuto immagine di test")
        if mode == "bad-zip":
            archive.writestr("../escaped.txt", "fuori dalla cartella prevista")
'''


class ConversionCliTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory(prefix="pdf-adapter-test-")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.pdf = self.directory / "documento con spazi.pdf"
        self.pdf.write_bytes(b"%PDF-1.7\nfixture solo per il contratto CLI\n")
        self.record = self.directory / "arguments.json"
        self.commands = {}
        for name, (_, _, binary) in ENGINES.items():
            command = self.directory / binary
            command.write_text(f"#!{sys.executable}\n" + FAKE_ENGINE, encoding="utf-8")
            command.chmod(0o755)
            self.commands[name] = command

    def invoke(self, engine, *options, mode="normal"):
        script, binary_flag, _ = ENGINES[engine]
        env = os.environ.copy()
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["ADAPTER_TEST_RECORD"] = str(self.record)
        env["ADAPTER_TEST_MODE"] = mode
        return subprocess.run(
            [sys.executable, str(ROOT / "src" / script), str(self.pdf),
             binary_flag, str(self.commands[engine]), *map(str, options)],
            env=env, capture_output=True, text=True,
        )

    def test_stdout_contains_markdown_and_no_engine_logs(self):
        for engine in ENGINES:
            with self.subTest(engine=engine):
                result = self.invoke(engine)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("- Padre\n    - Figlio", result.stdout)
                self.assertEqual(result.stdout.count("<!-- image -->"), 2)
                self.assertNotIn("LOG DEL MOTORE", result.stdout)
                self.assertIn("LOG DEL MOTORE", result.stderr)
                args = json.loads(self.record.read_text())
                if engine == "marker":
                    self.assertEqual(args["mode"], "fast")
                    self.assertFalse(args["force_ocr"] or args["disable_ocr"])
                    self.assertFalse(Path(args["output_dir"]).exists())
                else:
                    self.assertEqual(args["pages"], "all")
                    self.assertEqual(args["tier"], "basic")
                    self.assertEqual(args["ocr_mode"], "auto")
                    self.assertFalse(Path(args["output"]).parent.exists())

    def test_file_output_keeps_images_after_temporary_cleanup(self):
        for engine in ENGINES:
            with self.subTest(engine=engine):
                output = self.directory / f"output {engine}.md"
                result = self.invoke(engine, "-o", output)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, "")
                markdown = output.read_text(encoding="utf-8")
                self.assertIn("- Padre\n    - Figlio", markdown)
                url = f"output%20{engine}_assets/images/figura.png"
                self.assertIn(f"![Figura]({url})", markdown)
                self.assertIn(f'src="{url}"', markdown)
                image = self.directory / f"output {engine}_assets/images/figura.png"
                self.assertEqual(image.read_bytes(), b"contenuto immagine di test")

    def test_page_numbers_and_forced_ocr_are_translated(self):
        result = self.invoke("marker", "--pages", "2,4-6", "--ocr", "always", "--mode", "balanced")
        self.assertEqual(result.returncode, 0, result.stderr)
        args = json.loads(self.record.read_text())
        self.assertEqual(args["page_range"], "1,3-5")
        self.assertTrue(args["force_ocr"])
        self.assertEqual(args["mode"], "balanced")
        result = self.invoke("mineru", "--pages", "2,4-6", "--ocr", "always", "--tier", "standard", "--no-image-analysis")
        self.assertEqual(result.returncode, 0, result.stderr)
        args = json.loads(self.record.read_text())
        self.assertEqual(args["pages"], "2,4-6")
        self.assertEqual(args["ocr_mode"], "ocr")
        self.assertEqual(args["tier"], "standard")
        self.assertTrue(args["disable_image_analysis"])

    def test_ocr_can_be_disabled(self):
        for engine in ENGINES:
            with self.subTest(engine=engine):
                result = self.invoke(engine, "--ocr", "never")
                self.assertEqual(result.returncode, 0, result.stderr)
                args = json.loads(self.record.read_text())
                self.assertTrue(args["disable_ocr"] if engine == "marker" else args["ocr_mode"] == "txt")

    def test_failed_or_empty_conversion_preserves_existing_output(self):
        output = self.directory / "precedente.md"
        for engine in ENGINES:
            for mode in ("fail", "empty", "external-image"):
                with self.subTest(engine=engine, mode=mode):
                    output.write_text("Contenuto precedente\n", encoding="utf-8")
                    result = self.invoke(engine, "-o", output, mode=mode)
                    self.assertEqual(result.returncode, 1, result.stderr)
                    self.assertEqual(result.stdout, "")
                    self.assertEqual(output.read_text(), "Contenuto precedente\n")

    def test_archive_cannot_write_outside_result_directory(self):
        output = self.directory / "risultato.md"
        result = self.invoke("mineru", "-o", output, mode="bad-zip")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("percorso non valido", result.stderr)
        self.assertFalse(output.exists())

    def test_invalid_page_ranges_are_rejected(self):
        for engine in ENGINES:
            for pages in ("0", "3-1", "1,,2", "-2", "abc"):
                with self.subTest(engine=engine, pages=pages):
                    result = self.invoke(engine, "--pages", pages)
                    self.assertEqual(result.returncode, 2, result.stderr)
                    self.assertEqual(result.stdout, "")

    def test_output_cannot_overwrite_input_or_a_hard_link_to_it(self):
        link = self.directory / "alias.md"
        link.hardlink_to(self.pdf)
        for engine in ENGINES:
            for output in (self.pdf, link):
                with self.subTest(engine=engine, output=output):
                    result = self.invoke(engine, "-o", output)
                    self.assertEqual(result.returncode, 2, result.stderr)
                    self.assertTrue(self.pdf.read_bytes().startswith(b"%PDF-1.7"))

    def test_missing_engine_produces_installation_hint(self):
        for engine in ENGINES:
            with self.subTest(engine=engine):
                self.commands[engine] = self.directory / "comando-non-installato"
                result = self.invoke(engine)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn(f"requirements-{engine}.txt", result.stderr)
                self.assertEqual(result.stdout, "")

    def test_engine_is_found_next_to_virtualenv_python_without_activation(self):
        environment = self.directory / "venv"
        venv.EnvBuilder(with_pip=False).create(environment)
        binary_directory = environment / ("Scripts" if os.name == "nt" else "bin")
        interpreter = binary_directory / ("python.exe" if os.name == "nt" else "python")
        env = os.environ.copy()
        env["ADAPTER_TEST_RECORD"] = str(self.record)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        for engine, (script, _, binary) in ENGINES.items():
            with self.subTest(engine=engine):
                command = binary_directory / binary
                command.write_text(f"#!{sys.executable}\n" + FAKE_ENGINE, encoding="utf-8")
                command.chmod(0o755)
                result = subprocess.run(
                    [str(interpreter), str(ROOT / "src" / script), str(self.pdf)],
                    env=env, capture_output=True, text=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("- Padre\n    - Figlio", result.stdout)


if __name__ == "__main__":
    unittest.main()
