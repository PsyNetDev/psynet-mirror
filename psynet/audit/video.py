"""Validate participant evidence videos for experiment audits."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MAX_EVIDENCE_VIDEO_DURATION_SECONDS = 180
MAX_EVIDENCE_VIDEO_WIDTH = 1280
MAX_EVIDENCE_VIDEO_HEIGHT = 720
ACCEPTED_VIDEO_CONTAINER_FORMATS = frozenset(
    {"mp4", "mov", "m4v", "isom", "iso5", "iso6", "avc1", "qt"},
)


@dataclass(frozen=True)
class VideoProbeResult:
    """Result of probing a video file with ffprobe."""

    metadata: dict[str, Any] | None
    error: str | None = None


def video_metadata(video_file: Path) -> dict[str, Any] | None:
    """Return ffprobe metadata for a video file."""

    return probe_video_metadata(video_file).metadata


def probe_video_metadata(video_file: Path) -> VideoProbeResult:
    """Return ffprobe metadata and a coarse error classification."""

    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-print_format",
                "json",
                "-show_streams",
                "-show_format",
                str(video_file),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return VideoProbeResult(None, "unavailable")
    except (OSError, subprocess.CalledProcessError):
        return VideoProbeResult(None, "invalid")

    try:
        metadata = json.loads(result.stdout)
    except json.JSONDecodeError:
        return VideoProbeResult(None, "invalid")
    return VideoProbeResult(metadata, None)


def is_git_lfs_pointer(path: Path) -> bool:
    """Return whether a file is an unfetched Git LFS pointer."""

    try:
        data = path.read_bytes()[:128]
    except OSError:
        return False
    return data.startswith(b"version https://git-lfs.github.com/spec/v1")


def _positive_float(value: object) -> float | None:
    """Return a non-negative float when ``value`` is numeric."""

    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _accepted_container(metadata: dict[str, Any]) -> bool:
    """Return whether ffprobe reports an MP4-compatible container."""

    format_names = {
        name.strip().lower()
        for name in str(metadata.get("format", {}).get("format_name") or "").split(",")
        if name.strip()
    }
    return bool(format_names & ACCEPTED_VIDEO_CONTAINER_FORMATS)


def validate_evidence_video(
    video_file: Path,
    *,
    require_probe: bool = True,
) -> list[str]:
    """Validate participant evidence video size constraints."""

    problems: list[str] = []
    if is_git_lfs_pointer(video_file):
        return [
            f"{video_file}: file is a Git LFS pointer; fetch the video content "
            "before marking it present",
        ]

    probe = probe_video_metadata(video_file)
    if probe.error == "unavailable":
        if require_probe:
            problems.append(
                f"{video_file}: ffprobe is required to validate evidence videos",
            )
        return problems
    if probe.error == "invalid" or probe.metadata is None:
        problems.append(
            f"{video_file}: unable to read video metadata; ensure file is a valid MP4",
        )
        return problems

    metadata = probe.metadata
    if not _accepted_container(metadata):
        problems.append(
            f"{video_file}: evidence videos must use an MP4-compatible container",
        )
        return problems

    video_stream = next(
        (
            stream
            for stream in metadata.get("streams", [])
            if stream.get("codec_type") == "video"
        ),
        None,
    )
    if video_stream is None:
        problems.append(
            f"{video_file}: unable to read video metadata; ensure file is a valid MP4",
        )
        return problems

    duration = _positive_float(metadata.get("format", {}).get("duration"))
    if duration is None:
        duration = _positive_float(video_stream.get("duration"))
    if duration is None:
        problems.append(
            f"{video_file}: unable to determine evidence video duration",
        )
        return problems
    if duration > MAX_EVIDENCE_VIDEO_DURATION_SECONDS:
        problems.append(
            f"{video_file}: evidence videos must be at most "
            f"{MAX_EVIDENCE_VIDEO_DURATION_SECONDS} seconds long",
        )

    width = int(video_stream.get("width") or 0)
    height = int(video_stream.get("height") or 0)
    if width > MAX_EVIDENCE_VIDEO_WIDTH or height > MAX_EVIDENCE_VIDEO_HEIGHT:
        problems.append(
            f"{video_file}: evidence videos must be at most "
            f"{MAX_EVIDENCE_VIDEO_WIDTH}x{MAX_EVIDENCE_VIDEO_HEIGHT}",
        )

    return problems
