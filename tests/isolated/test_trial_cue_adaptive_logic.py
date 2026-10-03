"""Unit tests for the Trial.cue adaptive staircase demo policy."""

import importlib.util

from psynet.utils import get_psynet_root


def _load_adaptive_logic():
    path = (
        get_psynet_root()
        / "demos"
        / "features"
        / "trial_cue_adaptive"
        / "adaptive_logic.py"
    )
    spec = importlib.util.spec_from_file_location("trial_cue_adaptive_logic", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


logic = _load_adaptive_logic()


def test_first_item_is_the_starting_difficulty():
    assert logic.select_difficulty([]) == logic.START


def test_correct_answers_move_up_until_the_ceiling():
    history = [
        {"difficulty": 4, "correct": True},
        {"difficulty": 5, "correct": True},
        {"difficulty": 6, "correct": True},
        {"difficulty": 7, "correct": True},
    ]
    assert [logic.select_difficulty(history[:i]) for i in range(5)] == [
        4,
        5,
        6,
        7,
        7,
    ]


def test_incorrect_answers_move_down_until_the_floor():
    history = [{"difficulty": 4, "correct": False}]
    assert logic.select_difficulty(history) == 3
    history.append({"difficulty": 3, "correct": False})
    history.append({"difficulty": 2, "correct": False})
    history.append({"difficulty": 1, "correct": False})
    assert logic.select_difficulty(history) == 1


def test_stops_at_the_trial_cap_or_two_reversals():
    always_up = [{"difficulty": n, "correct": True} for n in (4, 5, 6, 7, 7, 7, 7)]
    assert not logic.should_stop(always_up)
    always_up.append({"difficulty": 7, "correct": True})
    assert logic.should_stop(always_up)

    reversing = [
        {"difficulty": 4, "correct": True},
        {"difficulty": 5, "correct": False},
        {"difficulty": 4, "correct": True},
        {"difficulty": 5, "correct": False},
    ]
    assert logic.n_reversals(reversing) == 2
    assert logic.should_stop(reversing)
