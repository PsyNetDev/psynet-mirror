.. |psynet_logo| image:: _static/images/psynet-transparent.png
   :height: 2.1em
   :alt: PsyNet logo

|psynet_logo| PsyNet
====================

PsyNet is a Python framework for behavioral experiments that are difficult
or impossible to run on conventional platforms: procedures that adapt to
each response as it arrives, chains in which one participant's response
becomes the next participant's stimulus, studies that balance ratings across
thousands of stimuli, and groups of participants interacting in real time.
Participants can be recruited online or tested in the lab. PsyNet builds on
the virtual lab framework
`Dallinger <https://dallinger.readthedocs.io/latest/>`_.

- **Complex designs.** Experiment logic runs on the server as data arrive,
  so each trial can depend on the participant's earlier answers or on what
  other participants have done. This supports adaptive psychophysics, Gibbs
  sampling and Markov chain Monte Carlo with people, serial reproduction
  chains, create-and-rate paradigms, and real-time multiplayer games.
- **Everything is code.** A PsyNet experiment is a Python project: its
  timeline, pages, stimuli and adaptive rules are all defined in code.
  Experiments can therefore be read from top to bottom, versioned and
  reviewed like any other software, and reused in later studies. The same
  property makes PsyNet well suited to coding agents, which can write and
  test an experiment from a written description.
- **Infrastructure included.** PsyNet provides the infrastructure that an online
  study needs beyond the task itself: recruitment and payment through
  Prolific, Cint or a lab's own participant pool, pre-screening, media
  handling, translation, automated testing with simulated participants,
  deployment to a server, monitoring, and data export.
- **Everything is extensible.** Any Python library can be used on the
  server, for example to synthesize stimuli or analyze recordings as they
  arrive. Pages can be built from scratch in HTML and JavaScript, and
  because PsyNet is open source, any part of it can be customized or
  replaced.

.. toctree::
   :hidden:
   :maxdepth: 3
   :titlesonly:
   :includehidden:

   About <introduction/index>
   install
   quickstart
   Design <design/index>
   Test <test/index>
   Deploy <deploy/index>
   data/index
   Code <code/index>
   Agent Skills <skills/index>
   examples/index
   reference/index
   whats_new/index
   developer/index
