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


def _make_vocab_test(tmp_path, **kwargs):
    csv_path = tmp_path / "items.csv"
    csv_path.write_text(
        "stimulus,correct_answer\ncat,correct\ndog,correct\nxzz,incorrect\nqrv,incorrect\n"
    )
    kwargs.setdefault("performance_threshold_per_trial", None)
    with pytest.warns(UserWarning, match="not presented as images"):
        return VocabTest(
            locale="en",
            label="vocab",
            csv_path=str(csv_path),
            n_items=4,
            present_as_image=False,
            **kwargs,
        )


def _score(vocab_test, hashes, answer):
    seed = vocab_test.start_nodes[0].seed
    trial = SimpleNamespace(
        id=1,
        definition={"hashes": hashes},
        node=SimpleNamespace(seed=seed),
        answer=answer,
    )
    return vocab_test.score_trial(trial)


def test_vocab_item_ids_do_not_identify_words(tmp_path):
    first, second = _make_vocab_test(tmp_path), _make_vocab_test(tmp_path)
    assert {item["hash"] for item in first.start_nodes[0].seed}.isdisjoint(
        item["hash"] for item in second.start_nodes[0].seed
    )


def test_vocab_scores_only_complete_answers(tmp_path):
    vocab_test = _make_vocab_test(tmp_path)
    seed = vocab_test.start_nodes[0].seed
    hashes = [item["hash"] for item in seed]
    correct = [
        {
            "hash": item["hash"],
            "answer": "real" if item["stimulus"] in ("cat", "dog") else "fake",
        }
        for item in seed
    ]

    assert _score(vocab_test, hashes, correct) == 1
    assert _score(vocab_test, hashes, correct[:1]) == 0
    assert _score(vocab_test, hashes, correct[:1] * 4) == 0
    assert _score(vocab_test, hashes, list(reversed(correct))) == 0
    assert (
        _score(vocab_test, hashes, [{**item, "answer": "yes"} for item in correct]) == 0
    )


def test_vocab_performance_check_scores_the_latest_trial(tmp_path):
    vocab_test = _make_vocab_test(
        tmp_path, n_trials=2, performance_threshold_per_trial=1
    )
    seed = vocab_test.start_nodes[0].seed
    hashes = [item["hash"] for item in seed]
    correct = [
        {
            "hash": item["hash"],
            "answer": "real" if item["stimulus"] in ("cat", "dog") else "fake",
        }
        for item in seed
    ]

    def trial(answer):
        return SimpleNamespace(
            id=1,
            definition={"hashes": hashes},
            node=SimpleNamespace(seed=seed),
            answer=answer,
        )

    result = vocab_test.performance_check(None, None, [trial(correct), trial(None)])
    assert result["passed"] is False


@pytest.mark.parametrize("answer", [None, "real", {"hash": "h", "answer": "real"}])
def test_vocab_scores_non_list_answers_as_zero(tmp_path, answer):
    vocab_test = _make_vocab_test(tmp_path)
    hashes = [item["hash"] for item in vocab_test.start_nodes[0].seed]
    assert _score(vocab_test, hashes, answer) == 0


def test_vocab_consistency_rejects_answers_for_other_items(tmp_path):
    vocab_test = _make_vocab_test(
        tmp_path, performance_check_type="consistency", n_repeat_items=2
    )
    seed = vocab_test.start_nodes[0].seed
    hashes = [item["hash"] for item in seed] + [seed[0]["hash"], seed[1]["hash"]]
    answer = [{"hash": seed[0]["hash"], "answer": "real"}] * len(hashes)

    assert _score(vocab_test, hashes, answer) == 0


@pytest.mark.parametrize(
    "performance_check_type, expected", [("accuracy", 1), ("consistency", 0.5)]
)
def test_vocab_scores_answers_with_repeat_items(
    tmp_path, performance_check_type, expected
):
    vocab_test = _make_vocab_test(
        tmp_path, performance_check_type=performance_check_type, n_repeat_items=2
    )
    seed = vocab_test.start_nodes[0].seed
    correct = [
        {
            "hash": item["hash"],
            "answer": "real" if item["stimulus"] in ("cat", "dog") else "fake",
        }
        for item in seed
    ]
    flipped = {"real": "fake", "fake": "real"}[correct[1]["answer"]]
    repeats = [correct[0], {**correct[1], "answer": flipped}]
    answer = correct + repeats

    assert _score(vocab_test, [item["hash"] for item in answer], answer) == expected


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


def _fake_font_response(content=b"font", error=None):
    def raise_for_status():
        if error:
            raise error

    return SimpleNamespace(content=content, raise_for_status=raise_for_status)


def test_vocab_font_is_downloaded_once_into_static_fonts(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    downloads = []

    def fake_get(url, **kwargs):
        downloads.append(url)
        return _fake_font_response()

    monkeypatch.setattr("psynet.prescreen.vocabtest.requests.get", fake_get)

    url = "https://example.org/fonts/Font.ttf"
    first = VocabTest.get_font_path(url)
    second = VocabTest.get_font_path(url)

    assert first == second == str(tmp_path / "static" / "fonts" / "Font.ttf")
    assert Path(first).read_bytes() == b"font"
    assert downloads == [url]
    assert sorted(p.name for p in (tmp_path / "static" / "fonts").iterdir()) == [
        "Font.ttf"
    ]


def test_vocab_font_download_failure_raises(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "psynet.prescreen.vocabtest.requests.get",
        lambda url, **kwargs: _fake_font_response(error=requests.HTTPError("404")),
    )

    with pytest.raises(requests.HTTPError):
        VocabTest.get_font_path("https://example.org/fonts/Font.ttf")
    assert not (tmp_path / "static" / "fonts" / "Font.ttf").exists()
