from __future__ import (  # Makes type hints lazy, so that classes can be defined in arbitrary order
    annotations,
)

import random
from typing import List, Literal, Optional

from ..utils import sample_from_surface_of_unit_sphere
from .static import StaticNode, StaticTrial, StaticTrialMaker


class DenseTrialMaker(StaticTrialMaker):
    """
    This is a trial maker for 'dense' experiment paradigms.
    A 'dense' paradigm is one where we have a continuous stimulus space
    parametrized by a finite number of dimensions,
    for example color which can be parametrized by R, G, and B values.
    The experiment then works by densely sampling stimuli from this space.

    The trial maker class is paired with a particular :class:`~psynet.trial.dense.DenseTrial` class.
    This :class:`~psynet.trial.dense.DenseTrial` class is important for determining the precise nature
    of the dense experiment paradigm.
    If each trial corresponds to a random sample from the stimulus space --
    for example, in a dense rating experiment --
    we would use the :class:`~psynet.trial.dense.SingleStimulusTrial` class.
    More complex trial classes are available that involve multiple locations in the stimulus space,
    for example
    :class:`~psynet.trial.dense.SameDifferentTrial` for same-different paradigms and
    :class:`~psynet.trial.dense.AXBTrial` for AXB paradigms.

    The user must also specify a
    :class:`~psynet.trial.dense.ConditionList`, which contains a list of
    :class:`~psynet.trial.dense.DenseNode` objects.
    These different :class:`~psynet.trial.dense.DenseNode` objects are used for specifying the different
    classes of stimuli seen by the participant.
    A given participant will typically receive trials from a variety of Conditions over the course of the trial maker.
    By default, the different Conditions will be randomly interspersed with one another;
    however, it is also possible to assign different Conditions to different blocks,
    so as to constrain the order of their presentation to the participant.

    The user may also override the following methods, if desired:

    * :meth:`~psynet.trial.dense.DenseTrialMaker.choose_block_order`;
      chooses the order of blocks in the experiment.
      By default the blocks are ordered randomly.

    * :meth:`~psynet.trial.dense.DenseTrialMaker.choose_participant_group`;
        only relevant if the trial maker uses nodes with non-default participant groups.
        In this case the experimenter is expected to supply a function that takes participant as an argument
        and returns the chosen participant group for that trial maker.
        For example, to randomly assign participants to one of two groups called g1 and g2, one could write::

            choose_participant_group=lambda(participant): random.choice(["g1", "g2"])

        Similarly, to alternate participants between two groups, one could write::

            choose_participant_group=lambda(participant): ["g1", "g2"][participant.id % 2]

    * :meth:`~psynet.trial.main.TrialMaker.on_complete`,
      run once the sequence of trials is complete.

    * :meth:`~psynet.trial.main.TrialMaker.performance_check`;
      checks the performance of the participant
      with a view to rejecting poor-performing participants.

    * :meth:`~psynet.trial.main.TrialMaker.compute_performance_reward`;
      computes the final performance reward to assign to the participant.

    Further customisable options are available in the constructor's parameter list,
    documented below.

    Parameters
    ----------

    id_
        A unique ID for the trial maker.

    trial_class
        The class object for trials administered by this maker
        (should subclass :class:`~psynet.trial.dense.DenseTrial`).

    conditions
        Defines a collection of conditions to be administered to the participants.

    recruit_mode
        Selects a recruitment criterion for determining whether to recruit
        another participant. The built-in criteria are ``"n_participants"``
        and ``"n_trials"``.

    target_n_participants
        Target number of participants to recruit for the experiment. All
        participants must successfully finish the experiment to count
        towards this quota. This target is only relevant if
        ``recruit_mode="n_participants"``.

    max_trials_per_block
        Determines the maximum number of trials that a participant will be allowed to experience in each block,
        including failed trials. Note that this number does not include repeat trials.

    expected_trials_per_participant
        Expected number of trials that each participant will complete.
        This is used for timeline/progress estimation purposes.
        This can either be an integer, or the string ``"n_nodes"``,
        which will be read as referring to the number of nodes in ``start_nodes``.

    max_trials_per_participant
        Maximum number of trials that each participant may complete (optional);
        once this number is reached, the participant will move on
        to the next stage in the timeline.

    balance_across_nodes
        If ``True`` (default), active balancing across participants is enabled, meaning that
        node selection favours nodes that have been presented fewest times to any participant
        in the experiment, excluding failed trials.

    check_performance_at_end
        If ``True``, the participant's performance
        is evaluated at the end of the series of trials.
        Defaults to ``False``.
        See :meth:`~psynet.trial.main.TrialMaker.performance_check`
        for implementing performance checks.

    check_performance_every_trial
        If ``True``, the participant's performance
        is evaluated after each trial.
        Defaults to ``False``.
        See :meth:`~psynet.trial.main.TrialMaker.performance_check`
        for implementing performance checks.

    fail_trials_on_premature_exit
        See :class:`~psynet.trial.main.TrialMaker`.

    fail_trials_on_participant_performance_check
        See :class:`~psynet.trial.main.TrialMaker`. Defaults to ``True``.

    n_repeat_trials
        Number of repeat trials to present to the participant. These trials
        are typically used to estimate the reliability of the participant's
        responses. Repeat trials are presented at the end of the trial maker,
        after all blocks have been completed.
        Defaults to ``0``.

    Attributes
    ----------

    check_timeout_interval_sec : float
        How often to check for trials that have timed out, in seconds (default = 30).
        Users are invited to override this.

    response_timeout_sec : float
        How long until a trial's response times out, in seconds (default = 60)
        (i.e. how long PsyNet will wait for the participant's response to a trial).
        This is a lower bound on the actual timeout
        time, which depends on when the timeout daemon next runs,
        which in turn depends on :attr:`~psynet.trial.main.TrialMaker.check_timeout_interval_sec`.
        Users are invited to override this.

    async_timeout_sec : float
        How long until an async process times out, in seconds (default = 300).
        This is a lower bound on the actual timeout
        time, which depends on when the timeout daemon next runs,
        which in turn depends on :attr:`~psynet.trial.main.TrialMaker.check_timeout_interval_sec`.
        Users are invited to override this.

    network_query : sqlalchemy.orm.Query
        An SQLAlchemy query for retrieving all networks owned by the current trial maker.
        Can be used for operations such as the following: ``self.network_query.count()``.

    n_networks : int
        Returns the number of networks owned by the trial maker.

    networks : list
        Returns the networks owned by the trial maker.

    performance_threshold : float
        Score threshold used by the default performance check method, defaults to 0.0.
        By default, corresponds to the minimum proportion of non-failed trials that
        the participant must achieve to pass the performance check.
        Override this to change the behavior.

    end_performance_check_waits : bool
        If ``True`` (default), then the final performance check waits until all trials no
        longer have any pending asynchronous processes.
    """

    def __init__(
        self,
        *,
        id_: str,
        trial_class,
        conditions: "List[DenseNode]",
        expected_trials_per_participant: int | str,
        max_trials_per_participant: Optional[int | str] = None,
        max_trials_per_block: Optional[int] = None,
        recruit_mode: Optional[str] = None,
        target_n_participants: Optional[int] = None,
        target_trials_per_condition: Optional[int] = None,
        balance_across_nodes: bool = True,
        check_performance_at_end: bool = False,
        check_performance_every_trial: bool = False,
        fail_trials_on_premature_exit: bool = False,
        fail_trials_on_participant_performance_check: bool = True,
        n_repeat_trials: int = 0,
        sync_group_type: Optional[str] = None,
        sync_group_max_wait_time: float = 45.0,
        sync_group_max_wait_action: Literal["fail", "kick"] = "fail",
        sync_group_timeout_between_barriers_time: Optional[float] = None,
        sync_group_timeout_between_barriers_action: Literal["kick", "fail"] = "fail",
    ):
        super().__init__(
            id_=id_,
            trial_class=trial_class,
            nodes=conditions,
            recruit_mode=recruit_mode,
            expected_trials_per_participant=expected_trials_per_participant,
            max_trials_per_participant=max_trials_per_participant,
            target_n_participants=target_n_participants,
            target_trials_per_node=target_trials_per_condition,
            max_trials_per_block=max_trials_per_block,
            allow_repeated_nodes=True,
            check_performance_at_end=check_performance_at_end,
            check_performance_every_trial=check_performance_every_trial,
            fail_trials_on_premature_exit=fail_trials_on_premature_exit,
            fail_trials_on_participant_performance_check=fail_trials_on_participant_performance_check,
            n_repeat_trials=n_repeat_trials,
            balance_across_nodes=balance_across_nodes,
            sync_group_type=sync_group_type,
            sync_group_max_wait_time=sync_group_max_wait_time,
            sync_group_max_wait_action=sync_group_max_wait_action,
            sync_group_timeout_between_barriers_time=sync_group_timeout_between_barriers_time,
            sync_group_timeout_between_barriers_action=sync_group_timeout_between_barriers_action,
        )


