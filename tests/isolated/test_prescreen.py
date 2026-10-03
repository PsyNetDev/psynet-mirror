import json

import numpy as np
import pytest

from psynet.prescreen import LanguageVocabularyTest, NumpySerializer


class TestNumpySerializer:
    @pytest.mark.parametrize(
        "value,expected",
        [
            (np.bool_(True), '{"value": true}'),
            (np.bool_(False), '{"value": false}'),
            (np.int64(42), '{"value": 42}'),
            (np.float64(3.14), '{"value": 3.14}'),
            (np.array([1, 2, 3]), '{"value": [1, 2, 3]}'),
        ],
    )
    def test_serialize_numpy_types(self, value, expected):
        result = json.dumps({"value": value}, cls=NumpySerializer)
        assert result == expected


def test_language_vocabulary_images_are_specific_to_each_word():
    node = LanguageVocabularyTest.get_nodes(
        None,
        media_url="https://example.com",
        language_code="en-US",
        words=["bell"],
    )[0]

    assert node.assets["image_correct"].url == (
        "https://example.com/images/bell/correct.png"
    )
    assert node.assets["image_wrong1"].url == (
        "https://example.com/images/bell/wrong1.png"
    )
