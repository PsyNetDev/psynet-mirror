import uuid

import pytest
from dallinger import db
from dallinger.models import Node
from sqlalchemy import inspect, select
from sqlalchemy.exc import OperationalError

from psynet.experiment import get_experiment
from psynet.participant import Participant
from psynet.pytest_psynet import path_to_test_experiment
from psynet.sqlalchemy_profiling import assert_query_count
from psynet.trial.chain import ChainNetwork, ChainNode, ChainTrial, ChainTrialMaker
from psynet.trial.create_and_rate import (
    CreateAndRateAssignmentPending,
    CreateAndRateTrialMakerMixin,
)
from psynet.trial.graph import (
    GraphChainEdge,
    GraphChainNetwork,
    GraphChainNode,
    GraphChainTrial,
    GraphChainTrialMaker,
    GraphChainVertex,
)
from psynet.trial.static import StaticNetwork, StaticNode, StaticTrial, StaticTrialMaker


class GrowthQueryTrial(ChainTrial):
    time_estimate = 1

    def make_definition(self, experiment, participant):
        return self.node.definition


class GrowthQueryStaticTrial(StaticTrial):
    time_estimate = 1


class GrowthQueryNode(ChainNode):
    def create_initial_seed(self, experiment, participant):
        return {"x": 0}

    def summarize_trials(self, trials, experiment, participant):
        return {"x": trials[0].answer}

    def create_definition_from_seed(self, seed, experiment, participant):
        return seed


class GrowthQueryGraphTrial(GraphChainTrial):
    time_estimate = 1


class GrowthQueryGraphNode(GraphChainNode):
    @staticmethod
    def generate_class_seed(vertex=None):
        return [{"vertex_id": vertex, "content": vertex, "is_center": True}]


class GrowthQueryGraphTrialMaker(GraphChainTrialMaker):
    pass


@pytest.fixture
def participant(db_session):
    return new_participant()


def new_participant():
    exp = get_experiment()
    participant = Participant(
        experiment=exp,
        recruiter_id="hotair",
        worker_id=str(uuid.uuid4()),
        hit_id=str(uuid.uuid4()),
        assignment_id=str(uuid.uuid4()),
        mode="debug",
    )
    db.session.add(participant)
    db.session.flush()
    return participant


def chain_trial_maker(maker_class=ChainTrialMaker, **kwargs):
    args = dict(
        id_="growth_query",
        node_class=GrowthQueryNode,
        trial_class=GrowthQueryTrial,
        chain_type="across",
        expected_trials_per_participant=1,
        max_trials_per_participant=1,
        chains_per_experiment=1,
        max_nodes_per_chain=2,
        trials_per_node=1,
        recruit_mode="n_trials",
    )
    return maker_class(**{**args, **kwargs})


def create_chain_network(
    trial_maker, experiment, *, network_class=ChainNetwork, participant=None
):
    start_node = trial_maker.node_class(definition={"x": 0})
    network = network_class(
        trial_maker_id=trial_maker.id,
        start_node=start_node,
        experiment=experiment,
        chain_type=trial_maker.chain_type,
        trials_per_node=trial_maker.trials_per_node,
        target_n_nodes=trial_maker.max_nodes_per_chain,
        participant=participant,
    )
    db.session.add(network)
    db.session.flush()
    return network


def static_trial_maker(
    *, target_trials_per_node, maker_class=StaticTrialMaker, **kwargs
):
    args = dict(
        id_="static_growth_query",
        trial_class=GrowthQueryStaticTrial,
        nodes=[StaticNode(definition={"x": 0})],
        expected_trials_per_participant=1,
        max_trials_per_participant=1,
        target_trials_per_node=target_trials_per_node,
        node_order="random",
    )
    return maker_class(**{**args, **kwargs})


def initialize_trial_maker_state(trial_maker, participant):
    state = trial_maker.state_class(trial_maker, participant)
    state.participant_group = "default"
    state.participated_networks = []
    state.block_order = ["default"]
    state.set_block_position(0)
    participant.module_state = state
    db.session.add(state)
    db.session.flush()


