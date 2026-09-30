from psynet.demography.general import CountryOfBirth, CountryOfResidence


def test_country_pages_save_to_separate_participant_vars():
    assert CountryOfBirth().save_answer == "country_of_birth"
    assert CountryOfResidence().save_answer == "country_of_residence"
