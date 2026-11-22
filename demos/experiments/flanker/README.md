# Flanker task

Run `psynet debug local` in this directory, then report which way the middle arrow points in 16 rows of arrows: press F for left and J for right, or tap the buttons. The arrows around it point the same way in half the trials and the other way in the rest. A break comes halfway through, and the last page shows your accuracy and mean reaction times. People usually answer more slowly when the arrows disagree.

## How it works

[experiment.py](experiment.py) uses a `StaticTrialMaker` with `node_order="random"` and `prepare_trials_in_advance=True`, so it creates all of a participant's trials in random order when they reach it, and each trial page also carries the arrows of the next few trials. `FlankerTrialMaker.show_after_trial` adds the break.

In [flanker.js](static/flanker.js), `update` shows a blank gap, a fixation cross and then the arrows. It starts the response clock with the time of the frame that shows the arrows and answers with the key press's or tap's timestamp, so each trial's `time_taken` is its reaction time. If nobody answers within 1.5 seconds, the trial is answered with `"timeout"`. PsyNet sends the answers to the server in the background and calls `update` with the next trial straight away, so the timing between trials doesn't depend on the server.

`Exp.get_basic_data` exports one row per trial with the condition, the answer, whether it was correct and the reaction time in milliseconds.

See [Keeping a task on one page](https://psynetdev.gitlab.io/PsyNet/alpha/code/trials/keeping_a_task_on_one_page.html) for the full guide.

## Timing

Reaction times use the browser's high-resolution clock and are measured from the start of the frame that paints the arrows to the key press. They still include the delays of the participant's screen and keyboard, which vary between devices, typically by tens of milliseconds. That is fine for comparing conditions within a participant, as here, but not for comparing absolute reaction times across devices.
