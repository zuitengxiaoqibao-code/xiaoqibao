from pathlib import Path

from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="QIBAO_", extra="ignore")

    data_dir: Path = Path(".runtime")
    scheduler_enabled: bool = True
    scheduler_interval_seconds: int = 30

    @computed_field
    @property
    def database_url(self) -> str:
        return f"sqlite:///{(self.data_dir / 'qibao.db').as_posix()}"

    @computed_field
    @property
    def decision_database_path(self) -> Path:
        return self.data_dir / "decisions.sqlite3"
