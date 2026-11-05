import sys
from pathlib import Path

import pytest
from markupsafe import Markup

from psynet import timeline_hold
from psynet.experiment import get_experiment
from psynet.group_prompt import GroupPrompt
from psynet.pytest_psynet import path_to_test_experiment
from psynet.sync import (
    GroupBarrier,
    SimpleGrouper,
    SimpleSyncGroup,
    arrival_notice_payload,
    group_seats,
)

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
    both = sorted([seats[first.id], seats[second.id]])
    (*_, update) = [t for t in published if t["participant_id"] == third.id]
    assert update["group_ready"]["seats"] == both
    # Without notice text, the update leaves the browser's notice alone.
    assert "notice" not in update and "notices" not in update["group_ready"]
    # Members already waiting get the ticks too.
    (*_, update) = [t for t in published if t["participant_id"] == first.id]
    assert update["group_ready"]["seats"] == both

    # Otherwise it carries the notice for each count the browser can reach,
    # so that it can count arrivals that concurrent requests reported apart.
    published.clear()
    _arrive(exp, GroupBarrier("next", group_type="room"), [first])
    (update,) = [t for t in published if t["participant_id"] == third.id]
    assert update["group_ready"]["notices_from"] == 1
    assert update["group_ready"]["notices"] == [
        "1/3 of your group are ready.",
        "2/3 of your group are ready.",
    ]
    # A page that connects later gets the ready seats from the snapshot.
    snapshot = arrival_notice_payload(third.unique_id)["group_ready"]
    assert {
        "group_id": group.id,
        "barrier_id": "next",
        "seats": [seats[first.id]],
    } in snapshot

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

    html = GroupPrompt(
        group=group, participant=first, subgroups=lambda p: p.id == second.id
    ).group_html
    clusters = html.split('class="psynet-group-cluster"')[1:]
    assert len(clusters) == 2
    assert "You" in clusters[0] and third.pseudonym.name in clusters[0]
    assert second.pseudonym.name in clusters[1]

    html = GroupPrompt(group=group, participant=first, anonymous=True).group_html
    assert html.count(">Another player<") == 2 and ">You<" in html
    assert not any(p.pseudonym.name in html for p in (first, second, third))

    # Pseudonyms are only made distinct in a participant's first group.
    third.set_pseudonym(first.pseudonym.color, first.pseudonym.animal)
    _arrive(exp, SimpleGrouper("again", initial_group_size=3), [first, second, third])
    assert third.pseudonym.name == first.pseudonym.name

    # Members without an answer get no bubble.
    html = GroupPrompt(
        group=group, participant=first, answers={second.id: None}
    ).group_html
    assert "psynet-group-bubble--none" in html and ">None<" not in html


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_group_seats_follow_joining_order(in_experiment_directory, db_session):
    exp = get_experiment()
    early, late = _working_participants(exp, 2)
    group = SimpleSyncGroup(group_type="room", initial_group_size=2)
    db_session.add(group)
    db_session.flush()
    assert (
        'aria-label="Group"' in GroupPrompt(group=group, participant=early).group_html
    )

    group.add_participant(late)
    group.add_participant(early)
    db_session.flush()
    assert group_seats(group) == {late.id: 0, early.id: 1}
