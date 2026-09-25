Pages in code
=============

This page shows how the ideas in :doc:`/designing/pages` appear in
``experiment.py``, using the ``demos/features/pages`` demo. Run it with
``psynet debug local`` from the demo directory and step through the pages
while reading the code:

.. literalinclude:: ../../../demos/features/pages/experiment.py
   :pyobject: get_timeline

Kinds of page
-------------

An :class:`~psynet.page.InfoPage` shows text. Wrap HTML in
``markupsafe.Markup`` to format it:

.. code-block:: python

    InfoPage(Markup("Welcome to the <strong>experiment</strong>!"), time_estimate=5)

A :class:`~psynet.modular_page.ModularPage` takes a label, a prompt (plain text
or a prompt object), and optionally a control. Commonly used prompts:

- :class:`~psynet.modular_page.AudioPrompt`,
  :class:`~psynet.modular_page.VideoPrompt`,
  :class:`~psynet.modular_page.ImagePrompt`,
  :class:`~psynet.modular_page.ColorPrompt`,
  :class:`~psynet.modular_page.MusicNotationPrompt`;
- :class:`~psynet.js_synth.JSSynth` for melodies played in the browser;
- :class:`~psynet.graphics.GraphicPrompt` for animations generated in code.

Commonly used controls:

- choices: :class:`~psynet.modular_page.PushButtonControl`,
  :class:`~psynet.modular_page.KeyboardPushButtonControl`,
  :class:`~psynet.modular_page.TimedPushButtonControl`,
  :class:`~psynet.modular_page.CheckboxControl`,
  :class:`~psynet.modular_page.RadioButtonControl`,
  :class:`~psynet.modular_page.DropdownControl`;
- sliders and ratings: :class:`~psynet.modular_page.SliderControl`,
  :class:`~psynet.modular_page.RatingControl`,
  :class:`~psynet.modular_page.MultiRatingControl`;
- text and numbers: :class:`~psynet.modular_page.TextControl`,
  :class:`~psynet.modular_page.NumberControl`;
- recording: :class:`~psynet.modular_page.AudioRecordControl`,
  :class:`~psynet.modular_page.VideoRecordControl`,
  :class:`~psynet.modular_page.AudioMeterControl`;
- surveys: :class:`~psynet.modular_page.SurveyJSControl`;
- clickable graphics: :class:`~psynet.graphics.GraphicControl`.

See :doc:`/guides/pages/modular_page` and :doc:`/reference/api/modular_page`
for the full list.

For consent, use one of the classes in :mod:`psynet.consent`, such as
:class:`~psynet.consent.MainConsent`, usually as the first element of the
timeline. For custom pages, see :doc:`/guides/pages/writing_custom_frontends`
and :doc:`/guides/pages/unity_integration`. End pages are covered in
:doc:`timeline`.

What happens to a response
--------------------------

Pass ``save_answer`` to store the answer in a participant variable:

.. code-block:: python

    ModularPage(
        "age",
        "How old are you?",
        NumberControl(),
        time_estimate=5,
        save_answer="age",
    )

The most recent answer is also available as ``participant.answer``. Every
response is a row of the ``response`` table: ``question`` holds the page's
label, alongside ``answer``, ``metadata`` (including ``time_taken``), and
``successful_validation``.

To validate a response, subclass the control and return a
:class:`~psynet.timeline.FailedValidation` with a message for the participant:

.. code-block:: python

    class MelodyControl(TextControl):
        def validate(self, response, **kwargs):
            if not is_valid_melody(response.answer):
                return FailedValidation("Please write the melody as note names, e.g. C D E.")
            return None

Timing within a page
--------------------

The demo's last page plays a sound, then records. ``events`` maps event names
to :class:`~psynet.timeline.Event` objects that change when things happen:
here, ``recordStart`` is triggered half a second after the prompt ends
(``promptEnd``), instead of immediately.
:class:`~psynet.timeline.ProgressDisplay` and
:class:`~psynet.timeline.ProgressStage` show the participant what is happening
when. Another common pattern prevents responding before a sound has finished:

.. code-block:: python

    events={"submitEnable": Event(is_triggered_by="promptEnd")}

See :doc:`/guides/pages/event_management` for the full list of events.

Look and language
-----------------

See :doc:`/guides/pages/theming` for themes, including how named colors in
progress stages follow the theme, and
:doc:`/guides/participants/internationalization` for marking text for
translation.

.. seealso::

   :doc:`/reference/api/page` and :doc:`/reference/api/modular_page` in the API
   reference.
