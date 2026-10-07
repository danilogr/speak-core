"""One holder at a time across processes, elected by an atomic `mkdir`."""

import logging
import os
import time

import pytest

from speak_core.exclusive import ClaimInProgressError, ExclusiveLock

ALIVE = {100, 200, 300}


class BusyError(RuntimeError):
    def __init__(self, owner: int) -> None:
        super().__init__(f"held by {owner}")
        self.owner = owner


def lock(tmp_path, pid, *, reentrant=True, ownerless_grace=None):
    return ExclusiveLock(
        directory=tmp_path / "held",
        is_alive=lambda p: p in ALIVE,
        busy=BusyError,
        pid=pid,
        reentrant=reentrant,
        ownerless_grace=ownerless_grace,
    )


def age(path, seconds):
    then = time.time() - seconds
    os.utime(path, (then, then))


def test_a_second_live_process_is_refused(tmp_path):
    lock(tmp_path, 100).acquire()
    with pytest.raises(BusyError) as refused:
        lock(tmp_path, 200).acquire()
    assert refused.value.owner == 100


def test_the_holder_may_claim_again_when_reentrant(tmp_path):
    lock(tmp_path, 100).acquire()
    lock(tmp_path, 100).acquire()
    assert lock(tmp_path, 100).owner() == 100


def test_the_holder_is_refused_a_second_claim_when_not_reentrant(tmp_path):
    lock(tmp_path, 100, reentrant=False).acquire()
    with pytest.raises(BusyError):
        lock(tmp_path, 100, reentrant=False).acquire()


def test_a_lock_left_by_a_dead_process_is_reclaimed(tmp_path):
    lock(tmp_path, 999).acquire()
    lock(tmp_path, 200).acquire()
    assert lock(tmp_path, 200).owner() == 200


def test_only_the_holder_releases(tmp_path):
    lock(tmp_path, 100).acquire()
    lock(tmp_path, 200).release()
    assert lock(tmp_path, 100).owner() == 100
    lock(tmp_path, 100).release()
    assert lock(tmp_path, 100).owner() is None


def test_a_takeover_moves_the_lock_to_the_receiver(tmp_path):
    lock(tmp_path, 100).acquire()
    lock(tmp_path, 200).take_over(previous=100)
    assert lock(tmp_path, 200).owner() == 200


def test_the_context_manager_releases(tmp_path):
    with lock(tmp_path, 100):
        assert lock(tmp_path, 100).owner() == 100
    assert lock(tmp_path, 100).owner() is None


def test_an_ownerless_lock_inside_the_grace_is_a_claim_in_progress(tmp_path):
    """Review focus: a lock directory with no owner file yet is another process
    between its `mkdir` and its owner write, not a free lock."""
    (tmp_path / "held").mkdir()
    with pytest.raises(ClaimInProgressError):
        lock(tmp_path, 200, ownerless_grace=2.0).acquire()
    assert lock(tmp_path, 200).owner() is None


def test_an_ownerless_lock_past_the_grace_is_reclaimed(tmp_path):
    held = tmp_path / "held"
    held.mkdir()
    (held / "owner.999").write_text("999")
    age(held, 5.0)
    claimer = lock(tmp_path, 200, ownerless_grace=2.0)
    claimer.acquire()
    assert claimer.owner() == 200
    claimer.release()
    assert not held.exists(), "a dead claimer's half-written owner file kept the lock"


def test_an_ownerless_lock_is_reclaimed_at_once_without_a_grace(tmp_path):
    (tmp_path / "held").mkdir()
    lock(tmp_path, 200).acquire()
    assert lock(tmp_path, 200).owner() == 200


def test_only_a_dead_owner_is_logged_as_reclaimed(tmp_path, caplog):
    caplog.set_level(logging.INFO, logger="speak_core.exclusive")
    held = tmp_path / "held"
    held.mkdir()
    age(held, 5.0)
    lock(tmp_path, 200, ownerless_grace=2.0).acquire()
    assert "reclaiming" not in caplog.text
    lock(tmp_path, 200).release()

    lock(tmp_path, 999).acquire()
    lock(tmp_path, 200, ownerless_grace=2.0).acquire()
    assert "reclaiming the held lock left by 999" in caplog.text
