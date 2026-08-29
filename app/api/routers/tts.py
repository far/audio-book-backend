from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from app.api.config import settings
from app.api.deps import get_provider_registry, get_session_store
from app.application.ports import SessionStore
from app.application.result import Err
from app.application.use_cases import SynthesizeChunk
from app.domain.entities import TTSSettings
from app.domain.errors import ChunkNotFoundError, ProviderError
from app.infrastructure.tts.encoding import OGG_OPUS_MIME_TYPE
from app.infrastructure.tts.registry import ProviderRegistry

router = APIRouter()

class VoiceDTO(BaseModel):
    id: str
    name: str


class ProviderInfoDTO(BaseModel):
    name: str
    voices: list[VoiceDTO]


@router.get("/tts/providers", response_model=list[ProviderInfoDTO])
async def list_providers(registry: ProviderRegistry = Depends(get_provider_registry)) -> list[ProviderInfoDTO]:
    """Providers that are actually usable right now.

    Only what the composition root registered, so a provider whose API key
    is unset is simply absent. The client builds its picker from this, so
    an unconfigured provider can't be chosen and then fail.
    """
    providers = []
    for name in registry.list_names():
        voices = await registry.get(name).list_voices()
        providers.append(
            ProviderInfoDTO(name=name, voices=[VoiceDTO(id=v.id, name=v.label) for v in voices])
        )
    return providers


@router.get("/tts/chunk/{chunk_id}")
async def get_chunk_audio(
    chunk_id: str,
    provider: str | None = None,
    voice_id: str | None = None,
    registry: ProviderRegistry = Depends(get_provider_registry),
    session_store: SessionStore = Depends(get_session_store),
) -> Response:
    # Falls back to the configured defaults so a bare URL still works from
    # a browser or curl; the app always sends both explicitly. Named
    # `tts_settings` because `settings` is this module's config import --
    # shadowing it left an AttributeError waiting for whoever next needed
    # config in this handler.
    tts_settings = TTSSettings(
        provider=provider or settings.default_provider,
        voice_id=voice_id or settings.default_voice_id,
    )

    try:
        tts_provider = registry.get(tts_settings.provider)
    except ProviderError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    use_case = SynthesizeChunk(provider=tts_provider, session_store=session_store)
    result = await use_case.execute(chunk_id, tts_settings)

    if isinstance(result, Err):
        error = result.error
        if isinstance(error, ChunkNotFoundError):
            raise HTTPException(status_code=404, detail="unknown chunk_id")
        raise HTTPException(status_code=502, detail=f"synthesis failed: {error.reason}")

    return Response(content=result.unwrap(), media_type=OGG_OPUS_MIME_TYPE)
