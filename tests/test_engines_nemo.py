import io
import json
import wave
from pathlib import Path

import httpx2
import pytest

from speak_core.engines.nemo import PIECE_CHARS, PIECE_PAUSE_MS, NemoEngine, NemoSynthesizer
from speak_core.engines.say import SayEngine
from speak_core.player import Player

WAV = b"RIFF\x00\x00\x00\x00WAVEfmt "

MODELS = {
    "data": [
        {"id": "whisper", "capability": "transcription"},
        {"id": "magpie", "capability": "speech", "voices": ["John", "Sofia", "Aria"]},
    ]
}


# An explicit player, so these tests assert the same thing on every platform rather
# than whichever binary this machine happens to have.
PLAYER = Player("testplay", ("-q",))


def engine_over(handler, **kwargs: object) -> NemoEngine:
    client = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    kwargs.setdefault("player", PLAYER)
    return NemoEngine(base_url="http://127.0.0.1:8082", client=client, **kwargs)


def speech_ok(request: httpx2.Request) -> httpx2.Response:
    return httpx2.Response(200, content=WAV)


async def test_writes_the_wav_and_hands_it_to_the_resolved_player():
    utterance = await engine_over(speech_ok).prepare("hello", voice=None, rate=None)
    assert utterance.command == "testplay"
    written = Path(utterance.args[-1])
    assert utterance.args[:-1] == ["-q"]
    assert written.read_bytes() == WAV
    assert written.suffix == ".wav"
    await utterance.cleanup()


async def test_a_machine_with_no_player_speaks_through_the_fallback(monkeypatch):
    """Audio that cannot be played is worse than no audio: the sentence would go
    missing silently, where the fallback at least says it."""
    monkeypatch.setattr("speak_core.engines.nemo.resolve_player", lambda: None)
    engine = engine_over(speech_ok, player=None)
    utterance = await engine.prepare("hello", voice=None, rate=None)
    assert utterance.command == "say"


async def test_cleanup_removes_the_temporary_file():
    utterance = await engine_over(speech_ok).prepare("hello", voice=None, rate=None)
    written = Path(utterance.args[0])
    await utterance.cleanup()
    assert not written.exists()


async def test_cleanup_is_safe_to_run_twice():
    utterance = await engine_over(speech_ok).prepare("hello", voice=None, rate=None)
    await utterance.cleanup()
    await utterance.cleanup()


async def test_sends_the_configured_model_and_the_default_voice():
    seen: list[dict] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(json.loads(request.content))
        return httpx2.Response(200, content=WAV)

    engine = engine_over(handler, model="magpie", default_voice="John")
    utterance = await engine.prepare("hello", voice=None, rate=None)
    await utterance.cleanup()

    assert seen[0]["model"] == "magpie"
    assert seen[0]["voice"] == "John"
    assert seen[0]["input"] == "hello"
    assert seen[0]["response_format"] == "wav"


async def test_a_dates_comma_before_its_year_never_reaches_the_server():
    """Its text normalization says "sil" there; voice-overs use the synthesizer directly."""
    seen: list[str] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(json.loads(request.content)["input"])
        return httpx2.Response(200, content=WAV)

    synthesizer = NemoSynthesizer(
        base_url="http://speech", client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    )
    await synthesizer.synthesize("Due Oct. 8, 2026, at noon.", voice=None)

    assert seen == ["Due Oct. 8 2026, at noon."]


async def test_an_explicit_voice_overrides_the_default():
    seen: list[dict] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(json.loads(request.content))
        return httpx2.Response(200, content=WAV)

    utterance = await engine_over(handler, default_voice="John").prepare(
        "hello", voice="Sofia", rate=None
    )
    await utterance.cleanup()
    assert seen[0]["voice"] == "Sofia"


async def test_sends_the_api_key_as_a_bearer_token():
    seen: list[str | None] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request.headers.get("authorization"))
        return httpx2.Response(200, content=WAV)

    utterance = await engine_over(handler, api_key="secret").prepare("hello", voice=None, rate=None)
    await utterance.cleanup()
    assert seen == ["Bearer secret"]


async def test_falls_back_to_say_when_the_server_errors():
    notified: list[bool] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(503)

    engine = engine_over(
        handler, fallback=SayEngine(), on_unavailable=lambda: notified.append(True)
    )
    utterance = await engine.prepare("hello", voice=None, rate=None)

    assert utterance.command == "say"
    assert utterance.args == ["hello"]
    assert notified == [True]


async def test_falls_back_to_say_when_the_server_is_unreachable():
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("connection refused")

    engine = engine_over(handler, fallback=SayEngine())
    utterance = await engine.prepare("hello", voice=None, rate=None)
    assert utterance.command == "say"


