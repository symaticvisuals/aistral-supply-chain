import Link from "next/link"

const WEEK = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

function pad(n: number) {
  return String(n).padStart(2, "0")
}

function isoDay(year: number, monthIndex: number, day: number) {
  return `${year}-${pad(monthIndex + 1)}-${pad(day)}`
}

function monthKey(year: number, monthIndex: number) {
  return `${year}-${pad(monthIndex + 1)}`
}

function monthLabel(year: number, monthIndex: number) {
  return new Date(Date.UTC(year, monthIndex, 1)).toLocaleDateString("en-IN", {
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  })
}

function prettyDay(iso: string) {
  return new Date(`${iso}T00:00:00Z`).toLocaleDateString("en-IN", {
    day: "numeric",
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  })
}

function monthsInRange(earliest: string, latest: string) {
  const months: { year: number; monthIndex: number; key: string }[] = []
  let year = Number(earliest.slice(0, 4))
  let monthIndex = Number(earliest.slice(5, 7)) - 1
  const endYear = Number(latest.slice(0, 4))
  const endMonth = Number(latest.slice(5, 7)) - 1
  while (year < endYear || (year === endYear && monthIndex <= endMonth)) {
    months.push({ year, monthIndex, key: monthKey(year, monthIndex) })
    monthIndex += 1
    if (monthIndex === 12) {
      monthIndex = 0
      year += 1
    }
  }
  return months
}

function monthCells(year: number, monthIndex: number) {
  const firstWeekday =
    (new Date(Date.UTC(year, monthIndex, 1)).getUTCDay() + 6) % 7
  const daysInMonth = new Date(Date.UTC(year, monthIndex + 1, 0)).getUTCDate()
  return [
    ...Array.from({ length: firstWeekday }, () => null),
    ...Array.from({ length: daysInMonth }, (_, i) => i + 1),
  ]
}

function dayHref(region: string | undefined, asOf: string) {
  const q = new URLSearchParams()
  if (region) q.set("region", region)
  q.set("as_of", asOf)
  return `/?${q.toString()}`
}

export function DayPicker({
  asOf,
  earliest,
  latest,
  region,
}: {
  asOf: string
  earliest: string
  latest: string
  region?: string
}) {
  const months = monthsInRange(earliest, latest)
  const selectedMonth = asOf.slice(0, 7)

  return (
    <details className="relative">
      <summary className="cursor-pointer list-none border border-border bg-card px-2.5 py-0.5 text-sm font-semibold hover:bg-accent [&::-webkit-details-marker]:hidden">
        {prettyDay(asOf)}
      </summary>
      <div
        className="absolute top-full left-0 z-20 mt-1 w-[18.5rem] border border-foreground bg-card p-3"
        role="dialog"
        aria-label="Pick a day"
      >
        {months.map((month, i) => {
          const prev = months[i - 1]
          const next = months[i + 1]
          const cells = monthCells(month.year, month.monthIndex)
          return (
            <div key={month.key}>
              <input
                type="radio"
                name="kestrel-cal"
                id={`cal-${month.key}`}
                className="peer sr-only"
                defaultChecked={month.key === selectedMonth}
              />
              <div className="hidden peer-checked:block">
                <div className="mb-2 flex items-center justify-between">
                  {prev ? (
                    <label
                      htmlFor={`cal-${prev.key}`}
                      className="cursor-pointer border border-border px-2 py-0.5 text-sm hover:bg-accent"
                    >
                      ‹
                    </label>
                  ) : (
                    <span className="px-2 py-0.5 text-sm text-muted-foreground/40">
                      ‹
                    </span>
                  )}
                  <p className="text-sm font-semibold">
                    {monthLabel(month.year, month.monthIndex)}
                  </p>
                  {next ? (
                    <label
                      htmlFor={`cal-${next.key}`}
                      className="cursor-pointer border border-border px-2 py-0.5 text-sm hover:bg-accent"
                    >
                      ›
                    </label>
                  ) : (
                    <span className="px-2 py-0.5 text-sm text-muted-foreground/40">
                      ›
                    </span>
                  )}
                </div>
                <div className="grid grid-cols-7 text-center text-xs text-muted-foreground">
                  {WEEK.map((d) => (
                    <span key={d} className="py-1">
                      {d}
                    </span>
                  ))}
                </div>
                <div className="grid grid-cols-7 text-center text-sm">
                  {cells.map((day, di) => {
                    if (day === null) return <span key={`e-${month.key}-${di}`} />
                    const iso = isoDay(month.year, month.monthIndex, day)
                    const allowed = iso >= earliest && iso <= latest
                    const current = iso === asOf
                    if (!allowed) {
                      return (
                        <span
                          key={iso}
                          className="py-1.5 text-muted-foreground/40"
                        >
                          {day}
                        </span>
                      )
                    }
                    return (
                      <Link
                        key={iso}
                        href={dayHref(region, iso)}
                        prefetch
                        className={`py-1.5 hover:bg-accent ${
                          current ? "bg-primary text-primary-foreground" : ""
                        }`}
                      >
                        {day}
                      </Link>
                    )
                  })}
                </div>
              </div>
            </div>
          )
        })}
      </div>
    </details>
  )
}
