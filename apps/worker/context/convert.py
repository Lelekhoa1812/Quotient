# Motivation vs Logic
# Motivation: People attach what they have: a design doc, a slide deck, a spreadsheet, meeting notes. The
# analysis agents read Markdown, so every format has to become Markdown first, and a hostile or broken
# file must never take the worker down or reach a model unsanitised.
# Logic: Plain text, Markdown and the two small structured formats (CSV, JSON) are read in-process.
# Everything else goes to Microsoft MarkItDown, run as a subprocess in its own Python venv
# (.local/context-venv, built by scripts/setup-context.sh) with a timeout, so a parser crash, a hang or
# a memory blow-up costs one file. MarkItDown plugins are off and nothing here makes a network call.
# Output is cleaned (control characters out, blank runs collapsed) and capped.

from __future__ import annotations

import csv
import io
import json
import os
import re
import signal
import subprocess
import sys
import zipfile
from pathlib import Path

MAX_DOC_CHARS = 400_000
TIMEOUT_SECONDS = 120.0
_PLAIN = {".txt", ".md", ".markdown"}
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
# Text a person cannot see but a model reads: the Unicode Tags block (used to smuggle hidden instructions), variation selectors
# beyond the first block, the word joiner and byte-order mark, C1 controls, and the bidirectional overrides and isolates (which reorder
# what is shown). Joiners, the zero-width space and the left/right marks stay: Persian, Indic, Thai, Arabic and emoji need them.
# The three subdivision flags (England, Scotland, Wales) are real emoji written with Tags characters and are kept exactly.
_FLAGS = "\U0001F3F4(?:\U000e0067\U000e0062(?:\U000e0065\U000e006e\U000e0067|\U000e0073\U000e0063\U000e0074|\U000e0077\U000e006c\U000e0073))\U000e007f"
_INVISIBLE = re.compile("(" + _FLAGS + ")|[\U000e0000-\U000e007f\U000e0100-\U000e01ef\u202a-\u202e\u2066-\u2069\u2060\ufeff\x80-\x9f]")


class ConverterUnavailable(RuntimeError):
    """The MarkItDown environment is not built."""


class ConversionFailed(RuntimeError):
    """The file could not be turned into text; the message is safe to show a person."""


def _python() -> Path | None:
    root = Path(__file__).resolve().parents[3]
    override = os.environ.get("QUOTIENT_CONTEXT_PYTHON", "").strip()
    candidate = Path(override) if override else root / ".local" / "context-venv" / "bin" / "python"
    return candidate if candidate.is_file() else None


def clean(text: str) -> tuple[str, bool]:
    """Printable text with tidy spacing, capped; the flag says whether it was cut."""
    text = _INVISIBLE.sub(lambda m: m.group(1) or "", _CONTROL.sub("", text.replace("\r\n", "\n").replace("\r", "\n")))
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if len(text) > MAX_DOC_CHARS:
        return text[:MAX_DOC_CHARS].rstrip(), True
    return text, False


_ZIP_BASED = {".docx", ".pptx", ".xlsx", ".epub"}
ZIP_MAX_UNCOMPRESSED = 100 * 1024**2
ZIP_MAX_RATIO = 100


def _zip_guard(path: Path) -> None:
    """Office files and EPUBs are zip archives; refuse one that would inflate into a bomb before any parser sees it."""
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            total = sum(info.file_size for info in infos)
            packed = max(1, sum(info.compress_size for info in infos))
    except zipfile.BadZipFile as exc:
        raise ConversionFailed("This file could not be read. It may be damaged.") from exc
    if total > ZIP_MAX_UNCOMPRESSED or total / packed > ZIP_MAX_RATIO or len(infos) > 5000:
        raise ConversionFailed("This file is too large once opened.")


def _read_text(path: Path) -> str:
    data = path.read_bytes()
    if b"\x00" in data[:8192] and not data.startswith((b"\xff\xfe", b"\xfe\xff")) or data.startswith(b"PK\x03\x04") or data.startswith(b"%PDF"):
        raise ConversionFailed("This file is not plain text. Check its type.")
    for encoding in ("utf-8-sig", "utf-16"):
        try:
            return data.decode(encoding)
        except UnicodeError:
            continue
    return data.decode("latin-1", errors="replace")


CSV_MAX_ROWS = 500
CSV_MAX_COLUMNS = 50
CSV_MAX_LINE = 100_000


