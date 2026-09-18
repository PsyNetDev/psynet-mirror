# pylint: disable=unused-argument

import datetime
import random
import sys
import warnings
from dataclasses import dataclass
from math import isnan
from typing import Any, List, Literal, Optional, Union

import dallinger.experiment
import dallinger.models
import dallinger.nodes
from dallinger import db
from dallinger.models import Info, Network
from dominate import tags
from markupsafe import Markup
from sqlalchemy import (
    Boolean,
    Column,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    and_,
    func,
    inspect,
    not_,
    or_,
    select,
    text,
)
from sqlalchemy.exc import NoResultFound
from sqlalchemy.ext.associationproxy import association_proxy
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import column_property, declared_attr, deferred, relationship
from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy.orm.collections import attribute_mapped_collection

from psynet import field

from ..asset import Asset, AssetNetwork, AssetNode, AssetTrial
from ..data import SQLMixinDallinger
from ..error import (  # noqa  # Importing the error module is important to ensure sqlalchemy is happy
    ErrorRecord,
)
from ..field import PythonDict, PythonObject, VarStore
from ..page import InfoPage, UnsuccessfulEndPage, WaitPage, wait_while
from ..participant import Participant
from ..process import WorkerAsyncProcess
from ..sync import GroupBarrier, SyncGroup
from ..timeline import (
    CodeBlock,
    DatabaseCheck,
    Module,
    ModuleState,
    PageMaker,
    ParticipantFailRoutine,
    PreDeployRoutine,
    RecruitmentCriterion,
    RegisterTrialMaker,
    conditional,
    join,
    switch,
    while_loop,
)
from ..utils import (
    NoArgumentProvided,
    call_function,
    call_function_with_context,
    corr,
    get_logger,
    is_method_overridden,
    log_time_taken,
    psynet_source_prefixes,
)

logger = get_logger()


def _warn_ignored_fail_trials_on_premature_exit(trial_maker_id):
    message = (
        f"fail_trials_on_premature_exit is ignored in trial maker {trial_maker_id!r}. "
        "Premature exit no longer fails completed trials; incomplete "
        "trials are always failed when the participant exits or fails."
    )
    if sys.version_info >= (3, 12):
        warnings.warn(
            message,
            DeprecationWarning,
            skip_file_prefixes=psynet_source_prefixes(),
        )
        return
    warnings.warn(message, DeprecationWarning, stacklevel=2)


def with_trial_maker_namespace(trial_maker_id: str, x: Optional[str] = None):
    if x is None:
        return trial_maker_id
    return f"{trial_maker_id}__{x}"


# Patch the relationship from Dallinger
Info.origin = relationship(
    "dallinger.models.Node", foreign_keys=[Info.origin_id], post_update=True
)  # type: TrialNode


class AssetParentMixin:
    # TODO: Consider removing add_asset(s) and instead implement a custom ``[]`` operator.
    def add_assets(self, assets: dict[str, Asset]):
        for local_key, asset in assets.items():
            self.add_asset(local_key, asset)

    def add_asset(self, local_key: str, asset: Asset):
        assert isinstance(asset, Asset)
        asset.update_metadata(self, local_key, definition=self.definition)
        if self.id is None:
            # Ensure the trial has an ID before asset keys/depositing.
            db.session.flush([self])
        if asset.deposited:
            asset.ensure_keys_and_paths()
        else:
            # deposit() will call ensure_keys_and_paths() internally.
            asset.deposit()

        self.assets[local_key] = asset


