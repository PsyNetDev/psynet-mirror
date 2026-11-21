# Arrow flanker

Run `psynet debug local` in this directory. Each screen shows five arrows; press the left or right arrow key to match the **middle** one. The round shows each of four patterns twice, in a shuffled order, all on one page. A short blank separates consecutive patterns, so you can tell when the same pattern repeats.

## What to look for

The trial maker creates all eight trials before the first pattern appears, and the page saves each answer on its own trial.

1. Open the trial table in the debug dashboard when the first pattern appears. All eight rows already exist, each with its node and position.
2. Answer three patterns and wait until those rows are marked complete.
3. Reload the participant page. The fourth pattern appears again.
4. Finish the round. The feedback score is the sum of the eight trials' scores. Each trial also stores the key pressed and the response time in seconds, from when the pattern last appeared to the key press.

## How it works

[experiment.py](experiment.py) defines the nodes, scores each trial and reads the trials back to build the feedback. [flanker.js](static/flanker.js) shows the next pattern straight away while PsyNet saves the previous answer.

The answer message subclasses `TrialAnswer`, narrowing `answer` to the two arrows. The page calls `game.startResponseClock(view)` when it shows a pattern and `response.answer(value)` when a key is pressed. It calls `game.predict(game.predictTrialAnswer)` to show the next pattern without waiting for the server.

## Using images instead

`preload_fields` sends the listed fields of each trial's definition to the browser in advance. For images, that would be a URL, and the browser still has to download and decode the picture. For a small fixed set, declare the images in the page's `media=MediaSpec(image=...)`, as the [bird direction demo](../live_trial_game_images) does: it downloads and decodes all six photographs before the first one appears. For a long or participant-specific set, see [VocabTest's page script](../../../psynet/resources/scripts/vocabtest.js). It downloads the next two images while the participant answers, and waits for `decode()` before showing an image and starting its response clock.
