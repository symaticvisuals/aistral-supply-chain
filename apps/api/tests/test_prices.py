"""The join between the shelf and our own catalogue."""

import sqlite3
from datetime import date

import pytest

from app.bazaarpulse.store import SCHEMA
from app.metrics import prices


@pytest.fixture
def pack(tmp_path):
    db = tmp_path / "pack.db"
    conn = sqlite3.connect(db)
    conn.execute("""CREATE TABLE products (sku_code TEXT, product_name TEXT,
                    brand TEXT, category TEXT, mrp_inr REAL)""")
    conn.executemany(
        "INSERT INTO products VALUES (?,?,?,?,?)",
        [
            ("SKU1", "Kestrel Select Juice 200ml", "Kestrel", "Beverages", 58.0),
            # Two live SKUs share a name and pack. Only the MRP tells them apart.
            ("SKU2", "Kestrel Juice 200ml", "Kestrel", "Beverages", 83.0),
            ("SKU3", "Kestrel Juice 200ml", "Kestrel", "Beverages", 46.0),
            ("SKU4", "Coastline Frozen Paratha 400g", "Coastline", "Frozen", 200.0),
        ],
    )
    conn.commit()
    conn.close()
    out = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    out.row_factory = sqlite3.Row
    yield out
    out.close()


def snapshot(tmp_path, listings, history=(), finished="2026-07-01T00:00:00"):
    db = tmp_path / "snap.db"
    conn = sqlite3.connect(db)
    conn.executescript(SCHEMA)
    conn.execute(
        "INSERT INTO scrape_run (run_id, base_url, started_at, finished_at,"
        " crawl_delay_s, robots_found, pages_ok, pages_rejected, listings,"
        " repeat_appearances, history_rows, details_fetched)"
        " VALUES (1,'http://x/','2026-07-01T00:00:00',?,1,1,1,0,?,0,0,0)",
        (finished, len(listings)),
    )
    for row in listings:
        conn.execute(
            "INSERT INTO listing (run_id, listing_id, city, retailer, title,"
            " price_inr, mrp_inr, availability, last_seen)"
            " VALUES (1,?,?,?,?,?,?,?,?)", row,
        )
    for row in history:
        conn.execute(
            "INSERT INTO price_history (run_id, listing_id, observed_on,"
            " price_inr) VALUES (1,?,?,?)", row,
        )
    conn.commit()
    conn.close()
    return db


def test_normalise_strips_the_noise_retailers_add():
    assert prices.normalise("Combo KESTREL SEL. JUICE 200ML | Best Before 6M") == (
        "kestrel select juice", (200.0, "ML"))
    assert prices.normalise("Pack of 1 Amritvalley Frzn Paratha 400Ml (New)") == (
        "amrit valley frozen paratha", (400.0, "ML"))
    assert prices.normalise("Bluepeak Inst. Noodles 1000ml") == (
        "bluepeak instant noodles", (1000.0, "ML"))


def test_no_snapshot_at_all_is_none_not_an_empty_book(pack, tmp_path):
    """"We have no prices" and "the prices say nothing" are different sentences."""
    assert prices.load(pack, tmp_path / "absent.db") is None


def test_a_run_that_never_finished_is_not_used(pack, tmp_path):
    db = snapshot(tmp_path, [("1", "Mumbai", "FreshCart",
                              "Kestrel Select Juice 200ml", 48.0, 58.0,
                              "in_stock", "2026-06-27")], finished=None)
    assert prices.load(pack, db) is None


def test_mrp_breaks_a_name_collision_our_own_master_cannot(pack, tmp_path):
    db = snapshot(tmp_path, [
        ("1", "Mumbai", "FreshCart", "Kestrel Juice 200ml", 70.0, 83.0,
         "in_stock", "2026-06-27"),
        ("2", "Mumbai", "DailyKart", "Kestrel Juice 200ml", 40.0, 46.0,
         "in_stock", "2026-06-27"),
    ])
    book = prices.load(pack, db)
    assert book is not None
    assert book.matched_n == 2
    assert {s.sku for s in book.shelves} == {"SKU2", "SKU3"}
    assert book.city_price("SKU2", "Mumbai").price_inr == 70.0
    assert book.city_price("SKU3", "Mumbai").price_inr == 40.0


