"""Structural audit manifest validation and non-fatal warnings."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from psynet.audit.constants import (
    ARTIFACT_CREATORS,
    ARTIFACT_ID_RE,
    ARTIFACT_KINDS,
    ARTIFACT_REQUIRED_FIELDS,
    ARTIFACT_STATUSES,
    AUDIT_TOP_LEVEL_REQUIRED,
    BLOCKER_REQUIRED_FIELDS,
    BLOCKER_SEVERITIES,
    CHECK_REQUIRED_FIELDS,
    CHECK_STATUSES,
    CORE_KNOWN_EXTENSION_IDS,
    DEFAULT_AUDIT_PROFILE,
    DOCUMENTED_EXTERNAL_EXTENSION_IDS,
    MAX_AUDIT_SECTION_BYTES,
    PLAN_SECTION_ID,
    SECTION_KINDS,
    SECTION_REQUIRED_FIELDS,
    artifact_label,
    format_allowed,
)
from psynet.audit.content import (
    artifact_allows_directory,
    artifact_path_is_ready,
    section_text,
    validate_present_artifact_file,
)
from psynet.audit.manifest import (
    audit_profile,
    is_placeholder_implementation_summary,
    read_audit_manifest,
)
from psynet.audit.paths import (
    experiment_source_root,
    relative_audit_path,
    validate_audit_site_dir,
)
from psynet.audit.timeline import (
    ALLOWED_TIMELINE_ACTORS,
    unparsed_timeline_entry_lines,
)
from psynet.audit.video import is_git_lfs_pointer, probe_video_metadata


def validate_audit_blockers(
    audit_dir: Path,
    manifest: dict[str, Any],
) -> tuple[set[str], list[str]]:
    """Validate blocker records and return the artifact IDs they cover."""

    blockers = manifest.get("blockers")
    if not isinstance(blockers, list):
        return set(), [f"{audit_dir / 'audit.json'}: blockers must be a list"]

    artifact_ids: set[str] = set()
    artifacts = manifest.get("artifacts")
    if isinstance(artifacts, list):
        artifact_ids = {
            artifact.get("id")
            for artifact in artifacts
            if isinstance(artifact, dict)
            and isinstance(artifact.get("id"), str)
            and ARTIFACT_ID_RE.fullmatch(artifact.get("id"))
        }

    blocker_ids: set[str] = set()
    problems: list[str] = []
    for index, blocker in enumerate(blockers):
        label = f"{audit_dir / 'audit.json'}: blockers[{index}]"
        if not isinstance(blocker, dict):
            problems.append(f"{label}: blocker must be a JSON object")
            continue
        for field in sorted(BLOCKER_REQUIRED_FIELDS):
            if field not in blocker:
                problems.append(f"{label}: missing {field}")
        artifact_id = blocker.get("artifact_id")
        if not isinstance(artifact_id, str) or not ARTIFACT_ID_RE.fullmatch(
            artifact_id
        ):
            problems.append(f"{label}: artifact_id must be a valid artifact ID")
        elif artifact_id not in artifact_ids:
            problems.append(
                f"{label}: artifact_id {artifact_id!r} is not declared in artifacts",
            )
        else:
            blocker_ids.add(artifact_id)
        if blocker.get("severity") not in BLOCKER_SEVERITIES:
            problems.append(f"{label}: severity must be warning or error")
        for field in ("reason", "next_step"):
            if not isinstance(blocker.get(field), str) or not blocker[field].strip():
                problems.append(f"{label}: {field} must be a non-empty string")
    return blocker_ids, problems


def validate_audit_checks(audit_dir: Path, manifest: dict[str, Any]) -> list[str]:
    """Validate check records in an experiment audit manifest."""

    checks = manifest.get("checks")
    if not isinstance(checks, list):
        return [f"{audit_dir / 'audit.json'}: checks must be a list"]

    problems: list[str] = []
    for index, check in enumerate(checks):
        label = f"{audit_dir / 'audit.json'}: checks[{index}]"
        if not isinstance(check, dict):
            problems.append(f"{label}: check must be a JSON object")
            continue
        for field in sorted(CHECK_REQUIRED_FIELDS):
            if field not in check:
                problems.append(f"{label}: missing {field}")
        check_id = check.get("id")
        if not isinstance(check_id, str) or not ARTIFACT_ID_RE.fullmatch(check_id):
            problems.append(f"{label}: id must be a valid check ID")
        if not isinstance(check.get("title"), str) or not check["title"].strip():
            problems.append(f"{label}: title must be a non-empty string")
        if check.get("status") not in CHECK_STATUSES:
            problems.append(
                f"{label}: status must be pass, fail, warning, or not_run",
            )
    return problems


def validate_audit_sections(audit_dir: Path, manifest: dict[str, Any]) -> list[str]:
    """Validate section records in an experiment audit manifest."""

    sections = manifest.get("sections")
    if not isinstance(sections, list):
        return [f"{audit_dir / 'audit.json'}: sections must be a list"]

    problems: list[str] = []
    section_ids: set[str] = set()
    for index, section in enumerate(sections):
        label = f"{audit_dir / 'audit.json'}: sections[{index}]"
        if not isinstance(section, dict):
            problems.append(f"{label}: section must be a JSON object")
            continue
        for field in sorted(SECTION_REQUIRED_FIELDS):
            if field not in section:
                problems.append(f"{label}: missing {field}")

        section_id = section.get("id")
        if not isinstance(section_id, str) or not ARTIFACT_ID_RE.fullmatch(section_id):
            problems.append(f"{label}: id must be a valid section ID")
        elif section_id in section_ids:
            problems.append(f"{label}: duplicate section ID {section_id!r}")
        else:
            section_ids.add(section_id)

        if not isinstance(section.get("title"), str) or not section["title"].strip():
            problems.append(f"{label}: title must be a non-empty string")
        kind = section.get("kind")
        if kind not in SECTION_KINDS:
            problems.append(f"{label}: kind is not recognized")
        if "display" in section and not isinstance(section.get("display"), bool):
            problems.append(f"{label}: display must be a boolean")
        if kind in {"markdown", "timeline", "json"} and not isinstance(
            section.get("content"),
            str,
        ):
            section_path, path_problems = relative_audit_path(
                audit_dir,
                section.get("path"),
                f"{label}: path",
            )
            problems.extend(path_problems)
            if section_path is not None and section.get("display") is not False:
                if not section_path.is_file():
                    problems.append(f"{label}: section file is missing: {section_path}")
                elif section_path.stat().st_size > MAX_AUDIT_SECTION_BYTES:
                    problems.append(
                        f"{label}: section file exceeds "
                        f"{MAX_AUDIT_SECTION_BYTES} bytes: {section_path}",
                    )
        elif "path" in section:
            _, path_problems = relative_audit_path(
                audit_dir,
                section.get("path"),
                f"{label}: path",
            )
            problems.extend(path_problems)
    return problems


def validate_audit_artifacts(
    audit_dir: Path,
    manifest: dict[str, Any],
    blocker_ids: set[str],
) -> list[str]:
    """Validate artifact records and their files."""

    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list):
        return [f"{audit_dir / 'audit.json'}: artifacts must be a list"]

    problems: list[str] = []
    artifact_ids: set[str] = set()
    for index, artifact in enumerate(artifacts):
        artifact_id_hint = artifact.get("id") if isinstance(artifact, dict) else None
        label = artifact_label(audit_dir, index, artifact_id_hint)
        if not isinstance(artifact, dict):
            problems.append(f"{label}: artifact must be a JSON object")
            continue
        for field in sorted(ARTIFACT_REQUIRED_FIELDS):
            if field not in artifact:
                problems.append(f"{label}: missing {field}")

        artifact_id = artifact.get("id")
        if not isinstance(artifact_id, str) or not ARTIFACT_ID_RE.fullmatch(
            artifact_id
        ):
            problems.append(f"{label}: id must be a valid artifact ID")
            artifact_id = None
        elif artifact_id in artifact_ids:
            problems.append(f"{label}: duplicate artifact ID {artifact_id!r}")
        else:
            artifact_ids.add(artifact_id)
            label = artifact_label(audit_dir, index, artifact_id)

        if artifact.get("kind") not in ARTIFACT_KINDS:
            problems.append(
                f"{label}: kind is not recognized "
                f"(allowed: {format_allowed(ARTIFACT_KINDS)})"
            )
        status = artifact.get("status")
        if status not in ARTIFACT_STATUSES:
            problems.append(
                f"{label}: status is not recognized "
                f"(allowed: {format_allowed(ARTIFACT_STATUSES)})"
            )
        if artifact.get("created_by") not in ARTIFACT_CREATORS:
            problems.append(
                f"{label}: created_by is not recognized "
                f"(allowed: {format_allowed(ARTIFACT_CREATORS)})"
            )
        if not isinstance(artifact.get("required"), bool):
            problems.append(f"{label}: required must be a boolean")
        for field in ("title", "description"):
            if not isinstance(artifact.get(field), str) or not artifact[field].strip():
                problems.append(f"{label}: {field} must be a non-empty string")

        artifact_path, path_problems = relative_audit_path(
            audit_dir,
            artifact.get("path"),
            label,
        )
        problems.extend(path_problems)
        if artifact_path is None:
            continue

        if status == "present":
            allow_directory = artifact_allows_directory(artifact_id)
            if artifact_path.is_dir() and not allow_directory:
                problems.append(
                    f"{label}: artifact must be a file, not a directory: "
                    f"{artifact_path}",
                )
                continue
            if not artifact_path_is_ready(
                artifact_path, allow_directory=allow_directory
            ):
                problems.append(
                    f"{label}: artifact marked present but path is missing or empty: "
                    f"{artifact_path}",
                )
                continue
            problems.extend(
                (
                    validate_present_artifact_file(
                        artifact_path,
                        artifact_kind=(
                            str(artifact.get("kind"))
                            if isinstance(artifact.get("kind"), str)
                            else None
                        ),
                        require_video_probe=False,
                    )
                    if artifact_path.is_file()
                    else []
                ),
            )

        if artifact.get("required") is True and status != "present":
            if artifact_id is None or artifact_id not in blocker_ids:
                problems.append(
                    f"{label}: required artifact must be present or have a "
                    "matching blocker",
                )
    return problems


def validate_audit_profile_and_extensions(
    audit_dir: Path,
    manifest: dict[str, Any],
) -> list[str]:
    """Validate profile and extensions fields (errors only)."""

    problems: list[str] = []
    manifest_path = audit_dir / "audit.json"
    if "profile" in manifest:
        profile = manifest.get("profile")
        if not isinstance(profile, str) or not profile.strip():
            problems.append(f"{manifest_path}: profile must be a non-empty string")
    if "extensions" in manifest:
        extensions = manifest.get("extensions")
        if not isinstance(extensions, list):
            problems.append(f"{manifest_path}: extensions must be a list")
        else:
            for index, extension_id in enumerate(extensions):
                if not isinstance(extension_id, str) or not extension_id.strip():
                    problems.append(
                        f"{manifest_path}: extensions[{index}] must be a non-empty string",
                    )
    if "extensions_meta" in manifest:
        extensions_meta = manifest.get("extensions_meta")
        if not isinstance(extensions_meta, dict):
            problems.append(f"{manifest_path}: extensions_meta must be a JSON object")
    return problems


def collect_media_validation_warnings(
    audit_dir: Path,
    manifest: dict[str, Any],
) -> list[str]:
    """Return warnings when present video artifacts could not be probed."""

    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list):
        return []

    warnings: list[str] = []
    for artifact in artifacts:
        if not isinstance(artifact, dict) or artifact.get("status") != "present":
            continue
        artifact_path, path_problems = relative_audit_path(
            audit_dir,
            artifact.get("path"),
            f"artifact {artifact.get('id')!r}",
        )
        if path_problems or artifact_path is None or not artifact_path.is_file():
            continue
        artifact_kind = (
            str(artifact.get("kind")) if isinstance(artifact.get("kind"), str) else None
        )
        is_video = artifact_path.suffix.lower() == ".mp4" or artifact_kind == "video"
        if not is_video or is_git_lfs_pointer(artifact_path):
            continue
        probe = probe_video_metadata(artifact_path)
        if probe.error == "unavailable":
            warnings.append(
                f"{artifact_path}: ffprobe is not available; "
                "video limits were not checked",
            )
            break
    return warnings


def collect_unparsed_timeline_warnings(
    audit_dir: Path, manifest: dict[str, Any]
) -> list[str]:
    """Warn when TIMELINE.md lines look like entries but were ignored."""
    warnings: list[str] = []
    sections = manifest.get("sections")
    if not isinstance(sections, list):
        return warnings
    allowed = ", ".join(ALLOWED_TIMELINE_ACTORS)
    for section in sections:
        if not isinstance(section, dict):
            continue
        kind = section.get("kind")
        section_id = section.get("id")
        if kind != "timeline" and section_id != "timeline":
            continue
        text = section_text(audit_dir, section)
        if text is None:
            continue
        path_label = section.get("path") or "TIMELINE.md"
        for line_number, line in unparsed_timeline_entry_lines(text):
            warnings.append(
                f"{audit_dir / path_label}: line {line_number} looks like a "
                "timeline entry but was ignored; use "
                f"'- T+HH:MM:SS [{allowed}] description' "
                f"(got {line!r})",
            )
    return warnings


def collect_audit_warnings(
    audit_dir: Path,
    manifest: dict[str, Any] | None = None,
) -> list[str]:
    """Return non-fatal validation warnings for an experiment audit."""

    if manifest is None:
        try:
            manifest = read_audit_manifest(audit_dir)
        except (OSError, ValueError, json.JSONDecodeError):
            return []

    warnings: list[str] = []
    manifest_path = audit_dir / "audit.json"
    experiment = manifest.get("experiment")
    if isinstance(experiment, dict) and "source_base" in experiment:
        warnings.append(
            f"{manifest_path}: experiment.source_base is ignored; experiment "
            "source is the parent of the audit directory"
        )
    if isinstance(experiment, dict) and "source_path" in experiment:
        warnings.append(
            f"{manifest_path}: experiment.source_path is ignored; experiment "
            "source is the parent of the audit directory. Put a subdirectory "
            "in experiment.entry_point if needed"
        )
    if audit_profile(manifest) == DEFAULT_AUDIT_PROFILE:
        sections = manifest.get("sections")
        if isinstance(sections, list):
            has_plan = any(
                isinstance(section, dict) and section.get("id") == PLAN_SECTION_ID
                for section in sections
            )
            if not has_plan:
                warnings.append(
                    f"{manifest_path}: no plan section; recommended for "
                    "agent-led implementation audits (optional for retrospective audits)",
                )
    warnings.extend(collect_media_validation_warnings(audit_dir, manifest))
    implementation = manifest.get("implementation")
    if isinstance(implementation, dict):
        summary = implementation.get("summary")
        if isinstance(summary, str) and is_placeholder_implementation_summary(summary):
            warnings.append(
                f"{manifest_path}: implementation.summary is still a TODO "
                "placeholder; rewrite it before review (it is omitted from the "
                "rendered page until then)",
            )
    warnings.extend(collect_unparsed_timeline_warnings(audit_dir, manifest))
    extensions = manifest.get("extensions", [])
    if not isinstance(extensions, list):
        return warnings
    for extension_id in extensions:
        if not isinstance(extension_id, str) or not extension_id.strip():
            continue
        if (
            extension_id not in CORE_KNOWN_EXTENSION_IDS
            and extension_id not in DOCUMENTED_EXTERNAL_EXTENSION_IDS
        ):
            warnings.append(
                f"{manifest_path}: unknown extension id {extension_id!r} "
                "(ignored by core validate/render)",
            )
    return warnings


def validate_audit_manifest(audit_dir: Path, manifest: dict[str, Any]) -> list[str]:
    """Validate experiment audit manifest structure and local artifact files."""

    problems: list[str] = []
    manifest_path = audit_dir / "audit.json"
    for field in sorted(AUDIT_TOP_LEVEL_REQUIRED):
        if field not in manifest:
            problems.append(f"{manifest_path}: missing {field}")

    if manifest.get("schema_version") != "1.0":
        problems.append(f"{manifest_path}: schema_version must be '1.0'")
    for field in ("created_at", "updated_at"):
        if not isinstance(manifest.get(field), str) or not manifest[field].strip():
            problems.append(f"{manifest_path}: {field} must be a non-empty string")
    for field in ("experiment", "implementation", "environment"):
        if not isinstance(manifest.get(field), dict):
            problems.append(f"{manifest_path}: {field} must be a JSON object")

    if isinstance(manifest.get("experiment"), dict):
        experiment = manifest["experiment"]
        if "title" in experiment and (
            not isinstance(experiment.get("title"), str)
            or not experiment["title"].strip()
        ):
            problems.append(
                f"{manifest_path}: experiment.title must be a non-empty string"
            )
        if "entry_point" in experiment:
            entry_point = experiment["entry_point"]
            if not isinstance(entry_point, str) or not entry_point.strip():
                problems.append(
                    f"{manifest_path}: experiment.entry_point must be a "
                    "non-empty string"
                )
            else:
                source_root = experiment_source_root(audit_dir)
                entry_relative = Path(entry_point)
                if entry_relative.is_absolute() or not (
                    source_root / entry_relative
                ).resolve().is_relative_to(source_root):
                    problems.append(
                        f"{manifest_path}: experiment.entry_point must stay "
                        "inside the experiment directory"
                    )
    if isinstance(manifest.get("implementation"), dict):
        implementation = manifest["implementation"]
        if (
            not isinstance(implementation.get("summary"), str)
            or not implementation["summary"].strip()
        ):
            problems.append(
                f"{manifest_path}: implementation.summary must be a non-empty string",
            )
    problems.extend(validate_audit_profile_and_extensions(audit_dir, manifest))
    blocker_ids, blocker_problems = validate_audit_blockers(audit_dir, manifest)
    problems.extend(blocker_problems)
    problems.extend(validate_audit_sections(audit_dir, manifest))
    problems.extend(validate_audit_checks(audit_dir, manifest))
    problems.extend(validate_audit_artifacts(audit_dir, manifest, blocker_ids))

    render = manifest.get("render")
    if isinstance(render, dict) and "site_path" in render:
        resolved_site, site_problems = relative_audit_path(
            audit_dir,
            render.get("site_path"),
            f"{audit_dir / 'audit.json'}: render.site_path",
        )
        problems.extend(site_problems)
        if resolved_site is not None:
            problems.extend(
                validate_audit_site_dir(
                    audit_dir,
                    resolved_site,
                    f"{audit_dir / 'audit.json'}: render.site_path",
                )
            )
    return problems


def validate_audit(audit_dir: Path) -> list[str]:
    """Validate a standalone experiment audit directory."""

    manifest_path = audit_dir / "audit.json"
    if not manifest_path.exists():
        return [f"{manifest_path}: missing experiment audit manifest"]
    try:
        manifest = read_audit_manifest(audit_dir)
    except json.JSONDecodeError as exc:
        return [f"{manifest_path}: invalid JSON: {exc}"]
    except ValueError as exc:
        return [str(exc)]
    return validate_audit_manifest(audit_dir, manifest)


__all__ = [
    "collect_audit_warnings",
    "collect_media_validation_warnings",
    "collect_unparsed_timeline_warnings",
    "validate_audit",
    "validate_audit_artifacts",
    "validate_audit_blockers",
    "validate_audit_checks",
    "validate_audit_manifest",
    "validate_audit_profile_and_extensions",
    "validate_audit_sections",
]
