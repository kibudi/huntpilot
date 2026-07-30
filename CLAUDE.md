# CLAUDE.md

Job-application tracker. Web dashboard + Discord bot over one FastAPI backend, with a Celery worker.
Learning project — the DevOps layers matter as much as the app. Runs locally, free, no cloud spend.

## Rules

- **Build in small steps.** One reviewable piece at a time. Never drop several layers at once, and
  never scaffold ahead of the current step.
- **Do not swap stack choices** (listed below) without asking first.
- **Docstrings are the documentation. No inline comments.** Every module, class, and public
  function gets a docstring; rationale that would have been an inline comment goes in the
  docstring of the thing it explains.
- Type hints on all function signatures.
- Tests live next to the feature they cover, written as the feature lands.

## Stack

FastAPI · SQLAlchemy 2.0 · Alembic · `uv` · Postgres 16 · Celery + Redis 7 · `discord.py` ·
React + Vite + TypeScript + Tailwind · `pytest` · `ruff` · Docker + Compose · `kind` ·
GitHub Actions · Terraform (LocalStack; real AWS only for free-tier-safe S3/ECR/IAM)

## Layout

```
docs/     plan.html — reveal.js deck of the overall idea, kept current as steps land
api/      FastAPI, sole owner of the DB   (not built yet)
web/      React + Vite dashboard          (not built yet)
worker/   Celery + Beat                   (not built yet)
bot/      discord.py slash commands       (not built yet)
infra/    Dockerfiles, k8s/, terraform/   (not built yet)
```

`api/` is the only service that touches Postgres. `web/` and `bot/` go through the API.

## Commands

```sh
cd api
uv sync                 # create .venv and install deps
uv run mypy app         # type check (strict)
uv run ruff check app   # lint
uv run pytest           # tests (none yet)
```

The venv lives at `api/.venv`; `.vscode/settings.json` points the editor at it.

Open `docs/plan.html` in a browser to review the plan. This section grows as services land.

## Preferences added along the way

<!-- Append your own conventions and best practices here as you find them. -->
