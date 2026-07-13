from pathlib import Path

from qibao_api.settings import Settings


def test_settings_places_runtime_data_outside_source(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path)

    assert settings.database_url == f"sqlite:///{(tmp_path / 'qibao.db').as_posix()}"
