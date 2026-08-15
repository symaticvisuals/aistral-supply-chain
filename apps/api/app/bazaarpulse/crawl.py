"""The walk, and the check that it actually moved.

Bengaluru and Chennai paginate at `index_p{n}.html`, but their own pager links
point at `index.html?p={n}`, which a static server answers with page 1. A
crawler that follows links fetches seventeen pages per city, parses every one of
them without error, and quietly records page one seventeen times. Nothing throws.

So no page is trusted to be the page we asked for. Every listing page states
which page it is, and a response that disagrees with the request is discarded
and the next convention tried. The trap is then reported rather than silently
worked around, because the next site will lie in a different way.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from urllib.parse import urljoin, urlsplit

from app.bazaarpulse import parse
from app.bazaarpulse.fetch import NOT_FOUND, REFUSED, Attempt, Fetcher

Progress = Callable[[str], None]


@dataclass
class Finding:
    """Same shape as /metrics/quality, on purpose. What the crawl learned about
    the site, as opposed to what the numbers mean once they are home."""

    id: str
    severity: str
    statement: str
    evidence: dict = field(default_factory=dict)


@dataclass
class Snapshot:
    base_url: str
    started_at: str
    finished_at: str | None = None
    crawl_delay_s: float = 0.0
    robots_found: bool = False
    listings: dict = field(default_factory=dict)
    first_seen_on: dict = field(default_factory=dict)
    history: dict = field(default_factory=dict)
    detail_price: dict = field(default_factory=dict)
    repeats: int = 0
    pages_ok: int = 0
    pages_rejected: int = 0
    findings: list = field(default_factory=list)
    attempts: list = field(default_factory=list)

    @property
    def rows(self) -> list:
        return list(self.listings.values())


def _noop(_: str) -> None:
    return None


def _city_root(entry_path: str) -> str:
    """The directory a city's pages hang off, whichever convention it uses."""
    if entry_path.endswith("/page/1.html"):
        return entry_path[: -len("/page/1.html")]
    return entry_path.rsplit("/", 1)[0]


def _candidates(
    page_url: str, entry_path: str, pager: dict, n: int,
    learned: str | None = None,
) -> list:
    """Where page n might be, most-likely first, as (url, template, source).

    A template that already worked for this city is tried first, then the site's
    own link, then the conventions we have seen. Learning the shape saves the
    two cities whose links mislead from being asked twice on every page — but
    nothing is trusted on the strength of it, because the caller still checks
    that the page it got is the page it asked for.
    """
    root = _city_root(entry_path)
    out, seen = [], set()

    def add(template: str | None, source: str, url: str) -> None:
        if url not in seen:
            seen.add(url)
            out.append((url, template, source))

    if learned:
        add(learned, "learned", urljoin(page_url, learned.format(n=n)))
    if n in pager:
        # A literal URL from the page, not a shape we could reuse.
        add(None, "site", urljoin(page_url, pager[n]))
    for template in (root + "/page/{n}.html", root + "/index_p{n}.html"):
        add(template, "convention", urljoin(page_url, template.format(n=n)))
    return out


def entry_points(fetcher: Fetcher, progress: Progress) -> list:
    """City entry pages, from the sitemap if there is one, else the home page."""
    sitemap = fetcher.get("sitemap.txt", "sitemap")
    if sitemap:
        paths = [ln.strip() for ln in sitemap.body.splitlines() if ln.strip()]
        cities = [p for p in paths if "/city/" in p]
        if cities:
            progress(f"sitemap lists {len(cities)} city entry points")
            return cities

    home = fetcher.get("index.html", "home")
    if not home:
        return []
    doc = parse.Document()
    doc.feed(home.body)
    found, out = set(), []
    for el in doc.elements:
        href = str(el.attrs.get("href", ""))
        if el.tag == "a" and "/city/" in href and href not in found:
            found.add(href)
            out.append(href)
    progress(f"home page links {len(out)} cities (no usable sitemap)")
    return out


