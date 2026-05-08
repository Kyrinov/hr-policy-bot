from __future__ import annotations

import argparse
import asyncio
import json
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.fetch.extractors import ContentExtractor

AUDIT_PATH = ROOT / "data" / "fetch_audit" / "policy_fetch_audit_20260508T174759Z.json"
CACHE_DIR = ROOT / "data" / "manual_policy_cache"
MANIFEST_PATH = CACHE_DIR / "manifest.json"
MIN_CHARS = 300


def slug(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", value.lower()).strip("-")
    return cleaned or "policy"


def chromium_executable() -> str | None:
    for candidate in (
        "chromium-browser",
        "chromium",
        "google-chrome-stable",
        "google-chrome",
    ):
        path = shutil.which(candidate)
        if path:
            return path
    return None


def load_manifest() -> dict[str, Any]:
    if MANIFEST_PATH.exists():
        return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    return {
        "generated_at": datetime.utcnow().isoformat(),
        "entry_count": 0,
        "entries": [],
        "failures": [],
    }


def write_manifest(manifest: dict[str, Any]) -> None:
    manifest["generated_at"] = datetime.utcnow().isoformat()
    manifest["entries"] = sorted(manifest["entries"], key=lambda item: item["id"])
    manifest["entry_count"] = len(manifest["entries"])
    manifest["failures"] = sorted(manifest.get("failures", []), key=lambda item: item["id"])
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def target_rows(mode: str, force: bool) -> list[dict[str, Any]]:
    rows = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
    if mode == "failed":
        rows = [row for row in rows if row["status"] == "failed"]
    elif mode == "thin":
        rows = [row for row in rows if row["status"] == "thin"]
    else:
        rows = [row for row in rows if row["status"] in {"failed", "thin"}]

    if force:
        return rows

    manifest = load_manifest()
    cached_ids = {entry["id"] for entry in manifest.get("entries", [])}
    return [row for row in rows if row["id"] not in cached_ids]


async def capture_row(
    page: Any,
    extractor: ContentExtractor,
    row: dict[str, Any],
) -> tuple[dict[str, Any], str | None, str | None]:
    try:
        response = await page.goto(
            row["normalized_url"],
            wait_until="domcontentloaded",
            timeout=45_000,
        )
        if response is not None and response.status >= 400:
            return row, None, f"HTTP {response.status}"

        try:
            await page.wait_for_timeout(2000)
            visible_text = await page.locator("main, article, body").first.inner_text(
                timeout=5000
            )
        except Exception:
            visible_text = ""

        html = await page.content()
        extracted = extractor.extract(row["normalized_url"], html, max_length=120000)
        content = visible_text if len(visible_text) > len(extracted) else extracted
        content = "\n".join(line.rstrip() for line in content.splitlines()).strip()
        if len(content) < MIN_CHARS:
            return row, None, f"thin browser content ({len(content)} chars)"
        return row, content, None
    except PlaywrightTimeoutError as exc:
        return row, None, f"Timeout: {exc}"
    except Exception as exc:
        return row, None, f"{type(exc).__name__}: {exc}"


def upsert_entry(manifest: dict[str, Any], row: dict[str, Any], content: str) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{slug(row['id'])}.txt"
    path = CACHE_DIR / filename
    path.write_text(content, encoding="utf-8")

    entries = [entry for entry in manifest.get("entries", []) if entry["id"] != row["id"]]
    entries.append(
        {
            "id": row["id"],
            "title": row["title"],
            "type": row["type"],
            "agent_ids": row["agent_ids"],
            "url": row["url"],
            "normalized_url": row["normalized_url"],
            "path": str(path.relative_to(ROOT)),
            "chars": len(content),
            "capture_method": "playwright",
        }
    )
    manifest["entries"] = entries
    manifest["failures"] = [
        failure for failure in manifest.get("failures", []) if failure["id"] != row["id"]
    ]


def record_failure(manifest: dict[str, Any], row: dict[str, Any], error: str) -> None:
    failures = [failure for failure in manifest.get("failures", []) if failure["id"] != row["id"]]
    failures.append({"id": row["id"], "title": row["title"], "error": error})
    manifest["failures"] = failures


async def run(mode: str, limit: int | None, force: bool) -> None:
    rows = target_rows(mode, force)
    if limit is not None:
        rows = rows[:limit]

    manifest = load_manifest()
    extractor = ContentExtractor()
    executable = chromium_executable()
    print(f"Capturing {len(rows)} policies with Chromium: {executable or 'playwright default'}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            executable_path=executable,
            env={
                "HOME": "/tmp",
                "XDG_RUNTIME_DIR": "/tmp",
                "XDG_CACHE_HOME": "/tmp",
                "XDG_CONFIG_HOME": "/tmp",
            },
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
            ],
        )
        context = await browser.new_context(
            locale="en-CA",
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
        )
        page = await context.new_page()

        for index, row in enumerate(rows, start=1):
            print(f"[{index}/{len(rows)}] {row['id']}")
            _row, content, error = await capture_row(page, extractor, row)
            if content is None:
                print(f"  failed: {error}")
                record_failure(manifest, row, error or "unknown")
            else:
                print(f"  captured: {len(content)} chars")
                upsert_entry(manifest, row, content)
                write_manifest(manifest)

        await context.close()
        await browser.close()

    write_manifest(manifest)
    print(f"Manifest now has {manifest['entry_count']} entries")
    print(f"Failures recorded: {len(manifest.get('failures', []))}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["failed", "thin", "both"], default="both")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    asyncio.run(run(args.mode, args.limit, args.force))


if __name__ == "__main__":
    main()
