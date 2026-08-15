"""Shelf prices, joined to our own catalogue.

The competitor tracker turns out not to be one. Every listing on BazaarPulse
matches a SKU we distribute — Kestrel moves all six brands on that site, none of
the five chains are outlets of ours — so "our MRP against what competitors
charge" can only mean one thing here: the same SKU, our printed MRP, priced on
five rival shelves. Comparing one of our brands against another would be
comparing us with us.

What that leaves is narrow and useful. The expiry panel names two levers,
a transfer or a promotion, and has never had the number that picks between them:
stock already selling at a quarter off cannot be discounted out of trouble, and
stock at full price can.

Two judgements are worth arguing with:

*The price of a listing is the mean of its own observations, not the newest one.*
The series has no trend and no memory, and the median listing swings 9.4% between
its high and low, so the latest card price is one draw from a wide range. Six
draws average to something steadier.

*A city's shelf price is the median across the listings in it*, counting only
what is actually in stock. A price on an unavailable listing is not a shelf
price, and Divya asked what shops charge on the shelf.
"""

import re
import sqlite3
import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from app.settings import settings

# Which BazaarPulse city a warehouse sits in. Explicit rather than matched on
# text: the DC names share no words with the city names, and guessing is how a
# transfer gets priced against the wrong shelf. Four DCs have no city here at
# all, which is reported rather than left as an empty column.
DC_CITY = {
    "Mumbai": "Mumbai",
    "Bengaluru": "Bengaluru",
    "Chennai": "Chennai",
    "Delhi": "Delhi NCR",
}

# Title noise the retailers add. Stripped, never guessed at.
_NOISE = re.compile(
    r"(combo|pack of \d+|\(new\)|best before \d+m|value pack|family pack|\bnew\b)",
    re.IGNORECASE,
)
# Abbreviations the site uses and our master does not. A short explicit table,
# because a fuzzy matcher that scores 100% on this data would be a matcher we
# cannot explain when it scores 80% on next week's.
_ABBREVIATIONS = (
    (r"\bsel\b", "select"),
    (r"\bamritvalley\b", "amrit valley"),
    (r"\binst\b", "instant"),
    (r"\bfrzn\b", "frozen"),
)
_SIZE = re.compile(r"(\d+(?:\.\d+)?)\s*(ml|g|kg|l)\b")


def normalise(title: str) -> tuple:
    """A product title reduced to (words, pack size), both sides of the join."""
    text = (title or "").replace("|", " ").replace(".", " ").lower()
    text = _NOISE.sub(" ", text)
    for pattern, replacement in _ABBREVIATIONS:
        text = re.sub(pattern, replacement, text)
    text = re.sub(r"[^a-z0-9. ]", " ", text)
    found = _SIZE.search(text)
    size = (float(found.group(1)), found.group(2).upper()) if found else None
    words = re.sub(r"\s+", " ", _SIZE.sub("", text)).strip()
    return words, size


@dataclass(frozen=True)
class Shelf:
    """What one retailer charges for one SKU in one city."""

    sku: str
    city: str
    retailer: str
    price_inr: float
    latest_inr: float
    observations: int
    mrp_inr: float
    last_seen: str
    in_stock: bool


@dataclass
class CityPrice:
    """The shelf price for a SKU in a city, and how thin the evidence is.

    Two numbers, because they answer different questions and blending them
    answers neither. `price_inr` is what a typical shop charges. `lowest_inr` is
    the deepest discount already standing in that city, and that is the one that
    says whether a promotion has any room left — if someone is already a quarter
    off and the stock still will not move, cutting further is pushing on a rope.
    """

    sku: str
    city: str
    price_inr: float
    lowest_inr: float
    mrp_inr: float
    listings: int
    retailers: list = field(default_factory=list)

    @property
    def vs_mrp_pct(self) -> float:
        return (self.price_inr - self.mrp_inr) / self.mrp_inr * 100.0

    @property
    def lowest_vs_mrp_pct(self) -> float:
        return (self.lowest_inr - self.mrp_inr) / self.mrp_inr * 100.0


@dataclass
class PriceBook:
    run_id: int
    scraped_at: str
    base_url: str
    listings_n: int
    matched_n: int
    observed_from: date | None = None
    observed_to: date | None = None
    mrp_agree: int = 0
    mrp_conflict: int = 0
    unmatched: list = field(default_factory=list)
    shelves: list = field(default_factory=list)
    # Observation series in date order, one per matched listing. Kept whole
    # because whether they carry a trend is itself a finding.
    series: list = field(default_factory=list)
    _by_key: dict = field(default_factory=dict)

    @property
    def match_pct(self) -> float:
        return 100.0 * self.matched_n / self.listings_n if self.listings_n else 0.0

    @property
    def scraped_on(self) -> date | None:
        try:
            return date.fromisoformat(self.scraped_at[:10])
        except (TypeError, ValueError):
            return None

    def age_days(self, as_of: date) -> int | None:
        """How old the *observations* are, not the crawl.

        The two are weeks apart and only one of them is a fact about the price.
        We scraped in August; the site last saw these shelves in June, which is
        where the pack's own data ends. Ageing prices from the crawl date would
        have reported a six-week-old number as fresh — or, running the scrape
        before the as-of date, as a price from the future.
        """
        if self.observed_to is None:
            return None
        return (as_of - self.observed_to).days

    def city_price(self, sku: str, city: str | None) -> CityPrice | None:
        return self._by_key.get((sku, city)) if city else None

    def for_warehouse_city(self, sku: str, dc_city: str | None) -> CityPrice | None:
        """The shelf price where that DC's stock would sell, if we scrape there."""
        return self.city_price(sku, DC_CITY.get(dc_city or ""))

    def above_mrp(self) -> dict:
        """Listings sold above the maximum price printed on the pack.

        Counted, not ranked. The spread between retailers is about two standard
        errors, which is not enough to name one of them.
        """
        breaches = [s for s in self.shelves if s.latest_inr > s.mrp_inr]
        by_retailer: dict = defaultdict(int)
        listings_by_retailer: dict = defaultdict(int)
        for shelf in self.shelves:
            listings_by_retailer[shelf.retailer] += 1
        for shelf in breaches:
            by_retailer[shelf.retailer] += 1
        return {
            "listings": len(breaches),
            "of_listings": len(self.shelves),
            "pct": round(100.0 * len(breaches) / len(self.shelves), 1)
            if self.shelves else None,
            "by_retailer": {
                name: {"breaches": by_retailer.get(name, 0),
                       "listings": total}
                for name, total in sorted(listings_by_retailer.items())
            },
        }


