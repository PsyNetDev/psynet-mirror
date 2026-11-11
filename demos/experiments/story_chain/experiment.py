"""Groups of three take turns writing a story, then rate it.

A :class:`~psynet.sync.SimpleGrouper` forms a group of three, which then
plays ``N_TURNS`` turns in a fixed loop. Each turn is one cued round:
``StoryTurn.cue(..., round=turn)`` gives every member a trial on the
round's shared node. One member writes a sentence while the others see
the story so far and wait at the turn's
:class:`~psynet.sync.GroupBarrier`.

The turn's definition stores the writer, chosen by seat with
:func:`~psynet.sync.group_seats`. The writer stores their sentence in
``node.var.sentence`` as soon as they submit it, and a turn that ends without
one stores ``None``. The last page reads the story with
:meth:`SyncGroup.rounds <psynet.sync.SyncGroup.rounds>`. See ``README.md`` for
what happens when members drop out.
"""

from typing import List, Optional

from dallinger import db

import psynet.experiment
from psynet.bot import (
    BotDriver,
    advance_past_wait_pages,
    bots_by_sync_group,
    run_bots_to_completion,
)
from psynet.group_prompt import GroupPrompt
from psynet.modular_page import ModularPage, PushButtonControl, TextControl
from psynet.page import InfoPage
from psynet.participant import Participant
from psynet.sync import GroupBarrier, SimpleGrouper, SyncGroup, group_seats
from psynet.timeline import (
    CodeBlock,
    Module,
    PageMaker,
    Timeline,
    conditional,
    for_loop,
    join,
)
from psynet.trial.main import SyncGroupNode, Trial

GROUP = "story"
GROUP_SIZE = 3
N_ROUNDS = 2
N_TURNS = N_ROUNDS * GROUP_SIZE
WRITE_SECONDS = 20
LATE_AFTER = 30
GROUPER_WAIT = 30
TURN_BARRIER = "turn_finished"


def get_timeline():
    return Timeline(
        InfoPage(
            "You will write a story with two other people. You take turns, "
            "each adding one sentence.",
            time_estimate=5,
        ),
        SimpleGrouper(
            GROUP,
            initial_group_size=GROUP_SIZE,
            quorum=2,
            below_quorum="continue_without_group",
            max_wait_time=GROUPER_WAIT,
            max_wait_action="continue_without_group",
            waiting_message="Waiting for your group of three to form…",
        ),
        CodeBlock(remember_group),
        Module(
            "story",
            for_loop(
                label="turns",
                iterate_over=range(N_TURNS),
                logic=lambda turn: conditional(
                    "in_group",
                    in_group,
                    StoryTurn.cue(turn_definition, round=turn),
                ),
                time_estimate_per_iteration=StoryTurn.time_estimate,
            ),
        ),
        PageMaker(final_page, time_estimate=10),
    )


def in_group(participant: Participant) -> bool:
    return participant.in_sync_group(GROUP)


def remember_group(participant: Participant):
    """Store the participant's group ID, or ``None``, for the last page and export."""
    group = participant.active_sync_groups.get(GROUP)
    participant.var.story_group_id = group.id if group else None


def choose_writer(group, turn: int) -> int:
    """Return the ID of the member in seat ``turn % GROUP_SIZE``.

    If that member has left, return the member in the next seat still in the
    group.
    """
    seats = group_seats(group)
    by_seat = sorted(seats, key=seats.get)
    start = turn % GROUP_SIZE
    present = {participant.id for participant in group.active_participants}
    return next(pid for pid in by_seat[start:] + by_seat[:start] if pid in present)


def turn_definition(group, round: int) -> dict:
    """Called at the turn's first cue only, so the writer is chosen once and stored."""
    return {"writer_id": choose_writer(group, round)}


def group_turns(group_id: int) -> List[SyncGroupNode]:
    """Return the nodes of the turns the group has started, in order.

    This works even after the group has ended.
    """
    return db.session.get(SyncGroup, group_id).rounds("story")


