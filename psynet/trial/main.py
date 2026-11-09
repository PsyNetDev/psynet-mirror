import datetime
import random
from dataclasses import dataclass
from functools import partial
from math import isnan
from typing import Any, Callable, List, Literal, Optional, Union

import dallinger.experiment
import dallinger.models
import dallinger.nodes
from dallinger import db
from dallinger.models import Network
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
    UniqueConstraint,
    and_,
    distinct,
    exists,
    func,
    inspect,
    not_,
    or_,
    select,
    text,
)
from sqlalchemy.ext.associationproxy import association_proxy
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import deferred, relationship
from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy.orm.collections import attribute_mapped_collection

from psynet import field

from ..asset import Asset, AssetNetwork, AssetNode, AssetTrial
from ..async_job import WorkerAsyncJob, _deprecated_async_processes, check_priority
from ..data import SQLBase, SQLMixin, SQLMixinDallinger, register_table
from ..db import forbid_commits
from ..error import (  # noqa  # Importing the error module is important to ensure sqlalchemy is happy
    ErrorRecord,
)
from ..field import PythonDict, PythonObject, VarStore
from ..page import InfoPage, UnsuccessfulEndPage, WaitPage, wait_while
from ..participant import Participant
from ..sync import (
    GroupBarrier,
    LateAction,
    ParticipantLinkSyncGroup,
    SyncGroup,
    _execute_advisory_xact_lock,
    _group_max_wait_time,
    _validate_group_timeouts,
)
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
from ..timeline_hold import _reject_countdown
from ..utils import (
    NoArgumentProvided,
    call_function,
    call_function_with_context,
    corr,
    get_logger,
    is_method_overridden,
    log_time_taken,
    warn_from_caller,
)

logger = get_logger()

N_PARTICIPANTS_COMPLETION_MODES = ("experiment", "trial_maker")


def _warn_ignored_fail_trials_on_premature_exit(trial_maker_id):
    message = (
        f"fail_trials_on_premature_exit is ignored in trial maker {trial_maker_id!r}. "
        "Premature exit no longer fails completed trials; incomplete "
        "trials are always failed when the participant exits or fails."
    )
    warn_from_caller(message, DeprecationWarning)


def _check_no_sync_group_options(trial_maker_id, **options):
    """Raise if a ``sync_group_*`` option differs from its default without ``sync_group_type``.

    Each option is passed as ``name=(value, default)``.
    """
    passed = [name for name, (value, default) in options.items() if value != default]
    if passed:
        raise ValueError(
            f"Trial maker {trial_maker_id!r} has sync_group_type=None, so it "
            f"can't use {', '.join(passed)}: pass the sync_group_type of the "
            "groups whose members take the trials together, or remove "
            f"{'it' if len(passed) == 1 else 'them'}."
        )


def with_trial_maker_namespace(trial_maker_id: str, x: Optional[str] = None):
    if x is None:
        return trial_maker_id
    return f"{trial_maker_id}__{x}"


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


