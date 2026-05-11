from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.fetch.extractors import ContentExtractor

REGISTRY_PATH = ROOT / "src" / "data" / "policy_registry.json"
DEFAULT_AUDIT_PATH = ROOT / "data" / "fetch_audit" / "policy_fetch_audit_20260508T174759Z.json"
OUTPUT_DIR = ROOT / "data" / "manual_policy_cache"
MIN_CHARS = 100


def normalize_url(url: str) -> str:
    if re.search(r"laws-lois\.justice\.gc\.ca/eng/acts/[^/]+/$", url):
        return url.rstrip("/") + "/FullText.html"
    return url


def slug(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", value.lower()).strip("-")
    return cleaned or "policy"


def selected_registry(audit_path: Path | None) -> list[dict[str, Any]]:
    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    by_id = {item["id"]: item for item in registry}
    if audit_path is None:
        return registry

    audit_rows = json.loads(audit_path.read_text(encoding="utf-8"))
    selected_ids = {
        row["id"] for row in audit_rows if row.get("status") in {"ok", "thin"}
    }
    return [by_id[item_id] for item_id in selected_ids if item_id in by_id]


async def fetch_text(
    client: httpx.AsyncClient,
    extractor: ContentExtractor,
    instrument: dict[str, Any],
) -> tuple[dict[str, Any], str | None, str | None]:
    url = normalize_url(instrument["url"])
    try:
        response = await client.get(url)
        response.raise_for_status()
        content = extractor.extract(url, response.text)
        if len(content) < MIN_CHARS:
            return instrument, None, f"thin content ({len(content)} chars)"
        return instrument, content, None
    except Exception as exc:
        return instrument, None, f"{type(exc).__name__}: {exc}"


async def build_cache(audit_path: Path | None) -> dict[str, Any]:
    instruments = selected_registry(audit_path)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    extractor = ContentExtractor()
    semaphore = asyncio.Semaphore(1)
    limits = httpx.Limits(max_connections=1, max_keepalive_connections=1)
    headers = {
        "User-Agent": (
            "HRPolicyBotPublicDocumentCache/1.0 "
            "(allowlisted public Government of Canada policy document cache)"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-CA,en;q=0.9",
    }

    async with httpx.AsyncClient(
        follow_redirects=True,
        headers=headers,
        timeout=httpx.Timeout(timeout=35.0, connect=10.0),
        limits=limits,
    ) as client:
        async def guarded(instrument: dict[str, Any]) -> tuple[dict[str, Any], str | None, str | None]:
            async with semaphore:
                return await fetch_text(client, extractor, instrument)

        results = await asyncio.gather(*[guarded(instrument) for instrument in instruments])

    entries: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    for instrument, content, error in results:
        if content is None:
            failures.append({"id": instrument["id"], "title": instrument["title"], "error": error or "unknown"})
            continue

        filename = f"{slug(instrument['id'])}.txt"
        path = OUTPUT_DIR / filename
        path.write_text(content, encoding="utf-8")
        entries.append(
            {
                "id": instrument["id"],
                "title": instrument["title"],
                "type": instrument["type"],
                "agent_ids": instrument["agent_ids"],
                "url": instrument["url"],
                "normalized_url": normalize_url(instrument["url"]),
                "path": str(path.relative_to(ROOT)),
                "chars": len(content),
            }
        )

    manifest = {
        "generated_at": datetime.utcnow().isoformat(),
        "entry_count": len(entries),
        "entries": sorted(entries, key=lambda item: item["id"]),
        "failures": sorted(failures, key=lambda item: item["id"]),
    }
    (OUTPUT_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit-json", type=Path, default=DEFAULT_AUDIT_PATH)
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()
    manifest = asyncio.run(build_cache(None if args.all else args.audit_json))
    print(f"Cached {manifest['entry_count']} policies")
    print(f"Skipped {len(manifest['failures'])} policies")
    print(f"Wrote {OUTPUT_DIR / 'manifest.json'}")


if __name__ == "__main__":
    main()
