"""Groups of three take turns writing a story, then rate it.

A :class:`~psynet.sync.SimpleGrouper` forms a group of three, which then
plays ``N_TURNS`` turns in a fixed loop. Each turn is one cued round:
``StoryTurn.cue(..., round=turn)`` gives every member a trial on the
round's shared node. One member writes a sentence while the others see
the story so far and wait at the turn's
:class:`~psynet.sync.GroupBarrier`.

Everything the story needs is stored rather than worked out later:

- The round's first cue chooses the writer by seat (see
  :func:`~psynet.sync.group_seats`), cycling through the seats in the order
  members joined, and stores their ID as ``writer_id`` in the node's
  definition. If the member in that seat has left, the member in the next
  seat writes instead, so turns become uneven (for example A, C, C).
- The writer stores their sentence in ``node.var.sentence`` as soon as they
  submit it, before the turn's barrier, or ``None`` if they ran out of time.
  A writer the barrier has removed as late stores nothing. When a member's
  trial finishes and the turn still has no sentence, because the writer was
  late or left, it stores ``None``. So every finished turn has a
  ``sentence``, whether the barrier released or the group dissolved. Why a
  sentence is ``None`` is the writer trial's ``sync_group_outcome``:
  ``"stayed"`` if they ran out of time, or why they left the group.
- The last page reads the story from the nodes of the group whose ID each
  member stored when the group formed, so it still works after the group
  has ended.

Dropouts:

- A writer who runs out of time adds nothing that turn and stays in the group.
- A member who returns the study, or takes more than ``LATE_AFTER`` seconds to
  finish a turn, leaves the group and plays no more turns.
- The group continues while two members remain. When only one is left, the
  group dissolves and that member goes on to the story so far.
- Someone who finds no group within ``GROUPER_WAIT`` seconds is told so and
  finishes.
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
from psynet.sync import GroupBarrier, SimpleGrouper, group_seats
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
    """Store the participant's group ID, or ``None``, for the last page and the export."""
    group = participant.active_sync_groups.get(GROUP)
    participant.var.story_group_id = group.id if group else None


def choose_writer(group, turn: int) -> int:
    """Return the ID of the member in seat ``turn % GROUP_SIZE``, or in the next seat still in the group."""
    seats = group_seats(group)
    by_seat = sorted(seats, key=seats.get)
    start = turn % GROUP_SIZE
    present = {participant.id for participant in group.active_participants}
    return next(pid for pid in by_seat[start:] + by_seat[:start] if pid in present)


def turn_definition(group, round: int) -> dict:
    """Called at the turn's first cue only, so the writer is chosen once and stored."""
    return {"writer_id": choose_writer(group, round)}


def group_turns(group_id: int) -> List[SyncGroupNode]:
    """Return the nodes of the turns the group has started, in order."""
    return (
        SyncGroupNode.query.filter_by(module_id="story", sync_group_id=group_id)
        .order_by(SyncGroupNode.id)
        .all()
    )


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
        )

    def save_sentence(self, participant):
        """Store the writer's sentence on the turn's node, unless the barrier has removed them as late.

        The sentence is ``None`` if they ran out of time. A writer whose
        group dissolved while they wrote still finishes the story. Locking
        the trial makes a submit that races the late removal wait for it, so
        a removed writer's sentence never lands.
        """
        db.session.refresh(self, ["sync_group_outcome"], with_for_update=True)
        if self.sync_group_outcome in (None, "group_dissolved"):
            self.node.var.sentence = participant.answer

    def on_finalized(self):
        """Store ``None`` as the sentence if the turn ended without one, because the writer was late or left."""
        super().on_finalized()
        if not self.node.var.has("sentence"):
            self.node.var.sentence = None

    def show_feedback(self, experiment, participant):
        ran_out_of_time = self.is_writer and self.answer is None
        if ran_out_of_time and self.sync_group_outcome == "stayed":
            return InfoPage(
                "You ran out of time, so nothing was added to the story this turn.",
                time_estimate=5,
            )
        return None


def waiting_for_writer(participant, trial):
    """Show the story so far to the members waiting for the writer."""
    if trial.is_writer:
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


NO_GROUP_TEXT = (
    "We couldn't find a group for you this time, so there is no story to "
    "write. Thank you for waiting."
)
FINISHED_INTRO = "Here is the story your group wrote:"
# By the reason the participant left their group, while the story is unfinished.
EARLY_END_INTROS = {
    "late": "You were away for too long, so your group went on without you. "
    "Here is the story so far:",
    "group_dissolved": "The others in your group left, so the story ended "
    "early. Here it is:",
}


