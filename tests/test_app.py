import pytest

from app import main
from app.driving_scene_annotation import cli


def test_main_uses_demo_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "run", lambda: 0)

    with pytest.raises(SystemExit) as result:
        main()
    assert result.value.code == 0
