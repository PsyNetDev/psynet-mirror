Trials (1)
==========

The first of three trial demos. A trial is a single unit of data collection,
typically the participant's response to a single stimulus. In this demo
participants rate different animals. Run it from ``demos/experiments/trial``
with ``psynet debug local``; :doc:`/designing/trials` covers
trials in more depth.

Source: ``demos/experiments/trial``

The demo is built around a custom class called ``RateTrial``, which defines the logic
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


.. literalinclude:: ../../../demos/experiments/trial/experiment.py
   :language: python