class DenseNode(StaticNode):
    """
    Defines a DenseNode within the dense experiment paradigm.

    definition
        A dictionary defining the key attributes of the DenseNode.
        The values in this dictionary will be propagated to the dictionary attribute
        of the resulting :class:`~psynet.trial.dense.DenseTrial` objects,
        and can be used to customize the display of these items
        (e.g., changing the instructions to the participant).
        Crucially, this dictionary must contain an item called "dimensions",
        corresponding to a list of :class:`~psynet.trial.dense.Dimension` objects
        which combine to define the stimulus space.

    participant_group
        The associated participant group.
        Defaults to a common participant group for all participants.

    block
        The associated block.
        Defaults to a single block for all trials.
        Use this in combination with :meth:`~psynet.trial.dense.DenseTrialMaker.choose_block_order`
        to manipulate the order in which Conditions are presented to participants.
    """

    def __init__(
        self,
        definition: dict,
        participant_group="default",
        block="default",
    ):
        assert "dimensions" in definition
        super().__init__(
            definition=definition,
            participant_group=participant_group,
            block=block,
        )


class Dimension(dict):
    """
    Defines a dimension of the stimulus space.

    label
        Label for the dimension.

    min_value
        Minimum value that the dimension can take (in this experiment).

    max_value
        Maximum value that the dimension can take (in this experiment).

    scale
        Indicates the relative scale of a dimension as compared to other dimensions.
        This is relevant for certain classes of dense experiment,
        for example same-different paradigms;
        doubling the scale parameter means that the perturbations will be twice as big
        along the specified dimension as compared to the other dimensions.
        Defaults to ``1.0``.
    """

    def __init__(self, label: str, min_value, max_value, scale: float = 1.0):
        super().__init__(
            label=label,
            min_value=min_value,
            max_value=max_value,
            scale=scale,
        )


