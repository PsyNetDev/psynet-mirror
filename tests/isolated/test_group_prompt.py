import sys
from pathlib import Path

import pytest
from markupsafe import Markup

from psynet import timeline_hold
from psynet.experiment import get_experiment
from psynet.group_prompt import GroupPrompt, redrawn_group_html
from psynet.pytest_psynet import path_to_test_experiment
from psynet.sync import (
    GroupBarrier,
    SimpleGrouper,
    SimpleSyncGroup,
    arrival_notice_payload,
    group_seats,
)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_regrouper import _arrive, _commit_barrier_arrivals  # noqa: E402
from timeline_hold_helpers import _working_participants  # noqa: E402


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

    # Arrivals in concurrent requests don't see each other, so every member,
    # including those already waiting, fetches the committed state instead.
    published.clear()
    _arrive(exp, GroupBarrier("decided", group_type="room"), [first, second])
    refreshed = {t["participant_id"] for t in published if t.get("refresh")}
    assert refreshed == {first.id, second.id, third.id}
    seats = group_seats(group)
    assert arrival_notice_payload(third.unique_id) == {
        "notice": "2/3 of your group are ready.",
        "group_ready": [
            {
                "group_id": group.id,
                "seats": sorted([seats[first.id], seats[second.id]]),
                "members": [0, 1, 2],
            }
        ],
    }

    html = GroupPrompt("Choose", group=group, participant=third).group_html
    assert html.index(">You<") < html.index(first.pseudonym.name)
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

    # When a member leaves, the others fetch the seats again without them.
    published.clear()
    group.remove_participant(first)
    _commit_barrier_arrivals()
    assert any(t.get("refresh") for t in published if t["participant_id"] == third.id)


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

    # Members are shown in seat order, and an anonymous partner is labelled as such.
    third = _working_participants(exp, 1)[0]
    html = GroupPrompt(group=group, participant=third, anonymous=True).group_html
    assert html.index('data-seat="0"') < html.index('data-seat="1"')
    html = GroupPrompt(group=group, participant=early, anonymous=True).group_html
    assert ">Your partner<" in html

    # Without ``group``, the prompt shows the participant's group, or just its
    # text if they aren't in one, for example after being removed from it.
    assert GroupPrompt(participant=early, group_type="room").group == group
    prompt = GroupPrompt("Choose", participant=third)
    assert prompt.group is None and prompt.group_html == ""
    # group=None, as trial.sync_group is after a removal, shows no group
    # even if the participant is in one.
    assert GroupPrompt("Hi", group=None, participant=early).group_html == ""
    with pytest.raises(ValueError, match="not both"):
        GroupPrompt("Hi", group=None, group_type="room", participant=early)

    # A removed member stays in their seat, faded and labelled by why they went.
    group.accepts_top_ups = False
    group.min_group_size = 1
    group.remove_participant(late, reason="out_of_time")
    db_session.flush()

    def html():
        return GroupPrompt(group=group, participant=early, anonymous=True).group_html

    assert 'psynet-group-member--left" data-seat="0"' in html()
    assert ">Your partner (out of time)<" in html()
    # Joining another room doesn't hide the seat they ran out of time in.
    other = SimpleSyncGroup(group_type="room", initial_group_size=2, min_group_size=1)
    db_session.add(other)
    other.add_participant(late)
    db_session.flush()
    assert ">Your partner (out of time)<" in html()
    other.remove_participant(late)
    late.status = "returned"
    assert ">Your partner (left)<" in html()
    # An open-ended group, like a lobby, doesn't show who left.
    group.accepts_top_ups = True
    assert "(left)" not in html()
    group.accepts_top_ups = False
    late.status = "working"
    for reason, label in [(None, "(dropped out)"), ("moved_on", None)]:
        group.add_participant(late)
        group.remove_participant(late, reason=reason)
        db_session.flush()
        if label:
            assert f">Your partner {label}<" in html()
    # Members who moved on to their next group are not shown, except with
    # their answer on a results page, which reads the same after a reload.
    assert "psynet-group-member--left" not in html()
    results = GroupPrompt(
        group=group, participant=early, anonymous=True, answers={late.id: "3"}
    ).group_html
    assert ">3</span>" in results and "psynet-group-member--left" not in results


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_a_removed_partner_stays_in_the_viewers_subgroup(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    viewer, partner, other = _working_participants(exp, 3)
    room, pair, other_pair = [
        SimpleSyncGroup(group_type=group_type, initial_group_size=3, min_group_size=1)
        for group_type in ("room", "pair", "pair")
    ]
    db_session.add_all([room, pair, other_pair])
    for member in (viewer, partner, other):
        room.add_participant(member)
    pair.add_participant(viewer)
    pair.add_participant(partner)
    other_pair.add_participant(other)
    room.remove_participant(partner, reason="out_of_time")
    pair.remove_participant(partner, reason="out_of_time")
    next_pair = SimpleSyncGroup(
        group_type="pair", initial_group_size=2, min_group_size=1
    )
    db_session.add(next_pair)
    next_pair.add_participant(partner)
    db_session.flush()

    html = GroupPrompt(
        group=room, participant=viewer, subgroups="pair", anonymous=True
    ).group_html
    clusters = html.split('class="psynet-group-cluster"')[1:]
    assert len(clusters) == 2
    assert ">Your partner (out of time)<" in clusters[0]


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_live_pages_redraw_the_group_when_someone_joins(
    in_experiment_directory, db_session, monkeypatch
):
    monkeypatch.setenv("FLASK_SECRET_KEY", "test secret")
    exp = get_experiment()
    published = []
    monkeypatch.setattr(timeline_hold, "_publish_wakes", published.extend)
    first, late, other = _working_participants(exp, 3)
    group = SimpleSyncGroup(group_type="room", initial_group_size=3, min_group_size=1)
    db_session.add(group)
    group.add_participant(first)
    db_session.flush()

    def token(**options):
        prompt = GroupPrompt(group=group, participant=first, **options)
        return prompt.get_js_vars()["group_prompt"]["redraw_token"]

    named, anonymous = token(show_names=True), token(anonymous=True)
    # A redraw would drop highlights, so highlighted pages don't redraw.
    assert token(highlight={first.id: "winner"}) is None

    # Members already in the group are told to fetch it again.
    published.clear()
    group.add_participant(late)
    _commit_barrier_arrivals()
    assert any(t.get("refresh") for t in published if t["participant_id"] == first.id)
    assert arrival_notice_payload(first.unique_id)["group_ready"][0]["members"] == [
        0,
        1,
    ]

    html = redrawn_group_html(first.unique_id, named)["html"]
    assert late.pseudonym.name in html
    html = redrawn_group_html(first.unique_id, anonymous)["html"]
    assert ">Your partner<" in html and late.pseudonym.name not in html
    # Tokens only work for the participant they were made for, unchanged.
    assert redrawn_group_html(other.unique_id, named) == {"html": None}
    assert redrawn_group_html(first.unique_id, named[:-2]) == {"html": None}
    # A removed viewer keeps their drawing rather than one without "You".
    group.remove_participant(first)
    assert redrawn_group_html(first.unique_id, named) == {"html": None}
