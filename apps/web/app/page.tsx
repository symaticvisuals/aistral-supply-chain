import Link from "next/link"

import { Queue } from "@/components/queue"
import {
  getFill,
  getMoney,
  getMorning,
  getOutlets,
  type ApiResult,
  type Money,
  type OutletRow,
} from "@/lib/api"

// Everything on this page is read at request time from the database.
export const dynamic = "force-dynamic"

const REGIONS = [
  { code: undefined, label: "All" },
  { code: "WST", label: "West" },
  { code: "NTH", label: "North" },
  { code: "STH", label: "South" },
  { code: "EST", label: "East" },
  { code: "CEN", label: "Central" },
]

const num = (n: number | null | undefined, digits = 0) =>
  n === null || n === undefined
    ? "—"
    : n.toLocaleString("en-IN", {
        minimumFractionDigits: digits,
        maximumFractionDigits: digits,
      })

function shiftDay(iso: string, days: number) {
  const d = new Date(`${iso}T00:00:00Z`)
  d.setUTCDate(d.getUTCDate() + days)
  return d.toISOString().slice(0, 10)
}

function href(region?: string, asOf?: string) {
  const q = new URLSearchParams()
  if (region) q.set("region", region)
  if (asOf) q.set("as_of", asOf)
  const s = q.toString()
  return s ? `/?${s}` : "/"
}

function Panel({
  title,
  meta,
  children,
}: {
  title: string
  meta?: string
  children: React.ReactNode
}) {
  return (
    <section className="flex h-full flex-col border border-border bg-card">
      <header className="flex items-baseline justify-between gap-3 border-b border-border px-4 py-2.5">
        <h2 className="text-[0.95rem] font-semibold tracking-tight">{title}</h2>
        {meta ? <p className="eyebrow shrink-0">{meta}</p> : null}
      </header>
      <div className="min-w-0 flex-1 px-4 py-3">{children}</div>
    </section>
  )
}

/** Name every call that failed and the exact URL, so it is diagnosable. */
function Unreachable({
  failures,
}: {
  failures: { error: string; url: string }[]
}) {
  return (
    <div className="border border-breach bg-card p-5">
      <p className="eyebrow text-breach">
        {failures.length} of 4 API calls failed
      </p>
      <ul className="mt-1.5 space-y-1">
        {failures.map((f) => (
          <li key={f.url} className="text-sm">
            {f.error}
            <span className="block font-mono text-[11px] text-muted-foreground">
              {f.url}
            </span>
          </li>
        ))}
      </ul>
      <p className="mt-2.5 text-xs text-muted-foreground">
        Panels below still show whatever did load. If the API is running, restart
        it — <code className="font-mono">pnpm dev</code> — and reload.
      </p>
    </div>
  )
}

/** Rupees, whole. The paisa on a credit note never changes a decision. */
const inr = (n: number | null | undefined) =>
  n === null || n === undefined
    ? "—"
    : `₹${n.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`

/** Agreed is a loss, undecided is exposure, refused is neither. Three tones. */
function creditTiles(c: Money["credit_notes"]) {
  return [
    { label: "Agreed", value: c.settled_inr, notes: c.settled_n,
      tone: "text-breach" },
    { label: "Undecided", value: c.undecided_inr, notes: c.undecided_n,
      tone: "text-watch" },
    { label: "Refused", value: c.refused_inr, notes: c.refused_n,
      tone: "text-muted-foreground" },
  ]
}

