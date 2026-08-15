"""Polite HTTP against one static site.

The pack says to treat robots.txt as we would on a live site. So this obeys the
crawl delay, never requests a disallowed path, and — the part that matters —
writes the refusal into the same log as every successful fetch. A scrape that
skipped a page and a scrape that never thought to ask look identical afterwards
unless the refusal is a row.
"""

import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

USER_AGENT = "KestrelControlTower/0.1 (+assignment scraper)"

OK = "ok"
NOT_FOUND = "not_found"
REFUSED = "refused_by_robots"
ERROR = "error"


@dataclass
class Attempt:
    url: str
    outcome: str
    status: int | None = None
    tries: int = 0
    size: int = 0
    note: str | None = None
    # Why we asked. Probing a second pagination convention produces 404s that
    # are the crawl working, not the site being broken, and a log that cannot
    # tell those from a genuinely missing page invites a false finding.
    purpose: str | None = None


@dataclass
class Response:
    url: str
    body: str
    attempt: Attempt


class Fetcher:
    def __init__(
        self,
        base_url: str,
        *,
        delay: float | None = None,
        retries: int = 3,
        timeout: float = 15.0,
        backoff: float = 1.0,
    ) -> None:
        self.base_url = base_url.rstrip("/") + "/"
        self.retries = max(1, retries)
        self.timeout = timeout
        self.backoff = backoff
        self.log: list[Attempt] = []
        self.robots_rules: list[str] = []
        self.robots_found = False
        self._robots = RobotFileParser()
        self._robots.parse([])
        self._delay_override = delay
        self._crawl_delay = 0.0
        self._last_request: float | None = None

    @property
    def delay(self) -> float:
        """What robots.txt asked for, unless a run explicitly overrode it."""
        if self._delay_override is not None:
            return self._delay_override
        return self._crawl_delay

    def load_robots(self) -> None:
        response = self._request(
            urljoin(self.base_url, "robots.txt"), "robots"
        )
        if response is None:
            self.robots_rules = []
            self._robots.parse([])
            return
        self.robots_found = True
        lines = response.body.splitlines()
        self.robots_rules = [ln.strip() for ln in lines if ln.strip()]
        self._robots.parse(lines)
        delay = self._robots.crawl_delay(USER_AGENT)
        self._crawl_delay = float(delay) if delay else 0.0

    def allowed(self, url: str) -> bool:
        if not self.robots_found:
            return True
        return self._robots.can_fetch(USER_AGENT, urlsplit(url).path or "/")

    def get(self, path: str, purpose: str | None = None) -> Response | None:
        url = urljoin(self.base_url, path.lstrip("/"))
        if not self.allowed(url):
            self.log.append(
                Attempt(url, REFUSED, note="Disallowed by robots.txt",
                        purpose=purpose)
            )
            return None
        return self._request(url, purpose)

    def _wait(self) -> None:
        if self._last_request is None or self.delay <= 0:
            return
        remaining = self.delay - (time.monotonic() - self._last_request)
        if remaining > 0:
            time.sleep(remaining)

    def _request(self, url: str, purpose: str | None = None) -> Response | None:
        request = urllib.request.Request(
            url, headers={"User-Agent": USER_AGENT}
        )
        note = None
        for attempt in range(1, self.retries + 1):
            self._wait()
            self._last_request = time.monotonic()
            try:
                with urllib.request.urlopen(  # noqa: S310 - fixed http base
                    request, timeout=self.timeout
                ) as raw:
                    body = raw.read()
                    record = Attempt(
                        url, OK, raw.status, attempt, len(body), note,
                        purpose,
                    )
                    self.log.append(record)
                    return Response(
                        url, body.decode("utf-8", errors="replace"), record
                    )
            except urllib.error.HTTPError as exc:
                if exc.code == 404:
                    self.log.append(
                        Attempt(url, NOT_FOUND, 404, attempt, 0,
                                "No such page", purpose)
                    )
                    return None
                if exc.code == 429:
                    note = "429, honoured Retry-After"
                    self._sleep_retry_after(exc.headers.get("Retry-After"))
                    continue
                if exc.code >= 500 and attempt < self.retries:
                    note = f"{exc.code}, retried"
                    time.sleep(self.backoff * 2 ** (attempt - 1))
                    continue
                self.log.append(
                    Attempt(url, ERROR, exc.code, attempt, 0,
                            str(exc.reason), purpose)
                )
                return None
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                if attempt < self.retries:
                    note = f"{exc}, retried"
                    time.sleep(self.backoff * 2 ** (attempt - 1))
                    continue
                self.log.append(
                    Attempt(url, ERROR, None, attempt, 0, str(exc), purpose)
                )
                return None
        self.log.append(
            Attempt(url, ERROR, None, self.retries, 0, note, purpose)
        )
        return None

    def _sleep_retry_after(self, header: str | None) -> None:
        try:
            time.sleep(min(float(header or 1.0), 30.0))
        except (TypeError, ValueError):
            time.sleep(1.0)
