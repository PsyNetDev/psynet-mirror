"""Bounded artifact reads, notebook validation, and section text helpers."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from psynet.audit.artifacts import redact_known_credentials
from psynet.audit.constants import DIRECTORY_ARTIFACT_IDS, MAX_AUDIT_NOTEBOOK_BYTES
from psynet.audit.model import MAX_AUDIT_TEXT_BYTES, TEXT_AUDIT_EXTENSIONS
from psynet.audit.paths import relative_audit_path
from psynet.audit.video import validate_evidence_video


def artifact_allows_directory(artifact_id: str | None) -> bool:
    """Return whether *artifact_id* is stored as a non-empty directory."""

    return artifact_id in DIRECTORY_ARTIFACT_IDS


def artifact_path_is_ready(path: Path, *, allow_directory: bool = False) -> bool:
    """Return whether an artifact path is ready for its allowed shape."""

    if allow_directory:
        return path.is_dir() and any(
            item.is_file() and not item.is_symlink() for item in path.rglob("*")
        )
    return path.is_file()


def validate_present_artifact_file(
    artifact_path: Path,
    *,
    artifact_kind: str | None = None,
    require_video_probe: bool = True,
) -> list[str]:
    """Validate a present artifact file before marking or accepting it."""

    problems: list[str] = []
    suffix = artifact_path.suffix.lower()
    is_video = suffix == ".mp4" or artifact_kind == "video"
    if is_video:
        problems.extend(
            validate_evidence_video(
                artifact_path,
                require_probe=require_video_probe,
            ),
        )
    if suffix == ".ipynb" or artifact_kind == "notebook":
        problems.extend(validate_audit_notebook(artifact_path))
    return problems


def validate_audit_notebook(notebook_file: Path) -> list[str]:
    """Validate that an audit notebook is parseable and small enough to render."""

    problems: list[str] = []
    size_bytes = notebook_file.stat().st_size
    if size_bytes > MAX_AUDIT_NOTEBOOK_BYTES:
        return [
            f"{notebook_file}: audit notebooks must be at most "
            f"{MAX_AUDIT_NOTEBOOK_BYTES} bytes",
        ]
    try:
        notebook = json.loads(notebook_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        problems.append(f"{notebook_file}: invalid notebook JSON: {exc}")
        return problems
    if not isinstance(notebook, dict):
        problems.append(f"{notebook_file}: notebook must be a JSON object")
    return problems


def read_bounded_bytes(source_file: Path, max_bytes: int) -> tuple[bytes | None, bool]:
    """Read at most ``max_bytes`` from a file without loading a larger remainder."""

    try:
        with source_file.open("rb") as handle:
            data = handle.read(max_bytes + 1)
    except OSError:
        return None, False
    truncated = len(data) > max_bytes
    if truncated:
        data = data[:max_bytes]
    return data, truncated


def read_audit_artifact_content(
    source_file: Path,
    max_bytes: int | None = None,
) -> tuple[str | None, bool]:
    """Read text artifact content for audit classification."""

    if source_file.suffix.lower() not in TEXT_AUDIT_EXTENSIONS:
        return None, False
    if max_bytes is None:
        max_bytes = (
            MAX_AUDIT_NOTEBOOK_BYTES
            if source_file.suffix.lower() == ".ipynb"
            else MAX_AUDIT_TEXT_BYTES
        )
    data, truncated = read_bounded_bytes(source_file, max_bytes)
    if data is None:
        return None, False
    text = data.decode("utf-8", errors="ignore")
    if not text:
        return None, truncated
    return (
        redact_known_credentials(
            text,
            for_source_code=source_file.suffix.lower() == ".py",
        ),
        truncated,
    )


def strip_redundant_section_heading(
    markdown: str,
    _section: dict[str, Any],
) -> str:
    """Remove a leading H1 because the enclosing panel already provides one."""

    pattern = re.compile(r"\A\s*#\s+.+?\s*(?:\n+|\Z)")
    return pattern.sub("", markdown, count=1)


def section_text(audit_dir: Path, section: dict[str, Any]) -> str | None:
    """Return inline or file-backed section text."""

    content = section.get("content")
    if isinstance(content, str):
        return content
    section_path, problems = relative_audit_path(
        audit_dir,
        section.get("path"),
        f"{audit_dir / 'audit.json'}: sections[{section.get('id', '')}].path",
    )
    if problems or section_path is None or not section_path.is_file():
        return None
    return section_path.read_text(encoding="utf-8")


__all__ = [
    "artifact_allows_directory",
    "artifact_path_is_ready",
    "read_audit_artifact_content",
    "read_bounded_bytes",
    "section_text",
    "strip_redundant_section_heading",
    "validate_audit_notebook",
    "validate_present_artifact_file",
]
