# Adaptive brightness comparison

Run `psynet debug local` in this directory. Press the left or right arrow key to choose the brighter patch. A correct answer moves one step towards a smaller difference and an error moves one step towards a larger difference. The eight pairs start 24 grey-code values apart. The feedback shows the differences you actually saw.

## Follow one response

[experiment.py](experiment.py) registers a typed `TrialAnswer` in an ordinary solo `LiveGame`. The game starts with one pair. On each accepted answer it checks the occurrence, scores against that pair, updates the difficulty and draws the brighter side for the next pair. The final answer ends the game. The game view includes only the current pair and position.

[contrast.js](static/contrast.js) calls `startResponseClock(view)` in the frame that shows the two patches. A queued response hides the pair until the next server view. The network wait between pairs falls outside the recorded response time.

[trials.py](trials.py) contains the database-specific part of this example. Each runner step queues the exact next pair along with the preceding answer. Dallinger saves the runner state and queued effect in Redis before publishing the view. Its ordered SQL writer completes the preceding native trial and opens the chosen successor in the same transaction. Its record cursor and those writes commit together. The last step only completes the last row. The experiment's final feedback reads the native scores after the ending is saved.

## Choosing an approach

Use [the ordinary adaptive staircase](../trial_cue_adaptive) as the starting point for a self-paced study. It uses the existing timeline and trial lifecycle. This live version keeps the same browser page throughout and still requires a server round trip for each new pair. It adds a persistent connection, runner state and an asynchronous SQL writer. While the writer catches up, the live session can be ahead of the trial table.

To check normal reload behavior, answer once and reload. The second pair should have the same contrast and brighter side. After the round, the dashboard should show eight completed trials with slots 0–7, one definition, answer, score and browser response time per slot. Recovery before the SQL write depends on the live session's Redis state remaining available.
