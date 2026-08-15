import { handleCase } from "@/app/actions"
import type { MorningEvent, Priority } from "@/lib/api"

const TITLE: Record<string, string> = {
  cold_chain: "Warm chilled loads",
  late_delivery: "Late warehouses",
  stockout_refusal: "No stock",
  credit_refusal: "Credit holds",
  sku_short: "Short SKUs",
  credit_backlog: "Undecided credit notes",
  expiring_stock: "Stock that will expire first",
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

const FIRST_BATCH = 6

function CaseRow({
  item,
  eventPriority,
  asOf,
}: {
  item: MorningEvent["items"][number]
  eventPriority: Priority
  asOf: string
}) {
  const id = String(item.case_id ?? "")
  const ticked = Boolean(item.done)
  return (
    <li className="flex items-start justify-between gap-3">
      <span className={`min-w-0 text-sm ${ticked ? "text-muted-foreground" : ""}`}>
        <span className={ticked ? "line-through" : undefined}>
          {item.label ?? id}
        </span>
        {item.priority && item.priority !== eventPriority ? (
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
          <input type="hidden" name="as_of" value={asOf} />
          <input type="hidden" name="done" value={ticked ? "false" : "true"} />
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
}

function Category({
  event,
  day,
}: {
  event: MorningEvent
  day: string
}) {
  const undone = event.items.filter((item) => !item.done)
  const done = event.items.filter((item) => item.done)
  const actNow = undone.filter((item) => item.priority === "act").length
  const title = TITLE[event.kind] ?? event.headline
  const key = asOfKey(event, day)
  const first = undone.slice(0, FIRST_BATCH)
  const rest = undone.slice(FIRST_BATCH)

  return (
    <li className={`status ${TONE[event.priority] ?? ""}`}>
      <details>
        <summary className="flex cursor-pointer list-none items-baseline justify-between gap-3 [&::-webkit-details-marker]:hidden">
          <span className="flex min-w-0 items-baseline gap-3">
            <span className="w-8 shrink-0 text-xl font-semibold tabular-nums">
              {num(undone.length)}
            </span>
            <span className="font-semibold">{title}</span>
            {actNow > 0 && actNow < undone.length ? (
              <span className="shrink-0 text-sm text-breach">
                {num(actNow)} now
              </span>
            ) : null}
          </span>
          <span className="shrink-0 text-sm text-muted-foreground">
            {event.owner}
          </span>
        </summary>
        {/* Why this category is here and how it was measured. The API computes
            it per request; leaving it out was how the cold chain reasoning
            stopped reaching the screen. */}
        {event.detail ? (
          <p className="mt-2 text-sm text-muted-foreground">{event.detail}</p>
        ) : null}
        <ul className="mt-3 space-y-2.5">
          {first.map((item) => (
            <CaseRow
              key={String(item.case_id ?? item.label)}
              item={item}
              eventPriority={event.priority}
              asOf={key}
            />
          ))}
          {rest.length ? (
            <li>
              <details>
                <summary className="cursor-pointer list-none text-sm text-muted-foreground [&::-webkit-details-marker]:hidden">
                  {num(rest.length)} more
                </summary>
                <ul className="mt-2.5 space-y-2.5">
                  {rest.map((item) => (
                    <CaseRow
                      key={String(item.case_id ?? item.label)}
                      item={item}
                      eventPriority={event.priority}
                      asOf={key}
                    />
                  ))}
                </ul>
              </details>
            </li>
          ) : null}
          {done.length ? (
            <li className="pt-1 text-xs text-muted-foreground">
              {num(done.length)} marked done
              <ul className="mt-2 space-y-2.5">
                {done.map((item) => (
                  <CaseRow
                    key={String(item.case_id ?? item.label)}
                    item={item}
                    eventPriority={event.priority}
                    asOf={key}
                  />
                ))}
              </ul>
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
  const all = [...events, ...standing]
  const openCount = all.reduce(
    (n, event) => n + event.items.filter((item) => !item.done).length,
    0
  )
  const actNow = events.reduce(
    (n, event) =>
      n + event.items.filter((item) => item.priority === "act" && !item.done).length,
    0
  )

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
