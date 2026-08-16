"""The crawl, against a site that lies the way the real one does.

The fixture site reproduces the two things that make BazaarPulse a scrape target
rather than a download: one city paginates by path and one paginates by a query
string its own server ignores, so following its links returns page 1 every time
without erroring.
"""

import functools
import http.server
import threading
from pathlib import Path

import pytest

from app.bazaarpulse import store
from app.bazaarpulse.crawl import crawl
from app.bazaarpulse.fetch import Fetcher

ROBOTS = """User-agent: *
Disallow: /internal/
Allow: /
Crawl-delay: 1
Sitemap: /sitemap.txt
"""

SITEMAP = "/index.html\n/city/honest/page/1.html\n/city/liar/index.html\n"


def card(listing_id: int, price_markup: str) -> str:
    return (
        f'<div class="card product-item" data-listing-id="{listing_id}">'
        f'<a href="/product/{listing_id}.html">'
        f"<strong>Kestrel Milk 400g</strong></a>"
        f'<div class="muted">FreshCart &middot; 400 g &middot; Dairy</div>'
        f"{price_markup}"
        f'<div class="muted">MRP &#8377;293 &middot; In stock</div>'
        f'<div class="muted">Last seen: 2026-06-27</div></div>'
    )


def listing_page(city: str, page: int, total: int, ids: list, markup, pager
                 ) -> str:
    cards = "".join(card(i, markup) for i in ids)
    return (
        f"<html><body><div class='wrap'>"
        f'<p class="muted">Home / {city} / page {page} of {total}</p>'
        f"<div class='grid'>{cards}</div>"
        f'<p class="pager">{pager}</p></div></body></html>'
    )


def detail(listing_id: int) -> str:
    return (
        '<div class="wrap"><p class="muted">Home / Honest / Dairy</p>'
        f"<h2>Kestrel Milk 400g</h2>"
        '<p class="muted">Retailer: FreshCart &middot; City: Honest '
        '&middot; Pack: 400 g</p>'
        '<p><span class="price">&#8377;250.00</span></p>'
        '<p class="muted">MRP &#8377;293 &middot; In stock</p>'
        "<table><tr><th>Observed on</th><th>Price</th></tr>"
        "<tr><td>2026-06-27</td><td>&#8377;250.00</td></tr>"
        "<tr><td>2026-06-20</td><td>&#8377;244.00</td></tr></table></div>"
    )


