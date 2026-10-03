"""Tests for explicit trial/network count helpers."""

from unittest.mock import MagicMock, patch

from psynet.trial.chain import (
    count_completed_trials_for_network,
    count_completed_trials_for_networks,
    count_participant_trials_in_block,
    count_participant_trials_in_trial_maker,
    count_viable_trials_for_node,
    count_viable_trials_for_nodes,
)


def test_count_viable_trials_for_nodes_empty():
    assert count_viable_trials_for_nodes([]) == {}
    assert count_viable_trials_for_nodes([None]) == {}


def test_count_completed_trials_for_networks_empty():
    assert count_completed_trials_for_networks([]) == {}
    assert count_completed_trials_for_networks([None]) == {}


def test_count_helpers_are_importable():
    # Smoke-check the public helper API used by chain allocation and recruitment.
    assert callable(count_viable_trials_for_node)
    assert callable(count_completed_trials_for_network)
    assert callable(count_completed_trials_for_networks)
    assert callable(count_participant_trials_in_trial_maker)
    assert callable(count_participant_trials_in_block)


def test_chain_trial_maker_n_trials_still_required_batches_counts():
    from psynet.trial.chain import ChainTrialMaker

    maker = ChainTrialMaker.__new__(ChainTrialMaker)
    maker.chain_type = "across"

    networks = []
    for network_id, full, target in [
        (1, False, 10),
        (2, True, 10),
        (3, False, 8),
    ]:
        network = MagicMock()
        network.id = network_id
        network.full = full
        network.target_n_trials = target
        networks.append(network)

    with (
        patch.object(ChainTrialMaker, "networks", new=property(lambda self: networks)),
        patch(
            "psynet.trial.chain.count_completed_trials_for_networks",
            return_value={1: 3, 3: 2},
        ) as batch_count,
    ):
        assert maker.n_trials_still_required == (10 - 3) + (8 - 2)
        batch_count.assert_called_once()
        # Full networks are skipped; only incomplete ids are queried.
        queried_ids = list(batch_count.call_args.args[0])
        assert queried_ids == [1, 3]
