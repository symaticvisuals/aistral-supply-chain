# Decisions

## 1 · What we built

One screen, one day, not a quarter — a quarter is a board number and barely moves,
and the complaint is about yesterday. The day appears twice, boxes for Divya and
pieces for Rakesh, because both are correct and hiding either restarts the
argument. Regional managers get it filtered; Q1 sits on it for the board. Beside
it: credit notes against what shipped, and stock that will expire before it sells.

## 2 · Ordering the work

A list of what broke is not a morning. Each case is tiered by one question — **can
what I do this morning still change the outcome?** Act before noon, decide today,
or a pattern to watch.

We did not score them. A warm load is spoiled rupees, a refusal is pieces never
sent, a late delivery lost nothing because the goods arrived. Those do not add up,
so we do not add them up; one blended urgency number is the same dishonesty as
blending case fill with piece fill. Within a tier we rank on the case's own
exposure and print it, so Divya can disagree and still see why.

Ticking a case off is shared, so it leaves everyone's queue rather than one
browser. No login, so we record that a case was handled, never who by.

## 3 · What we did not build

- **OTIF.** Nothing in eighteen months arrived complete; the tile would read zero.
- **On-time.** The two lateness records agree on one delivery in eight.
- **A price panel.** The tracker is not a competitor tracker: all 1,137 listings
  are SKUs we distribute, and none of the five chains is an outlet of ours, so
  brand against brand would be us against us. What is left is one column on the
  expiry panel — the lowest price shops charge, which is what says whether a
  markdown has room — and a count of listings sold above the printed MRP beside
  the credit notes. Divya's fourth ask is answered and then declined: the gap is
  1.2 points across four cities, so no city ranking.
- **A price-movement alert.** Lag-1 correlation −0.202 on six observations is
  what pure noise gives; "cut its price this week" is last week's dice.
- **Freight per case.** Carrier bills carry no order number; a rupee cannot reach
  a shop.
- **Ask-anything.** Only as honest as the layer beneath it.
- **Login and tabs.** One screen was the ask.

## 4 · What we assumed

Where the brief was silent we chose, and the third column is the part worth
arguing with.

| We assumed | Because | If it is wrong |
|---|---|---|
| Fill is cases **and** pieces | Divya commits in cases, modern trade fines on pieces | One side of the argument comes back |
| Pack size comes from the order line, not the product master | The master moves when a SKU is repacked | Every historic conversion shifts silently |
| A stockout cancel is ours; a credit hold is arguable | Stock is supply, credit is finance | One named setting — the ladder prices it at 1.35 pts of service |
| Four columns carry no signal, so nothing is sliced by them | Each fires at the same rate whatever the row | We would be ranking noise and calling it a cause |
| Chilled above 8C is an excursion, above 12C a write-off | The data has a peak temperature and no duration | A load at 9C is either over-called or ignored |
| Cover above days left means it cannot sell through | Cover tops out at 40 in this data | A slow mover with three months left is invisible |
| "Today" is the last day in the data | The pack is frozen | The screen is empty |
| A shelf price is the mean of its six weekly readings | The series has no trend, so one reading is one draw from a 9.4% range | We would call a wobble a markdown |
| A DC's stock is priced against its own metro's shelf | Four DCs sit in scraped cities | Bhiwandi feeds more than Mumbai, so the city is printed on the row and the reader can reject it |

Test outlets are dropped and named on screen. The fiscal year starts in April.

## 5 · Next two weeks

- Shelf prices for the other four depot cities; today the column is blank for
  115 of the 147 lines that cannot clear.
- Freight at warehouse level, labelled for what it cannot answer.
- Who ticked a case off — which needs identity, which needs a login.

## 6 · What breaks first

- **Load.** Every number is computed live, no cache. A quarter over half a million
  lines takes a tenth of a second; a hundred people at nine would feel it. A
  nightly rollup by day and region is the fix.
- **The date.** On a live feed "yesterday" has to mean yesterday, which means
  deciding when a day closes.
- **One field.** Cases-to-pieces rests on pack size at order time. Nulls from any
  source and the two numbers drift apart quietly.
