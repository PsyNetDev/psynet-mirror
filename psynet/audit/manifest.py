"""Audit manifest I/O, starter templates, init, and mutation helpers."""

from __future__ import annotations

import json
import platform
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from psynet.audit.constants import (
    ARTIFACT_ID_RE,
    CLI_NAME,
    DEFAULT_AUDIT_PROFILE,
    PLACEHOLDER_IMPLEMENTATION_SUMMARY,
)
from psynet.audit.content import validate_present_artifact_file
from psynet.audit.paths import relative_audit_path


def count_blockers(manifest: dict[str, Any]) -> int:
    """Return the number of blocker records in a manifest."""

    blockers = manifest.get("blockers")
    return len(blockers) if isinstance(blockers, list) else 0


def validate_success_message(
    audit_dir: Path, manifest: dict[str, Any] | None = None
) -> str:
    """Return the validate success line, including blocker count when known."""

    if manifest is None:
        try:
            manifest = read_audit_manifest(audit_dir)
        except (OSError, ValueError, json.JSONDecodeError):
            return f"Audit packet coherent: {audit_dir}"
    n = count_blockers(manifest)
    if n:
        return (
            f"Audit packet coherent: {audit_dir} "
            f"({n} blocker{'s' if n != 1 else ''} recorded; readiness incomplete)"
        )
    return f"Audit packet coherent: {audit_dir} (no blockers)"


def init_success_messages(audit_dir: Path, prog: str = CLI_NAME) -> list[str]:
    """Return user-facing lines printed after a successful init."""

    return [
        f"Initialized experiment audit directory: {audit_dir}",
        "This is a starter packet: validate can pass while required evidence is "
        "still blocked (packet coherent ≠ experiment ready). Fill artifacts, then "
        f"mark them present (see `{prog} mark-present`).",
        "Required artifacts use status blocked + a blocker; optional gaps may use "
        "missing without a blocker.",
        f"Next: {prog} validate",
        f"Next: {prog} render",
    ]


def audit_css_path() -> Path:
    """Return the packaged audit stylesheet path."""
    from importlib import resources

    return Path(resources.files("psynet") / "resources" / "audit" / "audit.css")


STARTER_PROMPT = """# Prompt

Summarize the original request or experiment brief.
"""
STARTER_PLAN = """# Plan

Summarize the implementation plan for this experiment audit.
"""

STARTER_TIMELINE = """# Timeline

Record notable implementation and evidence-collection events, or remove this
section from `audit.json`.

Use one list item per event. The actor tag must be one of `agent-start`,
`agent`, `agent-stop`, `manual`, or `system`:

`- T+00:00:00 [agent-start] Started implementation.`
`- T+00:05:12 [agent] Ran psynet simulate --audit.`
"""
STARTER_REPORT = """# Experiment audit report

Summarize the implementation, validation, analysis, and any unresolved issues.
"""


def read_audit_manifest(audit_dir: Path) -> dict[str, Any]:
    """Read the experiment audit manifest from an experiment audit directory."""

    manifest_path = audit_dir / "audit.json"
    with manifest_path.open(encoding="utf-8") as file:
        manifest = json.load(file)
    if not isinstance(manifest, dict):
        raise ValueError(f"{manifest_path}: manifest must be a JSON object")
    return manifest


def display_title_from_path(audit_dir: Path) -> str:
    """Derive a human-readable experiment title from the experiment directory."""

    source = audit_dir.resolve().parent
    normalized = re.sub(r"[-_]+", " ", source.name).strip()
    return normalized.title() if normalized else "Experiment Audit"


def audit_display_title(audit_dir: Path, manifest: dict[str, Any]) -> str:
    """Return the display title for an experiment audit."""

    experiment = manifest.get("experiment")
    if isinstance(experiment, dict):
        title = experiment.get("title")
        if isinstance(title, str) and title.strip():
            return title
        return display_title_from_path(audit_dir)
    return display_title_from_path(audit_dir)


def is_placeholder_implementation_summary(summary: str) -> bool:
    """Return True when ``summary`` is still the starter TODO placeholder."""
    text = summary.strip()
    return text == PLACEHOLDER_IMPLEMENTATION_SUMMARY or text.upper().startswith(
        "TODO:"
    )


def display_implementation_summary(manifest: dict[str, Any]) -> str:
    """Return the hero subtitle, or empty when it is still a TODO placeholder."""
    implementation = manifest.get("implementation")
    if not isinstance(implementation, dict):
        return ""
    summary = implementation.get("summary")
    if not isinstance(summary, str):
        return ""
    text = summary.strip()
    if not text or is_placeholder_implementation_summary(text):
        return ""
    return text