class Trial(SQLMixinDallinger, Info, AssetParentMixin):
    """
    Represents a trial in the experiment.
    The user is expected to override the following methods:

    * :meth:`~psynet.trial.main.Trial.make_definition`,
      responsible for deciding on the content of the trial.
    * :meth:`~psynet.trial.main.Trial.show_trial`,
      determines how the trial is turned into a webpage for presentation to the participant.
    * :meth:`~psynet.trial.main.Trial.show_feedback`,
      defines an optional feedback page to be displayed after the trial.

    The user must also override the ``time_estimate`` class attribute,
    providing the estimated duration of the trial in seconds.
    This is used for predicting the participant's performance reward
    and for constructing the progress bar.

    The user may also wish to override the
    :meth:`~psynet.trial.main.Trial.async_post_trial` method
    if they wish to implement asynchronous trial processing.

    They may also override the
    :meth:`~psynet.trial.main.Trial.score_answer` method
    if they wish to implement trial-level scoring;
    for scoring methods that work by analyzing multiple trials at the same time
    (e.g., test-retest correlations), see the trial maker method
    :meth:`~psynet.trial.main.TrialMaker.performance_check`.

    This class subclasses the :class:`~dallinger.models.Info` class from Dallinger,
    hence can be found in the ``Info`` table in the database.
    It inherits this class's methods, which the user is welcome to use
    if they seem relevant.

    Instances can be retrieved using *SQLAlchemy*; for example, the
    following command retrieves the ``Trial`` object with an ID of 1:

    ::

        Trial.query.filter_by(id=1).one()

    Parameters
    ----------

    experiment:
        An instantiation of :class:`psynet.experiment.Experiment`,
        corresponding to the current experiment.

    node:
        An object of class :class:`dallinger.models.Node` to which the
        :class:`~dallinger.models.Trial` object should be attached.
        Complex experiments are often organised around networks of nodes,
        but in the simplest case one could just make one :class:`~dallinger.models.Network`
        for each type of trial and one :class:`~dallinger.models.Node` for each participant,
        and then assign the :class:`~dallinger.models.Trial`
        to this :class:`~dallinger.models.Node`.
        Ask us if you want to use this simple use case - it would be worth adding
        it as a default to this implementation, but we haven't done that yet,
        because most people are using more complex designs.

    participant:
        An instantiation of :class:`psynet.participant.Participant`,
        corresponding to the current participant.

    propagate_failure : bool
        Whether failure of a trial should be propagated to other
        parts of the experiment depending on that trial
        (for example, subsequent parts of a transmission chain).

    Attributes
    ----------

    time_estimate : numeric
        The estimated duration of the trial (including any feedback), in seconds.
        This should generally correspond to the (sum of the) ``time_estimate`` parameters in
        the page(s) generated by ``show_trial``, plus the ``time_estimate`` parameter in
        the page generated by ``show_feedback`` (if defined).
        This is used for predicting the participant's performance reward
        and for constructing the progress bar.

    participant_id : int
        The ID of the associated participant.
        The user should not typically change this directly.
        Stored in ``property1`` in the database.

    position : int
        Zero-based position within this participant's current trial maker.
        Stored when the trial is created.

    node
        The :class:`dallinger.models.Node` to which the :class:`~dallinger.models.Trial`
        belongs.

    finalized : bool
        Whether the trial has been finalized. This is a stronger condition than ``complete``;
        in particular, a trial is only marked as finalized once its async processes
        have completed (if it has any).
        One day we might extend this to include arbitrary conditions,
        for example waiting for another user to evaluate that trial, or similar.

    answer : Object
        The response returned by the participant. This is serialised
        to JSON, so it shouldn't be too big.
        The user should not typically change this directly.
        Stored in ``details`` in the database.

    parent_trial_id : int
        If the trial is a repeat trial, this attribute corresponds to the ID
        of the trial from which that repeat trial was cloned.

    earliest_async_process_start_time : Optional[datetime]
        Time at which the earliest pending async process was called.

    propagate_failure : bool
        Whether failure of a trial should be propagated to other
        parts of the experiment depending on that trial
        (for example, subsequent parts of a transmission chain).

    var : :class:`~psynet.field.VarStore`
        A repository for arbitrary variables; see :class:`~psynet.field.VarStore` for details.

    definition : Object
        An arbitrary Python object that somehow defines the content of
        a trial. Often this will be a dictionary comprising a few
        named parameters.
        The user should not typically change this directly,
        as it is instead determined by
        :meth:`~psynet.trial.main.Trial.make_definition`.

    run_async_post_trial : bool
        Set this to ``False`` if you want to disable :meth:`~psynet.trial.main.Trial.async_post_trial`.
        This is only included for back-compatibility.

    wait_for_feedback : bool
        Set this class attribute to ``False`` if you don't want to wait for asynchronous processes
        to complete before giving feedback. The default is to wait.

    accumulate_answers : bool
        Set this class attribute to ``True`` if the trial contains multiple pages and you want
        the answers to all of these pages to be stored as a dict in ``participant.answer``.
        Otherwise, the default behaviour is to only store the answer from the final page.

    time_credit_before_trial: float
        Reports the amount of time credit that the participant had before they started the trial (in seconds).

    time_credit_after_trial: float
        Reports the amount of time credit that the participant had after they finished the trial (in seconds).

    time_credit_from_trial: float
        Reports the amount of time credit that was allocated to the participant on the basis of this trial (in seconds).
        This should be equal to ``time_credit_after_trial - time_credit_before_trial``.

    progress_before_trial: float
        Reports the progress that the participant had before they started the trial.
        Mainly useful for debugging.

    progress_after_trial: float
        Reports the progress that the participant had after they finished the trial.
        Mainly useful for debugging.

    check_time_credit_received : bool
        If ``True`` (default), PsyNet will check at the end of the trial whether the participant received
        the expected amount of time credit. If the received amount is inconsistent with the amount
        specified by ``time_estimate``, then a warning message will be delivered,
        suggesting a revised value for ``time_estimate``.

    response_id : int
        ID of the associated :class:`~psynet.timeline.Response` object.
        Equals ``None`` if no such object has been created yet.

    response :
        The associated :class:`~psynet.timeline.Response` object,
        which records in detail the response received from the participant's web browser.
        Equals ``None`` if no such object has been created yet.
    """

    # pylint: disable=unused-argument
    __extra_vars__ = SQLMixinDallinger.__extra_vars__.copy()

    node_id = Column(Integer, ForeignKey("node.id"), index=True)
    participant_id = Column(Integer, ForeignKey("participant.id"), index=True)
    # module_id = Column(String)
    module_id = association_proxy("module_state", "module_id")
    module_state_id = Column(Integer, ForeignKey("module_state.id"), index=True)
    module_state = relationship("ModuleState", foreign_keys=[module_state_id])
    trial_maker_id = Column(String, index=True)
    position = Column(
        Integer,
        nullable=True,
        doc=(
            "Zero-based creation position among all trials from this trial maker "
            "for the participant."
        ),
    )
    definition = Column(PythonObject)

    @declared_attr
    def complete(cls):
        # Dallinger v9.6.0 adds an Info.complete column.
        # The following code inherits that column if it exists.
        doc = (
            "Whether the trial has been completed (i.e. received a response from the "
            "participant). The user should not typically change this directly."
        )
        column = cls.__table__.c.get("complete")
        if column is None:
            column = Column(Boolean, doc=doc)
        else:
            # Ensure a consistent docstring even if Dallinger already defines one.
            column.doc = doc
        return column

    finalized = Column(Boolean)
    is_repeat_trial = Column(Boolean)
    score = Column(Float)
    performance_reward = Column(Float)
    parent_trial_id = Column(Integer, ForeignKey("info.id"), index=True)
    answer = Column(PythonObject)
    propagate_failure = Column(Boolean)
    response_id = Column(Integer, ForeignKey("response.id"), index=True)
    repeat_trial_index = Column(Integer)
    n_repeat_trials = Column(Integer)
    time_taken = Column(Float)
    _initial_assets = deferred(Column(PythonDict))

    time_credit_before_trial = Column(Float)
    time_credit_after_trial = Column(Float)
    time_credit_from_trial = Column(Float)

    progress_before_trial = Column(Float)
    progress_after_trial = Column(Float)

    async_post_trial_required = Column(Boolean, default=False, index=True)
    async_post_trial_requested = Column(Boolean, default=False, index=True)
    async_post_trial_complete = Column(Boolean, default=False, index=True)
    async_post_trial_failed = Column(Boolean, default=False, index=True)

    @hybrid_property
    def async_post_trial_pending(self):
        """Whether async post-trial work is still in flight.

        Used for feedback / wait loops. This is *not* the finalize gate:
        finalize requires async success when requested (see
        :attr:`async_post_trial_blocks_finalization`), so a failed async
        does not count as pending here but still blocks finalization.
        """
        return self.async_post_trial_requested and not (
            self.async_post_trial_complete or self.async_post_trial_failed
        )

    @async_post_trial_pending.expression
    def async_post_trial_pending(cls):
        return and_(
            cls.async_post_trial_requested,
            not_(
                or_(
                    cls.async_post_trial_complete,
                    cls.async_post_trial_failed,
                )
            ),
        )

    @hybrid_property
    def async_post_trial_blocks_finalization(self):
        """Whether async post-trial prevents finalization.

        Stricter than :attr:`async_post_trial_pending`: if async was
        requested, it must have *succeeded* (``async_post_trial_complete``)
        before the trial may finalize. Failed async therefore blocks
        finalization even though it is no longer "pending".
        """
        return self.async_post_trial_requested and not self.async_post_trial_complete

    @async_post_trial_blocks_finalization.expression
    def async_post_trial_blocks_finalization(cls):
        return and_(
            cls.async_post_trial_requested.is_(True),
            cls.async_post_trial_complete.is_(False),
        )

    node = relationship(
        "TrialNode",
        foreign_keys=[node_id],
        back_populates="all_trials",
        post_update=True,
    )
    participant = relationship(
        "psynet.participant.Participant",
        foreign_keys=[participant_id],
        backref="all_trials",
        post_update=True,
    )
    parent_trial = relationship(
        "psynet.trial.main.Trial", foreign_keys=[parent_trial_id], uselist=False
    )
    response = relationship("psynet.timeline.Response")

    async_processes = relationship("AsyncProcess")

    asset_links = relationship(
        "AssetTrial",
        collection_class=attribute_mapped_collection("local_key"),
        cascade="all, delete-orphan",
    )

    assets = association_proxy(
        "asset_links", "asset", creator=lambda k, v: AssetTrial(local_key=k, asset=v)
    )

    errors = relationship("ErrorRecord")

    time_estimate = None
    check_time_credit_received = True

    wait_for_feedback = True  # determines whether feedback waits for async_post_trial
    accumulate_answers = False

    @property
    def var(self):
        return VarStore(self)

    @classmethod
    def get_for_participant(cls, participant_id: int, trial_maker_id: int = None):
        """
        Returns all trials for a given participant.
        """
        query = (
            db.session.query(cls)
            .join(TrialNetwork)
            .filter(Trial.participant_id == participant_id)
        )
        if trial_maker_id is not None:
            query = query.filter(TrialNetwork.trial_maker_id == trial_maker_id)
        return query.order_by(Trial.id).all()

    @property
    def visualization_html(self):
        experiment = dallinger.experiment.load()
        participant = self.participant
        page = self.show_trial(experiment=experiment, participant=participant)
        return page.visualize(trial=self)

    def fail(self, reason=None):
        if not self.failed:
            logger.info(f"Failing trial (id: {self.id}, reason: {reason})")
            super().fail(reason=reason)

    @property
    def ready_for_feedback(self):
        """
        Determines whether a trial is ready to give feedback to the participant.
        """
        msg = f"Participant {self.participant.id}: Checking if the trial is ready for feedback... "

        if not self.complete:
            msg += "no, because the trial is not complete."
            outcome = False

        elif not self.wait_for_feedback:
            msg += "yes, because we don't need to wait for feedback."
            outcome = True

        elif self.asset_deposit_pending:
            msg += "no, because the trial is awaiting an asset deposit."
            outcome = False

        elif self.async_post_trial_pending:
            msg += "no, because the trial is awaiting async_post_trial."
            outcome = False

        else:
            msg += "yes, all conditions are satisfied."
            outcome = True

        logger.info(msg)
        return outcome

    def __init__(
        self,
        experiment,
        node,
        participant,
        propagate_failure,  # If the trial fails, should its failure be propagated to its descendants?
        is_repeat_trial,  # Is the trial a repeat trial?
        parent_trial=None,  # If the trial is a repeat trial, what is its parent?
        repeat_trial_index=None,  # Only relevant if the trial is a repeat trial
        n_repeat_trials=None,  # Only relevant if the trial is a repeat trial
        assets=None,
        definition=NoArgumentProvided,  # If provided, overrides make definition
        position=None,
    ):
        super().__init__(origin=node)
        db.session.add(self)

        self.node = node
        # self.node_id = node.id
        self.complete = False
        self.finalized = False
        self.participant_id = participant.id
        self.propagate_failure = propagate_failure
        self.is_repeat_trial = is_repeat_trial
        self.parent_trial = parent_trial
        self.repeat_trial_index = repeat_trial_index
        self.n_repeat_trials = n_repeat_trials
        self.score = None
        self.response_id = None
        self.time_taken = None
        self.trial_maker_id = node.trial_maker_id
        self.module_state = participant.module_state
        self.position = (
            position
            if position is not None
            else self._next_position(
                participant=participant,
                is_repeat_trial=is_repeat_trial,
                repeat_trial_index=repeat_trial_index,
            )
        )
        self.vars = {}

        self.async_post_trial_required = is_method_overridden(
            self, Trial, "async_post_trial"
        )
        self.async_post_trial_requested = False
        self.async_post_trial_complete = False
        self.async_post_trial_failed = False
        # self.module_id = node.module_id

        if assets is None:
            assets = {}

        if is_repeat_trial:
            self.definition = parent_trial.definition
            for k, v in parent_trial._initial_assets.items():
                self.assets[k] = v
        else:
            self.assets = {
                **node.assets,
                **assets,
            }
            if definition == NoArgumentProvided:
                self.definition = self.make_definition(experiment, participant)
                assert self.definition is not None

                self.definition = self.finalize_definition(
                    self.definition, experiment, participant
                )
                flag_modified(self, "definition")

                assert self.definition is not None
            else:
                self.definition = definition

        if (
            not is_repeat_trial
            and participant.module_state is not None
            and hasattr(participant.module_state, "n_created_trials")
        ):
            participant.module_state.n_created_trials += 1

    def _next_position(self, participant, is_repeat_trial, repeat_trial_index):
        """Return the next zero-based position in this participant's trial maker."""
        if participant.module_state is None or not hasattr(
            participant.module_state, "n_created_trials"
        ):
            return None

        position = participant.module_state.n_created_trials
        if is_repeat_trial:
            position += repeat_trial_index
        return position

    def to_dict(self):
        x = super().to_dict()
        field.json_unpack_field(x, "definition")
        field.json_unpack_field(x, "answer")
        return x

    @property
    def trial_maker(self) -> "TrialMaker":
        from ..experiment import get_trial_maker

        if self.trial_maker_id:
            return get_trial_maker(self.trial_maker_id)

    @property
    def sync_group(self) -> Optional[SyncGroup]:
        """
        The :class:`~psynet.sync.SyncGroup` that this trial's participant belongs
        to for this trial maker, or ``None`` if the trial maker is not
        synchronised (i.e. its ``sync_group_type`` is ``None``).
        """
        sync_group_type = self.trial_maker.sync_group_type
        if sync_group_type is None:
            return None
        return self.participant.active_sync_groups.get(sync_group_type)

    def _allocate_performance_reward(self):
        reward = self.compute_performance_reward(score=self.score)
        assert isinstance(reward, (float, int))
        self._log_performance_reward(reward)
        self.performance_reward = reward
        self.participant.inc_performance_reward(reward)

    def _log_performance_reward(self, reward):
        logger.info(
            "Allocating a performance reward of $%.2f to participant %i for trial %i.",
            reward,
            self.participant.id,
            self.id,
        )

    def score_answer(self, answer, definition):
        """
        Scores the participant's answer. At the point that this method is called,
        any pending asynchronous processes should already have been completed.

        Parameters
        ----------
        answer :
            The answer provided to the trial.

        definition :
            The trial's definition

        Returns
        -------

        A numeric score quantifying the participant's success.
        The experimenter is free to decide the directionality
        (whether high scores are better than low scores, or vice versa).
        Alternatively, ``None`` indicating no score.
        """
        return None

    def compute_performance_reward(self, score):
        """
        Computes a performance reward to allocate to the participant as a reward for the current trial.
        By default, no performance reward is given.
        Note: this trial-level performance reward system is complementary to the trial-maker-level performance reward system,
        which computes an overall performance reward for the participant at the end of a trial maker.
        It is possible to use these two performance reward systems independently or simultaneously.
        See :meth:`~psynet.trial.main.TrialMaker.compute_performance_reward` for more details.

        Parameters
        ----------

        score:
            The score achieved by the participant, as computed by :meth:`~psynet.trial.main.Trial.score_answer`.

        Returns
        -------

        The resulting performance reward, typically in dollars.
        """
        return 0.0

    def json_data(self):
        x = super().json_data()
        x["participant_id"] = self.participant_id
        return x

    def make_definition(self, experiment, participant):
        """
        Creates and returns a definition for the trial,
        which will be later stored in the ``definition`` attribute.
        This can be an arbitrary object as long as it
        is serialisable to JSON.

        Parameters
        ----------

        experiment:
            An instantiation of :class:`psynet.experiment.Experiment`,
            corresponding to the current experiment.

        participant:
            An instantiation of :class:`psynet.participant.Participant`,
            corresponding to the current participant.
        """
        raise NotImplementedError

    def finalize_definition(self, definition, experiment, participant):
        """
        This can be overridden to add additional randomized trial properties.
        For example:

        ::

            definition["bass_note"] = random.sample(10)

        It can also be used to add OnDemandAsset:

        ::

            self.add_assets({
                "audio": OnDemandAsset(
                    function=synth_stimulus,
                    extension=".wav",
                )
        """
        return definition

    def finalize_assets(self):
        for _, asset in self.assets.items():
            if not asset.deposited:
                asset.receive_node_definition(self.definition)
                asset.deposit()

    def show_trial(self, experiment, participant):
        """
        Returns a :class:`~psynet.timeline.Page` object,
        or alternatively a list of such objects,
        that solicits an answer from the participant.

        Parameters
        ----------

        experiment:
            An instantiation of :class:`psynet.experiment.Experiment`,
            corresponding to the current experiment.

        participant:
            An instantiation of :class:`psynet.participant.Participant`,
            corresponding to the current participant.
        """
        raise NotImplementedError

    def show_feedback(self, experiment, participant):
        """
        Returns a Page object displaying feedback
        (or None, which means no feedback).

        Parameters
        ----------

        experiment:
            An instantiation of :class:`psynet.experiment.Experiment`,
            corresponding to the current experiment.

        participant:
            An instantiation of :class:`psynet.participant.Participant`,
            corresponding to the current participant.
        """
        return None

    def _show_feedback(self, experiment, participant):
        return self.show_feedback(experiment=experiment, participant=participant)

    def gives_feedback(self, experiment, participant):
        return is_method_overridden(self, Trial, "show_feedback")
        # return (
        #     self._show_feedback(experiment=experiment, participant=participant)
        #     is not None
        # )

    run_async_post_trial = None

    def async_post_trial(self):
        """
        Optional function to be run after a trial is completed by the participant.
        Will only run if :attr:`~psynet.trial.main.Trial.run_async_post_trial`
        is set to ``True``.
        """
        raise NotImplementedError

    def format_answer(self, raw_answer, **kwargs):
        """
        Optional function to be run after a trial is completed by the participant.
        """
        return raw_answer

    def call_async_post_trial(self):
        try:
            self.async_post_trial()
        except Exception:
            # A failed async_post_trial method might introduce inconsistencies into the database
            # that we don't want to persist. We roll these back so that we revert to the state
            # before the method was called. However, we do need to record that the method failed,
            # so we set the async_post_trial_failed flag to True.
            # Also fail the trial here so it cannot sit complete-but-unfinalizable if the
            # surrounding process failure cascade is skipped (finalize requires async success).
            db.session.rollback()
            self.async_post_trial_failed = True
            self.fail(reason="async_post_trial_failed")
            db.session.commit()
            raise
        self.async_post_trial_complete = True
        self.check_if_can_mark_as_finalized()

    def fail_async_processes(self, reason):
        super().fail_async_processes(reason)
        self.fail(reason="fail_async_processes")

    def new_repeat_trial(self, experiment, repeat_trial_index, n_repeat_trials):
        repeat_trial = self.__class__(
            experiment=experiment,
            node=self.origin,
            participant=self.participant,
            propagate_failure=False,
            is_repeat_trial=True,
            parent_trial=self,
            repeat_trial_index=repeat_trial_index,
            n_repeat_trials=n_repeat_trials,
        )
        return repeat_trial

    def check_if_can_mark_as_finalized(self):
        """Finalize the trial when complete and no blockers remain.

        Intermediate waiting states log at debug; callers and the finalize
        backstop poller re-check as preconditions clear.

        Async post-trial is a success gate, not merely a pending check: if
        async was requested, it must have completed successfully before
        finalization (failed async must not finalize).
        """
        if not self.complete:
            return
        if self.finalized:
            return
        if self.failed:
            logger.debug(
                "Cannot mark trial %s as finalized because it is failed.",
                self.id,
            )
            return
        if self.asset_deposit_pending:
            logger.debug(
                "Cannot mark trial %s as finalized yet; awaiting asset deposit.",
                self.id,
            )
            return
        if self.async_post_trial_blocks_finalization:
            if self.async_post_trial_failed:
                logger.debug(
                    "Cannot mark trial %s as finalized; async_post_trial failed.",
                    self.id,
                )
            else:
                logger.debug(
                    "Cannot mark trial %s as finalized yet; awaiting async_post_trial.",
                    self.id,
                )
            return
        self.finalized = True
        self.on_finalized()

    @classmethod
    def _ready_to_finalize_condition(cls):
        """SQL condition for trials that appear ready to finalize.

        Uses :attr:`async_post_trial_blocks_finalization` (async must have
        succeeded if requested), not :attr:`async_post_trial_pending`.
        """
        return and_(
            cls.complete.is_(True),
            cls.finalized.is_(False),
            cls.failed.is_(False),
            ~cls.asset_deposit_pending,
            ~cls.async_post_trial_blocks_finalization,
        )

    @classmethod
    def ready_to_finalize_id_select(cls):
        """Select IDs of trials that appear ready to finalize."""
        return select(cls.id).where(cls._ready_to_finalize_condition()).order_by(cls.id)

    @classmethod
    def get_trials_ready_to_finalize(cls):
        """
        Return trials that appear ready to finalize, locking them for update.

        Known blockers (undeposited assets, pending async post-trial) are
        excluded in SQL so the steady-state result is empty.

        We use a two-step query on purpose: lock candidate IDs first with
        ``FOR UPDATE SKIP LOCKED``, then load full polymorphic ``Trial``
        objects by those IDs. Loading polymorphic rows in the locked query
        can introduce ``DISTINCT``, which PostgreSQL rejects with
        ``FOR UPDATE``. ``skip_locked`` keeps the poller non-blocking when
        participant requests or async workers already hold a row lock.
        """
        # Lock IDs first; polymorphic Trial loads may add DISTINCT, which
        # PostgreSQL does not allow with FOR UPDATE.
        id_rows = db.session.execute(
            cls.ready_to_finalize_id_select().with_for_update(of=cls, skip_locked=True)
        ).all()
        trial_ids = [row[0] for row in id_rows]
        if not trial_ids:
            return []
        return (
            cls.query.filter(cls.id.in_(trial_ids))
            .order_by(cls.id)
            .populate_existing()
            .all()
        )

    @classmethod
    def finalize_pending_trials(cls):
        """
        Backstop for missed event-driven finalize checks.

        The participant response path, asset deposit callbacks, and async
        post-trial completion remain the fast path. This method recovers
        trials that became ready without those callbacks running.

        Failures are isolated per trial (same idea as network growth): one
        bad ``on_finalized`` must not leave the whole candidate set retrying
        forever. ``handle_error`` rolls back the current session, so
        uncommitted successes since the last commit are undone and retried
        on the next poll. The failing trial is marked failed and committed
        immediately so a later ``handle_error`` in the same batch cannot
        undo that fail.
        """
        from psynet.experiment import get_experiment

        trials = cls.get_trials_ready_to_finalize()
        if not trials:
            return 0

        exp = get_experiment()
        finalized_count = 0
        # Iterate by ID so a mid-batch handle_error rollback cannot leave us
        # holding detached ORM instances for later trials.
        for trial_id in [trial.id for trial in trials]:
            trial = db.session.get(cls, trial_id)
            if trial is None:
                continue
            try:
                was_finalized = trial.finalized
                trial.check_if_can_mark_as_finalized()
                if trial.finalized and not was_finalized:
                    finalized_count += 1
            except Exception as err:
                # Rollback undid uncommitted successes since the last commit;
                # they will be picked up again on the next poll.
                finalized_count = 0
                exp.isolate_batch_item_failure(
                    err,
                    refetch=lambda: db.session.get(cls, trial_id),
                    fail=lambda t: (
                        t.fail(reason="finalize_backstop_error")
                        if not t.failed
                        else None
                    ),
                    trial=trial,
                )

        if finalized_count:
            logger.info(
                "Finalize backstop marked %i trial(s) as finalized.",
                finalized_count,
            )
        return finalized_count

    def check_if_can_run_async_post_trial(self):
        msg = f"Checking if we should run async_post_trial for trial {self.id}... "
        if self.async_post_trial_requested:
            logger.debug("%sno need, async_post_trial has already been requested.", msg)
            return

        if self.run_async_post_trial is not None and not self.run_async_post_trial:
            logger.debug("%sno need, as run_async_post_trial is False.", msg)
            return

        if not is_method_overridden(self, Trial, "async_post_trial"):
            logger.debug("%sno need, as no async_post_trial method is defined.", msg)
            return

        if self.asset_deposit_pending:
            logger.debug("%sawaiting an asset deposit, so we have to wait.", msg)
            return

        logger.debug("%sconditions satisfied, queueing async_post_trial.", msg)
        self.queue_async_post_trial()

    def queue_async_post_trial(self):
        self.async_post_trial_requested = True
        WorkerAsyncProcess(
            self.call_async_post_trial,
            label="post_trial",
            timeout=self.trial_maker.async_timeout_sec,
            trial=self,
            unique=True,
        )

    def on_finalized(self):
        self.score = self.score_answer(answer=self.answer, definition=self.definition)
        self._allocate_performance_reward()

    @classmethod
    def cue(cls, definition, assets=None):
        """
        Use this method to add a trial directly into a timeline,
        without needing to create a corresponding trial maker.

        Parameters
        ----------

        definition :
            This can be a ``dict`` object, which will then be saved to the trial's ``definition`` slot.
            Alternatively, it can be a ``Node`` object, in which case the ``Node`` object
            will be saved to ``trial.node``, and ``node.definition`` will be saved
            to ``trial.definition``.

        assets :
            Optional dictionary of assets to add to the trial (in addition to any provided by
            providing a ``Source`` containing assets to the ``definition`` parameter).
        """
        from psynet.trial.chain import ChainNode

        if isinstance(definition, ChainNode):
            use_default_node = False
            node = definition
            cls.check_node_is_valid(node)
            definition = node.definition
        elif isinstance(definition, dict):
            use_default_node = True
            node = None
        else:
            raise TypeError(f"Invalid definition type: {type(definition)}")

        def _register_trial(experiment, participant):
            nonlocal node

            if use_default_node:
                node = cls.get_default_parent_node(participant, experiment)

            trial = cls(
                experiment,
                node,
                participant,
                propagate_failure=False,
                is_repeat_trial=False,
                definition=definition,
            )
            db.session.add(trial)
            participant.current_trial = trial

            if assets:
                trial.add_assets(assets)

        return join(
            CodeBlock(_register_trial),
            cls.trial_logic(),
        )

    @classmethod
    def get_default_parent_node(cls, participant, experiment):
        module_id = participant.module_id
        try:
            return TrialNode.query.filter_by(
                module_id=module_id,
            ).one()
        except NoResultFound:
            node = GenericTrialNode(module_id, experiment)
            db.session.add(node)
            node.check_on_deploy()
            return node

    @classmethod
    def check_node_is_valid(cls, source):
        if not inspect(source).persistent:
            raise ValueError(
                f"The node with definition {source.definition} looks like it hasn't "
                "been registered in the database. This normally means that you are trying to "
                "access the node object in the wrong way. You should access it by writing "
                "(within a PageMaker or CodeBlock) "
                "lambda nodes: nodes['your_node_key'], "
                "or by writing a SQLAlchemy query, e.g. Node.query.filter_by(...).one()."
            )

    @classmethod
    def trial_logic(cls, trial_maker=None):
        time_estimate = cls._get_trial_time_estimate(trial_maker)

        return join(
            CodeBlock(cls._log_time_credit_before_trial),
            CodeBlock(cls._log_progress_before_trial),
            PageMaker(
                lambda experiment, participant: participant.current_trial._show_trial(
                    experiment, participant
                ),
                time_estimate=time_estimate,
                accumulate_answers=cls.accumulate_answers,
            ),
            cls._finalize_trial(trial_maker),
            cls._construct_feedback_logic(trial_maker),
            CodeBlock(cls._log_time_credit_after_trial),
            CodeBlock(cls._log_progress_after_trial),
        )

    @classmethod
    def _get_trial_time_estimate(cls, trial_maker):
        if cls.time_estimate is not None:
            return cls.time_estimate
        elif trial_maker.time_estimate_per_trial is not None:
            return trial_maker.time_estimate_per_trial
        else:
            raise AttributeError(
                f"You need to provide either time_estimate as a class attribute of {cls.__name__} "
                "or time_estimate_per_trial as a class/instance attribute of the corresponding trial maker."
            )

    def _show_trial(self, experiment, participant):
        return call_function_with_context(
            self.show_trial,
            experiment=experiment,
            participant=participant,
            trial_maker=self.trial_maker,
        )

    @classmethod
    def _log_time_credit_before_trial(cls, participant):
        trial = participant.current_trial
        trial.time_credit_before_trial = participant.time_credit

    @classmethod
    def _log_progress_before_trial(cls, participant):
        trial = participant.current_trial
        trial.progress_before_trial = participant.progress

    @classmethod
    def _log_time_credit_after_trial(cls, participant):
        trial = participant.current_trial
        trial.time_credit_after_trial = participant.time_credit
        trial.time_credit_from_trial = (
            trial.time_credit_after_trial - trial.time_credit_before_trial
        )
        if trial.check_time_credit_received:
            original_estimate = cls._get_trial_time_estimate(
                trial_maker=trial.trial_maker
            )
            actual = trial.time_credit_from_trial
            if actual != original_estimate:
                logger.info(
                    f"Warning: Trial {trial.id} received an unexpected amount of time credit "
                    f"(expected = {original_estimate} seconds; "
                    f"actual = {actual} seconds). "
                    f"Consider setting the trial's `time_estimate` parameter to {trial.time_credit_from_trial}."
                    "You can disable this warning message by setting `Trial.check_time_credit_received = False`."
                )

    @classmethod
    def _log_progress_after_trial(cls, participant):
        trial = participant.current_trial
        trial.progress_after_trial = participant.progress

    @classmethod
    def _finalize_trial(cls, trial_maker=None):
        def f(participant, experiment):
            logger.info("Calling _finalize_trial.")

            trial = participant.current_trial
            if participant.failed:
                # Race guard: a background fail() can land after
                # pending_redirect was already consumed at the start of
                # advance_page. The normal fail() path redirects before this
                # CodeBlock runs.
                logger.info(
                    "Not completing trial %s; the participant was already failed "
                    "(for example participant.fail() while this page was open).",
                    getattr(trial, "id", None),
                )
                return

            answer = participant.answer

            trial.answer = trial.format_answer(answer)
            trial.complete = True

            if trial_maker:
                trial_maker.finalize_trial(
                    answer=trial.answer,
                    trial=trial,
                    experiment=experiment,
                    participant=participant,
                )

            trial.check_if_can_run_async_post_trial()
            trial.check_if_can_mark_as_finalized()

        return CodeBlock(f)

    @classmethod
    def _construct_feedback_logic(cls, trial_maker):
        if trial_maker:
            label = trial_maker.with_namespace("feedback")
        else:
            label = f"{cls.__name__}__feedback"

        return conditional(
            label=label,
            condition=lambda experiment, participant: (
                participant.current_trial.gives_feedback(experiment, participant)
            ),
            logic_if_true=join(
                wait_while(
                    lambda participant: (
                        not participant.current_trial.ready_for_feedback
                    ),
                    expected_wait=0,
                    log_message="Waiting for feedback to be ready.",
                    check_interval=1.0,
                ),
                PageMaker(
                    lambda experiment, participant: (
                        participant.current_trial.show_feedback(
                            experiment=experiment, participant=participant
                        )
                    ),
                    time_estimate=0,
                ),
            ),
            fix_time_credit=False,
            log_chosen_branch=False,
        )

    @hybrid_property
    def asset_deposit_pending(self):
        return any(not asset.deposited for asset in self.assets.values())

    @asset_deposit_pending.expression
    def asset_deposit_pending(cls):
        return (
            select(Asset.id)
            .where(
                Asset.trial_id == Trial.id,
                ~Asset.deposited,
            )
            .exists()
        )


