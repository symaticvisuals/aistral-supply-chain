"""A tiny synthetic database with numbers you can check on paper.

Built at runtime into tmp_path — never committed, both because the repo
gitignores *.db and because a fixture you can regenerate is one you can trust.

The shape is chosen so every exclusion has a loud detector: the test, closed and
deleted outlets each carry a 0%-fill order big enough that if any of them leaks
into the scope, execution collapses and a test fails loudly.

    outlet 101  Balaji Provision   ACTIVE           <- the only one that counts
    outlet 102  ZZ_TEST_OUTLET     ACTIVE           <- matches test pattern
    outlet 103  Closed Shop        CLOSED
    outlet 104  Deleted Shop       ACTIVE, is_deleted=1

Outlet 101's attempted orders:
    order 1  DELIVERED  CASE pack 24  ordered 10  allocated 10  delivered  8
    order 2  PARTIAL    EACH pack 10  ordered 50  allocated 40  delivered 20

      ordered_cases   10 + 50/10 = 15        delivered_cases   8 + 20/10 = 10
      ordered_eaches  240 + 50   = 290       delivered_eaches  192 + 20  = 212
      allocated_eaches 240 + 40  = 280

      execution   = 10/15                    = 66.666...%
      CASE-only   =  8/10                    = 80%     (drops order 2 entirely)

Outlet 101's refused orders:
    order 3  CANCELLED CR03_NO_STOCK      CASE pack 24  ordered 5   -> counts by default
    order 4  CANCELLED CR02_OUTLET_CLOSED CASE pack 24  ordered 3   -> never counts
    order 5  OPEN                         CASE pack 24  ordered 7   -> excluded, flagged

      availability = 15 / (15 + 5) = 75%
      service      = 66.666% x 75% = 50%      and 10/20 = 50%, so the identity holds
"""

import sqlite3
from datetime import date
from pathlib import Path

import pytest

from app.settings import settings

SCHEMA = """
CREATE TABLE regions (region_id INTEGER, region_code TEXT, region_name TEXT);
CREATE TABLE warehouses (warehouse_id INTEGER, warehouse_code TEXT,
                         warehouse_name TEXT, city TEXT, region_id INTEGER);
CREATE TABLE routes (route_id INTEGER, route_code TEXT, warehouse_id INTEGER,
                     region_id INTEGER);
CREATE TABLE outlets (outlet_id INTEGER, outlet_code TEXT, outlet_name TEXT,
                      channel TEXT, city TEXT, region_id INTEGER, route_id INTEGER,
                      status TEXT, is_deleted INTEGER, gst_number TEXT);
CREATE TABLE products (product_id INTEGER, sku_code TEXT, product_name TEXT,
                       case_pack INTEGER, storage_temp_band TEXT, category TEXT,
                       is_chilled INTEGER, list_price_inr REAL, mrp_inr REAL);
CREATE TABLE inventory_snapshots (snapshot_id INTEGER, snapshot_date TEXT,
                                  warehouse_id INTEGER, product_id INTEGER,
                                  batch_id TEXT, on_hand_cases INTEGER,
                                  on_hand_eaches INTEGER, allocated_cases INTEGER,
                                  available_cases INTEGER, days_of_cover REAL,
                                  expiry_date TEXT, ageing_bucket TEXT,
                                  damaged_cases INTEGER, blocked_cases INTEGER,
                                  storage_temp_celsius REAL);
CREATE TABLE orders (order_id INTEGER, order_number TEXT, outlet_id INTEGER,
                     order_date TEXT, region_id INTEGER, route_id INTEGER,
                     warehouse_id INTEGER, order_status TEXT,
                     cancelled_reason_code TEXT, source_system TEXT,
                     order_value_gross_inr REAL, discount_amount_inr REAL,
                     tax_amount_inr REAL, order_value_net_inr REAL, created_at TEXT);
CREATE TABLE order_lines (order_line_id INTEGER, order_id INTEGER, line_number INTEGER,
                          product_id INTEGER, ordered_qty REAL, qty_uom TEXT,
                          case_pack_at_order INTEGER, allocated_qty REAL,
                          delivered_qty REAL, unit_price_inr REAL,
                          line_discount_pct REAL, line_value_inr REAL,
                          short_reason_code TEXT);
CREATE TABLE deliveries (delivery_id INTEGER, order_id INTEGER,
                         delivery_note_number TEXT, route_id INTEGER,
                         warehouse_id INTEGER, vehicle_registration TEXT,
                         planned_arrival TEXT, actual_arrival TEXT,
                         telematics_vendor TEXT, delay_minutes INTEGER,
                         delivery_status TEXT, temperature_excursion_flag INTEGER,
                         max_temp_celsius REAL, fuel_cost_inr REAL);
CREATE TABLE returns_credit_notes (return_id INTEGER, credit_note_number TEXT,
                                   order_id INTEGER, order_line_id INTEGER,
                                   outlet_id INTEGER, product_id INTEGER,
                                   return_date TEXT, return_qty REAL, qty_uom TEXT,
                                   return_reason_code TEXT,
                                   credit_note_value_inr REAL, approved_by TEXT,
                                   approval_date TEXT, disposition TEXT,
                                   status TEXT);
"""

