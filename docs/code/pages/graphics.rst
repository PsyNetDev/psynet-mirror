========
Graphics
========

A :class:`~psynet.graphics.GraphicPrompt` shows an animated graphic in a
:class:`~psynet.modular_page.ModularPage`, and a
:class:`~psynet.graphics.GraphicControl` shows one that the participant
answers by clicking. PsyNet draws graphics with the JavaScript library
`Raphaël <https://dmitrybaranovskiy.github.io/raphael/>`_, whose
`reference <https://dmitrybaranovskiy.github.io/raphael/reference.html>`_
documents the attributes that objects accept.

The examples on this page come from the ``demos/experiments/graphics`` demo.

Drawing frames
--------------

A graphic is a list of :class:`~psynet.graphics.Frame` objects, shown in
sequence. Each frame contains :class:`~psynet.graphics.GraphicObject`
instances that are drawn together: :class:`~psynet.graphics.Text`,
:class:`~psynet.graphics.Image`, :class:`~psynet.graphics.Path`,
:class:`~psynet.graphics.Circle`, :class:`~psynet.graphics.Ellipse` and
:class:`~psynet.graphics.Rectangle`. Each object takes an ID, which must be a
valid variable name.

``dimensions`` sets the coordinate system in which objects are placed. It also
sets the aspect ratio, but not the size on screen: ``viewport_width`` sets the
width as a fraction of the browser window (default ``0.6``). ``attributes``
sets SVG attributes such as ``fill`` or ``font-size``; the
`Raphaël attribute reference <https://dmitrybaranovskiy.github.io/raphael/reference.html#Element.attr>`_
lists them.

.. literalinclude:: ../../../demos/experiments/graphics/experiment.py
   :start-at: prompt=GraphicPrompt(
   :end-before: time_estimate=5,
   :dedent: 12

A frame lasts ``duration`` seconds, or indefinitely if ``duration`` is
``None`` (the default). Set ``loop=True`` on the prompt or control to return to
the first frame after the last one. An object with ``persist=True`` stays on
screen in later frames.

Clickable objects
-----------------

In a :class:`~psynet.graphics.GraphicControl`, objects created with
``click_to_answer=True`` submit the page when clicked. The answer is a
dictionary containing ``clicked_object``, the ID of the object, and
``click_coordinates``, the position of the click. This page combines a
graphic prompt with a graphic control:

.. literalinclude:: ../../../demos/experiments/graphics/experiment.py
   :start-at: text="This page contains both a GraphicPrompt and a GraphicControl.",
   :end-before: time_estimate=5,
   :dedent: 12
   :prepend: prompt=GraphicPrompt(

Animation
---------

An :class:`~psynet.graphics.Animation` moves an object from its initial
attributes to ``final_attributes`` over ``duration`` seconds, with an optional
``easing``. An object's ``animations`` list runs in order, and
``loop_animations=True`` repeats it. Circles and ellipses are positioned with
``cx`` and ``cy`` rather than ``x`` and ``y``.

Images must be listed in the ``media`` argument, which loads them once before
the graphic is drawn. Objects refer to them by ``media_id``:

.. literalinclude:: ../../../demos/experiments/graphics/experiment.py
   :start-at: control=GraphicControl(
   :end-before: time_estimate=5,
   :dedent: 12

Audio
-----

A frame's ``audio_id`` plays a sound from ``media`` when the frame starts:

.. literalinclude:: ../../../demos/experiments/graphics/experiment.py
   :start-at: text="This GraphicPrompt has synchronized audio.",
   :end-at: media=MediaSpec(audio={"bier": "/static/bier.wav"}),
   :dedent: 12
   :prepend: prompt=GraphicPrompt(
   :append: ),

Timing a control from a graphic
-------------------------------

With ``prevent_control_response=True``, the page's control stays inactive
until a frame with ``activate_control_response=True`` is reached.
``prevent_control_submit`` and ``activate_control_submit`` do the same for
submitting. This page counts down, then starts recording:

.. literalinclude:: ../../../demos/experiments/graphics/experiment.py
   :start-at: text="This example shows how the GraphicPrompt can be used to trigger timing in the Control object.",
   :end-before: time_estimate=6,
   :dedent: 12
   :prepend: prompt=GraphicPrompt(

Pages with only a graphic
-------------------------

:class:`~psynet.graphics.GraphicPage` is a shortcut for a
:class:`~psynet.modular_page.ModularPage` with an empty prompt and a
:class:`~psynet.graphics.GraphicControl`. It takes a label, a
``time_estimate``, and the arguments of
:class:`~psynet.graphics.GraphicControl`, such as ``auto_advance_after`` for
graphics that advance by themselves.

.. seealso::

   :doc:`/examples/exercises/graphics` and :doc:`/reference/api/graphics`.
