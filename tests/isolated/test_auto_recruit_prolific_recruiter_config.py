"""Lock auto_recruit_prolific recruiter selection to config files and launch guards."""

from psynet.utils import get_psynet_root

AUTO_RECRUIT_PROLIFIC = get_psynet_root() / "tests/deployment/auto_recruit_prolific"


def _config_recruiter(name: str) -> str:
    """Return the first uncommented recruiter assignment in a config file."""
    text = (AUTO_RECRUIT_PROLIFIC / name).read_text()
    for line in text.splitlines():
        stripped = line.split("#", 1)[0].strip()
        if stripped.startswith("recruiter"):
            return stripped.split("=", 1)[1].strip()
    raise AssertionError(f"no recruiter assignment in {name}")


def test_auto_recruit_prolific_recruiter_is_selected_in_config():
    assert _config_recruiter("config.txt") == "devprolific"
    assert _config_recruiter("config.txt.prolific") == "prolific"
    assert not (AUTO_RECRUIT_PROLIFIC / "experiment.py.prolific").exists()

    shared = (AUTO_RECRUIT_PROLIFIC / "experiment.py").read_text()
    assert '"recruiter":' not in shared
    assert 'recruiter not in ("prolific", "devprolific")' in shared
