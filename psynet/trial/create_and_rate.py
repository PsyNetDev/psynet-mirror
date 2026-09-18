"""Create-and-rate trials for collecting and evaluating participant creations.

The trial-maker mixin specializes chain selection: each chain head first
receives creator trials, waits for those trials to finalize, and then receives
rater trials. Selection therefore operates on chains, while trial-class
resolution remains node-based after the selected chain is resolved to its head.
Experiments may optionally assign fixed participant roles; the mixin then uses
the same role for candidate eligibility and final trial-class validation.
Creators only receive heads that still need creators. Raters receive heads that
are ready for raters, and they wait (or exit) on heads whose creator slots are
filled but not yet finalized. Heads that still need creators are not
rater-eligible.
"""

import inspect
from random import sample

from dallinger import db
from dallinger.transformations import Transformation
from sqlalchemy import Column, func
from sqlalchemy.orm import declared_attr, deferred

from psynet.field import PythonObject
from psynet.trial import ChainNode
from psynet.trial.chain import ChainTrial
from psynet.trial.main import TrialMaker
from psynet.utils import get_logger

logger = get_logger()


class CreateAndRateAssignmentPending(Exception):
    """Raised when a selected head cannot receive a trial yet.

    Parameters
    ----------
    outcome
        ``"wait"`` or ``"exit"``, matching ``wait_for_networks``.
    """

    def __init__(self, outcome):
        if outcome not in ("wait", "exit"):
            raise ValueError("outcome must be 'wait' or 'exit'")
        super().__init__(outcome)
        self.outcome = outcome


def get_super_classes(cls):
    return inspect.getmro(cls)


def get_extended_class(obj):
    super_classes = get_super_classes(obj.__class__)
    mixin_class = super_classes[1]
    extended_class_idx = len(inspect.getmro(mixin_class))
    return super_classes[extended_class_idx]


def assert_correct_inheritance(sub_class, super_class):
    super_classes = get_super_classes(sub_class)
    assert len(super_classes) >= 3, "The class must inherit from at least two classes"
    error_msg = (
        "The mixin must be the first class you inherit from, for example:\n"
        "class CreateAndRateTrialMaker(CreateAndRateTrialMakerMixin, ImitationChainTrialMaker) would be correct and \n"
        "class CreateAndRateTrialMaker(ImitationChainTrialMaker, CreateAndRateTrialMakerMixin) would be incorrect."
    )
    assert super_classes[1] == super_class, error_msg


def filter_relevant_kwargs(kwargs, func):
    params = inspect.getfullargspec(func)
    keys = params.args + params.kwonlyargs
    return {key: kwargs[key] for key in keys if key in kwargs}


def get_required_parameters(func):
    inspected_function = inspect.getfullargspec(func)
    args = inspected_function.args + [
        arg
        for arg in inspected_function.kwonlyargs
        if arg not in inspected_function.kwonlydefaults
    ]
    args.remove("self")

    if inspected_function.defaults is None:
        return args
    else:
        return args[: -len(inspected_function.defaults)]


def split_kwargs(obj, kwargs, trial_maker_class, mixin_class):
    required_parameters = list(
        set(
            get_required_parameters(trial_maker_class.__init__)
            + get_required_parameters(obj.setup)
        )
    )
    for param in required_parameters:
        assert param in kwargs, f"Missing required parameter: {param}"
    trial_maker_kwargs = filter_relevant_kwargs(kwargs, trial_maker_class.__init__)
    mixin_kwargs = filter_relevant_kwargs(kwargs, mixin_class.setup)
    return trial_maker_kwargs, mixin_kwargs


class CreateAndRateTrialMixin(object):
    def __init__(self, experiment, node, participant, *args, **kwargs):
        trial_class = get_extended_class(self)
        assert issubclass(trial_class, ChainTrial), (
            "The trial class must inherit from ChainTrial"
        )
        super().__init__(experiment, node, participant, *args, **kwargs)
        trial_class.__init__(self, experiment, node, participant, *args, **kwargs)


class CreateTrialMixin(CreateAndRateTrialMixin):
    pass


