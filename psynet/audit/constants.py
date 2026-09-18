"""Audit schema constants and validation error types."""

from __future__ import annotations

import re
from pathlib import Path

from psynet.audit.model import MAX_AUDIT_TEXT_BYTES

AUDIT_TOP_LEVEL_REQUIRED = {
    "schema_version",
    "created_at",
    "updated_at",
    "experiment",
    "implementation",
    "environment",
    "sections",
    "artifacts",
    "checks",
    "blockers",
}
DEFAULT_AUDIT_PROFILE = "psynet.core"
# Core does not register workshop plugins. Declared extension ids are opaque to
# PsyNet validate/render. Documented external ids are ignored silently; other
# unknown ids warn but do not fail.
CORE_KNOWN_EXTENSION_IDS: frozenset[str] = frozenset()
DOCUMENTED_EXTERNAL_EXTENSION_IDS: frozenset[str] = frozenset(
    {
        "psynetskills.challenge",
    }
)
SECTION_REQUIRED_FIELDS = {"id", "title", "kind"}
SECTION_KINDS = {
    "markdown",
    # ``evidence`` renders every evidence subsection in one panel. Newer packets
    # elevate those subsections to their own top-level sections instead.
    "evidence",
    "screenshots",
    "participant_video",
    "monitor",
    "performance",
    "data",
    "analysis",
    "source",
    "files",
    "timeline",
    "json",
    "checks",
    "blockers",
}
PLAN_SECTION_ID = "plan"
PLAN_SECTION_PATH = "PLAN.md"
ARTIFACT_REQUIRED_FIELDS = {
    "id",
    "kind",
    "path",
    "title",
    "description",
    "required",
    "status",
    "created_by",
}
BLOCKER_REQUIRED_FIELDS = {"artifact_id", "severity", "reason", "next_step"}
CHECK_REQUIRED_FIELDS = {"id", "title", "status"}
ARTIFACT_ID_RE = re.compile(r"^[a-z0-9]+(?:_[a-z0-9]+)*$")
ARTIFACT_KINDS = {
    "video",
    "screenshot",
    "notebook",
    "data_export",
    "performance",
    "monitor_snapshot",
    "log",
    "report",
    "source",
    "other",
}
ARTIFACT_STATUSES = {"present", "missing", "blocked", "not_applicable"}
ARTIFACT_CREATORS = {"agent", "cli", "manual", "unknown"}
BLOCKER_SEVERITIES = {"warning", "error"}
CHECK_STATUSES = {"pass", "fail", "warning", "not_run"}
# Notebooks often contain embedded image output. Keep the rendered text preview
# bounded separately, but allow a practical packet size for executed notebooks.
MAX_AUDIT_NOTEBOOK_BYTES = 10_000_000
MAX_AUDIT_SECTION_BYTES = MAX_AUDIT_TEXT_BYTES
PLACEHOLDER_IMPLEMENTATION_SUMMARY = "TODO: Summarize the experiment implementation."
CLI_NAME = "psynet audit"
AUDIT_CSS_OUTPUT = "css/audit.css"


class AuditValidationError(ValueError):
    """Raised when render is blocked by validation problems."""

    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("\n".join(problems))


def format_allowed(values: set[str] | frozenset[str]) -> str:
    """Format allowed enum values for validation errors."""

    return ", ".join(sorted(values))


def artifact_label(audit_dir: Path, index: int, artifact_id: object) -> str:
    """Return a human-oriented label for an artifact validation error."""

    base = f"{audit_dir / 'audit.json'}: artifacts[{index}]"
    if isinstance(artifact_id, str) and artifact_id:
        return f"{base} (id={artifact_id})"
    return base


__all__ = [
    "ARTIFACT_CREATORS",
    "ARTIFACT_ID_RE",
    "ARTIFACT_KINDS",
    "ARTIFACT_REQUIRED_FIELDS",
    "ARTIFACT_STATUSES",
    "AUDIT_CSS_OUTPUT",
    "AUDIT_TOP_LEVEL_REQUIRED",
    "AuditValidationError",
    "BLOCKER_REQUIRED_FIELDS",
    "BLOCKER_SEVERITIES",
    "CHECK_REQUIRED_FIELDS",
    "CHECK_STATUSES",
    "CLI_NAME",
    "CORE_KNOWN_EXTENSION_IDS",
    "DEFAULT_AUDIT_PROFILE",
    "DOCUMENTED_EXTERNAL_EXTENSION_IDS",
    "MAX_AUDIT_NOTEBOOK_BYTES",
    "MAX_AUDIT_SECTION_BYTES",
    "PLAN_SECTION_ID",
    "PLACEHOLDER_IMPLEMENTATION_SUMMARY",
    "PLAN_SECTION_PATH",
    "SECTION_KINDS",
    "SECTION_REQUIRED_FIELDS",
    "artifact_label",
    "format_allowed",
]
