"""Recording exports retain missing outcomes without fetching absent files."""

import csv

from test_media_upload import pytestmark as pytestmark
from test_media_upload import reservation as reservation

from psynet import data
from psynet.export.client import plan_asset_transfer


def test_unavailable_recording_is_exported_as_metadata(
    reservation, tmp_path, monkeypatch
):
    asset, _ = reservation
    asset.upload_status = "expired"
    asset.upload_failed_reason = "upload_timeout"

    def unexpected_export(*args, **kwargs):
        raise AssertionError("An unavailable recording has no bytes to export")

    monkeypatch.setattr(data, "export_asset", unexpected_export)
    output = tmp_path / "export"
    data.export_assets(str(output / "assets"), local=True)
    with (output / "assets" / "manifest.csv").open() as handle:
        row = next(row for row in csv.DictReader(handle) if row["id"] == str(asset.id))
    assert row["recording_status"] == "expired"
    assert row["recording_role"] == "answer"
    assert row["recording_failure_reason"] == "upload_timeout"
    assert row["page_uuid"] == "original-page"
    assert row["recording_source"] == "camera"
    assert row["url"] == ""
    assert "upload_token_hash" not in row
    plan = plan_asset_transfer(str(output))
    assert plan.eligible
    assert plan.digests == []


def test_pending_video_visualization_has_no_broken_player(reservation):
    from psynet.modular_page import VideoRecordControl

    asset, _ = reservation
    control = VideoRecordControl(duration=1)
    answer = {"camera_id": asset.id, "camera_url": asset.url}
    html = control.visualize_response(answer, None, None)
    assert "Recording pending" in html
    assert "<video" not in html
    asset.deposited = True
    asset.upload_status = "deposited"
    html = control.visualize_response(answer, None, None)
    assert "<video" in html
    assert "visualize-camera-video-response" in html
