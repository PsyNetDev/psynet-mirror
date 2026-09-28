.. _why_psynet:

Why PsyNet?
===========

PsyNet sits between two familiar options. Survey platforms and experiment
builders are quick to set up, but hard to extend beyond what they offer.
Writing your own web application gives you full control, but then you have
to build recruitment, payment, data storage and deployment yourself.
PsyNet gives you the control of code without that extra work: the whole
experiment is code, the infrastructure for running a study is built in, and
every part can be extended.

Everything is code
------------------

A PsyNet experiment is a Python project. The order of events, the pages
participants see, the stimuli, the adaptive rules and the configuration are
all written in ``experiment.py`` and the files beside it. This has several
benefits:

- You can read the experiment from top to bottom and see exactly what
  participants will do, including every branch and loop.
- You can version, review and share the experiment like any other code, and
  reuse parts of it in later studies.
- A coding agent can write and revise the experiment from a description,
  because everything it needs is in the project directory. PsyNet provides
  a rich list of agent skills to help agents work with PsyNet.
- Every step of a study, from running and testing it locally to deploying it
  and exporting the data, is a terminal command. Scripts, continuous
  integration and coding agents can therefore carry out the whole workflow.

See :doc:`/designing/timeline` for how an experiment is structured, and
:doc:`/guides/project/agentic_programming` for working with a coding agent.

Batteries included
------------------

Most of the work of an online study lies outside the task itself. PsyNet
provides that work ready-made.

Running a study
^^^^^^^^^^^^^^^

- **Deployment** to a server with one command. The experiment you deploy is
  the one you tested.
- **Recruitment and payment** through Prolific, Cint or your lab's own
  participant pool, including performance bonuses and caps on spending.
- **Screening**, with ready-made tasks such as headphone checks and language
  tests.
- **Trial bookkeeping**: tracking which stimuli still need responses, which
  chains are waiting for a participant, and which trials failed and need
  replacing.
- **Media**: serving audio, images and video, and collecting participants'
  recordings.
- **Translation** of participant-facing text into other languages.
- **Monitoring** through a dashboard for following participants and managing
  recruitment while the study runs.
- **Data export** to CSV files, during the study or after it ends.

See :doc:`/running_studies/index`,
:doc:`/running_studies/workflow/recruiters/index` and
:doc:`/guides/participants/index`.

Checking it before launch
^^^^^^^^^^^^^^^^^^^^^^^^^

- **Simulated participants** run through the whole experiment, so errors
  show up on your own computer rather than during data collection.
- **A practice dataset** comes from the same simulations, so you can write
  your analysis before collecting real data.
- **Performance tests** show how the server copes when many participants
  arrive at once.
- **Experiment audits** gather this evidence for a colleague or supervisor
  to review.

See :doc:`/guides/testing/tests` and :doc:`/guides/project/audit`.

Everything is extensible
------------------------

The built-in components are starting points rather than limits. Because an
experiment is ordinary Python and PsyNet is open source, you can go beyond
them in several ways:

- **Any procedure can be written directly.** Your code runs on the server
  between pages, so the next trial can depend on this participant's earlier
  answers or on what other participants have done, following whatever rule
  your design needs.
- **Any Python library can be used on the server**, for example to
  synthesize each new stimulus or to analyze a recording as soon as it
  arrives.
- **Pages can be written from scratch** in HTML and JavaScript when the
  built-in components aren't enough. The demos include a task written in
  jsPsych and a game built in Unity.
- **Built-in components can be subclassed**, so a trial maker, screening
  task or page type can be adapted instead of rewritten.
- **PsyNet itself can be changed.** You can read its source, override what
  you need in your experiment, or contribute an improvement back.

See :doc:`/designing/trials`, :doc:`/designing/chains` and
:doc:`/guides/pages/writing_custom_frontends`.

Open source and in active use
-----------------------------

PsyNet is free and open source, and builds on
`Dallinger <https://dallinger.readthedocs.io/>`_, a platform for online
experiments. Since 2020 it has been used in studies of perception, music,
language and cultural evolution; see :doc:`research` for example
publications.

What it asks of you
-------------------

PsyNet experiments are written in Python and run on a web server. You need
a computer on which you can install software and, for online studies,
access to a server. There is no visual experiment builder: a coding agent
can write much of the code, but you still need to specify the design and
check that the implementation matches it.

When PsyNet isn't the right tool
--------------------------------

- A fixed questionnaire with no adaptive logic is quicker to build in a
  survey platform.
- Tasks that need millisecond-precise timing from dedicated hardware are
  better run in lab software.