# Keeps the finalize backstop poller cheap: a compact list of row IDs still
# in the complete-but-not-finalized window (predicate columns are constant
# inside that window, so we index id rather than complete/finalized/failed).
Index(
    "ix_info_pending_finalization",
    Trial.id,
    postgresql_where=text(
        "complete IS true AND finalized IS false AND failed IS false"
    ),
)


class TrialMakerState(ModuleState):
    participant_group = Column(String)
    in_repeat_phase = Column(Boolean)
    performance_check = Column(PythonDict)
    trials_to_repeat = Column(PythonObject)
    repeat_trial_index = Column(Integer)
    n_created_trials = Column(Integer, default=0, nullable=False)
    n_completed_trials = Column(Integer)
    trial_maker_initialized = Column(Boolean)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.n_created_trials = 0
        self.n_completed_trials = 0
        self.trial_maker_initialized = False


class TrialMaker(Module):
    """
    Generic trial generation module, to be inserted
    in an experiment timeline. It is responsible for organising
    the administration of trials to the participant.

    Users are invited to override the following abstract methods/attributes:

    * :meth:`~psynet.trial.main.TrialMaker.prepare_trial`,
      which prepares the next trial to administer to the participant.

    * :meth:`~psynet.trial.main.TrialMaker.pre_deploy_routine`
      (optional), which defines a routine that sets up the experiment
      in advance of deployment (for example initialising and seeding networks).

    * :meth:`~psynet.trial.main.TrialMaker.init_participant`
      (optional), a function that is run when the participant begins
      this sequence of trials, intended to initialize the participant's state.
      Make sure you call ``super().init_participant`` when overriding this.

    * :meth:`~psynet.trial.main.TrialMaker.finalize_trial`
      (optional), which finalizes the trial after the participant
      has given their response.

    * :meth:`~psynet.trial.main.TrialMaker.on_complete`
      (optional), run once the sequence of trials is complete.

    * :meth:`~psynet.trial.main.TrialMaker.performance_check`
      (optional), which checks the performance of the participant
      with a view to rejecting poor-performing participants.

    * :meth:`~psynet.trial.main.TrialMaker.compute_performance_reward`;
      computes the final performance reward to assign to the participant.

    * :attr:`~psynet.trial.main.TrialMaker.n_trials_still_required`
      (optional), which is used to estimate how many more participants are
      still required in the case that ``recruit_mode="n_trials"``.

    * :attr:`~psynet.trial.main.TrialMaker.give_end_feedback_passed`
      (default = ``False``); if ``True``, then participants who pass the
      final performance check will be given feedback. This feedback can
      be customised by overriding
      :meth:`~psynet.trial.main.TrialMaker.get_end_feedback_passed_page`.

    Users are also invited to add new recruitment criteria for selection with
    the ``recruit_mode`` argument. This may be achieved using a custom subclass
    of :class:`~psynet.trial.main.TrialMaker` as follows:

    ::

        class CustomTrialMaker(TrialMaker):
            def new_recruit(self, experiment):
                if experiment.my_condition:
                    return True # True means recruit more
                else:
                    return False # False means don't recruit any more (for now)

            recruit_criteria = {
                **TrialMaker.recruit_criteria,
                "new_recruit": new_recruit
            }

    With the above code, you'd then be able to use ``recruit_mode="new_recruit"``.
    If you're subclassing a subclass of :class:`~psynet.trial.main.TrialMaker`,
    then just replace that subclass wherever :class:`~psynet.trial.main.TrialMaker`
    occurs in the above code.

    Parameters
    ----------

    trial_class
        The class object for trials administered by this maker.

    expected_trials_per_participant
        Expected number of trials that the participant will take,
        including repeat trials
        (used for progress estimation).

    check_performance_at_end
        If ``True``, the participant's performance
        is evaluated at the end of the series of trials.

    check_performance_every_trial
        If ``True``, the participant's performance
        is evaluated after each trial.

    fail_trials_on_premature_exit
        Deprecated. Premature exit no longer fails completed trials.
        Incomplete trials are always failed when the participant fails or
        exits. This argument is accepted for backwards compatibility and
        ignored. It is not stored on the trial maker.

    fail_trials_on_participant_performance_check
        If ``True``, a participant's completed trials for this TrialMaker are
        marked as failed when the participant fails a performance check,
        because those responses are treated as unusable. Incomplete trials are
        always failed on any participant failure, regardless of this setting.
        Subclasses document their own defaults.

    propagate_failure
        If ``True``, the failure of a trial is propagated to other
        parts of the experiment (the nature of this propagation is left up
        to the implementation).

    recruit_mode
        Selects a recruitment criterion for determining whether to recruit
        another participant. The built-in criteria are ``"n_participants"``
        and ``"n_trials"``, though the latter requires overriding of
        :attr:`~psynet.trial.main.TrialMaker.n_trials_still_required`.

    target_n_participants
        Target number of participants to recruit for the experiment. All
        participants must successfully finish the experiment to count
        towards this quota. This target is only relevant if
        ``recruit_mode="n_participants"``.

    n_repeat_trials
        Number of repeat trials to present to the participant. These trials
        are typically used to estimate the reliability of the participant's
        responses.
        Defaults to ``0``.

    Attributes
    ----------

    check_timeout_interval_sec : float
        How often to check for timeouts, in seconds (default = 30).
        Users are invited to override this.

    response_timeout_sec : float
        How long until a trial's response times out, in seconds (default = 60)
        (i.e. how long PsyNet will wait for the participant's response to a trial).
        This is a lower bound on the actual timeout
        time, which depends on when the timeout daemon next runs,
        which in turn depends on :attr:`~psynet.trial.main.TrialMaker.check_timeout_interval_sec`.
        Users are invited to override this.

    async_timeout_sec : float
        How long until an async process times out, in seconds (default = 300).
        This is a lower bound on the actual timeout
        time, which depends on when the timeout daemon next runs,
        which in turn depends on :attr:`~psynet.trial.main.TrialMaker.check_timeout_interval_sec`.
        Users are invited to override this.

    introduction
        An optional event or list of elts to execute prior to beginning the trial loop.

    give_end_feedback_passed : bool
        If ``True``, then participants who pass the final performance check
        are given feedback. This feedback can be customised by overriding
        :meth:`~psynet.trial.main.TrialMaker.get_end_feedback_passed_page`.

    performance_threshold : float
        Score threshold used by the default performance check method, defaults to 0.0.
        By default, corresponds to the minimum proportion of non-failed trials that
        the participant must achieve to pass the performance check.

    end_performance_check_waits : bool
        If ``True`` (default), then the final performance check waits until all trials no
        longer have any pending asynchronous processes.

    sync_group_type
        Optional SyncGroup type to use for synchronizing participant allocation to nodes.
        When this is set, then the ordinary node allocation logic will only apply to the 'leader'
        of each SyncGroup. The other members of this SyncGroup will follow that leader around,
        so that in every given trial the SyncGroup works on the same node together.

    sync_group_max_wait_time
        The maximum time that the participant will be allowed to wait for the SyncGroup to be ready.
        If this time is exceeded, the participant is either failed or kicked (see ``sync_group_max_wait_action``).
        Defaults to 45.0 seconds.

    sync_group_max_wait_action
        When ``sync_group_max_wait_time`` is exceeded: ``"fail"`` fails the participant and sends them to the end
        of the experiment; ``"kick"`` removes them from the group and lets them continue. Defaults to ``"fail"``.

    sync_group_timeout_between_barriers_time
        Optional timeout in seconds (since the group's last barrier pass) after which a participant
        is considered too slow. When ``None`` (default), no between-barrier timeout is applied.

    sync_group_timeout_between_barriers_action
        When ``sync_group_timeout_between_barriers_time`` is set: ``"kick"`` removes the participant from the group so
        the rest can proceed, or ``"fail"`` fails the participant. Defaults to ``"fail"``.
    """

    state_class = TrialMakerState

    def __init__(
        self,
        *,
        id_: str,
        trial_class,
        expected_trials_per_participant: Union[int, float],
        check_performance_at_end: bool,
        check_performance_every_trial: bool,
        fail_trials_on_participant_performance_check: bool,
        propagate_failure: bool,
        recruit_mode: str,
        target_n_participants: Optional[int],
        n_repeat_trials: int,
        assets: List,
        fail_trials_on_premature_exit: bool = False,
        sync_group_type: Optional[str] = None,
        sync_group_max_wait_time: float = 45.0,
        sync_group_max_wait_action: Literal["fail", "kick"] = "fail",
        sync_group_timeout_between_barriers_time: Optional[float] = None,
        sync_group_timeout_between_barriers_action: Literal["kick", "fail"] = "fail",
    ):
        if recruit_mode == "n_participants" and target_n_participants is None:
            raise ValueError(
                "If <recruit_mode> == 'n_participants', then <target_n_participants> must be provided."
            )

        if recruit_mode == "n_trials" and target_n_participants is not None:
            raise ValueError(
                "If <recruit_mode> == 'n_trials', then <target_n_participants> must be None."
            )

        if hasattr(self, "performance_check_threshold"):
            raise AttributeError(
                f"Please rename performance_check_threshold to performance_threshold in trial maker '{id_}'."
            )

        if hasattr(self, "compute_bonus"):
            raise AttributeError(
                f"Please rename compute_bonus to compute_performance_reward in trial maker '{id_}'."
            )

        self.trial_class = trial_class
        self.id = id_
        self.expected_trials_per_participant = expected_trials_per_participant
        self.check_performance_at_end = check_performance_at_end
        self.check_performance_every_trial = check_performance_every_trial
        if fail_trials_on_premature_exit:
            _warn_ignored_fail_trials_on_premature_exit(id_)
        self.fail_trials_on_participant_performance_check = (
            fail_trials_on_participant_performance_check
        )
        self.propagate_failure = propagate_failure
        self.recruit_mode = recruit_mode
        self.target_n_participants = target_n_participants
        self.n_repeat_trials = n_repeat_trials
        self.sync_group_type = sync_group_type
        self.sync_group_max_wait_time = sync_group_max_wait_time
        self.sync_group_max_wait_action = sync_group_max_wait_action
        self.sync_group_timeout_between_barriers_time = (
            sync_group_timeout_between_barriers_time
        )
        self.sync_group_timeout_between_barriers_action = (
            sync_group_timeout_between_barriers_action
        )

        elts = self.compile_elts()

        self.check_time_estimates()

        super().__init__(id_, elts, assets=assets)

    participant_progress_threshold = 0.1

    performance_threshold = 0.0

    time_estimate_per_trial = None

    introduction = None

    def compile_elts(self):
        return join(
            RegisterTrialMaker(self),
            self._setup_core,
            self._setup_extra,
            self.introduction,
            self._trial_loop(),
            self._wrapup_core,
            (
                self._check_performance_logic(type="end")
                if self.check_performance_at_end
                else None
            ),
        )

    def custom(self, *args, assets=None, nodes=None):
        return Module(
            self.id,
            join(
                RegisterTrialMaker(self),
                CodeBlock(lambda participant: participant.select_module(self.id)),
                self._setup_core,
                *args,
                CodeBlock(lambda participant: participant.select_module(self.id)),
                self._wrapup_core,
            ),
            assets=assets,
            nodes=nodes,
            state_class=self.state_class,
        )

    @property
    def _setup_core(self):
        return join(
            PreDeployRoutine(self.with_namespace(), self.pre_deploy_routine),
            ParticipantFailRoutine(
                self.with_namespace(), self.participant_fail_routine
            ),
            self.check_timeout_task,
            self._init_participant(),
        )

    def _init_participant(self):
        return conditional(
            "init_participant",
            # If the participant is in a sync group and the leader has not been initialized,
            # then we put a GroupBarrier to ensure that the leader can be initialized first.
            # Otherwise we go ahead and initialize the participant.
            self._requires_sync_group_initialization_barrier,
            logic_if_true=GroupBarrier(
                "init_participant",
                group_type=self.sync_group_type,
                max_wait_time=self.sync_group_max_wait_time,
                max_wait_action=self.sync_group_max_wait_action,
                on_release=self._init_participants_in_sync_group,
                timeout_between_barriers_time=self.sync_group_timeout_between_barriers_time,
                timeout_between_barriers_action=self.sync_group_timeout_between_barriers_action,
            ),
            logic_if_false=CodeBlock(self.init_participant),
            time_estimate=0.0 if self.sync_group_type is None else 3.0,
        )

    def _requires_sync_group_initialization_barrier(self, participant):
        """Return whether the participant should wait for sync-group initialization."""
        if self.sync_group_type is None:
            return False
        if self.sync_group_type not in participant.active_sync_groups:
            participant_id = getattr(participant, "id", "<unknown>")
            raise RuntimeError(
                f"Trial maker '{self.id}' expected participant {participant_id} "
                f"to have an active sync group of type '{self.sync_group_type}' "
                "during initialization."
            )
        return not self._leader_is_initialized(participant)

    def _leader_is_initialized(self, participant):
        group = participant.active_sync_groups[self.sync_group_type]
        leader = group.leader
        return self._is_initialized(leader)

    def _is_initialized(self, participant):
        try:
            state = participant.module_states[self.id][-1]
        except (KeyError, IndexError):
            return False
        return state.trial_maker_initialized

    def _init_participants_in_sync_group(self, group: SyncGroup, experiment):
        self.init_participant(experiment, group.leader)
        for participant in group.active_participants:
            if participant != group.leader and not self._is_initialized(participant):
                self.init_participant(experiment, participant)

    @property
    def _setup_extra(self):
        return join(
            RecruitmentCriterion(self.with_namespace(), self.selected_recruit_criterion)
        )

    @property
    def _wrapup_core(self):
        return join(CodeBlock(self.on_complete))

    @property
    def n_complete_participants(self):
        return Participant.query.filter_by(complete=True).count()

    @property
    def n_working_participants(self):
        return Participant.query.filter_by(status="working", failed=False).count()

    @property
    def n_viable_participants(self):
        return

    def prepare_trial(self, experiment, participant):
        """
        Prepares and returns a trial to administer the participant.

        Parameters
        ----------

        experiment
            An instantiation of :class:`psynet.experiment.Experiment`,
            corresponding to the current experiment.

        participant
            An instantiation of :class:`psynet.participant.Participant`,
            corresponding to the current participant.


        Returns
        _______

        A tuple of (:class:`~psynet.trial.main.Trial`, ``str``), where the first is a Trial object,
        and the second is a status string.
        """
        raise NotImplementedError

    def on_first_launch(self, experiment):
        """
        Defines a routine to run when the experiment is launched for the first time.

        Parameters
        ----------

        experiment
            An instantiation of :class:`psynet.experiment.Experiment`,
            corresponding to the current experiment.

        """
        pass

    def pre_deploy_routine(self, experiment):
        """
        Defines a routine for setting up the experiment prior to deployment.
        This is a good place to prepare networks etc.

        Parameters
        ----------

        experiment
            An instantiation of :class:`psynet.experiment.Experiment`,
            corresponding to the current experiment.

        """
        pass

    check_timeout_interval_sec = 30
    response_timeout_sec = 60 * 5
    async_timeout_sec = 300
    end_performance_check_waits = True

    def participant_fail_routine(self, participant, experiment):
        if "performance_check" not in participant.failure_tags:
            return
        if not self.fail_trials_on_participant_performance_check:
            return
        reason = ", ".join(participant.failure_tags)
        self.fail_participant_trials(participant, reason=reason)

    @property
    def check_timeout_task(self):
        return DatabaseCheck(self.with_namespace("check_timeout"), self.check_timeout)

    def check_timeout(self):
        # pylint: disable=no-member
        self.check_old_trials()
        WorkerAsyncProcess.check_timeouts()

    def selected_recruit_criterion(self, experiment):
        if self.recruit_mode not in self.recruit_criteria:
            raise ValueError(
                f"Invalid recruitment mode: {self.recruit_mode}. Valid options: f{self.recruit_criteria}"
            )
        function = self.recruit_criteria[self.recruit_mode]
        return call_function(function, self=self, experiment=experiment)

    def null_criterion(self, experiment):
        logger.info("Recruitment is disabled for this module.")
        return False

    def n_participants_criterion(self, experiment):
        logger.info(
            "Target number of participants = %i, number of completed participants = %i, number of working participants = %i.",
            self.target_n_participants,
            self.n_complete_participants,
            self.n_working_participants,
        )
        return (
            self.n_complete_participants + self.n_working_participants
        ) < self.target_n_participants

    def n_trials_criterion(self, experiment):
        n_trials_still_required = self.n_trials_still_required
        n_trials_pending = self.n_trials_pending
        logger.info(
            "Number of trials still required = %i, number of pending trials = %i.",
            n_trials_still_required,
            n_trials_pending,
        )
        return n_trials_still_required > n_trials_pending

    recruit_criteria = {
        None: null_criterion,
        "n_participants": n_participants_criterion,
        "n_trials": n_trials_criterion,
    }

    give_end_feedback_passed = False

    def get_end_feedback_passed_page(self, score):
        """
        Defines the feedback given to participants who pass the final performance check.
        This feedback is only given if :attr:`~psynet.trial.main.TrialMaker.give_end_feedback_passed`
        is set to ``True``.

        Parameters
        ----------

        score :
            The participant's score on the performance check.

        Returns
        -------

        :class:`~psynet.timeline.Page` :
            A feedback page.
        """
        score_to_display = "NA" if score is None else f"{(100 * score):.0f}"

        return InfoPage(
            Markup(
                f"Your performance score was <strong>{score_to_display}&#37;</strong>."
            ),
            time_estimate=5,
        )

    def _get_end_feedback_passed_logic(self):
        if self.give_end_feedback_passed:

            def f(participant):
                score = participant.module_state.performance_check["score"]
                return self.get_end_feedback_passed_page(score)

            return PageMaker(f, time_estimate=5)
        else:
            return []

    def visualize(self):
        rendered_div = super().visualize()

        div = tags.div()
        with div:
            with tags.ul(cls="details"):
                if (
                    hasattr(self, "expected_trials_per_participant")
                    and self.expected_trials_per_participant is not None
                ):
                    tags.li(
                        f"Expected number of trials: {self.expected_trials_per_participant}"
                    )
                if (
                    hasattr(self, "target_n_participants")
                    and self.target_n_participants is not None
                ):
                    tags.li(
                        f"Target number of participants: {self.target_n_participants}"
                    )
                if hasattr(self, "recruit_mode") and self.recruit_mode is not None:
                    tags.li(f"Recruitment mode: {self.recruit_mode}")

        return rendered_div + div.render()

    def visualize_tooltip(self):
        return super().visualize_tooltip()

    @property
    def n_trials_pending(self):
        return sum(
            [
                self.estimate_n_pending_trials(p)
                for p in self._established_working_participants
            ]
        )

    @property
    def n_trials_still_required(self):
        raise NotImplementedError

    def estimate_n_pending_trials(self, participant: Participant):
        assert participant.status == "working"
        assert not participant.failed

        module_states = participant.module_states.get(self.id, [])
        n_completed_trials = sum(
            [module_state.n_completed_trials for module_state in module_states]
        )

        # This will be an underestimate in the unusual case of a trial maker inside a while loop.
        # Ideally we'd multiply it by the number of repetitions of the while loop but that's hard to get at from here.
        # It shouldn't really matter though because all that'll happen is we'll recruit a few too many participants.
        expected_total_n_trials = self.expected_trials_per_participant

        return expected_total_n_trials - n_completed_trials

    @property
    def _working_participants(self):
        # Looks across the whole experiment, not just that trial maker.
        # Should migrate this to the experiment class eventually.
        return Participant.query.filter_by(status="working", failed=False)

    @property
    def _established_working_participants(self):
        # Returns the number of established working participants across the whole
        # experiment (not just that trial maker!). Should migrate this to the
        # Experiment class eventually.
        return [
            p
            for p in self._working_participants
            if p.progress > self.participant_progress_threshold
        ]

    def check_old_trials(self):
        time_threshold = datetime.datetime.now() - datetime.timedelta(
            seconds=self.response_timeout_sec
        )
        trials_to_fail = (
            self.trial_class.query.filter_by(complete=False, failed=False)
            .filter(self.trial_class.creation_time < time_threshold)
            .order_by(self.trial_class.id)
            .with_for_update(of=self.trial_class)
            .populate_existing()
            .all()
        )
        logger.info("Found %i old trial(s) to fail.", len(trials_to_fail))
        for trial in trials_to_fail:
            trial.fail(reason="response_timeout")

    def init_participant(self, experiment, participant):
        # pylint: disable=unused-argument
        """
        Initializes the participant at the beginning of the sequence of trials.
        If you override this, make sure you call ``super().init_particiant(...)``
        somewhere in your new method.

        Parameters
        ----------

        experiment
            An instantiation of :class:`psynet.experiment.Experiment`,
            corresponding to the current experiment.

        participant
            An instantiation of :class:`psynet.participant.Participant`,
            corresponding to the current participant.
        """
        participant.select_module(self.id)
        participant.module_state.n_completed_trials = 0
        participant.module_state.in_repeat_phase = False
        self.init_participant_group(experiment, participant)
        participant.module_state.trial_maker_initialized = True

    def init_participant_group(self, experiment, participant):
        if participant.module_state.participant_group:
            return

        sync_group = (
            participant.active_sync_groups[self.sync_group_type]
            if self.sync_group_type
            else None
        )
        is_follower = sync_group and participant != sync_group.leader
        if is_follower:
            logger.info(
                f"participant = {participant.id}, sync_group id = {sync_group.id}"
            )
            participant_group = sync_group.leader.module_state.participant_group
        else:
            if self.choose_participant_group is None:
                participant_group = "default"
            else:
                participant_group = self.choose_participant_group(
                    participant=participant,
                )
        participant.module_state.participant_group = participant_group

    def on_complete(self, experiment, participant):
        """
        An optional function run once the participant completes their
        sequence of trials.

        Parameters
        ----------

        experiment
            An instantiation of :class:`psynet.experiment.Experiment`,
            corresponding to the current experiment.

        participant
            An instantiation of :class:`psynet.participant.Participant`,
            corresponding to the current participant.
        """

    def finalize_trial(self, answer, trial, experiment, participant):
        # pylint: disable=unused-argument,no-self-use
        """
        This function is run after the participant completes the trial.
        It can be optionally customised, for example to add some more postprocessing.
        If you override this, make sure you call ``super().finalize_trial(...)``
        somewhere in your new method.


        Parameters
        ----------

        answer
            The ``answer`` object provided by the trial.

        trial
            The :class:`~psynet.trial.main.Trial` object representing the trial.

        experiment
            An instantiation of :class:`psynet.experiment.Experiment`,
            corresponding to the current experiment.

        participant
            An instantiation of :class:`psynet.participant.Participant`,
            corresponding to the current participant.
        """
        participant.module_state.n_completed_trials += 1

    def performance_check(self, experiment, participant, participant_trials):
        # pylint: disable=unused-argument
        """
        Defines an automated check for evaluating the participant's
        current performance. The default behaviour is to take the sum of
        the trial 'scores' (as computed by the Trial.score_answer),
        but this can be overridden if desired.

        Parameters
        ----------

        experiment
            An instantiation of :class:`psynet.experiment.Experiment`,
            corresponding to the current experiment.

        participant
            An instantiation of :class:`psynet.participant.Participant`,
            corresponding to the current participant.

        participant_trials
            A list of all trials completed so far by the participant.


        Returns
        -------

        dict
            The dictionary should include the following values:

            - ``score``, expressed as a ``float`` or ``None``.
            - ``passed`` (Boolean), identifying whether the participant passed the check.

        """
        score = sum(
            [trial.score for trial in participant_trials if trial.score is not None]
        )
        passed = score > self.performance_threshold
        return {"score": score, "passed": passed}

    def with_namespace(self, x=None):
        return with_trial_maker_namespace(self.id, x=x)

    def fail_participant_trials(self, participant, reason=None):
        """Fail this TrialMaker's non-failed trials for a participant.

        Parameters
        ----------
        participant
            The participant whose trials should be failed.
        reason
            Optional failure reason stored on each trial.
        """
        trials_to_fail = (
            Trial.query.filter_by(participant_id=participant.id, failed=False)
            .join(TrialNetwork)
            .filter_by(trial_maker_id=self.id)
            .order_by(Trial.id)
            .with_for_update(of=Trial)
            .populate_existing()
        )
        for trial in trials_to_fail:
            trial.fail(reason=reason)

    def check_fail_logic(self):
        """
        Determines the timeline logic for when a participant fails
        the performance check.
        By default, the participant is shown an :class:`~psynet.timeline.UnsuccessfulEndPage`.

        Returns
        -------

        An :class:`~psynet.timeline.Elt` or a list of :class:`~psynet.timeline.Elt` s.
        """
        return join(UnsuccessfulEndPage(failure_tags=["performance_check"]))

    def _check_performance_logic(self, type):
        assert type in ["trial", "end"]

        def eval_checks(experiment, participant):
            participant_trials = self.get_participant_trials(participant)
            results = self.performance_check(
                experiment=experiment,
                participant=participant,
                participant_trials=participant_trials,
            )

            assert isinstance(results["passed"], bool)
            participant.module_state.performance_check = results

            if type == "end":
                reward = call_function(self.compute_performance_reward, **results)
                participant.module_state.performance_reward = reward
                participant.inc_performance_reward(reward)

            return results["passed"]

        logic = switch(
            "performance_check",
            function=eval_checks,
            branches={
                True: [] if type == "trial" else self._get_end_feedback_passed_logic(),
                False: self.check_fail_logic(),
            },
            fix_time_credit=False,
            log_chosen_branch=False,
        )

        if type == "end" and self.end_performance_check_waits:

            def any_trials_awaiting_processing(participant):
                return (
                    db.session.query(func.count(Trial.id))
                    .filter(
                        Trial.participant_id == participant.id,
                        Trial.async_post_trial_pending | Trial.asset_deposit_pending,
                    )
                    .scalar()
                ) > 0

            return join(
                wait_while(
                    lambda participant: any_trials_awaiting_processing(participant),
                    expected_wait=5,
                    log_message="Waiting for remaining trials that are awaiting further processing.",
                ),
                logic,
            )
        else:
            return logic

    def get_all_participant_performance_check_results(self):
        records = (
            db.session.query(self.state_class.performance_check)
            .filter_by(module_id=self.id)
            .filter(self.state_class.performance_check.isnot(None))
            .all()
        )
        return [record[0] for record in records]

    def get_participant_trials(self, participant):
        """
        Returns all trials (complete and incomplete) owned by the current participant,
        including repeat trials. Not intended for overriding.

        Parameters
        ----------

        participant:
            An instantiation of :class:`psynet.participant.Participant`,
            corresponding to the current participant.

        """
        all_participant_trials = self.trial_class.query.filter_by(
            participant_id=participant.id
        ).all()
        return [t for t in all_participant_trials if t.trial_maker_id == self.id]

    @log_time_taken
    def _prepare_trial(self, experiment, participant, leader=None):
        # In synchronous trial makers, we only make sure that the participant is still in the sync group (and not e.g. kicked out) before delivering the next trial.
        if (
            self.sync_group_type is not None
            and self.sync_group_type not in participant.active_sync_groups
        ):
            return None, "exit"

        if not participant.module_state.in_repeat_phase:
            if leader is None:
                trial, trial_status = self.prepare_trial(
                    experiment=experiment, participant=participant
                )
            else:
                assert participant.id != leader.id
                trial, trial_status = self.prepare_follower_trial(
                    experiment=experiment, participant=participant, leader=leader
                )
            if trial_status == "exit" and self.n_repeat_trials > 0:
                participant.module_state.in_repeat_phase = True

        if participant.module_state.in_repeat_phase:
            trial, trial_status = self._prepare_repeat_trial(
                experiment=experiment, participant=participant
            )

        return trial, trial_status

    def _prepare_repeat_trial(self, experiment, participant):
        if not participant.module_state.trials_to_repeat:
            self._init_trials_to_repeat(participant)

        trials_to_repeat = participant.module_state.trials_to_repeat
        repeat_trial_index = participant.module_state.repeat_trial_index

        trial_status = "available"

        try:
            trial_to_repeat_id = trials_to_repeat[repeat_trial_index]
            trial_to_repeat = self.trial_class.query.filter_by(
                id=trial_to_repeat_id
            ).one()
            trial = trial_to_repeat.new_repeat_trial(
                experiment, repeat_trial_index, len(trials_to_repeat)
            )
            participant.module_state.repeat_trial_index += 1
            db.session.add(trial)
        except IndexError:
            trial = None
            trial_status = "exit"

        return trial, trial_status

    def _init_trials_to_repeat(self, participant):
        completed_trial_ids = [t.id for t in self.get_participant_trials(participant)]
        actual_n_repeat_trials = min(len(completed_trial_ids), self.n_repeat_trials)
        participant.module_state.trials_to_repeat = random.sample(
            completed_trial_ids, actual_n_repeat_trials
        )
        participant.module_state.repeat_trial_index = 0

    def cue_trial(self):
        """
        You can use this in combination with init_participant to administer trials
        outside of a trialmaker.
        """
        return join(
            CodeBlock(lambda participant: participant.select_module(self.id)),
            self._wait_for_trial(),
            conditional(
                "is_trial_available",
                condition=lambda participant: participant.trial_status != "exit",
                logic_if_true=self.trial_class.trial_logic(trial_maker=self),
                logic_if_false=CodeBlock(
                    lambda: logger.info("No trial found, skipping")
                ),
                fix_time_credit=False,
                log_chosen_branch=False,
            ),
        )

    def _trial_loop(self):
        return join(
            self._wait_for_trial(),
            while_loop(
                self.with_namespace("trial_loop"),
                condition=lambda participant: participant.trial_status != "exit",
                logic=join(
                    self.trial_class.trial_logic(trial_maker=self),
                    (
                        self._check_performance_logic(type="trial")
                        if self.check_performance_every_trial
                        else None
                    ),
                    self._wait_for_trial(),
                ),
                expected_repetitions=self.expected_trials_per_participant,
                fix_time_credit=False,
            ),
        )

    def _wait_for_trial(self):
        def try_to_prepare_trial():
            if not self.sync_group_type:
                return CodeBlock(self._try_to_prepare_trial_solo)
            return conditional(
                "prepare_trial",
                lambda participant: (
                    self.sync_group_type in participant.active_sync_groups
                ),
                join(
                    GroupBarrier(
                        id_="prepare_trial",
                        group_type=self.sync_group_type,
                        on_release=self._try_to_prepare_trial_group,
                        fix_time_credit=False,  # we're already within a while loop with fixed time credit
                        max_wait_time=self.sync_group_max_wait_time,
                        max_wait_action=self.sync_group_max_wait_action,
                        timeout_between_barriers_time=self.sync_group_timeout_between_barriers_time,
                        timeout_between_barriers_action=self.sync_group_timeout_between_barriers_action,
                    )
                ),
                CodeBlock(self._try_to_prepare_trial_solo),
            )

        return join(
            try_to_prepare_trial(),
            while_loop(
                "Waiting for trial",
                lambda participant: participant.trial_status == "wait",
                logic=join(
                    try_to_prepare_trial(),
                    WaitPage(wait_time=2.0),
                ),
                expected_repetitions=0,
                max_loop_time=self.max_time_waiting_for_trial,
                fix_time_credit=False,
            ),
        )

    def _try_to_prepare_trial_solo(self, experiment, participant):
        trial, trial_status = self._prepare_trial(experiment, participant)
        participant.current_trial = trial
        participant.trial_status = trial_status

    def _try_to_prepare_trial_group(self, group: SyncGroup):
        from ..experiment import get_experiment

        experiment = get_experiment()

        leader = group.leader

        leader.current_trial, leader.trial_status = self._prepare_trial(
            experiment=experiment, participant=group.leader
        )
        for follower in group.active_followers:
            follower.current_trial, follower.trial_status = self._prepare_trial(
                experiment=experiment,
                participant=follower,
                leader=group.leader,
            )

    max_time_waiting_for_trial = 60

    def check_time_estimates(self):
        if (
            self.trial_class.time_estimate is None
            and self.time_estimate_per_trial is None
        ):
            raise AttributeError(
                f"You need to provide either time_estimate as a class attribute of {self.trial_class.__name__} "
                f"or time_estimate_per_trial as an instance or class attribute of trial maker {self.id}."
            )

    @classmethod
    def extra_files(cls):
        return []


