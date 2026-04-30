from __future__ import annotations

import asyncio
import logging
import os

logger = logging.getLogger(__name__)

_browser_fetcher: BrowserFetcher | None = None
_init_lock: asyncio.Lock | None = None


def _get_init_lock() -> asyncio.Lock:
    global _init_lock
    if _init_lock is None:
        _init_lock = asyncio.Lock()
    return _init_lock


class BrowserFetcher:
    """
    Lazy singleton wrapper around a Playwright headless Chromium browser.

    Started on first use, reused across calls. Each fetch() gets a fresh
    isolated browser context so no cookies or session state bleeds between requests.
    """

    _NAV_TIMEOUT_MS = 30_000
    _WAIT_UNTIL = "networkidle"  # wait for JS-rendered content (e.g. TBS Web Experience Toolkit)

    def __init__(self) -> None:
        self._playwright = None
        self._browser = None
        self._ready = False

    async def _ensure_started(self) -> None:
        if self._ready:
            return
        async with _get_init_lock():
            if self._ready:
                return
            from playwright.async_api import async_playwright

            logger.info("Starting headless Chromium via Playwright")
            self._playwright = await async_playwright().start()

            executable_path = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH")
            if executable_path:
                logger.info("Using system Chromium at %s", executable_path)

            launch_kwargs: dict = {
                "headless": True,
                "args": [
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--no-first-run",
                    "--disable-extensions",
                ],
            }
            if executable_path:
                launch_kwargs["executable_path"] = executable_path

            self._browser = await self._playwright.chromium.launch(**launch_kwargs)
            self._ready = True
            logger.info("Headless Chromium ready")

    async def fetch(self, url: str) -> str:
        """Navigate to url and return the fully-rendered page HTML."""
        await self._ensure_started()
        context = None
        page = None
        try:
            context = await self._browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"
                ),
                locale="en-CA",
                extra_http_headers={
                    "Accept-Language": "en-CA,en;q=0.9",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                },
            )
            page = await context.new_page()
            page.set_default_navigation_timeout(self._NAV_TIMEOUT_MS)

            response = await page.goto(url, wait_until=self._WAIT_UNTIL)
            if response is None:
                raise BrowserFetchError(f"No response from browser for {url}")
            if not response.ok:
                raise BrowserFetchError(f"Browser got HTTP {response.status} for {url}")

            html = await page.content()
            logger.info("Browser fetch succeeded for %s (%d bytes)", url, len(html))
            return html

        except BrowserFetchError:
            raise
        except Exception as exc:
            raise BrowserFetchError(f"Browser fetch failed for {url}: {exc}") from exc
        finally:
            if page is not None:
                try:
                    await page.close()
                except Exception:
                    pass
            if context is not None:
                try:
                    await context.close()
                except Exception:
                    pass

    async def close(self) -> None:
        if self._browser is not None:
            try:
                await self._browser.close()
            except Exception as exc:
                logger.warning("Error closing browser: %s", exc)
            finally:
                self._browser = None
        if self._playwright is not None:
            try:
                await self._playwright.stop()
            except Exception as exc:
                logger.warning("Error stopping Playwright: %s", exc)
            finally:
                self._playwright = None
        self._ready = False
        logger.info("Headless Chromium shut down")

    async def health_check(self) -> dict:
        return {
            "browser_ready": self._ready,
            "browser_connected": (
                self._browser.is_connected() if self._ready and self._browser else False
            ),
        }


class BrowserFetchError(Exception):
    pass


def get_browser_fetcher() -> BrowserFetcher:
    global _browser_fetcher
    if _browser_fetcher is None:
        _browser_fetcher = BrowserFetcher()
    return _browser_fetcher


async def cleanup_browser_fetcher() -> None:
    global _browser_fetcher
    if _browser_fetcher is not None:
        await _browser_fetcher.close()
        _browser_fetcher = None
