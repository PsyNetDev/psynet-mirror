# Adaptive brightness comparison

Run `psynet debug local` and use the arrow keys to choose the brighter patch. Each correct answer makes the next comparison harder, and each error makes it easier. After eight responses the feedback shows the score and actual sequence of brightness differences.

[The experiment](experiment.py) gives a `StaticTrialMaker` fourteen stimulus nodes, two arrangements at each contrast. Its `select_node` reads the previous native trial's score and chooses a node at the new difficulty. Its `present_trials` starts one solo `OnDemandTrialGame`. Only the first trial exists when the first pair appears. Each accepted answer completes that trial and creates its successor in one SQL transaction. Each row has its assigned node, stimulus, response, score and time.

[The page](static/contrast.js) renders each assignment with `game.onTrial` and starts the response clock in the frame that displays it. Each keypress waits for the maker's selection. Reload to see the same open assignment again. If a reply is lost, the client retries with the original response time.

Compare this with [the arrow demo](../live_trial_game), which prepares a known sequence up front, and [the ordinary adaptive trial demo](../trial_cue_adaptive), which uses timeline pages.
