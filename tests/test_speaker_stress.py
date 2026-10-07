"""The speaker lock under real contention: several processes polling one shared
directory never hold the speakers at once, and none plays unlocked."""

import subprocess
import sys
import textwrap
import time

import pytest

# Each child takes the speakers `holds` times, creating a sentinel file exclusively while
# it holds them: a sentinel already there means another process holds them too. It also
# counts the warnings that mean an utterance played uncoordinated.
CHILD = textwrap.dedent(
    """
    import asyncio
    import logging
    import os
    import sys
    import time
    from pathlib import Path

    from speak_core import speaker as module
    from speak_core.speaker import SpeakerLock

    shared, holds, start = Path(sys.argv[1]), int(sys.argv[2]), float(sys.argv[3])
    # Shorter than production, so a few hundred handoffs fit in seconds; the races
    # are in the microseconds around each handoff, not in its length.
    module.HANDOFF_WINDOW = 0.01
    sentinel = shared / "holding"


    class Count(logging.Handler):
        warnings = 0

        def emit(self, record: logging.LogRecord) -> None:
            if record.levelno >= logging.WARNING:
                Count.warnings += 1


    logging.getLogger("speak_core").addHandler(Count())


    async def main() -> None:
        speaker = SpeakerLock(shared_dir=shared, poll=0.001)
        overlaps = 0
        never = asyncio.Event()
        await asyncio.sleep(max(0.0, start - time.time()))
        for _ in range(holds):
            assert await speaker.acquire(never)
            try:
                fd = os.open(sentinel, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                overlaps += 1
                await asyncio.sleep(0.002)
            else:
                os.close(fd)
                await asyncio.sleep(0.002)
                sentinel.unlink()
            speaker.release()
        print(overlaps, Count.warnings)


    asyncio.run(main())
    """
)

PROCESSES = 3
HOLDS = 100


@pytest.mark.timeout(60)
def test_processes_polling_one_directory_never_hold_the_speakers_together(tmp_path):
    """Review focus: an ownerless lock directory is another process between its
    `mkdir` and its owner write, or between its owner unlink and its `rmdir`; taking
    it then puts two processes on the speakers at once."""
    start = time.time() + 1.0
    children = [
        subprocess.Popen(
            [sys.executable, "-c", CHILD, str(tmp_path), str(HOLDS), str(start)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(PROCESSES)
    ]
    try:
        results = [child.communicate(timeout=55) for child in children]
    finally:
        # A child wedged on the lock would otherwise outlive the test run, holding
        # speaker/ in a temp directory nobody cleans.
        for child in children:
            if child.poll() is None:
                child.kill()
                child.wait()
    for child, (_, err) in zip(children, results, strict=True):
        assert child.returncode == 0, err
    overlaps = sum(int(out.split()[0]) for out, _ in results)
    unlocked = sum(int(out.split()[1]) for out, _ in results)
    assert (overlaps, unlocked) == (0, 0)
