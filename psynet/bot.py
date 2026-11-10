import json
import time
import uuid
import warnings
from datetime import timedelta
from functools import cached_property
from typing import List, Optional, Sequence, Union

from dallinger import db

from psynet.db import transaction

from .participant import Participant, ParticipantDriver, _status_is_waiting
from .utils import NoArgumentProvided, get_logger, log_time_taken, wait_until

logger = get_logger()


class Bot(Participant):
    """
    Simulated participant stored in the participant table, used for automated tests and simulations.

    Creating a bot waits for the experiment launch to finish, calls
    :meth:`~psynet.experiment.Experiment.initialize_bot`, and advances the bot to the first page.
    Hooks such as :meth:`~psynet.experiment.Experiment.test_check_bot` receive ``Bot`` objects.
    To drive a bot through pages over HTTP, use :class:`BotDriver`.
    """

    def __init__(
        self,
        recruiter_id=None,
        worker_id=None,
        assignment_id=None,
        unique_id=None,
        hit_id="",
        mode="debug",
    ):
        self.wait_until_experiment_launch_is_complete()

        if recruiter_id is None:
            recruiter_id = "generic"

        if worker_id is None:
            worker_id = str(uuid.uuid4())

        if assignment_id is None:
            assignment_id = str(uuid.uuid4())

        logger.info("Initializing bot with worker ID %s.", worker_id)

        super().__init__(
            self.experiment,
            recruiter_id=recruiter_id,
            worker_id=worker_id,
            assignment_id=assignment_id,
            hit_id=hit_id,
            mode=mode,
        )

        db.session.add(self)

        # Flushing ensures that we have a valid ID for the bot.
        db.session.flush()

        self._advance_to_first_page()

        db.session.commit()

    def get_driver(self):
        if self.id is None:
            db.session.flush()
        return BotDriver(id_=self.id)

    def _advance_to_first_page(self):
        assert self.elt_id == ["main", -1]
        self.experiment.timeline.advance_page(self.experiment, self)

    def initialize(self, experiment):
        # Participant.__init__ has already added the bot to the session;
        # flushing gives initialize_bot a valid bot.id.
        db.session.flush()
        self.experiment.initialize_bot(bot=self)
        super().initialize(experiment)

    def wait_until_experiment_launch_is_complete(self):
        from .experiment import is_experiment_launched

        def f():
            logger.info("Waiting for experiment launch to complete...")
            return is_experiment_launched()

        wait_until(
            f, max_wait=60, error_message="Experiment launch didn't finish in time"
        )

    @cached_property
    def experiment(self):
        from .experiment import get_experiment

        return get_experiment()

    @cached_property
    def timeline(self):
        return self.experiment.timeline

    def get_current_page(self):
        return self.experiment.get_current_page(self.experiment, self)

    @log_time_taken
    def take_experiment(self, *args, **kwargs):
        raise NotImplementedError(
            "Bot.take_experiment has now been removed. "
            "Please use Experiment.run_bot instead."
        )

    def take_page(self, *args, **kwargs):
        raise NotImplementedError(
            "The Bot class no longer provides a take_page method. "
            "Use BotDriver.take_page instead."
        )

    def submit_response(self, response=NoArgumentProvided):
        raise NotImplementedError(
            "The Bot class no longer provides a submit_response method. "
            "Use BotDriver.take_page instead."
        )

    def run_until(self, condition, render_pages=False):
        raise NotImplementedError(
            "The Bot class no longer provides a run_until method. "
            "Use BotDriver.run_until instead."
        )

    def run_to_completion(self, *args, **kwargs):
        raise NotImplementedError(
            "The Bot class no longer provides a run_to_completion method. "
            "Use BotDriver.run_to_completion instead."
        )


def _as_browser_json(x):
    """Return ``x`` with whole-number floats as ``int``, as the browser's ``JSON.stringify`` writes them."""
    if isinstance(x, float) and x.is_integer():
        return int(x)
    if isinstance(x, dict):
        return {key: _as_browser_json(value) for key, value in x.items()}
    if isinstance(x, (list, tuple)):
        return [_as_browser_json(value) for value in x]
    return x


class BotResponse:
    """
    Defines a bot's response to a given page.

    Parameters
    ----------
        raw_answer :
            The raw_answer returned from the page. Whole-number floats in it,
            such as ``3.0``, are submitted as ``int``, as the browser submits them.

        answer :
            The version of the answer that will be stored in the database,
            having been passed through .format_answer.

        metadata :
            A dictionary of metadata.

        blobs :
            A dictionary of blobs returned from the front-end.
    """

    def __init__(
        self,
        *,
        raw_answer=NoArgumentProvided,
        answer=NoArgumentProvided,
        metadata=NoArgumentProvided,
        blobs=NoArgumentProvided,
    ):
        if raw_answer != NoArgumentProvided and answer != NoArgumentProvided:
            raise ValueError(
                "raw_answer and answer cannot both be provided; you should probably just provide raw_answer."
            )

        if raw_answer == NoArgumentProvided and answer == NoArgumentProvided:
            raise ValueError("At least one of raw_answer and answer must be provided.")

        if blobs == NoArgumentProvided:
            blobs = {}

        if metadata == NoArgumentProvided:
            metadata = {}

        self.raw_answer = raw_answer
        self.answer = answer
        self.metadata = metadata
        self.blobs = blobs

    def __json__(self):
        data = {}

        if self.raw_answer != NoArgumentProvided:
            data["raw_answer"] = _as_browser_json(self.raw_answer)

        if self.answer != NoArgumentProvided:
            data["answer"] = self.answer

        data["metadata"] = self.metadata
        data["blobs"] = {key: value.__json__() for key, value in self.blobs.items()}

        return data

    def to_json(self):
        return json.dumps(self.__json__())


