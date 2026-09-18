"""
Synchronization primitives for coordinating participants.

This module contains the core building blocks for synchronous experiments.
If you have not seen PsyNet's synchronization features before, the key idea is
simple: participants move through a timeline, sometimes waiting for other
participants to arrive at the same point. We implement that waiting logic with
barriers, and we implement grouping logic with groupers and sync groups.

Glossary
--------
Barrier
    A timeline element that pauses participants until some release condition is
    satisfied (for example, "wait until two participants arrive"). Barriers are
    subclasses of ``Barrier``/``GroupBarrier``. In a timeline they usually wrap
    a ``WaitPage`` loop so participants see a waiting screen while they wait.

Grouper and sync group
    A ``SimpleGrouper`` (or other grouper) is a timeline element that forms
    ``SyncGroup`` rows once enough participants are available. Group barriers
    rely on these groups to decide who to release together.

Barrier registry
    Barriers and their waiting participants are persisted in the database via
    ``BarrierRecord`` and ``ParticipantLinkBarrier``. This replaces the older
    in-memory registry so multiple worker processes can safely cooperate.

Where this shows up in a timeline
---------------------------------
The most common pattern is:

1. A grouper runs early in the timeline to create sync groups.
2. A ``GroupBarrier`` appears later in the timeline to pause participants until
   the group is ready.
3. After release, the timeline continues with shared or individual tasks.

How processing works
--------------------
When a participant reaches a barrier, ``Barrier.receive_participant``:

- Ensures a ``BarrierRecord`` exists (storing a lightweight copy of the barrier).
- Inserts a ``ParticipantLinkBarrier`` row marking the participant as waiting.

A scheduled task in ``Experiment._check_barriers`` calls ``check_barriers`` in
this module. That loop:

- Finds the next waiting barrier record.
- Locks it using ``SELECT ... FOR UPDATE SKIP LOCKED`` so only one worker
  processes a barrier at a time.
- Calls ``Barrier.check`` in an isolated transaction.
- Logs and skips failures per barrier so one bad barrier does not stall others.

Callable attributes on barriers (e.g., ``on_release``) are serialized via
``serialize_callable`` so they can be stored inside ``BarrierRecord`` safely.
"""

import copy
import random
from math import floor
from typing import Callable, List, Literal, Optional, Union

from dallinger import db
from dallinger.models import timenow
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
)
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import backref, deferred, joinedload, object_session, relationship

from psynet.data import SQLBase, SQLMixin, register_table
from psynet.db import transaction
from psynet.field import PythonClass, PythonObject
from psynet.page import UnsuccessfulEndPage, WaitPage
from psynet.participant import Participant
from psynet.serialize import serialize_callable
from psynet.timeline import CodeBlock, EltCollection, conditional
from psynet.utils import get_logger

logger = get_logger()


class _ReadOnlyParticipantList(list):
    """A participant list whose membership must be changed through its group."""

    def _raise_mutation_error(self, *args, **kwargs):
        raise TypeError(
            "SyncGroup.participants is read-only; use group.add_participant() "
            "or group.remove_participant() instead."
        )

    append = clear = extend = insert = pop = remove = reverse = sort = (
        _raise_mutation_error
    )
    __delitem__ = __iadd__ = __imul__ = __setitem__ = _raise_mutation_error