async def test_the_fallback_keeps_the_rate_but_drops_the_neural_voice():
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("connection refused")

    engine = engine_over(handler, fallback=SayEngine(), default_voice="John")
    utterance = await engine.prepare("hello", voice=None, rate=190)
    assert utterance.args == ["-r", "190", "hello"]


async def test_lists_the_voices_of_the_speech_capable_model():
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json=MODELS)

    assert await engine_over(handler).list_voices() == ["John", "Sofia", "Aria"]


async def test_lists_no_voices_when_the_server_is_unreachable():
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("connection refused")

    assert await engine_over(handler).list_voices() == []


async def test_lists_no_voices_when_no_model_reports_speech():
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json={"data": [{"id": "whisper", "capability": "x"}]})

    assert await engine_over(handler).list_voices() == []


async def test_trailing_slash_in_the_base_url_does_not_double_up():
    seen: list[str] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(str(request.url))
        return httpx2.Response(200, content=WAV)

    client = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    engine = NemoEngine(base_url="http://127.0.0.1:8082/", client=client, player=PLAYER)
    utterance = await engine.prepare("hello", voice=None, rate=None)
    await utterance.cleanup()
    assert seen == ["http://127.0.0.1:8082/v1/audio/speech"]


async def test_an_utterance_reports_the_engine_and_the_voice_that_spoke_it():
    utterance = await engine_over(speech_ok, default_voice="John").prepare(
        "hello", voice=None, rate=None
    )
    await utterance.cleanup()
    assert (utterance.engine, utterance.voice) == ("nemo", "John")


async def test_a_fallback_utterance_reports_say_and_no_voice():
    """The fallback drops the neural voice, so the row it becomes must name `say`
    with its default voice, not the nemo speaker that was asked for."""

    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("connection refused")

    engine = engine_over(handler, fallback=SayEngine(), default_voice="John")
    utterance = await engine.prepare("hello", voice="Sofia", rate=None)
    assert (utterance.engine, utterance.voice) == ("say", None)


async def test_falls_back_to_say_when_the_server_times_out():
    """A server that takes the request and never answers would otherwise hold the
    sentence for the whole timeout and then lose it; it is spoken by `say` instead, and
    the supervisor is told, like any other failure to reach the server."""
    notified: list[bool] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ReadTimeout("slow", request=request)

    engine = engine_over(
        handler, fallback=SayEngine(), on_unavailable=lambda: notified.append(True)
    )
    utterance = await engine.prepare("hello", voice=None, rate=None)

    assert (utterance.command, utterance.args) == ("say", ["hello"])
    assert notified == [True]


async def test_falls_back_to_say_when_the_server_answers_with_something_that_is_not_audio():
    """A 200 carrying an error page or JSON is not a sound; handed to the player it
    would be silence, so the sentence is spoken by `say` and the supervisor is told."""
    notified: list[bool] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json={"error": "model not loaded"})

    engine = engine_over(
        handler, fallback=SayEngine(), on_unavailable=lambda: notified.append(True)
    )
    utterance = await engine.prepare("hello", voice=None, rate=None)

    assert (utterance.command, utterance.args) == ("say", ["hello"])
    assert notified == [True]


@pytest.mark.parametrize(
    "body",
    [
        {"data": None},
        {"data": "models"},
        {"data": ["whisper", 3, None]},
        {"data": [{"capability": "speech", "voices": None}]},
        {"data": [{"capability": "speech", "voices": 7}]},
    ],
)
async def test_lists_no_voices_when_the_listing_has_an_unexpected_shape(body):
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json=body)

    assert await engine_over(handler).list_voices() == []


async def test_skips_entries_that_are_not_objects_when_listing_voices():
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json={"data": ["junk", *MODELS["data"]]})

    assert await engine_over(handler).list_voices() == ["John", "Sofia", "Aria"]


async def test_lists_only_the_voices_that_are_names():
    def handler(request: httpx2.Request) -> httpx2.Response:
        listing = {"data": [{"capability": "speech", "voices": ["John", 7, None, {}, "Aria"]}]}
        return httpx2.Response(200, json=listing)

    assert await engine_over(handler).list_voices() == ["John", "Aria"]


