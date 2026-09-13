# pylint: disable=unused-argument,abstract-method

from typing import Literal, Optional, Type

from dallinger import db
from sqlalchemy import Column, Index, Integer, String, UniqueConstraint, and_, select
from sqlalchemy.orm import aliased

from ..data import SQLBase, SQLMixin, register_table
from ..field import PythonObject
from .chain import ChainNetwork, ChainNode, ChainTrial, ChainTrialMaker
from .main import with_trial_maker_namespace


@register_table
class GraphChainVertex(SQLBase, SQLMixin):
    """
    Stores the static vertex metadata for a graph chain trial maker.

    Graph topology is normalized into vertices and edges so graph readiness can
    be queried efficiently in SQL instead of relying on serialized Python lists.
    """

    __tablename__ = "graph_chain_vertex"

    id = Column(Integer, primary_key=True, autoincrement=True)
    trial_maker_id = Column(String, index=True)
    vertex_id = Column(Integer, index=True)
    block = Column(String, index=True)
    participant_group = Column(String, index=True)

    __table_args__ = (
        UniqueConstraint(
            "trial_maker_id",
            "vertex_id",
            name="unique_graph_chain_vertex",
        ),
    )


@register_table
class GraphChainEdge(SQLBase, SQLMixin):
    """
    Stores directed dependencies between graph-chain vertices.

    A target vertex can grow at a given degree only once each origin vertex for
    its incoming edges has a ready head node at the same degree.
    """

    __tablename__ = "graph_chain_edge"

    id = Column(Integer, primary_key=True, autoincrement=True)
    trial_maker_id = Column(String, index=True)
    origin_vertex_id = Column(Integer, index=True)
    target_vertex_id = Column(Integer, index=True)

    __table_args__ = (
        UniqueConstraint(
            "trial_maker_id",
            "origin_vertex_id",
            "target_vertex_id",
            name="unique_graph_chain_edge",
        ),
        Index(
            "ix_graph_chain_edge_trial_target_origin",
            "trial_maker_id",
            "target_vertex_id",
            "origin_vertex_id",
        ),
    )


class GraphChainNetwork(ChainNetwork):
    """
    A Network class for graph chains. A graph chain corresponds to the evolution of
    a vertex within a graph.

    Parameters (for now stating the new ones)
    -----------------------------------------

    vertex_id
        The id of the vertex that the network is representing within the graph.

    source_seed
        Source seed to use when initializing the graph in the trialmaker.

    """

    vertex_id = Column(Integer)
    source_seed = Column(PythonObject)

    def __init__(
        self,
        trial_maker_id: str,
        experiment,
        start_node: "GraphChainNode",
        chain_type: str,
        trials_per_node: int,
        target_n_nodes: int,
        participant=None,
        id_within_participant: Optional[int] = None,
    ):
        self.vertex_id = start_node.vertex_id
        self.source_seed = start_node.seed

        super().__init__(
            trial_maker_id=trial_maker_id,
            start_node=start_node,
            experiment=experiment,
            chain_type=chain_type,
            trials_per_node=trials_per_node,
            target_n_nodes=target_n_nodes,
            participant=participant,
            id_within_participant=id_within_participant,
        )

    @property
    def incoming_vertex_ids(self):
        return [
            edge.origin_vertex_id
            for edge in GraphChainEdge.query.filter_by(
                trial_maker_id=self.trial_maker_id,
                target_vertex_id=self.vertex_id,
            )
            .order_by(GraphChainEdge.origin_vertex_id)
            .all()
        ]

    @property
    def outgoing_vertex_ids(self):
        return [
            edge.target_vertex_id
            for edge in GraphChainEdge.query.filter_by(
                trial_maker_id=self.trial_maker_id,
                origin_vertex_id=self.vertex_id,
            )
            .order_by(GraphChainEdge.target_vertex_id)
            .all()
        ]


Index(
    "ix_graph_chain_network_trial_maker_vertex",
    GraphChainNetwork.trial_maker_id,
    GraphChainNetwork.vertex_id,
)