def test_price_is_the_mean_of_its_observations_not_the_latest(pack, tmp_path):
    """The newest card price is one draw from a series with no trend."""
    db = snapshot(
        tmp_path,
        [("1", "Mumbai", "FreshCart", "Kestrel Select Juice 200ml", 60.0, 58.0,
          "in_stock", "2026-06-27")],
        history=[("1", "2026-06-27", 60.0), ("1", "2026-06-20", 40.0),
                 ("1", "2026-06-13", 50.0)],
    )
    book = prices.load(pack, db)
    shelf = book.shelves[0]
    assert shelf.price_inr == 50.0
    assert shelf.latest_inr == 60.0
    assert shelf.observations == 3


def test_a_city_carries_both_the_typical_price_and_the_deepest_discount(
    pack, tmp_path
):
    db = snapshot(tmp_path, [
        ("1", "Mumbai", "FreshCart", "Kestrel Select Juice 200ml", 58.0, 58.0,
         "in_stock", "2026-06-27"),
        ("2", "Mumbai", "DailyKart", "Kestrel Select Juice 200ml", 40.0, 58.0,
         "in_stock", "2026-06-27"),
        ("3", "Mumbai", "QuickBasket", "Kestrel Select Juice 200ml", 49.0, 58.0,
         "in_stock", "2026-06-27"),
    ])
    city = prices.load(pack, db).city_price("SKU1", "Mumbai")
    assert (city.price_inr, city.lowest_inr) == (49.0, 40.0)
    assert city.listings == 3
    assert round(city.lowest_vs_mrp_pct) == -31
    assert city.retailers == ["DailyKart", "FreshCart", "QuickBasket"]


def test_a_price_on_an_unavailable_listing_is_not_a_shelf_price(pack, tmp_path):
    db = snapshot(tmp_path, [
        ("1", "Mumbai", "FreshCart", "Kestrel Select Juice 200ml", 58.0, 58.0,
         "in_stock", "2026-06-27"),
        ("2", "Mumbai", "DailyKart", "Kestrel Select Juice 200ml", 10.0, 58.0,
         "unavailable", "2026-06-27"),
    ])
    city = prices.load(pack, db).city_price("SKU1", "Mumbai")
    assert (city.lowest_inr, city.listings) == (58.0, 1)


def test_age_is_measured_from_the_observation_not_the_crawl(pack, tmp_path):
    """We crawled in August; the site last saw these shelves in June."""
    db = snapshot(
        tmp_path,
        [("1", "Mumbai", "FreshCart", "Kestrel Select Juice 200ml", 58.0, 58.0,
          "in_stock", "2026-06-20")],
        finished="2026-08-15T18:04:47+00:00",
    )
    book = prices.load(pack, db)
    assert book.observed_to == date(2026, 6, 20)
    assert book.age_days(date(2026, 6, 30)) == 10
    assert book.scraped_on == date(2026, 8, 15)


def test_a_dc_in_a_city_we_do_not_scrape_has_no_price(pack, tmp_path):
    db = snapshot(tmp_path, [
        ("1", "Mumbai", "FreshCart", "Kestrel Select Juice 200ml", 58.0, 58.0,
         "in_stock", "2026-06-27")])
    book = prices.load(pack, db)
    assert book.for_warehouse_city("SKU1", "Mumbai") is not None
    assert book.for_warehouse_city("SKU1", "Pune") is None
    assert book.for_warehouse_city("SKU1", None) is None


def test_above_mrp_is_counted_off_the_observed_price(pack, tmp_path):
    db = snapshot(tmp_path, [
        ("1", "Mumbai", "FreshCart", "Kestrel Select Juice 200ml", 61.0, 58.0,
         "in_stock", "2026-06-27"),
        ("2", "Mumbai", "DailyKart", "Kestrel Select Juice 200ml", 50.0, 58.0,
         "in_stock", "2026-06-27"),
    ])
    breach = prices.load(pack, db).above_mrp()
    assert (breach["listings"], breach["of_listings"], breach["pct"]) == (1, 2, 50.0)
    assert breach["by_retailer"]["FreshCart"] == {"breaches": 1, "listings": 1}


