# Adaptive brightness comparison

Run `psynet debug local` in this directory, then press the left or right arrow key to choose the brighter patch. A correct answer makes the next pair more similar, and a mistake makes it less similar. After eight answers, the feedback page shows your score and the brightness differences you saw, in order.

## How it works

[experiment.py](experiment.py) runs one staircase per participant with PsyNet's `GeometricStaircaseTrialMaker`. Each node's parameter is the brightness gap between the patches. `ContrastNode` sets `k = 1` and lists the gaps from easiest to hardest. PsyNet grows the staircase from each trial's score and tracks its reversals. `ContrastTrial` picks the brighter side when it creates the trial, so reloading the page shows the same pair.

The trial maker's `present_trials` plays one `OnDemandTrialGame`. Unlike the [arrow flanker](../live_trial_game), which creates every trial up front, this game has only the first trial when the first pair appears. Each answer completes its trial, and the trial maker chooses the next one and sends it to the same page. The staircase ends after eight trials. The demo turns off the trial maker's final threshold check, because eight answers may contain no reversals; the [pitch discrimination demo](../../experiments/staircase_pitch_discrimination) shows the same trial maker with threshold scoring.

[contrast.js](static/contrast.js) draws each trial in `game.onTrial` and starts the response clock in the frame that shows the patches. After each key press, the page waits for the server to choose the next pair. If you reload, you see the same unanswered pair. If the server's reply is lost, the page sends the answer again with its original response time.

For the same kind of task with one page per trial, see the [adaptive trial demo](../trial_cue_adaptive).
