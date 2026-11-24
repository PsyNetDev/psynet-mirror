Keeping a task on one page
==========================

A fast task can keep its interface on screen while the trial maker presents
one trial after another, still assigning, scoring and saving one trial per
response. If you're still deciding whether to do this, see
:doc:`/design/presenting_trials`.

This guide walks through
:download:`the adaptive brightness demo <../../../demos/features/staircase_on_one_page/experiment.py>`,
and shows its code. The participant sees two
grey patches and presses the left or right arrow key to say which is
brighter. A staircase, PsyNet's
:class:`~psynet.trial.staircase.GeometricStaircaseTrialMaker`, makes the next
pair more similar after each correct answer.

Such a task is a :class:`~psynet.page.JSPage`: you write the page's HTML and
one JavaScript module, and the module draws each trial from the data PsyNet
gives it and answers it. When one trial's page has the same HTML, module and
``page_config`` as the last, the page stays on screen and only the data
changes. This works with any trial maker, including
adaptive ones such as staircases, where each answer decides what comes next.

Between ordinary pages, PsyNet usually doesn't reload the browser tab
either, but it does replace the page's content and start its JavaScript
afresh. A ``JSPage``
goes further: its content and module stay as they are, and the module is
only given the next trial's data.

After each answer, the module waits for the server to send the next trial,
unless the trials are fixed in advance (see
`Showing the next trial without waiting`_). Meanwhile the page stays as the
module left it, so hide the stimulus on answering if it shouldn't stay
visible.

The trial's page
----------------

Write ``show_trial`` as usual, returning a :class:`~psynet.page.JSPage`.
Give every trial's page the same HTML, and put the data that changes from
trial to trial in the page's ``contents``. In the demo, the HTML holds the
two patches, and ``contents`` holds their shades of grey:

.. literalinclude:: ../../../demos/features/staircase_on_one_page/experiment.py
   :pyobject: ContrastTrial.show_trial

The HTML can be a string, a ``dominate`` tag or a list of them. Configuration that is the
same for every trial, such as the task's timings, goes in ``page_config``.
Both ``contents`` and ``page_config`` must be JSON-serialisable, as they are
sent to the browser.

When the participant answers, PsyNet completes the trial and the trial maker
chooses the next one, as on any trial page. Because the next trial's page has
the same HTML, module and ``page_config``, the page stays on screen and the
module shows the next trial. If any of the three differs, for example on a
break page or after the last trial, PsyNet replaces the page as usual.

The module
----------

The demo's module, ``static/contrast.js``, answers on an arrow key press
instead of a Next button. Its ``activate`` function sets up what stays the
same from trial to trial, such as listeners, and returns an object with two
functions:

- ``update`` shows one trial. It receives the trial's ``contents`` and a
  ``response`` handle for answering it.
- ``cleanup`` removes what ``activate`` set up outside the page, such as
  listeners on ``document``, which would otherwise keep running on the
  pages that follow.

.. literalinclude:: ../../../demos/features/staircase_on_one_page/static/contrast.js
   :language: javascript

Answering hides the patches and clears ``response``, so that further key
presses are ignored until ``update`` shows the next pair.

The module keeps running from trial to trial. PsyNet calls ``activate`` once,
when the first trial appears; ``update`` for each trial, including the
first; and ``cleanup`` once, when the participant leaves the page. This is
the same whether the next trial comes from the server or was prepared in
advance (see below). A ``JSPage`` whose module doesn't return ``update``
fails with an error. If ``update`` throws, or returns a promise that
rejects, while its trial is still the latest, the participant has nothing
to answer, so PsyNet asks them to reload the page.

So put anything specific to one trial in ``update``. State kept in the
module, such as a running score, carries over from trial to trial, and so
does whatever stays on the page: focus on the last button clicked, a sound
still playing, a pressed-looking button. Reset these in ``update`` or when
answering.

``update`` also receives a ``signal``, a standard
`AbortSignal <https://developer.mozilla.org/en-US/docs/Web/API/AbortSignal>`_
that PsyNet aborts when it calls ``update`` again or the participant leaves
the page. PsyNet doesn't wait for an asynchronous ``update`` to finish first,
so an ``update`` that awaits something, such as an image loading, should
return without drawing if ``signal.aborted`` is then true; otherwise it could
draw its trial over the next one::

    async update({contents, response, signal}) {
        const image = new Image();
        image.src = contents.image_url;
        await image.decode();
        if (signal.aborted) return;  // a newer trial has started
        // Show the image, then:
        response.startClock();
    },

