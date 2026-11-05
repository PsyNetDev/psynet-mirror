import sys
from pathlib import Path

import pytest
from markupsafe import Markup

from psynet import timeline_hold
from psynet.experiment import get_experiment
from psynet.group_prompt import GroupPrompt
from psynet.pytest_psynet import path_to_test_experiment
from psynet.sync import GroupBarrier, SimpleGrouper, group_seats

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_regrouper import _arrive  # noqa: E402
from timeline_hold_helpers import _working_participants  # noqa: E402


def _no_notice(**kwargs):
    return None


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_group_prompt_shows_distinct_members_ticks_and_answers(
    in_experiment_directory, db_session, monkeypatch
):
    exp = get_experiment()
    published = []
    monkeypatch.setattr(timeline_hold, "_publish_wakes", published.extend)
    first, second, third = _working_participants(exp, 3)
    for participant in (first, second):
        participant.set_pseudonym("blue", "fox")
    _arrive(exp, SimpleGrouper("room", initial_group_size=3), [first, second, third])
    group = third.active_sync_groups["room"]
    assert len({p.pseudonym.name for p in (first, second, third)}) == 3

    published.clear()
    barrier = GroupBarrier("decided", group_type="room", on_arrival_message=_no_notice)
    _arrive(exp, barrier, [first, second])
    seats = group_seats(group)
    (*_, update) = [t for t in published if t["participant_id"] == third.id]
    assert update["group_ready"] == {
        "group_id": group.id,
        "seats": sorted([seats[first.id], seats[second.id]]),
    }
    # Without notice text, the update leaves the browser's notice alone.
    assert "notice" not in update

    html = GroupPrompt("Choose", group=group, participant=third).group_html
    assert html.index("You") < html.index(first.pseudonym.name)
    assert html.count("psynet-group-member--answered") == 2

    html = GroupPrompt(
        "Results",
        group=group,
        participant=third,
        answers={first.id: "<b>3</b>", second.id: Markup("<img alt='3'>")},
        highlight={first.id: "winner"},
    ).group_html
    assert "&lt;b&gt;3&lt;/b&gt;" in html and "<img alt='3'>" in html
    assert "psynet-group-member--winner" in html
    assert "psynet-group-member--answered" not in html
