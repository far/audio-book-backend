"""Piper adapter -- offline default. Runs synthesis in a thread pool since
Piper inference is CPU-bound and would otherwise block the event loop
(plan.md Milestone 3.2)."""

from __future__ import annotations

import asyncio
import io
import threading
import wave
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from app.application.ports import SynthesisResult, TTSProvider
from app.domain.entities import TTSSettings, Voice


class PiperProvider(TTSProvider):
    name = "piper"

    def __init__(self, voice_path: Path, worker_pool: ThreadPoolExecutor) -> None:
        self._voice_path = voice_path
        self._worker_pool = worker_pool
        self._voice: Any | None = None  # lazy-loaded, kept warm once loaded (Milestone 3.2)
        # `synthesize` runs in a thread pool, so two requests can reach the
        # lazy load at once. The model is ~150MB resident, so loading it
        # twice is a ~300MB spike -- enough to be OOM-killed on a 1GB host,
        # for a second copy that is then discarded.
        self._voice_lock = threading.Lock()

    def _load_voice(self) -> Any:
        # Imported lazily so the rest of the app doesn't need onnxruntime at import time.
        from piper import PiperVoice

        if self._voice is None:
            with self._voice_lock:
                # Re-checked under the lock: a thread that waited here while
                # another loaded must use that copy rather than load again.
                if self._voice is None:
                    self._voice = PiperVoice.load(str(self._voice_path))
        return self._voice

    def _synthesize_sync(self, text: str) -> bytes:
        voice = self._load_voice()
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wav_file:
            voice.synthesize_wav(text, wav_file)
        return buf.getvalue()

    async def synthesize(self, text: str, settings: TTSSettings) -> SynthesisResult:
        loop = asyncio.get_running_loop()
        audio_bytes = await loop.run_in_executor(self._worker_pool, self._synthesize_sync, text)
        return SynthesisResult(audio_bytes=audio_bytes, mime_type="audio/wav")

    async def list_voices(self) -> list[Voice]:
        # One bundled model; a second would mean shipping another ~60MB.
        return [Voice(id="en_US-lessac-medium", provider=self.name, name="Lessac (US English)", language="en")]