def add_trial(
    trial_class,
    node,
    participant,
    *,
    answer=1,
    finalized=True,
    failed=False,
    propagate_failure=False,
):
    trial = trial_class(
        experiment=get_experiment(),
        node=node,
        participant=participant,
        propagate_failure=propagate_failure,
        is_repeat_trial=False,
    )
    trial.answer = answer
    trial.complete = finalized
    trial.finalized = finalized
    trial.failed = failed
    db.session.add(trial)
    db.session.flush()
    return trial


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
)
@pytest.mark.usefixtures("in_experiment_directory")
def test_find_chains_is_one_query_that_skips_full_chains(db_session, participant):
    exp = get_experiment()
    trial_maker = chain_trial_maker(
        chains_per_experiment=20,
        max_trials_per_participant=None,
    )
    networks = [create_chain_network(trial_maker, exp) for _ in range(20)]
    initialize_trial_maker_state(trial_maker, participant)
    add_trial(GrowthQueryTrial, networks[0].head, participant)

    with assert_query_count(max_queries=1):
        eligible = trial_maker.find_chains(participant, exp)

    assert {chain.id for chain in eligible} == {chain.id for chain in networks[1:]}


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
)
@pytest.mark.usefixtures("in_experiment_directory")
def test_find_nodes_is_one_query_that_skips_full_nodes(db_session, participant):
    exp = get_experiment()
    trial_maker = static_trial_maker(
        target_trials_per_node=1, max_trials_per_participant=None
    )
    networks = [
        create_chain_network(trial_maker, exp, network_class=StaticNetwork)
        for _ in range(20)
    ]
    initialize_trial_maker_state(trial_maker, participant)
    add_trial(GrowthQueryStaticTrial, networks[0].head, participant)

    with assert_query_count(max_queries=1):
        eligible = trial_maker.find_nodes(participant, exp)

    assert {node.id for node in eligible} == {
        network.head.id for network in networks[1:]
    }


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
)
@pytest.mark.usefixtures("in_experiment_directory")
def test_custom_finish_policy_ends_the_block(db_session, participant):
    class OneTrialPerBlock(StaticTrialMaker):
        def should_finish_block(self, participant, block):
            return participant.module_state.n_participant_trials_in_block >= 1

    exp = get_experiment()
    trial_maker = static_trial_maker(
        target_trials_per_node=None,
        max_trials_per_participant=None,
        maker_class=OneTrialPerBlock,
    )
    blocks = ["A", "A", "B"]
    networks = [
        create_chain_network(trial_maker, exp, network_class=StaticNetwork)
        for _ in blocks
    ]
    for network, block in zip(networks, blocks):
        network.block = network.head.block = block
    initialize_trial_maker_state(trial_maker, participant)
    participant.module_state.block_order = ["A", "B"]
    participant.module_state.set_block_position(0)
    db.session.flush()

    first, _ = trial_maker.prepare_trial(exp, participant)
    second = trial_maker._select_trial_node(participant, exp)

    assert first.node.block == "A"
    assert participant.module_state.block == "B"
    assert second.value.block == "B"


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
)
@pytest.mark.usefixtures("in_experiment_directory")
def test_unlimited_static_nodes_skip_viable_trial_counts(
    db_session, participant, monkeypatch
):
    import psynet.trial.chain as chain_module

    exp = get_experiment()
    trial_maker = static_trial_maker(target_trials_per_node=None)
    networks = [
        create_chain_network(trial_maker, exp, network_class=StaticNetwork)
        for _ in range(20)
    ]
    initialize_trial_maker_state(trial_maker, participant)
    monkeypatch.setattr(
        chain_module,
        "_count_viable_trials_for_nodes",
        lambda node_ids: pytest.fail("Unlimited nodes should not query trial counts."),
    )
    participant_id = participant.id
    expected_node_ids = {network.head.id for network in networks}
    db.session.commit()
    db.session.remove()
    participant = db.session.get(Participant, participant_id)
    participant.module_state

    with assert_query_count(min_queries=2, max_queries=5):
        eligible = trial_maker.find_nodes(participant, exp)

    assert {node.id for node in eligible} == expected_node_ids
    assert "n_viable_trials" not in inspect(StaticNode).attrs
    assert StaticNode.query.filter(StaticNode.n_viable_trials == 0).count() == len(
        expected_node_ids
    )


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
)
@pytest.mark.usefixtures("in_experiment_directory")
def test_node_filled_after_selection_is_not_overfilled(db_session, participant):
    class RacedStaticTrialMaker(StaticTrialMaker):
        def select_node(self, nodes, participant, experiment):
            node = nodes[-1]
            if not raced:
                raced.append(node)
                add_trial(GrowthQueryStaticTrial, node, other_participant)
            return node

    exp = get_experiment()
    raced = []
    other_participant = new_participant()
    trial_maker = static_trial_maker(
        target_trials_per_node=1, maker_class=RacedStaticTrialMaker
    )
    for _ in range(2):
        create_chain_network(trial_maker, exp, network_class=StaticNetwork)
    initialize_trial_maker_state(trial_maker, participant)

    trial, status = trial_maker.prepare_trial(exp, participant)

    assert status == "available"
    assert trial.node is not raced[0]


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
)
@pytest.mark.usefixtures("in_experiment_directory")
def test_headless_chain_raises_instead_of_being_skipped(db_session, participant):
    exp = get_experiment()
    trial_maker = chain_trial_maker()
    network = create_chain_network(trial_maker, exp)
    initialize_trial_maker_state(trial_maker, participant)
    network.head = None
    db.session.flush()

    with pytest.raises(RuntimeError, match="has no head"):
        trial_maker._select_trial_node(participant, exp)


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
)
@pytest.mark.usefixtures("in_experiment_directory")
def test_only_successful_capacity_claims_keep_their_node_lock(db_session, participant):
    exp = get_experiment()
    trial_maker = static_trial_maker(target_trials_per_node=1)
    full, free = [
        create_chain_network(trial_maker, exp, network_class=StaticNetwork).head
        for _ in range(2)
    ]
    add_trial(GrowthQueryStaticTrial, full, participant)
    db.session.commit()

    def locked_elsewhere(node):
        with db.engine.connect() as other, other.begin():
            try:
                other.execute(
                    select(Node.id)
                    .where(Node.id == node.id)
                    .with_for_update(key_share=True, nowait=True)
                )
            except OperationalError:
                return True
        return False

    assert not trial_maker._claim_node_capacity(full)
    assert not locked_elsewhere(full)
    assert trial_maker._claim_node_capacity(free)
    assert locked_elsewhere(free)


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
)
@pytest.mark.usefixtures("in_experiment_directory")
def test_create_and_rate_phase_queries_are_bounded(db_session, participant):
    exp = get_experiment()
    trial_maker = chain_trial_maker()
    networks = [create_chain_network(trial_maker, exp) for _ in range(20)]
    add_trial(GrowthQueryTrial, networks[0].head, participant, finalized=True)
    add_trial(GrowthQueryTrial, networks[0].head, participant, finalized=False)
    add_trial(GrowthQueryTrial, networks[1].head, participant, finalized=True)
    add_trial(GrowthQueryTrial, networks[1].head, participant, finalized=True)

    create_and_rate = object.__new__(CreateAndRateTrialMakerMixin)
    create_and_rate.creator_class = GrowthQueryTrial
    create_and_rate.rater_class = object()
    create_and_rate.n_creators = 2
    create_and_rate.wait_for_networks = False

    with assert_query_count(min_queries=2, max_queries=2):
        phases = create_and_rate.get_creation_phases(
            [network.head for network in networks]
        )

    assert phases[networks[0].head.id] == create_and_rate.WAITING_FOR_CREATORS
    assert phases[networks[1].head.id] == create_and_rate.READY_FOR_RATERS
    assert phases[networks[2].head.id] == create_and_rate.NEEDS_CREATORS

    with pytest.raises(CreateAndRateAssignmentPending, match="exit"):
        create_and_rate.get_trial_class(networks[0].head, participant, exp)
    assert (
        create_and_rate.get_trial_class(networks[1].head, participant, exp)
        is create_and_rate.rater_class
    )
    assert (
        create_and_rate.get_trial_class(networks[2].head, participant, exp)
        is create_and_rate.creator_class
    )


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
)
@pytest.mark.usefixtures("in_experiment_directory")
def test_performance_check_filters_trials_by_maker_in_sql(db_session, participant):
    exp = get_experiment()
    selected_maker = chain_trial_maker(id_="selected_performance")
    other_maker = chain_trial_maker(id_="other_performance")
    selected_network = create_chain_network(selected_maker, exp)
    other_network = create_chain_network(other_maker, exp)
    selected_trials = [
        add_trial(GrowthQueryTrial, selected_network.head, participant)
        for _ in range(2)
    ]
    for _ in range(20):
        add_trial(GrowthQueryTrial, other_network.head, participant)

    with assert_query_count(min_queries=1, max_queries=1) as profiler:
        trials = selected_maker.get_participant_trials(participant)

    # The other trial maker's rows must be excluded by the database rather than
    # hydrated and discarded, and the result must keep a deterministic order.
    assert trials == selected_trials
    statement = profiler.get_stats(top_n=None)[0].statement.lower()
    where_clause = statement.partition(" where ")[2].partition(" order by ")[0]
    assert "participant_id" in where_clause
    assert "trial_maker_id" in where_clause
    assert "order by" in statement


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
)
@pytest.mark.usefixtures("in_experiment_directory")
def test_ready_to_grow_query_uses_live_trial_state(db_session, participant):
    exp = get_experiment()
    trial_maker = chain_trial_maker()
    ready_network = create_chain_network(trial_maker, exp)
    pending_network = create_chain_network(trial_maker, exp)

    add_trial(GrowthQueryTrial, ready_network.head, participant, finalized=True)
    add_trial(GrowthQueryTrial, pending_network.head, participant, finalized=False)
    db.session.commit()

    ready_ids = {n.id for n in trial_maker.get_networks_ready_to_grow()}

    assert ready_network.id in ready_ids
    assert pending_network.id not in ready_ids


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
)
@pytest.mark.usefixtures("in_experiment_directory")
def test_can_spawn_excludes_static_networks_from_growth(db_session, participant):
    exp = get_experiment()
    trial_maker = chain_trial_maker()
    network = create_chain_network(trial_maker, exp, network_class=StaticNetwork)
    add_trial(GrowthQueryTrial, network.head, participant, finalized=True)
    db.session.commit()

    assert network.head.can_spawn is False
    assert trial_maker.get_networks_ready_to_grow() == []


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
)
@pytest.mark.usefixtures("in_experiment_directory")
def test_grow_network_uses_live_readiness_not_cached_flag(db_session, participant):
    exp = get_experiment()
    trial_maker = chain_trial_maker()
    network = create_chain_network(trial_maker, exp)
    add_trial(GrowthQueryTrial, network.head, participant, answer={"x": 1})
    db.session.commit()

    assert trial_maker.grow_network(network, exp) is True
    assert network.head.degree == 1


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
)
@pytest.mark.usefixtures("in_experiment_directory")
def test_ready_to_spawn_access_has_migration_error(db_session):
    exp = get_experiment()
    trial_maker = chain_trial_maker()
    network = create_chain_network(trial_maker, exp)

    with pytest.raises(AttributeError, match="ready_to_spawn has been removed"):
        network.ready_to_spawn

    with pytest.raises(AttributeError, match="check_ready_to_spawn"):
        network.head.check_ready_to_spawn()


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
)
@pytest.mark.usefixtures("in_experiment_directory")
def test_assignment_returned_does_not_fail_within_chain_start_node(
    db_session, participant
):
    exp = get_experiment()
    within_maker = chain_trial_maker(
        id_="within_growth",
        chain_type="within",
        chains_per_participant=1,
        chains_per_experiment=None,
        recruit_mode="n_participants",
        target_n_participants=1,
    )
    network = within_maker.create_network(
        exp, participant=participant, id_within_participant=0
    )
    start_node = network.head
    assert start_node.degree == 0
    assert start_node.participant_id == participant.id

    completed = add_trial(GrowthQueryTrial, start_node, participant, finalized=True)
    incomplete = add_trial(GrowthQueryTrial, start_node, participant, finalized=False)
    db.session.commit()

    exp.assignment_returned(participant)
    db.session.commit()

    assert participant.failed
    assert "assignment_returned" in participant.failure_tags
    assert "premature_exit" in participant.failure_tags
    assert not network.failed
    assert not start_node.failed
    assert not completed.failed
    assert incomplete.failed


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
)
@pytest.mark.usefixtures("in_experiment_directory")
def test_incomplete_trial_does_not_fail_child_node(db_session, participant):
    exp = get_experiment()
    trial_maker = chain_trial_maker()
    network = create_chain_network(trial_maker, exp)
    parent = network.head
    add_trial(GrowthQueryTrial, parent, participant, finalized=True)
    db.session.commit()

    assert trial_maker.grow_network(network, exp) is True
    child = network.head
    assert child.id != parent.id

    incomplete = add_trial(
        GrowthQueryTrial,
        parent,
        participant,
        finalized=False,
        propagate_failure=True,
    )
    incomplete.fail(reason="premature_exit")
    db.session.commit()

    assert incomplete.failed
    assert not incomplete.finalized
    assert not parent.failed
    assert not child.failed
    assert not network.failed


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
)
@pytest.mark.usefixtures("in_experiment_directory")
def test_finalized_trial_fails_child_node(db_session, participant):
    exp = get_experiment()
    trial_maker = chain_trial_maker()
    network = create_chain_network(trial_maker, exp)
    parent = network.head
    finalized = add_trial(
        GrowthQueryTrial,
        parent,
        participant,
        finalized=True,
        propagate_failure=True,
    )
    db.session.commit()

    assert trial_maker.grow_network(network, exp) is True
    child = network.head
    assert child.id != parent.id

    finalized.fail(reason="performance_check")
    db.session.commit()

    assert finalized.failed
    assert child.failed
    assert not parent.failed
    assert not network.failed


