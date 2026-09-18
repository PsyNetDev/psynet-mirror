# pylint: disable=attribute-defined-outside-init

import io
import json
import os
import re
import shutil
import tempfile
import time
import zipfile
from contextlib import ExitStack
from smtplib import SMTPAuthenticationError
from typing import TYPE_CHECKING, Dict

import dallinger.models
import requests
from dallinger import db
from dallinger.notifications import admin_notifier
from sqlalchemy import (
    Boolean,
    Column,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    desc,
)
from sqlalchemy.ext.associationproxy import association_proxy
from sqlalchemy.orm import relationship
from sqlalchemy.orm.collections import attribute_mapped_collection
from tenacity import Retrying, stop_after_attempt, wait_exponential

from psynet.db import transaction
from psynet.timeline import Page

from .asset import AssetParticipant
from .data import SQLMixinDallinger
from .field import PythonList, PythonObject, extra_var
from .utils import (
    NoArgumentProvided,
    call_function_with_context,
    get_config,
    get_logger,
    organize_by_key,
)

logger = get_logger()


def _extract_server_error_details(response_text):
    """Pull a useful exception message out of an HTTP error response body."""
    if not response_text:
        return None

    from .timeline import _SPA_INCOMPATIBILITY_MARKER

    spa_match = re.search(
        r"Page '[^']+' uses HTML/JS that needs a full browser reload.*?"
        + re.escape(_SPA_INCOMPATIBILITY_MARKER),
        response_text,
        flags=re.DOTALL,
    )
    if spa_match:
        return re.sub(r"[ \t]+\n", "\n", spa_match.group(0)).strip()

    value_error_match = re.search(
        r"ValueError:\s*(.+?)(?:\n\s*File \"|\n\s*</|\Z)",
        response_text,
        flags=re.DOTALL,
    )
    if value_error_match:
        return "ValueError: " + value_error_match.group(1).strip()

    return None


def _raise_for_status_with_server_details(response):
    """Like ``Response.raise_for_status``, but include useful server details."""
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        details = _extract_server_error_details(response.text)
        if details:
            raise requests.HTTPError(
                f"{exc}\n\nServer error details:\n{details}",
                response=response,
            ) from None
        raise


if TYPE_CHECKING:
    from .sync import SyncGroup
    from .timeline import Module

# pylint: disable=unused-import

UniqueConstraint(dallinger.models.Participant.worker_id)
UniqueConstraint(dallinger.models.Participant.unique_id)