def advance_past_wait_pages(
    bots: List["BotDriver"],
    max_iterations: Optional[int] = None,
    timeout: Optional[float] = NoArgumentProvided,
    stop_at: Union[str, Sequence[str]] = (),
):
    """
    Repeatedly take wait pages and timeline holds for a group of bots until none are waiting.

    Useful in synchronous bot tests, where bots must pass barriers or wait pages together.
    After the first two passes over ``bots``, it polls every half second, as a
    browser would, so it also works when barriers release on a clock or a
    deadline, as in round-based games.

    Parameters
    ----------
    bots : list of BotDriver
        Bots to advance.
    max_iterations : int, optional
        Deprecated; use ``timeout``. If given, also stop after this many passes.
    timeout : float, optional
        Seconds to keep trying before giving up. ``None`` means no limit.
        Default: 10, or no limit if only ``max_iterations`` is given.
    stop_at : str or sequence of str
        ID or IDs of barriers to leave bots waiting at, for example a responder
        waiting for the proposer's offer while the test plays the proposer.
        Only matches bots on the waiting indicator of a barrier, grouper or
        regrouper with that ID that has no ``waiting_logic``, and only while
        that barrier hasn't released them: bots it has released, for example
        a turn-taking game's waiters once the writer submits, still catch up.
        Bots on a ``WaitPage`` or on ``waiting_logic`` pages are always
        advanced.

    Raises
    ------
    RuntimeError
        If some bots are still waiting after ``timeout`` seconds (or
        ``max_iterations`` passes).
    """
    if max_iterations is not None:
        warnings.warn(
            "advance_past_wait_pages(max_iterations=...) is deprecated; "
            "pass timeout=<seconds> instead.",
            FutureWarning,
            stacklevel=2,
        )
    if timeout is NoArgumentProvided:
        timeout = None if max_iterations is not None else 10.0
    stop_at = {stop_at} if isinstance(stop_at, str) else set(stop_at)
    deadline = None if timeout is None else time.monotonic() + timeout
    iteration = 0
    while True:
        iteration += 1
        waiting = []
        for bot in bots:
            # Last-arrival may have skipped this waiter while another bot was
            # submitting. Refresh before reading the cached page, and decide
            # from that status rather than the database: a release between the
            # two would leave take_page submitting the stale waiting page.
            bot.refresh_status()
            page = bot.status.get("page") or {}
            if page.get("barrier_id") in stop_at and not page.get("can_resume"):
                continue
            if _status_is_waiting(bot.status):
                waiting.append(bot)
                bot.take_page()
        if not waiting:
            return
        ids = [bot.id for bot in waiting]
        if max_iterations is not None and iteration >= max_iterations:
            raise RuntimeError(
                f"Bots {ids} are still waiting after {max_iterations} passes."
            )
        if deadline is not None and time.monotonic() > deadline:
            raise RuntimeError(f"Bots {ids} are still waiting after {timeout} s.")
        if iteration >= 2:
            time.sleep(0.5)


def regroup_now(bots: List["BotDriver"], regrouper, timeout: Optional[float] = 10.0):
    """Split the bots' pools at a :class:`~psynet.sync.Regrouper` now, then advance them past it.

    A bot test would otherwise wait out the regrouper's ``deadline`` or its
    next ``every`` tick, for example to test a round that starts without a
    member who is still reading their results. This moves two clocks back by
    one ``deadline`` (or ``every`` period): the bots' arrival times at the
    regrouper and the creation times of the groups their pools' earlier
    splits formed. The next check then splits the pools as the deadline or
    tick would. Group memberships and roles are untouched, so a player still
    in last round's group keeps their role. ``max_wait_time`` doesn't
    move: it counts from the bots' real arrivals.

    Parameters
    ----------
    bots : list of BotDriver
        Bots waiting at the regrouper, and any others to advance with them.
        Only these bots' arrivals move back, so with ``every`` pass every bot
        waiting in the pool.
    regrouper : Regrouper
        The regrouper from the timeline.
    timeout : float, optional
        Passed to :func:`advance_past_wait_pages`.

    Raises
    ------
    ValueError
        If the regrouper has neither ``deadline`` nor ``every``, or none of
        the bots is waiting at it.

    Examples
    --------
    ::

        for bot in bots[:3]:
            bot.take_page()  # The fourth player is still reading.
        regroup_now(bots[:3], pairing)
    """
    period = regrouper.deadline or regrouper.every
    if period is None:
        raise ValueError(
            f"Regrouper '{regrouper.id}' has no deadline or every, so it splits "
            "a pool as soon as it is complete; use advance_past_wait_pages."
        )
    with transaction():
        participants = [Participant.query.get(bot.id) for bot in bots]
        waiting = [p for p in participants if regrouper.id in p.active_barriers]
        if not waiting:
            raise ValueError(f"None of the bots is waiting at '{regrouper.id}'.")
        _backdate_arrivals(regrouper, waiting, period)
        pools = {}
        for participant in waiting:
            group = regrouper.waiting_pool_group(participant)
            pools[group and group.id] = group
        for within_group in pools.values():
            _backdate_splits(regrouper, within_group, period)
    advance_past_wait_pages(bots, timeout=timeout)


