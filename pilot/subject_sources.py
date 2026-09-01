"""Download and stage remote per-subject Markdown sources safely.

Teacher packages do not contain the course Markdown files.  The configured
HTTPS source is fetched only for the current review, written to a short-lived
per-job directory, and removed after NotebookLM finishes using it.
"""
from __future__ import annotations

import uuid
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen


MAX_SUBJECT_BYTES = 16 * 1024 * 1024
USER_AGENT = "TYMM-Soru-Kontrol-Subject-Source/1"


class SubjectSourceError(RuntimeError):
    """Raised when a configured remote subject source cannot be used."""


def _is_allowed_url(value: str) -> bool:
    parsed = urlparse(str(value or "").strip())
    return parsed.scheme == "https" and bool(parsed.netloc)


def _download(url: str, timeout: int = 20) -> bytes:
    if not _is_allowed_url(url):
        raise SubjectSourceError("Ders kaynağı adresi HTTPS olmalı.")
    request = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/markdown, text/plain, application/octet-stream",
        },
    )
    try:
        with urlopen(request, timeout=max(1, min(120, int(timeout)))) as response:
            length = response.headers.get("Content-Length")
            if length and int(length) > MAX_SUBJECT_BYTES:
                raise SubjectSourceError("Ders kaynağı izin verilen boyutu aşıyor.")
            chunks: list[bytes] = []
            total = 0
            while True:
                chunk = response.read(min(1024 * 1024, MAX_SUBJECT_BYTES - total + 1))
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_SUBJECT_BYTES:
                    raise SubjectSourceError("Ders kaynağı izin verilen boyutu aşıyor.")
                chunks.append(chunk)
            return b"".join(chunks)
    except SubjectSourceError:
        raise
    except Exception as exc:
        raise SubjectSourceError(f"Ders kaynağı indirilemedi: {exc}") from exc


def _decode(raw: bytes) -> str:
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise SubjectSourceError("Ders Markdown kaynağı geçerli UTF-8 metin değil.") from exc
    if not text.strip():
        raise SubjectSourceError("İndirilen ders Markdown kaynağı boş.")
    return text


def stage_remote_subject(url: str, root: Path, subject_key: str, *, timeout: int = 20) -> Path:
    """Fetch one HTTPS Markdown source into a unique temporary job directory."""
    url = str(url or "").strip()
    text = _decode(_download(url, timeout))
    parsed_name = Path(urlparse(url).path).name
    filename = parsed_name if parsed_name.casefold().endswith(".md") else f"{subject_key}.md"
    # Keep the source title stable for the existing NotebookLM prompt while
    # isolating each download from other jobs.
    parent = root / "work" / "subject-sources" / f"{subject_key}-{uuid.uuid4().hex}"
    parent.mkdir(parents=True, exist_ok=True)
    target = parent / filename
    temporary = target.with_suffix(target.suffix + ".tmp")
    try:
        temporary.write_text(text, encoding="utf-8", newline="\n")
        temporary.replace(target)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return target


def cleanup_subject_source(path: Path | None) -> None:
    """Remove a staged subject source and its empty per-job directories."""
    if path is None:
        return
    try:
        path.unlink(missing_ok=True)
        parent = path.parent
        # The source is always placed below work/subject-sources.  Do not
        # recurse or remove arbitrary teacher files if a custom path is passed.
        if (
            parent.parent.name.casefold() == "subject-sources"
            and parent.parent.parent.name.casefold() == "work"
        ):
            parent.rmdir()
    except OSError:
        # Cleanup must not mask a NotebookLM result or an earlier error.
        return
