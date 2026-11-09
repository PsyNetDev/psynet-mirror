"""Tests for psynet.field module."""

import pytest

from psynet.experiment import get_experiment
from psynet.field import _PythonDict, _PythonList, claim_var
from psynet.participant import Participant
from psynet.pytest_psynet import path_to_test_experiment


class TestSerialize:
    """Test that serialize methods work correctly."""

    def test_python_list_serialize(self):
        """Test that _PythonList.serialize works correctly as a classmethod."""
        result = _PythonList.serialize([1, 2, 3])
        assert result == "[1, 2, 3]"

    def test_python_dict_serialize(self):
        """Test that _PythonDict.serialize works correctly as a classmethod."""
        result = _PythonDict.serialize({"a": 1, "b": 2})
        assert result == '{"a": 1, "b": 2}'


def test_claim_var_rejects_legacy_extra_vars_dict():
    with pytest.raises(TypeError, match="extra_vars"):
        claim_var("analysis", {"analysis": {}})


def test_claim_var_supports_use_default():
    class Stub:
        class _Var:
            def __getattr__(self, name):
                raise KeyError(name)

        var = _Var()
        value = claim_var("missing", use_default=True, default=lambda: "fallback")

    assert Stub().value == "fallback"


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_participant_var_keeps_integer_keys(in_experiment_directory, db_session):
    participant = Participant(
        experiment=get_experiment(),
        recruiter_id="hotair",
        worker_id="worker",
        hit_id="hit",
        assignment_id="assignment",
        mode="debug",
    )
    db_session.add(participant)
    participant.var.choice_by_player = {12: "rock", 15: "paper"}
    db_session.commit()
    db_session.expire_all()

    reloaded = Participant.query.get(participant.id)
    assert reloaded.var.choice_by_player == {12: "rock", 15: "paper"}
