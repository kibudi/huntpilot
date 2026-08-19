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
    redis_url: str = "redis://127.0.0.1:6379/0"
    """Where Celery queues tasks and stores their results.

    Defaults to a local Redis on its standard port so that importing the worker, running the
    tests, or sweeping by hand never depends on this being set — nothing here connects until a
    task is actually queued. Compose overrides it with the service name.
    """


settings = Settings()  # type: ignore[call-arg]
