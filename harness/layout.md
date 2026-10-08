# Codebase Layout

> Exhaustive guide to the files and directories in this repository.
> For system architecture, component boundaries, and design decisions, see [architecture.md](architecture.md).

## Directory Overview

```
.
├── harness/                Developer docs: architecture, layout, guidelines
├── src/speak_core/         The library
│   ├── engines/            Speech synthesis engines and the transcription client
│   └── telemetry/          Consent, local store, shipping and stats for any plugin's contract
└── tests/                  Offline, mocked tests
    └── telemetry/          Telemetry tests and their two fixture schemas
```

---

## Root Files

| File | Purpose |
|---|---|
| [`README.md`](../README.md) | What the library provides, the shared settings, installing NeMo-Speech.cpp, and the developer quickstart. |
| [`AGENTS.md`](../AGENTS.md) | Operating rules and behavioral constraints for AI coding agents working on this repository. |
| [`pyproject.toml`](../pyproject.toml) | Package metadata, the `speak-core-setup` console script, ruff/mypy/pytest settings. |
| [`uv.lock`](../uv.lock) | Pinned dependency lockfile ensuring reproducible builds. |
| [`.gitignore`](../.gitignore) | Virtual environment, tool caches, build output. |

---

## Harness (`harness/`)

| File | Description |
|---|---|
| [`harness/architecture.md`](architecture.md) | Component boundaries, data model, telemetry, and the rationale for each key decision. |
| [`harness/design-guidelines.md`](design-guidelines.md) | Coding standards, Python 3.12+ type conventions, Ruff/Mypy/Pytest rules, logging conventions, and testing requirements. |
| [`harness/layout.md`](layout.md) | This file: complete index and responsibility map of all codebase files. |

---

## Library (`src/speak_core/`)

| File | Responsibility |
|---|---|
| [`__init__.py`](../src/speak_core/__init__.py) | Package docstring. |
| [`py.typed`](../src/speak_core/py.typed) | Marks the package as typed for plugins' `mypy --strict`. |
| [`config.py`](../src/speak_core/config.py) | Settings every plugin reads the same way: shared `NEMO_*` server settings, a prefixed voice, and the plugin and shared state directories. |
| [`runtime.py`](../src/speak_core/runtime.py) | Logging for the plugin's and the core's loggers, the speech server health probe, and the supervisor factory. |
| [`queue.py`](../src/speak_core/queue.py) | Serial speech queue: plays sentences in order without overlapping, prepares the next sentence while one plays, and handles cancellations. |
| [`text.py`](../src/speak_core/text.py) | Text formatting: collapses multi-line text to a single line, and cuts it into the sentences a plugin queues and the clauses a speech model is sent one at a time. |
| [`player.py`](../src/speak_core/player.py) | Finds an installed audio player command for the current platform (`afplay` on macOS, PowerShell on Windows, `paplay`/`aplay`/`ffplay` on Linux). |
| [`exclusive.py`](../src/speak_core/exclusive.py) | Cross-process lock using filesystem directories, with automatic cleanup if a process exits unexpectedly. |
| [`speaker.py`](../src/speak_core/speaker.py) | Cross-process speaker lock: one utterance plays at a time across every process that speaks, with turns that alternate. |
| [`supervisor.py`](../src/speak_core/supervisor.py) | Speech server supervisor: starts, shares, and shuts down the local NeMo speech server across open terminal windows. |
| [`install-nemo.sh`](../src/speak_core/install-nemo.sh) | NeMo installer run by `speak-core-setup`: installs `nemo-speech` >= 0.2.0, pulls MagpieTTS and Nemotron 3.5, runs `doctor`. Idempotent. |
| [`setup.py`](../src/speak_core/setup.py) | The `speak-core-setup` console script. |

### Speech Engines (`src/speak_core/engines/`)

| File | Description |
|---|---|
| [`__init__.py`](../src/speak_core/engines/__init__.py) | `build_engine`: picks the engine a plugin's voice settings name, falling back to `say`. |
| [`base.py`](../src/speak_core/engines/base.py) | Core engine protocol (`Engine`) and data structure (`Utterance`) defining the synthesis interface. |
| [`say.py`](../src/speak_core/engines/say.py) | macOS native speech engine using the built-in `/usr/bin/say` executable. Supports voice listing and filtering by locale. |
| [`nemo.py`](../src/speak_core/engines/nemo.py) | Client for local NeMo-Speech.cpp HTTP server: synthesizes speech via MagpieTTS and manages temporary WAV files for playback; and `NemoSynthesizer`, the no-fallback synthesis call. |
| [`command.py`](../src/speak_core/engines/command.py) | Custom command engine: invokes any arbitrary command line (e.g., Piper, espeak-ng) passing the text as an argument. |
| [`asr.py`](../src/speak_core/engines/asr.py) | Speech-to-text client sending audio to the shared NeMo server via OpenAI-compatible `/v1/audio/transcriptions`. |

### Telemetry (`src/speak_core/telemetry/`)