class NetworkTrialMakerState(TrialMakerState):
    pass


@dataclass(frozen=True)
class Selection:
    """A selected value together with optional request-local context."""

    value: Any
    context: Any = None


class NetworkTrialMaker(TrialMaker):
    """
    Trial maker for network-based experiments.
    These experiments are organised around networks
    in an analogous way to the network-based experiments in Dallinger.
    A :class:`~dallinger.models.Network` comprises a collection of
    :class:`~dallinger.models.Node` objects organised in some kind of structure.
    Here the role of :class:`~dallinger.models.Node` objects
    is to generate :class:`~dallinger.models.Trial` objects.
    Typically the :class:`~dallinger.models.Node` object represents some
    kind of current experiment state, such as the last datum in a transmission chain.
    In some cases, a :class:`~dallinger.models.Network` or a :class:`~dallinger.models.Node`
    will be owned by a given participant; in other cases they will be shared
    between participants.

    An important feature of these networks is that their structure can change
    over time. This typically involves adding new nodes that somehow
    respond to the trials that have been submitted previously.

    This is an infrastructure base class. Concrete trial makers implement
    domain-specific discovery and selection hooks, then return the final node
    from :meth:`~psynet.trial.main.NetworkTrialMaker._select_trial_node`.
    The managed :meth:`~psynet.trial.main.NetworkTrialMaker.prepare_trial`
    implementation creates exactly one trial from that node.

    The trial is then administered to the participant, and a response elicited.
    Once the trial is finished, the network is given another opportunity to grow.

    The implementation also provides support for asynchronous processing,
    for example to prepare the stimuli available at a given node,
    or to postprocess trials submitted to a given node.
    There is some sophisticated logic to make sure that a
    participant is not assigned to a :class:`~dallinger.models.Node` object
    if that object is still waiting for an asynchronous process,
    and likewise a trial won't contribute to a growing network if
    it is still pending the outcome of an asynchronous process.

    Experiment authors should use the public hooks on concrete classes such as
    :class:`~psynet.trial.static.StaticTrialMaker` and
    :class:`~psynet.trial.chain.ChainTrialMaker`, and should not override
    ``prepare_trial``.

    Parameters
    ----------

    trial_class
        The class object for trials administered by this maker.

    network_class
        The class object for the networks used by this maker.
        This should subclass :class`~psynet.trial.main.TrialNetwork`.

    expected_trials_per_participant
        Expected number of trials that the participant will take,
        including repeat trials
        (used for progress estimation).

    check_performance_at_end
        If ``True``, the participant's performance
        is evaluated at the end of the series of trials.

    check_performance_every_trial
        If ``True``, the participant's performance
        is evaluated after each trial.

    fail_trials_on_premature_exit
        See :class:`~psynet.trial.main.TrialMaker`.

    fail_trials_on_participant_performance_check
        See :class:`~psynet.trial.main.TrialMaker`.

    propagate_failure
        If ``True``, the failure of a trial is propagated to other
        parts of the experiment (the nature of this propagation is left up
        to the implementation).

    recruit_mode
        Selects a recruitment criterion for determining whether to recruit
        another participant. The built-in criteria are ``"n_participants"``
        and ``"n_trials"``, though the latter requires overriding of
        :attr:`~psynet.trial.main.TrialMaker.n_trials_still_required`.

    target_n_participants
        Target number of participants to recruit for the experiment. All
        participants must successfully finish the experiment to count
        towards this quota. This target is only relevant if
        ``recruit_mode="n_participants"``.

    n_repeat_trials
        Number of repeat trials to present to the participant. These trials
        are typically used to estimate the reliability of the participant's
        responses.
        Defaults to ``0``.

    wait_for_networks
        If ``True``, then the participant will be made to wait if there are
        still more networks to participate in, but these networks are pending asynchronous processes.

    sync_group_type
        Optional SyncGroup type to use for synchronizing participant allocation to nodes.
        When this is set, then the ordinary node allocation logic will only apply to the 'leader'
        of each SyncGroup. The other members of this SyncGroup will follow that leader around,
        so that in every given trial the SyncGroup works on the same node together.

    sync_group_max_wait_time
        The maximum time that the participant will be allowed to wait for the SyncGroup to be ready.
        If this time is exceeded, the participant is either failed or kicked (see ``sync_group_max_wait_action``).
        Defaults to 45.0 seconds.

    sync_group_max_wait_action
        When ``sync_group_max_wait_time`` is exceeded: ``"fail"`` fails the participant and sends them to the end
        of the experiment; ``"kick"`` removes them from the group and lets them continue. Defaults to ``"fail"``.

    sync_group_timeout_between_barriers_time
        Optional timeout in seconds (since the group's last barrier pass) after which a participant
        is considered too slow. When ``None`` (default), no between-barrier timeout is applied.

    sync_group_timeout_between_barriers_action
        When ``sync_group_timeout_between_barriers_time`` is set: ``"kick"`` removes the participant from the group so
        the rest can proceed, or ``"fail"`` fails the participant. Defaults to ``"fail"``.

    Attributes
    ----------

    check_timeout_interval_sec : float
        How often to check for trials that have timed out, in seconds (default = 30).
        Users are invited to override this.

    response_timeout_sec : float
        How long until a trial's response times out, in seconds (default = 60)
        (i.e. how long PsyNet will wait for the participant's response to a trial).
        This is a lower bound on the actual timeout
        time, which depends on when the timeout daemon next runs,
        which in turn depends on :attr:`~psynet.trial.main.TrialMaker.check_timeout_interval_sec`.
        Users are invited to override this.

    async_timeout_sec : float
        How long until an async process times out, in seconds (default = 300).
        This is a lower bound on the actual timeout
        time, which depends on when the timeout daemon next runs,
        which in turn depends on :attr:`~psynet.trial.main.TrialMaker.check_timeout_interval_sec`.
        Users are invited to override this.

    network_query : sqlalchemy.orm.Query
        An SQLAlchemy query for retrieving all networks owned by the current trial maker.
        Can be used for operations such as the following: ``self.network_query.count()``.

    n_networks : int
        Returns the number of networks owned by the trial maker.

    networks : list
        Returns the networks owned by the trial maker.

    end_performance_check_waits : bool
        If ``True`` (default), then the final performance check waits until all trials no
        longer have any pending asynchronous processes.

    performance_threshold : float (default = -1.0)
        Score threshold used by the default performance check method.
        By default, corresponds to the minimum proportion of non-failed trials that
        the participant must achieve to pass the performance check.
        This is used in :meth:`~psynet.trial.main.NetworkTrialMaker.performance_check`.
    """

    state_class = NetworkTrialMakerState

    def __init__(
        self,
        *,
        id_,
        trial_class,
        network_class,
        expected_trials_per_participant,
        check_performance_at_end,
        check_performance_every_trial,
        fail_trials_on_participant_performance_check,
        # latest performance check is saved in as a participant variable (value, success)
        propagate_failure,
        recruit_mode,
        target_n_participants,
        n_repeat_trials: int,
        wait_for_networks: bool,
        fail_trials_on_premature_exit: bool = False,
        assets=None,
        sync_group_type: Optional[str] = None,
        sync_group_max_wait_time: float = 45.0,
        sync_group_max_wait_action: Literal["fail", "kick"] = "fail",
        sync_group_timeout_between_barriers_time: Optional[float] = None,
        sync_group_timeout_between_barriers_action: Literal["kick", "fail"] = "fail",
    ):
        performance_check_is_enabled = (
            check_performance_at_end or check_performance_every_trial
        )
        has_custom_performance_check = is_method_overridden(
            self, NetworkTrialMaker, "performance_check"
        )

        if (
            performance_check_is_enabled
            and self.performance_check_type is None
            and not has_custom_performance_check
        ):
            raise ValueError(
                f"Trial Maker '{id_}' has performance checks enabled but performance_check_type is not yet set. "
                "Please set this as a class attribute for your custom TrialMaker class, writing for example:\n\n"
                "class ConsonanceTrialMaker(StaticTrialMaker):\n"
                "    performance_check_type = 'score'\n\n"
                "Note: previous versions of PsyNet made this attribute default to "
                "performance_check_type = 'consistency', but we now force experimenters to be explicit "
                "with this decision."
            )

        super().__init__(
            id_=id_,
            trial_class=trial_class,
            expected_trials_per_participant=expected_trials_per_participant,
            check_performance_at_end=check_performance_at_end,
            check_performance_every_trial=check_performance_every_trial,
            fail_trials_on_premature_exit=fail_trials_on_premature_exit,
            fail_trials_on_participant_performance_check=fail_trials_on_participant_performance_check,
            propagate_failure=propagate_failure,
            recruit_mode=recruit_mode,
            target_n_participants=target_n_participants,
            n_repeat_trials=n_repeat_trials,
            assets=assets,
            sync_group_type=sync_group_type,
            sync_group_max_wait_time=sync_group_max_wait_time,
            sync_group_max_wait_action=sync_group_max_wait_action,
            sync_group_timeout_between_barriers_time=sync_group_timeout_between_barriers_time,
            sync_group_timeout_between_barriers_action=sync_group_timeout_between_barriers_action,
        )
        self.network_class = network_class
        self.wait_for_networks = wait_for_networks

    def _generic_removed_selection_hooks(
        self, find_networks_instruction, find_node_instruction
    ):
        """Return TypeError hooks shared by chain and static trial makers."""
        return [
            (
                NetworkTrialMaker,
                "find_networks",
                find_networks_instruction,
            ),
            (
                NetworkTrialMaker,
                "find_node",
                find_node_instruction,
            ),
        ]

    def _raise_unsupported_selection_hook(self, method_name):
        """Raise the configured error for an unsupported selection hook."""
        for _, configured_name, instruction in self._selection_hook_overrides():
            if configured_name == method_name:
                raise TypeError(
                    f"{self.__class__.__name__} called {method_name}, which is "
                    f"not supported by this trial maker. {instruction}"
                )
        raise TypeError(
            f"{self.__class__.__name__} called unsupported hook {method_name}."
        )

    def _apply_deprecated_network_filter(
        self,
        candidates,
        participant,
        *,
        replacement_method,
    ):
        """Apply and validate the deprecated network eligibility filter."""
        return self._validate_selection_subset(
            self.custom_network_filter(
                candidates=candidates,
                participant=participant,
            ),
            allowed_values=candidates,
            method_name=(f"custom_network_filter (replace with {replacement_method})"),
        )

    def check_initialization(self):
        """Validate trial-maker hooks after construction."""
        for ancestor, method_name, instruction in self._selection_hook_overrides():
            if is_method_overridden(self, ancestor, method_name):
                raise TypeError(
                    f"{self.__class__.__name__} overrides {method_name}, which is "
                    f"not supported by this trial maker. {instruction}"
                )
        for ancestor, method_name, instruction in self._deprecated_selection_hooks():
            if is_method_overridden(self, ancestor, method_name):
                message = (
                    f"{method_name} is deprecated: {self.__class__.__name__} still "
                    f"overrides it. {instruction}"
                )
                if sys.version_info >= (3, 12):
                    warnings.warn(
                        message,
                        DeprecationWarning,
                        skip_file_prefixes=psynet_source_prefixes(),
                    )
                else:
                    warnings.warn(message, DeprecationWarning, stacklevel=2)

    def _selection_hook_overrides(self):
        """Return obsolete or wrong-paradigm hooks and their replacements."""
        return []

    def _deprecated_selection_hooks(self):
        """Return still-honoured hooks that should be migrated."""
        return []

    @log_time_taken
    def prepare_trial(self, experiment, participant: Participant):
        logger.info("Preparing trial for participant %i.", participant.id)

        selection = self._select_trial_node(participant, experiment)
        if isinstance(selection, str):
            if selection not in ["wait", "exit"]:
                raise ValueError(
                    "_select_trial_node must return Selection, 'wait', or 'exit'"
                )
            logger.info("Outcome of trial selection: %s", selection)
            return None, selection
        if not isinstance(selection, Selection):
            raise TypeError(
                "_select_trial_node must return Selection, 'wait', or 'exit'"
            )

        node = selection.value
        logger.info(
            "Selected node %i from network %i to give to participant %i.",
            node.id,
            node.network.id,
            participant.id,
        )
        trial = self._create_trial(
            node=node,
            participant=participant,
            experiment=experiment,
        )
        self.on_trial_created(
            trial=trial,
            experiment=experiment,
            participant=participant,
            selection_context=selection.context,
        )
        return trial, "available"

    def on_trial_created(
        self,
        trial,
        experiment,
        participant,
        selection_context=None,
    ):
        """Run after a selected network trial is fully prepared.

        Override this hook to create records that must correspond to the exact
        trial assignment, such as an adaptive-selection decision. The trial and
        any related records are committed in the same transaction; its database
        ID may therefore remain unset until the session is flushed. This hook
        runs for primary trials created through the managed network-selection
        pipeline, not for repeat trials or synchronized follower copies.

        Trial-specific definition and assets belong in
        :meth:`~psynet.trial.main.Trial.finalize_definition`. Those assets are
        deposited and snapshotted before this hook runs.

        Parameters
        ----------
        trial
            The newly created :class:`~psynet.trial.main.Trial`.
        experiment
            The current :class:`~psynet.experiment.Experiment`.
        participant
            The participant to whom the trial was assigned.
        selection_context
            Request-local information returned with a
            :class:`~psynet.trial.main.Selection`, or ``None`` when the
            selection hook returned its value directly.
        """
        pass

    def prepare_follower_trial(
        self, experiment, participant: Participant, leader: Participant
    ):
        logger.info(
            f"Will follow the SyncGroup leader (participant {leader.id}, status = {leader.trial_status})."
        )
        if leader.trial_status in ["wait", "exit"]:
            assert leader.current_trial is None
            trial, trial_status = leader.current_trial, leader.trial_status
        else:
            node = leader.current_trial.node
            trial = self._create_trial(
                node=node,
                participant=participant,
                experiment=experiment,
                trial_class=leader.current_trial.__class__,
            )
            trial_status = "available"
        return trial, trial_status

    ####

    def _select_trial_node(self, participant, experiment):
        """Return ``Selection(node)``, ``"wait"``, or ``"exit"``."""
        raise NotImplementedError

    def _select_from_discovered(
        self, discovered, participant, experiment, select_hook, method_name
    ):
        """Select from a discovered list, or pass through ``wait`` / ``exit``."""
        if isinstance(discovered, str):
            return discovered
        if not isinstance(discovered, list):
            raise TypeError(
                "find_chains / find_nodes must return a list of eligible values, "
                "'wait', or 'exit'; it must not return None"
            )
        if not discovered:
            return "exit"
        return self._coerce_selection(
            select_hook(discovered, participant, experiment),
            allowed_values=discovered,
            method_name=method_name,
        )

    @staticmethod
    def _coerce_selection(selection, allowed_values, method_name):
        """Normalize and validate a public selection-hook result.

        The selected value must be one of ``allowed_values`` by object
        identity, not a re-queried copy with the same id.
        """
        if selection is None:
            raise TypeError(
                f"{method_name} must return one of the supplied eligible values "
                "or Selection(value, context); it must not return None"
            )
        if not isinstance(selection, Selection):
            selection = Selection(value=selection)
        if not any(selection.value is value for value in allowed_values):
            raise ValueError(
                f"{method_name} must select one of the supplied eligible values "
                "(same object identity, not a re-queried copy with the same id)"
            )
        return selection

    @staticmethod
    def _validate_selection_subset(values, allowed_values, method_name):
        """Validate values returned by a public eligibility filter."""
        if not isinstance(values, list):
            raise TypeError(f"{method_name} must return a list")
        allowed_ids = {id(value) for value in allowed_values}
        if any(id(value) not in allowed_ids for value in values):
            raise ValueError(f"{method_name} must return only supplied eligible values")
        if len({id(value) for value in values}) != len(values):
            raise ValueError(f"{method_name} must not return duplicate values")
        return values

    def find_networks(self, participant, experiment):
        """Removed selection hook.

        :meta private:
        """
        self._raise_unsupported_selection_hook("find_networks")

    def find_node(self, network, participant, experiment):
        """Removed selection hook.

        :meta private:
        """
        self._raise_unsupported_selection_hook("find_node")

    def grow_network(self, network, experiment):
        """
        Extends the network if necessary by adding one or more nodes.
        Returns ``True`` if any nodes were added.

        Parameters
        ----------

        network
            The network to be potentially extended.

        experiment
            An instantiation of :class:`psynet.experiment.Experiment`,
            corresponding to the current experiment.
        """
        raise NotImplementedError

    def get_trial_class(self, node, participant, experiment):
        """
        Returns the class of trial to be used for this trial maker.

        This must return a trial class for every eligible selection. Filter
        unavailable values in the concrete trial maker's eligibility hooks
        instead of returning ``None`` here. Synchronized follower trials reuse
        the leader trial's concrete class and do not call this hook again.
        """
        return self.trial_class

    @log_time_taken
    def _create_trial(
        self,
        node,
        participant,
        experiment,
        trial_class=None,
    ):
        if trial_class is None:
            trial_class = self.get_trial_class(node, participant, experiment)
        if trial_class is None:
            raise TypeError(
                f"{self.__class__.__name__}.get_trial_class returned None for node {node.id}. "
                "Filter unavailable values before selection; get_trial_class must "
                "return a trial class."
            )
        trial = trial_class(
            experiment=experiment,
            node=node,
            participant=participant,
            propagate_failure=self.propagate_failure,
            is_repeat_trial=False,
        )
        self._finalize_created_trial(trial)
        db.session.add(trial)
        return trial

    @staticmethod
    def _finalize_created_trial(trial):
        """Finalize assets and snapshot them for later repeat trials."""
        trial.finalize_assets()
        trial._initial_assets = dict(trial.assets)

    def call_grow_network(self, network):
        # pylint: disable=no-member
        from psynet.experiment import get_experiment

        experiment = get_experiment()
        grown = self.grow_network(network, experiment)
        assert isinstance(grown, bool)
        if grown:
            self._check_run_async_post_grow_network(network)

    def _check_run_async_post_grow_network(self, network):
        if (
            network.run_async_post_grow_network is not None
            and not network.run_async_post_grow_network
        ):
            return
        elif not is_method_overridden(network, TrialNetwork, "async_post_grow_network"):
            return
        else:
            self.queue_async_post_grow_network(network)

    def queue_async_post_grow_network(self, network):
        WorkerAsyncProcess(
            network.call_async_post_grow_network,
            label="post_grow_network",
            timeout=self.async_timeout_sec,
            network=network,
        )

    @property
    def network_query(self):
        return self.network_class.query.filter_by(trial_maker_id=self.id)

    @property
    def n_networks(self):
        return self.network_query.count()

    @property
    def networks(self):
        return self.network_query.all()

    performance_threshold = -1.0
    min_nodes_for_performance_check = 2
    performance_check_type = None
    consistency_check_type = "spearman_correlation"

    def compute_performance_reward(self, score, passed):
        """
        Computes the performance reward to allocate to the participant at the end of a trial maker
        on the basis of the results of the final performance check.
        Note: if `check_performance_at_end = False`, then this function will not be run
        and the performance reward will not be assigned.
        """
        return 0.0

    def performance_check(self, experiment, participant, participant_trials):
        if self.performance_check_type == "consistency":
            return self.performance_check_consistency(
                experiment, participant, participant_trials
            )
        elif self.performance_check_type == "performance":
            return self.performance_check_accuracy(
                experiment, participant, participant_trials
            )
        elif self.performance_check_type == "score":
            return self.performance_check_score(
                experiment, participant, participant_trials
            )
        else:
            raise NotImplementedError

    def performance_check_accuracy(self, experiment, participant, participant_trials):
        n_trials = len(participant_trials)
        if n_trials == 0:
            p = None
            passed = True
        else:
            n_failed_trials = len([t for t in participant_trials if t.failed])
            p = 1 - n_failed_trials / n_trials
            passed = p >= self.performance_threshold
        return {"score": p, "passed": passed}

    def performance_check_score(self, experiment, participant, participant_trials):
        score = sum(t.score for t in participant_trials)
        passed = score >= self.performance_threshold
        return {"score": score, "passed": passed}

    def get_answer_for_consistency_check(self, trial):
        # Must return a number
        return float(trial.answer)

    def performance_check_consistency(
        self, experiment, participant, participant_trials
    ):
        repeat_trials = [t for t in participant_trials if t.is_repeat_trial]
        parent_trials = [t.parent_trial for t in repeat_trials]

        repeat_trial_answers = [
            self.get_answer_for_consistency_check(t) for t in repeat_trials
        ]
        parent_trial_answers = [
            self.get_answer_for_consistency_check(t) for t in parent_trials
        ]

        assert self.min_nodes_for_performance_check >= 2

        if len(repeat_trials) < self.min_nodes_for_performance_check:
            logger.info(
                "min_nodes_for_performance_check was not reached, so consistency score cannot be calculated."
            )
            score = None
            passed = True
        else:
            consistency = self.get_consistency(
                repeat_trial_answers, parent_trial_answers
            )
            if isnan(consistency):
                logger.info(
                    """
                    get_consistency returned 'nan' in the performance check.
                    This commonly indicates that the participant gave the same response
                    to all repeat trials. The participant will be failed.
                    """
                )
                score = None
                passed = False
            else:
                score = float(consistency)
                passed = bool(score >= self.performance_threshold)
        logger.info(
            "Performance check for participant %i: consistency = %s, passed = %s",
            participant.id,
            "NA" if score is None else f"{score:.3f}",
            passed,
        )
        return {"score": score, "passed": passed}

    def get_consistency(self, x, y):
        if self.consistency_check_type == "pearson_correlation":
            return corr(x, y)
        elif self.consistency_check_type == "spearman_correlation":
            return corr(x, y, method="spearman")
        elif self.consistency_check_type == "percent_agreement":
            n_cases = len(x)
            n_agreements = sum([a == b for a, b in zip(x, y)])
            return n_agreements / n_cases
        else:
            raise NotImplementedError

    @staticmethod
    def group_trials_by_parent(trials):
        res = {}
        for trial in trials:
            parent_id = trial.parent_trial.id
            if parent_id not in res:
                res[parent_id] = []
            res[parent_id].append(trial)
        return res


