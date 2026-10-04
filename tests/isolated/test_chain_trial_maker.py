import inspect
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from dallinger import db

from psynet.sync import GroupBarrier
from psynet.timeline import ModuleState
from psynet.trial.chain import ChainNode, ChainTrial, ChainTrialMaker
from psynet.trial.dense import DenseTrialMaker
from psynet.trial.main import (
    NetworkTrialMaker,
    Selection,
    Trial,
    TrialMaker,
    TrialMakerState,
)
from psynet.trial.static import StaticNode, StaticTrial, StaticTrialMaker
from psynet.utils import shuffle_with_max_run


class CustomTrial(ChainTrial):
    time_estimate = 1


class CustomNode(ChainNode):
    pass


class CustomStaticTrial(StaticTrial):
    time_estimate = 1


class DummyModuleState:
    def __init__(self):
        self.in_repeat_phase = False
        self.n_completed_trials = 0
        self.block_order = ["default"]
        self.set_block_position(0)

    block = property(lambda self: self.block_order[self.block_position])
    is_last_block = property(
        lambda self: self.block_position == len(self.block_order) - 1
    )

    def set_block_position(self, position):
        self.block_position = position
        self.current_chain_id = None
        self.planned_network_ids = None
        self.plan_position = None


class DummySyncGroup:
    def remove_participant(self, participant):
        participant.active_sync_groups.pop("main", None)


class DummyParticipant:
    def __init__(self):
        self.id = 1
        self.active_sync_groups = {}
        self.branch_log = []
        self.module_state = DummyModuleState()
        self.current_trial = None
        self.trial_status = None

    def append_branch_log(self, entry):
        self.branch_log.append(entry)


def make_trial_maker(trial_maker_class=ChainTrialMaker, **kwargs):
    args = dict(
        id_="test_trial_maker",
        node_class=CustomNode,
        trial_class=CustomTrial,
        chain_type="across",
        expected_trials_per_participant=1,
        max_trials_per_participant=1,
        chains_per_experiment=1,
        recruit_mode="n_trials",
    )
    return trial_maker_class(**{**args, **kwargs})


def make_static_trial_maker(trial_maker_class=StaticTrialMaker, **kwargs):
    args = dict(
        id_="test_static_trial_maker",
        trial_class=CustomStaticTrial,
        nodes=[StaticNode(definition={"item_id": "item-1"})],
        expected_trials_per_participant=1,
        max_trials_per_participant=1,
        recruit_mode="n_trials",
        target_trials_per_node=1,
    )
    return trial_maker_class(**{**args, **kwargs})


@pytest.mark.parametrize("target_trials_per_node", [0, -1])
def test_static_trial_maker_rejects_non_positive_target_trials_per_node(
    target_trials_per_node,
):
    with pytest.raises(ValueError, match="positive"):
        make_static_trial_maker(target_trials_per_node=target_trials_per_node)


def test_failure_policy_constructor_defaults():
    chain = inspect.signature(ChainTrialMaker.__init__).parameters
    static = inspect.signature(StaticTrialMaker.__init__).parameters
    dense = inspect.signature(DenseTrialMaker.__init__).parameters
    base = inspect.signature(TrialMaker.__init__).parameters
    network = inspect.signature(NetworkTrialMaker.__init__).parameters

    assert chain["fail_trials_on_premature_exit"].default is False
    assert chain["fail_trials_on_participant_performance_check"].default is False
    assert static["fail_trials_on_premature_exit"].default is False
    assert static["fail_trials_on_participant_performance_check"].default is True
    assert dense["fail_trials_on_premature_exit"].default is False
    assert dense["fail_trials_on_participant_performance_check"].default is True
    assert base["fail_trials_on_premature_exit"].default is False
    assert network["fail_trials_on_premature_exit"].default is False

    trial_maker = make_trial_maker()
    assert not trial_maker.fail_trials_on_participant_performance_check
    assert not hasattr(trial_maker, "fail_trials_on_premature_exit")


def test_trial_maker_constructors_are_keyword_only():
    for cls in (TrialMaker, NetworkTrialMaker):
        params = inspect.signature(cls.__init__).parameters
        kinds = [p.kind for name, p in params.items() if name != "self"]
        assert kinds
        assert all(kind is inspect.Parameter.KEYWORD_ONLY for kind in kinds)

    with pytest.raises(TypeError):
        TrialMaker(
            "id",
            object,
            1,
            False,
            False,
            False,
            True,
            "n_trials",
            None,
            0,
            None,
        )

    with pytest.raises(TypeError):
        NetworkTrialMaker(
            "id",
            object,
            object,
            1,
            False,
            False,
            False,
            True,
            "n_trials",
            None,
            0,
            False,
        )


