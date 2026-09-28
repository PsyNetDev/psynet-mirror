.. _simulated_participants:

Simulated participants
======================

A simulated participant, or **bot**, takes the experiment through the same
server and timeline as a real participant, but without a browser. PsyNet
uses bots to test experiments (``psynet test local``), to produce the
simulated export for an audit (``psynet audit simulate``), and to run
performance tests.

Bot answers
-----------

By default, a bot gives a valid answer to each page, for example a random
choice from the options or a number in the allowed range. Pages that
collect recordings need a sample file for bots to submit.

A page can override the default answer. For example, bots in a rating study
can rate some stimuli higher than others, and bots in a chain can copy the
previous answer with some error. In group experiments, several bots take
the experiment together.

Response models
---------------

A response model is code, kept with the experiment, that generates bot
answers from assumptions about how participants behave. The same model is
used for the simulated export and the power analysis. See
:doc:`practice_data`.

Limitations
-----------

- Bots don't display pages, so they don't detect layout problems.
- Bot answers are generated, not collected from people. Simulated data
  can't show whether participants understand the task or how they will
  respond.

.. seealso::

   :doc:`/code/tests`, for running bots and adding checks.
