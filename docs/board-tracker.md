# Board-diff tracker — design note

Status: see **Built so far** below. Written 2026-08-16, kept current as steps land.

## What this is

A scheduled job that watches company job boards over time and reports the **deltas**, not the
listings. It answers questions no job board answers: did the role I applied to get filled, is
this company reposting the same job every six weeks, has anything opened at a company I care
about.

## Why this and not a lead-finder

A lead-finder — search boards, score fit, surface matches — is a solved problem. `Zync`
(github.com/Or-Hason/Zync) already does it, and the manual version is well covered by the
Hebrew AI job-search deck this project borrows prompts from.

Nothing in either tracks postings *over time*. Board state history is only valuable if
something records it continuously, and it is only actionable if it can be joined against an
application log — which this project already has. That combination is the differentiator.

Fit-scoring and CV tailoring are deliberately out of scope here. They are on-demand, single-shot,
and need no state, so they belong in a Claude skill rather than in this service.

## Research findings

Verified 2026-08-13 against live endpoints. These numbers drove the design; re-check before
trusting them.

### Sources that work

Public JSON, no auth, no scraping:

| ATS | Endpoint |
|---|---|
| Greenhouse | `https://boards-api.greenhouse.io/v1/boards/{token}/jobs` |
| Lever | `https://api.lever.co/v0/postings/{token}?mode=json` |
| Ashby | `https://api.ashbyhq.com/posting-api/job-board/{token}` |

Greenhouse payloads carry `title`, `location.name`, `absolute_url`, `updated_at` and a stable
`id`, so location filtering costs nothing.

### Sources that do not work

- **Comeet** is a JavaScript app. Every URL returns HTTP 200 whether or not it exists (confirmed
  with deliberately bogus company slugs), and the careers API rejects requests without a
  per-company token that is injected client-side. Needs a headless browser. Deferred.
- **Search-engine dorking** cannot be automated. DuckDuckGo and Bing both return 200 with zero
  result links. The technique works for a human in a browser; programmatically it needs a paid
  or keyed search API.

### Watchlist can be built for free

42% of company names resolve to a live board by guessing the token from the name (29 of 69 tried,
re-verified 2026-08-18 through `resolve`). No search API is required — a list of company names is
enough. 28 boards are now on the watchlist.

The list can grow passively: every company logged as an application gets run through the
resolver, and joins the watchlist if it has a board.

### The funnel is brutal

Across 14 companies, one snapshot:

| Stage | Count |
|---|---|
| All open postings | 279 |
| Located in Israel | 78 |
| Engineering roles | 23 |
| Senior / lead / staff | 15 |
| Mid or unmarked | 7 |
| Junior | 1 |

Roughly one or two genuinely applicable roles per sweep at this watchlist size. **Watchlist size
is the binding constraint**, not the pipeline. Seniority cannot be filtered on titles — most
unmarked roles still demand years of experience in the body, which is what the paid model call
is for.

## Data model

Two new Beanie documents alongside `Application`.

### `companies` — the watchlist

`name`, `ats` (greenhouse | lever | ashby), `token`, `last_swept_at`, `created_at`, `updated_at`.

Designed but not built: `active`, `watch_all` (report any opening at this company regardless of
fit) and `consecutive_failures`. They belong with the scheduled job that needs them, so they are
not on the document yet.

### `postings` — board state over time

`company_token`, `ats`, `external_id`, `url`, `title`, `location_raw`, `description`,
`first_seen_at`, `last_seen_at`, `missed_sweeps`, `closed_at`, `status`.

`description` is the posting body as plain text. The text is stored rather than the conclusions
drawn from it: those conclusions depend on a vocabulary that changes as it is corrected, so
storing the text keeps every posting rescorable, while storing a score freezes it at the moment
of the sweep. `fingerprint` was for the dedupe gate and does not exist.

**One document per posting, never one per sweep.** A sweep bumps `last_seen_at`; it does not
append. Closure is inferred from absence, so the collection grows with the market rather than
with time.

`external_id` is the ATS's own job id and is the stable key. `url` can change; the id does not.

## The sweep

Gates are numbered and each logs how many postings it dropped. When a digest comes back empty,
the counts say which gate did it. Gates 0–5 are free; only survivors reach gate 6.

0. **Fetch** — pull every watchlisted board. *A failing board is skipped, never fatal: a sweep
   that dies halfway leaves the boards it never reached looking absent, and absence is how
   closure is inferred.* Per-board failure counting is not built.
1. **Normalise** — map three different ATS shapes onto one internal record.
3. **Location** — `in_scope_location`: a list of Israeli city spellings, or advertised as remote.
   Country names alone are not enough — roughly half the Israeli postings never say "Israel".
5. **Title** — `role_family`, a **whitelist** of five families (fullstack, backend, frontend,
   platform, software), plus `states_seniority`, which drops any title saying senior, staff,
   principal, lead, head, director, VP, architect, manager, or a roman numeral. A whitelist
   rather than a subtraction: QA, data, security, embedded and game roles are all engineering and
   none are a match, so they never appear rather than being excluded one at a time as they turn up.
5b. **Stack and years** — `fits_stack` reads the description, free. It scores the share of the
   technologies a posting names that are already known (`MIN_TECH_SCORE`, 0.8) and drops anything
   asking for more than `MAX_YEARS` (3). A posting naming no technologies is unscored and dropped:
   keeping the unjudgeable ones refills the shortlist this gate exists to produce.
