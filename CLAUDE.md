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

FastAPI · MongoDB Atlas (M0 free tier) · Beanie ODM · `uv` · Celery + Redis 7 · `discord.py` ·
React + Vite + TypeScript + Tailwind · `pytest` · `ruff` · `mypy` · Docker + Compose · `kind` ·
GitHub Actions · Terraform (LocalStack; real AWS only for free-tier-safe S3/ECR/IAM)

MongoDB replaced Postgres/SQLAlchemy/Alembic. There is no migrations layer — Mongo is schemaless,
so document shape is enforced by Beanie's Pydantic validation, not by the database.

## Layout

```
docs/     plan.html — reveal.js deck of the overall idea, kept current as steps land
api/      FastAPI, sole owner of the DB   (not built yet)
web/      React + Vite dashboard          (not built yet)
worker/   Celery + Beat                   (not built yet)
bot/      discord.py slash commands       (not built yet)
infra/    Dockerfiles, k8s/, terraform/   (not built yet)
```

`api/` is the only service that touches MongoDB. `web/` and `bot/` go through the API.

## Configuration

`.env` at the repo root holds `MONGODB_URI` and `MONGODB_DB`. It is gitignored; `.env.example` is
the committed template. Never write real credentials into any tracked file.

## Commands

```sh
cd api
uv sync                 # create .venv and install deps
uv run mypy app         # type check (strict)
uv run ruff check app   # lint
uv run pytest           # tests (none yet)
```

The venv lives at `api/.venv`; `.vscode/settings.json` points the editor at it.

Beanie documents cannot be instantiated before `init_beanie()` runs, so model tests need a live
MongoDB — there is no in-memory equivalent. Point tests at a throwaway database and drop it after.

Open `docs/plan.html` in a browser to review the plan. This section grows as services land.

## Preferences added along the way

<!-- Append your own conventions and best practices here as you find them. -->
