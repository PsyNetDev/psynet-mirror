"""Chain-based trial assignment and network growth.

Chain trial makers discover available networks, apply chain eligibility rules,
then select one chain and resolve its head to the node used for trial creation.
Static trial makers reuse the availability checks but adapt candidate networks
to nodes before filtering and selection.
"""

import random
from dataclasses import dataclass
from typing import Any, Iterable, List, Literal, Optional, Type, Union

from dallinger import db
from dallinger.models import Vector
from sqlalchemy import (
    Boolean,
    Column,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    and_,
    func,
    or_,
)
from sqlalchemy.ext.associationproxy import association_proxy
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import relationship, subqueryload
from sqlalchemy.sql.expression import not_, select
from tqdm import tqdm

from ..data import SQLMixinDallinger
from ..field import PythonList, PythonObject, VarStore
from ..page import wait_while
from ..participant import Participant
from ..sync import SyncGroup
from ..timeline import is_list_of
from ..utils import (
    call_function_with_context,
    deep_copy,
    get_logger,
    is_method_overridden,
    log_time_taken,
    negate,
)
from .main import (
    NetworkTrialMaker,
    NetworkTrialMakerState,
    Selection,
    Trial,
    TrialNetwork,
    TrialNode,
)

logger = get_logger()


@dataclass(frozen=True)
class Candidate:
    """Connect a selection-hook value to its already-loaded network.

    ``value`` is the paradigm-specific object exposed to experiment authors:
    a network for chain trial makers and a node for static trial makers.
    ``network`` is the backing object used internally for capacity, asynchronous
    state, and block checks.

    Keeping both references together is intentional. In particular, static
    discovery must not recover the network through ``node.network``: that
    reverse ORM relationship is not populated when ``network.head`` is loaded
    and would issue lazy queries for every candidate.
    """

    value: Any
    network: "ChainNetwork"


def _count_viable_trials_for_nodes(node_ids: Iterable[int]) -> dict[int, int]:
    """Return viable trial counts keyed by node ID."""

    ids = list(dict.fromkeys(node_id for node_id in node_ids if node_id is not None))
    if not ids:
        return {}
    rows = (
        db.session.query(Trial.node_id, func.count(Trial.id))
        .filter(
            Trial.node_id.in_(ids),
            Trial.is_repeat_trial.is_(False),
            Trial.failed.is_(False),
        )
        .group_by(Trial.node_id)
        .all()
    )
    return {node_id: count for node_id, count in rows}


def count_viable_trials_for_nodes(node_ids: Iterable[int]) -> dict[int, int]:
    """Return viable trial counts keyed by node id.

    A viable trial is non-failed and not a repeat trial.
    """
    return _count_viable_trials_for_nodes(node_ids)


def _viable_trial_count_expression(node_id):
    """Return a correlated expression counting viable trials for a node ID."""

    return (
        select(func.count(Trial.id))
        .where(
            Trial.node_id == node_id,
            Trial.is_repeat_trial.is_(False),
            Trial.failed.is_(False),
        )
        .scalar_subquery()
    )


def count_viable_trials_for_node(node_id: int) -> int:
    """Return the number of viable trials for one node."""
    return _count_viable_trials_for_nodes([node_id]).get(node_id, 0)


def count_completed_trials_for_networks(
    network_ids: Iterable[int],
) -> dict[int, int]:
    """Return completed trial counts keyed by network id.

    Counts completed, non-failed, non-repeat trials.
    """
    ids = [network_id for network_id in network_ids if network_id is not None]
    if not ids:
        return {}
    rows = (
        db.session.query(Trial.network_id, func.count(Trial.id))
        .filter(
            Trial.network_id.in_(ids),
            Trial.failed.is_(False),
            Trial.complete.is_(True),
            Trial.is_repeat_trial.is_(False),
        )
        .group_by(Trial.network_id)
        .all()
    )
    return {network_id: count for network_id, count in rows}


def count_completed_trials_for_network(network_id: int) -> int:
    """Count completed, non-failed, non-repeat trials in a network."""
    return count_completed_trials_for_networks([network_id]).get(network_id, 0)


def count_participant_trials_in_trial_maker(module_state_id: int) -> int:
    """Count trials owned by a chain trial-maker module state."""
    return (
        db.session.query(func.count(Trial.id))
        .filter(Trial.module_state_id == module_state_id)
        .scalar()
    )


def count_participant_trials_in_block(module_state_id: int, block_position: int) -> int:
    """Count trials for a module state at a given block position.

    ``block_position`` is defined on :class:`ChainTrial`, not the base Trial.
    """
    return (
        db.session.query(func.count(ChainTrial.id))
        .filter(
            ChainTrial.module_state_id == module_state_id,
            ChainTrial.block_position == block_position,
        )
        .scalar()
    )


# class HasSeed:
#     # Mixin class that provides a 'seed' slot.
#     # See https://docs.sqlalchemy.org/en/14/orm/inheritance.html#resolving-column-conflicts
#     @declared_attr
#     def seed(cls):
#         return cls.__table__.c.get(
#             "seed", Column(JSONB, server_default="{}", default=lambda: {})
#         )
#
#     __extra_vars__ = {}
#     register_extra_var(__extra_vars__, "seed", field_type=dict)

# Vector.type = Column(String(50))
# Vector.__mapper_args__ = {"polymorphic_on": Vector.type, "polymorphic_identity": "vector"}


class ChainVector(SQLMixinDallinger, Vector):
    def __init__(self, origin, destination):
        """
        Patched version of ``dallinger.models.Vector`` that does not assume that
        ``origin`` or ``destination`` have been committed to the database yet.
        """
        self.origin = origin
        self.destination = destination
        self.network = self.origin.network


