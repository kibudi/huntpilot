---
name: Bug report
about: Something behaves differently from what the README or the design notes describe
title: ''
labels: bug
assignees: ''
---

**What happened, and what you expected instead**

**How to reproduce**

**Which part** — API, dashboard, sweep, worker, or Compose.

**If it is the sweep or the board tracker:**

- Which ATS and which board — Greenhouse, Lever or Ashby, plus the company token.
- What the sweep summary reported. Paste the JSON from `cd api && uv run python -m app.sweep`;
  `boards_failed` and the `failures` list say whether a board was skipped rather than empty, which
  is usually the difference between a bug and a board being down.

**How you are running it** — `docker compose up`, or the two services directly. Python and Node
versions if directly.