def utc_timestamp() -> str:
    """Return a UTC ISO timestamp for generated audit metadata."""

    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def starter_artifact(
    artifact_id: str,
    kind: str,
    path: str,
    title: str,
    description: str,
    *,
    required: bool,
    status: str,
    created_by: str = "unknown",
) -> dict[str, object]:
    """Create a starter artifact record."""

    return {
        "id": artifact_id,
        "kind": kind,
        "path": path,
        "title": title,
        "description": description,
        "required": required,
        "status": status,
        "created_by": created_by,
    }


def starter_blocker(artifact_id: str, reason: str, next_step: str) -> dict[str, str]:
    """Create a starter blocker for an incomplete required artifact."""

    return {
        "artifact_id": artifact_id,
        "severity": "error",
        "reason": reason,
        "next_step": next_step,
    }


def starter_section(
    section_id: str,
    title: str,
    kind: str,
    *,
    path: str | None = None,
    display: bool = True,
) -> dict[str, object]:
    """Create a starter audit section."""

    section: dict[str, object] = {
        "id": section_id,
        "title": title,
        "kind": kind,
        "display": display,
    }
    if path is not None:
        section["path"] = path
    return section


def audit_profile(manifest: dict[str, Any]) -> str:
    """Return the effective audit profile, defaulting to the core profile."""

    profile = manifest.get("profile", DEFAULT_AUDIT_PROFILE)
    if isinstance(profile, str) and profile.strip():
        return profile.strip()
    return DEFAULT_AUDIT_PROFILE


def starter_audit_manifest() -> dict[str, object]:
    """Create a starter experiment audit manifest."""

    timestamp = utc_timestamp()
    return {
        "schema_version": "1.0",
        "created_at": timestamp,
        "updated_at": timestamp,
        "profile": DEFAULT_AUDIT_PROFILE,
        "extensions": [],
        "experiment": {},
        "implementation": {
            "summary": PLACEHOLDER_IMPLEMENTATION_SUMMARY,
        },
        "environment": {
            "os": platform.system().lower(),
            "python_version": f"{sys.version_info.major}.{sys.version_info.minor}",
        },
        "sections": [
            starter_section("prompt", "Prompt", "markdown", path="PROMPT.md"),
            starter_section("plan", "Plan", "markdown", path="PLAN.md"),
            starter_section(
                "timeline",
                "Implementation timeline",
                "timeline",
                path="TIMELINE.md",
            ),
            starter_section(
                "report",
                "Implementation notes",
                "markdown",
                path="REPORT.md",
            ),
            starter_section("source", "Experiment code", "source"),
            starter_section("screenshots", "Screenshots", "screenshots"),
            starter_section(
                "participant_video", "Participant video", "participant_video"
            ),
            starter_section("monitor", "Monitor snapshot", "monitor"),
            starter_section("performance", "Performance test", "performance"),
            starter_section("data_exports", "Data exports", "data"),
            starter_section("analysis", "Analysis", "analysis"),
            starter_section("files", "Additional files", "files"),
            starter_section("blockers", "Blockers", "blockers"),
            starter_section("checks", "Checks", "checks"),
        ],
        "artifacts": [
            starter_artifact(
                "participant_video",
                "video",
                "artifacts/participant.mp4",
                "Participant walkthrough",
                "Participant-facing walkthrough video.",
                required=True,
                status="blocked",
            ),
            starter_artifact(
                "screenshots",
                "screenshot",
                "artifacts/screenshots/manifest.json",
                "Screenshot walkthrough",
                "Manifest describing targeted participant-facing screenshots.",
                required=False,
                status="missing",
            ),
            starter_artifact(
                "performance_result",
                "performance",
                "artifacts/performance.json",
                "Performance test result",
                "PsyNet performance-test output.",
                required=True,
                status="blocked",
            ),
            starter_artifact(
                "monitor_snapshot",
                "monitor_snapshot",
                "artifacts/monitor.html",
                "Monitor snapshot",
                "Static PsyNet monitor snapshot.",
                required=True,
                status="blocked",
            ),
            starter_artifact(
                "simulation_export",
                "data_export",
                "artifacts/simulated_data.zip",
                "Simulated data export",
                "Data export produced by simulated participants.",
                required=True,
                status="blocked",
            ),
            starter_artifact(
                "analysis_notebook",
                "notebook",
                "analyses/analysis.ipynb",
                "Analysis notebook",
                "Executed notebook that reads the simulated export and summarizes results.",
                required=True,
                status="blocked",
            ),
        ],
        "checks": [],
        "blockers": [
            starter_blocker(
                "participant_video",
                "Participant walkthrough has not been recorded yet.",
                "Record or explicitly mark participant video as not applicable.",
            ),
            starter_blocker(
                "performance_result",
                "Performance test has not been run yet.",
                "Run psynet performance-test local … --audit.",
            ),
            starter_blocker(
                "monitor_snapshot",
                "Monitor snapshot has not been captured yet.",
                "Capture a static PsyNet monitor snapshot at artifacts/monitor.html.",
            ),
            starter_blocker(
                "simulation_export",
                "Simulation export has not been produced yet.",
                "Run psynet simulate --audit.",
            ),
            starter_blocker(
                "analysis_notebook",
                "Analysis notebook has not been executed yet.",
                "Create and execute analyses/analysis.ipynb.",
            ),
        ],
        "render": {
            "site_path": "site",
            "generator": CLI_NAME,
        },
    }


