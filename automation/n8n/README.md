# n8n workflows

Four alerts over the huntpilot API. n8n runs as a service in `docker-compose.yml` and reaches the
API at `http://api:8000` on the compose network, so nothing is exposed and no data leaves the
machine. Self-hosted n8n is free; this adds no cost.

## The split

The API decides what is true — which applications have gone quiet, which postings are new, which
roles closed. n8n only decides *when to ask* and *where to send the answer*.

That line matters. Putting "14 days without a reply" inside a workflow node would be a second copy
of a rule living somewhere no test can reach, which is the same reason the dashboard does no
filtering of its own.

## Setup

1. Open <http://localhost:5678> and create the owner account. It is local only.
2. Make a Discord webhook: **Server → Edit Channel → Integrations → Webhooks → New Webhook**, copy
   the URL.
3. For each file here: **n8n → Workflows → Import from File**.
4. In the imported workflow, open **Post to Discord** and replace the placeholder URL with yours.
5. **Execute Workflow** to test against real data, then toggle **Active**.

## What each one does

| workflow | runs | says |
|---|---|---|
| `weekly-scorecard.json` | Sundays 09:00 | applications sent this week, how many were referrals, reply rate, how many have gone quiet |
| `new-postings.json` | every 6h | postings the sweep saw for the first time — applying inside 72 hours is the biggest lever a cold application has |
| `closed-roles-you-applied-to.json` | daily 09:00 | a role you applied to has come off its board. Stop waiting on it |
| `sweep-health.json` | daily 10:00 | the sweep failed, stalled, or a board would not load |

Three of the four are **silent when there is nothing to say**. A daily "nothing today" is how a
channel becomes wallpaper. The scorecard always sends, because an empty week is the most useful
thing it can report.

## Notes

- Use `http://api:8000`, never `localhost`. Inside the n8n container, `localhost` is n8n.
- `items` is always an array of `{json: record}` wrappers, one per record — never the raw response
  body. Every Code node here starts with `items.map(i => i.json)` for that reason.
- `new-postings.json` looks back 7 hours on a 6-hour schedule. The overlap is deliberate: an
  occasional repeat costs less than silently missing the posting that mattered.
- `closed-roles-you-applied-to.json` matches on URL, the only field both sides genuinely share, so
  an application logged without a link cannot be matched.
- Workflows live in the `n8n_data` volume. `docker compose down` keeps them; `down -v` deletes
  them, which is what these files are for.

`gen_flows.py` in the scratchpad generated these; the files are the artefact, edit them in the n8n
editor and re-export rather than hand-editing the JSON.
