import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

from psynet.audit.video import (
    VideoProbeResult,
    is_git_lfs_pointer,
    validate_evidence_video,
)

VALID_METADATA = {
    "format": {"duration": "10", "format_name": "mp4"},
    "streams": [{"codec_type": "video", "width": 640, "height": 480}],
}


def test_video_module_import_does_not_require_html_dependencies() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            ("import sys; sys.modules['nh3'] = None; import psynet.audit.video"),
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_validate_evidence_video_rejects_git_lfs_pointer(tmp_path: Path) -> None:
    video = tmp_path / "participant.mp4"
    video.write_bytes(
        b"version https://git-lfs.github.com/spec/v1\noid sha256:abc\nsize 1\n",
    )

    problems = validate_evidence_video(video)

    assert any("Git LFS pointer" in problem for problem in problems)


def test_validate_evidence_video_fails_for_unreadable_file(tmp_path: Path) -> None:
    video = tmp_path / "participant.mp4"
    video.write_bytes(b"not a video")

    with patch(
        "psynet.audit.video.probe_video_metadata",
        return_value=VideoProbeResult(None, "invalid"),
    ):
        problems = validate_evidence_video(video)

    assert any("unable to read video metadata" in problem for problem in problems)


def test_validate_evidence_video_fails_when_ffprobe_missing(tmp_path: Path) -> None:
    video = tmp_path / "participant.mp4"
    video.write_bytes(b"video bytes")

    with patch(
        "psynet.audit.video.probe_video_metadata",
        return_value=VideoProbeResult(None, "unavailable"),
    ):
        problems = validate_evidence_video(video)

    assert any("ffprobe is required" in problem for problem in problems)


def test_validate_evidence_video_warns_only_when_probe_optional(
    tmp_path: Path,
) -> None:
    video = tmp_path / "participant.mp4"
    video.write_bytes(b"video bytes")

    with patch(
        "psynet.audit.video.probe_video_metadata",
        return_value=VideoProbeResult(None, "unavailable"),
    ):
        assert validate_evidence_video(video, require_probe=False) == []


def test_validate_evidence_video_rejects_non_mp4_container(tmp_path: Path) -> None:
    video = tmp_path / "participant.mp4"
    video.write_bytes(b"video")

    metadata = {
        "format": {"duration": "10", "format_name": "h264"},
        "streams": [{"codec_type": "video", "width": 640, "height": 480}],
    }
    with patch(
        "psynet.audit.video.probe_video_metadata",
        return_value=VideoProbeResult(metadata, None),
    ):
        problems = validate_evidence_video(video)

    assert any("MP4-compatible container" in problem for problem in problems)


def test_validate_evidence_video_enforces_duration_limit(tmp_path: Path) -> None:
    video = tmp_path / "participant.mp4"
    video.write_bytes(b"video")

    metadata = {
        "format": {"duration": "200", "format_name": "mp4"},
        "streams": [{"codec_type": "video", "width": 640, "height": 480}],
    }
    with patch(
        "psynet.audit.video.probe_video_metadata",
        return_value=VideoProbeResult(metadata, None),
    ):
        problems = validate_evidence_video(video)

    assert any("at most 180 seconds" in problem for problem in problems)


def test_is_git_lfs_pointer_detects_pointer(tmp_path: Path) -> None:
    path = tmp_path / "participant.mp4"
    path.write_bytes(b"version https://git-lfs.github.com/spec/v1\n")
    assert is_git_lfs_pointer(path) is True
