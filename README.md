# huntpilot

A job-application tracker. One backend, a web dashboard, and — eventually — a Discord bot, so
tracking an application takes a slash command rather than opening a spreadsheet you stop updating
after two weeks.

Built as a learning project: the DevOps layers matter as much as the app, and everything runs
locally and free.

## Status

**Working:** the API, the dashboard, and containerisation. You can add applications, move them
through the pipeline, search, filter and sort.

| | |
|---|---|
| API | FastAPI + Beanie ODM on MongoDB Atlas, 5 endpoints, 50 tests |
| Dashboard | React 19 + TypeScript + Tailwind v4, one screen, inline status editing |
| Containers | `docker compose up` runs both |

**Not built:** Discord bot, Celery worker, CI, Kubernetes, Terraform.

## Quick start

Requires Docker and a MongoDB connection string.

Create `.env` in the repo root:

```
MONGODB_URI=mongodb+srv://<user>:<password>@<cluster>.<id>.mongodb.net/?retryWrites=true&w=majority
MONGODB_DB=huntpilot
```

Then:

```sh
docker compose up
```

and open <http://localhost:5173>.

Compose reads that file on the host and passes the values as environment variables. Nothing is
baked into an image, so the built images carry no credentials.

## Development

Running the two services directly gives you hot reload:

```sh
cd api && uv sync && uv run uvicorn app.main:app --port 8000
cd web && npm install && npm run dev
```

Vite proxies `/api` to port 8000, so the browser sees one origin either way.

```sh
cd api
uv run pytest                 # 50 tests; needs a live MongoDB
uv run mypy app tests         # strict
uv run ruff check app tests

cd web
npm run build                 # tsc -b && vite build
```

## Architecture

```
          ┌──────────────┐        ┌──────────────┐
          │ web (React)  │        │ bot (Discord)│  not built
          └──────┬───────┘        └──────┬───────┘
                 │ HTTP                  │ HTTP
                 └───────────┬───────────┘
                             ▼
                     ┌───────────────┐
                     │ api (FastAPI) │
                     └───────┬───────┘
                             │ Beanie
                             ▼
                     ┌───────────────┐
                     │ MongoDB Atlas │
                     └───────────────┘
```

`api/` is the only service that touches the database. In the container image, nginx serves the
built dashboard and proxies `/api` to the API service, which is why the client can call bare
`/api` paths in both development and production.

```
api/app/     config.py  db.py  models.py  schemas.py  main.py
api/tests/   conftest.py and one file per area
web/src/     App.tsx  api.ts  types.ts  state.ts  format.ts  components/
docs/        plan.html — reveal.js deck of the original plan
```

## API

| method | path | |
|---|---|---|
| `GET` | `/health` | process is up; does not check the database |
| `GET` | `/api/applications` | all applications, most recently updated first |
| `POST` | `/api/applications` | create one; `409` if that `url` is already tracked |
| `PATCH` | `/api/applications/{id}` | change one; only fields sent are written |
| `DELETE` | `/api/applications/{id}` | remove one permanently; `204`, or `404` if already gone |

## Design notes

**Outcomes are pipeline states, not a separate field.** `Status` is
`saved → applied → interview → offer | rejected | ghosted`. An application therefore cannot claim
an outcome it has not reached, and there is no cross-field constraint to enforce.

**Two schemas, not one.** `ApplicationCreate` forbids `id`, `created_at` and `updated_at`;
`ApplicationRead` marks them required. The same fields are optional on the way in and guaranteed
on the way out, which one class cannot express.

**MongoDB has no server-side defaults or on-update.** `updated_at` is set by the API on every
write. A write that bypasses the API leaves it stale.

**A posting link is unique, but only when there is one.** Two applications sharing a `url` are the
same job recorded twice, so the database rejects the second. The index is *partial* rather than
plain, because agency roles and undisclosed employers genuinely have no link and are stored as
`""` — a plain unique index would read every blank as a duplicate of the others and refuse to
build at all. Uniqueness is enforced by the index rather than a lookup before the insert, so two
requests arriving together cannot both pass a check and then both write.

**Timestamps are timezone-aware.** BSON stores no offset, so the client is created with
`tz_aware=True`. Without it, timestamps serialise with no `Z` and a client in another zone reads
them as local time.

## Known limitations

- No pagination; the list endpoint returns everything
- Required strings accept `""`, and free text has no maximum length, so a payload over BSON's
  16 MB limit fails as a 500 rather than a 422
- No frontend tests
- Tests need a live MongoDB — Beanie has no in-memory backend — and cannot run in parallel,
  because `init_beanie` binds document classes process-globally

## Origin

The plan deck in `docs/plan.html` describes the original intent, including the DevOps layers still
to come. It predates the switch from PostgreSQL to MongoDB in some details.
