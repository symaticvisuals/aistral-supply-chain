# Decisions

## 1 · What we built

One screen, one day. Not a quarter — a quarter barely moves, and the complaint
is about yesterday.

Fill rate shows twice: cases for Divya, pieces for Rakesh. Both are right, and
hiding either one restarts the argument. Managers can filter to their own
region. Q1 sits on the front page for the board. Next to it: credit notes
against what we shipped, a count of shops charging more than the printed MRP,
and stock that will expire before it sells — each line showing the lowest price
shops in that city charge, which tells you whether a discount still has room.

A list of what broke is not a morning. So cases are sorted by one question: can
anything I do today still change this? Three groups — act before noon, decide
today, or just watch. We did not give cases a single score, because spoiled
stock, orders never sent and a late load that still arrived are different kinds
of loss. Inside a group we sort by what the case costs and show that cost, so
Divya can disagree and see why. Marking a case done clears it from everyone's
screen; with no login, we record that it was handled, not who by.

## 2 · What we did not build

- **OTIF.** No order in eighteen months arrived complete, so the number would
  always read zero.
- **On-time.** The two lateness records agree on only one delivery in eight.
- **A price panel.** Every product on the tracker is one we already sell, and
  none of its five shops is ours. So "our price against theirs" can only mean
  our MRP against what they charge for our own goods. Discount off MRP differs
  by only 1.2 points across the four cities, so ranking cities ranks noise. The
  price appears instead on the one line where it changes a decision: whether
  expiring stock can still be discounted.
- **A price-drop alert.** Shelf prices move about 9% up and down week to week
  and go nowhere over time. A "price cut" cannot be told apart from that wobble,
  so an alert would send Divya after a coin toss.
- **Freight cost per case.** Carrier bills carry no order number, so a rupee
  cannot be traced back to a shop.
- **Ask-anything.** It would only be as honest as the layer underneath it.
- **Login and tabs.** One screen was the ask.

## 3 · What we assumed

The last column is the part worth arguing with.

| We assumed | Because | If it is wrong |
|---|---|---|
| Fill is counted in cases **and** pieces | Divya commits in cases; modern trade fines us on pieces | One side of the argument comes back |
| Pack size comes from the order line, not the product list | The product list changes when a SKU is repacked | Every past conversion shifts quietly |
| A stockout cancel is our fault; a credit hold is arguable | Stock is supply, credit is finance | One setting, worth 1.35 points of service |
| Four columns carry no signal, so we slice nothing by them | Each fires at the same rate whatever the row | We would rank noise and call it a cause |
| Chilled above 8C is a problem, above 12C a write-off | We have a peak temperature but no duration | A load at 9C is either over-called or ignored |
| Cover above days left means it cannot sell in time | Cover stops at 40 in this data | Slow stock with three months left stays hidden |
| A shelf price is the average of its six readings | No trend, and a 9.4% gap between high and low | We would call a wobble a price cut |
| Depot stock is priced against its own city's shops | Four depots sit in cities we track | Bhiwandi supplies more than Mumbai — so the city is printed and can be rejected |

Test outlets are dropped and named on screen. The financial year starts in
April. "Today" is the last day in the data, because the data is frozen.

## 4 · Next two weeks

- Shelf prices for the other four depot cities. That column is blank today on
  115 of the 147 lines that cannot clear.
- Freight by warehouse, labelled with what it cannot answer.
- Who marked a case done — which needs identity, which needs a login.

## 5 · What breaks first

- **Load.** Every number is worked out live, with no cache. A quarter of half a
  million lines takes a tenth of a second, but a hundred people at nine would
  feel it. A nightly summary by day and region is the fix.
- **The date.** On live data, "yesterday" has to mean yesterday, which means
  deciding when a day closes.
- **One field.** Cases-to-pieces rests on pack size at order time. If that
  arrives empty from any source, the two numbers drift apart quietly.