OUTLETS = [
    (101, "OUT101", "Balaji Provision", "GT", "Mumbai", 1, 1, "ACTIVE", 0, "GST101"),
    (102, "OUT102", "ZZ_TEST_OUTLET", "GT", "Guwahati", 1, 1, "ACTIVE", 0, "GST102"),
    (103, "OUT103", "Closed Shop", "GT", "Pune", 1, 1, "CLOSED", 0, "GST103"),
    (104, "OUT104", "Deleted Shop", "GT", "Bengaluru", 1, 1, "ACTIVE", 1, "GST104"),
]

# (order_id, outlet, date, status, cancel_reason)
ORDERS = [
    (1, 101, "2026-05-01", "DELIVERED", None),
    (2, 101, "2026-05-02", "PARTIAL", None),
    (3, 101, "2026-05-03", "CANCELLED", "CR03_NO_STOCK"),
    (4, 101, "2026-05-04", "CANCELLED", "CR02_OUTLET_CLOSED"),
    (5, 101, "2026-05-05", "OPEN", None),
    (6, 102, "2026-05-06", "DELIVERED", None),
    (7, 103, "2026-05-07", "DELIVERED", None),
    (8, 104, "2026-05-08", "DELIVERED", None),
    # outside the FY26 Q1 window, must never appear
    (9, 101, "2026-03-15", "DELIVERED", None),
]

# (order_id, line_no, uom, pack, ordered, allocated, delivered, short_reason)
LINES = [
    (1, 1, "CASE", 24, 10.0, 10.0, 8.0, "SH03_VEHICLE_CAP"),
    (2, 1, "EACH", 10, 50.0, 40.0, 20.0, "SH01_STOCKOUT"),
    (3, 1, "CASE", 24, 5.0, 0.0, 0.0, None),
    (4, 1, "CASE", 24, 3.0, 0.0, 0.0, None),
    (5, 1, "CASE", 24, 7.0, 7.0, 6.0, "SH02_DAMAGE"),
    # loud detectors: 0% fill on rows that must be excluded
    (6, 1, "CASE", 24, 100.0, 0.0, 0.0, "SH01_STOCKOUT"),
    (7, 1, "CASE", 24, 100.0, 0.0, 0.0, "SH01_STOCKOUT"),
    (8, 1, "CASE", 24, 100.0, 0.0, 0.0, "SH01_STOCKOUT"),
    (9, 1, "CASE", 24, 100.0, 0.0, 0.0, "SH01_STOCKOUT"),
]


