"""Parse audit timeline markdown entries."""

from __future__ import annotations

import re
from dataclasses import dataclass

ALLOWED_TIMELINE_ACTORS = (
    "agent-start",
    "agent",
    "agent-stop",
    "manual",
    "system",
)
_ACTOR_PATTERN = "|".join(ALLOWED_TIMELINE_ACTORS)
TIMELINE_ENTRY_RE = re.compile(
    r"^- (?P<timestamp>T\+\d{2}:\d{2}:\d{2}) "
    rf"\[(?P<actor>{_ACTOR_PATTERN})\] "
    r"(?P<details>.+)$"
)
ISO_TIMELINE_ENTRY_RE = re.compile(
    r"^-?\s*(?P<timestamp>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)\s+"
    r"(?P<details>.+)$"
)
LOOKS_LIKE_RELATIVE_ENTRY_RE = re.compile(r"^- T\+\d{2}:\d{2}:\d{2}\b")
LOOKS_LIKE_ISO_ENTRY_RE = re.compile(r"^-?\s*\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\b")
TIMELINE_TAG_RE = re.compile(r"^\[(?P<tag>[a-z][a-z0-9-]*)\]\s+")


@dataclass(frozen=True)
class TimelineEntry:
    """A structured audit timeline entry."""

    timestamp: str
    actor: str
    description: str
    tags: list[str]


def parse_timeline_line(line: str) -> TimelineEntry | None:
    """Parse one markdown line into a timeline entry, or return None."""
    match = TIMELINE_ENTRY_RE.fullmatch(line)
    actor = "agent"
    if match is None:
        match = ISO_TIMELINE_ENTRY_RE.fullmatch(line)
    else:
        actor = match.group("actor")
    if match is None:
        return None
    details = match.group("details")
    tags: list[str] = []
    while tag_match := TIMELINE_TAG_RE.match(details):
        tags.append(tag_match.group("tag"))
        details = details[tag_match.end() :]
    return TimelineEntry(
        timestamp=match.group("timestamp"),
        actor=actor,
        description=details,
        tags=tags,
    )


def parse_timeline_entries(markdown: str) -> list[TimelineEntry]:
    """Parse structured entries from ``TIMELINE.md``."""
    entries: list[TimelineEntry] = []
    for line in markdown.splitlines():
        entry = parse_timeline_line(line)
        if entry is not None:
            entries.append(entry)
    return entries


def looks_like_timeline_entry_line(line: str) -> bool:
    """Return True when a line looks like a timeline entry, even if invalid."""
    return bool(
        LOOKS_LIKE_RELATIVE_ENTRY_RE.match(line) or LOOKS_LIKE_ISO_ENTRY_RE.match(line)
    )


def unparsed_timeline_entry_lines(markdown: str) -> list[tuple[int, str]]:
    """Return 1-based line numbers that look like entries but did not parse."""
    skipped: list[tuple[int, str]] = []
    for index, line in enumerate(markdown.splitlines(), start=1):
        if looks_like_timeline_entry_line(line) and parse_timeline_line(line) is None:
            skipped.append((index, line))
    return skipped