def _absorb(snap: Snapshot, page: parse.ListingPage, url: str) -> int:
    fresh = 0
    for row in page.listings:
        if row.listing_id in snap.listings:
            snap.repeats += 1
            continue
        snap.listings[row.listing_id] = row
        snap.first_seen_on[row.listing_id] = url
        fresh += 1
    return fresh


def _walk_city(
    snap: Snapshot,
    fetcher: Fetcher,
    entry_path: str,
    progress: Progress,
    misleading: list,
) -> None:
    first = fetcher.get(entry_path, "listing_page")
    if first is None:
        progress(f"  {entry_path}: unreachable")
        return

    entry_url = urljoin(fetcher.base_url, entry_path.lstrip("/"))
    page = parse.listing_page(first.body)
    snap.pages_ok += 1
    _absorb(snap, page, entry_url)
    total = page.total_pages or 1
    progress(
        f"  {page.city or entry_path}: {len(page.listings)} listings on page 1 "
        f"of {total}"
    )

    learned: str | None = None
    for n in range(2, total + 1):
        for url, template, source in _candidates(
            entry_url, entry_path, page.pager, n, learned
        ):
            # A 404 on a convention we are guessing at is the crawl working;
            # a 404 on a link the site published is the site being wrong.
            purpose = ("pagination_probe" if source == "convention"
                       else "listing_page")
            body = fetcher.get(url, purpose)
            if body is None:
                continue
            got = parse.listing_page(body.body)
            if got.page is not None and got.page != n:
                # The page we were handed says it is a different page. Keeping
                # it would duplicate page 1 and look like a successful crawl.
                snap.pages_rejected += 1
                fetcher.log.append(
                    Attempt(url, "wrong_page", 200, 1, 0,
                            f"asked for page {n}, page says {got.page}",
                            purpose)
                )
                if source == "site" and not any(
                    m["city"] == page.city for m in misleading
                ):
                    misleading.append(
                        {"city": page.city, "asked": n, "url": url,
                         "served": got.page, "pages_in_city": total}
                    )
                continue
            learned = template or learned
            snap.pages_ok += 1
            _absorb(snap, got, url)
            break
        else:
            progress(f"  {page.city}: page {n} could not be reached")


def _walk_details(
    snap: Snapshot, fetcher: Fetcher, progress: Progress, limit: int | None
) -> None:
    rows = snap.rows if limit is None else snap.rows[:limit]
    progress(f"detail pages: {len(rows)} to fetch")
    for row in rows:
        if not row.detail_path:
            continue
        body = fetcher.get(row.detail_path, "detail_page")
        if body is None:
            continue
        detail = parse.detail_page(body.body, row.listing_id)
        if detail.history:
            snap.history[row.listing_id] = detail.history
        if detail.price_inr is not None:
            snap.detail_price[row.listing_id] = detail.price_inr