The signal can also be passed on, for example as ``fetch(url, {signal})``,
to cancel a download that is no longer needed. The ``AbortError`` this
raises in an ``update`` that has been superseded is ignored.

The next trial's ``update`` can follow an answer at once, so play any
feedback on the answer before answering. Pass the time of the input as
``at``, so that the feedback doesn't count towards ``time_taken``:

.. code-block:: javascript

    async function choose(choice, event) {
        const handle = response;
        response = null;  // ignore further input until the next update
        await showFeedback(choice);  // for example a card leaving the screen
        handle.answer(choice, {at: event.timeStamp});
    }

The ``response`` handle has three methods:

``response.startClock(at)``
    Starts the clock for the trial's ``time_taken``. Call it when the stimulus
    is shown or starts playing; calling it again restarts the clock. Without
    it, ``time_taken`` runs from when ``update`` was called. ``at`` is an
    optional ``performance.now()`` timestamp to start from instead of now,
    such as the time a ``requestAnimationFrame`` callback receives.

``response.mark(name, {at})``
    Records when a step of the trial happened, in seconds since the clock
    started, for trials answered in several steps, such as a choice followed
    by a confidence rating. The times are saved with the answer as
    ``metadata["marks"]``, which
    :meth:`~psynet.timeline.Page.format_answer` receives and which is stored
    on the trial's ``response``. ``at`` works as for ``answer``.

``response.answer(value, {at})``
    Submits ``value`` as the trial's answer, with ``time_taken`` up to now or
    to the optional ``performance.now()`` timestamp ``at``. Passing the key
    press's ``event.timeStamp`` measures the reaction time to the press itself
    rather than to when the code ran. Each handle answers once: it
    returns ``true`` the first time, and ``false`` afterwards or once its
    trial is no longer shown. PsyNet sends the
    answer in the background, so the page should stop accepting input until
    ``update`` is called with the next trial. If the server rejects the
    answer, for example because the page's ``validate`` returns an error,
    PsyNet shows the error message and calls ``update`` again with the same
    trial.

To measure reaction times, start the clock in a ``requestAnimationFrame``
callback with the time it receives, after putting the stimulus on the page,
and answer with the key press's ``event.timeStamp``. The trial's
``time_taken`` is then the time from the frame that shows the stimulus to the
press. :download:`The flanker demo <../../../demos/experiments/flanker/experiment.py>`
measures reaction times this way.

Showing the next trial without waiting
--------------------------------------

When nothing the participant answers changes which trials come next, the
browser can show the next trial straight away instead of waiting for the
server. Other trial pages, such as an
:class:`~psynet.modular_page.ImagePrompt` with a
:class:`~psynet.modular_page.PushButtonControl`, do this too (see
:ref:`showing_the_next_trials_without_waiting`), but they rebuild the page for
each trial. A ``JSPage`` stays on screen, along with anything it holds, such
as a game's state. Pass ``prepare_trials_in_advance=True`` to a
:class:`~psynet.trial.static.StaticTrialMaker`::

    trial_maker = StaticTrialMaker(
        id_="ratings",
        trial_class=RatingTrial,
        nodes=nodes,
        expected_trials_per_participant=len(nodes),
        prepare_trials_in_advance=True,
    )

Only :class:`~psynet.trial.static.StaticTrialMaker` can do this. Adaptive
trial makers, such as chains and staircases, choose each trial from the
answers before it, so their pages always wait for the server.

The trial maker then creates all of a participant's trials, in order, when they
reach it, and each trial page also carries the ``contents`` of the next few
trials (:attr:`~psynet.trial.static.StaticTrialMaker.n_upcoming_trials`, 2 by
default). The module needs no changes. When the participant answers,
PsyNet calls ``update`` with the next trial's ``contents`` at once, and sends
the answers to the server in the background, one at a time and in order.
``update`` also receives ``upcomingContents``, the contents of the known
trials after the one it shows, for example to preload their images:

.. code-block:: javascript

    update({contents, upcomingContents, response: handle}) {
        for (const next of upcomingContents) new Image().src = next.image_url;
        // Show contents as before.
    },

