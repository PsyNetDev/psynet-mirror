from types import SimpleNamespace

import pytest

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
    return VocabTest(
        locale="en",
        label="vocab",
        csv_path=str(csv_path),
        performance_threshold_per_trial=None,
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
    assert (
        _score(vocab_test, hashes, [{**item, "answer": "yes"} for item in correct]) == 0
    )


def test_vocab_consistency_rejects_answers_for_other_items(tmp_path):
    vocab_test = _make_vocab_test(
        tmp_path, performance_check_type="consistency", n_repeat_items=2
    )
    seed = vocab_test.start_nodes[0].seed
    hashes = [item["hash"] for item in seed] + [seed[0]["hash"], seed[1]["hash"]]
    answer = [{"hash": seed[0]["hash"], "answer": "real"}] * len(hashes)

    assert _score(vocab_test, hashes, answer) == 0


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
