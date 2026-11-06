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
    color, animal = stored or (None, None)
    return SimpleNamespace(id=id_, pseudonym_color=color, pseudonym_animal=animal)


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
    class Teams(_SeededScheme):
        def animals(self):
            return {"lion": ("lion", "🦁"), "bear": ("bear", "🐻")}

        def name(self, color_label, animal_label):
            return f"{animal_label.title()} ({color_label})"

    scheme = Teams("deployment-a")
    stored = scheme.pseudonym(_participant(1, ("red", "bear")))

    assert stored.name == "Bear (red)"
    half_stored = _participant(1, ("red", None))
    assert scheme.pseudonym(half_stored) == scheme.pseudonym(_participant(1))
    assert scheme.pseudonym(_participant(2)).animal in {"lion", "bear"}
    with pytest.raises(ValueError, match="Unknown pseudonym animal 'fox'"):
        scheme.make("red", "fox")


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_stored_deployment_id_and_overrides_decide_pseudonyms(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    exp.setup_experiment_config()
    participants = _working_participants(exp, 3)

    def names(deployment_id):
        exp.var.deployment_id = deployment_id
        return [PseudonymScheme().pseudonym(p).name for p in participants]

    assert names("deployment-a") == names("deployment-a") != names("deployment-b")

    participants[0].set_pseudonym("red", "whale")
    assert participants[0].pseudonym.name == "Red whale"
    assert participants[0].to_dict()["pseudonym"] == "Red whale"
    (column,) = [
        c for c in exp.table_columns("participant") if c["data"] == "pseudonym"
    ]
    assert not column["orderable"] and not column["searchable"]
    with pytest.raises(ValueError, match="Unknown pseudonym color"):
        participants[0].set_pseudonym("teal", "whale")