class GraphChainTrial(ChainTrial):
    """
    A Trial class for graph chains.
    """

    def make_definition(self, experiment, participant):
        """
        (Built-in)
        In a graph chain, the trial's definition equals the definition of
        the node that created it.

        Parameters
        ----------

        experiment
            An instantiation of :class:`psynet.experiment.Experiment`,
            corresponding to the current experiment.

        participant
            Optional participant with which to associate the trial.

        Returns
        -------

        object
            The trial's definition, equal to the node's definition.
        """
        return self.node.definition

    def on_finalized(self):
        super().on_finalized()
        # Graph chains have cross-network dependencies, so a finalized trial can
        # make outgoing graph vertices growable. Keep this request-path fast by
        # checking only targets that depend on this finalized node's vertex and
        # degree; the scheduled poller remains the correctness backstop.
        if not self.trial_maker:
            return
        db.session.flush()
        network_ids = self.trial_maker.get_candidate_network_ids_after_finalized_node(
            self.node
        )
        for network in self.trial_maker.get_networks_ready_to_grow(network_ids):
            self.trial_maker.call_grow_network(network, check_readiness=False)


class GraphChainNode(ChainNode):
    """
    A Node class for graph chains.

    Parameters (for now stating the new ones)
    -----------------------------------------

    vertex_id
        The id of the vertex that the network is representing within the graph.

    """

    def __init__(
        self,
        seed,
        degree: int,
        network,
        experiment,
        propagate_failure: bool,
        vertex_id: int,
        incoming_vertex_ids=None,
        outgoing_vertex_ids=None,
        participant=None,
        participant_group=None,
        block=None,
    ):
        # pylint: disable=unused-argument
        self.vertex_id = vertex_id
        super().__init__(
            seed=seed,
            degree=degree,
            network=network,
            experiment=experiment,
            propagate_failure=propagate_failure,
            participant=participant,
            participant_group=participant_group,
            block=block,
        )

    @staticmethod
    def generate_class_seed(vertex=None):
        raise NotImplementedError

    def create_definition_from_seed(self, seed, experiment, participant):
        """
        (Built-in)
        In a graph chain, the next node in the chain
        is a faithful reproduction of the previous iteration.

        Parameters
        ----------

        seed
            The seed being passed to the node.

        experiment
            An instantiation of :class:`psynet.experiment.Experiment`,
            corresponding to the current experiment.

        participant
            Current participant, if relevant.

        Returns
        -------

        object
            The node's new definition, which is a faithful reproduction of the seed
            that it was passed.
        """
        # The next node in the chain is a faithful reproduction of the previous iteration.
        return seed

    def summarize_trials(self, trials: list, experiment, participant):
        """
        (Abstract method, to be overridden)
        This method should summarize the answers to the provided trials.
        A default method is implemented for cases when there is
        just one trial per node; in this case, the method
        extracts and returns the trial's answer, available in ``trial.answer``.
        The method must be extended if it is to cope with multiple trials per node,
        however.

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

        if len(trials) == 1:
            return trials[0].answer
        raise NotImplementedError

    vertex_id = Column(Integer)

    @property
    def incoming_vertex_ids(self):
        if self.network is None:
            raise AttributeError(
                "GraphChainNode.incoming_vertex_ids is now derived from "
                "GraphChainEdge rows and is only available once the node has "
                "been assigned to a network."
            )
        return self.network.incoming_vertex_ids

    @property
    def outgoing_vertex_ids(self):
        if self.network is None:
            raise AttributeError(
                "GraphChainNode.outgoing_vertex_ids is now derived from "
                "GraphChainEdge rows and is only available once the node has "
                "been assigned to a network."
            )
        return self.network.outgoing_vertex_ids

    def get_incoming_nodes(self):
        return (
            db.session.query(GraphChainNode)
            .join(GraphChainNetwork, GraphChainNode.network_id == GraphChainNetwork.id)
            .join(
                GraphChainEdge,
                and_(
                    GraphChainEdge.trial_maker_id == GraphChainNetwork.trial_maker_id,
                    GraphChainEdge.origin_vertex_id == GraphChainNetwork.vertex_id,
                ),
            )
            .filter(
                GraphChainEdge.trial_maker_id == self.network.trial_maker_id,
                GraphChainEdge.target_vertex_id == self.network.vertex_id,
                GraphChainNode.degree == self.degree,
                GraphChainNode.failed.is_(False),
            )
            .all()
        )


Index(
    "ix_graph_chain_node_network_degree",
    GraphChainNode.network_id,
    GraphChainNode.degree,
)


class GraphChainTrialMaker(ChainTrialMaker):
    """
    A TrialMaker class for graph chains;
    see the documentation for
    :class:`~psynet.trial.chain.ChainTrialMaker`
    for usage instructions.

    Parameters
    ----------

    network_structure
        A representation of the graph structure to instantiate.
        The representation consistes of a dictionary of vertices and edges.
        E.g. {"vertices": [1,2], "edges": [{"origin": 1, "target": 2, "properties": {"type": "default"}}]}

        The "blocks" and "participant_groups" keys are optional and can be used to specify the blocks and participant groups for each vertex.
        E.g. {"vertices": [1,2], "edges": [{"origin": 1, "target": 2}], "blocks": {1: "block1", 2: "block2"], "participant_groups": {1: "group1", 2: "group2"}}
    """

    def __init__(
        self,
        *,
        id_,
        node_class: Type[GraphChainNode],
        trial_class: Type[GraphChainTrial],
        network_structure,
        chain_type: str,
        expected_trials_per_participant: int | str,
        max_trials_per_participant: Optional[int | str],
        chains_per_participant: Optional[int],
        # chains_per_experiment: Optional[int],
        trials_per_node: int,
        balance_across_chains: bool,
        check_performance_at_end: bool,
        check_performance_every_trial: bool,
        recruit_mode: str,
        target_n_participants=Optional[int],
        max_nodes_per_chain: Optional[int] = None,
        max_trials_per_block: Optional[int] = None,
        fail_trials_on_premature_exit: bool = False,
        fail_trials_on_participant_performance_check: bool = False,
        propagate_failure: bool = True,
        n_repeat_trials: int = 0,
        wait_for_networks: bool = False,
        allow_revisiting_networks_in_across_chains: bool = False,
        choose_participant_group: Optional[callable] = None,
        sync_group_type: Optional[str] = None,
        sync_group_max_wait_time: float = 45.0,
        sync_group_max_wait_action: Literal["fail", "kick"] = "fail",
        sync_group_timeout_between_barriers_time: Optional[float] = None,
        sync_group_timeout_between_barriers_action: Literal["kick", "fail"] = "fail",
    ):
        if chain_type == "within":
            raise NotImplementedError  # UNCLEAR TO ME HOW TO UNITE THE ON-DEMAND CREATION OF WITHIN CHAINS AND THE PRE-DFINED GRAPH NETWORK STRUCTURE
        chains_per_experiment = len(network_structure["vertices"])
        self.network_structure = network_structure
        super().__init__(
            id_=id_,
            node_class=node_class,
            trial_class=trial_class,
            chain_type=chain_type,
            expected_trials_per_participant=expected_trials_per_participant,
            max_trials_per_participant=max_trials_per_participant,
            chains_per_participant=chains_per_participant,
            chains_per_experiment=chains_per_experiment,
            trials_per_node=trials_per_node,
            balance_across_chains=balance_across_chains,
            check_performance_at_end=check_performance_at_end,
            check_performance_every_trial=check_performance_every_trial,
            recruit_mode=recruit_mode,
            target_n_participants=target_n_participants,
            max_nodes_per_chain=max_nodes_per_chain,
            max_trials_per_block=max_trials_per_block,
            fail_trials_on_premature_exit=fail_trials_on_premature_exit,
            fail_trials_on_participant_performance_check=fail_trials_on_participant_performance_check,
            propagate_failure=propagate_failure,
            n_repeat_trials=n_repeat_trials,
            wait_for_networks=wait_for_networks,
            allow_revisiting_networks_in_across_chains=allow_revisiting_networks_in_across_chains,
            choose_participant_group=choose_participant_group,
            sync_group_type=sync_group_type,
            sync_group_max_wait_time=sync_group_max_wait_time,
            sync_group_max_wait_action=sync_group_max_wait_action,
            sync_group_timeout_between_barriers_time=sync_group_timeout_between_barriers_time,
            sync_group_timeout_between_barriers_action=sync_group_timeout_between_barriers_action,
        )

    @property
    def default_network_class(self):
        return GraphChainNetwork

    def pre_deploy_routine(self, experiment):
        if self.chain_type == "across":
            experiment.var.set(
                with_trial_maker_namespace(self.id, "network_structure"),
                self.network_structure,
            )
        super().pre_deploy_routine(experiment)

    def create_networks_across(self, experiment):
        network_structure = self.network_structure
        vertices = network_structure["vertices"]
        blocks = network_structure.get("blocks", dict())
        groups = network_structure.get("participant_groups", dict())

        self.create_graph_topology(network_structure, blocks, groups)

        source_seeds = self.generate_source_seed_bundles()
        for i in range(self.chains_per_experiment):
            vertex_id = vertices[i]
            source_seed = [
                seed["bundle"]
                for seed in source_seeds
                if seed["vertex_id"] == vertex_id
            ][0]
            start_node = self.node_class(
                seed=source_seed,
                degree=0,
                network=None,
                experiment=experiment,
                propagate_failure=self.propagate_failure,
                vertex_id=vertex_id,
                participant=None,
                block=blocks.get(vertex_id, None),
                participant_group=groups.get(vertex_id, None),
            )
            self.create_graph_network(experiment, start_node)

    def create_graph_network(
        self,
        experiment,
        start_node,
        participant=None,
        id_within_participant=None,
    ):
        network = self.network_class(
            trial_maker_id=self.id,
            start_node=start_node,
            experiment=experiment,
            chain_type=self.chain_type,
            trials_per_node=self.trials_per_node,
            target_n_nodes=self.max_nodes_per_chain,
            participant=participant,
            id_within_participant=id_within_participant,
        )
        db.session.add(network)
        db.session.commit()
        return network

    def create_graph_topology(self, network_structure, blocks, groups):
        if GraphChainVertex.query.filter_by(trial_maker_id=self.id).count() > 0:
            return

        for vertex_id in network_structure["vertices"]:
            db.session.add(
                GraphChainVertex(
                    trial_maker_id=self.id,
                    vertex_id=vertex_id,
                    block=blocks.get(vertex_id, None),
                    participant_group=groups.get(vertex_id, None),
                )
            )

        for edge in network_structure["edges"]:
            db.session.add(
                GraphChainEdge(
                    trial_maker_id=self.id,
                    origin_vertex_id=edge["origin"],
                    target_vertex_id=edge["target"],
                )
            )

    def get_incoming_vertex_ids(self, target, network_structure):
        edges = network_structure["edges"]
        incoming_vertex_ids = [e["origin"] for e in edges if e["target"] == target]
        return incoming_vertex_ids

    def get_outgoing_vertex_ids(self, source, network_structure):
        edges = network_structure["edges"]
        outgoing_vertex_ids = [e["target"] for e in edges if e["origin"] == source]
        return outgoing_vertex_ids

    def get_candidate_network_ids_after_finalized_node(self, finalized_node):
        """
        Return graph networks that can be newly unlocked by a finalized node.

        A graph node at vertex ``u`` and degree ``d`` can only affect target
        networks ``v`` with an edge ``u -> v`` whose current head is also at
        degree ``d``. The full readiness predicate is applied by the caller.
        """
        network = finalized_node.network
        if network is None:
            return []

        rows = db.session.execute(
            select(self.network_class.id)
            .select_from(GraphChainEdge)
            .join(
                self.network_class,
                and_(
                    self.network_class.trial_maker_id == GraphChainEdge.trial_maker_id,
                    self.network_class.vertex_id == GraphChainEdge.target_vertex_id,
                ),
            )
            .join(self.node_class, self.network_class.head_id == self.node_class.id)
            .where(
                GraphChainEdge.trial_maker_id == self.id,
                GraphChainEdge.origin_vertex_id == network.vertex_id,
                self.node_class.degree == finalized_node.degree,
            )
        ).all()
        return [row[0] for row in rows]

    def grow_network(self, network, experiment, check_readiness=True):
        # We set participant = None because of Dallinger's constraint of not allowing participants
        # to create nodes after they have finished working.
        participant = None
        head = network.head
        if not check_readiness or self.network_is_ready_to_grow(network):
            seed_bundle = self.create_seed_bundle(head, experiment, participant)
            node = self.node_class(
                seed_bundle,
                head.degree + 1,
                network,
                experiment,
                self.propagate_failure,
                network.vertex_id,
                participant=participant,
                block=network.block,
                participant_group=network.participant_group,
            )
            db.session.add(node)
            network.add_node(node)
            db.session.commit()
            node.check_on_deploy()
            db.session.commit()
            return True
        return False

    def create_seed_bundle(self, head, experiment, participant):
        head_seed = head.create_seed(experiment, participant)
        incoming_nodes = head.get_incoming_nodes()
        bundle = [
            {
                "vertex_id": head.network.vertex_id,
                "content": head_seed,
                "is_center": True,
            }
        ] + [
            {
                "vertex_id": p.network.vertex_id,
                "content": p.create_seed(
                    experiment, participant
                ),  # might require some thought if participant becomes relevant
                "is_center": False,
            }
            for p in incoming_nodes
        ]
        return bundle

    def network_ready_to_grow_condition(self, network_cls=None, node_cls=None):
        if network_cls is None:
            network_cls = self.network_class
        if node_cls is None:
            node_cls = self.node_class

        incoming_network = aliased(self.network_class)
        incoming_head = aliased(self.node_class)

        missing_ready_incoming = (
            select(GraphChainEdge.id)
            .outerjoin(
                incoming_network,
                and_(
                    incoming_network.trial_maker_id == GraphChainEdge.trial_maker_id,
                    incoming_network.vertex_id == GraphChainEdge.origin_vertex_id,
                    incoming_network.failed.is_(False),
                ),
            )
            .outerjoin(
                incoming_head,
                and_(
                    incoming_head.network_id == incoming_network.id,
                    incoming_head.degree == node_cls.degree,
                    incoming_head.failed.is_(False),
                    self.local_head_ready_condition(incoming_head),
                ),
            )
            .where(
                GraphChainEdge.trial_maker_id == network_cls.trial_maker_id,
                GraphChainEdge.target_vertex_id == network_cls.vertex_id,
                incoming_head.id.is_(None),
            )
            .correlate(network_cls, node_cls)
            .exists()
        )

        return and_(
            super().network_ready_to_grow_condition(network_cls, node_cls),
            ~missing_ready_incoming,
        )

    def network_is_ready_to_grow(self, network):
        if not super().network_is_ready_to_grow(network):
            return False

        incoming_nodes = network.head.get_incoming_nodes()
        return len(incoming_nodes) == len(network.incoming_vertex_ids) and all(
            node.reached_target_n_trials and len(node.pending_trials) == 0
            for node in incoming_nodes
        )

    def generate_source_seed_bundles(self):
        network_structure = self.network_structure
        vertices = network_structure["vertices"]
        centers = [
            {
                "vertex_id": v,
                "content": self.node_class.generate_class_seed(v),
                "is_center": True,
            }
            for v in vertices
        ]
        bundles = []
        for i in range(len(centers)):
            center = centers[i]
            incoming_vertex_ids = self.get_incoming_vertex_ids(
                center["vertex_id"], network_structure
            )
            bundle = [center]
            for j in incoming_vertex_ids:
                content = [c["content"] for c in centers if c["vertex_id"] == j]
                bundle = bundle + [
                    {"vertex_id": j, "content": content[0], "is_center": False}
                ]
            bundles = bundles + [{"vertex_id": center["vertex_id"], "bundle": bundle}]
        return bundles
