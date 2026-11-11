"""Tests for the story_chain demo's own turn logic, with its trials built directly."""

import sys
import uuid

import pytest
from dallinger import db

from psynet.experiment import get_experiment
from psynet.participant import Participant
from psynet.pytest_psynet import path_to_demo_experiment
from psynet.sync import SimpleSyncGroup
from psynet.timeline import Module

in_story_chain = pytest.mark.parametrize(
    "experiment_directory", [path_to_demo_experiment("story_chain")], indirect=True
)


def _story_group(exp):
    """Return the demo module and a group of three that has started the story, in seat order."""
    demo = sys.modules[type(exp).__module__]
    members = [
        Participant(
            experiment=exp,
            recruiter_id="hotair",
            worker_id=str(uuid.uuid4()),
            hit_id="XYZ",
            assignment_id=str(uuid.uuid4()),
            mode="debug",
        )
        for _ in range(demo.GROUP_SIZE)
    ]
    group = SimpleSyncGroup(
        group_type=demo.GROUP,
        initial_group_size=demo.GROUP_SIZE,
        min_group_size=2,
        n_active_participants=demo.GROUP_SIZE,
        accepts_top_ups=False,
    )
    db.session.add_all([*members, group])
    for participant in members:
        participant.status = "working"
        group.add_participant(participant)
        participant.start_module(Module("story", []))
    group.leader = members[0]
    db.session.commit()
    return demo, group, members


def _cue_turn(demo, turn, players):
    """Give ``players`` their trials for the turn, as its cue does, and return the writer."""
    for participant in players:
        demo.StoryTurn.cue(demo.turn_definition, round=turn)[0].consume(
            get_experiment(), participant
        )
    return next(p for p in players if p.current_trial.is_writer)


def _play_turn(demo, turn, players, sentence):
    """Cue the turn and have its writer submit ``sentence``; return the writer."""
    writer = _cue_turn(demo, turn, players)
    writer.answer = sentence
    writer.current_trial.save_sentence(writer)
    return writer


@in_story_chain
@pytest.mark.parametrize(
    "outcome, saved", [(None, True), ("group_dissolved", True), ("late", False)]
)
def test_the_writer_s_sentence_is_kept_unless_they_were_late(
    in_experiment_directory, db_session, outcome, saved
):
    demo, _, members = _story_group(get_experiment())
    writer = _cue_turn(demo, 0, members)
    trial = writer.current_trial
    trial.sync_group_outcome = outcome
    writer.answer = "Once upon a time."
    trial.save_sentence(writer)
    trial.on_finalized()

    assert trial.node.var.sentence == ("Once upon a time." if saved else None)


@in_story_chain
def test_the_last_page_says_why_the_story_ended_early(
    in_experiment_directory, db_session
):
    demo, group, (first, second, third) = _story_group(get_experiment())
    for participant in (first, second, third):
        demo.remember_group(participant)
    _play_turn(demo, 0, [first, second, third], "Once upon a time.")
    group.remove_participant(second, reason="late")
    db.session.commit()

    assert demo.final_page(second).prompt.text == (
        "You were away for too long, so your group went on without you. "
        "Here is the story so far: Once upon a time. How much do you like the story?"
    )
    assert demo.final_page(third).prompt.text.startswith(
        "Here is the story your group wrote:"
    )


@in_story_chain
def test_the_next_seat_writes_for_a_member_who_left(
    in_experiment_directory, db_session
):
    demo, group, (first, second, third) = _story_group(get_experiment())
    assert _play_turn(demo, 0, [first, second, third], "Once upon a time.") == first
    group.remove_participant(second, reason="late")
    assert _play_turn(demo, 1, [first, third], "A dragon appeared.") == third
    assert _play_turn(demo, 2, [first, third], "It was hungry.") == third
    db.session.commit()

    assert [node.definition["writer_id"] for node in demo.group_turns(group.id)] == [
        first.id,
        third.id,
        third.id,
    ]
    assert demo.story_text(group.id) == (
        "Once upon a time. A dragon appeared. It was hungry."
    )
