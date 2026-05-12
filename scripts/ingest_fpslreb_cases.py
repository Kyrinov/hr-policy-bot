from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

INDEX_PATH = ROOT / "data" / "case_law" / "fpslreb_cases.json"
BASE_URL = "https://decisions.fpslreb-crtespf.gc.ca"
USER_AGENT = "HRPolicyBotPublicCaseLawIndexer/1.0 (compact public decision metadata retrieval)"


def load_index() -> dict[str, Any]:
    if INDEX_PATH.exists():
        return json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    return {
        "generated_at": datetime.utcnow().isoformat(),
        "source": "Federal Public Sector Labour Relations and Employment Board decisions",
        "scope": (
            "Compact case-law index for retrieval. Entries are interpretive examples only "
            "and do not replace legislation, collective agreements, policies, directives, or DAODs."
        ),
        "cases": [],
    }


def write_index(index: dict[str, Any]) -> None:
    index["generated_at"] = datetime.utcnow().isoformat()
    index["cases"] = sorted(
        deduplicate_cases(index.get("cases", [])),
        key=lambda item: (item.get("decision_date", ""), item.get("citation", "")),
        reverse=True,
    )
    INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    INDEX_PATH.write_text(json.dumps(index, indent=2), encoding="utf-8")


def deduplicate_cases(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for case in cases:
        key = case.get("case_id") or case.get("url") or case.get("citation")
        if key:
            by_id[str(key)] = case
    return list(by_id.values())


def fetch_html(url: str) -> str:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(request, timeout=30) as response:
            html = response.read().decode("utf-8", errors="replace")
    except HTTPError as exc:
        if exc.code in {403, 429}:
            raise RuntimeError(
                f"FPSLREB blocked automated access with HTTP {exc.code}. "
                "Stop automated fetching and use saved public pages or retry later "
                "from a clean approved session."
            ) from exc
        raise
    except URLError as exc:
        raise RuntimeError(f"Failed to fetch FPSLREB page {url}: {exc}") from exc
    if is_validation_page(html):
        raise RuntimeError(
            "FPSLREB returned a Decisia validation page. Stop automated fetching and "
            "use saved public pages or retry later from a clean session."
        )
    return html


def is_validation_page(html: str) -> bool:
    text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True).lower()
    return "validation" in text and "captcha" in text and "decisia" in text


