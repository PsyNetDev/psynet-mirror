import pytest

from psynet.trial.graph import GraphChainNode, GraphChainTrial, GraphChainTrialMaker
from psynet.trial.static import StaticNode, StaticTrial, StaticTrialMaker


class DummyTrial(StaticTrial):
    time_estimate = 1

    def show_trial(self, experiment, participant):
        pass


def _static_trial_maker(**kwargs):
    defaults = dict(
        id_="dummy",
        trial_class=DummyTrial,
        nodes=[StaticNode(definition={"x": 1})],
        expected_trials_per_participant=1,
        target_n_participants=1,
        recruit_mode="n_participants",
    )
    defaults.update(kwargs)
    return StaticTrialMaker(**defaults)


def test_default_n_participants_completion_is_experiment():
    trial_maker = _static_trial_maker()
    assert trial_maker.n_participants_completion == "experiment"


def test_rejects_unknown_n_participants_completion():
    with pytest.raises(ValueError, match="n_participants_completion"):
        _static_trial_maker(n_participants_completion="session")


class DummyGraphTrial(GraphChainTrial):
    time_estimate = 1


class DummyGraphNode(GraphChainNode):
    @staticmethod
    def generate_class_seed(vertex=None):
        return [{"vertex_id": vertex, "content": vertex, "is_center": True}]


def test_graph_trial_maker_defaults_target_n_participants_to_none():
    trial_maker = GraphChainTrialMaker(
        id_="dummy_graph",
        node_class=DummyGraphNode,
        trial_class=DummyGraphTrial,
        network_structure={"vertices": [1], "edges": []},
        chain_type="across",
        expected_trials_per_participant=1,
        max_trials_per_participant=1,
        chains_per_participant=None,
        trials_per_node=1,
        balance_across_chains=False,
        check_performance_at_end=False,
        check_performance_every_trial=False,
        recruit_mode="n_trials",
    )
    assert trial_maker.target_n_participants is None
