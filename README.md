# speak-core

The shared speech engine under the **voicebox** and **walkie** plugins. Runs entirely
on your machine, powered by [NVIDIA NeMo-Speech.cpp](https://github.com/NVIDIA/NeMo-Speech.cpp):
MagpieTTS for speech, Nemotron 3.5 for recognition.

It is a library, not a plugin: no MCP server, no tools, no commands. A plugin depends
on it by git tag:

    speak-core @ git+https://github.com/danilogr/speak-core@v0.4.0

## What it provides

| Module | What it does |
|---|---|
| `engines` | Speech engines (`say`, `nemo`, `command`), the no-fallback `NemoSynthesizer` for writing audio files, and the transcription client |
| `supervisor`, `runtime` | One NeMo-Speech.cpp server per machine, shared by every plugin and session |
| `queue`, `player`, `text`, `speaker` | Ordered playback, one utterance at a time across every process |
| `exclusive` | One holder at a time across processes |
| `config` | Shared server settings and per-plugin voice settings |
| `telemetry` | Consent, machine probe, local store, shipping, install ping, stats and the consent command, for any plugin's contract |
| `setup` | `speak-core-setup`, the NeMo-Speech.cpp installer |

## Settings

The speech server is shared, so its settings have no plugin prefix:

| Setting | Default | |
|---|---|---|
| `NEMO_HTTP_URL` | `http://127.0.0.1:8082` | where the server listens |
| `NEMO_API_KEY` | unset | bearer token for a remote OpenAI-compatible server |
| `NEMO_TTS_MODEL` | `magpie` | speech model |
| `NEMO_ASR_MODEL` | `nemotron-3.5` | transcription model |
| `NEMO_BIN` | `nemo-speech` | server binary |
| `NEMO_AUTOSTART` | `1` | `0` to run the server yourself |
| `NEMO_TTS_SEED` | unset | pins a voice's timbre across restarts |
| `SPEAK_CORE_STATE_DIR` | `<cache>/speak-core` | where plugins coordinate |

Every plugin on a machine must be given the same values for these. Whichever plugin
starts the server decides its arguments for all of them; plugins that disagree on
`NEMO_HTTP_URL` start two servers, and plugins that disagree on `SPEAK_CORE_STATE_DIR`
cannot see each other's sessions, so one can stop the server the other is using.

A voice belongs to one plugin and is read under its prefix: `<PREFIX>_ENGINE`,
`<PREFIX>_VOICE`, `<PREFIX>_VOICE_POOL`, `<PREFIX>_RATE`,
`<PREFIX>_COMMAND`. speak-core never reads the environment itself; plugins pass it.

## Installing NeMo-Speech.cpp

    uv run --directory <plugin checkout> speak-core-setup

installs `nemo-speech` 0.2.0 or later and pulls both models (about 1.4 GB). It reads
`NEMO_BIN` and `NEMO_INSTALLER`.

## Development

    uv sync
    uv run pytest
    uv run ruff check .
    uv run mypy

Operating rules are in [AGENTS.md](AGENTS.md); design and decisions in
[harness/architecture.md](harness/architecture.md).