class Barrier(EltCollection):
    """
    A barrier is a timeline construct that holds participants in a waiting area until certain conditions
    are satisfied to release them. The decision about which participants to release at any given point is taken by
    the ``choose_who_to_release`` method, which the user is expected to provide.

    Parameters
    ----------

    id_
        ID parameter for the barrier. Barriers with the same ID share waiting areas; this allows participants
        at different points in the timeline to share the same waiting areas.

    waiting_logic
        Either a single timeline element or a list of timeline elements (created by ``join``) that is to be displayed
        to the participant while they are waiting at the barrier. If left at the default value of ``None``
        then the participant will be shown a default waiting page.

    waiting_logic_expected_repetitions
        The number of times that the participant is expected to experience the waiting_logic during a given barrier
        visit. This is used for time estimation.

    max_wait_time
        The maximum amount of time in seconds that the participant will be allowed to wait at the barrier;
        if this time is exceeded then the participant will be failed and sent to the end of the experiment.

    fix_time_credit
        If set to ``True``, then the amount of time 'credit' that the participant receives will be capped
        according to the estimate derived from ``waiting_logic`` and ``waiting_logic_expected_repetitions``.
    """

    def __init__(
        self,
        id_: str,
        waiting_logic=None,
        waiting_logic_expected_repetitions=3,
        max_wait_time=20,
        fix_time_credit=False,
    ):
        if waiting_logic is None:
            waiting_logic = WaitPage(wait_time=0.5)

        self.id = id_
        self.waiting_logic = waiting_logic
        self.waiting_logic_expected_repetitions = waiting_logic_expected_repetitions
        self.max_wait_time = max_wait_time
        self.max_wait_action = "fail"
        self.fix_time_credit = fix_time_credit

    def for_registry(self):
        """Return a registry-safe copy of the barrier."""
        barrier = copy.copy(self)
        barrier.waiting_logic = None
        return barrier

    def __setattr__(self, name, value):
        if name.startswith("on_"):
            value = serialize_callable(value, f"{self.__class__.__name__}.{name}")
        super().__setattr__(name, value)

    def choose_who_to_release(
        self, waiting_participants: List[Participant]
    ) -> List[Participant]:
        """
        Given a list of waiting participants, decides which of these participants should be released
        from the barrier.

        Parameters
        ----------
        waiting_participants
            A list of waiting participants.

        Returns
        -------

        A list of participants to be released.
        """
        raise NotImplementedError

    def resolve(self):
        from psynet.timeline import join, while_loop

        elts = join(
            CodeBlock(lambda participant: self.receive_participant(participant)),
            while_loop(
                label=f"barrier:{self.id}",
                condition=lambda participant: (
                    not self.can_participant_exit(participant)
                ),
                logic=self.waiting_logic,
                expected_repetitions=self.waiting_logic_expected_repetitions,
                max_loop_time=self.max_wait_time,
                fix_time_credit=self.fix_time_credit,
                fail_on_timeout=(self.max_wait_action == "fail"),
                on_timeout=self.handle_max_wait_timeout,
            ),
            conditional(
                "participant_failed",
                condition=lambda participant: participant.failed,
                logic_if_true=UnsuccessfulEndPage(),
                time_estimate=0,
                log_chosen_branch=False,
            ),
        )
        for elt in elts:
            elt.links["barrier"] = self

        return elts

    def handle_max_wait_timeout(self, participant: Participant):
        """Release the participant's active barrier link after a max-wait timeout."""
        if self.id in participant.active_barriers:
            self.release(participant)

    def receive_participant(self, participant: Participant):
        if object_session(participant) is None:
            db.session.add(participant)

        BarrierRecord.ensure_exists(self.id, self.__class__, barrier=self)

        link = ParticipantLinkBarrier(
            participant=participant,
            barrier_id=self.id,
            arrival_time=timenow(),
        )
        participant.active_barriers[self.id] = link

    def get_waiting_participants(self, for_update: bool = False):
        return self.get_waiting_participants_from_barrier_id(
            self.id, for_update=for_update
        )

    @classmethod
    def get_waiting_participants_from_barrier_id(
        cls, barrier_id: str, for_update: bool = False
    ) -> List[Participant]:
        """
        Gets the participants currently waiting at a barrier.

        Parameters
        ----------
        barrier_id
            The ID of the barrier to check.

        for_update
            Set to ``True`` if you plan to update the resulting participant objects and their barrier links.
            The objects will be locked for update in the database
            and only released at the end of the transaction.

        Returns
        -------

        A list of waiting participants. Note that this only includes currently active participants
        (not participants who failed and left the experiment).
        """
        query = (
            ParticipantLinkBarrier.query.join(Participant)
            .filter(
                ParticipantLinkBarrier.barrier_id == barrier_id,
                ~ParticipantLinkBarrier.released,
                ~Participant.failed,
                Participant.status == "working",
            )
            .options(joinedload(ParticipantLinkBarrier.participant, innerjoin=True))
            .order_by(Participant.id)
        )

        if for_update:
            query = query.with_for_update(
                of=[ParticipantLinkBarrier, Participant]
            ).populate_existing()

        links = query.all()
        participants = [link.participant for link in links]

        return participants

    def release(self, participant: Participant):
        link = participant.active_barriers.get(self.id, None)
        if link is None:
            raise RuntimeError(
                "Could not find an appropriate barrier link to release the participant from "
                f"(participant_id = {participant.id}, barrier_id = '{self.id}')."
            )
        link.release()

    def can_participant_exit(self, participant: "Participant"):
        barrier_is_active = self.id in participant.active_barriers
        return not barrier_is_active

    def check_waiting_participants(self, waiting_participants: List[Participant]):
        """Run any side-effecting checks before deciding who to release."""

    def check(self):
        waiting_participants = self.get_waiting_participants(for_update=True)
        waiting_participants.sort(key=lambda p: p.id)

        logger.info(
            "Barrier '%s' currently has %i participant(s) waiting (ids = %s)",
            self.id,
            len(waiting_participants),
            ", ".join([str(p.id) for p in waiting_participants]),
        )

        self.check_waiting_participants(waiting_participants)
        participants_to_release = self.choose_who_to_release(waiting_participants)
        participants_to_release.sort(key=lambda p: p.id)

        if len(participants_to_release) > 0:
            logger.info(
                "Barrier '%s' is releasing %i participant(s) (ids = %s)",
                self.id,
                len(participants_to_release),
                ", ".join([str(p.id) for p in participants_to_release]),
            )

            for participant in participants_to_release:
                self.release(participant)