class TrialNetwork(SQLMixinDallinger, Network, AssetParentMixin):
    """
    A network class to be used by :class:`~psynet.trial.main.NetworkTrialMaker`.
    The user must override the abstract method :meth:`~psynet.trial.main.TrialNetwork.add_node`.
    The user may also wish to override the
    :meth:`~psynet.trial.main.TrialNetwork.async_post_grow_network` method
    if they wish to implement asynchronous network processing.

    Parameters
    ----------

    experiment
        An instantiation of :class:`psynet.experiment.Experiment`,
        corresponding to the current experiment.

    Attributes
    ----------

    target_n_trials : int or None
        Indicates the target number of trials for that network.
        Left empty by default, but can be set by custom ``__init__`` functions.
        Stored as the field ``property2`` in the database.

    participant : Optional[Participant]
        Returns the network's :class:`~psynet.participant.Participant`,
        or ``None`` if none can be found.

    sync_group_type : Optional[str]
        The ``sync_group_type`` attribute of the trial maker that owns this network.

    sync_group : Optional[SyncGroup]
        The SyncGroup that owns this network (normally only relevant for within-style chains).

    sync_group_id : Optional[int]
        The ID of the SyncGroup that owns this network (normally only relevant for within-style chains).

    n_alive_nodes : int
        Returns the number of non-failed nodes in the network.

    n_completed_trials : int
        Returns the number of completed and non-failed trials in the network
        (irrespective of asynchronous processes, but excluding repeat trials).

    all_trials : list
        A list of all trials owned by that network.

    alive_trials : list
        A list of all non-failed trials owned by that network.

    failed_trials : list
        A list of all failed trials owned by that network.

    var : :class:`~psynet.field.VarStore`
        A repository for arbitrary variables; see :class:`~psynet.field.VarStore` for details.

    run_async_post_grow_network : bool
        Set this to ``True`` if you want the :meth:`~psynet.trial.main.TrialNetwork.async_post_grow_network`
        method to run after the network is grown.
    """

    __extra_vars__ = {
        **SQLMixinDallinger.__extra_vars__.copy(),
    }

    def __repr__(self):
        return ("<Network-{}-{} with {} nodes>").format(
            self.id, self.type, len(self.alive_nodes)
        )

    trial_maker_id = Column(String)
    module_id = Column(String)
    target_n_trials = Column(Integer)
    participant_group = Column(String)

    sync_group_type = Column(String)
    sync_group_id = Column(Integer, ForeignKey("sync_group.id"), index=True)
    sync_group = relationship("SyncGroup", backref="networks")

    participant_id = Column(Integer, ForeignKey("participant.id"), index=True)
    participant = relationship(
        Participant, foreign_keys=[participant_id], post_update=True
    )
    participants = relationship(
        Participant,
        secondary="info",  # The info table is where Trials are stored (for historic reasons)
        primaryjoin="psynet.trial.main.TrialNetwork.id == psynet.trial.main.Trial.network_id",
        secondaryjoin="psynet.trial.main.Trial.participant_id == psynet.participant.Participant.id",
        viewonly=True,
    )

    async_post_grow_network_required = Column(Boolean, default=False, index=True)
    async_post_grow_network_requested = Column(Boolean, default=False, index=True)
    async_post_grow_network_complete = Column(Boolean, default=False, index=True)
    async_post_grow_network_failed = Column(Boolean, default=False, index=True)

    @hybrid_property
    def async_post_grow_network_pending(self):
        return self.async_post_grow_network_requested and not (
            self.async_post_grow_network_complete or self.async_post_grow_network_failed
        )

    @async_post_grow_network_pending.expression
    def async_post_grow_network_pending(cls):
        return and_(
            cls.async_post_grow_network_requested,
            not_(
                or_(
                    cls.async_post_grow_network_complete,
                    cls.async_post_grow_network_failed,
                )
            ),
        )

    id_within_participant = Column(Integer)

    all_trials = relationship("psynet.trial.main.Trial")

    @property
    def alive_nodes(self):
        return [node for node in self.all_nodes if not self.failed]

    @property
    def failed_nodes(self):
        return [node for node in self.all_nodes if self.failed]

    @property
    def alive_trials(self):
        return [t for t in self.all_trials if not t.failed]

    @property
    def failed_trials(self):
        return [t for t in self.all_trials if t.failed]

    @property
    def trials(self):
        raise RuntimeError(
            "The .trials attribute has been removed, please use .all_trials, .alive_trials, or .failed_trials instead."
        )

    async_processes = relationship("AsyncProcess")

    asset_links = relationship(
        "AssetNetwork",
        collection_class=attribute_mapped_collection("local_key"),
        cascade="all, delete-orphan",
    )

    assets = association_proxy(
        "asset_links", "asset", creator=lambda k, v: AssetNetwork(local_key=k, asset=v)
    )

    errors = relationship("ErrorRecord")

    def grow(self, experiment):
        if self.trial_maker:
            self.trial_maker.call_grow_network(self)

    @property
    def trial_maker(self) -> "TrialMaker":
        from ..experiment import get_trial_maker

        if self.trial_maker_id:
            return get_trial_maker(self.trial_maker_id)

    def calculate_full(self):
        raise RuntimeError("This should not be called directly.")

    def add_node(self, node):
        """
        Adds a node to the network. This method is responsible for setting
        ``self.full = True`` if the network is full as a result.
        """
        raise NotImplementedError

    def fail(self, reason=None):
        if not self.failed:
            logger.info(f"Failing network (id: {self.id}, reason: {reason})")
            super().fail(reason=reason)

    # vars = Column(PythonObject)

    @property
    def var(self):
        return VarStore(self)

    ####

    def __init__(
        self,
        trial_maker_id: str,
        experiment,  # noqa
        module_id: Optional[str] = None,
        sync_group_type: Optional[str] = None,
        sync_group: Optional[SyncGroup] = None,
    ):
        # pylint: disable=unused-argument
        self.trial_maker_id = trial_maker_id
        self.assets = {}

        self.sync_group_type = sync_group_type
        self.sync_group = sync_group

        if not module_id:
            module_id = trial_maker_id

        self.module_id = module_id

        self.async_post_grow_network_required = is_method_overridden(
            self, TrialNetwork, "async_post_grow_network"
        )
        self.async_post_grow_network_requested = False
        self.async_post_grow_network_complete = False
        self.async_post_grow_network_failed = False

    run_async_post_grow_network = None

    def async_post_grow_network(self):
        """
        Optional function to be run after the network is grown.
        Will only run if :attr:`~psynet.trial.main.TrialNetwork.run_async_post_grow_network`
        is set to ``True``.
        """

    def call_async_post_grow_network(self):
        try:
            self.async_post_grow_network()
        except Exception:
            self.async_post_grow_network_failed = True
            raise
        self.async_post_grow_network_complete = True


