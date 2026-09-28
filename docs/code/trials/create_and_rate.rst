Create and rate
===============

A create-and-rate experiment is a chain experiment in which each node
collects creations from some participants, such as text descriptions,
recordings or slider settings, and then ratings of those creations from
others. The best creation becomes the next node's definition: the one with
the highest mean rating, or the one chosen by the most raters. The same
structure can also validate stimuli during an experiment.

The examples on this page come from ``demos/experiments/create_and_rate/basic``,
in which creators describe a picture of an animal and raters judge the
descriptions. To run it from a PsyNet source checkout:

.. code-block:: console

    cd demos/experiments/create_and_rate/basic
    psynet debug local

How it works
------------

Each node first receives ``n_creators`` creator trials. Once those trials are
finalized, it receives ``n_raters`` rater trials. The trial maker then
summarizes the ratings to choose the next node's definition. It sets
``trials_per_node`` to ``n_creators + n_raters`` itself.

An experiment defines three classes, each combining a mixin from
``psynet.trial.create_and_rate`` with a chain class. The mixin must come
first:

- a creator trial: ``CreateTrialMixin`` and a
  :class:`~psynet.trial.chain.ChainTrial` subclass;
- a rater trial: ``RateTrialMixin`` (for ratings) or ``SelectTrialMixin``
  (for choosing one creation), and a
  :class:`~psynet.trial.chain.ChainTrial` subclass;
- a trial maker: ``CreateAndRateTrialMakerMixin`` and a
  :class:`~psynet.trial.chain.ChainTrialMaker` subclass.

``CreateAndRateNode`` is the node class for most experiments.

Creator trials
--------------

A creator trial works like any other chain trial. In the demo, creators
describe the image stored in the node's ``context``:

.. literalinclude:: ../../../demos/experiments/create_and_rate/basic/experiment.py
   :pyobject: CreateTrial

Rater trials
------------

A rater trial finds the creations to judge in ``self.targets``, and reads
each one's answer with ``self.get_target_answer(target)``. A target is either
a creator trial or, with ``include_previous_iteration=True``, the current
node.

With ``RateTrialMixin`` the answer is a number, or a list of numbers when
there are several targets:

.. literalinclude:: ../../../demos/experiments/create_and_rate/basic/experiment.py
   :pyobject: SingleRateTrial

With ``SelectTrialMixin`` the answer is the string form of the chosen target,
so the targets themselves serve as the choices:

.. literalinclude:: ../../../demos/experiments/create_and_rate/basic/experiment.py
   :pyobject: SelectTrial

The trial maker
---------------

The trial maker class only combines the mixin with a chain trial maker:

.. literalinclude:: ../../../demos/experiments/create_and_rate/basic/experiment.py
   :pyobject: CreateAndRateTrialMaker

The demo builds one trial maker for each of three configurations:

.. literalinclude:: ../../../demos/experiments/create_and_rate/basic/experiment.py
   :pyobject: get_trial_maker

The create-and-rate arguments are:

- ``n_creators`` and ``n_raters``: positive integers.
- ``node_class``, ``creator_class`` and ``rater_class``.
- ``rate_mode``: ``"rate"`` (default) or ``"select"``. With ``"select"``,
  each node needs at least two targets and ``rater_class`` must use
  ``SelectTrialMixin``.
- ``target_selection_method``: ``"one"`` (default) gives each rater one
  target, chosen at random among those with the fewest ratings so far;
  ``"all"`` gives each rater every target. ``"select"`` requires ``"all"``.
  With ``"rate"`` and ``"one"``, ``n_raters`` must be a multiple of the number
  of targets.
- ``include_previous_iteration`` (default ``False``): rate the current
  node's definition, the previous winner, alongside the new creations. Every
  start node then needs a ``seed``, as in the demo's ``get_trial_maker``.
- ``randomize_target_order`` (default ``True``): shuffle the targets for each
  rater.
- ``verbose`` (default ``False``): log how targets and winners are chosen.

The remaining arguments go to the chain trial maker; see
:doc:`/code/writing_a_chain_experiment`.

Separate creators and raters
----------------------------

By default, a participant creates or rates depending on which phase the
chosen node is in. To give participants a fixed role, override
``get_participant_role`` to return ``self.CREATOR_ROLE`` or
``self.RATER_ROLE``. Creators then only receive nodes that still need
creations. Raters receive nodes that are ready for ratings, and wait or exit
at nodes whose creations are not yet finalized, depending on
``wait_for_networks``.

``demos/experiments/create_and_rate/gap`` assigns roles in a
:class:`~psynet.timeline.CodeBlock` before the trial maker, stores them in
``participant.var.is_rater``, and also limits how many trials each role
completes:

.. literalinclude:: ../../../demos/experiments/create_and_rate/gap/experiment.py
   :pyobject: CreateAndRateTrialMaker

Two more demos in the same folder use other creator trials: in ``picnic``,
creators propose a rule that raters check against examples; in
``robot_voice``, creators adjust a synthesized voice with an
:class:`~psynet.trial.media_gibbs.AudioGibbsTrial`.