def pcm_wav(frames: int, *, rate: int = 22050, value: int = 1) -> bytes:
    out = io.BytesIO()
    with wave.open(out, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(value.to_bytes(2, "little") * frames)
    return out.getvalue()


# Three sentences of about 100 characters, so the text is past PIECE_CHARS but each
# sentence fits in it.
SENTENCES = [
    f"Sentence number {n} carries enough words to be a real one, " + "and more " * 4 + "here."
    for n in range(3)
]
LONG = " ".join(SENTENCES)


def recording(seen: list[str], *, frames: int = 100):
    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(json.loads(request.content)["input"])
        return httpx2.Response(200, content=pcm_wav(frames, value=len(seen)))

    return handler


async def test_a_text_that_is_one_piece_is_sent_as_it_is():
    seen: list[str] = []
    utterance = await engine_over(recording(seen)).prepare("One. Two words", voice=None, rate=None)
    await utterance.cleanup()
    assert seen == ["One. Two words"]


async def test_each_sentence_of_a_text_is_its_own_request():
    """MagpieTTS repeats and garbles words when one request holds several sentences."""
    seen: list[str] = []
    utterance = await engine_over(recording(seen)).prepare(
        "First one here. Second one here.", voice=None, rate=None
    )
    await utterance.cleanup()
    assert seen == ["First one here.", "Second one here."]


async def test_a_sentence_past_the_piece_size_goes_a_clause_at_a_time_each_closed():
    seen: list[str] = []
    clause = "a clause long enough to count for something real"
    sentence = ", ".join([clause] * 8) + "."
    assert len(sentence) > PIECE_CHARS
    utterance = await engine_over(recording(seen)).prepare(sentence, voice=None, rate=None)
    await utterance.cleanup()

    assert len(seen) > 1
    assert all(len(piece) <= PIECE_CHARS for piece in seen)
    assert all(piece.endswith(".") for piece in seen)
    assert " ".join(seen).replace(".", ",").rstrip(",") == sentence.rstrip(".")


async def test_the_pieces_audio_is_joined_in_order_with_a_pause_between_each_two():
    seen: list[str] = []
    utterance = await engine_over(recording(seen)).prepare(LONG, voice=None, rate=None)
    written = Path(utterance.args[-1]).read_bytes()
    await utterance.cleanup()

    pause = 22050 * PIECE_PAUSE_MS // 1000
    with wave.open(io.BytesIO(written)) as handle:
        assert (handle.getnchannels(), handle.getsampwidth(), handle.getframerate()) == (
            1,
            2,
            22050,
        )
        frames = handle.readframes(handle.getnframes())
    silence = b"\0\0" * pause
    assert frames == silence.join(
        (n).to_bytes(2, "little") * 100 for n in range(1, len(SENTENCES) + 1)
    )
    assert utterance.audio_ms == round((3 * 100 + 2 * pause) / 22050 * 1000)


async def test_a_piece_the_server_fails_sends_the_whole_text_to_the_fallback():
    """Half a sentence in the neural voice and half in `say` would be worse than all of
    it in `say`."""
    notified: list[bool] = []
    seen: list[str] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(json.loads(request.content)["input"])
        return httpx2.Response(503) if len(seen) == 2 else httpx2.Response(200, content=pcm_wav(10))

    engine = engine_over(
        handler, fallback=SayEngine(), on_unavailable=lambda: notified.append(True)
    )
    utterance = await engine.prepare(LONG, voice=None, rate=None)

    assert (utterance.command, utterance.args) == ("say", [LONG])
    assert len(seen) == 2
    assert notified == [True]


@pytest.mark.parametrize(
    "second",
    [pcm_wav(10, rate=16000), b"RIFF\x00\x00\x00\x00WAVEnot really"],
    ids=["another rate", "not pcm"],
)
async def test_pieces_that_cannot_be_joined_send_the_text_to_the_fallback(second):
    answers = iter([pcm_wav(10), second, pcm_wav(10)])

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, content=next(answers))

    utterance = await engine_over(handler, fallback=SayEngine()).prepare(
        LONG, voice=None, rate=None
    )
    assert (utterance.command, utterance.args) == ("say", [LONG])


async def test_audio_that_cannot_be_written_back_sends_the_text_to_the_fallback(monkeypatch):
    def refuse(self, params) -> None:
        raise wave.Error("cannot write compressed Wave files")

    monkeypatch.setattr(wave.Wave_write, "setparams", refuse)

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, content=pcm_wav(10))

    utterance = await engine_over(handler, fallback=SayEngine()).prepare(
        LONG, voice=None, rate=None
    )
    assert (utterance.command, utterance.args) == ("say", [LONG])


async def test_the_pause_between_8_bit_pieces_is_silence_not_the_loudest_sample():
    """8-bit WAV samples are unsigned: 0x80 is silence, and 0x00 the bottom of the wave."""

    def eight_bit(request: httpx2.Request) -> httpx2.Response:
        out = io.BytesIO()
        with wave.open(out, "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(1)
            handle.setframerate(8000)
            handle.writeframes(b"\x90" * 10)
        return httpx2.Response(200, content=out.getvalue())

    utterance = await engine_over(eight_bit).prepare(LONG, voice=None, rate=None)
    written = Path(utterance.args[-1]).read_bytes()
    await utterance.cleanup()
    with wave.open(io.BytesIO(written)) as handle:
        frames = handle.readframes(handle.getnframes())
    pause = b"\x80" * (8000 * PIECE_PAUSE_MS // 1000)
    assert frames == pause.join([b"\x90" * 10] * len(SENTENCES))
