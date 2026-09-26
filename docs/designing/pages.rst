.. _concept_pages:

Pages
=====

A **page** is one screen of the experiment. The participant sees it, responds
or clicks to continue, and PsyNet records the response and moves on to the
next element of the :doc:`timeline`. In a trial maker, each trial shows one or
more pages built from its node; see :doc:`trials`.

Kinds of page
-------------

- **Information pages** show text, such as instructions, and collect no
  response.
- **Modular pages** combine a **prompt**, what the participant sees or hears,
  with a **control**, how they respond. Because prompts and controls can be
  combined freely, most experiment screens need no custom web code. For
  example:

  - prompts: text, an image, a sound, a video, a color, a short melody played
    by a synthesizer, music notation, or an animation generated in code;
  - controls: buttons, checkboxes, radio buttons, dropdown menus, sliders,
    rating scales, free text, numbers, audio or video recording, and
    multi-item surveys.

- **Consent pages** ask participants for informed consent. PsyNet refuses to
  deploy an experiment without one, and some recruitment platforms require a
  particular consent page.
- **End pages** finish a participant's experiment; see :doc:`timeline`.
- **Custom pages** use your own HTML and JavaScript, or embed other software
  such as a Unity game, when no combination of prompt and control fits.

What happens to a response
--------------------------

Each response is stored with the page's **label**, the answer, and details
such as how long the participant took. A page can also save its answer into a
participant variable, so later parts of the timeline can use it.

A page can **validate** a response before accepting it, for example rejecting
an empty text box or an answer in the wrong format. The participant sees a
message and tries again.

Timing within a page
--------------------

Pages with sound, video, or recording often need things to happen in order:
play the sound, then start recording half a second later, then let the
participant continue. PsyNet coordinates this with **events**, such as "the
sound has finished" or "recording has started", which can trigger other
actions, optionally after a delay. A progress bar can show the participant
what is happening when.

Look and language
-----------------

The appearance of all pages follows the experiment's **theme**, which sets
colors, fonts, and dark mode in one place; see :doc:`/guides/pages/theming`.
Page text can be marked for translation, so the same experiment can run in
several languages; see :doc:`/guides/participants/internationalization`.

What to check when reviewing pages
----------------------------------

- Does every page have a distinct label? Responses are identified by label in
  the data, and PsyNet does not require labels to be unique.
- Can participants respond before they have seen or heard the whole stimulus,
  when they should not be able to?
- Do pages reject answers the analysis cannot use?

.. seealso::

   :doc:`in_code/pages` shows how each of these ideas appears in
   ``experiment.py``, using the ``demos/features/pages`` demo.