def graph_trial_maker():
    return make_graph_trial_maker(
        {
            "vertices": [1, 2, 3],
            "edges": [
                {"origin": 1, "target": 3},
                {"origin": 2, "target": 3},
            ],
        }
    )


def make_graph_trial_maker(network_structure):
    return GrowthQueryGraphTrialMaker(
        id_="graph_growth_query",
        node_class=GrowthQueryGraphNode,
        trial_class=GrowthQueryGraphTrial,
        network_structure=network_structure,
        chain_type="across",
        expected_trials_per_participant=1,
        max_trials_per_participant=1,
        chains_per_participant=None,
        trials_per_node=1,
        check_performance_at_end=False,
        check_performance_every_trial=False,
        recruit_mode="n_trials",
        target_n_participants=None,
        max_nodes_per_chain=2,
    )


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
)
@pytest.mark.usefixtures("in_experiment_directory")
def test_graph_topology_is_stored_in_normalized_tables(db_session):
    trial_maker = graph_trial_maker()
    trial_maker.create_networks_across(get_experiment())

    assert GraphChainVertex.query.filter_by(trial_maker_id=trial_maker.id).count() == 3
    assert GraphChainEdge.query.filter_by(trial_maker_id=trial_maker.id).count() == 2

    network = GraphChainNetwork.query.filter_by(
        trial_maker_id=trial_maker.id, vertex_id=3
    ).one()
    assert network.incoming_vertex_ids == [1, 2]
    assert network.outgoing_vertex_ids == []


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
)
@pytest.mark.usefixtures("in_experiment_directory")
def test_graph_readiness_waits_for_all_incoming_heads(db_session, participant):
    trial_maker = graph_trial_maker()
    trial_maker.create_networks_across(get_experiment())
    networks = {
        n.vertex_id: n
        for n in GraphChainNetwork.query.filter_by(trial_maker_id=trial_maker.id).all()
    }

    add_trial(GrowthQueryGraphTrial, networks[3].head, participant, finalized=True)
    db.session.commit()
    ready_ids = {n.id for n in trial_maker.get_networks_ready_to_grow()}
    assert networks[3].id not in ready_ids

    add_trial(GrowthQueryGraphTrial, networks[1].head, participant, finalized=True)
    db.session.commit()
    ready_ids = {n.id for n in trial_maker.get_networks_ready_to_grow()}
    assert networks[3].id not in ready_ids

    add_trial(GrowthQueryGraphTrial, networks[2].head, participant, finalized=True)
    db.session.commit()
    ready_ids = {n.id for n in trial_maker.get_networks_ready_to_grow()}
    assert networks[3].id in ready_ids


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
)
@pytest.mark.usefixtures("in_experiment_directory")
def test_graph_finalization_fast_path_is_scoped(db_session, participant, monkeypatch):
    trial_maker = make_graph_trial_maker(
        {
            "vertices": [1, 2, 3, 4],
            "edges": [
                {"origin": 1, "target": 2},
                {"origin": 1, "target": 3},
                {"origin": 4, "target": 3},
            ],
        }
    )
    get_experiment().timeline.trial_makers[trial_maker.id] = trial_maker
    trial_maker.create_networks_across(get_experiment())
    networks = {
        n.vertex_id: n
        for n in GraphChainNetwork.query.filter_by(trial_maker_id=trial_maker.id).all()
    }
    trial = add_trial(
        GrowthQueryGraphTrial, networks[1].head, participant, finalized=False
    )
    trial.answer = 1
    trial.complete = True

    checked_network_ids = []
    grow_calls = []

    def fake_get_networks_ready_to_grow(self, network_ids=None):
        checked_network_ids.append(set(network_ids))
        return []

    def fake_call_grow_network(self, network, check_readiness=True):
        grow_calls.append((network.id, check_readiness))

    monkeypatch.setattr(
        GrowthQueryGraphTrialMaker,
        "get_networks_ready_to_grow",
        fake_get_networks_ready_to_grow,
    )
    monkeypatch.setattr(
        GrowthQueryGraphTrialMaker, "call_grow_network", fake_call_grow_network
    )

    trial.on_finalized()

    assert grow_calls == [(networks[1].id, True)]
    assert checked_network_ids == [{networks[2].id, networks[3].id}]


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
)
@pytest.mark.usefixtures("in_experiment_directory")
def test_graph_growth_processes_ready_cycle_as_one_wave(db_session, participant):
    trial_maker = make_graph_trial_maker(
        {
            "vertices": [1, 2, 3],
            "edges": [
                {"origin": 1, "target": 2},
                {"origin": 2, "target": 1},
                {"origin": 2, "target": 3},
                {"origin": 3, "target": 2},
            ],
        }
    )
    trial_maker.create_networks_across(get_experiment())
    networks = GraphChainNetwork.query.filter_by(trial_maker_id=trial_maker.id).all()

    for network in networks:
        add_trial(GrowthQueryGraphTrial, network.head, participant, finalized=True)
    db.session.commit()

    ready_networks = trial_maker.get_networks_ready_to_grow()
    assert {network.vertex_id for network in ready_networks} == {1, 2, 3}

    for network in ready_networks:
        trial_maker.call_grow_network(network, check_readiness=False)

    assert {network.head.degree for network in networks} == {1}


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
)
@pytest.mark.usefixtures("in_experiment_directory")
def test_graph_growth_stays_in_the_callers_transaction(db_session, participant):
    trial_maker = graph_trial_maker()
    trial_maker.create_networks_across(get_experiment())
    network = GraphChainNetwork.query.filter_by(
        trial_maker_id=trial_maker.id, vertex_id=1
    ).one()
    add_trial(GrowthQueryGraphTrial, network.head, participant, finalized=True)
    db.session.commit()

    trial_maker.call_grow_network(network, check_readiness=False)
    db.session.rollback()

    assert network.head.degree == 0


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
)
@pytest.mark.usefixtures("in_experiment_directory")
def test_n_trials_still_required_counts_completed_trials_in_open_networks(
    db_session, participant
):
    exp = get_experiment()
    trial_maker = chain_trial_maker(chains_per_experiment=3, max_nodes_per_chain=3)
    started, full, empty = [create_chain_network(trial_maker, exp) for _ in range(3)]
    full.full = True
    initialize_trial_maker_state(trial_maker, participant)
    add_trial(GrowthQueryTrial, started.head, participant)
    add_trial(GrowthQueryTrial, started.head, participant, failed=True)
    add_trial(GrowthQueryTrial, started.head, participant, finalized=False)
    add_trial(GrowthQueryTrial, full.head, participant)

    with assert_query_count(max_queries=1):
        assert trial_maker.n_trials_still_required == (3 - 1) + 3