def build_db(path: Path) -> Path:
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    conn.execute("INSERT INTO regions VALUES (1, 'WST', 'West')")
    conn.execute("INSERT INTO regions VALUES (2, 'NTH', 'North')")
    conn.execute(
        "INSERT INTO warehouses VALUES (1, 'WH01', 'Bhiwandi DC', 'Mumbai', 1)"
    )
    conn.execute("INSERT INTO routes VALUES (1, 'RT0001', 1, 1)")
    conn.executemany("INSERT INTO outlets VALUES (?,?,?,?,?,?,?,?,?,?)", OUTLETS)
    conn.execute(
        "INSERT INTO products VALUES (1, 'SKU1', 'Test Product', 24, 'AMBIENT',"
        " 'Staples', 0, 50.0, 70.0)"
    )
    conn.execute(
        "INSERT INTO products VALUES (2, 'SKU2', 'Chilled Product', 12, 'CHILLED',"
        " 'Dairy', 1, 100.0, 140.0)"
    )
    # Stock on the rack, as of 2026-05-01. Hand-checkable:
    #   B001  cover 35 > 20 days left  -> cannot sell through
    #         100 cases x 24 pack x Rs 50  = Rs 120,000
    #   B002  cover  5 < 20 days left  -> near expiry, but it will move
    #          50 cases x 12 pack x Rs 100 = Rs 60,000
    #   B003  214 days left            -> neither; must never appear
    #   B004  sits on an older snapshot -> must never appear for 2026-05-01
    # (id, date, wh, product, batch, on_hand, eaches, alloc, avail, cover,
    #  expiry, bucket, damaged, blocked, temp)
    conn.executemany(
        "INSERT INTO inventory_snapshots VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            (1, "2026-05-01", 1, 1, "B001", 100, 2400, 0, 100, 35.0,
             "2026-05-21", "0-30", 0, 0, 22.0),
            (2, "2026-05-01", 1, 2, "B002", 50, 600, 0, 50, 5.0,
             "2026-05-21", "90+", 0, 0, 3.0),
            (3, "2026-05-01", 1, 1, "B003", 10, 240, 0, 10, 5.0,
             "2026-12-01", "90+", 0, 0, 22.0),
            (4, "2026-04-24", 1, 1, "B004", 999, 23976, 0, 999, 40.0,
             "2026-04-25", "0-30", 0, 0, 22.0),
        ],
    )

    for oid, outlet, day, status, reason in ORDERS:
        # header value ties to lines exactly, as it does in the real pack
        conn.execute(
            "INSERT INTO orders VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (oid, f"ORD{oid}", outlet, day, 1, 1, 1, status, reason,
             "ERP_WEB", 1000.0, 100.0, 180.0, 1080.0, f"{day} 10:00:00"),
        )
    for oid, ln, uom, pack, ordered, alloc, delivered, reason in LINES:
        # Order 2 carries the chilled SKU; everything else is ambient. Quantities
        # are untouched, so the fill arithmetic above still holds — this only
        # gives delivery DN0002 something that can actually spoil.
        product = 2 if oid == 2 else 1
        # Price is back-solved so line_value_inr lands on 1000.0 and still ties to
        # the header. line_value therefore prices the *ordered* quantity, exactly
        # as the real pack does — which is what makes the dispatch-value finding
        # fire here too.
        conn.execute(
            "INSERT INTO order_lines VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (oid * 10 + ln, oid, ln, product, ordered, uom, pack, alloc, delivered,
             1000.0 / ordered, 0.0, 1000.0, reason),
        )
    # Two drops: one clean, one warm and badly late. Deliberately uses both
    # vendor timestamp formats so the parser is exercised.
    #
    # DN0001 is the trap. Its vendor flag says excursion, but it rode at 3.1C
    # with only ambient stock aboard — the real pack flags loads exactly like
    # this. Cold chain must ignore it. DN0002 has the flag *off* and carries
    # chilled stock at 12.4C, which is the one that must show up.
    conn.executemany(
        "INSERT INTO deliveries VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            (1, 1, "DN0001", 1, 1, "MH01A0001", "2026-05-01 08:00:00",
             "2026-05-01 08:00:00", "TELEMATICS_A", 0, "DELIVERED", 1, 3.1, 500.0),
            (2, 2, "DN0002", 1, 1, "MH01B0002", "02-May-2026 08:00 AM",
             "02-May-2026 11:30 AM", "TELEMATICS_B", 210, "DELIVERED", 0, 12.4, 620.0),
        ],
    )
    # Deliberately the mirror image of the real pack: here the reason code DOES
    # predict things (RT06 only on chilled, dispositions differ, approval dated),
    # so a "clean" verdict on this fixture proves the noise checks discriminate
    # rather than always firing.
    # (id, cn_no, order, line, outlet, product, date, qty, uom, reason,
    #  value, approved_by, approval_date, disposition, status)
    RETURNS = [
        (1, "CN1", 1, 1, 101, 2, "2026-05-10", -5.0, "CASE",
         "RT06_COLD_CHAIN_BREACH", 5000.0, "RSM", "2026-05-12", "SCRAP", "APPROVED"),
        (2, "CN2", 1, 1, 101, 1, "2026-05-11", 3.0, "CASE",
         "RT01_NEAR_EXPIRY", 3000.0, "ASM", None, "RESTOCK", "PENDING"),
        (3, "CN3", 2, 1, 101, 1, "2026-05-12", 2.0, "CASE",
         "RT01_NEAR_EXPIRY", 2000.0, "AUTO", None, "RESTOCK", "REJECTED"),
        # Before the window, so only the un-windowed pending queue should see it.
        (4, "CN4", 2, 1, 101, 1, "2025-06-01", 1.0, "CASE",
         "RT05_OVERSUPPLY", 1000.0, "ASM", None, "SCRAP", "PENDING"),
        # On a test outlet — must be filtered out everywhere.
        (5, "CN5", 6, 1, 102, 1, "2026-05-13", 4.0, "CASE",
         "RT01_NEAR_EXPIRY", 9999.0, "ASM", None, "SCRAP", "APPROVED"),
    ]
    conn.executemany(
        "INSERT INTO returns_credit_notes VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        RETURNS,
    )
    conn.commit()
    conn.close()
    return path


@pytest.fixture(scope="session")
def fixture_db(tmp_path_factory) -> Path:
    return build_db(tmp_path_factory.mktemp("kestrel") / "fixture.db")


@pytest.fixture
def conn(fixture_db):
    c = sqlite3.connect(f"file:{fixture_db}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    try:
        yield c
    finally:
        c.close()


@pytest.fixture
def window():
    from app.metrics.windows import parse_window

    return parse_window("fy26q1", max_date=date(2026, 6, 30))


@pytest.fixture(autouse=True)
def no_stray_snapshot(tmp_path, monkeypatch):
    """No test reads the snapshot that happens to be on this machine.

    Prices come from a scrape someone may or may not have run, so without this
    the same test passes or fails depending on whether a colleague ran the
    scraper this morning. Tests that want prices point this at their own file.
    """
    monkeypatch.setattr(
        type(settings), "bazaarpulse_path",
        property(lambda _self: tmp_path / "no-scrape-here.db"),
    )
