# Kestrel Control Tower

One morning screen for Kestrel Provisions: which shops did not get what they ordered, and where cash leaked. Not a BI suite.

## Cold start (one machine)

Needs Node 20+, [pnpm](https://pnpm.io) 10, Python 3.12+, [uv](https://docs.astral.sh/uv/).

The SQLite file is **not** in git. Put the assignment pack next to this repo (or set the path):

```text
FDE_Assignment_Pack_Kestrel_v1.1/data/kestrel_ops.db
```

```bash
pnpm install
cd apps/api && uv sync && cd ../..
cp apps/web/.env.example apps/web/.env
cp apps/api/.env.example apps/api/.env
# edit apps/api/.env if the pack is not at ../../FDE_Assignment_Pack_Kestrel_v1.1
pnpm dev
```

| | |
|---|---|
| Screen | http://localhost:3000 |
| API | http://127.0.0.1:8000/health |
| API docs | http://127.0.0.1:8000/docs |

```bash
pnpm lint
pnpm typecheck
```

Optional later (not required to open the screen):

```bash
# carrier bills
python3 FDE_Assignment_Pack_Kestrel_v1.1/partner_api/server.py

# competitor site
cd FDE_Assignment_Pack_Kestrel_v1.1/bazaarpulse_site && python3 -m http.server 8080
```

Do not commit `kestrel_ops.db` or the assignment pack.

## What this repo is

Turborepo: Next.js in `apps/web`, FastAPI in `apps/api`, shared UI in `packages/ui`.

Read `DECISIONS.md` first. Working notes on the brief are in `understanding.md`.
