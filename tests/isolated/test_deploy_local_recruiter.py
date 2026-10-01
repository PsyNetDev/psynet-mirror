import click
import pytest

from psynet import command_line
from psynet.recruiters import GenericRecruiter, HotAirRecruiter, ProlificRecruiter


@pytest.fixture(autouse=True)
def _skip_dependency_checks(monkeypatch):
    monkeypatch.setattr(
        command_line, "check_psynet_requirement_is_unambiguous", lambda: None
    )
    monkeypatch.setattr(
        command_line, "check_core_dependency_versions_match_requirements", lambda: None
    )


@pytest.mark.parametrize("recruiter_class", [GenericRecruiter, HotAirRecruiter])
def test_deploy_local_accepts_local_recruiters(recruiter_class):
    command_line.run_pre_checks_deploy(True, recruiter_class.__new__(recruiter_class))


def test_deploy_local_rejects_platform_recruiters():
    recruiter = ProlificRecruiter.__new__(ProlificRecruiter)
    with pytest.raises(click.UsageError, match="generic"):
        command_line.run_pre_checks_deploy(True, recruiter)