def test_a_title_we_cannot_place_is_named_rather_than_dropped(pack, tmp_path):
    db = snapshot(tmp_path, [
        ("1", "Mumbai", "FreshCart", "Something We Do Not Sell 999g", 10.0, 12.0,
         "in_stock", "2026-06-27")])
    book = prices.load(pack, db)
    assert book.matched_n == 0
    assert book.unmatched == ["Something We Do Not Sell 999g"]
    assert book.match_pct == 0.0


# --- the findings these numbers feed -------------------------------------


def findings(conn, window, book):
    from app.metrics.quality import all_findings

    return {f.id: f for f in all_findings(conn, window, book)}


def test_without_a_scrape_the_screen_says_so(conn, window):
    found = findings(conn, window, None)
    assert "PRICES_NEVER_SCRAPED" in found
    assert "SHELF_PRICE_HAS_NO_MEMORY" not in found
    assert "COMPETITOR_GAP_FLAT_BY_CITY" not in found


def test_a_price_series_with_no_memory_blocks_a_movement_metric(
    conn, window, tmp_path
):
    """Six draws around a mean, correlating exactly as noise does. Nothing
    predicts the next one, so nothing can be alerted on."""
    prices_seen = [44.0, 48.0, 52.0, 50.0, 46.0, 54.0]
    db = snapshot(
        tmp_path,
        [("1", "Mumbai", "FreshCart", "Test Product", 45.0, 70.0,
          "in_stock", "2026-06-27")],
        history=[("1", f"2026-06-{10 + i:02d}", p)
                 for i, p in enumerate(prices_seen)],
    )
    book = prices.load(conn, db)
    finding = findings(conn, window, book)["SHELF_PRICE_HAS_NO_MEMORY"]
    assert finding.severity == "blocks_metric"
    assert "morning" in finding.affects


def test_a_price_series_that_trends_does_not_get_the_same_verdict(
    conn, window, tmp_path
):
    """The check has to be able to come back the other way, or it proves nothing."""
    trending = [30.0, 35.0, 40.0, 45.0, 50.0, 55.0]
    db = snapshot(
        tmp_path,
        [("1", "Mumbai", "FreshCart", "Test Product", 55.0, 70.0,
          "in_stock", "2026-06-27")],
        history=[("1", f"2026-06-{10 + i:02d}", p)
                 for i, p in enumerate(trending)],
    )
    book = prices.load(conn, db)
    finding = findings(conn, window, book)["SHELF_PRICE_HAS_NO_MEMORY"]
    assert finding.severity == "advisory"
    assert finding.evidence["lag1_correlation"] > 0


def test_coverage_is_stated_as_a_ceiling_on_every_price_sentence(
    conn, window, tmp_path
):
    db = snapshot(tmp_path, [("1", "Mumbai", "FreshCart", "Test Product",
                              45.0, 70.0, "in_stock", "2026-06-27")])
    finding = findings(conn, window, prices.load(conn, db))[
        "PRICE_COVERS_PART_OF_THE_BUSINESS"]
    assert finding.evidence["outlets_active"] > 0
    assert finding.evidence["dispatch_share_pct"] is not None
    assert finding.evidence["warehouses_total"] >= finding.evidence[
        "warehouses_inside"]


def test_mrp_agreement_is_reported_as_a_key_not_an_audit(conn, window, tmp_path):
    db = snapshot(tmp_path, [("1", "Mumbai", "FreshCart", "Test Product",
                              45.0, 70.0, "in_stock", "2026-06-27")])
    finding = findings(conn, window, prices.load(conn, db))[
        "SITE_MRP_MIRRORS_MASTER"]
    assert finding.evidence == {"agree": 1, "differ": 0}
    assert "cannot audit the master" in finding.statement