class ChainNetwork(TrialNetwork):
    """
    Implements a network in the form of a chain.
    Intended for use with :class:`~psynet.trial.chain.ChainTrialMaker`.
    Typically the user won't have to override anything here,
    but they can optionally override :meth:`~psynet.trial.chain.ChainNetwork.validate`.

    Parameters
    ----------

    experiment
        An instantiation of :class:`psynet.experiment.Experiment`,
        corresponding to the current experiment.

    chain_type
        Either ``"within"`` for within-participant chains,
        or ``"across"`` for across-participant chains.

    trials_per_node
        Number of satisfactory trials to be received by the last node
        in the chain before another chain will be added.
        Most paradigms have this equal to 1.

    target_n_nodes
        Indicates the target number of nodes for that network.
        In a network with one trial per node, the total number of nodes will generally
        be one greater than the total number of trials. This is because
        we start with one node, representing the random starting location of the
        chain, and each new trial takes us to a new node.

    participant
        Optional participant with which to associate the network.

    id_within_participant
        If ``participant is not None``, then this provides an optional ID for the network
        that is unique within a given participant.

    sync_group_type : Optional[str]
        The ``sync_group_type`` attribute of the trial maker that owns this network.

    sync_group : Optional[SyncGroup]
        The SyncGroup that owns this network (normally only relevant for within-style chains).


    Attributes
    ----------

    target_n_trials : int or None
        Indicates the target number of trials for that network.
        Left empty by default, but can be set by custom ``__init__`` functions.

    earliest_async_process_start_time : Optional[datetime]
        Time at which the earliest pending async process was called.

    var : :class:`~psynet.field.VarStore`
        A repository for arbitrary variables; see :class:`~psynet.field.VarStore` for details.

    participant_id : int
        The ID of the associated participant, or ``None`` if there is no such participant.
        Set by default in the ``__init__`` function.

    id_within_participant
        If ``participant is not None``, then this provides an optional ID for the network
        that is unique within a given participant.
        Set by default in the ``__init__`` function.

    chain_type
        Either ``"within"`` for within-participant chains,
        or ``"across"`` for across-participant chains.
        Set by default in the ``__init__`` function.

    trials_per_node
        Number of satisfactory trials to be received by the last node
        in the chain before another chain will be added.
        Most paradigms have this equal to 1.
        Set by default in the ``__init__`` function.
    """

    # pylint: disable=abstract-method
    nodes_can_spawn = True

    chain_type = Column(String)
    head_id = Column(Integer, ForeignKey("node.id"))
    trials_per_node = Column(Integer)
    definition = Column(PythonObject)
    context = Column(PythonObject)
    block = Column(String, index=True)

    head = relationship(
        "ChainNode", foreign_keys=[head_id], post_update=True, lazy="joined"
    )

    def __init__(
        self,
        trial_maker_id: str,
        start_node,
        experiment,
        chain_type: str,
        trials_per_node: int,
        target_n_nodes: int,
        participant=None,
        id_within_participant: Optional[int] = None,
        sync_group_type: Optional[str] = None,
        sync_group: Optional[SyncGroup] = None,
    ):
        super().__init__(
            trial_maker_id,
            experiment,
            sync_group_type=sync_group_type,
            sync_group=sync_group,
        )
        db.session.add(self)

        if participant is not None:
            self.id_within_participant = id_within_participant
            self.participant_id = participant.id
            self.participant = participant

        self.chain_type = chain_type
        self.trials_per_node = trials_per_node
        self.target_n_nodes = target_n_nodes
        self.target_n_trials = target_n_nodes * trials_per_node

        self.definition = self.make_definition()
        self.block = start_node.block

        if start_node.participant_group:
            self.participant_group = start_node.participant_group
        elif isinstance(self.definition, dict):
            try:
                self.participant_group = self.definition["participant_group"]
            except KeyError:
                pass
        else:
            self.participant_group = "default"

        db.session.add(start_node)
        self.add_node(start_node)
        start_node.check_on_deploy()

        self.validate()

    def validate(self):
        """
        Runs at the end of the constructor function to check that the
        network object has a legal structure. This can be useful for
        checking that the user hasn't passed illegal argument values.
        """
        pass

    def make_definition(self):
        """
        Derives the definition for the network.
        This definition represents some collection of attributes
        that is shared by all nodes/trials in a network,
        but that may differ between networks.

        Suppose one wishes to have multiple networks in the experiment,
        each characterised by a different value of an attribute
        (e.g. a different color).
        One approach would be to sample randomly; however, this would not
        guarantee an even distribution of attribute values.
        In this case, a better approach is to use the
        :meth:`psynet.trial.chain.ChainNetwork.balance_across_networks`
        method, as follows:

        ::

            colors = ["red", "green", "blue"]
            return {
                "color": self.balance_across_networks(colors)
            }

        See :meth:`psynet.trial.chain.ChainNetwork.balance_across_networks`
        for details on how this balancing works.

        Returns
        -------

        object
            By default this returns an empty dictionary,
            but this can be customised by subclasses.
            The object should be suitable for serialisation to JSON.
        """
        return {}

    def balance_across_networks(self, values: list):
        """
        Chooses a value from a list, with choices being balanced across networks.
        Relies on the fact that network IDs are guaranteed to be consecutive.
        sequences of integers.

        Suppose we wish to assign our networks to colors,
        and we want to balance color assignment across networks.
        We might write the following:

        ::

            colors = ["red", "green", "blue"]
            chosen_color = self.balance_across_networks(colors)

        In across-participant chain designs,
        :meth:`~psynet.trial.chain.ChainNetwork.balance_across_networks`
        will ensure that the distribution of colors is maximally uniform across
        the experiment by assigning
        the first network to red, the second network to green, the third to blue,
        then the fourth to red, the fifth to green, the sixth to blue,
        and so on. This is achieved by referring to the network's
        :attr:`~psynet.trial.chain.ChainNetwork.id`
        attribute.
        In within-participant chain designs,
        the same method is used but within participants,
        so that each participant's first network is assigned to red,
        their second network to green,
        their third to blue,
        then their fourth, fifth, and sixth to red, green, and blue respectively.

        Parameters
        ----------

        values
            The list of values from which to choose.

        Returns
        -------

        Object
            An object from the provided list.
        """
        # This ensures that ``self.id`` is available even if the object has yet to be committed to the database
        db.session.flush()

        if self.chain_type == "across":
            id_to_use = self.id
        elif self.chain_type == "within":
            id_to_use = self.id_within_participant
        else:
            raise RuntimeError(f"Unexpected chain_type: {self.chain_type}")

        return values[id_to_use % len(values)]

    @property
    def target_n_nodes(self):
        return self.max_size

    @target_n_nodes.setter
    def target_n_nodes(self, target_n_nodes):
        self.max_size = target_n_nodes

    @property
    def degree(self):
        if self.head is None:
            return 0
        else:
            return self.head.degree

    # @property
    # def head(self):
    #     return self.get_node_with_degree(self.degree)

    def get_node_with_degree(self, degree):
        nodes = [n for n in self.alive_nodes if n.degree == degree]
        nodes.sort(key=lambda n: n.id)

        first_node = nodes[0]
        other_nodes = nodes[1:]
        for node in other_nodes:
            node.fail(reason=f"duplicate_node_at_degree_{node.degree}")
        return first_node

    def add_node(self, node):
        node.set_network(self)
        # ``can_spawn`` is structural: it says whether this node is ever allowed
        # to create a child. Dynamic readiness is computed live from trials.
        node.can_spawn = self.nodes_can_spawn and node.degree < self.max_size
        if node.degree == 0:
            self.context = node.context
        if node.degree > 0:
            # previous_head = self.get_node_with_degree(node.degree - 1)
            previous_head = self.head
            vector = ChainVector(origin=previous_head, destination=node)
            db.session.add(vector)
            previous_head.child = node
            node.parent = previous_head
        if node.degree >= self.max_size:
            # Setting full=True means that no participants will be assigned to the final node,
            # and it'll just be used as a summary of the chain's final state.
            #
            # Note: We avoid calling self.calculate_full because it involves a database query.
            self.full = True
        self.head = node

    @property
    def n_trials_still_required(self):
        assert self.target_n_trials is not None
        if self.full:
            return 0
        else:
            return self.target_n_trials - count_completed_trials_for_network(self.id)

    @hybrid_property
    def ready_to_spawn(self):
        raise AttributeError(
            "ChainNetwork.ready_to_spawn has been removed. Network growth now "
            "uses live readiness queries; use the trial maker's "
            "ready_to_grow_network_query() helper instead."
        )

    @ready_to_spawn.expression
    def ready_to_spawn(cls):
        raise AttributeError(
            "ChainNetwork.ready_to_spawn has been removed. Network growth now "
            "uses live readiness queries; use the trial maker's "
            "ready_to_grow_network_query() helper instead."
        )

    @hybrid_property
    def n_viable_trials_at_head(self):
        if self.head is None:
            return 0
        return _count_viable_trials_for_nodes([self.head.id]).get(self.head.id, 0)

    @n_viable_trials_at_head.expression
    def n_viable_trials_at_head(cls):
        return _viable_trial_count_expression(cls.head_id)