def test_fail_trials_on_premature_exit_true_emits_deprecation_warning():
    with pytest.warns(
        DeprecationWarning, match="fail_trials_on_premature_exit"
    ) as record:
        StaticTrialMaker(
            id_="deprecated_flag",
            trial_class=CustomStaticTrial,
            nodes=[StaticNode(definition={"x": 1})],
            expected_trials_per_participant=1,
            max_trials_per_participant=1,
            recruit_mode="n_trials",
            target_trials_per_node=1,
            fail_trials_on_premature_exit=True,
        )

    warning = record[0]
    if sys.version_info >= (3, 12):
        assert Path(warning.filename).resolve() == Path(__file__).resolve()


@pytest.mark.parametrize(
    "make, kwargs, message",
    [
        (
            make_trial_maker,
            dict(recruit_mode=None, target_n_participants=5),
            "only takes effect",
        ),
        (
            make_trial_maker,
            dict(recruit_mode="n_participants"),
            "needs target_n_participants",
        ),
        (make_static_trial_maker, dict(target_n_participants=5), "only takes effect"),
        (
            make_static_trial_maker,
            dict(target_trials_per_node=None),
            "needs target_trials_per_node",
        ),
        (
            make_static_trial_maker,
            dict(recruit_mode=None),
            "target_trials_per_node only",
        ),
        (make_trial_maker, dict(recruit_mode="n_trial"), "Unknown recruit_mode"),
    ],
)
def test_recruitment_targets_need_the_matching_recruit_mode(make, kwargs, message):
    with pytest.raises(ValueError, match=message):
        make(**kwargs)


def test_custom_recruit_modes_are_allowed():
    class CustomRecruitMaker(ChainTrialMaker):
        recruit_criteria = {**ChainTrialMaker.recruit_criteria, "custom": None}

    trial_maker = make_trial_maker(CustomRecruitMaker, recruit_mode="custom")
    assert trial_maker.recruit_mode == "custom"


def test_chain_node_accepts_empty_definition():
    assert CustomNode(definition={}).definition == {}

    with pytest.raises(NotImplementedError, match="without a definition"):
        CustomNode()


def test_chain_trial_maker_rejects_mismatched_start_nodes():
    start_nodes = [ChainNode(definition={"seed": "x"})]

    with pytest.raises(ValueError, match="start_nodes must be instances of"):
        make_trial_maker(start_nodes=start_nodes)


def test_chain_trial_maker_rejects_callable_start_nodes_with_mismatch():
    def start_nodes():
        return [ChainNode(definition={"seed": "x"})]

    trial_maker = make_trial_maker(start_nodes=start_nodes)

    with pytest.raises(ValueError, match="start_nodes must be instances of"):
        trial_maker.resolve_start_nodes()


def test_static_trial_maker_error_mentions_nodes():
    nodes = [ChainNode(definition={"seed": "x"})]

    with pytest.raises(ValueError, match="nodes must be instances of StaticNode"):
        StaticTrialMaker(
            id_="test_static_trial_maker",
            trial_class=CustomStaticTrial,
            nodes=nodes,
            expected_trials_per_participant=1,
            max_trials_per_participant=1,
            recruit_mode="n_trials",
            target_trials_per_node=1,
        )


def test_sync_trial_maker_requires_active_group_for_synced_participant():
    trial_maker = make_trial_maker(sync_group_type="sync")
    participant = DummyParticipant()
    start_switch = next(
        elt
        for elt in trial_maker._init_participant()
        if getattr(elt, "label", None) == "init_participant"
    )

    with pytest.raises(RuntimeError, match="active sync group of type 'sync'"):
        start_switch.get_target(experiment=None, participant=participant)

    assert participant.branch_log == []


def test_trial_sync_group_returns_none_after_kick():
    trial = SimpleNamespace(
        trial_maker=SimpleNamespace(sync_group_type="main"),
        participant=DummyParticipant(),
    )

    assert Trial.sync_group.fget(trial) is None


def test_trial_position_is_stored_and_continues_through_repeats():
    assert Trial.__table__.c.position is not None
    state = TrialMakerState(SimpleNamespace(id="trial-maker"), participant=None)
    assert state.n_created_trials == 0

    participant = SimpleNamespace(
        module_state=SimpleNamespace(n_created_trials=6),
    )
    trial = SimpleNamespace()

    assert Trial._next_position(trial, participant, False, None) == 6
    assert Trial._next_position(trial, participant, True, 0) == 6
    assert Trial._next_position(trial, participant, True, 2) == 8
    assert (
        Trial._next_position(
            trial,
            SimpleNamespace(module_state=None),
            False,
            None,
        )
        is None
    )
    assert (
        Trial._next_position(
            trial,
            SimpleNamespace(
                module_state=ModuleState(
                    SimpleNamespace(id="plain-module"),
                    participant=None,
                )
            ),
            False,
            None,
        )
        is None
    )


