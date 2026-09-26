Hello world
===========

This is the smallest complete PsyNet experiment: one page that says
"Hello world", then an end page. Use it to check that your installation runs an
experiment, or as a minimal template for the structure every experiment
shares. Run it with:

.. code-block:: bash

   cd demos/experiments/hello_world
   psynet debug local

Source: ``demos/experiments/hello_world``. Only ``experiment.py`` is shown
below; the directory also contains the usual supporting files.

.. literalinclude:: ../../../demos/experiments/hello_world/experiment.py
   :language: python

The ``Timeline`` determines the order of pages in the experiment.
Here it contains a single ``InfoPage``, which displays some text to the
participant. The ``time_estimate`` parameter tells PsyNet that we expect the
participant to spend about 5 seconds on this page. This information is used for
progress bar and payment estimation.

Real experiments normally start the timeline with a ``Consent`` object,
which gives the participant information about the study and solicits their
informed consent. This is an ethical requirement for most research studies,
and each research group typically has its own consent form. The demo omits
it because ``psynet debug local`` does not require a consent page; before
deploying, add a page from :mod:`psynet.consent`, or ``NoConsent`` to skip
the check explicitly.

PsyNet appends a ``SuccessfulEndPage`` to every timeline, so the demo does
not list one. Reaching the successful-end branch marks the participant as
successful rather than unsuccessful; this is used mainly to decide how many
more participants need to be recruited.
