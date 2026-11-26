# Rapid ratings

Run `psynet debug local` in this directory, then rate eight pictures by clicking a number or pressing a key from 1 to 5. Each picture appears as soon as you rate the one before, without waiting for the server. A break page comes halfway through, and the last page lists your ratings.

## How it works

[experiment.py](experiment.py) uses an ordinary `StaticTrialMaker` with `prepare_trials_in_advance=True`. The trial maker then keeps the participant's next two trials prepared, and each trial page also carries the `contents` of the next few trials. `RatingTrialMaker.show_after_trial` adds the break, so the browser waits for the server after the fourth picture.

In [rate-picture.js](static/rate-picture.js), `activate` listens for clicks and key presses and returns an `update` function. `update` preloads the pictures of the upcoming trials, shows the current picture once it's decoded, starts the response clock and answers through the `response` handle. PsyNet sends the answers to the server in the background, in order, and calls `update` with the next trial straight away. If the server rejects an answer, PsyNet shows the error and calls `update` again with that trial.

See [Keeping a task on one page](https://psynetdev.gitlab.io/PsyNet/alpha/code/trials/keeping_a_task_on_one_page.html) for the full guide.
