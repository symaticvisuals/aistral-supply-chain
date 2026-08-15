import { handleCase } from "@/app/actions"
import type { MorningEvent, Priority } from "@/lib/api"

const TITLE: Record<string, string> = {
  cold_chain: "Warm chilled loads",
  late_delivery: "Late warehouses",
  stockout_refusal: "No stock",
  credit_refusal: "Credit holds",
  sku_short: "Short SKUs",
  credit_backlog: "Undecided credit notes",
}

// The tier drives the colour, not the category. A case that can still be
// changed this morning reads hot wherever it sits.
const TONE: Record<Priority, string> = {
  act: "text-breach",
  decide: "text-watch",
  pattern: "text-muted-foreground",
}

// Why the tier exists, in Divya's terms rather than the rule's.
const REASON: Record<Priority, string> = {
  act: "This morning still changes the outcome.",
  decide: "The loss is booked. Someone has to rule on it.",
  pattern: "Nothing to fix case by case. Watch the trend.",
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
    <li className={`status ${TONE[event.priority] ?? ""}`}>
      <details>
        <summary className="flex cursor-pointer list-none items-baseline justify-between gap-3 [&::-webkit-details-marker]:hidden">
          <span className="flex min-w-0 items-baseline gap-3">
            <span className="w-8 shrink-0 text-xl font-semibold tabular-nums">
              {num(remaining)}
            </span>
            <span className="font-semibold">{title}</span>
            {/* Only worth saying when the category is mixed — otherwise the
                tier heading above already said it. */}
            {event.act_now > 0 && event.act_now < event.items.length ? (
              <span className="shrink-0 text-sm text-breach">
                {num(event.act_now)} now
              </span>
            ) : null}
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
                  {/* Flag a case only where it is not what the tier heading
                      promised — a cooler load inside a hot category. */}
                  {item.priority && item.priority !== event.priority ? (
                    <span className="ml-2 text-xs text-muted-foreground">
                      {item.priority === "act" ? "act now" : "look"}
                    </span>
                  ) : null}
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
  priorities,
}: {
  asOf: string
  events: MorningEvent[]
  standing: MorningEvent[]
  priorities: { id: Priority; label: string }[]
}) {
  const openCount = [...events, ...standing].reduce((n, event) => {
    return n + event.items.filter((item) => !item.done).length
  }, 0)
  const actNow = events.reduce((n, e) => n + e.act_now, 0)

  return (
    <section className="flex h-full flex-col border border-border bg-card">
      <header className="flex items-baseline justify-between gap-3 border-b border-border px-5 py-3">
        <h2 className="text-lg font-semibold tracking-tight">
          Yesterday, to do
        </h2>
        <p className="text-sm text-muted-foreground">
          {actNow ? (
            <span className="text-breach">{actNow} before noon</span>
          ) : null}
          {actNow ? " · " : ""}
          {openCount} open
        </p>
      </header>
      <div className="min-w-0 flex-1 px-5 py-4">
        {events.length ? (
          <div className="space-y-5">
            {priorities.map(({ id, label }) => {
              const inTier = events.filter((e) => e.priority === id)
              if (!inTier.length) return null
              return (
                <div key={id}>
                  <p
                    className={`text-sm font-semibold ${TONE[id]}`}
                    title={REASON[id]}
                  >
                    {label}
                  </p>
                  <p className="mt-0.5 text-xs text-muted-foreground">
                    {REASON[id]}
                  </p>
                  <ul className="mt-2.5 space-y-3">
                    {inTier.map((event) => (
                      <Category key={event.kind} event={event} day={asOf} />
                    ))}
                  </ul>
                </div>
              )
            })}
          </div>
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
