"""Scrapling integration layer — adaptive crawling with Playwright backend."""

from __future__ import annotations

from typing import Any

try:
    from scrapling import PlayWrightFetcher
    _HAS_SCRAPLING = True
except ImportError:
    _HAS_SCRAPLING = False


class ScraplingEngine:
    """Wraps Scrapling for adaptive element selection."""

    def __init__(self, config: dict):
        self.config = config
        self._fetcher = None

    def _get_fetcher(self):
        if self._fetcher is None:
            if not _HAS_SCRAPLING:
                raise ImportError(
                    "scrapling is not installed. Run: pip install scrapling"
                )
            self._fetcher = PlayWrightFetcher(
                headless=True,
                disable_resources=False,
                network_idle=True,
                ignore_https_errors=True,
            )
        return self._fetcher

    async def fetch_page(self, url: str):
        """Fetch a page with Scrapling's adaptive engine."""
        fetcher = self._get_fetcher()
        page = await fetcher.async_fetch(url)
        return page

    def find_elements(self, page, previous_fingerprints: dict | None = None) -> dict:
        """Find and fingerprint interactive elements using Scrapling adaptive selectors."""
        buttons = page.css('button, [role="button"], input[type="submit"], a.btn')
        tabs = page.css('[role="tab"], .nav-tab, .tab-link')
        grids = page.css('.handsontable, .ag-root, table.dataTable, table')
        links = page.css('a[href]:not([href^="http"])')

        return {
            "buttons": [self._fingerprint(el) for el in buttons],
            "tabs": [self._fingerprint(el) for el in tabs],
            "grids": [self._fingerprint(el) for el in grids],
            "links": [self._fingerprint(el) for el in links],
        }

    def _fingerprint(self, element) -> dict:
        """Create a Scrapling-based fingerprint for adaptive relocation."""
        try:
            fingerprint_hash = element.generate_hash()
        except Exception:
            fingerprint_hash = None

        return {
            "text": getattr(element, "text", ""),
            "tag": getattr(element, "tag", ""),
            "attribs": dict(getattr(element, "attribs", {})),
            "selector": getattr(element, "css_selector", ""),
            "fingerprint": fingerprint_hash,
        }

    async def close(self):
        if self._fetcher is not None:
            try:
                await self._fetcher.close()
            except Exception:
                pass
            self._fetcher = None