class DenseTrial(StaticTrial):
    """
    This trial class is important for defining the behavior of the dense experiment.
    Ordinarily one will not use this class directly, but will instead use one of the
    built-in subclasses, for example
    :class:`~psynet.trial.dense.SingleStimulusTrial`,
    :class:`~psynet.trial.dense.SliderCopyTrial`,
    :class:`~psynet.trial.dense.PairedStimulusTrial`,
    :class:`~psynet.trial.dense.SameDifferentTrial`, or
    :class:`~psynet.trial.dense.AXBTrial`.

    Parameters
    ----------

    condition
        The :class:`~psynet.trial.dense.DenseNode` object to which the trial belongs.

    n_dimensions
        The number of dimensions of the stimulus space.
    """

    @property
    def condition(self):
        return self.node

    @property
    def n_dimensions(self):
        dimensions = self.get_from_definition(self.definition, "dimensions")
        return len(dimensions)

    def sample_from_dimension(self, dim):
        return random.uniform(dim["min_value"], dim["max_value"])

    def sample_location(self, dimensions, definition):
        return [self.sample_from_dimension(dim) for dim in dimensions]

    def within_bounds(self, location, dimensions, definition):
        for loc, dim in zip(location, dimensions):
            if not (dim["min_value"] <= loc <= dim["max_value"]):
                return False
        return True

    def sample_perturbation(self, dimensions, delta):
        n_dimensions = len(dimensions)

        raw_sample = sample_from_surface_of_unit_sphere(n_dimensions)
        scaled_sample = [
            raw * dim["scale"] * delta for raw, dim in zip(raw_sample, dimensions)
        ]
        return scaled_sample

    def save_in_definition(self, definition, key, value):
        if key in definition:
            raise ValueError(
                f"'{key}' is a protected key in {self.__class__.__name__}, please rename this key to something else."
            )
        definition[key] = value

    def get_from_definition(self, definition, key):
        try:
            return definition[key]
        except KeyError as e:
            if key == "dimensions":
                raise e
            raise KeyError(
                f"{self.__class__.__name__} requires '{key}' to be specified in each DenseNode object."
            )