def test_reinitialization_does_not_reset_trial_position_counter():
    trial_maker = make_trial_maker()
    state = SimpleNamespace(
        n_created_trials=4,
        n_completed_trials=3,
        in_repeat_phase=True,
        participant_group="default",
        trial_maker_initialized=False,
    )
    participant = SimpleNamespace(
        module_state=state,
        select_module=lambda module_id: None,
    )

    TrialMaker.init_participant(trial_maker, SimpleNamespace(), participant)

    assert state.n_created_trials == 4
    assert state.n_completed_trials == 0
    assert not state.in_repeat_phase
    assert state.trial_maker_initialized


def test_on_trial_created_is_not_called_for_generic_preparation(monkeypatch):
    trial_maker = make_trial_maker()
    participant = DummyParticipant()
    participant.module_state = DummyModuleState()
    trial = SimpleNamespace()
    experiment = SimpleNamespace()
    calls = []

    monkeypatch.setattr(
        trial_maker,
        "prepare_trial",
        lambda experiment, participant: (trial, "available"),
    )
    monkeypatch.setattr(
        trial_maker,
        "on_trial_created",
        lambda **kwargs: calls.append(kwargs),
    )

    result = trial_maker._prepare_trial(experiment, participant)

    assert result == (trial, "available")
    assert calls == []


def test_static_selection_carries_context_to_on_trial_created(monkeypatch):
    context = {"selected_utility": 0.75}

    class AdaptiveStaticTrialMaker(StaticTrialMaker):
        def select_node(self, nodes, participant, experiment):
            return Selection(value=nodes[0], context=context)

    trial_maker = make_static_trial_maker(
        AdaptiveStaticTrialMaker, recruit_mode=None, target_trials_per_node=None
    )
    participant = DummyParticipant()
    participant.module_state = DummyModuleState()
    network = SimpleNamespace(id=3, block="default")
    node = SimpleNamespace(id=2, network=network, network_id=3, block="default")
    trial = SimpleNamespace()
    calls = []

    monkeypatch.setattr(
        trial_maker,
        "find_nodes",
        lambda participant, experiment: [node],
    )
    monkeypatch.setattr(trial_maker, "_create_trial", lambda **kwargs: trial)
    monkeypatch.setattr(
        trial_maker,
        "on_trial_created",
        lambda **kwargs: calls.append(kwargs),
    )

    result = trial_maker._prepare_trial(SimpleNamespace(), participant)

    assert result == (trial, "available")
    assert calls[0]["selection_context"] == context


def test_deprecated_network_filter_accepts_keyword_only_override():
    class KeywordOnlyLegacyMaker(ChainTrialMaker):
        def custom_network_filter(self, *, candidates, participant):
            return [chain for chain in candidates if chain.id != 1]

    with pytest.warns(DeprecationWarning, match="custom_chain_filter"):
        trial_maker = make_trial_maker(KeywordOnlyLegacyMaker)
    kept = SimpleNamespace(id=0)
    dropped = SimpleNamespace(id=1)

    assert trial_maker._filter_eligible_candidates(
        [kept, dropped],
        participant=SimpleNamespace(),
        experiment=SimpleNamespace(),
    ) == [kept]


def test_select_chain_defaults_to_the_first_eligible_chain():
    trial_maker = make_trial_maker()
    first = SimpleNamespace(id=1)
    second = SimpleNamespace(id=2)

    selection = trial_maker.select_chain(
        [first, second],
        participant=SimpleNamespace(),
        experiment=SimpleNamespace(),
    )

    assert selection is first


@pytest.mark.parametrize(
    "trial_maker_factory", [make_trial_maker, make_static_trial_maker]
)
def test_empty_discovery_exits_without_calling_selection_hook(
    trial_maker_factory, monkeypatch
):
    trial_maker = trial_maker_factory()
    if isinstance(trial_maker, StaticTrialMaker):
        monkeypatch.setattr(
            trial_maker,
            "find_nodes",
            lambda participant, experiment: [],
        )
        monkeypatch.setattr(
            trial_maker,
            "select_node",
            lambda *args: pytest.fail("select_node should not be called"),
        )
    else:
        monkeypatch.setattr(
            trial_maker,
            "find_chains",
            lambda participant, experiment: [],
        )
        monkeypatch.setattr(
            trial_maker,
            "select_chain",
            lambda *args: pytest.fail("select_chain should not be called"),
        )

    assert (
        trial_maker._select_trial_node(DummyParticipant(), SimpleNamespace()) == "exit"
    )


