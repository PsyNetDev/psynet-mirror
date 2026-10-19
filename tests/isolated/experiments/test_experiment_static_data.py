import re

import jsonpickle
import pandas as pd
import pandas.testing as pdt
import pytest

import psynet.data  # noqa - for the jsonpickle registration
from psynet.pytest_psynet import path_to_test_experiment
from psynet.utils import json_to_data_frame


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("static")], indirect=True
)
@pytest.mark.usefixtures("launched_experiment")
def test_jsonpickle(trial):
    pattern = r'\{"py/object": "dallinger_experiment\.experiment\.AnimalTrial", "identifiers": \{"id": \d+}}'
    assert re.fullmatch(pattern, jsonpickle.encode(trial, keys=True).replace("\n", ""))


def test_json_to_data_frame():
    x = {"id": 1, "a": 2, "b": 3}
    y = {"id": 2, "a": 4, "b": 8}
    json_data = [x, y]
    columns = ["id", "a", "b"]
    expected_result = pd.DataFrame.from_records(json_data, columns=columns)

    assert (
        pdt.assert_frame_equal(json_to_data_frame(json_data), expected_result) is None
    )


def test_json_to_data_frame_extra_column():
    x = {"id": 1, "a": 2, "b": 3}
    y = {"id": 2, "a": 4, "c": 8}
    json_data = [x, y]
    columns = ["id", "a", "b", "c"]
    expected_result = pd.DataFrame.from_records(json_data, columns=columns)

    assert (
        pdt.assert_frame_equal(json_to_data_frame(json_data), expected_result) is None
    )


def test_json_to_data_frame_extra_columns_mixed_different_length():
    x = {"id": 1, "a": 2, "c": 3}
    y = {"id": 2, "d": 4, "a": 8, "b": 11}
    json_data = [x, y]
    columns = ["id", "a", "c", "d", "b"]
    expected_result = pd.DataFrame.from_records(json_data, columns=columns)

    assert (
        pdt.assert_frame_equal(json_to_data_frame(json_data), expected_result) is None
    )