@pytest.fixture(scope="module")
def site(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("bazaarpulse")
    (root / "robots.txt").write_text(ROBOTS)
    (root / "sitemap.txt").write_text(SITEMAP)
    (root / "index.html").write_text(
        '<a href="/city/honest/page/1.html">Honest</a>'
        '<a href="/city/liar/index.html">Liar</a>'
    )

    # Honest: pager links point where they say. Prices in the text.
    honest = root / "city" / "honest" / "page"
    honest.mkdir(parents=True)
    for page in (1, 2):
        pager = "".join(
            f'<a href="/city/honest/page/{n}.html">{n}</a>' for n in (1, 2)
        )
        honest.joinpath(f"{page}.html").write_text(listing_page(
            "Honest", page, 2, [page * 10, page * 10 + 1],
            '<span class="price">&#8377;250.00</span>', pager,
        ))

    # Liar: pager links carry a query string the server ignores, so following
    # them serves page 1 again. The real pages are at index_p{n}.html. Three
    # pages, so that "caught it once, stopped asking" is observable.
    liar = root / "city" / "liar"
    liar.mkdir(parents=True)
    pager = "".join(
        f'<a href="/city/liar/index.html?p={n}">{n}</a>' for n in (1, 2, 3)
    )
    markup = '<span class="pricing-block" data-price-paise="19731">' \
             "Price on card</span>"
    liar.joinpath("index.html").write_text(
        listing_page("Liar", 1, 3, [100, 101], markup, pager)
    )
    for page in (2, 3):
        liar.joinpath(f"index_p{page}.html").write_text(listing_page(
            "Liar", page, 3, [page * 100, page * 100 + 1], markup, pager,
        ))

    products = root / "product"
    products.mkdir()
    for listing_id in (10, 11, 100, 101, 200, 300):
        products.joinpath(f"{listing_id}.html").write_text(detail(listing_id))
    # 201 and the page-2 honest listings are deliberately absent: real sites
    # link to pages that are not there.

    internal = root / "internal"
    internal.mkdir()
    internal.joinpath("margin-sheet.html").write_text("<h2>Margins</h2>")
    return root


@pytest.fixture(scope="module")
def base_url(site: Path):
    handler = functools.partial(
        http.server.SimpleHTTPRequestHandler, directory=str(site)
    )
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture(scope="module")
def snapshot(base_url):
    return crawl(Fetcher(base_url, delay=0, backoff=0))


def test_query_string_pagination_does_not_silently_repeat_page_one(snapshot):
    """The trap. Following the pager link alone loses most of the city."""
    liar = {row.listing_id for row in snapshot.rows if row.city == "Liar"}
    assert liar == {"100", "101", "200", "201", "300", "301"}


def test_the_page_that_lied_is_rejected_and_reported(snapshot):
    assert snapshot.pages_rejected == 1
    finding = next(f for f in snapshot.findings
                   if f.id == "PAGINATION_LINKS_MISLEAD")
    assert finding.severity == "advisory"
    assert finding.evidence["examples"] == [
        {"city": "Liar", "asked": 2, "served": 1, "pages_in_city": 3,
         "url": finding.evidence["examples"][0]["url"]}
    ]


def test_a_city_caught_lying_once_is_not_asked_again(snapshot):
    """Page 3 is fetched straight from the shape page 2 taught us.

    Verified all the same — it is the asking that stops, not the checking.
    """
    asked = [a.url for a in snapshot.attempts]
    assert not any("index.html?p=3" in url for url in asked)
    assert sum(1 for url in asked if url.endswith("/index_p3.html")) == 1


def test_every_listing_from_every_city_is_captured(snapshot):
    assert len(snapshot.listings) == 10
    assert {row.city for row in snapshot.rows} == {"Honest", "Liar"}


def test_price_is_read_from_both_conventions(snapshot):
    finding = next(f for f in snapshot.findings
                   if f.id == "PRICE_MARKUP_VARIES_BY_CITY")
    assert finding.evidence["by_convention"] == {
        "span.price": 4, "data-price-paise": 6}
    assert finding.evidence["unreadable_listing_ids"] == []
    assert all(row.price_inr for row in snapshot.rows)


def test_robots_disallowed_paths_are_never_requested(snapshot):
    assert not any("/internal/" in a.url for a in snapshot.attempts
                   if a.outcome == "ok")
    finding = next(f for f in snapshot.findings
                   if f.id == "ROBOTS_DISALLOWED_PATHS_NOT_FETCHED")
    assert "Disallow: /internal/" in finding.evidence["rules"]


def test_robots_disallow_is_enforced_before_the_request_is_sent(base_url):
    fetcher = Fetcher(base_url, delay=0, backoff=0)
    fetcher.load_robots()
    assert fetcher.get("/internal/margin-sheet.html") is None
    assert fetcher.log[-1].outcome == "refused_by_robots"
    assert fetcher.log[-1].status is None


def test_crawl_delay_is_taken_from_robots_when_not_overridden(base_url):
    fetcher = Fetcher(base_url, backoff=0)
    fetcher.load_robots()
    assert fetcher.delay == 1.0
    assert Fetcher(base_url, delay=0).delay == 0.0


def test_missing_detail_pages_are_recorded_not_swallowed(snapshot):
    finding = next(f for f in snapshot.findings if f.id == "DETAIL_PAGES_MISSING")
    assert finding.severity == "advisory"
    assert len(finding.evidence["urls"]) >= 1


def test_price_history_comes_back_with_the_listing(snapshot):
    assert snapshot.history["10"] == [
        ("2026-06-27", 250.0), ("2026-06-20", 244.0)]


def test_detail_price_is_cross_checked_against_the_card(snapshot):
    finding = next(f for f in snapshot.findings
                   if f.id == "DETAIL_PRICE_DISAGREES_WITH_LISTING")
    # The Liar city cards say 197.31; its detail pages say 250.00.
    assert set(finding.evidence["listing_ids"]) == {"100", "101", "200", "300"}


def test_listings_only_skips_detail_pages(base_url):
    snap = crawl(Fetcher(base_url, delay=0, backoff=0), with_details=False)
    assert snap.history == {}
    assert len(snap.listings) == 10


def test_snapshot_round_trips_through_the_store(snapshot, tmp_path):
    path = tmp_path / "snapshot.db"
    run_id = store.write(snapshot, path)

    rows = store.listings(run_id, path)
    assert len(rows) == 10
    assert {r["city"] for r in rows} == {"Honest", "Liar"}

    run = store.latest_run(path)
    assert run is not None
    assert run["run_id"] == run_id
    assert run["listings"] == 10
    assert run["pages_rejected"] == 1
    assert run["crawl_delay_s"] == 0.0

    ids = {f["finding_id"] for f in store.findings(run_id, path)}
    assert "PAGINATION_LINKS_MISLEAD" in ids
    assert isinstance(
        next(f for f in store.findings(run_id, path)
             if f["finding_id"] == "LISTINGS_REPEAT_ACROSS_PAGES")["evidence"],
        dict,
    )


def test_two_runs_are_kept_side_by_side(snapshot, tmp_path):
    path = tmp_path / "twice.db"
    first = store.write(snapshot, path)
    second = store.write(snapshot, path)
    assert second > first
    assert len(store.listings(first, path)) == len(store.listings(second, path))
