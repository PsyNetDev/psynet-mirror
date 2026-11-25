.. _concept_pages:

Pages
=====

A **page** is one screen of the experiment. The participant sees it, responds
or clicks to continue, and PsyNet records the response and moves on to the
next element of the :doc:`timeline <timeline>`. A :doc:`trial <trials>` usually
shows one page, but it can show several, and several trials can share one
page; see :doc:`presenting_trials`.

.. _choosing_a_kind_of_page:

Choosing a kind of page
-----------------------

PsyNet offers three main ways to build a page, depending on how much of it
you want to write yourself.

- **Assemble it from ready-made parts** (:class:`~psynet.modular_page.ModularPage`).
  Most pages show something, such as text, an image or a sound, and then
  collect an answer, such as a button press, a slider value or a typed reply.
  PsyNet provides ready-made pieces for both halves: a **prompt**, what the
  participant sees or hears, and a **control**, how they respond. You combine
  them into a page, and can write pieces of your own to mix with the built-in
  ones. This is the quickest way to build most questionnaires and
  experiments, and PsyNet takes care of presentation and loading.
  :class:`~psynet.page.InfoPage`, for simply showing text, is a shortcut for
  this kind of page. For example:

  - prompts: text, an image, a sound, a video, a color, a short melody played
    by a synthesizer, music notation, or an animation generated in code;
  - controls: buttons, checkboxes, radio buttons, dropdown menus, sliders,
    rating scales, free text, numbers, audio or video recording, and
    multi-item surveys.

- **Write the whole page yourself** (:class:`~psynet.page.JSPage`). If you'd
  rather design the screen from scratch, write its HTML and a JavaScript file
  that brings it to life. PsyNet passes your JavaScript the page's data, such
  as which stimulus to show, and your JavaScript draws it and sends back the
  participant's answer. This suits a one-off page, such as a custom sign-up
  form, as well as trials. When one trial follows another on the same design,
  the page stays on screen and only the data changes. That makes trials
  follow each other instantly, which suits fast, timing-sensitive tasks such
  as reaction-time tests or long runs of quick ratings. This is also the
  natural choice when an AI assistant writes your front end for you. See
  :ref:`custom_front_ends_js_page` and
  :doc:`/code/trials/keeping_a_task_on_one_page`.

- **Run a live game between participants**
  (:class:`~psynet.live_game.LiveGamePage`). For tasks where several
  participants interact in real time, such as coordination and cooperation
  games, negotiations, or solving a puzzle together, you write the page's
  HTML and JavaScript as for a ``JSPage``. But instead of receiving one trial
  at a time, your JavaScript receives a continuous stream of updates as the
  game unfolds. The server keeps every player in sync and decides each
  player's result when the game ends. See :doc:`/code/multiplayer/live_games`.

A few specialised pages connect PsyNet to other tools, such as
:class:`~psynet.page.JsPsychPage` for experiments written with jsPsych, or
:class:`~psynet.page.UnityPage` for games built in Unity. Underneath them all
is the basic :class:`~psynet.timeline.Page`, which renders a template of your
own. You'll rarely need it directly.

Two kinds of page have special roles in every experiment:

- **Consent pages** ask participants for informed consent. PsyNet won't
  deploy an experiment without a consent page unless you explicitly opt out,
  and some recruitment platforms require a particular one.
- **End pages** finish a participant's experiment; see :doc:`timeline`.

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
colors, fonts, and dark mode in one place; see :doc:`/code/pages/theming`.
Page text can be marked for translation, so the same experiment can run in
several languages; see :doc:`/code/participants/internationalization`.

What to check when reviewing pages
----------------------------------

- Does every page have a distinct label? Responses are identified by label in
  the data, and PsyNet does not require labels to be unique.
- Can participants respond before they have seen or heard the whole stimulus,
  when they should not be able to?
- Do pages reject answers the analysis cannot use?

.. seealso::

   :doc:`/code/writing_pages` shows how each of these ideas appears in
   ``experiment.py``, using the ``demos/features/pages`` demo.

   The :doc:`/skills/develop-experiment-front-end` skill helps choose and
   build pages, and :doc:`/skills/playwright-testing` checks them in a
   browser.

