import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from psynet.experiment import get_experiment
from psynet.pseudonym import PseudonymScheme
from psynet.pytest_psynet import path_to_test_experiment

sys.path.insert(0, str(Path(__file__).resolve().parent))
from timeline_hold_helpers import _working_participants  # noqa: E402


def _participant(id_, stored=None):
    var = SimpleNamespace(get=lambda key, default: stored or default)
    return SimpleNamespace(id=id_, var=var)


class _SeededScheme(PseudonymScheme):
    def __init__(self, seed):
        self._seed = seed

    def seed(self):
        return self._seed


def test_neighbours_differ_and_deployments_shuffle_pseudonyms():
    scheme = _SeededScheme("deployment-a")
    pseudonyms = [scheme.pseudonym(_participant(i)) for i in range(1, 89)]

    assert len({p.name for p in pseudonyms}) == 88
    for a, b in zip(pseudonyms, pseudonyms[1:]):
        assert a.color != b.color and a.animal != b.animal
    other = [_SeededScheme("deployment-b").pseudonym(_participant(i)) for i in (1, 2)]
    assert [p.name for p in other] != [p.name for p in pseudonyms[:2]]
    blue_fox = scheme.make("blue", "fox")
    assert (blue_fox.name, blue_fox.emoji) == ("Blue fox", "🦊")
    assert "--psynet-pseudonym-color: #0072B2" in blue_fox.icon_html


def test_schemes_and_stored_pseudonyms_can_be_customized():
    class Teams(PseudonymScheme):
        def animals(self):
            return {"lion": ("lion", "🦁"), "bear": ("bear", "🐻")}

        def name(self, color_label, animal_label):
            return f"{animal_label.title()} ({color_label})"

    scheme = Teams()
    stored = scheme.pseudonym(_participant(1, {"color": "red", "animal": "bear"}))

    assert stored.name == "Bear (red)"
    assert scheme.pseudonym(_participant(2)).animal in {"lion", "bear"}
    with pytest.raises(ValueError, match="Unknown pseudonym animal 'fox'"):
        scheme.make("red", "fox")


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_set_pseudonym_overrides_the_default(in_experiment_directory, db_session):
    (participant,) = _working_participants(get_experiment(), 1)

    participant.set_pseudonym("red", "whale")

    assert participant.pseudonym.name == "Red whale"
    with pytest.raises(ValueError, match="Unknown pseudonym color"):
        participant.set_pseudonym("teal", "whale")
