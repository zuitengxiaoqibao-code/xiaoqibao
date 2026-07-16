import json
import os
from pathlib import Path

import pytest

from qibao_api.settings_repository import (
    AISettings,
    AISettingsRepository,
    UnconfiguredAISettings,
)


def settings() -> AISettings:
    return AISettings(
        base_url="https://api.example/v1",
        model="model-a",
        api_key="secret-value",
    )


def test_repository_round_trips_settings_without_leaving_temporary_file(tmp_path: Path) -> None:
    repository = AISettingsRepository(tmp_path)

    repository.save(settings())

    assert repository.load() == settings()
    assert json.loads((tmp_path / "ai-settings.json").read_text(encoding="utf-8"))["api_key"] == "secret-value"
    assert list(tmp_path.glob("*.tmp")) == []


def test_repository_returns_typed_unconfigured_state_for_corrupt_file(tmp_path: Path) -> None:
    (tmp_path / "ai-settings.json").write_text("{not-json", encoding="utf-8")

    result = AISettingsRepository(tmp_path).load()

    assert isinstance(result, UnconfiguredAISettings)
    assert result.reason == "invalid_local_config"
    assert "not-json" not in repr(result)


@pytest.mark.parametrize(
    "base_url",
    ["ftp://api.example/v1", "https://user:secret@api.example/v1", "api.example/v1"],
)
def test_settings_reject_unsafe_provider_urls_without_echoing_secret(base_url: str) -> None:
    secret = "never-echo-this"

    with pytest.raises(ValueError) as error:
        AISettings(base_url=base_url, model="model-a", api_key=secret)

    assert secret not in str(error.value)


@pytest.mark.parametrize("field", ["model", "api_key"])
def test_settings_reject_blank_required_values_without_echoing_secret(field: str) -> None:
    values = settings().model_dump()
    values[field] = "   "

    with pytest.raises(ValueError) as error:
        AISettings(**values)

    assert "secret-value" not in str(error.value)


def test_delete_removes_saved_configuration(tmp_path: Path) -> None:
    repository = AISettingsRepository(tmp_path)
    repository.save(settings())

    repository.delete()

    assert isinstance(repository.load(), UnconfiguredAISettings)


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits are not enforced on Windows")
def test_saved_configuration_is_owner_only(tmp_path: Path) -> None:
    repository = AISettingsRepository(tmp_path)
    repository.save(settings())

    assert (repository.path.stat().st_mode & 0o777) == 0o600


@pytest.mark.parametrize(
    ("base_url", "model", "api_key"),
    [
        ("https://api.example/v1", "same-secret", "same-secret"),
        ("https://api.example/v1", "model-with-secret-value-inside", "secret-value"),
        ("https://api.example/v1/secret-value", "model-a", "secret-value"),
        ("https://api.example/v1?token=secret-value", "model-a", "secret-value"),
        ("https://api.example/v1#secret-value", "model-a", "secret-value"),
    ],
)
def test_settings_reject_secret_reflection(base_url: str, model: str, api_key: str) -> None:
    with pytest.raises(ValueError) as error:
        AISettings(base_url=base_url, model=model, api_key=api_key)

    assert api_key not in str(error.value)
