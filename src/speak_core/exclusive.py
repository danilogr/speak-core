"""One holder at a time, across processes.

Sessions are separate processes with no other way to see each other, so they
coordinate through the filesystem the way the speech server already does: an
atomic `mkdir` elects one holder, and a lock whose owner has died is reclaimed.
"""

import logging
import os
import time
from collections.abc import Callable
from pathlib import Path
from types import TracebackType
from typing import Self

logger = logging.getLogger(__name__)


class ClaimInProgressError(RuntimeError):
    """The lock exists but names no owner yet, and has not for long enough to be stale.

    Another process is between its `mkdir` and its owner write, or between removing
    its owner file and its `rmdir`.
    """

    def __init__(self, directory: Path) -> None:
        super().__init__(f"the {directory.name} lock is being claimed or released")


class ExclusiveLock:
    """One holder at a time, elected by an atomic `mkdir`, released only by its holder.

    Re-entrant by default: the holder asking again is a session claiming something
    it already has, and refusing it would fail a retry that is no contention at
    all. A lock one process claims on another's behalf passes `reentrant=False`,
    because there the pid in the file is not the work: two calls inside one process
    would both find their own pid and both believe they had won.

    A lock directory with no owner file is ambiguous: a claimer that died before
    recording itself, or a live one in the gap between its `mkdir` and its owner
    write (or between its owner unlink and its `rmdir`). With `ownerless_grace` set,
    such a lock is reclaimed only once it has gone that many seconds without a
    change, and until then `acquire` raises `ClaimInProgressError`. Without it, an
    ownerless lock is reclaimed at once, so a process racing another's claim can take
    the lock too.
    """

    def __init__(
        self,
        *,
        directory: Path,
        is_alive: Callable[[int], bool],
        busy: Callable[[int], Exception],
        pid: int | None = None,
        reentrant: bool = True,
        ownerless_grace: float | None = None,
    ) -> None:
        self._dir = Path(directory)
        self._owner_file = self._dir / "owner"
        self._is_alive = is_alive
        self._busy = busy
        self._pid = pid if pid is not None else os.getpid()
        self._reentrant = reentrant
        self._ownerless_grace = ownerless_grace

    def owner(self) -> int | None:
        """The pid recorded in the lock, or None when there is none to read."""
        try:
            return int(self._owner_file.read_text().strip())
        except (OSError, ValueError):
            return None

    def acquire(self) -> None:
        """Claim the lock, or raise whatever `busy` builds for the live holder.

        Raises `ClaimInProgressError` for an ownerless lock inside `ownerless_grace`.
        """
        self._dir.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._dir.mkdir()
        except FileExistsError:
            self._reclaim()
        self._write_owner()

    def _reclaim(self) -> None:
        """Decide whether an existing lock may be taken over, raising if it may not."""
        grace = self._ownerless_grace
        held_by = self.owner()
        if held_by is None:
            if grace is None:
                return
            if not self._unchanged_for(grace):
                raise ClaimInProgressError(self._dir)
        elif held_by == self._pid and self._reentrant:
            return
        elif self._is_alive(held_by):
            raise self._busy(held_by)
        else:
            # Two reclaimers racing could both take over a dead owner's lock: the
            # window the supervisor's stale-start-lock takeover also accepts. It opens
            # only after a holder has died.
            logger.info("reclaiming the %s lock left by %s", self._dir.name, held_by)
        if grace is not None:
            self._clear_partials()

    def _unchanged_for(self, seconds: float) -> bool:
        # The directory's mtime moves with every entry created, renamed or removed in
        # it, so it dates the last step of a claim or a release.
        return time.time() - self._dir.stat().st_mtime >= seconds

    def _clear_partials(self) -> None:
        """Remove the half-written owner files a dead claimer left. One left behind
        keeps every release from removing the directory, and each next claim would
        then wait out the grace on an ownerless lock."""
        for partial in self._dir.glob("owner.*"):
            partial.unlink(missing_ok=True)

    def take_over(self, previous: int) -> None:
        """Become the holder of a lock `previous` claimed on this process's behalf.

        The receiver takes over rather than the claimer handing over, because the
        claimer cannot name a process that does not exist yet, and one that fails
        at once would otherwise try to release in the gap before the handover.
        """
        self._dir.mkdir(parents=True, exist_ok=True)
        held_by = self.owner()
        if held_by not in (None, previous, self._pid) and self._is_alive(held_by):
            raise self._busy(held_by)
        self._write_owner()

    def release(self) -> None:
        """Give the lock back. A lock held by someone else is left alone."""
        if self.owner() != self._pid:
            return
        # Not atomic: a take_over() landing between the check above and this unlink
        # loses the new holder's claim, and an unrelated process could then acquire
        # the "free" lock while that holder is still running, so callers release
        # only when no takeover can be in flight — the same class of window acquire() accepts.
        self._owner_file.unlink(missing_ok=True)
        try:
            self._dir.rmdir()
        except OSError as error:
            logger.debug("could not remove the %s lock: %s", self._dir.name, error)

    def _write_owner(self) -> None:
        # Replaced, not rewritten: a reader between a truncate and a write would
        # see no owner and reclaim a lock that is held.
        partial = self._owner_file.with_name(f"owner.{self._pid}")
        partial.write_text(str(self._pid))
        partial.replace(self._owner_file)

    def __enter__(self) -> Self:
        self.acquire()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.release()
