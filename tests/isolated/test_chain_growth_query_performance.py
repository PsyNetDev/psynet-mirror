import statistics
import time
import uuid

import pytest
from dallinger import db

from psynet.experiment import get_experiment
from psynet.participant import Participant
from psynet.pytest_psynet import path_to_test_experiment
from psynet.sqlalchemy_profiling import sqlalchemy_profile
from psynet.trial.chain import ChainNetwork, ChainNode, ChainTrial, ChainTrialMaker
from psynet.trial.graph import GraphChainNetwork, GraphChainNode, GraphChainTrialMaker
from psynet.trial.static import StaticNetwork

N_NETWORKS = 1000
N_REPEATS = 3
HANG_CAP_MS = 30_000


class BenchmarkTrial(ChainTrial):
    time_estimate = 1

    def make_definition(self, experiment, participant):
        return self.node.definition


class BenchmarkNode(ChainNode):
    def create_initial_seed(self, experiment, participant):
        return {"x": 0}

    def summarize_trials(self, trials, experiment, participant):
        return {"x": trials[0].answer}

    def create_definition_from_seed(self, seed, experiment, participant):
        return seed


class BenchmarkGraphNode(GraphChainNode):
    @staticmethod
    def generate_class_seed(vertex=None):
        return [{"vertex_id": vertex, "content": vertex, "is_center": True}]


def make_participant():
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


def make_chain_trial_maker(id_, *, network_class=ChainNetwork):
    return ChainTrialMaker(
        id_=id_,
        node_class=BenchmarkNode,
        trial_class=BenchmarkTrial,
        network_class=network_class,
        chain_type="across",
        expected_trials_per_participant=1,
        max_trials_per_participant=1,
        chains_per_experiment=1,
        max_nodes_per_chain=2,
        trials_per_node=1,
        recruit_mode="n_trials",
    )


def make_graph_trial_maker(id_):
    vertices = list(range(N_NETWORKS))
    return GraphChainTrialMaker(
        id_=id_,
        node_class=BenchmarkGraphNode,
        trial_class=BenchmarkTrial,
        network_structure={
            "vertices": vertices,
            "edges": [{"origin": i, "target": (i + 1) % N_NETWORKS} for i in vertices],
        },
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


def create_chain_network(trial_maker, experiment, *, network_class=ChainNetwork):
    start_node = trial_maker.node_class(definition={"x": 0})
    network = network_class(
        trial_maker_id=trial_maker.id,
        start_node=start_node,
        experiment=experiment,
        chain_type=trial_maker.chain_type,
        trials_per_node=trial_maker.trials_per_node,
        target_n_nodes=trial_maker.max_nodes_per_chain,
    )
    db.session.add(network)
    return network


def add_trial(node, participant, *, finalized):
    trial = BenchmarkTrial(
        experiment=get_experiment(),
        node=node,
        participant=participant,
        propagate_failure=False,
        is_repeat_trial=False,
    )
    trial.answer = {"x": 1}
    trial.complete = finalized
    trial.finalized = finalized
    trial.failed = False
    db.session.add(trial)
    return trial


def create_chain_scenario(trial_maker, participant, *, finalized, network_class):
    exp = get_experiment()
    for _ in range(N_NETWORKS):
        network = create_chain_network(trial_maker, exp, network_class=network_class)
        add_trial(network.head, participant, finalized=finalized)
    db.session.commit()


def create_graph_scenario(trial_maker, participant):
    trial_maker.create_networks_across(get_experiment())
    for network in GraphChainNetwork.query.filter_by(trial_maker_id=trial_maker.id):
        add_trial(network.head, participant, finalized=True)
    db.session.commit()


def time_ready_query(trial_maker):
    """Return the ready count, statement count, and median and max call times in ms."""
    with sqlalchemy_profile(db.engine) as profiler:
        trial_maker.get_networks_ready_to_grow()
    n_statements = profiler.total_count
    timings = []
    ready_count = None
    for _ in range(N_REPEATS):
        start = time.perf_counter()
        ready = trial_maker.get_networks_ready_to_grow()
        timings.append((time.perf_counter() - start) * 1000)
        ready_count = len(ready)
    return ready_count, n_statements, statistics.median(timings), max(timings)


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
)
@pytest.mark.usefixtures("in_experiment_directory")
def test_growth_readiness_query_performance(db_session):
    participant = make_participant()

    scenarios = [
        {
            "name": "ordinary_ready",
            "trial_maker": make_chain_trial_maker("ordinary_ready"),
            "setup": lambda tm: create_chain_scenario(
                tm, participant, finalized=True, network_class=ChainNetwork
            ),
            "expected_ready": N_NETWORKS,
            "n_edges": 0,
        },
        {
            "name": "ordinary_pending",
            "trial_maker": make_chain_trial_maker("ordinary_pending"),
            "setup": lambda tm: create_chain_scenario(
                tm, participant, finalized=False, network_class=ChainNetwork
            ),
            "expected_ready": 0,
            "n_edges": 0,
        },
        {
            "name": "static_excluded",
            "trial_maker": make_chain_trial_maker(
                "static_excluded", network_class=StaticNetwork
            ),
            "setup": lambda tm: create_chain_scenario(
                tm, participant, finalized=True, network_class=StaticNetwork
            ),
            "expected_ready": 0,
            "n_edges": 0,
        },
        {
            "name": "graph_sparse",
            "trial_maker": make_graph_trial_maker("graph_sparse"),
            "setup": lambda tm: create_graph_scenario(tm, participant),
            "expected_ready": N_NETWORKS,
            "n_edges": N_NETWORKS,
        },
    ]

    rows = []
    for scenario in scenarios:
        trial_maker = scenario["trial_maker"]
        scenario["setup"](trial_maker)
        ready_count, n_statements, median_ms, max_ms = time_ready_query(trial_maker)
        rows.append(
            {
                "scenario": scenario["name"],
                "networks": N_NETWORKS,
                "edges": scenario["n_edges"],
                "ready": ready_count,
                "expected_ready": scenario["expected_ready"],
                "statements": n_statements,
                "median_ms": median_ms,
                "max_ms": max_ms,
            }
        )

    print("\ngrowth readiness query benchmark")
    print("scenario             networks  edges  ready  statements  median_ms  max_ms")
    for row in rows:
        print(
            f"{row['scenario']:<20} "
            f"{row['networks']:>8} "
            f"{row['edges']:>6} "
            f"{row['ready']:>6} "
            f"{row['statements']:>11} "
            f"{row['median_ms']:>10.1f} "
            f"{row['max_ms']:>7.1f}"
        )

    for row in rows:
        assert row["ready"] == row["expected_ready"], row
        # One locking ID query, plus one load when any network is ready.
        assert row["statements"] == (2 if row["ready"] else 1), row
        # Timings vary too much under CI load for a budget; only catch hangs.
        assert row["max_ms"] < HANG_CAP_MS, row
