from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

APP_DIR = Path(__file__).resolve().parent
API_DIR = APP_DIR.parent


class Settings(BaseSettings):
    cors_origins: str = "http://localhost:3000"
    kestrel_db_path: str = "../../FDE_Assignment_Pack_Kestrel_v1.1/data/kestrel_ops.db"
    # The pack is frozen, so "today" cannot come from the clock. Unset means the
    # last day with data; set it to replay a past morning.
    as_of_date: str | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def db_path(self) -> Path:
        """Absolute path to the pack database.

        Configured relative paths resolve against apps/api, not the process cwd,
        so `uv run` from anywhere still finds the pack.
        """
        raw = Path(self.kestrel_db_path).expanduser()
        return raw if raw.is_absolute() else (API_DIR / raw).resolve()


settings = Settings()
