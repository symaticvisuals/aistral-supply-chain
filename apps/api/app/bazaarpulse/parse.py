"""BazaarPulse HTML into rows.

The site was not built for us and the pack says so. Each of the four cities
renders the price a different way and one of them keeps it out of the text
entirely, so every listing records *which* rule read its number. Four counts
that have to sum to the listing count is a check no amount of careful regex
gives you: a parser that silently reads nothing looks exactly like a city with
no listings until you ask it how it read them.
"""

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser

# Void elements never close, so they must not go on the open-tag stack.
_VOID = frozenset({
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
})

_NUMBER = re.compile(r"\d[\d,]*\.?\d*")
_MRP = re.compile(r"MRP\s*₹?\s*(\d[\d,]*\.?\d*)")
_RATED = re.compile(r"rated\s+(\d[\d.]*)\s*\((\d+)\)")
_SEEN = re.compile(r"Last seen:\s*(\d{4}-\d{2}-\d{2})")
_PAGE_OF = re.compile(r"page\s+(\d+)\s+of\s+(\d+)", re.IGNORECASE)
_CRUMB = re.compile(r"Home\s*/\s*([^/]+?)\s*(?:/|$)")
_HISTORY = re.compile(r"(\d{4}-\d{2}-\d{2})\D*?(\d[\d,]*\.?\d*)")
_PRODUCT_HREF = re.compile(r"/product/(\d+)\.html")
_LABELLED = re.compile(r"(Retailer|City|Pack)\s*:\s*([^·]+)")


@dataclass(frozen=True)
class Element:
    tag: str
    attrs: dict
    text: str

    @property
    def classes(self) -> frozenset:
        return frozenset(self.attrs.get("class", "").split())


@dataclass(frozen=True)
class Card:
    attrs: dict
    elements: list