@register_table
class Trial(SQLBase, SQLMixin, AssetParentMixin):
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

    Trials are stored in the physical ``trial`` table. Custom trial classes use
    single-table polymorphism within that table.

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
        :class:`~psynet.trial.main.Trial` object should be attached.
        Complex experiments are often organised around networks of nodes,
        but in the simplest case one could just make one :class:`~dallinger.models.Network`
        for each type of trial and one :class:`~dallinger.models.Node` for each participant,
        and then assign the :class:`~psynet.trial.main.Trial`
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

    node
        The :class:`dallinger.models.Node` to which the :class:`~psynet.trial.main.Trial`
        belongs.

    finalized : bool
        Whether the trial has been finalized. This is a stronger condition than ``complete``;
        in particular, a trial is only marked as finalized once its async jobs
        have completed (if it has any).
        One day we might extend this to include arbitrary conditions,
        for example waiting for another user to evaluate that trial, or similar.

    answer : Object
        The response returned by the participant. This is serialised
        to JSON, so it shouldn't be too big.
        The user should not typically change this directly.
        While the trial's pages are being answered, it holds the answer so far,
        as it would be in ``participant.answer``, so that for example a
        :class:`~psynet.sync.GroupBarrier` inside :meth:`show_trial` can read it
        in ``on_release``: with :attr:`accumulate_answers`, a dict that starts
        empty, and otherwise ``None`` until the first page is answered. When
        the trial ends, it is set to the result of :meth:`format_answer`.

    parent_trial_id : int
        If the trial is a repeat trial, this attribute corresponds to the ID
        of the trial from which that repeat trial was cloned.

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
        By default, feedback waits until the trial is finalized or failed, so that
        :meth:`~psynet.trial.main.Trial.show_feedback` sees the results of async
        jobs and :meth:`~psynet.trial.main.Trial.on_finalized`. Set this class attribute
        to ``False`` to give feedback straight away; ``show_feedback`` may then see a trial
        whose async jobs are still running and whose ``score`` is not yet set.

    async_post_trial_priority : str or None
        Priority of the :meth:`~psynet.trial.main.Trial.async_post_trial` job,
        ``"high"`` or ``"low"``; see :class:`~psynet.async_job.WorkerAsyncJob`.
        If ``None`` (default), it is ``"high"`` when a participant may wait for
        the result, i.e. when the trial maker checks performance, when it is a
        within-participant chain trial maker (``chain_type="within"``), whose
        next trial waits for this one to be finalized, or when the trial
        overrides :meth:`~psynet.trial.main.Trial.show_feedback` or
        :meth:`~psynet.trial.main.Trial.gives_feedback` with
        ``wait_for_feedback`` set; it is ``"low"`` otherwise.

    accumulate_answers : bool
        Set this class attribute to ``True`` if the trial contains multiple pages and you want
        the answers to all of these pages to be stored as a dict in ``participant.answer``,
        keyed by page label. The dict fills up as each page is submitted, so later pages
        can read earlier answers. Otherwise, the default behaviour is to only store the
        answer from the final page.

    sync_group_type : str or None
        Set this class attribute to a group type to make :meth:`cue` play the
        trial with the participant's group of that type: the trials that the
        group's members cue in one round share one :class:`SyncGroupNode`,
        and each trial records the group, the participant's role and the
        round. Only used by :meth:`cue`; trial
        makers take ``sync_group_type`` as an argument instead.

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
        suggesting a revised value for ``time_estimate``. Trials played in a
        group (with ``sync_group_id``) are not checked, because by default their
        barriers credit the time actually spent waiting for the others.

    response_id : int
        ID of the associated :class:`~psynet.timeline.Response` object.
        Equals ``None`` if no such object has been created yet.

    response :
        The associated :class:`~psynet.timeline.Response` object,
        which records in detail the response received from the participant's web browser.
        Equals ``None`` if no such object has been created yet.
    """

    __tablename__ = "trial"

    # Unused SharedMixin columns inherited via SQLMixin.
    property1 = None
    property2 = None
    property3 = None
    property4 = None
    property5 = None
    details = None

    node_id = Column(Integer, ForeignKey("node.id"), index=True)
    network_id = Column(Integer, ForeignKey("network.id"), index=True)
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
            "for the participant, or, for trials made by :meth:`Trial.cue`, among "
            "the participant's trials in the same module."
        ),
    )
    # No foreign key, so that creating a trial doesn't wait for a barrier
    # check that holds the group's row.
    sync_group_id = Column(
        Integer,
        index=True,
        doc=(
            "The group of the trial maker's (or, for cued trials, the trial "
            "class's) ``sync_group_type`` that the participant was in when the "
            "trial was created, kept after the group ends."
        ),
    )
    sync_group_role = Column(
        String,
        doc="The participant's role in ``sync_group_id``, if a Regrouper gave one.",
    )
    sync_group_round = Column(
        Integer,
        doc=(
            "Which round of ``sync_group_id`` this trial belongs to, counted "
            "from 0. A member who joined the group late shares the group's "
            "numbers. In a trial maker, a leader told to wait gives the group "
            "no trials, so the followers wait too and no number is used up."
        ),
    )
    definition = Column(PythonObject)

    complete = Column(
        Boolean,
        doc=(
            "Whether the trial has been completed (i.e. received a response from the "
            "participant). The user should not typically change this directly."
        ),
    )

    finalized = Column(Boolean)
    is_repeat_trial = Column(Boolean)
    score = Column(Float)
    performance_reward = Column(Float)
    parent_trial_id = Column(Integer, ForeignKey("trial.id"), index=True)
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
    network = relationship(
        "TrialNetwork",
        foreign_keys=[network_id],
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

    async_jobs = relationship("AsyncJob")
    async_processes = _deprecated_async_processes

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

    wait_for_feedback = True  # determines whether feedback waits for the trial to be finalized or failed
    accumulate_answers = False
    sync_group_type = None

    # Back-compat alias: older code referred to the creating node as ``origin``.
    @property
    def origin(self):
        return self.node

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
    def _recording_failed(self):
        """Identify unavailable media separately from author-defined trial failures."""
        return self.failed and (self.failed_reason or "").startswith("recording_")

    @property
    def ready_for_feedback(self):
        """
        Whether the trial is ready to give feedback to the participant.

        With :attr:`wait_for_feedback`, feedback waits until the trial is
        finalized (so :meth:`on_finalized` has run and ``score`` is set) or
        failed, so :meth:`show_feedback` sees one of those two states.
        """
        msg = f"Participant {self.participant.id}: Checking if the trial is ready for feedback... "

        if self._recording_failed:
            msg += "no, because a required recording failed."
            outcome = False

        elif not self.complete:
            msg += "no, because the trial is not complete."
            outcome = False

        elif not self.wait_for_feedback:
            msg += "yes, because we don't need to wait for feedback."
            outcome = True

        elif self.finalized:
            msg += "yes, the trial is finalized."
            outcome = True

        elif self.failed:
            msg += "yes, the trial failed."
            outcome = True

        else:
            msg += "no, because the trial is not finalized yet."
            outcome = False

        logger.debug(msg)
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
        self.node = node
        self.network = node.network
        db.session.add(self)

        self.complete = False
        self.finalized = False
        self.participant = participant
        self.participant_id = participant.id
        self.propagate_failure = propagate_failure
        self.is_repeat_trial = is_repeat_trial
        self.parent_trial = parent_trial
        self.repeat_trial_index = repeat_trial_index
        self.n_repeat_trials = n_repeat_trials
        self.score = None
        self.answer = {} if self.accumulate_answers else None
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
        The :class:`~psynet.sync.SyncGroup` that the trial was played in
        (``sync_group_id``), or ``None`` if the trial is not synchronised or the
        participant was in no group of that type when the trial was created.
        The group is returned even if the participant has left it since.
        """
        if self.sync_group_id is None:
            return None
        return db.session.get(SyncGroup, self.sync_group_id)

    def _allocate_performance_reward(self):
        reward = self.compute_performance_reward(score=self.score)
        assert isinstance(reward, (float, int))
        self._log_performance_reward(reward)
        self.performance_reward = reward
        self.participant.inc_performance_reward(reward)

    def _log_performance_reward(self, reward):
        logger.debug(
            "Allocating a performance reward of $%.2f to participant %i for trial %i.",
            reward,
            self.participant.id,
            self.id,
        )

    def score_answer(self, answer, definition):
        """
        Scores the participant's answer. At the point that this method is called,
        any pending async jobs should already have been completed.

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

        Unless :attr:`wait_for_feedback` is ``False``, the trial is either
        finalized, so :meth:`on_finalized` has run and ``score`` is set, or
        failed, in which case ``score`` may be unset. Check ``self.failed``
        and ``self.failed_reason`` to give feedback on a failed trial, for
        example a recording that the analysis rejected.

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
    async_post_trial_priority = None

    @classmethod
    def _get_async_post_trial_priority(cls, trial_maker):
        """Return the priority of this trial class's ``async_post_trial`` job.

        See :attr:`async_post_trial_priority` for the rules.
        """
        if cls.async_post_trial_priority is not None:
            check_priority(cls.async_post_trial_priority)
            return cls.async_post_trial_priority
        if trial_maker is not None and (
            trial_maker.check_performance_at_end
            or trial_maker.check_performance_every_trial
            # The participant's next trial waits for this trial to finalize.
            or getattr(trial_maker, "chain_type", None) == "within"
        ):
            return "high"
        if cls.wait_for_feedback and (
            cls.show_feedback is not Trial.show_feedback
            or cls.gives_feedback is not Trial.gives_feedback
        ):
            return "high"
        return "low"

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
        if self._recording_failed:
            logger.info("Skipping analysis for failed trial %s.", self.id)
            return
        try:
            self.async_post_trial()
        except Exception:
            # A failed async_post_trial method might introduce inconsistencies into the database
            # that we don't want to persist. We roll these back so that we revert to the state
            # before the method was called. However, we do need to record that the method failed,
            # so we set the async_post_trial_failed flag to True.
            # Also fail the trial here so it cannot sit complete-but-unfinalizable if the
            # surrounding async job failure cascade is skipped (finalize requires async success).
            db.session.rollback()
            self.async_post_trial_failed = True
            self.fail(reason="async_post_trial_failed")
            db.session.commit()
            raise
        # The worker re-checks finalization after committing (see
        # psynet.async_job._in_async_job).
        self.async_post_trial_complete = True

    def new_repeat_trial(self, experiment, repeat_trial_index, n_repeat_trials):
        repeat_trial = self.__class__(
            experiment=experiment,
            node=self.node,
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
        with forbid_commits(f"{type(self).__name__}.on_finalized"):
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

        Locks participants ``FOR NO KEY UPDATE`` and then trials
        ``FOR UPDATE``, both ``SKIP LOCKED``, so the poller does not block
        when participant requests or async workers already hold a lock on the
        trial or its participant.
        """
        return cls._lock_and_load(cls.ready_to_finalize_id_select(), skip_locked=True)

    @classmethod
    def _lock_and_load(cls, id_select, *, skip_locked=False):
        """Lock the trial rows selected by ``id_select`` and load fresh trials.

        Finalizing writes rows that the participant's requests also write
        (the participant's reward and, for chains, network growth), and
        requests lock the participant before its trials. Holding a trial lock
        while waiting for those rows can therefore deadlock with
        ``participant.fail()``, so the participants are locked first, in a
        separate statement, and only trials of locked participants are then
        locked. With ``skip_locked``, busy participants and trials are
        skipped and no lock is taken on a skipped trial (its participant
        stays locked if it was free), and trials without a participant are
        never returned. The participant lock is ``FOR NO KEY UPDATE``: it
        still excludes requests, but lets other transactions insert rows
        that reference the participant (async jobs, assets), which
        would otherwise wait on it while holding the trial.

        Locks IDs first, then loads full polymorphic ``Trial`` objects by
        those IDs: loading polymorphic rows in the locked query can introduce
        ``DISTINCT``, which PostgreSQL rejects with ``FOR UPDATE``.
        """
        from psynet.participant import Participant

        participant_rows = db.session.execute(
            select(Participant.id)
            .where(
                Participant.id.in_(
                    select(cls.participant_id).where(cls.id.in_(id_select))
                )
            )
            .order_by(Participant.id)
            .with_for_update(of=Participant, key_share=True, skip_locked=skip_locked)
        ).all()
        if skip_locked:
            if not participant_rows:
                return []
            id_select = id_select.where(
                cls.participant_id.in_([row[0] for row in participant_rows])
            )
        locked_select = id_select.with_for_update(of=cls, skip_locked=skip_locked)
        id_rows = db.session.execute(locked_select).all()
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
        forever. Each trial runs in a savepoint, so a failure undoes only
        that trial's work, and the trial is marked failed.
        """
        from psynet.experiment import get_experiment

        trials = cls.get_trials_ready_to_finalize()
        if not trials:
            return 0

        exp = get_experiment()
        finalized_count = 0
        for trial in trials:
            was_finalized = trial.finalized
            exp._run_batch_item(
                trial.check_if_can_mark_as_finalized,
                fail=partial(cls._fail_after_finalize_error, trial),
                trial=trial,
            )
            if trial.finalized and not was_finalized:
                finalized_count += 1
                trial._wake_participant(reason="trial_finalized")

        if finalized_count:
            logger.info(
                "Finalize backstop marked %i trial(s) as finalized.",
                finalized_count,
            )
        return finalized_count

    @staticmethod
    def _fail_after_finalize_error(trial):
        """Fail a trial whose finalization raised in the backstop."""
        if not trial.failed:
            trial.fail(reason="finalize_backstop_error")
            trial._wake_participant(reason="trial_failed")

    @classmethod
    def recheck_finalization(cls, trial_id):
        """Lock a trial, reload it, and finalize it if it is now ready.

        Finalize checks inside a transaction read attributes cached when the
        trial was loaded, so two transactions that each clear one blocker
        (e.g. the participant response and ``async_post_trial``) can both
        miss the other's change. Async workers call this in a fresh
        transaction after committing, so the last committer finalizes the
        trial without waiting for :meth:`finalize_pending_trials`. Leaves
        committing to the caller.
        """
        for trial in cls._lock_and_load(select(cls.id).where(cls.id == trial_id)):
            was_finalized = trial.finalized
            trial.check_if_can_mark_as_finalized()
            if trial.finalized and not was_finalized:
                trial._wake_participant(reason="trial_finalized")

    def _wake_participant(self, *, reason):
        """Wake the participant's held page after the background finalizes or fails this trial.

        The asset-deposit and async-job wakes are sent before that
        happens, so without this wake a page held for the trial (for example
        waiting for feedback) waits for its next poll.
        """
        if self.participant_id is not None:
            from psynet.timeline_hold import _queue_timeline_hold_wake

            _queue_timeline_hold_wake(self.participant_id, reason=reason)

    def check_if_can_run_async_post_trial(self):
        msg = f"Checking if we should run async_post_trial for trial {self.id}... "
        if self._recording_failed:
            logger.debug("%sno, because the trial failed.", msg)
            return
        if self.async_post_trial_requested:
            logger.debug("%sno need, async_post_trial has already been requested.", msg)
            return

        if self.run_async_post_trial is not None and not self.run_async_post_trial:
            logger.debug("%sno need, as run_async_post_trial is False.", msg)
            return

        if not is_method_overridden(self, Trial, "async_post_trial"):
            logger.debug("%sno need, as no async_post_trial method is defined.", msg)
            return

        if self._analysis_deposit_pending:
            logger.debug("%sawaiting an asset deposit, so we have to wait.", msg)
            return

        # A recording worker may have deposited the last asset and queued
        # async_post_trial since this trial was loaded. Re-read the flag under
        # the trial's row lock, which the worker holds until it commits, so
        # the job is queued only once.
        db.session.refresh(
            self, attribute_names=["async_post_trial_requested"], with_for_update=True
        )
        if self.async_post_trial_requested:
            logger.debug("%sno need, async_post_trial was requested meanwhile.", msg)
            return

        logger.debug("%sconditions satisfied, queueing async_post_trial.", msg)
        self.queue_async_post_trial()

    def queue_async_post_trial(self):
        self.async_post_trial_requested = True
        WorkerAsyncJob(
            self.call_async_post_trial,
            label="post_trial",
            timeout=self.trial_maker.async_timeout_sec,
            trial=self,
            unique=True,
            priority=self._get_async_post_trial_priority(self.trial_maker),
        ).enqueue()

    def on_finalized(self):
        self.score = self.score_answer(answer=self.answer, definition=self.definition)
        self._allocate_performance_reward()

    @classmethod
    def cue(
        cls,
        definition,
        assets=None,
        on_trial_created=None,
        creation_context=None,
        *,
        round=None,
    ):
        """
        Use this method to add a trial directly into a timeline,
        without needing to create a corresponding trial maker.

        If the trial class sets :attr:`sync_group_type`, the trial is played with
        the participant's group of that type: the trials that the group's
        members cue in one module and round share one :class:`SyncGroupNode`,
        whose ``var`` holds the group's results for the round. ``cue`` numbers
        each group's rounds from 0 by itself: a cue joins the group's newest
        round while it is open, that is until a barrier of that round
        releases the group, and otherwise starts the next. So a newcomer
        joins a round only before its first barrier releases. Each trial records
        ``sync_group_id``, ``sync_group_role`` and ``sync_group_round``; see
        :ref:`rounds-cued-trials` for the rules. In short:

        - Put a :class:`~psynet.sync.GroupBarrier` in each round, for example
          in :meth:`show_trial`, so that members stay in step.
        - The barriers' ``on_release`` can read each member's answer so far
          from ``trial.answer``: ``None`` there means the page ran out of
          time. With several answer pages before a barrier, set
          :attr:`accumulate_answers` to get them all.
        - In a loop of rounds played by a fixed group, pass the loop value as
          ``round``, so that a definition can come from the loop. Otherwise a
          grouped cue's definition must not depend on the player's own
          position in a loop; pass a function taking ``round`` or ``group``.
        - Each cued trial's ``position`` counts the participant's earlier
          trials in the current module from 0, grouped or not; it is
          ``None`` outside a module.
        - A participant who is in no group of that type gets an ungrouped
          trial on the module's default node, so put the cue in a
          :func:`~psynet.timeline.conditional` on
          ``participant.in_sync_group(...)`` if its pages need the group.
          Once started, the trial runs to its end even if they leave the
          group, so :meth:`show_feedback` can explain every outcome.

        Parameters
        ----------

        definition :
            This can be a ``dict`` object of plain JSON-like values, which will
            then be saved to the trial's ``definition`` slot.
            Alternatively, it can be a :class:`~psynet.trial.chain.ChainNode`,
            which will be saved to ``trial.node``, and whose ``definition`` will
            be saved to ``trial.definition``.
            It can also be a function returning the ``dict``, taking any of
            ``group``, ``round``, ``participant`` and ``experiment``. With
            :attr:`sync_group_type`, the round's first cue sets the node's
            definition, which every trial in the round gets: a function is only
            called then, with ``participant`` set to that first member, and a
            later cue with a different ``dict`` raises a ``ValueError``.
            Otherwise a function is called for each trial, with ``group=None``.

        assets :
            Optional dictionary of assets to add to the trial (in addition to any provided by
            providing a ``Source`` containing assets to the ``definition`` parameter).

        on_trial_created :
            Optional callback executed after the trial and its assets have been
            created. The callback runs in the same transaction as trial creation
            and may accept ``trial``, ``experiment``, ``participant``, and
            ``creation_context`` arguments. It should add related records to the
            current session without committing. Prefer a module-level function
            so the callback remains straightforward to serialize.

        creation_context :
            Optional request-local value passed to ``on_trial_created``. This is
            useful for recording adaptive-selection provenance without adding it
            to the participant-facing trial definition.

        round :
            The group's round to put this trial in, a non-negative integer,
            instead of the automatic one. Pass the loop value when a fixed
            group plays a loop of rounds, or the same value to the cues of
            two trial classes played one after the other in one round. A
            round closes when a :class:`~psynet.sync.GroupBarrier` releases
            the group there, so put one inside ``show_trial``; a round
            without one never closes, and a latecomer can join it after the
            others have finished. If the participant has no trial in a
            closed round, the group finished it without them: the cue is skipped,
            with no trial and no pages, and the round's later barriers don't
            wait for them. ``participant.current_trial`` is then ``None``, so
            guard later steps that read it, for example with a
            :func:`~psynet.timeline.conditional` on
            ``participant.current_trial is not None``. Rounds are ordered by
            when the group first plays them, not by number. A module whose
            cues pass ``round`` runs once per participant, so give each run
            of it its own module id: its cues raise an error if the
            participant has run the module before. Cueing a round again
            after a later one, even one the participant skipped, or a trial
            class again in the same round, also raises an error. Only
            for a trial class that sets :attr:`sync_group_type`, and not with a
            regrouper, whose groups mix players at different loop positions.
            For a participant without a group, ``round`` doesn't select a
            node: they get an ungrouped trial. See
            :ref:`a fixed group's loop <rounds-fixed-group-loop>`.

        Examples
        --------

        ::

            class PickTrial(Trial):
                sync_group_type = "room"
                time_estimate = 15

                def show_trial(self, experiment, participant):
                    return join(
                        ModularPage(
                            "pick",
                            "Pick a number.",
                            PushButtonControl([1, 2, 3, 4, 5]),
                            time_estimate=5,
                        ),
                        GroupBarrier(
                            id_="round_finished",
                            group_type="room",
                            on_release=self.score_room,
                        ),
                    )

                @classmethod
                def score_room(cls, trials, node):
                    node.var.picks = [t.answer for t in trials]

            # A fixed room plays rounds 0, 1 and 2; a player who leaves it
            # plays the remaining rounds alone. The Module gives the nodes a
            # module_id, for example to find them by when exporting.
            join(
                SimpleGrouper("room", initial_group_size=4),
                Module(
                    "game",
                    for_loop(
                        label="rounds",
                        iterate_over=range(3),
                        logic=lambda i: PickTrial.cue(
                            {"numbers": [1, 2, 3, 4, 5], "round": i}, round=i
                        ),
                        time_estimate_per_iteration=20,
                    ),
                ),
            )
        """
        from psynet.trial.chain import ChainNode

        if creation_context is not None and on_trial_created is None:
            raise ValueError("creation_context requires an on_trial_created callback.")
        if cls.sync_group_type is None and round is not None:
            raise ValueError(
                f"{cls.__name__}.cue() takes round= only if "
                f"{cls.__name__}.sync_group_type is set."
            )
        if round is not None and (
            isinstance(round, bool) or not isinstance(round, int) or round < 0
        ):
            raise ValueError(
                f"{cls.__name__}.cue() takes round= as a non-negative integer, "
                f"got {round!r}."
            )

        if isinstance(definition, ChainNode):
            if cls.sync_group_type is not None:
                raise TypeError(
                    f"{cls.__name__} has a sync_group_type, so cue() makes the "
                    "group's node itself; pass a dict or a function instead of a node."
                )
            cls.check_node_is_valid(definition)
        elif not (isinstance(definition, dict) or callable(definition)):
            raise TypeError(f"Invalid definition type: {type(definition)}")

        def _register_trial(experiment, participant):
            node, group, trial_definition = cls._cued_trial_node(
                definition, round, participant, experiment
            )
            if node is None:
                participant.current_trial = None
                return
            trial = cls(
                experiment,
                node,
                participant,
                propagate_failure=False,
                is_repeat_trial=False,
                definition=trial_definition,
                position=_cued_trial_position(participant),
            )
            if group is not None:
                _record_sync_group(trial, participant, group, node.sync_group_round)
            db.session.add(trial)
            participant.current_trial = trial

            if assets:
                trial.add_assets(assets)

            if on_trial_created is not None:
                # The surrounding timeline request owns the transaction. The
                # callback should link related objects through ORM relationships
                # because ``trial.id`` may not exist until that transaction flushes.
                call_function_with_context(
                    on_trial_created,
                    trial=trial,
                    experiment=experiment,
                    participant=participant,
                    creation_context=creation_context,
                )

        trial_logic = cls.trial_logic()
        if round is not None:
            trial_logic = conditional(
                "cued_round",
                lambda participant: participant.current_trial is not None,
                trial_logic,
                log_chosen_branch=False,
            )
        return join(CodeBlock(_register_trial), trial_logic)

    @classmethod
    def _cued_trial_node(cls, definition, round_number, participant, experiment):
        """Return the node, sync group and definition for a trial made by :meth:`cue`."""
        from psynet.trial.chain import ChainNode

        if isinstance(definition, ChainNode):
            return definition, None, definition.definition

        group = None
        if cls.sync_group_type is not None:
            group = participant.active_sync_groups.get(cls.sync_group_type)
            if group is None:
                logger.info(
                    "Participant %s is in no '%s' group, so their %s is not grouped.",
                    participant.id,
                    cls.sync_group_type,
                    cls.__name__,
                )

        def make_definition(round_number):
            if not callable(definition):
                return definition
            return call_function_with_context(
                definition,
                group=group,
                round=round_number,
                participant=participant,
                experiment=experiment,
            )

        if group is None:
            node = cls.get_default_parent_node(participant, experiment)
            return node, None, make_definition(round_number)
        node = SyncGroupNode.for_cue(
            group, round_number, participant, experiment, make_definition, cls
        )
        if node is None:
            logger.info(
                "Participant %s skips round %s of '%s' group %s, which finished "
                "without them.",
                participant.id,
                round_number,
                cls.sync_group_type,
                group.id,
            )
            return None, group, None
        if not callable(definition) and definition != node.definition:
            raise ValueError(
                f"{cls.__name__}.cue() got the definition {definition!r}, but "
                f"round {node.sync_group_round} of '{cls.sync_group_type}' group "
                f"{group.id} already has the definition {node.definition!r}. "
                "All trials in a group's round share the definition of its first "
                "cue, whatever their class or role. A definition taken from the "
                "player's own position in a loop differs for late joiners and in "
                "rooms mixing players from different rounds; in a fixed group's "
                "loop, also pass the loop value as round=. Otherwise pass the "
                "same dict, or a function taking round or group, which is only "
                "called for the round's first cue. Put role-specific content in "
                "the definition keyed by role, or derive it from sync_group_role."
            )
        return node, group, node.definition

    @classmethod
    def get_default_parent_node(cls, participant, experiment):
        """Return the module's shared node for ungrouped cued trials, creating it if needed."""
        module_id = participant.module_id

        def find():
            return (
                GenericTrialNode.query.filter_by(
                    module_id=module_id,
                    type=GenericTrialNode.__mapper__.polymorphic_identity,
                )
                .order_by(GenericTrialNode.id)
                .first()
            )

        node = find()
        if node is None:
            # The first trials of a module can be cued in parallel requests.
            _lock_until_commit(f"generic_trial_node:{module_id}")
            node = find()
        if node is None:
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
        if trial.check_time_credit_received and trial.sync_group_id is None:
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
            logger.debug("Calling _finalize_trial.")

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
                with forbid_commits(f"{type(trial_maker).__name__}.finalize_trial"):
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
        from ..media_upload import _recording_wait_timeout

        if trial_maker:
            label = trial_maker.with_namespace("feedback")
        else:
            label = f"{cls.__name__}__feedback"

        return conditional(
            label=label,
            condition=lambda experiment, participant: (
                not participant.current_trial._recording_failed
                and participant.current_trial.gives_feedback(experiment, participant)
            ),
            logic_if_true=join(
                wait_while(
                    lambda participant: (
                        not participant.current_trial._recording_failed
                        and not participant.current_trial.ready_for_feedback
                    ),
                    expected_wait=0,
                    max_wait_time=lambda participant: _recording_wait_timeout(
                        participant.id, trial_id=participant.current_trial.id
                    ),
                    log_message="Waiting for feedback to be ready.",
                    check_interval=1.0,
                ),
                conditional(
                    label=f"{label}__still_valid",
                    condition=lambda participant: (
                        not participant.current_trial._recording_failed
                    ),
                    logic_if_true=PageMaker(
                        lambda experiment, participant: (
                            participant.current_trial.show_feedback(
                                experiment=experiment, participant=participant
                            )
                        ),
                        time_estimate=0,
                    ),
                    fix_time_credit=False,
                    log_chosen_branch=False,
                ),
            ),
            fix_time_credit=False,
            log_chosen_branch=False,
        )

    @property
    def _analysis_deposit_pending(self):
        """Whether an asset that analysis depends on is still being deposited.

        Background clips never feed analysis, so only finalization waits for
        required ones (see ``asset_deposit_pending``).
        """
        return any(
            not asset.deposited
            and asset.required_for_trial is not False
            and getattr(asset, "recording_role", None) != "background"
            for asset in self.assets.values()
        )

    @hybrid_property
    def asset_deposit_pending(self):
        return any(
            not asset.deposited and asset.required_for_trial is not False
            for asset in self.assets.values()
        )

    @asset_deposit_pending.expression
    def asset_deposit_pending(cls):
        return (
            select(Asset.id)
            .where(
                Asset.trial_id == Trial.id,
                ~Asset.deposited,
                Asset.required_for_trial,
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

# Lets balanced selection count each candidate node's viable trials with an
# index-only scan instead of one heap page per trial. Count queries must use
# count(*) and the same IS false predicates for Postgres to use it.
Index(
    "ix_trial_viable_node_id",
    Trial.node_id,
    postgresql_where=text("is_repeat_trial IS false AND failed IS false"),
)


def _initialized_in(participant, trial_maker_id) -> bool:
    """Return whether the participant's latest run of the trial maker has initialized them."""
    try:
        state = participant.module_states[trial_maker_id][-1]
    except (KeyError, IndexError):
        return False
    return state.trial_maker_initialized


class _InitParticipantBarrier(GroupBarrier):
    """The barrier at which a synchronized trial maker initializes its group, leader first.

    Members wait here until the leader is initialized in this run of the
    trial maker. After that, anyone who arrives passes straight through and
    initializes alone, including a newcomer who arrived while the group's
    release was committing. A newcomer promoted to leader after the group
    passed (see :meth:`~psynet.sync.SyncGroup.check_leader`) also passes,
    and initializes as leader; followers who arrive before that wait for
    them, as followers copy the leader's state.
    """

    _lets_newcomers_through = True

    def __init__(self, trial_maker: "TrialMaker"):
        super().__init__(
            trial_maker.with_namespace("init_participant"),
            on_release=trial_maker._init_participants_in_sync_group,
            expected_wait=3.0,
            **trial_maker._sync_group_barrier_kwargs(),
        )
        self.trial_maker_id = trial_maker.id

    def _lets_through(self, group, participant) -> bool:
        leader = group.leader
        if leader is None:
            return False
        if _initialized_in(leader, self.trial_maker_id):
            return True
        return participant == leader and any(
            _initialized_in(p, self.trial_maker_id) for p in group.active_participants
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
        Custom criteria can be added to ``recruit_criteria``.
        ``None`` leaves recruitment to the rest of the experiment.

    target_n_participants
        Target number of participants to recruit for the experiment. Requires
        ``recruit_mode="n_participants"``; passing it with ``None`` or
        ``"n_trials"`` raises an error. Which completions fill the quota is
        controlled by ``n_participants_completion``.

    n_participants_completion
        Which kind of completion counts toward ``target_n_participants``.
        ``"experiment"`` (default) counts participants who successfully
        finish the whole experiment. ``"trial_maker"`` counts participants
        who finish this TrialMaker, even if they later leave before the
        experiment end page. In-progress participants still occupy a slot
        in both cases, including people who have not yet reached this
        TrialMaker, so PsyNet does not immediately recruit a replacement.
        ``"trial_maker"`` raises an error with ``recruit_mode=None`` or ``"n_trials"``.

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
        How long an async job may run before it times out, in seconds
        (default = 300), counted from when the job starts running, not
        from when it is queued.
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
        Threshold for the default performance check, defaults to 0.0.
        The participant passes when the sum of trial scores exceeds this value.

    end_performance_check_waits : bool
        If ``True`` (default), then the final performance check waits until all trials no
        longer have any pending async jobs, and until trials that are ready
        to finalize have been finalized (so their scores are set).

    sync_group_type
        Optional SyncGroup type to use for synchronizing participant allocation to nodes.
        When this is set, then the ordinary node allocation logic will only apply to the 'leader'
        of each SyncGroup. The other members of this SyncGroup will follow that leader around,
        so that in every given trial the SyncGroup works on the same node together.
        The other ``sync_group_*`` options raise an error without it.

    sync_group_max_wait_time
        Acts on members waiting for their group at the trial maker's own barriers: the longest
        each may wait, in seconds, counted from their arrival, before
        ``sync_group_max_wait_action`` is applied to them. Defaults to 45 seconds, or to no limit
        with ``sync_group_late_after``, which then moves slow members on; passing a number or a
        function together with ``sync_group_late_after`` raises an error. ``None`` means no limit.

    sync_group_max_wait_action
        What happens to a member who waits longer than ``sync_group_max_wait_time``: ``"fail"``
        (default) fails them and sends them to the end of the experiment; ``"leave_group"`` removes them
        from the group, and they get no more trials from this trial maker, or skip the rest of it if
        they haven't finished a trial (see :ref:`sync-leaving-a-group`).

    sync_group_late_after
        Acts on members who haven't reached the trial maker's barrier yet: the longest each may
        take to reach it, in seconds, counted from the group's previous barrier pass or from when
        they joined the group, whichever is later, before ``sync_group_late_action`` is applied
        to them. ``None`` (default) never treats anyone as late. See ``late_after`` in
        :class:`~psynet.sync.GroupBarrier`.

    sync_group_late_action
        What happens to a member who is later than ``sync_group_late_after``: ``"fail"``
        (default) fails them; ``"leave_group"`` removes them from the group, so the rest can go on
        without them (see :ref:`sync-leaving-a-group`); ``"leave_all_groups"`` also removes them
        from their other groups.

    sync_group_waiting_message
        Message on the waiting indicator at the trial maker's own sync-group waits
        (initialization and trial preparation). If omitted, participants see "Waiting for other
        participants…". :class:`~psynet.sync.Grouper` and :class:`~psynet.sync.GroupBarrier`
        elements use their own ``waiting_message``; pass the same text to them if the messages
        should match.
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
        sync_group_max_wait_time: Optional[Union[float, Callable]] = NoArgumentProvided,
        sync_group_max_wait_action: Literal["fail", "leave_group"] = "fail",
        sync_group_late_after: Optional[float] = None,
        sync_group_late_action: LateAction = "fail",
        sync_group_waiting_message=None,
        n_participants_completion: Literal["experiment", "trial_maker"] = "experiment",
    ):
        if recruit_mode not in self.recruit_criteria:
            raise ValueError(
                f"Unknown recruit_mode {recruit_mode!r}. Valid options: "
                f"{sorted(map(repr, self.recruit_criteria))}."
            )
        if recruit_mode == "n_participants" and target_n_participants is None:
            raise ValueError(
                "recruit_mode='n_participants' needs target_n_participants, "
                "the number of participants to recruit."
            )

        if recruit_mode in (None, "n_trials") and target_n_participants is not None:
            raise ValueError(
                f"target_n_participants only takes effect with "
                f"recruit_mode='n_participants', but recruit_mode is {recruit_mode!r}. "
                "Pass recruit_mode='n_participants' to recruit until this many "
                "participants finish, or remove target_n_participants."
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
        if n_participants_completion not in N_PARTICIPANTS_COMPLETION_MODES:
            raise ValueError(
                "n_participants_completion must be 'experiment' or 'trial_maker', "
                f"got {n_participants_completion!r}."
            )
        if n_participants_completion != "experiment" and recruit_mode in (
            None,
            "n_trials",
        ):
            raise ValueError(
                f"n_participants_completion only takes effect with "
                f"recruit_mode='n_participants', but recruit_mode is {recruit_mode!r}. "
                "Pass recruit_mode='n_participants' or remove n_participants_completion."
            )
        self.n_participants_completion = n_participants_completion
        self.n_repeat_trials = n_repeat_trials
        if sync_group_type is None:
            # Released in 13.3, where it was silently ignored, so only warn.
            if sync_group_max_wait_time is not NoArgumentProvided:
                warn_from_caller(
                    f"Trial maker '{id_}': sync_group_max_wait_time has no effect "
                    "without sync_group_type, so it is ignored.",
                    UserWarning,
                )
            _check_no_sync_group_options(
                id_,
                sync_group_max_wait_action=(sync_group_max_wait_action, "fail"),
                sync_group_late_after=(sync_group_late_after, None),
                sync_group_late_action=(sync_group_late_action, "fail"),
                sync_group_waiting_message=(sync_group_waiting_message, None),
            )
        _validate_group_timeouts(
            sync_group_max_wait_action,
            sync_group_late_after,
            sync_group_late_action,
            prefix="sync_group_",
        )
        if sync_group_type is not None:
            _reject_countdown(
                sync_group_waiting_message,
                f"Trial maker '{id_}'",
                argument="sync_group_waiting_message",
            )
        class_group_type = getattr(trial_class, "sync_group_type", None)
        if class_group_type is not None and class_group_type != sync_group_type:
            raise ValueError(
                f"Trial maker '{id_}' has sync_group_type={sync_group_type!r}, but "
                f"its trial class {trial_class.__name__} sets sync_group_type="
                f"{class_group_type!r}, which only Trial.cue uses. Pass the group "
                "type to the trial maker and leave it off the trial class."
            )
        self.sync_group_type = sync_group_type
        self.sync_group_max_wait_time = _group_max_wait_time(
            sync_group_max_wait_time,
            sync_group_late_after,
            default=45,
            prefix="sync_group_",
        )
        self.sync_group_max_wait_action = sync_group_max_wait_action
        self.sync_group_late_after = sync_group_late_after
        self.sync_group_late_action = sync_group_late_action
        self.sync_group_waiting_message = sync_group_waiting_message

        elts = self.compile_elts()

        self.check_time_estimates()

        super().__init__(id_, elts, assets=assets)

    participant_progress_threshold = 0.1

    performance_threshold = 0.0

    time_estimate_per_trial = None

    introduction = None

    def _sync_group_barrier_kwargs(self):
        """Return shared kwargs for trial-maker-owned sync-group barriers."""
        return dict(
            group_type=self.sync_group_type,
            max_wait_time=self.sync_group_max_wait_time,
            max_wait_action=self.sync_group_max_wait_action,
            late_after=self.sync_group_late_after,
            late_action=self.sync_group_late_action,
            waiting_message=self.sync_group_waiting_message,
        )

    def compile_elts(self):
        return join(
            RegisterTrialMaker(self),
            self._setup_core,
            self._setup_extra,
            conditional(
                "not_left_before_any_trial",
                lambda participant: not self._left_before_any_trial(participant),
                join(self.introduction, self._trial_loop()),
                log_chosen_branch=False,
            ),
            conditional(
                "not_left_before_any_trial_wrapup",
                lambda participant: not self._left_before_any_trial(participant),
                join(
                    self._wrapup_core,
                    (
                        self._check_performance_logic(type="end")
                        if self.check_performance_at_end
                        else None
                    ),
                ),
                log_chosen_branch=False,
            ),
        )

    def _left_before_any_trial(self, participant):
        """Return whether the participant left the trial maker's group before finishing a trial here.

        They skip the rest of the trial maker, including a performance check
        that would judge them on no trials.
        """
        return (
            self._left_sync_group(participant)
            and not participant.module_state.n_completed_trials
        )

    def _left_sync_group(self, participant):
        """Return whether the trial maker is synchronized and the participant is out of its group."""
        return (
            self.sync_group_type is not None
            and self.sync_group_type not in participant.active_sync_groups
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
        # The barrier makes sure the group's leader is initialized first.
        barrier = [] if self.sync_group_type is None else _InitParticipantBarrier(self)
        return join(
            barrier,
            # Everyone else initializes alone, including members released
            # from the barrier by a max-wait time-out, which skips on_release.
            CodeBlock(self._init_if_not_initialized),
        )

    def _init_if_not_initialized(self, experiment, participant):
        """Initialize the participant unless their group's release already did."""
        if not self._is_initialized(participant):
            self.init_participant(experiment, participant)

    def _is_initialized(self, participant):
        return _initialized_in(participant, self.id)

    def _init_participants_in_sync_group(self, group: SyncGroup, experiment):
        if not self._is_initialized(group.leader):
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
        """Number of participants who count as complete for this TrialMaker's quota."""
        if self.n_participants_completion == "trial_maker":
            return self._n_trial_maker_complete_participants
        return Participant.query.filter_by(complete=True).count()

    @property
    def n_working_participants(self):
        """Number of in-progress participants occupying a slot in this TrialMaker's quota."""
        if self.n_participants_completion == "trial_maker":
            return self._n_trial_maker_working_participants
        return Participant.query.filter_by(status="working", failed=False).count()

    @property
    def _n_trial_maker_complete_participants(self):
        """Count distinct participants who have finished this TrialMaker."""
        n = (
            db.session.query(func.count(distinct(ModuleState.participant_id)))
            .filter(
                ModuleState.module_id == self.id,
                ModuleState.finished.is_(True),
            )
            .scalar()
        )
        return n or 0

    @property
    def _n_trial_maker_working_participants(self):
        """Count working non-failed participants who have not finished this TrialMaker."""
        finished_this_module = exists().where(
            ModuleState.participant_id == Participant.id,
            ModuleState.module_id == self.id,
            ModuleState.finished.is_(True),
        )
        n = (
            db.session.query(func.count(distinct(Participant.id)))
            .filter(
                Participant.status == "working",
                Participant.failed.is_(False),
                Participant.early_exited.is_(False),
                ~finished_this_module,
            )
            .scalar()
        )
        return n or 0

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
        self.check_old_trials()

    def selected_recruit_criterion(self, experiment):
        if self.recruit_mode not in self.recruit_criteria:
            raise ValueError(
                f"Invalid recruitment mode: {self.recruit_mode}. Valid options: {list(self.recruit_criteria)}"
            )
        function = self.recruit_criteria[self.recruit_mode]
        return call_function(function, self=self, experiment=experiment)

    def null_criterion(self, experiment):
        logger.debug("Recruitment is disabled for this module.")
        return False

    def n_participants_criterion(self, experiment):
        logger.debug(
            "Target number of participants = %i, completion counted at %s, number of completed participants = %i, number of working participants = %i.",
            self.target_n_participants,
            self.n_participants_completion,
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
            Markup("Your performance score was <strong>{}&#37;</strong>.").format(
                score_to_display
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
                if (
                    getattr(self, "recruit_mode", None) == "n_participants"
                    and getattr(self, "n_participants_completion", None) is not None
                ):
                    tags.li(
                        f"Participants counted when: {self.n_participants_completion} complete"
                    )

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
            # A locked trial belongs to an in-flight request that may complete
            # it; the next check retries it if not.
            .with_for_update(of=self.trial_class, skip_locked=True)
            .populate_existing()
            .all()
        )
        logger.info("Found %i old trial(s) to fail.", len(trials_to_fail))
        for trial in trials_to_fail:
            trial.fail(reason="response_timeout")

    def init_participant(self, experiment, participant):
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

    def _active_sync_group(self, participant):
        """Return the participant's active group of ``sync_group_type``, if any."""
        if self.sync_group_type is None:
            return None
        return participant.active_sync_groups.get(self.sync_group_type)

    def _leader_state(self, sync_group):
        """Return the group leader's state for this trial maker.

        The leader may already be in a later module, so this reads their state
        for this trial maker rather than their current module state.
        """
        return sync_group.leader.module_states[self.id][-1]

    def init_participant_group(self, experiment, participant):
        if participant.module_state.participant_group:
            return

        sync_group = self._active_sync_group(participant)
        is_follower = sync_group and participant != sync_group.leader
        if is_follower:
            logger.info(
                f"participant = {participant.id}, sync_group id = {sync_group.id}"
            )
            participant_group = self._leader_state(sync_group).participant_group
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
            from ..media_upload import _recording_wait_timeout

            def any_trials_awaiting_processing(participant):
                return (
                    db.session.query(func.count(Trial.id))
                    .filter(
                        Trial.participant_id == participant.id,
                        # A trial failed by a missing recording keeps its
                        # pending flags, which would never clear.
                        ~Trial.failed,
                        Trial.async_post_trial_pending
                        | Trial.asset_deposit_pending
                        # Scores are set on finalization, which can lag behind
                        # the last blocker clearing.
                        | Trial._ready_to_finalize_condition(),
                    )
                    .scalar()
                ) > 0

            return join(
                wait_while(
                    lambda participant: any_trials_awaiting_processing(participant),
                    expected_wait=5,
                    max_wait_time=lambda participant: _recording_wait_timeout(
                        participant.id
                    ),
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
        # Performance checks may run after every trial. Filtering in Python
        # would repeatedly hydrate trials from the participant's other trial
        # makers, making long multi-module experiments increasingly expensive.
        # Order explicitly: callers such as performance_check and repeat-trial
        # sampling are sensitive to ordering, which the database does not
        # otherwise guarantee.
        return (
            self.trial_class.query.filter_by(
                participant_id=participant.id,
                trial_maker_id=self.id,
            )
            .order_by(self.trial_class.id)
            .all()
        )

    @log_time_taken
    def _prepare_trial(self, experiment, participant, leader=None):
        with forbid_commits(f"{type(self).__name__} trial preparation"):
            return self._prepare_trial_uncommitted(experiment, participant, leader)

    def _prepare_trial_uncommitted(self, experiment, participant, leader):
        # In synchronous trial makers, we only make sure that the participant is still in the sync group (and was not, e.g., removed from it) before delivering the next trial.
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

        if (
            trial is not None
            and self.sync_group_type is not None
            and trial.sync_group_id is None
        ):
            group = participant.active_sync_groups[self.sync_group_type]
            _record_sync_group(trial, participant, group)
            if trial.trial_maker_id is None:
                # A custom prepare_trial may put the trial on a node of no
                # trial maker; the group's round numbers need the trial maker.
                trial.trial_maker_id = self.id
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
                    lambda: logger.debug("No trial found, skipping")
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
        from ..media_upload import _has_outstanding_recordings

        def try_to_prepare_trial():
            if not self.sync_group_type:
                return CodeBlock(self._try_to_prepare_trial_solo)
            return join(
                GroupBarrier(
                    id_=self.with_namespace("prepare_trial"),
                    on_release=self._try_to_prepare_trial_group,
                    fix_time_credit=False,  # we're already within a while loop with fixed time credit
                    **self._sync_group_barrier_kwargs(),
                ),
                # For members who left the group, including those released
                # by a max-wait time-out, which skips on_release.
                CodeBlock(self._exit_if_left_group),
            )

        return join(
            try_to_prepare_trial(),
            while_loop(
                "Waiting for trial",
                lambda participant: participant.trial_status == "wait",
                logic=join(
                    # Keep an explicit page wait so each iteration reruns
                    # the preparation timeline logic.
                    WaitPage(wait_time=2.0),
                    # Refresh availability before the loop checks its timeout
                    # when the participant returns from this wait page.
                    try_to_prepare_trial(),
                ),
                expected_repetitions=0,
                max_loop_time=self.max_time_waiting_for_trial,
                # The next trial may depend on the participant's last answer.
                extend_while=lambda participant: _has_outstanding_recordings(
                    participant.id
                ),
                fix_time_credit=False,
            ),
        )

    def _exit_if_left_group(self, experiment, participant):
        """End the trial loop for a participant who is no longer in the group."""
        if self._left_sync_group(participant):
            participant.current_trial = None
            participant.trial_status = "exit"

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
        self._number_group_round(group, [leader, *group.active_followers])

    def _number_group_round(self, group: SyncGroup, members):
        """Give the trials just created for ``group`` its next round number."""
        trials = [
            member.current_trial
            for member in members
            if member.current_trial is not None
            and member.current_trial.sync_group_round is None
        ]
        if not trials:
            return
        latest = (
            db.session.query(func.max(Trial.sync_group_round))
            .filter_by(sync_group_id=group.id, trial_maker_id=self.id)
            .scalar()
        )
        number = 0 if latest is None else latest + 1
        for trial in trials:
            trial.sync_group_round = number

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
    if that object is still waiting for an async job,
    and likewise a trial won't contribute to a growing network if
    it is still pending the outcome of an async job.

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
        Custom criteria can be added to ``recruit_criteria``.
        ``None`` leaves recruitment to the rest of the experiment.

    target_n_participants
        Target number of participants to recruit for the experiment. Requires
        ``recruit_mode="n_participants"``; passing it with ``None`` or
        ``"n_trials"`` raises an error. Which completions fill the quota is
        controlled by ``n_participants_completion``.

    n_participants_completion
        Which kind of completion counts toward ``target_n_participants``.
        ``"experiment"`` (default) counts participants who successfully
        finish the whole experiment. ``"trial_maker"`` counts participants
        who finish this TrialMaker, even if they later leave before the
        experiment end page. In-progress participants still occupy a slot
        in both cases, including people who have not yet reached this
        TrialMaker, so PsyNet does not immediately recruit a replacement.
        ``"trial_maker"`` raises an error with ``recruit_mode=None`` or ``"n_trials"``.

    n_repeat_trials
        Number of repeat trials to present to the participant. These trials
        are typically used to estimate the reliability of the participant's
        responses.
        Defaults to ``0``.

    wait_for_networks
        If ``True``, then the participant will be made to wait if there are
        still more networks to participate in, but these networks are pending async jobs.

    sync_group_type
        Optional SyncGroup type to use for synchronizing participant allocation to nodes.
        When this is set, then the ordinary node allocation logic will only apply to the 'leader'
        of each SyncGroup. The other members of this SyncGroup will follow that leader around,
        so that in every given trial the SyncGroup works on the same node together.
        The other ``sync_group_*`` options raise an error without it.

    sync_group_max_wait_time
        Acts on members waiting for their group at the trial maker's own barriers: the longest
        each may wait, in seconds, counted from their arrival, before
        ``sync_group_max_wait_action`` is applied to them. Defaults to 45 seconds, or to no limit
        with ``sync_group_late_after``, which then moves slow members on; passing a number or a
        function together with ``sync_group_late_after`` raises an error. ``None`` means no limit.

    sync_group_max_wait_action
        What happens to a member who waits longer than ``sync_group_max_wait_time``: ``"fail"``
        (default) fails them and sends them to the end of the experiment; ``"leave_group"`` removes them
        from the group, and they get no more trials from this trial maker, or skip the rest of it if
        they haven't finished a trial (see :ref:`sync-leaving-a-group`).

    sync_group_late_after
        Acts on members who haven't reached the trial maker's barrier yet: the longest each may
        take to reach it, in seconds, counted from the group's previous barrier pass or from when
        they joined the group, whichever is later, before ``sync_group_late_action`` is applied
        to them. ``None`` (default) never treats anyone as late. See ``late_after`` in
        :class:`~psynet.sync.GroupBarrier`.

    sync_group_late_action
        What happens to a member who is later than ``sync_group_late_after``: ``"fail"``
        (default) fails them; ``"leave_group"`` removes them from the group, so the rest can go on
        without them (see :ref:`sync-leaving-a-group`); ``"leave_all_groups"`` also removes them
        from their other groups.

    sync_group_waiting_message
        Message on the waiting indicator at the trial maker's own sync-group waits
        (initialization and trial preparation). If omitted, participants see "Waiting for other
        participants…". :class:`~psynet.sync.Grouper` and :class:`~psynet.sync.GroupBarrier`
        elements use their own ``waiting_message``; pass the same text to them if the messages
        should match.

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
        How long an async job may run before it times out, in seconds
        (default = 300), counted from when the job starts running, not
        from when it is queued.
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
        longer have any pending async jobs, and until trials that are ready
        to finalize have been finalized (so their scores are set).

    performance_threshold : float (default = -1.0)
        Threshold for the built-in performance check chosen by ``performance_check_type``.
        The participant passes when the score (the summed trial scores, the proportion
        of non-failed trials, or the consistency) is at least this value.
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
        sync_group_max_wait_time: Optional[Union[float, Callable]] = NoArgumentProvided,
        sync_group_max_wait_action: Literal["fail", "leave_group"] = "fail",
        sync_group_late_after: Optional[float] = None,
        sync_group_late_action: LateAction = "fail",
        sync_group_waiting_message=None,
        n_participants_completion: Literal["experiment", "trial_maker"] = "experiment",
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
            sync_group_late_after=sync_group_late_after,
            sync_group_late_action=sync_group_late_action,
            sync_group_waiting_message=sync_group_waiting_message,
            n_participants_completion=n_participants_completion,
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
                warn_from_caller(message, DeprecationWarning)

    def _selection_hook_overrides(self):
        """Return obsolete or wrong-paradigm hooks and their replacements."""
        return []

    def _deprecated_selection_hooks(self):
        """Return still-honoured hooks that should be migrated."""
        return []

    @log_time_taken
    def prepare_trial(self, experiment, participant: Participant):
        logger.debug("Preparing trial for participant %i.", participant.id)

        full_node_ids = set()
        while True:
            selection = self._select_trial_node(participant, experiment)
            if isinstance(selection, str):
                if selection not in ["wait", "exit"]:
                    raise ValueError(
                        "_select_trial_node must return Selection, 'wait', or 'exit'"
                    )
                logger.debug("Outcome of trial selection: %s", selection)
                return None, selection
            if not isinstance(selection, Selection):
                raise TypeError(
                    "_select_trial_node must return Selection, 'wait', or 'exit'"
                )
            if self._claim_node_capacity(selection.value):
                break
            if selection.value.id in full_node_ids:
                raise RuntimeError(
                    f"Node {selection.value.id} was selected again after it was "
                    "found to be full. Custom discovery hooks must not return "
                    "nodes without remaining trial capacity."
                )
            full_node_ids.add(selection.value.id)
            logger.debug(
                "Node %i filled up during selection; selecting again.",
                selection.value.id,
            )

        node = selection.value
        logger.debug(
            "Selected node %i from network %i to give to participant %i.",
            node.id,
            node.network_id,
            participant.id,
        )
        trial = self._create_trial(
            node=node,
            participant=participant,
            experiment=experiment,
        )
        self._on_node_claimed(node, participant)
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

    def _claim_node_capacity(self, node):
        """Reserve capacity on the selected node, returning ``False`` if it is full."""
        return True

    def _on_node_claimed(self, node, participant):
        """Apply participant state changes once a trial has been created on the node."""
        pass

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
        from psynet.experiment import get_experiment

        experiment = get_experiment()
        with forbid_commits(f"{type(self).__name__}.grow_network"):
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
        WorkerAsyncJob(
            network.call_async_post_grow_network,
            label="post_grow_network",
            timeout=self.async_timeout_sec,
            network=network,
            # Participants may wait for the network's next node.
            priority="high",
        ).enqueue()

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

    def __repr__(self):
        return ("<Network-{}-{} with {} nodes>").format(
            self.id, self.type, len(self.alive_nodes)
        )

    trial_maker_id = Column(String, index=True)
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
        secondary="trial",
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

    all_trials = relationship(
        "psynet.trial.main.Trial",
        foreign_keys="psynet.trial.main.Trial.network_id",
        back_populates="network",
    )

    @property
    def alive_nodes(self):
        return [node for node in self.all_nodes if not node.failed]

    @property
    def failed_nodes(self):
        return [node for node in self.all_nodes if node.failed]

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

    async_jobs = relationship("AsyncJob")
    async_processes = _deprecated_async_processes

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
    trial_maker_id = Column(String, index=True)
    module_id = Column(String, index=True)
    module_state_id = Column(Integer, ForeignKey("module_state.id"), index=True)
    is_global = Column(Integer, ForeignKey("experiment.id"), index=True)
    definition = Column(PythonObject, default=lambda: {})

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
    async_jobs = relationship("AsyncJob")
    async_processes = _deprecated_async_processes

    asset_links = relationship(
        "AssetNode",
        collection_class=attribute_mapped_collection("local_key"),
        cascade="all, delete-orphan",
    )

    assets = association_proxy(
        "asset_links", "asset", creator=lambda k, v: AssetNode(local_key=k, asset=v)
    )

    errors = relationship("ErrorRecord")

    all_trials = relationship(
        "psynet.trial.main.Trial",
        foreign_keys=[Trial.node_id],
        back_populates="node",
    )

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

    @property
    def failure_cascade(self):
        # Trials are no longer Dallinger Infos, so Node.infos is empty for them.
        # Fail associated trials explicitly when the node fails.
        return [lambda: self.alive_trials]

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
        WorkerAsyncJob(
            function=self.call_async_on_deploy,
            node=self,
            timeout=self.trial_maker.async_timeout_sec,
            unique=True,
            # Participants may wait for this node to be deployed.
            priority="high",
        ).enqueue()
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


def _lock_until_commit(key):
    """Wait for, then hold until the transaction ends, a PostgreSQL advisory lock on ``key``."""
    _execute_advisory_xact_lock(db.session, key, wait=True)


def _record_sync_group(trial, participant, group, round_number=None):
    """Save ``group``, the participant's role in it and, if given, the round on ``trial``."""
    trial.sync_group_id = group.id
    if round_number is not None:
        trial.sync_group_round = round_number
    link = ParticipantLinkSyncGroup.query.filter_by(
        participant_id=participant.id, sync_group_id=group.id, active=True
    ).one_or_none()
    trial.sync_group_role = None if link is None else link.role


def _cued_trial_position(participant):
    """Return how many trials ``participant`` already has in their current module."""
    module_state = participant.module_state
    if module_state is None:
        return None
    return Trial.query.filter(
        Trial.participant_id == participant.id, Trial.module_state == module_state
    ).count()


class GenericTrialNetwork(TrialNetwork):
    """The network holding a module's nodes for trials made by :meth:`Trial.cue`."""

    trials_per_node = None

    def __init__(self, module_id, experiment):
        super().__init__(
            trial_maker_id=None,
            module_id=module_id,
            experiment=experiment,
        )

    def grow(self, experiment):
        pass

    @classmethod
    def for_module(cls, module_id, experiment):
        """Return the module's network, creating it if needed."""

        def find():
            return (
                cls.query.filter_by(module_id=module_id, trial_maker_id=None)
                .order_by(cls.id)
                .first()
            )

        network = find()
        if network is None:
            _lock_until_commit(f"generic_trial_network:{module_id}")
            network = find()
        if network is None:
            network = cls(module_id, experiment)
            db.session.add(network)
        return network


class GenericTrialNode(TrialNode):
    """A node for trials made by :meth:`Trial.cue`, which have no trial maker."""

    def __init__(self, module_id, experiment):
        super().__init__(
            network=self.get_default_network(module_id, experiment),
            participant=None,
        )

    def get_default_network(self, module_id, experiment):
        """Return the module's network for cued trials, creating it if needed."""
        return GenericTrialNetwork.for_module(module_id, experiment)


class SyncGroupNode(GenericTrialNode):
    """The node shared by a sync group's cued trials in one round.

    :meth:`Trial.cue` creates one per module, group and round for a trial class
    with ``sync_group_type``, numbering a group's rounds from 0. Its
    ``definition`` is every trial's definition in the round, and ``var`` is
    the place for the group's results, for example those that a
    :class:`~psynet.sync.GroupBarrier`'s ``on_release`` computes.

    Cued trials take ``sync_group_round`` from this node, while trial makers
    with ``sync_group_type`` compute it from their own trials.
    """

    # No foreign key, as on Trial.sync_group_id.
    sync_group_id = Column(Integer, index=True)
    sync_group_round = Column(Integer)
    # Set when a GroupBarrier releases the group with all its trials here,
    # after which the round takes no members who have no trial on it. Set
    # under the round lock that for_cue holds, so a cue reads it consistently.
    sync_group_closed = Column(Boolean, default=False)

    def __init__(self, module_id, experiment, group, round_number, definition):
        super().__init__(module_id, experiment)
        self.sync_group_id = group.id
        self.sync_group_round = round_number
        self.definition = definition

    @property
    def sync_group(self) -> Optional[SyncGroup]:
        """The :class:`~psynet.sync.SyncGroup` whose round this node holds."""
        return db.session.get(SyncGroup, self.sync_group_id)

    @staticmethod
    def _round_is_open(node, participant):
        """Whether ``participant``'s cue may join ``node`` as a newcomer to that round.

        ``node`` is the group's newest round for an automatic cue, or the
        round a cue's ``round`` names, which may be a past one.
        """
        played = Trial.query.filter_by(node_id=node.id, participant_id=participant.id)
        return played.first() is None and not node.sync_group_closed

    @classmethod
    def for_cue(
        cls, group, round_number, participant, experiment, make_definition, trial_class
    ):
        """Return the node that ``participant``'s cued trial joins, creating it if needed.

        Without ``round_number``, this is the group's newest node in the module
        while that round is open and the participant has no trial on it. A
        round is open until a :class:`~psynet.sync.GroupBarrier` releases the
        group with all its trials on the node, which sets
        ``sync_group_closed``; a round without such a barrier never closes.
        Otherwise the group moves on to a new node for the next round,
        counted from 0, which the others then join.
        With ``round_number``, it is the group's node for that round, or
        ``None`` if it is no longer open and the participant isn't playing it,
        as when the group finished it without them, or if they have a trial
        of ``trial_class`` on it from before they left and rejoined the
        group. Naming a round when
        the participant has run this module before raises a
        ``RuntimeError``, because the group's nodes for the module would be
        reused; so does naming a round in which they already have a trial of
        ``trial_class``, or one before a round they played or skipped (see
        :meth:`_named_round`).
        ``trial_class`` is the class of the cued trial. A new node's
        definition is ``make_definition(round_number)``. Either way, the
        participant's link to ``group`` records the round as the one they
        last cued or skipped, for :class:`~psynet.sync.GroupBarrier` to tell
        whom a round's barriers wait for.

        The group's members cue their trials in parallel requests, so this
        holds an advisory lock on the module and group until the request
        commits; the others then find the node it made.
        """
        module_id = participant.module_id
        _lock_until_commit(f"sync_group_node:{module_id}:{group.id}")
        # Re-read under the lock what another request may have just committed.
        db.session.expire(group, ["participant_links"])
        nodes = cls.query.filter_by(module_id=module_id, sync_group_id=group.id)
        if round_number is None:
            newest = (
                nodes.order_by(cls.sync_group_round.desc()).populate_existing().first()
            )
            if newest is None:
                round_number = 0
            elif cls._round_is_open(newest, participant):
                _record_round_position(group, participant, newest)
                return newest
            else:
                round_number = newest.sync_group_round + 1
        else:
            if len(participant.module_states.get(module_id, [])) > 1:
                raise RuntimeError(
                    f"Participant {participant.id} cued round {round_number} of "
                    f"'{group.group_type}' group {group.id} in module "
                    f"'{module_id}' again: the participant has run this module "
                    "before. A module whose cues pass round= can run only once "
                    "per participant; give each run of it its own module id."
                )
            node = (
                nodes.filter_by(sync_group_round=round_number)
                .populate_existing()
                .one_or_none()
            )
            if node is not None:
                return cls._named_round(node, group, participant, trial_class)
        node = cls(
            module_id, experiment, group, round_number, make_definition(round_number)
        )
        db.session.add(node)
        node.check_on_deploy()
        db.session.flush()
        _record_round_position(group, participant, node)
        return node

    @classmethod
    def _named_round(cls, node, group, participant, trial_class):
        """Return ``node``, a round named by ``round=``, or ``None`` if the participant skips it.

        Raises a ``RuntimeError`` if the participant has a trial of
        ``trial_class`` on the round they are playing, or their stored round
        in this module is one played after it, whether they played or
        skipped either. So a skip never moves their stored round back.
        A member who left and rejoined the group has no stored round, so
        they skip a round in which they already have a trial of
        ``trial_class``, like a closed round.
        """
        link = _member_link(group, participant)
        stored = link.round_node_id and db.session.get(cls, link.round_node_id)
        playing = link.round_node_id == node.id and not link.skipped_round
        played_after = (
            stored and stored.module_id == node.module_id and stored.id > node.id
        )
        has_trial = (
            trial_class.query.filter_by(
                node_id=node.id, participant_id=participant.id
            ).first()
            is not None
        )
        if played_after or (playing and has_trial):
            raise RuntimeError(
                f"Participant {participant.id} cued {trial_class.__name__} for "
                f"round {node.sync_group_round} of '{group.group_type}' group "
                f"{group.id} again in module '{node.module_id}', after it or a "
                "later round. A round takes one trial of each class, and "
                "can't be cued after a round played after it."
            )
        if playing:
            # Another trial class cued in the round the participant is playing.
            return node
        if not node.sync_group_closed and not has_trial:
            _record_round_position(group, participant, node)
            return node
        _record_round_position(group, participant, node, skipped=True)
        return None


def _member_link(group, participant):
    """Return ``participant``'s active link to ``group``."""
    return next(
        link
        for link in group.participant_links
        if link.active and link.participant_id == participant.id
    )


def _record_round_position(group, participant, node, skipped=False):
    """Store ``node`` as the round of ``group`` that ``participant`` last cued or skipped."""
    link = _member_link(group, participant)
    link.round_node_id = node.id
    link.skipped_round = skipped


# SyncGroupNode shares the node table, and SQLAlchemy doesn't accept
# __table_args__ on a single-table subclass, so the constraint is added here.
UniqueConstraint(
    SyncGroupNode.module_id, SyncGroupNode.sync_group_id, SyncGroupNode.sync_group_round
)