@pytest.mark.parametrize(
    "trial_maker_factory, find_hook",
    [
        (make_trial_maker, "find_chains"),
        (make_static_trial_maker, "find_nodes"),
    ],
)
@pytest.mark.parametrize("bad_value", [None, object()])
def test_discovery_rejects_non_list_results(
    trial_maker_factory, find_hook, bad_value, monkeypatch
):
    trial_maker = trial_maker_factory()
    monkeypatch.setattr(
        trial_maker,
        find_hook,
        lambda participant, experiment: bad_value,
    )

    with pytest.raises(TypeError, match="must return a list"):
        trial_maker._select_trial_node(DummyParticipant(), SimpleNamespace())


def test_chain_selection_resolves_head_without_leaving_the_block(monkeypatch):
    trial_maker = make_trial_maker()
    participant = DummyParticipant()
    participant.module_state.block_order = ["default", "next"]
    chain = SimpleNamespace(id=1, block="default")
    head = SimpleNamespace(id=2, network=chain, network_id=1)
    chain.head = head
    context = {"reason": "highest utility"}

    monkeypatch.setattr(
        trial_maker,
        "find_chains",
        lambda participant, experiment: [chain],
    )
    monkeypatch.setattr(
        trial_maker,
        "select_chain",
        lambda chains, participant, experiment: Selection(
            value=chain,
            context=context,
        ),
    )

    selection = trial_maker._select_trial_node(participant, SimpleNamespace())

    assert selection == Selection(value=head, context=context)
    trial_maker._on_node_claimed(head, participant)
    assert participant.module_state.block == "default"


def test_follower_uses_leader_trial_class(monkeypatch):
    class LeaderTrial:
        def __init__(
            self,
            experiment,
            node,
            participant,
            propagate_failure,
            is_repeat_trial,
        ):
            self.assets = {}

        def finalize_assets(self):
            pass

    trial_maker = make_trial_maker()
    participant = DummyParticipant()
    leader = DummyParticipant()
    leader.id = 2
    leader.trial_status = "available"
    leader.current_trial = object.__new__(LeaderTrial)
    leader.current_trial.node = SimpleNamespace(id=1)

    monkeypatch.setattr(
        trial_maker,
        "get_trial_class",
        lambda *args: pytest.fail("get_trial_class should not be called"),
    )
    monkeypatch.setattr(db.session, "add", lambda trial: None)

    trial, status = trial_maker.prepare_follower_trial(
        SimpleNamespace(),
        participant,
        leader,
    )

    assert isinstance(trial, LeaderTrial)
    assert status == "available"


def test_follower_does_not_call_on_trial_created(monkeypatch):
    class LeaderTrial:
        def __init__(
            self,
            experiment,
            node,
            participant,
            propagate_failure,
            is_repeat_trial,
        ):
            self.assets = {}

        def finalize_assets(self):
            pass

    trial_maker = make_trial_maker()
    participant = DummyParticipant()
    leader = DummyParticipant()
    leader.id = 2
    leader.trial_status = "available"
    leader.current_trial = object.__new__(LeaderTrial)
    leader.current_trial.node = SimpleNamespace(id=1)
    calls = []

    monkeypatch.setattr(
        trial_maker,
        "on_trial_created",
        lambda **kwargs: calls.append(kwargs),
    )
    monkeypatch.setattr(db.session, "add", lambda trial: None)

    trial_maker.prepare_follower_trial(
        SimpleNamespace(),
        participant,
        leader,
    )

    assert calls == []


def test_select_chain_rejects_none():
    trial_maker = make_trial_maker()
    chain = SimpleNamespace(id=1)

    with pytest.raises(TypeError, match="must not return None"):
        trial_maker._coerce_selection(
            None,
            allowed_values=[chain],
            method_name="select_chain",
        )


def test_select_chain_none_does_not_exit(monkeypatch):
    class NoneChainMaker(ChainTrialMaker):
        def select_chain(self, chains, participant, experiment):
            return None

    trial_maker = make_trial_maker(NoneChainMaker)
    chain = SimpleNamespace(id=1, head=SimpleNamespace(id=2), block="default")
    monkeypatch.setattr(
        trial_maker,
        "find_chains",
        lambda participant, experiment: [chain],
    )

    with pytest.raises(TypeError, match="must not return None"):
        trial_maker._select_trial_node(DummyParticipant(), SimpleNamespace())


