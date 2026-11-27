# Adaptive brightness comparison

Run `psynet debug local` in this directory, then press the left or right arrow key to choose the brighter patch. A correct answer makes the next pair more similar, and a mistake makes it less similar. After eight answers, the feedback page shows your score and the brightness differences you saw, in order.

## How it works

[experiment.py](experiment.py) runs one staircase per participant with PsyNet's `GeometricStaircaseTrialMaker`. Each node's parameter is the brightness gap between the patches. `ContrastNode` sets `k = 1` and lists the gaps from easiest to hardest. `ContrastTrial` picks the brighter side when it creates the trial, so reloading the page shows the same pair. The demo turns off the trial maker's final threshold check, because eight answers may contain no reversals; the [pitch discrimination demo](../../experiments/staircase_pitch_discrimination) shows the same trial maker with threshold scoring.

Each trial is an ordinary trial page, so the trial maker works as usual. The browser doesn't reload between pages: each trial is a `JSPage` with the same HTML and module, so one page stays on screen and only the patches change. Each page passes its pair in `contents`. Each page passes the trial number in `contents` too, since the HTML can't change between trials. In [contrast.js](static/contrast.js), `activate` listens for the arrow keys and returns an `update` function that draws the pair, shows the trial number, starts the response clock and answers on a key press, without a Next button. Each answer waits for the server to choose the next pair. Meanwhile the patches disappear and the chosen side's label turns bold, and the next pair appears no sooner than 200 ms after the answer, so each trial visibly ends.
