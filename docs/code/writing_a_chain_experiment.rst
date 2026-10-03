Writing a chain experiment
==========================

The examples on this page come from ``demos/experiments/chain_trial_maker``,
a serial-reproduction task in which each participant retells the previous
participant's story. To run it from a PsyNet source checkout:

.. code-block:: console

    cd demos/experiments/chain_trial_maker
    psynet debug local

How a chain grows
-----------------

Start nodes are built in a function, like the nodes of a static experiment:

.. literalinclude:: ../../demos/experiments/chain_trial_maker/experiment.py
   :pyobject: get_start_nodes

The rule for making the next node is the node class's
:meth:`~psynet.trial.chain.ChainNode.make_next_definition` method. PsyNet calls
it on the current node once that node has ``trials_per_node`` usable trials,
and uses the returned dictionary as the next node's definition. In the demo,
the next story is the previous participant's retelling:

.. literalinclude:: ../../demos/experiments/chain_trial_maker/experiment.py
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

.. literalinclude:: ../../demos/experiments/chain_trial_maker/experiment.py
   :pyobject: CustomTrial

If a node needs new media, for example a sound synthesized from the previous
participant's answer, override the node's ``async_on_deploy`` method and call
``self.add_assets`` there. It runs in the background after the node is
created, and participants cannot visit the node until it finishes.

Within and across participants
------------------------------

The :class:`~psynet.trial.chain.ChainTrialMaker` goes in the timeline:

.. literalinclude:: ../../demos/experiments/chain_trial_maker/experiment.py
   :pyobject: get_timeline

``chain_type`` is ``"across"`` or ``"within"``. For within-participant chains,
``start_nodes`` must be a function that creates fresh nodes; it may take a
``participant`` argument. Without ``start_nodes``, set
``chains_per_experiment`` (across) or ``chains_per_participant`` (within).

Choosing the next chain
-----------------------

- ``allow_revisiting_networks_in_across_chains`` (default ``False``) lets
  participants return to a chain they have already contributed to.
- ``block_order`` and ``chain_order`` set the order of blocks and of chains
  within a block. They work like ``block_order`` and ``node_order`` in
  :ref:`trial_order`, except that ``chain_order`` defaults to ``"random"``,
  ``"balanced"`` favours the shortest chains and then the heads with the
  fewest trials, and ``"listed"`` follows the order of the start nodes. A
  ``chain_order`` function takes any of ``participant``, ``experiment``,
  ``block`` and ``chains``, by name. Each chain is a
  :class:`~psynet.trial.chain.ChainNetwork` in start-node order; its start
  node's ``context`` is ``chain.context`` and its current node is
  ``chain.head``. For example, to run the hardest condition last:

  .. code-block:: python

      chain_order=lambda chains: sorted(chains, key=lambda chain: chain.context["difficulty"])

  With a planned order, the participant takes the planned chains in turn, one
  trial each, skipping any that are busy, until none can give them another
  trial. Create-and-rate trial makers support only ``"balanced"`` and
  ``"random"``.
- ``interleave_chains`` (default ``True``; ``False`` for
  :class:`~psynet.trial.staircase.GeometricStaircaseTrialMaker`). With
  ``False``, the participant stays on one chain until it can give them no
  more trials, then moves to the next chain in ``chain_order``. While their
  chain is busy they wait, and like any wait for a trial this fails them
  after ``max_time_waiting_for_trial`` seconds (default 60). It needs
  ``chain_type="within"`` or
  ``allow_revisiting_networks_in_across_chains=True``.
- ``wait_for_networks`` (default ``False``) decides what happens when every
  chain the participant could take in the current block is busy, either
  waiting on asynchronous processing or on other participants' unfinished
  trials. With ``True`` the participant waits; with ``False`` they finish
  the block early and move to the next one, or leave the trial maker after
  the last block.
- Participant groups work as in :doc:`/code/writing_a_trial_maker`: set ``participant_group`` on
  the start nodes and pass ``choose_participant_group``.
