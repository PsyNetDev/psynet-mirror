import pytest

from psynet.experiment import _deployment_label_slug


@pytest.mark.parametrize(
    "label, slug",
    [
        ("The prisoner's dilemma", "the-prisoner-s-dilemma"),
        ("Musik-Präferenz", "musik-präferenz"),
        ("音乐偏好", "音乐偏好"),
        ("!!!", "experiment"),
    ],
)
def test_deployment_label_slug(label, slug):
    assert _deployment_label_slug(label) == slug
