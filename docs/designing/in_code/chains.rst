Chains in code
==============

This page shows how the ideas in :doc:`/designing/chains` appear in
``experiment.py``, using the ``demos/experiments/chain_trial_maker`` demo, a
serial-reproduction task where each participant retells the previous
participant's story.

How a chain grows
-----------------

Start nodes are built in a function, like the nodes of a static experiment:

.. literalinclude:: ../../../demos/experiments/chain_trial_maker/experiment.py
   :pyobject: get_start_nodes

The rule for making the next node is the node class's
:meth:`~psynet.trial.chain.ChainNode.make_next_definition` method. PsyNet calls
it on the current node once that node has ``trials_per_node`` usable trials,
and uses the returned dictionary as the next node's definition. In the demo,
the next story is simply the previous participant's retelling:

.. literalinclude:: ../../../demos/experiments/chain_trial_maker/experiment.py
   :pyobject: CustomChainNode

Inside the method:

- ``self.definition`` is the current node's definition;
- ``self.completed_and_processed_trials`` lists the trials to build on: those
  that are complete, finalized (so any recording analysis has finished), and
  not failed, excluding repeat trials;
- ``self.degree`` is the current node's position in the chain, starting at 0;
  the new node will have degree ``self.degree + 1``;
- ``participant`` is the participant whose trial completed the node.

With several trials per node, combine their answers, and carry forward any
fields the next node still needs:

.. code-block:: python

    import statistics

    class RatingNode(ChainNode):
        def make_next_definition(self, experiment, participant):
            return {
                "question": self.definition["question"],
                "mean_rating": statistics.mean(
                    float(t.answer) for t in self.completed_and_processed_trials
                ),
            }

The trial is a subclass of :class:`~psynet.trial.chain.ChainTrial` and works
like a static trial:

.. literalinclude:: ../../../demos/experiments/chain_trial_maker/experiment.py
   :pyobject: CustomTrial

If a node needs new media, for example a sound synthesized from the previous
participant's answer, override the node's ``async_on_deploy`` method and call
``self.add_assets`` there. It runs in the background after the node is
created, and participants cannot visit the node until it finishes.

Within and across participants
------------------------------

The :class:`~psynet.trial.chain.ChainTrialMaker` goes in the timeline:

.. literalinclude:: ../../../demos/experiments/chain_trial_maker/experiment.py
   :pyobject: get_timeline

``chain_type`` is ``"across"`` or ``"within"``. For within-participant chains,
``start_nodes`` must be a function that creates fresh nodes; it may take a
``participant`` argument. Without ``start_nodes``, set
``chains_per_experiment`` (across) or ``chains_per_participant`` (within).

Choosing the next chain
-----------------------

- ``allow_revisiting_networks_in_across_chains`` (default ``False``) lets
  participants return to a chain they have already contributed to.
- ``balance_across_chains`` (default ``False``) sends new trials to the chains
  with fewest responses.
- ``wait_for_networks`` (default ``False``) makes participants wait when
  chains exist but are busy, instead of moving on.
- Participant groups work as in :doc:`trials`: set ``participant_group`` on
  the start nodes and pass ``choose_participant_group``.

Chain length and trials per node
--------------------------------

- ``trials_per_node`` (default ``1``): responses a node needs before the next
  node is made.
- ``max_nodes_per_chain``: the chain is full after this many nodes.
- ``expected_trials_per_participant`` and ``max_trials_per_participant``: an
  integer, or ``"n_start_nodes"``.
- ``recruit_mode`` (default ``"n_participants"``, with
  ``target_n_participants``), or ``"n_trials"`` to recruit until every chain is
  full.

Built-in paradigms
------------------

- :class:`~psynet.trial.imitation_chain.ImitationChainTrialMaker`, with
  :class:`~psynet.trial.audio.AudioImitationChainTrialMaker` and
  :class:`~psynet.trial.video.CameraImitationChainTrialMaker` for recorded
  reproductions;
- :class:`~psynet.trial.gibbs.GibbsTrialMaker` and
  :class:`~psynet.trial.media_gibbs.AudioGibbsTrialMaker` (with image, HTML,
  and video variants);
- :class:`~psynet.trial.mcmcp.MCMCPTrialMaker`;
- :class:`~psynet.trial.staircase.GeometricStaircaseTrialMaker`;
- the create-and-rate mixins in ``psynet.trial.create_and_rate``;
- :class:`~psynet.trial.graph.GraphChainTrialMaker`.

The ``demos/experiments`` folder has a demo for each, for example
``imitation_chain``, ``gibbs``, ``mcmcp``, ``staircase_pitch_discrimination``,
``create_and_rate``, and ``graph``.

When a trial fails
------------------

``fail_trials_on_participant_performance_check`` defaults to ``False`` for
chains, so completed trials are kept when a participant fails a check.
``propagate_failure`` (default ``True``) fails the nodes that a failed,
finalized trial helped to create.

Where the data goes
-------------------

Nodes, trials, and chains are database rows:

.. code-block:: python

    CustomChainNode.query.filter_by(trial_maker_id="stories").order_by(CustomChainNode.degree)
    node.network      # the chain
    node.child        # the next node, if any
    node.all_trials

.. seealso::

   :doc:`/reference/api/trial/chain` in the API reference.
