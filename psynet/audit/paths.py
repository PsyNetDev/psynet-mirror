"""Resolve and validate filesystem paths used by experiment audits."""

from __future__ import annotations

from pathlib import Path

AUDIT_DIR_NAME = "audit"
PROTECTED_PACKET_DIRECTORIES = ("artifacts", "logs", "simulate")


def _has_audit_manifest(candidate: Path) -> bool:
    """Return whether ``candidate/audit.json`` exists."""

    return (candidate / "audit.json").is_file()


def _is_named_audit_directory(path: Path) -> bool:
    """Return whether ``path`` is a directory named ``audit``."""

    return path.resolve().name == AUDIT_DIR_NAME


def _flat_packet_error(location: Path) -> ValueError:
    """Return an error for a leftover flat ``audit.json`` layout."""

    destination = location / AUDIT_DIR_NAME / "audit.json"
    return ValueError(
        "Audits must live in ./audit/. Found audit.json at "
        f"{location}; move it to {destination}"
    )


def _run_from_experiment_error() -> ValueError:
    """Return an error when the current directory is the audit packet."""

    return ValueError("Run this command from the experiment directory, not from audit/")


def resolve_experiment_root() -> Path:
    """Return the current directory as the experiment root.

    Audits are always ``./audit/``. Running from a directory named ``audit``
    is an error, as is a leftover ``audit.json`` in the experiment root.
    """

    cwd = Path(".")
    if _is_named_audit_directory(cwd):
        raise _run_from_experiment_error()
    if _has_audit_manifest(cwd):
        raise _flat_packet_error(cwd)
    return cwd


def resolve_audit_dir(*, require_manifest: bool = False) -> Path:
    """Return ``./audit`` for the current experiment directory."""

    resolved = resolve_experiment_root() / AUDIT_DIR_NAME
    if require_manifest and not _has_audit_manifest(resolved):
        raise ValueError(
            f"No audit packet found; expected {AUDIT_DIR_NAME}/audit.json",
        )
    return resolved


def experiment_source_root(audit_dir: Path) -> Path:
    """Return the experiment directory that contains ``audit/``."""

    return audit_dir.resolve().parent


def relative_audit_path(
    audit_dir: Path,
    path_text: object,
    label: str,
) -> tuple[Path | None, list[str]]:
    """Resolve a manifest path and ensure it stays inside the bundle."""

    if not isinstance(path_text, str) or not path_text:
        return None, [f"{label}: path must be a non-empty string"]

    relative_path = Path(path_text)
    if relative_path.is_absolute():
        return None, [
            f"{label}: path must be relative to the experiment audit directory"
        ]

    audit_root = audit_dir.resolve()
    resolved_path = (audit_dir / relative_path).resolve()
    if not resolved_path.is_relative_to(audit_root):
        return None, [f"{label}: path must stay inside the experiment audit directory"]
    return resolved_path, []


def validate_audit_site_dir(
    audit_dir: Path,
    site_dir: Path,
    label: str,
) -> list[str]:
    """Reject output directories that overlap audit packet inputs."""

    audit_root = audit_dir.resolve()
    resolved_site = site_dir.resolve()
    if not resolved_site.is_relative_to(audit_root):
        return []

    if resolved_site == audit_root:
        return [
            f"{label}: must use a dedicated output directory that does not "
            "overlap audit packet inputs"
        ]

    protected = [audit_root / name for name in PROTECTED_PACKET_DIRECTORIES]
    if any(
        resolved_site == path
        or resolved_site.is_relative_to(path)
        or path.is_relative_to(resolved_site)
        for path in protected
    ):
        return [
            f"{label}: must use a dedicated output directory that does not "
            "overlap audit packet inputs"
        ]
    return []