class SingleStimulusTrial(DenseTrial):
    """
    Defines a paradigm where each stimulus corresponds to a randomly sampled
    location from the stimulus space.
    The user is responsible for implementing :meth:`~psynet.trial.main.Trial.show_trial`,
    which determines how the trial is turned into a webpage for presentation to the participant.
    This method should make use of the following automatically generated entries within the Trial's
    ``definition`` attribute:

    location:
        A list of numbers defining the stimulus's position within the stimulus space.
    """

    def finalize_definition(self, definition, experiment, participant):
        dimensions = self.get_from_definition(definition, "dimensions")
        location = self.sample_location(dimensions, definition)
        self.save_in_definition(definition, "location", location)
        return definition

    def show_trial(self, experiment, participant):
        raise NotImplementedError


class SliderCopyTrial(SingleStimulusTrial):
    """
    Defines a paradigm where each trial corresponds to a random location in the stimulus space;
    the participant is presented with a stimulus corresponding to that location,
    and they must then copy that stimulus using a slider.
    The slider is associated with a randomly chosen dimension of the stimulus
    (specified by the randomly generated ``active_index`` property of the Trial)
    and moving that slider changes the stimulus along that dimension.
    The participant must move that slider until they believe that they have reproduced
    the original stimulus.

    This paradigm requires the user to specify several special parameters within each
    :class:`~psynet.trial.dense.DenseNode` object:

    * ``slider_width``, a number determining the width of the region of the stimulus space that the slider covers;
    * ``slider_jitter``, a number determining the amount of jitter applied to the slider's location;
      the slider will be jittered according to a uniform distribution ranging from
      ``- slider_jitter`` to ``+ slider_jitter``.
    * ``allow_slider_outside_range``, a Boolean determining whether the slider jitter is allowed to take
      the slider outside the range specified by the relevant :class:`~psynet.trial.dense.Dimension` object``.

    The user is responsible for implementing an appropriate :meth:`~psynet.trial.main.Trial.show_trial` method,
    which should make use of the following automatically generated entries within the Trial's
    ``definition`` attribute:

    location:
        A list of numbers defining the stimulus's position within the stimulus space.

    active_index:
        An integer identifying which of the dimensions should be linked with the slider (0-indexed).

    slider_range
        A pair of numbers identifying the minimum and maximum points of the slider,
        expressed in the units of the Dimension currently being manipulated.

    slider_start_value
        The (randomly generated) starting value of the slider.

    The class contains a built-in :meth:`~psynet.trial.dense.SliderCopyTrial.score_answer` method
    which returns the absolute distance between the true stimulus location and the stimulus location
    chosen by the participant. The resulting score is stored in the trial's ``score`` attribute,
    and can be used for performance rewards.
    """

    def finalize_definition(self, definition, experiment, participant):
        dimensions = self.get_from_definition(definition, "dimensions")
        location = self.get_from_definition(definition, "location")
        slider_width = self.get_from_definition(definition, "slider_width")
        slider_jitter = self.get_from_definition(definition, "slider_jitter")
        allow_slider_outside_range = self.get_from_definition(
            definition, "allow_slider_outside_range"
        )

        if slider_jitter > slider_width / 2:
            raise ValueError(
                "'slider_jitter' must not be greater than slider_width / 2."
            )

        active_index = random.randrange(len(dimensions))

        slider_range = self.sample_slider_range(
            dimensions[active_index],
            location[active_index],
            slider_width,
            slider_jitter,
            allow_slider_outside_range,
        )

        slider_start_value = random.uniform(*slider_range)

        self.save_in_definition(definition, "active_index", active_index)
        self.save_in_definition(definition, "slider_range", slider_range)
        self.save_in_definition(definition, "slider_start_value", slider_start_value)

        return definition

    @staticmethod
    def sample_slider_range(
        dimension, target_value, slider_width, slider_jitter, allow_slider_outside_range
    ):
        scale = dimension["scale"]
        min_value = dimension["min_value"]
        max_value = dimension["max_value"]

        rescaled_slider_width = slider_width * scale
        rescaled_slider_jitter = slider_jitter * scale

        unjittered_slider_bottom = target_value - rescaled_slider_width / 2
        unjittered_slider_top = target_value + rescaled_slider_width / 2

        if allow_slider_outside_range:
            jitter_min = -rescaled_slider_jitter
            jitter_max = +rescaled_slider_jitter
        else:
            # The lowest possible jitter value happens when the slider touches the bottom of the range:
            # unjittered_slider_bottom + jitter_min = min_value
            # => jitter_min = min_value - unjittered_slider_bottom
            jitter_min = max(
                -rescaled_slider_jitter, min_value - unjittered_slider_bottom
            )

            # The highest possible jitter value happens when the slider touches the top of the range:
            # unjittered_slider_top + jitter_max = max_value
            # => jitter_max = max_value - unjittered_slider_top
            jitter_max = min(rescaled_slider_jitter, max_value - unjittered_slider_top)

        jitter = random.uniform(jitter_min, jitter_max)
        slider_bottom = unjittered_slider_bottom + jitter
        slider_top = unjittered_slider_top + jitter

        return [slider_bottom, slider_top]

    def score_answer(self, answer, definition):
        location = self.get_from_definition(definition, "location")
        active_index = self.get_from_definition(definition, "active_index")
        target_value = location[active_index]
        actual_value = float(answer)
        return abs(target_value - actual_value)


