import json
import uuid
from functools import cached_property
from typing import List, Optional

from dallinger import db

from psynet.db import transaction

from .participant import Participant, ParticipantDriver
from .utils import NoArgumentProvided, get_logger, log_time_taken, wait_until

logger = get_logger()


class Bot(Participant):
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
        self.experiment.initialize_bot(bot=self)
        super().initialize(experiment)

    def wait_until_experiment_launch_is_complete(self):
        from .experiment import is_experiment_launched

        def f():
            logger.info("Waiting for experiment launch to complete....")
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


class BotResponse:
    """
    Defines a bot's response to a given page.

    Parameters
    ----------
        raw_answer :
            The raw_answer returned from the page.

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
            data["raw_answer"] = self.raw_answer

        if self.answer != NoArgumentProvided:
            data["answer"] = self.answer

        data["metadata"] = self.metadata
        data["blobs"] = {key: value.__json__() for key, value in self.blobs.items()}

        return data

    def to_json(self):
        return json.dumps(self.__json__())


def advance_past_wait_pages(bots: List["BotDriver"], max_iterations=10):
    from .page import WaitPage

    iteration = 0
    while True:
        iteration += 1
        any_waiting = False
        for bot in bots:
            current_page = bot.get_current_page()
            if isinstance(current_page, WaitPage):
                any_waiting = True
                bot.take_page()
        if not any_waiting:
            break
        if iteration >= max_iterations:
            raise RuntimeError("Not all bots finished waiting in time.")


class BotDriver(ParticipantDriver):
    """
    Driver class for automating bot participants in an experiment.

    The :class:`~psynet.participant.BotDriver` class is a convenience subclass of :class:`~psynet.participant.ParticipantDriver`
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
