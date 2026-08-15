"""Run the scrape.

    uv run python -m app.bazaarpulse

Serve the site first (`cd bazaarpulse_site && python3 -m http.server 8080`).
A full run honours the 1s crawl delay robots.txt asks for, so it takes about
twenty minutes for the whole site and about seventy seconds for the listing
pages alone. `--crawl-delay` overrides it and the value used is written into the
run row, because a scrape that quietly ignored the site's terms should not be
indistinguishable afterwards from one that did not.
"""

import argparse
import sys
from pathlib import Path

from app.bazaarpulse import store
from app.bazaarpulse.crawl import crawl
from app.bazaarpulse.fetch import Fetcher
from app.settings import settings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.bazaarpulse",
        description="Scrape the BazaarPulse competitor price site.",
    )
    parser.add_argument("--base-url", default=settings.bazaarpulse_base_url)
    parser.add_argument("--out", default=None,
                        help="snapshot database (default from settings)")
    parser.add_argument("--crawl-delay", type=float, default=None,
                        help="seconds between requests; default is whatever "
                             "robots.txt asks for")
    parser.add_argument("--listings-only", action="store_true",
                        help="skip the per-listing detail pages and their "
                             "price history")
    parser.add_argument("--detail-limit", type=int, default=None,
                        help="fetch at most this many detail pages")
    parser.add_argument("--quiet", action="store_true")
    return parser


def main(argv: list | None = None) -> int:
    args = build_parser().parse_args(argv)
    say = (lambda _: None) if args.quiet else (lambda m: print(m, flush=True))

    fetcher = Fetcher(args.base_url, delay=args.crawl_delay)
    say(f"scraping {fetcher.base_url}")
    try:
        snapshot = crawl(
            fetcher,
            with_details=not args.listings_only,
            detail_limit=args.detail_limit,
            progress=say,
        )
    except KeyboardInterrupt:
        print("stopped; nothing written", file=sys.stderr)
        return 130

    if not snapshot.listings:
        print(
            f"No listings found at {fetcher.base_url}. Is the site being "
            f"served? cd bazaarpulse_site && python3 -m http.server 8080",
            file=sys.stderr,
        )
        return 1

    path = Path(args.out).expanduser() if args.out else None
    run_id = store.write(snapshot, path)

    say("")
    say(f"run {run_id}: {len(snapshot.listings)} listings, "
        f"{snapshot.pages_ok} pages kept, {snapshot.pages_rejected} rejected, "
        f"{sum(len(v) for v in snapshot.history.values())} history rows")
    for finding in snapshot.findings:
        mark = " " if finding.severity == "clean" else "!"
        say(f" {mark} {finding.id}: {finding.statement}")
    say(f"written to {path or settings.bazaarpulse_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
