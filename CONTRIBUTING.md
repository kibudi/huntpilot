# Contributing

A learning project, so it is small and opinionated. Issues and pull requests are welcome. The two
conventions at the bottom are firm — they are unusual enough that they are worth reading before you
write anything.

## Setup

You need Python 3.12 or newer, Node 22 or newer, and a MongoDB connection string. Atlas M0 is free
and is what this was built against; a local `mongod` works too.

Copy the template and fill it in:

```sh
cp .env.example .env
```

`.env` is gitignored and must stay that way. Never put a real connection string in a tracked file.

Then install both sides:

```sh
cd api && uv sync
cd web && npm install
```

Running the two services directly gives hot reload:

```sh
cd api && uv run uvicorn app.main:app --port 8000
cd web && npm run dev
```

Vite proxies `/api` to port 8000, so the browser sees one origin either way.

## Checks

These are exactly what CI runs. The API and the dashboard are checked independently, because they
fail for unrelated reasons and one should not hide the other.

```sh
cd api
uv run ruff check app tests
uv run mypy app tests         # strict
uv run pytest

cd web
npm run lint                  # oxlint
npm run build                 # tsc -b && vite build
```

Run all five before opening a pull request. `npm run build` type-checks before it bundles, so it is
the frontend's only type check — there are no frontend tests.

## Tests need a live MongoDB

Beanie has no in-memory backend: `init_beanie` must reach a real server before a `Document` can even
be constructed, so most of the suite needs a database rather than a fixture. It runs against a
throwaway database, `huntpilot_test`, and drops it afterwards — point `MONGODB_URI` at a cluster
where that is safe.

The suite cannot run in parallel. `init_beanie` binds the document classes process-globally, so
tests are isolated by emptying collections between them instead of by scoping a connection per test.
Do not reach for `pytest-xdist`.

`tests/test_stack.py`, `tests/test_relevance.py`, and the normalising and token-guessing tests in
`tests/test_boards.py` are pure functions and run with no database at all. Everything else needs one.

## Two conventions

**Docstrings are the documentation, and there are no inline comments.** Every module, class and
public function gets a docstring, and rationale that would have been an inline comment goes in the
docstring of the thing it explains — including the reasoning behind a non-obvious choice, which is
the part most worth writing down. A comment sits next to the code and goes stale unnoticed; a
docstring travels with the thing it describes and shows up wherever that thing is read. Files with
no docstrings — Compose, the workflow, the Dockerfiles — keep comments, and the same rule applies:
say why, not what.

**A test must fail when the bug it guards is reintroduced.** Having written the test, mutate the
source so the bug is back, run the test, confirm it fails, then restore the source. A test that
passes either way is worse than none, because it reports coverage that does not exist. Say in the
pull request which mutation you checked against.

Two smaller ones: type hints on every function signature, and tests land with the feature they
cover rather than after it.

## Pull requests

Keep them to one reviewable change. Say what changed, why, and how you verified it — the template
asks for these, including the mutation check for any new test.
