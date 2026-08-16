"""The parser, against each markup convention the site actually uses.

Fixtures are hand-written rather than copied wholesale: the point is to state
what each convention looks like, so a future change to the site fails a test
that reads like a description of the site.
"""

from app.bazaarpulse import parse


def card(inner: str, listing_id: str = "1") -> str:
    return (
        f'<div class="card product-item" data-listing-id="{listing_id}">'
        f'{inner}</div>'
    )


def page(cards: str, crumb: str = "Home / Mumbai / page 1 of 3",
         pager: str = "") -> str:
    return (
        f'<html><body><div class="wrap"><p class="muted">{crumb}</p>'
        f"<div class='grid'>{cards}</div>"
        f'<p class="pager">{pager}</p></div></body></html>'
    )


MUMBAI = card(
    '<a href="/product/4.html"><strong>KESTREL SEL. JUICE 200ML</strong></a>'
    '<div class="muted">FreshCart &middot; 200 ml &middot; Beverages</div>'
    '<span class="price">&#8377;48.39</span>'
    '<div class="muted">MRP &#8377;58 &middot; In stock &middot; '
    'rated 3.8 (2992)</div>'
    '<div class="muted">Last seen: 2026-06-27</div>',
    listing_id="4",
)

BENGALURU = card(
    '<a href="/product/297.html"><strong>Kestrel Sel. Rusk 400G</strong></a>'
    '<div class="muted">FreshCart &middot; 400 g &middot; Bakery</div>'
    '<span class="pricing-block" data-price-paise="19731" '
    'data-currency="INR">Price on card</span>'
    '<div class="muted">MRP &#8377;245 &middot; In stock &middot; '
    'rated 4.0 (901)</div>'
    '<div class="muted">Last seen: 2026-06-13</div>',
    listing_id="297",
)

CHENNAI = card(
    '<a href="/product/845.html"><strong>Pack of 1 Marwar Chips 150G</strong>'
    '</a><div class="muted">FreshCart &middot; 150 g &middot; Snacks</div>'
    '<b class="sellingPrice">INR 229.86</b>'
    '<div class="muted">MRP &#8377;226 &middot; In stock</div>'
    '<div class="muted">Last seen: 2026-06-11</div>',
    listing_id="845",
)

DELHI = card(
    '<a href="/product/589.html"><strong>Hillfare Butter 750g</strong></a>'
    '<div class="muted">MetroBazaar &middot; 750 g &middot; Dairy</div>'
    '<div class="amt"><em>Rs.</em> 88.68 <small>incl. taxes</small></div>'
    '<div class="muted">MRP &#8377;96 &middot; Currently unavailable</div>'
    '<div class="muted">Last seen: 2026-06-25</div>',
    listing_id="589",
)


def only(html: str):
    result = parse.listing_page(page(html))
    assert len(result.listings) == 1
    return result.listings[0]


def test_reads_each_city_price_convention():
    assert (only(MUMBAI).price_inr, only(MUMBAI).price_source) == (
        48.39, "span.price")
    assert (only(CHENNAI).price_inr, only(CHENNAI).price_source) == (
        229.86, "b.sellingPrice")
    assert (only(DELHI).price_inr, only(DELHI).price_source) == (
        88.68, "div.amt")


def test_bengaluru_price_is_in_an_attribute_not_the_text():
    """The one that breaks a text-only scraper without raising anything."""
    row = only(BENGALURU)
    assert (row.price_inr, row.price_source) == (197.31, "data-price-paise")


def test_delhi_price_split_across_child_tags_is_still_read():
    assert only(DELHI).price_inr == 88.68


def test_listing_carries_the_rest_of_the_card():
    row = only(MUMBAI)
    assert row.listing_id == "4"
    assert row.title == "KESTREL SEL. JUICE 200ML"
    assert (row.retailer, row.pack_text, row.category) == (
        "FreshCart", "200 ml", "Beverages")
    assert row.mrp_inr == 58.0
    assert row.availability == "in_stock"
    assert (row.rating, row.rating_count) == (3.8, 2992)
    assert row.last_seen == "2026-06-27"
    assert row.detail_path == "/product/4.html"


def test_unavailable_is_not_read_as_a_shelf_price():
    assert only(DELHI).availability == "unavailable"


