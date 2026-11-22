Keeping a task on one page
==========================

A fast task can keep its interface on screen while the trial maker presents
one trial after another, still assigning, scoring and saving one trial per
response. If you're still deciding whether to do this, see
:doc:`/design/presenting_trials`.

The browser doesn't reload between pages: PsyNet swaps in the next page's
content. Trial pages that share a layout and answer on a key press therefore
already look like one page. This works with any trial maker, including
adaptive ones such as staircases, where each answer decides what comes next.
Each answer waits for the server to send the next trial's page, unless the
trials are fixed in advance (see `Showing the next trial without waiting`_).

:download:`The adaptive brightness demo <../../../demos/features/staircase_on_one_page/experiment.py>`
is a complete example. It runs a staircase with PsyNet's
:class:`~psynet.trial.staircase.GeometricStaircaseTrialMaker`.

The trial's page
----------------

Write ``show_trial`` as usual. Give every trial's page the same HTML, and put
the data that changes from trial to trial in the page's ``contents``::

    def show_trial(self, experiment, participant):
        return ModularPage(
            "contrast",
            patches_html,
            contents={"left": self.definition["left"], "right": self.definition["right"]},
            show_next_button=False,
            js_page_modules=["/static/contrast.js"],
            bot_response=...,
            time_estimate=self.time_estimate,
        )

When the participant answers, PsyNet completes the trial and the trial maker
chooses the next one, as on any trial page. The browser then swaps in the next
trial's page, and because the layout is the same, only the stimulus appears to
change.

The page module
---------------

The page module answers on a key press instead of a Next button. Its
``activate`` function sets up what stays the same from trial to trial, such as
listeners, and returns an object with two functions:

- ``update`` shows one trial. It receives the trial's ``contents`` and a
  ``response`` handle for answering it.
- ``cleanup`` removes what ``activate`` set up.

.. code-block:: javascript

    export function activate({root}) {
        let response = null;
        function keydown(event) {
            if (response === null) return;
            // On the left arrow key:
            response.answer("left");
        }
        document.addEventListener("keydown", keydown);
        return {
            update({contents, response: handle}) {
                // Draw contents.left and contents.right.
                response = handle;
                handle.startClock();
            },
            cleanup: () => document.removeEventListener("keydown", keydown),
        };
    }

PsyNet calls ``activate``, and then ``update`` once the page accepts answers.
Keep anything specific to one trial in ``update``, and don't assume
``activate`` runs again before each trial. PsyNet doesn't wait for an
asynchronous ``update`` to finish before calling it again, for example after a
rejected answer, so an ``update`` that awaits an image should check afterwards
that it is still the latest call. A module without trials to show can still
return just the cleanup function.

When each trial's page comes from the server, PsyNet runs ``cleanup`` and
``activate`` again for every trial, so state kept in the module, such as a
running score, starts afresh. When the browser shows trials in advance (see
below), the module keeps running from trial to trial instead, and whatever
stays on the page carries over: focus on the last button clicked, a sound
still playing, a pressed-looking button. Reset these in ``update`` or when
answering.

PsyNet waits for ``cleanup`` before replacing the page. A ``cleanup`` that
returns a promise can therefore let feedback on the last answer finish
before the next page appears, for example
``cleanup: () => feedbackShown.then(removeListeners)``. When the browser
shows trials in advance, ``cleanup`` doesn't run between trials and the next
trial's ``update`` follows the answer at once, so play the feedback before
answering, and pass the time of the input as ``at`` so that it doesn't count
towards ``time_taken``:

.. code-block:: javascript

    async function choose(choice, event) {
        accepting = false;
        await showFeedback(choice);  // for example a card leaving the screen
        response.answer(choice, {at: event.timeStamp});
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
    answer, PsyNet shows its error message and calls ``update`` again with the
    same trial.

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
server. Pass ``prepare_trials_in_advance=True`` to a
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
trials (:attr:`~psynet.trial.static.StaticTrialMaker.n_upcoming_trials`, 5 by
default). The page module needs no changes. When the participant answers,
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

    async update({contents, upcomingContents, response: handle}) {
        latest = handle;  // declared in activate
        for (const next of upcomingContents) {
            // A failed download shows up when that trial loads its sound.
            psynet.media.loadAudio(next.sound_url).catch(() => {});
        }
        const sound = await psynet.media.loadAudio(contents.sound_url);
        // A rejected answer can show the trial again while the sound loads.
        if (latest !== handle) return;
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
page module instead, which needs the correct answer in ``contents``. If the participant
reloads the page, the answers not yet sent are lost, and they continue from
the first trial the server hasn't saved; anything entered for that trial is
lost and its clock starts again.

For this to work:

- Every trial page must render the same HTML and JavaScript, with everything
  that changes between trials in ``contents`` rather than in the HTML or
  ``js_vars``. The browser checks this when the server's reply arrives; if
  the HTML differs, it drops the answers given ahead, loads the server's page
  and logs a warning in the browser console.
- ``show_trial`` and ``show_after_trial`` must not change anything or
  choose at random, because PsyNet also calls them for upcoming trials,
  before they are answered.
  Choose random values in
  :meth:`~psynet.trial.main.Trial.finalize_definition` instead.
- Pages with a ``time_limit``, background recording, ``media`` (such as an
  :class:`~psynet.modular_page.AudioPrompt`) or a full page reload aren't
  shown in advance, because PsyNet sets these up for each page. Their files
  are still downloaded early.
- The browser doesn't run ahead after a trial whose class overrides
  :meth:`~psynet.trial.main.Trial.show_feedback`, even if it sometimes
  returns ``None``, as whether it does depends on the answer.

Also keep in mind:

- ``contents``, including that of upcoming trials, is visible to anyone who
  inspects the page. Only put the correct answer there if seeing it doesn't
  matter, for example because the participant could work it out anyway.
- Bots answer each page through ``bot_response`` and don't run the page
  module, so ``psynet test local`` doesn't test it. Test the module with a
  Playwright spec; see :doc:`/test/frontend`.

Trials prepared in advance can't use sync groups, repeat trials, performance
checks after every trial, or ``recruit_mode="n_trials"``. The browser only runs
ahead with in-place timeline transitions, which are on by default. The response
timeout of each trial counts from when the server first sends its page, and
the participant can be one more answer ahead than ``n_upcoming_trials``.
