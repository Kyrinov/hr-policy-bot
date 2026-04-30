from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from src.config import get_config
from src.data.db import DatabaseManager

logger = logging.getLogger(__name__)


@dataclass
class CacheEntry:
    url: str
    content: str
    ttl_hours: int
    status_code: int | None = None
    content_length: int | None = None

    @property
    def expires_at(self) -> datetime:
        fetched_at_str = self.fetched_at
        if isinstance(fetched_at_str, str):
            fetched_at = datetime.fromisoformat(fetched_at_str)
        else:
            fetched_at = fetched_at_str
        return fetched_at + timedelta(hours=self.ttl_hours)

    def is_valid(self) -> bool:
        return datetime.utcnow() < self.expires_at

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.content.encode("utf-8")).hexdigest()


class FetchCache:
    def __init__(self, db_manager: DatabaseManager | None = None) -> None:
        self._db_manager = db_manager or DatabaseManager()
        self._config = get_config()

    async def get(self, url: str) -> CacheEntry | None:
        """Return cached content if valid and within TTL, else None."""
        cached = await self._db_manager.get_cached(url)
        if cached is None:
            return None
        return CacheEntry(
            url=cached.url,
            content=cached.content_text,
            ttl_hours=cached.ttl_hours,
            status_code=cached.status_code,
            content_length=cached.content_length,
        )

    async def get_stale(self, url: str) -> CacheEntry | None:
        """Return expired cache entry if available (for fallback)."""
        stale = await self._db_manager.get_stale(url)
        if stale is None:
            return None
        return CacheEntry(
            url=stale.url,
            content=stale.content_text,
            ttl_hours=stale.ttl_hours,
            status_code=stale.status_code,
            content_length=stale.content_length,
        )

    async def set_cached(self, entry: CacheEntry) -> None:
        """Store entry in cache with current timestamp."""
        from src.models.schemas import FetchCacheEntry

        fetched_at = datetime.utcnow()
        db_entry = FetchCacheEntry(
            url=entry.url,
            content_text=entry.content,
            content_hash=entry.content_hash,
            fetched_at=fetched_at,
            ttl_hours=entry.ttl_hours,
            status_code=entry.status_code,
            content_length=entry.content_length,
        )
        await self._db_manager.set_cached(db_entry)

    async def store(self, url: str, content: str, ttl_hours: int | None = None) -> None:
        """Convenience method: store content with auto-TTL selection."""
        ttl = ttl_hours or self._get_default_ttl(url)
        entry = CacheEntry(
            url=url,
            content=content,
            ttl_hours=ttl,
        )
        await self.set_cached(entry)

    def _get_default_ttl(self, url: str) -> int:
        """Return default TTL based on URL domain."""
        legislation_domains = ["laws-lois.justice.gc.ca"]
        collective_domains = [
            "tbs-sct.canada.ca/agreements-conventions",
            "www.njc-cnm.gc.ca/s14",
        ]

        if any(domain in url for domain in legislation_domains):
            return 720
        if any(domain in url for domain in collective_domains):
            return 720
        return self._config.cache.ttl_hours

    async def clear_expired(self) -> int:
        """Remove expired entries. Returns count deleted."""
        return await self._db_manager.clear_expired()

    async def health_check(self) -> dict:
        """Return cache health metrics."""
        try:
            import aiosqlite

            async with aiosqlite.connect(self._db_manager._db_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(
                    """
                    SELECT 
                        COUNT(*) as total,
                        SUM(CASE WHEN datetime(fetched_at, '+' || ttl_hours || ' hours') > datetime('now') 
                            THEN 1 ELSE 0 END) as valid,
                        SUM(CASE WHEN datetime(fetched_at, '+' || ttl_hours || ' hours') <= datetime('now') 
                            THEN 1 ELSE 0 END) as expired,
                        COALESCE(SUM(content_length), 0) as total_bytes
                    FROM fetch_cache
                    """
                ) as cursor:
                    row = await cursor.fetchone()
                    if row:
                        return {
                            "total": row["total"] or 0,
                            "valid": row["valid"] or 0,
                            "expired": row["expired"] or 0,
                            "total_bytes": row["total_bytes"] or 0,
                            "total_mb": round(
                                (row["total_bytes"] or 0) / (1024 * 1024), 2
                            ),
                        }
                return {"total": 0, "valid": 0, "expired": 0, "total_bytes": 0}
        except Exception as e:
            logger.error("Cache health check failed: %s", e)
            return {"error": str(e)}


_cache: FetchCache | None = None


def get_cache() -> FetchCache:
    """Return singleton cache instance."""
    global _cache
    if _cache is None:
        _cache = FetchCache()
    return _cache
