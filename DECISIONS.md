# Decisions

Working notes. One entry per decision, added as we build.

## 1 · Where we started

We read the data before deciding what to build. That changed the plan. Several of
the problems the brief warns about are not actually in the data, and two of the
numbers it asks for cannot be produced honestly — nothing here ever arrives
complete, and the two records of lateness disagree with each other. So we stopped
trying to answer those and spent the time on the one thing everyone in the brief
argues about: how much of what a shop ordered actually turned up.

We built it as yesterday rather than as a quarter. A quarter is a board number and
it barely moves; the complaint is about not knowing what happened yesterday. And we
show the same day twice — in boxes for Divya, in units for Rakesh — because both are
correct, and hiding either one starts the argument again. Regional managers get the
same thing, filtered to their region.

## 2 · What we built

One screen for one day: which shops did not get what they ordered, in boxes and in
units, each failure listed as something to do and a desk to call. Move the date,
filter to a region, or switch to the quarter when the board asks. The type is one
readable sans. Mono and condensed display made this look like a developer console.

Under it, one place computes every number. Every row we leave out of a total is
named and counted on the screen, because silent filters are how four people ended
up with four answers.

## 3 · What we did not build

- **OTIF.** Nothing in eighteen months ever arrived complete, so the tile would read
  zero every day. We report why instead.
- **On-time.** The two records of lateness agree on one delivery in eight. Either
  number is a guess.
- **Competitor prices.** A second system — scrape the site, then match our SKUs to
  their listings. Real work, but not a morning problem.
- **Freight per case.** The carrier bills carry no order or delivery number, so a
  rupee can never be traced back to a shop.
- **Ask-anything.** A question box is only as honest as the layer beneath it. A
  confident wrong number costs more than no box.
- **Login and tabs.** One screen was the ask.

## 4 · What we assumed

- Fill is cases *and* eaches, converted line by line using the pack size recorded at
  order time — not the product master, which moves when a SKU is repacked.
- A cancellation counts against us when we caused it. Out of stock, clearly. Credit
  hold is arguable, so it is one named setting and the screen says it is contested.
- Outlets named "test" or "do not use" are dropped and listed by name, so a wrong
  guess is visible rather than silent.
- The year starts in April, and a quarter takes the name of the year it starts in.
- "Today" is the last day in the data. The real date would show an empty screen.

## 5 · Next two weeks

- The morning queue is now a count per category. Open a row to see the cases
  and tick one off; that write is shared, so it leaves everyone's list.
- Returns and credit notes against dispatch value — the money half of the brief,
  and the same shape as what already exists.
- Cold chain as a rate per hundred chilled deliveries, not only as today's alerts.
- Freight in at warehouse level, labelled for what it can and cannot answer.

## 6 · What breaks first

- **Load.** Every number is computed live, with no cache. A quarter across half a
  million lines takes a tenth of a second today, but a hundred people at nine in the
  morning would feel it. The fix is a nightly rollup by day and region.
- **The date.** It comes from the data. On a live feed, "yesterday" has to mean
  yesterday, which means deciding when a day is closed.
- **One field.** The whole cases-to-eaches conversion rests on pack size at order
  time. It is clean today. If a source system starts sending nulls, the two numbers
  drift apart quietly — that needs a guard before anything else does.
