# Decisions

## 1 · What we built

One screen, one day, not a quarter — a quarter is a board number and barely moves,
and the complaint is about yesterday. The day appears twice, boxes for Divya and
pieces for Rakesh, because both are correct and hiding either restarts the
argument. Regional managers get it filtered; Q1 sits on it for the board. Beside
it: credit notes against what shipped, and stock that will expire before it sells.
We read the data first, and two of the numbers the brief asks for turned out to be
unanswerable.

## 2 · Ordering the work

A list of what broke is not a morning. Each case is tiered by one question — **can
what I do this morning still change the outcome?** Act before noon, decide today,
or a pattern to watch.

We did not score them. A warm load is spoiled rupees, a refusal is pieces never
sent, a late delivery lost nothing because the goods arrived. Those do not add up,
so we do not add them up; one blended urgency number is the same dishonesty as
blending case fill with piece fill. Within a tier we rank on the case's own
exposure and print it, so Divya can disagree and still see why.

Ticking a case off writes to a shared file, so it leaves everyone's queue, not one
browser. No login, so we record that a case was handled, never who by.

## 3 · What we did not build

- **OTIF.** Nothing in eighteen months arrived complete; the tile would read zero.
- **On-time.** The two lateness records agree on one delivery in eight.
- **Competitor prices.** A second system: scrape, then match SKUs.
- **Freight per case.** Carrier bills carry no order number; a rupee cannot reach
  a shop.
- **Ask-anything.** Only as honest as the layer beneath it.
- **Login and tabs.** One screen was the ask.

## 4 · What we assumed

- Fill is cases *and* pieces, converted per line on pack size at order time — not
  the product master, which moves when a SKU is repacked.
- A cancellation counts against us when we caused it. Stock, clearly; a credit
  hold is arguable, so it is one named setting the screen calls contested.
- **Four columns carry no signal and we ignore all four**: both reason codes, the
  excursion flag, the ageing bucket. Each is a finding at `/metrics/quality`,
  computed per request rather than asserted here.
- **Cold chain is measured, not read.** An excursion is chilled stock delivered
  above 8C. Past 12C it is gone regardless of duration; 8–12C turns on how long,
  which nothing records — hence two tiers.
- **Expiry** flags stock whose cover exceeds the days left. Cover tops out at 40
  here, so a slow mover with three months left is invisible. Counted weekly.
- Test outlets are dropped and named. The year starts in April. "Today" is the
  last day in the data.

## 5 · Next two weeks

- Excursions per hundred chilled deliveries, so cold chain is a trend too.
- Freight at warehouse level, labelled for what it cannot answer.
- Who ticked a case off — which needs identity, which needs a login.

## 6 · What breaks first

- **Load.** Numbers are computed live, no cache. A quarter over half a million
  lines takes a tenth of a second; a hundred people at nine would feel it. The fix
  is a nightly rollup by day and region.
- **The date.** It comes from the data. On a live feed "yesterday" must mean
  yesterday, which means deciding when a day closes.
- **One field.** Cases-to-pieces rests on pack size at order time. If a source
  starts sending nulls, the two numbers drift apart quietly.
