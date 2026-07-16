from pathlib import Path

from qibao_api.settings import Settings
from qibao_api.settings_repository import AISettings


def test_settings_places_runtime_data_outside_source(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path)

    assert settings.database_url == f"sqlite:///{(tmp_path / 'qibao.db').as_posix()}"


def test_decision_database_path_is_derived_from_data_dir(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path)

    assert settings.decision_database_path == tmp_path / "decisions.sqlite3"


def test_environment_ai_settings_are_available_as_initial_fallback(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path,
        ai_base_url="https://provider.example/v1",
        ai_model="environment-model",
        ai_api_key="environment-secret",
    )

    assert settings.initial_ai_settings == AISettings(
        base_url="https://provider.example/v1",
        model="environment-model",
        api_key="environment-secret",
    )


def test_incomplete_environment_ai_settings_are_unconfigured(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path, ai_api_key="environment-secret")

    assert settings.initial_ai_settings is None
