"""Lock deployment-test recruiter selection to config files and launch guards."""

from psynet.utils import get_psynet_root

DEPLOYMENT_ROOT = get_psynet_root() / "tests/deployment"


def _config_recruiter(experiment_dir, name):
    """Return the first uncommented recruiter assignment in a config file."""
    for line in (experiment_dir / name).read_text().splitlines():
        stripped = line.split("#", 1)[0].strip()
        if stripped.startswith("recruiter"):
            return stripped.split("=", 1)[1].strip()
    raise AssertionError(f"no recruiter assignment in {name}")


def test_deployment_experiments_select_recruiter_in_config():
    for experiment in (
        "payment_flows_prolific",
        "auto_recruit_prolific",
        "audio_gibbs",
    ):
        exp_dir = DEPLOYMENT_ROOT / experiment
        assert _config_recruiter(exp_dir, "config.txt") == "devprolific"
        assert _config_recruiter(exp_dir, "config.txt.prolific") == "prolific"
        assert not (exp_dir / "experiment.py.prolific").exists()
        shared = (exp_dir / "experiment.py").read_text()
        assert '"recruiter":' not in shared
        assert 'recruiter not in ("prolific", "devprolific")' in shared

    audio_gibbs = DEPLOYMENT_ROOT / "audio_gibbs"
    assert _config_recruiter(audio_gibbs, "config.txt.lucid") == "lucid-recruiter"
    assert (
        'recruiter != "lucid-recruiter"'
        in (audio_gibbs / "experiment.py.lucid").read_text()
    )
