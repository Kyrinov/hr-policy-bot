from __future__ import annotations

DEONTIC_VERBS: dict[str, str] = {
    "shall": "obligation",
    "must": "obligation",
    "will": "obligation",
    "may": "discretion",
    "can": "discretion",
    "should": "recommendation",
    "is to": "obligation",
    "are to": "obligation",
    "must not": "prohibition",
    "shall not": "prohibition",
    "may not": "prohibition",
}