def test_select_node_rejects_none(monkeypatch):
    class NoneStaticMaker(StaticTrialMaker):
        def select_node(self, nodes, participant, experiment):
            return None

    trial_maker = make_static_trial_maker(NoneStaticMaker)
    headed = _headed_chains(1)
    monkeypatch.setattr(
        trial_maker,
        "find_nodes",
        lambda participant, experiment: [headed[0].head],
    )

    with pytest.raises(TypeError, match="must not return None"):
        trial_maker._select_trial_node(DummyParticipant(), SimpleNamespace())


def test_bare_value_is_coerced_to_selection():
    trial_maker = make_trial_maker()
    first = SimpleNamespace(id=1)
    second = SimpleNamespace(id=2)

    selection = trial_maker._coerce_selection(
        second,
        allowed_values=[first, second],
        method_name="select_chain",
    )

    assert isinstance(selection, Selection)
    assert selection.value is second
    assert selection.context is None


def test_selection_keeps_context():
    trial_maker = make_trial_maker()
    chain = SimpleNamespace(id=1)
    context = {"selected_utility": 0.5}

    selection = trial_maker._coerce_selection(
        Selection(value=chain, context=context),
        allowed_values=[chain],
        method_name="select_chain",
    )

    assert selection.value is chain
    assert selection.context == context


def test_selection_rejects_a_value_outside_the_eligible_list():
    trial_maker = make_trial_maker()
    eligible = SimpleNamespace(id=1)
    other = SimpleNamespace(id=2)

    with pytest.raises(ValueError, match="supplied eligible values"):
        trial_maker._coerce_selection(
            other,
            allowed_values=[eligible],
            method_name="select_chain",
        )


def test_selection_rejects_a_requery_with_the_same_id():
    trial_maker = make_trial_maker()
    eligible = SimpleNamespace(id=1)
    requery = SimpleNamespace(id=1)

    with pytest.raises(ValueError, match="same object identity"):
        trial_maker._coerce_selection(
            requery,
            allowed_values=[eligible],
            method_name="select_chain",
        )


@pytest.mark.parametrize(
    ("method_name", "replacement"),
    [
        ("prioritize_networks", "select_chain"),
        ("find_networks", "find_chains"),
        ("find_node", "head"),
        ("find_nodes", "find_chains"),
        ("select_node", "select_chain"),
        ("custom_node_filter", "custom_chain_filter"),
        ("filter_nodes_query", "filter_chains_query"),
        ("node_priority", "chain_priority"),
    ],
)
def test_chain_rejects_removed_or_wrong_paradigm_hooks(method_name, replacement):
    old_maker = type(
        "OldMaker",
        (ChainTrialMaker,),
        {method_name: lambda self, *args, **kwargs: None},
    )

    with pytest.raises(TypeError, match=replacement):
        make_trial_maker(old_maker)


@pytest.mark.parametrize(
    ("method_name", "replacement"),
    [
        ("find_networks", "find_nodes"),
        ("find_node", "select nodes directly"),
        ("prioritize_networks", "select_node"),
        ("find_chains", "find_nodes"),
        ("select_chain", "select_node"),
        ("custom_chain_filter", "custom_node_filter"),
        ("filter_chains_query", "filter_nodes_query"),
        ("chain_priority", "node_priority"),
    ],
)
def test_static_rejects_removed_or_wrong_paradigm_hooks(method_name, replacement):
    old_maker = type(
        "OldStaticMaker",
        (StaticTrialMaker,),
        {method_name: lambda self, *args, **kwargs: None},
    )

    with pytest.raises(TypeError, match=replacement):
        make_static_trial_maker(old_maker)


def _headed_chains(n):
    chains = []
    for i in range(n):
        chain = SimpleNamespace(id=i)
        node = SimpleNamespace(id=i, network=chain)
        chain.head = node
        chains.append(chain)
    return chains


class CountingList(list):
    """Count how many times a candidate list is scanned."""

    def __init__(self, values):
        super().__init__(values)
        self.iter_count = 0

    def __iter__(self):
        self.iter_count += 1
        return super().__iter__()


def test_selection_subset_validation_is_linear_in_candidate_count():
    items = [SimpleNamespace(id=i) for i in range(80)]
    allowed = CountingList(items)

    NetworkTrialMaker._validate_selection_subset(
        list(items),
        allowed_values=allowed,
        method_name="custom_node_filter",
    )

    assert allowed.iter_count == 1


def test_custom_node_filter_drops_nodes():
    class SelectiveStaticMaker(StaticTrialMaker):
        def custom_node_filter(self, nodes, participant, experiment):
            return [node for node in nodes if node.id != 1]

    trial_maker = make_static_trial_maker(SelectiveStaticMaker)
    kept, dropped = _headed_chains(2)

    assert trial_maker._filter_eligible_candidates(
        [kept, dropped],
        participant=SimpleNamespace(),
        experiment=SimpleNamespace(),
    ) == [kept.head]


