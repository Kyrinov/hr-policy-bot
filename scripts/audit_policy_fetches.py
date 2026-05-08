from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.fetch.extractors import ContentExtractor


REGISTRY_PATH = Path("src/data/policy_registry.json")
OUTPUT_DIR = Path("data/fetch_audit")
MIN_USEFUL_CHARS = 500


def normalize_url(url: str) -> str:
    if "laws-lois.justice.gc.ca/eng/acts/" in url and url.endswith("/"):
        return url.rstrip("/") + "/FullText.html"
    return url


async def fetch_one(
    client: httpx.AsyncClient,
    extractor: ContentExtractor,
    instrument: dict[str, Any],
) -> dict[str, Any]:
    url = normalize_url(instrument["url"])
    result = {
        "id": instrument["id"],
        "title": instrument["title"],
        "type": instrument["type"],
        "agent_ids": instrument["agent_ids"],
        "url": instrument["url"],
        "normalized_url": url,
        "status": "failed",
        "http_status": None,
        "raw_chars": 0,
        "extracted_chars": 0,
        "error": None,
    }
    try:
        response = await client.get(url)
        result["http_status"] = response.status_code
        response.raise_for_status()
        result["raw_chars"] = len(response.text)
        content = extractor.extract(url, response.text)
        result["extracted_chars"] = len(content)
        result["status"] = "ok" if len(content) >= MIN_USEFUL_CHARS else "thin"
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


async def run_audit(limit: int | None) -> list[dict[str, Any]]:
    registry = json.loads(REGISTRY_PATH.read_text())
    if limit is not None:
        registry = registry[:limit]

    extractor = ContentExtractor()
    semaphore = asyncio.Semaphore(3)
    limits = httpx.Limits(max_connections=3, max_keepalive_connections=3)
    timeout = httpx.Timeout(timeout=35.0, connect=10.0)
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-CA,en;q=0.9",
    }
    async with httpx.AsyncClient(
        follow_redirects=True,
        headers=headers,
        timeout=timeout,
        limits=limits,
    ) as client:
        async def guarded_fetch(instrument: dict[str, Any]) -> dict[str, Any]:
            async with semaphore:
                return await fetch_one(client, extractor, instrument)

        tasks = [guarded_fetch(instrument) for instrument in registry]
        return await asyncio.gather(*tasks)


def write_reports(results: list[dict[str, Any]]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    json_path = OUTPUT_DIR / f"policy_fetch_audit_{timestamp}.json"
    md_path = OUTPUT_DIR / f"policy_fetch_audit_{timestamp}.md"

    json_path.write_text(json.dumps(results, indent=2), encoding="utf-8")

    failed = [item for item in results if item["status"] == "failed"]
    thin = [item for item in results if item["status"] == "thin"]
    ok = [item for item in results if item["status"] == "ok"]

    lines = [
        "# Policy Fetch Audit",
        "",
        f"Generated: {timestamp}",
        "",
        f"- OK: {len(ok)}",
        f"- Thin extraction: {len(thin)}",
        f"- Failed: {len(failed)}",
        f"- Total: {len(results)}",
        "",
        "## Failed",
        "",
    ]
    for item in failed:
        lines.extend(
            [
                f"### {item['title']}",
                f"- ID: `{item['id']}`",
                f"- Agents: {', '.join(item['agent_ids'])}",
                f"- URL: {item['normalized_url']}",
                f"- HTTP status: {item['http_status']}",
                f"- Error: {item['error']}",
                "",
            ]
        )

    lines.extend(["## Thin Extraction", ""])
    for item in thin:
        lines.extend(
            [
                f"### {item['title']}",
                f"- ID: `{item['id']}`",
                f"- Agents: {', '.join(item['agent_ids'])}",
                f"- URL: {item['normalized_url']}",
                f"- HTTP status: {item['http_status']}",
                f"- Raw chars: {item['raw_chars']}",
                f"- Extracted chars: {item['extracted_chars']}",
                "",
            ]
        )

    md_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {json_path}")
    print(f"Wrote {md_path}")
    print(f"OK={len(ok)} THIN={len(thin)} FAILED={len(failed)} TOTAL={len(results)}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    results = asyncio.run(run_audit(args.limit))
    write_reports(results)


if __name__ == "__main__":
    main()