class GroupBarrier(Barrier):
    """
    A GroupBarrier is a Barrier that waits until all participants in a given :class:`~psynet.sync.SyncGroup`
    have reached the Barrier. It also checks the current group size against the group's minimum size parameter;
    the group won't be allowed to proceed if it's below this size.
    If ``accepts_top_ups=True`` for that group, it'll wait just in case new participants join the group.
    If ``accepts_top_ups=False``, then there's no hope for new participants, so the group will be released
    and failed.

    Parameters
    ----------

    id_
        ID parameter for the Barrier. Barriers with the same ID share waiting areas; this allows participants
        at different points in the timeline to share the same waiting areas.

    group_type
        Identifies the kind of groups that the Barrier is operating over (see :class:`~psynet.sync.Grouper`).

    waiting_logic
        Either a single timeline element or a list of timeline elements (created by ``join``) that is to be displayed
        to the participant while they are waiting at the barrier. If left at the default value of ``None``
        then the participant will be shown a default waiting page.

    waiting_logic_expected_repetitions
        The number of times that the participant is expected to experience the waiting_logic during a given barrier
        visit. This is used for time estimation.

    max_wait_time
        The maximum amount of time in seconds that the participant will be allowed to wait at the barrier;
        if this time is exceeded, the participant is either failed or kicked (see ``max_wait_action``).

    max_wait_action
        When ``max_wait_time`` is exceeded: ``"fail"`` fails the participant and sends them to the end of the
        experiment; ``"kick"`` removes them from the group and lets them continue. Default is ``"fail"``.

    timeout_between_barriers_time
        The maximum amount of time in seconds that a participant is allowed to reach the barrier, measured from when
        the group collectively passed the previous barrier. If ``None`` (default), no between-barrier timeout is applied.
        Only applies from the second barrier onward (time since previous barrier pass).

    timeout_between_barriers_action
        When a participant exceeds ``timeout_between_barriers_time``: ``"kick"`` removes them from the group (so the
        rest can proceed without them), or ``"fail"`` fails the participant and sends them to the end of the experiment.
        Default is ``"fail"``.

    on_release
        Optional callback invoked when the barrier releases participants.
        Must be a module-level function, ``@staticmethod``/``@classmethod``,
        or a bound method on a TrialMaker or ORM instance with a primary key.

    on_release
        Optional callable invoked when the barrier releases participants.
        Must be a module-level function, ``@staticmethod``/``@classmethod``,
        or a bound method on a TrialMaker or ORM instance with a primary key.

    fix_time_credit
        If set to ``True``, then the amount of time 'credit' that the participant receives will be fixed
        according to the estimate derived from ``waiting_logic`` and ``waiting_logic_expected_repetitions``.
    """

    @staticmethod
    def _kick_participant_after_max_wait(
        participant: Participant, group_type: str
    ) -> None:
        """Remove the participant from their sync group when max wait uses action ``'kick'``."""
        if group_type in participant.active_sync_groups:
            participant.active_sync_groups[group_type].remove_participant(participant)

    def _validate_max_wait_action(self, max_wait_action):
        if max_wait_action not in ("fail", "kick"):
            raise ValueError(
                f"max_wait_action must be 'fail' or 'kick', got {max_wait_action!r}."
            )

    def __init__(
        self,
        id_: str,
        group_type: str,
        waiting_logic=None,
        waiting_logic_expected_repetitions=3,
        max_wait_time=20,
        max_wait_action: Literal["fail", "kick"] = "fail",
        on_release: Optional[Callable] = None,
        fix_time_credit=False,
        timeout_between_barriers_time: Optional[float] = None,
        timeout_between_barriers_action: Literal["kick", "fail"] = "fail",
    ):
        self._validate_max_wait_action(max_wait_action)
        super().__init__(
            id_=id_,
            waiting_logic=waiting_logic,
            waiting_logic_expected_repetitions=waiting_logic_expected_repetitions,
            max_wait_time=max_wait_time,
            fix_time_credit=fix_time_credit,
        )
        self.max_wait_action = max_wait_action
        self.group_type = group_type
        self.on_release = on_release
        self.timeout_between_barriers_time = timeout_between_barriers_time
        if timeout_between_barriers_action not in ("kick", "fail"):
            raise ValueError(
                "timeout_between_barriers_action must be 'kick' or 'fail', "
                f"got {timeout_between_barriers_action!r}"
            )
        self.timeout_between_barriers_action = timeout_between_barriers_action

    def handle_max_wait_timeout(self, participant: Participant):
        """Kick from the sync group when requested, then release the barrier link."""
        if self.max_wait_action == "kick":
            self._kick_participant_after_max_wait(
                participant=participant, group_type=self.group_type
            )
        super().handle_max_wait_timeout(participant)

    def choose_who_to_release(self, waiting_participants: List[Participant]):
        waiting_participant_ids = {p.id for p in waiting_participants}
        participants_to_release = []
        groups = self.get_waiting_groups(waiting_participants)

        for group in groups.values():
            group.check_numbers()

            if group.n_active_participants < group.min_group_size:
                # If join_existing_groups is False, then the group will never be able
                # to get to the minimum size, so we remove all participants from the group
                # and release participants who are waiting at this barrier. Optionally fail them
                # (when fail_participants_below_min_size is True).
                if not group.accepts_top_ups:
                    for participant in list(group.active_participants):
                        if group.fail_participants_below_min_size:
                            participant.fail("sync group below minimum size")
                        group.remove_participant(participant)
                        if participant.id in waiting_participant_ids:
                            participants_to_release.append(participant)
                    group.check_numbers()
                    if group.n_active_participants == 0:
                        group.close()
                continue

            all_participants_present = all(
                [
                    participant.id in waiting_participant_ids
                    for participant in group.active_participants
                ]
            )
            if all_participants_present:
                group.check_leader()
                for participant in group.active_participants:
                    participants_to_release.append(participant)

                group.last_barrier_pass_time = timenow()

                if self.on_release:
                    self.on_release(
                        group=group,
                        participants=group.active_participants,
                        participant=group.leader,
                        barrier=self,
                    )

        participants_to_release_ids = {p.id for p in participants_to_release}
        for participant in waiting_participants:
            # Release participants who reached this barrier but no longer belong
            # to the sync group (e.g., max-wait kicks or below-min-size dissolution).
            if (
                self.group_type not in participant.active_sync_groups
                and participant.id not in participants_to_release_ids
            ):
                participants_to_release.append(participant)
                participants_to_release_ids.add(participant.id)

        return participants_to_release

    def check_waiting_participants(self, waiting_participants: List[Participant]):
        for group in self.get_waiting_groups(waiting_participants).values():
            group.check_numbers()
            self._timeout_participants_between_barriers(group, waiting_participants)

    def get_waiting_groups(self, waiting_participants: List[Participant]):
        groups = {
            participant.active_sync_groups[
                self.group_type
            ].id: participant.active_sync_groups[self.group_type]
            for participant in waiting_participants
            if self.group_type in participant.active_sync_groups
        }
        return groups

    def _timeout_participants_between_barriers(
        self, group: "SyncGroup", waiting_participants: List[Participant]
    ):
        """Kick or fail group members who are late reaching this barrier."""
        if (
            self.timeout_between_barriers_time is None
            or group.last_barrier_pass_time is None
        ):
            return

        elapsed_seconds = (timenow() - group.last_barrier_pass_time).total_seconds()
        if elapsed_seconds <= self.timeout_between_barriers_time:
            return

        waiting_participant_ids = {p.id for p in waiting_participants}
        missing = [
            p for p in group.active_participants if p.id not in waiting_participant_ids
        ]
        for participant in missing:
            if self.timeout_between_barriers_action == "kick":
                logger.info(
                    "GroupBarrier '%s': kicking participant %s from group %s (timeout between barriers)",
                    self.id,
                    participant.id,
                    group.id,
                )
                group.remove_participant(participant)
            else:
                logger.info(
                    "GroupBarrier '%s': failing participant %s (timeout between barriers)",
                    self.id,
                    participant.id,
                )
                participant.fail("timeout between barriers")

    def release(self, participant: Participant):
        link = participant.active_barriers.get(self.id, None)
        if link is None:
            raise RuntimeError(
                "Could not find an appropriate barrier link to release the participant from "
                f"(participant_id = {participant.id}, barrier_id = '{self.id}')."
            )

        link.release()


