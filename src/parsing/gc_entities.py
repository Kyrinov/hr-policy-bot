from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

_REGISTRY_PATH = Path(__file__).parent.parent / "data" / "policy_registry.json"


@dataclass(frozen=True)
class EntityDefinition:
    text: str
    entity_type: str


@dataclass(frozen=True)
class EntityMatch:
    text: str
    canonical_text: str
    entity_type: str
    char_start: int
    char_end: int


STATIC_ENTITIES: tuple[EntityDefinition, ...] = (
    EntityDefinition("indeterminate", "TENURE_TYPE"),
    EntityDefinition("term", "TENURE_TYPE"),
    EntityDefinition("casual", "TENURE_TYPE"),
    EntityDefinition("acting", "TENURE_TYPE"),
    EntityDefinition("NCR", "GEOGRAPHIC_ZONE"),
    EntityDefinition("NCA", "GEOGRAPHIC_ZONE"),
    EntityDefinition("bilingual region", "GEOGRAPHIC_ZONE"),
    EntityDefinition("bilingual imperative", "LANGUAGE_DESIGNATION"),
    EntityDefinition("bilingual non-imperative", "LANGUAGE_DESIGNATION"),
    EntityDefinition("BBB", "LANGUAGE_DESIGNATION"),
    EntityDefinition("CBC", "LANGUAGE_DESIGNATION"),
    EntityDefinition("CCC", "LANGUAGE_DESIGNATION"),
    EntityDefinition("deployment", "STAFFING_MECHANISM"),
    EntityDefinition("secondment", "STAFFING_MECHANISM"),
    EntityDefinition("priority entitlement", "STAFFING_MECHANISM"),
    EntityDefinition("advertised process", "STAFFING_MECHANISM"),
    EntityDefinition("non-advertised process", "STAFFING_MECHANISM"),
    EntityDefinition("sick leave", "LEAVE_TYPE"),
    EntityDefinition("annual leave", "LEAVE_TYPE"),
    EntityDefinition("family-related leave", "LEAVE_TYPE"),
    EntityDefinition("LWOP", "LEAVE_TYPE"),
    EntityDefinition("employee", "GC_ACTOR"),
    EntityDefinition("deputy head", "GC_ACTOR"),
    EntityDefinition("delegated manager", "GC_ACTOR"),
    EntityDefinition("Treasury Board", "GC_ACTOR"),
    EntityDefinition("PSC", "GC_ACTOR"),
    EntityDefinition("TBS", "GC_ACTOR"),
    EntityDefinition("ADM", "GC_ACTOR"),
    EntityDefinition("DM", "GC_ACTOR"),
    EntityDefinition("PCO", "GC_ACTOR"),
    EntityDefinition("Privy Council", "GC_ACTOR"),
    EntityDefinition("DAOD", "INSTRUMENT_SHORTFORM"),
    EntityDefinition("NJC directive", "INSTRUMENT_SHORTFORM"),
    EntityDefinition("TBS directive", "INSTRUMENT_SHORTFORM"),
    EntityDefinition("collective agreement", "INSTRUMENT_SHORTFORM"),
    EntityDefinition("PSEA", "INSTRUMENT_SHORTFORM"),
    EntityDefinition("PSLRA", "INSTRUMENT_SHORTFORM"),
    EntityDefinition("FPSLRA", "INSTRUMENT_SHORTFORM"),
    EntityDefinition("CHRA", "INSTRUMENT_SHORTFORM"),
    EntityDefinition("CLC", "INSTRUMENT_SHORTFORM"),
    EntityDefinition("GECA", "INSTRUMENT_SHORTFORM"),
    EntityDefinition("staffing action", "HR_PROCESS"),
    EntityDefinition("lay-off", "HR_PROCESS"),
    EntityDefinition("workforce adjustment", "HR_PROCESS"),
    EntityDefinition("WFA", "HR_PROCESS"),
    EntityDefinition("WFAD", "HR_PROCESS"),
    EntityDefinition("demotion", "HR_PROCESS"),
    EntityDefinition("grievance", "HR_PROCESS"),
    EntityDefinition("adjudication", "HR_PROCESS"),
    EntityDefinition("discrimination", "CONCEPT"),
    EntityDefinition("racial characteristics", "CONCEPT"),
    EntityDefinition("duty to accommodate", "CONCEPT"),
    EntityDefinition("employment equity", "CONCEPT"),
)

