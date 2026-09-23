Dallinger
=========

PsyNet is build on top of the `Dallinger <https://dallinger.readthedocs.io/>`_ framework.
Dallinger is a framework for developing online network-based experiments, allowing researchers
to run complex cultural evolution experiments and human-in-the-loop experiments online.
Key features of Dallinger include sophisticated code for deploying online experiments onto
Heroku webservers, an advanced system for representing network-based experiments as graph-based
structures, and excellent integration with Amazon Mechanical Turk.

PsyNet provides several levels of abstractions above Dallinger that make it much more efficient
to develop advanced experiments. One key feature is the *timeline*, through which
the experimenter specifies the order of events within the experiment. Using familiar constructs
from other programming languages (e.g. for loops, while loops, conditionals),
the experimenter can construct very complex procedures in an intuitive and readable fashion.
Moreover, timeline components can easily be wrapped into self-contained components
(e.g. functions, classes) which can then be distributed and reused in other contexts.

Our long-term goal is that people should be able to design and run PsyNet experiments
without knowing or worrying about the details of Dallinger. For now, however, the abstraction
is still a little leaky, and you might find yourself running various Dallinger commands
as part of your experiment implementation workflow. It is worth having a little look
at the official `Dallinger documentation <https://dallinger.readthedocs.io/>`_ to get a feel
for this underlying framework.
