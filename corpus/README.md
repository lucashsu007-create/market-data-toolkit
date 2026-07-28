# Notice corpus

Real, public vendor/exchange notices used to evaluate the pipeline. This replaces the five
self-authored scenarios the demo originally shipped with.

## Licensing / what is stored

Notice text is the exchange's copyright. Records therefore store:

- `source_url` — the public notice, so anyone can verify against the original
- bibliographic fields (venue, id, published date, title)
- `summary` — **a paraphrase written for this corpus, not the notice text**
- `quote` — at most 25 words of original wording, for test fixtures only

Full notice text is never committed.

## Provenance & honesty notes

- **Nasdaq** records were collected from nasdaqtrader.com (RSS + notice pages) and are the richest.
- **CME** blocks automated access to cmegroup.com; CME records were reconstructed from public search
  metadata and carry `"depth": "shallow"`. Their summaries are correspondingly thinner.
- **Euronext** was planned but its notices sit behind the Connect portal login; none are included.
  (Records support adding manually saved ones later.)
- Ground-truth labels in `labels.json` are authored by the repo author from the notice content —
  a stated limitation, not a hidden one.

## Files

- `notices/*.json` — one record per notice
- `labels.json` — ground truth per notice id: notice type, affected estate feeds, priority, escalate
- `split.json` — frozen dev/held-out split, generated (seeded) **before any router rule was written**;
  rules may be tuned only on `dev`, `held_out` is scored once

## Record shape

```json
{
  "id": "nasdaq-dtn2026-15",
  "venue": "nasdaq",
  "source_url": "http://www.nasdaqtrader.com/TraderNews.aspx?id=DTN2026-15",
  "published": "2026-07-24",
  "notice_no": "DTN2026-15",
  "title": "...",
  "summary": "...paraphrase...",
  "quote": "<=25 words of original text",
  "effective": "2026-10-05",
  "depth": "full" | "shallow"
}
```

The router sees `title` + `summary` (+ `venue` withheld — venue detection is part of its job).
