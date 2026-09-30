from psynet.demography.general import CountryOfBirth, CountryOfResidence, Gender


def test_country_pages_save_to_separate_participant_vars():
    assert CountryOfBirth().save_answer == "country_of_birth"
    assert CountryOfResidence().save_answer == "country_of_residence"


def test_gender_options_wrap_in_rows_to_fit_the_window():
    assert Gender().control.arrange_vertically is False