def _csv_table(text: str) -> tuple[str, bool]:
    """(markdown table, cut). `cut` is true when rows, columns or bytes were left out."""
    # Bounded before parsing: a one-row file with millions of columns would otherwise be padded to every row.
    head = text[: 4 * 1024 * 1024]
    cut = len(head) < len(text)
    if any(len(line) > CSV_MAX_LINE for line in head.split("\n", CSV_MAX_ROWS + 20)[: CSV_MAX_ROWS + 20]):
        raise ConversionFailed("This CSV file has a row that is too long to read.")
    rows: list[list[str]] = []
    try:
        for row in csv.reader(io.StringIO(head)):
            if not any(cell.strip() for cell in row):
                continue
            if len(rows) >= CSV_MAX_ROWS:
                cut = True
                break
            cut = cut or len(row) > CSV_MAX_COLUMNS
            rows.append(row[:CSV_MAX_COLUMNS])
    except csv.Error as exc:
        raise ConversionFailed("This CSV file could not be read.") from exc
    if not rows:
        return "", cut
    width = max(len(row) for row in rows)
    pad = lambda row: [cell.replace("|", "\\|").replace("\n", " ").strip() for cell in row] + [""] * (width - len(row))  # noqa: E731
    lines = ["| " + " | ".join(pad(rows[0])) + " |", "| " + " | ".join(["---"] * width) + " |"]
    lines += ["| " + " | ".join(pad(row)) + " |" for row in rows[1:]]
    return "\n".join(lines), cut


def _json_block(text: str) -> str:
    try:
        pretty = json.dumps(json.loads(text), indent=2, ensure_ascii=False)
    except ValueError as exc:
        raise ConversionFailed("This JSON file is not valid JSON.") from exc
    return "```json\n" + pretty + "\n```"


def _limits() -> None:  # runs in the child before exec
    try:
        import resource

        resource.setrlimit(resource.RLIMIT_CPU, (int(TIMEOUT_SECONDS) + 30, int(TIMEOUT_SECONDS) + 30))
        resource.setrlimit(resource.RLIMIT_FSIZE, (512 * 1024**2, 512 * 1024**2))
    except Exception:
        pass


def _kill_group(process) -> None:
    if process is None:
        return
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        pass
    try:
        process.communicate(timeout=5)
    except Exception:
        pass


def to_markdown(path: Path, *, timeout_s: float = TIMEOUT_SECONDS) -> tuple[str, bool]:
    """(markdown, truncated). Raises ConverterUnavailable or ConversionFailed with a plain message."""
    extension = path.suffix.lower()
    if extension in _PLAIN:
        return clean(_read_text(path))
    if extension == ".csv":
        table, cut = _csv_table(_read_text(path))
        markdown, truncated = clean(table)
        return markdown, truncated or cut
    if extension == ".json":
        return clean(_json_block(_read_text(path)))
    if extension in _ZIP_BASED:
        _zip_guard(path)
    python = _python()
    if python is None:
        raise ConverterUnavailable("The document converter is not installed. Run scripts/setup-context.sh.")
    out = path.with_name(path.name + ".md")
    process = None
    try:
        process = subprocess.Popen(
            [str(python), "-I", str(Path(__file__).with_name("convert_cli.py")), str(path), str(out)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            text=True,
            env={"PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", ""), "PYTHONDONTWRITEBYTECODE": "1"},
            start_new_session=True,  # its own process group, so a timeout can take down everything it started
            preexec_fn=_limits,
        )
        _stdout, _stderr = process.communicate(timeout=timeout_s)
        completed = subprocess.CompletedProcess(process.args, process.returncode, _stdout, _stderr)
    except subprocess.TimeoutExpired as exc:
        _kill_group(process)
        raise ConversionFailed("This file took too long to read.") from exc
    except OSError as exc:
        raise ConverterUnavailable("The document converter could not be started.") from exc
    if completed.returncode != 0 or not out.is_file():
        print(f"context conversion failed: {path.suffix} exit {completed.returncode}", file=sys.stderr, flush=True)
        raise ConversionFailed("This file could not be read. It may be damaged or password-protected.")
    text = out.read_text(encoding="utf-8", errors="replace")
    if not text.strip():
        raise ConversionFailed("No readable text was found in this file.")
    return clean(text)
