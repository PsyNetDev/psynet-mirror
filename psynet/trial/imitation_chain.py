from .chain import ChainNetwork, ChainNode, ChainTrial, ChainTrialMaker


class ImitationChainNetwork(ChainNetwork):
    """
    A Network class for imitation chains.
    """

    def make_definition(self):
        return {}


class ImitationChainTrial(ChainTrial):
    """
    A Trial class for imitation chains.
    """

    def make_definition(self, experiment, participant):
        """
        (Built-in)
        In an imitation chain, the trial's definition equals the definition of
        the node that created it.

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
            The trial's definition, equal to the node's definition.
        """
        return self.node.definition


class ImitationChainNode(ChainNode):
    """
    A Node class for imitation chains.
    """

    def create_definition_from_seed(self, seed, experiment, participant):
        """
        (Built-in)
        In an imitation chain, the next node in the chain
        is a faithful reproduction of the previous iteration.

        Parameters
        ----------

        seed
            The seed being passed to the node.

        experiment
            An instantiation of :class:`psynet.experiment.Experiment`,
            corresponding to the current experiment.

        participant
            Current participant, if relevant.

        Returns
        -------

        object
            The node's new definition, which is a faithful reproduction of the seed
            that it was passed.
        """
        # The next node in the chain is a faithful reproduction of the previous iteration.
        return seed

    def summarize_trials(self, trials: list, experiment, participant):
        """
        (Abstract method, to be overridden)
        This method should summarize the answers to the provided trials.
        A default method is implemented for cases when there is
        just one trial per node; in this case, the method
        extracts and returns the trial's answer, available in ``trial.answer``.
        The method must be extended if it is to cope with multiple trials per node,
        however.

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

        if self.trial_maker.trials_per_node > 1:
            raise NotImplementedError

        if len(trials) > 1:
            for i in range(1, len(trials)):
                trials[i].fail(reason="Too many trials at the same node")

        return trials[0].answer


class ImitationChainTrialMaker(ChainTrialMaker):
    """
    A TrialMaker class for imitation chains;
    see the documentation for
    :class:`~psynet.trial.chain.ChainTrialMaker`
    for usage instructions.
    """

    performance_check_type = "consistency"

    @property
    def default_network_class(self):
        return ImitationChainNetwork