class TrialNode(SQLMixinDallinger, dallinger.models.Node, AssetParentMixin):
    __extra_vars__ = {
        **SQLMixinDallinger.__extra_vars__.copy(),
    }

    trial_maker_id = Column(String, index=True)
    module_id = Column(String, index=True)
    module_state_id = Column(Integer, ForeignKey("module_state.id"), index=True)
    is_global = Column(Integer, ForeignKey("experiment.id"), index=True)

    on_deploy_complete = Column(Boolean, default=False, index=True)

    async_on_deploy_required = Column(Boolean, default=False, index=True)
    async_on_deploy_requested = Column(Boolean, default=False, index=True)
    async_on_deploy_complete = Column(Boolean, default=False, index=True)
    async_on_deploy_failed = Column(Boolean, default=False, index=True)

    @hybrid_property
    def async_on_deploy_pending(self):
        return self.async_on_deploy_requested and not (
            self.async_on_deploy_complete or self.async_on_deploy_failed
        )

    @async_on_deploy_pending.expression
    def async_on_deploy_pending(cls):
        return and_(
            cls.async_on_deploy_requested,
            not_(
                or_(
                    cls.async_on_deploy_complete,
                    cls.async_on_deploy_failed,
                )
            ),
        )

    module_state = relationship("ModuleState")
    async_processes = relationship("AsyncProcess")

    asset_links = relationship(
        "AssetNode",
        collection_class=attribute_mapped_collection("local_key"),
        cascade="all, delete-orphan",
    )

    assets = association_proxy(
        "asset_links", "asset", creator=lambda k, v: AssetNode(local_key=k, asset=v)
    )

    errors = relationship("ErrorRecord")

    all_trials = relationship("psynet.trial.main.Trial", foreign_keys=[Trial.node_id])

    @property
    def trial(self):
        alive_trials = self.alive_trials
        if len(alive_trials) == 0:
            return None
        elif len(alive_trials) == 1:
            return alive_trials[0]
        else:
            raise RuntimeError(f"Node {self.id} has multiple trials.")

    @property
    def alive_trials(self) -> List[Trial]:
        return [t for t in self.all_trials if not t.failed]

    @property
    def pending_trials(self) -> List[Trial]:
        return [t for t in self.alive_trials if not t.finalized]

    @property
    def failed_trials(self) -> List[Trial]:
        return [t for t in self.all_trials if t.failed]

    def update_status(self):
        """
        Hook method called when the node's status may need updating.

        This method is called when trials associated with the node are finalized
        or fail. Subclasses can override this to update derived status attributes.
        For example, ``ChainNode`` uses this to check whether the node is ready
        to spawn a child node.
        """
        pass

    @property
    def trials(self):
        raise RuntimeError(
            "The .trials attribute has been removed, please use .all_trials, .alive_trials, or .failed_trials instead."
        )

    # assets = Column(PythonDict)

    # @property
    # def assets(self):
    #     assets_from_trials = Asset.query.filter(Asset.node_id == self.id, Asset.trial_id != None).all()
    #     assets_not_from_trials = Asset.query.filter(Asset.node_id == self.id, Asset.trial_id == None).all()
    #
    #     assets = {}
    #     for asset in assets_not_from_trials:
    #         assets[asset.label_or_key] = asset
    #
    #     return {
    #         organize_by_key(assets_from_trials, lambda asset: asset.label_or_key)
    #         **assets,
    #     }

    def __init__(self, network=None, participant=None, module_id=None):
        # Note: We purposefully do not call super().__init__(), because this parent constructor
        # requires the prior existence of the node's parent network, which is impractical for us.
        self.module_id = module_id

        if network is not None:
            self.set_network(network)

        if participant is not None:
            self.participant = participant
            self.participant_id = participant.id
            self.module_state = participant.module_state

        self.on_deploy_complete = False
        self.async_on_deploy_required = is_method_overridden(
            self, TrialNode, "async_on_deploy"
        )
        self.async_on_deploy_requested = False
        self.async_on_deploy_complete = False
        self.async_on_deploy_failed = False

    def check_on_deploy(self):
        from psynet.experiment import in_deployment_package

        if (not in_deployment_package()) or self.on_deploy_complete:
            return

        if self.async_on_deploy_required and not (
            self.async_on_deploy_requested or self.async_on_deploy_complete
        ):
            self.queue_async_on_deploy()

        self.on_deploy_complete = True

    def queue_async_on_deploy(self):
        WorkerAsyncProcess(
            function=self.call_async_on_deploy,
            node=self,
            timeout=self.trial_maker.async_timeout_sec,
            unique=True,
        )
        self.async_on_deploy_requested = True

    def call_async_on_deploy(self):
        try:
            self.async_on_deploy()
        except Exception:
            self.async_on_deploy_failed = True
            db.session.commit()
            raise
        self.async_on_deploy_complete = True

    def async_on_deploy(self):
        """
        Called when the node is deployed to the remote server. This includes both
        deploying nodes from the local machine to the remote machine
        (e.g. when we have static stimuli that are preregistered in the database)
        and creating new nodes on the remote machine (e.g. when we have a chain experiment).
        """
        pass

    def set_network(self, network):
        self.network = network
        self.trial_maker_id = network.trial_maker_id

        if not self.module_id:
            self.module_id = network.module_id

        if not self.participant:
            self.participant = network.participant

    @property
    def trial_maker(self) -> "TrialMaker":
        from ..experiment import get_trial_maker

        if self.trial_maker_id:
            return get_trial_maker(self.trial_maker_id)

    def fail(self, reason=None):
        if not self.failed:
            logger.info(f"Failing trial node (id: {self.id}, reason: {reason})")
            super().fail(reason=reason)

    def add_default_network(self):
        from psynet.experiment import get_experiment

        network = GenericTrialNetwork(
            experiment=get_experiment(), module_id=self.module_id
        )
        db.session.add(network)
        self.set_network(network)


