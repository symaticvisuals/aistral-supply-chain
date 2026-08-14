<!-- BEGIN:nextjs-agent-rules -->
# This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` before writing any code. Heed deprecation notices.
<!-- END:nextjs-agent-rules -->

# Kestrel

FDE take-home: one morning control tower. Graders read `DECISIONS.md` first, then `README.md`. Product reading of the brief is `understanding.md`.

## Commands

Use **pnpm**. Root scripts only call `turbo run`.

```bash
pnpm dev          # web :3000 + api :8000
pnpm lint
pnpm typecheck
pnpm --filter web build
cd apps/api && uv sync && uv run ruff check .
```

Add UI: `pnpm dlx shadcn@latest add <name> -c apps/web` (lands in `packages/ui`).

## Hard rules (from the brief)

- A small honest system beats a large half-working one.
- Do not commit `kestrel_ops.db` or `FDE_Assignment_Pack_Kestrel_v1.1/`.
- Do not scrape anything except the shipped BazaarPulse site.
- Do not use real client data.
- Do not silently "fix" dirty data. Notice it and surface it.
- Do not add auth, login, or a multi-tab BI shell.
- Show case fill **and** each fill. Do not pick one.
- Keep `DECISIONS.md` to one page. Update it when a judgement changes.

## Layout

```
apps/web          Next.js screen
apps/api          FastAPI
packages/ui       shadcn + theme
```
