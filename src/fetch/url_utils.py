import re


def normalize_url(url: str) -> str:
    """Rewrite laws-lois act index pages to their FullText.html version."""
    if re.search(r"laws-lois\.justice\.gc\.ca/eng/acts/[^/]+/$", url):
        return url.rstrip("/") + "/FullText.html"
    return url
