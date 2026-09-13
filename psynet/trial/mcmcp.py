# pylint: disable=unused-argument,abstract-method

import random
from collections import Counter

from .chain import ChainNetwork, ChainNode, ChainTrial, ChainTrialMaker


class MCMCPNetwork(ChainNetwork):
    """
    A Network class for MCMCP chains.
    """

    def make_definition(self):
        return {}


class MCMCPTrial(ChainTrial):
    """
    A Network class for MCMCP.

    Attributes
    ----------

    first_stimulus
        Definition of the first stimulus of the trial.
        This definition corresponds to a setting
        of the chain's free parameters.

    second_stimulus
        Definition of the second stimulus of the trial,
        This definition corresponds to a setting
        of the chain's free parameters.
    """

    def make_definition(self, experiment, participant):
        """
        In MCMCP, a trial's definition is created by taking the
        current state and the proposal from the source
        :class:`~psynet.trial.mcmcp.MCMCPNode`
        and adding a random ordering.

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
            plus the random ordering.

        """
        order = ["current_state", "proposal"]
        random.shuffle(order)
        definition = {
            "current_state": self.node.definition["current_state"],
            "proposal": self.node.definition["proposal"],
        }
        definition["ordered"] = [
            {"role": role, "value": definition[role]} for role in order
        ]
        return definition

    @property
    def first_stimulus(self):
        return self.definition["ordered"][0]["value"]

    @property
    def second_stimulus(self):
        return self.definition["ordered"][1]["value"]


class MCMCPNode(ChainNode):
    """
    A Node class for MCMCP chains.
    """

    def get_proposal(self, state, experiment, participant):
        """
        Implements the proposal function for the MCMP chain.

        Parameters
        ----------

        state
            The current state, with reference to which the proposal
            state should be constructed.

        experiment
            An instantiation of :class:`psynet.experiment.Experiment`,
            corresponding to the current experiment.

        participant
            An instantiation of :class:`psynet.participant.Participant`,
            corresponding to the current participant.

        Returns
        -------

        Object
            The proposal state.
        """
        raise NotImplementedError

    def summarize_trials(self, trials: list, experiment, participant):
        """
        This method should summarize the answers to the provided trials.
        A default method is implemented for cases when there is
        just one trial per node; in this case, the method extracts and returns
        the parameter values for the chosen stimulus, following the standard
        definition of MCMCP. The method must be extended if it is to cope
        with multiple trials per node.

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

        object
            The derived seed. Should be suitable for serialisation to JSON.
        """
        counts = Counter([t.answer["role"] for t in trials])
        max_count = max(counts.values())
        candidates = [item[0] for item in counts.items() if item[1] == max_count]
        chosen_role = random.sample(candidates, 1)[0]
        return self.definition[chosen_role]

    def create_definition_from_seed(self, seed, experiment, participant):
        return {
            "current_state": seed,
            "proposal": self.get_proposal(seed, experiment, participant),
        }

    def create_initial_seed(self, experiment, participant):
        raise NotImplementedError


class MCMCPTrialMaker(ChainTrialMaker):
    """
    A TrialMaker class for MCMCP chains;
    see the documentation for
    :class:`~psynet.trial.chain.ChainTrialMaker`
    for usage instructions.
    """

    def finalize_trial(self, answer, trial, experiment, participant):
        """
        Modifies ``answer`` so as to store three values:

        * The position of the chosen stimulus;
        * The role of the chosen stimulus (``"current_state"`` or ``"proposal"``);
        * The value of the parameters underlying the chosen stimulus.
        """
        # pylint: disable=unused-argument,no-self-use
        position = int(answer)
        answer = {
            "position": position,
            "role": trial.definition["ordered"][position]["role"],
            "value": trial.definition["ordered"][position]["value"],
        }
        trial.answer = answer
        super().finalize_trial(answer, trial, experiment, participant)

    def get_answer_for_consistency_check(self, trial):
        role = trial.answer["role"]
        assert role in ["proposal", "current_state"]
        return float(role == "proposal")

    performance_check_type = "consistency"
    consistency_check_type = "percent_agreement"

    @property
    def default_network_class(self):
        return MCMCPNetwork
