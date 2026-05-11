from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.fetch.extractors import ContentExtractor

REGISTRY_PATH = ROOT / "src" / "data" / "policy_registry.json"
INGEST_DIR = ROOT / "data" / "manual_policy_ingest"
CACHE_DIR = ROOT / "data" / "manual_policy_cache"
MANIFEST_PATH = CACHE_DIR / "manifest.json"
SUPPORTED_SUFFIXES = {".html", ".htm", ".md", ".pdf", ".txt"}

FOOTER_MARKERS = (
    "\nPage details",
    "\nDate modified:",
    "\nAbout this site",
    "\nGovernment of Canada\n",
)

DROP_LINES = {
    "Skip to main content",
    'Skip to "About government"',
    "Switch to basic HTML version",
    "Language selection",
    "Français",
    "Government of Canada / Gouvernement du Canada",
    "Search",
    "Search Canada.ca",
    "Menu",
    "You are here:",
}


def slug(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", value.lower()).strip("-")
    return cleaned or "policy"


def load_registry() -> dict[str, dict[str, Any]]:
    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    return {item["id"]: item for item in registry}


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
    manifest["entries"] = sorted(manifest.get("entries", []), key=lambda item: item["id"])
    manifest["entry_count"] = len(manifest["entries"])
    manifest["failures"] = sorted(manifest.get("failures", []), key=lambda item: item["id"])
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def read_source(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".html", ".htm"}:
        html = path.read_text(encoding="utf-8", errors="replace")
        return ContentExtractor().extract(path.as_uri(), html, max_length=500_000)
    if suffix == ".pdf":
        return read_pdf(path)
    return path.read_text(encoding="utf-8", errors="replace")


def read_pdf(path: Path) -> str:
    if shutil.which("pdftotext") is None:
        raise RuntimeError("pdftotext is required to ingest PDF files")
    result = subprocess.run(
        ["pdftotext", "-layout", str(path), "-"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def clean_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")

    footer_positions = [text.find(marker) for marker in FOOTER_MARKERS if text.find(marker) != -1]
    footer_match = re.search(
        r"\n\s*(Page details|Date modified:|About this site|Government of Canada)\b",
        text,
    )
    if footer_match is not None:
        footer_positions.append(footer_match.start())
    copyright_pos = text.find("\n© ")
    if copyright_pos != -1:
        footer_positions.append(copyright_pos)
    if footer_positions:
        text = text[: min(footer_positions)]

    lines: list[str] = []
    previous_blank = False
    for line in text.split("\n"):
        stripped = re.sub(r"[ \t]+", " ", line).strip()
        if stripped in DROP_LINES:
            continue
        if not stripped:
            if not previous_blank:
                lines.append("")
            previous_blank = True
            continue
        lines.append(stripped)
        previous_blank = False

    cleaned = "\n".join(lines).strip()
    return re.sub(r"\n{3,}", "\n\n", cleaned) + "\n"


def source_files(paths: list[Path]) -> list[Path]:
    files: list[Path] = []
    for path in paths:
        if path.is_dir():
            files.extend(
                child
                for child in sorted(path.iterdir())
                if child.is_file() and child.suffix.lower() in SUPPORTED_SUFFIXES
            )
        elif path.is_file():
            files.append(path)
    return files


def infer_instrument_id(path: Path, explicit_id: str | None, registry: dict[str, dict[str, Any]]) -> str:
    if explicit_id is not None:
        return explicit_id
    if path.stem in registry:
        return path.stem
    raise ValueError(
        f"Cannot infer registry id for {path}. Rename it to <registry-id>{path.suffix} "
        "or pass --id for a single-file ingest."
    )


def upsert_manifest_entry(
    manifest: dict[str, Any],
    instrument: dict[str, Any],
    cache_path: Path,
    chars: int,
) -> None:
    entries = [entry for entry in manifest.get("entries", []) if entry["id"] != instrument["id"]]
    entries.append(
        {
            "id": instrument["id"],
            "title": instrument["title"],
            "type": instrument["type"],
            "agent_ids": instrument["agent_ids"],
            "url": instrument["url"],
            "normalized_url": instrument["url"],
            "path": str(cache_path.relative_to(ROOT)),
            "chars": chars,
            "capture_method": "local_public_document",
        }
    )
    manifest["entries"] = entries
    manifest["failures"] = [
        failure
        for failure in manifest.get("failures", [])
        if failure.get("id") != instrument["id"]
    ]


def ingest(paths: list[Path], explicit_id: str | None, dry_run: bool) -> int:
    registry = load_registry()
    manifest = load_manifest()
    files = source_files(paths or [INGEST_DIR])
    if not files:
        print(f"No supported files found under {INGEST_DIR}")
        return 0
    if explicit_id is not None and len(files) != 1:
        raise ValueError("--id can only be used with one input file")

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    ingested = 0
    for path in files:
        instrument_id = infer_instrument_id(path, explicit_id, registry)
        instrument = registry.get(instrument_id)
        if instrument is None:
            raise ValueError(f"Unknown registry id: {instrument_id}")

        cleaned = clean_text(read_source(path))
        cache_path = CACHE_DIR / f"{slug(instrument_id)}.txt"
        print(f"{instrument_id}: {len(cleaned)} chars from {path}")
        if not dry_run:
            cache_path.write_text(cleaned, encoding="utf-8")
            upsert_manifest_entry(manifest, instrument, cache_path, len(cleaned))
        ingested += 1

    if not dry_run:
        write_manifest(manifest)
        print(f"Updated {MANIFEST_PATH}")
    return ingested


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ingest locally supplied public documents into the manual policy cache."
    )
    parser.add_argument("paths", nargs="*", type=Path, help="Files or directories to ingest")
    parser.add_argument("--id", help="Registry id for a single input file")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    try:
        count = ingest(args.paths, args.id, args.dry_run)
    except Exception as exc:
        print(f"ingest failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    print(f"Ingested {count} document(s)")


if __name__ == "__main__":
    main()
