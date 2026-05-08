from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import httpx

from src.config import get_config
from src.fetch.cache import CacheEntry, FetchCache, get_cache
from src.fetch.extractors import ContentExtractor, get_extractor
from src.parsing.sage_extractor import get_sage_pipeline

logger = logging.getLogger(__name__)


class FetchEngine:
    """
    Async web fetch engine with caching and rate limiting.

    Features:
    - Async HTTP fetching via httpx
    - Per-domain concurrency limiting (max 3 concurrent per domain)
    - Global concurrency limit (max 10)
    - 1-second minimum delay between requests to same domain
    - Cache integration (check before fetch, store after, fallback to stale)
    - Batch fetch support
    """

    def __init__(
        self,
        cache: FetchCache | None = None,
        extractor: ContentExtractor | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._cache = cache or get_cache()
        self._extractor = extractor or get_extractor()
        self._timeout = timeout
        self._config = get_config()

        # Concurrency control
        self._global_semaphore = asyncio.Semaphore(10)
        self._domain_semaphores: dict[str, asyncio.Semaphore] = defaultdict(
            lambda: asyncio.Semaphore(3)
        )
        self._domain_last_request: dict[str, float] = defaultdict(float)
        self._domain_lock = asyncio.Lock()

        # HTTP client
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout=self._timeout, connect=10.0),
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-CA,en;q=0.9",
                "Accept-Encoding": "gzip, deflate, br",
            },
        )

    async def fetch(self, url: str) -> str:
        """Fetch and return clean text content from a URL."""
        url = self._normalize_url(url)
        async with self._global_semaphore:
            return await self._fetch_with_concurrency(url)

    def _normalize_url(self, url: str) -> str:
        """Rewrite laws-lois act index pages to their FullText.html version for full text retrieval."""
        import re
        if re.search(r'laws-lois\.justice\.gc\.ca/eng/acts/[^/]+/$', url):
            return url.rstrip('/') + '/FullText.html'
        return url

    async def _fetch_with_concurrency(self, url: str) -> str:
        """Fetch with per-domain and global concurrency limits."""
        domain = self._get_domain(url)

        # Check minimum delay for domain
        async with self._domain_lock:
            last_request = self._domain_last_request[domain]
            delay_required = 1.0 - (time.time() - last_request)
            if delay_required > 0:
                await asyncio.sleep(delay_required)
                self._domain_last_request[domain] = time.time()

        async with self._domain_semaphores[domain]:
            return await self._do_fetch(url)

    async def _do_fetch(self, url: str) -> str:
        """Perform the actual fetch with cache fallback."""
        # Check fresh cache first
        cached = await self._cache.get(url)
        if cached is not None:
            logger.debug("Cache hit for %s", url)
            self._schedule_deterministic_parsing(url, cached.content)
            return cached.content

        # Attempt fetch
        try:
            response = await self._client.get(url)
            response.raise_for_status()

            content = self._extractor.extract(url, response.text)

            # Store in cache
            await self._cache.set_cached(
                CacheEntry(
                    url=url,
                    content=content,
                    ttl_hours=self._cache._get_default_ttl(url),
                    status_code=response.status_code,
                    content_length=len(response.text),
                )
            )

            logger.info("Successfully fetched %s (%d bytes)", url, len(content))
            self._schedule_deterministic_parsing(url, content)
            return content

        except (httpx.RequestError, httpx.HTTPStatusError) as e:
            logger.warning("Fetch failed for %s: %s", url, e)

            # Try stale cache
            stale = await self._cache.get_stale(url)
            if stale is not None:
                logger.info("Using stale cache for %s", url)
                return stale.content

            if not self._config.fetch.browser_fallback_enabled:
                raise FetchError(f"Failed to fetch {url}: httpx={e}") from e

            # Browser fallback for bot-protected sites (e.g. tbs-sct.canada.ca)
            logger.info("Attempting browser fallback for %s", url)
            try:
                from src.fetch.browser import BrowserFetchError, get_browser_fetcher

                html = await get_browser_fetcher().fetch(url)
                content = self._extractor.extract(url, html)
                await self._cache.set_cached(
                    CacheEntry(
                        url=url,
                        content=content,
                        ttl_hours=self._cache._get_default_ttl(url),
                        status_code=200,
                        content_length=len(html),
                    )
                )
                logger.info("Browser fallback succeeded for %s (%d bytes)", url, len(content))
                self._schedule_deterministic_parsing(url, content)
                return content
            except BrowserFetchError as browser_err:
                logger.warning("Browser fallback failed for %s: %s", url, browser_err)
                raise FetchError(
                    f"Failed to fetch {url}: httpx={e}, browser={browser_err}"
                ) from e

    async def fetch_batch(self, urls: list[str]) -> dict[str, str]:
        """Fetch multiple URLs concurrently within rate limits."""
        results: dict[str, str] = {}

        async def fetch_one(url: str) -> tuple[str, str | None]:
            try:
                content = await self.fetch(url)
                return (url, content)
            except FetchError as e:
                logger.error("Batch fetch error for %s: %s", url, e)
                return (url, None)

        tasks = [fetch_one(url) for url in urls]
        responses = await asyncio.gather(*tasks, return_exceptions=True)

        for result in responses:
            if isinstance(result, tuple) and result[1] is not None:
                results[result[0]] = result[1]

        return results

    def _get_domain(self, url: str) -> str:
        """Extract domain from URL."""
        try:
            return url.split("//")[-1].split("/")[0]
        except Exception:
            return "default"

    def _schedule_deterministic_parsing(self, url: str, content: str) -> None:
        if not self._config.parsing.enabled:
            return

        async def run_parser() -> None:
            try:
                await get_sage_pipeline().process_document_for_url(url, content)
            except Exception as e:
                logger.warning("Deterministic parsing failed for %s: %s", url, e)

        try:
            asyncio.create_task(run_parser())
        except RuntimeError as e:
            logger.debug("No running event loop for deterministic parsing of %s: %s", url, e)

    async def close(self) -> None:
        """Close the HTTP client."""
        await self._client.aclose()

    async def health_check(self) -> dict[str, Any]:
        """Check engine health."""
        return {
            "status": "ok",
            "global_semaphore_available": self._global_semaphore._value,
            "domains_tracked": len(self._domain_last_request),
        }


_engine: FetchEngine | None = None


class FetchError(Exception):
    """Raised when a fetch operation fails."""

    pass


def get_fetch_engine() -> FetchEngine:
    """Return singleton fetch engine instance."""
    global _engine
    if _engine is None:
        _engine = FetchEngine()
    return _engine


async def cleanup_fetch_engine() -> None:
    """Clean up the fetch engine (called on app shutdown)."""
    global _engine
    if _engine is not None:
        await _engine.close()
        _engine = None
