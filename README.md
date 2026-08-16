# Kestrel Control Tower

One morning screen for Kestrel Provisions: which shops did not get what they
ordered, and where cash leaked. Not a BI suite.

Read `DECISIONS.md` first — what we built, what we did not, and why.

## 1 · Before you start

| Needs | Version |
|---|---|
| [Node](https://nodejs.org) | 20+ |
| [pnpm](https://pnpm.io) | 10 |
| Python | 3.12+ |
| [uv](https://docs.astral.sh/uv/) | any recent |

## 2 · Put the database where the app can find it

The SQLite file is **not** in git. Unzip the assignment pack inside this repo so
the database lands here:

```text
<repo root>/FDE_Assignment_Pack_Kestrel_v1.1/data/kestrel_ops.db
```

Keeping it anywhere else is fine — put an absolute path in `KESTREL_DB_PATH` in
`apps/api/.env` (step 3). Nothing else needs changing.

## 3 · Run it

```bash
pnpm install
cd apps/api && uv sync && cd ../..

cp apps/api/.env.example apps/api/.env
cp apps/web/.env.example apps/web/.env
# edit apps/api/.env only if the pack is not at the path above

pnpm dev
```

| | |
|---|---|
| Screen | http://localhost:3000 |
| API health | http://127.0.0.1:8000/health |
| API docs | http://127.0.0.1:8000/docs |

## 4 · Check it worked

Open `/health`. It names the exact path it tried and whether it opened:

```json
{ "status": "ok",
  "database": { "path": "/…/kestrel_ops.db", "connected": true,
                "orders": 83671, "latest_order": "2026-06-30" } }
```

`"status": "no_database"` means the path in `apps/api/.env` is wrong, and the
message says which path was tried. The screen stays usable either way — any
panel that cannot load names itself and the URL that failed, rather than
showing a blank page.

## 5 · Databases

Three, and only the first has to exist. All are configured in `apps/api/.env`;
paths there are relative to `apps/api/`, so `uv run` works from anywhere.

| What | Setting | Notes |
|---|---|---|
| Assignment pack | `KESTREL_DB_PATH` | Opened **read-only**, never written to. You supply it. |
| Handled cases | `HANDLED_DB_PATH` | Created on the first tick. Separate file so the pack stays read-only. |
| Competitor prices | `BAZAARPULSE_DB_PATH` | Written by the scraper below. Absent until then. |

None of them are committed — `.gitignore` excludes `*.db`.

## 6 · Optional: competitor prices

Not needed to open the screen. Without it, the shelf-price column reads "no
shelf prices collected" and says so on the panel.

```bash
# terminal 1 — serve the site that ships with the pack
cd FDE_Assignment_Pack_Kestrel_v1.1/bazaarpulse_site && python3 -m http.server 8080

# terminal 2 — scrape it
cd apps/api
uv run python -m app.bazaarpulse                  # ~21 min, obeys the site's 1s crawl delay
uv run python -m app.bazaarpulse --listings-only  # ~70s, skips per-listing price history
```

This writes `apps/api/data/bazaarpulse.db` and is never run at request time —
prices come from someone else's web server, and the screen has to open whether
or not that server is up. See `apps/api/README.md` for what the site does to a
scraper and how much of that is reported rather than silently handled.

## 7 · Checks

```bash
pnpm lint
pnpm typecheck
```

## 8 · Layout

Turborepo. Next.js in `apps/web`, FastAPI in `apps/api`, shared UI in
`packages/ui`. Working notes on reading the brief are in `understanding.md`.

Do not commit `kestrel_ops.db` or the assignment pack.
