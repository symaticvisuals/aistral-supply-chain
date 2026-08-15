import { handleCase } from "@/app/actions"
import type { MorningEvent } from "@/lib/api"

const TITLE: Record<string, string> = {
  cold_chain: "Warm deliveries",
  late_delivery: "Late warehouses",
  stockout_refusal: "No stock",
  credit_refusal: "Credit holds",
  sku_short: "Short SKUs",
  credit_backlog: "Undecided credit notes",
}

const TONE: Record<string, string> = {
  breach: "text-breach",
  watch: "text-watch",
  info: "text-muted-foreground",
}

const num = (n: number) => n.toLocaleString("en-IN")

function asOfKey(event: MorningEvent, day: string) {
  return event.kind === "credit_backlog" ? "standing" : day
}

function Category({
  event,
  day,
}: {
  event: MorningEvent
  day: string
}) {
  const remaining = event.items.filter((item) => !item.done).length
  const title = TITLE[event.kind] ?? event.headline
  const more = event.population > event.items.length
  const key = asOfKey(event, day)

  return (
    <li className={`status ${TONE[event.severity] ?? ""}`}>
      <details>
        <summary className="flex cursor-pointer list-none items-baseline justify-between gap-3 [&::-webkit-details-marker]:hidden">
          <span className="flex min-w-0 items-baseline gap-3">
            <span className="w-8 shrink-0 text-xl font-semibold tabular-nums">
              {num(remaining)}
            </span>
            <span className="font-semibold">{title}</span>
          </span>
          <span className="shrink-0 text-sm text-muted-foreground">
            {event.owner}
          </span>
        </summary>
        <ul className="mt-3 space-y-2.5">
          {event.items.map((item) => {
            const id = String(item.case_id ?? "")
            const ticked = Boolean(item.done)
            return (
              <li
                key={id || String(item.label)}
                className="flex items-start justify-between gap-3"
              >
                <span
                  className={`min-w-0 text-sm ${
                    ticked ? "text-muted-foreground" : ""
                  }`}
                >
                  <span className={ticked ? "line-through" : undefined}>
                    {item.label ?? id}
                  </span>
                  {item.note ? (
                    <span className="mt-0.5 block text-xs text-muted-foreground">
                      {item.note}
                    </span>
                  ) : null}
                </span>
                {id ? (
                  <form action={handleCase} className="shrink-0">
                    <input type="hidden" name="case_id" value={id} />
                    <input type="hidden" name="as_of" value={key} />
                    <input
                      type="hidden"
                      name="done"
                      value={ticked ? "false" : "true"}
                    />
                    <button
                      type="submit"
                      className="border border-border px-2 py-0.5 text-sm hover:bg-accent"
                    >
                      {ticked ? "Undo" : "Done"}
                    </button>
                  </form>
                ) : null}
              </li>
            )
          })}
          {more ? (
            <li className="text-sm text-muted-foreground">
              {num(event.population)} in all. These are the ones to work first.
            </li>
          ) : null}
        </ul>
      </details>
    </li>
  )
}

export function Queue({
  asOf,
  events,
  standing,
}: {
  asOf: string
  events: MorningEvent[]
  standing: MorningEvent[]
}) {
  const openCount = [...events, ...standing].reduce((n, event) => {
    return n + event.items.filter((item) => !item.done).length
  }, 0)

  return (
    <section className="flex h-full flex-col border border-border bg-card">
      <header className="flex items-baseline justify-between gap-3 border-b border-border px-5 py-3">
        <h2 className="text-lg font-semibold tracking-tight">
          Yesterday, to do
        </h2>
        <p className="text-sm text-muted-foreground">{openCount} open</p>
      </header>
      <div className="min-w-0 flex-1 px-5 py-4">
        {events.length ? (
          <ul className="space-y-3">
            {events.map((event) => (
              <Category key={event.kind} event={event} day={asOf} />
            ))}
          </ul>
        ) : (
          <p className="text-muted-foreground">
            Nothing broke on this day. An empty list is a real answer.
          </p>
        )}

        {standing.length ? (
          <div className="mt-6 border-t border-border pt-4">
            <p className="text-sm text-muted-foreground">Still open from before today</p>
            <ul className="mt-3 space-y-3">
              {standing.map((event) => (
                <Category key={event.kind} event={event} day={asOf} />
              ))}
            </ul>
          </div>
        ) : null}
      </div>
    </section>
  )
}
