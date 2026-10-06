import pytest


@pytest.fixture(autouse=True)
def _shared_state_in_tmp(
    monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """No test may touch the real shared state directory.

    Core reads settings only from the mapping its caller passes, but a test that hands
    it `os.environ` would otherwise register with the developer's real speech server
    and take the real speaker lock under `~/Library/Caches/speak-core`.
    """
    monkeypatch.setenv("SPEAK_CORE_STATE_DIR", str(tmp_path_factory.mktemp("speak-core")))