class GenericTrialNetwork(TrialNetwork):
    trials_per_node = None

    def __init__(self, module_id, experiment):
        super().__init__(
            trial_maker_id=None,
            module_id=module_id,
            experiment=experiment,
        )

    def grow(self, experiment):
        pass


class GenericTrialNode(TrialNode):
    def __init__(self, module_id, experiment):
        super().__init__(
            network=self.get_default_network(module_id, experiment),
            participant=None,
        )

    def get_default_network(self, module_id, experiment):
        network = GenericTrialNetwork(module_id, experiment)
        db.session.add(network)
        return network


TrialNetwork.n_all_trials = column_property(
    select(func.count(Trial.id))
    .where(
        Trial.network_id == TrialNetwork.id,
    )
    .scalar_subquery()
)

TrialNetwork.n_alive_trials = column_property(
    select(func.count(Trial.id))
    .where(
        Trial.network_id == TrialNetwork.id,
        ~Trial.failed,
    )
    .scalar_subquery()
)

TrialNetwork.n_failed_trials = column_property(
    select(func.count(Trial.id))
    .where(
        Trial.network_id == TrialNetwork.id,
        Trial.failed,
    )
    .scalar_subquery()
)

TrialNetwork.n_completed_trials = column_property(
    select(func.count(Trial.id))
    .where(
        Trial.network_id == TrialNetwork.id,
        ~Trial.failed,
        Trial.complete,
        ~Trial.is_repeat_trial,
    )
    .scalar_subquery()
)

TrialNetwork.n_all_nodes = column_property(
    select(func.count(TrialNode.id))
    .where(
        TrialNode.network_id == TrialNetwork.id,
    )
    .scalar_subquery()
)

TrialNetwork.n_alive_nodes = column_property(
    select(func.count(TrialNode.id))
    .where(
        TrialNode.network_id == TrialNetwork.id,
        ~TrialNode.failed,
    )
    .scalar_subquery()
)

TrialNetwork.n_failed_nodes = column_property(
    select(func.count(TrialNode.id))
    .where(
        TrialNode.network_id == TrialNetwork.id,
        TrialNode.failed,
    )
    .scalar_subquery()
)
