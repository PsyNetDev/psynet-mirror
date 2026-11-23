"""Groups of three take turns writing a story, then rate it.

A :class:`~psynet.sync.SimpleGrouper` forms a group of three, which then
plays ``N_TURNS`` turns in a fixed loop. Each turn is one cued round:
``StoryTurn.cue(..., round=turn)`` gives every member a trial in the
group's round (a :class:`~psynet.sync.SyncGroupRound`). One member writes a sentence while the others see
the story so far and wait at the turn's
:class:`~psynet.sync.GroupBarrier`.

The turn's definition stores the writer, chosen by seat with
:attr:`~psynet.sync.SyncGroup.seats`. The writer stores their sentence in
``group_round.var.sentence`` as soon as they submit it, and a turn that ends without
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
    make_late_now,
    run_bots_to_completion,
)
from psynet.group_prompt import GroupPrompt
from psynet.modular_page import ModularPage, PushButtonControl, TextControl
from psynet.page import InfoPage
from psynet.participant import Participant
from psynet.sync import (
    GroupBarrier,
    SimpleGrouper,
    SyncGroup,
    SyncGroupRound,
)
from psynet.timeline import (
    CodeBlock,
    Module,
    PageMaker,
    Timeline,
    for_loop,
    join,
)
from psynet.trial.main import Trial

GROUP = "story"
GROUP_SIZE = 3
N_ROUNDS = 2
N_TURNS = N_ROUNDS * GROUP_SIZE
WRITE_SECONDS = 20
# How long a member may take to finish a turn, counted from its start or, for
# a writer who has opened the timed page, from 10 seconds after its time
# limit, so that a sentence sent at the deadline can arrive. A writer who
# closes their page is removed about 45 seconds into the turn.
LATE_AFTER = 15
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
            # Two members carry on the story; a member left alone is failed,
            # as is one for whom no group forms (max_wait_action defaults to
            # "fail").
            below_quorum="fail",
            max_wait_time=GROUPER_WAIT,
            waiting_message="Waiting for your group of three to form…",
        ),
        Module(
            "story",
            for_loop(
                label="turns",
                iterate_over=range(N_TURNS),
                logic=lambda turn: StoryTurn.cue(turn_definition, round=turn),
                time_estimate_per_iteration=StoryTurn.time_estimate,
                # Only the experimenter's removal on the dashboard leaves a
                # member without a group and still playing.
                stop_if=lambda participant: not in_group(participant),
            ),
        ),
        PageMaker(final_page, time_estimate=10),
    )


def in_group(participant: Participant) -> bool:
    return participant.in_sync_group(GROUP)


def choose_writer(group, turn: int) -> int:
    """Return the ID of the member in seat ``turn % GROUP_SIZE``.

    If that member has left, return the member in the next seat still in the
    group.
    """
    seats = group.seats
    by_seat = sorted(seats, key=seats.get)
    start = turn % GROUP_SIZE
    present = {participant.id for participant in group.active_participants}
    return next(pid for pid in by_seat[start:] + by_seat[:start] if pid in present)


def turn_definition(group, round: int) -> dict:
    """Called at the turn's first cue only, so the writer is chosen once and stored."""
    return {"writer_id": choose_writer(group, round)}


def group_turns(group_id: int) -> List[SyncGroupRound]:
    """Return the rounds of the turns the group has started, in order.

    This works even after the group has ended.
    """
    return db.session.get(SyncGroup, group_id).rounds("story")


def story_text(group_id: int) -> str:
    """Return the sentences the group's turns have saved so far, joined into a story.

    A turn still being played has no ``sentence`` yet.
    """
    turns = group_turns(group_id)
    return " ".join(turn.var.sentence for turn in turns if turn.var.get("sentence"))