class Grouper(Barrier):
    """
    A Grouper is a kind of Barrier that assigns incoming participants into groups.
    This is a generic class that requires several methods to be overrun, in particular
    ``ready_to_group`` and ``group``.

    Parameters
    ----------

    group_type
        A textual label for the groups that are created. This label is used to link the Grouper with
        subsequent GroupBarriers.

    id_
        Optional ID parameter for this grouper. If left blank the default value is ``group_type + "_" + "grouper"``.
        Groupers with the same ID are treated as equivalent and share the same participant waiting areas.

    waiting_logic
        Either a single timeline element or a list of timeline elements (created by ``join``) that is to be displayed
        to the participant while they are waiting at the barrier. If left at the default value of ``None``
        then the participant will be shown a default waiting page.

    waiting_logic_expected_repetitions
        The number of times that the participant is expected to experience the waiting_logic during a given barrier
        visit. This is used for time estimation.

    max_wait_time
        The maximum amount of time in seconds that the participant will be allowed to wait at the barrier;
        if this time is exceeded and the participant is still not released, then the participant will be failed
        and sent to the end of the experiment.

    fail_participants_below_min_size
        If ``True`` (default), participants in a group that is below minimum size and does not accept
        top-ups are failed and released when they hit a GroupBarrier. If ``False``, they are released
        without being failed. (Only applies to groups that have a minimum size, e.g. created by SimpleGrouper.)
    """

    def __init__(
        self,
        group_type: str,
        id_: Optional[str] = None,
        waiting_logic=None,
        waiting_logic_expected_repetitions=3,
        max_wait_time=20,
        fail_participants_below_min_size: bool = True,
    ):
        if not id_:
            id_ = group_type + "_" + "grouper"
        super().__init__(
            id_=id_,
            waiting_logic=waiting_logic,
            waiting_logic_expected_repetitions=waiting_logic_expected_repetitions,
            max_wait_time=max_wait_time,
        )
        self.group_type = group_type
        self.fail_participants_below_min_size = fail_participants_below_min_size

    def ready_to_group(self, participants: List[Participant]) -> bool:
        """
        Determines whether the Grouper is ready to group a given collection of participants.
        Note that not all participants need to be grouped at once; it's permissible to
        leave some participants still waiting.

        Parameters
        ----------

        participants
            List of participants who are candidates for grouping.

        Returns
        -------

        ``True`` if the grouper is ready to group (some of) the participants, ``False`` otherwise.

        """
        raise NotImplementedError

    def group(self, participants: List[Participant]) -> List["SyncGroup"]:
        """
        This method is run if ``ready_to_group`` returns ``True``.
        It is responsible for grouping participants.

        Parameters
        ----------
        participants
            Participants who are candidates for grouping.

        Returns
        -------
        A list of SyncGroups who should be populated by the grouped participants.
        """
        raise NotImplementedError

    def receive_participant(self, participant: Participant):
        if self.group_type in participant.active_sync_groups:
            raise RuntimeError(
                f"Participant is already in a group with this group_type ('{self.group_type}'). "
                "You should close this group, typically by including a GroupCloser in the timeline, "
                "before reassigning it."
            )
        super().receive_participant(participant)

    def choose_who_to_release(self, waiting_participants: List[Participant]):
        participants_to_release = []

        if self.ready_to_group(waiting_participants):
            groups = self.group(waiting_participants)

            if not isinstance(groups, list) and all(
                [isinstance(group, SyncGroup) for group in groups]
            ):
                raise ValueError("group() must return a list of SyncGroups.")

            for _group in groups:
                db.session.add(_group)
                for _participant in _group.participants:
                    participants_to_release.append(_participant)

        return participants_to_release

    def select_leader(self, participants: List[Participant]) -> Participant:
        """
        By default the leader is randomly chosen from the list of available participants.

        Parameters
        ----------

        participants
            Participants to choose from.

        Returns
        -------

        A participant to be assigned 'leader' of the SyncGroup.

        """
        return random.choice(participants)