CLASSIFICATION_PATTERN = re.compile(r"\b[A-Z]{2,4}-\d{2}\b")
LANGUAGE_PROFILE_PATTERN = re.compile(r"\b[ABCEX]-[ABCEX]-[ABCEX]\b")
SECTION_REF_PATTERN = re.compile(
    r"\b(?:s\.\s*\d+(?:\.\d+)*|[Ss]ection\s+\d+(?:\.\d+)*|[Aa]rticle\s+\d+)\b"
)


def _load_registry_titles() -> list[EntityDefinition]:
    with open(_REGISTRY_PATH) as f:
        registry = json.load(f)
    titles: list[EntityDefinition] = []
    for instrument in registry:
        title = instrument.get("title")
        if title:
            titles.append(EntityDefinition(title, "INSTRUMENT_TITLE"))
    return titles


def get_entity_definitions() -> list[EntityDefinition]:
    definitions = list(STATIC_ENTITIES)
    definitions.extend(_load_registry_titles())
    return definitions


class GCEntityMatcher:
    def __init__(self, definitions: list[EntityDefinition] | None = None) -> None:
        self._definitions = definitions or get_entity_definitions()
        self._by_lower = {
            definition.text.lower(): definition for definition in self._definitions
        }
        self._phrase_patterns = [
            (
                definition,
                re.compile(
                    rf"(?<!\w){self._phrase_regex(definition.text)}(?!\w)",
                    re.IGNORECASE,
                ),
            )
            for definition in sorted(
                self._definitions,
                key=lambda item: (len(item.text.split()), len(item.text)),
                reverse=True,
            )
        ]

    def _phrase_regex(self, text: str) -> str:
        return re.escape(text).replace(r"\ ", r"\s+")

    def find_matches(self, text: str) -> list[EntityMatch]:
        matches: list[EntityMatch] = []
        occupied: list[tuple[int, int]] = []

        for regex, entity_type in (
            (CLASSIFICATION_PATTERN, "CLASSIFICATION"),
            (LANGUAGE_PROFILE_PATTERN, "LANGUAGE_DESIGNATION"),
            (SECTION_REF_PATTERN, "SECTION_REF"),
        ):
            for match in regex.finditer(text):
                self._append_if_free(matches, occupied, match.group(0), match.group(0), entity_type, match.start(), match.end())

        for definition, pattern in self._phrase_patterns:
            for match in pattern.finditer(text):
                self._append_if_free(
                    matches,
                    occupied,
                    match.group(0),
                    definition.text,
                    definition.entity_type,
                    match.start(),
                    match.end(),
                )

        return sorted(matches, key=lambda item: (item.char_start, item.char_end))

    def get_entity_type(self, text: str) -> str | None:
        definition = self._by_lower.get(text.lower())
        if definition is not None:
            return definition.entity_type
        if CLASSIFICATION_PATTERN.fullmatch(text):
            return "CLASSIFICATION"
        if LANGUAGE_PROFILE_PATTERN.fullmatch(text):
            return "LANGUAGE_DESIGNATION"
        if SECTION_REF_PATTERN.fullmatch(text):
            return "SECTION_REF"
        return None

    def _append_if_free(
        self,
        matches: list[EntityMatch],
        occupied: list[tuple[int, int]],
        text: str,
        canonical_text: str,
        entity_type: str,
        char_start: int,
        char_end: int,
    ) -> None:
        if any(char_start < end and char_end > start for start, end in occupied):
            return
        occupied.append((char_start, char_end))
        matches.append(
            EntityMatch(
                text=text,
                canonical_text=canonical_text,
                entity_type=entity_type,
                char_start=char_start,
                char_end=char_end,
            )
        )
