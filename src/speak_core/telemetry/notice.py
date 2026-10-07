"""The first-run notice: owed once per disclosure version, before anything is sent.

A plugin supplies the text and decides where to show it; this module only remembers
that it was shown, in `notice.json` beside the consent file. That file is separate
from the consent file on purpose: showing the notice records no telemetry choice, so it
must not create the consent file and the install id that comes with it. Under
`DO_NOT_TRACK` nothing is ever sent, so no notice is owed and nothing is written.
"""

import json
import logging
from collections.abc import Mapping
from pathlib import Path

from speak_core.telemetry import consent
from speak_core.telemetry.identity import TelemetryIdentity

logger = logging.getLogger(__name__)

NOTICE_FILENAME = "notice.json"


def _marker(env: Mapping[str, str], identity: TelemetryIdentity, *, host_platform: str) -> Path:
    return identity.config_dir(env, host_platform=host_platform) / NOTICE_FILENAME


def due(env: Mapping[str, str], identity: TelemetryIdentity, *, host_platform: str) -> bool:
    """True until this install has been shown the plugin's current disclosure."""
    if consent.do_not_track(env):
        return False
    try:
        shown = json.loads(
            _marker(env, identity, host_platform=host_platform).read_text(encoding="utf-8")
        ).get("disclosure_ver")
    except (OSError, ValueError, AttributeError):
        return True
    # `bool` is an `int` subclass, and JSON `true` is no disclosure version.
    if not isinstance(shown, int) or isinstance(shown, bool):
        return True
    return shown < identity.disclosure_version


def mark_shown(env: Mapping[str, str], identity: TelemetryIdentity, *, host_platform: str) -> bool:
    """Record that the current disclosure was shown. False when nothing was written:
    under `DO_NOT_TRACK`, where none is owed, or when the marker could not be written,
    in which case the notice is simply owed again next time."""
    if consent.do_not_track(env):
        return False
    marker = _marker(env, identity, host_platform=host_platform)
    # Written beside it and renamed over it: a reader never sees half a marker.
    partial = marker.with_name(f".{NOTICE_FILENAME}.partial")
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        partial.write_text(
            json.dumps({"disclosure_ver": identity.disclosure_version}), encoding="utf-8"
        )
        partial.replace(marker)
    except OSError as error:
        logger.debug("telemetry: could not record the notice at %s: %s", marker, error)
        return False
    return True