class SimpleGrouper(Grouper):
    """
    A Simple Grouper waits until ``batch_size`` many participants are waiting,
    and then randomly partitions this group of participants into groups of size ``initial_group_size``.

    Parameters
    ----------

    group_type
        A textual label for the groups that are created. This label is used to link the Grouper with
        subsequent GroupBarriers.

    initial_group_size
        Size of the groups to create.

    max_group_size
        If ``join_existing_groups=True``, then participants will be allowed to join groups until
        they reach this maximum size. If set to ``"initial_group_size"`` (default),
        then the maximum size will be set to the initial group size.

    min_group_size
        If the current group size is below this value (taking into account failed participants
        and participants who have left the experiment), then the group will be considered under-quota.
        The group will not be allowed to pass through barriers until it is at or above this size.
        If set to ``"initial_group_size"`` (default), then the minimum size will be set to the initial group size.

    batch_size
        Number of participants that should be waiting until the groups are created.
        If set to ``"initial_group_size"`` (default), then the batch size will be set to the initial group size.

    join_existing_groups
        If set to ``True``, then before a new group is created, the Grouper will check if there are any existing
        groups that are under-quota (e.g. because some participants left the experiment early).
        If so, the arriving participant will be assigned to one of these groups instead.
        This behavior can be further customized via the ``join_criterion`` argument.

    join_criterion
        A callable that takes ``group`` and ``participant`` as arguments, and returns ``True``
        if the participant should be allowed to join the group, and ``False`` otherwise.
        To be used in conjunction with ``join_existing_groups=True``.

    fail_participants_below_min_size
        If ``True`` (default), participants in a group below minimum size that does not accept top-ups
        are failed and released at GroupBarriers. If ``False``, they are released without being failed.

    kwargs
        Further arguments to pass to Grouper.
    """

    def __init__(
        self,
        group_type: str,
        *,
        initial_group_size: Optional[int] = None,
        max_group_size: Optional[Union[int, str]] = "initial_group_size",
        min_group_size: Union[int, str] = "initial_group_size",
        batch_size: Union[int, str] = "initial_group_size",
        join_existing_groups: bool = False,
        join_criterion: Optional[Callable] = None,
        fail_participants_below_min_size: bool = True,
        **kwargs,
    ):
        if "group_size" in kwargs:
            raise ValueError(
                "The group_size argument has been renamed to initial_group_size, "
                "please update your code accordingly.",
            )

        if initial_group_size is None:
            raise ValueError("initial_group_size must be provided.")

        super().__init__(group_type=group_type, **kwargs)

        if max_group_size == "initial_group_size":
            max_group_size = initial_group_size
        else:
            if not join_existing_groups:
                raise ValueError(
                    "If max_group_size != 'initial_group_size', you probably want to set join_existing_groups=True."
                )

        if min_group_size == "initial_group_size":
            min_group_size = initial_group_size

        if batch_size == "initial_group_size":
            batch_size = initial_group_size

        self.initial_group_size = initial_group_size
        self.max_group_size = max_group_size
        self.min_group_size = min_group_size
        self.batch_size = batch_size
        self.join_existing_groups = join_existing_groups
        self.join_criterion = join_criterion
        self.fail_participants_below_min_size = fail_participants_below_min_size

    def resolve(self):
        from .timeline import conditional, join

        return join(
            CodeBlock(self._join_existing_groups),
            conditional(
                "joined_an_existing_group",
                condition=lambda participant: (
                    self.group_type in participant.active_sync_groups
                ),
                logic_if_true=[],
                logic_if_false=super().resolve(),
            ),
        )

    def _join_existing_groups(self, participant: Participant):
        # The current logic is flawed, in that participants end up joining groups that are no longer active.
        # It's difficult to figure out a good general-purpose solution here that works well for all possible applications.
        # I think we should disable this behaviour for now, and wait until we experience some real-world use cases,
        # which can inform the future API.
        if not self.join_existing_groups:
            return

        query = SimpleSyncGroup.query.filter(
            SimpleSyncGroup.group_type == self.group_type
        )

        if self.max_group_size is not None:
            query = query.filter(
                SimpleSyncGroup.n_active_participants < self.max_group_size
            )

        # Preferentially join the smallest groups, and among those, the oldest
        query = query.order_by(
            SimpleSyncGroup.n_active_participants, SimpleSyncGroup.id
        )

        groups = query.all()

        # Only keep groups that satisfy the joining criterion (if provided)
        groups = [
            g
            for g in groups
            if self.join_criterion is None
            or self.join_criterion(group=g, participant=participant)
        ]

        if len(groups) > 0:
            group = groups[0]
            group.add_participant(participant)
            assert participant.active_sync_groups[self.group_type] == group
            group.check_numbers()
            group.check_leader()

    def ready_to_group(self, participants: List[Participant]) -> bool:
        return len(participants) >= self.batch_size

    def group(self, participants: List[Participant]) -> List["SyncGroup"]:
        n_groups = floor(len(participants) / self.initial_group_size)
        n_participants_to_group = n_groups * self.initial_group_size
        participants_to_group = participants[:n_participants_to_group]

        grouped_participants = self.randomly_partition_list(
            participants_to_group, group_size=self.initial_group_size
        )
        groups = []
        for _participants in grouped_participants:
            _group = SimpleSyncGroup(
                group_type=self.group_type,
                initial_group_size=self.initial_group_size,
                max_group_size=self.max_group_size,
                min_group_size=self.min_group_size,
                n_active_participants=len(_participants),
                accepts_top_ups=self.join_existing_groups,
                fail_participants_below_min_size=self.fail_participants_below_min_size,
            )
            groups.append(_group)

            for _participant in _participants:
                _group.add_participant(_participant)

            _group.leader = self.select_leader(_participants)

        return groups

    @staticmethod
    def randomly_partition_list(lst: list, group_size: int):
        n_groups = len(lst) / group_size
        if not n_groups == floor(n_groups):
            raise ValueError(
                f"List size ({len(lst)}) is not an integer multiple of group_size ({group_size})"
            )
        n_groups = floor(n_groups)
        lst = lst.copy()
        random.shuffle(lst)
        return [lst[i::n_groups] for i in range(n_groups)]