class PairedStimulusTrial(DenseTrial):
    """
    Defines a paradigm where each trial corresponds to a pair of locations in stimulus space.
    Most users will not use this class directly, but will instead use one of the following subclasses:

    * :class:`~psynet.trial.dense.SameDifferentTrial`
    * :class:`~psynet.trial.dense.AXBTrial`

    There are several ways in which one might sample pairs of locations from a stimulus space.
    The present method may be summarised as follows:

        * Sample the 'original' stimulus uniformly from the stimulus space.
        * Sample the 'altered' stimulus randomly from the stimulus space with the constraint that
          it must be exactly ``delta`` units distant from the 'original' stimulus.

    We also considered a slight modification of the above, not implemented here, where the 'original' stimulus
    is constrained such that no dimension is less than delta units away from a boundary value.

    The ``delta`` parameter must be provided as one of the items within the :class:`~psynet.trial.dense.DenseNode`
    object's definition attribute.
    One can achieve different perturbation sizes for different Dimensions by manipulating the ``scale`` attribute
    of the Dimension objects.
    """

    def finalize_definition(self, definition, experiment, participant):
        dimensions = self.get_from_definition(definition, "dimensions")
        delta = self.get_from_definition(definition, "delta")
        locations = self.sample_location_pair(dimensions, delta, definition)
        self.save_in_definition(definition, "locations", locations)
        return definition

    def sample_location_pair(self, dimensions, delta, definition, max_try=1e6):
        original = self.sample_location(dimensions, definition)
        counter = 0
        while counter < max_try:
            perturbation = self.sample_perturbation(dimensions, delta)
            altered = [sum(x) for x in zip(original, perturbation)]
            if self.within_bounds(
                altered, dimensions, definition
            ) and self.is_valid_location_pair(definition, original, altered):
                return {
                    "original": original,
                    "altered": altered,
                }
            counter += 1
        raise RuntimeError(
            f"Could not find a valid alteration for original location = {original}, delta = {delta}."
        )

    # This method can be customized to introduce additional constraints on what constitutes a valid location pair.
    def is_valid_location_pair(self, definition, original, altered):
        return True

    # To be overridden by subclasses
    valid_answers = []

    def score_answer(self, answer, definition):
        """
        Returns 1 if the participant answers correctly, 0 otherwise.
        """
        assert answer in self.valid_answers
        correct_answer = self.get_from_definition(definition, "correct_answer")
        return int(answer == correct_answer)

    def show_trial(self, experiment, participant):
        raise NotImplementedError


