# pylint: disable=unused-argument,abstract-method

import random
from statistics import mean, median

from sqlalchemy import Column
from sqlalchemy.orm import declared_attr, deferred

from psynet.field import _PythonList

from ..utils import get_logger
from .chain import ChainNetwork, ChainNode, ChainTrial, ChainTrialMaker

logger = get_logger()


class GibbsNetwork(ChainNetwork):
    """
    A Network class for Gibbs sampler chains.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        trial_maker = self.trial_maker
        vector_length = trial_maker.node_class.vector_length
        dimension_order = list(range(vector_length))
        if trial_maker.randomize_dimension_order_per_network:
            random.shuffle(dimension_order)
        self.dimension_order = dimension_order

    @declared_attr
    def dimension_order(cls):
        return deferred(cls.__table__.c.get("dimension_order", Column(_PythonList)))

    def make_definition(self):
        return {}


class GibbsTrial(ChainTrial):
    """
    A Trial class for Gibbs sampler chains.

    Attributes
    ----------

    resample_free_parameter : bool
        If ``True`` (default), the starting value of the free parameter
        is resampled on each trial. Disable this behaviour
        by setting this parameter to ``False`` in the definition of
        the custom :class:`~psynet.trial.gibbs.GibbsTrial` class.

    initial_vector : list
        The starting vector that is presented to the participant
        at the beginning of the trial.

    initial_index : int
        The initial index of the parameter that the participant manipulates
        on the first trial.

    active_index : int
        The index of the parameter that the participant manipulates
        on this trial.

    reverse_scale : bool
        Whether the response scale should be reversed.
        This reversal should be implemented on the front-end,
        with the correct numbers still being reported to the back-end.

    updated_vector : list
        The updated vector after the participant has responded.
    """

    resample_free_parameter = True

    def choose_reverse_scale(self):
        return bool(random.randint(0, 1))

    def make_definition(self, experiment, participant):
        """
        In the Gibbs sampler, a trial's definition is created by taking the
        definition from the source
        :class:`~psynet.trial.gibbs.GibbsNode`,
        modifying it such that the free parameter has a randomised
        starting value, and adding a randomised Boolean determining whether the
        corresponding slider (or similar) has its direction reversed.
        Note that different trials at the same
        :class:`~psynet.trial.gibbs.GibbsNode` will have the same
        free parameters but different starting values for those free parameters.

        Parameters
        ----------

        experiment
            An instantiation of :class:`psynet.experiment.Experiment`,
            corresponding to the current experiment.

        participant
            Optional participant with which to associate the trial.

        Returns
        -------

        object
            The trial's definition, equal to the node's definition
            with the free parameter randomised.

        """
        vector = self.node.definition["vector"].copy()
        initial_index = self.node.definition["initial_index"]
        active_index = self.node.definition["active_index"]
        reverse_scale = self.choose_reverse_scale()

        if self.resample_free_parameter:
            vector[active_index] = self.node.random_sample(active_index)

        definition = {
            "vector": vector,
            "initial_index": initial_index,
            "active_index": active_index,
            "reverse_scale": reverse_scale,
        }

        return definition

    @property
    def initial_vector(self):
        return self.definition["vector"]

    @property
    def initial_index(self):
        return self.definition["initial_index"]

    @property
    def active_index(self):
        return self.definition["active_index"]

    @property
    def reverse_scale(self):
        return self.definition["reverse_scale"]

    @property
    def updated_vector(self):
        if self.answer is None:
            return None
        new = self.initial_vector.copy()
        new[self.active_index] = self.answer
        return new


class GibbsNode(ChainNode):
    """
    A Node class for Gibbs sampler chains.

    Attributes
    ----------

    vector_length : int
        Must be overridden with the length of the free parameter vector
        that is manipulated during the Gibbs sampling procedure.
    """

    vector_length = None

    def random_sample(self, i: int):
        """
        (Abstract method, to be overridden)
        Randomly samples a new value for the ith element of the
        free parameter vector.
        This is used for initialising the participant's response options.

        Parameters
        ----------

        i
            The index of the element that is being resampled.

        Returns
        -------

        float
            The new parameter value.
        """
        raise NotImplementedError

    @property
    def vector(self):
        return self.definition["vector"]

    @property
    def initial_index(self):
        return self.definition["initial_index"]

    @property
    def active_index(self):
        return self.definition["active_index"]

    @staticmethod
    def parallel_mean(*vectors):
        return [mean(x) for x in zip(*vectors)]

    @staticmethod
    def get_unique(x):
        assert len(set(x)) == 1
        return x[0]

    # mean, median, kernel
    summarize_trials_method = "mean"

    def summarize_trial_dimension(self, observations):
        method = self.summarize_trials_method
        logger.debug("Summarizing observations using method %s...", method)

        self.var.summarize_trial_method = method

        if method == "mean":
            return mean(observations)
        elif method == "median":
            return median(observations)
        elif method == "kernel_mode":
            return self.kernel_summarize(observations, method="mode")
        else:
            raise NotImplementedError

    # can be a number, or normal_reference, cv_ml, cv_ls (see https://www.statsmodels.org/devel/generated/statsmodels.nonparametric.kernel_density.KDEMultivariate.html)
    kernel_width = "cv_ls"

    def kernel_summarize(self, observations, method):
        import numpy as np
        import statsmodels.api as sm

        assert isinstance(observations, list)

        kernel_width = self.kernel_width
        if (not isinstance(kernel_width, str)) and (np.ndim(kernel_width) == 0):
            kernel_width = [kernel_width]

        density = sm.nonparametric.KDEMultivariate(
            data=observations, var_type="c", bw=kernel_width
        )
        points_to_evaluate = np.linspace(min(observations), max(observations), num=501)
        pdf = density.pdf(points_to_evaluate)

        if method == "mode":
            index_max = np.argmax(pdf)
            mode = points_to_evaluate[index_max]

            self.var.summary_kernel = {
                "bandwidth": kernel_width,
                "index_max": int(index_max),
                "mode": float(mode),
                "observations": observations,
                "pdf_locations": points_to_evaluate.tolist(),
                "pdf_values": pdf.tolist(),
            }
            return mode
        else:
            raise NotImplementedError

    def summarize_trials(self, trials: list, experiment, participant):
        """
        This method summarizes the answers to the provided trials.
        The default method averages over all the provided parameter vectors,
        and will typically not need to be overridden.

        Parameters
        ----------
        trials
            Trials to be summarized. By default only trials that are completed
            (i.e. have received a response) and processed
            (i.e. aren't waiting for an asynchronous process)
            are provided here.

        experiment
            An instantiation of :class:`psynet.experiment.Experiment`,
            corresponding to the current experiment.

        participant
            The participant who initiated the creation of the node.

        Returns
        -------

        dict
            A dictionary of the following form:

            ::

                {
                    "vector": summary_vector,
                    "initial_index": initial_index
                    "active_index": active_index
                }

            where ``summary_vector`` is the summary of all the vectors,
            and ``active_index`` is an integer identifying which was the
            free parameter. The initial index is also passed on, as it is
            used to identify the current dimension in the chain.
        """
        self.var.summarize_trials_used = [t.id for t in trials]
        active_index = trials[0].active_index
        initial_index = trials[0].initial_index
        observations = [t.updated_vector[active_index] for t in trials]

        summary = self.summarize_trial_dimension(observations)
        self.var.summarize_trials_output = summary

        vector = trials[0].updated_vector.copy()
        vector[active_index] = summary

        return {
            "vector": vector,
            "initial_index": initial_index,
            "active_index": active_index,
        }

    def create_definition_from_seed(self, seed, experiment, participant):
        """
        Creates a :class:`~psynet.trial.gibbs.GibbsNode` definition
        from the seed passed by the previous :class:`~psynet.trial.gibbs.GibbsNode`
        or :class:`~psynet.trial.gibbs.GibbsSource` in the chain.
        The vector of parameters is preserved from the seed,
        but the 'active index' is increased by 1 modulo the length of the vector,
        meaning that the next parameter in the vector is chosen as the current free parameter.
        This method will typically not need to be overridden.


        Returns
        -------

        dict
            A dictionary of the following form:

            ::

                {
                    "vector": vector,
                    "initial_index": initial_index
                    "active_index": active_index
                }

            where ``vector`` is the vector passed by the seed,
            ``initial_index`` identifies the dimension of the first iteration,
            and ``active_index`` identifies the position of the new free parameter.
        """

        vector = seed["vector"]
        initial_index = seed["initial_index"]
        if self.network is None:
            return {
                "vector": vector,
                "initial_index": initial_index,
                "active_index": initial_index,
            }
        else:
            dimension_order = self.network.dimension_order
            dimension_index = dimension_order.index(initial_index)
            dimension_index = (dimension_index + self.degree) % len(vector)
            active_index = dimension_order[dimension_index]
            return {
                "vector": vector,
                "initial_index": initial_index,
                "active_index": active_index,
            }

    def create_initial_seed(self, experiment, participant):
        """
        Generates the seed for the :class:`~psynet.trial.gibbs.GibbsSource`.
        By default the method samples the vector of parameters by repeatedly
        applying :meth:`~psynet.trial.gibbs.GibbsNetwork.random_sample`,
        and randomly chooses one of these parameters to be the initial free parameter (``"initial_index"``).
        Note that the source itself doesn't receive trials, and the first proper node in the chain will actually have
        the free parameter after this one, see GibbsNode.create_definition_from_seed for the implementation.
        This method will not normally need to be overridden.

        Parameters
        ----------

        experiment
            An instantiation of :class:`psynet.experiment.Experiment`,
            corresponding to the current experiment.

        participant:
            An instantiation of :class:`psynet.participant.Participant`,
            corresponding to the current participant.

        Returns
        -------

        dict
            A dictionary of the following form:

            ::

                {
                    "vector": vector,
                    "initial_index": initial_index
                }

            where ``vector`` is the initial vector
            and ``initial_index`` identifies the initial position of the free parameter.
        """
        if self.vector_length is None:
            raise ValueError(
                "node.vector_length must not be None. Did you forget to set it? "
                "Please provide this as a class attribute of your Node class."
            )
        return {
            "vector": [self.random_sample(i) for i in range(self.vector_length)],
            "initial_index": random.randint(0, self.vector_length - 1),
        }


class GibbsTrialMaker(ChainTrialMaker):
    """
    A TrialMaker class for Gibbs sampler chains;
    see the documentation for
    :class:`~psynet.trial.chain.ChainTrialMaker`
    for usage instructions.
    """

    randomize_dimension_order_per_network = False
    performance_check_type = "consistency"

    def check_initialization(self):
        super().check_initialization()
        if self.node_class.random_sample == GibbsNode.random_sample:
            raise NotImplementedError(
                "The GibbsNode class is missing a random_sample method, "
                "which tells the Gibbs process how to resample free parameters. "
                "If you are migrating from a previous version of PsyNet (< 10.0.0), "
                "you probably need to copy this method over from your custom network class "
                "to your custom node class."
            )
        if self.node_class.vector_length is None:
            raise NotImplementedError(
                "The GibbsNode class is missing a vector_length attribute. "
                "If you are migrating from a previous version of PsyNet (< 10.0.0), "
                "you probably need to copy this method over from your custom network class "
                "to your custom node class."
            )

    @property
    def default_network_class(self):
        return GibbsNetwork
