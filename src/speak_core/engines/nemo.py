"""A local NeMo-Speech.cpp server, or any OpenAI-compatible /v1/audio/speech endpoint."""

import asyncio
import io
import logging
import tempfile
import uuid
import wave
from collections.abc import Callable
from pathlib import Path

import httpx2

from speak_core.engines.base import Engine, Utterance
from speak_core.engines.say import SayEngine
from speak_core.player import Player, resolve_player

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 15.0

# The speakers of the MagpieTTS model the plugin installs. Telemetry records these
# names as they are and any other voice - another model's, or another
# OpenAI-compatible server's - as `custom`, so a speaker added by a new model shows
# up as `custom` until it is listed here.
KNOWN_VOICES = ("John", "Sofia", "Aria", "Jason", "Leo")


def _wav_duration_ms(wav: bytes) -> int | None:
    """The audio's own length, read from the WAV header already in memory.

    Best-effort: a server that returns something other than a well-formed WAV
    still gets spoken, just without this one figure.
    """
    try:
        with wave.open(io.BytesIO(wav)) as handle:
            frames = handle.getnframes()
            rate = handle.getframerate()
    except (wave.Error, EOFError):
        return None
    return round(frames / rate * 1000) if rate > 0 else None


def _is_wav(body: bytes) -> bool:
    """Whether the body opens like a RIFF/WAVE file, which is all the player needs it to
    be; a JSON or HTML error page sent with a 200 does not."""
    return body[:4] == b"RIFF" and body[8:12] == b"WAVE"


class SynthesisFailed(RuntimeError):  # noqa: N818 - reads as what happened, like TranscriptionFailed
    """The speech server could not be reached, did not answer in time, or refused."""

    UNREACHABLE = "unreachable"
    TIMEOUT = "timeout"
    REFUSED = "refused"

    def __init__(self, message: str, *, kind: str) -> None:
        super().__init__(message)
        self.kind = kind


class NemoSynthesizer:
    """Text to WAV bytes over `/v1/audio/speech`, and the voices `/v1/models` reports.

    No fallback and no playback. A caller with somewhere else to send a sentence
    (`NemoEngine`, which speaks through `say`) decides that itself; one that must not
    change voice halfway (a voice-over file) gets the failure, with a `kind` it can
    turn into its own reason.
    """

    def __init__(
        self,
        *,
        base_url: str,
        client: httpx2.AsyncClient | None = None,
        api_key: str | None = None,
        model: str = "magpie",
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = client or httpx2.AsyncClient(timeout=timeout)
        self._model = model
        self._timeout = timeout
        self._headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}

    async def synthesize(self, text: str, *, voice: str | None) -> bytes:
        try:
            response = await self._client.post(
                f"{self._base_url}/v1/audio/speech",
                json={
                    "model": self._model,
                    "input": text,
                    "voice": voice,
                    "response_format": "wav",
                },
                headers=self._headers,
                timeout=self._timeout,
            )
            response.raise_for_status()
        except httpx2.TimeoutException as error:
            raise SynthesisFailed(
                f"the speech server did not answer within {self._timeout:g}s",
                kind=SynthesisFailed.TIMEOUT,
            ) from error
        except httpx2.HTTPStatusError as error:
            raise SynthesisFailed(
                f"the speech server refused the request: {error.response.status_code} "
                f"{error.response.text[:200]}",
                kind=SynthesisFailed.REFUSED,
            ) from error
        except (httpx2.HTTPError, OSError) as error:
            raise SynthesisFailed(
                f"could not reach the speech server: {error}", kind=SynthesisFailed.UNREACHABLE
            ) from error
        if not _is_wav(response.content):
            raise SynthesisFailed(
                "the speech server answered with something that is not a WAV: "
                f"{response.content[:80]!r}",
                kind=SynthesisFailed.REFUSED,
            )
        return response.content

    async def list_voices(self) -> list[str]:
        try:
            response = await self._client.get(
                f"{self._base_url}/v1/models", headers=self._headers, timeout=self._timeout
            )
            response.raise_for_status()
            body = response.json()
        except (httpx2.HTTPError, ValueError) as error:
            logger.warning("could not list speech server voices: %s", error)
            return []
        if not isinstance(body, dict):
            logger.warning("could not list speech server voices: the listing is not an object")
            return []
        models = body.get("data", [])
        if not isinstance(models, list):
            logger.warning("could not list speech server voices: the models are not a list")
            return []
        for model in models:
            if isinstance(model, dict) and model.get("capability") == "speech":
                voices = model.get("voices", [])
                return list(voices) if isinstance(voices, list) else []
        return []


class NemoEngine:
    """Synthesises to a WAV file and plays it.

    When the server cannot answer, the sentence is handed to the fallback engine
    instead of being lost, and `on_unavailable` is invoked so the server can be
    started for the next one.
    """

    name = "nemo"
    random_pool: tuple[str, ...] | None = None

    def __init__(
        self,
        *,
        base_url: str,
        client: httpx2.AsyncClient | None = None,
        api_key: str | None = None,
        model: str = "magpie",
        default_voice: str | None = "John",
        timeout: float = DEFAULT_TIMEOUT,
        fallback: Engine | None = None,
        on_unavailable: Callable[[], None] | None = None,
        player: Player | None = None,
    ) -> None:
        self._speech = NemoSynthesizer(
            base_url=base_url, client=client, api_key=api_key, model=model, timeout=timeout
        )
        self.default_voice = default_voice
        self._fallback = fallback or SayEngine()
        self._player = player if player is not None else resolve_player()
        self._on_unavailable = on_unavailable

    async def prepare(self, text: str, *, voice: str | None, rate: float | None) -> Utterance:
        try:
            audio = await self._speech.synthesize(text, voice=voice or self.default_voice)
        except SynthesisFailed as error:
            logger.warning("speech server unavailable, using say instead: %s", error)
            if self._on_unavailable is not None:
                self._on_unavailable()
            return await self._fallback.prepare(text, voice=None, rate=rate)

        if self._player is None:
            # Audio we cannot play is worse than no audio: the sentence would be
            # silently lost. The fallback speaks it instead.
            logger.warning("no sound player on this machine, using say instead")
            return await self._fallback.prepare(text, voice=None, rate=rate)

        path = Path(tempfile.gettempdir()) / f"speak-{uuid.uuid4().hex}.wav"
        await asyncio.to_thread(path.write_bytes, audio)

        async def cleanup() -> None:
            await asyncio.to_thread(path.unlink, True)

        command, args = self._player.command_for(str(path))
        return Utterance(
            command=command,
            args=args,
            cleanup=cleanup,
            audio_ms=_wav_duration_ms(audio),
            engine=self.name,
            voice=voice or self.default_voice,
        )

    async def list_voices(self) -> list[str]:
        return await self._speech.list_voices()
