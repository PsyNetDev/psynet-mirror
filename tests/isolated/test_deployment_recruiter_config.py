"""Lock deployment-test recruiter selection to config files and launch guards."""

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from psynet.utils import get_psynet_root

DEPLOYMENT_ROOT = get_psynet_root() / "tests/deployment"
PROLIFIC_LAUNCH_GUARD = 'recruiter not in ("prolific", "devprolific")'


@dataclass(frozen=True)
class _RecruiterLayout:
    experiment: str
    extra_config_recruiters: dict[str, str] = field(default_factory=dict)
    extra_experiment_snippets: dict[str, str] = field(default_factory=dict)
    expects_prolific_launch_guard: bool = True


def _config_recruiter(experiment_dir: Path, name: str) -> str:
    """Return the first uncommented recruiter assignment in a config file."""
    text = (experiment_dir / name).read_text()
    for line in text.splitlines():
        stripped = line.split("#", 1)[0].strip()
        if stripped.startswith("recruiter"):
            return stripped.split("=", 1)[1].strip()
    raise AssertionError(f"no recruiter assignment in {name}")


@pytest.mark.parametrize(
    "layout",
    [
        _RecruiterLayout("payment_flows_prolific", expects_prolific_launch_guard=False),
        _RecruiterLayout("auto_recruit_prolific"),
        _RecruiterLayout(
            "audio_gibbs",
            extra_config_recruiters={"config.txt.lucid": "lucid-recruiter"},
            extra_experiment_snippets={
                "experiment.py.lucid": 'recruiter != "lucid-recruiter"'
            },
        ),
    ],
    ids=lambda layout: layout.experiment,
)
def test_deployment_experiment_selects_recruiter_in_config(layout):
    exp_dir = DEPLOYMENT_ROOT / layout.experiment
    assert _config_recruiter(exp_dir, "config.txt") == "devprolific"
    assert _config_recruiter(exp_dir, "config.txt.prolific") == "prolific"
    assert not (exp_dir / "experiment.py.prolific").exists()

    shared = (exp_dir / "experiment.py").read_text()
    assert '"recruiter":' not in shared
    if layout.expects_prolific_launch_guard:
        assert PROLIFIC_LAUNCH_GUARD in shared

    for name, recruiter in layout.extra_config_recruiters.items():
        assert _config_recruiter(exp_dir, name) == recruiter
    for name, snippet in layout.extra_experiment_snippets.items():
        assert snippet in (exp_dir / name).read_text()