def final_page(participant: Participant):
    group_id = participant.var.story_group_id
    if group_id is None:
        return InfoPage(NO_GROUP_TEXT, time_estimate=5)
    turns = group_turns(group_id)
    finished = len(turns) == N_TURNS and all(t.var.has("sentence") for t in turns)
    reason = participant.sync_group_removal_reason(GROUP)
    intro = FINISHED_INTRO if finished else EARLY_END_INTROS.get(reason, FINISHED_INTRO)
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
        # None if the writer ran out of time or left the group.
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
        """Return one row per turn, from the turns' nodes and writers' trials, and one per player."""
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

    test_n_bots = 10
    test_mode = "serial"

    def test_serial_run_bots(self, bots: List[BotDriver]):
        full_group, lost_group, short_group = bots[:3], bots[3:6], bots[6:9]
        (loner,) = bots[9:]
        self._test_full_story(full_group)
        self._test_group_dissolving_while_writing(lost_group)
        self._test_shrinking_group(short_group, loner)

        advance_past_wait_pages([loner], timeout=GROUPER_WAIT + 10)
        assert loner.current_page_text == NO_GROUP_TEXT, loner.current_page_text
        run_bots_to_completion([bot for bot in bots if not bot.failed])

        assert self._removal_reasons([loner]) == ["no_group_formed"]
        assert self._player(loner)["group_id"] is None

    def _player(self, bot: BotDriver) -> dict:
        """Return the bot's row of the ``player`` table."""
        return next(
            row
            for row in self.get_basic_data()["player"]
            if row["participant_id"] == bot.id
        )

    def _removal_reasons(self, bots: List[BotDriver]) -> list:
        return [self._player(bot)["removal_reason"] for bot in bots]

    def _turns(self, bot: BotDriver):
        """Return the writer, sentence and writer outcome of each turn of the bot's group."""
        group_id = bot.with_participant(lambda p: p.var.story_group_id)
        return [
            (row["writer_id"], row["sentence"], row["writer_outcome"])
            for row in self.get_basic_data()["turn"]
            if row["group_id"] == group_id
        ]

    def _test_full_story(self, bots: List[BotDriver]):
        members = _seated(bots)
        for turn in range(N_TURNS):
            writer = members[turn % GROUP_SIZE]
            assert writer.current_page_label == "write", writer.current_page_text
            if turn == 4:
                writer.run_out_of_time()
                advance_past_wait_pages(members, stop_at=TURN_BARRIER)
                assert "ran out of time" in writer.current_page_text
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

        sentences = [f"Sentence {turn}." for turn in range(N_TURNS)]
        sentences[4] = None
        assert self._turns(members[0]) == [
            (members[turn % GROUP_SIZE].id, sentences[turn], "stayed")
            for turn in range(N_TURNS)
        ]

    def _test_group_dissolving_while_writing(self, bots: List[BotDriver]):
        # Both others wait at the barrier and then return the study while the
        # first writes, so the group dissolves but the sentence still counts.
        first, second, third = _seated(bots)
        second.drop_out()
        third.drop_out()
        first.take_page(response="Once upon a time.")
        advance_past_wait_pages([first])
        text = first.current_page_text
        assert "the story ended early. Here it is: Once upon a time. How" in text
        assert self._turns(first) == [
            (first.id, "Once upon a time.", "group_dissolved")
        ]
        assert self._removal_reasons([first, second, third]) == [
            "group_dissolved",
            "left_experiment",
            "left_experiment",
        ]

    def _test_shrinking_group(self, bots: List[BotDriver], loner: BotDriver):
        first, second, third = _seated(bots)
        # Meanwhile a participant arrives who will find no group.
        loner.take_page()
        first.take_page(response="Once upon a time.")
        advance_past_wait_pages(bots, stop_at=TURN_BARRIER)

        # The second writer goes silent, so the barrier takes them out and
        # the other two go on without them.
        assert second.current_page_label == "write"
        advance_past_wait_pages([third], timeout=LATE_AFTER + 20)
        advance_past_wait_pages([first, third], stop_at=TURN_BARRIER)
        assert (
            second.current_notice == "Your group went on without you. Please continue."
        )
        second.take_page(response="Too late.")
        advance_past_wait_pages([second])
        text = second.current_page_text
        assert f"{EARLY_END_INTROS['late']} Once upon a time. How" in text, text

        # The third writes their own turn and, after the first's, the
        # second's. The third returns the study while writing the last turn,
        # so the group dissolves with the first waiting. The story still has
        # all its turns, so the first isn't told it ended early.
        third.take_page(response="A dragon appeared.")
        advance_past_wait_pages([first, third], stop_at=TURN_BARRIER)
        first.take_page(response="It was hungry.")
        advance_past_wait_pages([first, third], stop_at=TURN_BARRIER)
        assert third.current_page_label == "write", third.current_page_text
        third.take_page(response="It ate the moon.")
        advance_past_wait_pages([first, third], stop_at=TURN_BARRIER)
        assert third.current_page_label == "write", third.current_page_text
        third.drop_out()
        advance_past_wait_pages([first])
        story = "Once upon a time. A dragon appeared. It was hungry. It ate the moon."
        assert f"{FINISHED_INTRO} {story} How" in first.current_page_text

        assert self._turns(first) == [
            (first.id, "Once upon a time.", "stayed"),
            (second.id, None, "late"),
            (third.id, "A dragon appeared.", "stayed"),
            (first.id, "It was hungry.", "stayed"),
            (third.id, "It ate the moon.", "stayed"),
            (third.id, None, "left_experiment"),
        ]
        assert self._removal_reasons([first, second, third]) == [
            "group_dissolved",
            "late",
            "left_experiment",
        ]
