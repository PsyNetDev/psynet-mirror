"""Tests for psynet.field module."""

import pytest

from psynet.field import _PythonDict, _PythonList, claim_var


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
