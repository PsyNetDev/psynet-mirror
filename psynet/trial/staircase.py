from statistics import mean
from typing import Literal, Optional, Type, Union

from sqlalchemy import Boolean, Column, Float, Integer, String

from ..field import PythonObject
from ..utils import get_args
from .chain import ChainNetwork, ChainNode, ChainTrial, ChainTrialMaker

# Overview #############################################################################################################

# This module provides classes for implementing a staircase procedure in which the difficulty of a task is adjusted
# based on the participant's performance. Specifically, a geometric staircase procedure is implemented
# (also known as a k-up-1-down procedure). In this procedure, the difficulty increases after a certain number (k) of
# consecutive correct responses, and decreases after an incorrect response. The procedure typically continues until a
# maximum number of reversals is reached. The mean of the reversals is then used as an estimate of the participant's
# threshold.
#
# See the staircase_pitch_discrimination demo for an example of how to use these classes.


class GeometricStaircaseNode(ChainNode):
    """
    Attributes
    ----------

    k : int
        The number of consecutive correct responses required to increase the difficulty.
        Defaults to 2, which corresponds to a 2-up-1-down procedure.

    parameter : object
        The parameter that determines the difficulty of the task.

    reversal : bool
        Whether the present node constitutes a 'reversal'. A reversal is a node where the difficulty changes direction.
        More formally, a node is a reversal if its parameter value was originally reached from one direction
        (e.g. ascending), but the parameter value of the next node changed in the opposite direction (e.g. descending).
        Reversals are often used for score estimation.

    n_prev_correct : int
        The number of consecutive correct responses that have already occurred at the same difficulty level
        in the immediate preceding nodes, not including the present node.

    n_prev_reversals : int
        The number of reversals that have occurred before (but not including) the present node.

    last_difficulty_change : str
        The direction of the last difficulty change, potentially including any difficulty change that produced
        the current node. Can be either "increase" or "decrease".
    """

    # k up 2 down procedure
    k = 2

    parameter = Column(PythonObject)
    reversal = Column(Boolean)
    n_prev_correct = Column(Integer)
    n_prev_reversals = Column(Integer)
    last_difficulty_change = Column(String)

    def __init__(self, *args, parameter=None, **kwargs):
        super().__init__(*args, **kwargs)

        self.check_methods()

        if self.network:
            assert self.network.chain_type == "within"

        parent = self.parent

        if self.degree == 0:
            assert parameter is not None
            self.parameter = parameter
            self.last_difficulty_change = None
            self.n_prev_reversals = 0
            self.n_prev_correct = 0
        else:
            assert parent is not None
            assert parent.trial.score in [0, 1]
            assert parent.n_prev_correct < self.k

            if parent.trial.score == 1:
                if parent.n_prev_correct + 1 == self.k:
                    self.parameter = self.increase_difficulty(parent.parameter)
                    self.last_difficulty_change = "increase"
                    self.n_prev_correct = 0
                else:
                    self.parameter = parent.parameter
                    self.last_difficulty_change = parent.last_difficulty_change
                    self.n_prev_correct = parent.n_prev_correct + 1
            else:
                self.parameter = self.decrease_difficulty(parent.parameter)
                self.last_difficulty_change = "decrease"
                self.n_prev_correct = 0

            if (
                parent.last_difficulty_change is not None
                and parent.last_difficulty_change != self.last_difficulty_change
            ):
                parent.reversal = True
                self.n_prev_reversals = parent.n_prev_reversals + 1
            else:
                parent.reversal = False
                self.n_prev_reversals = parent.n_prev_reversals

        if self.chain:
            if self.n_prev_reversals == self.chain.max_reversals_per_chain:
                self.chain.full = True

    def check_methods(self):
        for method in ["increase_difficulty", "decrease_difficulty"]:
            if not get_args(getattr(self, method)) == ["parameter"]:
                raise ValueError(
                    "In the current version of psynet.staircase, the increase_difficulty and decrease_difficulty "
                    "methods must take exactly one argument (the parameter value to be changed)."
                )

    def make_next_definition(self, experiment, participant):
        # To consider one day -- refactoring logic out of __init__ into make_next_definition
        return {}

    @property
    def definition(self):
        return {"parameter": self.parameter}

    def increase_difficulty(self, parameter):
        raise NotImplementedError()

    def decrease_difficulty(self, parameter):
        raise NotImplementedError()

    def create_seed(self, experiment, participant):
        return {}


class GeometricStaircaseTrial(ChainTrial):
    parameter = Column(PythonObject)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.parameter = self.node.parameter

    def make_definition(self, experiment, participant):
        return {"parameter": self.node.parameter}