def _backdate_splits(regrouper, within_group, seconds):
    """Move every split ``regrouper`` made in this pool back by ``seconds``.

    All of them, not just the latest, because the pool's deadline counts from
    its most recent split.
    """
    from .sync import SyncGroup

    shift = timedelta(seconds=seconds)
    for group in SyncGroup.query.filter(*regrouper._pool_splits(within_group)):
        group.creation_time -= shift


def _backdate_arrivals(barrier, participants, seconds):
    """Move the participants' current arrivals at ``barrier`` back by ``seconds``."""
    for participant in participants:
        participant.active_barriers[barrier.id].arrival_time -= timedelta(
            seconds=seconds
        )


def run_bots_to_completion(bots: List["BotDriver"], timeout: Optional[float] = 60.0):
    """Take pages for bots in turn until all of them have finished the experiment.

    Use this instead of calling ``run_to_completion`` on each bot when the bots
    still wait for each other, for example players a
    :class:`~psynet.sync.Regrouper` keeps pairing: one bot run to completion on
    its own would wait at the next barrier for partners who never move. Each
    pass takes one page for every bot that is still working, answering with
    the page's bot response; a bot waiting at a barrier polls it, as a browser
    would.

    Parameters
    ----------
    bots : list of BotDriver
        Bots to run.
    timeout : float, optional
        Seconds to keep going before giving up (default 60). ``None`` means
        no limit.

    Raises
    ------
    RuntimeError
        If some bots are still working after ``timeout`` seconds.
    """
    deadline = None if timeout is None else time.monotonic() + timeout
    first_pass = True
    while True:
        for bot in bots:
            bot.refresh_status()
        working = [bot for bot in bots if bot.is_working]
        if not working:
            return
        if deadline is not None and time.monotonic() > deadline:
            ids = [bot.id for bot in working]
            raise RuntimeError(f"Bots {ids} are still working after {timeout} s.")
        if not first_pass and all(_status_is_waiting(bot.status) for bot in working):
            # Everyone waits, for example for a clock tick, so poll as a browser would.
            time.sleep(0.5)
        first_pass = False
        for bot in working:
            bot.take_page()


def bots_by_sync_group(bots: List["BotDriver"], group_type: str):
    """Return the bots grouped by their current group of ``group_type``.

    Groupers and regroupers can group bots in any order, so a test can use this
    to find who plays with whom. Bots not in a group of that type are left out.

    Parameters
    ----------
    bots : list of BotDriver
        Bots to sort into groups.
    group_type : str
        The group type, as in ``participant.in_sync_group(group_type)``.

    Returns
    -------
    list of list of BotDriver
        One list per group, ordered by group ID, each ordered by bot ID.

    Examples
    --------
    ::

        for first, second in bots_by_sync_group(bots, "pair"):
            first.take_page(response="circle")
            second.take_page(response="square")
    """
    groups = {}
    for bot in sorted(bots, key=lambda bot: bot.id):
        group_id = bot.with_participant(
            lambda participant: getattr(
                participant.active_sync_groups.get(group_type), "id", None
            )
        )
        if group_id is not None:
            groups.setdefault(group_id, []).append(bot)
    return [groups[group_id] for group_id in sorted(groups)]


class BotDriver(ParticipantDriver):
    """
    Driver class for automating bot participants in an experiment.

    The :class:`~psynet.bot.BotDriver` class is a convenience subclass of :class:`~psynet.participant.ParticipantDriver`
    specifically focused on creating and controlling bot participants.

    If no ``id_`` is specified, a new :class:`~psynet.bot.Bot` instance is created automatically.
    Otherwise, behaves like :class:`~psynet.participant.ParticipantDriver`.

    This class is primarily used for automated testing, simulation studies, and experiments where human participants
    interact with virtual (bot) participants. Like its parent, it interacts with the experiment server via HTTP requests,
    ensuring that the simulation closely matches real participant behavior.

    Parameters
    ----------
    id_ : int, optional
        The ID of the participant to automate
        (i.e. corresponding to the ``id`` column in the Participant table).
        If not provided, a new bot participant is created.
    """

    def __init__(
        self,
        id_: Optional[int] = None,
    ):
        from psynet.bot import Bot

        if id_ is None:
            with transaction():
                bot = Bot()
                db.session.add(bot)
                db.session.flush()
                id_ = bot.id

        super().__init__(id_)
