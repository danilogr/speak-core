"""The speaker lock: one process makes sound at a time, a waiter can be stopped, and
two processes that both have a lot to say take turns."""

import asyncio
import os
import time
from collections.abc import Callable

import pytest

from speak_core.speaker import LOCK_DIRNAME, WAITING_DIRNAME, SpeakerLock

ALIVE = {1, 2}


def lock(directory, pid, *, poll=0.01):
    return SpeakerLock(shared_dir=directory, pid=pid, is_alive=ALIVE.__contains__, poll=poll)


async def until(predicate: Callable[[], bool], timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline, "condition never became true"
        await asyncio.sleep(0.005)


async def test_a_free_speaker_is_taken_at_once(tmp_path):
    assert await asyncio.wait_for(lock(tmp_path, 1).acquire(asyncio.Event()), 1.0) is True
    assert (tmp_path / LOCK_DIRNAME / "owner").read_text() == "1"


async def test_a_second_process_waits_until_the_first_releases(tmp_path):
    first, second = lock(tmp_path, 1), lock(tmp_path, 2)
    assert await first.acquire(asyncio.Event())
    waiting = asyncio.create_task(second.acquire(asyncio.Event()))
    await until(lambda: (tmp_path / WAITING_DIRNAME / "2").exists())
    assert not waiting.done()
    first.release()
    assert await asyncio.wait_for(waiting, 1.0) is True
    assert not (tmp_path / WAITING_DIRNAME / "2").exists()


async def test_a_waiter_is_stopped_at_once_not_at_its_next_poll(tmp_path):
    holder, waiter = lock(tmp_path, 1), lock(tmp_path, 2, poll=60.0)
    assert await holder.acquire(asyncio.Event())
    stopped = asyncio.Event()
    waiting = asyncio.create_task(waiter.acquire(stopped))
    await until(lambda: (tmp_path / WAITING_DIRNAME / "2").exists())
    stopped.set()
    assert await asyncio.wait_for(waiting, 1.0) is False
    assert not (tmp_path / WAITING_DIRNAME / "2").exists()


async def test_a_lock_left_by_a_dead_process_is_reclaimed(tmp_path):
    """Review focus: a process that died mid-sentence must not silence everyone else."""
    dead = SpeakerLock(shared_dir=tmp_path, pid=999, is_alive=ALIVE.__contains__)
    assert await dead.acquire(asyncio.Event())
    assert await asyncio.wait_for(lock(tmp_path, 1).acquire(asyncio.Event()), 1.0) is True


async def test_a_process_that_just_spoke_lets_a_waiting_one_go_first(tmp_path):
    """Review focus: a process with its next sentence ready would otherwise take the
    lock back within milliseconds, and a waiter that polls would never get a turn."""
    first, second = lock(tmp_path, 1), lock(tmp_path, 2)
    never = asyncio.Event()
    assert await first.acquire(never)
    second_turn = asyncio.create_task(second.acquire(never))
    await until(lambda: (tmp_path / WAITING_DIRNAME / "2").exists())

    first.release()
    first_again = asyncio.create_task(first.acquire(never))

    assert await asyncio.wait_for(second_turn, 1.0) is True
    assert not first_again.done()
    second.release()
    assert await asyncio.wait_for(first_again, 1.0) is True
    first.release()


async def test_an_unusable_shared_directory_never_silences_speech(tmp_path, caplog):
    """Review focus: coordination is a courtesy; a broken cache directory plays
    uncoordinated rather than not at all."""
    blocked = tmp_path / "shared"
    blocked.write_text("a file where the directory should be")
    speaker = lock(blocked, 1)
    assert await asyncio.wait_for(speaker.acquire(asyncio.Event()), 1.0) is True
    speaker.release()
    assert "playing anyway" in caplog.text


async def test_an_unusable_shared_directory_is_warned_about_once(tmp_path, caplog):
    blocked = tmp_path / "shared"
    blocked.write_text("a file where the directory should be")
    speaker = lock(blocked, 1)
    for _ in range(3):
        assert await asyncio.wait_for(speaker.acquire(asyncio.Event()), 1.0) is True
        speaker.release()
    warnings = [r for r in caplog.records if "playing anyway" in r.getMessage()]
    assert len(warnings) == 1


async def test_releasing_a_lock_this_process_does_not_hold_changes_nothing(tmp_path):
    first = lock(tmp_path, 1)
    assert await first.acquire(asyncio.Event())
    lock(tmp_path, 2).release()
    assert (tmp_path / LOCK_DIRNAME / "owner").read_text() == "1"


async def test_a_failure_inside_the_lock_directory_is_retried_not_played_unlocked(tmp_path, caplog):
    """Review focus: the holder releasing, or another waiter claiming, between two of
    this process's steps surfaces as an OSError from inside the lock directory; that is
    contention, not a broken shared directory."""
    speaker = lock(tmp_path, 2)
    real = speaker._lock.acquire
    failures = [FileNotFoundError("owner file vanished"), OSError(22, "Invalid argument")]

    def racing() -> None:
        if failures:
            raise failures.pop(0)
        real()

    speaker._lock.acquire = racing  # type: ignore[method-assign]
    assert await asyncio.wait_for(speaker.acquire(asyncio.Event()), 1.0) is True
    assert not failures
    assert (tmp_path / LOCK_DIRNAME / "owner").read_text() == "2"
    assert "playing anyway" not in caplog.text


async def test_a_lock_being_claimed_is_waited_for_until_it_goes_stale(tmp_path):
    """Review focus: an ownerless lock directory is another process mid-claim, so it
    is waited for; one that stays ownerless was left by a claimer that died."""
    held = tmp_path / LOCK_DIRNAME
    held.mkdir()
    waiting = asyncio.create_task(lock(tmp_path, 2).acquire(asyncio.Event()))
    await until(lambda: (tmp_path / WAITING_DIRNAME / "2").exists())
    await asyncio.sleep(0.05)
    assert not waiting.done()

    stale = time.time() - 60
    os.utime(held, (stale, stale))
    assert await asyncio.wait_for(waiting, 1.0) is True
    assert (held / "owner").read_text() == "2"


async def test_a_shared_directory_this_process_cannot_write_never_silences_speech(tmp_path, caplog):
    shared = tmp_path / "shared"
    shared.mkdir()
    shared.chmod(0o500)
    try:
        if os.access(shared, os.W_OK):
            pytest.skip("running as root: directory permissions do not apply")
        speaker = lock(shared, 1)
        assert await asyncio.wait_for(speaker.acquire(asyncio.Event()), 1.0) is True
        assert "playing anyway" in caplog.text
    finally:
        shared.chmod(0o700)
