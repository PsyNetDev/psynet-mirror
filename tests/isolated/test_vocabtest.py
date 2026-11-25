from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

from psynet.prescreen.vocabtest import VocabTest, VocabTrial


def _make_vocab_test(tmp_path, real=("cat", "dog"), fake=("xzz", "qrv"), **kwargs):
    csv_path = tmp_path / "items.csv"
    csv_path.write_text(
        "stimulus,correct_answer\n"
        + "".join(f"{word},correct\n" for word in real)
        + "".join(f"{word},incorrect\n" for word in fake)
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
    assert maker.score_form(list(reversed(form)), 6) == expected
    assert maker.score_form(form[:-1], 6) == 0
    form[0].failed = True
    assert maker.score_form(form, 6) == 0


def test_each_form_is_checked_once_its_last_word_is_answered_and_at_the_end(tmp_path):
    maker = _make_vocab_test(tmp_path, n_trials=2, performance_threshold_per_trial=1)
    trials = words(maker, ["real", "real", "fake", "fake"]) + words(
        maker, ["fake"] * 4, offset=4
    )
    checked = [maker.should_check_performance_after(t) for t in trials]
    assert checked == [False, False, False, True] * 2
    assert maker.performance_check(None, None, trials[:4]) == {
        "score": 1,
        "passed": True,
    }
    assert maker.performance_check(None, None, trials) == {
        "score": 0.5,
        "passed": False,
    }
    # The check at the end also fails a form left unfinished, for example
    # because its last words timed out.
    assert not maker.performance_check(None, None, trials[:6])["passed"]
    # Every form must pass, not only the latest.
    first_fails = words(maker, ["fake"] * 4) + words(
        maker, ["real", "real", "fake", "fake"], offset=4
    )
    assert maker.performance_check(None, None, first_fails) == {
        "score": 1,
        "passed": False,
    }


def test_forms_balance_real_and_fake_words_and_prefer_unseen_ones(tmp_path):
    maker = _make_vocab_test(
        tmp_path,
        real=("cat", "dog", "owl"),
        fake=("xzz", "qrv", "plk"),
        n_trials=2,
        n_repeat_items=1,
    )
    order = maker.word_order(maker.start_nodes, participant=None)
    forms = [order[:5], order[5:]]
    for form in forms:
        originals, repeat = form[:4], form[4]
        answers = [node.definition["correct_answer"] for node in originals]
        assert sorted(answers) == ["correct"] * 2 + ["incorrect"] * 2
        assert len(set(map(id, originals))) == 4 and repeat in originals
    # Each word left out of the first form is in the second.
    assert set(map(id, maker.start_nodes)) - set(map(id, forms[0])) <= set(
        map(id, forms[1])
    )


def test_word_pages_share_their_html_and_hide_the_answer(tmp_path):
    maker = _make_vocab_test(tmp_path)
    pages = [
        maker.word_page(SimpleNamespace(definition=node.definition))
        for node in maker.start_nodes[:2]
    ]
    assert [page.contents for page in pages] == [
        {"stimulus": "cat"},
        {"stimulus": "dog"},
    ]
    assert str(pages[0].html) == str(pages[1].html)


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
