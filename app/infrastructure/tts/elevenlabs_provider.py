"""ElevenLabs adapter. Paid API -- registered only when its API key is
configured (see api/deps.py), so it is absent rather than broken when it
isn't set up.
"""

from __future__ import annotations

import httpx

from app.application.ports import SynthesisResult, TTSProvider
from app.domain.entities import TTSSettings, Voice
from app.domain.errors import ProviderError

_API_BASE = "https://api.elevenlabs.io/v1"

# Used when the voice list can't be fetched. "Rachel", ElevenLabs' stock
# default -- a picker with one usable entry beats an empty one, and a bad
# key shouldn't take down /tts/providers for the other providers.
_FALLBACK_VOICE_ID = "21m00Tcm4TlvDq8ikWAM"

# The API's own default model, named explicitly so an upstream change of
# default can't silently change how the book sounds mid-book.
_MODEL_ID = "eleven_multilingual_v2"

# ElevenLabs also offers opus_48000_* directly, which would let us skip the
# ffmpeg transcode entirely (~67ms of CPU per chunk). Not taken: their docs
# don't state whether that Opus is Ogg-contained, and shipping raw Opus as
# audio/ogg is precisely the bug that made Safari refuse chunks once
# already. Verify the container against a real key before switching.
_OUTPUT_FORMAT = "mp3_44100_128"


class ElevenLabsProvider(TTSProvider):
    name = "elevenlabs"

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key
        self._voices: list[Voice] | None = None

    async def synthesize(self, text: str, settings: TTSSettings) -> SynthesisResult:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{_API_BASE}/text-to-speech/{settings.voice_id}",
                headers={"xi-api-key": self._api_key},
                # Pinned rather than left to the API default, which is
                # documented as mp3_44100_128 but is theirs to change.
                # EncodingTTSProvider transcodes it to Opus regardless, so
                # a silent change of default would be a silent change of
                # what we feed ffmpeg.
                params={"output_format": _OUTPUT_FORMAT},
                json={"text": text, "model_id": _MODEL_ID},
            )
        if response.status_code != 200:
            raise ProviderError(provider=self.name, reason=f"HTTP {response.status_code}: {response.text[:200]}")
        return SynthesisResult(audio_bytes=response.content, mime_type="audio/mpeg")

    async def list_voices(self) -> list[Voice]:
        """The account's voices, fetched once and kept.

        Cached because the list is stable for a session and this is called
        on every `/tts/providers` request; only successes are cached, so a
        key fixed after a failed attempt takes effect without a restart.
        """
        if self._voices is None:
            fetched = await self._fetch_voices()
            if fetched is None:
                return [Voice(id=_FALLBACK_VOICE_ID, provider=self.name, name="Rachel", language="en")]
            self._voices = fetched
        return self._voices

    async def _fetch_voices(self) -> list[Voice] | None:
        """None on any failure -- listing voices is a convenience, and it
        must not take down the endpoint for the other providers."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(f"{_API_BASE}/voices", headers={"xi-api-key": self._api_key})
            if response.status_code != 200:
                return None
            voices = response.json().get("voices", [])
        except Exception:  # noqa: BLE001 -- network, JSON, or schema drift all mean "no list"
            return None

        return [
            Voice(
                id=voice["voice_id"],
                provider=self.name,
                name=voice.get("name", ""),
                language=(voice.get("labels") or {}).get("language", "en"),
            )
            for voice in voices
            if voice.get("voice_id")
        ]
