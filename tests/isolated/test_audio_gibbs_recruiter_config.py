"""Lock audio_gibbs recruiter selection to config files and matching launch guards."""

from psynet.utils import get_psynet_root

AUDIO_GIBBS = get_psynet_root() / "tests/deployment/audio_gibbs"


def _config_recruiter(name: str) -> str:
    """Return the first uncommented recruiter assignment in a config file."""
    text = (AUDIO_GIBBS / name).read_text()
    for line in text.splitlines():
        stripped = line.split("#", 1)[0].strip()
        if stripped.startswith("recruiter"):
            return stripped.split("=", 1)[1].strip()
    raise AssertionError(f"no recruiter assignment in {name}")


def test_audio_gibbs_prolific_recruiter_is_selected_in_config():
    assert _config_recruiter("config.txt") == "devprolific"
    assert _config_recruiter("config.txt.prolific") == "prolific"
    assert _config_recruiter("config.txt.lucid") == "lucid-recruiter"
    assert not (AUDIO_GIBBS / "experiment.py.prolific").exists()

    shared = (AUDIO_GIBBS / "experiment.py").read_text()
    assert '"recruiter":' not in shared
    assert 'recruiter not in ("prolific", "devprolific")' in shared

    lucid = (AUDIO_GIBBS / "experiment.py.lucid").read_text()
    assert 'recruiter != "lucid-recruiter"' in lucid
