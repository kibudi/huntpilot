**What changed**

**Why**

**How it was verified**

- [ ] `uv run ruff check app tests`
- [ ] `uv run mypy app tests`
- [ ] `uv run pytest`
- [ ] `npm run lint` and `npm run build` (if the dashboard changed)

For any new test: which mutation to the source you made it fail against, and that you restored the
source afterwards. A test that passes with the bug reintroduced is not a test.

Anything a reviewer should look at first, or that you are unsure about.
