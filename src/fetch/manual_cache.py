from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_MANIFEST_PATH = _PROJECT_ROOT / "data" / "manual_policy_cache" / "manifest.json"


class ManualPolicyCache:
    """File-backed policy cache loaded lazily by URL."""

    def __init__(self, manifest_path: Path = _DEFAULT_MANIFEST_PATH) -> None:
        self._manifest_path = manifest_path
        self._url_index: dict[str, dict[str, Any]] | None = None

    def get(self, url: str) -> str | None:
        entry = self._entries_by_url().get(_normalize_url(url))
        if entry is None:
            return None

        path = _PROJECT_ROOT / entry["path"]
        try:
            return path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("Manual policy cache read failed for %s: %s", path, exc)
            return None

    def _entries_by_url(self) -> dict[str, dict[str, Any]]:
        if self._url_index is not None:
            return self._url_index

        self._url_index = {}
        if not self._manifest_path.exists():
            return self._url_index

        try:
            manifest = json.loads(self._manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Manual policy cache manifest unavailable: %s", exc)
            return self._url_index

        for entry in manifest.get("entries", []):
            for url in {entry.get("url"), entry.get("normalized_url")}:
                if url:
                    self._url_index[_normalize_url(url)] = entry
        return self._url_index


def _normalize_url(url: str) -> str:
    if re.search(r"laws-lois\.justice\.gc\.ca/eng/acts/[^/]+/$", url):
        return url.rstrip("/") + "/FullText.html"
    return url


_manual_policy_cache: ManualPolicyCache | None = None


def get_manual_policy_cache() -> ManualPolicyCache:
    global _manual_policy_cache
    if _manual_policy_cache is None:
        _manual_policy_cache = ManualPolicyCache()
    return _manual_policy_cache
