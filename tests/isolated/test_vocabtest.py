import os
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

from psynet.prescreen.vocabtest import VocabTest, VocabTrial


def test_vocab_finalize_definition_sets_hashes_after_asset_setup(monkeypatch):
    received_previous = []

    def choose_hashes(stimuli, previous):
        received_previous.extend(previous)
        return ["h"]

    def expire_then_return_assets(stimuli, hashes):
        trial.definition = {}
        return {"h": object()}

    maker = SimpleNamespace(
        choose_hashes=choose_hashes,
        get_assets=expire_then_return_assets,
    )
    trial = SimpleNamespace(
        trial_maker_id="vocab",
        assets={},
        definition={},
        node=SimpleNamespace(seed=[{"hash": "h"}]),
        trial_maker=maker,
    )

    monkeypatch.setattr(
        VocabTrial,
        "query",
        SimpleNamespace(
            filter_by=lambda **kwargs: SimpleNamespace(all=lambda: [trial])
        ),
    )

    definition = VocabTrial.finalize_definition(trial, {}, None, SimpleNamespace(id=1))

    assert received_previous == []
    assert definition["hashes"] == ["h"]
    assert "h" in trial.assets


def test_vocab_test_rejects_sync_groups(tmp_path):
    csv_path = tmp_path / "items.csv"
    csv_path.write_text("stimulus,correct_answer\ncat,correct\nxzz,incorrect\n")

    with pytest.raises(ValueError, match="does not support synchronized groups"):
        VocabTest(
            locale="en",
            label="vocab",
            csv_path=str(csv_path),
            performance_threshold_per_trial=None,
            n_items=2,
            present_as_image=False,
            sync_group_type="group",
        )


def test_vocab_font_is_cached_outside_the_experiment(tmp_path, monkeypatch):
    experiment_dir = tmp_path / "experiment"
    experiment_dir.mkdir()
    monkeypatch.chdir(experiment_dir)
    monkeypatch.setattr("tempfile.tempdir", str(tmp_path / "tmp"))
    downloads = []

    def fake_get(url, timeout):
        downloads.append(url)
        return SimpleNamespace(content=b"font", raise_for_status=lambda: None)

    monkeypatch.setattr("psynet.prescreen.vocabtest.requests.get", fake_get)

    url = "https://example.org/fonts/Font.ttf"
    first = VocabTest.get_font_path(None, url)
    second = VocabTest.get_font_path(None, url)

    font_dir = tmp_path / "tmp" / f"psynet-fonts-{os.getuid()}"
    assert first == second == str(font_dir / "Font.ttf")
    assert Path(first).read_bytes() == b"font"
    assert downloads == [url]
    assert list(experiment_dir.iterdir()) == []


def test_vocab_font_download_failure_raises(tmp_path, monkeypatch):
    monkeypatch.setattr("tempfile.tempdir", str(tmp_path))

    def raise_for_status():
        raise requests.HTTPError("404")

    monkeypatch.setattr(
        "psynet.prescreen.vocabtest.requests.get",
        lambda url, timeout: SimpleNamespace(raise_for_status=raise_for_status),
    )

    with pytest.raises(requests.HTTPError):
        VocabTest.get_font_path(None, "https://example.org/fonts/Font.ttf")
    assert list(tmp_path.iterdir()) == []
