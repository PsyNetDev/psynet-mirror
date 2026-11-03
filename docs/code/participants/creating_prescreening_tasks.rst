============================
Creating pre-screening tasks
============================

Put custom pre-screening tasks in your experiment, not in the PsyNet package.

A single question
-----------------

A one-question pre-screening task is a :class:`~psynet.timeline.Module` that
asks the question and uses :func:`~psynet.timeline.conditional` to send
failing participants to :class:`~psynet.page.UnsuccessfulEndPage`:

.. code-block:: python

    from psynet.modular_page import ModularPage, PushButtonControl
    from psynet.page import UnsuccessfulEndPage
    from psynet.timeline import Module, conditional


    def hearing_impairment_check():
        return Module(
            "hearing_impairment_check",
            ModularPage(
                "hearing_impairment",
                "Do you have any kind of hearing impairment?",
                PushButtonControl(["Yes", "No"]),
                time_estimate=3,
            ),
            conditional(
                "fail_if_impaired",
                lambda participant: participant.answer == "Yes",
                UnsuccessfulEndPage(failure_tags=["hearing_impairment_check"]),
            ),
        )

Place ``hearing_impairment_check()`` in the timeline before the main task.
With a :class:`~psynet.modular_page.TextControl`, evaluate the typed answer
in the ``conditional`` in the same way.

Several scored trials
---------------------

A test with several trials is a
:class:`~psynet.trial.static.StaticTrialMaker` with
``check_performance_at_end=True``. Each trial implements
:meth:`~psynet.trial.main.Trial.score_answer`. With
``performance_check_type = "score"``, the participant passes if the sum of the
trial scores reaches ``performance_threshold``, and a participant who fails is
sent to an :class:`~psynet.page.UnsuccessfulEndPage`.

:class:`~psynet.prescreen.ColorBlindnessTest` is built this way. Its trial
shows an image and scores the typed number:

.. literalinclude:: ../../../psynet/prescreen/__init__.py
   :pyobject: ColorBlindnessTrial

The trial maker defines one :class:`~psynet.trial.static.StaticNode` per
image, and passes the threshold and trial count on to
:class:`~psynet.trial.static.StaticTrialMaker`:

.. literalinclude:: ../../../psynet/prescreen/__init__.py
   :pyobject: ColorBlindnessTest.get_nodes

The images are hosted on S3 under file names that reveal the correct answer,
either directly or when looked up in PsyNet's public source code (here, the
plate numbers), and participants can read stimulus URLs in the page source.
The built-in test therefore wraps each URL with the internal helper
``_opaque_media_asset``, which serves the image through PsyNet under an opaque
``/asset/<access_token>`` URL. This helper is internal for now, so don't
import it in your own experiments. In your own pre-screen, give stimulus files
neutral names that don't reveal the answer, or add local files with :func:`~psynet.asset.asset` or
:class:`~psynet.asset.FileAsset`, whose URLs don't contain the file name.
Passing an http(s) URL to :func:`~psynet.asset.asset` creates an
:class:`~psynet.asset.ExternalAsset`, which keeps the original URL.

.. literalinclude:: ../../../psynet/prescreen/__init__.py
   :pyobject: ColorBlindnessTest.__init__

The class also sets ``performance_check_type = "score"`` and defines an
``introduction`` property that returns the instructions page.

If the test only decides whether the participant may continue, set
``fail_trials_on_participant_performance_check=False`` so that the trials of
participants who fail stay valid. The default for static trial makers is
``True``.