class Document(HTMLParser):
    """Every closed element, plus the ones inside a product card.

    Text is accumulated into every open ancestor, so `Element.text` is full
    inner text. Delhi splits its price across `<em>Rs.</em>` and a bare text
    node; an extractor reading only direct children would drop the number.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.elements: list[Element] = []
        self.cards: list[Card] = []
        self._open: list[dict] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in _VOID:
            return
        node = {"tag": tag, "attrs": dict(attrs), "parts": [], "card": None}
        classes = set(str(node["attrs"].get("class", "")).split())
        if {"card", "product-item"} <= classes:
            node["card"] = len(self.elements)
        self._open.append(node)

    def handle_data(self, data: str) -> None:
        for node in self._open:
            node["parts"].append(data)

    def handle_endtag(self, tag: str) -> None:
        for i in range(len(self._open) - 1, -1, -1):
            if self._open[i]["tag"] == tag:
                closing = self._open[i:]
                del self._open[i:]
                break
        else:
            return
        # Innermost first, so a card's children are already recorded when it
        # closes and the slice below is exactly its contents.
        for node in reversed(closing):
            if node["card"] is not None:
                self.cards.append(
                    Card(node["attrs"], self.elements[node["card"]:])
                )
            self.elements.append(
                Element(
                    node["tag"],
                    node["attrs"],
                    " ".join("".join(node["parts"]).split()),
                )
            )


@dataclass
class Listing:
    listing_id: str
    title: str
    city: str | None = None
    retailer: str | None = None
    pack_text: str | None = None
    category: str | None = None
    price_inr: float | None = None
    price_source: str | None = None
    mrp_inr: float | None = None
    availability: str | None = None
    rating: float | None = None
    rating_count: int | None = None
    last_seen: str | None = None
    detail_path: str | None = None


@dataclass
class ListingPage:
    city: str | None
    page: int | None
    total_pages: int | None
    listings: list[Listing] = field(default_factory=list)
    pager: dict = field(default_factory=dict)


@dataclass
class DetailPage:
    listing_id: str | None
    title: str | None = None
    city: str | None = None
    retailer: str | None = None
    pack_text: str | None = None
    price_inr: float | None = None
    price_source: str | None = None
    mrp_inr: float | None = None
    availability: str | None = None
    history: list = field(default_factory=list)


def money(text: str) -> float | None:
    """First number in a price string, whatever currency dressing it wears."""
    found = _NUMBER.search(text or "")
    return float(found.group(0).replace(",", "")) if found else None


def availability(text: str) -> str | None:
    low = (text or "").lower()
    if "in stock" in low:
        return "in_stock"
    if "unavailable" in low or "out of stock" in low:
        return "unavailable"
    return None


def price_of(elements: list) -> tuple:
    """(amount, which rule read it). One rule per city, and they do not overlap.

    Bengaluru is the one that matters: its visible text says "Price on card" and
    the number lives in a data attribute, so a scraper that reads text alone
    loses a quarter of the site without raising anything.

    Listing cards and detail pages share this because they share the problem —
    a detail parser that only knew Mumbai's markup read three cities as having
    no price at all, and said so as "all the prices we read agree".
    """
    for el in elements:
        paise = el.attrs.get("data-price-paise")
        if paise is not None and str(paise).isdigit():
            return int(paise) / 100, "data-price-paise"
        for token, name in (("price", "span.price"),
                            ("sellingPrice", "b.sellingPrice"),
                            ("amt", "div.amt")):
            if token in el.classes:
                amount = money(el.text)
                if amount is not None:
                    return amount, name
    return None, None


def price(card: Card) -> tuple:
    return price_of(card.elements)


def _muted(card: Card) -> list:
    return [el for el in card.elements
            if el.tag == "div" and "muted" in el.classes]


def _split_meta(text: str) -> tuple:
    """"DailyKart · 400 ml · Staples" -> the three of them.

    methodology.html warns that some retailers publish no pack size, so a
    two-part line is read as retailer and category with the pack left None
    rather than shifting the category into the pack column.
    """
    parts = [p.strip() for p in (text or "").split("·") if p.strip()]
    if len(parts) >= 3:
        return parts[0], parts[1], parts[2]
    if len(parts) == 2:
        return parts[0], None, parts[1]
    return (parts[0] if parts else None), None, None


def listing(card: Card, city: str | None = None) -> Listing | None:
    listing_id = str(card.attrs.get("data-listing-id") or "").strip()
    titles = [el.text for el in card.elements if el.tag == "strong" and el.text]
    if not listing_id or not titles:
        return None

    row = Listing(listing_id=listing_id, title=titles[0], city=city)

    for el in card.elements:
        href = str(el.attrs.get("href", ""))
        if el.tag == "a" and _PRODUCT_HREF.search(href):
            row.detail_path = href
            break

    row.price_inr, row.price_source = price(card)

    # Read the meta lines by what they contain, not by their order.
    for el in _muted(card):
        text = el.text
        if seen := _SEEN.search(text):
            row.last_seen = seen.group(1)
        elif mrp := _MRP.search(text):
            row.mrp_inr = float(mrp.group(1).replace(",", ""))
            row.availability = availability(text)
            if rated := _RATED.search(text):
                row.rating = float(rated.group(1))
                row.rating_count = int(rated.group(2))
        elif row.retailer is None and "·" in text:
            row.retailer, row.pack_text, row.category = _split_meta(text)

    return row


def breadcrumb(doc: Document) -> tuple:
    """(city, page, total pages) as the page states them about itself.

    This is the only thing that says which page we are actually holding, which
    is what makes the pagination check in crawl.py possible.
    """
    for el in doc.elements:
        if el.tag != "p" or "muted" not in el.classes or "Home" not in el.text:
            continue
        city = _CRUMB.search(el.text)
        of = _PAGE_OF.search(el.text)
        return (
            city.group(1).strip() if city else None,
            int(of.group(1)) if of else None,
            int(of.group(2)) if of else None,
        )
    return None, None, None


def pager(doc: Document) -> dict:
    """Page number -> href, exactly as the site gives it. Not to be trusted."""
    links = {}
    for el in doc.elements:
        href = str(el.attrs.get("href", ""))
        if el.tag == "a" and href and el.text.isdigit():
            links.setdefault(int(el.text), href)
    return links


def listing_page(html: str) -> ListingPage:
    doc = Document()
    doc.feed(html)
    city, page, total = breadcrumb(doc)
    rows = [row for row in (listing(card, city) for card in doc.cards) if row]
    return ListingPage(city, page, total, rows, pager(doc))


def detail_page(html: str, listing_id: str | None = None) -> DetailPage:
    doc = Document()
    doc.feed(html)
    out = DetailPage(listing_id=listing_id)
    out.price_inr, out.price_source = price_of(doc.elements)

    for el in doc.elements:
        if el.tag == "h2" and out.title is None:
            out.title = el.text
        if el.tag == "tr":
            row = _HISTORY.search(el.text)
            if row:
                out.history.append(
                    (row.group(1), float(row.group(2).replace(",", "")))
                )
        if el.tag == "p" and "muted" in el.classes:
            for label, value in _LABELLED.findall(el.text):
                setattr(out, {"Retailer": "retailer", "City": "city",
                              "Pack": "pack_text"}[label], value.strip())
            if mrp := _MRP.search(el.text):
                out.mrp_inr = float(mrp.group(1).replace(",", ""))
                out.availability = availability(el.text)

    # A history table lists the same observation once; duplicates would be the
    # markup repeating itself, and silently summing them would invent a series.
    out.history = sorted(dict(out.history).items(), reverse=True)
    return out