- To choose the chain yourself, override
  :meth:`~psynet.trial.chain.ChainTrialMaker.custom_chain_filter`, which
  removes chains the participant must not receive, and
  :meth:`~psynet.trial.chain.ChainTrialMaker.select_chain`, which picks one of
  the rest. They follow the same rules as the static trial maker's node hooks
  (see :ref:`choosing nodes yourself <custom_node_selection>`); PsyNet then gives the participant the
  selected chain's current node. With many chains, filter and rank them in
  the database with
  :meth:`~psynet.trial.chain.ChainTrialMaker.filter_chains_query` and
  :meth:`~psynet.trial.chain.ChainTrialMaker.chain_priority` instead (see
  :ref:`trial_selection_performance`).

Chain length and trials per node
--------------------------------

- ``trials_per_node`` (default ``1``): responses a node needs before the next
  node is made.
- ``max_nodes_per_chain``: the chain is full after this many nodes.
- ``expected_trials_per_participant`` and ``max_trials_per_participant``: an
  integer, or ``"n_start_nodes"``.
- ``target_n_participants``: recruit until this many participants finish.
  Alternatively, pass ``recruit_mode="n_trials"`` to recruit until every chain
  is full. Without either, the trial maker leaves recruitment to the rest of
  the experiment.

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
- the create-and-rate mixins in ``psynet.trial.create_and_rate`` (see
  :doc:`/code/trials/create_and_rate`);
- :class:`~psynet.trial.graph.GraphChainTrialMaker`.

The ``demos/experiments`` folder has a demo for each, for example
``imitation_chain``, ``gibbs``, ``mcmcp``, ``staircase_pitch_discrimination``,
``create_and_rate``, and ``graph``.

A :class:`~psynet.trial.staircase.GeometricStaircaseTrialMaker` runs
within-participant staircases. Subclass
:class:`~psynet.trial.staircase.GeometricStaircaseNode` to set ``k`` (the
number of consecutive correct answers needed before the task gets harder;
default ``2``) and define the ``increase_difficulty`` and
``decrease_difficulty`` methods; the ``staircase_pitch_discrimination`` demo
multiplies or divides the parameter by a fixed ``step``. The trial maker takes ``max_nodes_per_chain`` and optionally
``max_reversals_per_chain``, where a reversal is a node at which the
difficulty changes direction. At the end, it scores each staircase as the mean
parameter at its reversals and passes or fails the participant against
``min_passing_score`` and ``max_passing_score`` if you set them.

.. _gibbs_participant_groups:

Writing a Gibbs Sampling with People experiment
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A Gibbs experiment subclasses three classes from :mod:`psynet.trial.gibbs`:

#. A :class:`~psynet.trial.gibbs.GibbsNode` subclass sets ``vector_length``,
   the number of stimulus dimensions, and defines ``random_sample(i)``, which
   returns a random value for dimension ``i``:

   .. literalinclude:: ../../demos/experiments/gibbs/experiment.py
      :pyobject: CustomNode

   Start nodes can carry a ``context``, which stays fixed within a chain,
   such as the target word, and a ``participant_group``. For
   within-participant chains, ``start_nodes`` is a function that creates
   fresh nodes.

#. A :class:`~psynet.trial.gibbs.GibbsTrial` subclass defines
   ``show_trial``. The page shows the stimulus for ``self.initial_vector``,
   lets the participant change dimension ``self.active_index``, and returns
   the new value of that dimension as the answer. ``self.context`` holds the
   chain's fixed parameters:

   .. literalinclude:: ../../demos/experiments/gibbs/experiment.py
      :pyobject: CustomTrial.show_trial
      :dedent: 4

   ``show_trial`` can return a list of pages and code blocks; the answer
   then comes from the last page.

#. A :class:`~psynet.trial.gibbs.GibbsTrialMaker` combines the node and
   trial classes and goes in the timeline.

When a trial fails
------------------

When a participant leaves early, PsyNet fails their incomplete trials and
keeps their completed ones. ``fail_trials_on_participant_performance_check``
defaults to ``False`` for chains, so completed trials are also kept when a
participant fails a check. ``propagate_failure`` (default ``True``) fails the
nodes that a failed, finalized trial helped to create. See
:doc:`/code/trials/participant_and_trial_failure`.

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

   The :doc:`/skills/make-experiment-adaptive` skill describes how to plan,
   simulate and check an adaptive chain.