@register_table
class SyncGroup(SQLBase, SQLMixin):
    """
    A SyncGroup represents a group of participants that are synchronized at various points in the experiment.
    Such groups are created by Groupers and synchronized by GroupBarriers.

    Attributes
    ----------

    leader : Participant
        The leader of the SyncGroup. This can be reassigned by logic such as ``group.leader = participant``.

    participants : List[Participant]
        Read-only list of participants currently in the group (links with ``active=True``). Use
        ``group.add_participant(participant)`` to add a participant.
    """

    __tablename__ = "sync_group"

    group_type = Column(String)
    active = Column(Boolean, default=True)
    end_time = Column(DateTime)
    last_barrier_pass_time = Column(DateTime, nullable=True)
    leader_id = Column(Integer, ForeignKey("participant.id"))

    participant_links = relationship(
        "ParticipantLinkSyncGroup",
        cascade="all, delete-orphan",
    )

    n_active_participants = Column(Integer)

    @property
    def participants(self) -> List[Participant]:
        """Participants currently in the group (links with active=True)."""
        return _ReadOnlyParticipantList(
            link.participant
            for link in self.participant_links
            if getattr(link, "active", True)
        )

    def add_participant(self, participant: Participant):
        """Add a participant to the group (creates an active link)."""
        self.participant_links.append(
            ParticipantLinkSyncGroup(participant=participant, active=True)
        )

    @property
    def active_participants(self) -> List[Participant]:
        return [p for p in self.participants if not p.failed and p.status == "working"]

    leader = relationship(
        "psynet.participant.Participant",
        cascade="all",
    )

    def check_leader(self):
        active_participants = sorted(self.active_participants, key=lambda p: p.id)
        if len(active_participants) == 0:
            self.leader = None
        elif self.leader not in active_participants:
            self.leader = active_participants[0]

    @property
    def active_followers(self):
        return [p for p in self.active_participants if p != self.leader]

    @classmethod
    def get_active_group(
        cls,
        participant: Participant,
        group_type: str,
    ) -> "SyncGroup":
        return participant.active_sync_groups[group_type]

    def close(self):
        self.active = False
        self.end_time = timenow()

    def check_numbers(self):
        self.n_active_participants = len(self.active_participants)

    def remove_participant(self, participant: Participant):
        for link in self.participant_links:
            if link.participant_id == participant.id:
                link.active = False
        self.check_numbers()
        if self.n_active_participants == 0 and not getattr(
            self, "accepts_top_ups", False
        ):
            self.close()
        else:
            self.check_leader()


