# Kestrel API

FastAPI service for the morning control tower. Read-only over the pack SQLite
file; no precompute, no cache, no build step.

```bash
uv sync
pnpm --filter api dev
```

| Endpoint | What it answers |
|---|---|
| `GET /health` | Is the pack database reachable, and how much is in it |
| `GET /metrics/morning` | **Yesterday as a queue of things to do**, each with an owner |
| `GET /metrics/fill` | Service split into execution × availability, all three unit definitions, units short by cause, the scope ladder, and every excluded row by name |
| `GET /metrics/fill/outlets` | Worst outlets by units short **and** by fill %, both lists, with their overlap |
| `GET /metrics/quality` | What the data actually does, computed per request |

Query params: `window` (`fy26q1`, `YYYY-MM-DD:YYYY-MM-DD`, or omit for the latest
complete fiscal quarter), `as_of` (`YYYY-MM-DD`, morning view only), `region`
(code, e.g. `WST`), `scope` (`attempted` · `stockout` · `kestrel_fault` ·
`all_cancels`), `limit`.

## Two tiers, on purpose

`/metrics/morning` reports **events**; everything else reports **rates**. About
130 of 624 active outlets order on a given day, so an outlet orders roughly once
every five days and a daily per-shop fill rate is one order's luck. At that grain
rates are noise and events are facts — a warm truck happened, an order was
refused, and neither needs a sample size. Rates need the quarter behind them.

The pack is frozen, so `as_of` cannot come from the clock. It defaults to the last
day with data and is overridable, which is also what makes a past morning
reproducible:

```bash
curl "localhost:8000/metrics/morning?as_of=2026-04-14&region=WST"
```

## Why service is two numbers

`service = execution × availability`, exactly. Execution is what the warehouse
floor did with orders we accepted; availability is how much of the ask we agreed
to ship at all. They have different owners, so a single blended rate cannot say
which one moved — and "which of these four numbers is wrong" is the problem this
service exists to end. Both factors ship on every response.

`case_only_pct` is what a `qty_uom = 'CASE'` filter produces. It is computed so
it can be recognised, never used: it silently discards every EACH line.

## Interfaces this does not offer, on purpose

- **No OTIF.** Zero orders in the pack are delivered in full, so the in-full leg
  is a constant zero. Reported as a blocking finding on `/metrics/quality`.
- **No warehouse or route geography.** An outlet's route belongs to its own
  region only ~21% of the time, so "which DC is worst" has no honest answer.
  `region` means the outlet's own region.
- **No leading short-reason.** The reason codes are uniform noise.

## The competitor scrape

Prices come from BazaarPulse, which is a web server, so they are fetched by a
separate command and written to `data/bazaarpulse.db`. The screen reads the
snapshot and says how old it is. Scraping at request time would mean a morning
where the control tower does not open because someone else's site is down.

```bash
cd FDE_Assignment_Pack_Kestrel_v1.1/bazaarpulse_site && python3 -m http.server 8080
cd apps/api && uv run python -m app.bazaarpulse
```

`--listings-only` skips the per-listing price history (70s instead of 21
minutes). `--crawl-delay` overrides the 1s the site asks for; whatever was used
is written into the run row, so a scrape that ignored the site's terms cannot be
mistaken afterwards for one that did not.

Four things about that site are worth knowing, and the scraper reports all four
as findings rather than handling them quietly:

- **Every city prices differently.** Bengaluru puts the number in
  `data-price-paise` and shows "Price on card" as text — 292 listings a
  text-only parser loses without erroring.
- **Bengaluru and Chennai pager links lie.** They point at `index.html?p=13`;
  the server ignores the query string and returns page 1. The real page is
  `index_p13.html`. So no page is trusted: each states which page it is, and one
  that disagrees with the request is discarded. 32 pages were discarded.
- **8 listings appear on two pages.** Counting cards gives 1,145; counting
  listings gives 1,137.
- **`/internal/margin-sheet.html` exists and robots.txt disallows it.** It is
  the most commercially interesting page on the site and it was not fetched.

`OPTIONS` and freight are not here. Freight is the next slice.
