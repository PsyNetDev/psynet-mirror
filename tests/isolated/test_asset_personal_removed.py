"""Tests for removal of the Asset personal flag."""

import pytest

from psynet.asset import ExperimentAsset, asset
from psynet.modular_page import AudioRecordControl, VideoRecordControl


def test_experiment_asset_rejects_personal_argument(tmp_path):
    path = tmp_path / "a.txt"
    path.write_text("x")
    with pytest.raises(TypeError, match="personal"):
        ExperimentAsset(input_path=str(path), local_key="a", personal=True)
    with pytest.raises(TypeError, match="personal"):
        ExperimentAsset(input_path=str(path), local_key="a", personal=False)


def test_asset_helper_rejects_personal_argument(tmp_path):
    path = tmp_path / "a.txt"
    path.write_text("x")
    with pytest.raises(TypeError, match="personal"):
        asset(str(path), personal=True)


def test_record_controls_reject_personal_argument():
    with pytest.raises(TypeError, match="personal"):
        AudioRecordControl(personal=True)
    with pytest.raises(TypeError, match="personal"):
        VideoRecordControl(personal=False)
