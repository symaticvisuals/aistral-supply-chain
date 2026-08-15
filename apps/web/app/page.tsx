import Link from "next/link"

import { DayPicker } from "@/components/day-picker"
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
      <header className="flex items-baseline justify-between gap-3 border-b border-border px-5 py-3">
        <h2 className="text-lg font-semibold tracking-tight">{title}</h2>
        {meta ? <p className="eyebrow shrink-0">{meta}</p> : null}
      </header>
      <div className="min-w-0 flex-1 px-5 py-4">{children}</div>
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
        {failures.length} of 4 numbers did not load
      </p>
      <ul className="mt-1.5 space-y-1">
        {failures.map((f) => (
          <li key={f.url} className="text-sm">
            {f.error}
            <span className="mt-0.5 block text-xs text-muted-foreground">
              {f.url}
            </span>
          </li>
        ))}
      </ul>
      <p className="mt-2.5 text-sm text-muted-foreground">
        The rest of the page still shows whatever did load.
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
    <table className="w-full border-collapse text-[15px] tabular-nums">
      <thead>
        <tr className="border-b border-border">
          <th className="pb-2 text-left text-sm font-semibold text-muted-foreground">
            Shop
          </th>
          <th className="pb-2 text-right text-sm font-semibold text-muted-foreground">
            Orders
          </th>
          <th className="pb-2 text-right text-sm font-semibold text-muted-foreground">
            {metric === "fill" ? "Case fill" : "Pieces short"}
          </th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.outlet_id} className="border-b border-border/40">
            <td className="py-2.5">{r.outlet_name}</td>
            <td className="py-2.5 text-right text-muted-foreground">{r.orders}</td>
            <td
              className={`py-2.5 text-right font-semibold ${
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
      <header className="sticky top-0 z-10 border-b border-foreground bg-background/95 backdrop-blur">
        <div className="mx-auto flex max-w-[1100px] flex-wrap items-center gap-x-6 gap-y-3 px-6 py-3.5">
          <span className="text-xl font-semibold tracking-tight">Kestrel</span>
          {day ? (
            <span className="flex items-center gap-2">
              {day.as_of > day.earliest ? (
                <Link
                  href={href(region, shiftDay(day.as_of, -1))}
                  className="border border-border px-2 py-0.5 text-sm hover:bg-accent"
                  aria-label="Previous day"
                >
                  ‹
                </Link>
              ) : (
                <span className="border border-transparent px-2 py-0.5 text-sm text-muted-foreground/40">
                  ‹
                </span>
              )}
              <DayPicker
                asOf={day.as_of}
                earliest={day.earliest}
                latest={day.latest}
                region={region}
              />
              {day.as_of < day.latest ? (
                <Link
                  href={href(region, shiftDay(day.as_of, 1))}
                  className="border border-border px-2 py-0.5 text-sm hover:bg-accent"
                  aria-label="Next day"
                >
                  ›
                </Link>
              ) : (
                <span className="border border-transparent px-2 py-0.5 text-sm text-muted-foreground/40">
                  ›
                </span>
              )}
            </span>
          ) : null}
          <nav className="ml-auto flex flex-wrap items-center gap-1" aria-label="Region">
            {REGIONS.map((r) => {
              const active = (r.code ?? undefined) === region
              return (
                <Link
                  key={r.label}
                  href={href(r.code, asOf)}
                  className={`px-2.5 py-1 text-sm transition-colors ${
                    active
                      ? "bg-primary text-primary-foreground"
                      : "hover:bg-accent"
                  }`}
                >
                  {r.label}
                </Link>
              )
            })}
          </nav>
        </div>
      </header>

      <main className="mx-auto max-w-[1100px] space-y-8 px-6 py-8">
        {failures.length ? <Unreachable failures={failures} /> : null}

        <section className="grid gap-6 border-b border-border pb-6 sm:grid-cols-2 lg:grid-cols-4">
          <div>
            <p className="eyebrow">Case fill</p>
            <p className="figure mt-1 text-[2.4rem] text-watch">
              {num(q?.fill.case_pct, 1)}%
            </p>
            <p className="mt-1.5 text-sm text-muted-foreground">
              {q?.window.label ?? "This quarter"}
            </p>
          </div>
          <div>
            <p className="eyebrow">Pieces short</p>
            <p className="figure mt-1 text-[2.4rem] text-breach">
              {num(q?.units_short.shipped_short)}
            </p>
            <p className="mt-1.5 text-sm text-muted-foreground">
              Same shortfall, counted piece by piece
            </p>
          </div>
          <div>
            <p className="eyebrow">Yesterday</p>
            <p className="figure mt-1 text-[2.4rem]">{num(day?.day.orders)}</p>
            <p className="mt-1.5 text-sm text-muted-foreground">
              orders, {num(day?.day.units_short)} pieces short
            </p>
          </div>
          <div>
            <p className="eyebrow">Late over 2 hours</p>
            <p className="figure mt-1 text-[2.4rem] text-breach">
              {num(day?.day.late_over_2h_by_timestamps)}
            </p>
            <p className="mt-1.5 text-sm text-muted-foreground">
              The other clock says {num(day?.day.late_over_2h_by_delay_field)}.
              They do not agree.
            </p>
          </div>
        </section>

        {day ? (
          <Queue asOf={day.as_of} events={day.events} standing={day.standing} />
        ) : (
          <Panel title="Yesterday">
            <p className="text-muted-foreground">No data.</p>
          </Panel>
        )}

        <section className="grid gap-6 lg:grid-cols-2">
          <Panel title="Shops short on cases" meta="Lowest case fill">
            {outlets.ok ? (
              <OutletTable rows={outlets.data.by_fill_pct} metric="fill" />
            ) : (
              <p className="text-muted-foreground">No data.</p>
            )}
          </Panel>
          <Panel
            title="Shops short on pieces"
            meta={
              outlets.ok
                ? `${outlets.data.overlap} shops sit on both lists`
                : undefined
            }
          >
            {outlets.ok ? (
              <OutletTable rows={outlets.data.by_units_short} metric="short" />
            ) : (
              <p className="text-muted-foreground">No data.</p>
            )}
          </Panel>
        </section>

        <section className="grid gap-6 lg:grid-cols-3">
          <div className="lg:col-span-2">
            <Panel
              title="Credit notes"
              meta={m ? m.window.label : undefined}
            >
              {m ? (
                <>
                  <div className="grid gap-6 sm:grid-cols-3">
                    {creditTiles(m.credit_notes).map((t) => (
                      <div key={t.label}>
                        <p className="eyebrow">{t.label}</p>
                        <p className={`figure mt-1 text-[1.75rem] ${t.tone}`}>
                          {inr(t.value)}
                        </p>
                        <p className="mt-1 text-sm text-muted-foreground">
                          {num(t.notes)} notes
                        </p>
                      </div>
                    ))}
                  </div>
                  <p className="mt-4 text-sm text-muted-foreground">
                    Agreed is a loss. Undecided is still open. Refused is
                    neither. {inr(m.dispatch_inr)} went out this quarter, priced
                    on what arrived.
                    {m.ratio_is_material
                      ? ` Raised notes are ${num(m.raised_pct, 2)}% of that.`
                      : " The rupees are the number to watch, not the rate."}
                  </p>
                </>
              ) : (
                <p className="text-muted-foreground">No data.</p>
              )}
            </Panel>
          </div>

          <Panel title="By product type">
            {m && m.by_category.length ? (
              <table className="w-full border-collapse text-[15px] tabular-nums">
                <thead>
                  <tr className="border-b border-border">
                    <th className="pb-2 text-left text-sm font-semibold text-muted-foreground">
                      Type
                    </th>
                    <th className="pb-2 text-right text-sm font-semibold text-muted-foreground">
                      Agreed
                    </th>
                    <th className="pb-2 text-right text-sm font-semibold text-muted-foreground">
                      Open
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {m.by_category.map((c) => (
                    <tr key={c.category} className="border-b border-border/40">
                      <td className="py-2">{c.category}</td>
                      <td className="py-2 text-right text-breach">
                        {inr(c.settled_inr)}
                      </td>
                      <td className="py-2 text-right text-watch">
                        {inr(c.undecided_inr)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <p className="text-muted-foreground">No data.</p>
            )}
          </Panel>
        </section>
      </main>
    </div>
  )
}