class ChainNode(TrialNode):
    """
    Represents a node in a chain network.
    In an experimental context, the node represents a state in the experiment;
    in particular, the last node in the chain represents a current state
    in the experiment.

    This class is intended for use with :class:`~psynet.trial.chain.ChainTrialMaker`.
    It subclasses :class:`dallinger.models.Node`.

    The most important attribute is :attr:`~psynet.trial.chain.ChainNode.definition`.
    This is the core information that represents the current state of the node.
    In a transmission chain of drawings, this might be an (encoded) drawing;
    in a Markov Chain Monte Carlo with People paradigm, this might be the current state
    from the proposal is sampled.

    The user is required to override the following abstract methods:

    * :meth:`~psynet.trial.chain.ChainNode.create_definition_from_seed`,
      which creates a node definition from the seed passed from the previous
      source or node in the chain;

    * :meth:`~psynet.trial.chain.ChainNode.summarize_trials`,
      which summarizes the trials at a given node to produce a seed that can
      be passed to the next node in the chain.

    Parameters
    ----------

    seed
        The seed which is used to initialize the node, potentially stochastically.
        This seed typically comes from either a :class:`~psynet.trial.chain.ChainSource`
        or from another :class:`~psynet.trial.chain.ChainNode`
        via the :meth:`~psynet.trial.chain.ChainNode.create_seed` method.
        For example, in a transmission chain of drawings, the seed might be
        a serialised version of the last drawn image.

    degree
        The position of the node in the chain,
        where 0 indicates the source,
        where 1 indicates the first node,
        2 the second node, and so on.

    network
        The network with which the node is to be associated.

    experiment
        An instantiation of :class:`psynet.experiment.Experiment`,
        corresponding to the current experiment.

    propagate_failure
        If ``True``, the failure of a trial is propagated to other
        parts of the experiment (the nature of this propagation is left up
        to the implementation).

    participant
        Optional participant with which to associate the node.

    Attributes
    ----------

    degree
        See the ``__init__`` function.

    child_id
        See the ``__init__`` function.

    seed
        See the ``__init__`` function.

    definition
        This is the core information that represents the current state of the node.
        In a transmission chain of drawings, this might be an (encoded) drawing;
        in a Markov Chain Monte Carlo with People paradigm, this might be the current state
        from the proposal is sampled.
        It is set by the :meth:`~psynet.trial.chain.ChainNode:create_definition_from_seed` method.

    propagate_failure
        See the ``__init__`` function.

    var : :class:`~psynet.field.VarStore`
        A repository for arbitrary variables; see :class:`~psynet.field.VarStore` for details.

    child
        The node's child (i.e. direct descendant) in the chain, or
        ``None`` if no child exists.

    target_n_trials
        The target number of trials for the node,
        set from :attr:`psynet.trial.chain.ChainNetwork.trials_per_node`.

    can_spawn
        Returns ``True`` if the node is structurally allowed to spawn a child.
        Dynamic readiness is computed live from trial state.

    complete_and_processed_trials
        Returns all completed trials associated with the node,
        excluding those that are awaiting some asynchronous processing.
        excludes failed nodes.

    completed_trials
        Returns all completed trials associated with the node.
        Excludes failed nodes and repeat trials.

    n_completed_trials
        Counts the number of completed trials associated with the node.
        Excludes failed nodes and repeat_trials.

    all_trials : list
        A list of all trials owned by that node.

    alive_trials : list
        A list of all non-failed trials owned by that node.

    failed_trials : list
        A list of all failed trials owned by that node.

    viable_trials
        Returns all viable trials associated with the node,
        i.e. all trials that have not failed.
    """

    key = Column(String, index=True)
    degree = Column(Integer)
    target_n_trials = Column(Integer)
    can_spawn = Column(Boolean, default=False, index=True)
    child_id = Column(Integer, ForeignKey("node.id"), index=True)
    parent_id = Column(Integer, ForeignKey("node.id"), index=True)
    seed = Column(PythonObject, default=lambda: {})
    definition = Column(PythonObject, default=lambda: {})
    context = Column(PythonObject)
    participant_group = Column(String, index=True)
    block = Column(String, index=True)
    propagate_failure = Column(Boolean)

    child = relationship(
        "ChainNode",
        foreign_keys=[child_id],
        remote_side=TrialNode.id,
        uselist=False,
        post_update=True,
    )
    parent = relationship(
        "ChainNode",
        foreign_keys=[parent_id],
        remote_side=TrialNode.id,
        uselist=False,
        post_update=True,
    )

    @property
    def chain(self):
        return self.network

    @chain.setter
    def chain(self, value):
        self.network = value

    def __init__(
        self,
        *,
        definition=None,
        context=None,
        seed=None,
        parent=None,
        participant_group=None,
        block=None,
        assets=None,
        degree=None,
        module_id=None,
        network=None,
        experiment=None,
        participant=None,
        propagate_failure=False,
    ):
        super().__init__(network=network, participant=participant)

        assert not (definition and seed)

        if participant_group is None:
            if parent:
                participant_group = parent.participant_group
            else:
                participant_group = "default"

        if block is None:
            if parent:
                block = parent.block
            else:
                block = "default"

        if not isinstance(block, str):
            raise ValueError(f"block must be a string (got {block}).")

        if degree is None:
            if parent:
                degree = parent.degree + 1
            else:
                degree = 0

        self.degree = degree
        self.can_spawn = False

        if module_id is None:
            if parent:
                module_id = parent.module_id

        if context is None:
            if parent:
                context = parent.context

        if assets is None:
            assets = {}

        # This is the legacy interface -- if we are using the new interface (make_next_definition),
        # then definition will have been provided.
        if not definition and not self.definition:
            if not seed:
                if degree == 0:
                    seed = self.create_initial_seed(experiment, participant)
                else:
                    assert parent is not None
                    seed = parent.create_seed(experiment, participant)
            definition = self.create_definition_from_seed(seed, experiment, participant)

        if definition:
            self.definition = definition

        self.assets = assets
        self.block = block
        self.participant_group = participant_group
        self.module_id = module_id
        self.seed = seed
        self.context = context
        self.propagate_failure = propagate_failure
        self._staged_assets = assets

        if parent:
            parent.child = self
            self.parent = parent

    def make_next_definition(self, experiment, participant) -> dict:
        """
        Creates the definition for the next node in the chain.

        Parameters
        ----------

        experiment
            An instantiation of :class:`psynet.experiment.Experiment`,
            corresponding to the current experiment.

        participant
            The participant who initiated the creation of the node
            (if relevant).

        Returns
        -------

        dict
            The definition for the next node in the chain.
        """
        # The default make_next_definition uses the legacy ``create_seed`` and
        # ``create_definition_from_seed`` methods for back-compatibility.
        # We encourage users to avoid using ``create_seed`` and ``create_definition_from_seed``,
        # and instead put their full logic in ``make_next_definition``.
        seed = self.create_seed(experiment, participant)
        definition = self.create_definition_from_seed(seed, experiment, participant)
        self.seed = seed
        return definition

    def set_network(self, network):
        super().set_network(network)
        self.target_n_trials = network.trials_per_node

    def create_initial_seed(self, experiment, participant):
        raise NotImplementedError

    def stage_assets(self, experiment):
        # self.assets = {}

        for local_key, asset in self._staged_assets.items():
            asset.update_metadata(
                self,
                local_key,
                definition=self.definition,
                module_id=self.module_id,
            )

            experiment.assets.stage(asset)
            self.assets[local_key] = asset

    def create_definition_from_seed(self, seed, experiment, participant):
        """
        Creates a node definition from a seed.
        The seed comes from the previous node in the chain.
        In many cases (e.g. iterated reproduction) the definition
        will be trivially equal to the seed,
        but in some cases we may introduce some kind of stochastic alteration
        to produce the definition.

        Parameters
        ----------

        seed : object
            The seed, passed from the previous state in the chain.

        experiment
            An instantiation of :class:`psynet.experiment.Experiment`,
            corresponding to the current experiment.

        participant
            The participant who initiated the creation of the node.

        Returns
        -------

        object
            The derived definition. Should be suitable for serialisation to JSON.
        """
        raise NotImplementedError

    def summarize_trials(self, trials: list, experiment, participant):
        """
        Summarizes the trials at the node to produce a seed that can
        be passed to the next node in the chain.

        Parameters
        ----------

        trials
            Trials to be summarized. By default only trials that are completed
            (i.e. have received a response) and processed
            (i.e. aren't waiting for an asynchronous process)
            are provided here.

        experiment
            An instantiation of :class:`psynet.experiment.Experiment`,
            corresponding to the current experiment.

        participant
            The participant who initiated the creation of the node.

        Returns
        -------

        object
            The derived seed. Should be suitable for serialisation to JSON.
        """
        raise NotImplementedError

    def create_seed(self, experiment, participant):
        trials = self.completed_and_processed_trials
        return self.summarize_trials(trials, experiment, participant)

    @property
    def var(self):
        return VarStore(self)

    # @property
    # def ready_to_spawn(self):
    #     return self.reached_target_n_trials

    @property
    def completed_and_processed_trials(self):
        return [
            t
            for t in self.alive_trials
            if (t.complete and t.finalized and not t.is_repeat_trial)
        ]

    @hybrid_property
    def n_completed_and_processed_trials(self):
        return len(self.completed_and_processed_trials)

    @n_completed_and_processed_trials.expression
    def n_completed_and_processed_trials(cls):
        return (
            select(func.count(Trial.id))
            .where(
                Trial.node_id == TrialNode.id,
                Trial.complete,
                Trial.finalized,
                ~Trial.failed,
                ~Trial.is_repeat_trial,
            )
            .scalar_subquery()
        )

    @hybrid_property
    def reached_target_n_trials(self):
        if self.target_n_trials is None:
            return False
        else:
            return self.n_completed_and_processed_trials >= self.target_n_trials

    def update_status(self):
        super().update_status()

    def check_ready_to_spawn(self):
        raise AttributeError(
            "ChainNode.check_ready_to_spawn() has been removed. Node readiness "
            "is computed live by ChainTrialMaker.ready_to_grow_network_query()."
        )

    def _ready_to_spawn(self):
        raise AttributeError(
            "ChainNode._ready_to_spawn() has been removed. Node readiness is "
            "computed live by ChainTrialMaker.ready_to_grow_network_query()."
        )

    @property
    def viable_trials(self):
        return [t for t in self.alive_trials if not t.is_repeat_trial]

    def fail(self, reason=None):
        if self.network.head == self:
            self.network.head = self.parent
        if self.degree == 0:
            self.network.fail(reason=f"Start node failed (reason: {reason})")
        super().fail(reason)

    @property
    def failure_cascade(self):
        to_fail = []
        if self.propagate_failure:
            to_fail.append(lambda: self.alive_trials)
            if self.child:
                to_fail.append(lambda: [self.child])
        return to_fail


