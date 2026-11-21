from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

from psynet.prescreen.vocabtest import VocabTest, VocabTrial


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


def words(maker, answers, offset=0):
    nodes = list(enumerate(maker.start_nodes, start=1))
    occurrences = nodes + nodes[: maker.n_repeat_items]
    return [
        SimpleNamespace(
            position=position,
            node_id=node_id,
            definition=node.definition,
            module_state_id=7,
            complete=True,
            failed=False,
            answer=answer,
            score=VocabTrial.score_answer(answer, node.definition),
        )
        for position, ((node_id, node), answer) in enumerate(
            zip(occurrences, answers, strict=True), start=offset
        )
    ]


@pytest.mark.parametrize("kind,expected", [("accuracy", 1), ("consistency", 0.5)])
def test_form_scores_native_trials_and_repeated_nodes(tmp_path, kind, expected):
    maker = _make_vocab_test(tmp_path, performance_check_type=kind, n_repeat_items=2)
    form = words(maker, ["real", "real", "fake", "fake", "real", "fake"])
    participant = SimpleNamespace(
        module_state=SimpleNamespace(id=7, n_completed_trials=6)
    )
    assert maker.score_form(participant, list(reversed(form))) == expected
    assert maker.score_form(participant, form[:-1]) == 0
    form[0].failed = True
    assert maker.score_form(participant, form) == 0


def test_performance_check_uses_latest_form_in_this_run(tmp_path):
    maker = _make_vocab_test(tmp_path, n_trials=2, performance_threshold_per_trial=1)
    correct = ["real", "real", "fake", "fake"]
    first = words(maker, correct)
    second = words(maker, ["fake"] * 4, offset=4)
    participant = SimpleNamespace(
        module_state=SimpleNamespace(id=7, n_completed_trials=4)
    )
    assert maker.performance_check(None, participant, first + second)["passed"]
    participant.module_state.n_completed_trials = 8
    other_run = words(maker, correct, offset=4)
    for trial in other_run:
        trial.module_state_id = 8
    assert maker.performance_check(None, participant, first + second + other_run) == {
        "score": 0.5,
        "passed": False,
    }


@pytest.mark.parametrize(
    "public_word", [{"image": "/asset/example"}, {"stimulus": "cat"}]
)
def test_repeat_uses_presentation_position_without_exposing_identifiers(public_word):
    from psynet.live_game import Reject
    from psynet.live_game.testing import LocalGame
    from psynet.prescreen.vocab_live import VocabularyGame, WordResponse

    word = {**public_word, "correct_answer": "correct"}
    plan = {
        "definitions": [word, word, word],
        "_trial_ids": [40, 41, 42],
        "completed": 1,
    }
    session = LocalGame(
        VocabularyGame, players=1, settings={"plans": [plan], "stop": 2}
    )
    view = session.view(0)
    assert view["completed"] == 1
    assert view["definition"] == public_word and view["deck"] == [
        public_word,
        public_word,
    ]
    with pytest.raises(Reject, match="no longer current"):
        session.send(0, WordResponse(position=0, answer="fake"))
    session.send(0, WordResponse(position=1, answer="real"))
    assert session.is_over()


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