class PythonFilteredStaticTrialMaker(StaticTrialMaker):
    def custom_node_filter(self, nodes, participant, experiment):
        return nodes


def static_selection_fixture(
    participant, maker_class=StaticTrialMaker, wait_for_networks=False
):
    """Return a static trial maker and its nodes, the first three unavailable."""
    exp = get_experiment()
    trial_maker = static_trial_maker(
        target_trials_per_node=1,
        max_trials_per_participant=None,
        maker_class=maker_class,
    )
    trial_maker.wait_for_networks = wait_for_networks
    networks = [
        create_chain_network(trial_maker, exp, network_class=StaticNetwork)
        for _ in range(6)
    ]
    nodes = [network.head for network in networks]
    initialize_trial_maker_state(trial_maker, participant)
    add_trial(GrowthQueryStaticTrial, nodes[0], participant)
    nodes[1].async_on_deploy_requested = True
    networks[2].participant_group = "other"
    db.session.flush()
    return trial_maker, nodes


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
)
@pytest.mark.usefixtures("in_experiment_directory")
@pytest.mark.parametrize("wait_for_networks", [False, True])
def test_database_and_python_filter_paths_agree(
    db_session, participant, wait_for_networks
):
    exp = get_experiment()
    results = {}
    for maker_class in (StaticTrialMaker, PythonFilteredStaticTrialMaker):
        trial_maker, nodes = static_selection_fixture(
            participant, maker_class, wait_for_networks=wait_for_networks
        )
        eligible = trial_maker.find_nodes(participant, exp)
        available = {node.id for node in eligible} - {node.id for node in nodes[3:]}
        for node in nodes[3:]:
            add_trial(GrowthQueryStaticTrial, node, participant)
        results[maker_class] = (
            len(eligible),
            available,
            trial_maker.find_nodes(participant, exp),
        )
        db.session.rollback()
        participant = new_participant()

    assert results[StaticTrialMaker] == results[PythonFilteredStaticTrialMaker]
    assert results[StaticTrialMaker] == (
        3,
        set(),
        "wait" if wait_for_networks else [],
    )


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
)
@pytest.mark.usefixtures("in_experiment_directory")
def test_query_hooks_filter_and_rank_nodes(db_session, participant):
    class RankedTrialMaker(StaticTrialMaker):
        def filter_nodes_query(self, query, participant, experiment):
            return query.filter(self.node_class.id != highest_id)

        def node_priority(self, participant, experiment):
            return self.node_class.id.desc()

    trial_maker, nodes = static_selection_fixture(participant, RankedTrialMaker)
    highest_id = nodes[-1].id

    selection = trial_maker._select_trial_node(participant, get_experiment())

    assert selection.value is nodes[-2]


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
)
@pytest.mark.usefixtures("in_experiment_directory")
def test_before_selection_can_wait_or_exit_before_discovery(db_session, participant):
    class GatedTrialMaker(StaticTrialMaker):
        def before_selection(self, participant, experiment):
            return outcome

    trial_maker, _ = static_selection_fixture(participant, GatedTrialMaker)
    exp = get_experiment()

    outcome = "wait"
    with assert_query_count(max_queries=0):
        assert trial_maker._select_trial_node(participant, exp) == "wait"

    outcome = "later"
    with pytest.raises(ValueError, match="before_selection must return"):
        trial_maker._select_trial_node(participant, exp)


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
)
@pytest.mark.usefixtures("in_experiment_directory")
@pytest.mark.parametrize("filter_in_python", [False, True])
def test_selection_pool_limits_candidates_to_available_ones(
    db_session, participant, filter_in_python
):
    base = PythonFilteredStaticTrialMaker if filter_in_python else StaticTrialMaker

    class PooledTrialMaker(base):
        selection_pool_size = 2

        def select_node(self, nodes, participant, experiment):
            seen.append(nodes)
            return nodes[0]

    seen = []
    trial_maker, nodes = static_selection_fixture(participant, PooledTrialMaker)

    trial_maker._select_trial_node(participant, get_experiment())

    (pool,) = seen
    assert len(pool) == 2
    assert {node.id for node in pool} <= {node.id for node in nodes[3:]}


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
)
@pytest.mark.usefixtures("in_experiment_directory")
def test_python_filters_warn_once_when_loading_many_candidates(
    db_session, participant, caplog
):
    trial_maker, _ = static_selection_fixture(
        participant, PythonFilteredStaticTrialMaker
    )
    trial_maker._many_candidates_threshold = 3
    exp = get_experiment()

    trial_maker.find_nodes(participant, exp)
    trial_maker.find_nodes(participant, exp)

    warnings = [r for r in caplog.records if "selection_pool_size" in r.message]
    assert len(warnings) == 1
    assert "custom_node_filter" in warnings[0].message
    assert "filter_nodes_query" in warnings[0].message


