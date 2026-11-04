import json
import re
from types import SimpleNamespace

import numpy as np
import pytest
import requests
from werkzeug.exceptions import HTTPException

import psynet.prescreen
from psynet.asset import ExternalAsset
from psynet.prescreen import (
    AntiphaseHeadphoneTest,
    BeepHeadphoneTest,
    ColorBlindnessTest,
    HugginsHeadphoneTest,
    LanguageVocabularyTest,
    LanguageVocabularyTrial,
    LexTaleTest,
    NumpySerializer,
    _opaque_media_asset,
)


class TestNumpySerializer:
    @pytest.mark.parametrize(
        "value,expected",
        [
            (np.bool_(True), '{"value": true}'),
            (np.bool_(False), '{"value": false}'),
            (np.int64(42), '{"value": 42}'),
            (np.float64(3.14), '{"value": 3.14}'),
            (np.array([1, 2, 3]), '{"value": [1, 2, 3]}'),
        ],
    )
    def test_serialize_numpy_types(self, value, expected):
        result = json.dumps({"value": value}, cls=NumpySerializer)
        assert result == expected


@pytest.mark.parametrize(
    "trial_maker_class",
    [
        AntiphaseHeadphoneTest,
        BeepHeadphoneTest,
        ColorBlindnessTest,
        HugginsHeadphoneTest,
        LanguageVocabularyTest,
        LexTaleTest,
    ],
)
def test_prescreen_stimulus_urls_do_not_reveal_answers(trial_maker_class):
    assets = [
        asset
        for node in trial_maker_class().start_nodes
        for asset in node.assets.values()
    ]
    assert assets
    for asset in assets:
        assert re.fullmatch(r"/asset/[\w-]+", asset.get_url())


def test_prescreen_assets_fetch_the_matching_remote_files():
    def source_urls(node):
        return {key: a.arguments["source_url"] for key, a in node.assets.items()}

    media_url = "https://s3.amazonaws.com/langauge-test-materials"
    for node in LanguageVocabularyTest().start_nodes:
        word = node.definition["word"]
        assert source_urls(node) == {
            "audio": f"{media_url}/recordings/en-US/{word}.wav",
            **{
                f"image_{image}": f"{media_url}/images/{word}/{image}.png"
                for image in ["correct", "wrong1", "wrong2", "wrong3"]
            },
        }

    for node in ColorBlindnessTest().start_nodes:
        label = node.definition["label"]
        assert source_urls(node) == {
            "image": f"https://s3.amazonaws.com/ishihara-eye-test/jpg/ishihara-{label}.jpg"
        }


def test_opaque_media_asset_returns_502_when_the_download_fails(
    monkeypatch, tmp_path, caplog
):
    def get(url, timeout):
        raise requests.Timeout("timed out")

    monkeypatch.setattr(psynet.prescreen.requests, "get", get)
    asset = _opaque_media_asset("https://example.com/bell.wav")

    with pytest.raises(HTTPException) as error:
        asset.export(tmp_path / "out.wav")

    assert error.value.code == 502
    assert "https://example.com/bell.wav" in caplog.text


def test_opaque_media_asset_fetches_the_source_url(monkeypatch, tmp_path):
    fetched = []

    def get(url, timeout):
        fetched.append(url)
        return SimpleNamespace(content=b"RIFF", raise_for_status=lambda: None)

    monkeypatch.setattr(psynet.prescreen.requests, "get", get)
    asset = _opaque_media_asset("https://example.com/bell.wav")
    asset.export(tmp_path / "out.wav")

    assert asset.extension == ".wav"
    assert fetched == ["https://example.com/bell.wav"]
    assert (tmp_path / "out.wav").read_bytes() == b"RIFF"


def test_opaque_media_asset_keeps_non_http_urls_with_one_warning_per_directory(
    monkeypatch,
):
    monkeypatch.setattr(psynet.prescreen, "_warned_non_http_media_directories", set())
    with pytest.warns(UserWarning, match="participants can see them") as record:
        asset = _opaque_media_asset("/static/opaque-media-test/1.wav")
        _opaque_media_asset("/static/opaque-media-test/2.wav")

    assert len(record) == 1
    assert isinstance(asset, ExternalAsset)
    assert asset.url == "/static/opaque-media-test/1.wav"


def test_on_demand_assets_have_no_id_based_route():
    from dallinger.experiment import EXPERIMENT_ROUTE_REGISTRATIONS

    import psynet.experiment  # noqa: F401

    rules = {route["rule"] for route in EXPERIMENT_ROUTE_REGISTRATIONS}
    assert "/asset/<access_token>" in rules
    assert "/on-demand-asset" not in rules


def test_language_vocabulary_page_hides_and_checks_the_answer():
    trial = SimpleNamespace(
        definition={},
        assets={
            key: ExternalAsset(f"/asset/{i}")
            for i, key in enumerate(LanguageVocabularyTrial.image_keys + ["audio"])
        },
        image_keys=LanguageVocabularyTrial.image_keys,
    )
    trial.definition = LanguageVocabularyTrial.finalize_definition(
        trial, {}, None, None
    )
    control = LanguageVocabularyTrial.show_trial(trial, None, None).control

    assert control.choices == ["1", "2", "3", "4"]
    correct = control.choices[trial.definition["order"].index(0)]
    assert control.labels[int(correct) - 1].startswith('<img src="/asset/0"')

    def score(answer):
        return LanguageVocabularyTrial.score_answer(None, answer, trial.definition)

    assert score(correct) == 1
    assert [score(c) for c in control.choices if c != correct] == [0, 0, 0]
    assert score("correct") == 0
