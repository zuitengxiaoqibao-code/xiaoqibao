from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from qibao_api.routes.settings import router
from qibao_api.settings_repository import (
    AISettings,
    AISettingsRepository,
    EffectiveAISettingsResolver,
)


def client(tmp_path: Path, fallback: AISettings | None = None) -> TestClient:
    application = FastAPI()
    repository = AISettingsRepository(tmp_path)
    application.state.ai_settings_repository = repository
    application.state.effective_ai_settings = EffectiveAISettingsResolver(
        repository, fallback=fallback
    )
    application.include_router(router)
    return TestClient(application)


def environment_settings() -> AISettings:
    return AISettings(
        base_url="http://localhost:11434/v1",
        model="environment-model",
        api_key="environment-secret",
    )


def test_ai_settings_never_return_secret(tmp_path: Path) -> None:
    subject = client(tmp_path)
    payload = {
        "base_url": "https://api.example/v1",
        "model": "model-a",
        "api_key": "secret-value",
    }

    response = subject.put("/api/v1/settings/ai", json=payload)
    body = subject.get("/api/v1/settings/ai").json()

    assert response.status_code == 200
    assert body["configured"] is True
    assert body["api_key_hint"].endswith("alue")
    assert "secret-value" not in str(response.json())
    assert "secret-value" not in str(body)


def test_unconfigured_and_deleted_settings_have_no_hint(tmp_path: Path) -> None:
    subject = client(tmp_path)
    assert subject.get("/api/v1/settings/ai").json() == {
        "configured": False,
        "base_url": None,
        "model": None,
        "api_key_hint": None,
    }
    subject.put(
        "/api/v1/settings/ai",
        json={"base_url": "https://api.example/v1", "model": "m", "api_key": "secret"},
    )

    response = subject.delete("/api/v1/settings/ai")

    assert response.status_code == 200
    assert response.json()["configured"] is False


def test_short_api_key_is_not_returned_in_full(tmp_path: Path) -> None:
    subject = client(tmp_path)
    subject.put(
        "/api/v1/settings/ai",
        json={"base_url": "https://api.example/v1", "model": "m", "api_key": "abc"},
    )

    response = subject.get("/api/v1/settings/ai")

    assert "abc" not in response.text


def test_get_reports_environment_fallback_when_local_is_missing(tmp_path: Path) -> None:
    response = client(tmp_path, environment_settings()).get("/api/v1/settings/ai")

    assert response.json() == {
        "configured": True,
        "base_url": "http://localhost:11434/v1",
        "model": "environment-model",
        "api_key_hint": "****cret",
    }


def test_delete_local_override_reveals_environment_fallback(tmp_path: Path) -> None:
    subject = client(tmp_path, environment_settings())
    subject.put(
        "/api/v1/settings/ai",
        json={"base_url": "https://api.example/v1", "model": "local", "api_key": "local-secret"},
    )

    response = subject.delete("/api/v1/settings/ai")

    assert response.json()["model"] == "environment-model"
    assert response.json()["configured"] is True


def test_corrupt_local_file_blocks_environment_fallback(tmp_path: Path) -> None:
    (tmp_path / "ai-settings.json").write_text("{broken", encoding="utf-8")

    response = client(tmp_path, environment_settings()).get("/api/v1/settings/ai")

    assert response.json()["configured"] is False


def test_put_rejects_unsafe_url_without_returning_secret(tmp_path: Path) -> None:
    secret = "do-not-return"

    response = client(tmp_path).put(
        "/api/v1/settings/ai",
        json={
            "base_url": f"https://user:{secret}@api.example/v1",
            "model": "m",
            "api_key": secret,
        },
    )

    assert response.status_code == 422
    assert secret not in response.text


def test_put_never_echoes_secret_from_malformed_payload(tmp_path: Path) -> None:
    secret = "malformed-secret"

    response = client(tmp_path).put(
        "/api/v1/settings/ai",
        json={
            "base_url": "https://api.example/v1",
            "model": [secret],
            "api_key": secret,
            "unexpected": secret,
        },
    )

    assert response.status_code == 422
    assert secret not in response.text
