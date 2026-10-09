# Motivation vs Logic
# Motivation: Uploaded context has to become a library before the analysis starts, and one bad file must
# not stop the meeting. Converting a large PDF is slow, and the same pack is often reused, so the work is
# cached by the file's content.
# Logic: For each declared item: check it exists and is within limits, download it to a private temporary
# directory, convert it (cache hit by SHA-256 of the bytes skips conversion), and record a status the
# person can read: ready, skipped (too big, unsupported) or failed (could not be read). Pasted notes are
# already Markdown. Nothing raises: the result is the library of what worked and the per-item statuses.

from __future__ import annotations

import hashlib
import shutil
import sys
import tempfile
import time
from pathlib import Path

from context.convert import ConversionFailed, ConverterUnavailable, to_markdown
from context.library import ContextDoc, ContextLibrary, gist_of, headings_of
from media import storage


CACHE_DAYS = 30


def _cache_path(cache_dir: Path | None, scope: str, digest: str) -> Path | None:
    """Converted text is cached per person: identical bytes from someone else must not be a cache hit, which
    would reveal that the same file was uploaded before and keep their text under another person's name."""
    return cache_dir / (scope or "shared") / f"{digest}.md" if cache_dir is not None else None


def _evict(cache_dir: Path) -> None:
    cutoff = time.time() - CACHE_DAYS * 86400
    try:
        for path in cache_dir.rglob("*"):
            if path.is_file() and path.stat().st_mtime < cutoff:
                path.unlink(missing_ok=True)
    except OSError:
        pass


def load_library(items: list[dict], purpose: str = "", *, cache_dir: Path | None = None, scope: str = "", download=None, head=None) -> tuple[ContextLibrary, list[dict]]:
    """(library, items with status/reason/chars/summary filled in)."""
    download = download or storage.download
    head = head or storage.head
    if cache_dir is not None:
        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
            _evict(cache_dir)
        except OSError:
            cache_dir = None  # a cache that cannot be written only costs speed; the documents are still read
    docs: list[ContextDoc] = []
    updated: list[dict] = []
    total = 0
    for position, raw in enumerate(items or [], start=1):
        item = dict(raw)
        item.setdefault("name", f"Document {position}")
        item["status"], item["reason"], item["chars"], item["summary"] = "failed", None, None, None
        scratch = Path(tempfile.mkdtemp(prefix="quotient-context-"))
        try:
            key = str(item.get("key") or "")
            if not key.startswith(storage.CONTEXT_PREFIX):
                item["status"], item["reason"] = "skipped", "This item was not uploaded."
                continue
            info = head(key)
            if info is None:
                item["reason"] = "The upload did not finish."
                continue
            if info["size"] <= 0:
                item["status"], item["reason"] = "skipped", "The file is empty."
                continue
            if info["size"] > storage.CONTEXT_MAX_FILE_BYTES:
                item["status"], item["reason"] = "skipped", "Larger than 25 MB."
                continue
            if total + info["size"] > storage.CONTEXT_MAX_TOTAL_BYTES:
                item["status"], item["reason"] = "skipped", "The context is over 100 MB in total."
                continue
            try:
                path = download(key, scratch, max_bytes=storage.CONTEXT_MAX_FILE_BYTES)
            except storage.TooLarge:
                item["status"], item["reason"] = "skipped", "Larger than 25 MB."
                continue
            total += path.stat().st_size
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            cached = _cache_path(cache_dir, scope, digest)
            if cached is not None and cached.is_file():
                text = cached.read_text(encoding="utf-8")
                truncated = cached.with_suffix(".cut").is_file()
            else:
                text, truncated = to_markdown(path)
                if cached is not None and text:
                    cached.parent.mkdir(parents=True, exist_ok=True)
                    cached.write_text(text, encoding="utf-8")
                    if truncated:
                        cached.with_suffix(".cut").write_text("1", encoding="utf-8")
            if not text.strip():
                item["reason"] = "No readable text was found in this file."
                continue
            doc = ContextDoc(
                id=f"c{len(docs) + 1}",
                name=str(item["name"])[:160],
                markdown=text,
                truncated=truncated,
                headings=headings_of(text),
                gist=gist_of(text),
            )
            docs.append(doc)
            item.update(status="ready", reason=("Only the first part was kept." if truncated else None), chars=doc.chars, summary=doc.gist or None, doc_id=doc.id)
        except ConverterUnavailable as exc:
            item["status"], item["reason"] = "skipped", str(exc)
        except ConversionFailed as exc:
            item["reason"] = str(exc)
        except Exception as exc:  # one item's problem is never the meeting's
            print(f"context item skipped: {type(exc).__name__}", file=sys.stderr, flush=True)
            item["reason"] = "This file could not be read."
        finally:
            shutil.rmtree(scratch, ignore_errors=True)
            updated.append(item)
    return ContextLibrary(docs, purpose), updated
