import sys
from datetime import timedelta
from pathlib import Path

import pytest
from dallinger.models import timenow
from markupsafe import Markup

from psynet import timeline_hold
from psynet.experiment import get_experiment
from psynet.group_prompt import GroupPrompt, _token_serializer, redrawn_group_html
from psynet.modular_page import ModularPage
from psynet.page import InfoPage
from psynet.pseudonym import PseudonymScheme
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


class _AllBlueFoxes(PseudonymScheme):
    def assign(self, participant):
        return ("blue", "fox")


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_group_prompt_shows_distinct_members_ticks_and_answers(
    in_experiment_directory, db_session, monkeypatch
):
    exp = get_experiment()
    published = []
    monkeypatch.setattr(timeline_hold, "_publish_wakes", published.extend)
    monkeypatch.setattr(exp, "pseudonym_scheme", _AllBlueFoxes())
    first, second, third = _working_participants(exp, 3)
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
                "ran_out_of_time": [],
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

    html = GroupPrompt(group=group, participant=first, names="anonymous").group_html
    assert html.count(">Another player<") == 2 and ">You<" in html
    assert not any(p.pseudonym.name in html for p in (first, second, third))
    with pytest.raises(ValueError, match="names must be one of"):
        GroupPrompt(group=group, participant=first, names="hidden")
    with pytest.raises(ValueError, match="either progress or answers"):
        GroupPrompt(group=group, participant=first, answers={}, show_progress=True)

    # Derived pseudonyms are only made distinct in a participant's first
    # group, and pseudonyms that were set are kept there too.
    alike = _working_participants(exp, 2)
    for participant in alike:
        participant.set_pseudonym("blue", "fox")
    _arrive(exp, SimpleGrouper("pair", initial_group_size=2), alike)
    assert {p.pseudonym.name for p in alike} == {"Blue fox"}
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
    group.remove_participant(first, reason="removed_by_experimenter")
    _commit_barrier_arrivals()
    assert any(t.get("refresh") for t in published if t["participant_id"] == third.id)


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_pending_members_joining_separately_get_distinct_pseudonyms(
    in_experiment_directory, db_session, monkeypatch
):
    exp = get_experiment()
    grouper = SimpleGrouper(
        "society",
        initial_group_size=2,
        max_group_size=4,
        quorum=2,
        target_group_size=2,
        join_existing_groups=True,
        use_admission_points=True,
        top_up_wait=30,
        below_quorum="continue_without_group",
    )
    founders = _working_participants(exp, 2)
    founders[0].set_pseudonym("red", "cat")
    founders[1].set_pseudonym("green", "owl")
    grouper._make_group(founders, initial_group_size=2)
    db_session.commit()
    monkeypatch.setattr(exp, "pseudonym_scheme", _AllBlueFoxes())
    newcomers = _working_participants(exp, 2)
    for newcomer in newcomers:
        grouper._join_existing_groups(newcomer)
        db_session.commit()
    assert len({p.pseudonym.name for p in [*founders, *newcomers]}) == 4


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_a_member_who_ran_out_of_time_gets_a_dash(in_experiment_directory, db_session):
    exp = get_experiment()
    first, second, third = _working_participants(exp, 3)
    _arrive(exp, SimpleGrouper("room", initial_group_size=3), [first, second, third])
    group = third.active_sync_groups["room"]

    def time_out(participant, waiting_at=None):
        # These arrivals skip the timeline step that ends a barrier's waiting.
        participant.waiting_barrier_id = waiting_at
        page = ModularPage("choose", "Pick", time_limit=10, time_estimate=5)
        participant.page_deadline = timenow() - timedelta(seconds=10)
        page.process_response(
            raw_answer=None,
            blobs=None,
            metadata={"time_limit_reached": True},
            experiment=exp,
            participant=participant,
        )

    time_out(first)
    # An untimed page, such as feedback, keeps the time-out.
    InfoPage("Feedback").process_response(
        raw_answer=None, blobs=None, metadata={}, experiment=exp, participant=first
    )
    _arrive(exp, GroupBarrier("decided", group_type="room"), [first, second])

    html = GroupPrompt(group=group, participant=third).group_html
    assert html.count("psynet-group-member--ran-out-of-time") == 1
    assert ">ran out of time<" in html
    assert html.count("psynet-group-member--answered") == 1
    (ready,) = arrival_notice_payload(third.unique_id)["group_ready"]
    assert ready["ran_out_of_time"] == [group_seats(group)[first.id]]

    # The timeout only marks the barrier that the page led to.
    _arrive(exp, GroupBarrier("decided", group_type="room"), [third])
    _arrive(exp, GroupBarrier("next", group_type="room"), [first])
    html = GroupPrompt(group=group, participant=third).group_html
    assert "psynet-group-member--ran-out-of-time" not in html

    # Nor does a timed waiting page, such as a filler page.
    time_out(first, waiting_at="next")
    _arrive(exp, GroupBarrier("next", group_type="room"), [second, third])
    _arrive(exp, GroupBarrier("after", group_type="room"), [first])
    html = GroupPrompt(group=group, participant=third).group_html
    assert "psynet-group-member--ran-out-of-time" not in html

    # A member removed for being late is no longer drawn.
    time_out(second)
    _arrive(exp, GroupBarrier("after", group_type="room"), [second])
    group.remove_participant(second, reason="late")
    html = GroupPrompt(group=group, participant=third).group_html
    assert second.pseudonym.name not in html


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
    html = GroupPrompt(group=group, participant=third, names="anonymous").group_html
    assert html.index('data-seat="0"') < html.index('data-seat="1"')
    html = GroupPrompt(group=group, participant=early, names="anonymous").group_html
    assert ">Your partner<" in html

    # Without ``group``, the prompt shows the participant's group, or just its
    # text if they aren't in one, for example after being removed from it.
    assert GroupPrompt(participant=early, group_type="room").group == group
    prompt = GroupPrompt("Choose", participant=third)
    assert prompt.group is None and prompt.group_html == ""
    # group=None, as trial.sync_group is after a removal, shows no group
    # even if the participant is in one.
    assert GroupPrompt("Hi", group=None, participant=early).group_html == ""
    # Bots read the note with the text, but only while it is shown.
    assert GroupPrompt("Hi", participant=early, note="Score: 3").plain_text == (
        "Hi Score: 3"
    )
    assert GroupPrompt("Hi", group=None, participant=early, note="3").plain_text == "Hi"
    with pytest.raises(ValueError, match="not both"):
        GroupPrompt("Hi", group=None, group_type="room", participant=early)

    # A member who left is no longer drawn on a live page.
    group.quorum = 1
    group.remove_participant(late, reason="late")
    db_session.flush()

    # They stay in groups of other types, so groups are looked up by type.
    cohort = SimpleSyncGroup(group_type="cohort", initial_group_size=2)
    db_session.add(cohort)
    cohort.add_participant(late)
    db_session.flush()
    assert late.sync_group == cohort
    assert GroupPrompt(participant=late, group_type="room").group is None
    with pytest.raises(ValueError, match="several types"):
        GroupPrompt(participant=late)

    def html(**options):
        return GroupPrompt(
            group=group, participant=early, names="anonymous", **options
        ).group_html

    assert 'data-seat="0"' not in html()
    # A results page draws everyone in its answers, labelled "(left)" unless
    # they moved on or finished, and reads the same after a reload.
    for answer in ["3", None]:
        assert ">Your partner (left)<" in html(answers={late.id: answer})
    assert "psynet-group-bubble--none" in html(answers={late.id: None})
    for reason in ["moved_on", "finished"]:
        group.add_participant(late)
        group.remove_participant(late, reason=reason)
        db_session.flush()
        results = html(answers={late.id: "3"})
        assert ">Your partner<" in results and 'data-seat="0"' in results
        assert "psynet-group-member--left" not in results
    with pytest.raises(ValueError, match="reason must be"):
        group.remove_participant(late, reason="kicked")


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
    group = SimpleSyncGroup(group_type="room", initial_group_size=3, quorum=1)
    db_session.add(group)
    group.add_participant(first)
    db_session.flush()

    def token(**options):
        prompt = GroupPrompt(group=group, participant=first, **options)
        return prompt.get_js_vars()["group_prompt"]["redraw_token"]

    named, anonymous = token(names="shown"), token(names="anonymous")

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
    highlighted = token(
        highlight={first.id: "duplicate", late.id: "winner"}, note="Round 2"
    )
    # The page can read its token, so it names members by seat.
    assert _token_serializer().loads(highlighted)["highlight"] == {
        "0": "duplicate",
        "1": "winner",
    }
    html = redrawn_group_html(first.unique_id, highlighted)["html"]
    assert "psynet-group-member--winner" in html and "Round 2" in html
    assert "psynet-group-member--duplicate" in html
    # Tokens only work for the participant they were made for, unchanged.
    assert redrawn_group_html(other.unique_id, named) == {"html": None}
    assert redrawn_group_html(first.unique_id, named[:-2]) == {"html": None}
    # A removed viewer keeps their drawing rather than one without "You".
    group.remove_participant(first, reason="removed_by_experimenter")
    assert redrawn_group_html(first.unique_id, named) == {"html": None}