class GeometricStaircaseChain(ChainNetwork):
    start_parameter = Column(PythonObject)
    max_reversals_per_chain = Column(Integer)
    mean_reversal_score = Column(Float)

    # By default, the first reversal is excluded from the score calculation.
    # This can be disabled by setting exclude_first_reversal to False.
    exclude_first_reversal = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.start_parameter = self.head.parameter
        self.max_reversals_per_chain = self.trial_maker.max_reversals_per_chain

    def compute_score(self):
        self.compute_reversal_score()

        # A possibility for the future:
        # implement more sophisticated scoring using the upndown R package via rpy2

    def compute_reversal_score(self):
        reversals = [node for node in self.alive_nodes if node.reversal]
        if self.exclude_first_reversal:
            reversals = reversals[1:]
        scores = [node.parameter for node in reversals]
        self.mean_reversal_score = self.summarize_scores(scores)

    def summarize_scores(self, scores):
        if len(scores) == 0:
            return None
        else:
            return mean(scores)


class GeometricStaircaseTrialMaker(ChainTrialMaker):
    @property
    def default_network_class(self):
        return GeometricStaircaseChain

    def __init__(
        self,
        *,
        id_,
        trial_class: Type[GeometricStaircaseTrial],
        node_class: Type[GeometricStaircaseNode],
        network_class: Type["GeometricStaircaseChain"] = None,
        start_nodes: Union[callable, list],
        max_nodes_per_chain: int,
        max_reversals_per_chain: Optional[int] = None,
        balance_across_chains: bool = False,
        min_passing_score: Optional[float] = None,
        max_passing_score: Optional[float] = None,
        expected_trials_per_participant: Optional[int | str] = None,
        max_trials_per_participant: Optional[int | str] = None,
        target_n_participants: Optional[int] = None,
        recruit_mode: str = "n_participants",
        assets=None,
        choose_participant_group: Optional[callable] = None,
        sync_group_type: Optional[str] = None,
        sync_group_max_wait_time: float = 45.0,
        sync_group_max_wait_action: Literal["fail", "kick"] = "fail",
        sync_group_timeout_between_barriers_time: Optional[float] = None,
        sync_group_timeout_between_barriers_action: Literal["kick", "fail"] = "fail",
    ):
        self.max_reversals_per_chain = max_reversals_per_chain
        self.min_passing_score = min_passing_score
        self.max_passing_score = max_passing_score

        super().__init__(
            id_=id_,
            trial_class=trial_class,
            node_class=node_class,
            network_class=network_class,
            chain_type="within",
            target_n_participants=target_n_participants,
            recruit_mode=recruit_mode,
            start_nodes=start_nodes,
            trials_per_node=1,
            expected_trials_per_participant=expected_trials_per_participant,
            max_trials_per_participant=max_trials_per_participant,
            assets=assets,
            choose_participant_group=choose_participant_group,
            sync_group_type=sync_group_type,
            sync_group_max_wait_time=sync_group_max_wait_time,
            sync_group_max_wait_action=sync_group_max_wait_action,
            sync_group_timeout_between_barriers_time=sync_group_timeout_between_barriers_time,
            sync_group_timeout_between_barriers_action=sync_group_timeout_between_barriers_action,
            max_nodes_per_chain=max_nodes_per_chain,
            check_performance_at_end=True,
            check_performance_every_trial=False,
            balance_across_chains=balance_across_chains,
        )

    # The current scoring method is to take the mean of the reversal scores.
    # In the future we might add support for other scoring methods,
    # which will be selected by setting the score_method attribute.
    score_method = "mean_reversal_score"

    def performance_check(self, experiment, participant, participant_trials):
        """Should return a dict: {"score": float, "passed": bool}"""
        chains = GeometricStaircaseChain.query.filter_by(
            participant=participant, trial_maker_id=self.id
        ).all()

        for chain in chains:
            chain.compute_score()

        try:
            chain_scores = [getattr(chain, self.score_method) for chain in chains]
        except AttributeError:
            raise ValueError(f"Unknown score method: {self.score_method}")

        score = self.summarize_scores(chain_scores)

        passed = True
        if score is None:
            passed = False
        if self.min_passing_score is not None and score < self.min_passing_score:
            passed = False
        if self.max_passing_score is not None and score > self.max_passing_score:
            passed = False

        return {
            "score": score,
            "passed": passed,
            "min_passing_score": self.min_passing_score,
            "max_passing_score": self.max_passing_score,
            "score_method": self.score_method,
            "chain_scores": chain_scores,
        }

    def summarize_scores(self, scores):
        scores = [score for score in scores if score is not None]
        if len(scores) == 0:
            return None
        else:
            return mean(scores)