def test_meta_line_without_a_pack_size_does_not_shift_the_category():
    """methodology.html warns some retailers publish no structured pack size."""
    row = only(card(
        '<a href="/product/9.html"><strong>Marwar Chips 150G</strong></a>'
        '<div class="muted">DailyKart &middot; Snacks</div>'
        '<span class="price">&#8377;10</span>'
        '<div class="muted">MRP &#8377;12 &middot; In stock</div>',
        listing_id="9",
    ))
    assert (row.retailer, row.pack_text, row.category) == (
        "DailyKart", None, "Snacks")


def test_breadcrumb_states_which_page_this_is():
    result = parse.listing_page(page(MUMBAI, "Home / Bengaluru / page 13 of 17"))
    assert (result.city, result.page, result.total_pages) == (
        "Bengaluru", 13, 17)
    assert result.listings[0].city == "Bengaluru"


def test_pager_links_are_recorded_as_given():
    result = parse.listing_page(page(
        MUMBAI,
        pager='<a href="/city/bengaluru/index.html?p=2">2</a>'
              '<a href="/city/bengaluru/index.html?p=3">3</a>',
    ))
    assert result.pager == {
        2: "/city/bengaluru/index.html?p=2",
        3: "/city/bengaluru/index.html?p=3",
    }


def test_a_card_without_an_id_or_title_is_not_a_listing():
    assert parse.listing_page(page(card("<em>nothing here</em>"))).listings == []


def test_detail_page_yields_history_newest_first():
    html = (
        '<div class="wrap"><p class="muted">Home / Mumbai / Beverages</p>'
        '<div class="card"><h2>KESTREL SEL. JUICE 200ML</h2>'
        '<p class="muted">Retailer: FreshCart &middot; City: Mumbai '
        '&middot; Pack: 200 ml</p>'
        '<p><strong>Current price:</strong> '
        '<span class="price">&#8377;48.39</span></p>'
        '<p class="muted">MRP &#8377;58 &middot; In stock</p>'
        "<table><tr><th>Observed on</th><th>Price</th></tr>"
        "<tr><td>2026-06-20</td><td>&#8377;47.94</td></tr>"
        "<tr><td>2026-06-27</td><td>&#8377;51.66</td></tr></table>"
        "</div></div>"
    )
    detail = parse.detail_page(html, "4")
    assert detail.title == "KESTREL SEL. JUICE 200ML"
    assert (detail.retailer, detail.city, detail.pack_text) == (
        "FreshCart", "Mumbai", "200 ml")
    assert detail.price_inr == 48.39
    assert detail.mrp_inr == 58.0
    assert detail.history == [("2026-06-27", 51.66), ("2026-06-20", 47.94)]


def detail_html(price_markup: str) -> str:
    return (
        '<div class="wrap"><div class="card"><h2>A Product 400g</h2>'
        '<p class="muted">Retailer: FreshCart &middot; City: Bengaluru '
        '&middot; Pack: 400 g</p>'
        f'<p><strong>Current price:</strong> {price_markup}</p>'
        '<p class="muted">MRP &#8377;245 &middot; In stock</p>'
        "<table><tr><th>Observed on</th><th>Price</th></tr>"
        "<tr><td>2026-06-13</td><td>&#8377;200.34</td></tr></table>"
        "</div></div>"
    )


def test_detail_pages_price_the_same_four_ways_the_listings_do():
    """A detail parser that knew one convention read three cities as priceless
    and then reported that every price it read agreed."""
    cases = [
        ('<span class="price">&#8377;48.39</span>', 48.39, "span.price"),
        ('<span class="pricing-block" data-price-paise="19731">Price on card'
         "</span>", 197.31, "data-price-paise"),
        ('<b class="sellingPrice">INR 229.86</b>', 229.86, "b.sellingPrice"),
        ('<div class="amt"><em>Rs.</em> 88.68 <small>incl. taxes</small></div>',
         88.68, "div.amt"),
    ]
    for markup, expected, source in cases:
        detail = parse.detail_page(detail_html(markup), "1")
        assert (detail.price_inr, detail.price_source) == (expected, source)
        assert detail.mrp_inr == 245.0
        assert detail.history == [("2026-06-13", 200.34)]


def test_history_header_row_is_not_an_observation():
    detail = parse.detail_page(
        "<table><tr><th>Observed on</th><th>Price</th></tr></table>", "4"
    )
    assert detail.history == []
