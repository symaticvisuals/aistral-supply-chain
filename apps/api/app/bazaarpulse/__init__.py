"""Scraping BazaarPulse, the competitor price tracker shipped with the pack.

Four modules, in the order they run: `fetch` speaks HTTP and obeys robots.txt,
`parse` turns a page into rows, `crawl` walks the site and checks that it
actually moved, `store` writes a snapshot nobody has to re-crawl to read.

The scrape is a separate step on purpose. Prices come from a web server that may
be down, and a morning screen that cannot open because a scraper failed is worse
than one that says how old its prices are.
"""