class RateOrSelectTrialMixin(CreateAndRateTrialMixin):
    def __init__(self, experiment, node, participant, *args, **kwargs):
        super().__init__(experiment, node, participant, *args, **kwargs)
        self.targets = self.get_targets()
        self.register_transformations(self.targets)

    @declared_attr
    def targets(cls):
        # See the mixin section of https://docs.sqlalchemy.org/en/14/orm/inheritance.html#resolving-column-conflicts
        # return deferred(Column(PythonObject))
        return deferred(cls.__table__.c.get("targets", Column(PythonObject)))

    def register_transformations(self, targets):
        # Register the transformations
        for target in targets:
            if issubclass(target.__class__, ChainTrial):
                transformation = Transformation(info_out=self, info_in=target)
                db.session.add(transformation)
        db.session.commit()

    def get_targets(self):
        return self.get_all_targets()

    def get_all_targets(self):
        trial_maker = self.trial_maker
        shuffle = trial_maker.randomize_target_presentation_order
        assert issubclass(trial_maker.__class__, CreateAndRateTrialMakerMixin)
        creator_class = trial_maker.creator_class
        targets = creator_class.query.filter_by(
            node_id=self.node_id, failed=False, finalized=True
        ).all()
        if self.trial_maker.include_previous_iteration:
            targets += [self.node]
        if shuffle:
            targets = sample(targets, len(targets))
        return targets

    def get_target_answer(self, target):
        if issubclass(target.__class__, ChainNode):
            return target.definition
        elif issubclass(target.__class__, ChainTrial):
            return target.answer
        else:
            raise NotImplementedError()


class SelectTrialMixin(RateOrSelectTrialMixin):
    def get_targets(self):
        assert self.trial_maker.target_selection_method == "all"
        return self.get_all_targets()

    def format_answer(self, answer, **kwargs):
        rated_target_strs = [f"{target}" for target in self.targets]
        assert answer in rated_target_strs, (
            "The answer must be one of the rated target_strs"
        )
        return answer


class RateTrialMixin(RateOrSelectTrialMixin):
    def get_targets(self):
        target_selection_method = self.trial_maker.target_selection_method
        if target_selection_method == "all":
            return self.get_all_targets()
        elif target_selection_method == "one":
            return self.get_one_target()
        else:
            raise NotImplementedError(
                f"Unknown rated_targets value: {target_selection_method}"
            )

    def count_rated_targets(self, available_targets_str):
        rater_class = self.trial_maker.rater_class
        all_rating_trials = rater_class.query.filter_by(
            node_id=self.node_id, failed=False
        ).all()
        all_rating_trials = [
            trial for trial in all_rating_trials if trial.id != self.id
        ]
        all_rated_target_strs = [
            f"{target}" for rating in all_rating_trials for target in rating.targets
        ]
        target2count = dict(
            zip(available_targets_str, [0] * len(available_targets_str))
        )
        for target_str in all_rated_target_strs:
            target2count[target_str] += 1
        return target2count

    def select_target_with_least_ratings(self, all_targets):
        all_targets_str = [f"{target}" for target in all_targets]
        target2count = self.count_rated_targets(all_targets_str)

        min_count = min(target2count.values())
        targets_with_min_count = [
            target_str
            for target_str, count in target2count.items()
            if count == min_count
        ]

        target_str_with_least_ratings = sample(targets_with_min_count, 1)[0]

        if self.trial_maker.verbose:
            logger.info(
                f"For network {self.network.id} at iteration {self.node.degree} we have the following"
                + f" ratings for: {target2count}. We therefore selected: {target_str_with_least_ratings}."
            )

        target_idx = all_targets_str.index(target_str_with_least_ratings)
        return all_targets[target_idx]

    def get_one_target(self):
        return [self.select_target_with_least_ratings(self.get_all_targets())]

    def format_answer(self, answer, **kwargs):
        rated_target_strs = [f"{target}" for target in self.targets]
        if len(self.targets) > 1:
            assert type(answer) is list, "The answer must be a list of ratings"
            assert len(answer) == len(self.targets), (
                "The answer must have the same length as the number of targets"
            )
            assert all([type(rating) in [int, float] for rating in answer]), (
                "The answer must be a list of numbers"
            )
            answer = dict(zip(rated_target_strs, answer))
        else:
            if isinstance(answer, str):
                float_answer = float(answer)
                int_answer = int(answer)
                answer = float_answer if float_answer != int_answer else int_answer
            assert type(answer) in [int, float], "The answer must be a number"
            assert len(rated_target_strs) == 1
            answer = {rated_target_strs[0]: answer}
        return answer


