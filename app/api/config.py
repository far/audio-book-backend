"""Env-based config.

Every value is a `default_factory` rather than a plain default so the
environment is read when a `Settings` is constructed, not when the class
body executes -- otherwise `Settings()` could never pick up anything but
the env present at import.
 See spec/plan.md decisions table: no auth/TLS for
testing, Piper-only unless a paid provider's API key is configured."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _env_int(name: str, default: int) -> int:
    val = os.environ.get(name)
    return int(val) if val is not None else default


@dataclass(frozen=True, slots=True)
class Settings:
    backend_dir: Path = field(default_factory=lambda: Path(__file__).parent.parent.parent)

    voice_path: Path = field(
        default_factory=lambda: Path(__file__).parent.parent.parent
        / "voices"
        / "en_US-lessac-medium.onnx"
    )
    tmp_dir: Path = field(default_factory=lambda: Path(__file__).parent.parent.parent / "tmp")

    default_provider: str = field(default_factory=lambda: os.environ.get("DEFAULT_TTS_PROVIDER", "piper"))

    # Used when a chunk request omits `voice_id`. The app always sends one;
    # this keeps a bare URL working from a browser or curl.
    default_voice_id: str = field(
        default_factory=lambda: os.environ.get("DEFAULT_TTS_VOICE_ID", "en_US-lessac-medium")
    )


    # A key present is taken as intent to offer that provider. There used
    # to be a separate PAID_PROVIDERS_ENABLED switch so a key sitting in the
    # environment couldn't spend credits by itself -- but selection is now
    # per request and defaults to Piper, so a registered provider costs
    # nothing until someone picks it, and two flags for one decision only
    # produced "why isn't ElevenLabs showing?".
    elevenlabs_api_key: str | None = field(default_factory=lambda: os.environ.get("ELEVENLABS_API_KEY"))
    openai_api_key: str | None = field(default_factory=lambda: os.environ.get("OPENAI_API_KEY"))

    # Parsing peaks at roughly 18x the compressed file (measured: 6MB peak
    # for a 0.31MB EPUB), so a 50MB upload would need ~900MB and get
    # OOM-killed on a 1GB host. 12MB covers any ordinary book with room to
    # spare; raise it if the host has the memory.
    max_upload_bytes: int = field(default_factory=lambda: _env_int("MAX_UPLOAD_BYTES", 12 * 1024 * 1024))
    max_epub_uncompressed_bytes: int = field(default_factory=lambda: _env_int("MAX_EPUB_UNCOMPRESSED_BYTES", 200 * 1024 * 1024))
    max_characters_per_session: int = field(default_factory=lambda: _env_int("MAX_CHARACTERS_PER_SESSION", 500_000))


    # 1 by default: the target host is a single-vCPU droplet, where a second
    # inference thread can't run in parallel anyway but still costs ~70MB of
    # working memory on top of the ~150MB resident model. Raise it to match
    # the core count on a bigger host. Note this pool is shared with ffmpeg
    # transcoding, which *is* a separate process and so does benefit from
    # more threads -- but not enough to pay for the memory here.
    synthesis_worker_pool_size: int = field(default_factory=lambda: _env_int("SYNTHESIS_WORKER_POOL_SIZE", 1))

    # How long an untouched session is kept. "Touched" includes fetching a
    # chunk, so an active listener never expires; this only bounds how long
    # an abandoned book holds memory (~5MB per 0.3MB EPUB).
    session_ttl_seconds: int = field(default_factory=lambda: _env_int("SESSION_TTL_SECONDS", 60 * 60 * 2))


settings = Settings()