def _findings(snap: Snapshot, fetcher: Fetcher, misleading: list) -> list:
    out = []

    conventions: dict = {}
    unreadable = []
    for row in snap.rows:
        key = row.price_source or "unreadable"
        conventions[key] = conventions.get(key, 0) + 1
        if row.price_source is None:
            unreadable.append(row.listing_id)
    out.append(Finding(
        id="PRICE_MARKUP_VARIES_BY_CITY",
        severity="advisory" if not unreadable else "blocks_metric",
        statement=(
            f"{len(conventions)} different price markups across the site, and "
            f"{conventions.get('data-price-paise', 0)} listings keep the number "
            f"out of the visible text entirely. "
            + (f"{len(unreadable)} listings had no readable price."
               if unreadable else "Every listing had a readable price.")
        ),
        evidence={"by_convention": conventions,
                  "unreadable_listing_ids": unreadable[:20]},
    ))

    probes = [a for a in fetcher.log if a.purpose == "pagination_probe"]
    out.append(Finding(
        id="PAGINATION_LINKS_MISLEAD",
        severity="advisory" if misleading else "clean",
        statement=(
            f"{len(misleading)} cities publish pager links that name one page "
            f"and serve another: the query string is ignored and page 1 comes "
            f"back. Following them would have recorded page 1 for every page "
            f"after the first, without erroring. Once a city was caught its "
            f"links were stopped being followed, and every page kept was still "
            f"checked against the page it says it is."
            if misleading else
            "Every pager link served the page it named."
        ),
        evidence={
            "rejected_pages": snap.pages_rejected,
            "examples": misleading[:5],
            "probes_sent": len(probes),
            "probes_404": sum(1 for a in probes if a.outcome == NOT_FOUND),
        },
    ))

    out.append(Finding(
        id="LISTINGS_REPEAT_ACROSS_PAGES",
        severity="advisory" if snap.repeats else "clean",
        statement=(
            f"{snap.repeats} listing appearances were the same listing seen "
            f"again on another page. Counting cards rather than ids would "
            f"overstate the site by {snap.repeats}."
            if snap.repeats else "No listing appeared on two pages."
        ),
        evidence={"unique_listings": len(snap.listings),
                  "repeat_appearances": snap.repeats},
    ))

    # Only pages a listing actually linked to. A 404 on a pagination guess
    # belongs to the finding above; counting it here would claim the site is
    # broken in a way it is not.
    requested = sum(1 for a in fetcher.log if a.purpose == "detail_page")
    missing = [a.url for a in fetcher.log
               if a.purpose == "detail_page" and a.outcome == NOT_FOUND]
    if requested:
        out.append(Finding(
            id="DETAIL_PAGES_MISSING",
            severity="advisory" if missing else "clean",
            statement=(
                f"{len(missing)} of {requested} pages linked from a listing "
                f"do not exist."
                if missing else
                f"All {requested} pages linked from a listing exist."
            ),
            evidence={"requested": requested, "urls": missing[:10]},
        ))

    refused = [a.url for a in fetcher.log if a.outcome == REFUSED]
    disallowed = [r for r in fetcher.robots_rules
                  if r.lower().startswith("disallow")]
    out.append(Finding(
        id="ROBOTS_DISALLOWED_PATHS_NOT_FETCHED",
        severity="advisory",
        statement=(
            f"robots.txt disallows {len(disallowed)} paths and we requested "
            f"none of them. {len(refused)} requests were refused before they "
            f"were sent."
        ),
        evidence={"rules": disallowed, "refused_urls": refused[:10],
                  "crawl_delay_s": snap.crawl_delay_s},
    ))

    disagreed = [
        row.listing_id for row in snap.rows
        if row.listing_id in snap.detail_price
        and row.price_inr is not None
        and abs(snap.detail_price[row.listing_id] - row.price_inr) > 0.005
    ]
    if snap.detail_price:
        out.append(Finding(
            id="DETAIL_PRICE_DISAGREES_WITH_LISTING",
            severity="advisory" if disagreed else "clean",
            statement=(
                f"{len(disagreed)} of {len(snap.detail_price)} detail pages "
                f"quote a different current price than the listing card."
                if disagreed else
                f"All {len(snap.detail_price)} detail pages agree with their "
                f"listing card on the current price."
            ),
            evidence={"listing_ids": disagreed[:10]},
        ))

    return out


def crawl(
    fetcher: Fetcher,
    *,
    with_details: bool = True,
    detail_limit: int | None = None,
    progress: Progress = _noop,
) -> Snapshot:
    snap = Snapshot(
        base_url=fetcher.base_url,
        started_at=datetime.now(UTC).isoformat(timespec="seconds"),
    )

    fetcher.load_robots()
    snap.robots_found = fetcher.robots_found
    snap.crawl_delay_s = fetcher.delay
    progress(
        f"robots.txt: {len(fetcher.robots_rules)} directives, "
        f"crawl delay {snap.crawl_delay_s}s"
    )

    misleading: list = []
    for entry in entry_points(fetcher, progress):
        _walk_city(snap, fetcher, urlsplit(entry).path or entry,
                   progress, misleading)

    progress(f"{len(snap.listings)} unique listings from {snap.pages_ok} pages")

    if with_details:
        _walk_details(snap, fetcher, progress, detail_limit)

    snap.findings = _findings(snap, fetcher, misleading)
    snap.attempts = list(fetcher.log)
    snap.finished_at = datetime.now(UTC).isoformat(timespec="seconds")
    return snap
