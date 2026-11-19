from types import SimpleNamespace

import numpy as np
import pytest

from psynet.demography.general import Age, CountryOfBirth, CountryOfResidence, Gender
from psynet.demography.gmsi import GMSI


@pytest.mark.parametrize(
    "answer, valid",
    [(25, True), (np.int64(30), True), (25.5, False), (30.0, False)]
    + [("", False), ("25", False), (150, False), (True, False)],
)
def test_age_accepts_whole_numbers_in_range(answer, valid):
    failed = Age().validate(SimpleNamespace(answer=answer)) is not None
    assert failed != valid


def test_gmsi_start_age_is_unscored_when_no_instrument_is_played():
    assert GMSI.calculate_score("q_40", 19) is None
    assert GMSI.calculate_score("q_40", 5) == 5


def test_country_pages_save_to_separate_participant_vars():
    assert CountryOfBirth().save_answer == "country_of_birth"
    assert CountryOfResidence().save_answer == "country_of_residence"


def test_gender_options_wrap_in_rows_to_fit_the_window():
    assert Gender().control.arrange_vertically is False
