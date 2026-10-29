from types import SimpleNamespace

from psynet.trial.chain import (
    ChainNode,
    ChainTrial,
    ChainTrialMaker,
    ChainTrialMakerState,
)


class CustomTrial(ChainTrial):
    time_estimate = 1


def build_trial_maker(sync_group_type=None):
    return ChainTrialMaker(
        id_="tm",
        trial_class=CustomTrial,
        node_class=ChainNode,
        chain_type="across",
        expected_trials_per_participant=1,
        max_trials_per_participant=1,
        max_nodes_per_chain=1,
        chains_per_experiment=1,
        check_performance_at_end=False,
        check_performance_every_trial=False,
        recruit_mode="n_participants",
        target_n_participants=1,
        sync_group_type=sync_group_type,
    )


class BlockState:
    block = ChainTrialMakerState.block
    is_last_block = ChainTrialMakerState.is_last_block
    set_block_position = ChainTrialMakerState.set_block_position


def make_state(block_order):
    state = BlockState()
    state.block_order = block_order
    state.set_block_position(0)
    state.planned_network_ids = [1, 2]
    state.plan_position = 1
    return state


def test_next_block_moves_the_sync_group_and_clears_plans():
    states = [make_state(["A", "B"]), make_state(["A", "B"])]
    participants = [SimpleNamespace(module_state=state) for state in states]
    group = SimpleNamespace(participants=participants)
    for participant in participants:
        participant.id = 1
        participant.active_sync_groups = {"sync": group}

    build_trial_maker(sync_group_type="sync")._go_to_next_block(participants[0])

    for state in states:
        assert state.block == "B"
        assert state.is_last_block
        assert state.planned_network_ids is None
        assert state.plan_position is None
