# Pinned to the minor version the project develops against, so a new Python release cannot change
# behaviour between a local run and a built image.
FROM python:3.12-slim

# uv is copied from its own published image rather than installed with pip, which avoids pulling a
# toolchain into the runtime layer.
COPY --from=ghcr.io/astral-sh/uv:0.12.0 /uv /bin/uv

WORKDIR /srv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/srv/.venv \
    PATH="/srv/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

# Dependencies are installed before the source is copied so a code change does not invalidate the
# dependency layer. --frozen fails rather than silently resolving something not in the lockfile.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY app ./app

# Runs as a non-root user: a container that only serves HTTP has no reason to be able to write to
# its own image. --system is deliberately not used: it restricts the uid to below SYS_UID_MAX
# (999), so pairing it with 1001 silently fails to create the account and the container then dies
# with "unable to find user".
RUN useradd --create-home --uid 1001 huntpilot && chown -R huntpilot /srv
USER huntpilot

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
