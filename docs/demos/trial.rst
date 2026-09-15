Trials (1)
==========

Source: ``demos/experiments/trial``

Often psychological experiments are organized into 'trials'. A trial is a single unit of data collection,
which might typically involve recording the participant's response to a single stimulus.
PsyNet contains some sophisticated abstractions for working with trials in progressively more
complex fashions. These are documented in detail elsewhere, but you can get a feel for
an approach by looking at the demos.

This simple demo implements an experiment where participants have to give ratings for different
animals. The demo is build around a custom class called ``RateTrial``, which defines the logic
for a given trial. The key element of this class is the ``show_trial`` method, which
defines the page (or pages) shown to the participant. In the simplest case, this method
just returns a single page, which will most commonly be a Modular Page.

Below this we define the ``word_ratings`` Module. Modules are a useful way for organizing the
logic of PsyNet experiments into discrete components. This Module contains a For Loop,
which here is used to sample three random words to present to the participant.
To present a word in the form of a Rate Trial, we call ``RateTrial.cue``.
For another example with a ``while_loop``,
see ``demos/features/trial_cue_adaptive``.

.. note::

    The ``test_check_bot`` method in the Experiment class is used to define a custom function
    for checking whether a bot has the expected state. It's run by the automated PsyNet tests
    once a given bot has finished the experiment. For example, the code assert ``len(trials) == 3``
    will throw an error if the bot hasn't completed exactly 3 trials.


.. literalinclude:: ../../demos/experiments/trial/experiment.py
   :language: python