def writer_trial(turn: SyncGroupRound) -> Optional["StoryTurn"]:
    """Return the writer's trial for the turn, or ``None`` if they never started it."""
    writer_id = turn.definition["writer_id"]
    return next((t for t in turn.trials if t.participant_id == writer_id), None)


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
            late_action="fail",
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
        """Store the writer's sentence on the turn's round, if the turn is still theirs.

        A writer the experimenter removed from the group stores nothing,
        because the others have finished the turn without them. The sentence
        is ``None`` if they ran out of time.
        """
        if in_group(participant):
            self.group_round.var.sentence = participant.answer

    def on_finalized(self):
        """Store ``None`` as the sentence if the turn ended without one.

        That happens when the writer was failed, for example for being late,
        or was removed from the group.
        """
        super().on_finalized()
        if not self.group_round.var.has("sentence"):
            self.group_round.var.sentence = None

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


def final_page(participant: Participant):
    group_id = participant.latest_sync_group(GROUP).id
    turns = group_turns(group_id)
    finished = len(turns) == N_TURNS and all(t.var.has("sentence") for t in turns)
    if finished or in_group(participant):
        intro = "Here is the story your group wrote:"
    else:
        # The experimenter removed them on the dashboard; members who leave
        # otherwise are failed and don't see this page.
        intro = "You were removed from your group. Here is the story so far:"
    story = story_text(group_id) or "(Nobody wrote a sentence.)"
    return ModularPage(
        "rate",
        f"{intro} {story} How much do you like the story?",
        PushButtonControl(choices=[1, 2, 3, 4, 5], arrange_vertically=False),
        time_estimate=10,
        save_answer="rating",
    )


def _turn_row(turn: SyncGroupRound) -> dict:
    trial = writer_trial(turn)
    return {
        "group_id": turn.sync_group_id,
        "turn": turn.number,
        "round_id": turn.id,
        "writer_id": turn.definition["writer_id"],
        "writer_trial_id": trial.id if trial else None,
        # False while the turn is being played, or if it never finished.
        "finished": turn.var.has("sentence"),
        # None if the writer ran out of time or left the group, or if the turn
        # isn't finished.
        "sentence": turn.var.get("sentence"),
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
            lambda participant: participant.sync_group.seats[participant.id]
        ),
    )


class Exp(psynet.experiment.Experiment):
    label = "Story chain demo"

    timeline = get_timeline()

    @classmethod
    def get_basic_data(cls, context=None, **kwargs):
        """Return one row per turn and one per player.

        Turn rows come from the turns' rounds and the writers' trials.
        """
        turns = SyncGroupRound.query.filter_by(module_id="story").order_by(
            SyncGroupRound.id
        )
        players = Participant.query.order_by(Participant.id)
        return {
            "turn": [_turn_row(turn) for turn in turns],
            "player": [
                {
                    "participant_id": p.id,
                    # None if no group formed for the player, who was then
                    # failed.
                    "group_id": getattr(p.latest_sync_group(GROUP), "id", None),
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
        for turn in range(N_TURNS - 1):
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

        # The last writer goes quiet and is failed; the other two rate the story.
        quiet, playing = members[2], members[:2]
        quiet.allow_failure()
        make_late_now(playing, TURN_BARRIER)  # instead of waiting LATE_AFTER
        assert quiet.failed

        story = "Sentence 0. Sentence 1. Sentence 2. Sentence 3."
        for bot in playing:
            assert bot.current_page_label == "rate", bot.current_page_text
            assert f"your group wrote: {story} How" in bot.current_page_text
        run_bots_to_completion(playing)

        sentences = [f"Sentence {turn}." for turn in range(N_TURNS)]
        sentences[4] = sentences[5] = None
        outcomes = ["stayed"] * (N_TURNS - 1) + ["late"]
        data = self.get_basic_data()
        assert [
            (row["writer_id"], row["sentence"], row["writer_outcome"])
            for row in data["turn"]
        ] == [
            (members[turn % GROUP_SIZE].id, sentences[turn], outcomes[turn])
            for turn in range(N_TURNS)
        ]
        assert all(row["finished"] for row in data["turn"])
        assert {
            row["participant_id"]: row["removal_reason"] for row in data["player"]
        } == {bot.id: "late" if bot is quiet else None for bot in members}
