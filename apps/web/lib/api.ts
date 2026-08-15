/**
 * Server-side reads of the Kestrel API.
 *
 * Every call is no-store: the point of the screen is what happened, not what
 * was cached. If the API is unreachable we return the error rather than
 * throwing, so the page can say so in plain words instead of showing a stack
 * trace — "if it does not open, I will not use it".
 */

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000"

export type ApiResult<T> =
  | { ok: true; data: T }
  | { ok: false; error: string; url: string }

async function get<T>(path: string): Promise<ApiResult<T>> {
  const url = `${BASE}${path}`
  try {
    const res = await fetch(url, { cache: "no-store" })
    if (!res.ok) {
      const body = await res.json().catch(() => null)
      const detail =
        body && typeof body === "object" && "detail" in body
          ? String((body as { detail: unknown }).detail)
          : `${res.status} ${res.statusText}`
      return { ok: false, error: detail, url }
    }
    return { ok: true, data: (await res.json()) as T }
  } catch {
    return {
      ok: false,
      error: `Cannot reach the API at ${BASE}. Start it with \`pnpm dev\`.`,
      url,
    }
  }
}

export type Priority = "act" | "decide" | "pattern"

export type EventItem = Record<string, string | number | boolean | null> & {
  case_id?: string
  label?: string
  done?: boolean
  note?: string
  priority?: Priority
}

export type MorningEvent = {
  kind: string
  severity: "breach" | "watch" | "info"
  headline: string
  owner: string
  detail: string
  items: EventItem[]
  population: number
  /** The worst case in this category. */
  priority: Priority
  /** Cases here that need doing this morning. */
  act_now: number
}

export type Morning = {
  as_of: string
  is_latest: boolean
  earliest: string
  latest: string
  region: string | null
  day: {
    orders: number
    units_short: number
    deliveries: number
    late_over_2h_by_delay_field: number
    late_over_2h_by_timestamps: number
  }
  events: MorningEvent[]
  /** Already true before the day started. Never merged into events. */
  standing: MorningEvent[]
  /** Tier labels come from the API so the screen never hardcodes them. */
  priorities: { id: Priority; label: string }[]
  notes: string[]
}

export type Fill = {
  window: { id: string; label: string; is_latest_complete: boolean }
  scope: { id: string; label: string; contested: string[] }
  service: {
    execution_pct: number | null
    availability_pct: number | null
    service_pct: number | null
    identity_holds: boolean
  }
  fill: { case_pct: number | null; each_pct: number | null }
  units_short: { shipped_short: number; never_shipped: number; total: number }
  exclusions: { excluded_outlets: unknown[]; total_orders_excluded: number }
}

export type OutletRow = {
  outlet_id: number
  outlet_name: string
  orders: number
  case_fill_pct: number | null
  units_short: number
}

export type Outlets = {
  by_units_short: OutletRow[]
  by_fill_pct: OutletRow[]
  overlap: number
  exposure: { by_units_short: number; by_fill_pct: number }
}

export type Money = {
  window: { id: string; label: string }
  dispatch_inr: number
  credit_notes: {
    settled_inr: number
    undecided_inr: number
    refused_inr: number
    exposed_inr: number
    raised_inr: number
    settled_n: number
    undecided_n: number
    refused_n: number
  }
  raised_pct: number | null
  /** False when the ratio is too small to carry a decision. Read the rupees. */
  ratio_is_material: boolean
  by_category: {
    category: string
    settled_inr: number
    undecided_inr: number
    notes_n: number
  }[]
  pending_queue: {
    notes_n: number
    value_inr: number
    oldest_date: string | null
    oldest_days: number | null
  }
  notes: string[]
}

export type Expiry = {
  as_of: string
  snapshot_date: string | null
  snapshot_age_days: number | null
  is_stale: boolean
  near_lines: number
  near_cases: number
  near_value_inr: number
  doomed_lines: number
  doomed_cases: number
  doomed_value_inr: number
  lines: {
    warehouse: string
    product: string
    batch: string
    on_hand_cases: number
    days_left: number
    days_of_cover: number
    value_inr: number
    cannot_sell: boolean
  }[]
  notes: string[]
}

const qs = (params: Record<string, string | undefined>) => {
  const q = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) if (v) q.set(k, v)
  const s = q.toString()
  return s ? `?${s}` : ""
}

export const getMorning = (region?: string, asOf?: string) =>
  get<Morning>(`/metrics/morning${qs({ region, as_of: asOf })}`)

export const getFill = (region?: string) =>
  get<Fill>(`/metrics/fill${qs({ region, scope: "attempted" })}`)

export const getOutlets = (region?: string, limit = 5) =>
  get<Outlets>(
    `/metrics/fill/outlets${qs({ region, scope: "attempted", limit: String(limit) })}`
  )

export const getMoney = (region?: string) =>
  get<Money>(`/metrics/money${qs({ region })}`)

export const getExpiry = (region?: string, asOf?: string, limit = 6) =>
  get<Expiry>(
    `/metrics/expiry${qs({ region, as_of: asOf, limit: String(limit) })}`
  )

export async function markHandled(
  caseId: string,
  asOf: string,
  done: boolean
): Promise<ApiResult<{ case_id: string; as_of: string; done: boolean }>> {
  const url = `${BASE}/metrics/morning/handle`
  try {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ case_id: caseId, as_of: asOf, done }),
    })
    if (!res.ok) {
      const body = await res.json().catch(() => null)
      const detail =
        body && typeof body === "object" && "detail" in body
          ? String((body as { detail: unknown }).detail)
          : `${res.status} ${res.statusText}`
      return { ok: false, error: detail, url }
    }
    return { ok: true, data: (await res.json()) as { case_id: string; as_of: string; done: boolean } }
  } catch {
    return {
      ok: false,
      error: `Cannot reach the API at ${BASE}. Start it with \`pnpm dev\`.`,
      url,
    }
  }
}
