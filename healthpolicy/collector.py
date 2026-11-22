"""Policy information collection with Firecrawl.

Two modes:
  * live    - Firecrawl `scrape` returns clean markdown for each configured public source.
  * offline - reads saved snapshots from data/fixtures/<cycle>/ (same markdown shape),
              so the pipeline can be demonstrated and tested without API keys.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone

from .config import FIXTURE_DIR, Settings, Source

log = logging.getLogger(__name__)


@dataclass
class RawPage:
    source_id: str
    source_name: str
    url: str
    category: str
    region: str
    authority: str
    title: str
    markdown: str
    fetched_at: str
    mode: str  # live | offline
    status: str = "ok"  # ok | error
    error: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class FirecrawlCollector:
    """Collects public policy pages through the Firecrawl API (firecrawl-py v4)."""

    # Strip navigation / boilerplate before markdown conversion
    EXCLUDE_TAGS = ["nav", "footer", "header", "aside", "script", "style", "form", ".breadcrumb", ".cookie"]

    def __init__(self, settings: Settings, retries: int = 2, timeout_ms: int = 60000):
        if not settings.firecrawl_api_key:
            raise RuntimeError("FIRECRAWL_API_KEY is not set. Use --offline for the demo snapshots.")
        from firecrawl import Firecrawl  # imported lazily so offline mode needs no package

        self.app = Firecrawl(api_key=settings.firecrawl_api_key)
        self.retries = retries
        self.timeout_ms = timeout_ms

    def fetch(self, src: Source) -> RawPage:
        last_err = None
        for attempt in range(self.retries + 1):
            try:
                doc = self.app.scrape(
                    src.url,
                    formats=["markdown"],
                    only_main_content=True,
                    exclude_tags=self.EXCLUDE_TAGS,
                    timeout=self.timeout_ms,
                    max_age=0,  # always fetch fresh content - we are tracking changes
                )
                md = getattr(doc, "markdown", None) or ""
                meta = getattr(doc, "metadata", None)
                title = (getattr(meta, "title", None) if meta else None) or src.name
                return RawPage(src.id, src.name, src.url, src.category, src.region, src.authority,
                               str(title), md, _now(), "live")
            except Exception as e:  # network / rate limit / blocked page
                last_err = str(e)
                log.warning("Firecrawl failed for %s (attempt %d): %s", src.id, attempt + 1, e)
                time.sleep(2 * (attempt + 1))
        return RawPage(src.id, src.name, src.url, src.category, src.region, src.authority,
                       src.name, "", _now(), "live", status="error", error=last_err)


class OfflineCollector:
    """Reads saved Firecrawl-style markdown snapshots for a given crawl cycle."""

    def __init__(self, cycle: str = "cycle1"):
        self.dir = FIXTURE_DIR / cycle
        if not self.dir.exists():
            raise FileNotFoundError(f"No fixture snapshots at {self.dir}")

    def fetch(self, src: Source) -> RawPage:
        path = self.dir / (src.fixture or f"{src.id}.md")
        if not path.exists():
            return RawPage(src.id, src.name, src.url, src.category, src.region, src.authority,
                           src.name, "", _now(), "offline", status="error", error=f"missing {path.name}")
        md = path.read_text(encoding="utf-8")
        return RawPage(src.id, src.name, src.url, src.category, src.region, src.authority,
                       src.name, md, _now(), "offline")


def collect(sources: list[Source], collector) -> list[RawPage]:
    pages = []
    for s in sources:
        page = collector.fetch(s)
        log.info("Collected %-16s %-6s %5d chars", s.id, page.status, len(page.markdown))
        pages.append(page)
    return pages
