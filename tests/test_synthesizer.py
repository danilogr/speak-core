"""A synthesis call with no fallback: a voice-over that silently changes voice halfway
is worse than an error, so every failure is raised with a kind the caller can act on."""

import json

import httpx2
import pytest

from speak_core.engines.nemo import NemoSynthesizer, SynthesisFailed

WAV = b"RIFF\x00\x00\x00\x00WAVEfmt "


def synthesizer(handler, **kwargs: object) -> NemoSynthesizer:
    client = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    return NemoSynthesizer(base_url="http://127.0.0.1:8082/", client=client, **kwargs)


async def test_returns_the_wav_and_sends_model_voice_and_key():
    seen = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, content=WAV)

    audio = await synthesizer(handler, model="magpie", api_key="k").synthesize("hi", voice="Sofia")

    assert audio == WAV
    (request,) = seen
    assert str(request.url) == "http://127.0.0.1:8082/v1/audio/speech"
    assert json.loads(request.content) == {
        "model": "magpie",
        "input": "hi",
        "voice": "Sofia",
        "response_format": "wav",
    }
    assert request.headers["authorization"] == "Bearer k"


async def test_a_refusal_is_raised_with_its_status_never_spoken_by_say():
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(400, text="unknown voice")

    with pytest.raises(SynthesisFailed) as raised:
        await synthesizer(handler).synthesize("hi", voice="Nobody")
    assert raised.value.kind == SynthesisFailed.REFUSED
    assert "400" in str(raised.value)


async def test_a_timeout_is_its_own_kind():
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ReadTimeout("slow", request=request)

    with pytest.raises(SynthesisFailed) as raised:
        await synthesizer(handler, timeout=7).synthesize("hi", voice="John")
    assert raised.value.kind == SynthesisFailed.TIMEOUT
    assert "7s" in str(raised.value)


async def test_an_unreachable_server_is_its_own_kind():
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("refused", request=request)

    with pytest.raises(SynthesisFailed) as raised:
        await synthesizer(handler).synthesize("hi", voice="John")
    assert raised.value.kind == SynthesisFailed.UNREACHABLE


async def test_the_per_request_timeout_is_sent_with_the_request():
    timeouts = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        timeouts.append(request.extensions["timeout"])
        return httpx2.Response(200, content=WAV)

    await synthesizer(handler, timeout=90.0).synthesize("hi", voice="John")
    assert timeouts[0]["read"] == 90.0


async def test_lists_the_speech_models_voices_and_nothing_on_failure():
    def models(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200, json={"data": [{"capability": "speech", "voices": ["John", "Aria"]}]}
        )

    def down(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("refused", request=request)

    assert await synthesizer(models).list_voices() == ["John", "Aria"]
    assert await synthesizer(down).list_voices() == []


async def test_a_200_that_is_not_a_wav_is_a_refusal_not_audio():
    """An error page or JSON body on a 200 would otherwise be written out and played as
    silence, and a voice-over file would be a file of JSON."""

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json={"error": "model not loaded"})

    with pytest.raises(SynthesisFailed) as raised:
        await synthesizer(handler).synthesize("hi", voice="John")
    assert raised.value.kind == SynthesisFailed.REFUSED
    assert "not a WAV" in str(raised.value)


async def test_a_models_listing_that_is_not_an_object_lists_no_voices():
    def array(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json=["magpie"])

    def scalar(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json="ok")

    assert await synthesizer(array).list_voices() == []
    assert await synthesizer(scalar).list_voices() == []