def story_text(group_id: int) -> str:
    """Return the sentences the group's turns have saved so far, joined into a story.

    A turn still being played has no ``sentence`` yet.
    """
    turns = group_turns(group_id)
    return " ".join(turn.var.sentence for turn in turns if turn.var.get("sentence"))


def writer_trial(node: SyncGroupNode) -> Optional["StoryTurn"]:
    """Return the writer's trial for the turn, or ``None`` if they never started it."""
    writer_id = node.definition["writer_id"]
    return next((t for t in node.all_trials if t.participant_id == writer_id), None)


class StoryTurn(Trial):
    sync_group_type = GROUP
    time_estimate = WRITE_SECONDS

    @property
    def is_writer(self) -> bool:
        return self.participant_id == self.definition["writer_id"]

    def show_trial(self, experiment, participant):
        barrier = GroupBarrier(
            id_=TURN_BARRIER,
            group_type=GROUP,
            waiting_message="Waiting for this turn to finish…",
            waiting_screen=waiting_for_writer,
            late_after=LATE_AFTER,
            late_action="leave_group",
        )
        if not self.is_writer:
            return barrier
        return join(
            self.write_page(participant), CodeBlock(self.save_sentence), barrier
        )

    def write_page(self, participant):
        story = story_text(self.sync_group_id)
        task = (
            f"Add the next sentence to the story: {story}"
            if story
            else "Write the first sentence of a story."
        )
        return ModularPage(
            "write",
            GroupPrompt(
                f"It's your turn, and you have {WRITE_SECONDS} seconds. {task}",
                participant=participant,
                group=self.sync_group,
                show_progress=False,
            ),
            TextControl(one_line=True),
            time_estimate=WRITE_SECONDS,
            time_limit=WRITE_SECONDS,
            validate=lambda answer: (
                None if answer.strip() else "Please write a sentence."
            ),
        )

    def save_sentence(self, participant):
        """Store the writer's sentence on the turn's node, if the turn is still theirs.

        A writer removed from the group, for example as late, stores nothing,
        because the others have finished the turn without them. The sentence
        is ``None`` if they ran out of time.
        """
        # A writer whose group dissolved while they wrote is the last one
        # left, so their sentence still ends the story.
        if in_group(participant) or self.sync_group_outcome == "group_dissolved":
            self.node.var.sentence = participant.answer

    def on_finalized(self):
        """Store ``None`` as the sentence if the turn ended without one.

        That happens when the writer was late or left.
        """
        super().on_finalized()
        if not self.node.var.has("sentence"):
            self.node.var.sentence = None

    def show_feedback(self, experiment, participant):
        if self.time_limit_reached and self.sync_group_outcome == "stayed":
            # Moves on by itself, so a writer who has stepped away still
            # reaches the next turn in time and isn't removed as late.
            return InfoPage(
                "You ran out of time, so nothing was added to the story this turn.",
                time_estimate=5,
                time_limit=5,
            )
        return None


def waiting_for_writer(participant, trial):
    """Show the story so far to the members waiting for the writer."""
    if trial.is_writer and trial.time_limit_reached:
        text = "You ran out of time. Waiting for the others."
    elif trial.is_writer:
        text = "Thank you. Waiting for the others."
    else:
        story = story_text(trial.sync_group_id) or "(Nothing yet.)"
        text = (
            "Another member of your group is writing the next sentence. "
            f"The story so far: {story}"
        )
    return GroupPrompt(
        text, participant=participant, group=trial.sync_group, show_progress=False
    )


# The ways a member can leave the group before the story's end.
ENDED_EARLY_TEXTS = {
    "late": "You were away for too long, so your group went on without you.",
    "group_dissolved": "Too few members of your group stayed, so the story ended early.",
    "removed": "You were removed from your group.",
}


def final_page(participant: Participant):
    group_id = participant.var.story_group_id
    if group_id is None:
        return InfoPage(
            "We couldn't find two other people to write with you. "
            "Thank you for waiting.",
            time_estimate=5,
        )
    turns = group_turns(group_id)
    finished = len(turns) == N_TURNS and all(t.var.has("sentence") for t in turns)
    if finished or in_group(participant):
        intro = "Here is the story your group wrote:"
    else:
        reason = participant.sync_group_removal_reason(GROUP)
        intro = f"{ENDED_EARLY_TEXTS[reason]} Here is the story so far:"
    story = story_text(group_id) or "(Nobody wrote a sentence.)"
    return ModularPage(
        "rate",
        f"{intro} {story} How much do you like the story?",
        PushButtonControl(choices=[1, 2, 3, 4, 5], arrange_vertically=False),
        time_estimate=10,
        save_answer="rating",
    )