def _n_viable_trials(node):
    """Return the current viable-trial count for a node."""

    return _count_viable_trials_for_nodes([node.id]).get(node.id, 0)


TrialNode.n_viable_trials = hybrid_property(
    _n_viable_trials,
    expr=lambda cls: _viable_trial_count_expression(cls.id),
)


UniqueConstraint(ChainNode.module_id, ChainNode.key)


class ChainTrial(Trial):
    """
    Represents a trial in a :class:`~psynet.trial.chain.ChainNetwork`.
    The user is expected to override the following methods:

    * :meth:`~psynet.trial.chain.ChainTrial.make_definition`,
      responsible for deciding on the content of the trial.
    * :meth:`~psynet.trial.chain.ChainTrial.show_trial`,
      determines how the trial is turned into a webpage for presentation to the participant.
    * :meth:`~psynet.trial.chain.ChainTrial.show_feedback`.
      defines an optional feedback page to be displayed after the trial.

    The user must also override the ``time_estimate`` class attribute,
    providing the estimated duration of the trial in seconds.
    This is used for predicting the participant's reward
    and for constructing the progress bar.

    The user may also wish to override the
    :meth:`~psynet.trial.chain.ChainTrial.async_post_trial` method
    if they wish to implement asynchronous trial processing.

    This class subclasses :class:`~psynet.trial.main.Trial`.
    Trials are stored in the physical ``trial`` table, not Dallinger's
    ``info`` table. Custom trial classes use single-table polymorphism
    within ``trial``.

    Instances can be retrieved using *SQLAlchemy*; for example, the
    following command retrieves the ``ChainTrial`` object with an ID of 1:

    ::

        ChainTrial.query.filter_by(id=1).one()

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

    run_async_post_trial : bool
        Set this to ``True`` if you want the :meth:`~psynet.trial.main.Trial.async_post_trial`
        method to run after the user responds to the trial.

    Attributes
    ----------

    time_estimate : numeric
        The estimated duration of the trial (including any feedback), in seconds.
        This should generally correspond to the (sum of the) ``time_estimate`` parameters in
        the page(s) generated by ``show_trial``, plus the ``time_estimate`` parameter in
        the page generated by ``show_feedback`` (if defined).
        This is used for predicting the participant's reward
        and for constructing the progress bar.

    node
        The class:`dallinger.models.Node` to which the :class:`~dallinger.models.Trial`
        belongs.

    participant_id : int
        The ID of the associated participant.
        The user should not typically change this directly.
        Stored in ``property1`` in the database.

    answer : Object
        The response returned by the participant. This is serialised
        to JSON, so it shouldn't be too big.
        The user should not typically change this directly.
        Stored in ``details`` in the database.

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

    """

    # pylint: disable=abstract-method

    participant_group = association_proxy("node", "participant_group")
    degree = association_proxy("node", "degree")
    context = association_proxy("node", "context")

    block_position = Column(Integer, index=True)
    block = Column(String, index=True)

    @property
    def chain(self):
        return self.network

    @chain.setter
    def chain(self, value):
        self.network = value

    def __init__(self, experiment, node, participant, *args, **kwargs):
        super().__init__(experiment, node, participant, *args, **kwargs)
        if participant.in_module and hasattr(
            participant.module_state, "block_position"
        ):
            self.block_position = participant.module_state.block_position
            self.block = participant.module_state.block

    def make_definition(self, experiment, participant):
        for k, v in self.node.assets.items():
            self.assets[k] = v
        return deep_copy(self.node.definition)

    # @property
    # @extra_var(__extra_vars__)
    # def degree(self):
    #     return self.node.degree
    #
    # @property
    # def node(self):
    #     return self.origin

    def fail(self, reason=None):
        super().fail(reason)
        self.node.update_status()

    @property
    def failure_cascade(self):
        """Fail ``node.child`` when this trial is finalized and already has one."""
        to_fail = []
        if self.propagate_failure and self.finalized and self.node.child:
            to_fail.append(lambda: [self.node.child])
        return to_fail

    @property
    def trial_maker(self) -> "ChainTrialMaker":
        return self.node.trial_maker

    def on_finalized(self):
        super().on_finalized()
        self.node.update_status()
        if self.trial_maker:
            # This is a latency fast path. The scheduled growth poller is still
            # responsible for eventual growth correctness if this callback is
            # missed or races with other work.
            self.trial_maker.call_grow_network(network=self.network)


class ChainTrialMakerState(NetworkTrialMakerState):
    block_order = Column(PythonList)
    block_position = Column(Integer)
    block = Column(String)
    participated_networks = Column(PythonList, default=lambda: [])

    # @hybrid_property
    # def block(self):
    #     return self.block_order[self.block_position]

    @property
    def n_blocks(self):
        return len(self.block_order)

    @property
    def remaining_blocks(self):
        return self.block_order[self.block_position :]

    def set_block_position(self, i):
        self.block_position = i
        self.block = self.block_order[i]

    def go_to_next_block(self):
        self.set_block_position(self.block_position + 1)


ChainTrialMakerState.n_participant_trials_in_trial_maker = property(
    lambda self: count_participant_trials_in_trial_maker(self.id)
)

ChainTrialMakerState.n_participant_trials_in_block = property(
    lambda self: count_participant_trials_in_block(self.id, self.block_position)
)