def test_custom_node_filter_rejects_noncandidate_node():
    outsider = SimpleNamespace(id=2)

    class InvalidStaticMaker(StaticTrialMaker):
        def custom_node_filter(self, nodes, participant, experiment):
            return [outsider]

    trial_maker = make_static_trial_maker(InvalidStaticMaker)
    chain = SimpleNamespace(id=1)
    node = SimpleNamespace(id=1, network=chain)
    chain.head = node

    with pytest.raises(ValueError, match="supplied eligible values"):
        trial_maker._filter_eligible_candidates(
            [chain],
            participant=SimpleNamespace(),
            experiment=SimpleNamespace(),
        )


def test_custom_node_filter_rejects_duplicate_node():
    class DuplicateStaticMaker(StaticTrialMaker):
        def custom_node_filter(self, nodes, participant, experiment):
            return [nodes[0], nodes[0]]

    trial_maker = make_static_trial_maker(DuplicateStaticMaker)
    chain = SimpleNamespace(id=1)
    node = SimpleNamespace(id=1, network=chain)
    chain.head = node

    with pytest.raises(ValueError, match="duplicate values"):
        trial_maker._filter_eligible_candidates(
            [chain],
            participant=SimpleNamespace(),
            experiment=SimpleNamespace(),
        )


def test_custom_chain_filter_drops_chains():
    class SelectiveChainMaker(ChainTrialMaker):
        def custom_chain_filter(self, chains, participant, experiment):
            return [chain for chain in chains if chain.id != 1]

    trial_maker = make_trial_maker(SelectiveChainMaker)
    kept = SimpleNamespace(id=0)
    dropped = SimpleNamespace(id=1)

    assert trial_maker._filter_eligible_candidates(
        [kept, dropped],
        participant=SimpleNamespace(),
        experiment=SimpleNamespace(),
    ) == [kept]


def test_deprecated_network_filter_still_filters_chains():
    class LegacyChainMaker(ChainTrialMaker):
        def custom_network_filter(self, candidates, participant):
            return [chain for chain in candidates if chain.id != 1]

    with pytest.warns(DeprecationWarning, match="custom_chain_filter") as record:
        trial_maker = make_trial_maker(LegacyChainMaker)
    if sys.version_info >= (3, 12):
        assert Path(record[0].filename).resolve() == Path(__file__).resolve()
    kept = SimpleNamespace(id=0)
    dropped = SimpleNamespace(id=1)

    assert trial_maker._filter_eligible_candidates(
        [kept, dropped],
        participant=SimpleNamespace(),
        experiment=SimpleNamespace(),
    ) == [kept]


def test_deprecated_network_filter_still_filters_static_networks():
    class LegacyStaticMaker(StaticTrialMaker):
        def custom_network_filter(self, candidates, participant):
            return [chain for chain in candidates if chain.id != 1]

    with pytest.warns(DeprecationWarning, match="custom_node_filter"):
        trial_maker = make_static_trial_maker(LegacyStaticMaker)
    kept, dropped = _headed_chains(2)

    assert trial_maker._filter_eligible_candidates(
        [kept, dropped],
        participant=SimpleNamespace(),
        experiment=SimpleNamespace(),
    ) == [kept.head]


def test_deprecated_static_network_filter_errors_name_that_method():
    class LegacyStaticMaker(StaticTrialMaker):
        def custom_network_filter(self, candidates, participant):
            return [SimpleNamespace(id=99)]

    with pytest.warns(DeprecationWarning, match="custom_node_filter"):
        trial_maker = make_static_trial_maker(LegacyStaticMaker)
    (chain,) = _headed_chains(1)

    with pytest.raises(ValueError, match="custom_network_filter"):
        trial_maker._filter_eligible_candidates(
            [chain],
            participant=SimpleNamespace(),
            experiment=SimpleNamespace(),
        )


def test_custom_chain_filter_takes_precedence_over_deprecated_network_filter():
    class BothFilters(ChainTrialMaker):
        def custom_chain_filter(self, chains, participant, experiment):
            return [chain for chain in chains if chain.id != 2]

        def custom_network_filter(self, candidates, participant):
            return [chain for chain in candidates if chain.id != 1]

    with pytest.warns(DeprecationWarning, match="custom_chain_filter"):
        trial_maker = make_trial_maker(BothFilters)
    first = SimpleNamespace(id=1)
    second = SimpleNamespace(id=2)

    assert trial_maker._filter_eligible_candidates(
        [first, second],
        participant=SimpleNamespace(),
        experiment=SimpleNamespace(),
    ) == [first]


