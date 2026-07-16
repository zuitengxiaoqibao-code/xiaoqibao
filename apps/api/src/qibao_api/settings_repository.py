import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit


@dataclass(frozen=True)
class AISettings:
    base_url: str
    model: str
    api_key: str

    def __post_init__(self) -> None:
        parsed = urlsplit(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("base_url must be an HTTP(S) URL")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("base_url must not contain user information")
        if not self.model.strip():
            raise ValueError("model must not be blank")
        if not self.api_key.strip():
            raise ValueError("api_key must not be blank")

    def model_dump(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class UnconfiguredAISettings:
    reason: Literal["missing", "invalid_local_config"]


AISettingsState = AISettings | UnconfiguredAISettings


class AISettingsRepository:
    def __init__(self, data_dir: Path) -> None:
        self.path = data_dir / "ai-settings.json"

    def load(self) -> AISettingsState:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("configuration must be an object")
            return AISettings(
                base_url=raw["base_url"],
                model=raw["model"],
                api_key=raw["api_key"],
            )
        except FileNotFoundError:
            return UnconfiguredAISettings(reason="missing")
        except (KeyError, TypeError, ValueError, json.JSONDecodeError, OSError):
            return UnconfiguredAISettings(reason="invalid_local_config")

    def save(self, settings: AISettings) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{self.path.name}.", suffix=".tmp", dir=self.path.parent
        )
        temporary_path = Path(temporary_name)
        try:
            if os.name != "nt":
                os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as file:
                json.dump(settings.model_dump(), file, ensure_ascii=False)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary_path, self.path)
            if os.name != "nt":
                self.path.chmod(0o600)
        except Exception:
            try:
                os.close(descriptor)
            except OSError:
                pass
            temporary_path.unlink(missing_ok=True)
            raise

    def delete(self) -> None:
        self.path.unlink(missing_ok=True)