class ChainTrialMaker(NetworkTrialMaker):
    """
    Administers a sequence of trials in a chain-based paradigm.

    :meth:`~psynet.trial.chain.ChainTrialMaker.find_chains` applies PsyNet's
    eligibility checks and returns all remaining chains.
    :meth:`~psynet.trial.chain.ChainTrialMaker.select_chain` then chooses one.
    Override ``select_chain`` to change assignment among eligible chains;
    override ``custom_chain_filter`` to change eligibility. Do not override
    ``find_chains`` unless you need to replace that whole procedure.

    Parameters
    ----------

    node_class
        The class object for the networks used by this maker.
        This should subclass :class:`~psynet.trial.chain.ChainNode`.

    trial_class
        The class object for trials administered by this maker
        (should subclass :class:`~psynet.trial.chain.ChainTrial`).

    network_class
        The class object for the networks used by this maker.
        This should subclass :class:`~psynet.trial.chain.ChainNetwork`.

    chain_type
        Either ``"within"`` for within-participant chains,
        or ``"across"`` for across-participant chains.

    expected_trials_per_participant
        Expected number of trials that each participant will complete.
        This can either be an integer, or the string ``"n_start_nodes"``,
        which will be read as referring to the number of start nodes with
        which the trial maker is initialized
        (i.e. ``len(start_nodes)``, ``chains_per_experiment``,
        or ``chains_per_participant`` as appropriate).
        This is used for timeline/progress estimation purposes.

    max_trials_per_participant
        Maximum number of trials that each participant may complete (optional);
        once this number is reached, the participant will move on
        to the next stage in the timeline.
        This can either be an integer, or the string ``"n_start_nodes"``,
        which will be read as referring to the number of start nodes with
        which the trial maker is initialized
        (i.e. ``len(start_nodes)``, ``chains_per_experiment``,
        or ``chains_per_participant`` as appropriate).

    chains_per_participant
        Number of chains to be created for each participant;
        only relevant if ``chain_type="within"``.
        Not required if ``start_nodes`` is provided.

    chains_per_experiment
        Number of chains to be created for the entire experiment;
        only relevant if ``chain_type="across"``.
        Not required if ``start_nodes`` is provided.

    max_nodes_per_chain
        Specifies chain length in terms of the
        number of data-collection iterations that are required to complete a chain.
        The number of successful participant trials required to complete the chain then
        corresponds to ``trials_per_node * max_nodes_per_chain``.

    max_nodes_per_chain
        Maximum number of nodes in the chain before the chain is marked as full and no more nodes will be added.

    trials_per_node
        Number of satisfactory trials to be received by the last node
        in the chain before another chain will be added.
        Most paradigms have this equal to 1.

    balance_across_chains
        Whether trial selection should be actively balanced across chains,
        such that trials are preferentially sourced from chains with
        fewer valid trials.

    start_nodes
        A list of nodes that are used to initialize the chains.
        In an across-participant trial maker, this should be a simple list of instances of the class ``node_class``.
        In a within-participant trial maker, a fresh set of nodes should be created for each new participant.
        To achieve this, ``start_nodes`` should be a lambda function that returns a list of newly created nodes.
        This lambda function may accept ``participant`` as one of its arguments.

    # balance_strategy
        #   A two-element list that determines how balancing occurs, if ``balance_across_chains`` is ``True``.
        #   If the list contains "across", then the balancing will take into account trials from other participants.
        #   If it contains "within", then the balancing will take into account trials from the present participant.
        #   If both are selected, then the balancing strategy will prioritize balancing within the current participant,
        #   but will use counts from other participants as a tie breaker.

    check_performance_at_end
        If ``True``, the participant's performance
        is evaluated at the end of the series of trials.

    check_performance_every_trial
        If ``True``, the participant's performance
        is evaluated after each trial.

    recruit_mode
        Selects a recruitment criterion for determining whether to recruit
        another participant. The built-in criteria are ``"n_participants"``
        and ``"n_trials"``.

    target_n_participants
        Target number of participants to recruit for the experiment. All
        participants must successfully finish the experiment to count
        towards this quota. This target is only relevant if
        ``recruit_mode="n_participants"``.

    fail_trials_on_premature_exit
        See :class:`~psynet.trial.main.TrialMaker`.

    fail_trials_on_participant_performance_check
        See :class:`~psynet.trial.main.TrialMaker`. Defaults to ``False``
        because failing completed trials can invalidate large amounts of
        downstream chain data.

    propagate_failure
        If ``True``, the failure of a trial is propagated to other
        parts of the experiment (the nature of this propagation is left up
        to the implementation).

    n_repeat_trials
        Number of repeat trials to present to the participant. These trials
        are typically used to estimate the reliability of the participant's
        responses.
        Defaults to ``0``.

    wait_for_networks
        If ``True``, then the participant will be made to wait if there are
        still more networks to participate in, but these networks are pending asynchronous processes.

    allow_revisiting_networks_in_across_chains : bool
        If this is set to ``True``, then participants can revisit the same network
        in across-participant chains. The default is ``False``.

    choose_participant_group
        Only relevant if the trial maker uses nodes with non-default participant groups.
        In this case the experimenter is expected to supply a function that takes participant as an argument
        and returns the chosen participant group for that trial maker.
        For example, to randomly assign participants to one of two groups called g1 and g2, one could write::

            choose_participant_group=lambda(participant): random.choice(["g1", "g2"])

        Similarly, to alternate participants between two groups, one could write::

            choose_participant_group=lambda(participant): ["g1", "g2"][participant.id % 2]

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
        When ``sync_group_max_wait_time`` is exceeded: ``"fail"`` fails the participant; ``"kick"`` removes them
        from the group and lets them continue. Defaults to ``"fail"``.

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

    performance_threshold : float
        Score threshold used by the default performance check method, defaults to 0.0.
        By default, corresponds to the minimum proportion of non-failed trials that
        the participant must achieve to pass the performance check.

    end_performance_check_waits : bool
        If ``True`` (default), then the final performance check waits until all trials no
        longer have any pending asynchronous processes.
    """

    state_class = ChainTrialMakerState

    def __init__(
        self,
        *,
        id_,
        trial_class: Type[ChainTrial],
        node_class: Type[ChainNode],
        network_class: Optional[Type[ChainNetwork]] = None,
        chain_type: str,
        expected_trials_per_participant: int | str,
        max_trials_per_participant: Optional[int | str] = None,
        max_trials_per_block: Optional[int] = None,
        max_nodes_per_chain: Optional[int] = None,
        chains_per_participant: Optional[int] = None,
        chains_per_experiment: Optional[int] = None,
        trials_per_node: int = 1,
        n_repeat_trials: int = 0,
        target_n_participants: Optional[int] = None,
        balance_across_chains: bool = False,
        start_nodes: Optional[Union[callable, List[ChainNode]]] = None,
        # balance_strategy: Set[str] = {"within", "across"},
        check_performance_at_end: bool = False,
        check_performance_every_trial: bool = False,
        recruit_mode: str = "n_participants",
        fail_trials_on_premature_exit: bool = False,
        fail_trials_on_participant_performance_check: bool = False,
        propagate_failure: bool = True,
        wait_for_networks: bool = False,
        allow_revisiting_networks_in_across_chains: bool = False,
        assets=None,
        choose_participant_group: Optional[callable] = None,
        sync_group_type: Optional[str] = None,
        sync_group_max_wait_time: float = 45.0,
        sync_group_max_wait_action: Literal["fail", "kick"] = "fail",
        sync_group_timeout_between_barriers_time: Optional[float] = None,
        sync_group_timeout_between_barriers_action: Literal["kick", "fail"] = "fail",
    ):
        if network_class is None:
            network_class = self.default_network_class

        assert chain_type in ["within", "across"]

        self.node_class = node_class
        assert isinstance(expected_trials_per_participant, (int, float, str))
        if isinstance(expected_trials_per_participant, str):
            assert expected_trials_per_participant == "n_start_nodes"

        assert max_trials_per_participant is None or isinstance(
            max_trials_per_participant, (int, float, str)
        )
        if isinstance(max_trials_per_participant, str):
            assert max_trials_per_participant == "n_start_nodes"

        if (
            chain_type == "across"
            and expected_trials_per_participant
            and chains_per_experiment
            and expected_trials_per_participant > chains_per_experiment
            and not allow_revisiting_networks_in_across_chains
        ):
            raise ValueError(
                "In across-participant chain experiments, <expected_trials_per_participant> "
                "cannot exceed <chains_per_experiment> unless ``allow_revisiting_networks_in_across_chains`` "
                "is ``True``."
            )

        if chain_type == "within" and recruit_mode == "n_trials":
            raise ValueError(
                "In within-chain experiments the 'n_trials' recruit method is not available."
            )

        if chain_type == "within":
            assert start_nodes is None or callable(start_nodes)
            assert not (start_nodes is None and chains_per_participant is None)
            assert (
                max_trials_per_participant is not None
                or max_trials_per_block is not None
                or max_nodes_per_chain is not None
            )
        elif chain_type == "across":
            assert (
                start_nodes is None
                or callable(start_nodes)
                or is_list_of(start_nodes, ChainNode)
            )
            if allow_revisiting_networks_in_across_chains:
                assert (
                    max_trials_per_participant is not None
                    or max_trials_per_block is not None
                )
        else:
            raise ValueError(f"Unrecognized chain type: {chain_type}")

        if isinstance(start_nodes, list):
            self._validate_start_nodes(start_nodes)
            for node in start_nodes:
                if node.trial_maker_id is not None and node.trial_maker_id != id_:
                    raise RuntimeError(
                        "Nodes cannot belong to multiple modules/trial makers. "
                        "Please make a separate node list for each one."
                    )
                node.trial_maker_id = id_

        self.start_nodes = start_nodes

        if chain_type == "across":
            # Using a pre-deploy constant allows us to count the nodes once on the local deployment machine,
            # and use this same value on the deployed web server.
            # This is helpful when using nodes generated from a directory, because this directory
            # is not necessarily going to be available on the deployed web server.
            from psynet.experiment import pre_deploy_constant

            if chains_per_experiment is not None:
                self.n_start_nodes = chains_per_experiment
            else:
                self.n_start_nodes = pre_deploy_constant(
                    ("trial_maker", id_, "n_start_nodes"),
                    lambda: self.count_start_nodes(),
                )
        else:
            assert chain_type == "within"
            if chains_per_participant is None and "n_start_nodes" in [
                expected_trials_per_participant,
                max_trials_per_participant,
            ]:
                raise ValueError(
                    "Can't use 'n_start_nodes' parameter with within-participant chain trial-makers "
                    "without specifying chains_per_participant."
                )
            self.n_start_nodes = chains_per_participant

        if expected_trials_per_participant == "n_start_nodes":
            expected_trials_per_participant = self.n_start_nodes

        if max_trials_per_participant == "n_start_nodes":
            max_trials_per_participant = self.n_start_nodes

        # assert len(balance_strategy) <= 2
        # assert all([x in ["across", "within"] for x in balance_strategy])

        self.trial_class = trial_class
        self.chain_type = chain_type
        self.max_trials_per_participant = max_trials_per_participant
        self.max_trials_per_block = max_trials_per_block
        self.chains_per_participant = chains_per_participant
        self.chains_per_experiment = chains_per_experiment
        self.max_nodes_per_chain = max_nodes_per_chain
        self.trials_per_node = trials_per_node
        self._node_capacity_is_unlimited = False
        self.balance_across_chains = balance_across_chains
        # self.balance_strategy = balance_strategy
        self.check_performance_at_end = check_performance_at_end
        self.check_performance_every_trial = check_performance_every_trial
        self.propagate_failure = propagate_failure
        self.allow_revisiting_networks_in_across_chains = (
            allow_revisiting_networks_in_across_chains
        )
        self.choose_participant_group = choose_participant_group

        super().__init__(
            id_=id_,
            trial_class=trial_class,
            network_class=network_class,
            expected_trials_per_participant=expected_trials_per_participant
            + n_repeat_trials,
            check_performance_at_end=check_performance_at_end,
            check_performance_every_trial=check_performance_every_trial,
            fail_trials_on_premature_exit=fail_trials_on_premature_exit,
            fail_trials_on_participant_performance_check=fail_trials_on_participant_performance_check,
            propagate_failure=propagate_failure,
            recruit_mode=recruit_mode,
            target_n_participants=target_n_participants,
            n_repeat_trials=n_repeat_trials,
            wait_for_networks=wait_for_networks,
            assets=assets,
            sync_group_type=sync_group_type,
            sync_group_max_wait_time=sync_group_max_wait_time,
            sync_group_max_wait_action=sync_group_max_wait_action,
            sync_group_timeout_between_barriers_time=sync_group_timeout_between_barriers_time,
            sync_group_timeout_between_barriers_action=sync_group_timeout_between_barriers_action,
        )

        self.check_initialization()

    def count_start_nodes(self):
        self.resolve_start_nodes()
        return len(self.start_nodes)

    def resolve_start_nodes(self):
        if callable(self.start_nodes):
            self.start_nodes = call_function_with_context(self.start_nodes)
            self._validate_start_nodes(self.start_nodes)

    def _start_nodes_param_name(self) -> str:
        return "start_nodes"

    def _validate_start_nodes(self, nodes):
        if not isinstance(nodes, list):
            return
        param_name = self._start_nodes_param_name()
        for index, node in enumerate(nodes):
            if node is None:
                continue
            if not isinstance(node, self.node_class):
                raise ValueError(
                    f"{param_name} must be instances of "
                    f"{self.node_class.__name__} (or subclasses). "
                    f"Got {type(node).__name__} at index {index}."
                )

    def _selection_hook_overrides(self):
        return [
            *self._generic_removed_selection_hooks(
                "Override find_chains(participant, experiment) instead.",
                "The selected chain's head is now resolved automatically.",
            ),
            (
                ChainTrialMaker,
                "prioritize_networks",
                "Override select_chain(chains, participant, experiment) instead.",
            ),
            (
                ChainTrialMaker,
                "find_nodes",
                "Chain trial makers now use find_chains(participant, experiment).",
            ),
            (
                ChainTrialMaker,
                "select_node",
                "Chain trial makers now use select_chain(chains, participant, experiment).",
            ),
            (
                ChainTrialMaker,
                "custom_node_filter",
                "Chain trial makers now use custom_chain_filter(chains, participant, experiment).",
            ),
        ]

    def _deprecated_selection_hooks(self):
        return [
            (
                ChainTrialMaker,
                "custom_network_filter",
                # TODO: remove this deprecation once downstream packages
                # (notably psynet-step, https://github.com/pmcharrison/STEP/pull/5)
                # ship custom_chain_filter for PsyNet 14.
                "Override custom_chain_filter(chains, participant, experiment) instead.",
            ),
        ]

    def check_participant_groups(self, networks):
        for n in networks:
            if (
                n.participant_group != "default"
                and self.choose_participant_group is None
            ):
                raise ValueError(
                    f"Since the Trial Maker's starting nodes contain a non-default participant_group "
                    f"({n.participant_group}), you must provide a value for the choose_participant_groups "
                    "argument. This should be a function that takes 'participant' as an argument and returns "
                    "the participant group chosen for that Trial Maker."
                )

    @property
    def default_network_class(self):
        return ChainNetwork

    def init_participant(self, experiment, participant):
        super().init_participant(experiment, participant)
        participant.module_state.participated_networks = []

        sync_group = (
            participant.active_sync_groups[self.sync_group_type]
            if self.sync_group_type
            else None
        )
        is_follower = sync_group and participant != sync_group.leader

        if not is_follower:
            if self.chain_type == "within":
                networks = self.create_networks_within(experiment, participant)
            else:
                networks = self.networks
                if len(self.networks) == 0:
                    raise RuntimeError(
                        f"Couldn't find any networks for the trial maker '{participant.module_state.module_id}'. "
                        "A common reason for this is deploying your experiment using 'dallinger deploy' instead of "
                        "'psynet deploy'. "
                        "Another common reason is reloading the experiment in debug mode after adding a new trial maker. "
                        "In the latter case you need to restart the debug session before continuing."
                    )
            self.check_participant_groups(networks)

            blocks = set([network.block for network in networks])
            self.init_block_order(experiment, participant, blocks)
        else:
            participant.module_state.block_order = (
                sync_group.leader.module_state.block_order
            )
            participant.module_state.set_block_position(
                sync_group.leader.module_state.block_position
            )

    def init_block_order(self, experiment, participant, blocks):
        block_order = call_function_with_context(
            self.choose_block_order,
            experiment=experiment,
            participant=participant,
            blocks=blocks,
        )
        participant.module_state.block_order = block_order
        participant.module_state.set_block_position(0)

    def choose_block_order(self, experiment, participant, blocks):
        # pylint: disable=unused-argument
        """
        Determines the order of blocks for the current participant.
        By default this function shuffles the blocks randomly for each participant.
        The user is invited to override this function for alternative behaviour.

        Parameters
        ----------

        experiment
            An instantiation of :class:`psynet.experiment.Experiment`,
            corresponding to the current experiment.

        participant
            An instantiation of :class:`psynet.participant.Participant`,
            corresponding to the current participant.

        Returns
        -------

        list
            A list of blocks in order of presentation,
            where each block is identified by a string label.
        """
        return random.sample(list(blocks), len(blocks))

    def _should_finish_block(self, participant):
        state = participant.module_state

        assert state.block is not None
        assert state.block_position is not None

        # Used to pass these for convenience, but it produces unnecessary computation.
        # Keeping the code here though in case people overriding this function want
        # to make use of these.
        #
        # trials_in_trial_maker = [
        #     trial for trial in participant.all_trials if trial.trial_maker_id == self.id
        # ]
        # trials_in_block = [
        #     trial
        #     for trial in trials_in_trial_maker
        #     if trial.block_position == block_position
        # ]

        uses_default_policy = (
            type(self).should_finish_block is ChainTrialMaker.should_finish_block
        )
        if uses_default_policy:
            if (
                self.max_trials_per_block is None
                and self.max_trials_per_participant is None
            ):
                return False
            needs_block_count = self.max_trials_per_block is not None
            needs_trial_maker_count = self.max_trials_per_participant is not None
        else:
            # Custom policies historically received both real counts regardless
            # of which built-in limits were configured.
            needs_block_count = True
            needs_trial_maker_count = True

        n_in_block = (
            count_participant_trials_in_block(state.id, state.block_position)
            if needs_block_count
            else 0
        )
        n_in_trial_maker = (
            count_participant_trials_in_trial_maker(state.id)
            if needs_trial_maker_count
            else 0
        )
        return self.should_finish_block(
            participant,
            state.block,
            state.block_position,
            n_in_block,
            n_in_trial_maker,
        )

    def should_finish_block(
        self,
        participant,  # noqa
        block,  # noqa
        block_position,  # noqa
        n_participant_trials_in_block,
        n_participant_trials_in_trial_maker,
    ):  # noqa
        return (
            self.max_trials_per_block is not None
            and n_participant_trials_in_block >= self.max_trials_per_block
        ) or (
            self.max_trials_per_participant is not None
            and n_participant_trials_in_trial_maker >= self.max_trials_per_participant
        )

    @property
    def introduction(self):
        if self.chain_type == "within":
            return wait_while(
                negate(self.all_participant_networks_ready),
                expected_wait=5.0,
                log_message="Waiting for participant networks to be ready.",
                max_wait_time=self.max_time_waiting_for_trial,
            )
        return None

    def all_participant_networks_ready(self, participant):
        cls = self.network_class
        return (
            db.session.query(func.count(cls.id))
            .join(self.node_class, cls.head_id == self.node_class.id)
            .filter(
                cls.participant_id == participant.id,
                cls.trial_maker_id == self.id,
                or_(
                    cls.async_post_grow_network_pending,
                    self.node_class.async_on_deploy_pending,
                ),
            )
            .scalar()
            == 0
        )

    @property
    def n_trials_still_required(self):
        assert self.chain_type == "across"
        networks = list(self.networks)
        for network in networks:
            assert network.target_n_trials is not None
        incomplete = [network for network in networks if not network.full]
        completed = count_completed_trials_for_networks(
            network.id for network in incomplete
        )
        return sum(
            network.target_n_trials - completed.get(network.id, 0)
            for network in incomplete
        )

    #########################
    # Participated networks #
    #########################

    def pre_deploy_routine(self, experiment):
        if self.chain_type == "across":
            self.create_networks_across(experiment)

    def create_networks_within(self, experiment, participant: Participant):
        if self.start_nodes:
            nodes = call_function_with_context(
                self.start_nodes, experiment=experiment, participant=participant
            )
            self._validate_start_nodes(nodes)
            if self.chains_per_participant is not None:
                assert len(nodes) == self.chains_per_participant, (
                    f"Problem with trial maker {self.id}: "
                    f"The number of nodes generated by start_nodes ({len(nodes)} did not equal "
                    f"chains_per_participant ({self.chains_per_participant})."
                )
        else:
            nodes = [None for _ in range(self.chains_per_participant)]

        networks = []
        for i, node in enumerate(nodes):
            network = self.create_network(
                experiment, participant, id_within_participant=i, start_node=nodes[i]
            )
            # self.call_grow_network(network, experiment)  # not necessary any more!
            networks.append(network)
            if node:
                node.check_on_deploy()

        return networks

    def create_networks_across(self, experiment):
        if self.start_nodes:
            self.resolve_start_nodes()
            nodes = self.start_nodes
            assert isinstance(nodes, list)
            if self.chains_per_experiment:
                assert len(nodes) == self.chains_per_experiment, (
                    f"Problem with trial maker {self.id}: "
                    f"The number of nodes provided by start_nodes ({len(nodes)}) did not equal 0 or "
                    f"chains_per_experiment ({self.chains_per_experiment})."
                )
        else:
            nodes = [None for _ in range(self.chains_per_experiment)]

        if len(nodes) == 0:
            raise ValueError(f"No nodes provided for trial maker {self.id}")

        for node in tqdm(nodes, desc="Creating networks"):
            self.create_network(experiment, start_node=node)

        db.session.flush()

        for node in tqdm(nodes, desc="Staging assets"):
            if node is not None:
                node.stage_assets(experiment)

    def create_network(
        self, experiment, participant=None, id_within_participant=None, start_node=None
    ):
        if not start_node:
            start_node = self.node_class(
                network=None, experiment=experiment, participant=participant
            )

        if participant is not None and self.sync_group_type is not None:
            sync_group = participant.active_sync_groups[self.sync_group_type]
        else:
            sync_group = None

        network = self.network_class(
            trial_maker_id=self.id,
            start_node=start_node,
            experiment=experiment,
            chain_type=self.chain_type,
            trials_per_node=self.trials_per_node,
            target_n_nodes=self.max_nodes_per_chain,
            participant=participant,
            id_within_participant=id_within_participant,
            sync_group_type=self.sync_group_type,
            sync_group=sync_group,
        )
        db.session.add(network)
        start_node.set_network(network)
        return network

    @log_time_taken
    def find_chains(self, participant, experiment):
        """Find eligible chains for the participant's next trial.

        This method applies PsyNet's built-in eligibility checks (capacity,
        blocks, asynchronous processes, and
        :meth:`~psynet.trial.chain.ChainTrialMaker.custom_chain_filter`).
        Override ``select_chain`` to change which eligible chain is assigned.
        To wait, exit, or drop candidates after those built-in checks, override
        this method, call ``super().find_chains``, then filter or return
        ``"wait"`` / ``"exit"``. ``select_chain`` cannot return those outcomes.

        Parameters
        ----------
        participant
            The participant receiving the next trial.
        experiment
            The current experiment.

        Returns
        -------
        "exit", "wait", or list of chains
        """
        return self._find_eligible_candidates(participant, experiment)

    _candidate_label = "chain"

    def _find_eligible_candidates(self, participant, experiment):
        """Discover, filter, and order candidates for selection."""
        candidate_plural = f"{self._candidate_label}s"

        logger.info(
            "Looking for eligible %s for participant %i.",
            candidate_plural,
            participant.id,
        )

        n_completed_trials = participant.module_state.n_completed_trials
        if (
            self.max_trials_per_participant is not None
            and n_completed_trials >= self.max_trials_per_participant
        ):
            logger.info(
                "N completed trials (%i) >= N trials per participant (%i), skipping forward",
                n_completed_trials,
                self.max_trials_per_participant,
            )
            return "exit"

        if self._should_finish_block(participant):
            next_block_position = participant.module_state.block_position + 1
            if next_block_position >= participant.module_state.n_blocks:
                return "exit"
            else:
                next_block = participant.module_state.block_order[next_block_position]
                self.set_block_state(participant, next_block)

        chain_query = self.network_class.query.filter_by(
            trial_maker_id=self.id, full=False, failed=False
        ).options(
            subqueryload(self.network_class.head),
        )

        if self.chain_type == "within":
            if self.sync_group_type is not None:
                sync_group = participant.active_sync_groups[self.sync_group_type]
                assert sync_group.id is not None
                chain_query = chain_query.filter_by(sync_group_id=sync_group.id)
            else:
                chain_query = self.filter_by_participant_id(chain_query, participant)
        elif (
            self.chain_type == "across"
            and not self.allow_revisiting_networks_in_across_chains
        ):
            chain_query = self.exclude_participated(chain_query, participant)

        participant_group = participant.module_state.participant_group
        chain_query = chain_query.filter_by(participant_group=participant_group)

        discovered_chains = chain_query.all()
        # Candidate records let the shared pipeline work with either chains or
        # static nodes while retaining the network objects loaded by the query.
        candidates = self._build_candidates(
            discovered_chains,
            participant=participant,
            experiment=experiment,
        )
        logger.info(
            "%i eligible %s remain after applying custom filters.",
            len(candidates),
            candidate_plural,
        )

        def has_pending_process(network):
            return network.async_post_grow_network_pending or (
                network.head and network.head.async_on_deploy_pending
            )

        available_candidates = [
            candidate
            for candidate in candidates
            if not has_pending_process(candidate.network)
        ]

        logger.info(
            "%i out of %i eligible %s await asynchronous processing.",
            len(candidates) - len(available_candidates),
            len(candidates),
            candidate_plural,
        )

        if (
            len(available_candidates) == 0
            and len(candidates) > 0
            and self.wait_for_networks
        ):
            logger.info("Will wait for an eligible %s.", self._candidate_label)
            return "wait"

        # Discovery normally runs in the response that submits the previous trial.
        # Counting all viable trials, rather than only finalized trials, includes
        # that newly submitted trial and prevents over-allocation.
        needs_viable_counts = (
            not self._node_capacity_is_unlimited or self.balance_across_chains
        )
        viable_counts = (
            _count_viable_trials_for_nodes(
                candidate.network.head.id
                for candidate in available_candidates
                if candidate.network.head is not None
            )
            if needs_viable_counts
            else {}
        )
        candidates_with_head_space = [
            candidate
            for candidate in available_candidates
            if candidate.network.head
            and (
                self._node_capacity_is_unlimited
                or viable_counts.get(candidate.network.head.id, 0)
                < self.trials_per_node
            )
        ]

        if len(available_candidates) > 0 and len(candidates_with_head_space) == 0:
            logger.info(
                "All eligible %s have exhausted their current trial capacity.",
                candidate_plural,
            )
            if self.wait_for_networks:
                return "wait"
            else:
                return "exit"

        candidates = candidates_with_head_space
        if len(candidates) == 0:
            return "exit"

        random.shuffle(candidates)

        if self.balance_across_chains:
            # We used to sort by n_completed_trials, but this is likely to be out of date
            # because the completion of the latest trial might not have been committed yet.
            candidates.sort(
                key=lambda candidate: viable_counts.get(
                    candidate.network.head.id,
                    0,
                )
            )
            candidates.sort(key=lambda candidate: candidate.network.head.degree)

        remaining_blocks = participant.module_state.remaining_blocks
        candidates = [
            candidate
            for candidate in candidates
            if candidate.network.block in remaining_blocks
        ]
        candidates.sort(
            key=lambda candidate: remaining_blocks.index(candidate.network.block)
        )

        return [candidate.value for candidate in candidates]

    def _build_candidates(self, discovered_chains, participant, experiment):
        """Build internal records for chain selection candidates."""

        chains = self._filter_eligible_candidates(
            discovered_chains,
            participant=participant,
            experiment=experiment,
        )
        return [Candidate(value=chain, network=chain) for chain in chains]

    def _select_trial_node(self, participant, experiment):
        selection = self._select_from_discovered(
            self.find_chains(participant, experiment),
            participant,
            experiment,
            self.select_chain,
            "select_chain",
        )
        if not isinstance(selection, Selection):
            return selection

        chain = selection.value
        if chain.head is None:
            raise RuntimeError(f"Selected chain {chain.id} has no head")

        self._advance_to_selected_block(chain.block, participant)
        return Selection(value=chain.head, context=selection.context)

    def select_chain(self, chains, participant, experiment):
        """Select from a nonempty list of eligible chains.

        Return a chain from ``chains`` or ``Selection(value, context)``.
        Returning ``None`` raises ``TypeError``. The returned chain must be
        one of the objects in ``chains``, not a re-queried copy.
        """
        return chains[0]

    def _advance_to_selected_block(self, chosen_block, participant):
        current_block = participant.module_state.block
        if chosen_block != current_block:
            logger.info(
                "Advanced from block %r to %r.",
                current_block,
                chosen_block,
            )
            self.set_block_state(participant, chosen_block)

    def prioritize_networks(self, networks, participant, experiment):
        """Removed selection hook.

        :meta private:
        """
        self._raise_unsupported_selection_hook("prioritize_networks")

    def set_block_state(self, participant, block):
        new_block_position = participant.module_state.block_order.index(block)
        if self.sync_group_type:
            group = participant.active_sync_groups[self.sync_group_type]
            for group_participant in group.participants:
                group_participant.module_state.set_block_position(new_block_position)
        else:
            participant.module_state.set_block_position(new_block_position)

    def _filter_eligible_candidates(self, chains, participant, experiment):
        """Apply chain eligibility before wait/exit checks."""
        return self._validate_selection_subset(
            self.custom_chain_filter(chains, participant, experiment),
            allowed_values=chains,
            method_name="custom_chain_filter",
        )

    def custom_chain_filter(self, chains, participant, experiment):
        """Filter eligible chains before selection.

        Override this to remove chains the participant must not receive.
        The default returns the original list, or applies a deprecated
        ``custom_network_filter`` override when that is the only filter present.
        Ranking among eligible chains belongs in ``select_chain``.
        """
        return self._apply_deprecated_network_filter(
            chains,
            participant,
            replacement_method="custom_chain_filter",
        )

    def custom_network_filter(self, candidates, participant):
        """Deprecated list-based eligibility hook.

        Chain trial makers should override
        :meth:`~psynet.trial.chain.ChainTrialMaker.custom_chain_filter` instead.
        Static trial makers should override
        :meth:`~psynet.trial.static.StaticTrialMaker.custom_node_filter`.
        This method still receives candidate networks as keyword arguments
        (``candidates`` and ``participant``) and must return a subset of those
        objects.
        """
        return candidates

    def find_nodes(self, participant, experiment):
        """Wrong-paradigm selection hook.

        :meta private:
        """
        self._raise_unsupported_selection_hook("find_nodes")

    def select_node(self, nodes, participant, experiment):
        """Wrong-paradigm selection hook.

        :meta private:
        """
        self._raise_unsupported_selection_hook("select_node")

    def custom_node_filter(self, nodes, participant, experiment):
        """Wrong-paradigm selection hook.

        :meta private:
        """
        self._raise_unsupported_selection_hook("custom_node_filter")

    @staticmethod
    def filter_by_participant_id(chains, participant):
        return chains.filter_by(participant_id=participant.id)

    def exclude_participated(self, chains, participant):
        return chains.filter(
            not_(
                self.network_class.id.in_(
                    participant.module_state.participated_networks
                )
            )
        )

    @staticmethod
    def _completed_trial_count_for_node(node_cls):
        trial_table = Trial.__table__
        return (
            select(func.count(trial_table.c.id))
            .select_from(trial_table)
            .where(
                trial_table.c.node_id == node_cls.id,
                trial_table.c.complete.is_(True),
                trial_table.c.finalized.is_(True),
                trial_table.c.failed.is_(False),
                trial_table.c.is_repeat_trial.is_(False),
            )
            .correlate_except(trial_table)
            .scalar_subquery()
        )

    @staticmethod
    def _has_pending_trials_for_node(node_cls):
        trial_table = Trial.__table__
        return (
            select(trial_table.c.id)
            .select_from(trial_table)
            .where(
                trial_table.c.node_id == node_cls.id,
                trial_table.c.failed.is_(False),
                trial_table.c.finalized.is_(False),
            )
            .correlate_except(trial_table)
            .exists()
        )

    def local_head_ready_condition(self, node_cls=None):
        """
        SQL expression for the standard chain readiness condition.

        This is the live replacement for the old ``ready_to_spawn`` cache:
        the head must be structurally able to spawn, have enough finalized
        non-repeat trials, and have no alive unfinished trials.
        """
        if node_cls is None:
            node_cls = self.node_class
        completed_count = self._completed_trial_count_for_node(node_cls)
        return and_(
            node_cls.can_spawn.is_(True),
            node_cls.target_n_trials.is_not(None),
            completed_count >= node_cls.target_n_trials,
            ~self._has_pending_trials_for_node(node_cls),
            node_cls.async_on_deploy_pending.is_(False),
        )

    def network_ready_to_grow_condition(self, network_cls=None, node_cls=None):
        if network_cls is None:
            network_cls = self.network_class
        if node_cls is None:
            node_cls = self.node_class
        return and_(
            network_cls.failed.is_(False),
            network_cls.full.is_(False),
            network_cls.async_post_grow_network_pending.is_(False),
            self.local_head_ready_condition(node_cls),
        )

    def ready_to_grow_network_id_select(
        self, network_ids: Optional[Iterable[int]] = None
    ):
        query = (
            select(self.network_class.id)
            .select_from(self.network_class)
            .join(self.node_class, self.network_class.head_id == self.node_class.id)
            .where(self.network_class.trial_maker_id == self.id)
            .where(self.network_ready_to_grow_condition())
        )
        if network_ids is not None:
            query = query.where(self.network_class.id.in_(list(network_ids)))
        return query

    def ready_to_grow_network_query(self, network_ids: Optional[Iterable[int]] = None):
        """
        Return a query for networks that are ready to grow.

        The scheduler uses the corresponding ID select as the authoritative
        growth check for both within- and across-chain networks.
        """
        return self.network_class.query.filter(
            self.network_class.id.in_(self.ready_to_grow_network_id_select(network_ids))
        ).populate_existing()

    def get_networks_ready_to_grow(self, network_ids: Optional[Iterable[int]] = None):
        # Lock only the network IDs first. Loading full polymorphic network
        # objects can introduce DISTINCT clauses, which PostgreSQL does not
        # allow with FOR UPDATE. ``skip_locked`` keeps the poller non-blocking.
        id_rows = db.session.execute(
            self.ready_to_grow_network_id_select(network_ids).with_for_update(
                of=self.network_class, skip_locked=True
            )
        ).all()
        network_ids = [row[0] for row in id_rows]
        if not network_ids:
            return []
        return (
            self.network_class.query.filter(self.network_class.id.in_(network_ids))
            .populate_existing()
            .all()
        )

    def network_is_ready_to_grow(self, network):
        head = network.head
        return (
            not network.failed
            and not network.full
            and not network.async_post_grow_network_pending
            and head is not None
            and head.can_spawn
            and not head.async_on_deploy_pending
            and head.reached_target_n_trials
            and len(head.pending_trials) == 0
        )

    def call_grow_network(self, network, check_readiness=True):
        from psynet.experiment import get_experiment

        experiment = get_experiment()
        grown = self.grow_network(network, experiment, check_readiness=check_readiness)
        assert isinstance(grown, bool)
        if grown:
            self._check_run_async_post_grow_network(network)

    @log_time_taken
    def grow_network(self, network, experiment, check_readiness=True):
        # We set participant = None because of Dallinger's constraint of not allowing participants
        # to create nodes after they have finished working.
        participant = None
        if not check_readiness or self.network_is_ready_to_grow(network):
            head = network.head

            if is_method_overridden(head, ChainNode, "make_next_definition"):
                # make_next_definition is a more recent interface for creating definitions,
                # we are going to trial this for a while, and potentially later
                # deprecate the former interface (create_seed)
                definition = head.make_next_definition(experiment, participant)
                seed = None
            else:
                # create_seed is the former interface for creating definitions
                definition = None
                seed = head.create_seed(experiment, participant)

            node = self.node_class(
                seed=seed,
                definition=definition,
                parent=head,
                network=network,
                experiment=experiment,
                propagate_failure=self.propagate_failure,
                participant=participant,
            )
            db.session.add(node)
            network.add_node(node)
            node.check_on_deploy()
            return True
        return False

    def finalize_trial(self, answer, trial, experiment, participant):
        super().finalize_trial(answer, trial, experiment, participant)
        participant.module_state.participated_networks.append(trial.network_id)