def _products(conn: sqlite3.Connection) -> dict:
    index: dict = defaultdict(list)
    for row in conn.execute(
        "SELECT sku_code, product_name, mrp_inr FROM products"
    ):
        index[normalise(row["product_name"])].append(row)
    return index


def _snapshot(path: Path | None) -> sqlite3.Connection | None:
    db = path or settings.bazaarpulse_path
    if not db.exists():
        return None
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def load(
    conn: sqlite3.Connection, path: Path | None = None
) -> PriceBook | None:
    """The latest completed scrape, matched to our SKUs. None if never scraped.

    None rather than an empty book, so that "we have no prices" and "the prices
    say nothing" stay different sentences on the screen.
    """
    snap = _snapshot(path)
    if snap is None:
        return None
    try:
        run = snap.execute(
            "SELECT * FROM scrape_run WHERE finished_at IS NOT NULL"
            " ORDER BY run_id DESC LIMIT 1"
        ).fetchone()
        if run is None:
            return None
        listings = snap.execute(
            "SELECT * FROM listing WHERE run_id = ?", (run["run_id"],)
        ).fetchall()
        history: dict = defaultdict(list)
        for row in snap.execute(
            "SELECT listing_id, price_inr FROM price_history"
            " WHERE run_id = ? ORDER BY observed_on",
            (run["run_id"],),
        ):
            history[row["listing_id"]].append(row["price_inr"])
    except sqlite3.DatabaseError:
        return None
    finally:
        snap.close()

    index = _products(conn)
    shelves, unmatched, series = [], [], []
    agree = conflict = 0
    for row in listings:
        candidates = index.get(normalise(row["title"]), [])
        if len(candidates) > 1 and row["mrp_inr"] is not None:
            # Our own master has name collisions — two live SKUs are both
            # "Kestrel Juice 200ml" at different MRPs. The site publishes the
            # MRP, which is the only thing that tells them apart.
            narrowed = [
                p for p in candidates
                if abs(p["mrp_inr"] - row["mrp_inr"]) < 0.51
            ]
            candidates = narrowed or candidates
        if len(candidates) != 1:
            unmatched.append(row["title"])
            continue
        product = candidates[0]
        observed = history.get(row["listing_id"]) or []
        if row["price_inr"] is not None:
            observed = observed or [row["price_inr"]]
        if not observed:
            unmatched.append(row["title"])
            continue
        if row["mrp_inr"] is not None:
            if abs(product["mrp_inr"] - row["mrp_inr"]) < 0.51:
                agree += 1
            else:
                conflict += 1
        if len(observed) > 1:
            series.append(list(observed))
        shelves.append(Shelf(
            sku=product["sku_code"],
            city=row["city"] or "",
            retailer=row["retailer"] or "",
            price_inr=round(statistics.mean(observed), 2),
            latest_inr=row["price_inr"],
            observations=len(observed),
            mrp_inr=product["mrp_inr"],
            last_seen=row["last_seen"] or "",
            in_stock=row["availability"] == "in_stock",
        ))

    # Only what is on the shelf. An unavailable listing has a price and no shelf,
    # and Divya asked what shops charge on the shelf.
    stocked: dict = defaultdict(list)
    for shelf in shelves:
        if shelf.in_stock:
            stocked[(shelf.sku, shelf.city)].append(shelf)

    by_key = {}
    for (sku, city), group in stocked.items():
        by_key[(sku, city)] = CityPrice(
            sku=sku,
            city=city,
            price_inr=round(statistics.median(s.price_inr for s in group), 2),
            lowest_inr=round(min(s.price_inr for s in group), 2),
            mrp_inr=group[0].mrp_inr,
            listings=len(group),
            retailers=sorted({s.retailer for s in group}),
        )

    seen = sorted(s.last_seen for s in shelves if s.last_seen)
    return PriceBook(
        run_id=run["run_id"],
        scraped_at=run["finished_at"] or run["started_at"],
        base_url=run["base_url"],
        listings_n=len(listings),
        matched_n=len(shelves),
        series=series,
        mrp_agree=agree,
        mrp_conflict=conflict,
        observed_from=date.fromisoformat(seen[0]) if seen else None,
        observed_to=date.fromisoformat(seen[-1]) if seen else None,
        unmatched=unmatched,
        shelves=shelves,
        _by_key=by_key,
    )
