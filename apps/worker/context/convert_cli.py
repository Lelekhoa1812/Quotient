# Motivation vs Logic
# Motivation: MarkItDown pulls in heavy parsers (PDF, Office, EPUB) that must not run inside the worker.
# Logic: Run as a subprocess by apps/worker/context/convert.py with the context venv's Python:
#   python convert_cli.py <input file> <output markdown file>
# It converts one local file, with plugins off, and exits non-zero on any failure. It never prints the
# file's content and makes no network call.
import sys


def main() -> int:
    if len(sys.argv) != 3:
        return 2
    source, target = sys.argv[1], sys.argv[2]
    try:
        from markitdown import MarkItDown

        converter = MarkItDown(enable_plugins=False)
        result = converter.convert(source)
        text = getattr(result, "text_content", None) or getattr(result, "markdown", None) or ""
    except Exception as exc:  # any parser failure is one file's problem
        print(f"convert failed: {type(exc).__name__}", file=sys.stderr)
        return 1
    with open(target, "w", encoding="utf-8") as handle:
        handle.write(str(text))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
