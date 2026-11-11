"""Scoring, results text and export of the public_goods demo when players leave or time out."""

import json
import uuid
from datetime import datetime
from types import SimpleNamespace

import pytest
from dallinger import db

from psynet.experiment import get_experiment, import_local_experiment
from psynet.participant import Participant
from psynet.pytest_psynet import path_to_demo_experiment
from psynet.sync import SimpleSyncGroup
from psynet.timeline import Module


def _trial(participant_id, answer, **attributes):
    return SimpleNamespace(
        participant_id=participant_id,
        answer=answer,
        var=SimpleNamespace(),
        **attributes,
    )


@pytest.mark.parametrize(
    "experiment_directory", [path_to_demo_experiment("public_goods")], indirect=True
)
@pytest.mark.usefixtures("in_experiment_directory")
class TestPublicGoods:
    @pytest.fixture
    def demo(self):
        return import_local_experiment()["module"]

    @pytest.mark.parametrize(
        "answers, n_left, share, payoffs",
        [
            # Two players played the round after a third left.
            ([10, 0], 1, 7.5, [7.5, 17.5]),
            # A player who ran out of time puts in nothing but still gets a share.
            ([4, 8, None], 0, 6, [12, 8, 16]),
            ([6, None], 1, 4.5, [8.5, 14.5]),
        ],
    )
    def test_the_pot_is_shared_between_the_players_of_the_round(
        self, demo, answers, n_left, share, payoffs
    ):
        trials = [_trial(i, answer) for i, answer in enumerate(answers)]
        node = SimpleNamespace(var=SimpleNamespace())
        demo.ContributionTrial.score_round(trials, node, left=[object()] * n_left)
        assert node.var.contributions == {str(i): a for i, a in enumerate(answers)}
        assert (node.var.share, node.var.n_left) == (share, n_left)
        assert [t.var.payoff for t in trials] == payoffs

    @pytest.mark.parametrize(
        "outcome, tokens",
        [
            ("stayed", 13.5),
            ("group_dissolved", 10),
            ("late", 0),
            ("removed_by_experimenter", 0),
        ],
    )
    def test_score_depends_on_how_the_round_ended(self, demo, outcome, tokens):
        trial = _trial(1, 2, sync_group_outcome=outcome)
        trial.var.payoff = 13.5
        assert demo.ContributionTrial.score_answer(trial, 2, None) == tokens

    @pytest.mark.parametrize(
        "answers, n_left, expected",
        [
            (
                [3, 2, 4],
                0,
                "The group put 9 tokens in the pot, which became 13.5 and was "
                "shared between 3 players: 4.5 tokens each. You put in 3, so you "
                "earned 11.5 tokens this round.",
            ),
            (
                [None, 9],
                1,
                "One player has left the group. The group put 9 tokens in the "
                "pot, which became 13.5 and was shared between 2 players: 6.75 "
                "tokens each. You ran out of time and put in nothing, so you "
                "earned 16.75 tokens this round.",
            ),
        ],
    )
    def test_results_text(self, demo, answers, n_left, expected):
        node = SimpleNamespace(var=SimpleNamespace())
        trials = [
            _trial(i, a, node=node, time_limit_reached=a is None, sync_group=None)
            for i, a in enumerate(answers)
        ]
        demo.ContributionTrial.score_round(trials, node, left=[object()] * n_left)
        page = demo.ContributionTrial.show_feedback(
            trials[0], None, SimpleNamespace(id=0)
        )
        assert page.prompt.text == expected

    def test_export_of_a_cancelled_round_is_json(self, demo, db_session):
        exp = get_experiment()
        members = [
            Participant(
                experiment=exp,
                recruiter_id="hotair",
                worker_id=str(uuid.uuid4()),
                hit_id="XYZ",
                assignment_id=str(uuid.uuid4()),
                mode="debug",
            )
            for _ in range(3)
        ]
        group = SimpleSyncGroup(
            group_type=demo.GROUP,
            initial_group_size=3,
            min_group_size=2,
            n_active_participants=3,
            accepts_top_ups=False,
        )
        db.session.add_all([*members, group])
        for participant in members:
            participant.status = "working"
            group.add_participant(participant)
            participant.start_module(Module("game", []))
        db.session.commit()
        for participant in members:
            demo.ContributionTrial.cue(round=0)[0].consume(exp, participant)
        group.remove_participant(members[0], reason="late")
        group.remove_participant(members[1], reason="late")
        db.session.commit()

        (team,) = json.loads(json.dumps(demo.Exp.get_basic_data()))["team_round"]
        assert datetime.fromisoformat(team["dissolved_at"])
