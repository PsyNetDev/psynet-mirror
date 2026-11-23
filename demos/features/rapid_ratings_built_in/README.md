# Rapid ratings with built-in pages

Run `psynet debug local` in this directory. Clicking Next on the intro shows the instructions at once, and their Back button returns to the intro. Then rate eight pictures by clicking a number from 1 to 5. Each picture appears as soon as you rate the one before, without waiting for the server. A break page comes halfway through, and the last page lists your ratings.

## How it works

[experiment.py](experiment.py) builds each trial from a built-in `ImagePrompt` and `PushButtonControl` and uses an ordinary `StaticTrialMaker` with `prepare_trials_in_advance=True`. The trial maker then creates all of a participant's trials when they reach it, and each trial page also carries the rendered pages of the next few trials, whose pictures the browser downloads straight away. When the participant answers, PsyNet swaps in the next trial's page and sends the answer to the server in the background. `RatingTrialMaker.show_after_trial` adds the break, so the browser waits for the server after the fourth picture. The instructions page comes straight after the intro in the timeline, so PsyNet renders it in advance in the same way and gives it a Back button.

The [rapid ratings](../rapid_ratings) demo shows the same task with a page module, which keeps one page for all the trials.
