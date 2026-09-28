Getting help
============

Getting stuck is a normal part of running experiments. A short
investigation before you ask often solves the problem, and when it does
not, it makes your question much easier to answer.

Investigate the error
---------------------

Read the stack trace carefully. The last line usually names the actual
error, but scroll up as well: the final error is often only a symptom of
an earlier one. Most editors let you click file paths in the trace to jump
to the failing line, and setting a breakpoint there usually shows why the
error occurs. See the :ref:`development workflow <development_workflow>`
for the recommended editor and debugging setup.

For example, in a trace ending like this, the last line is the one to
search for:

.. code:: text

   Traceback (most recent call last):
     ...
     File ".../psynet/experiment.py", line 848, in config_defaults
       expected_type = config_types[key]
   KeyError: 'show_bonus'

Search for the specific part of the message first (``show_bonus``), then
for the more generic part (``KeyError``) together with the name of the
function that failed. Useful places to search are:

- your lab's chat history, if your lab uses a shared support channel;
- the `PsyNet issue tracker <https://gitlab.com/PsyNetDev/PsyNet/-/issues>`__
  and `Dallinger issue tracker <https://github.com/Dallinger/Dallinger/issues>`__;
- a web search, which is particularly helpful when the error comes from a
  dependency (for example ``numpy``) or third-party software (for
  example Docker). Wrap the message in double quotes for exact matches.

Many problems like the one above come from a mismatch between your local
PsyNet version and the version in your experiment's ``requirements.txt``,
so check that early.

Ask for help
------------

If you have been stuck on the same problem for more than about an hour,
ask for help.

- **Ask in a shared place.** Prefer your lab's public support channel or
  a PsyNet issue over direct messages, so that others can find the answer
  later and more people can respond.
- **Be specific.** Include:

  - what you were trying to do;
  - which error occurs, and where;
  - the PsyNet and Dallinger versions you use locally and in
    ``requirements.txt``;
  - whether you run in a virtual environment or with Docker;
  - the full stack trace;
  - if possible, a minimal example, such as a PsyNet demo that shows the
    problem or a link to your repository.

- **Post the solution.** Once the problem is solved, reply in the same
  thread with what fixed it.
