"""Scoring and results text of the public_goods demo when players leave or time out."""

from types import SimpleNamespace

import pytest

from psynet.experiment import import_local_experiment
from psynet.pytest_psynet import path_to_demo_experiment


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
            # A departed player is not in the pot: two players share it.
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
        [("stayed", 13.5), ("group_dissolved", 10), ("late", 0), ("removed", 0)],
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
