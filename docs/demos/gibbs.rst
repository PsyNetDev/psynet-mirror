.. _gibbs:

==========================
Gibbs Sampling with People
==========================

Gibbs Sampling with People (GSP) is an adaptive technique for
mapping semantic associations of a stimulus space. The procedure constructs a series
of stimulus 'chains', where a stimulus is passed from one participant to the next,
and each participant adjusts a particular stimulus dimension in order to maximise
a particular subjective criterion (e.g. 'beauty'). The project takes advantage of
PsyNet's support for experiments whose state evolves over time.

Implementing a GSP experiment depends on the following three classes:

* :class:`~psynet.trial.gibbs.GibbsNode`;
* :class:`~psynet.trial.gibbs.GibbsTrial`;
* :class:`~psynet.trial.gibbs.GibbsTrialMaker`.

You can define a custom Gibbs sampling experiment through the following steps:

1. Define a custom GibbsNode class. You need to customize two aspects of this class:
   the ``vector_length`` attribute and the ``random_sample`` method.
   The ``vector_length`` attribute should correspond to the dimensionality of your
   stimulus space.
   The ``random_sample`` method should determine how to sample randomly from the ith
   dimension of that stimulus space.

2. (Optional) define a set of ``start_nodes``.
   These set the initialization parameters for each GSP chain.
   You may wish to give different nodes different 'contexts' via the ``context`` argument:
   these are parameters that will stay constant within
   a chain but may change between chains.
   You may also wish to assign different nodes to different participant groups
   via the ``participant_group`` argument.
   If you are planning a within-participant Gibbs procedure (where each participant
   has their own chains) then this needs to be wrapped in a lambda function
   that can optionally take the participant object as an input.

3. Implement a subclass of :class:`~psynet.trial.gibbs.GibbsTrial`
   with a custom
   :meth:`~psynet.trial.gibbs.GibbsTrial.show_trial` method.
   This :meth:`~psynet.trial.gibbs.GibbsTrial.show_trial` method
   should produce an object of
   class :class:`~psynet.timeline.Page` [1]_
   that presents the participant with some dynamic stimulus (e.g. a color
   or a looping audio sample) that jointly

   a) Embodies the fixed network parameter, e.g. ``"forest"``, found in ``trial.network.definition``;
   b) Embodies the free network parameters, e.g. ``[255, 25, 0]``, found in ``trial.initial_vector``;
   c) Listens to some kind of response interface, e.g. an on-screen slider, which manipulates
      the value of the ith free network parameter, where i is defined from ``trial.active_index``.
   d) Returns the chosen value of the free network parameter as an ``answer``.

4. Create an instance of :class:`~psynet.trial.gibbs.GibbsMaker`,
   filling in its constructor parameter list
   with reference to the classes you created above,
   and insert it into your experiment's timeline.


.. [1] The :meth:`~psynet.trial.gibbs.GibbsTrial.show_trial` method
   may alternatively return a list of :class:`~psynet.timeline.Page` objects.
   In this case, the user is responsible for ensuring that the final
   page returns the appropriate ``answer``.
   The user should also specify an estimated number of pages in the
   :attr:`~psynet.trial.gibbs.GibbsTrial.num_pages` attribute.

.. note::
    The demo included here also incorporates demonstrations of various other
    complex features that are not necessarily needed for most Gibbs experiments.

Source: ``demos/experiments/gibbs``

.. literalinclude:: ../../demos/experiments/gibbs/experiment.py
   :language: python