class Participant(SQLMixinDallinger, dallinger.models.Participant):
    """
    Represents an individual participant taking the experiment.
    The object is linked to the database - when you make changes to the
    object, it should be mirrored in the database.

    Users should not have to instantiate these objects directly.

    The class extends the ``Participant`` class from base Dallinger
    (:class:`dallinger.models.Participant`) to add some useful features,
    in particular the ability to store arbitrary variables.

    The following attributes are recommended for external use:

    * :attr:`~psynet.participant.Participant.answer`
    * :attr:`~psynet.participant.Participant.var`
    * :attr:`~psynet.participant.Participant.failure_tags`

    The following method is recommended for external use:

    * :meth:`~psynet.participant.Participant.append_failure_tags`

    See below for more details.

    Attributes
    ----------

    id : int
        The participant's unique ID.

    elt_id : list
        Represents the participant's position in the timeline.
        Should not be modified directly.
        The position is represented as a list, where the first element corresponds
        to the index of the participant within the timeline's underlying
        list representation, and successive elements (if any) represent
        the participant's position within (potentially nested) page makers.
        For example, ``[10, 3, 2]`` would mean go to
        element 10 in the timeline (0-indexing),
        which must be a page maker;
        go to element 3 within that page maker, which must also be a page maker;
        go to element 2 within that page maker.

    elt_bounds : list
        Represents the number of elements at each level of the current
        ``elt_id`` hierarchy; used to work out when to leave a page maker
        and go up to the next level.
        Should not be modified directly.

    page_uuid : str
        A long unique string that is randomly generated when the participant advances
        to a new page, used as a passphrase to guarantee the security of
        data transmission from front-end to back-end.
        Should not be modified directly.

    page_count : int
        The number of pages that the participant has advanced through.
        Should not be modified directly.

    complete : bool
        Whether the participant has successfully completed the experiment.
        A participant is considered to have successfully completed the experiment
        once they hit a :class:`~psynet.timeline.SuccessfulEndPage`.
        Should not be modified directly.

    aborted : bool
        Whether the participant has aborted the experiment.
        A participant is considered to have aborted the experiment
        once they have hit the "Abort experiment" button on the "Abort experiment" confirmation page.

    answer : object
        The most recent answer submitted by the participant.
        Can take any form that can be automatically serialized to JSON.
        Should not be modified directly.

    response : Response
        An object of class :class:`~psynet.timeline.Response`
        providing detailed information about the last response submitted
        by the participant. This is a more detailed version of ``answer``.

    branch_log : list
        Stores the conditional branches that the participant has taken
        through the experiment.
        Should not be modified directly.

    failure_tags : list
        Stores tags that identify the reason that the participant has failed
        the experiment (if any). For example, if a participant fails
        a microphone pre-screening test, one might add "failed_mic_test"
        to this tag list.
        Should be modified using the method :meth:`~psynet.participant.Participant.append_failure_tags`.

    var : :class:`~psynet.field.VarStore`
        A repository for arbitrary variables; see :class:`~psynet.field.VarStore` for details.

    progress : float [0 <= x <= 1]
        The participant's estimated progress through the experiment.

    client_ip_address : str
        The participant's IP address as reported by Flask.

    answer_is_fresh : bool
        ``True`` if the current value of ``participant.answer`` (and similarly ``participant.last_response_id`` and
        ``participant.last_response``) comes from the last page that the participant saw, ``False`` otherwise.

    browser_platform : str
        Information about the participant's browser version and OS platform.

    all_trials : list
        A list of all trials for that participant.

    alive_trials : list
        A list of all non-failed trials for that participant.

    failed_trials : list
        A list of all failed trials for that participant.
    """

    # We set the polymorphic_identity manually to differentiate the class
    # from the Dallinger Participant class.
    __extra_vars__ = {}

    _in_advance_page = False

    elt_id = Column(PythonList)
    elt_id_max = Column(PythonList)

    time_credit = Column(Float)
    estimated_max_time_credit = Column(Float)
    progress = Column(Float)

    # If time_credit_fixes is non-empty, then the last element of time_credit_fixes
    # is used as the currently active time credit 'fix'. While this fix is active,
    # the participant's time credit will not be allowed to increase above this number.
    # Once the fix expires, the participant's time credit will be set to that number exactly.
    # See ``psynet.timeline.with_fixed_time_credit`` for an explanation.
    time_credit_fixes = Column(PythonList)
    # progress_fixes is analogous to time_credit_fixes, but for progress.
    progress_fixes = Column(PythonList)

    page_uuid = Column(String)
    page_count = Column(Integer)
    aborted = Column(Boolean)
    complete = Column(Boolean)
    pending_redirect = Column(String)
    answer = Column(PythonObject)
    answer_accumulators = Column(PythonList)
    sequences = Column(PythonList)
    branch_log = Column(PythonObject)
    for_loops = Column(PythonObject)
    failure_tags = Column(PythonList)

    base_payment = Column(Float)
    performance_reward = Column(Float)
    unpaid_bonus = Column(Float)
    total_wait_page_time = Column(Float)
    client_ip_address = Column(String, default=lambda: "")
    answer_is_fresh = Column(Boolean, default=False)
    browser_platform = Column(String, default="")
    module_state_id = Column(Integer, ForeignKey("module_state.id"))
    module_state = relationship(
        "ModuleState", foreign_keys=[module_state_id], post_update=True, lazy="selectin"
    )
    current_trial_id = Column(Integer, ForeignKey("info.id"))
    _current_trial = relationship(
        "psynet.trial.main.Trial", foreign_keys=[current_trial_id], lazy="joined"
    )
    trial_status = Column(String)

    all_responses = relationship("psynet.timeline.Response")

    awaited_async_code_block_process_id = Column(Integer, ForeignKey("process.id"))
    awaited_async_code_block_process = relationship(
        "AsyncProcess", foreign_keys=[awaited_async_code_block_process_id]
    )

    @property
    def current_trial(self):
        """
        This property is used to deal with some flakiness we've seen in the
        underlying SQLAlchemy relationship. For some unclear reason, we sometimes
        end up in a situation where the foreign key current_trial_id is not None,
        but the _current_trial attribute is (incorrectly) None. The following code
        detects this situation and retries loading the attribute a few times.
        """
        # Ideally, the _current_trial relationship is being loaded properly.
        # If we do see a trial there, we can just return it.
        if self._current_trial is not None:
            return self._current_trial

        # If both _current_trial and current_trial_id are None, that suggests
        # there is truly no current trial. We can therefore return None.
        if self.current_trial_id is None:
            return None

        # If we got here, that means that current_trial_id is not None,
        # but _current_trial is None. This suggests that the trial is not
        # loaded properly. We can therefore try to load it again.
        retrying = Retrying(
            stop=stop_after_attempt(4),
            wait=wait_exponential(multiplier=0.1, min=0.1, max=0.5),
            reraise=True,
        )
        for attempt in retrying:
            with attempt:
                logger.warning(
                    f"Failed to load participant [{self.id}]'s current_trial attribute, will wait a moment and retry..."
                )
                db.session.expire(self, ["_current_trial"])
                if self._current_trial is None:
                    raise RuntimeError(
                        "The _current_trial attribute is None even though current_trial_id is not None"
                    )
        logger.warning(
            f"Successfully loaded participant [{self.id}]'s current_trial attribute."
        )
        return self._current_trial

    @current_trial.setter
    def current_trial(self, value):
        if value is None:
            self.current_trial_id = None
        else:
            self.current_trial_id = value.id

        self._current_trial = value

    @property
    def current_node(self):
        if self.current_trial is None:
            return None
        return self.current_trial.node

    @property
    def last_response(self):
        return self.response

    # all_trials = relationship("psynet.trial.main.Trial")

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

    # This would be better, but we end up with a circular import problem
    # if we try and read csv files using this foreign key...
    #
    # last_response = relationship(
    #     "psynet.timeline.Response", foreign_keys=[last_response_id]
    # )

    # current_trial_id = Column(
    #     Integer, ForeignKey("info.id")
    # )  # 'info.id' because trials are stored in the info table

    # This should work but it's buggy, don't know why.
    # current_trial = relationship(
    #     "psynet.trial.main.Trial",
    #     foreign_keys="[psynet.participant.Participant.current_trial_id]",
    # )
    #
    # Instead we resort to the below...

    # @property
    # def current_trial(self):
    #     from dallinger.models import Info
    #
    #     # from .trial.main import Trial
    #
    #     if self.current_trial_id is None:
    #         return None
    #     else:
    #         # We should just be able to use Trial for the query, but using Info seems
    #         # to avoid an annoying SQLAlchemy bug that comes when we run multiple demos
    #         # in one session. When this happens, what we see is that Trial.query.all()
    #         # sees all trials appropriately, but Trial.query.filter_by(id=1).all() fails.
    #         #
    #         # return Trial.query.filter_by(id=self.current_trial_id).one()
    #         return Info.query.filter_by(id=self.current_trial_id).one()
    #
    # @current_trial.setter
    # def current_trial(self, trial):
    #     from psynet.trial.main import Trial
    #     self.current_trial_id = trial.id if isinstance(trial, Trial) else None

    asset_links = relationship(
        "AssetParticipant",
        collection_class=attribute_mapped_collection("local_key"),
        cascade="all, delete-orphan",
    )

    assets = association_proxy(
        "asset_links",
        "asset",
        creator=lambda k, v: AssetParticipant(local_key=k, asset=v),
    )

    # sync_group_links and sync_groups are defined in sync.py
    # because of import-order necessities

    # sync_groups is a relationship that gives a list of all SyncGroups for that participnat

    @property
    def active_sync_groups(self) -> Dict[str, "SyncGroup"]:
        return {group.group_type: group for group in self.sync_groups if group.active}

    @property
    def sync_group(self) -> "SyncGroup":
        candidates = self.active_sync_groups
        if len(candidates) == 1:
            return list(candidates.values())[0]
        elif len(candidates) == 0:
            return None
        elif len(candidates) > 1:
            raise RuntimeError(
                f"Participant {self.id} is in more than one SyncGroup: "
                f"{list(self.active_sync_groups)}. "
                "Use participant.active_sync_groups[group_type] to access the SyncGroup you need."
            )

    active_barriers = relationship(
        "ParticipantLinkBarrier",
        collection_class=attribute_mapped_collection("barrier_id"),
        cascade="all, delete-orphan",
        primaryjoin=(
            "and_(psynet.participant.Participant.id==remote(ParticipantLinkBarrier.participant_id), "
            "ParticipantLinkBarrier.released==False)"
        ),
        lazy="selectin",
    )

    errors = relationship("ErrorRecord")
    # _module_states = relationship("ModuleState", foreign_keys=[dallinger.models.Participant.id], lazy="selectin")

    @property
    def module_states(self):
        return organize_by_key(
            self._module_states,
            key=lambda x: x.module_id,
            sort_key=lambda x: x.time_started,
        )

    def select_module(self, module_id: str):
        candidates = [
            state
            for state in self._module_states
            if not state.finished and state.module_id == module_id
        ]
        assert len(candidates) == 1
        self.module_state = candidates[0]

    @property
    def globals(self):
        raise RuntimeError(
            "The .globals attribute has been removed, please use .var instead."
        )

    @property
    def locals(self):
        raise RuntimeError(
            "The .locals attribute has been removed, please use .module_state.var instead."
        )

    def locals_to_dict(self):
        raise RuntimeError(
            "The .locals_to_dict() method has been removed because module-local variables are no longer flattened into participant exports."
        )

    @property
    @extra_var(__extra_vars__)
    def aborted_modules(self):
        return [
            log.module_id
            for log in sorted(self._module_states, key=lambda x: x.time_started)
            if log.aborted
        ]

    @property
    @extra_var(__extra_vars__)
    def started_modules(self):
        return [
            log.module_id
            for log in sorted(self._module_states, key=lambda x: x.time_started)
            if log.started
        ]

    @property
    @extra_var(__extra_vars__)
    def finished_modules(self):
        return [
            log.module_id
            for log in sorted(self._module_states, key=lambda x: x.time_started)
            if log.finished
        ]

    def start_module(self, module: "Module"):
        self.check_module_not_already_started(module)
        state = module.state_class(module, self)
        state.start()
        self.module_state = state

    def check_module_not_already_started(self, module: "Module"):
        if module.id not in self.module_states:
            return
        else:
            states = self.module_states[module.id]
            for state in states:
                if not state.finished:
                    raise RuntimeError(
                        f"Participant already has an unfinished module state for '{module.id}'..."
                    )

    def end_module(self, module):
        # This should only fail (delivering multiple logs) if the experimenter has perversely
        # defined a recursive module (or is reusing module ID)
        state = [
            _state for _state in self.module_states[module.id] if not _state.finished
        ]

        if len(state) == 0:
            raise RuntimeError(
                f"Participant had no unfinished module states with id = '{module.id}'."
            )
        elif len(state) > 1:
            raise RuntimeError(
                (
                    f"Participant had multiple unfinished module states with id = '{module.id}': "
                    f"{[s.__json__() for s in state]}, participant: {self.__json__()}"
                )
            )

        state = state[0]
        state.finish()
        self.refresh_module_state()

    def refresh_module_state(self):
        if len(self._module_states) == 0:
            self.module_state = None
        else:
            unfinished = [x for x in self._module_states if not x.finished]
            unfinished.sort(key=lambda x: x.time_started)
            if len(unfinished) == 0:
                self.module_state = None
            else:
                self.module_state = unfinished[-1]

    @property
    def in_module(self):
        return self.module_state is not None

    @property
    @extra_var(__extra_vars__)
    def module_id(self):
        if self.module_state:
            return self.module_state.module_id

    def set_answer(self, value):
        self.answer = value
        return self

    def __init__(self, experiment, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.page_count = 0
        self.aborted = False
        self.complete = False
        self.vars = {}
        self.time_credit = 0.0
        self.estimated_max_time_credit = (
            experiment.timeline.estimated_time_credit.get_max("time")
        )
        self.progress = 0.0
        self.time_credit_fixes = []
        self.progress_fixes = []
        self.elt_id = ["main", -1]
        self.elt_id_max = []
        self.answer_accumulators = []
        self.for_loops = {}
        self.failure_tags = []
        self.sequences = []
        self.complete = False
        self.performance_reward = 0.0
        self.unpaid_bonus = 0.0
        self.base_payment = experiment.base_payment
        self.client_ip_address = None
        self.branch_log = []
        self.total_wait_page_time = 0.0
        self.pending_redirect = None

        db.session.add(self)

        self.initialize(
            experiment
        )  # Hook for custom subclasses to provide further initialization

    def initialize(self, experiment):
        pass

    @property
    def locale(self):
        return self.var.get("locale", default=None)

    @property
    def failure_cascade(self):
        """Return no owned objects. ``failed`` is not an ownership marker."""
        return []

    @property
    def gettext(self):
        return self.translator[0]

    @property
    def pgettext(self):
        return self.translator[1]

    @property
    def time_reward(self):
        wage_per_hour = get_config().get("wage_per_hour")
        seconds = self.time_credit
        hours = seconds / 3600
        return hours * wage_per_hour

    def calculate_reward(self):
        """
        Calculates and returns the currently accumulated reward for the given participant.

        :returns:
            The reward as a ``float``.
        """
        return round(
            self.time_reward + self.performance_reward,
            ndigits=2,
        )

    def inc_time_credit(self, time_credit: float):
        new_value = self.time_credit + time_credit
        new_value = min([new_value, *self.time_credit_fixes])
        self.time_credit = new_value

    def inc_progress(self, time_credit: float):
        if self.estimated_max_time_credit == 0.0:
            new_value = 1.0
        else:
            new_value = self.progress + time_credit / self.estimated_max_time_credit
            new_value = min([new_value, *self.progress_fixes])
        self.progress = new_value

    def inc_performance_reward(self, value):
        self.performance_reward += value

    def amount_paid(self):
        return (0.0 if self.base_payment is None else self.base_payment) + (
            0.0 if self.bonus is None else self.bonus
        )

    def send_email_max_payment_reached(
        self, experiment_class, requested_reward, reduced_reward
    ):
        config = get_config()
        template = """Dear experimenter,

            This is an automated email from PsyNet. You are receiving this email because
            the total amount paid to the participant with assignment_id '{assignment_id}'
            has reached the maximum of {max_participant_payment}$. The reward paid was {reduced_reward}$
            instead of a requested reward of {requested_reward}$.

            The application id is: {app_id}

            To see the logs, use the command "dallinger logs --app {app_id}"
            To pause the app, use the command "dallinger hibernate --app {app_id}"
            To destroy the app, use the command "dallinger destroy --app {app_id}"

            The PsyNet developers.
            """
        message = {
            "subject": "Maximum experiment payment reached.",
            "body": template.format(
                assignment_id=self.assignment_id,
                max_participant_payment=experiment_class.var.max_participant_payment,
                requested_reward=requested_reward,
                reduced_reward=reduced_reward,
                app_id=config.get("id"),
            ),
        }
        logger.info(
            f"Recruitment ended. Maximum amount paid to participant "
            f"with assignment_id '{self.assignment_id}' reached!"
        )
        try:
            admin_notifier(config).send(**message)
        except SMTPAuthenticationError as e:
            logger.error(
                f"SMTPAuthenticationError sending 'max_participant_payment' reached email: {e}"
            )
        except Exception as e:
            logger.error(
                f"Unknown error sending 'max_participant_payment' reached email: {e}"
            )

    @property
    def response(self):
        from .timeline import Response

        return (
            Response.query.filter_by(participant_id=self.id)
            .order_by(desc(Response.id))
            .first()
        )

    def append_branch_log(self, entry: str):
        # We need to create a new list otherwise the change may not be recognized
        # by SQLAlchemy(?)
        if (
            not isinstance(entry, list)
            or len(entry) != 2
            or not isinstance(entry[0], str)
        ):
            raise ValueError(
                f"Log entry must be a list of length 2 where the first element is a string (received {entry})."
            )
        if json.loads(json.dumps(entry)) != entry:
            raise ValueError(
                f"The provided log entry cannot be accurately serialised to JSON (received {entry}). "
                + "Please simplify the log entry (this is typically determined by the output type of the user-provided function "
                + "in switch() or conditional())."
            )
        self.branch_log = self.branch_log + [entry]

    def append_failure_tags(self, *tags):
        """
        Appends tags to the participant's list of failure tags.
        Duplicate tags are ignored.
        See :attr:`~psynet.participant.Participant.failure_tags` for details.

        Parameters
        ----------

        *tags
            Tags to append.

        Returns
        -------

        :class:`psynet.participant.Participant`
            The updated ``Participant`` object.

        """
        original = self.failure_tags
        new = [*tags]
        combined = list(set(original + new))
        self.failure_tags = combined
        return self

    def abort_info(self):
        """
            Information that will be shown to a participant if they click the abort button,
            e.g. in the case of an error where the participant is unable to finish the experiment.

        :returns: ``dict`` which may be rendered to the worker as an HTML table
            when they abort the experiment.
        """
        return {
            "assignment_id": self.assignment_id,
            "hit_id": self.hit_id,
            "accumulated_reward": "$" + "{:.2f}".format(self.calculate_reward()),
        }

    def fail(self, reason=None):
        """
        Mark this participant as failed.

        Incomplete trials are failed here. Completed trials stay unless a
        TrialMaker performance-check policy treats them as unusable. A
        completed participant can still be failed; they are not redirected
        off the successful-end page. Already-failed calls are a no-op.

        If they are still on the main timeline, they are redirected to
        ``unsuccessful_end``. They are also removed from active sync groups.
        If that drops a ``SimpleSyncGroup`` below its minimum size, remaining
        members are failed immediately when
        ``fail_participants_below_min_size`` is True. See
        :doc:`/tutorials/participant_and_trial_failure`.

        Parameters
        ----------
        reason : str, optional
            Failure tag to append, for example ``"premature_exit"``.
        """
        if self.failed:
            logger.info("Participant %i already failed, not failing again.", self.id)
            return

        if reason is not None:
            self.append_failure_tags(reason)
        reason = ", ".join(self.failure_tags)

        logger.info(
            "Failing participant %i (reason: %s)",
            self.id,
            reason,
        )

        from psynet.experiment import get_experiment

        exp = get_experiment()

        self._fail_incomplete_trials(reason)

        for i, routine in enumerate(exp.participant_fail_routines):
            logger.info(
                "Executing fail routine %i/%i ('%s')...",
                i + 1,
                len(exp.participant_fail_routines),
                routine.label,
            )
            call_function_with_context(
                routine.function,
                participant=self,
                experiment=exp,
            )

        super().fail(reason=reason)

        for group in list(self.active_sync_groups.values()):
            group.remove_participant(self)

        self._redirect_to_unsuccessful_end(exp)

    def _fail_incomplete_trials(self, reason):
        """Fail this participant's unfinished trials.

        Includes the trial currently on screen and trials not owned by a
        timeline TrialMaker. Completed trials are left to TrialMaker
        performance-check policy.
        """
        from psynet.trial.main import Trial

        trials = (
            Trial.query.filter_by(participant_id=self.id, failed=False)
            .filter(Trial.complete.is_not(True))
            .order_by(Trial.id)
            .with_for_update(of=Trial)
            .populate_existing()
            .all()
        )
        for trial in trials:
            trial.fail(reason=reason)

    def _redirect_to_unsuccessful_end(self, experiment):
        # Queued redirect is navigation only. Incomplete trials, including the
        # one on screen, have already been failed.
        if self.complete or experiment.timeline.participant_is_in_end_logic(self):
            return

        if self._in_advance_page:
            logger.info(
                "Redirecting participant %i to unsuccessful_end branch.",
                self.id,
            )
            experiment.timeline.redirect_to_branch(experiment, self, "unsuccessful_end")
        else:
            logger.info(
                "Queuing redirect for participant %i to unsuccessful_end branch.",
                self.id,
            )
            self.pending_redirect = "unsuccessful_end"


def get_participant(participant_id: int, for_update: bool = False) -> Participant:
    """
    Returns the participant with a given ID.
    Warning: we recommend just using SQLAlchemy directly instead of using this function.
    When doing so, use ``with_for_update().populate_existing()`` if you plan to update
    this Participant object, that way the database row will be locked appropriately.

    Parameters
    ----------

    participant_id
        ID of the participant to get.

    for_update
        Set to ``True`` if you plan to update this Participant object.
        The Participant object will be locked for update in the database
        and only released at the end of the transaction.

    Returns
    -------

    :class:`psynet.participant.Participant`
        The requested participant.
    """
    query = Participant.query.filter_by(id=participant_id)
    if for_update:
        query = query.with_for_update(of=Participant).populate_existing()
    return query.one()


class ParticipantDriver:
    """
    Driver class for automating participant actions in an experiment.

    The :class:`~psynet.participant.ParticipantDriver` class contrasts with the :class:`~psynet.participant.Participant` class.
    :class:`~psynet.participant.Participant` instances correspond to rows in the Participant table in the database.
    These :class:`~psynet.participant.Participant` instances are used in the primary experiment logic.
    The :class:`~psynet.participant.ParticipantDriver` class is meanwhile used to simulate how a human actually
    interacts with the user interface.
    This simulation is primarily useful for automated testing, but it is also
    used for simulation studies as well as for studies where human participants interact
    with virtual participants.

    From an implementation perspective, the primary reason why we have this driver class
    in addition to the :class:`~psynet.participant.Participant` class
    is to avoid having long-lived database object proxies.
    Such long-lived proxies can cause hard-to-debug issues such as database deadlocks.
    Where possible, the class uses HTTP requests to interact with the experiment server
    rather than directly interacting with the database; this helps us to ensure
    that the simulation is as close as possible to the real thing.

    In most cases, we anticipate users will want to use the convenience subclass :class:`~psynet.bot.BotDriver`,
    which is a subclass of :class:`~psynet.participant.ParticipantDriver` that is specifically focused on creating
    and controlling bot participants. However, the :class:`~psynet.participant.ParticipantDriver` class can be used
    in the rare case where we want to occasionally control individual actions of a
    human participant.

    Parameters
    ----------
    id_ : int, optional
        The ID of the participant to automate
        (i.e. corresponding to the ``id`` column in the Participant table).
        If not provided, a new bot participant is created.
    """

    def __init__(
        self,
        id_: int,
    ):
        from .experiment import get_experiment

        self.id = id_
        self.experiment = get_experiment()
        # self._directory = tempfile.TemporaryDirectory()
        # self.directory = self._directory.name
        self.directory = tempfile.mkdtemp()
        self.status = None
        self.status_time_fetched = None
        self.response_files = None

        with transaction(commit=False):
            self.participant_unique_id = Participant.query.get(id_).unique_id

        self._render_page()
        self._fetch_status()

    def __del__(self):
        if hasattr(self, "directory"):
            shutil.rmtree(self.directory)
        # self._directory.cleanup()

    @property
    def is_working(self):
        return self.status["status"] == "working"

    @property
    def current_page_label(self):
        return self.status["page"]["label"]

    @property
    def current_page_text(self):
        return self.status["page"]["text"]

    @property
    def current_page_time_estimate(self):
        return self.status["page"]["time_estimate"]

    @property
    def current_page_uuid(self):
        return self.status["page_uuid"]

    def run_until(self, condition, render_pages=True, time_factor=0.0):
        """
        Take pages until a condition is met.
        """
        while not condition(self):
            if not self.is_working:
                raise RuntimeError(
                    "Participant finished the experiment before condition was met."
                )
            self.take_page(render_pages, time_factor)

    def run_to_completion(self, render_pages=True, time_factor=0.0):
        """
        Take pages until the participant has finished the experiment.
        """
        self.run_until(lambda bot: not bot.is_working, render_pages, time_factor)

    def take_experiment(self, render_pages: bool = True, time_factor: float = 0.0):
        """
        Run the participant through the entire experiment.
        """
        start_time = time.monotonic()
        self.run_to_completion(render_pages, time_factor)
        total_experiment_time = time.monotonic() - start_time
        self._report_stats(total_experiment_time)

    def take_page(
        self,
        render_pages: bool = True,
        time_factor: float = 0.0,
        response=NoArgumentProvided,
    ):
        """
        Advance the participant by one page. Returns False if finished.

        Parameters
        ----------
        render_pages : bool, optional
            Whether to render pages during automation (default is True).
        time_factor : float, optional
            Factor to multiply the simulated page time by (default is 0.0).
        response : optional
            If provided, the participant's raw_answer will be set to this value.

        Returns
        -------
        bool
            True if the participant should continue, False if finished.
        """
        if isinstance(render_pages, Page):
            raise ValueError(
                "The signature of take_page has changed; it no longer acceptes a page argument."
            )
        assert self.status is not None

        self._simulate_page_time(time_factor)
        self._submit_response(self.status, self.response_files, response)
        if render_pages:
            self._render_page()

        return True

    def _fetch_status(self):
        """
        Fetch the participant's current status and any associated response files,
        and store them in the participant driver's attributes
        (self.status and self.response_files).

        Parameters
        ----------
        directory : str
            Path to a directory for extracting files.
        """
        response = self.experiment.authenticated_session.get(
            f"{self.experiment.base_url}/participant_status/{self.id}"
        )
        response.raise_for_status()

        self.response_files = {}

        with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
            # Load the status.
            with zf.open("status.json") as f:
                self.status = json.load(f)

            # Clean up any old response files.
            try:
                shutil.rmtree(os.path.join(self.directory, "bot_response_files"))
            except FileNotFoundError:
                pass

            # Extract the new response files.
            for name in zf.namelist():
                if name.startswith("bot_response_files/") and not name.endswith("/"):
                    zf.extract(name, self.directory)
                    key = name.replace("bot_response_files/", "", 1)
                    self.response_files[key] = os.path.join(self.directory, name)

        self.status_time_fetched = time.monotonic()

    def _render_page(self):
        """
        Render the current page for the participant.
        """
        response = requests.get(
            f"{self.experiment.base_url}/timeline",
            params={"unique_id": self.participant_unique_id},
        )
        _raise_for_status_with_server_details(response)

    def _simulate_page_time(self, time_factor):
        """
        Sleep so that the total time spent on the page matches the simulated duration.

        Parameters
        ----------
        page_time_started : float
            The time the page started (from time.monotonic()).
        status : dict
            The status dictionary for the participant.
        time_factor : float
            Factor to multiply the simulated page time by.
        """
        time_estimate = self.status["page"]["time_estimate"]
        simulated_page_time = time_estimate * time_factor
        wake_time = self.status_time_fetched + simulated_page_time
        remaining_sleep_duration = wake_time - time.monotonic()
        if remaining_sleep_duration > 0:
            time.sleep(remaining_sleep_duration)

    def _submit_response(self, status, response_files, response=NoArgumentProvided):
        """
        Submit the participant's response to the server.

        The HTTP submission is a POST request to the /response endpoint
        with the following data:

        - participant_id
        - page_uuid
        - raw_answer
        - answer
        - metadata
        - blobs

        At least one of raw_answer and answer should be provided.
        If answer is present, then raw_answer will be ignored.

        Parameters
        ----------
        status : dict
            The status dictionary for the participant.
        response_files : dict
            Mapping of file keys to file paths.
        """
        from .bot import BotResponse

        # These come from the /participant_status endpoint.
        time_estimate = status["page"]["time_estimate"]
        bot_response = status["page"]["bot_response"]

        if response != NoArgumentProvided:
            bot_response = BotResponse(answer=response).__json__()

        submission_data = {
            "participant_id": self.id,
            "page_uuid": status["page_uuid"],
            **bot_response,
            # Drivers fetch status separately and do not consume SPA fragments.
            "include_timeline_fragment": False,
        }

        if "time_taken" not in submission_data["metadata"]:
            submission_data["metadata"]["time_taken"] = time_estimate

        with ExitStack() as stack:
            files = {}
            for key, path in response_files.items():
                file_obj = stack.enter_context(open(path, "rb"))
                files[key] = (os.path.basename(path), file_obj)
            response = requests.post(
                f"{self.experiment.base_url}/response",
                data={"json": json.dumps(submission_data)},
                files=files,
            )
        _raise_for_status_with_server_details(response)
        resp_json = response.json()
        if resp_json.get("submission") != "approved":
            raise RuntimeError(
                f"The participant's response was rejected: {resp_json.get('message')}"
            )
        # We've made some changes to the database, so we need to expire all objects
        # to ensure that the changes are reflected in our local session.
        db.session.expire_all()

        # Update our status to reflect the new state of the participant.
        self._fetch_status()

    def _report_stats(self, total_experiment_time: float):
        """
        Report statistics for the participant's run through the experiment.
        """
        with transaction(commit=False):
            page_count, progress, total_wait_page_time = (
                db.session.query(Participant)
                .filter_by(id=self.id)
                .with_entities(
                    Participant.page_count,
                    Participant.progress,
                    Participant.total_wait_page_time,
                )
                .one()
            )

        stats = {
            "page_count": page_count,
            "progress": progress,
            "total_wait_page_time": total_wait_page_time,
            "total_experiment_time": total_experiment_time,
        }

        logger.info(
            f"ParticipantDriver {self.id} has finished the experiment (took {stats['page_count']} page(s), "
            f"progress = {100 * stats['progress']:.0f}%, "
            f"total WaitPage time = {stats['total_wait_page_time']:.3f} seconds, "
            f"total experiment time = {stats['total_experiment_time']:.3f} seconds)."
        )

    # The following methods cheat and use the database directly.
    # The intention is that these provide utilities for testing,
    # rather than being intended to simulate particular participant actions.
    # We deem these methods low-risk because they only use
    # short-term transactions and hence should not cause deadlocks.
    # Feel free to add more convenience methods here as and when they prove useful.
    ###############################################################################

    def get_current_page(self) -> Page:
        with transaction():
            participant = Participant.query.get(self.id)
            return participant.get_current_page()

    def fail(self, reason=None):
        with transaction(commit=True):
            participant = Participant.query.get(self.id)
            participant.fail(reason)

    def from_db(self, attr: str):
        with transaction(commit=False):
            participant = (
                Participant.query.filter_by(id=self.id).populate_existing().one()
            )
            return getattr(participant, attr)

    @property
    def active_barriers(self):
        return self.from_db("active_barriers")

    @property
    def current_trial(self):
        return self.from_db("current_trial")

    @property
    def current_node(self):
        return self.from_db("current_node")

    @property
    def sync_group_n_active_participants(self):
        with transaction(commit=False):
            participant = Participant.query.get(self.id)
            return participant.sync_group.n_active_participants

    ###############################################################################