def parse_nav_page(html: str, page_url: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    cases: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for link in soup.find_all("a", href=True):
        href = link["href"]
        if "/item/" not in href:
            continue
        url = urljoin(page_url, href)
        if url in seen_urls:
            continue
        seen_urls.add(url)
        block = nearest_result_text(link)
        case = parse_case_text(block, url)
        if case["title"]:
            cases.append(case)
    return cases


def nearest_result_text(link: Any) -> str:
    for parent_name in ("li", "article", "tr", "div"):
        parent = link.find_parent(parent_name)
        if parent is not None:
            text = parent.get_text("\n", strip=True)
            if "FPSLREB" in text or "Summary" in text:
                return text
    return link.get_text("\n", strip=True)


def parse_decision_page(html: str, page_url: str) -> dict[str, Any]:
    text = BeautifulSoup(html, "html.parser").get_text("\n", strip=True)
    return parse_case_text(text, page_url)


def parse_case_text(text: str, url: str) -> dict[str, Any]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    joined = "\n".join(lines)
    citation = first_match(r"\b(20\d{2}\s+FPSLREB\s+\d+)\b", joined)
    title = extract_title(lines, citation)
    decision_date = value_after_label(lines, "Decision Rendered") or first_match(
        r"\b(20\d{2}-\d{2}-\d{2})\b", joined
    )
    decision_type = value_after_label(lines, "Decision Type")
    subject_terms = split_terms(value_after_label(lines, "Subject Terms"))
    keywords = split_terms(value_after_label(lines, "Keywords"))
    summary = extract_summary(joined)
    disposition = extract_disposition(joined)
    return {
        "case_id": case_id(citation, url),
        "title": title,
        "citation": citation,
        "decision_date": decision_date,
        "decision_type": decision_type,
        "subject_terms": subject_terms,
        "keywords": keywords,
        "summary": summary,
        "disposition": disposition,
        "url": url.split("?")[0],
        "agent_ids": ["labour"],
    }


def extract_title(lines: list[str], citation: str) -> str:
    for line in lines:
        if " v. " in line or " v " in line:
            return re.sub(r"\s+-\s+Federal Public Sector.*$", "", line).strip()
    for line in lines:
        if citation and citation in line:
            continue
        if len(line) > 8 and not line.startswith("/"):
            return re.sub(r"\s+-\s+Federal Public Sector.*$", "", line).strip()
    return ""


def value_after_label(lines: list[str], label: str) -> str:
    for index, line in enumerate(lines):
        if line.strip(":") == label and index + 1 < len(lines):
            return lines[index + 1]
        if line.startswith(f"{label}:"):
            return line.split(":", 1)[1].strip()
    return ""


def split_terms(value: str) -> list[str]:
    if not value:
        return []
    return [
        item.strip(" -;\t")
        for item in re.split(r"\s+[–-]\s+|;|,", value)
        if item.strip(" -;\t")
    ]


def extract_summary(text: str) -> str:
    match = re.search(
        r"Summary:\s*(.+?)(?:\nDecision Content|\n[A-Z][A-Za-z ]+ denied\.|\n[A-Z][A-Za-z ]+ allowed\.|$)",
        text,
        flags=re.DOTALL,
    )
    if not match:
        return ""
    summary = re.sub(r"\s+", " ", match.group(1)).strip()
    return summary[:1200]


def extract_disposition(text: str) -> str:
    patterns = (
        r"\b(Grievance denied\.)",
        r"\b(Grievance allowed(?: in part)?\.)",
        r"\b(Complaint dismissed\.)",
        r"\b(Complaint allowed(?: in part)?\.)",
        r"\b(Application dismissed\.)",
        r"\b(Application allowed(?: in part)?\.)",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1)
    return ""


def first_match(pattern: str, text: str) -> str:
    match = re.search(pattern, text)
    return match.group(1) if match else ""


def case_id(citation: str, url: str) -> str:
    if citation:
        return "fpslreb-" + re.sub(r"[^a-zA-Z0-9]+", "-", citation.lower()).strip("-")
    match = re.search(r"/item/(\d+)/", url)
    return f"fpslreb-item-{match.group(1)}" if match else "fpslreb-case"


def ingest_files(paths: list[Path]) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for path in paths:
        html = path.read_text(encoding="utf-8", errors="replace")
        page_url = path.as_uri()
        parsed = parse_nav_page(html, page_url)
        if parsed:
            cases.extend(parsed)
        else:
            case = parse_decision_page(html, page_url)
            if case["title"]:
                cases.append(case)
    return cases


def fetch_years(start_year: int, end_year: int, delay_seconds: float) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for year in range(start_year, end_year + 1):
        first_url = f"{BASE_URL}/fpslreb-crtespf/d/en/{year}/nav_date.do?iframe=true"
        first_html = fetch_html(first_url)
        cases.extend(parse_nav_page(first_html, first_url))
        pages = page_count(first_html)
        time.sleep(delay_seconds)
        for page in range(2, pages + 1):
            page_url = f"{BASE_URL}/fpslreb-crtespf/d/en/{year}/nav_date.do?page={page}&iframe=true"
            html = fetch_html(page_url)
            cases.extend(parse_nav_page(html, page_url))
            time.sleep(delay_seconds)
    return cases


def page_count(html: str) -> int:
    soup = BeautifulSoup(html, "html.parser")
    pages = [1]
    for link in soup.find_all("a", href=True):
        match = re.search(r"[?&]page=(\d+)", link["href"])
        if match:
            pages.append(int(match.group(1)))
    return max(pages)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a compact FPSLREB case-law index.")
    parser.add_argument("paths", nargs="*", type=Path, help="Saved Decisia nav or decision HTML files")
    parser.add_argument("--fetch-years", nargs=2, type=int, metavar=("START", "END"))
    parser.add_argument("--delay", type=float, default=5.0, help="Delay between public requests")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.paths and args.fetch_years is None:
        parser.error("provide saved HTML paths or --fetch-years START END")

    new_cases: list[dict[str, Any]] = []
    if args.paths:
        new_cases.extend(ingest_files(args.paths))
    if args.fetch_years is not None:
        start_year, end_year = args.fetch_years
        try:
            new_cases.extend(fetch_years(start_year, end_year, args.delay))
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            raise SystemExit(2) from exc

    index = load_index()
    index["cases"] = index.get("cases", []) + new_cases
    index["cases"] = deduplicate_cases(index["cases"])
    print(f"Parsed {len(new_cases)} cases; index will contain {len(index['cases'])} cases")
    if not args.dry_run:
        write_index(index)
        print(f"Updated {INDEX_PATH}")


if __name__ == "__main__":
    main()
