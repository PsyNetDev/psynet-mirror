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
Only put trusted text in ``Markup``, never participant-provided data. To show
participant text inside your own HTML, let ``Markup.format`` escape it rather
than using an f-string:

.. code-block:: python

    Markup("Another participant wrote: <strong>{}</strong>").format(answer)

``Markup.format`` escapes a ``dominate`` tag too, so pass
``Markup(tag.render())`` to insert one.

The same rule applies to control labels, such as the ``labels`` of
:class:`~psynet.modular_page.PushButtonControl`, to
:class:`~psynet.modular_page.Button` text and to
:class:`~psynet.page.WaitPage` content: a plain string is shown as text, and
HTML needs ``Markup`` or a ``dominate`` tag:

.. code-block:: python

    PushButtonControl(
        choices=["cat", "dog"],
        labels=[Markup('<img src="/static/cat.png" alt="Cat">'), "Dog"],
    )

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
``successful_validation``. Responses submitted on the pages of a trial also
store that trial's ID in ``trial_id`` (feedback pages are not part of the
trial), so you can group a trial's responses in the export. PsyNet stores the
summed time of the trial's accepted pages in the trial's ``time_taken`` column
and links the last page's response as its ``response``; see
:class:`~psynet.trial.main.Trial` and :class:`~psynet.timeline.Response`.

Choice controls save the element of ``choices`` that the participant picked,
keeping its type: ``DropdownControl([1, 2, 3])`` saves the integer ``3``, and
:class:`~psynet.modular_page.CheckboxControl` saves a list of choices.
:class:`~psynet.modular_page.TimedPushButtonControl` is the exception; it saves
the timing of each button press. The browser submits choices as text, so a
control whose choices share the same text, such as ``1`` and ``"1"``, raises
``ValueError``.

The experiment rejects an answer that is not one of the control's choices, such
as an offer of 11 from a tampered request in a 0–10 game, so you don't need to
check this yourself. The check runs before any ``validate``, including a page
that overrides ``validate``, so a ``validate`` cannot accept such an answer. An
empty answer, such as ``None`` from a page that submits without a click, still
passes this check; where a control has ``force_selection``, that decides whether
to accept it. A radio button control with ``show_free_text_option=True`` accepts
any text. If the saved answer is something other than a choice, for example
because the control or the page overrides ``format_answer`` to wrap the choice
in a dictionary, pass ``restrict_to_choices=False`` to the control, or set the
class attribute ``restrict_to_choices = False`` on your control subclass.
``TimedPushButtonControl`` does this for you. See
:class:`~psynet.modular_page.OptionControl`.

The experiment builds the page again when the response arrives, re-running a
:class:`~psynet.timeline.PageMaker` function or a trial's ``show_trial``, and
checks the answer against the choices of that new page. The choices must
therefore be the same each time the page is built. If you pick them at random,
for example with ``random.sample``, pick them once and reuse them: choose them in
the trial's ``finalize_definition``, or store them in ``participant.var``
(keyed by the repetition, if the page repeats in a loop).
Otherwise the participant's click can be rejected with
"You need to select an answer!"; the server log then shows a warning with the
page label, the answer and the choices. If the choices cannot be kept stable,
pass ``restrict_to_choices=False``.

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

