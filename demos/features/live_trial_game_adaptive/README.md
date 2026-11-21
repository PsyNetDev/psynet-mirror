# Adaptive brightness comparison

Run `psynet debug local` and use the arrow keys to choose the brighter patch. Each correct answer makes the next comparison harder, and each error makes it easier. After eight responses the feedback shows the score and actual sequence of brightness differences.

[The experiment](experiment.py) starts one within-participant chain using PsyNet’s `GeometricStaircaseTrialMaker`. The node parameter is the brightness gap. `ContrastNode` sets `k = 1` and defines the next harder and easier gaps. PsyNet grows the chain from each trial’s score and tracks reversals. `ContrastTrial` draws the brighter side when it creates the trial definition, so reopening the trial reproduces the same pair.

The maker’s `present_trials` starts one solo `OnDemandTrialGame`. Only the first trial exists when the first pair appears. Each accepted answer completes its native trial and feeds the next assignment to the same page. The chain ends after eight nodes. This demonstration disables the final threshold check because an eight-answer run can contain no reversals. The [pitch-discrimination demo](../../experiments/staircase_pitch_discrimination) illustrates threshold scoring with the same maker.

[The page](static/contrast.js) renders each assignment with `game.onTrial` and starts the response clock in the frame that displays it. Each keypress waits for the maker's selection. Reload to see the same open assignment again. If a reply is lost, the client retries with the original response time.

Compare this with [the arrow demo](../live_trial_game), which prepares a known sequence up front, and [the ordinary adaptive trial demo](../trial_cue_adaptive), which uses timeline pages.
