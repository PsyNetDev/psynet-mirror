Hello world
===========

Source: ``demos/experiments/hello_world``

Following programmer tradition, our first demo is as simple as possible,
and simply prints "Hello world" to the user. We'll just show the ``experiment.py`` file
below, though note that the experiment directory contains various other boilerplate
files too.

.. literalinclude:: ../../demos/experiments/hello_world/experiment.py
   :language: python

Note the use of the timeline, which determines the order of events within the
experiment.
The first component of the timeline will normally be a ``Consent`` object.
This is where we give the participant information about our experiment and
solicit their informed consent. This is an ethical requirement for most research studies.
Ordinarily each research group will have their own custom-made consent form.
Here we've told PsyNet to skip the consent form by including a ``NoConsent`` object.

The second component is an ``InfoPage`` object. Info Pages display some text to the user.
Note the ``time_estimate`` parameter: we use this to tell PsyNet that we expect the
participant to spend about 5 seconds on this page. This information is used for
progress bar and payment estimation.

The final component is a ``SuccessfulEndPage`` object. All PsyNet experiments must
finish with some kind of End Page. Participants who reach a Successful End Page
are marked as successful participants, rather than unsuccessful participants; this
information is primarily used for deciding how many more participants need to be
recruited.
