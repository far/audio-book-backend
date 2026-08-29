"""EncodingTTSProvider: transcodes every provider's output to Opus (plan.md
Milestone 3.3) so the Flutter side only ever handles one codec, regardless
of whether the underlying provider returned WAV (Piper) or MP3
(ElevenLabs/OpenAI). Transcoding is blocking CPU work, so it runs through
the same thread/process pool as Piper inference -- never inline.
"""

from __future__ import annotations

import asyncio
import subprocess
from concurrent.futures import ThreadPoolExecutor

from app.application.ports import SynthesisResult, TTSProvider
from app.domain.entities import TTSSettings, Voice
from app.domain.errors import ProviderError

# ffmpeg's `-f opus` writes Opus in an Ogg container, so the correct type is
# audio/ogg. Reporting the bare "audio/opus" (which means raw Opus) makes
# Safari and iOS refuse to decode the response outright.
OGG_OPUS_MIME_TYPE = "audio/ogg; codecs=opus"


def _transcode_to_opus_sync(audio_bytes: bytes) -> bytes:
    proc = subprocess.run(
        # 24k mono is transparent for speech and measured 26% smaller than
        # 32k (14.6KB -> 10.8KB per chunk) at no CPU cost -- worth it on a
        # host billed for egress. `-f wav` skips input probing; Piper always
        # emits mono 22050Hz.
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            "-f", "wav", "-i", "pipe:0",
            "-c:a", "libopus", "-b:a", "24k", "-ac", "1", "-application", "voip",
            "-f", "opus", "pipe:1",
        ],
        input=audio_bytes,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg transcode failed: {proc.stderr.decode(errors='replace')[:300]}")
    return proc.stdout


class EncodingTTSProvider(TTSProvider):
    def __init__(self, wrapped: TTSProvider, worker_pool: ThreadPoolExecutor) -> None:
        self._wrapped = wrapped
        self._worker_pool = worker_pool
        self.name = wrapped.name

    async def synthesize(self, text: str, settings: TTSSettings) -> SynthesisResult:
        result = await self._wrapped.synthesize(text, settings)
        loop = asyncio.get_running_loop()
        try:
            opus_bytes = await loop.run_in_executor(self._worker_pool, _transcode_to_opus_sync, result.audio_bytes)
        except RuntimeError as exc:
            raise ProviderError(provider=self._wrapped.name, reason=str(exc)) from exc
        return SynthesisResult(audio_bytes=opus_bytes, mime_type=OGG_OPUS_MIME_TYPE)

    async def list_voices(self) -> list[Voice]:
        return await self._wrapped.list_voices()
