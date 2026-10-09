# Passage search

`GET /search/passages` searches stored `document_text` with Postgres full-text.
It is lexical search over the english `tsvector` already stored on each passage.
It does not embed text and it does not call a model.

The GIN index `ix_document_text_tsv` was created with the core schema.
This endpoint adds no migration.

## Query

`q` is required. It is parsed with `websearch_to_tsquery('english', q)`:

- `cross-border` matches the stemmed tokens.
- `"cross-border volume"` keeps those tokens in order.
- `volume OR incentives` matches either term.
- `volume -incentives` matches volume and drops passages that also contain incentives.

A query made only of stopwords (`the`) matches nothing and returns an empty
`hits` list. A blank `q` is rejected with 422.

Matches are ordered by `ts_rank_cd` descending, then `publication_ts`
descending, then passage id ascending. `limit` defaults to 20 and cannot
exceed 100. The response does not include a total count.

Each hit returns the stored page and character span (`char_start`, `char_end`)
and the passage `text` those offsets point at, plus a short `ts_headline`
snippet with matches wrapped in `<b>` tags.

## Filters

All filters are optional. The response echoes the filters that were applied.
`cutoff_ts` is echoed after it is normalized to UTC.

| Parameter | Effect |
| --- | --- |
| `company` | Exact match on `source.company` after trimming whitespace. `Visa` does not match `visa`. |
| `period_start`, `period_end` | Keep a source only when both of its period bounds are set and the period overlaps the requested range: `period_end >= period_start` (request) and `period_start <= period_end` (request). Passing either bound drops sources whose period is null. |
| `cutoff_ts` | Keep `source.publication_ts <= cutoff_ts`. A document published at the cutoff is included. |

A cutoff with no timezone is read as UTC. A date with no time is midnight UTC
at the start of that day, so a release later the same day is excluded. Pass an
explicit end-of-day timestamp when the whole calendar day should be included.

`period_start` later than `period_end` is rejected with 422.

```bash
curl -sG 'http://127.0.0.1:8000/search/passages' \
  --data-urlencode 'q=cross-border' \
  --data-urlencode 'company=visa' \
  --data-urlencode 'cutoff_ts=2024-07-23T00:00:00Z'
```

Superseded sources are not collapsed: a passage still matches when a later
source points at it through `supersedes_id`. See `docs/limitations.md`.