def test_custom_node_filter_takes_precedence_over_deprecated_network_filter():
    class BothFilters(StaticTrialMaker):
        def custom_node_filter(self, nodes, participant, experiment):
            return [node for node in nodes if node.id != 1]

        def custom_network_filter(self, candidates, participant):
            return [chain for chain in candidates if chain.id != 0]

    with pytest.warns(DeprecationWarning, match="custom_node_filter"):
        trial_maker = make_static_trial_maker(BothFilters)
    kept, dropped = _headed_chains(2)

    assert trial_maker._filter_eligible_candidates(
        [kept, dropped],
        participant=SimpleNamespace(),
        experiment=SimpleNamespace(),
    ) == [kept.head]


def test_create_trial_rejects_none_trial_class():
    trial_maker = make_trial_maker()
    node = SimpleNamespace(id=1)

    trial_maker.get_trial_class = lambda node, participant, experiment: None

    with pytest.raises(TypeError, match="get_trial_class must return"):
        trial_maker._create_trial(
            node=node,
            participant=SimpleNamespace(),
            experiment=SimpleNamespace(),
        )


def test_sync_trial_maker_wait_content_is_used_by_internal_barriers():
    trial_maker = make_trial_maker(
        sync_group_type="main",
        sync_group_wait_content="Waiting for your partner",
    )
    holds = [
        elt
        for elt in trial_maker.elts
        if getattr(elt, "barrier_id", None)
        in {
            trial_maker.with_namespace("init_participant"),
            trial_maker.with_namespace("prepare_trial"),
        }
    ]
    assert {hold.barrier_id for hold in holds} == {
        trial_maker.with_namespace("init_participant"),
        trial_maker.with_namespace("prepare_trial"),
    }
    assert all(hold.content == "Waiting for your partner" for hold in holds)
    assert all(
        hold.translated_content() == "Waiting for your partner" for hold in holds
    )


def test_sync_trial_maker_prepare_barrier_kick_exits_cleanly(monkeypatch):
    trial_maker = make_trial_maker(
        sync_group_type="main",
        sync_group_max_wait_action="kick",
    )
    participant = DummyParticipant()
    participant.module_state = DummyModuleState()
    participant.active_sync_groups["main"] = DummySyncGroup()

    GroupBarrier._kick_participant_after_max_wait(participant, group_type="main")
    assert "main" not in participant.active_sync_groups

    prepare_trial_calls = []

    def fail_if_prepare_trial_called(experiment, participant):
        prepare_trial_calls.append(participant.id)
        raise AssertionError("kicked participants should exit before preparing a trial")

    monkeypatch.setattr(trial_maker, "prepare_trial", fail_if_prepare_trial_called)

    trial_maker._try_to_prepare_trial_solo(experiment=None, participant=participant)

    assert participant.current_trial is None
    assert participant.trial_status == "exit"
    assert prepare_trial_calls == []


def _check_consistency(repeat_answers, parent_answers):
    class ConsistencyTrialMaker(ChainTrialMaker):
        performance_check_type = "consistency"

    trials = [
        SimpleNamespace(
            is_repeat_trial=True,
            answer=repeat_answer,
            parent_trial=SimpleNamespace(is_repeat_trial=False, answer=parent_answer),
        )
        for repeat_answer, parent_answer in zip(repeat_answers, parent_answers)
    ]

    return make_trial_maker(ConsistencyTrialMaker).performance_check(
        experiment=None,
        participant=DummyParticipant(),
        participant_trials=trials,
    )


@pytest.mark.parametrize(
    "repeat_answers, parent_answers",
    [
        ([1.0, 1.0, 1.0], [3.0, 5.0, 8.0]),
        ([3.0, 5.0, 8.0], [1.0, 1.0, 1.0]),
    ],
)
def test_always_giving_the_same_answer_fails_the_consistency_check(
    repeat_answers, parent_answers
):
    assert _check_consistency(repeat_answers, parent_answers) == {
        "score": None,
        "passed": False,
    }


def test_varying_answers_are_scored_by_their_correlation():
    assert _check_consistency([1.0, 2.0, 3.0], [7.0, 8.0, 9.0]) == {
        "score": 1.0,
        "passed": True,
    }


def test_removed_balance_flags_name_their_replacement():
    with pytest.raises(TypeError, match="chain_order='balanced'"):
        make_trial_maker(balance_across_chains=True)
    with pytest.raises(TypeError, match="node_order='random'"):
        make_static_trial_maker(balance_across_nodes=False)


@pytest.mark.parametrize(
    "node_order, message",
    [
        ({}, "every block"),
        ({"default": "random", "other": "random"}, "every block"),
        ("sorted", "node_order"),
        (None, "node_order"),
    ],
)
def test_invalid_node_orders_are_rejected(node_order, message):
    with pytest.raises((TypeError, ValueError), match=message):
        make_static_trial_maker(node_order=node_order)