def networks_in_blocks(trial_maker, participant, blocks, network_class=ChainNetwork):
    """Create one network per entry of ``blocks`` and start the participant in the first block."""
    exp = get_experiment()
    networks = [
        create_chain_network(trial_maker, exp, network_class=network_class)
        for _ in blocks
    ]
    for network, block in zip(networks, blocks):
        network.block = network.head.block = block
    initialize_trial_maker_state(trial_maker, participant)
    participant.module_state.block_order = list(dict.fromkeys(blocks))
    participant.module_state.set_block_position(0)
    db.session.flush()
    return networks


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
)
@pytest.mark.usefixtures("in_experiment_directory")
@pytest.mark.parametrize("wait_for_networks", [True, False])
def test_busy_block_waits_or_finishes_early(db_session, participant, wait_for_networks):
    trial_maker = chain_trial_maker(
        chains_per_experiment=2,
        max_trials_per_participant=None,
        wait_for_networks=wait_for_networks,
    )
    busy, free = networks_in_blocks(trial_maker, participant, ["A", "B"])
    add_trial(GrowthQueryTrial, busy.head, new_participant(), finalized=False)

    outcome = trial_maker._select_trial_node(participant, get_experiment())

    if wait_for_networks:
        assert outcome == "wait"
        assert participant.module_state.block == "A"
    else:
        assert outcome.value is free.head
        assert participant.module_state.block == "B"


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
)
@pytest.mark.usefixtures("in_experiment_directory")
def test_without_interleaving_participant_waits_for_current_chain(
    db_session, participant
):
    trial_maker = chain_trial_maker(
        chains_per_experiment=2,
        max_trials_per_participant=10,
        interleave_chains=False,
        allow_revisiting_networks_in_across_chains=True,
    )
    first, _ = networks_in_blocks(trial_maker, participant, ["default", "default"])
    trial_maker._on_node_claimed(first.head, participant)
    add_trial(GrowthQueryTrial, first.head, new_participant(), finalized=False)

    assert trial_maker._select_trial_node(participant, get_experiment()) == "wait"