Without ``prepare_trials_in_advance``, ``upcomingContents`` is empty.

Sounds work the same way: ``psynet.media.loadAudio(url)`` downloads and
decodes a sound once per URL and resolves with an object whose ``play()``
plays it, so ``update`` can start the next trial's sound at once:

.. code-block:: javascript

    async update({contents, upcomingContents, response: handle, signal}) {
        for (const next of upcomingContents) {
            // A failed download shows up when that trial loads its sound.
            psynet.media.loadAudio(next.sound_url).catch(() => {});
        }
        const sound = await psynet.media.loadAudio(contents.sound_url);
        if (signal.aborted) return;  // a newer trial has started
        sound.play();
        handle.startClock();
    },

``play()`` returns the playing sound, whose ``finished`` promise resolves once
it has ended or been stopped, for example to accept answers only after the
sound: ``sound.play().finished.then(enableButtons)``. The promise from
``loadAudio`` rejects if the file can't be downloaded or decoded, so the page
can offer to try again. Call ``psynet.media.requireAudio()`` in ``activate``
so that PsyNet asks the participant to enable sound before the first trial.

:download:`The rapid ratings demo <../../../demos/features/rapid_ratings/experiment.py>`
rates pictures this way, with a break halfway through.

Each answer is still checked and saved as usual. If the server rejects one,
PsyNet also drops the answers given after it. The browser stops running ahead
after a trial with feedback or with pages from
:meth:`~psynet.trial.main.TrialMaker.show_after_trial`, and at the end of the
trials. With a feedback
page after every trial, it never runs ahead, and the participant waits for
the server twice per trial. To give feedback straight away, show it from the
module instead, which needs the correct answer in ``contents``.

Answers are sent one at a time, as soon as each earlier one is saved, so
they only pile up in the browser while the server is slow to reply. While
any are waiting, the browser asks the participant to confirm before the page
reloads or closes. If they leave anyway, the waiting answers are lost, and
when they come back they continue from the first trial the server hasn't
saved, with its clock started again.

For this to work:

- Every trial page must be a ``JSPage`` with the same HTML, module and
  ``page_config``, as above. PsyNet renders each upcoming trial's page once
  to compare them; a trial whose page differs isn't shown in advance, but
  waits for the server, and PsyNet logs a warning. If no trial at all could
  be shown in advance, bot tests such as ``psynet test local`` fail. A
  stimulus written into the HTML makes every trial's HTML differ, so pass it
  in ``contents`` instead.
- ``show_trial`` and ``show_after_trial`` must not change anything or
  choose at random, because PsyNet also calls them for upcoming trials,
  before they are answered.
  Choose random values in
  :meth:`~psynet.trial.main.Trial.finalize_definition` instead.
- The trial maker picks all the trials' nodes when the participant reaches
  it, before any is answered, so ``custom_node_filter`` and ``select_node``
  can't adapt to the participant's answers.
- Pages with a ``time_limit`` or background recording work, but PsyNet sets
  these up for each page, so such a page isn't shown in advance and replaces
  the last one: the module starts afresh for each trial.
- A ``JSPage`` doesn't need the page's ``media``. Put the files' URLs in
  ``contents`` and load them with ``psynet.media.loadAudio`` or
  ``new Image()``, as above, so that the page can stay on screen and show
  trials in advance.
- The browser doesn't run ahead after a trial whose class overrides
  :meth:`~psynet.trial.main.Trial.show_feedback`, even if it sometimes
  returns ``None``, as whether it does depends on the answer.

Also keep in mind:

- ``contents``, including that of upcoming trials, is visible to anyone who
  inspects the page. Only put the correct answer there if seeing it doesn't
  matter, for example because the participant could work it out anyway.
- Bots answer each page through ``bot_response`` and don't run the module,
  so ``psynet test local`` doesn't test it. Test the module with a
  Playwright spec; see :doc:`/test/frontend`.

Trials prepared in advance can't use sync groups, repeat trials, performance
checks after every trial, or ``recruit_mode="n_trials"``. The browser only runs
ahead with in-place timeline transitions, which are on by default. The response
timeout of each trial counts from when the server first sends its page; once
one times out, the participant's trials waiting their turn fail with it.
The participant can be one more answer ahead than ``n_upcoming_trials``.
