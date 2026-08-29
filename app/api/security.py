"""Upload guards (plan.md Milestone 1.2). These protect against malformed
files and runaway synthesis cost, not attackers -- no auth in v1 (see
decisions table), but the guards stay regardless.
"""

from __future__ import annotations

from fastapi import UploadFile

from app.domain.errors import InvalidUploadError

_EPUB_MAGIC_PREFIXES = (b"PK\x03\x04", b"PK\x05\x06")  # zip local-file-header / empty-archive signatures


async def read_upload_with_cap(file: UploadFile, max_bytes: int) -> bytes:
    """Stream-read with a running size cap instead of trusting Content-Length
    (which the client controls and can lie about)."""
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise InvalidUploadError(reason=f"file exceeds {max_bytes} byte limit")
        chunks.append(chunk)
    return b"".join(chunks)


def check_epub_magic_bytes(content: bytes) -> None:
    if not content.startswith(_EPUB_MAGIC_PREFIXES):
        raise InvalidUploadError(reason="file is not a valid EPUB (bad magic bytes)")