| File | Responsibility |
|---|---|
| [`__init__.py`](../src/speak_core/telemetry/__init__.py) | Package docstring. |
| [`schema.py`](../src/speak_core/telemetry/schema.py) | Schema types: `RowTable` and `TelemetrySchema`, what the table-agnostic store and shipper need to know of a plugin's tables. |
| [`store.py`](../src/speak_core/telemetry/store.py) | SQLite client: builds a plugin's schema, handles database migrations and records local session events. |
| [`identity.py`](../src/speak_core/telemetry/identity.py) | `TelemetryIdentity`: the plugin's name, env prefix, endpoint and disclosure version; every variable and the config directory derive from it. |
| [`wiring.py`](../src/speak_core/telemetry/wiring.py) | Shared composition: HTTP transport, harness and locale detection, and `start_install` (consent, machine probe, store, `installs` row). |
| [`ship.py`](../src/speak_core/telemetry/ship.py) | Background uploader: sends unsent anonymous metrics (with all local-only fields stripped) to the server. |
| [`ping.py`](../src/speak_core/telemetry/ping.py) | Anonymous install ping: sends version, OS, and event type on install or upgrade. |
| [`consent.py`](../src/speak_core/telemetry/consent.py) | Consent state: the mode switches, the persisted install id, and where they are stored. |
| [`cli.py`](../src/speak_core/telemetry/cli.py) | The consent command: `on`, `local`, `off`, `--id`, `record on|off`, and status. |
| [`report.py`](../src/speak_core/telemetry/report.py) | Stats scaffolding: finds the store, renders it with the plugin's function, prints install id and mode. |
| [`notice.py`](../src/speak_core/telemetry/notice.py) | Whether the first-run notice is owed, and recording that it was shown (`notice.json`). |
| [`machine.py`](../src/speak_core/telemetry/machine.py) | System probe: detects OS, CPU core counts, bucketed RAM (e.g. 16, 32 GB), and GPU acceleration. |

---

## Test Suite (`tests/`)

Offline tests executed with `uv run pytest`:

| File | What it tests |
|---|---|
| [`tests/conftest.py`](../tests/conftest.py) | Points the shared state directory at a temporary one for every test. |
| [`tests/test_config.py`](../tests/test_config.py) | Shared server settings and a voice read under a plugin's prefix. |
| [`tests/test_runtime.py`](../tests/test_runtime.py) | Logging on both loggers, the health probe, and the supervisor factory. |
| [`tests/test_engine_selection.py`](../tests/test_engine_selection.py) | `build_engine`: which engine each voice setting selects, and the `say` fallback. |
| [`tests/test_engines_say.py`](../tests/test_engines_say.py) | The `say` engine. |
| [`tests/test_engines_nemo.py`](../tests/test_engines_nemo.py) | The `nemo` engine under normal, degraded, and fallback conditions, and a long text sent in pieces and joined. |
| [`tests/test_synthesizer.py`](../tests/test_synthesizer.py) | `NemoSynthesizer`: the request it sends and the `SynthesisFailed` kinds it raises. |
| [`tests/test_engines_command.py`](../tests/test_engines_command.py) | The `command` engine. |
| [`tests/test_asr.py`](../tests/test_asr.py) | The transcription client and the speech server liveness check. |
| [`tests/test_text.py`](../tests/test_text.py) | Whitespace collapsing, and cutting text into sentences and pieces. |
| [`tests/test_player.py`](../tests/test_player.py) | Finding a sound player per platform with an injected lookup. |
| [`tests/test_queue.py`](../tests/test_queue.py) | FIFO playback order, depth-1 prefetch pipelining, and `stop` cancellation. |
| [`tests/test_exclusive.py`](../tests/test_exclusive.py) | One holder at a time across processes, elected by an atomic `mkdir`. |
| [`tests/test_speaker.py`](../tests/test_speaker.py) | The speaker lock: waiting, immediate stop, dead-holder reclaim, alternating turns, a claim in progress, failures inside the lock directory, and an unusable shared directory. |
| [`tests/test_speaker_stress.py`](../tests/test_speaker_stress.py) | The speaker lock across real processes: three processes polling one directory never hold it together and never play unlocked. |
| [`tests/test_supervisor.py`](../tests/test_supervisor.py) | NeMo server process management, election locks, PID tracking, and graceful shutdowns. |
| [`tests/test_setup.py`](../tests/test_setup.py) | `speak-core-setup`: the installer travels inside the package and is run with bash. |

### Telemetry tests (`tests/telemetry/`)

| File | What it tests |
|---|---|
| [`telemetry_fixtures.py`](../tests/telemetry/telemetry_fixtures.py) | An utterance-shaped and a job-shaped schema, and a test identity. |
| [`utterances_schema.sql`](../tests/telemetry/utterances_schema.sql) | A copy of walkie's contract schema, the utterance-shaped fixture's DDL. |
| [`test_store.py`](../tests/telemetry/test_store.py) | Schema creation, foreign-key enforcement, and the CRUD the shipper relies on. |
| [`test_jobs_table.py`](../tests/telemetry/test_jobs_table.py) | The store and shipper over a job-shaped row table. |
| [`test_ship.py`](../tests/telemetry/test_ship.py) | Projection, chunking, and the retry rules. |
| [`test_ping.py`](../tests/telemetry/test_ping.py) | When the install ping is due, what it says, and that its marker moves only on success. |
| [`test_consent.py`](../tests/telemetry/test_consent.py) | Consent switches, the persisted install id, and where both live. |
| [`test_identity.py`](../tests/telemetry/test_identity.py) | A plugin's variables, directory and endpoint, and nothing of another plugin's. |
| [`test_machine.py`](../tests/telemetry/test_machine.py) | The hardware probe: bounded, cached, honest about what it could not tell. |
| [`test_wiring.py`](../tests/telemetry/test_wiring.py) | Harness and locale detection and the install row. |
| [`test_cli.py`](../tests/telemetry/test_cli.py) | The consent command's modes, `--id`, status and `record`. |
| [`test_report.py`](../tests/telemetry/test_report.py) | The stats scaffolding: store lookup, rendering, install id and mode. |
| [`test_notice.py`](../tests/telemetry/test_notice.py) | The first-run notice: owed once per disclosure version, never under DO_NOT_TRACK. |
