"""Application configuration, read from the environment."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    """Runtime settings.

    Values come from the process environment first and from the repo-root ``.env`` second, so a
    container can override anything at deploy time without the file being present.
    """

    model_config = SettingsConfigDict(env_file=ENV_FILE, extra="ignore")

    mongodb_uri: str
    mongodb_db: str = "huntpilot"


settings = Settings()  # type: ignore[call-arg]
