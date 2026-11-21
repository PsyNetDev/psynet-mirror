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
Each answer waits for the server to send the next trial's page.

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
    is visible. Without it, ``time_taken`` runs from when the page was set up.

``response.answer(value)``
    Submits ``value`` as the trial's answer, like ``psynet.nextPage(value)``.
    It resolves to ``false`` if the answer wasn't accepted, so the page can
    let the participant answer again.
