# AI Reader backend

FastAPI service that turns an uploaded EPUB into a readable document plus synthesized speech.

See [../spec/plan.md](../spec/plan.md) for decisions and ADRs, [../CLAUDE.md](../CLAUDE.md) for conventions, [../README.md](../README.md) for the Flutter client.

## Setup

Python 3.13 and [`uv`](https://docs.astral.sh/uv/).

```bash
cd backend
uv sync

# Piper voice — gitignored, ~60MB
mkdir -p voices
uv run python -m piper.download_voices en_US-lessac-medium --data-dir voices
```

`ffmpeg` must be on `PATH` for Opus transcoding.

## Run

```bash
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Bind `0.0.0.0`, not `127.0.0.1`, or a device on the LAN can't reach it.

> **Restarting ends every open session.** Sessions are in-memory with no persistence, so clients' chunk fetches start 404ing and the book must be re-uploaded. You cannot hot-restart mid-listen.

## Pipeline

```
POST /upload  →  EbooklibParser  →  Book(Chapter[], Chunk[])  →  InMemorySessionStore
                      └─ spine order → blocks + chunks

GET /tts/chunk/{id}  →  audio, synthesized on demand and cached
```

All HTTP. A WebSocket control plane used to warm the cache ahead of the playhead; it was removed once the player's own read-ahead proved to cover it, and it had caused most of this project's hard bugs ([ADR-1](../spec/plan.md#architecture-decision-records)). No per-client connection state, and seeking anywhere is free.

### Parsing

Documents are walked in **spine order** — `get_items_of_type()` returns manifest order, which routinely differs and once shuffled the contents list.

Each chapter becomes ordered blocks plus the chunks that voice them:

| Block | Rendered | Voiced |
| --- | --- | --- |
| `TextBlock` | its segments, in order | segments carrying a chunk ID |
| `HeadingBlock` | at heading weight | yes |
| `ImageBlock` | client-side, from its copy of the EPUB | no |
| `CodeBlock` | verbatim | no |

**Shown and voiced are separate.** A `TextBlock` is a sequence of `Segment`s — text plus the chunk that voices it, *or `None`*. Ask `chunk_ids_of(block)`, don't test the block's type.

Prose is detected by **shape, not a dictionary** (`parsers/text_quality.py`): mostly alphabetic tokens, few operators, vowels where words have vowels. A lexicon would need per-language word lists and would still reject proper nouns. Thresholds are permissive — skipping a wanted sentence is worse than voicing an awkward one.

**Images are never stored here.** The upload already contains them, so the client reads them from its own copy. `ImageBlock.src` is archive-root relative, resolved against the chapter document by the parser.

### Chunking

Sentence-level, per block, so a paragraph break is a hard boundary and the highlight stays in the paragraph being read. The first chunk of the first paragraph is a single sentence for fast first audio ([ADR-3](../spec/plan.md#architecture-decision-records)); later chunks group three.

## TTS providers

One narrow port:

```python
class TTSProvider(ABC):
    name: str
    async def synthesize(self, text: str, settings: TTSSettings) -> SynthesisResult: ...
    async def list_voices(self) -> list[Voice]: ...
```

Adding a provider is **one adapter file + one line in `deps.py`**.

### Decorators

Applied identically to every provider in `_build_provider`, so cross-cutting work is written once:

```
Caching( Encoding( provider ) )
   │        └─ ffmpeg → Ogg Opus, so the client handles one codec
   └─────────── sha256(provider:voice:text) → filesystem cache
```

Caching sits **outside** encoding, so a hit costs neither an API call nor a transcode. Speed is not in the key — it's applied client-side, so changing it never re-synthesizes ([ADR-3](../spec/plan.md#architecture-decision-records)).

There was a retry decorator. Removed: Piper is the default and its failures are deterministic, so retrying never helped the common case, and a failed chunk isn't fatal — the reader taps again.

### Registered providers

| Provider | `name` | Native output | Requires |
| --- | --- | --- | --- |
| Piper | `piper` | WAV | nothing — offline |
| ElevenLabs | `elevenlabs` | MP3 | `ELEVENLABS_API_KEY` |
| OpenAI TTS | `openai` | MP3 | `OPENAI_API_KEY` |

A provider is registered **only when its key is set**, so `/tts/providers` never offers one that would fail, and the client's picker is built from that response.

## ElevenLabs

Adapter: `app/infrastructure/tts/elevenlabs_provider.py`, ~70 lines — the decorators handle everything cross-cutting.

### Enable

```bash
export ELEVENLABS_API_KEY=sk_...
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
curl localhost:8000/tts/providers   # confirm it registered
```

The app builds one `Settings` at import, so **restart after changing the environment**. A key present costs nothing by itself: selection is per request and defaults to Piper.

### Request

```
POST https://api.elevenlabs.io/v1/text-to-speech/{voice_id}?output_format=mp3_44100_128
  xi-api-key: <key>
  {"text": "...", "model_id": "eleven_multilingual_v2"}
→ MP3, 30s timeout
```

`model_id` and `output_format` are pinned rather than left to API defaults, which are theirs to change. Non-200 raises `ProviderError` with the status and first 200 bytes of the body.

### Voices

`list_voices()` calls `GET /v1/voices` and returns voices with their **names** — the picker can't offer `21m00Tcm4TlvDq8ikWAM` as a choice. Fetched once per process; only successes are cached, so a corrected key takes effect without a restart. Any failure falls back to one stock voice, because `/tts/providers` lists every provider and one bad key must not break it for the rest.

### Cost

- **`MAX_CHARACTERS_PER_SESSION`** (500k) bounds spend per upload. Over-budget books are **truncated, not rejected** — the overflow stays readable but unvoiced.
- **The cache is the main saving.** Keyed on content, shared across sessions, survives restarts (`tmp/audio_cache`, 500MB LRU). Re-reading a chapter or changing speed costs nothing.
- **The player reads ahead**, so audio is paid for slightly before it's heard. Skipping around can pay for chunks never played.

### Gaps

- **No streaming** — latency is the full synthesis time. Their streaming endpoint (and its character timings, [ADR-2](../spec/plan.md#architecture-decision-records)) is unused.
- **MP3, then transcoded.** They can return `opus_48000_*` directly, skipping ffmpeg (~67ms CPU/chunk). Not taken: the docs don't say whether that Opus is Ogg-contained, and serving raw Opus as `audio/ogg` is the exact bug that made Safari refuse chunks once. Verify against a real key first.

## Configuration

| Env var | Default | Purpose |
| --- | --- | --- |
| `ELEVENLABS_API_KEY` | unset | Registers ElevenLabs when set |
| `OPENAI_API_KEY` | unset | Registers OpenAI when set |
| `DEFAULT_TTS_PROVIDER` | `piper` | Used when a request omits `provider` |
| `DEFAULT_TTS_VOICE_ID` | `en_US-lessac-medium` | Used when a request omits `voice_id` |
| `MAX_UPLOAD_BYTES` | 12MB | Bounds RAM as much as bandwidth — parsing peaks at ~18× the compressed file |
| `MAX_EPUB_UNCOMPRESSED_BYTES` | 200MB | Zip-bomb guard, checked before parsing |
| `MAX_CHARACTERS_PER_SESSION` | 500,000 | Synthesis budget; over-budget books are truncated |
| `SESSION_TTL_SECONDS` | 7200 | How long an *untouched* session is kept. Fetching a chunk counts, so an active listener never expires |
| `SYNTHESIS_WORKER_POOL_SIZE` | 1 | Threads shared by Piper and ffmpeg. Sized for one vCPU |

No auth, no TLS. Don't expose beyond a LAN or a disposable host.

## API

Self-documenting at `/docs`, or `/openapi.json`.

| Endpoint | Purpose |
| --- | --- |
| `POST /upload` | EPUB → parsed `Book`. Non-EPUBs get 422 |
| `GET /session/{book_id}` | Re-fetch a parsed book |
| `GET /tts/chunk/{chunk_id}` | Audio for one chunk. `?provider=&voice_id=` optional. Returns `audio/ogg; codecs=opus` |
| `GET /tts/providers` | Registered providers and their voices |

## Testing

```bash
uv run pytest              # fakes only, no model or network
uv run mypy --strict app/
uv run ruff check app/
```

`tests/test_piper_provider_real.py` uses real Piper and ffmpeg; it skips itself if either is missing.

### Inspecting a book

```bash
uv run python -m tools.inspect_book /path/to/book.epub
```

Prints each chapter's blocks, its first chunks **with their text**, and resolves every image `src` against the archive exactly as the client does — separating a parsing problem from a lookup problem in one run. Also reports duplicate chapter IDs.

## Small hosts

Measured at 1GB / 1 vCPU. Piper is the memory floor:

| Stage | RSS |
| --- | --- |
| Python baseline | 17 MB |
| `+ onnxruntime` | 43 MB |
| `+ voice loaded` | 190 MB |
| `+ one synthesis` | 259 MB |

A 60MB `.onnx` expands to ~150MB resident and is kept warm deliberately. Budget ~400MB at rest: **1GB works, 512MB does not.**

- **`MAX_UPLOAD_BYTES` bounds RAM.** Parsing peaks at ~18× the compressed file, so 12MB is already ~200MB of peak.
- **Mount `tmp/` on a volume.** ffmpeg alone is ~67ms CPU per chunk — ~9 minutes for an 8,000-chunk book.
- **Sessions hold ~5MB per 0.3MB book.** Nothing signals a reader is done, so memory is reclaimed by `SESSION_TTL_SECONDS`.

## Docker

```bash
docker build -t aireader-backend .
docker run -p 8000:8000 \
  -e ELEVENLABS_API_KEY=sk_... \
  -v $(pwd)/voices:/app/voices -v $(pwd)/tmp:/app/tmp aireader-backend
```

Mount `tmp/` or every restart re-synthesizes from scratch — on a paid provider, that means paying twice.
