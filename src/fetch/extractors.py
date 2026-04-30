from __future__ import annotations

import logging
from typing import Any

import yaml
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


class ContentExtractor:
    def __init__(self, selectors_path: str = "src/fetch/selectors.yaml") -> None:
        self._selectors = self._load_selectors(selectors_path)

    def extract(self, url: str, html: str, max_length: int = 48000) -> str:
        """Extract main content from HTML for a given URL."""
        try:
            selectors = self._get_selectors(url)
            soup = BeautifulSoup(html, "lxml")

            for selector in selectors.get("content_selector", ["main", "article"]):
                content_elem = soup.select_one(selector)
                if content_elem is not None:
                    break
            else:
                content_elem = soup.find("body")

            if content_elem is None:
                return self._clean_text(soup.get_text(), max_length)

            self._remove_elements(content_elem, selectors.get("remove_selector", []))

            extracted = self._format_content(content_elem)

            return self._truncate(extracted, max_length)
        except Exception as e:
            logger.error("Extraction failed for %s: %s", url, e)
            return self._clean_text(html[:48000], max_length)

    def _load_selectors(self, path: str) -> dict[str, Any]:
        try:
            with open(path) as f:
                return yaml.safe_load(f)
        except Exception as e:
            logger.warning(
                "Could not load selectors from %s: %s. Using defaults.", path, e
            )
            return {
                "default": {
                    "content_selector": "main, article, .content",
                    "remove_selector": ["nav", "header", "footer", "aside"],
                    "heading_selector": ["h1", "h2", "h3"],
                    "paragraph_selector": "p",
                }
            }

    def _get_selectors(self, url: str) -> dict[str, Any]:
        domains = self._selectors.get("domain_selectors", {})
        for domain, selectors in domains.items():
            if domain in url:
                return selectors
        default = domains.get("default", domains.get("laws-lois.justice.gc.ca", {}))
        return default

    def _remove_elements(self, elem: Any, selectors: list[str]) -> None:
        for selector in selectors:
            for el in elem.select(selector):
                el.decompose()

    def _format_content(self, elem: Any) -> str:
        lines = []

        for child in elem.children:
            if child.name is None:
                text = str(child).strip()
                if text:
                    lines.append(text)
            elif child.name in ("h1", "h2", "h3", "h4", "h5", "h6"):
                text = child.get_text().strip()
                if text:
                    lines.append(f"\n{text}\n")
            elif child.name in ("p", "li"):
                text = child.get_text().strip()
                if text:
                    lines.append(text)
            elif child.name in ("div", "section"):
                inner = self._format_content(child)
                if inner.strip():
                    lines.append(inner)

        return "\n\n".join(lines)

    def _clean_text(self, text: str, max_length: int) -> str:
        clean = " ".join(text.split())
        return clean[:max_length]

    def _truncate(self, text: str, max_length: int) -> str:
        if len(text) <= max_length:
            return text
        return text[: max_length - 3] + "..."


_extractor: ContentExtractor | None = None


def get_extractor() -> ContentExtractor:
    """Return singleton extractor instance."""
    global _extractor
    if _extractor is None:
        _extractor = ContentExtractor()
    return _extractor
