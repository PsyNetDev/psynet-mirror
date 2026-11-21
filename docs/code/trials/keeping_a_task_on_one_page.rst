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
``activate`` runs again before each trial. A module without trials to show
can still return just the cleanup function.

The ``response`` handle has two methods:

``response.startClock()``
    Starts the clock for the trial's ``time_taken``. Call it when the stimulus
    is visible. Without it, ``time_taken`` runs from when ``update`` was
    called.

``response.answer(value)``
    Submits ``value`` as the trial's answer. Each handle answers once: it
    returns ``true`` the first time and ``false`` afterwards. PsyNet sends the
    answer in the background, so the page should stop accepting input until
    ``update`` is called with the next trial. If the server rejects the
    answer, PsyNet shows its error message and calls ``update`` again with the
    same trial.

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

The trial maker then creates all of a participant's trials, in order, when they
reach it, and each trial page also carries the ``contents`` of the next few
trials (:attr:`~psynet.trial.static.StaticTrialMaker.n_upcoming_trials`, 5 by
default). The page module needs no changes. When the participant answers,
PsyNet calls ``update`` with the next trial's ``contents`` at once, and sends
the answers to the server in the background, one at a time and in order.
``update`` also receives ``upcoming``, the contents of the known trials after
the one it shows, for example to preload their images:

.. code-block:: javascript

    update({contents, upcoming, response: handle}) {
        for (const next of upcoming) new Image().src = next.image_url;
        // Show contents as before.
    },

Without ``prepare_trials_in_advance``, ``upcoming`` is empty.

:download:`The rapid ratings demo <../../../demos/features/rapid_ratings/experiment.py>`
rates pictures this way, with a break halfway through.
:class:`~psynet.prescreen.vocabtest.VocabTest` works the same way, with its page
script in ``psynet/resources/scripts/vocabtest.js``.

Each answer is still checked and saved as usual. If the server rejects one,
PsyNet also drops the answers given after it. The browser only runs ahead while
the next page would be another trial page with the same HTML: it waits for the
server before pages from
:meth:`~psynet.trial.main.TrialMaker.show_before_trial`, before feedback
pages, and at the end of the trials.

Trials prepared in advance can't use sync groups, repeat trials, performance
checks after every trial, or ``recruit_mode="n_trials"``. The browser only runs
ahead with in-place timeline transitions, which are on by default. The response timeout
of each trial counts from when it is first shown.