def _turn_row(node: SyncGroupNode) -> dict:
    trial = writer_trial(node)
    return {
        "group_id": node.sync_group_id,
        "turn": node.sync_group_round,
        "node_id": node.id,
        "writer_id": node.definition["writer_id"],
        "writer_trial_id": trial.id if trial else None,
        # False while the turn is being played, or if it never finished.
        "finished": node.var.has("sentence"),
        # None if the writer ran out of time or left the group, or if the turn
        # isn't finished.
        "sentence": node.var.get("sentence"),
        # "stayed" if the writer was still in the group when the turn ended,
        # otherwise why they left; None if they never started the turn.
        "writer_outcome": trial.sync_group_outcome if trial else None,
    }


def _seated(bots: List[BotDriver]) -> List[BotDriver]:
    """Start the story for a group of bots and return them in seat order."""
    for bot in bots:
        bot.take_page()
    advance_past_wait_pages(bots, stop_at=TURN_BARRIER)
    (members,) = bots_by_sync_group(bots, GROUP)
    return sorted(
        members,
        key=lambda bot: bot.with_participant(
            lambda participant: group_seats(participant.sync_group)[participant.id]
        ),
    )


class Exp(psynet.experiment.Experiment):
    label = "Story chain demo"

    timeline = get_timeline()

    @classmethod
    def get_basic_data(cls, context=None, **kwargs):
        """Return one row per turn and one per player.

        Turn rows come from the turns' nodes and the writers' trials.
        """
        turns = SyncGroupNode.query.filter_by(module_id="story").order_by(
            SyncGroupNode.id
        )
        players = Participant.query.order_by(Participant.id)
        return {
            "turn": [_turn_row(node) for node in turns],
            "player": [
                {
                    "participant_id": p.id,
                    # None if no group formed for the player.
                    "group_id": p.var.get("story_group_id"),
                    # Why the player left their group, or found none; None if
                    # they stayed.
                    "removal_reason": p.sync_group_removal_reason(GROUP),
                    "rating": p.var.get("rating"),
                }
                for p in players
            ],
        }

    test_n_bots = GROUP_SIZE
    test_mode = "serial"

    def test_serial_run_bots(self, bots: List[BotDriver]):
        members = _seated(bots)
        for turn in range(N_TURNS):
            writer = members[turn % GROUP_SIZE]
            assert writer.current_page_label == "write", writer.current_page_text
            if turn == 4:
                writer.run_out_of_time()
                advance_past_wait_pages(members, stop_at=TURN_BARRIER)
                assert "nothing was added" in writer.current_page_text
                writer.take_page()
            else:
                writer.take_page(response=f"Sentence {turn}.")
            advance_past_wait_pages(members, stop_at=TURN_BARRIER)
            if turn == 0:
                waiting = members[2].current_page_text
                assert "The story so far: Sentence 0." in waiting, waiting

        story = "Sentence 0. Sentence 1. Sentence 2. Sentence 3. Sentence 5."
        for bot in members:
            assert bot.current_page_label == "rate", bot.current_page_text
            assert f"your group wrote: {story} How" in bot.current_page_text
        run_bots_to_completion(members)

        sentences = [f"Sentence {turn}." for turn in range(N_TURNS)]
        sentences[4] = None
        data = self.get_basic_data()
        assert [
            (row["writer_id"], row["sentence"], row["writer_outcome"])
            for row in data["turn"]
        ] == [
            (members[turn % GROUP_SIZE].id, sentences[turn], "stayed")
            for turn in range(N_TURNS)
        ]
        assert all(row["finished"] for row in data["turn"])
        assert [row["removal_reason"] for row in data["player"]] == [None] * 3