def init_audit(audit_dir: Path, force: bool = False) -> None:
    """Create a starter experiment audit directory.

    ``audit_dir`` is the packet directory (``<experiment>/audit``). The CLI
    always creates that nested folder; tests may pass it directly.
    """

    manifest_path = audit_dir / "audit.json"
    if manifest_path.exists() and not force:
        raise FileExistsError(
            f"{manifest_path}: already exists; pass --force to replace it"
        )

    for directory in (
        audit_dir,
        audit_dir / "artifacts",
        audit_dir / "artifacts" / "screenshots",
        audit_dir / "analyses",
        audit_dir / "logs",
    ):
        directory.mkdir(parents=True, exist_ok=True)

    manifest_path.write_text(
        json.dumps(
            starter_audit_manifest(),
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (audit_dir / "REPORT.md").write_text(STARTER_REPORT, encoding="utf-8")
    (audit_dir / "PROMPT.md").write_text(STARTER_PROMPT, encoding="utf-8")
    (audit_dir / "PLAN.md").write_text(STARTER_PLAN, encoding="utf-8")
    (audit_dir / "TIMELINE.md").write_text(STARTER_TIMELINE, encoding="utf-8")


def mark_artifact_present(
    audit_dir: Path,
    artifact_id: str,
    path: str | None = None,
) -> dict[str, Any]:
    """Mark an artifact present, optionally updating its path, and drop its blockers."""

    if not ARTIFACT_ID_RE.fullmatch(artifact_id):
        raise ValueError(f"artifact id must be snake_case: {artifact_id!r}")

    manifest = read_audit_manifest(audit_dir)
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list):
        raise ValueError(f"{audit_dir / 'audit.json'}: artifacts must be a list")

    target: dict[str, Any] | None = None
    for artifact in artifacts:
        if isinstance(artifact, dict) and artifact.get("id") == artifact_id:
            target = artifact
            break
    if target is None:
        raise ValueError(f"artifact id not found: {artifact_id!r}")

    if path is not None:
        resolved, path_problems = relative_audit_path(
            audit_dir,
            path,
            f"{audit_dir / 'audit.json'}: artifact {artifact_id}",
        )
        if path_problems:
            raise ValueError("; ".join(path_problems))
        target["path"] = path
    else:
        resolved, path_problems = relative_audit_path(
            audit_dir,
            target.get("path"),
            f"{audit_dir / 'audit.json'}: artifact {artifact_id}",
        )
        if path_problems:
            raise ValueError("; ".join(path_problems))

    assert resolved is not None
    if not resolved.is_file():
        raise FileNotFoundError(
            f"{resolved}: file missing; create it before marking present"
        )

    problems = validate_present_artifact_file(
        resolved,
        artifact_kind=(
            str(target.get("kind")) if isinstance(target.get("kind"), str) else None
        ),
        require_video_probe=True,
    )
    if problems:
        raise ValueError("; ".join(problems))

    target["status"] = "present"
    blockers = manifest.get("blockers")
    if isinstance(blockers, list):
        manifest["blockers"] = [
            blocker
            for blocker in blockers
            if not (
                isinstance(blocker, dict) and blocker.get("artifact_id") == artifact_id
            )
        ]
    manifest["updated_at"] = utc_timestamp()
    (audit_dir / "audit.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


__all__ = [
    "STARTER_PLAN",
    "STARTER_PROMPT",
    "STARTER_REPORT",
    "STARTER_TIMELINE",
    "audit_css_path",
    "audit_display_title",
    "audit_profile",
    "count_blockers",
    "display_implementation_summary",
    "display_title_from_path",
    "init_audit",
    "init_success_messages",
    "is_placeholder_implementation_summary",
    "mark_artifact_present",
    "read_audit_manifest",
    "starter_artifact",
    "starter_audit_manifest",
    "starter_blocker",
    "starter_section",
    "utc_timestamp",
    "validate_success_message",
]