2. **Reconcile** — known and present bumps `last_seen_at`; unknown and present is new; known and
   absent counts towards closure. **This gate is the product.** It runs last, over the survivors.

Gate 4 (**dedupe** — TF-IDF against recent postings, to catch a repost at a new URL) and gate 6
(**judge** — a paid model call) are designed and not built. Gate 5b was not in the original plan,
and does for free most of what gate 6 was budgeted to pay for, which is why gate 6 has not been
needed yet.

## Digest

**Not built.** Delivered by the Discord bot once it exists; console output before that.

1. **Closed on you** — applied, and the posting has disappeared. Stop waiting.
2. **Still open, still silent** — applied 30+ days ago, posting still live.
3. **Reposted** — same role listed again. Churn, or an unrealistic spec.
4. **New and worth a look** — gate 6 survivors, with the reason.
5. **Watched company opened something** — any role at a `watch_all` company.

Sections 1 through 3 exist nowhere else.

## Known pitfalls

- **A posting can vanish for one sweep** on a board glitch. Require two or three consecutive
  misses before marking closed, or the digest cries wolf.
- **The first sweep sees everything as new.** It must seed silently or it fires a 200-item digest.
- **`updated_at` churns constantly** on these boards and carries no signal. Ignore it.
- **A guessed token can belong to a different company.** `vast` resolved to a Californian rocket
  company, not the Israeli storage one; only its posting locations gave it away. A resolved board
  is a candidate, not a fact — `resolve` reports and a person confirms before `watch` stores.
- **Payload sizes vary wildly** — one Ashby board returned 2.2 MB. Stream and discard.

## Cost

Every gate that exists is free and local; nothing in the tracker has yet called a paid model.
Gate 6 would be the only cost, and only for the postings that survived every free filter — cents
per sweep, not per posting.

Extraction and structuring can move to a local model (Ollama) if the paid surface should be
zero; judgement is the part worth paying for.

Only structured requirements and skill metadata should leave the machine. Raw CV text and
personal details stay local.

## Built so far

1. The two documents, plus `fetch_board` and `reconcile` — gates 0 to 2.
2. `resolve` — a company name to the board token it answers on, verified against the live APIs.
3. `watch` — a confirmed board onto the watchlist, idempotent on `(ats, token)`.
4. `relevance.relevant` — gates 3, 5 and 5b, applied to a board's postings *before* `reconcile`
   sees them, so reconcile stays pure and everything stored has passed the same filter.
5. `stack.tech_match` — the technology vocabulary and the years-of-experience reader behind gate
   5b. The vocabulary deliberately includes technologies that are *not* known, because a score
   measured only against familiar words rates every posting perfectly.
6. `GET /api/postings` and a Board tab on the dashboard, which reports each posting's region
   so the dashboard never keeps its own copy of the location rules.

Seeded 2026-08-18: 28 boards, 4 of which currently list nothing.

First full sweep, 2026-08-18: **1,026 postings**, 290 of them in Israel. Stored unfiltered, which
made the dashboard unreadable — the first row was a UX Design Lead.

Filtering moved to storage on 2026-08-19. Storing only what passes gates 3 and 5 left **130
postings** across 22 companies, down from 1,026; adding gate 5b the same day left **7**.

The cost of that decision, accepted deliberately: a posting that is never stored can never be
reported as closed, so the "closed on you" signal only covers roles the filter keeps. That blind
spot widened when the seniority and stack gates moved to storage time — the filter now also drops
anything whose title states seniority, anything asking for more than three years, and anything
under 80% technology overlap. Widening it again is a one-constant change, and because the
description is stored rather than the score, everything already kept can be rescored without
fetching a single board.

The second sweep, 2026-08-19, produced the first real deltas: two roles that did not exist the
day before, one of them a **Junior Software Engineer at Cato Networks**. That is the feature
working — a junior opening surfaced the morning it appeared.

### Locations are free text, and the boards disagree

The 1,026 postings carry **243 distinct location strings**. Israel alone appears as `Tel Aviv`
(71), `Tel Aviv, Israel` (46), `Tel Aviv District, Israel` (42), `TLV` (26), `Herzliya` (16),
`Tel Aviv-Yafo, Gush Dan, Israel` (12) and more. Gate 3 is therefore a list of known variants,
not a country match, and a plain substring search misses a quarter of the Israeli roles by
skipping `TLV`.

## Next step

The digest, and gate 4. Still no model call.

## Open questions

- Where the company-name list comes from beyond the confirmed 28 and passive growth.
- Whether Comeet is worth a headless browser later, given it covers Israeli companies the three
  supported systems miss.
- JobMaster (jobmaster.co.il) covers Israeli companies not on any of the three ATSes. Zync
  scrapes it with BeautifulSoup; fragile and ToS-shaky, so noted rather than adopted.

## Prior art

- `Zync` — github.com/Or-Hason/Zync. Independently arrived at the same free-gates-before-paid-call
  funnel. Source of the TF-IDF dedupe and local-extraction ideas here.
- The Hebrew AI job-search deck by Shahar (Imagen) — source of the alternate-job-titles idea, the
  ATS-scoped dorking technique, and the anti-hallucination rules intended for the gate 6 prompt
  ("base every claim only on what is in the CV", "verify each posting is live", "do not guess").
