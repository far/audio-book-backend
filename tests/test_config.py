"""Config reads the environment when a Settings is built, not when the
module is imported -- otherwise the defaults are frozen at import and
nothing can construct a differently-configured instance.
"""

from __future__ import annotations

import pytest

from app.api.config import Settings


def test_reads_the_environment_at_construction(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAX_UPLOAD_BYTES", "999")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "sk-test")

    settings = Settings()

    assert settings.max_upload_bytes == 999
    assert settings.elevenlabs_api_key == "sk-test"


def test_falls_back_to_defaults_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MAX_UPLOAD_BYTES", raising=False)
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)

    settings = Settings()

    assert settings.max_upload_bytes == 12 * 1024 * 1024
    assert settings.elevenlabs_api_key is None
    # Piper needs no key, so it is the only provider guaranteed present.
    assert settings.default_provider == "piper"