class SameDifferentTrial(PairedStimulusTrial):
    """
    Defines a same-different paradigm.
    Each trial comprises a pair of stimuli located in a random region of the stimulus space.
    These two stimuli may either be "same" or "different".
    In the latter case, the two stimuli are separated by a distance of ``delta`` in the stimulus space,
    where ``delta`` is defined within the :class:`~psynet.trial.dense.DenseNode` object's definition dictionary.

    The user is responsible for implementing an appropriate :meth:`~psynet.trial.main.Trial.show_trial` method,
    which should make use of the following automatically generated entries within the Trial's
    ``definition`` attribute:

    locations:
        A dictionary of the form ``{"original": [a, b], "altered": [c, d]}``,
        providing the locations of the original and the altered stimuli respectively.

    order:
        A list providing the order of the original and altered stimuli.
        Valid values are:
        * ["original", "original"]
        * ["altered", "same"]
        * ["same", "altered"]
        These values can be used to index into ``locations`` to find the stimuli to present
        in the appropriate order.

    correct_answer:
        The correct answer; will be either ``same`` or ``different``.

    The :meth:`~psynet.trial.main.Trial.show_trial` method should return either ``same`` or ``different``
    as the answer.
    """

    valid_answers = ["same", "different"]

    def finalize_definition(self, definition, experiment, participant):
        correct_answer = random.choice(["same", "different"])

        if correct_answer == "same":
            order = ["original", "original"]
        elif correct_answer == "different":
            order = random.sample(["original", "altered"], k=2)
        else:
            raise RuntimeError("This shouldn't happen.")

        self.save_in_definition(definition, "correct_answer", correct_answer)
        self.save_in_definition(definition, "order", order)

        return definition

    def show_trial(self, experiment, participant):
        raise NotImplementedError


class AXBTrial(PairedStimulusTrial):
    """
    Defines an AXB paradigm.
    Each trial is built from a pair of stimuli located in a random region of the stimulus space.
    These stimuli are designated "original" and "altered" respectively,
    and are always separated by a distance of ``delta`` in the stimulus space,
    where ``delta`` is defined within the :class:`~psynet.trial.dense.DenseNode` object's definition dictionary.

    Each trial in an AXB paradigm takes one of two forms, "AAB" or "ABB",
    where the forms dictate the order of presentation of the stimuli,
    specifically their repetition structure.
    Put explicitly, "AAB" means the participant hears the same stimulus twice followed by a different stimulus,
    whereas "ABB" means that the participant hears one stimulus once followed by a different stimulus
    which is then repeated.
    If "A" is the "original" stimulus, then "B" will be the "altered" stimulus;
    however, it is equivalently possible for
    "A" to be the "altered" stimulus, in which case "B" will then be the "original" stimulus.

    The user is responsible for implementing an appropriate :meth:`~psynet.trial.main.Trial.show_trial` method,
    which should make use of the following automatically generated entries within the Trial's
    ``definition`` attribute:

    locations:
        A dictionary of the form ``{"original": [a, b], "altered": [c, d]}``,
        providing the locations of the original and the altered stimuli respectively.

    order:
        A list providing the order of the original and altered stimuli.
        Valid values are:
        * ["original", "original", "altered"] (here, the correct answer would be "AAB")
        * ["altered", "altered", "original"] (here, the correct answer would be "AAB")
        * ["original", "altered", "altered"] (here, the correct answer would be "ABB")
        * ["altered", "original", "original"] (here, the correct answer would be "ABB")

    correct_answer:
        The correct answer; will be either ``AAB`` or ``ABB``.

    The :meth:`~psynet.trial.main.Trial.show_trial` method should return either ``AAB`` or ``ABB``
    as the answer.
    """

    valid_answers = ["AAB", "ABB"]

    def finalize_definition(self, definition, experiment, participant):
        correct_answer = random.choice(["AAB", "ABB"])
        a, b = random.sample(["original", "altered"], k=2)

        if correct_answer == "AAB":
            order = [a, a, b]
        elif correct_answer == "ABB":
            order = [a, b, b]
        else:
            raise RuntimeError("This shouldn't happen.")

        self.save_in_definition(definition, "correct_answer", correct_answer)
        self.save_in_definition(definition, "order", order)

        return definition

    def show_trial(self, experiment, participant):
        raise NotImplementedError
