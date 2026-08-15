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

export type EventItem = Record<string, string | number | null>

export type MorningEvent = {
  kind: string
  severity: "breach" | "watch" | "info"
  headline: string
  owner: string
  detail: string
  items: EventItem[]
}

export type Morning = {
  as_of: string
  is_latest: boolean
  region: string | null
  day: {
    orders: number
    units_short: number
    deliveries: number
    late_over_2h_by_delay_field: number
    late_over_2h_by_timestamps: number
  }
  events: MorningEvent[]
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
