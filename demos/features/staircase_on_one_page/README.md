# Adaptive brightness comparison

Run `psynet debug local` in this directory, then press the left or right arrow key to choose the brighter patch. A correct answer makes the next pair more similar, and a mistake makes it less similar. After eight answers, the feedback page shows your score and the brightness differences you saw, in order.

## How it works

[experiment.py](experiment.py) runs one staircase per participant with PsyNet's `GeometricStaircaseTrialMaker`. Each node's parameter is the brightness gap between the patches. `ContrastNode` sets `k = 1` and lists the gaps from easiest to hardest. `ContrastTrial` picks the brighter side when it creates the trial, so reloading the page shows the same pair. The demo turns off the trial maker's final threshold check, because eight answers may contain no reversals; the [pitch discrimination demo](../../experiments/staircase_pitch_discrimination) shows the same trial maker with threshold scoring.

Each trial is an ordinary trial page, so the trial maker works as usual. The browser doesn't reload between pages: PsyNet swaps in each new trial's page, and the trial pages share one layout, so only the patches change. Each page passes its pair in `contents`, and [contrast.js](static/contrast.js) draws it from `psynet.page.contents` and answers on a key press, without a Next button.

Each answer still waits for the server to choose the next pair. For a fixed sequence, where the browser can receive the upcoming stimuli in advance, see the [arrow flanker demo](../live_trial_game).
