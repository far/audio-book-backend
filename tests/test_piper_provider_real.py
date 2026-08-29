"""Exercises real Piper synthesis + ffmpeg Opus transcoding -- the one test
that doesn't use FakeTTSProvider. Skipped if the voice model isn't present
(it's gitignored -- see backend/README.md for the download command) so the
rest of the suite stays fast and doesn't require a multi-hundred-MB model
download to run.
"""

from __future__ import annotations

import shutil
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.api.config import settings
from app.api.deps import get_worker_pool
from app.domain.entities import TTSSettings
from app.infrastructure.tts.encoding import EncodingTTSProvider
from app.infrastructure.tts.piper_provider import PiperProvider

pytestmark = pytest.mark.skipif(
    not settings.voice_path.exists(), reason="voice model not downloaded -- see backend/README.md"
)


async def test_piper_synthesizes_audible_bytes() -> None:
    provider = PiperProvider(settings.voice_path, get_worker_pool())
    result = await provider.synthesize("This is a real synthesis test.", TTSSettings(provider="piper", voice_id="v"))

    assert result.mime_type == "audio/wav"
    assert len(result.audio_bytes) > 1000  # a real WAV, not an empty/error response


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
async def test_piper_output_transcodes_to_opus() -> None:
    piper = PiperProvider(settings.voice_path, get_worker_pool())
    encoding = EncodingTTSProvider(piper, get_worker_pool())

    result = await encoding.synthesize("Opus transcoding test.", TTSSettings(provider="piper", voice_id="v"))

    assert result.mime_type == "audio/ogg; codecs=opus"
    assert len(result.audio_bytes) > 0


def test_concurrent_first_synthesis_loads_the_model_once() -> None:
    """The model is ~150MB resident, so a double load is a ~300MB spike --
    enough to be OOM-killed on a small host for a copy that is then thrown
    away. Both threads must end up with the same object."""
    provider = PiperProvider(settings.voice_path, get_worker_pool())
    barrier = threading.Barrier(4)

    def load() -> object:
        barrier.wait()  # maximise the odds of a real race
        return provider._load_voice()

    with ThreadPoolExecutor(max_workers=4) as pool:
        voices = [f.result() for f in [pool.submit(load) for _ in range(4)]]

    assert all(v is voices[0] for v in voices)
