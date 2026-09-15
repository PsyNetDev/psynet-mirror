"""Experiment readiness audit packet: manifest, evidence HTML, and CLI.

Public helpers are loaded lazily so lightweight utilities such as video and
path validation do not import the HTML rendering dependency stack.
"""

from importlib import import_module
from typing import Any

_EXPORT_MODULES = {
    "ARTIFACT_URL_PREFIX_ENV": "psynet.audit.artifacts",
    "HASHED_ARTIFACTS_DIR": "psynet.audit.artifacts",
    "LEGACY_ARTIFACT_URL_PREFIX_ENV": "psynet.audit.artifacts",
    "MONITOR_STATIC_ARTIFACTS_DIR": "psynet.audit.artifacts",
    "ArtifactPublication": "psynet.audit.artifacts",
    "redact_known_credentials": "psynet.audit.artifacts",
    "sanitize_html_artifact": "psynet.audit.artifacts",
    "sanitize_text_artifact": "psynet.audit.artifacts",
    "write_hashed_artifact": "psynet.audit.artifacts",
    "write_shared_monitor_static_assets": "psynet.audit.artifacts",
    "render_analysis_notebook": "psynet.audit.html",
    "render_evidence_section": "psynet.audit.html",
    "render_file_grid": "psynet.audit.html",
    "render_json_block": "psynet.audit.html",
    "render_markdown_block": "psynet.audit.html",
    "render_markdown_document": "psynet.audit.html",
    "render_monitor_snapshot": "psynet.audit.html",
    "render_participant_video": "psynet.audit.html",
    "render_performance_result": "psynet.audit.html",
    "render_screenshot_gallery": "psynet.audit.html",
    "render_timeline_section": "psynet.audit.html",
    "safe_section_html": "psynet.audit.html",
    "AuditEvidenceView": "psynet.audit.model",
    "AuditFile": "psynet.audit.model",
    "CompletenessItem": "psynet.audit.model",
    "classify_audit_evidence": "psynet.audit.model",
    "completeness_items": "psynet.audit.model",
    "screenshot_caption": "psynet.audit.model",
}

__all__ = [
    "ARTIFACT_URL_PREFIX_ENV",
    "LEGACY_ARTIFACT_URL_PREFIX_ENV",
    "ArtifactPublication",
    "AuditEvidenceView",
    "AuditFile",
    "CompletenessItem",
    "HASHED_ARTIFACTS_DIR",
    "MONITOR_STATIC_ARTIFACTS_DIR",
    "classify_audit_evidence",
    "completeness_items",
    "redact_known_credentials",
    "render_analysis_notebook",
    "render_evidence_section",
    "render_file_grid",
    "render_json_block",
    "render_markdown_block",
    "render_markdown_document",
    "render_monitor_snapshot",
    "render_participant_video",
    "render_performance_result",
    "render_screenshot_gallery",
    "render_timeline_section",
    "safe_section_html",
    "sanitize_html_artifact",
    "sanitize_text_artifact",
    "screenshot_caption",
    "write_hashed_artifact",
    "write_shared_monitor_static_assets",
]


def __getattr__(name: str) -> Any:
    """Load a public audit helper from its defining module."""

    try:
        module_name = _EXPORT_MODULES[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc
    value = getattr(import_module(module_name), name)
    globals()[name] = value
    return value