def _reverse_and_drop_last(nodes):
    return list(reversed(nodes))[:-1]


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
)
@pytest.mark.usefixtures("in_experiment_directory")
@pytest.mark.parametrize(
    "node_order, expected_positions",
    [("listed", [0, 1, 2]), (_reverse_and_drop_last, [2, 1])],
)
def test_planned_node_order_is_followed_then_exits(
    db_session, participant, node_order, expected_positions
):
    trial_maker = static_trial_maker(
        target_trials_per_node=None,
        max_trials_per_participant=None,
        node_order=node_order,
    )
    exp = get_experiment()
    networks = networks_in_blocks(
        trial_maker, participant, ["default"] * 3, network_class=StaticNetwork
    )

    received = []
    while True:
        trial, status = trial_maker.prepare_trial(exp, participant)
        if trial is None:
            break
        received.append(trial.node)

    assert status == "exit"
    assert received == [networks[i].head for i in expected_positions]


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
)
@pytest.mark.usefixtures("in_experiment_directory")
def test_full_planned_node_is_skipped_with_a_warning(db_session, participant, caplog):
    trial_maker = static_trial_maker(
        target_trials_per_node=1,
        max_trials_per_participant=None,
        node_order="listed",
    )
    *full, other = networks_in_blocks(
        trial_maker, participant, ["default"] * 21, network_class=StaticNetwork
    )
    other_participant = new_participant()
    for network in full:
        add_trial(GrowthQueryStaticTrial, network.head, other_participant)
    trial_maker._plan_block(participant, get_experiment())

    # Skipping many full nodes costs no more queries than skipping one.
    with assert_query_count(max_queries=8):
        selection = trial_maker._select_trial_node(participant, get_experiment())

    assert selection.value is other.head
    assert any("Skipping planned node" in r.message for r in caplog.records)


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
)
@pytest.mark.usefixtures("in_experiment_directory")
def test_held_planned_node_is_retried_at_the_end(db_session, participant):
    trial_maker = static_trial_maker(
        target_trials_per_node=1,
        max_trials_per_participant=None,
        node_order="listed",
    )
    held, other = networks_in_blocks(
        trial_maker, participant, ["default"] * 2, network_class=StaticNetwork
    )
    add_trial(GrowthQueryStaticTrial, held.head, new_participant(), finalized=False)

    selection = trial_maker._select_trial_node(participant, get_experiment())

    assert selection.value is other.head
    assert participant.module_state.planned_network_ids == [other.id, held.id]


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
)
@pytest.mark.usefixtures("in_experiment_directory")
def test_planned_chains_skip_a_busy_chain_when_interleaving(db_session, participant):
    trial_maker = chain_trial_maker(
        chains_per_experiment=2,
        max_trials_per_participant=10,
        chain_order="listed",
    )
    busy, free = networks_in_blocks(trial_maker, participant, ["default", "default"])
    add_trial(GrowthQueryTrial, busy.head, new_participant(), finalized=False)

    selection = trial_maker._select_trial_node(participant, get_experiment())

    assert selection.value is free.head


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
)
@pytest.mark.usefixtures("in_experiment_directory")
@pytest.mark.parametrize("chain_order", ["random", "listed"])
def test_without_interleaving_participant_moves_on_once_chain_is_full(
    db_session, participant, chain_order
):
    trial_maker = chain_trial_maker(
        chains_per_experiment=2,
        max_trials_per_participant=10,
        interleave_chains=False,
        allow_revisiting_networks_in_across_chains=True,
        chain_order=chain_order,
        trials_per_node=10,
    )
    networks = networks_in_blocks(trial_maker, participant, ["default", "default"])
    exp = get_experiment()

    first = trial_maker._select_trial_node(participant, exp).value
    trial_maker._on_node_claimed(first, participant)
    assert trial_maker._select_trial_node(participant, exp).value is first

    first.network.full = True
    db.session.flush()
    second = trial_maker._select_trial_node(participant, exp).value

    assert {first, second} == {network.head for network in networks}
    if chain_order == "listed":
        assert first is networks[0].head


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
)
@pytest.mark.usefixtures("in_experiment_directory")
def test_listed_chain_order_rotates_through_chains(db_session, participant):
    trial_maker = chain_trial_maker(
        chains_per_experiment=2,
        max_trials_per_participant=10,
        chain_order="listed",
        allow_revisiting_networks_in_across_chains=True,
        trials_per_node=10,
    )
    first, second = networks_in_blocks(trial_maker, participant, ["default", "default"])
    exp = get_experiment()

    received = []
    for _ in range(3):
        selection = trial_maker._select_trial_node(participant, exp)
        trial_maker._on_node_claimed(selection.value, participant)
        received.append(selection.value)

    assert received == [first.head, second.head, first.head]