class SimpleSyncGroup(SyncGroup):
    """
    A SyncGroup that is created by a SimpleGrouper.
    """

    initial_group_size = Column(Integer)
    max_group_size = Column(Integer)
    min_group_size = Column(Integer)
    accepts_top_ups = Column(Boolean)
    fail_participants_below_min_size = Column(Boolean, default=True)

    def remove_participant(self, participant: Participant):
        super().remove_participant(participant)
        self.dissolve_if_below_min_size()

    def dissolve_if_below_min_size(self):
        if (
            getattr(self, "_dissolving_below_min_size", False)
            or self.accepts_top_ups
            or self.n_active_participants >= self.min_group_size
        ):
            return

        self._dissolving_below_min_size = True
        try:
            remaining_participants = list(self.active_participants)
            for participant in remaining_participants:
                if self.fail_participants_below_min_size:
                    participant.fail("sync group below minimum size")
                else:
                    super().remove_participant(participant)

            self.check_numbers()
            if self.n_active_participants == 0:
                self.close()
        finally:
            self._dissolving_below_min_size = False


def _insert_values_from_state(record) -> dict:
    """Build insert values from an ORM instance state."""
    state = sa_inspect(record)
    mapper = state.mapper
    if mapper.polymorphic_on is not None:
        discriminator = mapper.polymorphic_on.key
        if getattr(record, discriminator) is None:
            setattr(record, discriminator, mapper.polymorphic_identity)
    column_keys = {column.key for column in mapper.columns}
    return {key: value for key, value in state.dict.items() if key in column_keys}


@register_table
class BarrierRecord(SQLBase, SQLMixin):
    __tablename__ = "barrier"

    id = Column(String, primary_key=True)
    barrier_class = Column(PythonClass)
    created_at = Column(DateTime, default=timenow)
    barrier = deferred(Column(PythonObject))

    participant_links = relationship(
        "ParticipantLinkBarrier", back_populates="barrier_record"
    )

    @classmethod
    def ensure_exists(cls, barrier_id: str, barrier_class, barrier=None):
        with db.session.no_autoflush:
            record = cls.query.get(barrier_id)
            if record is not None:
                if barrier is not None:
                    if isinstance(barrier, Barrier):
                        barrier = barrier.for_registry()
                    record.barrier = barrier
                return

            record = cls(
                id=barrier_id,
                barrier_class=barrier_class,
                created_at=timenow(),
                barrier=(
                    barrier.for_registry() if isinstance(barrier, Barrier) else barrier
                ),
            )
            values = _insert_values_from_state(record)
            stmt = (
                pg_insert(cls)
                .values(**values)
                .on_conflict_do_nothing(index_elements=["id"])
            )
            result = db.session.execute(stmt)
            if barrier is not None and result.rowcount == 0:
                record = cls.query.get(barrier_id)
                if record is not None:
                    if isinstance(barrier, Barrier):
                        barrier = barrier.for_registry()
                    record.barrier = barrier