function OutletTable({
  rows,
  metric,
}: {
  rows: OutletRow[]
  metric: "fill" | "short"
}) {
  return (
    <table className="w-full border-collapse font-mono text-[11px] tabular-nums">
      <thead>
        <tr className="border-b border-foreground">
          <th className="pb-1 text-left font-medium text-muted-foreground">
            Outlet
          </th>
          <th className="pb-1 text-right font-medium text-muted-foreground">
            Orders
          </th>
          <th className="pb-1 text-right font-medium text-muted-foreground">
            {metric === "fill" ? "Case fill" : "Units short"}
          </th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.outlet_id} className="border-b border-border/50">
            <td className="py-1.5">{r.outlet_name}</td>
            <td className="py-1.5 text-right text-muted-foreground">{r.orders}</td>
            <td
              className={`py-1.5 text-right ${
                metric === "fill" ? "text-watch" : "text-breach"
              }`}
            >
              {metric === "fill"
                ? `${num(r.case_fill_pct, 1)}%`
                : num(r.units_short)}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

export default async function Page({
  searchParams,
}: {
  searchParams: Promise<{ region?: string; as_of?: string }>
}) {
  const { region, as_of: asOf } = await searchParams
  const calls = [
    getMorning(region, asOf),
    getFill(region),
    getOutlets(region, 5),
    getMoney(region),
  ] as const
  const [morning, fill, outlets, money] = await Promise.all(calls)

  const day = morning.ok ? morning.data : null
  const q = fill.ok ? fill.data : null
  const m = money.ok ? money.data : null
  const failures = [morning, fill, outlets, money]
    .filter((r): r is Extract<ApiResult<never>, { ok: false }> => !r.ok)
    .map(({ error, url }) => ({ error, url }))

  return (
    <div className="min-h-dvh">
      <header className="sticky top-0 z-10 border-b-2 border-foreground bg-background/95 backdrop-blur">
        <div className="mx-auto flex max-w-[1400px] flex-wrap items-center gap-x-6 gap-y-2 px-6 py-2.5">
          <span className="figure text-2xl uppercase">Kestrel control tower</span>
          {day ? (
            <span className="flex items-center gap-1.5">
              <Link
                href={href(region, shiftDay(day.as_of, -1))}
                className="eyebrow border border-border px-1.5 py-0.5 hover:bg-accent"
              >
                ‹
              </Link>
              <span className="eyebrow">
                {day.as_of}
                {day.is_latest ? " · latest" : ""}
              </span>
              <Link
                href={href(region, shiftDay(day.as_of, 1))}
                className="eyebrow border border-border px-1.5 py-0.5 hover:bg-accent"
              >
                ›
              </Link>
            </span>
          ) : null}
          <div className="ml-auto flex flex-wrap items-center gap-1.5">
            <span className="eyebrow mr-1">Region</span>
            {REGIONS.map((r) => {
              const active = (r.code ?? undefined) === region
              return (
                <Link
                  key={r.label}
                  href={href(r.code, asOf)}
                  className={`border px-2 py-1 font-mono text-[11px] transition-colors ${
                    active
                      ? "border-primary bg-primary text-primary-foreground"
                      : "border-foreground hover:bg-foreground hover:text-background"
                  }`}
                >
                  {r.label}
                </Link>
              )
            })}
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-[1400px] space-y-4 px-6 py-5">
        {failures.length ? <Unreachable failures={failures} /> : null}

        <section className="grid gap-px border border-border bg-border sm:grid-cols-2 lg:grid-cols-4">
          <div className="bg-card p-4">
            <p className="eyebrow">Case fill · {q?.window.label ?? "—"}</p>
            <p className="figure mt-2 text-4xl text-watch">
              {num(q?.fill.case_pct, 1)}%
            </p>
            <p className="mt-2 font-mono text-[11px] text-muted-foreground">
              Divya · commits in cases
            </p>
            <p className="mt-0.5 text-xs text-muted-foreground">
              each fill {num(q?.fill.each_pct, 1)}% on the same rows
            </p>
          </div>
          <div className="bg-card p-4">
            <p className="eyebrow">Units short · quarter</p>
            <p className="figure mt-2 text-4xl text-breach">
              {num(q?.units_short.shipped_short)}
            </p>
            <p className="mt-2 font-mono text-[11px] text-muted-foreground">
              Rakesh · fined in eaches
            </p>
            <p className="mt-0.5 text-xs text-muted-foreground">
              every unit is invoiced against
            </p>
          </div>
          <div className="bg-card p-4">
            <p className="eyebrow">Yesterday · {day?.as_of ?? "—"}</p>
            <p className="figure mt-2 text-4xl">{num(day?.day.orders)}</p>
            <p className="mt-2 font-mono text-[11px] text-muted-foreground">
              orders · {num(day?.day.units_short)} units short
            </p>
            <p className="mt-0.5 text-xs text-muted-foreground">
              {num(day?.day.deliveries)} drops
            </p>
          </div>
          <div className="bg-card p-4">
            <p className="eyebrow">Late over 2h · yesterday</p>
            <p className="figure mt-2 text-4xl text-breach">
              {num(day?.day.late_over_2h_by_timestamps)}
            </p>
            <p className="mt-2 font-mono text-[11px] text-muted-foreground">
              by planned vs actual
            </p>
            <p className="mt-0.5 text-xs text-muted-foreground">
              delay_minutes says {num(day?.day.late_over_2h_by_delay_field)} — the
              two sources disagree
            </p>
          </div>
        </section>

        <section className="grid gap-4 lg:grid-cols-3">
          <div className="lg:col-span-2">
            {day ? (
              <Queue
                asOf={day.as_of}
                events={day.events}
                standing={day.standing}
              />
            ) : (
              <Panel title="Yesterday, as things to do">
                <p className="text-sm text-muted-foreground">No data.</p>
              </Panel>
            )}
          </div>

          <Panel title="Why two numbers" meta="Cases vs eaches">
            <p className="text-sm">
              A line ordered in bottles barely moves a box-weighted average, and
              a line ordered in boxes barely moves a bottle-weighted one. Same
              rows, same shortfall, different denominator.
            </p>
            {q ? (
              <p className="mt-3 font-mono text-[11px] text-muted-foreground">
                execution {num(q.service.execution_pct, 2)}% × availability{" "}
                {num(q.service.availability_pct, 2)}% = service{" "}
                {num(q.service.service_pct, 2)}%
                <br />
                {q.exclusions.total_orders_excluded.toLocaleString()} orders
                excluded, all named by the API.
              </p>
            ) : null}
          </Panel>
        </section>

        <section className="grid gap-4 lg:grid-cols-2">
          <Panel title="Divya would call" meta="Lowest case fill">
            {outlets.ok ? (
              <OutletTable rows={outlets.data.by_fill_pct} metric="fill" />
            ) : (
              <p className="text-sm text-muted-foreground">No data.</p>
            )}
          </Panel>
          <Panel
            title="Rakesh would call"
            meta={outlets.ok ? `${outlets.data.overlap} shared` : undefined}
          >
            {outlets.ok ? (
              <OutletTable rows={outlets.data.by_units_short} metric="short" />
            ) : (
              <p className="text-sm text-muted-foreground">No data.</p>
            )}
          </Panel>
        </section>

        <section className="grid gap-4 lg:grid-cols-3">
          <div className="lg:col-span-2">
            <Panel
              title="Credit notes against dispatch"
              meta={m ? m.window.label : undefined}
            >
              {m ? (
                <>
                  <div className="grid gap-px border border-border bg-border sm:grid-cols-3">
                    {creditTiles(m.credit_notes).map((t) => (
                      <div key={t.label} className="bg-panel p-3">
                        <p className="eyebrow">{t.label}</p>
                        <p className={`figure mt-1 text-2xl ${t.tone}`}>
                          {inr(t.value)}
                        </p>
                        <p className="mt-0.5 font-mono text-[11px] text-muted-foreground">
                          {num(t.notes)} notes
                        </p>
                      </div>
                    ))}
                  </div>
                  <p className="mt-3 text-sm">
                    A rejected note is not a loss and an undecided one is not a
                    decision, so none of the three is blended away.
                  </p>
                  <p className="mt-2 font-mono text-[11px] text-muted-foreground">
                    {inr(m.dispatch_inr)} dispatched — priced on what was
                    delivered, not what was ordered.
                    <br />
                    Raised is {num(m.raised_pct, 2)}% of that
                    {m.ratio_is_material
                      ? "."
                      : ", too small to watch as a rate. The rupees are the number."}
                  </p>
                </>
              ) : (
                <p className="text-sm text-muted-foreground">No data.</p>
              )}
            </Panel>
          </div>

          <Panel
            title="By category"
            meta={m ? `${m.by_category.length} categories` : undefined}
          >
            {m && m.by_category.length ? (
              <>
                <table className="w-full border-collapse font-mono text-[11px] tabular-nums">
                  <thead>
                    <tr className="border-b border-foreground">
                      <th className="pb-1 text-left font-medium text-muted-foreground">
                        Category
                      </th>
                      <th className="pb-1 text-right font-medium text-muted-foreground">
                        Agreed
                      </th>
                      <th className="pb-1 text-right font-medium text-muted-foreground">
                        Undecided
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {m.by_category.map((c) => (
                      <tr key={c.category} className="border-b border-border/50">
                        <td className="py-1.5">{c.category}</td>
                        <td className="py-1.5 text-right text-breach">
                          {inr(c.settled_inr)}
                        </td>
                        <td className="py-1.5 text-right text-watch">
                          {inr(c.undecided_inr)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <p className="mt-2.5 text-xs text-muted-foreground">
                  Shown in rupees, not as a share of each category&rsquo;s own
                  dispatch. They sit inside a narrow band, and a percentage would
                  dress that flatness up as a ranking.
                </p>
              </>
            ) : (
              <p className="text-sm text-muted-foreground">No data.</p>
            )}
          </Panel>
        </section>
      </main>
    </div>
  )
}
