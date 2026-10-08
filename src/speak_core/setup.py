"""`speak-core-setup`: install NeMo-Speech.cpp and the models every plugin uses.

The installer is a shell script shipped inside the package, so a plugin's `/setup`
runs it from the plugin's own environment wherever the package was installed from.
It reads `NEMO_BIN` and `NEMO_INSTALLER` itself, from the environment it inherits, and
`NEMO_TN_DIR`, which this sets to where the speech server will look for its
text-normalization grammars.
"""

import os
import subprocess
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from speak_core.config import ServerSettings

SCRIPT = Path(__file__).with_name("install-nemo.sh")

Runner = Callable[[Sequence[str], Mapping[str, str]], int]


def _run(argv: Sequence[str], env: Mapping[str, str]) -> int:
    return subprocess.run(list(argv), env=dict(env), check=False).returncode


def run(*, runner: Runner = _run, env: Mapping[str, str] | None = None) -> int:
    """Run the installer with bash and return its exit status."""
    environ = dict(os.environ if env is None else env)
    environ["NEMO_TN_DIR"] = str(ServerSettings.from_env(environ).tn_dir)
    return runner(["bash", str(SCRIPT)], environ)


def main() -> None:
    raise SystemExit(run())
