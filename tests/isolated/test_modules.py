import time
import uuid

import pytest
from dallinger import db

from psynet.experiment import get_experiment
from psynet.page import InfoPage
from psynet.participant import Participant
from psynet.pytest_psynet import path_to_test_experiment
from psynet.timeline import Module, Timeline
from psynet.trial.static import StaticNode, StaticTrial, StaticTrialMaker


def test_repeated_modules():
    with pytest.raises(
        ValueError,
        match="Duplicated module name detected: my-module",
    ):
        Timeline(
            Module("my-module", [InfoPage("My page", time_estimate=5)]),
            Module("my-module", [InfoPage("My page", time_estimate=5)]),
            Module("my-module-2", [InfoPage("My page", time_estimate=5)]),
            Module("my-module-2", [InfoPage("My page", time_estimate=5)]),
            Module("my-module-3", [InfoPage("My page", time_estimate=5)]),
        )


def get_random_id():
    return str(uuid.uuid4())


@pytest.mark.parametrize(
    "experiment_directory",
    [path_to_test_experiment("consents")],
    indirect=True,
)
def test_progress_info(in_experiment_directory, db_session):
    exp = get_experiment()

    module_ids = list(exp.timeline.modules.keys())

    hit_id = get_random_id()

    participants = []
    for _ in range(100):
        participant = Participant(
            experiment=exp,
            recruiter_id="hotair",
            worker_id=get_random_id(),
            hit_id=hit_id,
            assignment_id=get_random_id(),
            mode="debug",
        )
        db.session.add(participant)
        participants.append(participant)

    db.session.commit()

    main_consent = exp.timeline.modules["main_consent"]
    audiovisual_consent = exp.timeline.modules["audiovisual_consent"]

    for i, participant in enumerate(participants):
        main_consent.start(participant)
        main_consent.end(participant)

        if i < 50:
            audiovisual_consent.start(participant)

        if i < 25:
            audiovisual_consent.end(participant)

    db.session.commit()

    # Discard the first call. It pays one-off warm-up costs (notably reading
    # the config) that dwarf the queries under test: locally the first call
    # takes around 0.1 s while later calls take around 0.012 s. Timing the
    # cold call measured warm-up rather than dashboard query cost, and tipped
    # over the threshold on loaded CI runners.
    exp._get_progress_info(module_ids)

    start_time = time.monotonic()
    progress_info = exp._get_progress_info(module_ids)
    end_time = time.monotonic()

    time_taken = end_time - start_time

    assert time_taken < 0.5

    assert progress_info["main_consent"]["started_n_participants"] == 100
    assert progress_info["main_consent"]["finished_n_participants"] == 100

    assert progress_info["audiovisual_consent"]["started_n_participants"] == 50
    assert progress_info["audiovisual_consent"]["finished_n_participants"] == 25


def dummy_page():
    return InfoPage("Dummy content", time_estimate=5)


def dummy_node():
    return StaticNode(definition={"x": 0})


def test_nodes_in_multiple_modules():
    nodes = [dummy_node()]

    err = "Nodes cannot belong to multiple modules/trial makers. Please make a separate node list for each one."

    with pytest.raises(RuntimeError, match=err):
        module_1 = Module("module_1", dummy_page(), nodes=nodes)  # noqa
        module_2 = Module("module_2", dummy_page(), nodes=nodes)  # noqa


class CustomTrial(StaticTrial):
    time_estimate = 5


def test_nodes_in_multiple_trial_makers():
    nodes = [
        StaticNode(
            definition={"animal": "cat"},
        )
    ]

    err = "Nodes cannot belong to multiple modules/trial makers. Please make a separate node list for each one."

    with pytest.raises(RuntimeError, match=err):
        StaticTrialMaker(
            id_="animals",
            trial_class=CustomTrial,
            nodes=nodes,
            expected_trials_per_participant=6,
            max_trials_per_block=2,
            allow_repeated_nodes=True,
            balance_across_nodes=True,
            check_performance_at_end=False,
            check_performance_every_trial=False,
            target_n_participants=1,
            target_trials_per_node=None,
            recruit_mode="n_participants",
            n_repeat_trials=3,
        )

        StaticTrialMaker(
            id_="colors",
            trial_class=CustomTrial,
            nodes=nodes,
            expected_trials_per_participant=6,
            max_trials_per_block=2,
            allow_repeated_nodes=True,
            balance_across_nodes=True,
            check_performance_at_end=False,
            check_performance_every_trial=False,
            target_n_participants=1,
            target_trials_per_node=None,
            recruit_mode="n_participants",
            n_repeat_trials=3,
        )
