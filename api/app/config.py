"""Application configuration, read from the environment."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_FILE = Path(__file__).resolve().parents[2] / ".env"

DEFAULT_PROFILE_FILE = Path(__file__).resolve().parent / "profile.json"
"""The committed profile: the search this repository is set up for out of the box.

It sits inside the package, beside the ``relevance`` and ``stack`` modules it configures, for two
reasons. It is the worked example a reader goes looking for once they know a profile exists, and
those modules are where they find out. And the api image is built from ``api/`` with only
``app/`` copied in, so a profile anywhere further up would be outside the build context — present
in a checkout, missing from every container, which is the worst of both.

Resolved from this file's own location rather than from the working directory, because the sweep
is run from the repo root, from ``api/``, by Celery and by pytest, and a relative default would
mean a different file each time.
"""


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

    profile_path: Path = DEFAULT_PROFILE_FILE
    """Which profile the filters are run against: locations, role families, stack, seniority.

    Settable like every other setting so that a second search — someone else's, or a wider one
    kept for comparison — is ``PROFILE_PATH=...`` rather than an edit to a tracked file. The
    default is the committed profile, so a fresh checkout filters the same way it always has
    without anything being set.
    """


settings = Settings()  # type: ignore[call-arg]
