Writing pages
=============

The examples on this page come from the ``demos/features/pages`` demo, which
you can run with ``psynet debug local`` from the demo directory:

.. literalinclude:: ../../demos/features/pages/experiment.py
   :pyobject: get_timeline

Kinds of page
-------------

An :class:`~psynet.page.InfoPage` shows text. Wrap HTML in
``markupsafe.Markup`` to format it:

.. code-block:: python

    InfoPage(Markup("Welcome to the <strong>experiment</strong>!"), time_estimate=5)

Pages and prompts also accept `dominate <https://pypi.org/project/dominate/>`_
tags, which build longer structured content without writing HTML strings:

.. code-block:: python

    from dominate import tags

    InfoPage(
        tags.div(tags.h2("Instructions"), tags.p("Press Next to begin.")),
        time_estimate=5,
    )

Use one approach per piece of content. ``dominate`` escapes strings placed
inside its tags, including ``Markup`` strings, so their HTML is shown as text.
Only put trusted text in ``Markup``, never participant-provided data.

A :class:`~psynet.modular_page.ModularPage` takes a label, a prompt (plain text
or a prompt object), and optionally a control. The
:doc:`API reference </reference/api/modular_page>` documents every prompt and
control. Commonly used prompts:

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

A consent page usually opens the timeline. The built-in forms in
:mod:`psynet.consent` name the institutions they were written for, so most
studies need their own; see :doc:`/code/participants/consent`.

Pages that go beyond prompts and controls are
:doc:`custom front ends </code/pages/custom_front_ends>`.

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

To validate a response, subclass the control and implement ``validate``. The
method returns ``None`` to accept the response, or a message for the
participant to reject it. This control from ``demos/features/validate``
rejects the answer ``"green"``:

.. literalinclude:: ../../demos/features/validate/experiment.py
   :pyobject: NoGreenControl

The message can also be wrapped in :class:`~psynet.timeline.FailedValidation`.

Timing within a page
--------------------

The demo's last page plays a sound, then records. ``events`` maps
:doc:`event names </code/pages/event_management>` to
:class:`~psynet.timeline.Event` objects that change when things happen:
here, ``recordStart`` is triggered half a second after the prompt ends
(``promptEnd``), instead of immediately.
:class:`~psynet.timeline.ProgressDisplay` and
:class:`~psynet.timeline.ProgressStage` show the participant what is happening
when. Another common pattern prevents responding before a sound has finished:

.. code-block:: python

    events={"submitEnable": Event(is_triggered_by="promptEnd")}

Look and language
-----------------

Page colors come from the theme's
:doc:`CSS tokens </code/pages/theming>`. To change them, redefine the tokens
in a stylesheet under ``static/`` and list it in the experiment class's
``css_links``.

To :doc:`translate </code/participants/internationalization>` page text, wrap
each string in ``_``, obtained from :func:`~psynet.utils.get_translator`.

.. seealso::

   :doc:`/reference/api/page` and :doc:`/reference/api/modular_page` in the API
   reference.

   The :doc:`/skills/develop-experiment-front-end` and
   :doc:`/skills/playwright-testing` skills.