class CreateAndRateNodeMixin(object):
    def __init__(self, **kwargs):
        extended_class = get_extended_class(self)
        assert issubclass(extended_class, ChainNode), (
            "The extended class must be a ChainNode"
        )
        extended_class.__init__(self, **kwargs)

    def get_str2target(self, rate_or_select_trials):
        all_targets = rate_or_select_trials[0].get_all_targets()
        return {f"{target}": target for target in all_targets}

    def summarize_rate_trials(self, rate_trials):
        import numpy as np

        str2target = self.get_str2target(rate_trials)
        all_target_strs = list(str2target.keys())
        rating_dict = {target_str: [] for target_str in all_target_strs}
        for rate_trial in rate_trials:
            for target_str, rating in rate_trial.answer.items():
                rating_dict[target_str] += [rating]
        mean_rating_dict = {
            target_str: np.mean(ratings) for target_str, ratings in rating_dict.items()
        }
        target_str_with_highest_rating = max(mean_rating_dict, key=mean_rating_dict.get)

        if self.trial_maker.verbose:
            logger.info(
                f"For network {self.network_id} at iteration {self.degree} we have the following"
                + f" ratings for: {mean_rating_dict}. We therefore selected: {target_str_with_highest_rating}."
            )
        return str2target[target_str_with_highest_rating]

    def summarize_select_trials(self, select_trials):
        str2target = self.get_str2target(select_trials)
        count_dict = {target_str: 0 for target_str in str2target.keys()}
        for trial in select_trials:
            count_dict[trial.answer] += 1
        target_str_with_highest_count = max(count_dict, key=count_dict.get)
        if self.trial_maker.verbose:
            logger.info(
                f"For network {self.network_id} at iteration {self.degree} we have the following"
                + f" ratings for: {count_dict}. We therefore selected: {target_str_with_highest_count}."
            )
        return str2target[target_str_with_highest_count]

    def summarize_trials(self, trials, experiment, participant):
        trial_maker = self.trial_maker
        all_rate_trials = trial_maker.rater_class.query.filter_by(
            node_id=self.id, failed=False, finalized=True
        ).all()

        rate_mode = trial_maker.rate_mode

        if rate_mode == "rate":
            return self.summarize_rate_trials(all_rate_trials)
        elif rate_mode == "select":
            return self.summarize_select_trials(all_rate_trials)
        else:
            raise NotImplementedError(f"Unknown rate_mode value: {rate_mode}")


class CreateAndRateNode(CreateAndRateNodeMixin, ChainNode):
    def create_initial_seed(self, experiment, participant):
        return {}

    def create_definition_from_seed(self, seed, experiment, participant):
        return seed