def test_planned_order_cannot_be_combined_with_ranking_hooks():
    class RankingMaker(StaticTrialMaker):
        def select_node(self, nodes, participant, experiment):
            return nodes[-1]

    with pytest.raises(TypeError, match="select_node"):
        make_static_trial_maker(RankingMaker, node_order="listed")


def test_old_should_finish_block_signature_is_rejected():
    class OldFinishMaker(ChainTrialMaker):
        def should_finish_block(
            self,
            participant,
            block,
            block_position,
            n_participant_trials_in_block,
            n_participant_trials_in_trial_maker,
        ):
            return False

    with pytest.raises(TypeError, match=r"\(participant, block\)"):
        make_trial_maker(OldFinishMaker)

    class FlexibleFinishMaker(ChainTrialMaker):
        def should_finish_block(self, participant, block, **kwargs):
            return False

    make_trial_maker(FlexibleFinishMaker)


def test_choose_block_order_override_conflicts_with_block_order():
    class OrderedMaker(ChainTrialMaker):
        def choose_block_order(self, experiment, participant, blocks):
            return blocks

    with pytest.raises(TypeError, match="block_order"):
        make_trial_maker(OrderedMaker, block_order="listed")


def test_sequential_across_chains_need_revisiting():
    with pytest.raises(ValueError, match="interleave_chains=False"):
        make_trial_maker(interleave_chains=False)


def test_shuffle_with_max_run_limits_runs():
    items = ["a"] * 50 + ["b"] * 50
    for _ in range(20):
        shuffled = shuffle_with_max_run(items, key=str, max_run=1)
        assert sorted(shuffled) == items
        assert all(x != y for x, y in zip(shuffled, shuffled[1:]))
    with pytest.raises(ValueError, match="at most 1 consecutive"):
        shuffle_with_max_run(["a", "a", "a", "b"], key=str, max_run=1, max_attempts=10)


@pytest.mark.parametrize(
    "block_order, expected",
    [
        ("listed", ["B", "A", "C"]),
        (["C", "A"], ["C", "A"]),
        (lambda blocks: blocks[::-1], ["C", "A", "B"]),
        (lambda trial_maker: [trial_maker.id], ["B"]),
    ],
)
def test_block_order_settings(block_order, expected):
    trial_maker = make_trial_maker(block_order=block_order)
    trial_maker.id = "B"
    participant = DummyParticipant()

    trial_maker.init_block_order(SimpleNamespace(), participant, ["B", "A", "C"])

    assert participant.module_state.block_order == expected
    assert participant.module_state.block == expected[0]


@pytest.mark.parametrize("block_order", [["A", "Z"], ["A", "A"], lambda: []])
def test_invalid_block_orders_are_rejected(block_order):
    with pytest.raises(ValueError, match="non-empty list"):
        make_trial_maker(block_order=[])
    with pytest.raises(ValueError, match="does not have: \\['Z'\\]"):
        make_static_trial_maker(block_order=["default", "Z"])
    trial_maker = make_trial_maker(block_order=block_order)

    with pytest.raises(ValueError, match="block order"):
        trial_maker.init_block_order(SimpleNamespace(), DummyParticipant(), ["A", "B"])


def test_within_chains_skip_listed_blocks_the_participant_lacks():
    trial_maker = make_trial_maker(
        chain_type="within",
        chains_per_experiment=None,
        chains_per_participant=1,
        recruit_mode=None,
        block_order=["C", "Z", "A"],
    )
    participant = DummyParticipant()

    trial_maker.init_block_order(SimpleNamespace(), participant, ["A", "C"])

    assert participant.module_state.block_order == ["C", "A"]


def test_order_dict_may_cover_more_blocks_than_one_participant_has():
    trial_maker = make_trial_maker(chain_order={"A": "listed", "B": "random"})
    trial_maker._check_order_setting_blocks({"A"})
    with pytest.raises(ValueError, match="every block"):
        trial_maker._check_order_setting_blocks({"C"})


def test_order_function_arguments_are_checked_at_construction():
    with pytest.raises(TypeError, match="takes items"):
        make_static_trial_maker(node_order=lambda items: items)
    with pytest.raises(TypeError, match="takes nodes"):
        make_trial_maker(chain_order=lambda nodes: nodes)
    make_static_trial_maker(node_order=lambda participant, block, nodes: nodes)


def test_repeats_without_a_trial_limit_name_the_missing_argument():
    with pytest.raises(ValueError, match="max_trials_per_block"):
        make_static_trial_maker(
            allow_repeated_nodes=True, max_trials_per_participant=None
        )
