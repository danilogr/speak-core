"""The first-run notice is owed once per disclosure version, and never under
DO_NOT_TRACK, where nothing is ever sent."""

import json
from dataclasses import replace

from telemetry_fixtures import IDENTITY

from speak_core.telemetry import notice


def env_at(tmp_path, **extra: str) -> dict[str, str]:
    return {"HOME": str(tmp_path), **extra}


def test_a_fresh_install_owes_the_notice(tmp_path):
    assert notice.due(env_at(tmp_path), IDENTITY, host_platform="linux") is True


def test_once_shown_it_is_no_longer_due(tmp_path):
    env = env_at(tmp_path)
    assert notice.mark_shown(env, IDENTITY, host_platform="linux") is True
    assert notice.due(env, IDENTITY, host_platform="linux") is False


def test_the_marker_lives_beside_the_consent_file(tmp_path):
    env = env_at(tmp_path)
    notice.mark_shown(env, IDENTITY, host_platform="darwin")
    marker = IDENTITY.config_dir(env, host_platform="darwin") / notice.NOTICE_FILENAME
    assert json.loads(marker.read_text()) == {"disclosure_ver": IDENTITY.disclosure_version}


def test_a_newer_disclosure_is_owed_again(tmp_path):
    env = env_at(tmp_path)
    notice.mark_shown(env, IDENTITY, host_platform="linux")
    newer = replace(IDENTITY, disclosure_version=IDENTITY.disclosure_version + 1)
    assert notice.due(env, newer, host_platform="linux") is True


def test_do_not_track_owes_nothing_and_writes_nothing(tmp_path):
    env = env_at(tmp_path, DO_NOT_TRACK="1")
    assert notice.due(env, IDENTITY, host_platform="linux") is False
    assert not IDENTITY.config_dir(env, host_platform="linux").exists()


def test_a_corrupt_marker_means_the_notice_is_owed(tmp_path):
    env = env_at(tmp_path)
    marker = IDENTITY.config_dir(env, host_platform="linux") / notice.NOTICE_FILENAME
    marker.parent.mkdir(parents=True)
    marker.write_text("not json")
    assert notice.due(env, IDENTITY, host_platform="linux") is True


def test_marking_does_not_create_the_consent_file(tmp_path):
    """Showing the notice records no telemetry choice, so it must not create the
    consent file (and with it an install id)."""
    env = env_at(tmp_path)
    notice.mark_shown(env, IDENTITY, host_platform="linux")
    directory = IDENTITY.config_dir(env, host_platform="linux")
    assert sorted(p.name for p in directory.iterdir()) == [notice.NOTICE_FILENAME]


def test_an_unwritable_config_directory_is_reported_not_raised(tmp_path):
    env = env_at(tmp_path)
    directory = IDENTITY.config_dir(env, host_platform="linux")
    directory.parent.mkdir(parents=True)
    directory.write_text("a file where the directory should be")
    assert notice.mark_shown(env, IDENTITY, host_platform="linux") is False


def test_a_boolean_in_the_marker_is_not_a_disclosure_version(tmp_path):
    """JSON `true` is a Python `int` subclass; it must not read as disclosure 1."""
    first = replace(IDENTITY, disclosure_version=1)
    env = env_at(tmp_path)
    marker = first.config_dir(env, host_platform="linux") / notice.NOTICE_FILENAME
    marker.parent.mkdir(parents=True)
    marker.write_text(json.dumps({"disclosure_ver": True}))
    assert notice.due(env, first, host_platform="linux") is True


def test_marking_under_do_not_track_writes_nothing(tmp_path):
    env = env_at(tmp_path, DO_NOT_TRACK="1")
    assert notice.mark_shown(env, IDENTITY, host_platform="linux") is False
    assert not IDENTITY.config_dir(env, host_platform="linux").exists()


def test_the_marker_is_replaced_whole_and_leaves_nothing_beside_it(tmp_path):
    env = env_at(tmp_path)
    assert notice.mark_shown(env, IDENTITY, host_platform="linux") is True
    assert notice.mark_shown(env, IDENTITY, host_platform="linux") is True
    directory = IDENTITY.config_dir(env, host_platform="linux")
    assert sorted(p.name for p in directory.iterdir()) == [notice.NOTICE_FILENAME]