class CreateAndRateTrialMakerMixin(object):
    NEEDS_CREATORS = "needs_creators"
    WAITING_FOR_CREATORS = "waiting_for_creators"
    READY_FOR_RATERS = "ready_for_raters"
    CREATOR_ROLE = "creator"
    RATER_ROLE = "rater"

    def __init__(self, **kwargs):
        assert_correct_inheritance(self.__class__, CreateAndRateTrialMakerMixin)
        extended_class = get_extended_class(self)
        assert issubclass(extended_class, TrialMaker), (
            "The extended class must be a TrialMaker"
        )
        trial_maker_kwargs, mixin_kwargs = self.prepare_kwargs(
            kwargs, extended_class, CreateAndRateTrialMakerMixin
        )
        self.setup(**mixin_kwargs)
        extended_class.__init__(self, **trial_maker_kwargs)

    def assert_correct_inheritance_elements(self):
        def check_inheritance(clc, base_class, mixin_class):
            assert issubclass(clc, mixin_class)
            assert issubclass(clc, base_class)

        check_inheritance(self.node_class, ChainNode, CreateAndRateNodeMixin)
        check_inheritance(self.creator_class, ChainTrial, CreateTrialMixin)
        if self.rate_mode == "select":
            check_inheritance(self.rater_class, ChainTrial, SelectTrialMixin)
        elif self.rate_mode == "rate":
            check_inheritance(self.rater_class, ChainTrial, RateTrialMixin)
        else:
            raise NotImplementedError(f"Unknown rate_mode value: {self.rate_mode}")

    def setup(
        self,
        n_creators,
        n_raters,
        node_class,
        creator_class,
        rater_class,
        start_nodes,
        rate_mode="rate",
        include_previous_iteration=False,
        target_selection_method="one",
        randomize_target_order=True,
        verbose=False,
    ):
        # Set class variables
        self.n_creators = n_creators
        self.n_raters = n_raters
        self.rate_mode = rate_mode
        self.creator_class = creator_class
        self.rater_class = rater_class
        self.node_class = node_class
        self.include_previous_iteration = include_previous_iteration
        self.n_rate_stimuli = self.n_creators + int(self.include_previous_iteration)
        self.target_selection_method = target_selection_method
        self.randomize_target_presentation_order = randomize_target_order
        self.verbose = verbose

        # Assertions
        self.assert_is_positive_integer(n_creators)
        self.assert_is_positive_integer(n_raters)
        self.assert_correct_inheritance_elements()

        if self.include_previous_iteration:
            error_msg = (
                "If you want to include previous iterations, you need to specify the seed, e.g."
                " CreateAndRateNode(seed='My initial response shown to the participant')"
            )
            n_nodes_with_seed = sum(
                [node.seed is not None and len(node.seed) > 0 for node in start_nodes]
            )
            assert len(start_nodes) == n_nodes_with_seed, error_msg

        if self.rate_mode == "rate":
            if self.target_selection_method == "one":
                if self.include_previous_iteration:
                    error_msg = (
                        "n_raters must be a multiple of n_creators + 1 (since include_previous_iteration == "
                        "True) if rate_mode is 'rate' and target_selection_method is 'one'."
                    )
                else:
                    error_msg = (
                        "n_raters must be a multiple of n_creators if rate_mode is 'rate' and "
                        "target_selection_method is 'one'."
                    )
                assert self.n_raters % (self.n_rate_stimuli) == 0, error_msg
                self.n_rate_stimuli = 1
        elif self.rate_mode == "select":
            assert self.n_rate_stimuli > 1, (
                '`n_rate_stimuli` must be greater than 1 if `rate_mode` is "select"'
            )
        else:
            raise NotImplementedError(f"Unknown rate_mode value: {rate_mode}")

        assert target_selection_method in ["one", "all"]

    @staticmethod
    def assert_is_positive_integer(x):
        assert type(x) is int and x > 0, f"{x} must be a positive integer"

    def prepare_kwargs(self, kwargs, trial_maker_class, mixin_class):
        kwargs["trial_class"] = kwargs["creator_class"]
        kwargs["node_class"] = kwargs["node_class"]
        trial_maker_kwargs, mixin_kwargs = split_kwargs(
            self, kwargs, trial_maker_class, mixin_class
        )
        trials_per_node = kwargs["n_creators"] + kwargs["n_raters"]
        trial_maker_kwargs["trials_per_node"] = trials_per_node
        return trial_maker_kwargs, mixin_kwargs

    def prepare_trial(self, experiment, participant):
        try:
            return super().prepare_trial(experiment, participant)
        except CreateAndRateAssignmentPending as exc:
            logger.info(
                "Create-and-rate assignment deferred for participant %s: %s",
                getattr(participant, "id", participant),
                exc.outcome,
            )
            return None, exc.outcome

    def get_trial_class(self, node, participant, experiment):
        phase = self.get_creation_phases([node])[node.id]
        if phase == self.WAITING_FOR_CREATORS:
            self._defer_assignment()

        phase_role = self._role_for_phase(phase)
        participant_role = self._participant_role(participant, experiment)
        if participant_role is not None and participant_role != phase_role:
            self._defer_assignment()

        role = participant_role or phase_role
        return self.creator_class if role == self.CREATOR_ROLE else self.rater_class

    def get_participant_role(self, participant, experiment):
        """Return a fixed create-and-rate role, or ``None`` for phase-driven roles.

        Override this when participants must remain creators or raters. The
        returned role controls both chain eligibility and final trial-class
        validation. Creators are eligible only for ``NEEDS_CREATORS`` heads.
        Raters are eligible for ``READY_FOR_RATERS`` heads and for
        ``WAITING_FOR_CREATORS`` heads (so assignment can wait or exit until
        those heads become ratable). ``NEEDS_CREATORS`` heads are not
        rater-eligible.

        Returns
        -------
        str or None
            ``CREATOR_ROLE``, ``RATER_ROLE``, or ``None``.
        """
        return None

    def _participant_role(self, participant, experiment):
        role = self.get_participant_role(participant, experiment)
        if role not in (None, self.CREATOR_ROLE, self.RATER_ROLE):
            raise ValueError(
                "get_participant_role must return CREATOR_ROLE, RATER_ROLE, or None"
            )
        return role

    def _role_for_phase(self, phase):
        if phase == self.NEEDS_CREATORS:
            return self.CREATOR_ROLE
        if phase == self.READY_FOR_RATERS:
            return self.RATER_ROLE
        raise ValueError(f"Cannot assign a trial for create-and-rate phase {phase!r}")

    def _phase_matches_role(self, phase, role):
        if phase == self.WAITING_FOR_CREATORS:
            return role == self.RATER_ROLE
        return self._role_for_phase(phase) == role

    def _defer_assignment(self):
        raise CreateAndRateAssignmentPending(
            "wait" if self.wait_for_networks else "exit"
        )

    def _require_chain_heads(self, chains):
        """Raise if any chain is missing a head.

        A headless chain is a programming or data error, not an empty
        candidate list. Skipping it would hide the problem behind wait/exit.
        """
        headless_ids = [chain.id for chain in chains if chain.head is None]
        if headless_ids:
            raise RuntimeError(f"Create-and-rate chains have no head: {headless_ids}")

    def _filter_eligible_candidates(self, chains, participant, experiment):
        """Apply custom and role eligibility before availability checks.

        Headless chains raise before wait/exit, including phase-driven
        assignment where ``get_participant_role`` returns ``None``.
        """
        chains = super()._filter_eligible_candidates(
            chains,
            participant,
            experiment,
        )
        self._require_chain_heads(chains)
        participant_role = self._participant_role(participant, experiment)
        if participant_role is None:
            return chains

        phases = self.get_creation_phases([chain.head for chain in chains])
        return [
            chain
            for chain in chains
            if self._phase_matches_role(phases[chain.head.id], participant_role)
        ]

    def _creation_phase_from_counts(self, n_creations, n_finished_creations):
        if n_creations < self.n_creators:
            return self.NEEDS_CREATORS
        if n_finished_creations < n_creations:
            return self.WAITING_FOR_CREATORS
        return self.READY_FOR_RATERS

    def get_creation_phases(self, nodes):
        """Classify nodes using a constant number of database queries.

        Parameters
        ----------
        nodes
            Create-and-rate nodes to classify.

        Returns
        -------
        dict
            A mapping from node ID to ``NEEDS_CREATORS``,
            ``WAITING_FOR_CREATORS``, or ``READY_FOR_RATERS``.
        """
        node_ids = [node.id for node in nodes]
        if not node_ids:
            return {}

        def counts(finalized=None):
            query = db.session.query(
                self.creator_class.node_id,
                func.count(self.creator_class.id),
            ).filter(
                self.creator_class.node_id.in_(node_ids),
                self.creator_class.failed.is_(False),
            )
            if finalized is not None:
                query = query.filter(self.creator_class.finalized.is_(finalized))
            return dict(query.group_by(self.creator_class.node_id).all())

        creation_counts = counts()
        finished_creation_counts = counts(finalized=True)
        return {
            node.id: self._creation_phase_from_counts(
                creation_counts.get(node.id, 0),
                finished_creation_counts.get(node.id, 0),
            )
            for node in nodes
        }

    def find_chains(self, participant, experiment):
        chains = super().find_chains(participant, experiment)
        if isinstance(chains, str):
            return chains

        self._require_chain_heads(chains)
        phases = self.get_creation_phases([chain.head for chain in chains])
        classified = [(chain, phases[chain.head.id]) for chain in chains]
        assignable = [
            chain for chain, phase in classified if phase != self.WAITING_FOR_CREATORS
        ]
        if assignable:
            return assignable

        has_pending = any(phase == self.WAITING_FOR_CREATORS for _, phase in classified)
        if has_pending and self.wait_for_networks:
            return "wait"
        return "exit"

    def get_finished_creations(self, node):
        """Return the finalized, non-failed creator trials for a node."""
        return self.creator_class.query.filter_by(
            node_id=node.id, failed=False, finalized=True
        ).all()
