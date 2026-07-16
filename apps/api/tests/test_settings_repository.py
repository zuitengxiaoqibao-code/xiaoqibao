import json
import os
from pathlib import Path
from urllib.parse import quote

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


@pytest.mark.parametrize(
    "base_url",
    [
        "https://api.example/v1/%73ecret-value",
        "https://api.example/v1/%73%65%63%72%65%74%2D%76%61%6C%75%65",
        "https://api.example/v1/%2573ecret-value",
    ],
)
def test_settings_reject_percent_encoded_secret_in_url_path(base_url: str) -> None:
    secret = "secret-value"

    with pytest.raises(ValueError) as error:
        AISettings(base_url=base_url, model="model-a", api_key=secret)

    assert secret not in str(error.value)


def test_settings_allows_percent_encoded_nonsecret_url_path() -> None:
    result = AISettings(
        base_url="http://localhost:11434/models/%E6%B5%8B%E8%AF%95",
        model="model-a",
        api_key="secret-value",
    )

    assert result.base_url.endswith("/%E6%B5%8B%E8%AF%95")


def test_settings_rejects_malformed_percent_escape_without_echoing_input() -> None:
    with pytest.raises(ValueError) as error:
        AISettings(
            base_url="https://api.example/v1/bad%2/path",
            model="model-a",
            api_key="secret-value",
        )

    assert "bad%2" not in str(error.value)
    assert "secret-value" not in str(error.value)


def test_settings_nfkc_normalizes_before_secret_comparison() -> None:
    fullwidth_secret = "ｓｅｃｒｅｔ"

    with pytest.raises(ValueError) as error:
        AISettings(
            base_url="https://api.example/v1",
            model=fullwidth_secret,
            api_key="secret",
        )

    assert "secret" not in str(error.value)


def test_settings_returns_nfkc_normalized_safe_values() -> None:
    result = AISettings(
        base_url="https://api.example/v1",
        model="ｍｏｄｅｌ",
        api_key="ｓｅｃｒｅｔ",
    )

    assert result.model == "model"
    assert result.api_key == "secret"


def nested_encode(value: str, rounds: int) -> str:
    for _ in range(rounds):
        value = quote(value, safe="")
    return value


def nested_encode_secret(rounds: int) -> str:
    value = "%73ecret-value"
    return nested_encode(value, rounds - 1)


def test_settings_rejects_quadruple_encoded_secret() -> None:
    secret = "secret-value"
    url = f"https://api.example/v1/{nested_encode_secret(4)}"

    with pytest.raises(ValueError) as error:
        AISettings(base_url=url, model="model-a", api_key=secret)

    assert secret not in str(error.value)


def test_settings_rejects_secret_encoded_beyond_decode_limit() -> None:
    secret = "secret-value"
    url = f"https://api.example/v1/{nested_encode_secret(10)}"

    with pytest.raises(ValueError) as error:
        AISettings(base_url=url, model="model-a", api_key=secret)

    assert secret not in str(error.value)


def test_settings_rejects_outer_encoded_malformed_escape() -> None:
    with pytest.raises(ValueError) as error:
        AISettings(
            base_url="https://api.example/v1/bad%252",
            model="model-a",
            api_key="secret-value",
        )

    assert "bad" not in str(error.value)
    assert "secret-value" not in str(error.value)


def test_settings_rejects_excessive_benign_nested_encoding() -> None:
    encoded = nested_encode("benign path", 10)

    with pytest.raises(ValueError) as error:
        AISettings(
            base_url=f"https://api.example/v1/{encoded}",
            model="model-a",
            api_key="secret-value",
        )

    assert encoded not in str(error.value)


def test_settings_accepts_stable_single_encoded_benign_path() -> None:
    settings = AISettings(
        base_url="https://api.example/v1/benign%20path",
        model="model-a",
        api_key="secret-value",
    )

    assert settings.base_url.endswith("/benign%20path")