@register_table
class ParticipantLinkSyncGroup(SQLBase, SQLMixin):
    __tablename__ = "participant_link_sync_group"

    arrival_time = Column(DateTime)
    active = Column(Boolean, default=True)

    participant_id = Column(Integer, ForeignKey("participant.id"), index=True)
    participant = relationship(
        "psynet.participant.Participant", back_populates="sync_group_links"
    )

    sync_group_id = Column(Integer, ForeignKey("sync_group.id"), index=True)
    sync_group = relationship("SyncGroup", back_populates="participant_links")


@register_table
class ParticipantLinkBarrier(SQLBase, SQLMixin):
    __tablename__ = "participant_link_barrier"

    barrier_id = Column(String, ForeignKey("barrier.id"), index=True)
    participant_id = Column(Integer, ForeignKey("participant.id"), index=True)
    participant = relationship(
        "psynet.participant.Participant",
        backref=backref(
            "barrier_links", cascade="all, delete-orphan"
        ),  # for some reason backpopulates didn't work here
    )

    arrival_time = Column(DateTime)
    departure_time = Column(DateTime)
    released = Column(Boolean, default=False)

    barrier_record = relationship("BarrierRecord", back_populates="participant_links")

    def get_barrier(self):
        barrier_record = BarrierRecord.query.get(self.barrier_id)
        if barrier_record is None or not isinstance(barrier_record.barrier, Barrier):
            raise RuntimeError(
                f"Barrier '{self.barrier_id}' is missing or invalid in the registry."
            )
        return barrier_record.barrier

    def release(self):
        self.departure_time = timenow()
        self.released = True

    def get_waiting_participants(self, for_update: bool = False):
        barrier = self.get_barrier()
        return barrier.get_waiting_participants(for_update=for_update)


def _next_waiting_barrier(excluded_ids):
    """Return the next eligible barrier record, if any."""
    waiting_barrier_query = BarrierRecord.query.filter(
        db.session.query(ParticipantLinkBarrier.id)
        .join(Participant)
        .filter(
            ParticipantLinkBarrier.barrier_id == BarrierRecord.id,
            ~ParticipantLinkBarrier.released,
            ~Participant.failed,
            Participant.status == "working",
        )
        .exists()
    )
    if excluded_ids:
        waiting_barrier_query = waiting_barrier_query.filter(
            ~BarrierRecord.id.in_(excluded_ids)
        )
    return (
        waiting_barrier_query.order_by(BarrierRecord.id)
        .with_for_update(skip_locked=True)
        .populate_existing()
        .first()
    )


def check_barriers():
    """Process waiting barriers, isolating failures to individual barriers."""
    excluded_ids = set()

    while True:
        barrier_id = None
        try:
            with transaction():
                barrier_record = _next_waiting_barrier(excluded_ids)
                if barrier_record is None:
                    return
                barrier_id = barrier_record.id
                barrier = barrier_record.barrier
                if not isinstance(barrier, Barrier):
                    raise RuntimeError(
                        f"Barrier '{barrier_record.id}' is missing or invalid."
                    )
                barrier.check()
        except Exception:
            if barrier_id is None:
                raise
            logger.exception("Failed to process barrier '%s'.", barrier_id)
        finally:
            if barrier_id is not None:
                excluded_ids.add(barrier_id)


Participant.sync_group_links = relationship(
    "ParticipantLinkSyncGroup",
    cascade="all, delete-orphan",
)


def _participant_sync_groups(participant) -> List["SyncGroup"]:
    """Sync groups with an active participant-group link for this participant."""
    return [
        link.sync_group
        for link in participant.sync_group_links
        if getattr(link, "active", True)
    ]


Participant.sync_groups = property(lambda self: _participant_sync_groups(self))

# No association proxy for barrier links because barriers are not exposed as objects


class GroupCloser(GroupBarrier):
    """
    A timeline construct for closing a previously created group.
    This is required before creating a new group with the same ``group_type``.
    """

    def __init__(self, group_type: str, **kwargs):
        if "id_" not in kwargs:
            kwargs["id_"] = f"closer_{group_type}"

        super().__init__(group_type=group_type, on_release=close_sync_group, **kwargs)


def close_sync_group(group):
    group.close()
